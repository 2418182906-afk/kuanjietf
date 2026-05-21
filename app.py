import streamlit as st
import akshare as ak
import pandas as pd
import requests
import time

st.set_page_config(page_title="ETF净申购看板", layout="wide")
st.title("📈 宽基ETF 每日净申购监控")

KEYWORDS = ["沪深300", "中证500", "中证1000", "上证50", "科创50", "创业板", "深证100", "A50", "A500"]

@st.cache_data(ttl=3600)
def get_etf_list():
    df = ak.fund_etf_category_sina(symbol="ETF基金")
    df["code_6"] = df["代码"].str.replace(r"^(sh|sz)", "", regex=True)
    mask = df["名称"].str.contains("|".join(KEYWORDS), na=False)
    return df[mask][["code_6", "名称"]].reset_index(drop=True)

@st.cache_data(ttl=3600)
def fetch_etf_data(code):
    try:
        url = f"http://fundf10.eastmoney.com/ETFJzrl_5588/etflsjz?fundCode={code}&page=1"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=10)
        tables = pd.read_html(r.text, flavor="lxml", header=0)
        if not tables: return None
        df = tables[0]
        df.columns = [str(c).strip() for c in df.columns]
        date_col = next((c for c in ["日期", "截止日"] if c in df.columns), None)
        share_col = next((c for c in ["总份额(份)", "总份额"] if c in df.columns), None)
        if not date_col or not share_col: return None
        df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
        df = df.dropna(subset=[date_col]).sort_values(date_col)
        df['share_num'] = pd.to_numeric(df[share_col].astype(str).str.replace(',', '').str.replace('份', ''), errors='coerce')
        df['net_subscribe'] = df['share_num'].diff() / 1e8
        df['etf_code'] = code
        return df[[date_col, 'share_num', 'net_subscribe', 'etf_code']].rename(columns={date_col: 'date'})
    except:
        return None

with st.spinner("正在加载ETF列表..."):
    etf_list = get_etf_list()
st.success(f"检测到 {len(etf_list)} 只宽基ETF")

if st.button("🚀 点击拉取最新数据"):
    progress_bar = st.progress(0)
    status_text = st.empty()
    all_data = []
    for i, (_, row) in enumerate(etf_list.iterrows()):
        status_text.text(f"正在处理 {row['名称']} ({i+1}/{len(etf_list)})...")
        df = fetch_etf_data(row['code_6'])
        if df is not None:
            df['name'] = row['名称']
            all_data.append(df)
        progress_bar.progress((i + 1) / len(etf_list))
        time.sleep(0.2)
    if all_data:
        final_df = pd.concat(all_data, ignore_index=True)
        final_df['date'] = final_df['date'].dt.date
        st.subheader("📊 最新交易日净申购排行")
        latest_date = final_df['date'].max()
        latest_df = final_df[final_df['date'] == latest_date].sort_values('net_subscribe', ascending=False)
        latest_df['net_subscribe'] = latest_df['net_subscribe'].round(2)
        st.dataframe(latest_df[['name', 'etf_code', 'net_subscribe']].rename(columns={'name':'名称', 'etf_code':'代码', 'net_subscribe':'净申购(亿份)'}))
        st.subheader("📉 全市场宽基ETF 近期资金流向")
        chart_df = final_df.groupby('date')['net_subscribe'].sum().reset_index()
        st.line_chart(chart_df.set_index('date'))
    else:
        st.error("没有抓取到数据，请检查网络或稍后再试。")
