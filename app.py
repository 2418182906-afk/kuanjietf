import streamlit as st
import akshare as ak
import pandas as pd
import time

st.set_page_config(page_title="宽基ETF净申购看板(分类)", layout="wide")
st.title("📈 宽基ETF 净申购 — 分类 · 汇总 · 累计曲线")

# ========== 宽基分类 ==========
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
ALL_KEYWORDS = list({kw for kws in CATEGORY_MAP.values() for kw in kws})

# ========== ETF列表 ==========
@st.cache_data(ttl=3600)
def get_broad_etf():
    df = ak.fund_etf_category_sina(symbol="ETF基金")
    df["code_6"] = df["代码"].str.replace(r"^(sh|sz)", "", regex=True)
    mask = df["名称"].str.contains("|".join(ALL_KEYWORDS), na=False)
    sub = df[mask][["code_6", "名称"]].reset_index(drop=True)
    def classify(name):
        for cat, kws in CATEGORY_MAP.items():
            if any(k in name for k in kws):
                return cat
        return "其他宽基"
    sub["category"] = sub["名称"].apply(classify)
    return sub

# ========== 拉历史份额（改用 fund_em_etf_fund_daily）==========
@st.cache_data(ttl=3600)
def fetch_etf_hist(code_6):
    """
    用 akshare fund_em_etf_fund_daily 拉历史数据
    返回 DataFrame: date, net_sub(亿份), etf_code
    """
    try:
        # 先试 6 位代码，部分版本也支持 sh510300
        df = ak.fund_em_etf_fund_daily(symbol=code_6)
    except Exception:
        try:
            df = ak.fund_em_etf_fund_daily(symbol="sh" + code_6)
        except Exception:
            return None

    if df is None or df.empty:
        return None

    # ---- 标准化列名 ----
    df.columns = [str(c).strip() for c in df.columns]

    # 找日期列
    date_col = next((c for c in df.columns if "日期" in c or "date" in c.lower()), None)
    # 找份额列（常见名）
    share_col = next((c for c in df.columns if "基金份额" in c or "总份额" in c or "份额" == c.strip()), None)

    if not date_col or not share_col:
        # 调试用可 print(df.columns)
        return None

    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=[date_col]).sort_values(date_col)

    # 清理份额：已是数值(份)，若带字符串再清逗号
    if df[share_col].dtype == object:
        df["share_num"] = pd.to_numeric(
            df[share_col].astype(str).str.replace(",", "").str.replace("份", ""),
            errors="coerce")
    else:
        df["share_num"] = df[share_col]

    df = df.dropna(subset=["share_num"])
    df["net_sub(亿份)"] = df["share_num"].diff() / 1e8
    df["etf_code"] = code_6
    return df[[date_col, "net_sub(亿份)", "etf_code"]].rename(columns={date_col: "date"})


# ========== 主程序 ==========
with st.spinner("加载宽基ETF列表…"):
    etf_meta = get_broad_etf()
st.success(f"宽基ETF共 {len(etf_meta)} 只 — 分类：{', '.join(CATEGORY_MAP.keys())}")

if st.button("🚀 拉取数据并计算"):
    prog = st.progress(0, text="开始拉取历史份额…")
    recs = []
    skip = []

    for i, (_, row) in enumerate(etf_meta.iterrows()):
        df = fetch_etf_hist(row["code_6"])
        if df is not None and not df.empty:
            df["category"] = row["category"]
            df["etf_name"] = row["名称"]
            recs.append(df)
        else:
            skip.append(row["名称"])
        prog.progress((i + 1) / len(etf_meta),
                      text=f"({i+1}/{len(etf_meta)}) {row['名称']}")
        time.sleep(0.15)

    prog.empty()
    if skip:
        st.caption(f"⚠️ 跳过无数据ETF：{', '.join(skip[:5])}{' …' if len(skip)>5 else ''}  共{len(skip)}只")

    if not recs:
        st.error("❌ 未获取到任何ETF历史份额数据，请重试（偶发网络超时可再点一次）")
        st.stop()

    all_df = pd.concat(recs, ignore_index=True)
    all_df["date"] = all_df["date"].dt.normalize()

    # ---- 最新交易日 分类 + 合计 ----
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
            lambda x: "color:#d62728;" if isinstance(x,(int,float)) and x < 0 else ("color:#2ca02c;" if isinstance(x,(int,float)) and x > 0 else ""),
            subset=["净申购(亿份)"]
        ),
        use_container_width=True
    )

    # 明细
    with st.expander("🔍 查看最新日 各ETF明细"):
        det = latest[["category","etf_name","etf_code","net_sub(亿份)"]] \
            .sort_values(["category","net_sub(亿份)"], ascending=[True,False])
        det["net_sub(亿份)"] = det["net_sub(亿份)"].round(2)
        st.dataframe(
            det.rename(columns={"category":"分类","etf_name":"名称","etf_code":"代码","net_sub(亿份)":"净申购(亿份)"}),
            use_container_width=True
        )

    # ---- 累计曲线 ----
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

    st.session_state["all_df"] = all_df
    st.success(f"✅ 完成！使用 {len(recs)}/{len(etf_meta)} 只ETF数据（其余无历史份额自动跳过）")

st.caption("数据源：AkShare → 东方财富ETF历史份额 ｜ 净申购=当日份额−前日份额 ｜ 有数据才参与统计")
