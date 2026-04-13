"""
pipeline/parser.py — Schema-driven JSONL parser.

Consumes the Bedrock batch output JSONL and a field manifest, and produces
a structured summary dict. No LLM calls. No external dependencies beyond
json-repair.

The summary dict shape is defined in chi_explorer_handoff.md section 2 and
must not deviate from that spec.
"""
from __future__ import annotations

import json
import logging
import random
import statistics
from collections import defaultdict

from json_repair import repair_json

logger = logging.getLogger(__name__)


# ── Public API ────────────────────────────────────────────────────────────────

def parse(jsonl_text: str, field_manifest: dict, metadata_by_id: dict) -> tuple[dict, list[dict]]:
    """
    Parse JSONL batch output into a structured summary dict and the full
    list of enriched records.

    Args:
        jsonl_text:      Raw JSONL string (one JSON object per line).
        field_manifest:  {"fields": [{"name": str, "type": str, "range": [...]}]}
        metadata_by_id:  {record_id: {call_id, agent_name, team_name, ...}}

    Returns:
        A tuple of (summary_dict, enriched_records_list).
    """
    fields = {f["name"]: f for f in field_manifest.get("fields", [])}
    records = _parse_lines(jsonl_text)

    enriched = []
    for rec in records:
        record_id = rec.get("_record_id")
        meta = metadata_by_id.get(record_id, {})
        combined = {**rec, **meta}
        enriched.append(combined)

    summary = _aggregate(enriched, fields)
    return summary, enriched


# ── Line parsing ──────────────────────────────────────────────────────────────

def _parse_lines(jsonl_text: str) -> list:
    """
    Parse each JSONL line. Returns list of dicts containing the model output
    fields plus a '_record_id' key for metadata joining.
    Skips error lines and lines where modelOutput is absent.
    Uses jsonrepair for malformed output text.
    """
    records = []
    for i, raw_line in enumerate(jsonl_text.splitlines()):
        raw_line = raw_line.strip()
        if not raw_line:
            continue

        try:
            envelope = json.loads(raw_line)
        except json.JSONDecodeError:
            try:
                envelope = json.loads(repair_json(raw_line))
            except Exception:
                logger.warning("Line %d: could not parse envelope, skipping", i + 1)
                continue

        record_id = envelope.get("recordId", f"unknown_{i}")

        if "error" in envelope:
            logger.debug("Line %d (recordId=%s): batch error, skipping", i + 1, record_id)
            continue

        model_output = envelope.get("modelOutput", {})
        results = model_output.get("results", [])
        if not results:
            logger.warning("Line %d (recordId=%s): no results, skipping", i + 1, record_id)
            continue

        output_text = results[0].get("outputText", "")
        try:
            output = json.loads(output_text)
        except json.JSONDecodeError:
            try:
                output = json.loads(repair_json(output_text))
            except Exception:
                logger.warning(
                    "Line %d (recordId=%s): could not parse outputText, skipping",
                    i + 1, record_id,
                )
                continue

        if not isinstance(output, dict):
            logger.warning("Line %d (recordId=%s): outputText is not a dict, skipping", i + 1, record_id)
            continue

        output["_record_id"] = record_id
        records.append(output)

    logger.info("Parsed %d valid records from JSONL", len(records))
    return records


# ── Aggregation ───────────────────────────────────────────────────────────────

def _aggregate(records: list, fields: dict) -> dict:
    """Build the summary dict from enriched records."""
    if not records:
        return _empty_summary()

    all_teams  = [r.get("team_name", "Unknown") for r in records]
    all_dates  = [r.get("call_datetime") for r in records if r.get("call_datetime")]
    unique_agents = {r.get("agent_name") for r in records if r.get("agent_name")}

    meta = {
        "total_calls": len(records),
        "date_range": {
            "min": min(all_dates) if all_dates else None,
            "max": max(all_dates) if all_dates else None,
        },
        "teams":       sorted(set(all_teams)),
        "agent_count": len(unique_agents),
    }

    numerical_fields     = {}
    categorical_fields   = {}
    boolean_fields       = {}
    date_fields          = {}
    freeform_text_fields = {}

    for fname, fdef in fields.items():
        ftype = fdef.get("type", "freeform_text")

        if ftype == "numerical":
            numerical_fields[fname]      = _agg_numerical(records, fname)
        elif ftype == "categorical":
            categorical_fields[fname]    = _agg_categorical(records, fname)
        elif ftype == "boolean":
            boolean_fields[fname]        = _agg_boolean(records, fname)
        elif ftype == "date":
            date_fields[fname]           = _agg_date(records, fname)
        elif ftype == "freeform_text":
            freeform_text_fields[fname]  = _agg_freeform(records, fname)

    return {
        "meta":                 meta,
        "numerical_fields":     numerical_fields,
        "categorical_fields":   categorical_fields,
        "boolean_fields":       boolean_fields,
        "date_fields":          date_fields,
        "freeform_text_fields": freeform_text_fields,
    }


def _empty_summary() -> dict:
    return {
        "meta": {
            "total_calls": 0,
            "date_range": {"min": None, "max": None},
            "teams": [],
            "agent_count": 0,
        },
        "numerical_fields":     {},
        "categorical_fields":   {},
        "boolean_fields":       {},
        "date_fields":          {},
        "freeform_text_fields": {},
    }


