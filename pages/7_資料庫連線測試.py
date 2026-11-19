import streamlit as st
from services.storage import check_database, save_job_run

st.set_page_config(page_title="資料庫連線測試｜AI Market Radar", layout="wide")
st.title("🛠️ 資料庫連線測試")
st.write("此頁使用伺服器端 DATABASE_URL 測試 Supabase PostgreSQL，不會顯示密碼或完整連線字串。")
if st.button("測試 Supabase 連線", type="primary"):
    ok, message = check_database()
    if ok:
        st.success(message)
        try:
            save_job_run("manual_database_test", "success", "Streamlit database connection test succeeded.")
            st.info("測試紀錄已寫入 job_runs 資料表。")
        except Exception as exc:
            st.warning(f"連線成功，但寫入測試紀錄失敗：{type(exc).__name__}: {str(exc).splitlines()[0][:180]}")
    else:
        st.error(message)
        st.caption("請確認 DATABASE_URL、密碼、連線模式及資料庫狀態。不要公開完整連線字串。")
