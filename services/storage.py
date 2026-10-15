"""Supabase PostgreSQL storage adapter. Reads DATABASE_URL from Streamlit Secrets or env."""
import os, json
from contextlib import contextmanager
import streamlit as st
import psycopg
from psycopg.rows import dict_row

def _database_url():
    value = None
    try:
        value = st.secrets.get("DATABASE_URL")
    except Exception:
        pass
    value = value or os.getenv("DATABASE_URL")
    if not value:
        raise RuntimeError("尚未設定 DATABASE_URL。請在 Streamlit Cloud → Settings → Secrets 設定。")
    if "sslmode=" not in value:
        value += ("&" if "?" in value else "?") + "sslmode=require"
    return value

@contextmanager
def _connection():
    conn = psycopg.connect(_database_url(), row_factory=dict_row, connect_timeout=10)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def check_database():
    try:
        with _connection() as conn:
            row = conn.execute("select current_database() as db, now() as server_time").fetchone()
        return True, f"連線成功；資料庫：{row['db']}；伺服器時間：{row['server_time']}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {str(exc).splitlines()[0][:240]}"

def _fetch_all(sql, params=()):
    with _connection() as conn:
        return conn.execute(sql, params).fetchall()

def load_recent_news(limit=20):
    return _fetch_all("""select market,title,summary,source,url,published_at,fetched_at
        from public.news order by published_at desc nulls last,fetched_at desc limit %s""", (int(limit),))

def load_latest_report():
    rows = load_report_history(1)
    return rows[0] if rows else None

def load_report_history(limit=30):
    rows = _fetch_all("""select report_date,title,market_summary,updated_at
        from public.daily_reports order by report_date desc limit %s""", (int(limit),))
    for row in rows:
        row["report_date"] = str(row["report_date"])
    return rows

def load_recent_analyses(limit=30):
    return _fetch_all("""select headline,summary,industry_impact,related_stocks,watch_items,source_url,created_at
        from public.analyses order by created_at desc limit %s""", (int(limit),))

def save_news(item):
    with _connection() as conn:
        row = conn.execute("""insert into public.news
            (source_id,market,title,summary,source,url,published_at)
            values (%s,%s,%s,%s,%s,%s,%s)
            on conflict (source_id) do update set market=excluded.market,title=excluded.title,
            summary=excluded.summary,source=excluded.source,url=excluded.url,published_at=excluded.published_at
            returning id""", (item.get("source_id"),item["market"],item["title"],item.get("summary"),
            item.get("source"),item.get("url"),item.get("published_at"))).fetchone()
        return row["id"]

def save_analysis(item):
    with _connection() as conn:
        row = conn.execute("""insert into public.analyses
            (headline,summary,industry_impact,related_stocks,watch_items,source_url)
            values (%s,%s,%s,%s::jsonb,%s::jsonb,%s) returning id""",
            (item["headline"],item.get("summary"),item.get("industry_impact"),
             json.dumps(item.get("related_stocks",[]),ensure_ascii=False),
             json.dumps(item.get("watch_items",[]),ensure_ascii=False),item.get("source_url"))).fetchone()
        return row["id"]

def save_daily_report(report):
    with _connection() as conn:
        conn.execute("""insert into public.daily_reports(report_date,title,market_summary,updated_at)
            values (%s,%s,%s,now()) on conflict(report_date) do update set title=excluded.title,
            market_summary=excluded.market_summary,updated_at=now()""",
            (report["report_date"],report.get("title"),report.get("market_summary")))

def save_job_run(job_name,status,message=None,started_at=None):
    with _connection() as conn:
        row = conn.execute("""insert into public.job_runs(job_name,status,message,started_at,finished_at)
            values (%s,%s,%s,coalesce(%s,now()),now()) returning id""",
            (job_name,status,(message or "")[:2000],started_at)).fetchone()
        return row["id"]
