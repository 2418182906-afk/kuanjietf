"""
宽基ETF净申购看板 - 修正版
数据源：新浪ETF列表(分类) + 东方财富ETF历史份额JSON接口
功能：按分类(上证50/沪深300/中证500/中证1000/科创50/创业板/A50)显示
      最新交易日净申购 + 全市场&分类累计净申购曲线
"""
import streamlit as st
import akshare as ak
import pandas as pd
import requests
import time

st.set_page_config(page_title="宽基ETF净申购看板", layout="wide")
st.title("📈 宽基ETF 净申购 — 分类 · 汇总 · 累计曲线")

# ===== 宽基分类关键词 =====
CATEGORY_MAP = {
    "上证50":   ["上证50", "50ETF"],
    "沪深300":  ["沪深300", "300ETF"],
    "中证500":  ["中证500", "500ETF"],
    "中证1000": ["中证1000", "1000ETF"],
    "科创50":   ["科创50"],
    "创业板":   ["创业板"],
    "深证100":  ["深证100"],
    "A50/A500": ["MSCI中国A50", "富时中国A50", "A50", "A500"],
}
ALL_KW = list({kw for kws in CATEGORY_MAP.values() for kw in kws})

# ===== 获取宽基ETF列表（新浪）=====
@st.cache_data(ttl=3600)
def get_broad_etf():
    df = ak.fund_etf_category_sina(symbol="ETF基金")
    df["code_6"] = df["代码"].str.replace(r"^(sh|sz)", "", regex=True)
    mask = df["名称"].str.contains("|".join(ALL_KW), na=False)
    sub = df[mask][["code_6", "名称"]].reset_index(drop=True)
    def classify(name):
        for cat, kws in CATEGORY_MAP.items():
            if any(k in name for k in kws):
                return cat
        return "其他宽基"
    sub["category"] = sub["名称"].apply(classify)
    return sub

# ===== 拉历史份额 — 东方财富JSON接口（稳定）=====
@st.cache_data(ttl=3600)
def fetch_etf_share_hist(code_6):
    """
    调东方财富 /f10/etf/lsjz JSON接口取历史总份额
    返回 DataFrame: date, share(份), net_sub(亿份), etf_code
    """
    try:
        url = "http://api.fund.eastmoney.com/f10/etf/lsjz"
        params = {"FundCode": code_6, "pageIndex": 1, "pageSize": 5000}
        headers = {"User-Agent": "Mozilla/5.0",
                   "Referer": "http://fundf10.eastmoney.com/"}
        r = requests.get(url, params=params, headers=headers, timeout=12)
        js = r.json()
        if js.get("ErrCode") != 0 or "Data" not in js or not js["Data"].get("LSJZList"):
            return None
        rows = js["Data"]["LSJZList"]
        if not rows:
            return None
        df = pd.DataFrame(rows)
        # 字段名通常为 FSDate(日期) TotalShares(总份额,单位:份)
        if "FSDate" not in df.columns or "TotalShares" not in df.columns:
            # 兼容大小写
            df.columns = [c.strip() for c in df.columns]
            date_col = next((c for c in df.columns if "date" in c.lower() or "fsdate" in c.lower()), None)
            share_col = next((c for c in df.columns if "totalshare" in c.lower() or "shares" in c.lower()), None)
            if not date_col or not share_col:
                return None
        else:
            date_col, share_col = "FSDate", "TotalShares"

        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=[date_col]).sort_values(date_col)
        df["share"] = pd.to_numeric(df[share_col], errors="coerce")
        df = df.dropna(subset=["share"])
        df["net_sub(亿份)"] = df["share"].diff() / 1e8
        df["etf_code"] = code_6
        return df[[date_col, "share", "net_sub(亿份)", "etf_code"]].rename(columns={date_col: "date"})
    except Exception as e:
        return None


# ===== 主逻辑 =====
with st.spinner("加载宽基ETF列表…"):
    etf_meta = get_broad_etf()
st.success(f"宽基ETF共 {len(etf_meta)} 只 — 分类：{', '.join(CATEGORY_MAP.keys())}")

