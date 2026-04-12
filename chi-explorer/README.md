# Chi Explorer — Home Build

Conversational call analysis tool. Ask a business question in plain English, get AI-powered charts and analysis drawn from call transcript data.

## Quick start

```bash
cd chi-explorer
cp .env.example .env
# Edit .env — add your OPENROUTER_API_KEY
pip install -r requirements.txt
python3 app.py
# Open http://localhost:5001
```

## What the stubs replace

| File | Stub behaviour | Replace with |
|---|---|---|
| `pipeline/db.py` | Returns random call count + synthetic metadata | Real SQL queries against `calls` table |
| `pipeline/batch.py` | Generates synthetic JSONL directly, no wait | Real Bedrock batch dispatch + polling |
| `pipeline/provider.py` | `_bedrock_*` raises `NotImplementedError` | Implement Bedrock Converse API calls |

**To switch to the real backend:** set these three values in `.env` (or `config.py`):
```
INFERENCE_PROVIDER=bedrock
DB_ENABLED=true
BATCH_ENABLED=true
```
No other code changes required.

## Architecture

```
User question
  → Business Agent          generates WHERE clause + system prompt + field manifest
  → Approval gate           shows call count, cost estimate, prompt preview
  → [User approves]
  → DB stub                 fetches (synthetic) call metadata
  → Batch stub              generates (synthetic) JSONL
  → Parser                  schema-driven aggregation → summary dict
  → Briefing Agent          summary dict → plain-text chart brief
  → Code Agent              brief → matplotlib script
  → AST linter + executor   validates + runs script → base64 PNG charts
  → Vision Agent            charts + question → executive summary + follow-ups
```

## Running the tests

```bash
python3 test_provider.py      # confirms OpenRouter connectivity
python3 test_parser.py        # generates 100 synthetic records + parses them
python3 test_executor.py      # validates AST linter (4 cases)
python3 test_business_agent.py # live Business Agent test (requires API key)
```

## Config reference

All settings live in `config.py` / `.env`:

| Variable | Default | Notes |
|---|---|---|
| `OPENROUTER_API_KEY` | — | Required for home build |
| `INFERENCE_PROVIDER` | `openrouter` | `openrouter` or `bedrock` |
| `DB_ENABLED` | `false` | `true` = real DB |
| `BATCH_ENABLED` | `false` | `true` = real Bedrock batch |
| `BUSINESS_AGENT_MODEL` | `moonshotai/kimi-k2` | OpenRouter model slug |
| `CODE_AGENT_MODEL` | same | Can be a cheaper model |
| `VISION_AGENT_MODEL` | same | Must support vision |
| `FLASK_PORT` | `5001` | port 5000 is taken by macOS ControlCenter |
| `COST_WARN_THRESHOLD_USD` | `3.00` | Warning threshold on approval gate |
| `CALL_COUNT_WARN_THRESHOLD` | `1000` | Warning threshold on approval gate |
