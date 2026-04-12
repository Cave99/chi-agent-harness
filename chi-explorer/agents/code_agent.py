"""
agents/code_agent.py — Code Agent.

Receives a technical brief + summary dict and writes a self-contained
matplotlib Python script that produces base64-encoded PNG charts.
"""
from __future__ import annotations

import json
import logging

from pipeline import provider
import config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a Python data visualisation engineer. You have no knowledge of the business domain. You receive a technical brief describing what charts to generate, and a data variable called `summary` that is already available in your execution environment.

## Your output
Output ONLY a single self-contained Python script. No explanation, no markdown, no code fences. Just raw Python code.

## Execution environment
- The variable `summary` is already injected — do NOT try to load data from files or define `summary` yourself
- The variable `charts` is already defined as an empty list — append base64 PNG strings to it
- Allowed imports: matplotlib, matplotlib.pyplot, json, collections, math, base64, io, numpy
- No file I/O, no network calls, no user input

## Required chart structure
For each chart:
1. Use `plt.style.use('ggplot')` or `plt.style.use('seaborn-v0_8-whitegrid')` at the top (once)
2. Create the figure: `fig, ax = plt.subplots(figsize=(10, 5))`
3. Set a clear title: `ax.set_title("...", fontsize=14, fontweight='bold')`
4. Set axis labels with `ax.set_xlabel(...)` and `ax.set_ylabel(...)`
5. Use `fig.tight_layout()`
6. Encode and append:
```python
import io, base64
buf = io.BytesIO()
fig.savefig(buf, format='png', dpi=120, bbox_inches='tight')
buf.seek(0)
charts.append(base64.b64encode(buf.read()).decode('utf-8'))
plt.close(fig)
```

## Chart quantity
- Produce at least 2 and at most 6 charts
- Follow the brief exactly — do not invent charts not requested

## Colour palette
Use these colours for a warm, professional look:
- Primary bars/lines: `#ac3500` (burnt orange)
- Secondary: `#ffb233` (amber)
- Tertiary: `#5f5e5e` (grey)
- For multi-team charts, use: `['#ac3500', '#ffb233', '#5f5e5e', '#390c00']`

## Horizontal bar charts for agent names
When the brief asks for top/bottom agent charts, always use horizontal bar charts with agent names on the y-axis so names are fully readable. Sort bars from highest to lowest (top agents) or lowest to highest (bottom agents).

## Style rules
- Font sizes: title=14, axis labels=11, tick labels=9
- Do not use seaborn — only matplotlib
- Use `ax.spines` to remove top and right spines for a clean look
- Sequential code only — no functions, no classes

## Data access pattern
Access nested summary data like this:
```python
# Numerical by_team
teams = list(summary["numerical_fields"]["field_name"]["by_team"].keys())
means = [summary["numerical_fields"]["field_name"]["by_team"][t]["mean"] for t in teams]

# Categorical value_counts
labels = list(summary["categorical_fields"]["field_name"]["value_counts"].keys())
counts = list(summary["categorical_fields"]["field_name"]["value_counts"].values())

# Boolean by_team
for team, vals in summary["boolean_fields"]["field_name"]["by_team"].items():
    true_pct = vals["true"] / (vals["true"] + vals["false"]) * 100
```

Always guard against missing keys using `.get()` with a fallback value.
"""


def generate_script(brief_text: str, summary: dict) -> str:
    """
    Generate a matplotlib Python script from the brief and summary dict.

    Args:
        brief_text: Plain-text brief from the Briefing Agent.
        summary:    The parsed summary dict (passed for context, not exec'd here).

    Returns:
        Python source code as a string.
    """
    user_message = f"""Technical brief:
{brief_text}

Summary dict structure (for reference — `summary` is already injected at runtime):
{json.dumps(summary, indent=2)[:4000]}

Write the Python script now. Output ONLY raw Python code — no markdown, no explanation."""

    raw = provider.chat(
        messages=[{"role": "user", "content": user_message}],
        system=SYSTEM_PROMPT,
        model=config.CODE_AGENT_MODEL,
    )

    # Strip markdown code fences if the model wraps output anyway
    import re
    fence = re.search(r"```(?:python)?\s*([\s\S]+?)\s*```", raw)
    if fence:
        return fence.group(1).strip()
    return raw.strip()
