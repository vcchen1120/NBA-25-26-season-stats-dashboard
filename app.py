import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import re

st.set_page_config(
    page_title="NBA 25-26 Dashboard",
    page_icon="🏀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=DM+Mono:wght@400;500&display=swap');
.main { background-color: #07080a; }
h1, h2, h3 { font-family: 'Bebas Neue', sans-serif; letter-spacing: 2px; }
.metric-card {
    background: #0f1114; border: 1px solid #1f2329; border-radius: 10px;
    padding: 16px 20px; text-align: center;
}
.metric-label { font-size: 11px; color: #6b7280; letter-spacing: 1.5px; text-transform: uppercase; }
.metric-value { font-size: 32px; font-weight: 700; color: #c8a84b; }
.playoff { color: #22c55e; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

# ── ETL Pipeline ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def load_data():
    def clean(name):
        if not isinstance(name, str): return name
        return re.sub(r'\s*\(\d+\)', '', name).replace('*', '').strip()

    # Sheet 1 - Totals
    df1 = pd.read_excel("nba_25-26_stats.xlsx", sheet_name="工作表1")
    df1["Team"] = df1["Team"].apply(clean)

    # Sheet 2 - Standings
    df2 = pd.read_excel("nba_25-26_stats.xlsx", sheet_name="工作表2")
    df2.columns = ["Team", "W", "L", "WL_pct", "GB", "PS_G", "PA_G", "SRS"]
    east, west = [], []
    conf = "East"
    for _, row in df2.iterrows():
        name = str(row["Team"]).strip()
        if "Eastern" in name: conf = "East"; continue
        if "Western" in name: conf = "West"; continue
        try: w = int(row["W"])
        except: continue
        entry = {
            "Team": clean(name), "W": int(row["W"]), "L": int(row["L"]),
            "WL%": float(row["WL_pct"]), "PS/G": float(row["PS_G"]),
            "PA/G": float(row["PA_G"]), "SRS": float(row["SRS"]),
            "Playoff": "✅" if "*" in str(row["Team"]) else ""
        }
        (east if conf == "East" else west).append(entry)

    # Sheet 3 - Per Game
    df3 = pd.read_excel("nba_25-26_stats.xlsx", sheet_name="工作表3")
    df3 = df3[df3["Rk"].apply(lambda x: str(x).isdigit())].copy()
    df3["Team"] = df3["Team"].apply(clean)
    df3 = df3.rename(columns={"PTS": "PPG", "AST": "APG", "TRB": "RPG",
                                "STL": "SPG", "BLK": "BPG", "TOV": "TOPG",
                                "FG%": "FG%", "3P%": "3P%", "FT%": "FT%"})

    # Sheet 4 - Advanced
    df4r = pd.read_excel("nba_25-26_stats.xlsx", sheet_name="工作表4", header=None)
    hr = df4r[df4r.iloc[:, 0] == "Rk"].index[0]
    df4 = df4r.iloc[hr:].copy()
    df4.columns = df4.iloc[0]
    df4 = df4[1:].reset_index(drop=True)
    df4 = df4[df4["Rk"].apply(lambda x: str(x).strip().isdigit())].copy()
    df4["Team"] = df4["Team"].apply(clean)
    df4 = df4.loc[:, ~df4.columns.duplicated()].copy()
    for col in ["ORtg", "DRtg", "NRtg", "Pace", "TS%", "eFG%", "TOV%", "ORB%",
                "W", "L", "Age", "Attend.", "Attend./G"]:
        if col in df4.columns:
            df4[col] = pd.to_numeric(df4[col], errors="coerce")

    return df1, pd.DataFrame(east), pd.DataFrame(west), df3, df4

df1, east_df, west_df, df3, df4 = load_data()

GOLD = "#c8a84b"
PLOTLY_THEME = dict(
    plot_bgcolor="#07080a", paper_bgcolor="#07080a",
    font=dict(color="#9ca3af", family="DM Mono"),
    xaxis=dict(gridcolor="#1a1d22", linecolor="#1f2329"),
    yaxis=dict(gridcolor="#1a1d22", linecolor="#1f2329"),
    margin=dict(l=10, r=10, t=30, b=10)
)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🏀 NBA 25-26")
    st.markdown("---")
    page = st.radio("Navigate", ["Overview", "Standings", "Team Stats", "Advanced", "Attendance"])
    st.markdown("---")
    if st.button("🔄 Refresh Data"):
        st.cache_data.clear()
        st.rerun()
    st.caption("Data: NBA 2025-26 Regular Season")

# ── OVERVIEW ──────────────────────────────────────────────────────────────────
if page == "Overview":
    st.title("LEAGUE OVERVIEW")
    st.caption("2025–26 Regular Season · All 30 Teams")

    # KPI Row
    all_teams = pd.concat([east_df, west_df])
    top_team = all_teams.loc[all_teams["W"].idxmax()]
    playoff_count = len(all_teams[all_teams["Playoff"] == "✅"])

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Avg PPG", f"{df3['PPG'].mean():.1f}")
    c2.metric("Avg APG", f"{df3['APG'].mean():.1f}")
    c3.metric("Avg RPG", f"{df3['RPG'].mean():.1f}")
    c4.metric("Best Record", f"{top_team['W']}-{top_team['L']}", top_team["Team"])
    c5.metric("Playoff Teams", playoff_count)

    st.markdown("---")
    col1, col2 = st.columns([3, 2])

    with col1:
        st.subheader("Points Per Game — All Teams")
        sorted_ppg = df3.sort_values("PPG", ascending=True)
        colors = [GOLD if i >= len(sorted_ppg)-3 else "rgba(200,168,75,0.25)"
                  for i in range(len(sorted_ppg))]
        fig = go.Figure(go.Bar(
            x=sorted_ppg["PPG"], y=sorted_ppg["Team"],
            orientation="h", marker_color=colors,
            text=sorted_ppg["PPG"], textposition="outside",
            textfont=dict(size=10, color="#9ca3af")
        ))
        fig.update_layout(**PLOTLY_THEME, height=650, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.subheader("Win % Distribution")
        bins = ["Elite\n(70%+)", "Good\n(55-70%)", "Average\n(45-55%)", "Rebuilding\n(<45%)"]
        counts = [
            len(all_teams[all_teams["WL%"] >= 0.7]),
            len(all_teams[(all_teams["WL%"] >= 0.55) & (all_teams["WL%"] < 0.7)]),
            len(all_teams[(all_teams["WL%"] >= 0.45) & (all_teams["WL%"] < 0.55)]),
            len(all_teams[all_teams["WL%"] < 0.45]),
        ]
        fig2 = go.Figure(go.Pie(
            labels=bins, values=counts, hole=0.5,
            marker_colors=[GOLD, "rgba(200,168,75,0.55)", "rgba(200,168,75,0.25)", "rgba(224,92,46,0.4)"],
            textfont=dict(size=11)
        ))
        fig2.update_layout(**PLOTLY_THEME, height=300, showlegend=True,
                           legend=dict(font=dict(size=10)))
        st.plotly_chart(fig2, use_container_width=True)

        st.subheader("Top Scoring Teams")
        top5 = df3.nlargest(5, "PPG")[["Team", "PPG", "APG", "RPG"]]
        st.dataframe(top5.set_index("Team"), use_container_width=True)

    # Shooting Efficiency
    st.subheader("Shooting Efficiency — Top 10")
    top10 = df3.nlargest(10, "PPG")
    fig3 = go.Figure()
    fig3.add_trace(go.Bar(name="FG%", x=top10["Team"],
                          y=(top10["FG%"]*100).round(1),
                          marker_color="rgba(200,168,75,0.7)"))
    fig3.add_trace(go.Bar(name="3P%", x=top10["Team"],
                          y=(top10["3P%"]*100).round(1),
                          marker_color="rgba(224,92,46,0.7)"))
    fig3.update_layout(**PLOTLY_THEME, barmode="group", height=300,
                       legend=dict(font=dict(size=11, color="#9ca3af")))
    st.plotly_chart(fig3, use_container_width=True)

# ── STANDINGS ─────────────────────────────────────────────────────────────────
elif page == "Standings":
    st.title("STANDINGS")
    st.caption("* = Playoff Qualified")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("🔵 Eastern Conference")
        st.dataframe(east_df.set_index("Team"), use_container_width=True, height=560)
    with col2:
        st.subheader("🟡 Western Conference")
        st.dataframe(west_df.set_index("Team"), use_container_width=True, height=560)

    st.markdown("---")
    st.subheader("Win Total Comparison — Top 20")
    all_teams = pd.concat([
        east_df.assign(Conf="East"),
        west_df.assign(Conf="West")
    ]).sort_values("W", ascending=False).head(20)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Wins", y=all_teams["Team"], x=all_teams["W"], orientation="h",
        marker_color=[("#3a7bd5" if c == "East" else GOLD) for c in all_teams["Conf"]]
    ))
    fig.add_trace(go.Bar(
        name="Losses", y=all_teams["Team"], x=all_teams["L"], orientation="h",
        marker_color="rgba(80,80,80,0.35)"
    ))
    fig.update_layout(**PLOTLY_THEME, barmode="stack", height=500,
                      legend=dict(font=dict(size=11, color="#9ca3af")))
    st.plotly_chart(fig, use_container_width=True)

# ── TEAM STATS ────────────────────────────────────────────────────────────────
elif page == "Team Stats":
    st.title("TEAM STATS")
    st.caption("Per Game Averages")

    tab1, tab2, tab3 = st.tabs(["📊 Per Game", "🎯 Shooting", "🛡️ Defense / Rebounds"])

    search = st.text_input("🔍 Search team", "")

    def filter_df(df):
        if search:
            return df[df["Team"].str.contains(search, case=False)]
        return df

    with tab1:
        cols = ["Team", "PPG", "APG", "RPG", "SPG", "BPG", "TOPG"]
        cols = [c for c in cols if c in df3.columns]
        st.dataframe(filter_df(df3[cols]).set_index("Team").sort_values("PPG", ascending=False),
                     use_container_width=True, height=600)

    with tab2:
        cols = ["Team", "FG%", "3P%", "FT%", "3PA", "FTA"]
        cols = [c for c in cols if c in df3.columns]
        disp = filter_df(df3[cols]).copy()
        for pct_col in ["FG%", "3P%", "FT%"]:
            if pct_col in disp.columns:
                disp[pct_col] = (disp[pct_col] * 100).round(1).astype(str) + "%"
        st.dataframe(disp.set_index("Team"), use_container_width=True, height=600)

    with tab3:
        cols = ["Team", "RPG", "ORB", "DRB", "BPG", "SPG", "PF"]
        cols = [c for c in cols if c in df3.columns]
        st.dataframe(filter_df(df3[cols]).set_index("Team").sort_values("RPG", ascending=False),
                     use_container_width=True, height=600)

# ── ADVANCED ──────────────────────────────────────────────────────────────────
elif page == "Advanced":
    st.title("ADVANCED METRICS")
    st.caption("Offensive · Defensive · Four Factors")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("ORtg vs DRtg (Scatter)")
        valid = df4.dropna(subset=["ORtg", "DRtg"])
        avg_off = valid["ORtg"].mean()
        avg_def = valid["DRtg"].mean()

        def quadrant_color(row):
            if row["ORtg"] > avg_off and row["DRtg"] < avg_def: return GOLD
            if row["ORtg"] < avg_off and row["DRtg"] > avg_def: return "#ef4444"
            return "#6b7280"

        valid = valid.copy()
        valid["color"] = valid.apply(quadrant_color, axis=1)
        fig = go.Figure()
        fig.add_vline(x=avg_def, line_dash="dash", line_color="#1f2329")
        fig.add_hline(y=avg_off, line_dash="dash", line_color="#1f2329")
        fig.add_trace(go.Scatter(
            x=valid["DRtg"], y=valid["ORtg"], mode="markers+text",
            text=valid["Team"].str.split().str[-1],
            textposition="top center", textfont=dict(size=9, color="#9ca3af"),
            marker=dict(size=10, color=valid["color"]),
            hovertext=valid["Team"] + "<br>ORtg: " + valid["ORtg"].astype(str) +
                      " | DRtg: " + valid["DRtg"].astype(str)
        ))
        fig.update_layout(**PLOTLY_THEME, height=400,
                          xaxis_title="← Better   DEF RTG   Worse →",
                          yaxis_title="OFF RTG", showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.subheader("Net Rating Ranking")
        nrtg = df4.dropna(subset=["NRtg"]).sort_values("NRtg")
        colors = ["#22c55e" if v > 0 else "#ef4444" for v in nrtg["NRtg"]]
        fig2 = go.Figure(go.Bar(
            x=nrtg["NRtg"], y=nrtg["Team"], orientation="h",
            marker_color=colors,
            text=nrtg["NRtg"].round(1), textposition="outside",
            textfont=dict(size=9, color="#9ca3af")
        ))
        fig2.update_layout(**PLOTLY_THEME, height=400, showlegend=False)
        st.plotly_chart(fig2, use_container_width=True)

    st.markdown("---")
    st.subheader("Full Advanced Table")
    search_adv = st.text_input("🔍 Search team", "", key="adv_search")
    adv_cols = ["Team", "ORtg", "DRtg", "NRtg", "Pace", "TS%", "eFG%", "TOV%", "ORB%", "Age"]
    adv_cols = [c for c in adv_cols if c in df4.columns]
    disp = df4[adv_cols].copy()
    if search_adv:
        disp = disp[disp["Team"].str.contains(search_adv, case=False)]
    st.dataframe(disp.set_index("Team").sort_values("NRtg", ascending=False),
                 use_container_width=True, height=500)

# ── ATTENDANCE ────────────────────────────────────────────────────────────────
elif page == "Attendance":
    st.title("ATTENDANCE")
    st.caption("Arena Capacity & Fan Engagement")

    att = df4.dropna(subset=["Attend./G"]).sort_values("Attend./G", ascending=False)

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Attendance", f"{att['Attend.'].sum()/1e6:.2f}M")
    c2.metric("Avg Per Game", f"{att['Attend./G'].mean():,.0f}")
    c3.metric("Top Draw", att.iloc[0]["Team"], f"{att.iloc[0]['Attend./G']:,.0f} /game")

    st.markdown("---")
    col1, col2 = st.columns([3, 2])

    with col1:
        st.subheader("Attendance Per Game — All Arenas")
        colors = [GOLD if i == 0 else ("rgba(200,168,75,0.45)" if i < 5 else "rgba(200,168,75,0.15)")
                  for i in range(len(att))]
        fig = go.Figure(go.Bar(
            x=att["Attend./G"], y=att["Team"], orientation="h",
            marker_color=colors,
            text=att["Attend./G"].apply(lambda x: f"{x:,.0f}"),
            textposition="outside", textfont=dict(size=9, color="#9ca3af")
        ))
        fig.update_layout(**PLOTLY_THEME, height=700,
                          xaxis=dict(tickformat=",", gridcolor="#1a1d22", linecolor="#1f2329"),
                          yaxis=dict(gridcolor="#1a1d22", linecolor="#1f2329"),
                          showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.subheader("Arena Directory")
        arena_cols = ["Team", "Arena", "Attend.", "Attend./G"]
        arena_cols = [c for c in arena_cols if c in df4.columns]
        disp = att[arena_cols].copy()
        if "Attend." in disp.columns:
            disp["Attend."] = disp["Attend."].apply(lambda x: f"{int(x):,}" if pd.notna(x) else "-")
        if "Attend./G" in disp.columns:
            disp["Attend./G"] = disp["Attend./G"].apply(lambda x: f"{int(x):,}" if pd.notna(x) else "-")
        st.dataframe(disp.set_index("Team"), use_container_width=True, height=700)
