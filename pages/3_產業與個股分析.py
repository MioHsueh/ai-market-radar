
"""Rule-based industry and stock analysis without a paid AI API."""
from datetime import datetime
import re
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
import plotly.express as px


from services.storage import (
    load_recent_news,
    load_news_for_date_range,
)

TAIPEI_TZ = ZoneInfo("Asia/Taipei")
NEWS_LIMIT = 500

INDUSTRY_KEYWORDS = {
    "AI 與半導體": [
        "AI", "人工智慧", "半導體", "晶片", "晶圓", "台積電",
        "TSMC", "NVIDIA", "輝達", "GPU", "伺服器", "先進製程",
        "封裝", "HBM", "記憶體",
    ],
    "總體經濟與金融": [
        "聯準會", "Fed", "利率", "通膨", "CPI", "GDP",
        "央行", "匯率", "美元", "債券", "就業", "降息", "升息",
    ],
    "電動車與能源": [
        "電動車", "EV", "Tesla", "特斯拉", "電池", "充電",
        "能源", "太陽能", "風電", "儲能",
    ],
    "企業與消費": [
        "營收", "財報", "獲利", "訂單", "出貨", "展望",
        "零售", "消費", "電商", "品牌", "供應鏈",
    ],
    "政策與國際局勢": [
        "關稅", "貿易", "制裁", "出口管制", "政策",
        "地緣政治", "戰爭", "選舉", "法案",
    ],
}

# 只使用可明確識別的公司名稱或常見名稱。
# 股票代號是參考索引，不代表新聞一定會影響該股票。
STOCK_KEYWORDS = {
    "台股": {
        "台積電（2330）": ["台積電", "TSMC"],
        "鴻海（2317）": ["鴻海", "Hon Hai", "Foxconn"],
        "聯發科（2454）": ["聯發科", "MediaTek"],
        "廣達（2382）": ["廣達", "Quanta"],
        "緯創（3231）": ["緯創", "Wistron"],
        "日月光投控（3711）": ["日月光", "ASE Technology"],
        "台達電（2308）": ["台達電", "Delta Electronics"],
    },
    "美股": {
        "NVIDIA（NVDA）": ["NVIDIA", "輝達"],
        "Apple（AAPL）": ["Apple", "蘋果公司", "iPhone"],
        "Microsoft（MSFT）": ["Microsoft", "微軟"],
        "Amazon（AMZN）": ["Amazon", "亞馬遜"],
        "Alphabet（GOOGL）": ["Alphabet", "Google", "谷歌"],
        "Meta（META）": ["Meta Platforms", "Facebook"],
        "Tesla（TSLA）": ["Tesla", "特斯拉"],
        "AMD（AMD）": ["AMD", "超微"],
        "Broadcom（AVGO）": ["Broadcom", "博通"],
    },
}

POSITIVE_KEYWORDS = [
    "成長", "創高", "優於預期", "增加", "上升", "成長動能",
    "獲利增加", "營收成長", "訂單增加", "需求強勁", "擴產",
    "上調", "突破", "回購", "利多",
]

NEGATIVE_KEYWORDS = [
    "衰退", "低於預期", "下滑", "下降", "減少", "虧損",
    "裁員", "需求疲弱", "砍單", "下調", "制裁", "關稅",
    "風險升高", "違約", "利空",
]


# 產業影響路徑與後續觀察指標：屬於分析提示，不代表已證實的股價影響。
INDUSTRY_IMPACT_GUIDES = {
    "AI 與半導體": {
        "impact": "需求、晶片供應、先進製程／封裝產能與資本支出可能影響供應鏈。",
        "watch": "月營收、客戶訂單、產能利用率、資本支出、毛利率及法說會展望。",
        "caution": "需確認新聞是否涉及實際訂單、出貨或公司公告；僅提到 AI 不足以判定受惠。",
    },
    "總體經濟與金融": {
        "impact": "利率、通膨、匯率與就業數據可能改變資金成本、企業需求及市場評價。",
        "watch": "官方經濟數據、央行聲明、債券殖利率、匯率及後續政策指引。",
        "caution": "需確認數據相對市場預期的差異，不能只依數據升降判斷市場方向。",
    },
    "電動車與能源": {
        "impact": "需求、電池成本、能源價格與政策可能影響車廠、零組件及能源供應鏈。",
        "watch": "交車量、電池價格、訂單、原物料價格、補助政策及公司毛利率。",
