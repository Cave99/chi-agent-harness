# Chi Explorer — Claude Code Handoff Document

> **For Claude Code:** Read this document in full before doing anything else.
> Do not generate any code until you have completed the file-reading and
> clarification steps listed at the end of this document.

---

## 1. Product Goal & Context

### What is this?

Chi Explorer is a conversational analysis tool that lets a user ask a natural
language question about call centre data and receive a data-driven answer —
charts, statistics, and a written summary — without manually writing SQL,
building prompts, or processing batch outputs.

It is an internal development tool (single user, local deployment for now,
with plans to host later). It wraps an existing toolchain that already handles
transcript fetching, prompt injection, and Amazon Bedrock batch job dispatch.

### Why does it exist?

The user currently does call analysis manually via a separate visual app —
fetching transcripts, labelling them, iterating on prompts. Chi Explorer
replaces the manual exploration loop with a chat interface where the question
itself drives the entire pipeline: SQL filter → batch job → parsed outputs →
charts → summary → follow-up.

### Business context

The business operates a contact centre and has a large, continuous volume of
call recordings that no human team has the capacity to listen through at scale.
AI is used to read transcripts and surface trends, patterns, and behaviours
that would otherwise be invisible.

Chi Explorer is the analytical layer on top of that capability. The core idea
is: **ask a business question in plain English, get an AI-powered answer drawn
from the actual content of calls.** The question scope is intentionally broad
and not limited to any fixed prompt type. Examples of the kinds of questions
the business wants to ask:

- Are our agents following the approved script for this product?
- Are customers mentioning specific competitors, and if so, which ones and in
  what context?
- What objections are customers raising most often this week?
- Are agents offering broadband upgrades during billing calls?
- Which teams are handling hardship calls with the right tone?
- What reasons are customers giving for wanting to cancel?
- Are agents correctly identifying themselves and the company at call open?
- How often are customers expressing frustration, and does it correlate with
  call length?

The system achieves this by building a **novel AI prompt from scratch** for
each question — not by selecting from a fixed menu of prompt types. The
Business Agent designs whatever prompt structure will best answer the question,
instructs the batch job to run it across a filtered set of calls, and then
synthesises the outputs into charts and a written summary.

Two existing prompt types — CHI Scoring and CHI Coaching — are examples of
what this system can produce, not the limits of what it does. Their output
structures are included in the project as reference examples of well-structured
prompt outputs that the Business Agent can draw on for inspiration when
deciding how to structure a novel prompt's JSON output.

- `Chi_Scoring_prompt_output_structure` — scores calls 1–5 across quality
  dimensions; useful as a reference for structured numerical output design
- `Chi_Coaching_prompt_output_structure` — produces coaching recommendations
  with exact transcript quotes; useful as a reference for structured
  categorical and freeform output design

The Business Agent should be given both files as examples of good prompt output
structure, alongside general prompting principles, when it designs novel
prompts. It should not treat them as templates to parameterise.

---

## 2. Decisions Made

These are finalised. Do not re-litigate them.

### Tech stack
- **Backend:** Python, Flask (chosen for simplicity and interactivity during
  local development; designed to be portable to a hosted environment later)
- **Frontend:** Served by Flask; streaming-capable; single page with a chat
  input, message history area, and a results/charts pane
- **AI layer:** Amazon Bedrock (model flexible — Claude preferred for tool-use
  reliability, but architecture should not hard-code a single model)
- **Existing tooling:** The user has a Python package that accepts a SQL query,
  fetches call IDs, injects transcripts into a prompt template using
  `{transcript}` placeholder replacement, and dispatches to Bedrock either as
  a direct call or a batch job. This package must be treated as a black box and
  called via its existing interface — do not rewrite it.

### Pipeline architecture (8 steps)

