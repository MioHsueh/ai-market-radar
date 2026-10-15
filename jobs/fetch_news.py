"""Fetch real Taiwan exchange news and optional US stock news into Supabase."""
import hashlib
import os
from datetime import datetime, timezone
import requests
import streamlit as st

from services.storage import save_news, save_job_run

TWSE_BASE = "https://openapi.twse.com.tw/v1"
TIMEOUT = 25
HEADERS = {"User-Agent": "AI-Market-Radar/1.0 (market research dashboard)"}


def _pick(row, keys):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _stable_id(market, source, title, url, published_at):
    raw = "|".join([market, source or "", title or "", url or "", published_at or ""])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalise(market, source, title, url="", published_at="", summary=""):
    title = (title or "").strip()
    if not title:
        return None
    return {
        "source_id": _stable_id(market, source, title, url, published_at),
        "market": market,
        "title": title[:1000],
        "summary": summary[:5000] if summary else None,
        "source": source or "Unknown",
        "url": url or None,
        "published_at": published_at or None,
    }


def fetch_twse_endpoint(path, source_label, kind):
    response = requests.get(f"{TWSE_BASE}/{path}", headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError(f"{path} 回傳格式不是清單")
    results = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        if kind == "news":
            title = _pick(row, ["title", "Title", "新聞標題", "標題", "主旨"])
            date = _pick(row, ["publishDate", "date", "發布日期", "日期", "發佈日期"])
            url = _pick(row, ["url", "URL", "link", "連結", "網址"])
            summary = _pick(row, ["content", "summary", "內容", "摘要"])
        else:
            company = _pick(row, ["公司代號", "公司代碼", "Code", "公司簡稱", "公司名稱"])
            title = _pick(row, ["事實發生日", "主旨", "重大訊息主旨", "title", "Subject"])
            date = _pick(row, ["發言日期", "公告日期", "日期", "Date", "事實發生日"])
            url = _pick(row, ["網址", "url", "URL", "連結"])
            summary = _pick(row, ["說明", "內容", "摘要", "Description"])
            if company:
                title = f"[{company}] {title}"
        item = _normalise("TW", source_label, title, url, date, summary)
        if item:
            results.append(item)
    return results


def fetch_tw_news():
    collected = []
    errors = []
    endpoints = [
        ("news/newsList", "臺灣證券交易所新聞", "news"),
        ("opendata/t187ap04_L", "臺灣證券交易所上市公司重大訊息", "announcement"),
    ]
    for path, label, kind in endpoints:
        try:
            collected.extend(fetch_twse_endpoint(path, label, kind))
        except Exception as exc:
            errors.append(f"{path}: {type(exc).__name__}: {str(exc)[:180]}")
    # De-duplicate inside this run.
    unique = {}
    for item in collected:
        unique[item["source_id"]] = item
    if not unique and errors:
        raise RuntimeError("台股資料來源皆失敗；" + "；".join(errors))
    return list(unique.values()), errors


def fetch_us_news():
    api_key = os.getenv("STOCKNEWS_API_KEY", "").strip()
    if not api_key:
        try:
            api_key = str(st.secrets.get("STOCKNEWS_API_KEY", "")).strip()
        except Exception:
            api_key = ""
    if not api_key:
        return [], ["未設定 STOCKNEWS_API_KEY；美股新聞尚未抓取。"]
    response = requests.get(
        "https://stocknews.ai/api/news",
        headers={"x-api-key": api_key, **HEADERS},
        params={"symbol": "SPY,NVDA,MSFT,AAPL,AMZN,GOOGL,META,TSLA", "limit": 30},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("data", []) if isinstance(payload, dict) else []
    results = []
    for row in rows:
        title = _pick(row, ["signalTitle", "title"])
        source = _pick(row, ["source"]) or "StockNews.AI"
        url = _pick(row, ["url"])
        published = _pick(row, ["publishedAt", "firstSeenAt", "createdAt"])
        summary = _pick(row, ["stockImpactReasoning", "sentimentReasoning"])
        if not summary:
            bullets = row.get("trimSummarys")
            if isinstance(bullets, list):
                summary = "；".join(str(x) for x in bullets[:5])
        item = _normalise("US", source, title, url, published, summary)
        if item:
            results.append(item)
    return results, []


def main():
    started = datetime.now(timezone.utc)
    total_saved = 0
    notes = []
    try:
        tw_items, tw_errors = fetch_tw_news()
        for item in tw_items:
            save_news(item)
            total_saved += 1
        notes.append(f"台股匯入 {len(tw_items)} 筆")
        notes.extend(tw_errors)

        try:
            us_items, us_notes = fetch_us_news()
            for item in us_items:
                save_news(item)
                total_saved += 1
            notes.append(f"美股匯入 {len(us_items)} 筆")
            notes.extend(us_notes)
        except Exception as exc:
            notes.append(f"美股來源錯誤：{type(exc).__name__}: {str(exc)[:180]}")

        status = "success" if total_saved > 0 else "warning"
        message = f"本次新增/更新處理 {total_saved} 筆。 " + "；".join(notes)
        save_job_run("fetch_news", status, message, started)
        print(message)
    except Exception as exc:
        message = f"新聞匯入失敗：{type(exc).__name__}: {str(exc)[:500]}"
        try:
            save_job_run("fetch_news", "failed", message, started)
        finally:
            raise RuntimeError(message) from exc


if __name__ == "__main__":
    main()
