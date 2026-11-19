"""原 Page 9：AI 分析績效。"""
def render():
    """AI 分析績效儀表板（唯讀）

    讀取既有 public.news_impact_assessments、public.stock_review_events、
    public.stock_review_observations；不建立或修改資料表，也不呼叫 AI API。
    """

    from datetime import date, timedelta

    import pandas as pd
    import plotly.express as px
    import streamlit as st

    try:
        from services.storage import _connection
    except ImportError as exc:
        st.error("無法載入既有資料庫連線，請確認 services/storage.py 存在。")
        st.caption(str(exc))
        st.stop()

    st.title("🎯 AI 分析績效儀表板")
    st.caption("以既有新聞分級與 T+1／T+3／T+5 股價回顧資料，檢視歷史表現；本頁唯讀，不重新呼叫 AI。")


    @st.cache_data(ttl=300, show_spinner=False)
    def load_performance_data():
        with _connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    e.id AS event_id,
                    e.headline,
                    e.source_url,
                    e.published_at,
                    e.stock_name,
                    e.ticker,
                    e.expected_direction,
                    e.baseline_date,
                    e.analysis_snapshot,
                    o.horizon_days,
                    o.observation_date,
                    o.stock_return_pct,
                    o.benchmark_return_pct,
                    o.relative_return_pct,
                    o.status
                FROM public.stock_review_events e
                JOIN public.stock_review_observations o
                     ON o.event_id = e.id
                ORDER BY e.published_at DESC NULLS LAST, e.id, o.horizon_days
                LIMIT 20000
                """
            ).fetchall()
            assessments = conn.execute(
                """
                SELECT news_url, headline, impact_grade, assessed_at
                FROM public.news_impact_assessments
                ORDER BY assessed_at DESC NULLS LAST
                LIMIT 10000
                """
            ).fetchall()

        def canonical_url(value):
            from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
            value = str(value or "").strip()
            if not value.startswith(("http://", "https://")):
                return ""
            try:
                p = urlsplit(value)
                ignored = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source"}
                query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                         if not k.casefold().startswith("utm_") and k.casefold() not in ignored]
                return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/") or "/",
                                   urlencode(sorted(query), doseq=True), ""))
            except ValueError:
                return ""

        def title_key(value):
            import re
            return re.sub(r"[\\W_]+", "", str(value or "").casefold())

        grade_by_url, grade_by_title = {}, {}
        for item in assessments:
            grade = item.get("impact_grade")
            url_key = canonical_url(item.get("news_url"))
            title = title_key(item.get("headline"))
            if grade and url_key and url_key not in grade_by_url:
                grade_by_url[url_key] = grade
            if grade and title and title not in grade_by_title:
                grade_by_title[title] = grade

        result = []
        for row in rows:
            item = dict(row)
            item["impact_grade"] = (
                grade_by_url.get(canonical_url(item.get("source_url")))
                or grade_by_title.get(title_key(item.get("headline")))
            )
            result.append(item)
        return pd.DataFrame(result)


    def to_num(series):
        return pd.to_numeric(series, errors="coerce")


    def stock_market(ticker):
        code = str(ticker or "").strip().upper()
        if code.endswith((".TW", ".TWO")) or (code.isdigit() and 3 <= len(code) <= 6):
            return "TW"
        if code and not code.startswith("^"):
            return "US"
        return "未知"


    def normalize_direction(value):
        value = str(value or "").strip()
        if value in ("利多", "偏多", "看多"):
            return "利多"
        if value in ("利空", "偏空", "看空"):
            return "利空"
        if value == "中性":
            return "中性"
        return "資訊不足"


    try:
        with st.spinner("讀取既有股價回顧資料…"):
            df = load_performance_data()
    except Exception as exc:
        st.error("讀取績效資料失敗。請確認 Page 8 所需的三張資料表已建立，且資料庫帳號有讀取權限。")
        st.caption(f"{type(exc).__name__}: {str(exc).splitlines()[0][:300]}")
        st.stop()

    if df.empty:
        st.info("目前尚無股價回顧資料。請先到「新聞與個股分析」→「個股股價分析」執行批次分析。")
        st.stop()

    # Normalize types and derive the listed market from the actual ticker, not the news market.
    df["published_at"] = pd.to_datetime(df["published_at"], errors="coerce", utc=True).dt.tz_convert("Asia/Taipei")
    df["observation_date"] = pd.to_datetime(df["observation_date"], errors="coerce")
    df["stock_return_pct"] = to_num(df["stock_return_pct"])
    df["benchmark_return_pct"] = to_num(df["benchmark_return_pct"])
    df["relative_return_pct"] = to_num(df["relative_return_pct"])
    df["horizon_days"] = pd.to_numeric(df["horizon_days"], errors="coerce")
    df["個股市場"] = df["ticker"].map(stock_market)
    df["影響力等級"] = df["impact_grade"].fillna("未分級")
    df["AI新聞情緒"] = df["expected_direction"].map(normalize_direction)
    df["回顧狀態"] = df["status"].fillna("待觀察")

    # The date filter is based on the news publication date (Taipei time).
    valid_dates = df["published_at"].dropna()
    if valid_dates.empty:
        min_date = date.today() - timedelta(days=365)
        max_date = date.today()
    else:
        min_date = valid_dates.min().date()
        max_date = valid_dates.max().date()

    f1, f2, f3 = st.columns(3)
    with f1:
        market_choice = st.selectbox("個股市場", ["全部", "TW", "US"], index=0)
    with f2:
        grade_choice = st.selectbox("新聞影響力等級", ["全部", "S", "A", "B", "C", "未分級"], index=0)
    with f3:
        horizon_choice = st.selectbox("觀察期間", ["全部", "T+1", "T+3", "T+5"], index=0)

    start_col, end_col = st.columns(2)
    with start_col:
        start_date = st.date_input("新聞起始日期", value=min_date, min_value=min_date, max_value=max_date)
    with end_col:
        end_date = st.date_input("新聞結束日期", value=max_date, min_value=min_date, max_value=max_date)

    filtered = df.copy()
    if market_choice != "全部":
        filtered = filtered[filtered["個股市場"] == market_choice]
    if grade_choice != "全部":
        filtered = filtered[filtered["影響力等級"] == grade_choice]
    if horizon_choice != "全部":
        selected_horizon = int(horizon_choice.replace("T+", ""))
        filtered = filtered[filtered["horizon_days"] == selected_horizon]
    if start_date > end_date:
        st.warning("起始日期不可晚於結束日期。")
        st.stop()
    if filtered["published_at"].notna().any():
        local_dates = filtered["published_at"].dt.date
        filtered = filtered[(local_dates >= start_date) & (local_dates <= end_date)]

    completed = filtered[
        filtered["relative_return_pct"].notna()
        & filtered["回顧狀態"].astype(str).str.contains("完成", na=False)
    ].copy()

    # Summary cards use the selected filters and only completed relative-return observations.
    unique_events = completed["event_id"].nunique()
    positive_rate = (completed["relative_return_pct"] > 0).mean() * 100 if not completed.empty else None
    avg_excess = completed["relative_return_pct"].mean() if not completed.empty else None
    avg_stock = completed["stock_return_pct"].mean() if not completed.empty else None

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("完成觀察筆數", f"{len(completed):,}")
    k2.metric("涵蓋新聞／個股事件", f"{unique_events:,}")
    k3.metric("相對大盤正報酬比例", "—" if positive_rate is None else f"{positive_rate:.1f}%")
    k4.metric("平均相對大盤報酬", "—" if avg_excess is None else f"{avg_excess:+.2f}%")

    st.caption("相對大盤報酬 = 個股報酬率 − 比較基準指數報酬率。以下只統計狀態完成且有相對報酬的觀察值。")

    if completed.empty:
        st.info("目前篩選條件下沒有已完成的股價觀察。T+1／T+3／T+5 尚未到期的資料不會納入績效統計。")
    else:
        st.subheader("一、S／A／B／C 分級後續表現")
        grade_summary = (
            completed.groupby(["影響力等級", "horizon_days"], dropna=False)
            .agg(
                樣本數=("event_id", "count"),
                平均個股報酬率=("stock_return_pct", "mean"),
                平均相對報酬率=("relative_return_pct", "mean"),
                相對大盤正報酬比例=("relative_return_pct", lambda x: (x > 0).mean() * 100),
                相對報酬中位數=("relative_return_pct", "median"),
            )
            .reset_index()
        )
        grade_order = {"S": 0, "A": 1, "B": 2, "C": 3, "未分級": 4}
        grade_summary["_order"] = grade_summary["影響力等級"].map(grade_order).fillna(99)
        grade_summary = grade_summary.sort_values(["_order", "horizon_days"]).drop(columns="_order")
        st.dataframe(
            grade_summary.rename(columns={"horizon_days": "觀察期間"}).assign(
                觀察期間=lambda x: x["觀察期間"].map(lambda v: f"T+{int(v)}")
            ).round(2),
            use_container_width=True,
            hide_index=True,
        )

        chart_data = grade_summary.copy()
        chart_data["觀察期間"] = chart_data["horizon_days"].map(lambda v: f"T+{int(v)}")
        fig = px.bar(
            chart_data,
            x="影響力等級",
            y="平均相對報酬率",
            color="觀察期間",
            barmode="group",
            category_orders={"影響力等級": ["S", "A", "B", "C", "未分級"], "觀察期間": ["T+1", "T+3", "T+5"]},
            title="各新聞等級的平均超額報酬（%）",
        )
        fig.add_hline(y=0, line_dash="dash", line_color="gray")
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("二、AI 新聞情緒與股價表現一致度")
        st.caption("AI 情緒是新聞整體方向，並非每檔股票獨立的方向預測。此處以相對大盤報酬作比較：利多看正報酬、利空看負報酬；中性以 ±0.5% 作為觀察區間。")
        directional = completed[completed["AI新聞情緒"].isin(["利多", "利空", "中性"])].copy()
        if directional.empty:
            st.info("目前完成資料尚無可用的利多／利空／中性 AI 情緒標籤。")
        else:
            directional["方向一致"] = False
            directional.loc[directional["AI新聞情緒"] == "利多", "方向一致"] = directional.loc[
                directional["AI新聞情緒"] == "利多", "relative_return_pct"
            ] > 0
            directional.loc[directional["AI新聞情緒"] == "利空", "方向一致"] = directional.loc[
                directional["AI新聞情緒"] == "利空", "relative_return_pct"
            ] < 0
            neutral_mask = directional["AI新聞情緒"] == "中性"
            directional.loc[neutral_mask, "方向一致"] = directional.loc[neutral_mask, "relative_return_pct"].abs() <= 0.5
            sentiment_summary = (
                directional.groupby(["AI新聞情緒", "horizon_days"])
                .agg(樣本數=("event_id", "count"), 一致比例=("方向一致", lambda x: x.mean() * 100),
                     平均相對報酬=("relative_return_pct", "mean"))
                .reset_index()
            )
            sentiment_summary["觀察期間"] = sentiment_summary["horizon_days"].map(lambda v: f"T+{int(v)}")
            st.dataframe(
                sentiment_summary[["AI新聞情緒", "觀察期間", "樣本數", "一致比例", "平均相對報酬"]].round(2),
                use_container_width=True,
                hide_index=True,
            )

        st.subheader("三、台股與美股績效比較")
        market_summary = (
            completed.groupby(["個股市場", "horizon_days"])
            .agg(樣本數=("event_id", "count"), 平均個股報酬=("stock_return_pct", "mean"),
                 平均相對報酬=("relative_return_pct", "mean"),
                 正報酬比例=("relative_return_pct", lambda x: (x > 0).mean() * 100))
            .reset_index()
        )
        market_summary["觀察期間"] = market_summary["horizon_days"].map(lambda v: f"T+{int(v)}")
        st.dataframe(
            market_summary[["個股市場", "觀察期間", "樣本數", "平均個股報酬", "平均相對報酬", "正報酬比例"]].round(2),
            use_container_width=True,
            hide_index=True,
        )

        with st.expander("查看納入統計的逐筆資料"):
            show_cols = ["published_at", "影響力等級", "個股市場", "headline", "stock_name", "ticker",
                         "AI新聞情緒", "horizon_days", "stock_return_pct", "relative_return_pct", "回顧狀態"]
            details = completed[[c for c in show_cols if c in completed.columns]].copy()
            details = details.rename(columns={"published_at": "新聞發布時間", "headline": "新聞標題",
                                              "stock_name": "公司", "ticker": "代號",
                                              "horizon_days": "觀察交易日", "stock_return_pct": "個股報酬率%",
                                              "relative_return_pct": "相對大盤報酬%"})
            details["觀察交易日"] = details["觀察交易日"].map(lambda v: f"T+{int(v)}")
            st.dataframe(details, use_container_width=True, hide_index=True)
            st.download_button(
                "下載目前篩選結果 CSV",
                data=details.to_csv(index=False).encode("utf-8-sig"),
                file_name="ai_market_radar_performance.csv",
                mime="text/csv",
            )

    with st.expander("統計口徑與注意事項"):
        st.markdown("""
        - 本頁只讀取既有資料，不會新增、更新或刪除資料庫內容，也不會呼叫 AI API。
        - S／A／B／C 是新聞研究優先級，不是投資評等；樣本數不足時不應過度解讀。
        - 報酬率以 Page 8 已保存的觀察值為準；未完成或缺少比較基準的資料不納入績效統計。
        - 相對大盤報酬為個股報酬率減去比較基準指數報酬率，並非新聞造成股價變動的因果證明。
        - AI 新聞情緒是新聞整體標籤，不等於每檔關聯股票的個別影響方向。
        - 中性一致度使用相對報酬介於 -0.5% 至 +0.5% 作為本頁統計門檻；這是分析口徑，不是既有 AI 模型設定。
        - 資料查詢最多讀取最近 20,000 筆觀察紀錄；若未來資料量超過此範圍，需再增加分頁查詢。
        """)
