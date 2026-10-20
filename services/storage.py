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

def _canonical_news_url(url):
    """Remove common tracking parameters so syndicated URLs match."""
    from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
    if not url:
        return ""
    try:
        parts = urlsplit(str(url).strip())
        ignored = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source"}
        query = [
            (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not k.casefold().startswith("utm_") and k.casefold() not in ignored
        ]
        path = parts.path.rstrip("/") or "/"
        return urlunsplit((parts.scheme.casefold(), parts.netloc.casefold(), path, urlencode(query), ""))
    except (TypeError, ValueError):
        return str(url).strip().rstrip("/")


def _normalized_news_title(title):
    """Normalize title by removing punctuation/whitespace for cross-feed matching."""
    import re
    return re.sub(r"[\W_]+", "", str(title or "").casefold(), flags=re.UNICODE)


def _news_day_taipei(value):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    if not value:
        return ""
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("Asia/Taipei"))
        return dt.astimezone(ZoneInfo("Asia/Taipei")).date().isoformat()
    except (TypeError, ValueError, OverflowError):
        return str(value)[:10]


def _deduplicate_news_rows(rows):
    """Deduplicate display rows across feeds, retaining the richest record."""
    kept = []
    seen_url = {}
    seen_title_day = {}
    for row in rows:
        item = dict(row)
        market = str(item.get("market") or "").upper()
        day = _news_day_taipei(item.get("published_at"))
        url_key = _canonical_news_url(item.get("url"))
        title_key = _normalized_news_title(item.get("title"))
        key_url = (market, url_key) if url_key else None
        key_title = (market, title_key, day) if title_key and day else None
        existing_index = None
        if key_url and key_url in seen_url:
            existing_index = seen_url[key_url]
        elif key_title and key_title in seen_title_day:
            existing_index = seen_title_day[key_title]
        if existing_index is None:
            idx = len(kept)
            kept.append(item)
            if key_url:
                seen_url[key_url] = idx
            if key_title:
                seen_title_day[key_title] = idx
            continue
        existing = kept[existing_index]
        if len(item.get("summary") or "") > len(existing.get("summary") or ""):
            existing["summary"] = item.get("summary")
        if not existing.get("url") and item.get("url"):
            existing["url"] = item["url"]
        # Keep source names visible as a combined provenance label.
        sources = [x.strip() for x in str(existing.get("source") or "").split(" / ") if x.strip()]
        incoming_source = str(item.get("source") or "").strip()
        if incoming_source and incoming_source not in sources:
            sources.append(incoming_source)
            existing["source"] = " / ".join(sources)
    return kept


def load_recent_news(limit=20):
    # Fetch a wider pool first, then deduplicate so duplicate rows do not occupy
    # the homepage/page limit and older unique stories are still visible.
    rows = _fetch_all("""select market,title,summary,source,url,published_at,fetched_at
        from public.news
        order by published_at desc nulls last,fetched_at desc
        limit %s""", (max(int(limit) * 10, 500),))
    return _deduplicate_news_rows(rows)[:int(limit)]

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
    return _fetch_all("""select headline,summary,industry,industry_impact,
        sentiment,sentiment_reason,sentiment_evidence,sentiment_confidence,
        related_stocks,watch_items,source_url,created_at
        from public.analyses order by created_at desc limit %s""", (int(limit),))

