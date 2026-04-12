import os
import json
import sqlite3
import random
import uuid
import requests
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

# Create a small cheap model to act as our customer/agent simulator
MODEL = "openai/gpt-oss-120b"
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "chi_data.db")

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS calls (
        call_id TEXT PRIMARY KEY,
        agent_name TEXT,
        team_name TEXT,
        call_datetime TEXT,
        call_duration INTEGER,
        call_queue TEXT,
        agent_leader_name TEXT,
        agent_team_id TEXT,
        region TEXT
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS transcripts (
        call_id TEXT PRIMARY KEY,
        transcript_text TEXT,
        FOREIGN KEY (call_id) REFERENCES calls (call_id)
    )
    """)
    
    conn.commit()
    return conn

def generate_call_metadata(call_id):
    teams   = ["Retention", "Sales", "Collections", "Technical Support"]
    regions = ["VIC", "NSW", "QLD", "WA", "SA"]

    first_names = ["James", "Sarah", "Michael", "Emma", "David", "Jessica",
                   "Daniel", "Olivia", "Chris", "Mia", "Ryan", "Chloe"]
    last_names  = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia",
                   "Miller", "Davis", "Wilson", "Taylor", "Anderson"]

    now = datetime.now()
    first    = random.choice(first_names)
    last     = random.choice(last_names)
    team     = random.choice(teams)
    days_ago = random.randint(0, 30)
    call_dt  = now - timedelta(days=days_ago, seconds=random.randint(0, 86400))

    return {
        "call_id":           call_id,
        "agent_name":        f"{first} {last}",
        "team_name":         team,
        "call_datetime":     call_dt.strftime("%Y-%m-%d"),
        "call_duration":     random.randint(60, 1800),
        "call_queue":        team,
        "agent_leader_name": f"Leader {random.choice(last_names)}",
        "agent_team_id":     f"T{random.randint(1, 20):02d}",
        "region":            random.choice(regions),
    }

def generate_transcript(metadata: dict) -> str:
    prompt = (
        f"Write a realistic telecom call center transcript between Agent and Customer. "
        f"Agent: {metadata['agent_name']}. Queue: {metadata['call_queue']}. "
        f"Duration: ~{metadata['call_duration'] // 60} minutes. "
        f"Cover: greeting, account verification, issue, brief hold, resolution or escalation, sign-off. "
        f"Make this a substantial, complete conversation of about 20-30 back-and-forth turns. "
        f"Output ONLY the raw dialogue starting with 'Agent:'. No commentary."
    )

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 3000,
        # Explicitly disable chain-of-thought/thinking so the model responds immediately
        "include_reasoning": False, 
    }

    # Some models use different flags for thinking, I'll provide both common ones
    # though OpenRouter standard for gpt-oss is usually just max_tokens + temp.
    # We will also add 'transforms' to strip reasoning if supported.
    
    resp = requests.post(OPENROUTER_BASE_URL, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()

def generate_one(i, total):
    """Generate a single call record + transcript. Returns (metadata, transcript) or None on error."""
    call_id  = uuid.uuid4().hex[:10].upper()
    metadata = generate_call_metadata(call_id)
    try:
        transcript = generate_transcript(metadata)
        print(f"  [{i+1}/{total}] call_id={call_id} agent={metadata['agent_name']} done")
        return metadata, transcript
    except Exception as e:
        print(f"  [{i+1}/{total}] FAILED: {e}")
        return None

def main():
    if not OPENROUTER_API_KEY:
        print("Error: OPENROUTER_API_KEY is not set.")
        return

    conn = init_db()
    cursor = conn.cursor()

    # Check if we already have data
    cursor.execute("SELECT count(*) FROM calls")
    if cursor.fetchone()[0] > 0:
        print("Database already populated. Skipping generation.")
        print("To regenerate, delete data/chi_data.db and re-run.")
        conn.close()
        return

    num_to_generate = 50 # Increased since it's faster now
    print(f"Generating {num_to_generate} mock transcripts in parallel via OpenRouter ({MODEL})...")

    results = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(generate_one, i, num_to_generate): i for i in range(num_to_generate)}
        for future in as_completed(futures):
            result = future.result()
            if result:
                results.append(result)

    print(f"\nInserting {len(results)} records into database...")
    for metadata, transcript in results:
        cursor.execute("""
            INSERT INTO calls (call_id, agent_name, team_name, call_datetime, call_duration, call_queue, agent_leader_name, agent_team_id, region)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            metadata["call_id"], metadata["agent_name"], metadata["team_name"],
            metadata["call_datetime"], metadata["call_duration"], metadata["call_queue"],
            metadata["agent_leader_name"], metadata["agent_team_id"], metadata["region"],
        ))
        cursor.execute(
            "INSERT INTO transcripts (call_id, transcript_text) VALUES (?, ?)",
            (metadata["call_id"], transcript),
        )
    conn.commit()

    print(f"Done. {len(results)} records saved to data/chi_data.db")
    conn.close()

if __name__ == "__main__":
    main()
