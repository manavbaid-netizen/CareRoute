"""
Phase 5 Tests: ASI1 LLM Core Reasoning Engine & Multi-Tier Fallback Validation.
Verifies:
1. Valid JSON from ASI:One/OpenAI-compatible endpoint parses into valid ClinicalDossier with provenance.
2. Malformed JSON triggers 1 error-correction retry and succeeds if retry returns valid JSON.
3. Persistent malformed JSON gracefully falls back to deterministic clinical engine without crashing.
4. Network timeout (APITimeoutError / TimeoutError) triggers graceful fallback without unhandled exception.
5. 401 AuthenticationError triggers graceful fallback without crashing.
6. Vision handling: honestly states image could not be analyzed; never fabricates visual findings.
7. Provenance footer is strictly set ('ASI1 (model_name)' or 'deterministic_fallback').
"""

import json
from unittest.mock import MagicMock, patch
import pytest
from openai import APITimeoutError, AuthenticationError

from services.llm_client import LLMClient, CLINICAL_DISCLAIMER_EN, CLINICAL_DISCLAIMER_HI, HONEST_VISION_NOTE_HI
from models.clinical_schemas import ClinicalDossier, TriageUrgency
from services.vlm_service import VLMService


SAMPLE_VALID_LLM_JSON = json.dumps({
    "subjective": {
        "chief_complaint_english": "Patient reports pain in both knees while walking for 1 month.",
        "history_of_present_illness": "Insidious onset of bilateral knee pain exacerbated by weight-bearing.",
        "symptom_duration": "1 month",
        "associated_symptoms": ["Joint stiffness in morning"],
        "past_medical_history": [],
    },
    "objective": {
        "vitals_reported": {},
        "visual_photo_findings": [],
        "ocr_prescriptions": [],
        "clinical_signs_summary": "Chronic joint pain without systemic signs.",
    },
    "assessment": {
        "triage_urgency": "Low (Routine OPD / नियमित ओपीडी)",
        "differential_diagnoses": [
            "1. Primary Osteoarthritis (Bilateral knees)",
            "2. Patellofemoral Pain Syndrome",
            "3. Tendinitis / Overuse strain",
        ],
        "recommended_specialty": "Orthopedics & Joint Care",
        "recommended_specialty_hindi": "हड्डी एवं जोड़ रोग विशेषज्ञ",
        "clinical_rationale": "Age-related chronic knee pain exacerbated by walking suggests degenerative joint change.",
    },
    "plan": {
        "suggested_investigations": [
            "X-Ray Bilateral Knees (AP and Lateral weight-bearing views)",
            "Serum Uric Acid and ESR",
        ],
        "interim_patient_advice_hindi": "सीढ़ियां चढ़ने से बचें और घुटनों पर अत्यधिक दबाव न डालें। ओपीडी में डॉक्टर से परामर्श लें।",
        "interim_patient_advice_english": "Avoid heavy weight-bearing and high-impact activities. Consult CHC orthopedics OPD.",
        "red_flag_warnings": ["Sudden hot red swelling or fever"],
    },
    "hindi_summary": "आपके घुटनों के दर्द के आधार पर हमने सीएचसी के **हड्डी एवं जोड़ रोग विशेषज्ञ** हेतु सारांश तैयार किया है।",
})


@pytest.fixture
def mock_fallback_engine():
    return VLMService()


def test_llm_valid_json_parsing(mock_fallback_engine):
    """Assert valid JSON output from ASI:One parses into ClinicalDossier with proper provenance."""
    client = LLMClient(fallback_engine=mock_fallback_engine)
    mock_openai = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = SAMPLE_VALID_LLM_JSON
    mock_openai.chat.completions.create.return_value = MagicMock(choices=[mock_choice])
    client.asi1_client = mock_openai

    with patch("config.Config.USE_MOCK_VLM", False):
        dossier, summary, is_em, reasons = client.generate_clinical_dossier(
            session_id="test_asi1_valid",
            patient_id="PAT_01",
            patient_name="Mohan Lal",
            text_transcript="एक महीने से चलते समय दोनों घुटनों में दर्द होता है",
        )

    assert isinstance(dossier, ClinicalDossier)
    assert not is_em
    assert dossier.assessment.recommended_specialty == "Orthopedics & Joint Care"
    assert dossier.assessment.triage_urgency == TriageUrgency.LOW
    assert dossier.engine.startswith("ASI1")
    assert CLINICAL_DISCLAIMER_EN in dossier.disclaimer
    assert CLINICAL_DISCLAIMER_HI in summary
    assert dossier.objective.vitals_reported == {}
    assert dossier.subjective.past_medical_history == []


def test_llm_fence_stripping_and_clean_json(mock_fallback_engine):
    """Assert markdown fences like ```json ... ``` are cleanly stripped before parsing."""
    fenced_json = f"```json\n{SAMPLE_VALID_LLM_JSON}\n```"
    client = LLMClient(fallback_engine=mock_fallback_engine)
    mock_openai = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = fenced_json
    mock_openai.chat.completions.create.return_value = MagicMock(choices=[mock_choice])
    client.asi1_client = mock_openai

    with patch("config.Config.USE_MOCK_VLM", False):
        dossier, summary, is_em, _ = client.generate_clinical_dossier(
            session_id="test_fence",
            patient_id="PAT_02",
            patient_name="Sita Devi",
            text_transcript="घुटने में दर्द है",
        )

    assert dossier is not None
    assert dossier.assessment.recommended_specialty == "Orthopedics & Joint Care"


