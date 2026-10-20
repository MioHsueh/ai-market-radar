import streamlit as st
from services.storage import load_report_history
from services.market_summary import generate_daily_market_summary

st.set_page_config(page_title="歷史報告｜AI Market Radar", layout="wide")
st.title("🗓️ 每日市場總結與歷史報告")
st.caption("整理美股、台股、總經、產業影響與後續觀察；報告會保存至 daily_reports。")

with st.container(border=True):
    st.subheader("產生今日市場總結")
    st.write("使用今天（台灣時間）已匯入的新聞與資料庫 AI 分析，產生一份精簡市場總結。重新產生會更新今天的報告，不會新增重複日期。")
    if st.button("✨ 立即產生／更新今日市場總結", type="primary"):
        with st.spinner("正在整理今日新聞並產生市場總結…"):
            result = generate_daily_market_summary()
        if result.get("saved"):
            st.success(result["message"])
            st.caption(f"使用模型：{result.get('model')}｜參考新聞：{result.get('news_count')} 則")
            st.markdown(result.get("report", ""))
        else:
            st.error(result.get("message", "產生報告失敗。"))

st.divider()
st.subheader("📚 歷史報告")
try:
    reports = load_report_history(60)
except Exception as exc:
    st.error("無法讀取歷史報告，請確認 Supabase 連線與 daily_reports 資料表。")
    st.caption(f"錯誤類型：{type(exc).__name__}")
    st.stop()

if not reports:
    st.info("目前沒有歷史報告。請先產生今日市場總結。")
for report in reports:
    with st.expander(f"{report.get('report_date', '日期未知')}｜{report.get('title', '每日市場報告')}"):
        st.caption(f"更新時間：{report.get('updated_at', '未知')}")
        st.markdown(report.get("market_summary", "尚無摘要。"))
