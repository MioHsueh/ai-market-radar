
import json
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

import streamlit as st
from openai import OpenAI

from services.storage import (
    load_recent_news,
    load_recent_analyses,
    save_analysis,
)

TAIPEI = ZoneInfo("Asia/Taipei")
DEFAULT_MODEL = "gpt-4o-mini"


def _get_api_key():
    """優先讀取 Streamlit Secrets，再讀取環境變數。"""
    try:
        key = st.secrets.get("OPENAI_API_KEY", "")
    except Exception:
        key = ""

    return key or os.getenv("OPENAI_API_KEY", "")


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
            "尚未設定 OPENAI_API_KEY。請先到 Streamlit Cloud 的 Secrets 設定。"
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

    client = OpenAI(api_key=api_key)
    model = os.getenv("OPENAI_MODEL", DEFAULT_MODEL)

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
使用繁體中文，分析輸入的真實新聞。

規則：
1. 只依據提供的新聞內容分析，不得虛構財報、股價、數字或公司關係。
2. 明確區分新聞已確認的事實與 AI 推論。
3. 不確定的股票代號或產業關係應明確標示「待確認」。
4. 不可將可能影響寫成確定會發生的結果。
5. 相關股票應說明關聯依據；若沒有足夠依據，回傳空陣列。
6. watch_items 要列出可後續查證的觀察事項。
7. 每則新聞產生一筆分析，保留原始 source_url。
8. 回傳 JSON 物件，格式如下：
{
  "analyses": [
    {
      "id": 1,
      "headline": "分析標題",
      "summary": "事件摘要，並指出哪些是新聞已確認事實",
      "industry_impact": "可能的產業影響及推論依據",
      "related_stocks": [
        {
          "name": "公司名稱或代號",
          "market": "TW 或 US",
          "reason": "與事件的關聯依據",
          "evidence_type": "新聞事實或 AI 推論"
        }
      ],
      "watch_items": [
        "後續觀察事項"
      ]
    }
  ]
}
不要輸出 JSON 以外的文字。
"""

    response = client.chat.completions.create(
        model=model,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(input_news, ensure_ascii=False),
            },
        ],
    )

    content = response.choices[0].message.content
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
