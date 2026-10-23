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
        """Create bookings table if not existing."""
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
                    escrow_status TEXT NOT NULL,
                    booking_status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
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
                    dossier_id, escrow_status, booking_status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
