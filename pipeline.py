"""
NBA 25-26 Data Pipeline
========================
Flow:
  1. Fetch from balldontlie.io API (per-game, standings, advanced)
  2. On failure → fallback to Excel file
  3. Clean & transform
  4. Store into SQLite (4 tables + pipeline_log)
"""

import sqlite3
import pandas as pd
import numpy as np
import re
import os
import logging
import time
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

DB_PATH   = os.path.join(os.path.dirname(__file__), "nba_stats.db")
XLSX_PATH = os.path.join(os.path.dirname(__file__), "nba_25-26_stats.xlsx")

# ── balldontlie config ─────────────────────────────────────────────────────────
BDL_KEY     = "e33b5508-b64d-4927-9d13-0509e46b85cb"
BDL_HEADERS = {"Authorization": BDL_KEY}
BDL_BASE    = "https://api.balldontlie.io/nba/v1"
SEASON      = 2025   # balldontlie uses 2025 for the 2025-26 season

# ── Helpers ────────────────────────────────────────────────────────────────────
def clean_team(name):
    if not isinstance(name, str): return name
    return re.sub(r"\s*\(\d+\)", "", name).replace("*", "").strip()

def get_conn():
    return sqlite3.connect(DB_PATH)

def bdl_get(path, params=None):
    """GET from balldontlie with auto-pagination."""
    import requests
    url = f"{BDL_BASE}/{path}"
    all_data = []
    params = params or {}
    params["per_page"] = 100

    while url:
        r = requests.get(url, headers=BDL_HEADERS, params=params, timeout=30)
        r.raise_for_status()
        body = r.json()
        all_data.extend(body.get("data", []))
        # cursor-based pagination
        meta = body.get("meta", {})
        next_cursor = meta.get("next_cursor")
        if next_cursor:
            params["cursor"] = next_cursor
            params = {k: v for k, v in params.items() if k != "per_page"}
            url = f"{BDL_BASE}/{path}"
        else:
            url = None
        time.sleep(0.5)

    return all_data

# ── balldontlie fetch ──────────────────────────────────────────────────────────
def fetch_from_api():
    log.info("Fetching per-game averages from balldontlie...")
    pg_raw = bdl_get("team_season_averages/base", {"seasons[]": SEASON})
    if not pg_raw:
        raise ValueError("Empty per-game response from balldontlie")

    log.info("Fetching standings from balldontlie...")
    st_raw = bdl_get("standings", {"season": SEASON})

    log.info("Fetching advanced metrics from balldontlie...")
    adv_raw = bdl_get("team_season_averages/advanced", {"seasons[]": SEASON})

    return pg_raw, st_raw, adv_raw

def transform_api(pg_raw, st_raw, adv_raw):
    """Flatten nested JSON → DataFrames."""

    # ── Per Game ──────────────────────────────────────────────────────────────
    pg_rows = []
    for r in pg_raw:
        team = r.get("team", {})
        pg_rows.append({
            "Team":    team.get("full_name", team.get("name", "")),
            "PPG":     r.get("pts"),
            "APG":     r.get("ast"),
            "RPG":     r.get("reb"),
            "SPG":     r.get("stl"),
            "BPG":     r.get("blk"),
            "TOPG":    r.get("turnover"),
            "FG_PCT":  r.get("fg_pct"),
            "FG3_PCT": r.get("fg3_pct"),
            "FT_PCT":  r.get("ft_pct"),
            "ORB":     r.get("oreb"),
            "DRB":     r.get("dreb"),
            "3PA":     r.get("fg3a"),
            "FTA":     r.get("fta"),
            "PF":      r.get("pf"),
            "GP":      r.get("games_played"),
        })
    pg = pd.DataFrame(pg_rows)

    # ── Standings ─────────────────────────────────────────────────────────────
    st_rows = []
    for r in st_raw:
        team = r.get("team", {})
        conf = team.get("conference", "")
        st_rows.append({
            "team":       team.get("full_name", team.get("name", "")),
            "W":          r.get("wins"),
            "L":          r.get("losses"),
            "WL_pct":     r.get("win_pct"),
            "PS_G":       r.get("pts_per_game"),
            "PA_G":       r.get("opp_pts_per_game"),
            "conference": "East" if "East" in conf else "West",
            "playoff":    1 if r.get("playoff_rank") and int(r.get("playoff_rank", 99)) <= 8 else 0,
            "SRS":        r.get("srs", None),
        })
    standings = pd.DataFrame(st_rows)

    # ── Advanced ──────────────────────────────────────────────────────────────
    adv_rows = []
    for r in adv_raw:
        team = r.get("team", {})
        adv_rows.append({
            "Team":   team.get("full_name", team.get("name", "")),
            "ORtg":   r.get("off_rating"),
            "DRtg":   r.get("def_rating"),
            "NRtg":   r.get("net_rating"),
            "Pace":   r.get("pace"),
            "TS%":    r.get("ts_pct"),
            "eFG%":   r.get("efg_pct"),
            "TOV%":   r.get("tm_tov_pct"),
            "ORB%":   r.get("oreb_pct"),
            "AST%":   r.get("ast_pct"),
        })
    adv = pd.DataFrame(adv_rows)

    return pg, standings, adv

