"""
agents/code_agent.py — Code Agent (JSON Recharts Refactor).

Receives a technical brief + summary dict and writes a JSON array containing
chart configurations designed to be rendered by Recharts on the frontend.
"""
from __future__ import annotations

import json
import logging

from pipeline import provider
import config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a JSON data visualization engineer. You have no knowledge of the business domain. You receive a technical brief describing what charts to generate, and a data variable called `summary`.

## Your output
Output ONLY a raw JSON array of chart configuration objects. No explanation, no markdown, no code fences. Just valid JSON.

## Required chart structure
The React frontend (using Recharts) expects an array of chart objects exactly in this format:

```json
[
  {
    "title": "String - The title of the chart",
    "type": "bar" | "line" | "pie",
    "data": [
      { "name": "Category A", "value": 45 },
      { "name": "Category B", "value": 30 }
    ],
    "xAxisKey": "name",
    "dataKey": "value",
    "color": "#ac3500"
  }
]
```

## Rules for Mapping from `summary`:
- You MUST construct the `"data"` array by reading values from the provided `summary` dict.
- For `by_team` numeric aggregates, create `{"name": team_name, "value": mean_score}`.
- For `categorical` value counts, create `{"name": category, "value": count}`.
- For `boolean` true/false counts, create `{"name": "True / Yes", "value": ...}`.
- Sort horizontal Bar Charts for Top/Bottom Agents by value (Highest first for Top, Lowest first for Bottom).
- Produce at least 2 and at most 6 charts based on the brief.

## Colour palette
Use these colors for the `"color"` field based on visual variety:
- `#ac3500` (burnt orange)
- `#ffb233` (amber)
- `#5f5e5e` (grey)
- `#6366f1` (indigo)

Make absolutely sure the output is VALID JSON.
"""

def generate_script(brief_text: str, summary: dict) -> str:
    """
    Generate JSON array of chart configs from the brief and summary dict.

    Args:
        brief_text: Plain-text brief from the Briefing Agent.
        summary:    The parsed summary dict.

    Returns:
        String of JSON array.
    """
    user_message = f"""Technical brief:
{brief_text}

Summary dict structure:
{json.dumps(summary, indent=2)[:4000]}

Write the JSON array now. Output ONLY valid JSON — no markdown, no explanation."""

    raw = provider.chat(
        messages=[{"role": "user", "content": user_message}],
        system=SYSTEM_PROMPT,
        model=config.CODE_AGENT_MODEL,
    )

    import re
    fence = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", raw)
    if fence:
        return fence.group(1).strip()
    return raw.strip()
