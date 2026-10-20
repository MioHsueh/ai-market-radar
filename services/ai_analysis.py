
import json
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

import streamlit as st
from google import genai
from google.genai import types

from services.storage import (
    load_recent_news,
    load_recent_analyses,
    save_analysis,
)

TAIPEI = ZoneInfo("Asia/Taipei")
DEFAULT_MODEL = "gemini-3.5-flash-lite"

def _get_api_key():
    """優先讀取 Streamlit Secrets，再讀取環境變數。"""
    try:
        key = st.secrets.get("GEMINI_API_KEY", "")
    except Exception:
        key = ""

    return key or os.getenv("GEMINI_API_KEY", "")


def _to_taipei_date(value):
    """將資料庫時間轉成台灣日期。"""
    if not value:
        return None

    try:
        if isinstance(value, datetime):
            dt = value
        else:
            dt = datetime.fromisoformat(
                str(value).strip().replace("Z", "+00:00")
            )

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TAIPEI)

        return dt.astimezone(TAIPEI).date()
    except (TypeError, ValueError, OverflowError):
        return None


def load_today_news(limit=200):
    """只取台灣時間今天發布的新聞。"""
    today = datetime.now(TAIPEI).date()
    news = load_recent_news(limit=limit)

    result = []
    seen = set()

    for item in news:
        published_date = _to_taipei_date(item.get("published_at"))

        if published_date != today:
            continue

        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()

        if not title:
            continue

        # 基本去重：相同網址或相同標題不重複送給 AI。
        key = url or title.casefold()
        if key in seen:
            continue

        seen.add(key)
        result.append({
            "market": item.get("market", ""),
            "title": title,
            "summary": str(item.get("summary") or "")[:1500],
            "source": item.get("source", ""),
            "url": url,
            "published_at": str(item.get("published_at") or ""),
        })

    return result


def _parse_json_response(content):
    """解析模型回傳的 JSON。"""
    content = (content or "").strip()

    if content.startswith("```"):
        content = content.split("\n", 1)[-1]
        if content.endswith("```"):
            content = content[:-3].strip()

    data = json.loads(content)

    if isinstance(data, dict):
        data = data.get("analyses", [])

    if not isinstance(data, list):
        raise ValueError("AI 回傳格式不是分析清單。")

    return data


