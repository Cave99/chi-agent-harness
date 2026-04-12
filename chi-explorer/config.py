"""
config.py — Single source of truth for all environment decisions.
No other file checks environment variables directly.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Inference backend ─────────────────────────────────────────────────────────
# "openrouter" for local dev; swap to "bedrock" when AWS access is available
INFERENCE_PROVIDER = os.getenv("INFERENCE_PROVIDER", "openrouter")

# ── Stub toggles ──────────────────────────────────────────────────────────────
# False = stub (synthetic data); True = real backend
DB_ENABLED    = os.getenv("DB_ENABLED", "false").lower() == "true"
BATCH_ENABLED = os.getenv("BATCH_ENABLED", "false").lower() == "true"

SQLITE_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "chi_data.db")

# ── OpenRouter ────────────────────────────────────────────────────────────────
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

# Verify this slug matches the exact OpenRouter model ID for Kimi K2.5
_DEFAULT_MODEL = "moonshotai/kimi-k2"

BUSINESS_AGENT_MODEL = os.getenv("BUSINESS_AGENT_MODEL", _DEFAULT_MODEL)
CODE_AGENT_MODEL     = os.getenv("CODE_AGENT_MODEL",     _DEFAULT_MODEL)
VISION_AGENT_MODEL   = os.getenv("VISION_AGENT_MODEL",   _DEFAULT_MODEL)

# ── Cost / scale guardrails ───────────────────────────────────────────────────
COST_WARN_THRESHOLD_USD    = float(os.getenv("COST_WARN_THRESHOLD_USD", "3.00"))
CALL_COUNT_WARN_THRESHOLD  = int(os.getenv("CALL_COUNT_WARN_THRESHOLD", "1000"))
POLL_INTERVAL_SECONDS      = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))

# ── Flask ─────────────────────────────────────────────────────────────────────
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")
FLASK_PORT       = int(os.getenv("FLASK_PORT", "5001"))
FLASK_DEBUG      = os.getenv("FLASK_ENV", "development") == "development"

# ── Provider retry settings ───────────────────────────────────────────────────
PROVIDER_MAX_RETRIES    = 3
PROVIDER_RETRY_BASE_SEC = 2   # exponential backoff: 2, 4, 8 seconds
