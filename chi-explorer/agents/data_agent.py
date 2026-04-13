"""
agents/data_agent.py — Data Agent.

Receives a user question, the field manifest, and a sample of the data.
Generates a Python script that uses Pandas to perform data analysis over the
full dataset (available as a DataFrame 'df') and produce a text answer and
Recharts JSON configuration.
"""
from __future__ import annotations

import json
import logging
import re

from pipeline import provider
import config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a Python data scientist expert in Pandas and Recharts.
Your goal is to write a Python script that analyzes a dataset of call transcripts results.

## Your environment
The script runs in a restricted sandbox where:
1.  A Pandas DataFrame named `df` is already available in the global namespace.
2.  `pandas` (as `pd`) and `json` are imported.
3.  The `df` contains the extraction results joined with call metadata (call_id, agent_name, team_name, call_datetime).
4.  You MUST populate two variables in the local namespace:
    - `answer`: (string) A concise natural language answer to the user's question based on the analysis.
    - `charts`: (list of dicts) A list of Recharts configuration objects.

## Required chart structure (for the `charts` list)
```python
[
  {
    "title": "...",
    "type": "bar" | "line" | "pie",
    "data": [
      { "name": "...", "value": ... },
      ...
    ],
    "xAxisKey": "name",
    "dataKey": "value",
    "color": "#ac3500"
  }
]
```
Colors to use: `#ac3500`, `#ffb233`, `#5f5e5e`, `#6366f1`.

## Instructions for your script:
1.  Perform the analysis on `df`.
2.  Handle cases where fields might be 'N/A' or None (drop them or filter them out before calculating stats).
3.  Format the `answer` string with your findings.
4.  Construct the `charts` list with appropriate visualizations (1-4 charts).
5.  Use ONLY standard pandas methods. No `eval()`, `exec()`, or file operations.
6.  Produce output ONLY as a raw Python script. No markdown, no explanation.
"""

def generate_script(question: str, field_manifest: dict, sample_records: list[dict]) -> str:
    """
    Generate a Python script to analyze the data and answer the question.

    Args:
        question:       The user's business question (or follow-up).
        field_manifest: The schema of the extracted data.
        sample_records: A small sample of enriched records to show the LLM the structure.

    Returns:
        The Python script code as a string.
    """
    prompt = f"""User Question: {question}

Data Schema (Field Manifest):
{json.dumps(field_manifest, indent=2)}

Data Sample (first 3 records):
{json.dumps(sample_records[:3], indent=2)}

Write the Python script now. Populate `answer` and `charts`.
"""
    raw = provider.chat(
        messages=[{"role": "user", "content": prompt}],
        system=SYSTEM_PROMPT,
        model=config.CODE_AGENT_MODEL,
    )

    # Clean up the output in case the LLM included markdown fences
    text = raw.strip()
    fence_match = re.search(r"```(?:python)?\s*([\s\S]+?)\s*```", text)
    if fence_match:
        return fence_match.group(1).strip()
    return text
