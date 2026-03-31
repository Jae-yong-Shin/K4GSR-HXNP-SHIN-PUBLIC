#!/usr/bin/env python3
"""SQLite scan history database for K4GSR BL10 NanoProbe.

Stores scan metadata persistently so history survives server restarts.
Auto-created on first use. Thread-safe.

Usage:
    from data.scan_db import ScanDB

    db = ScanDB()          # creates scan_history.db in data/scans/
    db.record_scan(...)    # called by BlueskyRunner after each scan
    rows = db.list_scans() # returns recent scans
    db.close()
"""

import os
import json
import sqlite3
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

log = logging.getLogger("scan-db")

DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(__file__), 'scans', 'scan_history.db'
)


class ScanDB:
    """SQLite-backed scan history database."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._create_tables()
        log.info(f"ScanDB opened: {db_path}")

    def _create_tables(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS scans (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                uid         TEXT UNIQUE,
                plan_name   TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'unknown',
                start_time  TEXT NOT NULL,
                end_time    TEXT,
                num_points  INTEGER DEFAULT 0,
                energy_keV  REAL,
                params      TEXT,          -- JSON
                h5_file     TEXT,          -- path to HDF5 file
                notes       TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_scans_time ON scans(start_time DESC);
            CREATE INDEX IF NOT EXISTS idx_scans_plan ON scans(plan_name);
        """)
        self._conn.commit()

    def record_scan(self, uid: str, plan_name: str, status: str,
                    start_time: str, end_time: Optional[str] = None,
                    num_points: int = 0, energy_keV: Optional[float] = None,
                    params: Optional[dict] = None,
                    h5_file: Optional[str] = None,
                    notes: str = '') -> int:
        """Record a completed scan.

        Returns:
            Row ID of the inserted record.
        """
        try:
            cur = self._conn.execute("""
                INSERT OR REPLACE INTO scans
                    (uid, plan_name, status, start_time, end_time,
                     num_points, energy_keV, params, h5_file, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                uid, plan_name, status, start_time, end_time,
                num_points, energy_keV,
                json.dumps(params) if params else None,
                h5_file, notes
            ))
            self._conn.commit()
            log.info(f"Recorded scan: {plan_name} uid={uid[:8]} ({num_points} pts)")
            return cur.lastrowid
        except Exception as e:
            log.error(f"Failed to record scan: {e}")
            return -1

    def list_scans(self, limit: int = 50, offset: int = 0,
                   plan_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """List recent scans.

        Args:
            limit: max number of results
            offset: pagination offset
            plan_filter: filter by plan name (optional)

        Returns:
            List of scan dicts, most recent first.
        """
        query = "SELECT * FROM scans"
        params = []
        if plan_filter:
            query += " WHERE plan_name = ?"
            params.append(plan_filter)
        query += " ORDER BY start_time DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self._conn.execute(query, params).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            if d.get('params'):
                try:
                    d['params'] = json.loads(d['params'])
                except (json.JSONDecodeError, TypeError):
                    pass
            result.append(d)
        return result

    def get_scan(self, uid: str) -> Optional[Dict[str, Any]]:
        """Get a single scan by UID."""
        row = self._conn.execute(
            "SELECT * FROM scans WHERE uid = ?", (uid,)
        ).fetchone()
        if row:
            d = dict(row)
            if d.get('params'):
                try:
                    d['params'] = json.loads(d['params'])
                except (json.JSONDecodeError, TypeError):
                    pass
            return d
        return None

    def count(self, plan_filter: Optional[str] = None) -> int:
        """Count total scans."""
        if plan_filter:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM scans WHERE plan_name = ?",
                (plan_filter,)
            ).fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) FROM scans").fetchone()
        return row[0] if row else 0

    def delete_scan(self, uid: str) -> bool:
        """Delete a scan record."""
        cur = self._conn.execute("DELETE FROM scans WHERE uid = ?", (uid,))
        self._conn.commit()
        return cur.rowcount > 0

    def close(self):
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
            log.info("ScanDB closed")
