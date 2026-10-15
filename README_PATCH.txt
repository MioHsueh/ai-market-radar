AI Market Radar：新聞標題、摘要與首頁排版改善補丁

這是增量補丁，不是完整專案。請在 GitHub 的 ai-market-radar 專案根目錄套用：

1. 覆蓋根目錄 app.py
2. 新增 services/news_display.py
3. 覆蓋 jobs/fetch_news.py
4. 不要覆蓋 services/storage.py、requirements.txt、Streamlit Secrets 或其他 pages。
5. 將修改 commit 到 main，等待 Streamlit Community Cloud 自動部署。
6. 先開首頁檢查新排版。確認後再進「新聞匯入測試」按一次匯入，修正匯入程式會讓新抓取的上市公司公告優先使用「主旨」，不再把「事實發生日」當成標題。

改動說明：
- 首頁增加新聞總數、美股/台股計數、每日報告區、市場篩選、搜尋與顯示筆數。
- 長公告改成短摘錄，較長內容放在「查看完整公告內容」展開區。
- 舊資料若標題是 [公司代號] 民國日期，顯示成「上市公司重大訊息｜公司代號 XXXX」；舊資料原本沒有正確主旨欄位時，無法從 UI 猜回真正標題。修正匯入程式後新抓取資料會優先用主旨。
- 顯示的短摘要只是原文摘錄，不會假稱為 AI 生成摘要。
- API 請求設定連線/讀取逾時，日期會將常見民國日期轉成西元日期。

安全提醒：不要把 DATABASE_URL 或任何 API 金鑰貼到 GitHub 程式碼中；維持放在 Streamlit Cloud → Settings → Secrets。
