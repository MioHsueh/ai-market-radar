import streamlit as st
from services.storage import load_recent_news
from services.news_display import render_news_card, format_datetime

st.set_page_config(page_title="台股新聞中心｜AI Market Radar", page_icon="🇹🇼", layout="wide")
st.title("🇹🇼 TW 台股新聞中心")
st.caption("標題優先使用官方公告主旨；摘要為公告內容摘錄，請以原始公告為準。")

try:
    all_news = [dict(item) for item in load_recent_news(limit=200)]
except Exception as exc:
    st.error("目前無法讀取新聞資料，請確認 Supabase 連線設定。")
    st.caption(f"錯誤類型：{type(exc).__name__}")
    st.stop()

news = [item for item in all_news if str(item.get("market", "")).upper() == "TW"]
col1, col2 = st.columns([1, 2])
with col1:
    count = st.selectbox("顯示筆數", [10, 20, 50, 100], index=1)
with col2:
    query = st.text_input("搜尋標題或公告內容", placeholder="例如：董事會、股利、營收、半導體")
if query.strip():
    q = query.strip().casefold()
    news = [item for item in news if q in str(item.get("title") or "").casefold() or q in str(item.get("summary") or "").casefold()]

st.caption(f"目前顯示 {min(count, len(news))} / {len(news)} 筆符合條件的台股新聞")
if not news:
    st.info("沒有符合條件的新聞，請調整搜尋字詞。")
else:
    for item in news[:count]:
        render_news_card(st, item, compact=False)

with st.expander("資料來源與閱讀說明"):
    st.write("上市公司重大訊息標題優先取自臺灣證券交易所 OpenAPI 的「主旨」欄位；公告內容來自「說明」欄位。若是舊資料，資料庫可能只保留舊標題，畫面會以公司代號作為中性替代標題。")
    st.write("官方公告文字為原始揭露內容，畫面整理僅改善可讀性，不代表 AI 對公告作出解讀，也不構成投資建議。")
