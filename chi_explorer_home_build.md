# Chi Explorer — Home Build Handoff (Non-AWS Environment)

> **For Claude Code:** Read this entire document before doing anything.
> This is a scoped build plan for a local development environment with no
> access to AWS, Amazon Bedrock, or the production database. Everything built
> here must slot cleanly into the full system described in
> `chi_explorer_handoff.md` when AWS access is available. Do not make
> architectural decisions that conflict with that document.
>
> Do not write any code until you have completed the steps in Section 6.

---

## 1. Context & Goal for This Build

Chi Explorer is a conversational call analysis tool. The full system uses
Amazon Bedrock for LLM inference, a production SQL database for call metadata,
and an existing internal Python package for batch transcript processing.

None of those are available in this environment. This build delivers a
**fully working end-to-end prototype** of Chi Explorer using:

- **OpenRouter** for all LLM inference (in place of Bedrock)
- **Synthetic data** for call transcripts, metadata, and batch outputs
- **Stub layers** for DB queries and batch dispatch that can be swapped for
  real implementations without touching surrounding code

The goal is that by the end of this build, the entire pipeline runs
locally on synthetic data — Business Agent → approval gate → synthetic batch
→ parser → Code Agent → chart execution → vision pass → summary. When AWS
access is restored, only the three stub files need replacing.

---

## 2. What This Build Covers

### In scope
- Flask app shell with streaming chat UI
- Provider abstraction layer (OpenRouter now, Bedrock later)
- Business Agent: generates SQL WHERE clause, novel system prompt, field manifest
- Approval gate UI: stubbed call count, token/cost estimate, prompt preview, sample transcripts
- Synthetic data generator: produces realistic fake JSONL batch output from a field manifest
- Schema-driven JSONL parser: consumes any field manifest, produces summary dict
- Business Agent briefing pass: reads summary dict, writes plain-text brief for Code Agent
- Code Agent: receives brief + summary dict, writes matplotlib script
- AST safety linter: validates generated Python before execution
- Chart execution layer: runs linted script, captures base64 PNG outputs
- Vision pass: Business Agent receives chart images, writes executive summary and follow-up probes
- Session state management (in-memory, per-session)
- Config system with environment switching

### Out of scope for this build
- Real SQL queries or database connections
- Real transcript fetching from S3
- Real Bedrock batch dispatch or polling
- Authentication or multi-user support
- HTML report generation (defer to full build)
- Micro-summarisation pass for freeform text fields (defer to full build)

---

## 3. Repository Structure to Create

```
chi-explorer/
├── app.py                        # Flask entry point
├── config.py                     # Environment config and feature flags
├── requirements.txt
├── .env.example
│
├── agents/
│   ├── __init__.py
│   ├── business_agent.py         # SQL + prompt + manifest generation
│   ├── briefing_agent.py         # Summary dict → code agent brief
│   ├── code_agent.py             # Brief → matplotlib script
│   └── vision_agent.py           # Chart images → executive summary
│
├── pipeline/
│   ├── __init__.py
│   ├── provider.py               # OpenRouter / Bedrock abstraction
│   ├── db.py                     # DB stub (count queries, metadata joins)
│   ├── batch.py                  # Batch stub (direct inference fallback)
│   ├── parser.py                 # Schema-driven JSONL parser
│   ├── executor.py               # AST linter + script execution
│   └── synthetic.py              # Synthetic data generator
│
├── session/
│   ├── __init__.py
│   └── state.py                  # In-memory session state manager
│
├── static/
│   ├── style.css
│   └── app.js                    # Minimal JS for streaming + UI updates
│
├── templates/
│   ├── base.html
│   ├── chat.html                 # Main chat interface
│   ├── approval_gate.html        # Gate UI fragment (HTMX partial)
│   └── results.html              # Charts + summary fragment (HTMX partial)
│
└── examples/
    ├── Chi_Scoring_prompt_output_structure.json
    ├── Chi_Coaching_prompt_output_structure.json
    └── synthetic_batch_sample.jsonl  # Generated reference file
```

---

## 4. Decisions for This Build

### 4.1 Tech stack
- **Backend:** Flask with server-sent events (SSE) for streaming
- **Frontend:** Jinja2 templates + HTMX for partial updates + minimal vanilla JS
  for SSE handling. No React, no build step.
