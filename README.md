# CHI Explorer

CHI Explorer is a conversational call analysis tool that enables natural language querying of call center transcripts to generate data-driven insights, interactive charts, and executive summaries.

## Documentation

For detailed information on the project's architecture, components, and development guidelines, please refer to the following documents:

-   [**DOCUMENTATION.md**](./DOCUMENTATION.md): Comprehensive overview of the system, pipeline, and agents.
-   [**PORTING_GUIDE.md**](./PORTING_GUIDE.md): Instructions for transitioning to AWS Bedrock and a live SQL database.
-   [**DESIGN.md**](./DESIGN.md): The "Editorial Energy" design system strategy.
-   [**chi_explorer_handoff.md**](./chi_explorer_handoff.md): Original product goal and pipeline architecture specification.
-   [**chi_explorer_home_build.md**](./chi_explorer_home_build.md): The build plan for the current "Home Build" environment.

---

## Prerequisites

-   **Python 3.11+**
-   **Node.js & npm**
-   **OpenRouter API Key** (for the Home Build)

---

## Quick Start (Home Build)

The project is split into a **FastAPI backend** (`chi-explorer/`) and a **React frontend** (`frontend/`).

### 1. Initial Setup
Copy the example environment file and add your OpenRouter API key:
```bash
cd chi-explorer
cp .env.example .env
# Edit .env and add your OPENROUTER_API_KEY
```

### 2. Install Dependencies
```bash
# Backend
cd chi-explorer
pip install -r requirements.txt

# Frontend
cd ../frontend
npm install
```

### 3. How to Run

#### Option A: Using the Makefile (Recommended)
If you have `make` installed, you can start both the backend and frontend simultaneously from the `chi-explorer/` directory:
```bash
cd chi-explorer
make dev
```
-   **Backend:** http://localhost:5001
-   **Frontend:** http://localhost:5173

#### Option B: Manual Start
**Start the Backend:**
```bash
cd chi-explorer
python3 app.py
```
**Start the Frontend:**
```bash
cd frontend
npm run dev
```

---

## Running Tests

The project includes several test scripts in the `chi-explorer/` directory to validate individual components:

```bash
cd chi-explorer
python3 test_provider.py      # Verifies OpenRouter connectivity
python3 test_parser.py        # Tests the JSONL parser against synthetic data
python3 test_business_agent.py # Validates the planning phase (requires API key)
```

---

*Note: This repository is currently in a "Home Build" state. See `PORTING_GUIDE.md` for production deployment instructions.*
