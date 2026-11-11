# -*- coding: utf-8 -*-
"""
MOMO 商品爬蟲 + 視覺化 (Streamlit)
- 輸入商品關鍵字與爬取頁數
- 爬取 momo 購物網搜尋結果
- 繪製折線圖、圓餅圖、旭日圖 (Plotly)

執行方式:
    pip install -r requirements.txt
    streamlit run app.py

關於中文字型:
    原本使用 matplotlib + !wget 下載字型。改用 Plotly 後，圖表由瀏覽器渲染，
    直接使用使用者系統的中文字型，不需要再下載或設定字型檔。
"""

import re
import time

import pandas as pd
import plotly.express as px
import streamlit as st
from curl_cffi import requests  # 模擬 Chrome 的 TLS 指紋，避免被擋

# ----------------------------------------------------------------------
# 基本設定
# ----------------------------------------------------------------------
st.set_page_config(page_title="MOMO 商品價格分析", page_icon="🛍️", layout="wide")

HOME_URL = "https://www.momoshop.com.tw/"
API_URL = "https://apisearch.momoshop.com.tw/momoSearchCloud/moec/textSearch"
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Content-Type": "application/json;charset=UTF-8",
    "Origin": "https://www.momoshop.com.tw",
    "Referer": "https://www.momoshop.com.tw/",
}
CHART_FONT = "Noto Sans TC, Microsoft JhengHei, PingFang TC, sans-serif"


# ----------------------------------------------------------------------
# 爬蟲
# ----------------------------------------------------------------------
def build_payload(keyword: str, page: int) -> dict:
    """組出 momo 搜尋 API 需要的 payload。"""
    return {
        "host": "momoshop",
        "flag": "searchEngine",
        "data": {
            "searchValue": keyword,
            "searchType": "1",
            "cateLevel": "-1",
            "curPage": str(page),
            "priceS": "0",
            "priceE": "9999999",
            "showType": "chessboardType",
            "isFuzzy": "0",
            "rtnCateDatainfo": {
                "cateCode": "",
                "cateLv": "-1",
                "keyword": keyword,
                "curPage": str(page),  # 與外層一致
                "historyDoPush": "false",
                "timestamp": int(time.time() * 1000),  # 每次用當下時間
            },
            "flag": 2018,
            "serviceCode": "MT01",
            "addressSearchData": {},
        },
    }


def crawl(keyword: str, pages: int, delay: float, progress) -> pd.DataFrame:
    """爬取多頁並合併成 DataFrame。"""
    session = requests.Session(impersonate="chrome")
    try:
        session.get(HOME_URL, headers=HEADERS, timeout=15)  # 先取得 cookie
    except Exception as e:
        st.error(f"無法連線到 momo 首頁：{e}")
        return pd.DataFrame()

    rows = []
    for i in range(1, pages + 1):
        progress.progress((i - 1) / pages, text=f"正在爬取第 {i} / {pages} 頁…")
        try:
            resp = session.post(
                API_URL, headers=HEADERS, json=build_payload(keyword, i), timeout=15
            )
        except Exception as e:
            st.warning(f"第 {i} 頁請求失敗：{e}")
            break

        if resp.status_code != 200:
            st.warning(f"第 {i} 頁回應狀態碼 {resp.status_code}：{resp.text[:200]}")
            break

        try:
            products = resp.json().get("rtnSearchData", {}).get("goodsInfoList", [])
        except ValueError:
            st.warning(f"第 {i} 頁回傳內容不是 JSON，可能被網站擋下。")
            break

        if not products:
            st.info(f"第 {i} 頁沒有資料，已停止爬取。")
            break

        for p in products:
            rows.append({
                "品名": p.get("goodsName", ""),
                "價格": p.get("goodsPrice", ""),
                "頁數": i,
            })

        if i < pages:
            time.sleep(delay)

    progress.progress(1.0, text="爬取完成")
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------
# 資料處理
# ----------------------------------------------------------------------
PRICE_BINS = [0, 500, 1000, 2000, 5000, 10000, float("inf")]
PRICE_LABELS = ["0-500", "501-1000", "1001-2000", "2001-5000", "5001-10000", "10000以上"]


def parse_price(value) -> float:
    """把 '$1,273' 之類的字串轉成數字；若是區間（如 '$100~$200'）取第一個數字。"""
    m = re.search(r"\d[\d,]*", str(value))
    return float(m.group().replace(",", "")) if m else float("nan")


def extract_brand(name: str) -> str:
    """從商品名稱抽取品牌，例如『【Anker】xxx』→ Anker；抓不到則為『其他』。"""
    m = re.search(r"[【\[「](.+?)[】\]」]", str(name))
    return m.group(1).strip() if m else "其他"


def prepare(df: pd.DataFrame, top_brands: int) -> pd.DataFrame:
    """清理資料並建立圖表需要的欄位。"""
    df = df.copy()
    df["價格"] = df["價格"].map(parse_price)
    df = df.dropna(subset=["品名", "價格"]).reset_index(drop=True)
    df["價格"] = df["價格"].astype(int)

    df["價格區間"] = pd.cut(
        df["價格"], bins=PRICE_BINS, labels=PRICE_LABELS, right=True, include_lowest=True
    ).astype(str)

    brand = df["品名"].map(extract_brand)
    top = brand[brand != "其他"].value_counts().head(top_brands).index
    df["品牌"] = brand.where(brand.isin(top), "其他")
    return df