- **LLM inference:** OpenRouter via standard HTTP (requests library).
  All calls go through `pipeline/provider.py` — no agent file imports
  requests or an SDK directly.
- **Charting:** matplotlib only. The Code Agent is instructed to use only
  matplotlib. No plotly, no seaborn.
- **Python version:** 3.11+

### 4.2 Config and environment switching

`config.py` is the single source of truth for all environment decisions.
No other file checks environment variables directly.

```python
# config.py — shape only, Claude Code writes the real implementation
INFERENCE_PROVIDER = "openrouter"   # "openrouter" | "bedrock"
DB_ENABLED = False                   # False = stub, True = real DB
BATCH_ENABLED = False                # False = direct inference, True = Bedrock batch
OPENROUTER_API_KEY = ...             # from .env
OPENROUTER_MODEL = "anthropic/claude-3-5-sonnet"  # configurable
BUSINESS_AGENT_MODEL = ...           # can differ from code agent
CODE_AGENT_MODEL = ...
VISION_AGENT_MODEL = ...
COST_WARN_THRESHOLD_USD = 3.00
CALL_COUNT_WARN_THRESHOLD = 1000
POLL_INTERVAL_SECONDS = 60
```

### 4.3 Provider abstraction

`pipeline/provider.py` exposes exactly one public function that all agents use:

```python
def chat(messages: list[dict], system: str, model: str = None) -> str:
    ...
```

It routes to OpenRouter or Bedrock based on `config.INFERENCE_PROVIDER`.
The function handles retries, rate limit backoff, and error normalisation.
Agents never know which backend they are talking to.

For streaming responses (chat UI), a companion function:

```python
def stream(messages: list[dict], system: str, model: str = None) -> Iterator[str]:
    ...
```

### 4.4 DB stub behaviour

`pipeline/db.py` when `DB_ENABLED = False`:

- `count_calls(where_clause) → {"count": 142, "stubbed": True}`
- `fetch_call_metadata(call_ids) → list[dict]` returns synthetic metadata
  records matching the call_ids passed in
- Both functions log a warning that stub data is in use

The stub metadata generator in `db.py` should produce realistic-looking
records with: call_id, call_date (last 30 days, random), agent_id, agent_name
(fake names), team (from a fixed list: Retention, Sales, Collections,
Technical Support), region (VIC, NSW, QLD, WA), call_duration_seconds.

### 4.5 Batch stub behaviour

`pipeline/batch.py` when `BATCH_ENABLED = False`:

Instead of dispatching a real batch job, it:
1. Takes the call_ids and system_prompt
2. Generates a synthetic JSONL output using `pipeline/synthetic.py`
   (see section 4.7)
3. Returns a fake job_id and marks it as immediately complete
4. Skips the polling loop (or runs one immediate "poll" that returns done)

This means the full pipeline executes synchronously in the home environment
with no waiting, which is fine for development.

### 4.6 Schema-driven parser

`pipeline/parser.py` is the most important file in this build. It must:

- Accept a JSONL file path (or file-like object) and a field manifest
- Use `jsonrepair` to handle malformed lines (pip install json-repair)
- Extract only the model output from each line (ignore input and params)
- Enrich each record with call metadata (from the stored metadata dict)
- Aggregate into a summary dict according to the field manifest types:
  - `numerical`: min, max, mean, median, by_team breakdown, top/bottom 3
    agents, distribution (binned into 10 equal buckets or value counts if
    ≤10 distinct values)
  - `categorical`: value_counts, by_team breakdown
  - `boolean`: true/false counts, by_team breakdown
  - `date`: by_day counts, by_team_by_day counts
  - `freeform_text`: 5 random samples, avg character length — no aggregation
- Handle `"N/A"` string values by excluding them from numerical aggregation
  and counting them separately as `"na_count"` on the field stats
- Be fully testable against a synthetic JSONL file with no other dependencies

The summary dict shape is defined in `chi_explorer_handoff.md` section 2.
Do not deviate from that shape.

### 4.7 Synthetic data generator

`pipeline/synthetic.py` produces fake but structurally valid batch output.
It takes a field manifest and a count, and returns a JSONL string where each
line is a realistic fake LLM output conforming to the manifest.

Rules for generation:
- `numerical` fields: random float within the declared range, occasional
  `"N/A"` (~10% of records) to test parser handling
