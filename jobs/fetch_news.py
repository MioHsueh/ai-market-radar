"""Fetch previous-day market news from TWSE and public RSS feeds."""
import hashlib
import os
import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from time import mktime
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

import requests
import streamlit as st

from services.storage import save_news, save_job_run

TWSE_BASE = "https://openapi.twse.com.tw/v1"
TIMEOUT = (5, 25)
HEADERS = {"User-Agent": "AI-Market-Radar/1.6 (market research dashboard; contact: admin@example.com)"}
TAIPEI_TZ = ZoneInfo("Asia/Taipei")

# RSS feeds are public feed endpoints. Some publishers may change feed URLs or limit access.
RSS_FEEDS = [
    {
        "name": "Yahoo 股市",
        "market": "TW",
        "url": "https://tw.stock.yahoo.com/rss?category=tw-market",
    },
    {
        "name": "中央社財經",
        "market": "TW",
        "url": "https://www.cna.com.tw/rss/aall.xml",
    },
    {
        "name": "CNBC Top News",
        "market": "US",
        "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    },
]


def _progress(callback, message):
    if callback:
        callback(message)
    print(f"[fetch_news] {message}", flush=True)


def _field(row, *keywords):
    for key, value in row.items():
        normalized = re.sub(r"\s+", "", str(key)).casefold()
        if all(re.sub(r"\s+", "", word).casefold() in normalized for word in keywords):
            if value not in (None, ""):
                return str(value).strip()
    return ""


def _pick(row, keys):
    lowered = {str(k).casefold(): v for k, v in row.items()}
    for key in keys:
        value = row.get(key)
        if value in (None, ""):
            value = lowered.get(str(key).casefold())
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _parse_published_date(value):
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None

    # ISO timestamp/date.
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TAIPEI_TZ)
        return dt.astimezone(TAIPEI_TZ).date()
    except ValueError:
        pass

    # RFC email date, common in RSS pubDate.
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(TAIPEI_TZ).date()
    except (TypeError, ValueError, OverflowError):
        pass

    # Gregorian/ROC compact dates, e.g. 20261014 / 1151014.
    digits = re.sub(r"\D", "", raw)
    try:
        if len(digits) == 7 and int(digits[:3]) < 300:
            return date(int(digits[:3]) + 1911, int(digits[3:5]), int(digits[5:7]))
        if len(digits) >= 8:
            year, month, day = int(digits[:4]), int(digits[4:6]), int(digits[6:8])
            if year >= 1900:
                return date(year, month, day)
    except (ValueError, IndexError):
        return None
    return None


def _normalise_date(value):
    raw = (value or "").strip()
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TAIPEI_TZ)
        return dt.isoformat()
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(TAIPEI_TZ).isoformat()
    except (TypeError, ValueError, OverflowError):
        pass
    parsed = _parse_published_date(raw)
    return parsed.isoformat() if parsed else raw


def _is_target_day(item, target_day):
    return _parse_published_date(item.get("published_at")) == target_day


def _stable_id(market, source, title, url, published_at):
    raw = "|".join([market, source or "", title or "", url or "", published_at or ""])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalise(market, source, title, url="", published_at="", summary=""):
    title = (title or "").strip()
    if not title:
        return None
    published_at = _normalise_date(published_at)
    return {
        "source_id": _stable_id(market, source, title, url, published_at),
        "market": market,
        "title": title[:1000],
        "summary": summary[:5000] if summary else None,
        "source": source or "Unknown",
        "url": url or None,
        "published_at": published_at or None,
    }


