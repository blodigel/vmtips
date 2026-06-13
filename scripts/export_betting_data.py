#!/usr/bin/env python3
"""
Export script for vmtips betting data.

This dumps all user predictions, group picks, tournament picks,
and current match results to JSON files so you can manually re-insert
them after cleaning the database (e.g. after duplicates or reset).

Usage (run inside the pod):
  python3 /app/scripts/export_betting_data.py /data/vmtips.db

It will create files in the current directory (or specify --output-dir):
  - matches.json
  - results.json
  - predictions.json          (per-match bets by Lillen/Stinis)
  - group_predictions.json    (group winner bets)
  - tournament_picks.json     (overall winner bets)

These files are human-readable. You can use them to re-populate a clean DB
via the admin UI, another script, or direct SQL.

Example to run inside pod:
  kubectl exec -it deployment/vmtips -- python3 /app/scripts/export_betting_data.py /data/vmtips.db

Then copy the JSON files out:
  kubectl cp deployment/vmtips:/app/scripts/matches.json ./matches.json
  etc.
"""

import sqlite3
import json
import sys
import os
from datetime import datetime

def export_to_json(db_path, output_dir="."):
    if not os.path.exists(db_path):
        print(f"ERROR: Database not found at {db_path}")
        sys.exit(1)

    os.makedirs(output_dir, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    print(f"Exporting from {db_path} to {output_dir} ...")

    # 1. Matches (all, even duplicates for reference)
    cur.execute("SELECT id, datetime, home, away, stage FROM matches ORDER BY datetime, id")
    matches = [dict(row) for row in cur.fetchall()]
    with open(os.path.join(output_dir, "matches.json"), "w", encoding="utf-8") as f:
        json.dump(matches, f, indent=2, ensure_ascii=False)
    print(f"  Exported {len(matches)} matches to matches.json")

    # 2. Results (final and provisional)
    cur.execute("""
        SELECT match_id, home_goals, away_goals, is_final 
        FROM match_results 
        ORDER BY match_id
    """)
    results = [dict(row) for row in cur.fetchall()]
    with open(os.path.join(output_dir, "results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"  Exported {len(results)} results to results.json")

    # 3. Per-match predictions (the actual bets)
    cur.execute("""
        SELECT p.user, p.match_id, m.datetime, m.home, m.away, 
               p.home_goals, p.away_goals
        FROM predictions p
        JOIN matches m ON p.match_id = m.id
        ORDER BY m.datetime, p.user
    """)
    predictions = [dict(row) for row in cur.fetchall()]
    with open(os.path.join(output_dir, "predictions.json"), "w", encoding="utf-8") as f:
        json.dump(predictions, f, indent=2, ensure_ascii=False)
    print(f"  Exported {len(predictions)} predictions to predictions.json")

    # 4. Group winner predictions
    cur.execute("SELECT user, group_name, winner FROM group_predictions ORDER BY group_name, user")
    group_picks = [dict(row) for row in cur.fetchall()]
    with open(os.path.join(output_dir, "group_predictions.json"), "w", encoding="utf-8") as f:
        json.dump(group_picks, f, indent=2, ensure_ascii=False)
    print(f"  Exported {len(group_picks)} group predictions to group_predictions.json")

    # 5. Tournament winner picks
    cur.execute("SELECT user, champion FROM tournament_picks ORDER BY user")
    tournament_picks = [dict(row) for row in cur.fetchall()]
    with open(os.path.join(output_dir, "tournament_picks.json"), "w", encoding="utf-8") as f:
        json.dump(tournament_picks, f, indent=2, ensure_ascii=False)
    print(f"  Exported {len(tournament_picks)} tournament picks to tournament_picks.json")

    conn.close()

    print("\nExport complete!")
    print("Files are in:", os.path.abspath(output_dir))
    print("\nYou can now safely reset the DB (rm /data/vmtips.db) if needed.")
    print("After a clean start, you can re-insert using the admin UI or a future import script.")
    print("The JSON files above contain everything you need to recreate the bets manually.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 export_betting_data.py /path/to/vmtips.db [output_directory]")
        sys.exit(1)

    db_path = sys.argv[1]
    out_dir = sys.argv[2] if len(sys.argv) > 2 else "/tmp"

    export_to_json(db_path, out_dir)
