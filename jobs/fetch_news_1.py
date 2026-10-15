
"""Fetch previous-day Taiwan-time market news and save to Supabase."""
import hashlib
import os
import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
import streamlit as st

from services.storage import save_news, save_job_run

TWSE_BASE = "https://openapi.twse.com.tw/v1"
TIMEOUT = (5, 25)
HEADERS = {"User-Agent": "AI-Market-Radar/1.5"}
TAIPEI_TZ = ZoneInfo("Asia/Taipei")


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
    """Find a field using case-insensitive key matching."""
    lowered = {str(k).casefold(): v for k, v in row.items()}
    for key in keys:
        value = row.get(key)
        if value in (None, ""):
            value = lowered.get(str(key).casefold())
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _parse_published_date(value):
    """Parse Gregorian/ROC dates and convert timestamps to Taiwan-local dates."""
    if value is None:
        return None

    raw = str(value).strip()
    if not raw:
        return None

    # ISO timestamps, e.g. 2026-10-14T07:00:03 or timestamps with offsets.
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TAIPEI_TZ)
        return dt.astimezone(TAIPEI_TZ).date()
    except ValueError:
        pass

    digits = re.sub(r"\D", "", raw)
    try:
        # ROC date: 1151014 -> 2026-10-14.
        if len(digits) == 7 and int(digits[:3]) < 300:
            return date(
                int(digits[:3]) + 1911,
                int(digits[3:5]),
                int(digits[5:7]),
            )

        # Gregorian compact date: 20261014.
        if len(digits) >= 8:
            year = int(digits[:4])
            month = int(digits[4:6])
            day = int(digits[6:8])
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

    parsed = _parse_published_date(raw)
    return parsed.isoformat() if parsed else raw


def _is_target_day(item, target_day):
    return _parse_published_date(item.get("published_at")) == target_day