```
1. User types natural language question into chat UI
2. Business Agent (Bedrock) generates:
      - SQL WHERE clause (not a full query — WHERE only)
      - A novel system prompt tailored to the question
      - A field manifest declaring output field names and types
3. Approval gate shown to user:
      - SQL + matched call count (run a COUNT query immediately)
      - Token estimate + input cost estimate
      - Warning if >1,000 calls or >$3 estimated input cost
      - 2–3 sample transcripts displayed alongside generated system prompt
      - Single "Run batch" button; user can also edit the question and regenerate
4. On approval: existing tool is called with the SQL and injected prompt
      Batch job is dispatched; UI polls every 60 seconds with a progress indicator
5. Batch output (JSONL) is parsed by a pure Python parser (no LLM involved):
      - Uses jsonrepair to handle malformed lines
      - Extracts LLM output fields only (ignores input prompt and model params)
      - Enriches each record with call metadata joined at fetch time:
        call_id, call_date, agent_id, agent_name, team, and any other
        hierarchy fields from the call metadata SQL table
      - Produces a structured summary dict (see section below)
6. Business Agent (second pass) reads the summary dict and writes a plain-text
   briefing for the Code Agent, specifying:
      - Which fields to use for which charts
      - What chart types are appropriate given the data shape and date range
      - Top/bottom agent names and values to highlight
      - What the user's original question was
7. Code Agent (separate Bedrock call, no business context) receives only the
   briefing and the summary dict. It writes a self-contained matplotlib Python
   script. The script receives data via a variable called `summary` injected
   at runtime. It outputs each chart as base64-encoded PNG to a list. No file
   I/O, no network calls, no imports outside the allowlist.
      - Before execution, the script is linted via Python's ast module.
        Allowed imports: matplotlib, matplotlib.pyplot, json, collections,
        math, base64, io. Any other import, and any use of exec, eval, open,
        subprocess, or __import__, causes rejection and a re-prompt.
      - HTML reports are rendered in a sandboxed iframe
        (sandbox="allow-scripts", no allow-same-origin).
8. Business Agent (vision pass) receives the generated chart images as base64.
   It writes an executive summary paragraph and 3–5 key findings, then probes
   the user with follow-up questions (drill into a team? want an HTML report?
   specific agents to flag?). The HTML report is generated on request, not
   automatically.
```

### Summary dict structure

The parser produces this structure and nothing else is passed to any LLM:

```python
{
  "meta": {
    "total_calls": int,
    "date_range": {"min": "YYYY-MM-DD", "max": "YYYY-MM-DD"},
    "teams": [str, ...],
    "agent_count": int
  },
  "numerical_fields": {
    "<field_name>": {
      "min": float, "max": float, "mean": float, "median": float,
      "by_team": {
        "<team>": {"mean": float, "median": float, "n": int}
      },
      "top_agents":    [[agent_name, value], ...],  # top 3
      "bottom_agents": [[agent_name, value], ...],  # bottom 3
      "distribution":  {str: int, ...}              # value counts or binned
    }
  },
  "categorical_fields": {
    "<field_name>": {
      "value_counts": {str: int},
      "by_team": {"<team>": {str: int}}
    }
  },
  "boolean_fields": {
    "<field_name>": {
      "true_count": int, "false_count": int,
      "by_team": {"<team>": {"true": int, "false": int}}
    }
  },
  "date_fields": {
    "<field_name>": {
      "by_day": {"YYYY-MM-DD": int},
      "by_team_by_day": {"<team>": {"YYYY-MM-DD": int}}
    }
  },
  "freeform_text_fields": {
    "<field_name>": {
      "sample": [str, ...],        # 5 random values
      "avg_length_chars": float
    }
  }
}
```

### Field manifest (produced by Business Agent alongside the SQL and prompt)

```json
{
  "fields": [
    {"name": "overall_chi_score", "type": "numerical", "range": [1, 5]},
    {"name": "primary_coaching_area", "type": "categorical"},
    {"name": "digital_deflection_attempted", "type": "boolean"},
    {"name": "call_summary", "type": "freeform_text"}
  ]
}
```

The parser reads this manifest to know how to handle each field. It is stored
alongside the job so the parser does not have to infer field types from data.

### Metadata enrichment

