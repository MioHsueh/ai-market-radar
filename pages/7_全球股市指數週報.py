"""
全球股市指數週報
放置位置：pages/5_全球股市指數週報.py

資料來源：Yahoo Finance（yfinance）
走勢區間：最近 14 個日曆日
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

try:
    import yfinance as yf
except ImportError:
    st.error("缺少 yfinance 套件。請在 requirements.txt 新增：yfinance")
    st.stop()


TAIPEI_TZ = ZoneInfo("Asia/Taipei")
LOOKBACK_DAYS = 14

st.set_page_config(
    page_title="全球股市指數週報｜AI Market Radar",
    page_icon="🌏",
    layout="wide",
)

st.title("🌏 全球股市指數週報")
st.caption(
    "追蹤美國、日本、韓國、香港與中國主要指數，"
    "顯示最新收盤及最近 14 個日曆日走勢。"
)

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


def _extract_close(raw: pd.DataFrame, ticker: str):
    """兼容 yfinance 不同版本的 MultiIndex 欄位順序。"""
    if raw is None or raw.empty:
        return None

    if not isinstance(raw.columns, pd.MultiIndex):
        if len(ALL_TICKERS) == 1 and "Close" in raw.columns:
            return raw["Close"]
        return None

    # 不假設 MultiIndex 是 (Ticker, Price) 或 (Price, Ticker)。
    matches = []
    for col in raw.columns:
        parts = [str(part) for part in (col if isinstance(col, tuple) else (col,))]
        if ticker in parts and "Close" in parts:
            matches.append(col)

    if not matches:
        return None

    close = raw[matches[0]]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    return close


@st.cache_data(ttl=900, show_spinner=False)
def load_index_history(tickers):
    """批次下載近一個月資料，供最近 14 個日曆日圖表使用。"""
    raw = yf.download(
        tickers=list(tickers),
        period="1mo",
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
            close = _extract_close(raw, ticker)
            if close is None:
                continue

            close = pd.to_numeric(close, errors="coerce").dropna()
            if close.empty:
                continue

            index = pd.to_datetime(close.index)
            # 移除時區，保留交易日期；日線日期以交易所交易日為準。
            if getattr(index, "tz", None) is not None:
                index = index.tz_localize(None)
            close.index = index
            close = close[~close.index.duplicated(keep="last")].sort_index()
            result[ticker] = close
        except (KeyError, TypeError, ValueError, AttributeError):
            continue

    return result


def fmt_number(value):
    return f"{value:,.2f}" if pd.notna(value) else "—"


def fmt_pct(value):
    return f"{value:+.2f}%" if pd.notna(value) else "—"


def build_summary(history):
    rows = []
    for ticker, (market, name) in ALL_TICKERS.items():
        series = history.get(ticker)
        if series is None or series.empty:
            rows.append({
                "市場": market, "指數": name, "Yahoo 代號": ticker,
                "最新收盤": None, "漲跌點數": None, "漲跌幅": None,
                "最後交易日": "無資料",
            })
            continue

        latest = float(series.iloc[-1])
        previous = float(series.iloc[-2]) if len(series) >= 2 else None
        change = latest - previous if previous is not None else None
        change_pct = (
            change / previous * 100
            if previous not in (None, 0) else None
        )
        rows.append({
            "市場": market,
            "指數": name,
            "Yahoo 代號": ticker,
            "最新收盤": latest,
            "漲跌點數": change,
            "漲跌幅": change_pct,
            "最後交易日": pd.Timestamp(series.index[-1]).strftime("%Y-%m-%d"),
        })
    return pd.DataFrame(rows)


# 控制列
c1, c2 = st.columns([3, 1])
with c1:
    st.info("走勢區間固定為最近 14 個日曆日（休市日不補值）。")
with c2:
    refresh = st.button("🔄 重新整理資料", use_container_width=True)

if refresh:
    load_index_history.clear()

now_taipei = datetime.now(TAIPEI_TZ)
st.caption(f"查詢時間：{now_taipei:%Y-%m-%d %H:%M}（台灣時間）")

with st.spinner("正在向 Yahoo Finance 取得全球指數資料…"):
    history = load_index_history(tuple(ALL_TICKERS.keys()))

if not history:
    st.error(
        "目前無法取得指數資料。請確認網路及 yfinance 套件，"
        "或稍後按「重新整理資料」再試。"
    )
    st.stop()

summary = build_summary(history)

st.subheader("一、各市場最新收盤")
st.caption(
    "漲跌幅以該指數最近兩筆有效日線收盤價計算；"
    "各市場最後交易日期可能不同。"
)

display = summary.copy()
display["最新收盤"] = display["最新收盤"].map(fmt_number)
display["漲跌點數"] = display["漲跌點數"].map(
    lambda x: f"{x:+,.2f}" if pd.notna(x) else "—"
)
display["漲跌幅"] = display["漲跌幅"].map(fmt_pct)
st.dataframe(display, use_container_width=True, hide_index=True)

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
        hover_data=["最後交易日", "最新收盤", "漲跌點數", "Yahoo 代號"],
        labels={"漲跌幅": "漲跌幅（%）", "指數": ""},
    )
    fig_rank.add_vline(x=0, line_dash="dash", line_color="gray")
    fig_rank.update_layout(
        height=max(420, len(rank) * 30),
        legend_title_text="市場",
    )
    st.plotly_chart(fig_rank, use_container_width=True)

st.subheader("三、最近 14 天指數走勢")
cutoff = pd.Timestamp((now_taipei - timedelta(days=LOOKBACK_DAYS)).date())

for market, indices in MARKETS.items():
    with st.expander(market, expanded=(market == "🇺🇸 美國")):
        fig = go.Figure()
        plotted = 0

        for name, ticker in indices.items():
            series = history.get(ticker)
            if series is None or series.empty:
                st.warning(f"{name}（{ticker}）：Yahoo Finance 目前沒有回傳資料。")
                continue

            selected = series.loc[series.index >= cutoff].copy()
            if selected.empty:
                st.warning(f"{name}（{ticker}）：最近 14 個日曆日沒有有效交易資料。")
                continue

            base = float(selected.iloc[0])
            if base == 0:
                continue

            change_series = (selected / base - 1) * 100
            fig.add_trace(go.Scatter(
                x=pd.to_datetime(change_series.index),
                y=change_series.values,
                mode="lines+markers",
                name=name,
                connectgaps=False,
                customdata=selected.values,
                hovertemplate=(
                    "%{x|%Y-%m-%d}<br>"
                    "區間漲跌：%{y:.2f}%<br>"
                    "收盤點位：%{customdata:,.2f}"
                    "<extra>%{fullData.name}</extra>"
                ),
            ))
            plotted += 1

        if plotted:
            fig.add_hline(y=0, line_dash="dash", line_color="gray")
            fig.update_layout(
                height=430,
                xaxis_title="交易日期",
                yaxis_title="相對區間第一筆收盤（%）",
                legend_title_text="指數",
                hovermode="x unified",
                margin=dict(l=20, r=20, t=25, b=20),
            )
            fig.update_xaxes(type="date", tickformat="%m-%d", tickangle=0)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("此市場最近 14 天沒有可顯示的走勢資料。")

st.divider()
with st.expander("資料來源與使用說明"):
    st.markdown(
        """
        - 資料來源：Yahoo Finance，透過 `yfinance` 取得日線資料。
        - 美國指數包含道瓊、S&P 500、NASDAQ 綜合、NASDAQ 100、羅素 2000，以及費城半導體指數（費半，`^SOX`）。
        - 美國資料以 Yahoo Finance 最新回傳的日線為準；台灣時間清晨收盤後通常會更新，但供應端可能延遲，請以最後交易日確認。
        - 最近 14 天指日曆日；週末、國定假日及休市日不補造資料。
        - 不同市場交易時間不同，因此最後交易日期可能不一致。
        - Yahoo Finance 是第三方來源，可能出現延遲、缺漏或指數代號暫時無法查詢。
        - 走勢圖以各指數在所選區間內的第一筆有效收盤價設為 0%，呈現區間累積變化，方便比較不同點位規模的指數。
        """
    )
