
"""Daily Market Radar pipeline: fetch today's news and save a report."""
from datetime import datetime
from zoneinfo import ZoneInfo

from jobs.fetch_news import main as fetch_news_main
from services.storage import (
    load_recent_news,
    save_daily_report,
    save_job_run,
)

TAIPEI_TZ = ZoneInfo("Asia/Taipei")
REPORT_NEWS_LIMIT = 500

CATEGORY_KEYWORDS = {
    "AI 與半導體": [
        "AI", "人工智慧", "半導體", "晶片", "晶圓", "台積電",
        "TSMC", "NVIDIA", "輝達", "GPU", "伺服器", "先進製程",
        "封裝", "HBM", "記憶體",
    ],
    "總體經濟與金融": [
        "聯準會", "Fed", "利率", "通膨", "CPI", "GDP",
        "經濟成長", "央行", "匯率", "美元", "債券", "公債",
        "就業", "失業率", "降息", "升息",
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


def safe_text(value, fallback="未提供"):
    text = str(value or "").strip()
    return text if text else fallback


def build_daily_report(news, today):
    tw_news = [
        item for item in news
        if str(item.get("market") or "").upper() == "TW"
    ]
    us_news = [
        item for item in news
        if str(item.get("market") or "").upper() == "US"
    ]

    lines = [
        f"# 每日市場新聞整理｜{today.isoformat()}",
        "",
        "> 本報告根據已匯入的真實新聞及關鍵字規則整理。",
        "> 分類與情緒判讀不等於已證實的市場影響，也不構成投資建議。",
        "",
        "## 一、今日新聞概況",
        "",
        f"- 台股新聞：{len(tw_news)} 則",
        f"- 美股新聞：{len(us_news)} 則",
        f"- 新聞總數：{len(news)} 則",
        "",
        "## 二、新聞主題分類",
        "",
    ]

    category_items = {}
    for item in news:
        for category in classify_news(item):
            category_items.setdefault(category, []).append(item)

    for category, items in sorted(
        category_items.items(),
        key=lambda pair: (-len(pair[1]), pair[0]),
    ):
        lines.append(f"### {category}（{len(items)} 則）")

        for item in items[:12]:
            market = (
                "台股"
                if str(item.get("market") or "").upper() == "TW"
                else "美股"
            )
            title = safe_text(item.get("title"), "未提供標題")
            source = safe_text(item.get("source"), "來源未提供")
            summary = " ".join(
                str(item.get("summary") or "").split()
            )
            url = str(item.get("url") or "").strip()

            lines.append(f"- **[{market}] {title}**")
            lines.append(f"  - 新聞來源：{source}")

            if summary:
                if len(summary) > 240:
                    summary = summary[:240] + "…"
                lines.append(f"  - 摘要：{summary}")

            if url.startswith(("https://", "http://")):
                lines.append(f"  - [閱讀原文]({url})")

        if len(items) > 12:
            lines.append(f"- 另有 {len(items) - 12} 則相關新聞未列出。")

        lines.append("")

    for heading, items in [
        ("三、台股新聞", tw_news),
        ("四、美股新聞", us_news),
    ]:
        lines.extend([f"## {heading}", ""])

        if not items:
            lines.append("今日尚無符合日期條件的新聞。")
        else:
            for item in items[:30]:
                title = safe_text(item.get("title"), "未提供標題")
                url = str(item.get("url") or "").strip()

                if url.startswith(("https://", "http://")):
                    lines.append(f"- [{title}]({url})")
                else:
                    lines.append(f"- {title}")

        lines.append("")

    lines.extend([
        "## 五、閱讀提醒",
        "",
        "- 分類依新聞標題與摘要中的關鍵字比對產生。",
        "- 同一則新聞可以歸入多個主題，各分類筆數不能直接相加。",
        "- 股票關聯與利多利空判讀應以原始新聞及後續資料再次確認。",
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

        # Reuse the existing tested news importer.
        fetch_message = fetch_news_main()
        news = load_recent_news(limit=REPORT_NEWS_LIMIT)
        today_news = [
            item for item in news if is_today_news(item, today)
        ]

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
            "title": f"每日市場新聞整理｜{today.isoformat()}",
            "market_summary": report,
        })

        message = (
            f"每日報告已更新；日期：{today.isoformat()}；"
            f"新聞 {len(today_news)} 則；"
            f"台股 {sum(str(n.get('market') or '').upper() == 'TW' for n in today_news)} 則；"
            f"美股 {sum(str(n.get('market') or '').upper() == 'US' for n in today_news)} 則。"
        )
        save_job_run(job_name, "success", message, started)
        print(message, flush=True)

    except Exception as exc:
        message = f"每日排程失敗：{type(exc).__name__}: {str(exc)[:500]}"
        try:
            save_job_run(job_name, "failed", message, started)
        except Exception as log_exc:
            print(
                f"寫入排程失敗紀錄也失敗：{type(log_exc).__name__}: "
                f"{str(log_exc)[:200]}",
                flush=True,
            )
        raise


if __name__ == "__main__":
    run_pipeline()

