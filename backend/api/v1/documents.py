import os
import uuid
import tempfile
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import Document, get_db
from models.schemas import DocumentOut, RAGQuery
from api.v1.auth import get_current_user
from models.database import User
from core.rag import process_document_upload, answer_rag_question
from core.config import settings

router = APIRouter(prefix="/documents", tags=["documents"])

ALLOWED_TYPES = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/msword": "doc",
    "text/plain": "txt",
}


@router.post("", status_code=201, response_model=DocumentOut)
async def upload_document(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Validate file type
    file_type = ALLOWED_TYPES.get(file.content_type)
    if not file_type:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: PDF, DOCX, TXT"
        )

    # Validate file size
    content = await file.read()
    max_bytes = settings.max_file_size_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size: {settings.max_file_size_mb}MB"
        )

    temp_path = None
    try:
        suffix = os.path.splitext(file.filename or "upload")[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(content)
            temp_path = tmp.name

        document_id = uuid.uuid4()
        doc = Document(
            id=document_id,
            user_id=user.id,
            filename=file.filename,
            file_type=file_type,
            chunk_count=0,
        )
        db.add(doc)
        await db.flush()

        # Process document (extract, chunk, embed, store)
        chunk_count = await process_document_upload(
            file_path=temp_path,
            filename=file.filename,
            file_type=file_type,
            user_id=str(user.id),
            document_id=str(document_id),
        )

        doc.chunk_count = chunk_count
        await db.commit()
        await db.refresh(doc)
        return doc

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


@router.get("", response_model=list[DocumentOut])
async def list_documents(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Document)
        .where(Document.user_id == user.id)
        .order_by(Document.upload_timestamp.desc())
    )
    return result.scalars().all()


@router.post("/query")
async def query_document(
    body: RAGQuery,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Answer a question using RAG over uploaded documents."""
    # Verify document ownership if document_id provided
    if body.document_id:
        result = await db.execute(
            select(Document)
            .where(Document.id == str(body.document_id))
            .where(Document.user_id == user.id)
        )
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Document not found")

    answer = await answer_rag_question(
        question=body.question,
        user_id=str(user.id),
        document_id=str(body.document_id) if body.document_id else None,
    )
    return {"question": body.question, "answer": answer}


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Document)
        .where(Document.id == document_id)
        .where(Document.user_id == user.id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Delete from ChromaDB
    try:
        from core.rag import get_or_create_collection
        collection = get_or_create_collection("document_chunks")
        # Get all chunk IDs for this document
        results = collection.get(
            where={"document_id": document_id},
            include=[],
        )
        if results["ids"]:
            collection.delete(ids=results["ids"])
    except Exception:
        pass

    await db.delete(doc)
    await db.commit()
