import streamlit as st
from services.storage import load_recent_news
from services.news_display import render_news_card
from datetime import datetime
from zoneinfo import ZoneInfo

TAIPEI_TZ = ZoneInfo("Asia/Taipei")

def is_today_news(item):
    value = item.get("published_at")
    if not value:
        return False
    try:
        if isinstance(value, datetime):
            dt = value
        else:
            dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TAIPEI_TZ)
        return dt.astimezone(TAIPEI_TZ).date() == datetime.now(TAIPEI_TZ).date()
    except (TypeError, ValueError, OverflowError):
        return False

st.set_page_config(page_title="台股新聞中心｜AI Market Radar", page_icon="🇹🇼", layout="wide")
st.title("🇹🇼 TW 台股新聞中心")
today = datetime.now(TAIPEI_TZ).date()
st.caption(f"只顯示台灣時間今天（{today.isoformat()}）發布的台股新聞。")

try:
    all_news = [dict(item) for item in load_recent_news(limit=500)]
except Exception as exc:
    st.error("目前無法讀取新聞資料，請確認 Supabase 連線設定。")
    st.caption(f"錯誤類型：{type(exc).__name__}")
    st.stop()

news = [
    item for item in all_news
    if str(item.get("market", "")).upper() == "TW" and is_today_news(item)
]
col1, col2 = st.columns([1, 2])
with col1:
    count = st.selectbox("顯示筆數", [10, 20, 50, 100], index=1)
with col2:
    query = st.text_input("搜尋標題或內容", placeholder="例如：營收、半導體、董事會")
if query.strip():
    q = query.strip().casefold()
    news = [item for item in news if q in str(item.get("title") or "").casefold() or q in str(item.get("summary") or "").casefold()]

st.caption(f"今天的台股新聞：顯示 {min(count, len(news))} / {len(news)} 筆")
if not news:
    st.info("今天尚無符合條件的台股新聞，或來源尚未提供今天發布的文章。")
else:
    for item in news[:count]:
        render_news_card(st, item, compact=False)

with st.expander("資料來源與閱讀說明"):
    st.write("新聞以原始來源的發布時間為準，僅顯示台灣時間今天發布的內容。")
    st.write("本網站提供資訊整理與研究輔助，不構成投資建議。")