if st.button("🚀 拉取历史份额并计算净申购"):
    prog = st.progress(0, text="开始拉取…")
    frames = []
    skipped = []

    for i, (_, row) in enumerate(etf_meta.iterrows()):
        df = fetch_etf_share_hist(row["code_6"])
        if df is not None and not df.empty:
            df["category"] = row["category"]
            df["etf_name"] = row["名称"]
            frames.append(df)
        else:
            skipped.append(f"{row['名称']}({row['code_6']})")
        prog.progress((i+1)/len(etf_meta),
                      text=f"({i+1}/{len(etf_meta)}) {row['名称']}")
        time.sleep(0.15)

    prog.empty()

    if skipped:
        st.warning(f"⚠️ 跳过无历史份额数据（通常系深交所ETF）：{', '.join(skipped[:6])}{' …' if len(skipped)>6 else ''}  共{len(skipped)}只（上交所宽基正常计入）")

    if not frames:
        st.error("❌ 未获取到任何份额数据，可能是网络超时，请再点一次重试")
        st.stop()

    all_df = pd.concat(frames, ignore_index=True)
    all_df["date"] = all_df["date"].dt.normalize()

    # —— 最新交易日 分类 & 合计 ——
    latest_dt = all_df["date"].max()
    latest = all_df[all_df["date"] == latest_dt]

    cat_sum = latest.groupby("category", as_index=False)["net_sub(亿份)"].sum() \
        .rename(columns={"net_sub(亿份)": "净申购(亿份)"})
    total_row = pd.DataFrame([{
        "category": "【全部宽基合计】",
        "净申购(亿份)": latest["net_sub(亿份)"].sum()
    }])
    tbl = pd.concat([cat_sum, total_row], ignore_index=True)
    tbl["净申购(亿份)"] = tbl["净申购(亿份)"].round(2)

    st.subheader(f"📊 最新交易日（{latest_dt.strftime('%Y-%m-%d')}）净申购(亿份)")
    st.dataframe(
        tbl.style.applymap(
            lambda x: "color:#d62728;" if isinstance(x,(int,float)) and x<0 else ("color:#2ca02c;" if isinstance(x,(int,float)) and x>0 else ""),
            subset=["净申购(亿份)"]
        ),
        use_container_width=True
    )

    # 明细
    with st.expander("🔍 查看最新日 各ETF明细（含上交所宽基）"):
        det = latest[["category","etf_name","etf_code","net_sub(亿份)"]] \
            .sort_values(["category","net_sub(亿份)"], ascending=[True,False])
        det["net_sub(亿份)"] = det["net_sub(亿份)"].round(2)
        st.dataframe(
            det.rename(columns={"category":"分类","etf_name":"名称","etf_code":"代码","net_sub(亿份)":"净申购(亿份)"}),
            use_container_width=True
        )

    # —— 累计曲线 ——
    st.subheader("📈 累计净申购份额曲线（亿份）")
    tab_all, tab_cat = st.tabs(["全市场累计", "分类累计"])

    with tab_all:
        daily = all_df.groupby("date", as_index=False)["net_sub(亿份)"].sum()
        daily["累计"] = daily["net_sub(亿份)"].cumsum()
        st.line_chart(daily.set_index("date")[["累计"]], use_container_width=True)

    with tab_cat:
        cd = all_df.groupby(["date","category"], as_index=False)["net_sub(亿份)"].sum()
        cd["累计"] = cd.groupby("category")["net_sub(亿份)"].cumsum()
        pivot = cd.pivot_table(index="date", columns="category", values="累计")
        st.line_chart(pivot, use_container_width=True)

    st.success(f"✅ 使用 {len(frames)}/{len(etf_meta)} 只ETF数据（上交所宽基已纳入，深交所部分需东财F10支持则跳过）")

st.caption("数据源：新浪ETF列表 + 东方财富ETF历史份额JSON接口 ｜ 净申购=当日份额−前日份额 ｜ 深交所ETF若无历史数据自动跳过")
