"""MVP persistence: write each analysis result to a local SQLite DB.

Stage 2 swaps this for Supabase (UPDATE row by id). Keeping the interface tiny so the
swap is a one-file change.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

DB_PATH = os.environ.get("ANOMALY_DB", str(Path(__file__).resolve().parents[2] / "anomaly_results.db"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS results (
  id TEXT,                      -- row id (optional, ties to source record)
  image_url TEXT,
  task TEXT, mode TEXT, model TEXT,
  description TEXT,
  anomalies_json TEXT,
  road_condition TEXT,
  tags_json TEXT,
  pothole_present INTEGER,
  latency_ms INTEGER,
  created_at TEXT
);
"""


def init():
    con = sqlite3.connect(DB_PATH)
    con.execute(_SCHEMA)
    con.commit()
    con.close()


def save(rec: dict) -> int:
    con = sqlite3.connect(DB_PATH)
    cur = con.execute(
        """INSERT INTO results
           (id,image_url,task,mode,model,description,anomalies_json,road_condition,
            tags_json,pothole_present,latency_ms,created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (rec.get("id"), rec.get("image_url"), rec.get("task"), rec.get("mode"),
         rec.get("model"), rec.get("description"),
         json.dumps(rec.get("anomalies", []), ensure_ascii=False),
         rec.get("road_condition"),
         json.dumps(rec.get("tags", []), ensure_ascii=False),
         1 if rec.get("pothole_present") else 0,
         rec.get("latency_ms"),
         time.strftime("%Y-%m-%dT%H:%M:%S")),
    )
    con.commit()
    rowid = cur.lastrowid
    con.close()
    return rowid
