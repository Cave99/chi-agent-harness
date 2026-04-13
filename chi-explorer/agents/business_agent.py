"""
agents/business_agent.py — Business Agent.

Takes a natural language question and returns a structured analysis plan:
  - where_clause: SQL WHERE conditions (no SELECT/FROM)
  - system_prompt: full novel prompt to run on each transcript
  - field_manifest: output field definitions for the parser

Also handles the second-pass briefing (summary dict → plain-text brief for
Code Agent) and the vision pass (charts → executive summary).
"""
from __future__ import annotations

import json
import logging
import re

from pipeline import provider
import config

logger = logging.getLogger(__name__)

# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert call centre data analyst. Your job is to translate a business user's natural language question into a structured analysis plan that will be run against a large set of call transcripts.

## Your output
You must respond with a single JSON object containing exactly three keys:

```json
{
  "where_clause": "<SQL WHERE conditions only — no SELECT, FROM, or WHERE keyword>",
  "system_prompt": "<the full novel prompt to inject into each transcript>",
  "field_manifest": {
    "fields": [
      {
        "name": "<field_name>",
        "type": "<numerical|categorical|boolean|freeform_text>",
        "description": "<one sentence: what this field measures and what values it can take>",
        "range": [min, max]
      },
      ...
    ]
  }
}
```

Do not include any explanation, preamble, or markdown outside the JSON object. Output valid JSON only.

---

## Call metadata SQL schema

Table: `calls` (table name uncertain — use with caution)

| Column              | Type     | Notes                          |
|---------------------|----------|--------------------------------|
| call_id             | text     | Primary key                    |
| agent_name          | text     | Full name of the agent         |
| team_name           | text     | e.g. Retention, Sales, Collections, Technical Support |
| call_datetime       | datetime | Date and time of call          |
| call_duration       | integer  | Duration in seconds            |
| call_queue          | text     | Queue the call entered         |
| agent_leader_name   | text     | Team leader name               |
| agent_team_id       | text     | Team identifier                |

Only reference columns that exist in this schema. If filtering by team, use `team_name`. If filtering by date, use `call_datetime`.

Example WHERE clauses (SQLite syntax):
- `team_name = 'Retention'`
- `call_datetime >= date('now', '-30 days')`
- `call_datetime >= date('now', 'start of month')`
- `call_datetime >= date('now', 'start of month') AND call_datetime < date('now', 'start of month', '+1 month')`
- `team_name IN ('Sales', 'Retention') AND call_duration > 120`
- `call_datetime >= '2026-01-01'`

---

## Reference examples: well-structured prompt output design

The following two output structures are from existing prompt types. They are examples of good JSON output design. Use them as inspiration when deciding how to structure your novel prompt output, ensuring you put reasoning BEFORE the actual value.

### Example 1: CHI Scoring (numerical scores with reasoning and quotes)

```json
{
  "customer_engagement_reasoning": "...",
  "customer_engagement_score": "1-5",
  "needs_identification_reasoning": "...",
  "needs_identification_score": "1-5",
  "digital_deflection_reasoning": "...",
  "digital_deflection_score": "1-5 or N/A",
  "key_quotes": ["..."],
  "overall_performance": {
    "average_score": "...",
    "key_strengths": ["..."],
    "priority_improvement_areas": ["..."]
  }
}
```

### Example 2: Boilerplate structure (boolean flags)

```json
{
  "main_flag_reasoning": "<reasoning here>",
  "main_flag": <true/false>,
  "secondary_category_reasoning": "<reasoning here>",
  "secondary_category": <true/false>,
  "key_quotes": ["<up to 3 key quotes of supporting evidence>"]
}
```

---

## Prompting principles for your `system_prompt` generation

You are writing a `system_prompt` that will be executed by a small, cheap, low-temperature LLM. Its instructions must be EXTREMELY clear, explicit, and direct, following best practices for prompt engineering.

1. **Clear and direct instructions**: Provide a detailed explanation of what fields exist, what scenarios make them true/false, and exactly how to score them. Think of the downstream LLM as a new employee who lacks context.
2. **Reasoning first**: To improve the small model's analysis, ALWAYS force it to output its reasoning BEFORE the final answer (e.g., `main_flag_reasoning` before `main_flag`).
3. **Strict JSON constraint**: The very end of the `system_prompt` YOU generate MUST include the exact phrasing in all caps followed by the example JSON structure:

RESPOND IN ONLY VALID JSON AS FOLLOWS:
```json
{
  "field_reasoning": "...",
  "field_name": "..."
}
```

4. **Prefer structured output.** Use numerical scores, categorical labels, and booleans whenever possible. Freeform text fields are a last resort — they cannot be aggregated across hundreds of calls.
5. **Always include an overall summary score** where meaningful.
6. **Keep field names snake_case**, short, and self-explanatory. They will appear as axis labels on charts.

