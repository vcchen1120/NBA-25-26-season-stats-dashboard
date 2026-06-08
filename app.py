import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from pipeline import (
    run_pipeline, db_exists,
    read_pergame, read_standings, read_advanced, read_players, last_updated
)

st.set_page_config(
    page_title="NBA 25-26 Dashboard",
    page_icon="🏀",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=DM+Mono:wght@400;500&display=swap');
h1,h2,h3{font-family:'Bebas Neue',sans-serif;letter-spacing:2px}
.stMetric{background:#0f1114;border:1px solid #1f2329;border-radius:10px;padding:12px}
div[data-testid="stMetricValue"]{font-size:2rem;color:#c8a84b}
div[data-testid="stMetricLabel"]{color:#6b7280;font-size:11px;letter-spacing:1px}
.source-badge{
    display:inline-block;padding:3px 10px;border-radius:99px;font-size:11px;font-weight:600;
    font-family:'DM Mono',monospace;letter-spacing:1px
}
.badge-api{background:rgba(34,197,94,0.15);color:#22c55e;border:1px solid rgba(34,197,94,0.3)}
.badge-excel{background:rgba(200,168,75,0.15);color:#c8a84b;border:1px solid rgba(200,168,75,0.3)}
</style>
""", unsafe_allow_html=True)

GOLD = "#c8a84b"
THEME = dict(
    plot_bgcolor="#07080a", paper_bgcolor="#07080a",
    font=dict(color="#9ca3af", family="DM Mono"),
    margin=dict(l=10, r=10, t=30, b=10)
)
AXIS = dict(gridcolor="#1a1d22", linecolor="#1f2329",
            ticks="", tickfont=dict(size=10))

# ── Bootstrap DB on first run ─────────────────────────────────────────────────
if not db_exists():
    with st.spinner("⚙️ 首次啟動：正在建立資料庫..."):
        run_pipeline()

# ── Load data from SQLite ─────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def load():
    pg  = read_pergame()
    st_ = read_standings()
    adv = read_advanced()
    return pg, st_, adv

pg, standings, adv = load()
east_df = standings[standings["conference"] == "East"].reset_index(drop=True)
west_df = standings[standings["conference"] == "West"].reset_index(drop=True)
all_teams = standings.reset_index(drop=True)

ts, src = last_updated()
src_badge = (f'<span class="source-badge badge-api">🟢 NBA API</span>'
             if src == "github"
             else f'<span class="source-badge badge-excel">🟡 Excel Fallback</span>')

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🏀 NBA 25-26")
    st.markdown("---")
    page = st.radio("Navigate", ["Overview", "Standings", "Team Stats", "Advanced", "Attendance", "Pipeline Log"])
    st.markdown("---")

    st.markdown(f"**Last Updated**  \n`{ts}`")
    st.markdown(f"**Source** {src_badge}", unsafe_allow_html=True)
    st.markdown("")

    if st.button("🔄 Refresh from NBA API"):
        st.cache_data.clear()
        with st.spinner("Running ETL pipeline..."):
            source_used = run_pipeline()
        label = '🟢 GitHub' if source_used == 'github' else '🟡 Local Excel'
        st.success(f"✓ Updated from **{label}**")
        st.rerun()

    st.caption("Data: NBA 2025-26 Regular Season  \nPipeline: GitHub → SQLite")

# ── OVERVIEW ──────────────────────────────────────────────────────────────────
if page == "Overview":
    st.title("LEAGUE OVERVIEW")
    st.caption("2025–26 Regular Season · All 30 Teams")

    top_idx  = all_teams["W"].idxmax()
    top_team = all_teams.loc[top_idx]
    playoff_n = len(all_teams[all_teams["playoff"] == 1])

    c1,c2,c3,c4,c5 = st.columns(5)
    c1.metric("Avg PPG",    f"{pg['PPG'].mean():.1f}")
    c2.metric("Avg APG",    f"{pg['APG'].mean():.1f}")
    c3.metric("Avg RPG",    f"{pg['RPG'].mean():.1f}")
    c4.metric("Best Record",f"{int(top_team['W'])}-{int(top_team['L'])}", str(top_team["team"]))
    c5.metric("Playoff Teams", playoff_n)

    st.markdown("---")
    col1, col2 = st.columns([3, 2])

    with col1:
        st.subheader("Points Per Game — All Teams")
        spg = pg.sort_values("PPG", ascending=True)
        n   = len(spg)
        colors = [GOLD if i >= n-3 else "rgba(200,168,75,0.25)" for i in range(n)]
        fig = go.Figure(go.Bar(
            x=spg["PPG"], y=spg["Team"], orientation="h",
            marker_color=colors,
            text=spg["PPG"].round(1), textposition="outside",
            textfont=dict(size=9, color="#9ca3af")
        ))
        fig.update_layout(**THEME, height=680, showlegend=False)
        fig.update_xaxes(**AXIS, range=[95, spg["PPG"].max()+3])
        fig.update_yaxes(**AXIS)
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.subheader("Win % Distribution")
        labels = ["Elite (70%+)", "Good (55-70%)", "Average (45-55%)", "Rebuilding (<45%)"]
        counts = [
            len(all_teams[all_teams["WL_pct"] >= 0.7]),
            len(all_teams[(all_teams["WL_pct"] >= 0.55) & (all_teams["WL_pct"] < 0.7)]),
            len(all_teams[(all_teams["WL_pct"] >= 0.45) & (all_teams["WL_pct"] < 0.55)]),
            len(all_teams[all_teams["WL_pct"] < 0.45]),
        ]
        fig2 = go.Figure(go.Pie(
            labels=labels, values=counts, hole=0.5,
            marker_colors=[GOLD, "rgba(200,168,75,0.55)", "rgba(200,168,75,0.2)", "rgba(224,92,46,0.4)"],
        ))
        fig2.update_layout(**THEME, height=280,
                           legend=dict(font=dict(size=10), orientation="h",
                                       y=-0.15, x=0))
        st.plotly_chart(fig2, use_container_width=True)

        st.subheader("Top 5 Scoring Teams")
        top5 = pg.nlargest(5, "PPG")[["Team","PPG","APG","RPG"]].reset_index(drop=True)
        top5.index += 1
        st.dataframe(top5, use_container_width=True)

    st.subheader("Shooting Efficiency — Top 10")
    top10 = pg.nlargest(10, "PPG").copy()
    fig3 = go.Figure()
    fig3.add_trace(go.Bar(name="FG%", x=top10["Team"],
                          y=(top10["FG_PCT"]*100).round(1),
                          marker_color="rgba(200,168,75,0.7)"))
    fig3.add_trace(go.Bar(name="3P%", x=top10["Team"],
                          y=(top10["FG3_PCT"]*100).round(1),
                          marker_color="rgba(224,92,46,0.7)"))
    fig3.update_layout(**THEME, barmode="group", height=300,
                       legend=dict(font=dict(size=11, color="#9ca3af")))
    fig3.update_xaxes(**AXIS)
    fig3.update_yaxes(**AXIS)
    st.plotly_chart(fig3, use_container_width=True)

# ── STANDINGS ─────────────────────────────────────────────────────────────────
elif page == "Standings":
    st.title("STANDINGS")
    st.caption("✅ = Playoff Qualified")

    def fmt_standings(df):
        d = df.copy()
        d["WL%"]  = (d["WL_pct"] * 100).round(1).astype(str) + "%"
        d["Playoff"] = d["playoff"].apply(lambda x: "✅" if x == 1 else "")
        cols = ["team","W","L","WL%","PS_G","PA_G","SRS","Playoff"]
        cols = [c for c in cols if c in d.columns]
        return d[cols].rename(columns={"team":"Team","PS_G":"PPG","PA_G":"OPP PPG"})

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("🔵 Eastern Conference")
        st.dataframe(fmt_standings(east_df).set_index("Team"),
                     use_container_width=True, height=560)
    with col2:
        st.subheader("🟡 Western Conference")
        st.dataframe(fmt_standings(west_df).set_index("Team"),
                     use_container_width=True, height=560)

    st.markdown("---")
    st.subheader("Win Total Comparison — Top 20")
    top20 = all_teams.sort_values("W", ascending=False).head(20)
    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Wins", y=top20["team"], x=top20["W"], orientation="h",
        marker_color=["#3a7bd5" if c=="East" else GOLD for c in top20["conference"]]
    ))
    fig.add_trace(go.Bar(
        name="Losses", y=top20["team"], x=top20["L"], orientation="h",
        marker_color="rgba(80,80,80,0.35)"
    ))
    fig.update_layout(**THEME, barmode="stack", height=520,
                      legend=dict(font=dict(size=11, color="#9ca3af")))
    fig.update_xaxes(**AXIS)
    fig.update_yaxes(**AXIS)
    st.plotly_chart(fig, use_container_width=True)

# ── TEAM STATS ────────────────────────────────────────────────────────────────
elif page == "Team Stats":
    st.title("TEAM STATS")
    st.caption("Per Game Averages")

    tab1, tab2, tab3 = st.tabs(["📊 Per Game", "🎯 Shooting", "🛡️ Defense / Rebounds"])
    search = st.text_input("🔍 Search team", "")

    def filt(df):
        return df[df["Team"].str.contains(search, case=False)] if search else df

    with tab1:
        cols = [c for c in ["Team","PPG","APG","RPG","SPG","BPG","TOPG"] if c in pg.columns]
        st.dataframe(filt(pg[cols]).sort_values("PPG", ascending=False).set_index("Team"),
                     use_container_width=True, height=620)
    with tab2:
        disp = pg.copy()
        for c in ["FG_PCT","FG3_PCT","FT_PCT"]:
            if c in disp.columns:
                disp[c] = (disp[c]*100).round(1).astype(str)+"%"
        cols = [c for c in ["Team","FG_PCT","FG3_PCT","FT_PCT","3PA","FTA"] if c in disp.columns]
        st.dataframe(filt(disp[cols]).set_index("Team"), use_container_width=True, height=620)
    with tab3:
        cols = [c for c in ["Team","RPG","ORB","DRB","BPG","SPG","PF"] if c in pg.columns]
        st.dataframe(filt(pg[cols]).sort_values("RPG", ascending=False).set_index("Team"),
                     use_container_width=True, height=620)

# ── ADVANCED ──────────────────────────────────────────────────────────────────
elif page == "Advanced":
    st.title("ADVANCED METRICS")
    st.caption("Offensive · Defensive · Four Factors")

    col1, col2 = st.columns(2)
    valid = adv.dropna(subset=["ORtg","DRtg"]).copy()

    with col1:
        st.subheader("ORtg vs DRtg")
        avg_off = valid["ORtg"].mean()
        avg_def = valid["DRtg"].mean()
        def qcolor(row):
            if row["ORtg"] > avg_off and row["DRtg"] < avg_def: return GOLD
            if row["ORtg"] < avg_off and row["DRtg"] > avg_def: return "#ef4444"
            return "#6b7280"
        valid["color"] = valid.apply(qcolor, axis=1)
        fig = go.Figure()
        fig.add_vline(x=avg_def, line_dash="dash", line_color="#2d3139")
        fig.add_hline(y=avg_off, line_dash="dash", line_color="#2d3139")
        fig.add_trace(go.Scatter(
            x=valid["DRtg"], y=valid["ORtg"], mode="markers+text",
            text=valid["Team"].str.split().str[-1],
            textposition="top center", textfont=dict(size=9, color="#9ca3af"),
            marker=dict(size=10, color=valid["color"]),
            hovertemplate="<b>%{text}</b><br>ORtg: %{y}<br>DRtg: %{x}<extra></extra>"
        ))
        fig.update_layout(**THEME, height=400, showlegend=False,
                          xaxis_title="← Better   DEF RTG   Worse →",
                          yaxis_title="OFF RTG")
        fig.update_xaxes(**AXIS)
        fig.update_yaxes(**AXIS)
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.subheader("Net Rating Ranking")
        nrtg = adv.dropna(subset=["NRtg"]).sort_values("NRtg")
        colors = ["#22c55e" if v > 0 else "#ef4444" for v in nrtg["NRtg"]]
        fig2 = go.Figure(go.Bar(
            x=nrtg["NRtg"], y=nrtg["Team"], orientation="h",
            marker_color=colors,
            text=nrtg["NRtg"].round(1), textposition="outside",
            textfont=dict(size=9, color="#9ca3af")
        ))
        fig2.update_layout(**THEME, height=400, showlegend=False)
        fig2.update_xaxes(**AXIS)
        fig2.update_yaxes(**AXIS)
        st.plotly_chart(fig2, use_container_width=True)

    st.markdown("---")
    st.subheader("Full Advanced Table")
    search_adv = st.text_input("🔍 Search team", "", key="adv")
    adv_cols = [c for c in ["Team","ORtg","DRtg","NRtg","Pace","TS%","eFG%","TOV%","ORB%","Age"] if c in adv.columns]
    disp = adv[adv_cols].copy()
    if search_adv:
        disp = disp[disp["Team"].str.contains(search_adv, case=False)]
    if "NRtg" in disp.columns:
        disp = disp.sort_values("NRtg", ascending=False)
    st.dataframe(disp.set_index("Team"), use_container_width=True, height=520)

# ── ATTENDANCE ────────────────────────────────────────────────────────────────
elif page == "Attendance":
    st.title("ATTENDANCE")
    st.caption("Arena Capacity & Fan Engagement")

    att_col = "Attend./G"
    att = adv.dropna(subset=[att_col]).sort_values(att_col, ascending=False).copy()

    if att.empty:
        st.warning("Attendance data not available in current dataset.")
    else:
        c1,c2,c3 = st.columns(3)
        total_att = att["Attend."].sum() if "Attend." in att.columns else 0
        c1.metric("Total Attendance", f"{total_att/1e6:.2f}M" if total_att else "N/A")
        c2.metric("Avg Per Game", f"{att[att_col].mean():,.0f}")
        c3.metric("Top Draw", att.iloc[0]["Team"], f"{att.iloc[0][att_col]:,.0f} /game")

        st.markdown("---")
        col1, col2 = st.columns([3, 2])

        with col1:
            st.subheader("Attendance Per Game — All Arenas")
            n = len(att)
            colors = [GOLD if i==0 else ("rgba(200,168,75,0.45)" if i<5 else "rgba(200,168,75,0.15)")
                      for i in range(n)]
            fig = go.Figure(go.Bar(
                x=att[att_col], y=att["Team"], orientation="h",
                marker_color=colors,
                text=att[att_col].apply(lambda x: f"{x:,.0f}"),
                textposition="outside", textfont=dict(size=9, color="#9ca3af")
            ))
            fig.update_layout(**THEME, height=720, showlegend=False)
            fig.update_xaxes(**AXIS, tickformat=",")
            fig.update_yaxes(**AXIS)
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            st.subheader("Arena Directory")
            a_cols = [c for c in ["Team","Arena","Attend.","Attend./G"] if c in att.columns]
            disp = att[a_cols].copy()
            if "Attend." in disp.columns:
                disp["Attend."] = disp["Attend."].apply(lambda x: f"{int(x):,}" if pd.notna(x) else "-")
            disp[att_col] = disp[att_col].apply(lambda x: f"{int(x):,}" if pd.notna(x) else "-")
            st.dataframe(disp.set_index("Team"), use_container_width=True, height=720)

# ── PIPELINE LOG ──────────────────────────────────────────────────────────────
elif page == "Pipeline Log":
    st.title("PIPELINE LOG")
    st.caption("ETL run history")

    log_df = read_pipeline_log()
    if log_df.empty:
        st.info("No pipeline runs recorded yet.")
    else:
        log_df["source"] = log_df["source"].apply(
            lambda s: "🟢 GitHub" if s == "nba_api" else "🟡 Local Excel"
        )
        st.dataframe(log_df, use_container_width=True)

    st.markdown("---")
    st.subheader("Pipeline Architecture")
    st.code("""
GitHub (vcchen1120/NBA-25-26-season-stats-dashboard)
       │  on failure
       ▼
nba_25-26_stats.xlsx  (Excel fallback)
       │
       ▼  pipeline.py
   Extract → Transform → Clean
       │
       ▼
  SQLite  (nba_stats.db)
  ├── team_pergame
  ├── team_totals
  ├── standings
  ├── team_advanced
  └── pipeline_log
       │
       ▼
  app.py  (Streamlit)
  └── @st.cache_data (TTL 300s)
    """, language="text")

# ── PLAYERS (injected) ────────────────────────────────────────────────────────

# ── PLAYERS ───────────────────────────────────────────────────────────────────
elif page == "Players":
    st.title("PLAYERS")
    st.caption("Per Game Stats · 661 Players · 30 Teams")

    @st.cache_data(ttl=300)
    def get_players():
        return read_players()

    all_players = get_players()
    NUM_COLS = ["G","GS","MP","FG","FGA","FG%","3P","3PA","3P%",
                "FT","FTA","FT%","ORB","DRB","TRB","AST","STL","BLK","TOV","PF","PTS","eFG%"]
    for c in NUM_COLS:
        if c in all_players.columns:
            all_players[c] = pd.to_numeric(all_players[c], errors="coerce")

    tab1, tab2, tab3 = st.tabs(["🏀 Team Roster", "📊 League Rankings", "⚖️ Player Comparison"])

    # ── TAB 1: Team Roster → Player Detail ───────────────────────────────────
    with tab1:
        col1, col2 = st.columns([1, 2])
        with col1:
            teams = sorted(all_players["Team"].unique())
            selected_team = st.selectbox("Select Team", teams)
            roster = all_players[all_players["Team"] == selected_team].copy()
            roster_display = roster[["Player","Pos","Age","G","PTS","AST","TRB"]].copy()
            roster_display["PTS"] = roster_display["PTS"].round(1)
            roster_display["AST"] = roster_display["AST"].round(1)
            roster_display["TRB"] = roster_display["TRB"].round(1)
            selected_player = st.selectbox("Select Player", roster["Player"].tolist())

        with col2:
            p = roster[roster["Player"] == selected_player].iloc[0]
            st.subheader(f"{selected_player}")
            st.caption(f"{selected_team} · {p.get('Pos','–')} · Age {int(p['Age']) if pd.notna(p['Age']) else '–'} · {int(p['G']) if pd.notna(p['G']) else '–'} GP")

            m1,m2,m3,m4,m5 = st.columns(5)
            m1.metric("PPG",  f"{p['PTS']:.1f}"  if pd.notna(p.get('PTS'))  else "–")
            m2.metric("APG",  f"{p['AST']:.1f}"  if pd.notna(p.get('AST'))  else "–")
            m3.metric("RPG",  f"{p['TRB']:.1f}"  if pd.notna(p.get('TRB'))  else "–")
            m4.metric("STL",  f"{p['STL']:.1f}"  if pd.notna(p.get('STL'))  else "–")
            m5.metric("BLK",  f"{p['BLK']:.1f}"  if pd.notna(p.get('BLK'))  else "–")

            st.markdown("---")
            # Shooting radar bar
            shoot_cats  = ["FG%","3P%","FT%","eFG%"]
            shoot_vals  = [float(p[c])*100 if pd.notna(p.get(c)) else 0 for c in shoot_cats]
            fig = go.Figure(go.Bar(
                x=shoot_cats, y=shoot_vals,
                marker_color=[GOLD,"rgba(200,168,75,0.6)","rgba(200,168,75,0.4)","rgba(224,92,46,0.7)"],
                text=[f"{v:.1f}%" for v in shoot_vals], textposition="outside",
                textfont=dict(size=11, color="#9ca3af")
            ))
            fig.update_layout(**THEME, height=240, showlegend=False,
                              yaxis_range=[0, 105], title_text="Shooting %")
            fig.update_xaxes(**AXIS); fig.update_yaxes(**AXIS)
            st.plotly_chart(fig, use_container_width=True)

            # Full stats table
            stat_cols = [c for c in ["G","GS","MP","PTS","AST","TRB","STL","BLK","TOV","FG%","3P%","FT%","eFG%"] if c in roster.columns]
            st.dataframe(roster[["Player"]+stat_cols].set_index("Player"), use_container_width=True)

    # ── TAB 2: League Rankings ────────────────────────────────────────────────
    with tab2:
        col1, col2 = st.columns([1, 3])
        with col1:
            rank_stat = st.selectbox("Rank by", ["PTS","AST","TRB","STL","BLK","FG%","3P%","FT%","eFG%"])
            min_games = st.slider("Min games played", 10, 82, 30)
            top_n     = st.slider("Show top N", 10, 50, 20)
            pos_filter = st.multiselect("Position", ["PG","SG","SF","PF","C"], default=[])

        with col2:
            filtered = all_players[all_players["G"] >= min_games].copy()
            if pos_filter:
                filtered = filtered[filtered["Pos"].isin(pos_filter)]
            filtered = filtered.dropna(subset=[rank_stat])
            top = filtered.nlargest(top_n, rank_stat)

            colors = [GOLD if i == 0 else ("rgba(200,168,75,0.5)" if i < 3 else "rgba(200,168,75,0.2)") for i in range(len(top))]
            label_col = rank_stat + "%" if "%" not in rank_stat else rank_stat
            text_vals = [(f"{v*100:.1f}%" if "%" in rank_stat else f"{v:.1f}") for v in top[rank_stat]]

            fig = go.Figure(go.Bar(
                x=top[rank_stat] * (100 if "%" in rank_stat else 1),
                y=top["Player"] + " (" + top["Team"].str.split().str[-1] + ")",
                orientation="h", marker_color=colors,
                text=text_vals, textposition="outside",
                textfont=dict(size=10, color="#9ca3af")
            ))
            fig.update_layout(**THEME, height=max(400, top_n*22), showlegend=False,
                              title_text=f"Top {top_n} — {rank_stat}")
            fig.update_xaxes(**AXIS); fig.update_yaxes(**AXIS)
            st.plotly_chart(fig, use_container_width=True)

    # ── TAB 3: Player Comparison ──────────────────────────────────────────────
    with tab3:
        c1, c2 = st.columns(2)
        with c1:
            t1 = st.selectbox("Team A", sorted(all_players["Team"].unique()), key="cmp_t1")
            p1_list = all_players[all_players["Team"]==t1]["Player"].tolist()
            p1_name = st.selectbox("Player A", p1_list, key="cmp_p1")
        with c2:
            t2 = st.selectbox("Team B", sorted(all_players["Team"].unique()), index=1, key="cmp_t2")
            p2_list = all_players[all_players["Team"]==t2]["Player"].tolist()
            p2_name = st.selectbox("Player B", p2_list, key="cmp_p2")

        p1 = all_players[all_players["Player"]==p1_name].iloc[0]
        p2 = all_players[all_players["Player"]==p2_name].iloc[0]

        cmp_stats = ["PTS","AST","TRB","STL","BLK","MP","FG%","3P%","FT%"]
        cmp_stats = [c for c in cmp_stats if c in all_players.columns]

        # KPI comparison row
        cols = st.columns(len(cmp_stats))
        for i, stat in enumerate(cmp_stats):
            v1 = float(p1[stat]) if pd.notna(p1.get(stat)) else 0
            v2 = float(p2[stat]) if pd.notna(p2.get(stat)) else 0
            fmt = lambda v: f"{v*100:.1f}%" if "%" in stat else f"{v:.1f}"
            delta = v1 - v2
            cols[i].metric(stat, fmt(v1), f"{'+' if delta>=0 else ''}{fmt(delta)} vs {p2_name.split()[-1]}")

        st.markdown("---")
        # Radar-style grouped bar
        vals1 = []
        vals2 = []
        labels = []
        for stat in ["PTS","AST","TRB","STL","BLK"]:
            if stat in all_players.columns:
                labels.append(stat)
                vals1.append(float(p1[stat]) if pd.notna(p1.get(stat)) else 0)
                vals2.append(float(p2[stat]) if pd.notna(p2.get(stat)) else 0)

        fig = go.Figure()
        fig.add_trace(go.Bar(name=p1_name, x=labels, y=vals1,
                             marker_color=GOLD, text=[f"{v:.1f}" for v in vals1],
                             textposition="outside"))
        fig.add_trace(go.Bar(name=p2_name, x=labels, y=vals2,
                             marker_color="rgba(58,123,213,0.8)", text=[f"{v:.1f}" for v in vals2],
                             textposition="outside"))
        fig.update_layout(**THEME, barmode="group", height=360,
                          legend=dict(font=dict(size=12,color="#9ca3af")),
                          title_text=f"{p1_name} vs {p2_name}")
        fig.update_xaxes(**AXIS); fig.update_yaxes(**AXIS)
        st.plotly_chart(fig, use_container_width=True)

        # Shooting comparison
        shoot = ["FG%","3P%","FT%","eFG%"]
        shoot = [c for c in shoot if c in all_players.columns]
        sv1 = [float(p1[c])*100 if pd.notna(p1.get(c)) else 0 for c in shoot]
        sv2 = [float(p2[c])*100 if pd.notna(p2.get(c)) else 0 for c in shoot]
        fig2 = go.Figure()
        fig2.add_trace(go.Bar(name=p1_name, x=shoot, y=sv1, marker_color=GOLD,
                              text=[f"{v:.1f}%" for v in sv1], textposition="outside"))
        fig2.add_trace(go.Bar(name=p2_name, x=shoot, y=sv2,
                              marker_color="rgba(58,123,213,0.8)",
                              text=[f"{v:.1f}%" for v in sv2], textposition="outside"))
        fig2.update_layout(**THEME, barmode="group", height=300,
                           legend=dict(font=dict(size=12,color="#9ca3af")),
                           title_text="Shooting Efficiency Comparison",
                           yaxis_range=[0,105])
        fig2.update_xaxes(**AXIS); fig2.update_yaxes(**AXIS)
        st.plotly_chart(fig2, use_container_width=True)
