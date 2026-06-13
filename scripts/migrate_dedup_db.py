#!/usr/bin/env python3
"""
Migration script to clean duplicate matches in vmtips.db.

Groups matches by (normalized date + canonical team names) to handle
Swedish vs English name variations (Sverige/Sweden, etc.).

For each duplicate group:
- Picks the best representative (prefers one with a final result)
- Migrates all predictions and results from duplicate rows to the kept row
- Deletes the duplicate match rows

Usage (run from inside the pod):
  python3 /app/scripts/migrate_dedup_db.py /data/vmtips.db

Strongly recommended:
  cp /data/vmtips.db /data/vmtips.db.bak.$(date +%s)
before running.
"""

import sqlite3
import json
import urllib.request
import sys
import os
from collections import defaultdict
from datetime import datetime, timedelta

def canonical_name(name: str) -> str:
    if not name:
        return ""
    n = name.lower().strip()
    aliases = {
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
        # English variants (for robustness)
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
        "korea republic": "South Korea",
        "south korea": "South Korea",
        "south africa": "South Africa",
        "czech republic": "Czechia",
        "bosnia and herzegovina": "Bosnia and Herzegovina",
        "bosnia-herzegovina": "Bosnia and Herzegovina",
    }
    return aliases.get(n, name.title())

def get_canonical_from_json():
    """Fetch the live openfootball JSON to get authoritative English names."""
    url = "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        mapping = {}
        for m in data.get("matches", []):
            d = m.get("date", "")[:10]
            h = canonical_name(m.get("team1", ""))
            a = canonical_name(m.get("team2", ""))
            key = (d, h, a)
            mapping[key] = (m.get("team1", ""), m.get("team2", ""))
            # also store swapped
            mapping[(d, a, h)] = (m.get("team2", ""), m.get("team1", ""))
        return mapping
    except Exception as e:
        print(f"Warning: could not fetch JSON for canonical names ({e}). Using best effort.")
        return {}

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 migrate_dedup_db.py /path/to/vmtips.db")
        sys.exit(1)

    db_path = sys.argv[1]
    if not os.path.exists(db_path):
        print(f"ERROR: DB not found at {db_path}")
        sys.exit(1)

    print(f"Working on: {db_path}")
    print("IMPORTANT: You should have a backup (e.g. cp /data/vmtips.db /data/vmtips.db.bak.$(date +%s))")

    json_map = get_canonical_from_json()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT id, datetime, home, away, stage FROM matches ORDER BY id")
    rows = cur.fetchall()

    # Group by (date, canonical_home, canonical_away)
    groups = defaultdict(list)
    for r in rows:
        d = (r["datetime"] or "")[:10]
        ch = canonical_name(r["home"])
        ca = canonical_name(r["away"])
        key = (d, ch, ca)
        groups[key].append(dict(r))

    print(f"Found {len(groups)} unique groups from {len(rows)} total match rows.")

    total_deleted = 0
    total_migrated_predictions = 0
    total_migrated_results = 0

    for key, items in groups.items():
        if len(items) <= 1:
            continue

        print(f"  Duplicate group {key} has {len(items)} rows - cleaning...")

        # Choose best: prefer one with final result
        best = None
        for it in items:
            cur.execute("SELECT 1 FROM match_results WHERE match_id = ? AND is_final = 1 LIMIT 1", (it["id"],))
            if cur.fetchone():
                best = it
                break

        if best is None:
            # Prefer one that matches the live JSON canonical names
            if key in json_map:
                jh, ja = json_map[key]
                for it in items:
                    if it["home"] == jh and it["away"] == ja:
                        best = it
                        break
            if best is None:
                best = min(items, key=lambda x: x["id"])

        best_id = best["id"]

        # Update the kept row to use nice canonical names (from JSON if available)
        final_home = best["home"]
        final_away = best["away"]
        if key in json_map:
            final_home, final_away = json_map[key]
            cur.execute("UPDATE matches SET home = ?, away = ? WHERE id = ?", (final_home, final_away, best_id))

        for it in items:
            if it["id"] == best_id:
                continue
            dup_id = it["id"]

            # Migrate predictions
            cur.execute("""
                INSERT OR REPLACE INTO predictions (user, match_id, home_goals, away_goals)
                SELECT user, ?, home_goals, away_goals FROM predictions WHERE match_id = ?
            """, (best_id, dup_id))
            total_migrated_predictions += cur.rowcount

            # Migrate results (prefer final)
            cur.execute("SELECT home_goals, away_goals, is_final FROM match_results WHERE match_id = ?", (dup_id,))
            res = cur.fetchone()
            if res:
                cur.execute("""
                    INSERT OR REPLACE INTO match_results (match_id, home_goals, away_goals, is_final)
                    VALUES (?, ?, ?, ?)
                """, (best_id, res[0], res[1], res[2]))
                total_migrated_results += 1

            # Delete from duplicate
            cur.execute("DELETE FROM predictions WHERE match_id = ?", (dup_id,))
            cur.execute("DELETE FROM match_results WHERE match_id = ?", (dup_id,))
            cur.execute("DELETE FROM matches WHERE id = ?", (dup_id,))
            total_deleted += 1

    conn.commit()
    conn.close()

    print("\n=== Migration complete ===")
    print(f"Deleted {total_deleted} duplicate match rows.")
    print(f"Migrated {total_migrated_predictions} prediction rows.")
    print(f"Migrated {total_migrated_results} result rows.")
    print("Run a sync (button or wait for background) and restart the pod to pick up the clean data.")

if __name__ == "__main__":
    main()