- `categorical` fields: random choice from a small fixed set of plausible
  values (e.g. for a coaching_area field: "Digital deflection", "Call closure",
  "Needs identification", "Customer engagement", "Value added services")
- `boolean` fields: random True/False with ~60/40 weighting
- `freeform_text` fields: short lorem-ipsum-style paragraph (2–3 sentences)
- The generator should wrap each output in the JSONL envelope the real batch
  tool produces: `{"input": {...}, "model_params": {...}, "output": <json>}`
  so the parser's extraction logic is tested against the real structure

### 4.8 AST safety linter

`pipeline/executor.py` runs two steps before executing any generated script:

**Step 1 — AST lint.** Parse the script with Python's `ast` module and walk
the tree. Reject if any of the following are found:
- Import of any module not in the allowlist:
  `{matplotlib, matplotlib.pyplot, matplotlib.figure, matplotlib.axes,
  json, collections, math, base64, io, numpy}`
- Any `ast.Call` where the function name is in:
  `{exec, eval, open, compile, __import__, getattr, setattr, delattr}`
- Any `ast.Attribute` accessing `.__class__`, `.__bases__`, `.__subclasses__`
- Any string containing `subprocess`, `os.system`, `socket`, `urllib`

**Step 2 — Execution.** If lint passes, inject the summary dict as a local
variable called `summary`, execute in a restricted namespace (no builtins
except a safe whitelist), and capture any base64 PNG values written to a
list called `charts`. Enforce a 30-second timeout via `threading.Timer`.

On lint failure: return the error to the Code Agent with instructions to
fix it, and retry up to 3 times before surfacing an error to the user.

### 4.9 Agent system prompts

Each agent has a dedicated system prompt defined as a constant in its module
file. They must be written carefully — this is where most iteration will
happen. Initial versions should be written as complete, detailed prompts (not
placeholders). See section 5 for the content each system prompt must cover.

### 4.10 Session state

`session/state.py` stores per-session state in a Python dict keyed by
session_id (Flask session cookie). Each session holds:

```python
{
  "messages": [...],           # full conversation history for the UI
  "current_job": {
      "question": str,
      "where_clause": str,
      "system_prompt": str,
      "field_manifest": dict,
      "job_id": str,
      "status": "pending"|"complete"|"failed",
      "metadata": [...]        # enriched call metadata records
  },
  "last_summary_dict": dict,   # most recent parsed summary
  "last_charts": [str, ...],   # most recent base64 chart images
}
```

No disk persistence for the home build. In-memory only.

---

## 5. Agent System Prompt Requirements

These are the contents each system prompt must cover. Claude Code writes
the actual prompt text — these are the requirements, not the prompts.

### 5.1 Business Agent system prompt

Must include:
- Role: an expert call centre data analyst who translates business questions
  into structured analysis plans
- The approximate call metadata SQL schema (ask the user for this — see
  section 6)
- The two example output structures from the project files, presented as
  "examples of well-structured prompt output design, not templates"
- Prompting principles: prefer structured output (scores, categoricals,
  booleans) over freeform text; always include an overall summary score where
  meaningful; design outputs that can be aggregated across hundreds of calls
- Instructions to output a JSON object with exactly three keys:
  `where_clause` (string, SQL WHERE conditions only, no SELECT/FROM),
  `system_prompt` (string, the full novel prompt to run on each transcript),
  `field_manifest` (array of field objects with name, type, and optional range)
- Instruction that the where_clause must only reference columns that exist in
  the provided schema
- Guidance on what field types to use when: numerical for scores/counts,
  categorical for labels/outcomes, boolean for yes/no checks, freeform_text
  only when there is no better option

### 5.2 Briefing Agent system prompt

Must include:
- Role: bridges business context and technical chart generation; knows what
  the user asked and what the data contains, but writes instructions for a
  model that has neither
- Instructions to read the summary dict and identify which fields are most
  relevant to the user's original question
- Rules for chart type selection:
  - by_team data on a numerical field → grouped bar chart
  - distribution data → histogram or bar chart
  - by_day data spanning >3 days → line chart
  - categorical value_counts → horizontal bar chart (sorted descending)
  - boolean by_team → stacked bar chart (% true vs false)
  - top/bottom agents → two small bar charts side by side
- Instructions to name each chart clearly so the vision agent understands
  what it is looking at