# ── Per-type aggregators ──────────────────────────────────────────────────────

def _agg_numerical(records: list, fname: str) -> dict:
    values_by_agent = defaultdict(list)
    values_by_team  = defaultdict(list)
    all_values      = []
    na_count        = 0

    for r in records:
        raw   = r.get(fname)
        agent = r.get("agent_name", "Unknown")
        team  = r.get("team_name", "Unknown")

        if raw == "N/A" or raw is None:
            na_count += 1
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError):
            na_count += 1
            continue

        all_values.append(val)
        values_by_agent[agent].append(val)
        values_by_team[team].append(val)

    if not all_values:
        return {
            "min": None, "max": None, "mean": None, "median": None,
            "by_team": {}, "top_agents": [], "bottom_agents": [],
            "distribution": {}, "na_count": na_count,
        }

    by_team = {
        team: {
            "mean":   round(statistics.mean(vals), 3),
            "median": round(statistics.median(vals), 3),
            "n":      len(vals),
        }
        for team, vals in values_by_team.items()
    }

    agent_means   = {a: statistics.mean(v) for a, v in values_by_agent.items() if v}
    sorted_agents = sorted(agent_means.items(), key=lambda x: x[1], reverse=True)
    top_agents    = [[a, round(v, 3)] for a, v in sorted_agents[:3]]
    bottom_agents = [[a, round(v, 3)] for a, v in sorted_agents[-3:]]

    return {
        "min":           round(min(all_values), 3),
        "max":           round(max(all_values), 3),
        "mean":          round(statistics.mean(all_values), 3),
        "median":        round(statistics.median(all_values), 3),
        "by_team":       by_team,
        "top_agents":    top_agents,
        "bottom_agents": bottom_agents,
        "distribution":  _distribution(all_values),
        "na_count":      na_count,
    }


def _distribution(values: list) -> dict:
    """Bin into 10 equal buckets, or use value_counts if ≤10 distinct values."""
    distinct = sorted(set(round(v, 1) for v in values))
    if len(distinct) <= 10:
        counts = defaultdict(int)
        for v in values:
            counts[str(round(v, 1))] += 1
        return dict(sorted(counts.items()))

    lo, hi = min(values), max(values)
    if lo == hi:
        return {str(lo): len(values)}

    bucket_size = (hi - lo) / 10
    bins = defaultdict(int)
    for v in values:
        idx  = min(int((v - lo) / bucket_size), 9)
        lo_b = round(lo + idx * bucket_size, 2)
        hi_b = round(lo + (idx + 1) * bucket_size, 2)
        bins[f"{lo_b}–{hi_b}"] += 1

    return dict(bins)


def _agg_categorical(records: list, fname: str) -> dict:
    value_counts = defaultdict(int)
    by_team      = defaultdict(lambda: defaultdict(int))

    for r in records:
        val  = r.get(fname)
        team = r.get("team_name", "Unknown")
        if val is None or val == "N/A":
            continue
        val = str(val)
        value_counts[val] += 1
        by_team[team][val] += 1

    return {
        "value_counts": dict(sorted(value_counts.items(), key=lambda x: x[1], reverse=True)),
        "by_team":      {t: dict(v) for t, v in by_team.items()},
    }


def _agg_boolean(records: list, fname: str) -> dict:
    true_count  = 0
    false_count = 0
    by_team     = defaultdict(lambda: {"true": 0, "false": 0})

    for r in records:
        raw  = r.get(fname)
        team = r.get("team_name", "Unknown")
        if raw is None or raw == "N/A":
            continue

        if isinstance(raw, bool):
            is_true = raw
        elif isinstance(raw, str):
            is_true = raw.lower() in ("true", "yes", "1")
        else:
            is_true = bool(raw)

        if is_true:
            true_count += 1
            by_team[team]["true"] += 1
        else:
            false_count += 1
            by_team[team]["false"] += 1

    return {
        "true_count":  true_count,
        "false_count": false_count,
        "by_team":     dict(by_team),
    }


def _agg_date(records: list, fname: str) -> dict:
    by_day         = defaultdict(int)
    by_team_by_day = defaultdict(lambda: defaultdict(int))

    for r in records:
        val  = r.get(fname) or r.get("call_datetime")
        team = r.get("team_name", "Unknown")
        if not val:
            continue
        day = str(val)[:10]
        by_day[day] += 1
        by_team_by_day[team][day] += 1

    return {
        "by_day":         dict(sorted(by_day.items())),
        "by_team_by_day": {t: dict(sorted(v.items())) for t, v in by_team_by_day.items()},
    }


def _agg_freeform(records: list, fname: str) -> dict:
    values = [str(r[fname]) for r in records if r.get(fname) and r[fname] != "N/A"]
    if not values:
        return {"sample": [], "avg_length_chars": 0.0}

    sample  = random.sample(values, min(5, len(values)))
    avg_len = sum(len(v) for v in values) / len(values)

    return {
        "sample":           sample,
        "avg_length_chars": round(avg_len, 1),
    }
