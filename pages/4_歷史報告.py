import streamlit as st
from services.storage import load_report_history

st.set_page_config(page_title="歷史報告｜AI Market Radar", layout="wide")
st.title("🗓️ 每日報告與歷史紀錄")
reports = load_report_history(60)
if not reports:
    st.info("目前沒有歷史報告。")
for report in reports:
    with st.expander(f"{report.get('report_date', '日期未知')}｜{report.get('title', '每日市場報告')}"):
        st.caption(f"更新時間：{report.get('updated_at', '未知')}")
        st.markdown(report.get("market_summary", "尚無摘要。"))
