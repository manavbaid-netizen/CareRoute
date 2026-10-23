"""
Tests for Phase 4: Clinical Dossier persistence and end-to-end agent integration.
Verifies Pydantic v2 serialization/deserialization, data retention cleanup,
and file creation driven through agent message handlers.
"""

import os
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

from config import Config
from services.dossier_generator import DossierGeneratorService
from services.clinic_roster import ClinicRosterService
from models.clinical_schemas import (
    ClinicalDossier,
    SubjectiveSOAP,
    ObjectiveSOAP,
    AssessmentSOAP,
    PlanSOAP,
    TriageUrgency,
)
from models.chat_models import (
    TriageAnalysisRequest,
    BookingCommitRequest,
)
from agents.diagnostic_worker import handle_triage_request
from agents.logistics_worker import handle_booking_commit


@pytest.fixture
def dossier_service(tmp_path):
    return DossierGeneratorService(storage_dir=tmp_path)


@pytest.fixture
def sample_dossier():
    return ClinicalDossier(
        dossier_id="DOS-PHASE4-001",
        created_at="2026-10-24T10:00:00+00:00",
        patient_id="PAT-RAM-01",
        patient_name="रामकुमार (Ram Kumar)",
        subjective=SubjectiveSOAP(
            patient_chief_complaint_hindi="दो हफ्ते से खांसी और शाम को बुखार",
            chief_complaint_english="Productive cough with evening fever for 2 weeks",
            history_of_present_illness="Patient reports 14-day history of low-grade evening pyrexia and productive cough.",
            symptom_duration="14 days",
            associated_symptoms=["Evening fever", "Weight loss"],
            past_medical_history=["Denies diabetes or hypertension"],
        ),
        objective=ObjectiveSOAP(),
        assessment=AssessmentSOAP(
            triage_urgency=TriageUrgency.HIGH,
            recommended_specialty="Pulmonology / Chest Medicine",
            recommended_specialty_hindi="छाती एवं फेफड़ा रोग विशेषज्ञ",
            differential_diagnoses=["Pulmonary TB", "Subacute LRTI"],
            clinical_rationale="Features warrant evaluation for tuberculosis per NTEP criteria.",
        ),
        plan=PlanSOAP(
            suggested_investigations=["Sputum AFB smear x2", "Chest X-Ray PA"],
            interim_patient_advice_hindi="गुनगुना पानी पिएं। खांसते समय मुंह ढकें।",
            interim_patient_advice_english="Stay hydrated and wear a cloth mask when coughing.",
            red_flag_warnings=["Hemoptysis", "Severe breathlessness"],
        ),
        engine="ASI1 | safe_fallback",
    )


def test_dossier_pydantic_v2_roundtrip(dossier_service, sample_dossier):
    """Verify that model_dump and model_validate_json preserve all fields and enums."""
    paths = dossier_service.save_dossier(sample_dossier)
    assert Path(paths["json_path"]).exists()
    assert Path(paths["md_path"]).exists()

    loaded = dossier_service.load_dossier(sample_dossier.dossier_id)
    assert loaded is not None
    assert loaded.dossier_id == sample_dossier.dossier_id
    assert loaded.patient_name == sample_dossier.patient_name
    assert loaded.assessment.triage_urgency == TriageUrgency.HIGH
    assert loaded.assessment.recommended_specialty == sample_dossier.assessment.recommended_specialty
    assert loaded.engine == sample_dossier.engine


def test_dossier_retention_cleanup(tmp_path):
    """Verify cleanup_old_dossiers safely deletes files older than retention days."""
    service = DossierGeneratorService(storage_dir=tmp_path)

    # 1. Create an old file (> 35 days old)
    old_file = tmp_path / "old_dossier.json"
    old_file.write_text("{}", encoding="utf-8")
    old_mtime = time.time() - (35 * 86400)
    os.utime(old_file, (old_mtime, old_mtime))

    # 2. Create a fresh file (0 days old)
    fresh_file = tmp_path / "fresh_dossier.json"
    fresh_file.write_text("{}", encoding="utf-8")

    # Run cleanup with 30-day retention
    removed = service.cleanup_old_dossiers(days=30)
    assert removed == 1
    assert not old_file.exists()
    assert fresh_file.exists()


