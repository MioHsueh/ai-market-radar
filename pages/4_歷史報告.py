
from datetime import date, datetime
from zoneinfo import ZoneInfo

import streamlit as st

from services.storage import (
    load_recent_news,
    load_report_history,
    save_daily_report,
)

TAIPEI_TZ = ZoneInfo("Asia/Taipei")
REPORT_LIMIT = 180


# ---------- 日期處理 ----------

def taipei_today():
    return datetime.now(TAIPEI_TZ).date()


def to_taipei_datetime(value):
    """將資料庫日期轉為台灣時區日期時間。"""
    if not value:
        return None

    try:
        if isinstance(value, datetime):
            dt = value
        else:
            text = str(value).strip()
            if len(text) == 10:
                dt = datetime.fromisoformat(text)
            else:
                dt = datetime.fromisoformat(
                    text.replace("Z", "+00:00")
                )

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TAIPEI_TZ)

        return dt.astimezone(TAIPEI_TZ)

    except (ValueError, TypeError, OverflowError):
        return None


def is_today_news(item, today):
    published = to_taipei_datetime(item.get("published_at"))
    return published is not None and published.date() == today


# ---------- 新聞分類 ----------

CATEGORY_KEYWORDS = {
    "AI 與半導體": [
        "AI", "人工智慧", "半導體", "晶片", "晶圓",
        "台積電", "TSMC", "NVIDIA", "輝達", "GPU",
        "伺服器", "先進製程", "封裝", "HBM",
    ],
    "總體經濟與金融": [
        "聯準會", "Fed", "利率", "通膨", "CPI",
        "GDP", "經濟成長", "央行", "匯率", "美元",
        "債券", "公債", "就業", "失業率",
    ],
    "股市與投資": [
        "股市", "台股", "美股", "加權指數", "那斯達克",
        "NASDAQ", "S&P 500", "標普", "道瓊", "Dow Jones",
        "成交量", "外資", "投資人", "股票",
    ],
    "企業與產業動態": [
        "營收", "財報", "獲利", "訂單", "併購",
        "合作", "裁員", "新品", "出貨", "展望",
        "供應鏈", "電動車", "能源", "零售",
    ],
    "政策與國際局勢": [
        "關稅", "貿易", "制裁", "出口管制", "政策",
        "政府", "選舉", "地緣政治", "戰爭", "中國",
        "美國政府", "法案",
    ],
}


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


# ---------- 產生新聞整理報告 ----------

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
        "> 本報告由已匯入的新聞資料與關鍵字規則自動整理，",
        "> 並非 AI 投資推論，也不構成投資建議。",
        "",
        "## 一、今日新聞概況",
        "",
        f"- 台股新聞：{len(tw_news)} 則",
        f"- 美股新聞：{len(us_news)} 則",
        f"- 新聞總數：{len(tw_news) + len(us_news)} 則",
        "",
    ]

    category_items = {}

    for item in news:
        for category in classify_news(item):
            category_items.setdefault(category, []).append(item)

    lines.extend([
        "## 二、新聞主題分類",
        "",
    ])

    for category, items in category_items.items():
        lines.append(f"### {category}（{len(items)} 則）")

        for item in items[:12]:
            market = (
                "台股"
                if str(item.get("market") or "").upper() == "TW"
                else "美股"
            )
            title = safe_text(item.get("title"), "未提供標題")
            source = safe_text(item.get("source"), "來源未提供")
            summary = str(item.get("summary") or "").strip()
            url = str(item.get("url") or "").strip()

            lines.append(f"- **[{market}] {title}**")
            lines.append(f"  - 新聞來源：{source}")

            if summary:
                summary = " ".join(summary.split())
                if len(summary) > 240:
                    summary = summary[:240] + "…"
                lines.append(f"  - 摘要：{summary}")

            if url.startswith(("https://", "http://")):
                lines.append(f"  - [閱讀原文]({url})")

        if len(items) > 12:
            lines.append(f"- 另有 {len(items) - 12} 則相關新聞未列出。")

        lines.append("")

    lines.extend([
        "## 三、台股新聞",
        "",
    ])

    if tw_news:
        for item in tw_news[:30]:
            title = safe_text(item.get("title"), "未提供標題")
            url = str(item.get("url") or "").strip()

            if url.startswith(("https://", "http://")):
                lines.append(f"- [{title}]({url})")
            else:
                lines.append(f"- {title}")
    else:
        lines.append("今日尚無符合日期條件的台股新聞。")

    lines.extend([
        "",
        "## 四、美股新聞",
        "",
    ])

    if us_news:
        for item in us_news[:30]:
            title = safe_text(item.get("title"), "未提供標題")
            url = str(item.get("url") or "").strip()

            if url.startswith(("https://", "http://")):
                lines.append(f"- [{title}]({url})")
            else:
                lines.append(f"- {title}")
    else:
        lines.append("今日尚無符合日期條件的美股新聞。")

    lines.extend([
        "",
        "## 五、閱讀提醒",
        "",
        "- 分類依新聞標題及摘要的關鍵字比對產生。",
        "- 同一則新聞可能同時歸入多個主題，因此各分類筆數不能直接相加作為新聞總數。",
        "- 新聞內容與市場影響仍應以原始來源及後續市場資料確認。",
        "",
    ])

    return "\n".join(lines)


