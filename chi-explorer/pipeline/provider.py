"""
pipeline/provider.py — LLM provider abstraction.

All agents call chat() or stream() from this module.
No agent file imports requests or an SDK directly.

Routing:
  config.INFERENCE_PROVIDER == "openrouter"  →  OpenRouter (HTTP)
  config.INFERENCE_PROVIDER == "bedrock"     →  Amazon Bedrock (stub until AWS available)
"""

from __future__ import annotations

import json
import time
import logging
from typing import Iterator, Optional

import requests

import config

logger = logging.getLogger(__name__)


# ── Public interface ──────────────────────────────────────────────────────────

def chat(messages: list[dict], system: str, model: Optional[str] = None) -> str:
    """
    Send a chat request and return the full response text.

    Args:
        messages: List of {"role": "user"|"assistant", "content": str} dicts.
        system:   System prompt string.
        model:    Override model. Defaults to config.BUSINESS_AGENT_MODEL.

    Returns:
        Response text as a string.

    Raises:
        RuntimeError: If all retries are exhausted or a non-retryable error occurs.
    """
    if config.INFERENCE_PROVIDER == "openrouter":
        return _openrouter_chat(messages, system, model)
    elif config.INFERENCE_PROVIDER == "bedrock":
        return _bedrock_chat(messages, system, model)
    else:
        raise ValueError(f"Unknown INFERENCE_PROVIDER: {config.INFERENCE_PROVIDER!r}")


def stream(messages: list[dict], system: str, model: Optional[str] = None) -> Iterator[str]:
    """
    Send a chat request and yield response text chunks as they arrive (SSE).

    Args:
        messages: List of {"role": "user"|"assistant", "content": str} dicts.
        system:   System prompt string.
        model:    Override model. Defaults to config.BUSINESS_AGENT_MODEL.

    Yields:
        String chunks of the response as they stream in.

    Raises:
        RuntimeError: If the request fails after retries.
    """
    if config.INFERENCE_PROVIDER == "openrouter":
        yield from _openrouter_stream(messages, system, model)
    elif config.INFERENCE_PROVIDER == "bedrock":
        yield from _bedrock_stream(messages, system, model)
    else:
        raise ValueError(f"Unknown INFERENCE_PROVIDER: {config.INFERENCE_PROVIDER!r}")


# ── OpenRouter implementation ─────────────────────────────────────────────────

def _openrouter_headers() -> dict:
    if not config.OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Add it to your .env file."
        )
    return {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:5000",
        "X-Title": "Chi Explorer",
    }


def _build_openrouter_payload(
    messages: list[dict],
    system: str,
    model: Optional[str],
    stream: bool,
) -> dict:
    resolved_model = model or config.BUSINESS_AGENT_MODEL
    # Prepend system message in the messages list (OpenRouter style)
    full_messages = [{"role": "system", "content": system}] + messages
    return {
        "model": resolved_model,
        "messages": full_messages,
        "stream": stream,
    }


def _openrouter_chat(
    messages: list[dict],
    system: str,
    model: Optional[str],
) -> str:
    payload = _build_openrouter_payload(messages, system, model, stream=False)
    last_error: Optional[Exception] = None

    for attempt in range(config.PROVIDER_MAX_RETRIES):
        try:
            resp = requests.post(
                config.OPENROUTER_BASE_URL,
                headers=_openrouter_headers(),
                json=payload,
                timeout=120,
            )

            if resp.status_code == 429 or resp.status_code >= 500:
                wait = config.PROVIDER_RETRY_BASE_SEC * (2 ** attempt)
                logger.warning(
                    "OpenRouter returned %s on attempt %d/%d, retrying in %ds",
                    resp.status_code,
                    attempt + 1,
                    config.PROVIDER_MAX_RETRIES,
                    wait,
                )
                time.sleep(wait)
                last_error = RuntimeError(
                    f"OpenRouter HTTP {resp.status_code}: {resp.text[:200]}"
                )
                continue

            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            if content is None:
                # Some models return null content on refusal or empty finish
                raise RuntimeError(
                    f"Model returned null content. finish_reason="
                    f"{data['choices'][0].get('finish_reason')}"
                )
            return content

        except (requests.RequestException, RuntimeError) as exc:
            wait = config.PROVIDER_RETRY_BASE_SEC * (2 ** attempt)
            logger.warning(
                "OpenRouter request error on attempt %d/%d: %s, retrying in %ds",
                attempt + 1,
                config.PROVIDER_MAX_RETRIES,
                exc,
                wait,
            )
            time.sleep(wait)
            last_error = exc

    raise RuntimeError(
        f"OpenRouter chat failed after {config.PROVIDER_MAX_RETRIES} attempts. "
        f"Last error: {last_error}"
    )


def _openrouter_stream(
    messages: list[dict],
    system: str,
    model: Optional[str],
) -> Iterator[str]:
    payload = _build_openrouter_payload(messages, system, model, stream=True)

    for attempt in range(config.PROVIDER_MAX_RETRIES):
        try:
            with requests.post(
                config.OPENROUTER_BASE_URL,
                headers=_openrouter_headers(),
                json=payload,
                stream=True,
                timeout=120,
            ) as resp:
                if resp.status_code == 429 or resp.status_code >= 500:
                    wait = config.PROVIDER_RETRY_BASE_SEC * (2 ** attempt)
                    logger.warning(
                        "OpenRouter stream returned %s on attempt %d/%d, retrying in %ds",
                        resp.status_code,
                        attempt + 1,
                        config.PROVIDER_MAX_RETRIES,
                        wait,
                    )
                    time.sleep(wait)
                    continue

                resp.raise_for_status()

                for raw_line in resp.iter_lines():
                    if not raw_line:
                        continue
                    line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        return
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk["choices"][0].get("delta", {})
                        text = delta.get("content", "")
                        if text:
                            yield text
                    except (json.JSONDecodeError, KeyError):
                        continue
                return  # stream completed successfully

        except requests.RequestException as exc:
            wait = config.PROVIDER_RETRY_BASE_SEC * (2 ** attempt)
            logger.warning(
                "OpenRouter stream error on attempt %d/%d: %s, retrying in %ds",
                attempt + 1,
                config.PROVIDER_MAX_RETRIES,
                exc,
                wait,
            )
            time.sleep(wait)

    raise RuntimeError(
        f"OpenRouter stream failed after {config.PROVIDER_MAX_RETRIES} attempts."
    )


# ── Bedrock stub (replace when AWS access is available) ───────────────────────

def _bedrock_chat(
    messages: list[dict],
    system: str,
    model: Optional[str],
) -> str:
    raise NotImplementedError(
        "Bedrock provider is not yet implemented. "
        "Set INFERENCE_PROVIDER=openrouter in .env for the home build."
    )


def _bedrock_stream(
    messages: list[dict],
    system: str,
    model: Optional[str],
) -> Iterator[str]:
    raise NotImplementedError(
        "Bedrock provider is not yet implemented. "
        "Set INFERENCE_PROVIDER=openrouter in .env for the home build."
    )
    yield  # make this a generator