- Instructions to output a plain-text brief (not JSON) describing:
  the user's question, the fields to use, the chart types to generate,
  exact field paths in the summary dict, and any notable values to highlight
  (e.g. "agent Dan W. has the lowest score at 1.9 — flag this")

### 5.3 Code Agent system prompt

Must include:
- Role: a Python data visualisation engineer with no knowledge of the
  business domain; receives a technical brief and writes code only
- The data is available in a variable called `summary` (already injected)
- Must output only the charts list: `charts = []` then
  `charts.append(base64_encode(fig))` for each figure
- No file I/O, no network calls, no user input
- Allowed imports only: matplotlib, json, collections, math, base64, io, numpy
- Each chart must have: a title, axis labels, readable font sizes, a tight
  layout call, and use a clean non-default matplotlib style (`seaborn-v0_8-whitegrid`
  or `ggplot`)
- Where a brief specifies top/bottom agents, use horizontal bar charts with
  agent names on the y-axis so names are readable
- Must produce at least 2 and at most 6 charts per call
- Output must be a single self-contained Python script with no functions,
  no classes — just sequential code

### 5.4 Vision Agent system prompt

Must include:
- Role: a senior contact centre analytics manager reviewing AI-generated
  analysis of call data
- It will receive one or more charts as images alongside the user's original
  question and a plain-text description of what each chart shows
- Must write: one executive summary paragraph (4–6 sentences) synthesising
  the key finding that answers the user's original question
- Must list 3–5 specific findings as bullet points, each referencing a
  specific number or name from the charts
- Must then ask the user 2–3 follow-up questions to guide next steps, such as:
  drilling into a specific team, flagging specific agents, generating an HTML
  report, or asking a related question
- Tone: direct, specific, numbers-first. No hedging. No "it appears that".

---

## 6. First Instructions for Claude Code

**Follow these steps exactly. Do not write application code until step 4
clears you to proceed.**

### Step 1 — Read the reference files

Read both of these files from the project directory before anything else:

```
Chi_Scoring_prompt_output_structure
Chi_Coaching_prompt_output_structure
```

Also read `chi_explorer_handoff.md` if it is present in the project. These
files define the output structures the Business Agent will use as examples,
and the full system architecture this home build must be compatible with.

### Step 2 — Check what already exists

Run the following before creating any files:

- List the current directory structure to see if any files already exist
- Check if a virtual environment or `requirements.txt` is already present
- Check if a `.env` file exists (do not read its contents — just check existence)
- Check if Flask, requests, matplotlib, or json-repair are already installed

Report what you find before creating anything. Do not overwrite existing files
without asking.

### Step 3 — Ask the user these questions

Ask all of these together in a single message. Do not split across multiple
exchanges.

1. **OpenRouter model preference:** Which model should be used as the default
   for all three agents? Suggested: `anthropic/claude-sonnet-4-5` for business
   and vision agents, `anthropic/claude-haiku-4-5` or similar for the code agent
   (cheaper, faster for codegen). Confirm or specify alternatives.

2. **Approximate SQL schema:** Even without DB access, the Business Agent
   needs a schema to write valid WHERE clauses. Please provide the approximate
   call metadata table structure from memory — table name(s), column names,
   and types. Rough is fine. If you cannot recall, provide a best guess and
   flag which parts are uncertain.

3. **Synthetic team and agent names:** The stub data generator needs a list
   of team names and approximate agent counts per team. Please provide the
   real team names if you are comfortable doing so, or confirm that the
   defaults (Retention, Sales, Collections, Technical Support) are
   representative enough for testing.

4. **JSONL envelope structure:** From memory, what does one line of the real
   batch output JSONL look like? Specifically: what are the top-level keys,
   and where does the model output JSON live within the structure? This is
   needed so the parser's extraction logic matches the real format.

5. **Flask port:** Any preference for which localhost port to run on?
   Default will be 5000.

6. **Existing OpenRouter setup:** Do you already have an OpenRouter API key
   and any preferred wrapper code, or should a fresh requests-based
   implementation be written from scratch?

### Step 4 — Confirm before writing code

Once you have the answers above, write a short confirmation (no code) covering:

- The model choices for each agent
- The schema you will use in the Business Agent system prompt (mark uncertain
  columns explicitly)
- The JSONL envelope structure the parser will use
- The team/agent configuration for the synthetic data generator
- A summary of what already exists vs what needs to be created

Wait for the user to confirm this summary before writing any code.

