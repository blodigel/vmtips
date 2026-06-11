#!/usr/bin/env python3
"""
VM-Tips 2026 - Enkel betting/tips app för Lillen & Stinis
Kör på Raspberry Pi i Kubernetes internt på LAN.
"""

import sqlite3
import json
import os
from datetime import datetime, date
from pathlib import Path
from typing import Optional, List

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
            FOREIGN KEY(match_id) REFERENCES matches(id) ON DELETE CASCADE
        )
    """)

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

    conn.commit()

    # Seed if empty
    cur.execute("SELECT COUNT(*) FROM matches")
    if cur.fetchone()[0] == 0:
        seed_data(conn)
        conn.commit()

    conn.close()

def seed_data(conn):
    cur = conn.cursor()

    # Seed some realistic early matches from VM 2026 (using data from public sources June 2026)
    # Format: (iso_datetime, home, away, stage)
    matches = [
        # 11 juni - öppningsdag
        ("2026-06-11T15:00:00", "Mexico", "South Africa", "Grupp A"),
        ("2026-06-11T22:00:00", "South Korea", "Czechia", "Grupp A"),

        # 12 juni
        ("2026-06-12T15:00:00", "Canada", "Bosnia and Herzegovina", "Grupp B"),
        ("2026-06-12T21:00:00", "USA", "Paraguay", "Grupp D"),

        # 13 juni
        ("2026-06-13T15:00:00", "Australia", "Türkiye", "Grupp D"),
        ("2026-06-13T18:00:00", "Brazil", "Morocco", "Grupp C"),
        ("2026-06-13T21:00:00", "Haiti", "Scotland", "Grupp C"),

        # Sverige matcher + andra
        ("2026-06-15T04:00:00", "Sverige", "Tunisien", "Grupp F"),
        ("2026-06-15T18:00:00", "Spanien", "Kap Verde", "Grupp H"),
        ("2026-06-15T22:00:00", "Tyskland", "Elfenbenskusten", "Grupp E"),

        # 20 juni - Sverige
        ("2026-06-20T19:00:00", "Nederländerna", "Sverige", "Grupp F"),

        # 26 juni - Sverige
        ("2026-06-26T01:00:00", "Japan", "Sverige", "Grupp F"),

        # Extra intressanta gruppspelsmatcher
        ("2026-06-14T19:00:00", "Nederländerna", "Japan", "Grupp F"),
        ("2026-06-18T15:00:00", "Argentina", "Algeriet", "Grupp J"),
        ("2026-06-19T18:00:00", "England", "Croatia", "Grupp L"),
        ("2026-06-22T15:00:00", "Frankrike", "Senegal", "Grupp K"),
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

# --- API routes ---

@app.on_event("startup")
def on_startup():
    init_db()

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
        # attach result if exists
        cur2 = conn.cursor()
        cur2.execute("SELECT home_goals, away_goals FROM match_results WHERE match_id = ?", (m["id"],))
        res = cur2.fetchone()
        m["result"] = {"home_goals": res[0], "away_goals": res[1]} if res else None

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
def set_result(match_id: int, res: ResultUpdate):
    conn = get_db()
    cur = conn.cursor()
    # Upsert result
    cur.execute(
        "INSERT OR REPLACE INTO match_results (match_id, home_goals, away_goals) VALUES (?, ?, ?)",
        (match_id, res.home_goals, res.away_goals)
    )
    conn.commit()
    conn.close()
    return {"ok": True, "match_id": match_id, "result": res.dict()}

@app.post("/api/predictions")
def save_prediction(p: PredictionCreate):
    if p.user not in USERS:
        raise HTTPException(400, "Ogiltig användare")
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """INSERT OR REPLACE INTO predictions 
           (user, match_id, home_goals, away_goals) 
           VALUES (?, ?, ?, ?)""",
        (p.user, p.match_id, p.home_goals, p.away_goals)
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

    # Get all finished matches with results
    cur.execute("""
        SELECT m.id, m.home, m.away, m.stage, m.datetime,
               r.home_goals as act_h, r.away_goals as act_a
        FROM matches m
        JOIN match_results r ON r.match_id = m.id
    """)
    finished = cur.fetchall()

    scores = {u: {"total": 0, "match_points": 0, "score_bonus": 0, "correct_picks": 0} for u in USERS}

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

    # Champion points (if set)
    actual_champion = get_setting("actual_champion")
    champion_points = 12  # nice round number for the big prize

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

    # Add current picks for display
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
            "champion_points": s.get("champion_points", 0),
            "correct_picks": s.get("correct_picks", 0),
            "champion_pick": picks[user]
        })

    # Sort by total desc
    leaderboard.sort(key=lambda x: x["total"], reverse=True)
    return {
        "leaderboard": leaderboard,
        "actual_champion": actual_champion,
        "champion_points_value": champion_points if actual_champion else 0
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
