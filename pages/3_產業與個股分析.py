
"""Rule-based industry and stock analysis without a paid AI API."""
from datetime import datetime
import re
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
import plotly.express as px


from services.storage import (
    load_recent_news,
    load_news_for_date_range,
)

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


# 產業影響路徑與後續觀察指標：屬於分析提示，不代表已證實的股價影響。
INDUSTRY_IMPACT_GUIDES = {
    "AI 與半導體": {
        "impact": "需求、晶片供應、先進製程／封裝產能與資本支出可能影響供應鏈。",
        "watch": "月營收、客戶訂單、產能利用率、資本支出、毛利率及法說會展望。",
        "caution": "需確認新聞是否涉及實際訂單、出貨或公司公告；僅提到 AI 不足以判定受惠。",
    },
    "總體經濟與金融": {
        "impact": "利率、通膨、匯率與就業數據可能改變資金成本、企業需求及市場評價。",
        "watch": "官方經濟數據、央行聲明、債券殖利率、匯率及後續政策指引。",
        "caution": "需確認數據相對市場預期的差異，不能只依數據升降判斷市場方向。",
    },
    "電動車與能源": {
        "impact": "需求、電池成本、能源價格與政策可能影響車廠、零組件及能源供應鏈。",
        "watch": "交車量、電池價格、訂單、原物料價格、補助政策及公司毛利率。",
        "caution": "產業題材不等於單一公司營運改善，應確認公司實際產品與營收曝險。",
    },
    "企業與消費": {
        "impact": "營收、訂單、消費需求與成本變化可能影響企業成長與獲利。",
        "watch": "月營收、訂單能見度、存貨、毛利率、財報與公司展望。",
        "caution": "需區分已公布的實際數字、公司預測與媒體推測。",
    },
    "政策與國際局勢": {
        "impact": "關稅、出口管制與地緣政治可能改變供應鏈成本、出貨限制及市場風險。",
        "watch": "政策正式公告、生效日期、豁免範圍、公司回應與供應鏈調整。",
        "caution": "政策消息仍可能變動，應以正式公告及公司揭露確認影響範圍。",
    },
    "其他市場新聞": {
        "impact": "目前無法從已設定的產業關鍵字推導明確影響路徑。",
        "watch": "閱讀原始新聞，確認涉及的公司、事件、時間點與可驗證數據。",
        "caution": "資料不足時不推定產業或股價方向。",
    },
}

def industry_evidence(item, industry):
    """Return keywords supporting an industry match."""
    text = combined_text(item)
    keywords = INDUSTRY_KEYWORDS.get(industry, [])
    return [keyword for keyword in keywords if keyword.casefold() in text]



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


def sentiment_evidence(item):
    """Return the exact keyword hits used by the rule-based sentiment hint."""
    text = combined_text(item)
    positive_hits = [
        keyword for keyword in POSITIVE_KEYWORDS
        if keyword.casefold() in text
    ]
    negative_hits = [
        keyword for keyword in NEGATIVE_KEYWORDS
        if keyword.casefold() in text
    ]
    return positive_hits, negative_hits


def company_impact_guidance(item):
    """
    Build a cautious, evidence-linked company impact note.
    This is a rule-based follow-up checklist, not a claim of confirmed impact.
    """
    industries = classify_industries(item)
    guides = []
    for industry in industries:
        guide = INDUSTRY_IMPACT_GUIDES.get(industry)
        if guide:
            guides.append((industry, guide))

    if not guides:
        return (
            "尚無足夠的產業線索，需先核對原文與公司業務。",
            "確認公司公告、營收、訂單及新聞所述事件是否直接涉及該公司。",
        )

    paths = "；".join(
        f"{industry}：{guide['impact']}" for industry, guide in guides
    )
    watches = "；".join(
        f"{industry}：{guide['watch']}" for industry, guide in guides
    )
    return paths, watches


def market_label(item):
    market = str(item.get("market") or "").upper()
    if market == "TW":
        return "台股"
    if market == "US":
        return "美股"
    return market or "未分類"


