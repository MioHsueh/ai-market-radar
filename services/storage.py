"""Small storage adapter.

Demo mode uses local JSON files for development. For deployment, replace this
adapter with PostgreSQL/Supabase; ephemeral local files are not durable on all hosts.
"""
import json
import os
from pathlib import Path

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))

def _read(name):
    path = DATA_DIR / name
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

def load_recent_news(limit=20):
    items = _read("news.json")
    return sorted(items, key=lambda x: x.get("published_at", ""), reverse=True)[:limit]

def load_latest_report():
    items = load_report_history(1)
    return items[0] if items else None

def load_report_history(limit=30):
    items = _read("reports.json")
    return sorted(items, key=lambda x: x.get("report_date", ""), reverse=True)[:limit]

def load_recent_analyses(limit=30):
    items = _read("analyses.json")
    return sorted(items, key=lambda x: x.get("created_at", ""), reverse=True)[:limit]