# ---------- 頁面 ----------

st.set_page_config(
    page_title="歷史報告｜AI Market Radar",
    page_icon="🗓️",
    layout="wide",
)

st.title("🗓️ 每日市場報告與歷史紀錄")

st.caption(
    "依台灣時間整理真實新聞｜不使用付費 AI API｜"
    "歷史報告最多顯示最近 180 筆"
)

st.info(
    "報告採用新聞資料與關鍵字規則自動整理。"
    "只有實際已匯入的新聞會納入報告，不會自行編造新聞或行情。"
)

today = taipei_today()

st.subheader(f"產生今日報告｜{today.isoformat()}")

if st.button("📝 產生／更新今日報告", type="primary"):
    try:
        with st.spinner("正在讀取今日新聞並整理報告…"):
            # 讀取近期新聞，再嚴格篩選台灣時間今天發布的新聞。
            recent_news = load_recent_news(limit=500)
            today_news = [
                item for item in recent_news
                if is_today_news(item, today)
            ]

            if not today_news:
                st.warning(
                    "目前沒有找到台灣時間今天發布的新聞，"
                    "因此沒有儲存報告。請先確認新聞匯入是否完成。"
                )
            else:
                report_text = build_daily_report(today_news, today)

                save_daily_report({
                    "report_date": today.isoformat(),
                    "title": f"每日市場新聞整理｜{today.isoformat()}",
                    "market_summary": report_text,
                })

                st.success(
                    f"今日報告已儲存！共整理 {len(today_news)} 則新聞。"
                )
                st.rerun()

    except Exception as exc:
        st.error("產生或儲存報告時發生錯誤。")
        st.code(f"{type(exc).__name__}: {str(exc)[:1000]}")


st.divider()
st.subheader("歷史報告")

try:
    reports = load_report_history(REPORT_LIMIT)

    if not reports:
        st.info(
            "目前還沒有歷史報告。請先按上方按鈕產生今日報告。"
        )
    else:
        st.caption(f"目前顯示最近 {len(reports)} 筆報告。")

        report_dates = sorted(
            {str(r.get("report_date") or "") for r in reports if r.get("report_date")},
            reverse=True,
        )

        selected_date = st.selectbox(
            "依日期篩選",
            options=["全部日期"] + report_dates,
        )

        visible_reports = reports

        if selected_date != "全部日期":
            visible_reports = [
                r for r in reports
                if str(r.get("report_date") or "") == selected_date
            ]

        for report in visible_reports:
            report_date = str(report.get("report_date") or "日期未知")
            report_title = safe_text(
                report.get("title"),
                "每日市場報告",
            )
            updated_at = to_taipei_datetime(report.get("updated_at"))

            with st.expander(
                f"{report_date}｜{report_title}",
                expanded=(report_date == today.isoformat()),
            ):
                if updated_at:
                    st.caption(
                        "更新時間（台灣時間）："
                        + updated_at.strftime("%Y-%m-%d %H:%M:%S")
                    )
                else:
                    st.caption(
                        f"資料庫更新時間：{safe_text(report.get('updated_at'))}"
                    )

                st.markdown(
                    report.get("market_summary") or "這筆報告尚無內容。"
                )

except Exception as exc:
    st.error("讀取歷史報告失敗。")
    st.code(f"{type(exc).__name__}: {str(exc)[:1000]}")
