"""
test_provider.py — Smoke test for pipeline/provider.py.

Run this to confirm OpenRouter connectivity before building anything else:
  python test_provider.py

Expected output: A short reply from the model printed to stdout.
"""

import sys
import os

# Allow running from the chi-explorer/ directory
sys.path.insert(0, os.path.dirname(__file__))

from pipeline.provider import chat, stream
import config


def test_chat():
    print(f"Provider : {config.INFERENCE_PROVIDER}")
    print(f"Model    : {config.BUSINESS_AGENT_MODEL}")
    print()

    print("── chat() test ──────────────────────────────────")
    response = chat(
        messages=[{"role": "user", "content": "Say 'Chi Explorer online.' and nothing else."}],
        system="You are a terse assistant. Follow instructions exactly.",
    )
    print(f"Response : {response!r}")
    print()


def test_stream():
    print("── stream() test ────────────────────────────────")
    print("Streaming: ", end="", flush=True)
    chunks = []
    for chunk in stream(
        messages=[{"role": "user", "content": "Count to five, one number per word, nothing else."}],
        system="You are a terse assistant. Follow instructions exactly.",
    ):
        print(chunk, end="", flush=True)
        chunks.append(chunk)
    print()
    print(f"Chunks received: {len(chunks)}")
    print()


if __name__ == "__main__":
    if not config.OPENROUTER_API_KEY:
        print("ERROR: OPENROUTER_API_KEY is not set in .env")
        sys.exit(1)

    try:
        test_chat()
        test_stream()
        print("All provider tests passed.")
    except Exception as exc:
        print(f"\nFAILED: {exc}")
        sys.exit(1)