### Step 5 — Build order

Build in this exact sequence. Complete and verify each step before moving
to the next. After each step, confirm with the user before continuing.

**Step 5.1 — Project scaffold**
Create the directory structure from section 3. Create all `__init__.py`
files. Create `requirements.txt` with pinned versions. Create `.env.example`.
Do not write logic yet — just the scaffold.

**Step 5.2 — Config and provider**
Write `config.py` and `pipeline/provider.py`. The provider must handle
OpenRouter chat and stream calls with retry logic. Write a minimal test
script `test_provider.py` that sends a single "hello" message and prints
the response. The user will run this to confirm OpenRouter connectivity
before anything else is built.

**Step 5.3 — Synthetic data generator and parser**
Write `pipeline/synthetic.py` and `pipeline/parser.py` together — these
are tightly coupled. Write `test_parser.py` that generates 100 synthetic
records from a hardcoded field manifest and runs the parser, printing the
full summary dict. This step has no LLM or Flask dependency and can be
fully validated in isolation.

**Step 5.4 — AST linter and executor**
Write `pipeline/executor.py`. Write `test_executor.py` with three test
cases: a valid matplotlib script that should pass, a script with a banned
import that should be rejected, and a script with `eval()` that should be
rejected. All three must behave as expected before moving on.

**Step 5.5 — Business Agent**
Write `agents/business_agent.py` with its system prompt. Write
`test_business_agent.py` that sends three test questions and prints the
JSON output (where_clause, system_prompt, field_manifest) for each. Test
questions should include: a simple team comparison, a script compliance
check, and a competitor mention analysis. The user will review the outputs
and confirm quality before continuing.

**Step 5.6 — Session state and Flask shell**
Write `session/state.py` and `app.py` with the basic Flask routes. At this
point the UI should load, accept a message, and echo it back. No agent
calls yet — just confirm the chat UI works end to end.

**Step 5.7 — Approval gate**
Wire the Business Agent into the chat flow. When the user submits a question,
the Business Agent runs, the stub DB count is called, cost is estimated, and
the approval gate UI renders. The user should be able to see the WHERE clause,
the system prompt, the cost estimate, and 2–3 synthetic sample transcripts
(hardcoded placeholder transcripts are fine at this stage). The "Run batch"
button should be present but not yet wired.

**Step 5.8 — Briefing Agent and Code Agent**
Write `agents/briefing_agent.py` and `agents/code_agent.py`. Wire the "Run
batch" button to trigger: synthetic batch generation → parser → briefing
agent → code agent → AST lint → execution → base64 chart capture. At this
stage, display the raw base64 charts in the UI to confirm they render.
No vision pass yet.

**Step 5.9 — Vision pass and full pipeline**
Write `agents/vision_agent.py`. Wire it into the pipeline after chart
generation. The full flow should now work end-to-end: question → approval
→ run → parse → brief → code → lint → execute → vision → summary displayed
in chat with follow-up questions.

**Step 5.10 — Polish and edge cases**
- Handle the case where the Code Agent's script fails AST lint (retry up to 3
  times, then surface a graceful error)
- Handle the case where the Business Agent produces invalid JSON (retry once)
- Add the cost/count warning banners to the approval gate UI
- Confirm all stub functions log clearly that they are returning stub data
- Write a `README.md` documenting how to run the project and what each stub
  replaces in the full system

---

## 7. Definition of Done for This Build

The home build is complete when:

- [ ] A user can type any free-form question about calls into the chat UI
- [ ] The Business Agent produces a valid WHERE clause, system prompt, and
      field manifest for that question
- [ ] The approval gate renders with a stubbed call count, cost estimate,
      system prompt preview, and sample transcripts
- [ ] Clicking "Run batch" triggers the full pipeline on synthetic data
- [ ] The parser produces a valid summary dict from the synthetic JSONL
- [ ] The Code Agent produces a matplotlib script that passes AST lint
- [ ] Charts render correctly in the UI as base64 images
- [ ] The Vision Agent produces a written summary and follow-up questions
- [ ] All stub functions are clearly marked and log warnings when used
- [ ] Swapping `INFERENCE_PROVIDER`, `DB_ENABLED`, and `BATCH_ENABLED` in
      `config.py` is the only change needed to point at the real backend

---

*Home build plan — April 2026. Full system spec: `chi_explorer_handoff.md`.*