Call metadata (call_id, call_date, agent_id, agent_name, team, and hierarchy
fields) is joined to each transcript at fetch time, before the batch fires.
When the batch output comes back, the parser zips it with the stored metadata
by call_id — no second DB query required.

### Text field handling strategy

- **Low-cardinality text** (e.g. coaching area labels, call outcomes): treat
  as categorical, count occurrences.
- **Freeform text** (e.g. call summaries, quote fields): sample 5 random
  values, compute average character length, skip for charting. Surfaced in
  summary dict as context only.
- **Optional micro-summarisation pass:** for important freeform fields, a
  cheap secondary Bedrock call over 50 random samples can produce a bullet-
  point synthesis. This is opt-in and triggered explicitly by the user, not
  run automatically.
- **Prompt design principle:** the Business Agent should strongly prefer
  structured output fields (scores, categorical labels, booleans) when
  building novel prompts. Freeform text is a second-class output type.

### Deployment target

Local development tool for now. The execution wrapper for generated Python
scripts must be designed as a clean interface so the sandbox backend can be
swapped (e.g. to AWS Lambda with no network) when the tool moves to hosted
deployment without touching surrounding code.

### Cost guardrails

- Warn (do not block) if matched call count exceeds 1,000
- Warn (do not block) if estimated input token cost exceeds $3
- Both warnings shown at the approval gate before the user can confirm

---

## 3. Assumed Architecture

**These are assumptions based on the design conversation. Verify before
building.**

- The existing tooling is a Python package (importable, not a CLI or REST
  API) with a callable interface along the lines of:
  `tool.run(sql_where_clause, system_prompt, mode="batch"|"direct")`
  returning a job ID or result object.

- The call metadata lives in a SQL database (likely PostgreSQL or MySQL)
  with a table that has at minimum: call_id, call_date, agent_id, agent_name,
  team. Additional hierarchy columns (region, cohort, etc.) are assumed to
  exist but are unknown.

- Transcripts are stored in Amazon S3. The existing tool handles the S3 fetch
  given a call_id — the new code does not need to interact with S3 directly.

- Batch output is a JSONL file (one JSON object per line) stored somewhere
  accessible after the job completes. Each line contains the input prompt,
  model parameters, and model output. The parser extracts the model output
  only.

- The existing visual app and Chi Explorer will run as separate processes
  and do not share state. Chi Explorer does not need to read or write any
  files used by the existing app.

- Bedrock credentials are available in the environment (via AWS profile or
  environment variables). No credential management code needs to be written.

---

## 4. Known Unknowns

These must be resolved before the relevant code is written. They are ordered
by when they become blocking.

1. **Existing tool interface** — The exact import path, function signatures,
   and return types of the existing Python package are unknown. The package's
   interface determines how the batch dispatch layer is written and how job
   status is polled.

2. **Batch output file location** — Where does the completed JSONL file land?
   Local filesystem path, S3 bucket, or returned directly by the tool? This
   determines how the parser reads it.

3. **Call metadata SQL schema** — The exact table name(s), column names, and
   available hierarchy fields are unknown. The Business Agent system prompt
   must include the real schema with example values to generate valid SQL.
   Foreign key relationships between calls, agents, and teams are also unknown.

4. **Database connection method** — How does the existing codebase connect to
   SQL? SQLAlchemy, psycopg2, a custom wrapper? Chi Explorer needs to run
   COUNT queries and metadata joins using the same connection.

5. **Bedrock invocation pattern** — Does the existing tool use the Bedrock
   `InvokeModel` API or the Converse API? What model IDs are currently in use?
   The Business Agent and Code Agent calls in Chi Explorer need to use
   compatible API patterns.

6. **Job polling mechanism** — Does the existing tool expose a status-check
   method, or is polling implemented externally? If externally, what is the
   job ID format and how is status checked against Bedrock batch APIs?

7. **Transcript join key** — When the parser zips batch outputs with metadata,
   what field in the JSONL output corresponds to call_id? Is it preserved
   verbatim, or does it need to be extracted from a request identifier?

