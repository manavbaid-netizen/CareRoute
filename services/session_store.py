from __future__ import annotations

import sqlite3
import json
import datetime
from typing import Dict, Any, Optional
from config import Config


class SessionStore:
    """
    Persistent SQLite session store for CareRoute patient conversations.
    Ensures that conversation state is keyed by patient user address and
    survives agent restarts.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = str(db_path or Config.DB_PATH)
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._init_db()

    def _init_db(self) -> None:
        Config.ensure_directories()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS patient_sessions (
                    user_address TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    patient_id TEXT NOT NULL,
                    patient_name TEXT NOT NULL,
                    dossier_id TEXT,
                    selected_slot_json TEXT,
                    booking_details_json TEXT,
                    pending_request_json TEXT,
                    metadata_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def get_or_create_session(self, user_address: str) -> Dict[str, Any]:
        """Fetch active session for user address, or initialize a new one."""
        if user_address in self._cache:
            return self._cache[user_address]

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM patient_sessions WHERE user_address = ?", (user_address,)
            )
            row = cursor.fetchone()

            if row:
                session = {
                    "user_address": row["user_address"],
                    "session_id": row["user_address"],
                    "state": row["state"],
                    "patient_id": row["patient_id"],
                    "patient_name": row["patient_name"],
                    "dossier_id": row["dossier_id"],
                    "selected_slot": json.loads(row["selected_slot_json"]) if row["selected_slot_json"] else None,
                    "booking_details": json.loads(row["booking_details_json"]) if row["booking_details_json"] else None,
                    "pending_request": json.loads(row["pending_request_json"]) if row["pending_request_json"] else None,
                    "metadata": json.loads(row["metadata_json"]) if row["metadata_json"] else {},
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "dossier": None,
                }
                self._cache[user_address] = session
                return session

        # New session initialization
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        # Derive short patient ID from address
        clean_addr = user_address.replace("agent", "").replace("1", "")[:6].upper() or "USER"
        new_session: Dict[str, Any] = {
            "user_address": user_address,
            "session_id": user_address,
            "state": "STATE_INTAKE",
            "patient_id": f"PAT-{clean_addr}",
            "patient_name": "रामकुमार (Ram Kumar)",
            "dossier_id": None,
            "dossier": None,
            "selected_slot": None,
            "booking_details": None,
            "pending_request": None,
            "metadata": {},
            "created_at": now,
            "updated_at": now,
        }
        self._cache[user_address] = new_session
        self.save_session(user_address, new_session)
        return new_session

    def save_session(self, user_address: str, session: Dict[str, Any]) -> None:
        """Persist session state to SQLite."""
        self._cache[user_address] = session
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        session["updated_at"] = now

        selected_slot_json = json.dumps(session.get("selected_slot")) if session.get("selected_slot") else None
        booking_details_json = json.dumps(session.get("booking_details")) if session.get("booking_details") else None
        pending_request_json = json.dumps(session.get("pending_request")) if session.get("pending_request") else None
        metadata_json = json.dumps(session.get("metadata", {}))

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO patient_sessions (
                    user_address, state, patient_id, patient_name, dossier_id,
                    selected_slot_json, booking_details_json, pending_request_json,
                    metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_address) DO UPDATE SET
                    state=excluded.state,
                    patient_id=excluded.patient_id,
                    patient_name=excluded.patient_name,
                    dossier_id=excluded.dossier_id,
                    selected_slot_json=excluded.selected_slot_json,
                    booking_details_json=excluded.booking_details_json,
                    pending_request_json=excluded.pending_request_json,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    user_address,
                    session.get("state", "STATE_INTAKE"),
                    session.get("patient_id", "PAT_UNKNOWN"),
                    session.get("patient_name", "Patient"),
                    session.get("dossier_id"),
                    selected_slot_json,
                    booking_details_json,
                    pending_request_json,
                    metadata_json,
                    session.get("created_at", now),
                    now,
                ),
            )
            conn.commit()

    def clear_session(self, user_address: str) -> None:
        """Remove session on explicit completion."""
        self._cache.pop(user_address, None)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM patient_sessions WHERE user_address = ?", (user_address,))
            conn.commit()
