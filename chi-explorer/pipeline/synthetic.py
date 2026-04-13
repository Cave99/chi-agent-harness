"""
pipeline/synthetic.py — Synthetic batch output generator.

Produces fake but structurally valid JSONL that mirrors the real Bedrock
batch output format, so the parser can be fully tested with no live data.

Real JSONL envelope (from Bedrock batch):
  {"recordId": "ABCD1234", "modelInput": {...}, "modelOutput": {"inputTextTokenCount": 8, "results": [{"outputText": "<json>", "completionReason": "FINISH"}]}}
  {"recordId": "EFGH5678", "modelInput": {...}, "error": {"errorCode": 400, "errorMessage": "bad request"}}
"""
from __future__ import annotations

import json
import random
import string
from datetime import datetime, timedelta

# ── Freeform text pool ────────────────────────────────────────────────────────
_FREEFORM_SENTENCES = [
    "The customer called in regarding a billing discrepancy on their latest statement.",
    "Agent explained the payment options clearly and the customer seemed satisfied.",
    "Customer expressed frustration about the extended wait time before being connected.",
    "The agent offered a payment extension which the customer accepted.",
    "Customer inquired about upgrading their broadband plan to a higher speed tier.",
    "Agent successfully guided the customer through the self-service portal steps.",
    "Customer mentioned they had called twice previously without resolution.",
    "The agent identified an account credit and applied it during the call.",
    "Customer was considering cancelling but was retained after the agent offered a discount.",
    "Agent confirmed the direct debit details and updated the account accordingly.",
    "Customer asked about NBN availability in their area and was given a timeframe.",
    "The interaction concluded positively with the customer thanking the agent.",
    "Customer reported intermittent outages over the past week.",
    "Agent escalated the technical fault to the network team for investigation.",
    "Customer had difficulty understanding the bill breakdown despite explanation.",
]


def _random_freeform(sentences: int = 2) -> str:
    return " ".join(random.sample(_FREEFORM_SENTENCES, min(sentences, len(_FREEFORM_SENTENCES))))


def _random_record_id() -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=10))


# ── Value generators per field type ──────────────────────────────────────────

def _gen_numerical(field: dict):
    """~10% chance of N/A, otherwise random float within declared range."""
    if random.random() < 0.10:
        return "N/A"
    lo, hi = field.get("range", [0, 10])
    val = random.uniform(lo, hi)
    if hi - lo <= 10:
        return round(val, 1)
    return round(val, 2)


_CATEGORICAL_POOLS = {
    "coaching_area":    ["Digital deflection", "Call closure", "Needs identification", "Customer engagement", "Value added services"],
    "sentiment":        ["Positive", "Neutral", "Negative", "Frustrated", "Highly Satisfied"],
    "outcome":          ["Resolved", "Escalated", "Transferred", "Callback arranged", "Unresolved"],
    "call_type":        ["Billing enquiry", "Technical fault", "Account change", "Cancellation", "General enquiry"],
    "queue":            ["Retention", "Sales", "Collections", "Technical Support"],
    "region":           ["VIC", "NSW", "QLD", "WA", "SA"],
    "objection":        ["Price too high", "Competitor offer", "No longer needed", "Technical issues", "Contract terms"],
    "reason":           ["Billing question", "Price increase", "Moving house", "Switching provider", "Technical support"],
    "compliance":       ["Fully compliant", "Missing ID check", "Incorrect pricing stated", "No closing script", "Partial compliance"],
    "competitor":       ["Telstra", "Optus", "Vodafone", "TPG", "Aussie Broadband"],
    "product":          ["Broadband 50", "Broadband 100", "Mobile 20GB", "Mobile Unlimited", "Fetch TV"],
    "script":           ["Intro followed", "Price explained", "Contract mentioned", "Closing followed", "Digital mentioned"],
    "yes_no":           ["Yes", "No", "N/A"],
    "status":           ["Active", "Pending", "Cancelled", "Suspended"],
    "_default":         ["Option 1", "Option 2", "Option 3", "Option 4"],
}


