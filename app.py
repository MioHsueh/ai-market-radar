import streamlit as st
from services.storage import load_latest_report, load_recent_news
from services.news_display import render_news_card, format_datetime
from datetime import datetime
from zoneinfo import ZoneInfo

TAIPEI_TZ = ZoneInfo("Asia/Taipei")

def is_today_news(item):
    value = item.get("published_at")
    if not value:
        return False
    try:
        if isinstance(value, datetime):
            dt = value
        else:
            dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TAIPEI_TZ)
        return dt.astimezone(TAIPEI_TZ).date() == datetime.now(TAIPEI_TZ).date()
    except (TypeError, ValueError, OverflowError):
        return False

st.set_page_config(page_title="AI Market Radar", page_icon="🌐", layout="wide")
st.markdown("""
<style>
.block-container {max-width: 1400px; padding-top: 1.7rem; padding-bottom: 3rem;}
.hero {padding: 1.35rem 1.5rem; border: 1px solid rgba(128,128,128,.25); border-radius: 18px; margin-bottom: 1.1rem;}
.hero-kicker {font-size: .82rem; letter-spacing: .12em; text-transform: uppercase; opacity: .72;}
.hero h1 {margin: .35rem 0 .2rem 0; font-size: 2.35rem;}
.hero p {margin: 0; opacity: .78;}
.section-note {opacity: .72; font-size: .92rem;}
div[data-testid="stVerticalBlockBorderWrapper"] {border-radius: 14px;}
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="hero">
  <div class="hero-kicker">Daily market intelligence</div>
  <h1>🌐 AI Market Radar</h1>
  <p>美股 × 台股｜只呈現台灣時間今天發布的新聞</p>
</div>
""", unsafe_allow_html=True)

today = datetime.now(TAIPEI_TZ).date()
try:
    report = load_latest_report()
    all_news = [dict(x) for x in load_recent_news(limit=500)]
except Exception as exc:
    st.error("目前無法讀取 Supabase 資料。請確認 Streamlit Secrets 的 DATABASE_URL 與資料庫連線。")
    st.caption(f"錯誤類型：{type(exc).__name__}")
    st.stop()

news = [x for x in all_news if is_today_news(x)]
us_news = [x for x in news if str(x.get("market", "")).upper() == "US"]
tw_news = [x for x in news if str(x.get("market", "")).upper() == "TW"]

m1, m2, m3 = st.columns(3)
m1.metric("今日新聞", f"{len(news):,}")
m2.metric("🇺🇸 今日美股新聞", f"{len(us_news):,}")
m3.metric("🇹🇼 今日台股新聞", f"{len(tw_news):,}")

if report and str(report.get("report_date", "")) == today.isoformat():
    st.subheader("📌 今日市場總覽")
    st.caption(f"報告日期：{report.get('report_date', '未提供')} · 更新時間：{format_datetime(report.get('updated_at'))}")
    st.markdown(report.get("market_summary") or "目前尚無市場摘要。")
else:
    st.info("今天的市場報告尚未產生。")
