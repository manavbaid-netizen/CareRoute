"""
Targeted tests for stability updates:
1. Resilient parsing of markdown-fenced and conversational JSON responses in LLMClient.
2. Fast fallback to local clinic roster when OpenStreetMap Overpass request times out.
3. Escalated triage classification for acute cough with respiratory distress and negation safety.
"""

import json
import time
from unittest.mock import patch

import requests

from models.clinical_schemas import ClinicalDossier, TriageUrgency
from services.geo_service import GeoService
from services.llm_client import LLMClient, extract_clean_json
from services.safety import SafetyService
from services.vlm_service import VLMService
from services.vlm_service import extract_clean_json as vlm_extract_clean_json

# ==============================================================================
# 1. ROBUST LLM JSON STRIPPING TESTS
# ==============================================================================

SAMPLE_NESTED_PAYLOAD = {
    "subjective": {
        "chief_complaint_english": "Acute cough for 3 days with shortness of breath.",
        "history_of_present_illness": "Patient presents with acute productive cough and difficulty breathing.",
        "symptom_duration": "3 days",
        "associated_symptoms": ["Dyspnea"],
        "past_medical_history": [],
    },
    "objective": {
        "vitals_reported": {},
        "visual_photo_findings": [],
        "ocr_prescriptions": [],
        "clinical_signs_summary": "Urgent triage vitals required.",
    },
    "assessment": {
        "triage_urgency": "High (Urgent Same-Day / तत्काल परामर्श)",
        "differential_diagnoses": ["1. Acute Community-Acquired Pneumonia", "2. Acute Bronchitis"],
        "recommended_specialty": "General Medicine",
        "recommended_specialty_hindi": "सामान्य चिकित्सा (General Medicine)",
        "clinical_rationale": "High-acuity respiratory markers require same-day assessment.",
    },
    "plan": {
        "suggested_investigations": ["Pulse Oximetry", "Chest X-Ray"],
        "interim_patient_advice_hindi": "तुरंत अस्पताल जाएं।",
        "interim_patient_advice_english": "Visit CHC immediately.",
        "red_flag_warnings": ["Severe cyanosis"],
    },
    "hindi_summary": "कृपया आज ही सीएचसी डॉक्टर को दिखाएं।",
}


def test_extract_clean_json_pure_and_fenced():
    """Verify extract_clean_json handles pure JSON, ```json fences, and bare ``` fences."""
    raw_json_str = json.dumps(SAMPLE_NESTED_PAYLOAD)

    # Pure JSON
    res1 = extract_clean_json(raw_json_str)
    assert res1["assessment"]["triage_urgency"] == "High (Urgent Same-Day / तत्काल परामर्श)"

    # Markdown json fence
    res2 = extract_clean_json(f"```json\n{raw_json_str}\n```")
    assert res2["subjective"]["symptom_duration"] == "3 days"

    # Bare fence
    res3 = extract_clean_json(f"```\n{raw_json_str}\n```")
    assert len(res3["assessment"]["differential_diagnoses"]) == 2

    # Exported via vlm_service as well
    res4 = vlm_extract_clean_json(f"```json\n{raw_json_str}\n```")
    assert res4["hindi_summary"] == "कृपया आज ही सीएचसी डॉक्टर को दिखाएं।"


def test_extract_clean_json_with_conversational_text():
    """Verify resilient extraction when LLM appends conversational text before and after JSON."""
    raw_json_str = json.dumps(SAMPLE_NESTED_PAYLOAD)
    noisy_response = (
        "Hello Doctor, I have reviewed the patient's Hindi narrative and generated the clinical dossier:\n\n"
        f"```json\n{raw_json_str}\n```\n\n"
        "Please note that the patient should consult a physician immediately."
    )

    parsed = extract_clean_json(noisy_response)
    assert isinstance(parsed, dict)
    assert parsed["assessment"]["recommended_specialty"] == "General Medicine"
    assert parsed["plan"]["suggested_investigations"] == ["Pulse Oximetry", "Chest X-Ray"]


def test_llm_client_resilient_parsing_of_fenced_response():
    """Verify LLMClient._parse_and_validate_json succeeds with markdown fences and conversational noise."""
    client = LLMClient()
    raw_json_str = json.dumps(SAMPLE_NESTED_PAYLOAD)
    noisy_llm_output = (
        f"Certainly! Here is the SOAP dossier:\n```json\n{raw_json_str}\n```\nHope this is helpful!"
    )

    dossier, summary = client._parse_and_validate_json(
        raw_text=noisy_llm_output,
        engine_name="ASI1 (asi1-mini)",
        session_id="test_resilience_sess",
        patient_id="PAT_RESILIENT",
        patient_name="Mohan",
        text_transcript="मुझे 3 दिन से खांसी है",
        has_vision=False,
    )

    assert dossier is not None
    assert isinstance(dossier, ClinicalDossier)
    assert dossier.assessment.triage_urgency == TriageUrgency.HIGH
    assert dossier.assessment.recommended_specialty == "General Medicine"
    assert "कृपया आज ही सीएचसी" in summary


# ==============================================================================
# 2. STRICT OVERPASS API TIMEOUT & FALLBACK TESTS
# ==============================================================================


