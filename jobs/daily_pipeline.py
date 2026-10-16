
"""Daily Market Radar pipeline: fetch today's news and save a concise report."""

import re
from collections import Counter
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from jobs.fetch_news import main as fetch_news_main
from services.storage import (
    load_recent_news,
    save_daily_report,
    save_job_run,
)

TAIPEI_TZ = ZoneInfo("Asia/Taipei")
REPORT_NEWS_LIMIT = 500
CATEGORY_DISPLAY_LIMIT = 5
MARKET_DISPLAY_LIMIT = 8

CATEGORY_KEYWORDS = {
    "AI 與半導體": [
        "AI", "人工智慧", "半導體", "晶片", "晶圓", "台積電",
        "TSMC", "NVIDIA", "輝達", "GPU", "伺服器", "先進製程",
        "封裝", "HBM", "記憶體", "ASIC",
    ],
    "總體經濟與金融": [
        "聯準會", "Fed", "利率", "通膨", "CPI", "GDP",
        "經濟成長", "央行", "匯率", "美元", "債券", "公債",
        "就業", "失業率", "降息", "升息", "通貨膨脹",
    ],
    "股市與投資": [
        "股市", "台股", "美股", "加權指數", "那斯達克",
        "NASDAQ", "S&P 500", "標普", "道瓊", "Dow Jones",
        "成交量", "外資", "投資人", "股票", "股價",
    ],
    "企業與產業動態": [
        "營收", "財報", "獲利", "訂單", "併購", "合作",
        "裁員", "新品", "出貨", "展望", "供應鏈", "電動車",
        "能源", "零售", "毛利率", "資本支出",
    ],
    "政策與國際局勢": [
        "關稅", "貿易", "制裁", "出口管制", "政策", "政府",
        "選舉", "地緣政治", "戰爭", "中國", "美國政府", "法案",
    ],
}

INDUSTRY_KEYWORDS = {
    "半導體與晶圓代工": [
        "半導體", "晶片", "晶圓", "台積電", "TSMC", "先進製程",
    ],
    "AI 與伺服器": [
        "AI", "人工智慧", "伺服器", "GPU", "輝達", "NVIDIA", "HBM",
    ],
    "記憶體": ["記憶體", "DRAM", "NAND", "HBM"],
    "金融與銀行": ["銀行", "金融股", "金控", "利率", "放款", "壽險"],
    "電動車與汽車": ["電動車", "汽車", "特斯拉", "Tesla", "車用"],
    "能源與原物料": ["原油", "油價", "天然氣", "能源", "銅價", "黃金"],
    "航運與物流": ["航運", "貨櫃", "運價", "海運", "航空貨運"],
}


def taipei_today():
    return datetime.now(TAIPEI_TZ).date()


def to_taipei_datetime(value):
    if not value:
        return None

    try:
        if isinstance(value, datetime):
            dt = value
        else:
            raw = str(value).strip()
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TAIPEI_TZ)

        return dt.astimezone(TAIPEI_TZ)
    except (ValueError, TypeError, OverflowError):
        return None


def is_today_news(item, today):
    published = to_taipei_datetime(item.get("published_at"))
    return published is not None and published.date() == today


def safe_text(value, fallback="未提供"):
    text = str(value or "").strip()
    return text if text else fallback


def normalise_title(value):
    """Normalize title text for conservative duplicate detection."""
    text = str(value or "").casefold()
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[\W_]+", "", text, flags=re.UNICODE)
    return text


def normalise_url(value):
    url = str(value or "").strip()
    if not url.startswith(("https://", "http://")):
        return ""

    try:
        parts = urlsplit(url)
        # Ignore tracking query strings and fragments.
        return urlunsplit((
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path.rstrip("/"),
            "",
            "",
        ))
    except ValueError:
        return url


def deduplicate_news(news):
    """
    Remove exact duplicate URLs or normalized titles.
    Similar-but-not-identical headlines are retained to avoid false matches.
    """
    unique = {}
    for item in news:
        title = safe_text(item.get("title"), "")
        url = normalise_url(item.get("url"))
        title_key = normalise_title(title)

        if not title_key and not url:
            continue

        key = ("url", url) if url else ("title", title_key)
        existing = unique.get(key)

        if existing is None:
            unique[key] = item
            continue

        # Prefer the record with the more informative summary.
        old_summary = str(existing.get("summary") or "")
        new_summary = str(item.get("summary") or "")
        if len(new_summary) > len(old_summary):
            unique[key] = item

    return list(unique.values())


