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

    prompt = f"""你是 AI Market Radar 的每日市場研究編輯。請用繁體中文，根據下方提供的真實新聞與已儲存分析，撰寫「{today} 每日市場總結」。

請依序使用 Markdown 標題輸出：
## 一、今日市場重點（3–5 點，若資料不足就少寫，不可湊數）
## 二、美股與台股觀察（分開說明；沒有資料請明確註明）
## 三、產業影響與相關公司（每項附新聞事實及推論依據）
## 四、潛在利多／利空與不確定性（區分新聞方向和股價影響；不得宣稱股價必漲或必跌）
## 五、接下來值得觀察的事件
## 六、資料限制

規則：
1. 只使用提供資料，不得捏造股價、漲跌幅、財報、日期、公司關係或事件。
2. 清楚區分「新聞已確認事實」與「可能影響／推論」。
3. 不要把公司被提及等同於受惠，也不要把利多新聞等同股價必漲。
4. 沒有足夠證據時，直接寫「目前資料不足，無法判斷」。
5. 內容要精簡、可供每日閱讀；不要給個人化買賣指令。

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