def fetch_twse_endpoint(path, source_label, kind, target_day):
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
            title = _pick(row, ["Title", "title", "新聞標題", "標題", "主旨"])
            date_value = _pick(row, ["Date", "date", "publishDate", "publish_date", "發布日期", "日期", "發佈日期"])
            url = _pick(row, ["Url", "URL", "url", "link", "連結", "網址"])
            summary = _pick(row, ["Content", "content", "Summary", "summary", "內容", "摘要"])
        else:
            company = _field(row, "公司代號")
            company_name = _field(row, "公司名稱") or _field(row, "公司簡稱")
            subject = _field(row, "主旨") or _field(row, "重大訊息主旨") or _field(row, "Subject")
            if not subject:
                continue
            if company_name and company:
                title = f"{company_name}（{company}）：{subject}"
            elif company:
                title = f"{company}：{subject}"
            else:
                title = subject
            date_value = (
                _field(row, "發言日期") or _field(row, "出表日期")
                or _field(row, "公告日期") or _field(row, "發布日期")
            )
            time_value = _field(row, "發言時間")
            time_digits = re.sub(r"\D", "", time_value)
            if date_value and len(time_digits) in (5, 6):
                time_digits = time_digits.zfill(6)
                date_value = (
                    f"{_normalise_date(date_value)}T"
                    f"{time_digits[:2]}:{time_digits[2:4]}:{time_digits[4:6]}"
                )
            url = _field(row, "網址") or _field(row, "url") or _field(row, "連結")
            summary = _field(row, "說明") or _field(row, "內容") or _field(row, "摘要")
            if not url and company:
                url = f"https://mops.twse.com.tw/mops/web/t05sr01_1?step=1&co_id={company}"

        if not title or _parse_published_date(date_value) != target_day:
            continue
        item = _normalise("TW", source_label, title, url, date_value, summary)
        if item and _is_target_day(item, target_day):
            results.append(item)
    return results


def fetch_tw_news(target_day):
    collected, errors = [], []
    endpoints = [
        ("news/newsList", "臺灣證券交易所新聞", "news"),
        ("opendata/t187ap04_L", "臺灣證券交易所上市公司重大訊息", "announcement"),
    ]
    for path, label, kind in endpoints:
        try:
            collected.extend(fetch_twse_endpoint(path, label, kind, target_day))
        except Exception as exc:
            errors.append(f"{path}: {type(exc).__name__}: {str(exc)[:180]}")
    unique = {item["source_id"]: item for item in collected}
    if not unique and errors:
        raise RuntimeError("台股官方資料來源皆失敗；" + "；".join(errors))
    return list(unique.values()), errors


def _xml_text(element, names):
    for name in names:
        found = element.find(name)
        if found is not None and found.text:
            return found.text.strip()
    return ""


