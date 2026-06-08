"""
NBA 25-26 Data Pipeline
Flow: GitHub Raw URL → Excel (4 team sheets + 30 player sheets) → SQLite
"""
import sqlite3, pandas as pd, requests, re, os, logging
from datetime import datetime
from io import BytesIO

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

DB_PATH    = os.path.join(os.path.dirname(__file__), "nba_stats.db")
XLSX_PATH  = os.path.join(os.path.dirname(__file__), "nba_25-26_stats.xlsx")
GITHUB_URL = "https://raw.githubusercontent.com/vcchen1120/NBA-25-26-season-stats-dashboard/main/nba_25-26_stats.xlsx"

def clean_team(name):
    if not isinstance(name, str): return name
    return re.sub(r"\s*\(\d+\)", "", name).replace("*", "").strip()

def get_conn(): return sqlite3.connect(DB_PATH)

def fetch_excel_bytes():
    try:
        log.info(f"Fetching from GitHub...")
        r = requests.get(GITHUB_URL, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        log.info(f"GitHub OK — {len(r.content):,} bytes")
        return BytesIO(r.content), "github"
    except Exception as e:
        log.warning(f"GitHub failed ({e}), using local file.")
        with open(XLSX_PATH, "rb") as f:
            return BytesIO(f.read()), "local_excel"

def parse_excel(buf):
    xl = pd.ExcelFile(buf); buf.seek(0)

    # ── Sheet 3: Per Game ──────────────────────────────────────────────────────
    pg = pd.read_excel(buf, sheet_name="工作表3"); buf.seek(0)
    pg = pg[pg["Rk"].apply(lambda x: str(x).isdigit())].copy()
    pg["Team"] = pg["Team"].apply(clean_team)
    pg = pg.rename(columns={"PTS":"PPG","AST":"APG","TRB":"RPG","STL":"SPG",
                             "BLK":"BPG","TOV":"TOPG","FG%":"FG_PCT",
                             "3P%":"FG3_PCT","FT%":"FT_PCT"})
    for col in ["PPG","APG","RPG","SPG","BPG","TOPG","FG_PCT","FG3_PCT","FT_PCT","3PA","FTA","ORB","DRB","PF"]:
        if col in pg.columns: pg[col] = pd.to_numeric(pg[col], errors="coerce")

    # ── Sheet 2: Standings ─────────────────────────────────────────────────────
    df2 = pd.read_excel(buf, sheet_name="工作表2"); buf.seek(0)
    df2.columns = ["Team","W","L","WL_pct","GB","PS_G","PA_G","SRS"]
    rows, conf = [], "East"
    for _, row in df2.iterrows():
        name = str(row["Team"]).strip()
        if "Eastern" in name: conf = "East"; continue
        if "Western" in name: conf = "West"; continue
        try: int(row["W"])
        except: continue
        rows.append({"team": clean_team(name), "W": int(row["W"]), "L": int(row["L"]),
                     "WL_pct": float(row["WL_pct"]), "PS_G": float(row["PS_G"]),
                     "PA_G": float(row["PA_G"]), "SRS": float(row["SRS"]),
                     "conference": conf, "playoff": 1 if "*" in str(row["Team"]) else 0})
    standings = pd.DataFrame(rows)

    # ── Sheet 4: Advanced ──────────────────────────────────────────────────────
    df4r = pd.read_excel(buf, sheet_name="工作表4", header=None); buf.seek(0)
    hr = df4r[df4r.iloc[:, 0] == "Rk"].index[0]
    adv = df4r.iloc[hr:].copy()
    adv.columns = adv.iloc[0]; adv = adv[1:].reset_index(drop=True)
    adv = adv[adv["Rk"].apply(lambda x: str(x).strip().isdigit())].copy()
    adv["Team"] = adv["Team"].apply(clean_team)
    adv = adv.loc[:, ~adv.columns.duplicated()].copy()
    for col in ["ORtg","DRtg","NRtg","Pace","TS%","eFG%","TOV%","ORB%","Age","Attend.","Attend./G","MOV","SOS","SRS","FTr","3PAr"]:
        if col in adv.columns: adv[col] = pd.to_numeric(adv[col], errors="coerce")

    # ── Player sheets — hardcoded mapping per user spec ──────────────────────
    SHEET_TEAM_MAP = {
        '工作表7':  'Denver Nuggets',       '工作表8':  'Miami Heat',
        '工作表9':  'San Antonio Spurs',     '工作表10': 'Cleveland Cavaliers',
        '工作表11': 'Oklahoma City Thunder', '工作表12': 'Atlanta Hawks',
        '工作表13': 'Minnesota Timberwolves','工作表14': 'Detroit Pistons',
        '工作表15': 'Utah Jazz',             '工作表16': 'New York Knicks',
        '工作表17': 'Chicago Bulls',         '工作表18': 'Los Angeles Lakers',
        '工作表19': 'Charlotte Hornets',     '工作表20': 'Philadelphia 76ers',
        '工作表22': 'Orlando Magic',         '工作表23': 'Portland Trail Blazers',
        '工作表5':  'New Orleans Pelicans',  '工作表24': 'Houston Rockets',
        '工作表25': 'Boston Celtics',        '工作表26': 'Memphis Grizzlies',
        '工作表27': 'Golden State Warriors', '工作表28': 'Toronto Raptors',
        '工作表29': 'Dallas Mavericks',      '工作表30': 'Los Angeles Clippers',
        '工作表31': 'Washington Wizards',    '工作表32': 'Phoenix Suns',
        '工作表33': 'Indiana Pacers',        '工作表34': 'Sacramento Kings',
        '工作表35': 'Milwaukee Bucks',       '工作表36': 'Brooklyn Nets',
    }
    all_players = []
    for sheet, team_name in SHEET_TEAM_MAP.items():
        df = pd.read_excel(buf, sheet_name=sheet); buf.seek(0)
        # First column is rank (may be "Rk" or "Unnamed: 0")
        rank_col = df.columns[0]
        df = df[df[rank_col].apply(lambda x: str(x) not in ["nan","Rk",""])].copy()
        df = df.dropna(subset=["Player"])
        df["Team"] = team_name
        num_cols = ["Age","G","GS","MP","FG","FGA","FG%","3P","3PA","3P%",
                    "2P","2PA","2P%","eFG%","FT","FTA","FT%","ORB","DRB",
                    "TRB","AST","STL","BLK","TOV","PF","PTS"]
        for col in num_cols:
            if col in df.columns: df[col] = pd.to_numeric(df[col], errors="coerce")
        all_players.append(df)
        log.info(f"  {team_name}: {len(df)} players")

    players = pd.concat(all_players, ignore_index=True) if all_players else pd.DataFrame()
    keep = [c for c in ["Team","Player","Age","Pos","G","GS","MP","FG","FGA","FG%",
                         "3P","3PA","3P%","FT","FTA","FT%","ORB","DRB","TRB",
                         "AST","STL","BLK","TOV","PF","PTS","eFG%","Awards"]
            if c in players.columns]
    players = players[keep]

    return pg, standings, adv, players

def load_to_db(pg, standings, adv, players, source):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS pipeline_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_at TEXT NOT NULL, source TEXT NOT NULL,
        status TEXT NOT NULL, message TEXT)""")

    pg_cols = [c for c in ["Team","PPG","APG","RPG","SPG","BPG","TOPG","FG_PCT","FG3_PCT","FT_PCT","3PA","FTA","ORB","DRB","PF"] if c in pg.columns]
    pg[pg_cols].to_sql("team_pergame", conn, if_exists="replace", index=False)
    standings.to_sql("standings", conn, if_exists="replace", index=False)
    adv_cols = [c for c in ["Team","ORtg","DRtg","NRtg","Pace","TS%","eFG%","TOV%","ORB%","Age","Attend.","Attend./G","MOV","SOS","SRS","FTr","3PAr","Arena"] if c in adv.columns]
    adv[adv_cols].to_sql("team_advanced", conn, if_exists="replace", index=False)
    if not players.empty:
        players.to_sql("players", conn, if_exists="replace", index=False)
        log.info(f"Players table: {len(players)} rows")

    cur.execute("INSERT INTO pipeline_log (run_at,source,status,message) VALUES (?,?,?,?)",
                (datetime.now().isoformat(), source, "success",
                 f"Loaded {len(pg)} teams, {len(players)} players via {source}"))
    conn.commit(); conn.close()
    log.info(f"✓ SQLite updated — source={source}")

def run_pipeline():
    buf, source = fetch_excel_bytes()
    pg, standings, adv, players = parse_excel(buf)
    load_to_db(pg, standings, adv, players, source)
    return source

def db_exists():
    if not os.path.exists(DB_PATH): return False
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {r[0] for r in cur.fetchall()}; conn.close()
    return {"team_pergame","standings","team_advanced","players"}.issubset(tables)

def read_pergame():    return pd.read_sql("SELECT * FROM team_pergame", get_conn())
def read_standings():  return pd.read_sql("SELECT * FROM standings", get_conn())
def read_advanced():   return pd.read_sql("SELECT * FROM team_advanced", get_conn())
def read_players():    return pd.read_sql("SELECT * FROM players", get_conn())
def read_pipeline_log(): return pd.read_sql("SELECT run_at,source,status,message FROM pipeline_log ORDER BY id DESC LIMIT 10", get_conn())
def last_updated():
    try:
        df = pd.read_sql("SELECT run_at,source FROM pipeline_log ORDER BY id DESC LIMIT 1", get_conn())
        if df.empty: return "Never","–"
        return df.iloc[0]["run_at"][:19], df.iloc[0]["source"]
    except: return "Never","–"

if __name__ == "__main__":
    run_pipeline()
