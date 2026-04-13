"""
agents/business_agent.py — Business Agent.

Takes a natural language question and returns a structured analysis plan.
"""
from __future__ import annotations

import json
import logging
import re
import asyncio
from typing import Any, Dict, Optional, Callable

from pipeline import provider
from agents.base import BaseAgent
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

class BusinessAgent(BaseAgent):
    def run(self, question: str, refinement: Optional[str] = None, current_plan: Optional[Dict] = None) -> Dict[str, Any]:
        """Synchronous entry point for analysis or refinement."""
        if refinement:
            return self.analyse_with_refinement(question, refinement, current_plan)
        return self.analyse(question)

    async def run_async(self, question: str, refinement: Optional[str] = None, current_plan: Optional[Dict] = None) -> Dict[str, Any]:
        """Asynchronous entry point."""
        return await asyncio.to_thread(self.run, question, refinement, current_plan)

    def analyse(self, question: str) -> Dict[str, Any]:
        """Run the Business Agent on a user question with retries."""
        messages = [{"role": "user", "content": question}]
        last_error = None
        for attempt in range(2):
            raw = provider.chat(messages, SYSTEM_PROMPT, model=config.BUSINESS_AGENT_MODEL)
            try:
                result = self._parse_json_response(raw)
                self._validate_result(result)
                return result
            except (ValueError, KeyError) as exc:
                logger.warning("Business Agent attempt %d failed: %s", attempt + 1, exc)
                last_error = exc
                messages = messages + [
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": f"Your response was not valid JSON or was missing required keys. Error: {exc}. Please respond with ONLY a valid JSON object containing exactly the keys: where_clause, system_prompt, field_manifest."}
                ]
        raise ValueError(f"Business Agent failed after 2 attempts. Last error: {last_error}")

    def analyse_stream(self, question: str, on_token: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
        """Stream the first attempt, fall back to blocking for retries."""
        messages = [{"role": "user", "content": question}]
        last_error = None

        for attempt in range(2):
            if attempt == 0:
                raw_chunks: list[str] = []
                for chunk in provider.stream(messages, SYSTEM_PROMPT, model=config.BUSINESS_AGENT_MODEL):
                    raw_chunks.append(chunk)
                    if on_token:
                        on_token(chunk)
                raw = "".join(raw_chunks)
            else:
                raw = provider.chat(messages, SYSTEM_PROMPT, model=config.BUSINESS_AGENT_MODEL)

            try:
                result = self._parse_json_response(raw)
                self._validate_result(result)
                return result
            except (ValueError, KeyError) as exc:
                logger.warning("Business Agent stream attempt %d failed: %s", attempt + 1, exc)
                last_error = exc
                messages = messages + [
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": f"Your response was not valid JSON or missing keys. Error: {exc}."}
                ]
        raise ValueError(f"Business Agent stream failed after 2 attempts. Last error: {last_error}")

    def analyse_with_refinement(self, question: str, refinement: str, current_plan: Optional[Dict] = None) -> Dict[str, Any]:
        """Re-run with refinement instruction."""
        if current_plan:
            current_plan_json = json.dumps(current_plan, indent=2)
            context_block = (
                f"Here is the CURRENT analysis plan that already exists:\n\n"
                f"```json\n{current_plan_json}\n```\n\n"
                f"The user wants to refine it with this instruction: {refinement}\n\n"
                f"Respond with a complete, updated JSON object that incorporates the change while keeping all unchanged parts intact."
            )
        else:
            context_block = f"Please update your analysis plan based on this refinement: {refinement}\n\nRespond with a fresh, complete JSON object."

        messages = [
            {"role": "user", "content": question},
            {"role": "user", "content": context_block},
        ]

        last_error = None
        for attempt in range(2):
            raw = provider.chat(messages, SYSTEM_PROMPT, model=config.BUSINESS_AGENT_MODEL)
            try:
                result = self._parse_json_response(raw)
                self._validate_result(result)
                return result
            except (ValueError, KeyError) as exc:
                logger.warning("Business Agent refinement attempt %d failed: %s", attempt + 1, exc)
                last_error = exc
                messages = messages + [
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": f"Your response was not valid JSON. Error: {exc}."}
                ]
        raise ValueError(f"Business Agent refinement failed after 2 attempts. Last error: {last_error}")

    def route_question(self, question: str, context: Dict[str, Any]) -> str:
        """Decide if follow-up or new analysis."""
        if not context.get("has_data"):
            return "new_analysis"

        prompt = f"""You are a query router. Decided if follow-up or new analysis.
Original Question: {context.get("previous_question", "None")}
Extracted Fields: {", ".join(f["name"] for f in context.get("field_manifest", {}).get("fields", []))}
New Question: {question}
Respond with exactly 'new_analysis' or 'follow_up'."""

        raw = provider.chat(
            messages=[{"role": "user", "content": prompt}],
            system="You are a query router. Output exactly one word.",
            model=config.BUSINESS_AGENT_MODEL,
        )
        decision = raw.strip().lower()
        return "follow_up" if "follow_up" in decision else "new_analysis"

    def _parse_json_response(self, raw: str) -> Dict[str, Any]:
        """Extract JSON from response."""
        text = raw.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        fence_match = re.match(r"^```(?:json)?\s*([\s\S]+)\s*```\s*$", text)
        if fence_match:
            inner = fence_match.group(1).strip()
            try:
                return json.loads(inner)
            except json.JSONDecodeError:
                text = inner

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError as exc:
                raise ValueError(f"Could not extract JSON: {exc}") from exc
        raise ValueError("Could not find JSON object")

    def _validate_result(self, result: Dict[str, Any]) -> None:
        """Validate result keys and structure."""
        for key in ("where_clause", "system_prompt", "field_manifest"):
            if key not in result:
                raise ValueError(f"Missing required key: {key!r}")
        manifest = result["field_manifest"]
        if not isinstance(manifest, dict) or "fields" not in manifest:
            raise ValueError("field_manifest must be a dict with a 'fields' key")

_agent = BusinessAgent()

# Module-level aliases so callers can use `business_agent.analyse_stream(...)` etc.
# (orchestrator and app.py import the module, not the instance)
analyse_stream = _agent.analyse_stream
analyse_with_refinement = _agent.analyse_with_refinement
route_question = _agent.route_question