# ── Excel fallback ─────────────────────────────────────────────────────────────
def fetch_from_excel():
    log.info("Loading from Excel fallback...")

    # Sheet 3 – Per Game
    pg = pd.read_excel(XLSX_PATH, sheet_name="工作表3")
    pg = pg[pg["Rk"].apply(lambda x: str(x).isdigit())].copy()
    pg["Team"] = pg["Team"].apply(clean_team)
    pg = pg.rename(columns={
        "PTS":"PPG","AST":"APG","TRB":"RPG","STL":"SPG","BLK":"BPG","TOV":"TOPG",
        "FG%":"FG_PCT","3P%":"FG3_PCT","FT%":"FT_PCT",
    })
    for col in ["PPG","APG","RPG","SPG","BPG","TOPG","FG_PCT","FG3_PCT","FT_PCT",
                "3PA","FTA","ORB","DRB","PF"]:
        if col in pg.columns:
            pg[col] = pd.to_numeric(pg[col], errors="coerce")

    # Sheet 2 – Standings
    df2 = pd.read_excel(XLSX_PATH, sheet_name="工作表2")
    df2.columns = ["Team","W","L","WL_pct","GB","PS_G","PA_G","SRS"]
    rows, conf = [], "East"
    for _, row in df2.iterrows():
        name = str(row["Team"]).strip()
        if "Eastern" in name: conf = "East"; continue
        if "Western" in name: conf = "West"; continue
        try: int(row["W"])
        except: continue
        rows.append({
            "team":       clean_team(name),
            "W":          int(row["W"]),   "L": int(row["L"]),
            "WL_pct":     float(row["WL_pct"]),
            "PS_G":       float(row["PS_G"]), "PA_G": float(row["PA_G"]),
            "SRS":        float(row["SRS"]),
            "conference": conf,
            "playoff":    1 if "*" in str(row["Team"]) else 0,
        })
    standings = pd.DataFrame(rows)

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
                "Age","Attend.","Attend./G","MOV","SOS","SRS","FTr","3PAr"]:
        if col in adv.columns:
            adv[col] = pd.to_numeric(adv[col], errors="coerce")

    return pg, standings, adv

# ── Load into SQLite ───────────────────────────────────────────────────────────
def load_to_db(pg, standings, adv, source):
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pipeline_log (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            run_at  TEXT NOT NULL,
            source  TEXT NOT NULL,
            status  TEXT NOT NULL,
            message TEXT
        )
    """)

    # Per game
    pg_cols = [c for c in ["Team","PPG","APG","RPG","SPG","BPG","TOPG",
                            "FG_PCT","FG3_PCT","FT_PCT","3PA","FTA","ORB","DRB","PF","GP"]
               if c in pg.columns]
    pg[pg_cols].to_sql("team_pergame", conn, if_exists="replace", index=False)

    # Standings
    standings.to_sql("standings", conn, if_exists="replace", index=False)

    # Advanced
    adv_cols = [c for c in ["Team","ORtg","DRtg","NRtg","Pace","TS%","eFG%",
                             "TOV%","ORB%","Age","Attend.","Attend./G",
                             "MOV","SOS","SRS","FTr","3PAr","Arena","AST%"]
                if c in adv.columns]
    adv[adv_cols].to_sql("team_advanced", conn, if_exists="replace", index=False)

    cur.execute(
        "INSERT INTO pipeline_log (run_at, source, status, message) VALUES (?,?,?,?)",
        (datetime.now().isoformat(), source, "success",
         f"Loaded {len(pg)} teams via {source}")
    )
    conn.commit()
    conn.close()
    log.info(f"✓ SQLite updated — source={source}, teams={len(pg)}")

# ── Main ───────────────────────────────────────────────────────────────────────
def run_pipeline():
    source = "balldontlie_api"
    try:
        pg_raw, st_raw, adv_raw = fetch_from_api()
        pg, standings, adv = transform_api(pg_raw, st_raw, adv_raw)
        log.info("balldontlie API fetch successful.")
    except Exception as e:
        log.warning(f"balldontlie API failed ({e}), falling back to Excel.")
        source = "excel_fallback"
        pg, standings, adv = fetch_from_excel()

    load_to_db(pg, standings, adv, source)
    return source

# ── DB read helpers ────────────────────────────────────────────────────────────
def db_exists():
    if not os.path.exists(DB_PATH): return False
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {r[0] for r in cur.fetchall()}
    conn.close()
    return {"team_pergame","standings","team_advanced"}.issubset(tables)

def read_pergame():
    return pd.read_sql("SELECT * FROM team_pergame", get_conn())

def read_standings():
    return pd.read_sql("SELECT * FROM standings", get_conn())

def read_advanced():
    return pd.read_sql("SELECT * FROM team_advanced", get_conn())

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