def test_llm_malformed_json_retry_success(mock_fallback_engine):
    """Assert malformed JSON triggers 1 error-correction retry and succeeds if retry returns valid JSON."""
    client = LLMClient(fallback_engine=mock_fallback_engine)
    mock_openai = MagicMock()

    # First call returns broken JSON, second call (retry) returns valid JSON
    choice_bad = MagicMock()
    choice_bad.message.content = "{ broken json: true "
    choice_good = MagicMock()
    choice_good.message.content = SAMPLE_VALID_LLM_JSON

    mock_openai.chat.completions.create.side_effect = [
        MagicMock(choices=[choice_bad]),
        MagicMock(choices=[choice_good]),
    ]
    client.asi1_client = mock_openai

    with patch("config.Config.USE_MOCK_VLM", False):
        dossier, summary, is_em, _ = client.generate_clinical_dossier(
            session_id="test_retry",
            patient_id="PAT_03",
            patient_name="Ram",
            text_transcript="घुटने में दर्द है",
        )

    assert mock_openai.chat.completions.create.call_count == 2
    assert dossier is not None
    assert dossier.engine.startswith("ASI1")


def test_llm_malformed_json_persistent_fallback(mock_fallback_engine):
    """Assert repeated malformed JSON smoothly falls back to deterministic engine without crashing."""
    client = LLMClient(fallback_engine=mock_fallback_engine)
    mock_openai = MagicMock()

    # Both initial and retry return invalid text
    choice_bad = MagicMock()
    choice_bad.message.content = "I am an AI, I cannot output JSON."
    mock_openai.chat.completions.create.return_value = MagicMock(choices=[choice_bad])
    client.asi1_client = mock_openai

    with patch("config.Config.USE_MOCK_VLM", False):
        dossier, summary, is_em, _ = client.generate_clinical_dossier(
            session_id="test_bad_fallback",
            patient_id="PAT_04",
            patient_name="Ram",
            text_transcript="मुझे हल्का बुखार है",
        )

    # Must fall back gracefully to deterministic engine
    assert dossier is not None
    assert dossier.engine == "deterministic_fallback"
    assert dossier.assessment.recommended_specialty == "General Medicine"


def test_llm_timeout_triggers_graceful_fallback(mock_fallback_engine):
    """Assert network timeout (APITimeoutError) falls back to deterministic engine without exception."""
    client = LLMClient(fallback_engine=mock_fallback_engine)
    mock_openai = MagicMock()
    mock_openai.chat.completions.create.side_effect = APITimeoutError(request=MagicMock())
    client.asi1_client = mock_openai

    with patch("config.Config.USE_MOCK_VLM", False):
        dossier, summary, is_em, _ = client.generate_clinical_dossier(
            session_id="test_timeout",
            patient_id="PAT_05",
            patient_name="Geeta",
            text_transcript="मुझे दो दिन से सिर दर्द है",
        )

    assert dossier is not None
    assert dossier.engine == "deterministic_fallback"
    assert not is_em
    assert dossier.assessment.recommended_specialty == "General Medicine"


def test_llm_401_authentication_error_fallback(mock_fallback_engine):
    """Assert 401 AuthenticationError from invalid API key triggers graceful fallback."""
    client = LLMClient(fallback_engine=mock_fallback_engine)
    mock_openai = MagicMock()
    mock_openai.chat.completions.create.side_effect = AuthenticationError(
        message="Invalid API Key",
        response=MagicMock(status_code=401),
        body=None,
    )
    client.asi1_client = mock_openai

    with patch("config.Config.USE_MOCK_VLM", False):
        dossier, summary, is_em, _ = client.generate_clinical_dossier(
            session_id="test_401",
            patient_id="PAT_06",
            patient_name="Sunita",
            text_transcript="पैर में मोच आ गई है",
        )

    assert dossier is not None
    assert dossier.engine == "deterministic_fallback"
    assert dossier.assessment.recommended_specialty == "General Medicine"


def test_honest_vision_handling(mock_fallback_engine):
    """Assert when an image is provided without a vision model, the system honestly states analysis is unavailable."""
    client = LLMClient(fallback_engine=mock_fallback_engine)

    dossier, summary, is_em, _ = client.generate_clinical_dossier(
        session_id="test_vision_honest",
        patient_id="PAT_VIS",
        patient_name="Anoop",
        text_transcript="त्वचा पर दाने हैं",
        image_data="base64fakeimagebytes",
        image_type="lesion_photo",
    )

    assert dossier is not None
    assert HONEST_VISION_NOTE_HI in summary
    assert "फोटो का विश्लेषण अभी उपलब्ध नहीं है" in summary
    # Assert no fake morphological findings were hallucinated
    assert dossier.objective.visual_photo_findings == []
