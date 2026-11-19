"""
全球股市指數週報
放置位置：pages/5_全球股市指數週報.py

資料來源：Yahoo Finance（yfinance）
注意：Yahoo Finance 資料可能延遲、缺漏或調整；畫面會標示各指數最後一筆資料日期。
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import streamlit as st

try:
    import yfinance as yf
except ImportError:
    st.error("缺少 yfinance 套件。請在 requirements.txt 新增一行：yfinance")
    st.stop()


TAIPEI_TZ = ZoneInfo("Asia/Taipei")

st.set_page_config(
    page_title="全球股市指數週報｜AI Market Radar",
    page_icon="🌏",
    layout="wide",
)

st.title("🌏 全球股市指數週報")
st.caption(
    "追蹤美國、日本、韓國、香港與中國上海市場主要指數。"
    "資料來源為 Yahoo Finance，指數資料以來源實際更新時間為準。"
)

# Yahoo Finance 指數代號
MARKETS = {
    "🇺🇸 美國": {
        "道瓊工業指數": "^DJI",
        "S&P 500": "^GSPC",
        "NASDAQ 綜合指數": "^IXIC",
        "NASDAQ 100": "^NDX",
        "羅素 2000": "^RUT",
        "費城半導體指數（費半）": "^SOX",
    },
    "🇯🇵 日本": {
        "日經 225": "^N225",
        "TOPIX": "^TOPX",
    },
    "🇰🇷 韓國": {
        "KOSPI": "^KS11",
        "KOSDAQ": "^KQ11",
    },
    "🇭🇰 香港": {
        "恒生指數": "^HSI",
        "恒生科技指數": "^HSTECH",
    },
    "🇨🇳 上海／深圳": {
        "上證綜合指數": "000001.SS",
        "深證成指": "399001.SZ",
    },
}

ALL_TICKERS = {
    ticker: (market, name)
    for market, indices in MARKETS.items()
    for name, ticker in indices.items()
}


@st.cache_data(ttl=900, show_spinner=False)
def load_index_history(tickers, period="1mo"):
    """批次下載指數日線；回傳每個 ticker 的收盤價序列。"""
    raw = yf.download(
        tickers=list(tickers),
        period=period,
        interval="1d",
        auto_adjust=False,
        progress=False,
        group_by="ticker",
        threads=True,
    )

    result = {}
    if raw is None or raw.empty:
        return result

    for ticker in tickers:
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                if ticker not in raw.columns.get_level_values(0):
                    continue
                close = raw[ticker]["Close"]
            else:
                # 單一代號時，yfinance 可能回傳一般欄位
                close = raw["Close"]

            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]

            close = pd.to_numeric(close, errors="coerce").dropna()
            if not close.empty:
                close.index = pd.to_datetime(close.index).tz_localize(None)
                result[ticker] = close
        except (KeyError, TypeError, ValueError):
            continue

    return result


def format_number(value):
    return f"{value:,.2f}" if pd.notna(value) else "—"


def format_pct(value):
    return f"{value:+.2f}%" if pd.notna(value) else "—"


def build_summary(history):
    rows = []
    for ticker, (market, name) in ALL_TICKERS.items():
        series = history.get(ticker)
        if series is None or len(series) == 0:
            rows.append({
                "市場": market,
                "指數": name,
                "代號": ticker,
                "最新收盤": None,
                "漲跌點數": None,
                "漲跌幅": None,
                "資料日期": "無資料",
                "_date": None,
            })
            continue

        latest = float(series.iloc[-1])
        previous = float(series.iloc[-2]) if len(series) >= 2 else None
        change = latest - previous if previous is not None else None
        change_pct = (change / previous * 100) if previous not in (None, 0) else None
        latest_date = pd.Timestamp(series.index[-1]).date()

        rows.append({
            "市場": market,
            "指數": name,
            "代號": ticker,
            "最新收盤": latest,
            "漲跌點數": change,
            "漲跌幅": change_pct,
            "資料日期": latest_date.strftime("%Y-%m-%d"),
            "_date": latest_date,
        })

    return pd.DataFrame(rows)


# 頁面控制
left, right = st.columns([3, 1])
with left:
    period_label = st.selectbox(
        "走勢區間",
        ["最近 7 個日曆日", "最近 7 個交易日"],
        index=0,
    )
with right:
    refresh = st.button("🔄 重新整理資料", use_container_width=True)

if refresh:
    load_index_history.clear()

now_taipei = datetime.now(TAIPEI_TZ)
st.caption(f"頁面查詢時間：{now_taipei.strftime('%Y-%m-%d %H:%M')}（台灣時間）")

with st.spinner("正在向 Yahoo Finance 取得全球指數資料…"):
    history = load_index_history(tuple(ALL_TICKERS.keys()))

if not history:
    st.error(
        "目前無法取得指數資料。可能是 Yahoo Finance 暫時無回應，"
        "請稍後按「重新整理資料」再試。"
    )
    st.stop()

summary = build_summary(history)

# 摘要總覽
st.subheader("一、各市場最新收盤")
st.caption(
    "漲跌幅以該指數最近兩筆有效日線收盤價計算；"
    "不同市場的最後交易日期可能不同。"
)

display = summary.drop(columns=["_date"]).copy()
display["最新收盤"] = display["最新收盤"].map(format_number)
display["漲跌點數"] = display["漲跌點數"].map(
    lambda x: f"{x:+,.2f}" if pd.notna(x) else "—"
)
display["漲跌幅"] = display["漲跌幅"].map(format_pct)

st.dataframe(
    display,
    use_container_width=True,
    hide_index=True,
    column_config={
        "市場": st.column_config.TextColumn("市場", width="small"),
        "指數": st.column_config.TextColumn("指數", width="medium"),
        "代號": st.column_config.TextColumn("Yahoo 代號", width="small"),
        "最新收盤": st.column_config.TextColumn("最新收盤", width="small"),
        "漲跌點數": st.column_config.TextColumn("漲跌點數", width="small"),
        "漲跌幅": st.column_config.TextColumn("漲跌幅", width="small"),
        "資料日期": st.column_config.TextColumn("最後交易日", width="small"),
    },
)

# 市場漲跌排行
st.subheader("二、各指數漲跌幅")
rank = summary.dropna(subset=["漲跌幅"]).sort_values("漲跌幅", ascending=True)
if rank.empty:
    st.info("目前沒有足夠的前一交易日資料可計算漲跌幅。")
else:
    fig_rank = px.bar(
        rank,
        x="漲跌幅",
        y="指數",
        color="市場",
        orientation="h",
        hover_data=["資料日期", "最新收盤", "漲跌點數", "代號"],
        labels={"漲跌幅": "漲跌幅（%）", "指數": ""},
    )
    fig_rank.add_vline(x=0, line_dash="dash", line_color="gray")
    fig_rank.update_layout(height=max(420, len(rank) * 30), legend_title_text="市場")
    st.plotly_chart(fig_rank, use_container_width=True)

# 走勢圖
st.subheader("三、近一週指數走勢")
if period_label == "最近 7 個日曆日":
    cutoff = pd.Timestamp((now_taipei - timedelta(days=7)).date())
else:
    # 每個指數各自顯示最近七筆有效交易日
    cutoff = None

for market, indices in MARKETS.items():
    with st.expander(market, expanded=(market == "🇺🇸 美國")):
        chart_rows = []
        for name, ticker in indices.items():
            series = history.get(ticker)
            if series is None or series.empty:
                st.warning(f"{name}（{ticker}）：Yahoo Finance 目前沒有回傳資料。")
                continue

            selected = series.tail(7) if cutoff is None else series[series.index >= cutoff]
            if selected.empty:
                # 若最近七個日曆日沒有資料，仍顯示最新有效交易資料並清楚標示日期
                selected = series.tail(1)

            base = float(selected.iloc[0])
            if base == 0:
                continue

            for dt, close in selected.items():
                chart_rows.append({
                    "日期": pd.Timestamp(dt).strftime("%m-%d"),
                    "指數": name,
                    "相對區間起點變化（%）": (float(close) / base - 1) * 100,
                    "收盤點位": float(close),
                })

        if chart_rows:
            chart_df = pd.DataFrame(chart_rows)
            fig = px.line(
                chart_df,
                x="日期",
                y="相對區間起點變化（%）",
                color="指數",
                markers=True,
                hover_data={"收盤點位": ":,.2f"},
                labels={"相對區間起點變化（%）": "相對區間起點（%）"},
            )
            fig.add_hline(y=0, line_dash="dash", line_color="gray")
            fig.update_layout(height=380, legend_title_text="指數")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("此市場目前沒有可顯示的走勢資料。")

# 資料來源與限制
st.divider()
with st.expander("資料來源與使用說明"):
    st.markdown(
        """
        - 資料來源：Yahoo Finance，透過 `yfinance` 取得日線資料。
        - 美國指數包含道瓊、S&P 500、NASDAQ 綜合、NASDAQ 100、羅素 2000，以及**費城半導體指數（費半，^SOX）**。
        - 美國市場以 Yahoo Finance 最新回傳的日線為準；美股通常在台灣時間清晨收盤，但資料供應端可能延遲，請以「最後交易日」欄位確認是否已更新。
        - 週末、國定假日及市場休市日不會產生虛構資料。
        - 不同市場交易時間不同，因此各指數的最後交易日期可能不一致。
        - Yahoo Finance 為第三方資料來源，可能出現延遲、缺漏或代號暫時無法查詢的情況。
        - 走勢圖以區間第一筆收盤價換算為 0% 基準，方便比較不同點位規模的指數。
        """
    )
