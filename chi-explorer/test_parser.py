"""
test_parser.py — Integration test for synthetic.py + parser.py.

Generates 100 synthetic records from a hardcoded field manifest,
runs the parser, and prints the full summary dict.

No LLM or Flask dependency — fully standalone.

Run:
  python test_parser.py
"""

import json
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from pipeline.synthetic import generate_jsonl, generate_call_metadata
from pipeline.parser import parse

MANIFEST = {
    "fields": [
        {"name": "overall_chi_score",           "type": "numerical",    "range": [1, 5]},
        {"name": "customer_engagement_score",   "type": "numerical",    "range": [1, 5]},
        {"name": "digital_deflection_score",    "type": "numerical",    "range": [1, 5]},
        {"name": "primary_coaching_area",       "type": "categorical"},
        {"name": "customer_sentiment",          "type": "categorical"},
        {"name": "digital_deflection_attempted","type": "boolean"},
        {"name": "script_compliant",            "type": "boolean"},
        {"name": "call_summary",                "type": "freeform_text"},
    ]
}

COUNT = 100


def main():
    print(f"Generating {COUNT} synthetic records...")
    jsonl = generate_jsonl(MANIFEST, count=COUNT)

    lines = [l for l in jsonl.splitlines() if l.strip()]
    print(f"Generated {len(lines)} JSONL lines")

    # Extract record IDs so we can generate matching metadata
    import json as _json
    record_ids = []
    for line in lines:
        try:
            obj = _json.loads(line)
            rid = obj.get("recordId")
            if rid and "error" not in obj:
                record_ids.append(rid)
        except Exception:
            pass

    print(f"Valid records (no error): {len(record_ids)}")

    metadata = generate_call_metadata(record_ids)
    metadata_by_id = {m["call_id"]: m for m in metadata}

    print("Running parser...")
    summary = parse(jsonl, MANIFEST, metadata_by_id)

    print("\n" + "="*60)
    print(json.dumps(summary, indent=2))
    print("="*60)

    # Basic assertions
    meta = summary["meta"]
    assert meta["total_calls"] > 0,       "total_calls must be > 0"
    assert meta["agent_count"] > 0,       "agent_count must be > 0"
    assert len(meta["teams"]) > 0,        "teams must be populated"
    assert "overall_chi_score" in summary["numerical_fields"],      "numerical field missing"
    assert "primary_coaching_area" in summary["categorical_fields"],"categorical field missing"
    assert "digital_deflection_attempted" in summary["boolean_fields"], "boolean field missing"
    assert "call_summary" in summary["freeform_text_fields"],        "freeform field missing"

    num = summary["numerical_fields"]["overall_chi_score"]
    assert num["mean"] is not None,       "mean must be computed"
    assert len(num["top_agents"]) > 0,    "top_agents must be populated"
    assert "distribution" in num,         "distribution must be present"

    cat = summary["categorical_fields"]["primary_coaching_area"]
    assert len(cat["value_counts"]) > 0,  "value_counts must be populated"

    print("\nAll assertions passed.")


if __name__ == "__main__":
    main()
