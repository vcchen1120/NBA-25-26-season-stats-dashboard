"""
NBA 25-26 Data Pipeline
========================
Flow:
  1. Try fetching from stats.nba.com (nba_api)
  2. On failure → fallback to Excel file
  3. Clean & transform data
  4. Store into SQLite (4 tables)
  5. Log each run with timestamp + source
"""

import sqlite3
import pandas as pd
import numpy as np
import re
import os
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

DB_PATH   = os.path.join(os.path.dirname(__file__), "nba_stats.db")
XLSX_PATH = os.path.join(os.path.dirname(__file__), "nba_25-26_stats.xlsx")
SEASON    = "2025-26"

NBA_HEADERS = {
    "Host": "stats.nba.com",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:72.0) Gecko/20100101 Firefox/72.0",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "x-nba-stats-origin": "stats",
    "x-nba-stats-token": "true",
    "Connection": "keep-alive",
    "Referer": "https://www.nba.com/",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
}

# ── Helpers ────────────────────────────────────────────────────────────────────

def clean_team(name):
    if not isinstance(name, str):
        return name
    return re.sub(r"\s*\(\d+\)", "", name).replace("*", "").strip()

def get_conn():
    return sqlite3.connect(DB_PATH)

# ── NBA API fetch ──────────────────────────────────────────────────────────────

def fetch_from_api():
    """Fetch all tables from stats.nba.com. Returns (pg, totals, standings, advanced) or raises."""
    from nba_api.stats.endpoints import (
        leaguedashteamstats,
        leaguestandingsv3,
        teamestimatedmetrics,
    )
    import time

    log.info("Fetching per-game stats from NBA API...")
    pg = leaguedashteamstats.LeagueDashTeamStats(
        season=SEASON, per_mode_detailed="PerGame",
        headers=NBA_HEADERS, timeout=45
    ).get_data_frames()[0]
    time.sleep(1.5)

    log.info("Fetching season totals from NBA API...")
    totals = leaguedashteamstats.LeagueDashTeamStats(
        season=SEASON, per_mode_detailed="Totals",
        headers=NBA_HEADERS, timeout=45
    ).get_data_frames()[0]
    time.sleep(1.5)

    log.info("Fetching standings from NBA API...")
    standings = leaguestandingsv3.LeagueStandingsV3(
        season=SEASON, headers=NBA_HEADERS, timeout=45
    ).get_data_frames()[0]
    time.sleep(1.5)

    log.info("Fetching advanced metrics from NBA API...")
    advanced = teamestimatedmetrics.TeamEstimatedMetrics(
        season=SEASON, headers=NBA_HEADERS, timeout=45
    ).get_data_frames()[0]

    return pg, totals, standings, advanced

# ── Excel fallback ─────────────────────────────────────────────────────────────

def fetch_from_excel():
    """Read all 4 sheets from Excel. Returns (pg, totals, standings_east, standings_west, advanced)."""
    log.info("Loading data from Excel fallback...")

    # Sheet 1 – Totals
    totals = pd.read_excel(XLSX_PATH, sheet_name="工作表1")
    totals["Team"] = totals["Team"].apply(clean_team)

    # Sheet 2 – Standings
    df2 = pd.read_excel(XLSX_PATH, sheet_name="工作表2")
    df2.columns = ["Team", "W", "L", "WL_pct", "GB", "PS_G", "PA_G", "SRS"]
    east, west = [], []
    conf = "East"
    for _, row in df2.iterrows():
        name = str(row["Team"]).strip()
        if "Eastern" in name:  conf = "East";  continue
        if "Western" in name:  conf = "West";  continue
        try:   int(row["W"])
        except: continue
        entry = {
            "team": clean_team(name), "W": int(row["W"]), "L": int(row["L"]),
            "WL_pct": float(row["WL_pct"]), "PS_G": float(row["PS_G"]),
            "PA_G": float(row["PA_G"]),  "SRS": float(row["SRS"]),
            "conference": conf,
            "playoff": 1 if "*" in str(row["Team"]) else 0,
        }
        (east if conf == "East" else west).append(entry)
    standings = pd.DataFrame(east + west)

    # Sheet 3 – Per Game
    pg = pd.read_excel(XLSX_PATH, sheet_name="工作表3")
    pg = pg[pg["Rk"].apply(lambda x: str(x).isdigit())].copy()
    pg["Team"] = pg["Team"].apply(clean_team)
    pg = pg.rename(columns={
        "PTS": "PPG", "AST": "APG", "TRB": "RPG",
        "STL": "SPG", "BLK": "BPG", "TOV": "TOPG",
        "FG%": "FG_PCT", "3P%": "FG3_PCT", "FT%": "FT_PCT",
    })
    for col in ["PPG","APG","RPG","SPG","BPG","TOPG","FG_PCT","FG3_PCT","FT_PCT",
                "3PA","FTA","ORB","DRB","PF"]:
        if col in pg.columns:
            pg[col] = pd.to_numeric(pg[col], errors="coerce")

    # Sheet 4 – Advanced
    df4r = pd.read_excel(XLSX_PATH, sheet_name="工作表4", header=None)
    hr = df4r[df4r.iloc[:, 0] == "Rk"].index[0]
    adv = df4r.iloc[hr:].copy()
    adv.columns = adv.iloc[0]
    adv = adv[1:].reset_index(drop=True)
    adv = adv[adv["Rk"].apply(lambda x: str(x).strip().isdigit())].copy()
    adv["Team"] = adv["Team"].apply(clean_team)
    adv = adv.loc[:, ~adv.columns.duplicated()].copy()
    for col in ["ORtg","DRtg","NRtg","Pace","TS%","eFG%","TOV%","ORB%",
                "W","L","Age","Attend.","Attend./G","MOV","SOS","SRS","FTr","3PAr"]:
        if col in adv.columns:
            adv[col] = pd.to_numeric(adv[col], errors="coerce")

    return pg, totals, standings, adv

