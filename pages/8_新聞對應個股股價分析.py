"""
新聞對應個股股價分析（自動批次版）
放置位置：pages/8_新聞對應個股股價分析.py

自動讀取既有 public.analyses.related_stocks，
依新聞分組呈現關聯個股，並批次建立／更新股價回顧。
不修改既有新聞、AI 分析或 storage 程式。
"""

import json
import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import streamlit as st

try:
    import yfinance as yf
except ImportError:
    st.error("缺少 yfinance 套件。請確認 requirements.txt 已包含 yfinance。")
    st.stop()

try:
    from services.storage import _connection
except ImportError as exc:
    st.error("無法載入既有資料庫連線，請確認 services/storage.py 存在。")
    st.caption(str(exc))
    st.stop()


TAIPEI = ZoneInfo("Asia/Taipei")
BENCHMARK = "^TWII"
HORIZONS = (1, 3, 5)

st.set_page_config(
    page_title="新聞對應個股股價分析｜AI Market Radar",
    page_icon="📈",
    layout="wide",
)

st.title("📈 新聞對應個股股價分析")
st.caption(
    "以每則 AI 新聞分析為主，自動列出關聯股票並批次建立股價回顧。"
    "不需要逐則選新聞或逐檔選股票。"
)


def parse_json(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return []
    return value if value is not None else []


def to_taipei(value):
    if not value:
        return None
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TAIPEI)
        return dt.astimezone(TAIPEI)
    except (TypeError, ValueError, OverflowError):
        return None


def load_analyzed_news(limit=300):
    """以 source_url 對應原始新聞時間，只讀既有資料。"""
    with _connection() as conn:
        rows = conn.execute(
            """
            SELECT
                a.id::text AS analysis_id,
                a.headline,
                a.summary,
                a.industry,
                a.industry_impact,
                a.sentiment,
                a.sentiment_reason,
                a.sentiment_confidence,
                a.related_stocks,
                a.watch_items,
                a.source_url,
                a.created_at,
                n.published_at,
                n.market,
                n.source
            FROM public.analyses AS a
            LEFT JOIN LATERAL (
                SELECT published_at, market, source
                FROM public.news
                WHERE url = a.source_url
                ORDER BY published_at DESC NULLS LAST
                LIMIT 1
            ) AS n ON TRUE
            ORDER BY a.created_at DESC
            LIMIT %s
            """,
            (int(limit),),
        ).fetchall()
    return [dict(row) for row in rows]


def load_saved_reviews(limit=500):
    with _connection() as conn:
        rows = conn.execute(
            """
            SELECT
                e.id,
                e.analysis_id,
                e.headline,
                e.stock_name,
                e.ticker,
                e.expected_direction,
                e.published_at,
                e.baseline_date,
                e.baseline_close,
                COALESCE(
                    json_agg(
                        json_build_object(
                            'horizon_days', o.horizon_days,
                            'observation_date', o.observation_date,
                            'stock_close', o.stock_close,
                            'stock_return_pct', o.stock_return_pct,
                            'benchmark_return_pct', o.benchmark_return_pct,
                            'relative_return_pct', o.relative_return_pct,
                            'status', o.status
                        )
                    ) FILTER (WHERE o.id IS NOT NULL),
                    '[]'::json
                ) AS observations
            FROM public.stock_review_events e
            LEFT JOIN public.stock_review_observations o ON o.event_id = e.id
            GROUP BY e.id
            ORDER BY e.published_at DESC, e.created_at DESC
            LIMIT %s
            """,
            (int(limit),),
        ).fetchall()
    return [dict(row) for row in rows]