---

## Field type guidance

| Type         | Use when                                                  | Examples                            |
|--------------|-----------------------------------------------------------|-------------------------------------|
| numerical    | Scoring (1–5), counts, percentages, durations             | overall_score, competitor_mentions  |
| categorical  | Labels, outcomes, classifications with <10 distinct values | coaching_area, call_outcome, sentiment |
| boolean      | Yes/no checks                                             | script_compliant, upgrade_offered   |
| freeform_text | Only when no structured alternative exists              | verbatim_customer_objection         |

**description**: Write one concise sentence that explains (a) what the field measures and (b) the values it can take. Example: "Score from 1–5 measuring how well the agent identified the customer's needs before offering a solution."

---

## where_clause rules

- Output only the WHERE clause body — no SELECT, no FROM, no WHERE keyword
- Only reference columns from the schema above
- Use **SQLite** date/time functions — NOT PostgreSQL syntax
- If the question does not require a filter (i.e. all calls), output an empty string ""
- Do not invent columns that do not exist in the schema
"""


# ── Public API ────────────────────────────────────────────────────────────────

def analyse_stream(question: str, on_token=None) -> dict:
    """
    Like analyse(), but streams the first LLM attempt, calling on_token(chunk)
    for each text chunk as it arrives. Falls back to a regular blocking call
    on the retry turn so error-correction still works.

    Args:
        question: Natural language business question.
        on_token: Optional callable(str) invoked per streamed chunk.

    Returns:
        Dict with keys: where_clause, system_prompt, field_manifest.
    """
    messages = [{"role": "user", "content": question}]
    last_error = None

    for attempt in range(2):
        if attempt == 0:
            # Stream the first attempt so callers can show live progress
            raw_chunks: list[str] = []
            for chunk in provider.stream(messages, SYSTEM_PROMPT, model=config.BUSINESS_AGENT_MODEL):
                raw_chunks.append(chunk)
                if on_token:
                    on_token(chunk)
            raw = "".join(raw_chunks)
        else:
            # Retry with a regular (blocking) call
            raw = provider.chat(messages, SYSTEM_PROMPT, model=config.BUSINESS_AGENT_MODEL)

        try:
            result = _parse_json_response(raw)
            _validate_result(result)
            return result
        except (ValueError, KeyError) as exc:
            logger.warning(
                "Business Agent stream attempt %d: JSON parse/validation failed: %s",
                attempt + 1, exc,
            )
            last_error = exc
            messages = messages + [
                {"role": "assistant", "content": raw},
                {
                    "role": "user",
                    "content": (
                        f"Your response was not valid JSON or was missing required keys. "
                        f"Error: {exc}. "
                        f"Please respond with ONLY a valid JSON object containing exactly the keys: "
                        f"where_clause, system_prompt, field_manifest."
                    ),
                },
            ]

    raise ValueError(
        f"Business Agent failed to produce valid JSON after 2 attempts. "
        f"Last error: {last_error}"
    )


def analyse(question: str) -> dict:
    """
    Run the Business Agent on a user question.

    Args:
        question: Natural language business question.

    Returns:
        Dict with keys: where_clause (str), system_prompt (str), field_manifest (dict).

    Raises:
        ValueError: If the model output cannot be parsed as valid JSON after retries.
    """
    messages = [{"role": "user", "content": question}]

    last_error = None
    for attempt in range(2):
        raw = provider.chat(messages, SYSTEM_PROMPT, model=config.BUSINESS_AGENT_MODEL)
        try:
            result = _parse_json_response(raw)
            _validate_result(result)
            return result
        except (ValueError, KeyError) as exc:
            logger.warning(
                "Business Agent attempt %d: JSON parse/validation failed: %s",
                attempt + 1, exc,
            )
            last_error = exc
            # Feed the error back so the model can self-correct
            messages = messages + [
                {"role": "assistant", "content": raw},
                {
                    "role": "user",
                    "content": (
                        f"Your response was not valid JSON or was missing required keys. "
                        f"Error: {exc}. "
                        f"Please respond with ONLY a valid JSON object containing exactly the keys: "
                        f"where_clause, system_prompt, field_manifest."
                    ),
                },
            ]

    raise ValueError(
        f"Business Agent failed to produce valid JSON after 2 attempts. "
        f"Last error: {last_error}"
    )


def analyse_with_refinement(
    question: str,
    refinement: str,
    current_plan: dict | None = None,
) -> dict:
    """
    Re-run the Business Agent with the original question plus a refinement
    instruction, optionally providing the current plan as context.

    Args:
        question:       The original natural language question.
        refinement:     The user's refinement instruction.
        current_plan:   The existing plan dict (where_clause, system_prompt,
                        field_manifest) to use as context for targeted editing.

    Returns:
        Dict with keys: where_clause, system_prompt, field_manifest.
    """
    if current_plan:
        current_plan_json = json.dumps(current_plan, indent=2)
        context_block = (
            f"Here is the CURRENT analysis plan that already exists:\n\n"
            f"```json\n{current_plan_json}\n```\n\n"
            f"The user wants to refine it with this instruction: {refinement}\n\n"
            f"Respond with a complete, updated JSON object that incorporates the change "
            f"while keeping all unchanged parts intact."
        )
    else:
        context_block = (
            f"Please update your analysis plan based on this refinement: {refinement}\n\n"
            f"Respond with a fresh, complete JSON object incorporating the change."
        )

    messages = [
        {"role": "user", "content": question},
        {"role": "user", "content": context_block},
    ]

    last_error = None
    for attempt in range(2):
        raw = provider.chat(messages, SYSTEM_PROMPT, model=config.BUSINESS_AGENT_MODEL)
        try:
            result = _parse_json_response(raw)
            _validate_result(result)
            return result
        except (ValueError, KeyError) as exc:
            logger.warning(
                "Business Agent refinement attempt %d failed: %s", attempt + 1, exc
            )
            last_error = exc
            messages = messages + [
                {"role": "assistant", "content": raw},
                {
                    "role": "user",
                    "content": (
                        f"Your response was not valid JSON. Error: {exc}. "
                        f"Please respond with ONLY a valid JSON object containing exactly the keys: "
                        f"where_clause, system_prompt, field_manifest."
                    ),
                },
            ]

    raise ValueError(
        f"Business Agent refinement failed after 2 attempts. Last error: {last_error}"
    )


def route_question(question: str, context: dict) -> str:
    """
    Decide if a user question is a new analysis request or a follow-up on 
    existing data in the session.

    Args:
        question: The user's new question.
        context:  A dict containing:
                    - previous_question: (str)
                    - field_manifest: (dict)
                    - summary: (dict)
                    - has_data: (bool)

    Returns:
        One of: "new_analysis", "follow_up".
    """
    if not context.get("has_data"):
        return "new_analysis"

    prompt = f"""You are a query router. Your goal is to decide if a business question 
