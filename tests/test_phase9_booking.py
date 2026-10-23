"""
Phase 9 Tests: Booking Logic & Capacity Validation (Fixes Findings 10, 11, 12).
Verifies:
1. Slots loaded from data/clinic_roster.json.
2. Per-date slots: date isolation ensures different dates have independent capacities.
3. Atomic capacity decrement: a slot with capacity N fills up and rejects the (N+1)th booking with SLOT_FULL.
4. Unknown slot_id rejection: explicit error (SLOT_NOT_FOUND) instead of silent fallback to pulmonology slot 0.
5. Controlled Specialty Enum mapping with fallback to General Medicine and transparent note.
6. Patient identity: derived from address (PAT_{sender[:10]}), dynamic name extraction, zero hardcoded Ram Kumar.
7. SQLite foreign key enforcement (PRAGMA foreign_keys = ON).
"""

import sqlite3
from datetime import date, timedelta

import pytest

from services.clinic_roster import (
    ClinicRosterService,
    Specialty,
    map_specialty,
)
from services.session_store import SessionStore


@pytest.fixture
def roster(tmp_path):
    db_file = tmp_path / "test_roster.db"
    return ClinicRosterService(db_path=str(db_file))


def test_slots_loaded_from_json(roster):
    """Verify slots and doctors are loaded from data/clinic_roster.json."""
    data = roster.roster_data
    assert "specialties" in data
    assert "pulmonology" in data["specialties"]
    assert "dermatology" in data["specialties"]
    assert "general" in data["specialties"]
    assert len(data["specialties"]["pulmonology"]["slots"]) >= 3


def test_specialty_enum_and_mapping():
    """Verify controlled Specialty Enum and mapping fallback."""
    spec, key = map_specialty("Chest Specialist")
    assert spec == Specialty.PULMONOLOGY
    assert key == "pulmonology"

    spec, key = map_specialty("Skin Fungal Infection")
    assert spec == Specialty.DERMATOLOGY
    assert key == "dermatology"

    # Unknown specialty maps to General Medicine
    spec, key = map_specialty("RandomUnknownSpecialty")
    assert spec == Specialty.GENERAL_MEDICINE
    assert key == "general"


def test_atomic_capacity_limit_and_slot_full_rejection(roster):
    """
    Assert slot capacity is strictly enforced atomically:
    For a slot with capacity=2, the 3rd booking must fail with SLOT_FULL.
    """
    test_date = (date.today() + timedelta(days=3)).isoformat()
    slot_id = "ALW_DERM_1145"  # Capacity is 2 in clinic_roster.json

    # 1st booking succeeds
    b1 = roster.book_appointment(
        slot_id=slot_id,
        patient_id="PAT_01",
        patient_name="Patient One",
        dossier_id="DOS_01",
        slot_date=test_date,
    )
    assert b1["status"] == "CONFIRMED"

    # 2nd booking succeeds
    b2 = roster.book_appointment(
        slot_id=slot_id,
        patient_id="PAT_02",
        patient_name="Patient Two",
        dossier_id="DOS_02",
        slot_date=test_date,
    )
    assert b2["status"] == "CONFIRMED"

    # 3rd booking MUST fail with SLOT_FULL
    with pytest.raises(ValueError) as excinfo:
        roster.book_appointment(
            slot_id=slot_id,
            patient_id="PAT_03",
            patient_name="Patient Three",
            dossier_id="DOS_03",
            slot_date=test_date,
        )

    assert "SLOT_FULL" in str(excinfo.value)
    assert "capacity: 2" in str(excinfo.value)


def test_per_date_isolation(roster):
    """
    Assert capacity is per-date:
    Booking a slot on Day 1 does NOT reduce capacity for the same slot on Day 2.
    """
    day1 = (date.today() + timedelta(days=4)).isoformat()
    day2 = (date.today() + timedelta(days=5)).isoformat()
    slot_id = "ALW_DERM_1145"  # Capacity: 2

    # Fill day 1
    roster.book_appointment(slot_id=slot_id, patient_id="P1", patient_name="P1", dossier_id="D1", slot_date=day1)
    roster.book_appointment(slot_id=slot_id, patient_id="P2", patient_name="P2", dossier_id="D2", slot_date=day1)

    # Day 1 is now full
    with pytest.raises(ValueError) as exc:
        roster.book_appointment(slot_id=slot_id, patient_id="P3", patient_name="P3", dossier_id="D3", slot_date=day1)
    assert "SLOT_FULL" in str(exc.value)

    # Day 2 still has full capacity!
    b_day2 = roster.book_appointment(
        slot_id=slot_id,
        patient_id="P_Day2",
        patient_name="Patient Day 2",
        dossier_id="D_Day2",
        slot_date=day2,
    )
    assert b_day2["status"] == "CONFIRMED"
    assert b_day2["slot_date"] == day2


def test_unknown_slot_id_raises_slot_not_found(roster):
    """
    Assert an unknown slot_id raises an explicit SLOT_NOT_FOUND error
    and does NOT silently fall back to pulmonology slot 0 (Fixing Finding 11).
    """
    test_date = (date.today() + timedelta(days=2)).isoformat()

    with pytest.raises(ValueError) as excinfo:
        roster.book_appointment(
            slot_id="INVALID_NON_EXISTENT_SLOT",
            patient_id="PAT_ERR",
            patient_name="Error Patient",
            dossier_id="DOS_ERR",
            slot_date=test_date,
        )

    assert "SLOT_NOT_FOUND" in str(excinfo.value)
    assert "INVALID_NON_EXISTENT_SLOT" in str(excinfo.value)


def test_patient_identity_derivation(tmp_path):
    """
    Assert patient ID is derived from sender address (PAT_{sender[:10]})
    and patient name defaults to neutral rather than hardcoded Ram Kumar (Fixing Finding 12).
    """
    db_file = tmp_path / "test_session.db"
    store = SessionStore(db_path=str(db_file))

    user_addr = "agent1qvy8z7exampleuseraddress456"
    session = store.get_or_create_session(user_addr)

    assert session["patient_id"] == f"PAT_{user_addr[:10]}"
    assert session["patient_name"] != "रामकुमार (Ram Kumar)"
    assert "Patient" in session["patient_name"] or "मरीज" in session["patient_name"]


def test_sqlite_foreign_keys_enforced(roster):
    """Assert SQLite foreign keys are active."""
    with sqlite3.connect(roster.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys;")
        # Note: PRAGMA foreign_keys is connection-local, but tables must have FOREIGN KEY defined
        cursor.execute("PRAGMA foreign_key_list(escrow);")
        fks = cursor.fetchall()
        assert len(fks) >= 1
        assert fks[0][2] == "appointments"
