import streamlit as st
from services.storage import load_latest_report, load_recent_news
from services.news_display import render_news_card, market_label, format_datetime

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
  <p>美股 × 台股｜把重要市場資訊整理成容易閱讀的每日情報</p>
</div>
""", unsafe_allow_html=True)

try:
    report = load_latest_report()
    news = load_recent_news(limit=100)
except Exception as exc:
    st.error("目前無法讀取 Supabase 資料。請確認 Streamlit Secrets 的 DATABASE_URL 與資料庫連線。")
    st.caption(f"錯誤類型：{type(exc).__name__}")
    st.stop()

news = [dict(x) for x in news]
us_news = [x for x in news if str(x.get("market", "")).upper() == "US"]
tw_news = [x for x in news if str(x.get("market", "")).upper() == "TW"]

m1, m2, m3 = st.columns(3)
m1.metric("近期新聞", f"{len(news):,}")
m2.metric("🇺🇸 美股新聞", f"{len(us_news):,}")
m3.metric("🇹🇼 台股新聞", f"{len(tw_news):,}")

if report:
    st.subheader("📌 每日市場總覽")
    st.caption(f"報告日期：{report.get('report_date', '未提供')} · 更新時間：{format_datetime(report.get('updated_at'))}")
    st.markdown(report.get("market_summary") or "目前尚無市場摘要。")
else:
    st.info("每日市場報告尚未產生。現在先顯示已匯入的真實新聞；後續接上分析流程後，這裡會呈現每日總覽。")

st.divider()
st.subheader("📰 近期市場新聞")
st.markdown('<div class="section-note">摘要目前是來源內容的精簡摘錄，並非 AI 生成；請點選原文核對完整資訊。</div>', unsafe_allow_html=True)

f1, f2, f3 = st.columns([1, 1, 2])
with f1:
    market_filter = st.selectbox("市場", ["全部市場", "台股", "美股"], index=0)
with f2:
    max_items = st.selectbox("顯示筆數", [10, 20, 50], index=1)
with f3:
    search_text = st.text_input("搜尋標題或內容", placeholder="例如：半導體、董事會、AI")

filtered = news
if market_filter == "台股":
    filtered = [x for x in filtered if str(x.get("market", "")).upper() == "TW"]
elif market_filter == "美股":
    filtered = [x for x in filtered if str(x.get("market", "")).upper() == "US"]
if search_text.strip():
    q = search_text.strip().casefold()
    filtered = [x for x in filtered if q in str(x.get("title") or "").casefold() or q in str(x.get("summary") or "").casefold()]

st.caption(f"目前顯示 {min(len(filtered), max_items)} / {len(filtered)} 筆符合條件的新聞")
if not filtered:
    st.info("沒有符合條件的新聞。可以清除搜尋字詞，或切換市場篩選。")
else:
    for item in filtered[:max_items]:
        render_news_card(st, item, compact=True)

with st.expander("資料來源與閱讀說明"):
    st.write("台股資料包含交易所新聞與上市公司重大訊息。部分舊資料的標題欄位曾被日期誤用，首頁會以中性公告標題呈現；修正匯入程式後的新資料會優先使用公告主旨。")
    st.write("新聞內容及時間以原始來源為準。本網站提供資訊整理與研究輔助，不構成投資建議。")
