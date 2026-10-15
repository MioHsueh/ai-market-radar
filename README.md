# AI Market Radar

獨立的美股＋台股每日市場新聞與趨勢分析網站。

## 功能骨架
- Streamlit 首頁與美股、台股、產業分析、歷史報告頁
- 每日排程工作流程（GitHub Actions）
- 儲存層介面（目前為本機 JSON 開發模式）
- 明確顯示尚未設定資料來源的狀態，不會製造假新聞

## 本機啟動
```bash
python -m venv .venv
# macOS/Linux
source .venv/bin/activate
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## 上線前必做
1. 選定並確認新聞 API 的授權、額度、台股涵蓋範圍。
2. 將 `services/storage.py` 改為 PostgreSQL/Supabase 持久化存取。
3. 實作 `jobs/daily_update.py` 的資料擷取、去重、分析、驗證與儲存流程。
4. 在 GitHub Repository Settings → Secrets and variables → Actions 設定金鑰。
5. 部署 Streamlit Community Cloud，設定必要 secrets。
6. 在 GitHub Actions 手動執行一次，檢查日誌與資料庫結果，再啟用正式排程。

## 資料品質規則
- 保留來源 URL、發布時間、擷取時間與分析時間。
- 區分新聞事實與 AI 推論。
- 來源失敗或資料過舊時明確顯示，不得將舊資料標成今日資料。
- 不將 API 金鑰寫入程式碼或提交到 Git。
- 本專案不構成投資建議。