8. **Existing prompt template format** — The existing tool uses `{transcript}`
   as a placeholder. Are there other placeholders in use? Is the template a
   plain string or a more structured format? This affects how the Business
   Agent's novel system prompt gets handed to the tool.

9. **N/A field handling in aggregation** — Novel prompts may produce fields
   that are not applicable to every call (e.g. a script compliance check is
   N/A if the call type doesn't involve that script). The CHI Scoring output
   structure uses `"N/A"` as a literal string value for this. A general policy
   is needed: should N/A values be excluded from means, counted as a separate
   category, or flagged in the field manifest so the Business Agent can declare
   the intended behaviour per field?

10. **Session persistence requirements** — Does conversation state (question
    history, job IDs, summary dicts) need to survive a server restart, or is
    in-memory per-session storage acceptable for the local dev phase?

11. **Chart output format for the HTML report** — Charts are embedded as
    base64 PNG in the report. Is there a preferred charting style or colour
    palette to match existing internal tools?

12. **Flask vs alternative** — The user said Flask or FastAPI or similar.
    Confirm Flask is the preferred choice before scaffolding the app shell,
    as HTMX vs minimal React for the frontend depends on this.

---

## 5. First Instructions for Claude Code

**Follow these steps in order. Do not skip ahead. Do not write application
code until step 4 explicitly clears you to do so.**

### Step 1 — Read the project output structure examples

Read both of these files in full before anything else. They are **reference
examples** of well-structured prompt outputs — not the fixed schema for this
system. The Business Agent will be given these as examples of good JSON output
design when building novel prompts for arbitrary questions. Do not treat them
as the only output shapes the parser needs to handle — the parser must be
schema-driven and work with any field manifest the Business Agent produces.

```
Chi_Scoring_prompt_output_structure
Chi_Coaching_prompt_output_structure
```

### Step 2 — Read the existing codebase

Locate and read the following before writing any code:

- The existing Python tool/package used for transcript fetching, prompt
  injection, and Bedrock dispatch. Find its entry point, read its public
  interface, and note every method signature and return type.
- Any existing database connection or ORM setup files.
- Any existing configuration files (`.env`, `config.py`, `settings.py` or
  similar) to understand how credentials and environment variables are managed.
- Any existing SQL migration files or schema definition files to understand
  the call metadata table structure.

If you cannot locate these files, ask the user for their paths before
proceeding.

### Step 3 — Ask the user to confirm the following before writing any code

Ask these as a grouped list. Do not ask one at a time across multiple messages.

1. What is the import path and calling interface of the existing tool?
   Specifically: how do you invoke a batch job, and how do you check its
   status? Please share the relevant function signatures or a short example.

2. Where does the completed batch JSONL output file land — local path, S3, or
   returned by the tool directly?

3. What is the exact name of the calls table and what columns does it have?
   Please include column names and types, particularly: what column holds
   call_id, call_date, agent_id/name, and team. Are there other hierarchy
   columns (region, cohort, etc.)?

4. How does the existing codebase connect to the database — SQLAlchemy,
   psycopg2, a custom wrapper, or something else?

5. In the JSONL batch output, what field contains the call_id so the parser
   can join outputs back to metadata?

6. When a prompt output field is not applicable to a given call (e.g. a script
   check that doesn't apply to that call type), the existing output structures
   use a literal `"N/A"` string. Should the parser always exclude N/A from
   numerical aggregations, or should the field manifest be able to declare the
   intended handling per field?

7. Confirm: Flask is the preferred backend framework, and you are happy with
   server-side rendered HTML (using HTMX for streaming/interactivity) rather
   than a separate React frontend?

### Step 4 — Confirm understanding before generating code

Once you have read the files and received answers to the questions above,
write a short confirmation message (no code) that summarises:

- The existing tool's interface as you understand it
- The DB schema for the calls table as confirmed
- The batch output format and join key
- The Flask + HTMX stack confirmation

Only after the user confirms that summary is correct should you begin writing
code, starting with the Flask app shell and the schema-driven JSONL parser.

---

*Document generated from product design conversation — April 2026.*
