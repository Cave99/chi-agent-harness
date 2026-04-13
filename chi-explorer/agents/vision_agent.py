"""
agents/vision_agent.py — Vision Agent.

Receives chart images (base64 PNG) + the user's original question and writes
an executive summary with key findings and follow-up questions.
"""
from __future__ import annotations

import logging

from pipeline import provider
import config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a senior contact centre analytics manager reviewing AI-generated analysis of call data.

You will receive one or more charts along with the user's original question and a description of what each chart shows. Your job is to write a clear, numbers-first analytical response.

## Your output structure (use these exact headings)

**Summary**
Write one executive summary paragraph (4–6 sentences) synthesising the key finding that directly answers the user's original question. Lead with the most important number or insight. No hedging, no "it appears that", no "the data suggests" — be direct.

**Key Findings**
- [Finding 1 — reference a specific number or name from the charts]
- [Finding 2 — reference a specific number or name from the charts]
- [Finding 3 — reference a specific number or name from the charts]
- [Finding 4 — optional]
- [Finding 5 — optional]

**Follow-up**
Ask the user 2–3 specific follow-up questions to guide next steps. Examples of good follow-up questions:
- "Retention is your worst-performing team at 2.3 average score — want to drill into which specific agents are pulling this down?"
- "Digital deflection attempt rates are low across all teams. Want to run a deeper analysis focused specifically on billing calls?"
- "Want me to generate an HTML report with these findings that you can share with team leaders?"

## Tone
- Direct and specific
- Numbers first
- Name specific teams and agents when the data shows clear outliers
- No corporate hedging language
"""


def build_messages(question: str, charts: list, chart_descriptions: list) -> list:
    """
    Build the message payload for the vision agent without calling the LLM.
    Charts are Recharts JSON specs (not images) so they are included as text.
    Shared by analyse() and the streaming path in app.py.
    """
    chart_blocks = "\n\n".join(
        f"Chart {i+1} — {chart_descriptions[i] if i < len(chart_descriptions) else ''}:\n```json\n{chart}\n```"
        for i, chart in enumerate(charts)
    )
    content = (
        f"User's original question: {question}\n\n"
        f"Below are the chart data specifications (Recharts JSON) produced by the analysis.\n"
        f"Treat these as the data source and write your analytical response.\n\n"
        f"{chart_blocks}"
    )
    return [{"role": "user", "content": content}]


def analyse(question: str, charts: list, chart_descriptions: list) -> str:
    """
    Produce an executive summary from chart data (blocking).

    Args:
        question:           The user's original question.
        charts:             List of base64-encoded PNG strings (or JSON chart specs).
        chart_descriptions: List of strings describing each chart.

    Returns:
        Markdown-formatted executive summary string.
    """
    messages = build_messages(question, charts, chart_descriptions)
    return provider.chat(
        messages=messages,
        system=SYSTEM_PROMPT,
        model=config.VISION_AGENT_MODEL,
    )