def deduplicate_news(items):
    """Deduplicate by canonical URL first, then normalized exact title."""
    def canonical_url(value):
        value = str(value or "").strip()
        if not value.startswith(("https://", "http://")):
            return ""
        try:
            from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
            parts = urlsplit(value)
            # Remove tracking parameters only; preserve query parameters that may
            # identify the actual article (some publishers put IDs in the query).
            kept_query = [
                (key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True)
                if key.casefold() not in {"fbclid", "gclid", "mc_cid", "mc_eid"}
                and not key.casefold().startswith("utm_")
            ]
            return urlunsplit((
                parts.scheme.lower(),
                parts.netloc.lower(),
                parts.path.rstrip("/"),
                urlencode(kept_query, doseq=True),
                "",
            ))
        except ValueError:
            return ""

    def title_key(value):
        return re.sub(r"[\\W_]+", "", str(value or "").casefold(), flags=re.UNICODE)

    # Prefer the record with the most useful summary when duplicates collide.
    unique = []
    seen_urls = {}
    seen_titles = {}

    for item in items:
        url_key = canonical_url(item.get("url"))
        title = title_key(item.get("title"))
        match_index = None

        if url_key and url_key in seen_urls:
            match_index = seen_urls[url_key]
        elif title and title in seen_titles:
            match_index = seen_titles[title]

        if match_index is None:
            match_index = len(unique)
            unique.append(item)
        else:
            old_summary = str(unique[match_index].get("summary") or "")
            new_summary = str(item.get("summary") or "")
            if len(new_summary) > len(old_summary):
                unique[match_index] = item

        if url_key:
            seen_urls[url_key] = match_index
        if title:
            seen_titles[title] = match_index

    return unique


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
        if date_choice == "台灣時間今天":
            # Query the complete Taiwan-local date instead of filtering only the
            # newest 500 rows, which can silently omit articles on busy days.
            news = load_news_for_date_range(today, today)
        elif date_choice == "最近 7 天":
            start_date = today - pd.Timedelta(days=6)
            news = load_news_for_date_range(start_date, today)
        else:
            # This option intentionally means a recent sample, limited to 500.
            news = load_recent_news(limit=NEWS_LIMIT)

    news = [item for item in news if news_day(item) is not None]

    # Remove exact duplicate URLs/titles before metrics and charts.
    news = deduplicate_news(news)

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
            "positive_evidence": sentiment_evidence(item)[0],
            "negative_evidence": sentiment_evidence(item)[1],
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
    
    # 計算不重複的「市場＋公司」配對數
    unique_companies = {
        (market, company)
        for item in news
        for market, company in find_related_stocks(item)
    }
    
    unique_company_count = len(unique_companies)
    
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("分析新聞", f"{len(news):,}")
    col2.metric("台股新聞", f"{tw_count:,}")
    col3.metric("美股新聞", f"{us_count:,}")
    col4.metric("命中公司關鍵字的新聞", f"{linked_news_count:,}")
    col5.metric("不重複公司（市場別）", f"{unique_company_count:,}")
    st.caption(
        "統計口徑：分析新聞先依相同文章網址或正規化後完全相同標題去重；"
        "「命中公司關鍵字的新聞」是至少命中一家公司名稱的新聞篇數；"
        "「不重複公司（市場別）」是去重後的市場＋公司配對數。"
        "今天與最近 7 天使用日期區間查詢；只有「資料庫最新新聞」選項限制為最新 500 筆。"
    )


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
        
        fig = px.bar(
            industry_counts.sort_values("新聞筆數", ascending=True),
            x="新聞筆數",
            y="產業主題",
            orientation="h",
            text="新聞筆數",
            labels={
                "新聞筆數": "新聞筆數",
                "產業主題": "產業主題",
            },
        )
        fig.update_layout(
            xaxis_title="新聞筆數",
            yaxis_title="",
            yaxis=dict(autorange="reversed"),
            height=420,
            margin=dict(l=20, r=20, t=20, b=20),
        )
        fig.update_traces(textposition="outside")
        st.plotly_chart(fig, use_container_width=True)
        
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

    st.subheader("二、產業影響路徑與後續觀察")
    st.caption(
        "以下內容由新聞關鍵字對應到產業分析框架，屬於待驗證的觀察方向，"
        "不是已確認的營運影響或股價預測。"
    )

    if industry_rows:
        impact_industries = (
            industry_df.groupby("產業主題")
            .size()
            .sort_values(ascending=False)
            .index.tolist()
        )
        for industry in impact_industries:
            guide = INDUSTRY_IMPACT_GUIDES.get(
                industry, INDUSTRY_IMPACT_GUIDES["其他市場新聞"]
            )
            with st.expander(f"{industry}｜影響路徑與觀察指標", expanded=(industry == impact_industries[0])):
                st.markdown(f"**可能的影響路徑**：{guide['impact']}")
                st.markdown(f"**後續觀察指標**：{guide['watch']}")
                st.markdown(f"**判讀限制**：{guide['caution']}")

                evidence_rows = industry_df[industry_df["產業主題"] == industry]
                st.write(f"目前關聯新聞：{len(evidence_rows)} 則")
                for _, evidence_row in evidence_rows.head(3).iterrows():
                    st.markdown(f"- **{evidence_row['新聞標題']}**（{evidence_row['市場']}｜{evidence_row['來源']}）")
    else:
        st.info("目前沒有足夠的產業新聞可供分析。")

    st.divider()

    # This trend is always calculated from the last 7 Taipei calendar days,
    # regardless of the page's current news-date filter.
    st.subheader("三、最近 7 天產業熱度變化")
    seven_day_start = today - pd.Timedelta(days=6)
    
    # 直接從資料庫查詢最近 7 天的新聞
    with st.spinner("正在載入最近 7 天的新聞資料…"):
        seven_day_news = load_news_for_date_range(
            seven_day_start,
            today,
        )
    # Use the same deduplication rule for the heat chart as the headline metrics.
    seven_day_news = deduplicate_news(
        [item for item in seven_day_news if news_day(item) is not None]
    )

    heat_rows = []
    for item in seven_day_news:
        day = news_day(item)
        for industry in classify_industries(item):
            heat_rows.append({
                "日期": day.isoformat(),
                "產業主題": industry,
                "新聞筆數": 1,
            })

    if heat_rows:
        heat_df = pd.DataFrame(heat_rows)
        heat_counts = (
            heat_df.groupby(["日期", "產業主題"], as_index=False)
            .size()
            .rename(columns={"size": "新聞筆數"})
        )
        # Include dates with no articles in the x-axis by setting a stable date range.
        date_axis = pd.date_range(
            start=seven_day_start, end=pd.Timestamp(today), freq="D"
        ).strftime("%Y-%m-%d").tolist()
        heat_fig = px.line(
            heat_counts,
            x="日期",
            y="新聞筆數",
            color="產業主題",
            markers=True,
            category_orders={"日期": date_axis},
            labels={"日期": "台灣日期", "新聞筆數": "新聞篇數", "產業主題": "產業主題"},
        )
        heat_fig.update_layout(
            height=420,
            xaxis=dict(categoryorder="array", categoryarray=date_axis),
            margin=dict(l=20, r=20, t=30, b=20),
            legend_title_text="產業主題",
        )
        st.plotly_chart(heat_fig, use_container_width=True)
        st.caption(
            f"統計區間：{seven_day_start:%Y-%m-%d} 至 {today:%Y-%m-%d}（台灣時間）。"
            "七天資料依相同網址／標題規則去重；分類可重疊，新聞量代表報導量，不代表股價方向。"
        )
        heat_table = heat_counts.pivot(
            index="產業主題", columns="日期", values="新聞筆數"
        ).fillna(0).astype(int)
        st.dataframe(heat_table, use_container_width=True)
    else:
        st.info("最近 7 天目前沒有可用的日期新聞資料。")

    st.divider()

    st.subheader("四、關聯個股新聞與公司摘要")
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

        # Company-level roll-up: aggregate today's (or currently selected range's)
        # matched articles, sentiment hints, and industry topics.
        company_news = [
            row for row in analyzed_rows
            if chosen_stock in row["關聯公司"].split("、")
        ]
        if company_news:
            positive_n = sum(row["初步判讀"] == "偏正面" for row in company_news)
            negative_n = sum(row["初步判讀"] == "偏負面" for row in company_news)
            neutral_n = len(company_news) - positive_n - negative_n
            topic_counts = {}
            for row in company_news:
                for topic in row["產業主題"].split("、"):
                    topic_counts[topic] = topic_counts.get(topic, 0) + 1
            main_topics = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)[:3]
            st.markdown(f"#### {chosen_stock}｜新聞彙整")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("相關新聞", f"{len(company_news):,}")
            m2.metric("偏正面", f"{positive_n:,}")
            m3.metric("偏負面", f"{negative_n:,}")
            m4.metric("中性／需確認", f"{neutral_n:,}")
            st.write("主要涉及主題：" + ("、".join(f"{topic}（{count}）" for topic, count in main_topics) or "未分類"))
            st.caption("以下列出命中公司關鍵字的原始新聞；摘要是規則式彙整，不是 AI 生成的投資結論。")

            st.markdown("##### 個股影響證據摘要")
            st.dataframe(
                pd.DataFrame([
                    {
                        "新聞標題": row["新聞標題"],
                        "市場": row["市場"],
                        "初步方向": row["初步判讀"],
                        "來源": row["來源"],
                    }
                    for row in company_news
                ]),
                use_container_width=True,
                hide_index=True,
            )

        for _, row in details.iterrows():
            with st.container(border=True):
                st.markdown(f"**{row['新聞標題']}**")
                st.caption(
                    f"{row['市場']}｜{row['發布時間']}｜"
                    f"來源：{row['來源']}"
                )
                st.write(f"初步判讀：{row['初步判讀']}")
                matching = [
                    keyword for keyword in STOCK_KEYWORDS.get(row["市場"], {}).get(chosen_stock, [])
                    if keyword.casefold() in (
                        row["新聞標題"] + " " + str(
                            next(
                                (item.get("summary") or "" for item in news
                                 if str(item.get("title") or "未提供標題") == row["新聞標題"]),
                                ""
                            )
                        )
                    ).casefold()
                ]
                if matching:
                    st.caption("公司關聯依據：" + "、".join(matching))
                matched_item = next(
                    (
                        item for item in news
                        if str(item.get("title") or "未提供標題") == row["新聞標題"]
                    ),
                    {},
                )
                impact_path, watch_items = company_impact_guidance(matched_item)
                st.markdown("**可能的影響路徑（待驗證）**")
                st.write(impact_path)
                st.markdown("**後續建議查證**")
                st.write(watch_items)
                pos_hits, neg_hits = sentiment_evidence(matched_item)
                if pos_hits or neg_hits:
                    st.caption(
                        "本則新聞命中的情緒字詞："
                        + (
                            "偏正面字詞：" + "、".join(pos_hits)
                            if pos_hits else "未命中偏正面字詞"
                        )
                        + "；"
                        + (
                            "偏負面字詞：" + "、".join(neg_hits)
                            if neg_hits else "未命中偏負面字詞"
                        )
                    )
                else:
                    st.caption("標題與摘要未命中明確正負面字詞，列為中性／需人工確認。")
                st.caption(
                    "注意：新聞提及公司不代表公司一定受惠或受害；"
                    "請以原文、公司公告及財報確認實際關聯。"
                )
                if row["原文連結"].startswith(("https://", "http://")):
                    st.markdown(f"[閱讀原文]({row['原文連結']})")
    else:
        st.info(
            "目前新聞沒有命中已設定的公司名稱關鍵字。"
            "這不代表沒有相關公司，只代表目前字典尚未辨識到。"
        )

    st.divider()

    st.subheader("五、利多／利空／中性初步判讀與依據")
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
                if row["positive_evidence"]:
                    st.write("正面判讀依據：" + "、".join(row["positive_evidence"]))
                if row["negative_evidence"]:
                    st.write("負面判讀依據：" + "、".join(row["negative_evidence"]))
                if not row["positive_evidence"] and not row["negative_evidence"]:
                    st.write("判讀依據：未命中明確正負面關鍵字，因此列為中性／需人工確認。")
                if row["summary"]:
                    st.write(row["summary"])
                if row["原文連結"].startswith(("https://", "http://")):
                    st.markdown(f"[閱讀原文]({row['原文連結']})")

except Exception as exc:
    st.error("產業與個股分析頁載入失敗。")
    st.code(f"{type(exc).__name__}: {str(exc)[:1000]}")
