"""Presentation helpers for readable, source-faithful news cards."""
import re
from datetime import date, datetime


def _text(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def display_title(item):
    title = _text(item.get("title"))
    source = _text(item.get("source"))
    # Older imported TWSE rows accidentally used the ROC event date as the title.
    match = re.match(r"^\[(\d{4,6})\]\s*(\d{6,7})$", title)
    if match:
        code = match.group(1)
        if "重大訊息" in source or "證券交易所" in source:
            return f"上市公司重大訊息｜公司代號 {code}"
        return f"市場公告｜代碼 {code}"
    if not title or title.lower() in {"none", "null", "nan"}:
        return "未提供新聞標題"
    return title


def short_summary(item, limit=220):
    summary = _text(item.get("summary"))
    if not summary:
        return "來源未提供摘要；可開啟原文查看完整內容。"
    # Keep this as a clearly labelled excerpt, not an AI-generated summary.
    summary = re.sub(r"^(摘要|內容|說明)\s*[:：]\s*", "", summary)
    if len(summary) <= limit:
        return summary
    cut = summary[:limit]
    # Prefer stopping at a sentence boundary when one occurs in the first 80%.
    boundary = max(cut.rfind("。"), cut.rfind("；"), cut.rfind("！"), cut.rfind("？"))
    if boundary >= int(limit * 0.65):
        cut = cut[:boundary + 1]
    return cut.rstrip(" ，,；;。") + "……"


def format_datetime(value):
    if value is None or _text(value) == "":
        return "時間未提供"
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        return value.isoformat()
    else:
        raw = _text(value)
        # Handle ISO strings, including PostgreSQL UTC timestamps.
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            # ROC dates such as 1151014 are rendered as ROC calendar dates.
            m = re.fullmatch(r"(\d{2,3})(\d{2})(\d{2})", raw)
            if m:
                return f"民國{m.group(1)}年{int(m.group(2)):02d}月{int(m.group(3)):02d}日"
            return raw
    # Legacy rows may have parsed ROC year 115 as Gregorian year 0115.
    if 1 <= dt.year <= 300:
        dt = dt.replace(year=dt.year + 1911)
    if dt.tzinfo:
        # Display in Taiwan local time for this Taiwan-focused dashboard.
        from datetime import timezone, timedelta
        dt = dt.astimezone(timezone(timedelta(hours=8)))
    return dt.strftime("%Y-%m-%d %H:%M" if (dt.hour or dt.minute) else "%Y-%m-%d")


def market_label(market):
    return {"TW": "🇹🇼 台股", "US": "🇺🇸 美股"}.get(_text(market).upper(), _text(market) or "未分類")


def render_news_card(st, item, compact=False):
    title = display_title(item)
    summary = short_summary(item, 170 if compact else 240)
    with st.container(border=True):
        st.markdown(f"**{title}**")
        st.caption(
            f"{market_label(item.get('market'))}  ·  {format_datetime(item.get('published_at'))}  ·  "
            f"來源：{_text(item.get('source')) or '未提供'}"
        )
        st.write(summary)
        full = _text(item.get("summary"))
        if full and len(full) > (170 if compact else 240):
            with st.expander("查看完整公告內容"):
                st.write(full)
        url = _text(item.get("url"))
        if url.startswith(("https://", "http://")):
            st.link_button("閱讀原文 ↗", url)
