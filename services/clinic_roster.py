from __future__ import annotations

import datetime
import json
import logging
import sqlite3
import uuid
from enum import Enum
from pathlib import Path
from typing import Any

from config import Config

logger = logging.getLogger("CareRoute.ClinicRoster")


class Specialty(str, Enum):
    """Controlled medical specialties supported across CHC telemedicine network."""

    PULMONOLOGY = "Pulmonology / Chest & Respiratory Medicine"
    DERMATOLOGY = "Dermatology & Venereology"
    GENERAL_MEDICINE = "General Medicine & Primary Health"
    PEDIATRICS = "Pediatrics & Child Health"
    ORTHOPEDICS = "Orthopedics & Joint Care"
    OBGYN = "Obstetrics & Gynecology"


def map_specialty(target_specialty: str) -> tuple[Specialty, str]:
    """
    Map arbitrary clinical specialty string to controlled Specialty Enum and roster key.
    Defaults to General Medicine if unclassified.
    """
    low = (target_specialty or "").lower()
    if any(k in low for k in ("pulmon", "chest", "respirat", "tb", "फेफड़ा", "छाती")):
        return Specialty.PULMONOLOGY, "pulmonology"
    elif any(k in low for k in ("derm", "skin", "fungal", "त्वचा", "चर्म")):
        return Specialty.DERMATOLOGY, "dermatology"
    elif any(k in low for k in ("pediatric", "child", "बच्चा", "शिशु")):
        return Specialty.PEDIATRICS, "pediatrics"
    elif any(k in low for k in ("ortho", "bone", "joint", "हड्डी", "घुटने", "कमर")):
        return Specialty.ORTHOPEDICS, "orthopedics"
    elif any(k in low for k in ("gyn", "obstetric", "pregnancy", "महिला", "गर्भावस्था")):
        return Specialty.OBGYN, "obgyn"
    else:
        return Specialty.GENERAL_MEDICINE, "general"


