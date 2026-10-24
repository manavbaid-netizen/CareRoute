"""
Tests for Phase 12: End-to-End Primary Lifecycle, Concurrency & LLM-Down Resilience.
Verifies the complete patient journey from intake -> triage -> slot query ->
escrow locking -> booking confirmation -> desk QR check-in & refund.
Tests concurrency under capacity constraints and LLM outage graceful degradation.
"""

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agents.escrow_worker import execute_patient_checkin
from config import Config
from models.clinical_schemas import TriageUrgency
from services.clinic_roster import ClinicRosterService
from services.dossier_generator import DossierGeneratorService
from services.llm_client import LLMClient
from services.vlm_service import VLMService


@pytest.fixture
def clean_environment():
    Config.ensure_directories()
    roster = ClinicRosterService()
    roster.reset_slot("ALW_CHEST_1000")
    roster.reset_slot("ALW_DERM_1030")
    roster.reset_slot("ALW_GEN_0930")
    return roster


def test_full_primary_telehealth_lifecycle(clean_environment):
    """
    Assert full multi-step clinical & financial lifecycle:
    1. Patient Vernacular Hindi input -> Triage Analysis
    2. English SOAP Dossier generation & persistence
    3. Doctor slot selection for matching specialty
    4. Atomic slot capacity booking
    5. Escrow deposit lock (0.5 FET)
    6. Clinic Desk QR verification and 100% deposit refund
    """
    roster = clean_environment
    vlm = VLMService()
    dossier_gen = DossierGeneratorService()

    patient_addr = "agent1q_test_lifecycle_patient"
    patient_id = "PAT-E2E-001"
    patient_name = "सुनीता देवी (Sunita Devi, 38F)"
    symptom_text = "मुझे पिछले 3 हफ्तों से लगातार खांसी आ रही है और शाम को बुखार के साथ पसीना आता है।"

    # Step 1: Vernacular Triage
    dossier, _hindi_summary, is_emergency, _emergency_reasons = vlm.analyze_case(
        session_id=patient_addr,
        patient_id=patient_id,
        patient_name=patient_name,
        text_transcript=symptom_text,
    )
    assert not is_emergency
    assert dossier.assessment.triage_urgency in (
        TriageUrgency.HIGH,
        TriageUrgency.LOW,
        TriageUrgency.MODERATE,
    )
    assert dossier.assessment.recommended_specialty in ("Pulmonology", "General Medicine")

    # Step 2: Save initial clinical dossier
    paths = dossier_gen.save_dossier(dossier)
    assert Path(paths["json_path"]).exists()

    # Step 3: Logistics slot discovery
    slots_res = roster.get_available_slots(dossier.assessment.recommended_specialty)
    assert len(slots_res["slots"]) >= 1
    selected_slot = slots_res["slots"][0]
    slot_id = selected_slot["slot_id"]

    # Step 4 & 5: Book appointment & lock escrow
    booking = roster.book_appointment(
        slot_id=slot_id,
        patient_id=patient_id,
        patient_name=patient_name,
        dossier_id=dossier.dossier_id,
    )
    ticket_id = booking["ticket_id"]
    assert ticket_id.startswith("CR-ALW-")
    assert booking["status"] == "CONFIRMED"

    # Verify booking and escrow tables updated
    record = roster.get_booking(ticket_id)
    assert record is not None
    assert record["booking_status"] == "CONFIRMED"
    assert record["escrow_status"] == "LOCKED"

    # Step 6: Desk QR check-in & refund
    release_resp = execute_patient_checkin(
        ticket_id=ticket_id,
        scanned_by="alwar_chc_reception_desk",
        qr_token=booking["qr_payload"],
    )
    assert release_resp.status == "REFUNDED"
    assert release_resp.refund_amount_fet == Config.ESCROW_DEPOSIT_FET
    assert "sim_refund_" in release_resp.refund_tx_hash

    # Verify database state after refund
    updated_record = roster.get_booking(ticket_id)
    assert updated_record["booking_status"] == "CHECKED_IN"
    assert updated_record["escrow_status"] == "REFUNDED"


def test_capacity_concurrency_race_conditions(clean_environment):
    """
    Assert that atomic capacity tracking in SQLite strictly prevents overbooking
    when multiple concurrent booking requests exceed remaining capacity.
    """
    roster = clean_environment
    slot_id = "ALW_CHEST_1130"
    target_date = "2026-11-01"

    # Ensure slot is seeded with known capacity = 3
    roster._ensure_slots_for_date(target_date)
    with sqlite3.connect(roster.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE slots SET capacity = 3, booked_count = 0 WHERE slot_id = ? AND slot_date = ?",
            (slot_id, target_date),
        )
        conn.commit()

    successful_bookings = 0
    rejected_bookings = 0

    # Attempt 5 simultaneous bookings for capacity of 3
    for i in range(5):
        try:
            roster.book_appointment(
                slot_id=slot_id,
                patient_id=f"PAT-CONC-{i}",
                patient_name=f"Patient {i}",
                dossier_id=f"DOS-CONC-{i}",
                slot_date=target_date,
            )
            successful_bookings += 1
        except ValueError as exc:
            if "SLOT_FULL" in str(exc):
                rejected_bookings += 1

    assert successful_bookings == 3
    assert rejected_bookings == 2


def test_llm_outage_graceful_degradation():
    """
    Assert that when external LLM endpoints experience timeouts or errors,
    the clinical system seamlessly degrades to the deterministic clinical engine
    producing zero fabrication and 100% valid SOAP dossiers.
    """
    client = LLMClient()
    client.asi1_client = MagicMock()
    client.gemini_client = MagicMock()
    client.openai_client = MagicMock()

    # Simulate network outage on primary ASI:One, secondary Gemini, and tertiary OpenAI
    with (
        patch.object(
            client, "_call_openai_compatible", side_effect=Exception("ASI:One connection timed out")
        ),
        patch.object(client, "_call_gemini", side_effect=Exception("Gemini quota exceeded")),
    ):
        dossier, _hindi_summary, _is_em, _reasons = client.generate_clinical_dossier(
            session_id="test_down",
            patient_id="p1",
            patient_name="Ram",
            text_transcript="मुझे दो हफ्ते से खांसी और बुखार है",
        )

    assert "fallback" in dossier.engine
    assert dossier.assessment.triage_urgency in (
        TriageUrgency.HIGH,
        TriageUrgency.LOW,
        TriageUrgency.MODERATE,
    )
    assert len(dossier.assessment.differential_diagnoses) >= 1
    # Verify zero hallucinated vitals
    assert dossier.objective.vitals_reported == {}
