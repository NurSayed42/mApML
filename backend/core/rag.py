import os
import uuid
from typing import List, Optional
import structlog
import asyncio
from functools import lru_cache
from core.config import settings
from core.llm_client import chat_completion

logger = structlog.get_logger(__name__)


@lru_cache(maxsize=1)
def get_embedding_model():
    from sentence_transformers import SentenceTransformer
    logger.info("loading_embedding_model", model="all-MiniLM-L6-v2")
    return SentenceTransformer("all-MiniLM-L6-v2")


def embed_text(text: str) -> List[float]:
    model = get_embedding_model()
    return model.encode(text, convert_to_numpy=True).tolist()


def embed_texts(texts: List[str]) -> List[List[float]]:
    model = get_embedding_model()
    return model.encode(texts, convert_to_numpy=True, batch_size=32).tolist()


def get_chroma_client():
    import chromadb
    chroma_url = settings.chroma_url.rstrip("/")
    if "://" in chroma_url:
        chroma_url = chroma_url.split("://", 1)[1]
    if ":" in chroma_url:
        host, port_str = chroma_url.rsplit(":", 1)
        port = int(port_str)
    else:
        host = chroma_url
        port = 8000

    return chromadb.HttpClient(host=host, port=port)


def get_or_create_collection(collection_name: str):
    client = get_chroma_client()
    return client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"}
    )


async def process_document_upload(
    file_path: str,
    filename: str,
    file_type: str,
    user_id: str,
    document_id: str,
) -> int:
    loop = asyncio.get_event_loop()

    def _process():
        text = ""
        if file_type == "pdf":
            import fitz
            doc = fitz.open(file_path)
            for page in doc:
                text += page.get_text()
            doc.close()
        elif file_type in ("docx", "doc"):
            from docx import Document
            doc = Document(file_path)
            text = "\n".join(p.text for p in doc.paragraphs)
        else:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()

        if not text.strip():
            raise ValueError("Document contains no extractable text")

        from langchain.text_splitter import RecursiveCharacterTextSplitter
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.chunk_size_tokens * 4,
            chunk_overlap=settings.chunk_overlap_tokens * 4,
            length_function=len,
        )
        chunks = splitter.split_text(text)
        if not chunks:
            raise ValueError("No chunks created from document")

        embeddings = embed_texts(chunks)
        collection = get_or_create_collection("document_chunks")
        ids = [f"{document_id}_chunk_{i}" for i in range(len(chunks))]
        metadatas = [
            {
                "user_id": user_id,
                "document_id": document_id,
                "filename": filename,
                "chunk_index": i,
                "total_chunks": len(chunks),
                "upload_timestamp": __import__("time").time(),
            }
            for i in range(len(chunks))
        ]
        collection.upsert(ids=ids, embeddings=embeddings, documents=chunks, metadatas=metadatas)
        logger.info("document_processed", document_id=document_id, chunk_count=len(chunks))
        return len(chunks)

    return await loop.run_in_executor(None, _process)


async def answer_rag_question(
    question: str,
    user_id: str,
    document_id: Optional[str] = None,
    correlation_id: str = "",
) -> str:
    loop = asyncio.get_event_loop()

    def _retrieve():
        query_embedding = embed_text(question)
        collection = get_or_create_collection("document_chunks")
        where_filter: dict = {"user_id": user_id}
        if document_id:
            where_filter["document_id"] = document_id

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=5,
            where=where_filter,
            include=["documents", "distances", "metadatas"],
        )
        chunks = []
        if results["documents"] and results["documents"][0]:
            for i, (doc, meta) in enumerate(zip(results["documents"][0], results["metadatas"][0])):
                chunks.append(f"[{i+1}] From '{meta.get('filename', 'document')}': {doc}")
        return chunks

    chunks = await loop.run_in_executor(None, _retrieve)
    if not chunks:
        return "No relevant information found in the uploaded documents for this question."

    context = "\n\n".join(chunks)
    prompt = f"""Answer using ONLY the provided context. If not in context say so clearly.

Context:
{context}

Question: {question}

Answer:"""

    try:
        result = await chat_completion(
            prompt=prompt,
            max_tokens=1024,
            temperature=0.3,
        )
        logger.info("rag_answer_generated", provider=result["provider"], model=result["model"])
        return result["content"]
    except Exception as e:
        logger.error("rag_llm_error", error=str(e))
        return "Failed to generate answer. Please try again."