def _stable_id(market, source, title, url, published_at):
    raw = "|".join([
        market,
        source or "",
        title or "",
        url or "",
        published_at or "",
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalise(market, source, title, url="", published_at="", summary=""):
    title = (title or "").strip()
    if not title:
        return None

    published_at = _normalise_date(published_at)
    return {
        "source_id": _stable_id(
            market, source, title, url, published_at
        ),
        "market": market,
        "title": title[:1000],
        "summary": summary[:5000] if summary else None,
        "source": source or "Unknown",
        "url": url or None,
        "published_at": published_at or None,
    }


def fetch_twse_endpoint(path, source_label, kind, target_day):
    response = requests.get(
        f"{TWSE_BASE}/{path}",
        headers=HEADERS,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()

    if not isinstance(payload, list):
        raise ValueError(f"{path} 回傳格式不是清單")

    results = []

    for row in payload:
        if not isinstance(row, dict):
            continue

        if kind == "news":
            # Confirmed TWSE newsList keys: Title, Url, Date.
            title = _pick(
                row,
                ["Title", "title", "新聞標題", "標題", "主旨"],
            )
            date_value = _pick(
                row,
                [
                    "Date", "date", "publishDate", "publish_date",
                    "發布日期", "日期", "發佈日期",
                ],
            )
            url = _pick(
                row,
                ["Url", "URL", "url", "link", "連結", "網址"],
            )
            summary = _pick(
                row,
                ["Content", "content", "Summary", "summary", "內容", "摘要"],
            )

        else:
            company = _field(row, "公司代號")
            company_name = (
                _field(row, "公司名稱")
                or _field(row, "公司簡稱")
            )
            subject = (
                _field(row, "主旨")
                or _field(row, "重大訊息主旨")
                or _field(row, "Subject")
            )

            if not subject:
                continue

            if company_name and company:
                title = f"{company_name}（{company}）：{subject}"
            elif company:
                title = f"{company}：{subject}"
            else:
                title = subject

            date_value = (
                _field(row, "發言日期")
                or _field(row, "出表日期")
                or _field(row, "公告日期")
                or _field(row, "發布日期")
            )

            time_value = _field(row, "發言時間")
            time_digits = re.sub(r"\D", "", time_value)

            if date_value and len(time_digits) in (5, 6):
                time_digits = time_digits.zfill(6)
                date_value = (
                    f"{_normalise_date(date_value)}T"
                    f"{time_digits[:2]}:{time_digits[2:4]}:"
                    f"{time_digits[4:6]}"
                )

            url = (
                _field(row, "網址")
                or _field(row, "url")
                or _field(row, "連結")
            )
            summary = (
                _field(row, "說明")
                or _field(row, "內容")
                or _field(row, "摘要")
            )

            if not url and company:
                url = (
                    "https://mops.twse.com.tw/mops/web/"
                    f"t05sr01_1?step=1&co_id={company}"
                )

        # Strictly include only the target calendar date.
        if not title or _parse_published_date(date_value) != target_day:
            continue

        item = _normalise(
            "TW", source_label, title, url, date_value, summary
        )

        if item and _is_target_day(item, target_day):
            results.append(item)

    return results


def fetch_tw_news(target_day):
    collected = []
    errors = []

    endpoints = [
        ("news/newsList", "臺灣證券交易所新聞", "news"),
        (
            "opendata/t187ap04_L",
            "臺灣證券交易所上市公司重大訊息",
            "announcement",
        ),
    ]

    for path, label, kind in endpoints:
        try:
            collected.extend(
                fetch_twse_endpoint(
                    path, label, kind, target_day
                )
            )
        except Exception as exc:
            errors.append(
                f"{path}: {type(exc).__name__}: {str(exc)[:180]}"
            )

    unique = {item["source_id"]: item for item in collected}

    if not unique and errors:
        raise RuntimeError(
            "台股資料來源皆失敗；" + "；".join(errors)
        )

    return list(unique.values()), errors


def fetch_us_news(target_day):
    api_key = os.getenv("STOCKNEWS_API_KEY", "").strip()

    if not api_key:
        try:
            api_key = str(
                st.secrets.get("STOCKNEWS_API_KEY", "")
            ).strip()
        except Exception:
            api_key = ""

    if not api_key:
        return [], [
            "未設定 STOCKNEWS_API_KEY；美股新聞尚未抓取。"
        ]

    response = requests.get(
        "https://stocknews.ai/api/news",
        headers={"x-api-key": api_key, **HEADERS},
        params={
            "symbol": "SPY,NVDA,MSFT,AAPL,AMZN,GOOGL,META,TSLA",
            "limit": 100,
        },
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
        published = _pick(
            row, ["publishedAt", "firstSeenAt", "createdAt"]
        )

        if _parse_published_date(published) != target_day:
            continue

        summary = _pick(
            row, ["stockImpactReasoning", "sentimentReasoning"]
        )

        if not summary and isinstance(row.get("trimSummarys"), list):
            summary = "；".join(
                str(x) for x in row["trimSummarys"][:5]
            )

        item = _normalise(
            "US", source, title, url, published, summary
        )

        if item and _is_target_day(item, target_day):
            results.append(item)

    return results, []


def main(progress_callback=None):
    started = datetime.now(timezone.utc)
    today_taipei = datetime.now(TAIPEI_TZ).date()
    target_day = today_taipei - timedelta(days=1)
    total_saved = 0
    notes = []

    try:
        _progress(
            progress_callback,
            f"1/5：開始抓取前一日 {target_day.isoformat()}（台灣時間）新聞…",
        )

        save_job_run(
            "fetch_news",
            "running",
            f"匯入工作已開始；只抓取前一日 {target_day.isoformat()} 的新聞。",
            started,
        )

        tw_items, tw_errors = fetch_tw_news(target_day)
        date_counts = Counter(
            str(item.get("published_at") or "無日期")[:10]
            for item in tw_items
        )

        _progress(
            progress_callback,
            f"2/5：台股前一日新聞篩選完成，共 {len(tw_items)} 筆；"
            f"日期分布：{dict(date_counts)}",
        )

        tw_saved = 0

        for index, item in enumerate(tw_items, start=1):
            if not _is_target_day(item, target_day):
                continue

            save_news(item)
            tw_saved += 1
            total_saved += 1

            if index == 1 or index % 25 == 0 or index == len(tw_items):
                _progress(
                    progress_callback,
                    f"3/5：台股寫入進度 {index}/{len(tw_items)}",
                )

        notes.append(f"台股前一日新聞處理 {tw_saved} 筆")
        notes.extend(tw_errors)

        _progress(
            progress_callback,
            "4/5：檢查美股前一日新聞來源…",
        )

        try:
            us_items, us_notes = fetch_us_news(target_day)
            us_saved = 0

            for index, item in enumerate(us_items, start=1):
                if not _is_target_day(item, target_day):
                    continue

                save_news(item)
                us_saved += 1
                total_saved += 1

                if index == 1 or index % 10 == 0 or index == len(us_items):
                    _progress(
                        progress_callback,
                        f"4/5：美股寫入進度 {index}/{len(us_items)}",
                    )

            notes.append(f"美股前一日新聞處理 {us_saved} 筆")
            notes.extend(us_notes)

        except Exception as exc:
            notes.append(
                f"美股來源錯誤：{type(exc).__name__}: {str(exc)[:180]}"
            )

        status = "success" if total_saved else "warning"
        message = (
            f"目標日期（台灣時間）：{target_day.isoformat()}；"
            f"本次處理 {total_saved} 筆前一日新聞。 "
            + "；".join(notes)
        )

        save_job_run("fetch_news", status, message, started)
        _progress(progress_callback, f"5/5：完成。{message}")
        return message

    except Exception as exc:
        message = (
            f"新聞匯入失敗：{type(exc).__name__}: {str(exc)[:500]}"
        )

        try:
            save_job_run("fetch_news", "failed", message, started)
        except Exception as log_exc:
            print(
                "[fetch_news] 寫入失敗紀錄也失敗："
                f"{type(log_exc).__name__}: {str(log_exc)[:200]}",
                flush=True,
            )

        raise RuntimeError(message) from exc


if __name__ == "__main__":
    main()
