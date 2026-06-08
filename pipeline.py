"""
NBA 25-26 Data Pipeline
========================
Flow:
  1. Fetch nba_25-26_stats.xlsx from GitHub raw URL
  2. On failure → fallback to local Excel file
  3. Clean & transform (4 sheets)
  4. Store into SQLite
  5. Log each run
"""

import sqlite3
import pandas as pd
import requests
import re
import os
import logging
from datetime import datetime
from io import BytesIO

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

DB_PATH    = os.path.join(os.path.dirname(__file__), "nba_stats.db")
XLSX_PATH  = os.path.join(os.path.dirname(__file__), "nba_25-26_stats.xlsx")
GITHUB_URL = "https://raw.githubusercontent.com/vcchen1120/NBA-25-26-season-stats-dashboard/main/nba_25-26_stats.xlsx"

# ── Helpers ────────────────────────────────────────────────────────────────────
def clean_team(name):
    if not isinstance(name, str): return name
    return re.sub(r"\s*\(\d+\)", "", name).replace("*", "").strip()

def get_conn():
    return sqlite3.connect(DB_PATH)

# ── Extract ────────────────────────────────────────────────────────────────────
def fetch_excel_bytes():
    """Try GitHub first, fall back to local file."""
    try:
        log.info(f"Fetching Excel from GitHub: {GITHUB_URL}")
        r = requests.get(GITHUB_URL, timeout=20,
                         headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        log.info(f"GitHub fetch OK — {len(r.content):,} bytes")
        return BytesIO(r.content), "github"
    except Exception as e:
        log.warning(f"GitHub fetch failed ({e}), using local file.")
        with open(XLSX_PATH, "rb") as f:
            return BytesIO(f.read()), "local_excel"

# ── Transform ──────────────────────────────────────────────────────────────────
def parse_excel(buf):
    """Parse all 4 sheets → (pg, standings, adv) DataFrames."""

    # Sheet 3 – Per Game
    pg = pd.read_excel(buf, sheet_name="工作表3")
    buf.seek(0)
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
    df2 = pd.read_excel(buf, sheet_name="工作表2")
    buf.seek(0)
    df2.columns = ["Team","W","L","WL_pct","GB","PS_G","PA_G","SRS"]
    rows, conf = [], "East"
    for _, row in df2.iterrows():
        name = str(row["Team"]).strip()
        if "Eastern" in name: conf = "East"; continue
        if "Western" in name: conf = "West"; continue
        try: int(row["W"])
        except: continue
        rows.append({
            "team": clean_team(name), "W": int(row["W"]), "L": int(row["L"]),
            "WL_pct": float(row["WL_pct"]),
            "PS_G": float(row["PS_G"]), "PA_G": float(row["PA_G"]),
            "SRS": float(row["SRS"]),
            "conference": conf,
            "playoff": 1 if "*" in str(row["Team"]) else 0,
        })
    standings = pd.DataFrame(rows)

    # Sheet 4 – Advanced
    df4r = pd.read_excel(buf, sheet_name="工作表4", header=None)
    buf.seek(0)
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

# ── Load ───────────────────────────────────────────────────────────────────────
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

    pg_cols = [c for c in ["Team","PPG","APG","RPG","SPG","BPG","TOPG",
                            "FG_PCT","FG3_PCT","FT_PCT","3PA","FTA","ORB","DRB","PF"]
               if c in pg.columns]
    pg[pg_cols].to_sql("team_pergame", conn, if_exists="replace", index=False)

    standings.to_sql("standings", conn, if_exists="replace", index=False)

    adv_cols = [c for c in ["Team","ORtg","DRtg","NRtg","Pace","TS%","eFG%",
                             "TOV%","ORB%","Age","Attend.","Attend./G",
                             "MOV","SOS","SRS","FTr","3PAr","Arena"]
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
    buf, source = fetch_excel_bytes()
    pg, standings, adv = parse_excel(buf)
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
