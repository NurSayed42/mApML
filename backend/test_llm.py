#!/usr/bin/env python
"""
Test script for freeflow-llm multi-provider setup.

Usage (from backend/):
    .\\venv\\Scripts\\python test_llm.py
    .\\venv\\Scripts\\python test_llm.py --provider groq
    .\\venv\\Scripts\\python test_llm.py --all
"""

import argparse
import asyncio
import sys

from dotenv import load_dotenv

load_dotenv()


async def test_provider_chain():
    """Test full Groq → Mistral → Gemini fallback chain."""
    from core.llm_client import chat_completion, list_configured_providers, reset_llm_client

    reset_llm_client()
    configured = list_configured_providers()
    print(f"Configured providers: {configured}")

    if not configured:
        print("ERROR: No API keys found. Set GROQ_API_KEY, MISTRAL_API_KEY, GEMINI_API_KEY in .env")
        return False

    result = await chat_completion(
        prompt="Reply with exactly: OK",
        system_prompt="You are a test assistant. Be very brief.",
        max_tokens=50,
        temperature=0.0,
    )

    print(f"  Provider used: {result['provider']}")
    print(f"  Model:         {result['model']}")
    print(f"  Response:      {result['content'][:200]}")
    print(f"  Tokens:        {result['total_tokens']}")
    return bool(result["content"].strip())


async def test_single_provider(provider_name: str) -> bool:
    """Test one provider in isolation."""
    from core.config import settings
    from core.llm_client import reset_llm_client
    from freeflow_llm import FreeFlowClient
    from freeflow_llm.providers import GeminiProvider, GroqProvider
    from core.llm_providers.mistral import MistralProvider

    key_map = {
        "groq": settings.groq_api_key,
        "mistral": settings.mistral_api_key,
        "gemini": settings.gemini_api_key,
    }
    provider_classes = {
        "groq": GroqProvider,
        "mistral": MistralProvider,
        "gemini": GeminiProvider,
    }

    api_key = key_map.get(provider_name, "")
    if not api_key:
        print(f"  SKIP {provider_name}: no API key in .env")
        return False

    reset_llm_client()
    cls = provider_classes[provider_name]
    provider = cls(api_key=api_key)

    print(f"\n--- Testing {provider_name} ---")
    with FreeFlowClient(providers=[provider], verbose=True) as client:
        response = client.chat(
            messages=[
                {"role": "system", "content": "Reply briefly."},
                {"role": "user", "content": f"Say hello from {provider_name} test."},
            ],
            max_tokens=80,
            temperature=0.0,
        )
        print(f"  OK — {response.content[:150]}")
        return True


async def main():
    parser = argparse.ArgumentParser(description="Test LLM providers")
    parser.add_argument(
        "--provider",
        choices=["groq", "mistral", "gemini"],
        help="Test a single provider only",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Test each provider individually, then the full chain",
    )
    args = parser.parse_args()

    print("=" * 50)
    print("Multi-Agent Platform — LLM Provider Test")
    print("=" * 50)

    if args.provider:
        ok = await test_single_provider(args.provider)
        sys.exit(0 if ok else 1)

    if args.all:
        results = {}
        for name in ("groq", "mistral", "gemini"):
            try:
                results[name] = await test_single_provider(name)
            except Exception as e:
                print(f"  FAIL {name}: {e}")
                results[name] = False

        print("\n--- Testing fallback chain ---")
        try:
            chain_ok = await test_provider_chain()
        except Exception as e:
            print(f"  FAIL chain: {e}")
            chain_ok = False

        print("\n" + "=" * 50)
        print("Summary:")
        for name, ok in results.items():
            print(f"  {name}: {'PASS' if ok else 'FAIL/SKIP'}")
        print(f"  chain: {'PASS' if chain_ok else 'FAIL'}")
        sys.exit(0 if chain_ok else 1)

    # Default: test fallback chain only
    try:
        ok = await test_provider_chain()
        print("\n" + ("PASS" if ok else "FAIL"))
        sys.exit(0 if ok else 1)
    except Exception as e:
        print(f"\nFAIL: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
