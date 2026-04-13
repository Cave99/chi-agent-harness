"""
test_business_agent.py — Live test of agents/business_agent.py.

Sends three test questions to the Business Agent and prints the structured
output for each. Requires OPENROUTER_API_KEY in .env.

Run:
  python3 test_business_agent.py
"""
from __future__ import annotations

import json
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from agents.business_agent import analyse
import config


QUESTIONS = [
    {
        "label": "Team comparison (CHI scores)",
        "question": "Compare the overall call quality scores across all teams over the last 30 days. Which teams are performing best and worst?",
    },
    {
        "label": "Script compliance check",
        "question": "Are agents in the Retention team following the correct script when handling cancellation requests? Check for proper identification, empathy language, and whether they offer a retention deal before the customer hangs up.",
    },
    {
        "label": "Competitor mention analysis",
        "question": "How often are customers mentioning our competitors by name? Which competitors come up most, and in what context — are customers threatening to switch, comparing prices, or something else?",
    },
]


def main():
    print(f"Model: {config.BUSINESS_AGENT_MODEL}\n")

    for i, item in enumerate(QUESTIONS, 1):
        print(f"{'='*60}")
        print(f"Question {i}: {item['label']}")
        print(f"  \"{item['question']}\"")
        print()

        try:
            result = analyse(item["question"])

            print(f"  where_clause:    {result['where_clause']!r}")
            print(f"  field_manifest:  {len(result['field_manifest']['fields'])} fields")
            for f in result["field_manifest"]["fields"]:
                range_str = f"  range={f['range']}" if "range" in f else ""
                print(f"    - {f['name']} ({f['type']}){range_str}")
            print()
            print(f"  system_prompt preview (first 200 chars):")
            print(f"    {result['system_prompt'][:200].strip()}...")
            print()
        except Exception as exc:
            print(f"  ERROR: {exc}")
            sys.exit(1)

    print("="*60)
    print("All business agent tests passed.")


if __name__ == "__main__":
    if not config.OPENROUTER_API_KEY:
        print("ERROR: OPENROUTER_API_KEY is not set in .env")
        sys.exit(1)
    main()
