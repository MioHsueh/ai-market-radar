"""Generate and save a daily market summary using the configured Gemini API."""
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st
from google import genai

from services.storage import load_news_for_date_range, load_recent_analyses, save_daily_report

TAIPEI = ZoneInfo("Asia/Taipei")
DEFAULT_MODEL = "gemini-3.5-flash-lite"


def _api_key():
    try:
        key = st.secrets.get("GEMINI_API_KEY", "")
    except Exception:
        key = ""
    return key or os.getenv("GEMINI_API_KEY", "")


def generate_daily_market_summary():
    """Summarize today's Taiwan-local news and saved AI analyses, then upsert report."""
    today = datetime.now(TAIPEI).date()
    news = load_news_for_date_range(today, today, limit=500)
    if not news:
        return {"saved": False, "message": f"台灣時間 {today} 尚無今日新聞，未產生報告。"}

    key = _api_key()
    if not key:
        return {"saved": False, "message": "找不到 GEMINI_API_KEY，請確認 Streamlit Secrets 設定。"}

    analyses = load_recent_analyses(limit=300)
    # Keep the prompt compact; source facts are taken only from stored records.
    news_lines = []
    for item in news:
        news_lines.append(
            f"[{item.get('market') or '市場未標示'}] {item.get('title') or ''}\n"
            f"摘要：{item.get('summary') or '無摘要'}\n來源：{item.get('source') or '未知'}\n"
            f"網址：{item.get('url') or '無'}"
        )
    analysis_lines = []
    for item in analyses:
        analysis_lines.append(
            f"標題：{item.get('headline') or ''}\n摘要：{item.get('summary') or ''}\n"
            f"產業影響：{item.get('industry_impact') or ''}\n"
            f"相關股票：{item.get('related_stocks') or ''}\n觀察重點：{item.get('watch_items') or ''}"
        )

    prompt = f"""你是 AI Market Radar 的資深市場研究編輯。請根據提供的新聞與資料庫 AI 分析，撰寫「{today} 每日市場總結」。讀者是想快速掌握市場、產業與公司風險的研究者。使用繁體中文，清楚、務實、不誇大。

請嚴格依照以下結構輸出 Markdown：
# {today} 每日市場總結
## 先看結論
用 3 個 bullet points 摘要今日最值得注意的事。若資料無法支持 3 點，請少寫，不要湊數。
## 一、今日最重要的市場事件
列出最多 5 件，依重要性排序。每件包含「已知事實」「為何重要」「目前還不知道什麼」。不要把同一事件的不同媒體報導當成多個獨立事件。
## 二、美股與台股分開觀察
### 美股
### 台股
只整理輸入資料有支持的內容；若其中一個市場缺乏新聞或資訊，明確寫出資料不足，不可推測市場當日漲跌。
## 三、產業影響與相關公司
以表格呈現：產業／相關公司（僅限資料明確提及或有清楚依據者）／新聞事實／可能影響與推論依據／信心程度（高、中、低）。不得只因公司被提及就說它受惠或受害；若關聯薄弱，標示「關聯待確認」。
## 四、利多、利空與股價影響要分開看
分別列出可能偏正面、可能偏負面、方向不明的事件。每項說明：新聞本身的方向、可能的股價傳導機制、可能抵銷因素。沒有證據可推論股價反應時，明確寫「無法僅憑此新聞判斷股價方向」。
## 五、接下來值得追蹤的事項
列出最多 5 項，包含「觀察事項」「為什麼重要」「何種新資訊會改變目前判斷」。只列資料中已提及或合理直接衍生的事項；不可捏造尚未公布的日期或事件。
## 六、資料品質與限制
說明本報告依據的新聞數量、AI 分析紀錄是否足夠、缺少哪些關鍵資料（例如實際股價、成交量、公司公告或財報），以及哪些結論只能視為初步推論。

分析規則：
1. 只能依據下方資料，不得自行補入外部事實，不得捏造股價、漲跌幅、財報數字、公司關係、事件日期或市場表現。
2. 優先找出有具體事件、數字、官方公告或清楚來源支持的新聞；標題聳動但摘要證據不足時，降低信心並指出限制。
3. 將「已確認事實」「分析推論」「未知／待確認」明確分開。推論需寫出推論鏈，不可只下結論。
4. 區分新聞情緒與股價反應。利多消息仍可能已被市場反映、低於預期，或被其他因素抵銷；不得寫成必漲／必跌。
5. 不要把重複報導算成多個獨立證據，也不要因資料筆數多就宣稱趨勢確立。
6. 沒有足夠證據時，直接寫「目前資料不足，無法判斷」，不要用一般市場常識填補缺口。
7. 不提供個人化買賣指令、目標價或沒有資料支持的投資建議。
8. 內容以有用、具體為主，避免空泛套話；不確定的地方要明確標示。

【今日新聞，共 {len(news)} 則】
{chr(10).join(news_lines)}

【資料庫中最近的 AI 分析】
{chr(10).join(analysis_lines) if analysis_lines else '目前沒有可用的 AI 分析紀錄。'}
"""
    model = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
    try:
        client = genai.Client(api_key=key)
        response = client.models.generate_content(model=model, contents=prompt)
        summary = (getattr(response, "text", None) or "").strip()
        if not summary:
            return {"saved": False, "message": "Gemini 沒有回傳報告內容，請稍後重試。"}
        save_daily_report({
            "report_date": today,
            "title": f"{today} 每日市場總結",
            "market_summary": summary,
        })
        return {"saved": True, "message": f"已儲存 {today} 每日市場總結。", "report": summary, "news_count": len(news), "model": model}
    except Exception as exc:
        return {"saved": False, "message": f"產生或儲存報告失敗：{type(exc).__name__}: {str(exc)[:300]}"}