def classify_news(item):
    text = " ".join([
        str(item.get("title") or ""),
        str(item.get("summary") or ""),
    ]).casefold()

    matched = []
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword.casefold() in text for keyword in keywords):
            matched.append(category)

    return matched or ["其他市場新聞"]


def matched_industries(item):
    text = " ".join([
        str(item.get("title") or ""),
        str(item.get("summary") or ""),
    ]).casefold()

    return [
        industry
        for industry, keywords in INDUSTRY_KEYWORDS.items()
        if any(keyword.casefold() in text for keyword in keywords)
    ]


def news_title(item):
    return safe_text(item.get("title"), "未提供標題")


def news_summary(item, limit=180):
    summary = " ".join(str(item.get("summary") or "").split())
    if len(summary) > limit:
        return summary[:limit].rstrip() + "…"
    return summary


def news_url(item):
    url = str(item.get("url") or "").strip()
    return url if url.startswith(("https://", "http://")) else ""


def add_news_bullet(lines, item, include_summary=True):
    market = (
        "台股"
        if str(item.get("market") or "").upper() == "TW"
        else "美股"
    )
    title = news_title(item)
    url = news_url(item)

    if url:
        lines.append(f"- **[{market}] [{title}]({url})**")
    else:
        lines.append(f"- **[{market}] {title}**")

    source = str(item.get("source") or "").strip()
    if source:
        lines.append(f"  - 來源：{source}")

    summary = news_summary(item) if include_summary else ""
    if summary:
        lines.append(f"  - 摘要：{summary}")


def build_daily_report(news, today):
    # Remove duplicates before computing all counts and classifications.
    news = deduplicate_news(news)

    tw_news = [
        item for item in news
        if str(item.get("market") or "").upper() == "TW"
    ]
    us_news = [
        item for item in news
        if str(item.get("market") or "").upper() == "US"
    ]

    category_items = {}
    for item in news:
        for category in classify_news(item):
            category_items.setdefault(category, []).append(item)

    industry_items = {}
    for item in news:
        for industry in matched_industries(item):
            industry_items.setdefault(industry, []).append(item)

    lines = [
        f"# 每日市場報告｜{today.isoformat()}",
        "",
        "> 本報告依當日匯入的新聞與關鍵字規則整理。",
        "> 分類與產業關聯屬初步線索，不代表已證實的股價影響，也不構成投資建議。",
        "",
        "## 一、今日市場一分鐘總覽",
        "",
        f"- 台股新聞：{len(tw_news)} 則",
        f"- 美股新聞：{len(us_news)} 則",
        f"- 去重後新聞總數：{len(news)} 則",
        "",
        "### 今日主要新聞主題",
        "",
    ]

    ranked_categories = sorted(
        category_items.items(),
        key=lambda pair: (-len(pair[1]), pair[0]),
    )

    if ranked_categories:
        for category, items in ranked_categories[:3]:
            lines.append(f"- **{category}：** {len(items)} 則相關新聞")
    else:
        lines.append("- 今日沒有足夠的新聞可供分類。")

    lines.extend([
        "",
        "## 二、台股今日重點",
        "",
    ])

    if tw_news:
        for item in tw_news[:MARKET_DISPLAY_LIMIT]:
            add_news_bullet(lines, item)
    else:
        lines.append("今日尚無符合日期條件的台股新聞。")

    lines.extend([
        "",
        "## 三、美股今日重點",
        "",
    ])

    if us_news:
        for item in us_news[:MARKET_DISPLAY_LIMIT]:
            add_news_bullet(lines, item)
    else:
        lines.append("今日尚無符合日期條件的美股新聞。")

    lines.extend([
        "",
        "## 四、產業觀察",
        "",
        "> 以下是依新聞關鍵字找出的關聯產業，不代表已確認利多或利空。",
        "",
    ])

    ranked_industries = sorted(
        industry_items.items(),
        key=lambda pair: (-len(pair[1]), pair[0]),
    )

    if ranked_industries:
        for industry, items in ranked_industries[:6]:
            lines.append(f"### {industry}（{len(items)} 則相關新聞）")

            for item in items[:3]:
                title = news_title(item)
                url = news_url(item)
                if url:
                    lines.append(f"- [{title}]({url})")
                else:
                    lines.append(f"- {title}")

            lines.append("")
    else:
        lines.append("目前沒有足夠資料辨識明確的產業主題。")
        lines.append("")

    lines.extend([
        "## 五、後續觀察清單",
        "",
        "- **半導體與 AI：** 留意公司營收、訂單、資本支出及供應鏈出貨資訊。",
        "- **總體經濟與金融：** 若今日新聞涉及利率、通膨或就業，留意後續官方數據與央行訊息。",
        "- **企業與產業：** 以公司正式公告、財報、營收及實際訂單驗證新聞影響。",
        "- **台美市場連動：** 確認美股相關產業動態是否有新的台灣供應鏈證據，不直接假設股價同步。",
        "",
        "## 六、分類統計",
        "",
        "> 同一則新聞可能符合多個分類，因此各分類筆數不可直接相加當作新聞總數。",
        "",
    ])

    for category, items in ranked_categories:
        lines.append(f"- {category}：{len(items)} 則")

    lines.extend([
        "",
        "## 七、精選新聞",
        "",
        "以下為去重後的代表性新聞；同一新聞不會再重複列出完整摘要。",
        "",
    ])

    # Select a compact list, prioritizing stories matching more themes.
    ranked_news = sorted(
        news,
        key=lambda item: (
            -len(classify_news(item)),
            -len(str(item.get("summary") or "")),
            news_title(item),
        ),
    )

    if ranked_news:
        for item in ranked_news[:10]:
            add_news_bullet(lines, item, include_summary=False)
    else:
        lines.append("今日沒有可供呈現的新聞。")

    lines.extend([
        "",
        "## 閱讀提醒",
        "",
        "- 本報告使用規則式分類，並非 AI 生成的市場預測。",
        "- 產業關聯是依標題與摘要中的關鍵字判定，仍須核對原始新聞。",
        "- 本報告不保證涵蓋所有當日新聞；目前最多讀取最近 500 筆資料。",
        "- 本報告不構成投資建議。",
        "",
    ])

    return "\n".join(lines)