def save_news(item):
    """Upsert by stable source_id, but also match existing stories across feeds."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    market = str(item["market"]).upper()
    title = str(item.get("title") or "").strip()
    source_id = item.get("source_id")
    published_at = item.get("published_at")
    item_day = _news_day_taipei(published_at)
    item_url = _canonical_news_url(item.get("url"))
    item_title_key = _normalized_news_title(title)

    with _connection() as conn:
        # URL matches are checked across ALL markets and dates, with no 1000-row
        # limit. RSS feeds can publish different titles/timestamps for the same URL.
        url_candidates = []
        if item_url:
            url_candidates = conn.execute(
                """select id,source_id,market,title,summary,source,url,published_at
                   from public.news
                   where url is not null and btrim(url) <> ''
                   order by fetched_at desc"""
            ).fetchall()

        # If there is no URL match, fall back to same market + Taiwan-local
        # publication date + normalized title. No arbitrary candidate limit.
        title_candidates = []
        if item_title_key and item_day:
            title_candidates = conn.execute(
                """select id,source_id,market,title,summary,source,url,published_at
                   from public.news
                   where upper(market) = %s
                     and published_at is not null
                     and (published_at at time zone 'Asia/Taipei')::date = %s::date
                   order by fetched_at desc""",
                (market, item_day),
            ).fetchall()

        candidates_by_id = {
            candidate["id"]: candidate
            for candidate in [*url_candidates, *title_candidates]
        }
        candidates = list(candidates_by_id.values())

        duplicates = []
        for candidate in candidates:
            row_url = _canonical_news_url(candidate.get("url"))
            row_title_key = _normalized_news_title(candidate.get("title"))
            same_url = bool(item_url and row_url and item_url == row_url)
            same_title_day = bool(
                item_title_key
                and row_title_key
                and item_title_key == row_title_key
                and str(candidate.get("market") or "").upper() == market
                and item_day
                and _news_day_taipei(candidate.get("published_at")) == item_day
            )
            if same_url:
                duplicates.append(candidate)

        if duplicates:
            # Reuse the oldest matching row and delete extra duplicate rows for
            # this same story/day. This also cleans up duplicates from earlier runs.
            duplicate = sorted(duplicates, key=lambda r: r["id"])[0]
            summaries = [str(r.get("summary") or "") for r in duplicates]
            summaries.append(str(item.get("summary") or ""))
            best_summary = max(summaries, key=len) or None
            urls = [r.get("url") for r in duplicates if r.get("url")]
            urls.append(item.get("url"))
            best_url = next((u for u in urls if u), None)
            sources = []
            for candidate in duplicates:
                for src in str(candidate.get("source") or "").split(" / "):
                    src = src.strip()
                    if src and src not in sources:
                        sources.append(src)
            incoming_source = str(item.get("source") or "").strip()
            if incoming_source and incoming_source not in sources:
                sources.append(incoming_source)
            merged_source = " / ".join(sources) or incoming_source or "Unknown"
            row = conn.execute("""update public.news set
                    title=%s, summary=%s, source=%s, url=%s, published_at=%s
                where id=%s returning id""",
                (title or duplicate.get("title"), best_summary, merged_source,
                 best_url, published_at or duplicate.get("published_at"),
                 duplicate["id"])).fetchone()
            return row["id"]

        row = conn.execute("""insert into public.news
            (source_id,market,title,summary,source,url,published_at)
            values (%s,%s,%s,%s,%s,%s,%s)
            on conflict (source_id) do update set market=excluded.market,title=excluded.title,
            summary=case when length(coalesce(excluded.summary,'')) > length(coalesce(public.news.summary,''))
                         then excluded.summary else public.news.summary end,
            source=excluded.source,url=coalesce(excluded.url,public.news.url),
            published_at=coalesce(excluded.published_at,public.news.published_at)
            returning id""", (source_id,market,title,item.get("summary"),
            item.get("source"),item.get("url"),published_at)).fetchone()
        return row["id"]

def save_analysis(item):
    with _connection() as conn:
        row = conn.execute("""insert into public.analyses
            (headline,summary,industry,industry_impact,sentiment,sentiment_reason,
             sentiment_evidence,sentiment_confidence,related_stocks,watch_items,source_url)
            values (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s)
            returning id""",
            (item["headline"], item.get("summary"), item.get("industry", "其他"),
             item.get("industry_impact"), item.get("sentiment", "資訊不足"),
             item.get("sentiment_reason"), item.get("sentiment_evidence"),
             item.get("sentiment_confidence", "低"),
             json.dumps(item.get("related_stocks", []), ensure_ascii=False),
             json.dumps(item.get("watch_items", []), ensure_ascii=False),
             item.get("source_url"))).fetchone()
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

def load_news_for_date_range(start_date, end_date, limit=1000):
    """Load news published within a Taiwan-local date range."""
    with _connection() as conn:
        rows = conn.execute(
            """
            SELECT id, source_id, market, title, summary, source,
                   url, published_at, fetched_at
            FROM public.news
            WHERE published_at IS NOT NULL
              AND (published_at AT TIME ZONE 'Asia/Taipei')::date
                  >= %s::date
              AND (published_at AT TIME ZONE 'Asia/Taipei')::date
                  <= %s::date
            ORDER BY published_at DESC
            LIMIT %s
            """,
            (start_date, end_date, limit),
        ).fetchall()
        return [dict(row) for row in rows]
