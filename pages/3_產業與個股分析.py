import streamlit as st
from services.storage import load_recent_analyses
from datetime import datetime
from zoneinfo import ZoneInfo
from services.ai_analysis import generate_today_analyses

if st.button("🤖 分析今天新聞", type="primary"):
    with st.spinner("AI 正在分析今天的新聞，請稍候…"):
        try:
            result = generate_today_analyses(max_articles=10)
            st.success(result["message"])
            st.rerun()
        except Exception as exc:
            st.error("AI 分析失敗")
            st.code(f"{type(exc).__name__}: {str(exc)[:1000]}")

st.set_page_config(page_title="產業與個股分析｜AI Market Radar", layout="wide")
st.title("🔎 產業與個股影響分析")
st.caption("僅顯示台灣時間今天建立的分析；每個分析應區分已確認事實與 AI 推論，並保留原始新聞來源。")
today = datetime.now(ZoneInfo("Asia/Taipei")).date()

def is_today_analysis(item):
    value = item.get("created_at")
    if not value:
        return False
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("Asia/Taipei"))
        return dt.astimezone(ZoneInfo("Asia/Taipei")).date() == today
    except (TypeError, ValueError, OverflowError):
        return False

analyses = [x for x in load_recent_analyses(100) if is_today_analysis(x)]
if not analyses:
    st.info("今天尚無分析紀錄。")
for item in analyses:
    with st.container(border=True):
        st.markdown(f"### {item.get('headline', '未命名分析')}")
        st.write("**事件摘要**")
        st.write(item.get("summary", "—"))
        st.write("**可能的產業影響**")
        st.write(item.get("industry_impact", "—"))
        st.write("**相關股票與關聯依據**")
        st.write(item.get("related_stocks", "—"))
        st.write("**後續觀察重點**")
        st.write(item.get("watch_items", "—"))
        if item.get("source_url"):
            st.link_button("查看原始來源", item["source_url"])
