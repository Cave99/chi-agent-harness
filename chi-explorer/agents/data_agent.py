"""
agents/data_agent.py — Data Agent.

Generates a Python script that uses Pandas to perform data analysis.
"""
from __future__ import annotations

import json
import logging
import re
import asyncio
from typing import Any, Dict, Optional, List

from pipeline import provider
from agents.base import BaseAgent
import config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a Python data scientist expert in Pandas and Recharts.
Your goal is to write a Python script that analyzes a dataset of call transcripts results.

## Your environment
The script runs in a restricted sandbox where:
1.  A Pandas DataFrame named `df` is already available in the global namespace.
2.  `pandas` (as `pd`) and `json` are imported.
3.  The `df` contains the extraction results joined with call metadata.
    AVAILABLE METADATA COLUMNS (always present):
    - `call_id`: (string) unique identifier for the call
    - `agent_name`: (string) name of the agent
    - `team_name`: (string) name of the agent's team
    - `call_datetime`: (string/datetime) when the call occurred
    - `call_duration`: (int) duration in seconds
    - `call_queue`: (string) the queue the call entered
    - `agent_leader_name`: (string) name of the agent's supervisor
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
2.  CRITICAL: Use `team_name` for team-related analysis, NOT `team`. Use `agent_name` for agent-related analysis.
3.  Handle cases where fields might be 'N/A' or None (drop them or filter them out before calculating stats).
4.  Format the `answer` string with your findings.
5.  Construct the `charts` list with appropriate visualizations (1-4 charts).
6.  Use ONLY standard pandas methods. No `eval()`, `exec()`, multiprocessing, or file operations.
7.  Stay within the allowed imports: `pandas`, `json`, `math`, `collections`, `statistics`, `datetime`. Do NOT attempt to import anything else.
8.  Produce output ONLY as a raw Python script. No markdown, no explanation.
"""

class DataAgent(BaseAgent):
    def run(self, question: str, field_manifest: Dict, sample_records: List[Dict]) -> str:
        """Synchronous entry point to generate the script."""
        return self.generate_script(question, field_manifest, sample_records)

    async def run_async(self, question: str, field_manifest: Dict, sample_records: List[Dict]) -> str:
        """Asynchronous entry point."""
        return await asyncio.to_thread(self.run, question, field_manifest, sample_records)

    def generate_script(self, question: str, field_manifest: Dict, sample_records: List[Dict]) -> str:
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

        text = raw.strip()
        fence_match = re.search(r"```(?:python)?\s*([\s\S]+?)\s*```", text)
        if fence_match:
            return fence_match.group(1).strip()
        return text

data_agent = DataAgent()