# ── Transform: normalise API response to match our schema ─────────────────────

def transform_api(pg_raw, totals_raw, standings_raw, adv_raw):
    """Rename NBA API columns to our standard schema."""

    # Per Game
    pg = pg_raw.rename(columns={
        "TEAM_NAME": "Team", "PTS": "PPG", "AST": "APG", "REB": "RPG",
        "STL": "SPG", "BLK": "BPG", "TOV": "TOPG",
        "FG_PCT": "FG_PCT", "FG3_PCT": "FG3_PCT", "FT_PCT": "FT_PCT",
        "OREB": "ORB", "DREB": "DRB", "PF": "PF",
        "FG3A": "3PA", "FTA": "FTA",
    })

    # Totals
    totals = totals_raw.rename(columns={"TEAM_NAME": "Team"})

    # Standings
    st = standings_raw.rename(columns={
        "TeamName": "team", "WINS": "W", "LOSSES": "L",
        "WinPct": "WL_pct", "PointsPG": "PS_G", "OppPointsPG": "PA_G",
        "Conference": "conference",
    })
    st["playoff"] = st.get("PlayoffRank", pd.Series(0)).apply(lambda x: 1 if x and int(x) <= 8 else 0)

    # Advanced (estimated metrics from API are different columns)
    adv = adv_raw.rename(columns={
        "TEAM_NAME": "Team",
        "E_OFF_RATING": "ORtg", "E_DEF_RATING": "DRtg",
        "E_NET_RATING": "NRtg", "E_PACE": "Pace",
        "E_AST_RATIO": "AST_RATIO", "E_OREB_PCT": "ORB%",
        "E_REB_PCT": "REB_PCT",
    })

    return pg, totals, st, adv

# ── Load into SQLite ───────────────────────────────────────────────────────────

def load_to_db(pg, totals, standings, adv, source):
    conn = get_conn()
    cur  = conn.cursor()

    # Create pipeline_log table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pipeline_log (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            run_at    TEXT NOT NULL,
            source    TEXT NOT NULL,
            status    TEXT NOT NULL,
            message   TEXT
        )
    """)

    # Write tables (replace fully on each run)
    keep_pg = [c for c in ["Team","PPG","APG","RPG","SPG","BPG","TOPG",
                            "FG_PCT","FG3_PCT","FT_PCT","3PA","FTA","ORB","DRB","PF"]
               if c in pg.columns]
    pg[keep_pg].to_sql("team_pergame", conn, if_exists="replace", index=False)

    standings.to_sql("standings", conn, if_exists="replace", index=False)

    adv_keep = [c for c in ["Team","ORtg","DRtg","NRtg","Pace","TS%","eFG%",
                             "TOV%","ORB%","Age","Attend.","Attend./G",
                             "MOV","SOS","SRS","FTr","3PAr","Arena"]
                if c in adv.columns]
    adv[adv_keep].to_sql("team_advanced", conn, if_exists="replace", index=False)

    keep_tot = [c for c in totals.columns if c in
                ["Team","G","MP","FG","FGA","FG_PCT","FG3","FG3A","FG3_PCT",
                 "FTA","FT_PCT","ORB","DRB","TRB","AST","STL","BLK","TOV","PF","PTS"]]
    if keep_tot:
        totals[keep_tot].to_sql("team_totals", conn, if_exists="replace", index=False)

    # Log this run
    cur.execute(
        "INSERT INTO pipeline_log (run_at, source, status, message) VALUES (?,?,?,?)",
        (datetime.now().isoformat(), source, "success",
         f"Loaded {len(pg)} teams from {source}")
    )
    conn.commit()
    conn.close()
    log.info(f"✓ Data written to SQLite from source={source}")

# ── Main entry point ───────────────────────────────────────────────────────────

def run_pipeline():
    source = "nba_api"
    try:
        pg_raw, tot_raw, st_raw, adv_raw = fetch_from_api()
        pg, totals, standings, adv = transform_api(pg_raw, tot_raw, st_raw, adv_raw)
        log.info("NBA API fetch successful.")
    except Exception as e:
        log.warning(f"NBA API failed ({e}), falling back to Excel.")
        source = "excel_fallback"
        pg, totals, standings, adv = fetch_from_excel()

    load_to_db(pg, totals, standings, adv, source)
    return source

# ── DB read helpers (used by app.py) ──────────────────────────────────────────

def db_exists():
    if not os.path.exists(DB_PATH):
        return False
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {r[0] for r in cur.fetchall()}
    conn.close()
    return {"team_pergame", "standings", "team_advanced"}.issubset(tables)

def read_pergame():
    return pd.read_sql("SELECT * FROM team_pergame", get_conn())

def read_standings():
    return pd.read_sql("SELECT * FROM standings", get_conn())

def read_advanced():
    return pd.read_sql("SELECT * FROM team_advanced", get_conn())

def read_totals():
    try:
        return pd.read_sql("SELECT * FROM team_totals", get_conn())
    except Exception:
        return pd.DataFrame()

def read_pipeline_log():
    return pd.read_sql(
        "SELECT run_at, source, status, message FROM pipeline_log ORDER BY id DESC LIMIT 10",
        get_conn()
    )

def last_updated():
    try:
        df = pd.read_sql(
            "SELECT run_at, source FROM pipeline_log ORDER BY id DESC LIMIT 1",
            get_conn()
        )
        if df.empty: return "Never", "–"
        return df.iloc[0]["run_at"][:19], df.iloc[0]["source"]
    except Exception:
        return "Never", "–"

if __name__ == "__main__":
    run_pipeline()
