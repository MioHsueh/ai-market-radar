"""
新聞分析與股價回顧（獨立頁面）
放置位置：pages/8_新聞分析與股價回顧.py

只讀取 public.analyses / public.news，回顧資料寫入獨立的
public.stock_review_events / public.stock_review_observations。
不修改既有 storage.py、AI 分析流程或既有資料表。
"""

import json
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

try:
    import yfinance as yf
except ImportError:
    st.error("缺少 yfinance 套件。請確認 requirements.txt 已有 yfinance（全球股市指數頁已使用此套件）。")
    st.stop()

try:
    from services.storage import _connection
except ImportError as exc:
    st.error("無法載入既有資料庫連線。請確認 services/storage.py 存在。")
    st.caption(str(exc))
    st.stop()


TAIPEI = ZoneInfo("Asia/Taipei")
HORIZONS = (1, 3, 5)
BENCHMARK = "^TWII"

st.set_page_config(
    page_title="新聞分析與股價回顧｜AI Market Radar",
    page_icon="📈",
    layout="wide",
)

st.title("📈 新聞分析與股價回顧")
st.caption(
    "獨立功能頁：讀取既有 AI 新聞分析，將台股回顧事件與股價觀察結果"
    "保存至專用資料表，不修改原始新聞或 AI 分析。"
)


def _json_value(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return []
    return value if value is not None else []


def _as_taipei_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI)
    return dt.astimezone(TAIPEI)