is a completely NEW analysis request (requiring different call transcripts) or 
a FOLLOW-UP question that can be answered using the data already retrieved in 
the current session.

## Existing Session Context
Original Question: {context.get("previous_question", "None")}
Extracted Fields: {", ".join(f["name"] for f in context.get("field_manifest", {}).get("fields", []))}
Summary Findings: {json.dumps(context.get("summary", {}))[:1000]}

## New User Question
{question}

## Routing Decision Logic:
- If the user wants to see DIFFERENT calls or filter by a DIFFERENT date range/team than the original question, route as "new_analysis".
- If the user wants to drill into specific agents, teams, or values ALREADY extracted, or asks for different charts/stats of the SAME data, route as "follow_up".

Respond with exactly one word: "new_analysis" or "follow_up"."""

    raw = provider.chat(
        messages=[{"role": "user", "content": prompt}],
        system="You are a query router. Output exactly one word.",
        model=config.BUSINESS_AGENT_MODEL,
    )

    decision = raw.strip().lower()
    if "follow_up" in decision:
        return "follow_up"
    return "new_analysis"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_json_response(raw: str) -> dict:
    """Extract JSON from model response, handling markdown code fences."""
    text = raw.strip()

    # Try direct parse first (model responded with bare JSON)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strip only the *outermost* code fence — non-greedy would stop at any
    # inner fence (e.g. the example JSON block inside system_prompt).
    fence_match = re.match(r"^```(?:json)?\s*([\s\S]+)\s*```\s*$", text)
    if fence_match:
        inner = fence_match.group(1).strip()
        try:
            return json.loads(inner)
        except json.JSONDecodeError:
            text = inner  # fall through to brace-extraction below

    # Last resort: find outermost {...} by position
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(f"Could not extract JSON from response: {exc}") from exc

    raise ValueError("Could not find JSON object in response")


def _validate_result(result: dict) -> None:
    """Raise ValueError if required keys are missing or malformed."""
    for key in ("where_clause", "system_prompt", "field_manifest"):
        if key not in result:
            raise ValueError(f"Missing required key: {key!r}")

    manifest = result["field_manifest"]
    if not isinstance(manifest, dict) or "fields" not in manifest:
        raise ValueError("field_manifest must be a dict with a 'fields' key")

    for field in manifest["fields"]:
        if "name" not in field or "type" not in field:
            raise ValueError(f"Field missing 'name' or 'type': {field}")
        if field["type"] not in ("numerical", "categorical", "boolean", "freeform_text", "date"):
            raise ValueError(f"Unknown field type: {field['type']!r}")
