"""
agents/briefing_agent.py — Briefing Agent.

Reads the summary dict and produces a plain-text brief for the Code Agent,
specifying which fields to chart, what chart types to use, and notable values.
"""
from __future__ import annotations

import json
import logging

from pipeline import provider
import config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a senior data analyst who bridges business context and technical chart generation.

You will receive:
1. The user's original business question
2. A structured summary dict containing aggregated call data

Your job is to write a plain-text technical brief for a Python data visualisation engineer who has NO knowledge of the business domain. They will read only your brief and the summary dict — nothing else.

## Output format
Write a plain-text brief (NOT JSON). Structure it as:

**USER QUESTION:**
[restate the original question in one sentence]

**DATA AVAILABLE:**
[list the key fields relevant to the question with their exact paths in the summary dict]

**CHARTS TO GENERATE:**
[numbered list of charts, each specifying:
 - Chart title
 - Chart type
 - Exact data path(s) in summary dict
 - Any notable values to highlight (e.g. "agent Dan W. has lowest score at 1.9 — flag this in red")]

**NOTES FOR THE ENGINEER:**
[any other context they need — axis labels, colour guidance, order of charts]

## Chart type rules
Apply these rules when choosing chart types:

- by_team data on a numerical field → grouped bar chart
- distribution data (binned) → histogram (bar chart with bin labels on x-axis)
- by_day data spanning >3 days → line chart
- categorical value_counts → horizontal bar chart, sorted descending by count
- boolean by_team → stacked bar chart showing % true vs false per team
- top/bottom agents → two side-by-side horizontal bar charts (agent names on y-axis so names are readable)
- If a field has both by_team and value_counts, prefer by_team for the main chart

## Quantity rules
- Request at least 2 and at most 6 charts total
- Prioritise charts that most directly answer the user's question
- Always include a chart for the most important numerical field's by_team breakdown if it exists

## Naming rule
Name each chart descriptively so the Vision Agent understands what it shows without seeing the data.
"""


def brief(question: str, summary: dict) -> str:
    """
    Produce a plain-text brief describing which charts to generate.

    Args:
        question: The user's original question.
        summary:  The parsed summary dict.

    Returns:
        Plain-text brief string.
    """
    user_message = f"""User's original question:
{question}

Summary dict (JSON):
{json.dumps(summary, indent=2)}

Write the technical brief for the Code Agent now."""

    return provider.chat(
        messages=[{"role": "user", "content": user_message}],
        system=SYSTEM_PROMPT,
        model=config.BUSINESS_AGENT_MODEL,
    )
