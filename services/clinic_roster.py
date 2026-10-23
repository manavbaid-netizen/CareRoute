from __future__ import annotations

import sqlite3
import datetime
import uuid
from typing import List, Dict, Any, Optional
from config import Config


class ClinicRosterService:
    """
    Manages rural Community Health Center (CHC) doctors, available OPD slots,
    and appointment registrations with SQLite persistence.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = str(db_path or Config.DB_PATH)
        self._init_db()

    def _init_db(self) -> None:
        """Create bookings and escrow tables if not existing."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
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
                    dossier_id TEXT NOT NULL,
                    dossier_path TEXT DEFAULT '',
                    escrow_status TEXT NOT NULL,
                    booking_status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            # Create unified escrow table
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
                    refunded_at TEXT
                )
                """
            )
            # Automatic schema migration for existing SQLite databases
            cursor.execute("PRAGMA table_info(appointments)")
            existing_cols = {col[1] for col in cursor.fetchall()}
            if "dossier_path" not in existing_cols:
                cursor.execute("ALTER TABLE appointments ADD COLUMN dossier_path TEXT DEFAULT ''")
            if "slot_date" not in existing_cols:
                cursor.execute("ALTER TABLE appointments ADD COLUMN slot_date TEXT DEFAULT ''")
            if "qr_hash" not in existing_cols:
                cursor.execute("ALTER TABLE appointments ADD COLUMN qr_hash TEXT DEFAULT ''")
            conn.commit()

    # Pre-configured Community Health Center Doctors (Alwar District CHC)
    DOCTORS = {
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
    }

    def match_doctor_for_specialty(self, target_specialty: str) -> Dict[str, Any]:
        """Match the recommended specialty to an available CHC doctor."""
        low = target_specialty.lower()
        if "pulmon" in low or "chest" in low or "respirat" in low or "tb" in low:
            return self.DOCTORS["pulmonology"]
        elif "derm" in low or "skin" in low or "fungal" in low:
            return self.DOCTORS["dermatology"]
        else:
            return self.DOCTORS["general"]

    def get_available_slots(self, specialty: str) -> Dict[str, Any]:
        """Fetch available slots for the given clinical specialty."""
        doc_profile = self.match_doctor_for_specialty(specialty)
        return {
            "clinic_name": doc_profile["clinic_name"],
            "doctor_name": doc_profile["doctor_name"],
            "specialty": doc_profile["specialty"],
            "room_no": doc_profile["room_no"],
            "slots": doc_profile["slots"],
        }

    def book_appointment(
        self,
        slot_id: str,
        patient_id: str,
        patient_name: str,
        dossier_id: str,
    ) -> Dict[str, Any]:
        """
        Record a confirmed appointment booking in the SQLite registry.
        """
        # Find slot details
        selected_slot = None
        matched_doc = None
        for key, doc in self.DOCTORS.items():
            for s in doc["slots"]:
                if s["slot_id"] == slot_id:
                    selected_slot = s
                    matched_doc = doc
                    break
            if selected_slot:
                break

        # Fallback if slot ID not found
        if not selected_slot:
            matched_doc = self.DOCTORS["pulmonology"]
            selected_slot = matched_doc["slots"][0]

        ticket_id = f"CR-ALW-{uuid.uuid4().hex[:6].upper()}"
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        qr_payload = f"CAREROUTE:{ticket_id}:{matched_doc['clinic_name']}:{matched_doc['room_no']}"

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO appointments (
                    ticket_id, patient_id, patient_name, clinic_name,
                    doctor_name, specialty, room_no, slot_id, slot_time,
                    dossier_id, escrow_status, booking_status, created_at, qr_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticket_id,
                    patient_id,
                    patient_name,
                    matched_doc["clinic_name"],
                    matched_doc["doctor_name"],
                    matched_doc["specialty"],
                    matched_doc["room_no"],
                    selected_slot["slot_id"],
                    selected_slot["time"],
                    dossier_id,
                    "LOCKED",
                    "CONFIRMED",
                    now_iso,
                    qr_payload,
                ),
            )
            # Create corresponding escrow record
            cursor.execute(
                """
                INSERT OR REPLACE INTO escrow (
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
            "doctor_name": matched_doc["doctor_name"],
            "clinic_name": matched_doc["clinic_name"],
            "room_no": matched_doc["room_no"],
            "slot_time": selected_slot["time"],
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

    def get_booking(self, ticket_id: str) -> Optional[Dict[str, Any]]:
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
        qr_token: Optional[str] = None,
        status: str = "PENDING",
    ) -> Dict[str, Any]:
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

    def get_escrow(self, ticket_id: str) -> Optional[Dict[str, Any]]:
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
            return cursor.rowcount > 0
