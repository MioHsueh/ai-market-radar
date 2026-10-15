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
    # Yahoo 股市：最新新聞與台股動態
    {
        "name": "Yahoo 股市－最新新聞",
        "market": "TW",
        "url": "https://tw.stock.yahoo.com/rss?category=news",
    },
    {
        "name": "Yahoo 股市－台股動態",
        "market": "TW",
        "url": "https://tw.stock.yahoo.com/rss?category=tw-market",
    },

    # 中央社：產經證券與科技
    {
        "name": "中央社財經",
        "market": "TW",
        "url": "https://feeds.feedburner.com/rsscna/finance",
    },
    {
        "name": "中央社科技",
        "market": "TW",
        "url": "https://feeds.feedburner.com/rsscna/technology",
    },

    # CNBC：美國綜合、經濟、財經與科技
    {
        "name": "CNBC Top News",
        "market": "US",
        "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    },
    {
        "name": "CNBC Economy",
        "market": "US",
        "url": "https://www.cnbc.com/id/20910258/device/rss/rss.html",
    },
    {
        "name": "CNBC Finance",
        "market": "US",
        "url": "https://www.cnbc.com/id/10000664/device/rss/rss.html",
    },
    {
        "name": "CNBC Technology",
        "market": "US",
        "url": "https://www.cnbc.com/id/19854910/device/rss/rss.html",
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




def _xml_text(element, names):
    for name in names:
        found = element.find(name)
        if found is not None and found.text:
            return found.text.strip()
    return ""


def fetch_rss_feed(feed, target_day):
    response = requests.get(
        feed["url"],
        headers=HEADERS,
        timeout=TIMEOUT,
    )
    response.raise_for_status()

    root = ET.fromstring(response.content)
    entries = root.findall(".//item")

    # 支援 Atom 格式
    if not entries:
        entries = root.findall(
            ".//{http://www.w3.org/2005/Atom}entry"
        )

    results = []
    missing_date = 0
    unparsed_date = 0
    parsed_dates = Counter()
    samples = []

    for entry in entries:
        title = _xml_text(
            entry,
            ["title", "{http://www.w3.org/2005/Atom}title"],
        )

        link = _xml_text(entry, ["link"])
        if not link:
            atom_link = entry.find(
                "{http://www.w3.org/2005/Atom}link"
            )
            if atom_link is not None:
                link = atom_link.attrib.get("href", "")

        published = _xml_text(
            entry,
            [
                "pubDate",
                "published",
                "updated",
                "{http://www.w3.org/2005/Atom}published",
                "{http://www.w3.org/2005/Atom}updated",
            ],
        )

        summary = _xml_text(
            entry,
            [
                "description",
                "summary",
                "{http://www.w3.org/2005/Atom}summary",
            ],
        )

        if not published:
            missing_date += 1
            continue

        parsed_day = _parse_published_date(published)
        if parsed_day is None:
            unparsed_date += 1
            if len(samples) < 3:
                samples.append(repr(published)[:100])
            continue

        parsed_dates[parsed_day.isoformat()] += 1

        if parsed_day != target_day or not title:
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

    latest_dates = sorted(parsed_dates.keys(), reverse=True)[:5]

    diagnostic = (
        f'{feed["name"]}：HTTP {response.status_code}；'
        f'文章總數 {len(entries)}；'
        f'符合目標日期 {len(results)}；'
        f'缺少日期 {missing_date}；'
        f'日期解析失敗 {unparsed_date}；'
        f'來源日期樣本 {latest_dates or "無"}'
    )

    if samples:
        diagnostic += f"；無法解析的日期樣本 {samples}"

    if not entries:
        diagnostic += "；警告：回應中沒有找到 RSS item 或 Atom entry"

    return results, diagnostic


def fetch_all_rss(target_day):
    collected = []
    notes = []

    for feed in RSS_FEEDS:
        try:
            items, diagnostic = fetch_rss_feed(feed, target_day)
            collected.extend(items)
            notes.append(diagnostic)
            _progress(None, diagnostic)

        except Exception as exc:
            note = (
                f'{feed["name"]} RSS 失敗：'
                f'{type(exc).__name__}: {str(exc)[:250]}'
            )
            notes.append(note)
            _progress(None, note)

    unique = {
        item["source_id"]: item
        for item in collected
    }
    return list(unique.values()), notes



def main(progress_callback=None):
    started = datetime.now(timezone.utc)
    today_taipei = datetime.now(TAIPEI_TZ).date()
    target_day = today_taipei
    total_saved = 0
    notes = []

    try:
        _progress(
            progress_callback,
            f"1/3：開始抓取 RSS 新聞，目標日期 {target_day.isoformat()}（台灣時間）…",
        )
        save_job_run(
            "fetch_news",
            "running",
            f"RSS 新聞匯入開始；目標日期為 {target_day.isoformat()}。",
            started,
        )

        _progress(progress_callback, "2/3：逐一檢查 RSS 來源及日期…")
        rss_items, rss_notes = fetch_all_rss(target_day)
        notes.extend(rss_notes)

        saved = 0
        for item in rss_items:
            if not _is_target_day(item, target_day):
                continue
            save_news(item)
            saved += 1
            total_saved += 1

        notes.append(f"RSS 符合日期並處理 {saved} 筆")

        status = "success" if total_saved else "warning"
        message = (
            f"目標日期（台灣時間）：{target_day.isoformat()}；"
            f"本次處理 {total_saved} 筆。"
            + "；".join(notes)
        )

        save_job_run("fetch_news", status, message, started)
        _progress(progress_callback, f"3/3：完成。{message}")
        return message

    except Exception as exc:
        message = f"新聞匯入失敗：{type(exc).__name__}: {str(exc)[:500]}"
        try:
            save_job_run("fetch_news", "failed", message, started)
        except Exception as log_exc:
            print(
                f"[fetch_news] 寫入失敗紀錄也失敗："
                f"{type(log_exc).__name__}: {str(log_exc)[:200]}",
                flush=True,
            )
        raise RuntimeError(message) from exc


if __name__ == "__main__":
    main()