class ClinicRosterService:
    """
    Manages rural Community Health Center (CHC) doctors, per-date appointment slots,
    and atomic booking capacity with SQLite persistence and foreign keys.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = str(db_path or Config.DB_PATH)
        self.roster_data = self._load_roster_json()
        self._init_db()

    def _load_roster_json(self) -> dict[str, Any]:
        """Load doctor roster and slot configurations from data/clinic_roster.json."""
        paths_to_try = [
            Path("data/clinic_roster.json"),
            Config.DATA_DIR / "clinic_roster.json",
            Path("data/seed/clinic_roster.json"),
        ]
        for path in paths_to_try:
            if path.exists():
                try:
                    with open(path, encoding="utf-8") as f:
                        data = json.load(f)
                        return data
                except Exception as e:
                    logger.warning(f"Could not load roster from {path}: {e}")

        # Inline fallback if json file missing
        return {
            "clinic_name": "अलवर सामुदायिक स्वास्थ्य केंद्र (Alwar CHC)",
            "specialties": {
                "pulmonology": {
                    "doctor_name": "Dr. Harish Sharma (एमडी, चेस्ट एवं जनरल फिजिशियन)",
                    "specialty": "Pulmonology / Chest & Respiratory Medicine",
                    "specialty_hi": "छाती एवं फेफड़ा रोग विशेषज्ञ",
                    "clinic_name": "अलवर सामुदायिक स्वास्थ्य केंद्र (Alwar CHC)",
                    "room_no": "कक्ष संख्या 4 (Room 4)",
                    "slots": [
                        {"slot_id": "ALW_CHEST_1000", "time": "10:00 AM - 10:30 AM", "capacity": 5},
                        {"slot_id": "ALW_CHEST_1130", "time": "11:30 AM - 12:00 PM", "capacity": 3},
                        {"slot_id": "ALW_CHEST_1230", "time": "12:30 PM - 01:00 PM", "capacity": 4},
                    ],
                },
                "dermatology": {
                    "doctor_name": "Dr. Sunita Verma (एमडी, त्वचा एवं चर्म रोग)",
                    "specialty": "Dermatology & Venereology",
                    "specialty_hi": "त्वचा एवं चर्म रोग विशेषज्ञ",
                    "clinic_name": "अलवर सामुदायिक स्वास्थ्य केंद्र (Alwar CHC)",
                    "room_no": "कक्ष संख्या 7 (Room 7)",
                    "slots": [
                        {"slot_id": "ALW_DERM_1030", "time": "10:30 AM - 11:00 AM", "capacity": 4},
                        {"slot_id": "ALW_DERM_1145", "time": "11:45 AM - 12:15 PM", "capacity": 2},
                        {"slot_id": "ALW_DERM_1245", "time": "12:45 PM - 01:15 PM", "capacity": 5},
                    ],
                },
                "general": {
                    "doctor_name": "Dr. Rajesh Meena (एमबीबीएस, वरिष्ठ चिकित्सा अधिकारी)",
                    "specialty": "General Medicine & Primary Health",
                    "specialty_hi": "सामान्य रोग विशेषज्ञ (General Physician)",
                    "clinic_name": "अलवर सामुदायिक स्वास्थ्य केंद्र (Alwar CHC)",
                    "room_no": "कक्ष संख्या 2 (Room 2)",
                    "slots": [
                        {"slot_id": "ALW_GEN_0930", "time": "09:30 AM - 10:00 AM", "capacity": 6},
                        {"slot_id": "ALW_GEN_1100", "time": "11:00 AM - 11:30 AM", "capacity": 5},
                    ],
                },
            },
        }

    @property
    def DOCTORS(self) -> dict[str, Any]:
        """Backward compatibility accessor for legacy code."""
        return self.roster_data.get("specialties", {})

    def _init_db(self) -> None:
        """Create tables with foreign keys and schema migration."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA foreign_keys = ON;")

            # 1. Per-date slots table with capacity & booked_count
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS slots (
                    slot_id TEXT NOT NULL,
                    slot_date TEXT NOT NULL,
                    slot_time TEXT NOT NULL,
                    specialty_key TEXT NOT NULL,
                    doctor_name TEXT NOT NULL,
                    room_no TEXT NOT NULL,
                    clinic_name TEXT NOT NULL,
                    capacity INTEGER NOT NULL,
                    booked_count INTEGER DEFAULT 0,
                    PRIMARY KEY (slot_id, slot_date)
                )
                """
            )

            # 2. Appointments table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS appointments (
                    ticket_id TEXT PRIMARY KEY,
                    patient_id TEXT NOT NULL,
                    patient_name TEXT NOT NULL,
                    clinic_name TEXT NOT NULL,
                    doctor_name TEXT NOT NULL,
                    specialty TEXT NOT NULL,
                    room_no TEXT NOT NULL,
                    slot_id TEXT NOT NULL,
                    slot_time TEXT NOT NULL,
                    slot_date TEXT NOT NULL,
                    dossier_id TEXT NOT NULL,
                    dossier_path TEXT DEFAULT '',
                    escrow_status TEXT NOT NULL,
                    booking_status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    qr_hash TEXT DEFAULT ''
                )
                """
            )

            # 3. Escrow table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS escrow (
                    ticket_id TEXT PRIMARY KEY,
                    patient_address TEXT NOT NULL,
                    amount_fet REAL NOT NULL,
                    lock_tx TEXT,
                    refund_tx TEXT,
                    status TEXT NOT NULL,
                    qr_token TEXT,
                    created_at TEXT NOT NULL,
                    locked_at TEXT,
                    refunded_at TEXT,
                    FOREIGN KEY (ticket_id) REFERENCES appointments(ticket_id) ON DELETE CASCADE
                )
                """
            )

            # Migrations for existing appointments tables
            cursor.execute("PRAGMA table_info(appointments)")
            existing_cols = {col[1] for col in cursor.fetchall()}
            if "dossier_path" not in existing_cols:
                cursor.execute("ALTER TABLE appointments ADD COLUMN dossier_path TEXT DEFAULT ''")
            if "slot_date" not in existing_cols:
                cursor.execute("ALTER TABLE appointments ADD COLUMN slot_date TEXT DEFAULT ''")
            if "qr_hash" not in existing_cols:
                cursor.execute("ALTER TABLE appointments ADD COLUMN qr_hash TEXT DEFAULT ''")

            conn.commit()

    def _ensure_slots_for_date(self, slot_date: str) -> None:
        """Seed per-date slots into SQLite slots table if not yet present."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM slots WHERE slot_date = ?", (slot_date,))
            count = cursor.fetchone()[0]
            if count > 0:
                return

            clinic_name = self.roster_data.get(
                "clinic_name", "अलवर सामुदायिक स्वास्थ्य केंद्र (Alwar CHC)"
            )
            specialties = self.roster_data.get("specialties", {})
            for spec_key, doc in specialties.items():
                for s in doc.get("slots", []):
                    cursor.execute(
                        """
                        INSERT OR IGNORE INTO slots (
                            slot_id, slot_date, slot_time, specialty_key,
                            doctor_name, room_no, clinic_name, capacity, booked_count
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                        """,
                        (
                            s["slot_id"],
                            slot_date,
                            s["time"],
                            spec_key,
                            doc["doctor_name"],
                            doc["room_no"],
                            clinic_name,
                            int(s.get("capacity", 5)),
                        ),
                    )
            conn.commit()

    def reset_slot(self, slot_id: str, slot_date: str | None = None) -> None:
        """Reset booked_count to 0 for a given slot (for testing and administrative reset)."""
        target_date = slot_date or (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        self._ensure_slots_for_date(target_date)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE slots SET booked_count = 0 WHERE slot_id = ? AND slot_date = ?",
                (slot_id, target_date),
            )
            today_str = datetime.date.today().isoformat()
            cursor.execute(
                "UPDATE slots SET booked_count = 0 WHERE slot_id = ? AND slot_date = ?",
                (slot_id, today_str),
            )
            conn.commit()

    def match_doctor_for_specialty(self, target_specialty: str) -> dict[str, Any]:
        """Match the recommended specialty to an available CHC doctor profile."""
        _, spec_key = map_specialty(target_specialty)
        specialties = self.roster_data.get("specialties", {})
        if spec_key in specialties:
            return specialties[spec_key]
        return specialties.get("general", {})

    def get_available_slots(self, specialty: str, slot_date: str | None = None) -> dict[str, Any]:
        """Fetch available slots for the given clinical specialty on a specific date (default tomorrow)."""
        spec_enum, spec_key = map_specialty(specialty)
        if not slot_date:
            slot_date = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        self._ensure_slots_for_date(slot_date)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM slots
                WHERE slot_date = ? AND specialty_key = ?
                ORDER BY slot_id ASC
                """,
                (slot_date, spec_key),
            )
            rows = cursor.fetchall()
            note = None
            if not rows:
                # If specialty not directly available at CHC, route to General Medicine with transparent note
                spec_enum, spec_key = Specialty.GENERAL_MEDICINE, "general"
                cursor.execute(
                    """
                    SELECT * FROM slots
                    WHERE slot_date = ? AND specialty_key = ?
                    ORDER BY slot_id ASC
                    """,
                    (slot_date, spec_key),
                )
                rows = cursor.fetchall()
                note = f"Specialty '{specialty}' not directly staffed today; routed to General Medicine OPD."

            doc_name = rows[0]["doctor_name"] if rows else "Dr. Rajesh Meena"
            clinic_name = rows[0]["clinic_name"] if rows else "Alwar CHC"
            room_no = rows[0]["room_no"] if rows else "Room 2"

            slots = []
            for r in rows:
                rem = max(0, r["capacity"] - r["booked_count"])
                slots.append(
                    {
                        "slot_id": r["slot_id"],
                        "time": r["slot_time"],
                        "slot_date": slot_date,
                        "capacity": r["capacity"],
                        "booked_count": r["booked_count"],
                        "remaining_capacity": rem,
                    }
                )

            return {
                "clinic_name": clinic_name,
                "doctor_name": doc_name,
                "specialty": spec_enum.value,
                "room_no": room_no,
                "slots": slots,
                "slot_date": slot_date,
                "routing_note": note,
            }

    def book_appointment(
        self,
        slot_id: str,
        patient_id: str,
        patient_name: str,
        dossier_id: str,
        slot_date: str | None = None,
    ) -> dict[str, Any]:
        """
        Record a confirmed appointment booking in SQLite with atomic capacity check.
        Raises ValueError with:
          - 'SLOT_NOT_FOUND' if slot_id is invalid
          - 'SLOT_FULL' if slot capacity is reached
        """
        if not slot_date:
            slot_date = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        self._ensure_slots_for_date(slot_date)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA foreign_keys = ON;")

            # 1. Verify slot exists
            cursor.execute(
                "SELECT * FROM slots WHERE slot_id = ? AND slot_date = ?",
                (slot_id, slot_date),
            )
            slot_row = cursor.fetchone()
            if not slot_row:
                raise ValueError(
                    f"SLOT_NOT_FOUND: Slot '{slot_id}' not found for date '{slot_date}'."
                )

            # 2. Atomic capacity decrement
            cursor.execute(
                """
                UPDATE slots
                SET booked_count = booked_count + 1
                WHERE slot_id = ? AND slot_date = ? AND booked_count < capacity
                """,
                (slot_id, slot_date),
            )
            if cursor.rowcount == 0:
                cursor.execute(
                    "SELECT capacity, booked_count FROM slots WHERE slot_id = ? AND slot_date = ?",
                    (slot_id, slot_date),
                )
                cap, booked = cursor.fetchone()
                raise ValueError(
                    f"SLOT_FULL: Slot '{slot_id}' is full for date '{slot_date}' (capacity: {cap}, booked: {booked})."
                )

            # 3. Create appointment and escrow records in transaction
            ticket_id = f"CR-ALW-{uuid.uuid4().hex[:6].upper()}"
            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            qr_payload = (
                f"CAREROUTE:{ticket_id}:{slot_row[6]}:{slot_row[5]}"  # clinic_name, room_no
            )

            cursor.execute(
                """
                INSERT INTO appointments (
                    ticket_id, patient_id, patient_name, clinic_name,
                    doctor_name, specialty, room_no, slot_id, slot_time,
                    slot_date, dossier_id, escrow_status, booking_status, created_at, qr_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticket_id,
                    patient_id,
                    patient_name,
                    slot_row[6],
                    slot_row[4],
                    slot_row[3],
                    slot_row[5],
                    slot_id,
                    slot_row[2],
                    slot_date,
                    dossier_id,
                    "LOCKED",
                    "CONFIRMED",
                    now_iso,
                    qr_payload,
                ),
            )

            cursor.execute(
                """
                INSERT INTO escrow (
                    ticket_id, patient_address, amount_fet, lock_tx,
                    refund_tx, status, qr_token, created_at, locked_at, refunded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticket_id,
                    patient_id,
                    Config.ESCROW_DEPOSIT_FET,
                    f"sim_tx_{Config.ESCROW_DEPOSIT_FET}fet_{uuid.uuid4().hex[:12]}",
                    None,
                    "LOCKED",
                    qr_payload,
                    now_iso,
                    now_iso,
                    None,
                ),
            )
            conn.commit()

            return {
                "ticket_id": ticket_id,
                "patient_id": patient_id,
                "patient_name": patient_name,
                "doctor_name": slot_row[4],
                "clinic_name": slot_row[6],
                "room_no": slot_row[5],
                "slot_time": slot_row[2],
                "slot_date": slot_date,
                "dossier_id": dossier_id,
                "qr_payload": qr_payload,
                "status": "CONFIRMED",
            }

    def update_dossier_path(self, ticket_id: str, dossier_path: str) -> None:
        """Record the persisted dossier file path for a confirmed booking."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE appointments SET dossier_path = ? WHERE ticket_id = ?",
                (dossier_path, ticket_id),
            )
            conn.commit()

    def get_booking(self, ticket_id: str) -> dict[str, Any] | None:
        """Retrieve booking record by ticket ID."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM appointments WHERE ticket_id = ?", (ticket_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
        return None

    def create_escrow_deposit(
        self,
        ticket_id: str,
        patient_address: str,
        amount_fet: float = 0.5,
        qr_token: str | None = None,
        status: str = "PENDING",
    ) -> dict[str, Any]:
        """Create a pending or locked escrow deposit record."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        lock_tx = f"sim_tx_{amount_fet}fet_{uuid.uuid4().hex[:12]}" if status == "LOCKED" else None
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO escrow (
                    ticket_id, patient_address, amount_fet, lock_tx,
                    refund_tx, status, qr_token, created_at, locked_at, refunded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticket_id,
                    patient_address,
                    amount_fet,
                    lock_tx,
                    None,
                    status,
                    qr_token,
                    now_iso,
                    now_iso if status == "LOCKED" else None,
                    None,
                ),
            )
            conn.commit()
        return self.get_escrow(ticket_id)

    def lock_escrow_deposit(self, ticket_id: str, lock_tx: str) -> bool:
        """Atomic lock transition on escrow record."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE escrow
                SET status = 'LOCKED', lock_tx = ?, locked_at = ?
                WHERE ticket_id = ? AND status = 'PENDING'
                """,
                (lock_tx, now_iso, ticket_id),
            )
            updated = cursor.rowcount > 0
            if updated:
                cursor.execute(
                    "UPDATE appointments SET escrow_status = 'LOCKED', booking_status = 'CONFIRMED' WHERE ticket_id = ?",
                    (ticket_id,),
                )
            conn.commit()
            return updated

    def release_escrow_refund(self, ticket_id: str, refund_tx: str) -> bool:
        """Atomic refund transition on escrow record."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE escrow
                SET status = 'REFUNDED', refund_tx = ?, refunded_at = ?
                WHERE ticket_id = ? AND status = 'LOCKED'
                """,
                (refund_tx, now_iso, ticket_id),
            )
            updated = cursor.rowcount > 0
            if updated:
                cursor.execute(
                    "UPDATE appointments SET escrow_status = 'REFUNDED', booking_status = 'CHECKED_IN' WHERE ticket_id = ?",
                    (ticket_id,),
                )
            conn.commit()
            return updated

    def get_escrow(self, ticket_id: str) -> dict[str, Any] | None:
        """Retrieve escrow record by ticket ID."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM escrow WHERE ticket_id = ?", (ticket_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
        return None

    def cancel_escrow(self, ticket_id: str, reason: str = "expired") -> bool:
        """Atomic cancellation of pending escrow deposit."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE escrow
                SET status = 'CANCELLED'
                WHERE ticket_id = ? AND status = 'PENDING'
                """,
                (ticket_id,),
            )
            updated = cursor.rowcount > 0
            if updated:
                cursor.execute(
                    "UPDATE appointments SET escrow_status = 'CANCELLED', booking_status = 'CANCELLED' WHERE ticket_id = ?",
                    (ticket_id,),
                )
            conn.commit()
            return updated

    def mark_checked_in(self, ticket_id: str) -> bool:
        """Mark booking as checked in upon clinic desk QR verification."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE appointments
                SET booking_status = 'CHECKED_IN', escrow_status = 'REFUNDED'
                WHERE ticket_id = ?
                """,
                (ticket_id,),
            )
            conn.commit()
            return cursor.rowcount > 0
