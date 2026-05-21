import streamlit as st
import akshare as ak
import pandas as pd
import requests
import time

st.set_page_config(page_title="宽基ETF净申购看板(分类)", layout="wide")
st.title("📈 宽基ETF 净申购 — 分类 · 汇总 · 累计曲线")

# ========== 宽基分类定义 ==========
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

# ========== 获取ETF列表 ==========
@st.cache_data(ttl=3600)
def get_broad_etf():
    df = ak.fund_etf_category_sina(symbol="ETF基金")
    df["code_6"] = df["代码"].str.replace(r"^(sh|sz)", "", regex=True)
    mask = df["名称"].str.contains("|".join(ALL_KEYWORDS), na=False)
    sub = df[mask][["code_6", "名称"]].reset_index(drop=True)
    # 给每只ETF打分类标签（归入第一个匹配的分类）
    def classify(name):
        for cat, kws in CATEGORY_MAP.items():
            if any(k in name for k in kws):
                return cat
        return "其他宽基"
    sub["category"] = sub["名称"].apply(classify)
    return sub

# ========== 拉取单只ETF历史份额，计算净申购(亿份) ==========
@st.cache_data(ttl=3600)
def fetch_etf_hist(code_6):
    try:
        url = f"http://fundf10.eastmoney.com/ETFJzrl_5588/etflsjz?fundCode={code_6}&page=1"
        r = requests.get(url,
            headers={"User-Agent":"Mozilla/5.0","Referer":"http://fundf10.eastmoney.com/"},
            timeout=10)
        tbls = pd.read_html(r.text, flavor="lxml", header=0)
        if not tbls: return None
        df = tbls[0]
        df.columns = [str(c).strip() for c in df.columns]
        dcol = next((c for c in ["日期","截止日"] if c in df.columns), None)
        scol = next((c for c in ["总份额(份)","总份额","基金份额(份)"] if c in df.columns), None)
        if not dcol or not scol: return None
        df[dcol] = pd.to_datetime(df[dcol], errors="coerce")
        df = df.dropna(subset=[dcol]).sort_values(dcol)
        df["share"] = pd.to_numeric(
            df[scol].astype(str).str.replace(",","").str.replace("份",""),
            errors="coerce")
        df["net_sub(亿份)"] = df["share"].diff() / 1e8
        df["etf_code"] = code_6
        return df[[dcol, "net_sub(亿份)", "etf_code"]].rename(columns={dcol:"date"})
    except:
        return None

# ========== 主 ==========
with st.spinner("加载ETF列表…"):
    etf_meta = get_broad_etf()
st.success(f"宽基ETF共 {len(etf_meta)} 只 ｜ 分类：{', '.join(CATEGORY_MAP.keys())}")

if st.button("🚀 拉取数据并计算"):
    prog = st.progress(0, text="开始拉取…")
    recs = []
    for i, (_, row) in enumerate(etf_meta.iterrows()):
        df = fetch_etf_hist(row["code_6"])
        if df is not None:
            df["category"] = row["category"]
            df["etf_name"] = row["名称"]
            recs.append(df)
        prog.progress((i+1)/len(etf_meta), text=f"处理 {row['名称']} ({i+1}/{len(etf_meta)})")
        time.sleep(0.25)
    prog.empty()

    if not recs:
        st.error("未获取到数据，请重试")
        st.stop()

    all_df = pd.concat(recs, ignore_index=True)
    all_df["date"] = all_df["date"].dt.normalize()

    # ---- 最新交易日分类+汇总 ----
    latest_dt = all_df["date"].max()
    latest = all_df[all_df["date"] == latest_dt]

    cat_sum = latest.groupby("category", as_index=False)["net_sub(亿份)"].sum()\
        .rename(columns={"net_sub(亿份)":"净申购(亿份)"})
    total_row = pd.DataFrame([{"category":"【全部宽基合计】",
                               "净申购(亿份)": latest["net_sub(亿份)"].sum()}])
    show_tbl = pd.concat([cat_sum, total_row], ignore_index=True).sort_values(
        "净申购(亿份)", ascending=False)
    show_tbl["净申购(亿份)"] = show_tbl["净申购(亿份)"].round(2)

    st.subheader(f"📊 最新交易日（{latest_dt}）— 分类 & 合计净申购(亿份)")
    st.dataframe(show_tbl.style.applymap(
        lambda x: "color:#d62728;" if x<0 else ("color:#2ca02c;" if x>0 else ""),
        subset=["净申购(亿份)"]),
        use_container_width=True)

    # ---- 单只ETF明细（最新日）展开可选 ----
    with st.expander("🔍 查看最新日 各ETF明细"):
        detail = latest[["category","etf_name","etf_code","net_sub(亿份)"]]\
            .sort_values(["category","net_sub(亿份)"], ascending=[True,False])
        detail["net_sub(亿份)"] = detail["net_sub(亿份)"].round(2)
        st.dataframe(detail.rename(columns={"category":"分类","etf_name":"名称",
                                            "etf_code":"代码","net_sub(亿份)":"净申购(亿份)"}),
                     use_container_width=True)

    # ---- 累计净申购曲线 ----
    st.subheader("📈 累计净申购份额曲线（亿份）")

    tab_cum_all, tab_cum_cat = st.tabs(["全市场累计", "分类累计"])

    # 全市场
    with tab_cum_all:
        daily_total = all_df.groupby("date", as_index=False)["net_sub(亿份)"].sum()
        daily_total["累计净申购(亿份)"] = daily_total["net_sub(亿份)"].cumsum()
        st.line_chart(daily_total.set_index("date")[["累计净申购(亿份)"]],
                      use_container_width=True)

    # 分类累计
    with tab_cum_cat:
        cat_daily = all_df.groupby(["date","category"], as_index=False)["net_sub(亿份)"].sum()
        cat_cum = cat_daily.copy()
        cat_cum["累计"] = cat_cum.groupby("category")["net_sub(亿份)"].cumsum()
        pivot = cat_cum.pivot_table(index="date", columns="category", values="累计")
        st.line_chart(pivot, use_container_width=True)

    # 存session供复用
    st.session_state["done"] = True
    st.session_state["all_df"] = all_df

st.caption("数据来源：东方财富F10 · AkShare ｜ 净申购=当日份额−前日份额 ｜ 首次加载约30–60秒")