def _load_analyses(limit=300):
    """以唯讀查詢讀取 AI 分析，並以 source_url 對應原始新聞發布時間。"""
    with _connection() as conn:
        rows = conn.execute(
            """
            SELECT
                a.id::text AS analysis_id,
                a.headline,
                a.summary,
                a.industry_impact,
                a.related_stocks,
                a.watch_items,
                a.source_url,
                a.created_at,
                n.published_at,
                n.market
            FROM public.analyses AS a
            LEFT JOIN LATERAL (
                SELECT published_at, market
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


def _load_events(limit=200):
    with _connection() as conn:
        rows = conn.execute(
            """
            SELECT
                e.id, e.analysis_id, e.headline, e.stock_name, e.ticker,
                e.expected_direction, e.published_at, e.baseline_date,
                e.baseline_close, e.created_at,
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
            FROM public.stock_review_events AS e
            LEFT JOIN public.stock_review_observations AS o
                ON o.event_id = e.id
            GROUP BY e.id
            ORDER BY e.created_at DESC
            LIMIT %s
            """,
            (int(limit),),
        ).fetchall()
    return [dict(row) for row in rows]


@st.cache_data(ttl=900, show_spinner=False)
def _download_daily(ticker, period="6mo"):
    data = yf.download(
        ticker,
        period=period,
        interval="1d",
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    if data is None or data.empty or "Close" not in data.columns:
        return pd.Series(dtype="float64")

    close = data["Close"]
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


def _baseline_date(published_at, trading_dates):
    """盤中或盤前新聞使用當日收盤；台股收盤後發布則從下一交易日開始。"""
    if not trading_dates:
        return None
    published = _as_taipei_datetime(published_at)
    if published is None:
        target = datetime.now(TAIPEI).date()
    else:
        target = published.date()
        if published.time() >= time(13, 30):
            target = target + timedelta(days=1)

    candidates = [d for d in trading_dates if d.date() >= target]
    return candidates[0] if candidates else None


def _direction(stock):
    if not isinstance(stock, dict):
        return "未判定"
    return str(
        stock.get("impact_direction")
        or stock.get("direction")
        or stock.get("sentiment")
        or "未判定"
    )


def _save_event_and_observations(analysis, stock_name, ticker, stock_series, benchmark_series):
    published_at = analysis.get("published_at")
    if not published_at:
        raise ValueError("找不到原始新聞發布時間，無法可靠設定回顧起點。")

    base_date = _baseline_date(published_at, list(stock_series.index))
    if base_date is None:
        raise ValueError("Yahoo Finance 尚未提供新聞事件後可用的台股交易日資料。")

    base_stock = float(stock_series.loc[base_date])
    benchmark_base = (
        float(benchmark_series.loc[base_date])
        if base_date in benchmark_series.index else None
    )
    if base_stock <= 0:
        raise ValueError("基準收盤價無效。")

    snapshot = {
        "headline": analysis.get("headline"),
        "summary": analysis.get("summary"),
        "industry_impact": analysis.get("industry_impact"),
        "related_stocks": analysis.get("related_stocks"),
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
                stock_name = EXCLUDED.stock_name,
                expected_direction = EXCLUDED.expected_direction,
                analysis_snapshot = EXCLUDED.analysis_snapshot,
                baseline_date = EXCLUDED.baseline_date,
                baseline_close = EXCLUDED.baseline_close,
                benchmark_ticker = EXCLUDED.benchmark_ticker,
                benchmark_baseline_close = EXCLUDED.benchmark_baseline_close
            RETURNING id
            """,
            (
                str(analysis["analysis_id"]),
                analysis.get("headline") or "",
                analysis.get("source_url"),
                published_at,
                stock_name,
                ticker,
                st.session_state.get("review_direction", "未判定"),
                json.dumps(snapshot, ensure_ascii=False, default=str),
                base_date.date(),
                base_stock,
                BENCHMARK,
                benchmark_base,
            ),
        ).fetchone()
        event_id = event["id"]

        for horizon in HORIZONS:
            # T+1/T+3/T+5：基準交易日之後第 N 個交易日。
            target_index = stock_series.index.get_loc(base_date) + horizon
            if target_index >= len(stock_series):
                conn.execute(
                    """
                    INSERT INTO public.stock_review_observations
                        (event_id, horizon_days, status)
                    VALUES (%s,%s,'待觀察')
                    ON CONFLICT (event_id, horizon_days) DO UPDATE SET
                        status = '待觀察',
                        observation_date = NULL,
                        stock_close = NULL,
                        benchmark_close = NULL,
                        stock_return_pct = NULL,
                        benchmark_return_pct = NULL,
                        relative_return_pct = NULL,
                        updated_at = now()
                    """,
                    (event_id, horizon),
                )
                continue

            obs_date = stock_series.index[target_index]
            stock_close = float(stock_series.iloc[target_index])
            stock_return = (stock_close / base_stock - 1) * 100

            benchmark_close = (
                float(benchmark_series.loc[obs_date])
                if obs_date in benchmark_series.index else None
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
    return event_id, base_date.date(), base_stock


# 檢查專用資料表是否已建立
try:
    with _connection() as conn:
        conn.execute("SELECT 1 FROM public.stock_review_events LIMIT 1")
        conn.execute("SELECT 1 FROM public.stock_review_observations LIMIT 1")
    tables_ready = True
except Exception as exc:
    tables_ready = False
    table_error = str(exc).splitlines()[0][:300]

if not tables_ready:
    st.warning("股價回顧專用資料表尚未建立。這是獨立資料表，不會修改原本的 news 或 analyses。")
    st.code("請先在 Supabase SQL Editor 執行隨附的 stock_review_migration.sql。", language="text")
    st.caption(f"資料庫回應：{table_error}")
    st.stop()

tab_new, tab_history = st.tabs(["建立新聞回顧", "回顧紀錄"])

with tab_new:
    try:
        analyses = _load_analyses(limit=300)
    except Exception as exc:
        st.error("讀取既有 AI 分析失敗。")
        st.caption(f"{type(exc).__name__}: {str(exc)[:300]}")
        st.stop()

    # 第一階段只處理台股新聞分析；無市場資料時不擅自推定。
    analyses = [
        a for a in analyses
        if str(a.get("market") or "").upper() in ("TW", "")
    ]

    if not analyses:
        st.info("目前沒有可供回顧的 AI 分析紀錄。請先完成既有新聞 AI 分析。")
    else:
        options = [
            f"{a.get('created_at')}｜{(a.get('headline') or '未命名分析')[:100]}"
            for a in analyses
        ]
        selected_index = st.selectbox(
            "選擇要回顧的新聞分析",
            range(len(analyses)),
            format_func=lambda i: options[i],
        )
        selected = analyses[selected_index]
        related = _json_value(selected.get("related_stocks"))

        st.markdown(f"**{selected.get('headline') or '未命名分析'}**")
        st.write(selected.get("summary") or "尚無摘要")
        if selected.get("source_url"):
            st.markdown(f"[閱讀原始新聞]({selected['source_url']})")
        st.caption(
            f"新聞發布時間：{selected.get('published_at') or '未取得'}｜"
            f"AI 分析時間：{selected.get('created_at')}"
        )

        stock_options = []
        if isinstance(related, list):
            for item in related:
                if isinstance(item, dict):
                    name = (
                        item.get("name")
                        or item.get("stock")
                        or item.get("company")
                        or item.get("ticker")
                    )
                    if name:
                        stock_options.append((str(name), item))
                elif item:
                    stock_options.append((str(item), {}))

        if stock_options:
            selected_stock_idx = st.selectbox(
                "選擇關聯個股",
                range(len(stock_options)),
                format_func=lambda i: (
                    f"{stock_options[i][0]}｜方向：{_direction(stock_options[i][1])}"
                ),
            )
            stock_name, stock_data = stock_options[selected_stock_idx]
        else:
            st.warning("這則 AI 分析沒有結構化關聯個股，請手動輸入公司名稱與代號。")
            stock_name, stock_data = "", {}

        with st.form("create_stock_review"):
            stock_name_input = st.text_input(
                "公司／股票名稱",
                value=stock_name,
                placeholder="例如：台積電",
            )
            suggested_ticker = ""
            for key in ("ticker", "symbol", "stock_code", "code"):
                if isinstance(stock_data, dict) and stock_data.get(key):
                    suggested_ticker = str(stock_data[key]).strip()
                    break
            ticker_input = st.text_input(
                "Yahoo Finance 台股代號",
                value=suggested_ticker,
                placeholder="例如 2330.TW 或 6488.TWO",
                help="上市輸入 .TW；上櫃輸入 .TWO。請確認代號正確。",
            )
            direction = st.text_input(
                "原始分析方向",
                value=_direction(stock_data),
                help="保留原始 AI 分析方向，不代表股價必然朝此方向變動。",
            )
            submitted = st.form_submit_button(
                "建立／更新股價回顧",
                type="primary",
                use_container_width=True,
            )

        if submitted:
            ticker = ticker_input.strip().upper()
            if not (ticker.endswith(".TW") or ticker.endswith(".TWO")):
                st.error("請輸入台股 Yahoo 代號，例如 2330.TW 或 6488.TWO。")
            elif not stock_name_input.strip():
                st.error("請輸入公司／股票名稱。")
            elif not selected.get("published_at"):
                st.error("原始新聞缺少發布時間，暫時無法建立準確的觀察起點。")
            else:
                st.session_state["review_direction"] = direction.strip() or "未判定"
                try:
                    with st.spinner("下載個股與台灣加權指數歷史收盤價並計算回顧…"):
                        stock_series = _download_daily(ticker)
                        benchmark_series = _download_daily(BENCHMARK)
                        if stock_series.empty:
                            raise ValueError(f"Yahoo Finance 沒有回傳 {ticker} 的有效日線資料。")
                        if benchmark_series.empty:
                            st.warning("台灣加權指數資料暫時不可用；個股報酬仍會計算，但相對大盤報酬會標示資料不足。")
                            benchmark_series = pd.Series(dtype="float64")
                        event_id, base_date, base_close = _save_event_and_observations(
                            selected,
                            stock_name_input.strip(),
                            ticker,
                            stock_series,
                            benchmark_series,
                        )
                    st.success(
                        f"回顧事件已保存（編號 {event_id}）。"
                        f"基準交易日：{base_date}；基準收盤：{base_close:,.2f}"
                    )
                    st.info("第 1／3／5 個交易日若尚未到達，會標示「待觀察」；之後可再次按更新取得新資料。")
                except Exception as exc:
                    st.error("建立回顧失敗。")
                    st.caption(f"{type(exc).__name__}: {str(exc)[:500]}")

with tab_history:
    try:
        events = _load_events(limit=200)
    except Exception as exc:
        st.error("讀取回顧紀錄失敗。")
        st.caption(f"{type(exc).__name__}: {str(exc)[:300]}")
        events = []

    if not events:
        st.info("目前還沒有股價回顧紀錄。")
    else:
        rows = []
        for event in events:
            observations = _json_value(event.get("observations"))
            obs_by_horizon = {
                int(o["horizon_days"]): o
                for o in observations
                if isinstance(o, dict) and o.get("horizon_days") is not None
            }
            row = {
                "新聞": event.get("headline"),
                "股票": event.get("stock_name"),
                "代號": event.get("ticker"),
                "原始方向": event.get("expected_direction"),
                "基準日": str(event.get("baseline_date") or ""),
                "基準收盤": event.get("baseline_close"),
            }
            for h in HORIZONS:
                obs = obs_by_horizon.get(h, {})
                row[f"T+{h}日期"] = str(obs.get("observation_date") or "待觀察")
                row[f"T+{h}個股報酬%"] = obs.get("stock_return_pct")
                row[f"T+{h}相對大盤%"] = obs.get("relative_return_pct")
                row[f"T+{h}狀態"] = obs.get("status") or "待觀察"
            rows.append(row)

        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.caption("相對大盤報酬 = 個股報酬率 − 台灣加權指數同期報酬率；此數值是比較，不代表新聞造成股價變動。")

st.divider()
with st.expander("計算方式與限制"):
    st.markdown(
        """
        - 第一階段僅處理台股，Yahoo Finance 代號使用 `.TW`（上市）或 `.TWO`（上櫃）。
        - 新聞於台灣時間 13:30（含）後發布，基準日從下一個有效交易日開始；其餘情況使用發布當日或之後第一個有效交易日。
        - T+1／T+3／T+5 是基準交易日之後第 1／3／5 個有效交易日。
        - 個股報酬率以基準收盤價計算；相對大盤報酬為個股報酬減台灣加權指數報酬。
        - 原始 AI 分析快照會另存，不會回寫或覆蓋 public.analyses。
        - Yahoo Finance 是第三方資料來源，可能延遲、缺漏或有公司行動調整；結果僅供回顧，不構成投資建議。
        """
    )