def fetch_rss_feed(feed, target_day):
    response = requests.get(feed["url"], headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    root = ET.fromstring(response.content)
    items = root.findall(".//item")
    # Atom feeds sometimes use namespaces; support common Atom item structure too.
    if not items:
        items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

    results = []
    for entry in items:
        title = _xml_text(entry, ["title", "{http://www.w3.org/2005/Atom}title"])
        link = _xml_text(entry, ["link"])
        if not link:
            atom_link = entry.find("{http://www.w3.org/2005/Atom}link")
            if atom_link is not None:
                link = atom_link.attrib.get("href", "")
        published = (
            _xml_text(entry, ["pubDate", "published", "updated",
                              "{http://www.w3.org/2005/Atom}published",
                              "{http://www.w3.org/2005/Atom}updated"])
        )
        summary = _xml_text(
            entry,
            ["description", "summary", "{http://www.w3.org/2005/Atom}summary"],
        )
        if not title or _parse_published_date(published) != target_day:
            continue
        item = _normalise(
            feed["market"],
            feed["name"],
            title,
            link,
            published,
            summary,
        )
        if item and _is_target_day(item, target_day):
            results.append(item)
    return results


def fetch_all_rss(target_day):
    collected, notes = [], []
    for feed in RSS_FEEDS:
        try:
            items = fetch_rss_feed(feed, target_day)
            collected.extend(items)
            notes.append(f'{feed["name"]} {len(items)} 筆')
            _progress(None, f'RSS：{feed["name"]}，目標日期符合 {len(items)} 筆')
        except Exception as exc:
            note = f'{feed["name"]} RSS 失敗：{type(exc).__name__}: {str(exc)[:160]}'
            notes.append(note)
            _progress(None, note)
    unique = {item["source_id"]: item for item in collected}
    return list(unique.values()), notes


def fetch_us_news_api(target_day):
    api_key = os.getenv("STOCKNEWS_API_KEY", "").strip()
    if not api_key:
        try:
            api_key = str(st.secrets.get("STOCKNEWS_API_KEY", "")).strip()
        except Exception:
            api_key = ""
    if not api_key:
        return [], ["未設定 STOCKNEWS_API_KEY；美股 API 新聞未抓取。"]

    response = requests.get(
        "https://stocknews.ai/api/news",
        headers={"x-api-key": api_key, **HEADERS},
        params={"symbol": "SPY,NVDA,MSFT,AAPL,AMZN,GOOGL,META,TSLA", "limit": 100},
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
        if _parse_published_date(published) != target_day:
            continue
        summary = _pick(row, ["stockImpactReasoning", "sentimentReasoning"])
        if not summary and isinstance(row.get("trimSummarys"), list):
            summary = "；".join(str(x) for x in row["trimSummarys"][:5])
        item = _normalise("US", source, title, url, published, summary)
        if item and _is_target_day(item, target_day):
            results.append(item)
    return results, []


def main(progress_callback=None):
    started = datetime.now(timezone.utc)
    today_taipei = datetime.now(TAIPEI_TZ).date()
    target_day = today_taipei - timedelta(days=1)
    total_saved, notes = 0, []

    try:
        _progress(progress_callback, f"1/5：開始抓取前一日 {target_day.isoformat()}（台灣時間）新聞…")
        save_job_run(
            "fetch_news",
            "running",
            f"匯入工作已開始；目標日期為 {target_day.isoformat()}。",
            started,
        )

        tw_items, tw_errors = fetch_tw_news(target_day)
        notes.extend(tw_errors)
        _progress(progress_callback, f"2/5：官方台股來源符合日期 {len(tw_items)} 筆，開始寫入…")

        tw_saved = 0
        for index, item in enumerate(tw_items, start=1):
            if not _is_target_day(item, target_day):
                continue
            save_news(item)
            tw_saved += 1
            total_saved += 1
            if index == 1 or index % 25 == 0 or index == len(tw_items):
                _progress(progress_callback, f"3/5：官方台股寫入進度 {index}/{len(tw_items)}")
        notes.append(f"官方台股新聞 {tw_saved} 筆")

        _progress(progress_callback, "4/5：開始抓取新聞 RSS 與美股 API…")
        rss_items, rss_notes = fetch_all_rss(target_day)
        notes.extend(rss_notes)

        # Avoid duplicate records within this run; storage.source_id uniqueness handles repeats across runs.
        rss_saved = 0
        for index, item in enumerate(rss_items, start=1):
            if not _is_target_day(item, target_day):
                continue
            save_news(item)
            rss_saved += 1
            total_saved += 1
        notes.append(f"RSS 新聞 {rss_saved} 筆")

        try:
            us_items, us_notes = fetch_us_news_api(target_day)
            us_saved = 0
            for item in us_items:
                if _is_target_day(item, target_day):
                    save_news(item)
                    us_saved += 1
                    total_saved += 1
            notes.append(f"美股 API 新聞 {us_saved} 筆")
            notes.extend(us_notes)
        except Exception as exc:
            notes.append(f"美股 API 失敗：{type(exc).__name__}: {str(exc)[:160]}")

        status = "success" if total_saved else "warning"
        message = (
            f"目標日期（台灣時間）：{target_day.isoformat()}；本次處理 {total_saved} 筆。 "
            + "；".join(notes)
        )
        save_job_run("fetch_news", status, message, started)
        _progress(progress_callback, f"5/5：完成。{message}")
        return message

    except Exception as exc:
        message = f"新聞匯入失敗：{type(exc).__name__}: {str(exc)[:500]}"
        try:
            save_job_run("fetch_news", "failed", message, started)
        except Exception as log_exc:
            print(f"[fetch_news] 寫入失敗紀錄也失敗：{type(log_exc).__name__}: {str(log_exc)[:200]}", flush=True)
        raise RuntimeError(message) from exc


if __name__ == "__main__":
    main()
