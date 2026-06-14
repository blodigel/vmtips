#!/usr/bin/env python3
"""
Re-import script for vmtips betting data.

After you have reset the database (rm /data/vmtips.db + restart pod),
run this to restore your predictions, group picks and tournament picks
from the exported JSON files.

Usage (inside the pod, after the app has started and re-seeded):
  python3 /app/scripts/reimport_betting_data.py /data/vmtips.db /path/to/export/dir

Example:
  python3 /app/scripts/reimport_betting_data.py /data/vmtips.db /tmp/vmtips-export

The script expects these files in the export dir:
- predictions.json
- group_predictions.json
- tournament_picks.json

It will look up the new match_ids by date + team names (using the same
normalization as the app).
"""

import sqlite3
import json
import sys
import os
from datetime import datetime

def canonical_name(name: str) -> str:
    if not name:
        return ""
    n = name.lower().strip()
    aliases = {
        "sverige": "Sweden", "sweden": "Sweden",
        "tunisien": "Tunisia", "tunisia": "Tunisia",
        "nederländerna": "Netherlands", "netherlands": "Netherlands",
        "elfenbenskusten": "Côte d'Ivoire", "ivory coast": "Côte d'Ivoire",
        "kap verde": "Cape Verde", "cabo verde": "Cape Verde",
        "spanien": "Spain", "spain": "Spain",
        "tyskland": "Germany", "germany": "Germany",
        "brasilien": "Brazil", "brazil": "Brazil",
        "marocko": "Morocco", "morocco": "Morocco",
        "haiti": "Haiti",
        "skottland": "Scotland", "scotland": "Scotland",
        "australien": "Australia", "australia": "Australia",
        "turkiet": "Turkey", "turkey": "Turkey",
        "argentina": "Argentina",
        "algeriet": "Algeria", "algeria": "Algeria",
        "england": "England",
        "kroatien": "Croatia", "croatia": "Croatia",
        "frankrike": "France", "france": "France",
        "senegal": "Senegal",
        "japan": "Japan",
        "usa": "USA", "united states": "USA",
        "paraguay": "Paraguay",
        "qatar": "Qatar",
        "schweiz": "Switzerland", "switzerland": "Switzerland",
        "mexico": "Mexico",
        "sydafrika": "South Africa", "south africa": "South Africa",
        "sydkorea": "South Korea", "south korea": "South Korea",
        "korea republic": "South Korea",
        "czechia": "Czechia", "czech republic": "Czechia",
        "kanada": "Canada", "canada": "Canada",
        "bosnien och hercegovina": "Bosnia and Herzegovina",
        "bosnia and herzegovina": "Bosnia and Herzegovina",
        "bosnia-herzegovina": "Bosnia and Herzegovina",
    }
    return aliases.get(n, name.title())

def find_match_id(cur, date_str, home, away):
    """Find the current match_id by date + normalized team names."""
    date_prefix = date_str[:10]
    ch = canonical_name(home)
    ca = canonical_name(away)

    cur.execute("""
        SELECT id, home, away, datetime
        FROM matches
        WHERE datetime LIKE ?
        ORDER BY id
    """, (date_prefix + '%',))

    for row in cur.fetchall():
        db_home = canonical_name(row["home"])
        db_away = canonical_name(row["away"])
        if (db_home == ch and db_away == ca) or (db_home == ca and db_away == ch):
            return row["id"]
    return None

def main():
    if len(sys.argv) < 3:
        print("Usage: python3 reimport_betting_data.py /path/to/vmtips.db /path/to/export/dir")
        sys.exit(1)

    db_path = sys.argv[1]
    export_dir = sys.argv[2]

    if not os.path.exists(db_path):
        print(f"ERROR: Database not found at {db_path}")
        sys.exit(1)

    predictions_file = os.path.join(export_dir, "predictions.json")
    group_file = os.path.join(export_dir, "group_predictions.json")
    tournament_file = os.path.join(export_dir, "tournament_picks.json")

    for f in [predictions_file, group_file, tournament_file]:
        if not os.path.exists(f):
            print(f"ERROR: Required file not found: {f}")
            sys.exit(1)

    print(f"Re-importing into {db_path} from {export_dir}...")

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # 1. Re-import match predictions
    with open(predictions_file, encoding="utf-8") as f:
        predictions = json.load(f)

    imported_preds = 0
    for p in predictions:
        new_match_id = find_match_id(cur, p["datetime"], p["home"], p["away"])
        if new_match_id is None:
            print(f"WARNING: Could not find match for prediction: {p['home']} vs {p['away']} on {p['datetime'][:10]}")
            continue

        cur.execute("""
            INSERT OR REPLACE INTO predictions (user, match_id, home_goals, away_goals)
            VALUES (?, ?, ?, ?)
        """, (p["user"], new_match_id, p["home_goals"], p["away_goals"]))
        imported_preds += 1

    print(f"Imported {imported_preds} match predictions.")

    # 2. Re-import group predictions
    with open(group_file, encoding="utf-8") as f:
        group_picks = json.load(f)

    for g in group_picks:
        cur.execute("""
            INSERT OR REPLACE INTO group_predictions (user, group_name, winner)
            VALUES (?, ?, ?)
        """, (g["user"], g["group_name"], g["winner"]))

    print(f"Imported {len(group_picks)} group predictions.")

    # 3. Re-import tournament picks
    with open(tournament_file, encoding="utf-8") as f:
        tournament_picks = json.load(f)

    for t in tournament_picks:
        cur.execute("""
            INSERT OR REPLACE INTO tournament_picks (user, champion)
            VALUES (?, ?)
        """, (t["user"], t["champion"]))

    print(f"Imported {len(tournament_picks)} tournament picks.")

    conn.commit()
    conn.close()

    print("\nRe-import complete!")
    print("You may want to restart the pod (kubectl rollout restart deployment/vmtips) so the app reloads everything.")
    print("Then open the UI and verify that your bets are back.")

if __name__ == "__main__":
    main()
