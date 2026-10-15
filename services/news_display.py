"""Readable, source-faithful presentation helpers for AI Market Radar."""
import re
from datetime import date, datetime, timezone, timedelta


def _text(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def display_title(item):
    title = _text(item.get("title"))
    source = _text(item.get("source"))
    # Legacy rows stored company code + ROC date instead of the actual subject.
    match = re.match(r"^\[(\d{4,6})\]\s*(\d{6,7})$", title)
    if match:
        code = match.group(1)
        if "重大訊息" in source or "證券交易所" in source:
            return f"上市公司重大訊息｜公司代號 {code}"
        return f"市場公告｜代碼 {code}"
    if not title or title.lower() in {"none", "null", "nan"}:
        return "未提供新聞標題"
    # Remove duplicated company-code prefix from title, if the code is separately visible.
    title = re.sub(r"^\[\d{4,6}\]\s*", "", title)
    return title


def _clean_announcement_text(text):
    text = _text(text)
    # Remove common field labels and numbered separators without rewriting facts.
    text = re.sub(r"^(?:摘要|內容|說明|公告內容)\s*[:：]\s*", "", text)
    text = re.sub(r"\s*\d+\s*[.、．]\s*(?=(?:事實發生日|發生緣由|因應措施|交易數量|每單位價格|交易總金額|董事會決議|公告事項|說明|主旨))", "｜", text)
    text = re.sub(r"(?:\s*[｜|]\s*){2,}", "｜", text)
    return text.strip(" ｜|，,；;。")


def short_summary(item, limit=220):
    raw = _text(item.get("summary"))
    if not raw:
        return "來源未提供可用摘要，請開啟原文查看完整公告。"
    summary = _clean_announcement_text(raw)
    if not summary:
        return "來源未提供可用摘要，請開啟原文查看完整公告。"
    if len(summary) <= limit:
        return summary
    # Prefer a natural sentence boundary in the last third of the excerpt.
    cut = summary[:limit]
    boundary = max(cut.rfind("。"), cut.rfind("；"), cut.rfind("！"), cut.rfind("？"), cut.rfind("｜"))
    if boundary >= int(limit * 0.55):
        cut = cut[:boundary + 1]
    return cut.rstrip(" ，,；;。｜") + "……"


def full_summary(item):
    return _clean_announcement_text(item.get("summary"))


def format_datetime(value):
    if value is None or _text(value) == "":
        return "時間未提供"
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        return value.isoformat()
    else:
        raw = _text(value)
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            m = re.fullmatch(r"(\d{2,3})(\d{2})(\d{2})", raw)
            if m:
                return f"民國{m.group(1)}年{int(m.group(2)):02d}月{int(m.group(3)):02d}日"
            return raw
    if 1 <= dt.year <= 300:
        dt = dt.replace(year=dt.year + 1911)
    if dt.tzinfo:
        dt = dt.astimezone(timezone(timedelta(hours=8)))
    return dt.strftime("%Y-%m-%d %H:%M" if (dt.hour or dt.minute) else "%Y-%m-%d")


def market_label(market):
    return {"TW": "🇹🇼 台股", "US": "🇺🇸 美股"}.get(_text(market).upper(), _text(market) or "未分類")


def render_news_card(st, item, compact=False):
    title = display_title(item)
    summary = short_summary(item, 170 if compact else 240)
    full = full_summary(item)
    with st.container(border=True):
        st.markdown(f"**{title}**")
        st.caption(
            f"{market_label(item.get('market'))}  ·  {format_datetime(item.get('published_at'))}  ·  "
            f"來源：{_text(item.get('source')) or '未提供'}"
        )
        st.write(summary)
        if full and len(full) > (170 if compact else 240):
            with st.expander("查看完整公告內容"):
                st.write(full)
        url = _text(item.get("url"))
        if url.startswith(("https://", "http://")):
            st.link_button("閱讀原文 ↗", url)