def generate_today_analyses(max_articles=10):
    """
    分析今天的新聞並寫入 public.analyses。

    max_articles 預設 10，避免一次分析過多新聞而產生高額 API 費用。
    """
    api_key = _get_api_key()
    if not api_key:
        raise RuntimeError(
            "尚未設定 GEMINI_API_KEY。請到 Streamlit Cloud → Settings → Secrets 設定。"
        )

    today = datetime.now(TAIPEI).date()
    news = load_today_news(limit=300)

    if not news:
        return {
            "saved": 0,
            "skipped": 0,
            "message": f"台灣時間 {today} 尚無符合日期的新聞。",
        }

    # 先排除今天已經分析過的來源網址，避免重複執行時重複寫入。
    existing = load_recent_analyses(limit=500)
    existing_urls = set()

    for item in existing:
        created_date = _to_taipei_date(item.get("created_at"))
        source_url = str(item.get("source_url") or "").strip()

        if created_date == today and source_url:
            existing_urls.add(source_url)

    pending = [
        item for item in news
        if not item["url"] or item["url"] not in existing_urls
    ]

    # 控制每次執行的 API 用量。
    pending = pending[:max(1, int(max_articles))]

    if not pending:
        return {
            "saved": 0,
            "skipped": len(news),
            "message": "今天的新聞已經有分析紀錄，沒有新增分析。",
        }

    client = genai.Client(api_key=api_key)
    model = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)

    input_news = []
    for index, item in enumerate(pending, start=1):
        input_news.append({
            "id": index,
            "market": item["market"],
            "title": item["title"],
            "summary": item["summary"],
            "source": item["source"],
            "url": item["url"],
            "published_at": item["published_at"],
        })


    system_prompt = """
你是 AI Market Radar 的金融新聞分析助手。
請使用繁體中文，分析輸入的真實新聞，並且每則新聞只產生一筆分析。

【一、事實與推論】
1. 只根據提供的標題、摘要與來源分析，不得虛構財報、股價、數字或公司關係。
2. summary 必須先寫新聞已確認的事實，再寫尚未證實的部分。
3. industry_impact 必須分成「已知事實」與「可能影響／推論」，並說明推論依據。
4. 不可把可能的影響寫成確定會發生的結果。

【二、產業分類】
1. 每則新聞都要判定一個主要產業。
2. industry 只能從以下分類選擇：
   - AI與半導體
   - 電子硬體與供應鏈
   - 軟體與雲端
   - 通訊與網路
   - 金融
   - 傳統產業
   - 能源與原物料
   - 總經與政策
   - 市場與投資
   - 其他
3. 依新聞的主要事件分類，不要只因為提到某家公司，就把整則新聞歸入該公司的產業。
4. 如果資訊不足，選擇「其他」，並在 summary 說明原因。

【三、相關股票】
1. 只列出與新聞事件有明確關聯的公司。
2. 不可只因公司知名、同產業或曾經合作，就認定與事件有關。
3. 股票代號只有在提供的新聞內容能確認時才填寫；不確定時標示待確認，不得猜測。
4. 每檔股票都要提供 reason，說明新聞與公司的具體關聯。
5. 若沒有足夠證據，related_stocks 回傳空陣列。
6. market 只能填 TW 或 US；無法確認時不要猜測。

【四、個股影響與消息方向】
1. sentiment 只能是「利多」、「利空」、「中性」或「資訊不足」。
2. sentiment_reason 必須簡短說明判斷理由，且要能對應新聞內容。
3. sentiment_evidence 必須摘述標題或摘要中支持判斷的具體事實；不得編造引文。
4. 以新聞事件對相關公司的基本面／市場預期可能造成的影響判讀，不要把新聞語氣直接等同股價方向。
5. 同一事件可能同時有正反面影響時，判為「中性」並說明兩面因素；證據不足時判為「資訊不足」。
6. sentiment_confidence 只能是「高」、「中」、「低」。若新聞只有標題或缺乏具體事實，信心應偏低。
7. related_stocks 只列明確涉及或有具體證據可支持關聯的公司。把「新聞直接提及」與「可能的間接影響」分開說明；沒有足夠證據就回傳空陣列。
8. 每檔股票需提供 impact_direction（利多／利空／中性／資訊不足）及 reason。不得因同產業就直接認定受惠或受害。

【五、後續觀察】
1. watch_items 必須是可查證的後續觀察事項。
2. 不要將一般性的投資建議當成新聞事實。
3. 不得承諾股價方向或報酬。

【六、輸出格式】
只輸出合法 JSON，不要輸出其他文字。
每則新聞必須保留輸入的 id，且不可增加不存在的新聞。

{
  "analyses": [
    {
      "id": 1,
      "headline": "分析標題",
      "summary": "已確認事實與必要的資訊限制",
      "industry": "上述分類之一",
      "sentiment": "利多／利空／中性／資訊不足",
      "sentiment_reason": "判斷理由",
      "sentiment_evidence": "新聞內容中的具體依據",
      "sentiment_confidence": "高／中／低",
      "industry_impact": "已知事實、可能影響、推論依據",
      "related_stocks": [
        {
          "name": "公司名稱",
          "ticker": "已確認的股票代號，否則填待確認",
          "market": "TW 或 US",
          "relation_type": "新聞直接提及／有證據支持的間接影響",
          "impact_direction": "利多／利空／中性／資訊不足",
          "reason": "具體關聯與可能影響原因",
          "evidence_type": "新聞事實或 AI 推論",
          "evidence": "支持此關聯的新聞依據"
        }
      ],
      "watch_items": [
        "可查證的後續觀察事項"
      ]
    }
  ]
}
"""


    response = client.models.generate_content(
        model=model,
        contents=(
            system_prompt
            + "\n\n以下是待分析新聞的 JSON 資料。請依照上方規則，只回傳 JSON：\n"
            + json.dumps(input_news, ensure_ascii=False)
        ),
        config=types.GenerateContentConfig(
            temperature=0.2,
            response_mime_type="application/json",
        ),
    )

    content = response.text
    analyses = _parse_json_response(content)

    news_by_id = {
        index: item
        for index, item in enumerate(pending, start=1)
    }

    saved = 0
    errors = []

    for result in analyses:
        try:
            index = int(result.get("id", 0))
            source = news_by_id.get(index)

            if not source:
                continue

            related_stocks = result.get("related_stocks", [])
            watch_items = result.get("watch_items", [])

            if not isinstance(related_stocks, list):
                related_stocks = []
            if not isinstance(watch_items, list):
                watch_items = []

            save_analysis({
                "headline": str(
                    result.get("headline") or source["title"]
                )[:300],
                "summary": str(result.get("summary") or ""),
                "industry": str(result.get("industry") or "其他"),
                "sentiment": str(result.get("sentiment") or "資訊不足"),
                "sentiment_reason": str(result.get("sentiment_reason") or "未提供明確判讀理由"),
                "sentiment_evidence": str(result.get("sentiment_evidence") or "新聞未提供足夠的具體依據"),
                "sentiment_confidence": str(result.get("sentiment_confidence") or "低"),
                "industry_impact": str(
                    result.get("industry_impact") or ""
                ),
                "related_stocks": related_stocks,
                "watch_items": watch_items,
                "source_url": source["url"] or None,
            })
            saved += 1

        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {str(exc)[:200]}")

    message = f"完成：新增 {saved} 筆分析。"
    if errors:
        message += f" 另有 {len(errors)} 筆寫入失敗。"

    return {
        "saved": saved,
        "skipped": len(news) - len(pending),
        "message": message,
        "errors": errors,
    }
