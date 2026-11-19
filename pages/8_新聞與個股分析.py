"""
新聞影響力、個股關聯與股價回顧（整合版）
放置位置：pages/8_新聞與個股分析.py

單一頁面整合原 Page 8（個股股價分析）與 Page 9（新聞影響力分級）。
既有 public.news / public.analyses 僅讀取；結果寫入兩張獨立資料表。
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
    st.error("缺少 yfinance 套件，請確認 requirements.txt 已包含 yfinance。")
    st.stop()

try:
    from services.storage import _connection
except ImportError as exc:
    st.error("無法載入既有資料庫連線，請確認 services/storage.py 存在。")
    st.caption(str(exc))
    st.stop()

TZ = ZoneInfo("Asia/Taipei")
BENCHMARKS = {"TW": "^TWII", "US": "^GSPC"}
HORIZONS = (1, 3, 5)

# 第一版公司關鍵字表；後續可擴充完整上市櫃公司主檔。
STOCKS = {
    "TW": {
        "台積電": ("2330.TW", ["台積電", "TSMC"]),
        "鴻海": ("2317.TW", ["鴻海", "Hon Hai", "Foxconn"]),
        "聯發科": ("2454.TW", ["聯發科", "MediaTek"]),
        "廣達": ("2382.TW", ["廣達", "Quanta"]),
        "緯創": ("3231.TW", ["緯創", "Wistron"]),
        "日月光投控": ("3711.TW", ["日月光", "ASE Technology"]),
        "台達電": ("2308.TW", ["台達電", "Delta Electronics"]),
    },
    "US": {
        "NVIDIA": ("NVDA", ["NVIDIA", "輝達"]),
        "Apple": ("AAPL", ["Apple", "蘋果公司", "iPhone"]),
        "Microsoft": ("MSFT", ["Microsoft", "微軟"]),
        "Amazon": ("AMZN", ["Amazon", "亞馬遜"]),
        "Alphabet": ("GOOGL", ["Alphabet", "Google", "谷歌"]),
        "Meta": ("META", ["Meta Platforms", "Facebook"]),
        "Tesla": ("TSLA", ["Tesla", "特斯拉"]),
        "AMD": ("AMD", ["AMD", "超微"]),
        "Broadcom": ("AVGO", ["Broadcom", "博通"]),
    },
}
S_TERMS = ["重大訂單", "大額訂單", "併購", "收購", "合併", "財測上修", "財測下修",
           "停產", "破產", "違約", "遭制裁", "出口禁令", "重大投資", "重大事故"]
A_TERMS = ["營收", "獲利", "財報", "法說", "訂單", "出貨", "擴產", "資本支出",
           "上調", "下調", "新產品", "合作", "供應鏈", "產能", "毛利率", "關稅"]
INDUSTRY_TERMS = ["半導體", "AI", "人工智慧", "伺服器", "資料中心", "電動車",
                  "金融", "航運", "能源", "記憶體", "晶片", "供應鏈", "利率", "通膨"]

st.set_page_config(page_title="新聞與個股分析｜AI Market Radar", page_icon="📈", layout="wide")
st.title("📈 新聞影響力、個股關聯與股價回顧")
st.caption("整合新聞分級、公司辨識、股價走勢及 T+1／T+3／T+5 回顧；原始新聞與 AI 分析資料維持唯讀。")


def jval(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (ValueError, TypeError):
            return []
    return v if v is not None else []


def load_news(limit=500):
    with _connection() as conn:
        rows = conn.execute(
            """
            SELECT n.title, n.summary, n.market, n.source, n.url, n.published_at,
                   a.id::text AS analysis_id, a.headline AS analysis_headline,
                   a.summary AS analysis_summary, a.industry, a.industry_impact,
                   a.sentiment, a.sentiment_reason, a.sentiment_confidence,
                   a.related_stocks, a.watch_items, a.created_at AS analysis_created_at
            FROM public.news n
            LEFT JOIN LATERAL (
                SELECT * FROM public.analyses
                WHERE source_url = n.url
                ORDER BY created_at DESC LIMIT 1
            ) a ON TRUE
            ORDER BY n.published_at DESC NULLS LAST
            LIMIT %s
            """, (int(limit),)
        ).fetchall()
    return [dict(r) for r in rows]


def infer_stock_market(ticker, fallback=""):
    """依 Yahoo Finance 代號判斷個股市場，不使用新聞來源市場代替。"""
    code = str(ticker or "").strip().upper()
    if code.endswith((".TW", ".TWO")) or (code.isdigit() and 3 <= len(code) <= 6):
        return "TW"
    if code and re.fullmatch(r"[A-Z][A-Z0-9.\-]*", code) and not code.startswith("^"):
        return "US"
    fallback = str(fallback or "").upper()
    return fallback if fallback in ("TW", "US") else "未知"


def discover_stocks(item):
    news_market = str(item.get("market") or "").upper()
    text = " ".join(str(item.get(k) or "") for k in
                    ("title", "summary", "analysis_summary", "industry_impact"))
    found = {}
    related = jval(item.get("related_stocks"))
    if isinstance(related, list):
        for s in related:
            if not isinstance(s, dict):
                continue
            name = s.get("name") or s.get("stock") or s.get("company") or s.get("company_name")
            ticker = s.get("ticker") or s.get("symbol") or s.get("stock_code") or s.get("code")
            if name or ticker:
                ticker = str(ticker or "").strip().upper()
                stock_market = infer_stock_market(ticker, news_market)
                key = (str(name or ticker), ticker)
                found[key] = {"name": key[0], "ticker": ticker,
                              "market": stock_market,
                              "source": ["AI 分析"],
                              "evidence": [s.get("reason") or s.get("impact_reason") or ""]}

    # 關鍵字辨識跨市場執行：台灣新聞提到 NVIDIA / Microsoft 時，也能辨識成美股。
    for stock_market, companies in STOCKS.items():
        for name, (ticker, keywords) in companies.items():
            hits = [k for k in keywords if k.casefold() in text.casefold()]
            if hits:
                key = (name, ticker)
                entry = found.setdefault(key, {"name": name, "ticker": ticker,
                                               "market": stock_market,
                                               "source": [], "evidence": []})
                entry["market"] = stock_market
                if "新聞關鍵字" not in entry["source"]:
                    entry["source"].append("新聞關鍵字")
                entry["evidence"].append("命中：" + "、".join(hits))
    # 對 AI 提供的裸數字台股代號補上市場資訊；裸英文字母代號視為美股。
    # 同一代號若同時由 AI 與關鍵字辨識到，合併成一筆，避免重複建立回顧。
    canonical_names = {ticker: name for companies in STOCKS.values()
                       for name, (ticker, _keywords) in companies.items()}
    merged = {}
    for stock in found.values():
        ticker = str(stock.get("ticker") or "").strip().upper()
        stock["market"] = infer_stock_market(ticker, stock.get("market") or news_market)
        key = ticker or (stock.get("name"), stock["market"])
        if key not in merged:
            merged[key] = stock.copy()
            if ticker in canonical_names:
                merged[key]["name"] = canonical_names[ticker]
        else:
            for field in ("source", "evidence"):
                merged[key][field] = list(dict.fromkeys(
                    merged[key].get(field, []) + stock.get(field, [])))
    return list(merged.values())


def grade_item(item, stocks):
    title = str(item.get("title") or "")
    text = title + " " + " ".join(str(item.get(k) or "") for k in
                                  ("summary", "analysis_summary", "industry_impact"))
    s_hits = [x for x in S_TERMS if x in text]
    a_hits = [x for x in A_TERMS if x in text]
    industry_hits = [x for x in INDUSTRY_TERMS if x.casefold() in text.casefold()]
    if stocks and s_hits:
        grade, reason = "S", "具名公司且出現重大事件線索"
    elif stocks and a_hits:
        grade, reason = "A", "具名公司且涉及營運、財務或政策事件"
    elif s_hits or a_hits or industry_hits:
        grade, reason = "B", "有產業或事件線索，但個股直接關聯尚待確認"
    else:
        grade, reason = "C", "目前可辨識的公司與事件證據有限"
    return grade, reason, {"重大事件詞": s_hits, "營運政策詞": a_hits,
                           "產業線索": industry_hits, "關聯股票數": len(stocks)}


@st.cache_data(ttl=900, show_spinner=False)
def prices(ticker):
    raw = yf.download(ticker, period="2y", interval="1d", auto_adjust=True,
                      progress=False, threads=False)
    if raw is None or raw.empty or "Close" not in raw.columns:
        return pd.Series(dtype="float64")
    close = raw["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    close = pd.to_numeric(close, errors="coerce").dropna()
    idx = pd.to_datetime(close.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    close.index = idx.normalize()
    return close[~close.index.duplicated(keep="last")].sort_index()


def resolve_ticker(raw, market):
    raw = str(raw or "").strip().upper()
    if not raw:
        return None, pd.Series(dtype=float), "沒有股票代號"
    if market == "TW" and raw.isdigit():
        for suffix in (".TW", ".TWO"):
            s = prices(raw + suffix)
            if not s.empty:
                return raw + suffix, s, "已自動確認上市／上櫃代號"
        return None, pd.Series(dtype=float), "無法確認 .TW 或 .TWO"
    s = prices(raw)
    return (raw, s, "已取得歷史資料") if not s.empty else (None, s, f"Yahoo 查無 {raw}")


def taipei_dt(v):
    if not v:
        return None
    try:
        d = v if isinstance(v, datetime) else datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=TZ)
        return d.astimezone(TZ)
    except Exception:
        return None


def save_impact(results):
    count = 0
    with _connection() as conn:
        for r in results:
            it = r["item"]
            if not it.get("url"):
                continue
            snapshot = {k: str(it.get(k)) for k in
                        ("title", "summary", "analysis_summary", "sentiment",
                         "sentiment_reason", "sentiment_confidence", "analysis_created_at")}
            conn.execute(
                """
                INSERT INTO public.news_impact_assessments
                    (news_url, headline, market, source, published_at, impact_grade,
                     grade_reason, related_stocks, evidence, analysis_snapshot, assessed_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,now())
                ON CONFLICT (news_url) DO UPDATE SET
                    headline=EXCLUDED.headline, market=EXCLUDED.market, source=EXCLUDED.source,
                    published_at=EXCLUDED.published_at, impact_grade=EXCLUDED.impact_grade,
                    grade_reason=EXCLUDED.grade_reason, related_stocks=EXCLUDED.related_stocks,
                    evidence=EXCLUDED.evidence, analysis_snapshot=EXCLUDED.analysis_snapshot,
                    assessed_at=now()
                """,
                (it["url"], it.get("title") or "", it.get("market"), it.get("source"),
                 it.get("published_at"), r["grade"], r["reason"],
                 json.dumps(r["stocks"], ensure_ascii=False),
                 json.dumps(r["evidence"], ensure_ascii=False),
                 json.dumps(snapshot, ensure_ascii=False))
            )
            count += 1
    return count


def save_review(item, stock, ticker, stock_prices, bench, benchmark_ticker):
    dt = taipei_dt(item.get("published_at"))
    if dt is None:
        raise ValueError("原始新聞缺少發布時間")
    stock_market = stock.get("market") or infer_stock_market(ticker)
    # 台股沿用原本 13:30 收盤後發布則從下一交易日起算；美股以當地日期對齊其交易日序列。
    target = dt.date() + (timedelta(days=1) if stock_market == "TW" and dt.time() >= time(13, 30) else timedelta())
    base_candidates = [d for d in stock_prices.index if d.date() >= target]
    if not base_candidates:
        raise ValueError("尚無新聞發布後的交易日資料")
    base_day = base_candidates[0]
    base_close = float(stock_prices.loc[base_day])
    bench_base = float(bench.loc[base_day]) if base_day in bench.index else None
    analysis_id = item.get("analysis_id") or item.get("url")
    snapshot = {"headline": item.get("title"), "summary": item.get("analysis_summary"),
                "related_stock": stock, "stock_market": stock_market,
                "analysis_created_at": str(item.get("analysis_created_at"))}
    with _connection() as conn:
        event = conn.execute(
            """
            INSERT INTO public.stock_review_events
                (analysis_id, headline, source_url, published_at, stock_name, ticker,
                 expected_direction, analysis_snapshot, baseline_date, baseline_close,
                 benchmark_ticker, benchmark_baseline_close)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s)
            ON CONFLICT (analysis_id,ticker) DO UPDATE SET
                headline=EXCLUDED.headline, source_url=EXCLUDED.source_url,
                published_at=EXCLUDED.published_at, stock_name=EXCLUDED.stock_name,
                expected_direction=EXCLUDED.expected_direction,
                analysis_snapshot=EXCLUDED.analysis_snapshot,
                baseline_date=EXCLUDED.baseline_date, baseline_close=EXCLUDED.baseline_close,
                benchmark_ticker=EXCLUDED.benchmark_ticker,
                benchmark_baseline_close=EXCLUDED.benchmark_baseline_close, updated_at=now()
            RETURNING id
            """,
            (str(analysis_id), item.get("title") or "", item.get("url"), item.get("published_at"),
             stock.get("name") or ticker, ticker,
             item.get("sentiment") or "未判定", json.dumps(snapshot, ensure_ascii=False, default=str),
             base_day.date(), base_close, benchmark_ticker, bench_base)
        ).fetchone()
        eid = event["id"]
        for h in HORIZONS:
            ix = stock_prices.index.get_loc(base_day) + h
            if ix >= len(stock_prices):
                conn.execute(
                    """INSERT INTO public.stock_review_observations(event_id,horizon_days,status)
                       VALUES (%s,%s,'待觀察')
                       ON CONFLICT (event_id,horizon_days) DO UPDATE SET status='待觀察',
                       observation_date=NULL, stock_close=NULL, benchmark_close=NULL,
                       stock_return_pct=NULL, benchmark_return_pct=NULL,
                       relative_return_pct=NULL, updated_at=now()""", (eid, h))
                continue
            day = stock_prices.index[ix]
            sc = float(stock_prices.iloc[ix])
            sr = (sc / base_close - 1) * 100
            bc = float(bench.loc[day]) if day in bench.index else None
            br = (bc / bench_base - 1) * 100 if bc is not None and bench_base else None
            rr = sr - br if br is not None else None
            status = "完成" if rr is not None else "個股完成／大盤資料不足"
            conn.execute(
                """INSERT INTO public.stock_review_observations
                   (event_id,horizon_days,observation_date,stock_close,benchmark_close,
                    stock_return_pct,benchmark_return_pct,relative_return_pct,status,updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                   ON CONFLICT (event_id,horizon_days) DO UPDATE SET
                    observation_date=EXCLUDED.observation_date, stock_close=EXCLUDED.stock_close,
                    benchmark_close=EXCLUDED.benchmark_close,
                    stock_return_pct=EXCLUDED.stock_return_pct,
                    benchmark_return_pct=EXCLUDED.benchmark_return_pct,
                    relative_return_pct=EXCLUDED.relative_return_pct,
                    status=EXCLUDED.status, updated_at=now()""",
                (eid, h, day.date(), sc, bc, sr, br, rr, status))


def load_reviews():
    with _connection() as conn:
        rows = conn.execute(
            """SELECT e.headline,e.stock_name,e.ticker,e.expected_direction,e.baseline_date,
                      e.baseline_close,
                      COALESCE(json_agg(json_build_object(
                        'horizon_days',o.horizon_days,'observation_date',o.observation_date,
                        'stock_return_pct',o.stock_return_pct,
                        'relative_return_pct',o.relative_return_pct,'status',o.status
                      )) FILTER (WHERE o.id IS NOT NULL),'[]'::json) AS observations
               FROM public.stock_review_events e
               LEFT JOIN public.stock_review_observations o ON o.event_id=e.id
               GROUP BY e.id ORDER BY e.published_at DESC LIMIT 500"""
        ).fetchall()
    return [dict(r) for r in rows]


# Verify the two isolated tables. This page never creates or alters tables itself.
try:
    with _connection() as conn:
        conn.execute("SELECT 1 FROM public.news_impact_assessments LIMIT 1")
        conn.execute("SELECT 1 FROM public.stock_review_events LIMIT 1")
        conn.execute("SELECT 1 FROM public.stock_review_observations LIMIT 1")
except Exception as exc:
    st.warning("整合頁所需的專用資料表尚未全部建立，請先執行 ZIP 內的整合 SQL。")
    st.caption(str(exc).splitlines()[0][:300])
    st.stop()

try:
    with st.spinner("載入新聞與既有 AI 分析…"):
        news = load_news()
except Exception as exc:
    st.error("讀取新聞失敗，請確認既有資料表欄位。")
    st.caption(f"{type(exc).__name__}: {str(exc)[:300]}")
    st.stop()

assessments = []
for item in news:
    stocks = discover_stocks(item)
    grade, reason, evidence = grade_item(item, stocks)
    assessments.append({"item": item, "stocks": stocks, "grade": grade,
                        "reason": reason, "evidence": evidence})

tab_news, tab_stocks, tab_review = st.tabs(
    ["🧭 新聞影響力與個股關聯", "📊 個股股價分析", "🕒 新聞事件回顧"]
)

with tab_news:
    a, b, c = st.columns(3)
    markets = sorted({str(x["item"].get("market") or "未知").upper() for x in assessments})
    with a:
        mf = st.selectbox("市場", ["全部"] + markets, key="impact_market")
    with b:
        gf = st.selectbox("影響力等級", ["全部", "S", "A", "B", "C"], key="impact_grade")
    with c:
        q = st.text_input("搜尋公司／股票", key="impact_search")
    filtered = assessments
    if mf != "全部":
        filtered = [x for x in filtered if str(x["item"].get("market") or "未知").upper() == mf]
    if gf != "全部":
        filtered = [x for x in filtered if x["grade"] == gf]
    if q.strip():
        filtered = [x for x in filtered if any(q.casefold() in
                    (s["name"] + " " + s["ticker"]).casefold() for s in x["stocks"])]
    # 依影響力固定排序：S → A → B → C；同級維持 load_news 的最新發布時間優先順序。
    grade_order = {"S": 0, "A": 1, "B": 2, "C": 3}
    filtered = sorted(filtered, key=lambda x: grade_order.get(x["grade"], 99))
    counts = {g: sum(x["grade"] == g for x in assessments) for g in "SABC"}
    m = st.columns(5)
    for col, label, val in zip(m, ["新聞", "S 級", "A 級", "B 級", "有個股關聯"],
                               [len(assessments), counts["S"], counts["A"], counts["B"],
                                sum(bool(x["stocks"]) for x in assessments)]):
        col.metric(label, val)
    if st.button("保存／更新全部新聞分級與個股關聯", type="primary", key="save_impact"):
        try:
            n = save_impact(assessments)
            st.success(f"已保存／更新 {n} 則新聞。")
        except Exception as exc:
            st.error(f"保存失敗：{type(exc).__name__}: {str(exc)[:300]}")
    for r in filtered:
        it = r["item"]
        title = it.get("title") or it.get("analysis_headline") or "未命名新聞"
        with st.expander(f"{r['grade']} 級｜{it.get('market') or '未知'}｜{title}｜{len(r['stocks'])} 檔"):
            st.caption(f"發布時間：{it.get('published_at') or '未知'}｜來源：{it.get('source') or '未知'}")
            st.write(it.get("summary") or "無新聞摘要")
            if it.get("url"):
                st.markdown(f"[閱讀原始新聞]({it['url']})")
            st.write(f"**分級理由：** {r['reason']}")
            if r["stocks"]:
                st.dataframe(pd.DataFrame([{
                    "公司": s["name"], "代號": s["ticker"] or "待確認",
                    "辨識來源": "、".join(s["source"]),
                    "文字證據": "；".join(x for x in s["evidence"] if x)
                } for s in r["stocks"]]), use_container_width=True, hide_index=True)
            else:
                st.caption("目前沒有辨識到明確關聯公司。")
            if it.get("sentiment"):
                st.caption(f"既有 AI 情緒：{it.get('sentiment')}｜{it.get('sentiment_reason') or ''}")

with tab_stocks:
    st.write("依股票代號自動判斷個股市場；台股以 ^TWII、美股以 ^GSPC 作比較基準。新聞市場與個股市場分開顯示。")
    market = st.selectbox("批次分析市場", ["台股", "美股"], key="stock_market")
    market_code = "TW" if market == "台股" else "US"
    stock_pairs = []
    seen_pairs = set()
    for r in assessments:
        for s in r["stocks"]:
            if (s.get("market") or infer_stock_market(s.get("ticker"))) != market_code:
                continue
            pair_key = (str(r["item"].get("analysis_id") or r["item"].get("url") or r["item"].get("title")),
                        s.get("ticker"))
            if pair_key not in seen_pairs:
                stock_pairs.append((r["item"], s))
                seen_pairs.add(pair_key)
    st.caption(f"目前找到 {len(stock_pairs)} 個新聞／股票關聯。")
    if st.button("批次下載並建立／更新股價回顧", type="primary", key="batch_prices"):
        try:
            benchmark_ticker = BENCHMARKS[market_code]
            bench = prices(benchmark_ticker)
            if bench.empty:
                raise RuntimeError(f"Yahoo Finance 無法取得比較基準 {benchmark_ticker}。")
            done, skipped, errors = 0, 0, []
            progress = st.progress(0)
            for i, (item, stock) in enumerate(stock_pairs):
                ticker, series, msg = resolve_ticker(stock.get("ticker"), market_code)
                if not ticker:
                    skipped += 1
                    errors.append(f"{stock['name']}：{msg}")
                else:
                    try:
                        save_review(item, stock, ticker, series, bench, benchmark_ticker)
                        done += 1
                    except Exception as exc:
                        errors.append(f"{stock['name']}：{str(exc)[:150]}")
                progress.progress((i + 1) / max(1, len(stock_pairs)))
            st.success(f"完成：{done} 筆回顧已建立／更新。比較基準：{benchmark_ticker}")
            if skipped or errors:
                with st.expander(f"略過或失敗項目（{len(errors)}）"):
                    for e in errors:
                        st.write("- " + e)
        except Exception as exc:
            st.error(f"批次處理失敗：{type(exc).__name__}: {str(exc)[:300]}")
    if stock_pairs:
        st.dataframe(pd.DataFrame([{
            "新聞": it.get("title"), "公司": s["name"], "代號": s["ticker"],
            "新聞市場": it.get("market"), "個股市場": s.get("market"), "AI 情緒": it.get("sentiment")
        } for it, s in stock_pairs]), use_container_width=True, hide_index=True)

with tab_review:
    try:
        reviews = load_reviews()
    except Exception as exc:
        st.error(f"讀取回顧紀錄失敗：{type(exc).__name__}: {str(exc)[:250]}")
        reviews = []
    if not reviews:
        st.info("目前尚無股價回顧紀錄。請先到「個股股價分析」執行批次分析。")
    else:
        rows = []
        for e in reviews:
            obs = {int(x["horizon_days"]): x for x in jval(e["observations"])
                   if isinstance(x, dict) and x.get("horizon_days") is not None}
            row = {"新聞": e["headline"], "個股": e["stock_name"], "代號": e["ticker"],
                   "AI 方向": e["expected_direction"], "基準日": str(e["baseline_date"]),
                   "基準收盤": e["baseline_close"]}
            for h in HORIZONS:
                o = obs.get(h, {})
                row[f"T+{h}日期"] = str(o.get("observation_date") or "待觀察")
                row[f"T+{h}個股報酬%"] = o.get("stock_return_pct")
                row[f"T+{h}相對大盤%"] = o.get("relative_return_pct")
                row[f"T+{h}狀態"] = o.get("status") or "待觀察"
            rows.append(row)
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.caption("相對大盤報酬 = 個股報酬率 − 台灣加權指數同期報酬率；比較結果不代表新聞造成股價變動。")
        chart_rows = []
        for e in reviews:
            for o in jval(e["observations"]):
                if isinstance(o, dict) and o.get("stock_return_pct") is not None:
                    chart_rows.append({"股票": e["stock_name"], "期間": f"T+{o['horizon_days']}",
                                       "個股報酬率（%）": o["stock_return_pct"]})
        if chart_rows:
            with st.expander("個股報酬比較圖"):
                fig = px.bar(pd.DataFrame(chart_rows), x="股票", y="個股報酬率（%）",
                             color="期間", barmode="group")
                fig.add_hline(y=0, line_dash="dash", line_color="gray")
                st.plotly_chart(fig, use_container_width=True)

with st.expander("分級與股價計算說明"):
    st.markdown("""
    - S/A/B/C 是新聞研究優先級，不是利多利空或買賣評等。
    - 公司關鍵字命中代表新聞文字提及，不保證公司實際受惠或受損。
    - 第一版股價回顧僅支援台股，代號使用 .TW／.TWO，基準指數為 ^TWII。
    - 新聞台灣時間 13:30（含）後發布，基準日從下一個有效交易日開始。
    - T+1／T+3／T+5 為基準交易日之後第 1／3／5 個有效交易日。
    - 個股使用 Yahoo Finance 調整後收盤價；相對報酬是市場比較，不是因果歸因。
    - 原始 news／analyses 僅讀取，結果分別保存於兩張專用資料表。
    """)
