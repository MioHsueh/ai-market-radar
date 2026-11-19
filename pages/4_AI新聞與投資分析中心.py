import streamlit as st

from services.analysis_center import industry, news_stock, performance

st.set_page_config(page_title="AI 新聞與投資分析中心｜AI Market Radar", page_icon="🧠", layout="wide")
st.title("🧠 AI 新聞與投資分析中心")
st.caption("整合原產業與個股分析、新聞影響力與股價回顧、AI 分析績效。各功能沿用原有資料讀取與計算邏輯。")

tab1, tab2, tab3 = st.tabs(["產業與個股分析", "新聞影響力與股價回顧", "AI 分析績效"])
with tab1:
    industry.render()
with tab2:
    news_stock.render()
with tab3:
    performance.render()