def run_pipeline():
    started = datetime.now(TAIPEI_TZ)
    today = started.date()
    job_name = "daily_market_radar"

    try:
        save_job_run(
            job_name,
            "running",
            f"每日排程開始；目標日期：{today.isoformat()}（台灣時間）。",
            started,
        )

        fetch_message = fetch_news_main()
        fetched_news = load_recent_news(limit=REPORT_NEWS_LIMIT)
        today_news = [
            item for item in fetched_news
            if is_today_news(item, today)
        ]
        today_news = deduplicate_news(today_news)

        if not today_news:
            message = (
                f"新聞匯入程式已執行，但資料庫沒有找到 "
                f"{today.isoformat()}（台灣時間）的新聞。"
                f"匯入結果：{fetch_message}"
            )
            save_job_run(job_name, "warning", message, started)
            print(message, flush=True)
            return

        report = build_daily_report(today_news, today)

        save_daily_report({
            "report_date": today.isoformat(),
            "title": f"每日市場報告｜{today.isoformat()}",
            "market_summary": report,
        })

        tw_count = sum(
            str(item.get("market") or "").upper() == "TW"
            for item in today_news
        )
        us_count = sum(
            str(item.get("market") or "").upper() == "US"
            for item in today_news
        )

        message = (
            f"每日報告已更新；日期：{today.isoformat()}；"
            f"去重後新聞 {len(today_news)} 則；"
            f"台股 {tw_count} 則；美股 {us_count} 則。"
        )
        save_job_run(job_name, "success", message, started)
        print(message, flush=True)

    except Exception as exc:
        message = (
            f"每日排程失敗：{type(exc).__name__}: {str(exc)[:500]}"
        )
        try:
            save_job_run(job_name, "failed", message, started)
        except Exception as log_exc:
            print(
                f"寫入排程失敗紀錄也失敗："
                f"{type(log_exc).__name__}: {str(log_exc)[:200]}",
                flush=True,
            )
        raise


if __name__ == "__main__":
    run_pipeline()
