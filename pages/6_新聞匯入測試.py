import streamlit as st
from jobs.fetch_news import main as run_news_import
from datetime import datetime
from zoneinfo import ZoneInfo

st.set_page_config(page_title="新聞匯入測試｜AI Market Radar", layout="wide")
st.title("📰 真實新聞匯入測試")
today = datetime.now(ZoneInfo("Asia/Taipei")).date()
st.write(f"從一般財經新聞 RSS 來源匯入台股與美股新聞；目標日期為台灣時間今天（{today.isoformat()}）。")
st.warning("請勿重複按下匯入。只會匯入來源實際提供且發布日期為今天的新聞。")

if st.button("開始抓取並寫入 Supabase", type="primary"):
    status_box = st.status("準備開始匯入…", expanded=True)
    progress_text = st.empty()
    latest = {"message": "準備開始匯入…"}

    def report_progress(message):
        latest["message"] = message
        progress_text.info(message)
        status_box.update(label=message, state="running", expanded=True)

    try:
        result = run_news_import(progress_callback=report_progress)
        status_box.update(label="新聞匯入已完成", state="complete", expanded=False)
        st.success(result or "新聞匯入工作已完成。")
        st.info("請到 Supabase 的 public.news 檢查今日新聞，並查看 public.job_runs 的執行紀錄。")
    except Exception as exc:
        status_box.update(label="新聞匯入失敗", state="error", expanded=True)
        st.error("新聞匯入工作失敗，詳細原因如下：")
        st.code(f"{type(exc).__name__}: {str(exc)[:1500]}")
        st.caption(f"最後回報階段：{latest['message']}")