def test_geo_service_fast_fallback_on_timeout(tmp_path):
    """Verify GeoService fails fast and returns local fallback clinic records on network timeout."""
    geo = GeoService(cache_dir=tmp_path, request_timeout=2.5)

    start_time = time.time()
    # Mock requests.post to simulate immediate timeout exception
    with patch(
        "requests.post", side_effect=requests.Timeout("Overpass gateway timeout after 2.5s")
    ):
        chcs = geo.find_nearest_chc(latitude=27.5530, longitude=76.6346, max_results=3)
    elapsed = time.time() - start_time

    # Must fail fast without hanging
    assert elapsed < 1.0, f"Fallback took too long: {elapsed:.2f}s"
    assert len(chcs) == 3
    # First record should be Alwar CHC from verified directory
    assert "Alwar" in chcs[0]["name"]
    assert chcs[0]["distance_km"] < 1.0
    assert chcs[0]["emergency_helpline"] == "108"
    assert chcs[0]["source"] == "verified_offline_directory"


def test_geo_service_fast_fallback_on_request_exception(tmp_path):
    """Verify GeoService returns verified local clinic records when Overpass returns HTTP error."""
    geo = GeoService(cache_dir=tmp_path, request_timeout=2.5)

    with patch("requests.post", side_effect=requests.RequestException("HTTP 429 Rate Limited")):
        chcs = geo.find_nearest_chc(latitude=27.5530, longitude=76.6346, max_results=2)

    assert len(chcs) == 2
    assert chcs[0]["id"] == "chc_alwar_main"
    assert chcs[0]["source"] == "verified_offline_directory"


# ==============================================================================
# 3. ACUTE HIGH-ACUITY RESPIRATORY SAFETY CHECK TESTS
# ==============================================================================


def test_acute_respiratory_risk_detection_hindi():
    """Verify cough + breathlessness trips acute high-acuity respiratory risk."""
    text = "नमस्ते डॉक्टर, मुझे 3 दिन से खांसी है और बहुत तेज सांस फूल रही है।"
    risk = SafetyService.check_acute_respiratory_risk(text)

    assert risk["is_acute_respiratory_risk"] is True
    assert risk["has_cough"] is True
    assert risk["has_breathlessness"] is True
    assert "सांस फूलना" in risk["markers_detected"][0]
    assert "तीव्र श्वसन मूल्यांकन" in risk["guidance_hi"]


def test_acute_respiratory_risk_detection_high_fever():
    """Verify acute cough + high fever (>102°F) trips acute respiratory risk."""
    text = "दो दिन से बलगम वाली खांसी है और 103 डिग्री तेज़ बुखार आ रहा है।"
    risk = SafetyService.check_acute_respiratory_risk(text)

    assert risk["is_acute_respiratory_risk"] is True
    assert risk["has_cough"] is True
    assert risk["has_high_fever"] is True
    assert "तेज़ बुखार" in risk["markers_detected"][0]


def test_acute_respiratory_risk_negation_no_false_positive():
    """Verify negation (सांस नहीं फूल रही) does NOT trigger high-acuity respiratory escalation."""
    text = "मुझे 3 दिन से खांसी और हल्का सिरदर्द है, लेकिन सांस नहीं फूल रही है और तेज़ बुखार नहीं है।"
    risk = SafetyService.check_acute_respiratory_risk(text)

    assert risk["has_cough"] is True
    assert risk["has_breathlessness"] is False
    assert risk["has_high_fever"] is False
    assert risk["is_acute_respiratory_risk"] is False


def test_vlm_escalates_acute_cough_with_breathlessness():
    """Verify VLMService escalates acute cough with breathlessness to High urgency under General Medicine."""
    vlm = VLMService()
    text = "मुझे 4 दिन से खांसी हो रही है और सांस लेने में दिक्कत और दम घुट रहा है।"

    dossier, summary, is_em, _ = vlm.analyze_case(
        session_id="test_resp_escalate",
        patient_id="PAT_RESP_01",
        patient_name="Kavita",
        text_transcript=text,
    )

    # Urgent clinical priority (Urgent Same-Day)
    assert dossier.assessment.triage_urgency in (TriageUrgency.HIGH, TriageUrgency.EMERGENCY)
    assert any(
        "Pneumonia" in d or "Respiratory" in d for d in dossier.assessment.differential_diagnoses
    )
    # Zero vitals fabrication preserved
    assert dossier.objective.vitals_reported == {}
    assert "तीव्र श्वसन" in summary or "आपातकालीन" in summary


def test_vlm_routine_cough_without_distress_remains_low_urgency():
    """Verify acute mild cough without breathlessness or fever remains routine General Medicine (Low)."""
    vlm = VLMService()
    # 2 days of mild cough without fever, without breathlessness
    text = "मुझे 2 दिन से हल्की खांसी है, सांस बिल्कुल ठीक है और कोई बुखार नहीं है।"

    dossier, summary, is_em, _ = vlm.analyze_case(
        session_id="test_mild_cough",
        patient_id="PAT_MILD",
        patient_name="Sunil",
        text_transcript=text,
    )

    assert not is_em
    assert dossier.assessment.triage_urgency == TriageUrgency.LOW
    assert dossier.assessment.recommended_specialty == "General Medicine"
    assert "Tuberculosis" not in dossier.assessment.differential_diagnoses[0]