@pytest.mark.anyio
async def test_agent_driven_dossier_flow():
    """
    Assert that .md and .json files exist after an intake & booking driven
    through the AGENTS (DiagnosticWorker -> LogisticsWorker), not just direct service calls.
    """
    Config.ensure_directories()
    user_address = "agent1q_test_dossier_agent_flow"

    # Step 1: Drive intake through Diagnostic Worker
    diag_ctx = MagicMock()
    diag_ctx.send = AsyncMock()
    diag_ctx.logger = MagicMock()

    triage_req = TriageAnalysisRequest(
        session_id=user_address,
        patient_id="PAT-FLOW-01",
        patient_name="सोहन लाल (Sohan Lal)",
        text_transcript="मुझे दो हफ्ते से खांसी आ रही है और शाम को बुखार है",
        user_address=user_address,
    )

    await handle_triage_request(diag_ctx, "dispatcher_addr", triage_req)

    # Verify diagnostic worker replied with TriageAnalysisResponse
    assert diag_ctx.send.call_count == 1
    _, triage_resp = diag_ctx.send.call_args_list[0][0]
    real_dossier_id = triage_resp.dossier.dossier_id
    assert real_dossier_id.startswith("DOS")

    # Verify dossier files were created right after triage
    raw_json_path = Config.DOSSIERS_DIR / f"{real_dossier_id}.json"
    raw_md_path = Config.DOSSIERS_DIR / f"{real_dossier_id}_opd_slip.md"
    assert raw_json_path.exists(), f"Raw JSON missing: {raw_json_path}"
    assert raw_md_path.exists(), f"Raw MD missing: {raw_md_path}"

    # Step 2: Drive booking through Logistics Worker using REAL dossier_id
    logi_ctx = MagicMock()
    logi_ctx.send = AsyncMock()
    logi_ctx.logger = MagicMock()

    booking_req = BookingCommitRequest(
        session_id=user_address,
        patient_id="PAT-FLOW-01",
        patient_name="सोहन लाल (Sohan Lal)",
        slot_id="ALW_CHEST_1000",
        dossier_id=real_dossier_id,
        user_address=user_address,
    )

    await handle_booking_commit(logi_ctx, "dispatcher_addr", booking_req)

    # Verify logistics worker confirmed booking
    assert logi_ctx.send.call_count == 1
    _, booking_resp = logi_ctx.send.call_args_list[0][0]
    assert booking_resp.status == "CONFIRMED"
    ticket_id = booking_resp.ticket_id
    assert ticket_id.startswith("CR-ALW-")

    # Step 3: Assert ticket-indexed .json and .md files exist on disk
    ticket_json_path = Config.DOSSIERS_DIR / f"{ticket_id}.json"
    ticket_md_path = Config.DOSSIERS_DIR / f"{ticket_id}_opd_slip.md"
    assert ticket_json_path.exists(), f"Ticket JSON file missing: {ticket_json_path}"
    assert ticket_md_path.exists(), f"Ticket MD slip missing: {ticket_md_path}"

    # Verify DB entry records the actual path
    roster = ClinicRosterService()
    booking_record = roster.get_booking(ticket_id)
    assert booking_record is not None
    assert booking_record["dossier_id"] == real_dossier_id
    assert booking_record["dossier_path"] == str(ticket_md_path)


@pytest.mark.anyio
async def test_logistics_rejects_missing_dossier():
    """Verify logistics worker reports error status when called with nonexistent dossier_id."""
    logi_ctx = MagicMock()
    logi_ctx.send = AsyncMock()
    logi_ctx.logger = MagicMock()

    booking_req = BookingCommitRequest(
        session_id="agent1q_fake",
        patient_id="PAT-FAKE",
        patient_name="Fake Patient",
        slot_id="ALW_CHEST_1000",
        dossier_id="DOS-NONEXISTENT-9999",
    )

    await handle_booking_commit(logi_ctx, "dispatcher_addr", booking_req)
    assert logi_ctx.send.call_count == 1
    _, resp = logi_ctx.send.call_args_list[0][0]
    assert resp.status == "ERROR_MISSING_DOSSIER"
    assert resp.dossier_path is None