# ----------------------------------------------------------------------
# 畫面
# ----------------------------------------------------------------------
st.title("🛍️ MOMO 商品價格分析")
st.caption("輸入商品名稱與頁數，爬取 momo 購物網搜尋結果並進行視覺化。")

with st.sidebar:
    st.header("搜尋設定")
    keyword = st.text_input("商品名稱", value="行動電源")
    pages = st.number_input("爬取頁數", min_value=1, max_value=20, value=2, step=1)
    delay = st.slider("每頁間隔秒數", 0.0, 10.0, 2.0, 0.5,
                      help="建議至少 1 秒以上，避免被網站封鎖。")
    top_brands = st.slider("旭日圖顯示品牌數", 3, 20, 8,
                           help="其餘品牌會合併為『其他』。")
    run = st.button("🔍 開始爬取", type="primary", use_container_width=True)

# 按下按鈕才爬取，結果存進 session_state，調整圖表選項時不會重爬
if run:
    if not keyword.strip():
        st.error("請輸入商品名稱。")
    else:
        bar = st.progress(0.0, text="準備中…")
        raw = crawl(keyword.strip(), int(pages), delay, bar)
        bar.empty()
        if raw.empty:
            st.session_state.pop("raw", None)
            st.error("沒有抓到任何資料，請換個關鍵字或稍後再試。")
        else:
            st.session_state["raw"] = raw
            st.session_state["keyword"] = keyword.strip()

if "raw" not in st.session_state:
    st.info("👈 請在左側輸入商品名稱與頁數，然後按下「開始爬取」。")
    st.stop()

raw = st.session_state["raw"]
kw = st.session_state["keyword"]
df = prepare(raw, top_brands)

if df.empty:
    st.error("資料中沒有可用的商品名稱與價格。")
    st.stop()

# ---- 統計 ----
mean_price = df["價格"].mean()
c1, c2, c3, c4 = st.columns(4)
c1.metric("商品數量", f"{len(df):,}")
c2.metric("平均價格", f"{mean_price:,.0f}")
c3.metric("最高價格", f"{df['價格'].max():,.0f}")
c4.metric("最低價格", f"{df['價格'].min():,.0f}")

tab_line, tab_pie, tab_sun, tab_data = st.tabs(["📈 折線圖", "🥧 圓餅圖", "🌞 旭日圖", "📋 資料表"])

# ---- 折線圖 ----
with tab_line:
    n_max = len(df)
    n_show = st.slider("顯示前 N 筆商品", 1, n_max, min(70, n_max)) if n_max > 1 else 1
    plot_df = df.head(n_show).copy()
    plot_df["序號"] = plot_df.index + 1

    fig_line = px.line(
        plot_df, x="序號", y="價格", markers=True,
        hover_data={"品名": True, "序號": False, "價格": ":,.0f"},
        title=f"MOMO 電商網站上「{kw}」售價",
    )
    fig_line.add_hline(
        y=mean_price, line_dash="dash", line_color="red",
        annotation_text=f"平均價格 {mean_price:,.0f}", annotation_position="top left",
    )
    fig_line.update_layout(font_family=CHART_FONT, xaxis_title="商品序號", yaxis_title="價格", height=550)
    st.plotly_chart(fig_line, use_container_width=True)

# ---- 圓餅圖 ----
with tab_pie:
    pie_by = st.radio("統計依據", ["價格區間", "品牌"], horizontal=True)
    pie_df = df[pie_by].value_counts().reset_index()
    pie_df.columns = [pie_by, "數量"]

    fig_pie = px.pie(
        pie_df, names=pie_by, values="數量", hole=0.3,
        title=f"「{kw}」商品{pie_by}分布",
    )
    fig_pie.update_traces(textposition="inside", textinfo="percent+label")
    fig_pie.update_layout(font_family=CHART_FONT, height=550)
    st.plotly_chart(fig_pie, use_container_width=True)

# ---- 旭日圖 ----
with tab_sun:
    order = st.radio("階層順序", ["價格區間 → 品牌", "品牌 → 價格區間"], horizontal=True)
    path = ["價格區間", "品牌"] if order.startswith("價格") else ["品牌", "價格區間"]

    fig_sun = px.sunburst(df, path=path, title=f"「{kw}」商品 {order}")
    fig_sun.update_traces(textinfo="label+percent parent", insidetextorientation="radial")
    fig_sun.update_layout(font_family=CHART_FONT, height=650)
    st.plotly_chart(fig_sun, use_container_width=True)

# ---- 資料表 ----
with tab_data:
    st.dataframe(df[["品名", "價格", "價格區間", "品牌", "頁數"]], use_container_width=True, height=450)

    st.download_button(
        "⬇️ 下載資料 (CSV)",
        data=df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"),
        file_name=f"MOMO_{time.strftime('%Y%m%d')}_{kw}.csv",
        mime="text/csv",
    )
