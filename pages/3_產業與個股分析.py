import streamlit as st
from services.storage import load_recent_analyses

st.set_page_config(page_title="產業與個股分析｜AI Market Radar", layout="wide")
st.title("🔎 產業與個股影響分析")
st.caption("每個分析應區分已確認事實與 AI 推論，並保留原始新聞來源。")
analyses = load_recent_analyses(50)
if not analyses:
    st.info("目前沒有分析紀錄。完成 AI API 設定與每日排程後，分析結果會顯示於此。")
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
