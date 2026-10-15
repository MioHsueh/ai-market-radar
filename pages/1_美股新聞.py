import streamlit as st
from services.storage import load_recent_news
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

st.set_page_config(page_title="美股新聞｜AI Market Radar", page_icon="🇺🇸", layout="wide")
st.title("🇺🇸 美股新聞中心")
today = datetime.now(TAIPEI_TZ).date()
st.caption(f"只顯示台灣時間今天（{today.isoformat()}）發布的美股新聞。")

try:
    all_items = [dict(x) for x in load_recent_news(500)]
except Exception as exc:
    st.error("目前無法讀取新聞資料，請確認 Supabase 連線設定。")
    st.caption(f"錯誤類型：{type(exc).__name__}")
    st.stop()

items = [x for x in all_items if str(x.get("market", "")).upper() == "US" and is_today_news(x)]
if not items:
    st.info("今天尚無符合條件的美股新聞，或來源尚未提供今天發布的文章。")
for item in items:
    with st.container(border=True):
        st.markdown(f"### {item.get('title', '無標題')}")
        st.caption(f"{item.get('published_at', '時間未知')}｜{item.get('source', '未知來源')}")
        st.write(item.get("summary", "尚無摘要。"))
        if item.get("url"):
            st.link_button("閱讀原文", item["url"])
