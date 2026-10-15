"""Shared display helpers for source-faithful market news."""
import re
from datetime import date, datetime, timezone, timedelta


def clean_text(value):
    if value is None:
        return ""
    text = str(value).replace("\u3000", " ").replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    return text.strip()


def display_title(item):
    title = clean_text(item.get("title"))
    source = clean_text(item.get("source"))
    # Old rows used a date as the title: [1235] 1151014.
    match = re.fullmatch(r"\[(\d{4,6})\]\s*(\d{6,7})", title)
    if match:
        code = match.group(1)
        # We cannot reconstruct the real subject from the legacy title alone.
        return f"上市公司重大訊息｜公司代號 {code}"
    if not title or title.lower() in {"none", "null", "nan"}:
        return "未提供新聞標題"
    # Avoid repeating the company code if an older title already has a bracket prefix.
    return title


def _strip_boilerplate(text):
    text = clean_text(text)
    text = re.sub(r"^(?:摘要|內容|說明)\s*[:：]\s*", "", text)
    # Normalize the common numbered disclosure fields for readability, without
    # deleting their meaning or asserting a generated interpretation.
    text = re.sub(r"(?<!\d)(\d{1,2})\s*[.．、]\s*", r"\n\1. ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def short_summary(item, limit=220):
    summary = _strip_boilerplate(item.get("summary"))
    if not summary:
        return "來源未提供摘要；請開啟原文查看完整資訊。"
    # Display the first coherent field(s); this is an excerpt, not an AI summary.
    one_line = re.sub(r"\s*\n\s*", " ", summary)
    one_line = re.sub(r"\s+", " ", one_line).strip()
    if len(one_line) <= limit:
        return one_line
    cut = one_line[:limit]
    boundary = max(cut.rfind("。"), cut.rfind("；"), cut.rfind("！"), cut.rfind("？"))
    if boundary >= int(limit * 0.55):
        cut = cut[:boundary + 1]
    return cut.rstrip(" ，,；;。") + "……"


def full_content(item):
    return _strip_boilerplate(item.get("summary"))


def format_datetime(value):
    if value is None or clean_text(value) == "":
        return "時間未提供"
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        return value.isoformat()
    else:
        raw = clean_text(value)
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            digits = re.sub(r"\D", "", raw)
            if len(digits) == 7:  # ROC yyyMMdd
                return f"民國{int(digits[:3])}年{int(digits[3:5]):02d}月{int(digits[5:]):02d}日"
            return raw
    if 1 <= dt.year <= 300:
        dt = dt.replace(year=dt.year + 1911)
    if dt.tzinfo:
        dt = dt.astimezone(timezone(timedelta(hours=8)))
    return dt.strftime("%Y-%m-%d %H:%M" if (dt.hour or dt.minute) else "%Y-%m-%d")


def market_label(market):
    return {"TW": "🇹🇼 台股", "US": "🇺🇸 美股"}.get(clean_text(market).upper(), clean_text(market) or "未分類")


def render_news_card(st, item, compact=False):
    title = display_title(item)
    summary = short_summary(item, 220 if compact else 300)
    with st.container(border=True):
        st.markdown(f"**{title}**")
        st.caption(f"{market_label(item.get('market'))} · {format_datetime(item.get('published_at'))} · 來源：{clean_text(item.get('source')) or '未提供'}")
        st.write(summary)
        full = full_content(item)
        if full and len(full) > (220 if compact else 300):
            with st.expander("查看完整公告內容"):
                st.text(full)
        url = clean_text(item.get("url"))
        if url.startswith(("https://", "http://")):
            st.link_button("閱讀原文 ↗", url)
