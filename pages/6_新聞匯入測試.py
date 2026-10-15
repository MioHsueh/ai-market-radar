import os
import streamlit as st
from jobs.fetch_news import main as run_news_import

st.set_page_config(page_title="新聞匯入測試｜AI Market Radar", layout="wide")
st.title("📰 真實新聞匯入測試")
st.write("這個工具會從證交所官方 API 抓取台股新聞與上市公司重大訊息，並寫入 Supabase。若已設定美股 API 金鑰，也會一併抓取美股新聞。")
st.warning("第一次測試請手動執行。匯入結果會寫入資料庫；API 金鑰不會顯示在畫面上。")

key_exists = bool(os.getenv("STOCKNEWS_API_KEY"))
if not key_exists:
    try:
        key_exists = bool(st.secrets.get("STOCKNEWS_API_KEY", ""))
    except Exception:
        key_exists = False
if not key_exists:
    st.info("尚未設定 STOCKNEWS_API_KEY：本次只會抓取台股官方資料。")

if st.button("開始抓取並寫入 Supabase", type="primary"):
    with st.spinner("正在取得新聞並寫入資料庫，請稍候……"):
        try:
            run_news_import()
            st.success("新聞匯入工作已完成。請到 Supabase 的 public.news 檢查資料，並查看 public.job_runs 的執行紀錄。")
        except Exception as exc:
            st.error("新聞匯入工作失敗。")
            st.code(f"{type(exc).__name__}: {str(exc)[:1500]}")
