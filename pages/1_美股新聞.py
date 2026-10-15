import streamlit as st
from services.storage import load_recent_news

st.set_page_config(page_title="美股新聞｜AI Market Radar", layout="wide")
st.title("🇺🇸 美股新聞中心")
items = [x for x in load_recent_news(100) if x.get("market") == "US"]
if not items:
    st.info("目前沒有已儲存的美股新聞。請先設定新聞來源與排程。")
for item in items:
    with st.container(border=True):
        st.markdown(f"### {item.get('title', '無標題')}")
        st.caption(f"{item.get('published_at', '時間未知')}｜{item.get('source', '未知來源')}")
        st.write(item.get("summary", "尚無 AI 摘要。"))
        if item.get("url"):
            st.link_button("閱讀原文", item["url"])
