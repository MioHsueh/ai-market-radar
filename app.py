import streamlit as st
from services.storage import load_latest_report, load_recent_news

st.set_page_config(page_title="AI Market Radar", page_icon="🌐", layout="wide")
st.title("🌐 AI Market Radar")
st.caption("美股 × 台股｜每日市場新聞與趨勢情報")

report = load_latest_report()
news = load_recent_news(limit=10)

if report:
    st.subheader("今日市場總覽")
    st.caption(f"報告日期：{report.get('report_date', '未提供')}｜更新時間：{report.get('updated_at', '未提供')}")
    st.markdown(report.get("market_summary", "目前尚無市場摘要。"))
else:
    st.info("尚未有每日報告。完成 API 與資料庫設定後，排程工作會自動產生報告。")

left, right = st.columns(2)
with left:
    st.subheader("🇺🇸 美股觀察")
    st.write("總經、聯準會、科技巨頭財報、半導體與 AI 產業。")
with right:
    st.subheader("🇹🇼 台股觀察")
    st.write("大盤、上市櫃重大訊息、半導體與台灣供應鏈。")

st.subheader("近期新聞")
if news:
    for item in news:
        with st.container(border=True):
            st.markdown(f"**{item.get('title', '無標題')}**")
            st.caption(f"{item.get('market', '未分類')}｜{item.get('published_at', '時間未知')}｜來源：{item.get('source', '未知')}")
            st.write(item.get("summary", "尚無摘要。"))
            if item.get("url"):
                st.link_button("閱讀原文", item["url"])
else:
    st.info("目前沒有已儲存的新聞。尚未連接資料來源前，這是正常狀態。")

st.caption("本網站提供資訊整理與研究輔助，不構成投資建議。請核對原始來源與資料時間。")