def _get_categorical_pool(field_name: str) -> list:
    name_lower = field_name.lower()
    for key, pool in _CATEGORICAL_POOLS.items():
        if key in name_lower:
            return pool
    return _CATEGORICAL_POOLS["_default"]


def _gen_categorical(field: dict) -> str:
    return random.choice(_get_categorical_pool(field["name"]))


def _gen_boolean(_field: dict) -> bool:
    return random.random() < 0.60  # ~60% True


def _gen_freeform(_field: dict) -> str:
    return _random_freeform(sentences=random.randint(2, 3))


def _gen_date(_field: dict) -> str:
    # Random date within the last 30 days
    now = datetime.now()
    days_ago = random.randint(0, 30)
    dt = now - timedelta(days=days_ago)
    return dt.strftime("%Y-%m-%d")


_GENERATORS = {
    "numerical":     _gen_numerical,
    "categorical":   _gen_categorical,
    "boolean":       _gen_boolean,
    "freeform_text": _gen_freeform,
    "date":          _gen_date,
}


# ── Public API ────────────────────────────────────────────────────────────────

def generate_jsonl(field_manifest: dict, count: int = 100, call_ids: list | None = None) -> str:
    """
    Generate synthetic JSONL lines conforming to `field_manifest`.

    If `call_ids` is provided, each line uses the corresponding call ID as its
    recordId so the parser can join it back to metadata. Otherwise generates
    random IDs.

    Returns:
        Multi-line JSONL string. Each line is a complete JSON object matching
        the real Bedrock batch output envelope.
    """
    fields = field_manifest.get("fields", [])
    lines = []
    ids = list(call_ids) if call_ids else [_random_record_id() for _ in range(count)]

    for record_id in ids:

        # ~3% of records simulate a batch error (no modelOutput)
        if random.random() < 0.03:
            line = {
                "recordId":  record_id,
                "modelInput": {"inputText": "[transcript]"},
                "error":     {"errorCode": 400, "errorMessage": "model output malformed"},
            }
        else:
            output = {}
            for field in fields:
                ftype = field.get("type", "freeform_text")
                generator = _GENERATORS.get(ftype, _gen_freeform)
                output[field["name"]] = generator(field)

            line = {
                "recordId":    record_id,
                "modelInput":  {"inputText": "[transcript]"},
                "modelOutput": {
                    "inputTextTokenCount": random.randint(200, 2000),
                    "results": [
                        {
                            "tokenCount":       random.randint(50, 400),
                            "outputText":       json.dumps(output),
                            "completionReason": "FINISH",
                        }
                    ],
                },
            }

        lines.append(json.dumps(line))

    return "\n".join(lines)


def generate_call_metadata(record_ids: list) -> list:
    """
    Generate synthetic call metadata records for a list of record IDs.
    Mirrors the shape that the real DB stub (pipeline/db.py) returns.
    """
    teams   = ["Retention", "Sales", "Collections", "Technical Support"]
    regions = ["VIC", "NSW", "QLD", "WA", "SA"]

    first_names = ["James", "Sarah", "Michael", "Emma", "David", "Jessica",
                   "Daniel", "Olivia", "Chris", "Mia", "Ryan", "Chloe",
                   "Nathan", "Priya", "Ahmed", "Zoe", "Tom", "Lily"]
    last_names  = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia",
                   "Miller", "Davis", "Wilson", "Taylor", "Anderson", "Thomas",
                   "Nguyen", "Patel", "Lee", "Martin", "White", "Harris"]

    now = datetime.now()
    records = []

    for record_id in record_ids:
        first    = random.choice(first_names)
        last     = random.choice(last_names)
        team     = random.choice(teams)
        days_ago = random.randint(0, 30)
        call_dt  = now - timedelta(days=days_ago, seconds=random.randint(0, 86400))

        records.append({
            "call_id":           record_id,
            "agent_name":        f"{first} {last}",
            "team_name":         team,
            "call_datetime":     call_dt.strftime("%Y-%m-%d"),
            "call_duration":     random.randint(60, 1800),
            "call_queue":        team,
            "agent_leader_name": f"Leader {random.choice(last_names)}",
            "agent_team_id":     f"T{random.randint(1, 20):02d}",
            "region":            random.choice(regions),
        })

    return records