@st.cache_data(ttl=900, show_spinner=False)
def download_daily(ticker):
    """下載兩年日線，使用調整後收盤價，降低除權息／拆股造成的失真。"""
    raw = yf.download(
        ticker,
        period="2y",
        interval="1d",
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if raw is None or raw.empty or "Close" not in raw.columns:
        return pd.Series(dtype="float64")

    close = raw["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    close = pd.to_numeric(close, errors="coerce").dropna()
    if close.empty:
        return pd.Series(dtype="float64")

    idx = pd.to_datetime(close.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    close.index = idx.normalize()
    return close[~close.index.duplicated(keep="last")].sort_index()


def resolve_ticker(raw_ticker, market):
    """
    優先使用 AI 提供的完整 Yahoo ticker。
    若只有純數字代號，依台股市場依序測試 .TW / .TWO，只有有日線資料才採用。
    """
    raw = str(raw_ticker or "").strip().upper()
    if not raw or raw in {"待確認", "未知", "N/A", "NA", "NONE"}:
        return None, pd.Series(dtype="float64"), "AI 未提供可用股票代號"

    if raw.endswith((".TW", ".TWO")):
        series = download_daily(raw)
        if not series.empty:
            return raw, series, "使用 AI 提供的 Yahoo 代號"
        return None, series, f"Yahoo Finance 查無 {raw} 歷史資料"

    digits = re.sub(r"\D", "", raw)
    if digits and digits == raw and market == "TW":
        for suffix in (".TW", ".TWO"):
            candidate = digits + suffix
            series = download_daily(candidate)
            if not series.empty:
                return candidate, series, f"已自動確認代號為 {candidate}"
        return None, pd.Series(dtype="float64"), f"無法自動確認 {digits} 是上市或上櫃股票"

    return None, pd.Series(dtype="float64"), f"不支援或無法辨識的代號：{raw}"


def baseline_trading_date(published_at, trading_dates):
    """收盤後（13:30 起）發布的新聞，以之後第一個交易日為基準。"""
    dt = to_taipei(published_at)
    if dt is None:
        return None

    target = dt.date()
    if dt.time() >= time(13, 30):
        target += timedelta(days=1)

    candidates = [d for d in trading_dates if d.date() >= target]
    return candidates[0] if candidates else None


def save_review(analysis, stock, ticker, stock_prices, benchmark_prices):
    published_at = analysis.get("published_at")
    if not published_at:
        raise ValueError("找不到原始新聞發布時間，暫不建立回顧，避免基準日期錯誤。")

    base_date = baseline_trading_date(published_at, list(stock_prices.index))
    if base_date is None:
        raise ValueError("新聞發布後尚無可用的台股交易日資料。")

    base_close = float(stock_prices.loc[base_date])
    if base_close <= 0:
        raise ValueError("基準收盤價無效。")

    benchmark_base = (
        float(benchmark_prices.loc[base_date])
        if base_date in benchmark_prices.index else None
    )

    snapshot = {
        "headline": analysis.get("headline"),
        "summary": analysis.get("summary"),
        "industry": analysis.get("industry"),
        "sentiment": analysis.get("sentiment"),
        "sentiment_reason": analysis.get("sentiment_reason"),
        "sentiment_confidence": analysis.get("sentiment_confidence"),
        "related_stock": stock,
        "source_url": analysis.get("source_url"),
        "analysis_created_at": str(analysis.get("created_at")),
    }

    with _connection() as conn:
        event = conn.execute(
            """
            INSERT INTO public.stock_review_events (
                analysis_id, headline, source_url, published_at,
                stock_name, ticker, expected_direction,
                analysis_snapshot, baseline_date, baseline_close,
                benchmark_ticker, benchmark_baseline_close
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s)
            ON CONFLICT (analysis_id, ticker) DO UPDATE SET
                headline = EXCLUDED.headline,
                source_url = EXCLUDED.source_url,
                published_at = EXCLUDED.published_at,
                stock_name = EXCLUDED.stock_name,
                expected_direction = EXCLUDED.expected_direction,
                analysis_snapshot = EXCLUDED.analysis_snapshot,
                baseline_date = EXCLUDED.baseline_date,
                baseline_close = EXCLUDED.baseline_close,
                benchmark_ticker = EXCLUDED.benchmark_ticker,
                benchmark_baseline_close = EXCLUDED.benchmark_baseline_close,
                updated_at = now()
            RETURNING id
            """,
            (
                str(analysis["analysis_id"]),
                analysis.get("headline") or "",
                analysis.get("source_url"),
                published_at,
                stock.get("name") or stock.get("stock") or ticker,
                ticker,
                stock.get("impact_direction") or analysis.get("sentiment") or "未判定",
                json.dumps(snapshot, ensure_ascii=False, default=str),
                base_date.date(),
                base_close,
                BENCHMARK,
                benchmark_base,
            ),
        ).fetchone()
        event_id = event["id"]

        for horizon in HORIZONS:
            target_idx = stock_prices.index.get_loc(base_date) + horizon
            if target_idx >= len(stock_prices):
                conn.execute(
                    """
                    INSERT INTO public.stock_review_observations
                        (event_id, horizon_days, status)
                    VALUES (%s,%s,'待觀察')
                    ON CONFLICT (event_id, horizon_days) DO UPDATE SET
                        observation_date = NULL,
                        stock_close = NULL,
                        benchmark_close = NULL,
                        stock_return_pct = NULL,
                        benchmark_return_pct = NULL,
                        relative_return_pct = NULL,
                        status = '待觀察',
                        updated_at = now()
                    """,
                    (event_id, horizon),
                )
                continue

            obs_date = stock_prices.index[target_idx]
            stock_close = float(stock_prices.iloc[target_idx])
            stock_return = (stock_close / base_close - 1) * 100

            benchmark_close = (
                float(benchmark_prices.loc[obs_date])
                if obs_date in benchmark_prices.index else None
            )
            benchmark_return = (
                (benchmark_close / benchmark_base - 1) * 100
                if benchmark_close is not None
                and benchmark_base is not None
                and benchmark_base > 0
                else None
            )
            relative_return = (
                stock_return - benchmark_return
                if benchmark_return is not None else None
            )
            status = "完成" if relative_return is not None else "個股完成／大盤資料不足"

            conn.execute(
                """
                INSERT INTO public.stock_review_observations (
                    event_id, horizon_days, observation_date,
                    stock_close, benchmark_close,
                    stock_return_pct, benchmark_return_pct,
                    relative_return_pct, status, updated_at
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                ON CONFLICT (event_id, horizon_days) DO UPDATE SET
                    observation_date = EXCLUDED.observation_date,
                    stock_close = EXCLUDED.stock_close,
                    benchmark_close = EXCLUDED.benchmark_close,
                    stock_return_pct = EXCLUDED.stock_return_pct,
                    benchmark_return_pct = EXCLUDED.benchmark_return_pct,
                    relative_return_pct = EXCLUDED.relative_return_pct,
                    status = EXCLUDED.status,
                    updated_at = now()
                """,
                (
                    event_id, horizon, obs_date.date(),
                    stock_close, benchmark_close,
                    stock_return, benchmark_return,
                    relative_return, status,
                ),
            )

    return event_id, base_date.date()


def get_related_stocks(analysis):
    items = parse_json(analysis.get("related_stocks"))
    if not isinstance(items, list):
        return []
    return [x for x in items if isinstance(x, dict)]


# Check the dedicated tables only; no DDL is executed by this page.
try:
    with _connection() as conn:
        conn.execute("SELECT 1 FROM public.stock_review_events LIMIT 1")
        conn.execute("SELECT 1 FROM public.stock_review_observations LIMIT 1")
except Exception as exc:
    st.warning("股價回顧專用資料表尚未建立，請先執行 ZIP 內的 stock_review_migration.sql。")
    st.code("stock_review_events\nstock_review_observations", language="text")
    st.caption(f"資料庫訊息：{str(exc).splitlines()[0][:300]}")
    st.stop()

try:
    analyses = load_analyzed_news(limit=300)
except Exception as exc:
    st.error("讀取既有 AI 新聞分析失敗。")
    st.caption(f"{type(exc).__name__}: {str(exc)[:300]}")
    st.stop()

# 第一階段只做台股；只使用 AI 明確標示 TW 或原始新聞市場為 TW 的分析。
tw_analyses = [
    a for a in analyses
    if str(a.get("market") or "").upper() == "TW"
]
if not tw_analyses:
    st.info("目前沒有可供回顧的台股 AI 新聞分析。")
    st.stop()

news_with_stocks = []
for analysis in tw_analyses:
    stocks = get_related_stocks(analysis)
    if stocks:
        news_with_stocks.append((analysis, stocks))

total_stocks = sum(len(stocks) for _, stocks in news_with_stocks)
st.caption(
    f"目前讀取 {len(tw_analyses)} 則台股 AI 分析；"
    f"其中 {len(news_with_stocks)} 則有關聯個股，共 {total_stocks} 個股票關聯。"
)

col1, col2 = st.columns([3, 1])
with col1:
    st.write("系統會依 AI 分析中的 `related_stocks` 自動配對股票代號；純數字代號會自動測試上市 `.TW` 與上櫃 `.TWO`。")
with col2:
    run_batch = st.button(
        "⚡ 批次建立／更新股價分析",
        type="primary",
        use_container_width=True,
        disabled=not news_with_stocks,
    )

if run_batch:
    try:
        with st.spinner("正在下載台股與加權指數歷史資料，並建立所有可辨識股票的回顧…"):
            benchmark_prices = download_daily(BENCHMARK)
            if benchmark_prices.empty:
                raise RuntimeError("Yahoo Finance 暫時無法取得台灣加權指數 ^TWII。")

            done, skipped, errors = 0, 0, []
            for analysis, stocks in news_with_stocks:
                for stock in stocks:
                    raw_ticker = (
                        stock.get("ticker")
                        or stock.get("symbol")
                        or stock.get("stock_code")
                        or stock.get("code")
                    )
                    ticker, prices, note = resolve_ticker(raw_ticker, "TW")
                    if not ticker:
                        skipped += 1
                        errors.append(
                            f"{analysis.get('headline','未命名新聞')[:45]}｜"
                            f"{stock.get('name') or stock.get('stock') or '未命名股票'}：{note}"
                        )
                        continue
                    try:
                        save_review(analysis, stock, ticker, prices, benchmark_prices)
                        done += 1
                    except Exception as exc:
                        errors.append(
                            f"{analysis.get('headline','未命名新聞')[:45]}｜{ticker}："
                            f"{type(exc).__name__}: {str(exc)[:160]}"
                        )

        st.success(f"批次處理完成：成功建立／更新 {done} 檔股票回顧。")
        if skipped:
            st.warning(f"有 {skipped} 檔股票無法自動確認代號，已略過，沒有猜測代號。")
        if errors:
            with st.expander(f"查看略過或失敗項目（{len(errors)}）"):
                for message in errors:
                    st.write(f"- {message}")
    except Exception as exc:
        st.error("批次處理失敗。")
        st.caption(f"{type(exc).__name__}: {str(exc)[:400]}")

st.subheader("一、新聞與關聯個股")
if not news_with_stocks:
    st.info("目前 AI 分析尚未辨識出有明確關聯的台股。")
else:
    for analysis, stocks in news_with_stocks:
        title = analysis.get("headline") or "未命名新聞"
        with st.expander(f"{title}（{len(stocks)} 檔關聯股票）", expanded=False):
            dt = to_taipei(analysis.get("published_at"))
            st.caption(
                f"新聞日期：{dt:%Y-%m-%d %H:%M}" if dt
                else "新聞發布時間：資料庫未能對應原始新聞"
            )
            st.write(analysis.get("summary") or "")
            if analysis.get("source_url"):
                st.markdown(f"[閱讀原始新聞]({analysis['source_url']})")
            for stock in stocks:
                name = stock.get("name") or stock.get("stock") or "未命名股票"
                ticker = stock.get("ticker") or stock.get("symbol") or "待確認"
                direction = stock.get("impact_direction") or "未判定"
                reason = stock.get("reason") or ""
                st.markdown(f"**{name}｜{ticker}｜{direction}**")
                if reason:
                    st.caption(reason)

st.subheader("二、股價回顧結果")
try:
    reviews = load_saved_reviews(limit=500)
except Exception as exc:
    st.error("讀取股價回顧紀錄失敗。")
    st.caption(f"{type(exc).__name__}: {str(exc)[:300]}")
    reviews = []

if not reviews:
    st.info("尚未建立回顧結果。按上方「批次建立／更新股價分析」即可一次處理所有可辨識股票。")
else:
    table_rows = []
    for event in reviews:
        observations = parse_json(event.get("observations"))
        by_horizon = {
            int(o["horizon_days"]): o
            for o in observations
            if isinstance(o, dict) and o.get("horizon_days") is not None
        }
        row = {
            "新聞": event.get("headline"),
            "個股": event.get("stock_name"),
            "代號": event.get("ticker"),
            "AI 方向": event.get("expected_direction"),
            "基準日": str(event.get("baseline_date") or ""),
            "基準收盤": event.get("baseline_close"),
        }
        for horizon in HORIZONS:
            obs = by_horizon.get(horizon, {})
            row[f"T+{horizon} 日期"] = str(obs.get("observation_date") or "待觀察")
            row[f"T+{horizon} 個股報酬%"] = obs.get("stock_return_pct")
            row[f"T+{horizon} 相對大盤%"] = obs.get("relative_return_pct")
            row[f"T+{horizon} 狀態"] = obs.get("status") or "待觀察"
        table_rows.append(row)

    result_df = pd.DataFrame(table_rows)
    st.dataframe(result_df, use_container_width=True, hide_index=True)

    chart_source = []
    for event in reviews:
        observations = parse_json(event.get("observations"))
        for obs in observations:
            if isinstance(obs, dict) and obs.get("stock_return_pct") is not None:
                chart_source.append({
                    "股票": event.get("stock_name"),
                    "觀察期間": f"T+{obs.get('horizon_days')}",
                    "個股報酬率（%）": obs.get("stock_return_pct"),
                    "相對大盤報酬（%）": obs.get("relative_return_pct"),
                })
    if chart_source:
        chart_df = pd.DataFrame(chart_source)
        with st.expander("查看個股報酬比較圖"):
            fig = px.bar(
                chart_df,
                x="股票",
                y="個股報酬率（%）",
                color="觀察期間",
                barmode="group",
                hover_data=["相對大盤報酬（%）"],
            )
            fig.add_hline(y=0, line_dash="dash", line_color="gray")
            st.plotly_chart(fig, use_container_width=True)

st.divider()
with st.expander("計算方式與限制"):
    st.markdown(
        """
        - 第一階段僅處理台股新聞，並依既有 AI 分析的 `related_stocks` 建立關聯。
        - 只採用 AI 明確提供且可由 Yahoo Finance 驗證的股票代號；純數字代號會測試 `.TW` 與 `.TWO`，無法確認則略過，不猜代號。
        - 新聞於台灣時間 13:30（含）後發布，基準日從下一個有效交易日開始；其他時間以發布當日或之後第一個有效交易日為基準。
        - T+1／T+3／T+5 是基準交易日之後第 1／3／5 個有效交易日。
        - 個股報酬使用 Yahoo Finance 調整後收盤價；相對大盤報酬 = 個股報酬 − 台灣加權指數同期報酬。
        - 新聞與 AI 分析原始資料只讀取；新回顧結果只寫入專用資料表。
        - 相對報酬是市場比較，不代表新聞造成股價變動，也不構成投資建議。
        """
    )
