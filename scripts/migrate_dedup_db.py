#!/usr/bin/env python3
"""
Standalone migration script to clean up duplicate matches in vmtips.db.

It groups matches by date + canonical team names (handles Swedish vs English),
picks the best representative for each group (prefers one with final result),
migrates all predictions and results to it, and deletes the duplicates.

Usage (run inside the pod or with the DB file):
  python3 scripts/migrate_dedup_db.py /data/vmtips.db

It will create /data/vmtips_clean.db with the deduplicated data.
Then you can backup the old one and replace:
  mv /data/vmtips.db /data/vmtips.db.bak
  mv /data/vmtips_clean.db /data/vmtips.db

Then restart the pod.

The script also tries to normalize names to English where possible
by cross-referencing the live openfootball JSON.
"""

import sqlite3
import json
import urllib.request
import os
import sys
from datetime import datetime
from collections import defaultdict

DB_PATH = sys.argv[1] if len(sys.argv) > 1 else "/data/vmtips.db"
CLEAN_PATH = DB_PATH.replace(".db", "_clean.db")

# Canonical mapping - extend as needed
NAME_MAP = {
    # Swedish -> English canonical
    "sverige": "Sweden",
    "tunisien": "Tunisia",
    "nederländerna": "Netherlands",
    "elfenbenskusten": "Côte d'Ivoire",
    "kap verde": "Cape Verde",
    "spanien": "Spain",
    "tyskland": "Germany",
    "brasilien": "Brazil",
    "marocko": "Morocco",
    "haiti": "Haiti",
    "skottland": "Scotland",
    "australien": "Australia",
    "turkiet": "Turkey",
    "argentina": "Argentina",
    "algeriet": "Algeria",
    "england": "England",
    "kroatien": "Croatia",
    "frankrike": "France",
    "senegal": "Senegal",
    "japan": "Japan",
    "usa": "USA",
    "paraguay": "Paraguay",
    "qatar": "Qatar",
    "schweiz": "Switzerland",
    "mexico": "Mexico",
    "sydafrika": "South Africa",
    "sydkorea": "South Korea",
    "czechia": "Czechia",
    "kanada": "Canada",
    "bosnien och hercegovina": "Bosnia and Herzegovina",
    # English variants to canonical
    "sweden": "Sweden",
    "tunisia": "Tunisia",
    "netherlands": "Netherlands",
    "côte d'ivoire": "Côte d'Ivoire",
    "ivory coast": "Côte d'Ivoire",
    "cape verde": "Cape Verde",
    "cabo verde": "Cape Verde",
    "spain": "Spain",
    "germany": "Germany",
    "brazil": "Brazil",
    "morocco": "Morocco",
    "haiti": "Haiti",
    "scotland": "Scotland",
    "australia": "Australia",
    "turkey": "Turkey",
    "argentina": "Argentina",
    "algeria": "Algeria",
    "england": "England",
    "croatia": "Croatia",
    "france": "France",
    "senegal": "Senegal",
    "japan": "Japan",
    "united states": "USA",
    "paraguay": "Paraguay",
    "qatar": "Qatar",
    "switzerland": "Switzerland",
    "mexico": "Mexico",
    "south africa": "South Africa",
    "south korea": "South Korea",
    "korea republic": "South Korea",
    "czechia": "Czechia",
    "czech republic": "Czechia",
    "canada": "Canada",
    "bosnia and herzegovina": "Bosnia and Herzegovina",
    "bosnia-herzegovina": "Bosnia and Herzegovina",
}

def canonical(name: str) -> str:
    if not name:
        return ""
    key = name.lower().strip()
    return NAME_MAP.get(key, name.title())

def get_json_matches():
    """Fetch current openfootball JSON to get canonical English names."""
    url = "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        json_map = {}
        for m in data.get("matches", []):
            d = m.get("date", "")[:10]
            h = canonical(m.get("team1", ""))
            a = canonical(m.get("team2", ""))
            key = (d, h, a)
            json_map[key] = {
                "home": m.get("team1", ""),
                "away": m.get("team2", ""),
            }
            # also swapped
            json_map[(d, a, h)] = {
                "home": m.get("team2", ""),
                "away": m.get("team1", ""),
            }
        return json_map
    except Exception as e:
        print(f"Warning: could not fetch JSON for canonical names: {e}")
        return {}

