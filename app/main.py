#!/usr/bin/env python3
"""
VM-Tips 2026 - Enkel betting/tips app för Lillen & Stinis
Kör på Raspberry Pi i Kubernetes internt på LAN.
"""

import sqlite3
import json
import os
import asyncio
from collections import defaultdict
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from typing import Optional, List

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# --- Config ---
DB_PATH = Path(os.environ.get("DB_PATH", "/data/vmtips.db"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
USERS = ["Lillen", "Stinis"]
STATIC_DIR = Path(__file__).parent / "static"

# 12 groups for VM 2026 (approximate based on draw - easy to extend)
GROUPS = [
    {"group": "A", "teams": ["Mexico", "South Africa", "South Korea", "Czechia"]},
    {"group": "B", "teams": ["Canada", "Bosnia and Herzegovina", "Qatar", "Switzerland"]},
    {"group": "C", "teams": ["Brazil", "Morocco", "Haiti", "Scotland"]},
    {"group": "D", "teams": ["USA", "Paraguay", "Australia", "Türkiye"]},
    {"group": "E", "teams": ["Germany", "Curaçao", "Elfenbenskusten", "Ecuador"]},
    {"group": "F", "teams": ["Netherlands", "Japan", "Tunisia", "Sweden"]},
    {"group": "G", "teams": ["Belgium", "Egypt", "Ghana", "Panama"]},
    {"group": "H", "teams": ["Spain", "Cape Verde", "Saudi Arabia", "Uruguay"]},
    {"group": "I", "teams": ["Argentina", "Algeria", "Iraq", "Norway"]},
    {"group": "J", "teams": ["France", "Senegal", "Austria", "Jordan"]},
    {"group": "K", "teams": ["England", "Croatia", "Portugal", "Colombia"]},
    {"group": "L", "teams": ["Italy", "Denmark", "Poland", "Serbia"]},
]

app = FastAPI(title="VM-Tips 2026", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static (for future assets if needed)
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# --- Pydantic models ---
class MatchCreate(BaseModel):
    datetime: str  # ISO format e.g. "2026-06-15T04:00:00"
    home: str
    away: str
    stage: str = "Grupp"

class ResultUpdate(BaseModel):
    home_goals: int
    away_goals: int

class PredictionCreate(BaseModel):
    match_id: int
    user: str
    home_goals: int
    away_goals: int

class TournamentPick(BaseModel):
    user: str
    champion: str

# --- DB helpers ---
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            datetime TEXT NOT NULL,
            home TEXT NOT NULL,
            away TEXT NOT NULL,
            stage TEXT NOT NULL DEFAULT 'Grupp'
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS match_results (
            match_id INTEGER PRIMARY KEY,
            home_goals INTEGER NOT NULL,
            away_goals INTEGER NOT NULL,
            is_final INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY(match_id) REFERENCES matches(id) ON DELETE CASCADE
        )
    """)

    # Migration for existing databases (before is_final column was added)
    try:
        cur.execute("SELECT is_final FROM match_results LIMIT 1")
    except sqlite3.OperationalError:
        print("Migrating match_results table: adding is_final column")
        cur.execute("ALTER TABLE match_results ADD COLUMN is_final INTEGER NOT NULL DEFAULT 1")
        conn.commit()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user TEXT NOT NULL,
            match_id INTEGER NOT NULL,
            home_goals INTEGER NOT NULL,
            away_goals INTEGER NOT NULL,
            UNIQUE(user, match_id),
            FOREIGN KEY(match_id) REFERENCES matches(id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS tournament_picks (
            user TEXT PRIMARY KEY,
            champion TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS group_predictions (
            user TEXT NOT NULL,
            group_name TEXT NOT NULL,
            winner TEXT NOT NULL,
            UNIQUE(user, group_name)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS group_winners (
            group_name TEXT PRIMARY KEY,
            winner TEXT NOT NULL
        )
    """)

    conn.commit()

    # Seeding of matches from the small hardcoded list is disabled.
    # All matches (full 104 schedule with correct UTC times and deduplication) now come
    # exclusively from the public openfootball JSON. This is triggered automatically
    # on startup (via await in on_startup) and periodically in background.
    # This is the clean way: after DB reset, everything is loaded fresh from the API source
    # without any manual "Synka" for the initial full schedule. When playoffs start, new
    # matches will be added automatically as the JSON updates.

    conn.close()

def seed_data(conn):
    cur = conn.cursor()

    # Seed some realistic early matches from VM 2026 (using data from public sources June 2026)
    # Format: (iso_datetime, home, away, stage)
    matches = [
        # 11 juni - öppningsdag (converted to UTC from source UTC-6 etc.)
        ("2026-06-11T21:00:00", "Mexico", "South Africa", "Grupp A"),
        ("2026-06-12T04:00:00", "South Korea", "Czechia", "Grupp A"),

        # 12 juni
        ("2026-06-12T21:00:00", "Canada", "Bosnia and Herzegovina", "Grupp B"),
        ("2026-06-13T03:00:00", "USA", "Paraguay", "Grupp D"),

        # 13 juni
        ("2026-06-13T21:00:00", "Australia", "Türkiye", "Grupp D"),
        ("2026-06-14T00:00:00", "Brazil", "Morocco", "Grupp C"),
        ("2026-06-14T03:00:00", "Haiti", "Scotland", "Grupp C"),

        # Sverige matcher + andra (adjusted to UTC)
        ("2026-06-15T10:00:00", "Sverige", "Tunisien", "Grupp F"),
        ("2026-06-16T00:00:00", "Spanien", "Kap Verde", "Grupp H"),
        ("2026-06-16T04:00:00", "Tyskland", "Elfenbenskusten", "Grupp E"),

        # 20 juni - Sverige
        ("2026-06-21T01:00:00", "Nederländerna", "Sverige", "Grupp F"),

        # 26 juni - Sverige
        ("2026-06-26T07:00:00", "Japan", "Sverige", "Grupp F"),

        # Extra intressanta gruppspelsmatcher
        ("2026-06-15T01:00:00", "Nederländerna", "Japan", "Grupp F"),
        ("2026-06-18T21:00:00", "Argentina", "Algeriet", "Grupp J"),
        ("2026-06-20T00:00:00", "England", "Croatia", "Grupp L"),
        ("2026-06-22T21:00:00", "Frankrike", "Senegal", "Grupp K"),
    ]

    for dt, home, away, stage in matches:
        cur.execute(
            "INSERT INTO matches (datetime, home, away, stage) VALUES (?, ?, ?, ?)",
            (dt, home, away, stage)
        )

    # Default tournament picks empty
    # Add a sample result for demo (opening match finished)
    # Leave most open so they can play with it immediately

    # Example: set one early result for testing points
    # We don't insert here; user will enter live.

    # Set a sample champion pick for fun
    cur.execute("INSERT OR IGNORE INTO tournament_picks (user, champion) VALUES (?, ?)", ("Lillen", "Sverige"))
    cur.execute("INSERT OR IGNORE INTO tournament_picks (user, champion) VALUES (?, ?)", ("Stinis", "Brasilien"))

def get_setting(key: str, default=None):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cur.fetchone()
    conn.close()
    return row["value"] if row else default

def set_setting(key: str, value: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def calculate_points(pred_h: int, pred_a: int, act_h: int, act_a: int) -> int:
    """3 poäng för rätt vinnare/oavgjort + 2 extra för exakt resultat."""
    points = 0
    actual_res = "H" if act_h > act_a else ("A" if act_a > act_h else "D")
    pred_res = "H" if pred_h > pred_a else ("A" if pred_a > pred_h else "D")
    if pred_res == actual_res:
        points += 3
    if pred_h == act_h and pred_a == act_a:
        points += 2
    return points


TEAM_ALIASES = {
    # Map all variations (Swedish/English, &/and) to a consistent canonical English name
    "south korea": "South Korea",
    "korea republic": "South Korea",
    "czech republic": "Czechia",
    "czechia": "Czechia",
    "bosnia-herzegovina": "Bosnia and Herzegovina",
    "bosnia and herzegovina": "Bosnia and Herzegovina",
    "bosnia & herzegovina": "Bosnia and Herzegovina",
    "türkiye": "Turkey",
    "turkey": "Turkey",
    "côte d'ivoire": "Côte d'Ivoire",
    "ivory coast": "Côte d'Ivoire",
    "cape verde": "Cape Verde",
    "cabo verde": "Cape Verde",
    "netherlands": "Netherlands",
    "sweden": "Sweden",
    "tunisia": "Tunisia",
    "japan": "Japan",
    "spain": "Spain",
    "germany": "Germany",
    "morocco": "Morocco",
    "brazil": "Brazil",
    "argentina": "Argentina",
    "france": "France",
    "england": "England",
    "portugal": "Portugal",
    "belgium": "Belgium",
    "croatia": "Croatia",
    "uruguay": "Uruguay",
    "paraguay": "Paraguay",
    "mexico": "Mexico",
    "usa": "USA",
    "united states": "USA",
    "canada": "Canada",
    "australia": "Australia",
    "saudi arabia": "Saudi Arabia",
    "qatar": "Qatar",
    "iran": "Iran",
    "iraq": "Iraq",
    "algeria": "Algeria",
    "senegal": "Senegal",
    "egypt": "Egypt",
    "ghana": "Ghana",
    "panama": "Panama",
    "italy": "Italy",
    "denmark": "Denmark",
    "poland": "Poland",
    "serbia": "Serbia",
    # Swedish from seed map to canonical English
    "sverige": "Sweden",
    "tunisien": "Tunisia",
    "nederländerna": "Netherlands",
    "elfenbenskusten": "Côte d'Ivoire",
    "kap verde": "Cape Verde",
}

def canonical_name(name: str) -> str:
    if not name:
        return ""
    key = name.lower().strip()
    return TEAM_ALIASES.get(key, key)


def parse_match_kickoff_utc(date_str: str, time_str: str) -> str:
    """Parse '2026-06-13' + '12:00 UTC-7' into UTC ISO string (naive UTC)."""
    if not date_str:
        return ""
    import re
    if not time_str:
        return f"{date_str}T00:00:00"
    m = re.search(r'(\d{1,2}):(\d{2})\s+UTC([+-]?\d+)', time_str)
    if not m:
        return f"{date_str}T00:00:00"
    h, mi, off_str = m.groups()
    try:
        local_dt = datetime.strptime(f"{date_str} {int(h):02d}:{mi}", "%Y-%m-%d %H:%M")
        offset = int(off_str)
        # local = UTC + offset (offset is negative for western zones)
        # UTC = local - offset
        utc_dt = local_dt - timedelta(hours=offset)
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
        return utc_dt.isoformat()
    except Exception:
        return f"{date_str}T00:00:00"


async def sync_results_from_openfootball() -> int:
    """Hämtar hela schemat + resultat från openfootball/worldcup.json (gratis, ingen nyckel).
    Importerar saknade matcher med korrekta UTC-tider och uppdaterar resultat när de finns.
    Detta gör att hela schemat (inkl. Qatar-Schweiz) och automatiska slutresultat fungerar."""
    url = "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json"
    updated_results = 0
    added_matches = 0

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        print(f"Failed to fetch openfootball data: {e}")
        return 0

    remote_matches = data.get("matches", [])
    conn = get_db()
    cur = conn.cursor()

    # Load existing matches with canonical keys for robust dedup (handles Swedish/English/& vs and)
    cur.execute("SELECT id, datetime, home, away FROM matches")
    existing = {}
    for row in cur.fetchall():
        d = row["datetime"][:10] if row["datetime"] else ""
        ch = canonical_name(row["home"])
        ca = canonical_name(row["away"])
        key = (d, ch, ca)
        existing[key] = row["id"]

    for r in remote_matches:
        r_date = r.get("date", "")
        stage = r.get("group") or r.get("round", "Grupp")
        dt_str = parse_match_kickoff_utc(r_date, r.get("time", ""))

        if not dt_str:
            continue

        home = r.get("team1", "")
        away = r.get("team2", "")
        ch = canonical_name(home)
        ca = canonical_name(away)
        key = (r_date, ch, ca)

        if key in existing:
            mid = existing[key]
            # update time/stage on existing (corrects any previous bad times)
            cur.execute("UPDATE matches SET datetime = ?, stage = ? WHERE id = ?", (dt_str, stage, mid))
        else:
            cur.execute("""
                INSERT INTO matches (datetime, home, away, stage)
                VALUES (?, ?, ?, ?)
            """, (dt_str, home, away, stage))
            mid = cur.lastrowid
            existing[key] = mid
            added_matches += 1

        # Parse and upsert result if present
        score1 = None
        score2 = None
        score = r.get("score") or {}
        if isinstance(score, dict) and "ft" in score:
            ft = score.get("ft", [None, None])
            if len(ft) >= 2:
                score1 = ft[0]
                score2 = ft[1]
        else:
            score1 = r.get("score1")
            score2 = r.get("score2")

        if score1 is not None and score2 is not None:
            new_h, new_a = int(score1), int(score2)
            cur2 = conn.cursor()
            cur2.execute("SELECT home_goals, away_goals, is_final FROM match_results WHERE match_id = ?", (mid,))
            existing_res = cur2.fetchone()
            if existing_res:
                try:
                    is_final = bool(existing_res["is_final"])
                except (KeyError, IndexError):
                    is_final = True  # old row without column or migration not run yet
            else:
                is_final = False
            if not existing_res or existing_res["home_goals"] != new_h or existing_res["away_goals"] != new_a or not is_final:
                cur2.execute(
                    "INSERT OR REPLACE INTO match_results (match_id, home_goals, away_goals, is_final) VALUES (?, ?, ?, 1)",
                    (mid, new_h, new_a)
                )
                updated_results += 1

    conn.commit()
    conn.close()

    if added_matches > 0 or updated_results > 0:
        print(f"[SYNC] Added/updated {added_matches} matches, {updated_results} results from openfootball JSON")
    # Always run dedup at end of sync to clean any lingering from name variations
    cleanup_duplicate_matches()
    return updated_results

# Call cleanup on startup too, after initial sync task starts (it will run soon)
# The task is async, but cleanup is safe to call here too if needed.


def cleanup_duplicate_matches() -> int:
    """Removes duplicate matches using canonical names (handles & vs and, Swedish/English).
    Keeps the one with a final result if possible, otherwise the oldest id.
    Any predictions tied only to deleted dups will be lost."""
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT id, datetime, home, away FROM matches ORDER BY id")
    rows = cur.fetchall()

    groups = defaultdict(list)
    for r in rows:
        d = (r["datetime"] or "")[:10]
        ch = canonical_name(r["home"])
        ca = canonical_name(r["away"])
        key = (d, ch, ca)
        groups[key].append(dict(r))

    to_delete = []
    for key, items in groups.items():
        if len(items) <= 1:
            continue
        # prefer final result
        best = None
        for it in items:
            cur.execute("SELECT 1 FROM match_results WHERE match_id = ? AND is_final=1 LIMIT 1", (it["id"],))
            if cur.fetchone():
                best = it
                break
        if not best:
            best = min(items, key=lambda x: x["id"])
        best_id = best["id"]
        for it in items:
            if it["id"] != best_id:
                to_delete.append(it["id"])

    if to_delete:
        cur.executemany("DELETE FROM matches WHERE id = ?", [(d,) for d in to_delete])
        # also clean orphaned predictions/results
        cur.executemany("DELETE FROM predictions WHERE match_id = ?", [(d,) for d in to_delete])
        cur.executemany("DELETE FROM match_results WHERE match_id = ?", [(d,) for d in to_delete])
    deleted = len(to_delete)
    conn.commit()
    conn.close()
    if deleted > 0:
        print(f"[CLEANUP] Removed {deleted} duplicate match rows")
    return deleted


async def periodic_result_sync():
    """Background task that automatically syncs results from the public source
    every 60 seconds. Final results (when the open source JSON is updated after a match)
    will be pulled and set automatically - no manual entry needed for completed matches."""
    while True:
        try:
            count = await sync_results_from_openfootball()
            if count > 0:
                print(f"[AUTO-SYNC] Updated {count} match results from open source")
        except Exception as e:
            print(f"[AUTO-SYNC] Error: {e}")
        await asyncio.sleep(60)  # every minute is plenty for this source

# --- API routes ---

@app.on_event("startup")
async def on_startup():
    init_db()
    # Block on full schedule import from the public JSON on startup (especially after DB reset).
    # This ensures the complete list of matches with correct UTC times is loaded automatically,
    # without needing the "Synka" button or waiting for background.
    # Results (when available in the JSON) are also pulled.
    await sync_results_from_openfootball()
    # Then start background for ongoing updates during the tournament
    asyncio.create_task(periodic_result_sync())

@app.get("/", response_class=HTMLResponse)
async def root():
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return HTMLResponse("<h1>VM-Tips</h1><p>Frontend saknas. Lägg index.html i app/static/</p>")

@app.get("/api/users")
def get_users():
    return {"users": USERS}

@app.get("/api/matches")
def get_matches():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM matches ORDER BY datetime ASC")
    matches = []
    for row in cur.fetchall():
        m = dict(row)
        # attach result if exists (defensive for schema migration)
        cur2 = conn.cursor()
        try:
            cur2.execute("SELECT home_goals, away_goals, is_final FROM match_results WHERE match_id = ?", (m["id"],))
            res = cur2.fetchone()
            if res:
                m["result"] = {
                    "home_goals": res[0], 
                    "away_goals": res[1],
                    "is_final": bool(res[2])
                }
            else:
                m["result"] = None
        except sqlite3.OperationalError:
            # Fallback if column still missing (should not happen after migration)
            cur2.execute("SELECT home_goals, away_goals FROM match_results WHERE match_id = ?", (m["id"],))
            res = cur2.fetchone()
            if res:
                m["result"] = {
                    "home_goals": res[0], 
                    "away_goals": res[1],
                    "is_final": True
                }
            else:
                m["result"] = None

        # attach both users' predictions
        preds = {}
        for user in USERS:
            cur2.execute(
                "SELECT home_goals, away_goals FROM predictions WHERE match_id = ? AND user = ?",
                (m["id"], user)
            )
            p = cur2.fetchone()
            preds[user] = {"home_goals": p[0], "away_goals": p[1]} if p else None
        m["predictions"] = preds

        # Compute status and lock (all times treated as UTC)
        try:
            match_dt = datetime.fromisoformat(m["datetime"])
            if match_dt.tzinfo is None:
                match_dt = match_dt.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            lock_buffer = timedelta(minutes=5)  # 5 minutes before kickoff predictions lock

            if m["result"] and m["result"].get("is_final"):
                m["status"] = "finished"
                m["prediction_locked"] = True
            elif now >= match_dt:
                m["status"] = "live"
                m["prediction_locked"] = True
            elif now >= match_dt - lock_buffer:
                m["status"] = "upcoming"
                m["prediction_locked"] = True
            else:
                m["status"] = "upcoming"
                m["prediction_locked"] = False
        except Exception:
            m["status"] = "upcoming"
            m["prediction_locked"] = False

        matches.append(m)
    conn.close()
    return matches

@app.post("/api/matches")
def create_match(m: MatchCreate):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO matches (datetime, home, away, stage) VALUES (?, ?, ?, ?)",
        (m.datetime, m.home, m.away, m.stage)
    )
    mid = cur.lastrowid
    conn.commit()
    conn.close()
    return {"id": mid, **m.dict()}

@app.delete("/api/matches/{match_id}")
def delete_match(match_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM matches WHERE id = ?", (match_id,))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.put("/api/matches/{match_id}/result")
def set_result(match_id: int, res: ResultUpdate, is_final: bool = True):
    """Set result. Use is_final=false for live/provisional scores during the match."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO match_results (match_id, home_goals, away_goals, is_final) VALUES (?, ?, ?, ?)",
        (match_id, res.home_goals, res.away_goals, 1 if is_final else 0)
    )
    conn.commit()
    conn.close()
    return {"ok": True, "match_id": match_id, "result": {**res.dict(), "is_final": is_final}}

@app.post("/api/predictions")
def save_prediction(p: PredictionCreate):
    if p.user not in USERS:
        raise HTTPException(400, "Ogiltig användare")

    # Check if predictions are locked for this match
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT datetime FROM matches WHERE id = ?", (p.match_id,))
    row = cur.fetchone()
    if row:
        try:
            match_dt = datetime.fromisoformat(row["datetime"])
            if match_dt.tzinfo is None:
                match_dt = match_dt.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) >= match_dt:
                raise HTTPException(403, "Tippning är stängd – matchen har startat")
        except Exception:
            pass

    cur.execute(
        """INSERT OR REPLACE INTO predictions 
           (user, match_id, home_goals, away_goals) 
           VALUES (?, ?, ?, ?)""",
        (p.user, p.match_id, p.home_goals, p.away_goals)
    )
    conn.commit()
    conn.close()
    return {"ok": True}


@app.post("/api/admin/prediction")
def save_admin_prediction(data: dict):
    """Admin endpoint to record bets in afterhand (bypasses lock).
    Body: {user, match_id, home_goals, away_goals}
    """
    user = data.get("user")
    match_id = data.get("match_id")
    home_goals = data.get("home_goals")
    away_goals = data.get("away_goals")
    if user not in USERS or match_id is None or home_goals is None or away_goals is None:
        raise HTTPException(400, "Ogiltig data")
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """INSERT OR REPLACE INTO predictions 
           (user, match_id, home_goals, away_goals) 
           VALUES (?, ?, ?, ?)""",
        (user, match_id, home_goals, away_goals)
    )
    conn.commit()
    conn.close()
    return {"ok": True}

@app.get("/api/predictions")
def get_predictions(user: Optional[str] = None):
    conn = get_db()
    cur = conn.cursor()
    if user:
        cur.execute("SELECT * FROM predictions WHERE user = ?", (user,))
    else:
        cur.execute("SELECT * FROM predictions")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

@app.get("/api/leaderboard")
def get_leaderboard():
    conn = get_db()
    cur = conn.cursor()

    # Get all finished matches with FINAL results
    cur.execute("""
        SELECT m.id, m.home, m.away, m.stage, m.datetime,
               r.home_goals as act_h, r.away_goals as act_a
        FROM matches m
        JOIN match_results r ON r.match_id = m.id
        WHERE r.is_final = 1
    """)
    finished = cur.fetchall()

    scores = {u: {"total": 0, "match_points": 0, "score_bonus": 0, "correct_picks": 0, "group_points": 0} for u in USERS}

    for row in finished:
        mid = row["id"]
        act_h, act_a = row["act_h"], row["act_a"]

        for user in USERS:
            cur.execute(
                "SELECT home_goals, away_goals FROM predictions WHERE match_id=? AND user=?",
                (mid, user)
            )
            pred = cur.fetchone()
            if pred:
                ph, pa = pred["home_goals"], pred["away_goals"]
                pts = calculate_points(ph, pa, act_h, act_a)
                scores[user]["total"] += pts
                if pts >= 3:
                    scores[user]["correct_picks"] += 1
                    scores[user]["match_points"] += 3
                if pts == 5:
                    scores[user]["score_bonus"] += 2

    # Group winner points (5p per correct group)
    GROUP_POINTS = 5
    for group in GROUPS:
        gname = group["group"]
        cur.execute("SELECT winner FROM group_winners WHERE group_name = ?", (gname,))
        actual = cur.fetchone()
        if actual:
            actual_winner = actual["winner"]
            for user in USERS:
                cur.execute(
                    "SELECT winner FROM group_predictions WHERE user=? AND group_name=?",
                    (user, gname)
                )
                pick = cur.fetchone()
                if pick and pick["winner"] == actual_winner:
                    scores[user]["total"] += GROUP_POINTS
                    scores[user]["group_points"] += GROUP_POINTS

    # Champion points (if set)
    actual_champion = get_setting("actual_champion")
    champion_points = 12

    if actual_champion:
        for user in USERS:
            cur.execute("SELECT champion FROM tournament_picks WHERE user = ?", (user,))
            pick = cur.fetchone()
            if pick and pick["champion"] == actual_champion:
                scores[user]["total"] += champion_points
                scores[user]["champion_points"] = champion_points
            else:
                scores[user]["champion_points"] = 0
    else:
        for user in USERS:
            scores[user]["champion_points"] = 0

    # Current picks
    picks = {}
    for user in USERS:
        cur.execute("SELECT champion FROM tournament_picks WHERE user = ?", (user,))
        row = cur.fetchone()
        picks[user] = row["champion"] if row else None

    conn.close()

    leaderboard = []
    for user in USERS:
        s = scores[user]
        leaderboard.append({
            "user": user,
            "total": s["total"],
            "match_points": s.get("match_points", 0),
            "score_bonus": s.get("score_bonus", 0),
            "group_points": s.get("group_points", 0),
            "champion_points": s.get("champion_points", 0),
            "correct_picks": s.get("correct_picks", 0),
            "champion_pick": picks[user]
        })

    leaderboard.sort(key=lambda x: x["total"], reverse=True)
    return {
        "leaderboard": leaderboard,
        "actual_champion": actual_champion,
        "champion_points_value": champion_points if actual_champion else 0,
        "group_points_value": 5
    }

@app.post("/api/tournament-pick")
def save_tournament_pick(p: TournamentPick):
    if p.user not in USERS:
        raise HTTPException(400, "Ogiltig användare")
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO tournament_picks (user, champion) VALUES (?, ?)",
        (p.user, p.champion)
    )
    conn.commit()
    conn.close()
    return {"ok": True}

@app.get("/api/tournament-pick")
def get_tournament_pick(user: str):
    if user not in USERS:
        raise HTTPException(400, "Ogiltig användare")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT champion FROM tournament_picks WHERE user = ?", (user,))
    row = cur.fetchone()
    conn.close()
    return {"user": user, "champion": row["champion"] if row else None}

@app.post("/api/set-champion")
def set_actual_champion(champion: str):
    """Sätt den riktiga turneringsvinnaren (när VM är slut). Ger poäng automatiskt."""
    set_setting("actual_champion", champion)
    return {"ok": True, "actual_champion": champion}


@app.post("/api/sync-results")
async def sync_results():
    """Hämtar och applicerar senaste resultat från öppen datakälla (openfootball/worldcup.json).
    Uppdaterar poäng automatiskt för matchade avslutade matcher."""
    count = await sync_results_from_openfootball()
    return {
        "ok": True,
        "updated_matches": count,
        "message": f"Uppdaterade {count} matchresultat från öppen källa."
    }


@app.get("/api/groups")
def get_groups():
    """Return groups with teams, current predictions for both users, and actual winners if set."""
    conn = get_db()
    cur = conn.cursor()

    result = []
    for g in GROUPS:
        gname = g["group"]
        teams = g["teams"]

        preds = {}
        for user in USERS:
            cur.execute(
                "SELECT winner FROM group_predictions WHERE user=? AND group_name=?",
                (user, gname)
            )
            row = cur.fetchone()
            preds[user] = row["winner"] if row else None

        cur.execute("SELECT winner FROM group_winners WHERE group_name=?", (gname,))
        actual = cur.fetchone()
        actual_winner = actual["winner"] if actual else None

        result.append({
            "group": gname,
            "teams": teams,
            "predictions": preds,
            "actual_winner": actual_winner
        })

    conn.close()
    return {"groups": result, "group_points": 5}


@app.post("/api/group-prediction")
def save_group_prediction(data: dict):
    user = data.get("user")
    group = data.get("group")
    winner = data.get("winner")
    if user not in USERS or not group or not winner:
        raise HTTPException(400, "Ogiltig data")
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO group_predictions (user, group_name, winner) VALUES (?, ?, ?)",
        (user, group, winner)
    )
    conn.commit()
    conn.close()
    return {"ok": True}


@app.post("/api/set-group-winner")
def set_group_winner(data: dict):
    group = data.get("group")
    winner = data.get("winner")
    if not group or not winner:
        raise HTTPException(400, "Ogiltig data")
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO group_winners (group_name, winner) VALUES (?, ?)",
        (group, winner)
    )
    conn.commit()
    conn.close()
    return {"ok": True}


@app.post("/api/cleanup-duplicates")
def cleanup_duplicates():
    """Admin endpoint to remove duplicate matches caused by earlier sync bugs.
    Predictions linked only to deleted duplicate rows will be lost.
    Run this once after deploying the fixed sync logic."""
    deleted = cleanup_duplicate_matches()
    # After cleanup, re-sync to make sure we have clean data from source
    # (this is async but we fire it; results will appear soon)
    asyncio.create_task(sync_results_from_openfootball())
    return {"ok": True, "deleted_duplicates": deleted, "message": f"Tog bort {deleted} dubbletter. Synk körs i bakgrunden."}

@app.get("/api/settings")
def get_settings():
    return {
        "actual_champion": get_setting("actual_champion"),
        "users": USERS
    }

# Simple health
@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now().isoformat()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
