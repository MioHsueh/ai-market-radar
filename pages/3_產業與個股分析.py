
"""Rule-based industry and stock analysis without a paid AI API."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from services.storage import load_recent_news

TAIPEI_TZ = ZoneInfo("Asia/Taipei")
NEWS_LIMIT = 500

INDUSTRY_KEYWORDS = {
    "AI 與半導體": [
        "AI", "人工智慧", "半導體", "晶片", "晶圓", "台積電",
        "TSMC", "NVIDIA", "輝達", "GPU", "伺服器", "先進製程",
        "封裝", "HBM", "記憶體",
    ],
    "總體經濟與金融": [
        "聯準會", "Fed", "利率", "通膨", "CPI", "GDP",
        "央行", "匯率", "美元", "債券", "就業", "降息", "升息",
    ],
    "電動車與能源": [
        "電動車", "EV", "Tesla", "特斯拉", "電池", "充電",
        "能源", "太陽能", "風電", "儲能",
    ],
    "企業與消費": [
        "營收", "財報", "獲利", "訂單", "出貨", "展望",
        "零售", "消費", "電商", "品牌", "供應鏈",
    ],
    "政策與國際局勢": [
        "關稅", "貿易", "制裁", "出口管制", "政策",
        "地緣政治", "戰爭", "選舉", "法案",
    ],
}

# 只使用可明確識別的公司名稱或常見名稱。
# 股票代號是參考索引，不代表新聞一定會影響該股票。
STOCK_KEYWORDS = {
    "台股": {
        "台積電（2330）": ["台積電", "TSMC"],
        "鴻海（2317）": ["鴻海", "Hon Hai", "Foxconn"],
        "聯發科（2454）": ["聯發科", "MediaTek"],
        "廣達（2382）": ["廣達", "Quanta"],
        "緯創（3231）": ["緯創", "Wistron"],
        "日月光投控（3711）": ["日月光", "ASE Technology"],
        "台達電（2308）": ["台達電", "Delta Electronics"],
    },
    "美股": {
        "NVIDIA（NVDA）": ["NVIDIA", "輝達"],
        "Apple（AAPL）": ["Apple", "蘋果公司", "iPhone"],
        "Microsoft（MSFT）": ["Microsoft", "微軟"],
        "Amazon（AMZN）": ["Amazon", "亞馬遜"],
        "Alphabet（GOOGL）": ["Alphabet", "Google", "谷歌"],
        "Meta（META）": ["Meta Platforms", "Facebook"],
        "Tesla（TSLA）": ["Tesla", "特斯拉"],
        "AMD（AMD）": ["AMD", "超微"],
        "Broadcom（AVGO）": ["Broadcom", "博通"],
    },
}

POSITIVE_KEYWORDS = [
    "成長", "創高", "優於預期", "增加", "上升", "成長動能",
    "獲利增加", "營收成長", "訂單增加", "需求強勁", "擴產",
    "上調", "突破", "回購", "利多",
]

NEGATIVE_KEYWORDS = [
    "衰退", "低於預期", "下滑", "下降", "減少", "虧損",
    "裁員", "需求疲弱", "砍單", "下調", "制裁", "關稅",
    "風險升高", "違約", "利空",
]


def taipei_today():
    return datetime.now(TAIPEI_TZ).date()


def to_taipei_datetime(value):
    if not value:
        return None
    try:
        if isinstance(value, datetime):
            dt = value
        else:
            dt = datetime.fromisoformat(
                str(value).strip().replace("Z", "+00:00")
            )
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TAIPEI_TZ)
        return dt.astimezone(TAIPEI_TZ)
    except (ValueError, TypeError, OverflowError):
        return None


def news_day(item):
    dt = to_taipei_datetime(item.get("published_at"))
    return dt.date() if dt else None


def combined_text(item):
    return " ".join([
        str(item.get("title") or ""),
        str(item.get("summary") or ""),
    ]).casefold()


def classify_industries(item):
    text = combined_text(item)
    matched = [
        industry
        for industry, keywords in INDUSTRY_KEYWORDS.items()
        if any(keyword.casefold() in text for keyword in keywords)
    ]
    return matched or ["其他市場新聞"]


def find_related_stocks(item):
    text = combined_text(item)
    found = []

    for market, companies in STOCK_KEYWORDS.items():
        for company, keywords in companies.items():
            if any(keyword.casefold() in text for keyword in keywords):
                found.append((market, company))

    return found


def sentiment_hint(item):
    text = combined_text(item)
    positive = sum(
        keyword.casefold() in text for keyword in POSITIVE_KEYWORDS
    )
    negative = sum(
        keyword.casefold() in text for keyword in NEGATIVE_KEYWORDS
    )

    # Avoid claiming direction when signals are mixed or absent.
    if positive > 0 and negative == 0:
        return "偏正面", positive, negative
    if negative > 0 and positive == 0:
        return "偏負面", positive, negative
    return "中性／需人工確認", positive, negative


def market_label(item):
    market = str(item.get("market") or "").upper()
    if market == "TW":
        return "台股"
    if market == "US":
        return "美股"
    return market or "未分類"


st.set_page_config(
    page_title="產業與個股分析｜AI Market Radar",
    page_icon="📊",
    layout="wide",
)

st.title("📊 產業與個股分析")
st.caption("免費規則式分析｜依已匯入新聞分類，不使用付費 AI API")
st.info(
    "分析結果由新聞標題與摘要的關鍵字比對產生。"
    "公司被新聞提及，不代表該新聞必然影響股價；"
    "利多／利空標籤僅供初步整理，不構成投資建議。"
)

today = taipei_today()
date_choice = st.radio(
    "新聞日期",
    ["台灣時間今天", "最近 7 天", "資料庫最新新聞"],
    horizontal=True,
)

try:
    with st.spinner("正在讀取新聞並整理產業與個股關聯…"):
        all_news = load_recent_news(limit=NEWS_LIMIT)

    dated_news = [
        item for item in all_news if news_day(item) is not None
    ]

    if date_choice == "台灣時間今天":
        news = [item for item in dated_news if news_day(item) == today]
    elif date_choice == "最近 7 天":
        news = [
            item for item in dated_news
            if 0 <= (today - news_day(item)).days < 7
        ]
    else:
        news = all_news

    if not news:
        st.warning(
            "這個日期範圍目前沒有可分析的新聞。"
            "請先到新聞匯入頁確認匯入結果，或改選其他日期範圍。"
        )
        st.stop()

    industry_rows = []
    stock_rows = []
    analyzed_rows = []

    for item in news:
        title = str(item.get("title") or "未提供標題")
        source = str(item.get("source") or "來源未提供")
        url = str(item.get("url") or "").strip()
        published = to_taipei_datetime(item.get("published_at"))
        industries = classify_industries(item)
        related_stocks = find_related_stocks(item)
        sentiment, positive_count, negative_count = sentiment_hint(item)

        for industry in industries:
            industry_rows.append({
                "產業主題": industry,
                "市場": market_label(item),
                "新聞標題": title,
                "來源": source,
            })

        for market, company in related_stocks:
            stock_rows.append({
                "市場": market,
                "公司／代號": company,
                "初步判讀": sentiment,
                "新聞標題": title,
                "來源": source,
                "發布時間": (
                    published.strftime("%Y-%m-%d %H:%M")
                    if published else "未知"
                ),
                "原文連結": url,
            })

        analyzed_rows.append({
            "市場": market_label(item),
            "發布時間": (
                published.strftime("%Y-%m-%d %H:%M")
                if published else "未知"
            ),
            "新聞標題": title,
            "產業主題": "、".join(industries),
            "關聯公司": "、".join(
                company for _, company in related_stocks
            ) or "未辨識",
            "初步判讀": sentiment,
            "來源": source,
            "原文連結": url,
            "summary": str(item.get("summary") or ""),
            "positive_count": positive_count,
            "negative_count": negative_count,
        })

    tw_count = sum(
        str(item.get("market") or "").upper() == "TW" for item in news
    )
    us_count = sum(
        str(item.get("market") or "").upper() == "US" for item in news
    )
    linked_news_count = sum(
        bool(find_related_stocks(item)) for item in news
    )

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("分析新聞", f"{len(news):,}")
    col2.metric("台股新聞", f"{tw_count:,}")
    col3.metric("美股新聞", f"{us_count:,}")
    col4.metric("辨識到公司", f"{linked_news_count:,}")

    st.divider()

    st.subheader("一、產業新聞分布")
    if industry_rows:
        industry_df = pd.DataFrame(industry_rows)
        industry_counts = (
            industry_df.groupby("產業主題")
            .size()
            .sort_values(ascending=False)
            .rename("新聞筆數")
            .reset_index()
        )
        st.bar_chart(
            industry_counts.set_index("產業主題")["新聞筆數"]
        )
        st.dataframe(
            industry_counts,
            use_container_width=True,
            hide_index=True,
        )

        with st.expander("查看各產業的新聞明細"):
            chosen_industry = st.selectbox(
                "選擇產業主題",
                industry_counts["產業主題"].tolist(),
            )
            details = industry_df[
                industry_df["產業主題"] == chosen_industry
            ]
            st.dataframe(
                details,
                use_container_width=True,
                hide_index=True,
            )

    st.divider()

    st.subheader("二、關聯個股新聞")
    if stock_rows:
        stock_df = pd.DataFrame(stock_rows)
        stock_counts = (
            stock_df.groupby(["市場", "公司／代號"])
            .size()
            .sort_values(ascending=False)
            .rename("相關新聞數")
            .reset_index()
        )
        st.dataframe(
            stock_counts,
            use_container_width=True,
            hide_index=True,
        )

        chosen_stock = st.selectbox(
            "查看公司相關新聞",
            stock_counts["公司／代號"].tolist(),
        )
        details = stock_df[
            stock_df["公司／代號"] == chosen_stock
        ]

        for _, row in details.iterrows():
            with st.container(border=True):
                st.markdown(f"**{row['新聞標題']}**")
                st.caption(
                    f"{row['市場']}｜{row['發布時間']}｜"
                    f"來源：{row['來源']}"
                )
                st.write(f"初步判讀：{row['初步判讀']}")
                if row["原文連結"].startswith(("https://", "http://")):
                    st.markdown(f"[閱讀原文]({row['原文連結']})")
    else:
        st.info(
            "目前新聞沒有命中已設定的公司名稱關鍵字。"
            "這不代表沒有相關公司，只代表目前字典尚未辨識到。"
        )

    st.divider()

    st.subheader("三、新聞初步判讀")
    sentiment_counts = {}
    for row in analyzed_rows:
        sentiment_counts[row["初步判讀"]] = (
            sentiment_counts.get(row["初步判讀"], 0) + 1
        )

    sentiment_df = pd.DataFrame([
        {"初步判讀": label, "新聞筆數": count}
        for label, count in sentiment_counts.items()
    ])
    st.dataframe(
        sentiment_df,
        use_container_width=True,
        hide_index=True,
    )

    with st.expander("查看全部新聞與分析依據"):
        filter_sentiment = st.selectbox(
            "依判讀結果篩選",
            ["全部", "偏正面", "偏負面", "中性／需人工確認"],
        )
        filtered = analyzed_rows
        if filter_sentiment != "全部":
            filtered = [
                row for row in analyzed_rows
                if row["初步判讀"] == filter_sentiment
            ]

        for row in filtered:
            with st.container(border=True):
                st.markdown(f"**{row['新聞標題']}**")
                st.caption(
                    f"{row['市場']}｜{row['發布時間']}｜"
                    f"來源：{row['來源']}"
                )
                st.write(f"產業主題：{row['產業主題']}")
                st.write(f"關聯公司：{row['關聯公司']}")
                st.write(f"初步判讀：{row['初步判讀']}")
                st.caption(
                    f"正面關鍵字命中：{row['positive_count']}；"
                    f"負面關鍵字命中：{row['negative_count']}"
                )
                if row["summary"]:
                    st.write(row["summary"])
                if row["原文連結"].startswith(("https://", "http://")):
                    st.markdown(f"[閱讀原文]({row['原文連結']})")

except Exception as exc:
    st.error("產業與個股分析頁載入失敗。")
    st.code(f"{type(exc).__name__}: {str(exc)[:1000]}")