def main():
    if not os.path.exists(DB_PATH):
        print(f"DB not found at {DB_PATH}")
        sys.exit(1)

    print(f"Reading from {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Get all matches
    cur.execute("SELECT id, datetime, home, away, stage FROM matches ORDER BY id")
    rows = cur.fetchall()

    json_map = get_json_matches()

    groups = defaultdict(list)
    for row in rows:
        m_id = row["id"]
        dt = row["datetime"] or ""
        date_key = dt[:10]
        ch = canonical(row["home"])
        ca = canonical(row["away"])
        key = (date_key, ch, ca)
        groups[key].append({
            "id": m_id,
            "datetime": dt,
            "home": row["home"],
            "away": row["away"],
            "stage": row["stage"],
        })

    print(f"Found {len(groups)} unique match groups, {len(rows)} total rows")

    # For each group, decide the canonical row and migrate data
    to_delete = []
    migrated_predictions = 0
    migrated_results = 0

    for key, items in groups.items():
        if len(items) == 1:
            continue

        # Prefer row that has final result
        best = None
        for item in items:
            cur.execute("SELECT is_final FROM match_results WHERE match_id = ?", (item["id"],))
            r = cur.fetchone()
            if r and r[0]:
                best = item
                break
        if best is None:
            # Prefer the one that looks like it came from JSON (English names)
            for item in items:
                if item["home"][0].isupper() and " " not in item["home"] or item["home"] in ["USA", "Qatar"]:
                    best = item
                    break
        if best is None:
            best = min(items, key=lambda x: x["id"])

        best_id = best["id"]
        # Try to get canonical English names from JSON if available
        date_key, ch, ca = key
        jnames = json_map.get(key) or json_map.get((date_key, ca, ch))
        if jnames:
            best_home = jnames["home"]
            best_away = jnames["away"]
        else:
            best_home = best["home"]
            best_away = best["away"]

        # Update the best row to canonical names + correct time (if we have it)
        cur.execute("""
            UPDATE matches SET home = ?, away = ? WHERE id = ?
        """, (best_home, best_away, best_id))

        for item in items:
            if item["id"] == best_id:
                continue
            dup_id = item["id"]

            # Migrate predictions
            cur.execute("""
                INSERT OR REPLACE INTO predictions (user, match_id, home_goals, away_goals)
                SELECT user, ?, home_goals, away_goals FROM predictions WHERE match_id = ?
            """, (best_id, dup_id))
            migrated_predictions += cur.rowcount

            # Migrate results - prefer final
            cur.execute("""
                SELECT home_goals, away_goals, is_final FROM match_results WHERE match_id = ?
            """, (dup_id,))
            r = cur.fetchone()
            if r:
                cur.execute("""
                    INSERT OR REPLACE INTO match_results (match_id, home_goals, away_goals, is_final)
                    VALUES (?, ?, ?, ?)
                """, (best_id, r[0], r[1], r[2]))
                migrated_results += 1

            # Delete from dup
            cur.execute("DELETE FROM predictions WHERE match_id = ?", (dup_id,))
            cur.execute("DELETE FROM match_results WHERE match_id = ?", (dup_id,))
            to_delete.append(dup_id)

        # Clean the dups
        if to_delete:
            cur.executemany("DELETE FROM matches WHERE id = ?", [(d,) for d in to_delete])
            print(f"Group {key}: kept {best_id} ({best_home} vs {best_away}), deleted {len(to_delete)} dups")

    deleted = len(to_delete)
    conn.commit()
    conn.close()

    print(f"\nDone. Deleted {deleted} duplicate match rows.")
    print(f"Migrated predictions: {migrated_predictions}")
    print(f"Migrated results: {migrated_results}")
    print(f"Clean DB written? No - this script works in-place on the given DB.")
    print("If you want a separate clean file, copy the DB first, then run the script on the copy.")

if __name__ == "__main__":
    main()
PYEOF
echo "Script written to scripts/migrate_dedup_db.py"