"""
Tests for Phase 7: Emergency Detection & Red-Flag Safety Tripwires.
Validates 100% accuracy on critical positives from data/redflag_test_cases.json,
robust negation handling, and category-specific reason generation.
"""

import json
from pathlib import Path

from services.safety import SafetyService
from services.vlm_service import VLMService

TEST_CASES_PATH = Path(__file__).resolve().parent.parent / "data" / "redflag_test_cases.json"


def load_test_cases():
    with open(TEST_CASES_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_redflag_corpus_minimum_count():
    """Verify test corpus contains at least 60 labelled test cases."""
    cases = load_test_cases()
    assert len(cases) >= 60, f"Expected >= 60 test cases, found {len(cases)}"


def test_finding_7_exact_sentence_detected():
    """Verify the exact sentence from main.py / finding 7 fires an emergency."""
    exact_text = "सीने में बहुत तेज दर्द हो रहा है और सांस लेने में भारी तकलीफ है"
    is_em, reasons, _hits = SafetyService.scan_for_emergencies(exact_text)
    assert is_em is True
    assert len(reasons) >= 1
    # Check that reasons are specific, not generic
    for r in reasons:
        assert "Critical red flag symptoms detected" not in r
        assert "सीने" in r or "श्वसन" in r or "Chest" in r or "Respiratory" in r


def test_finding_7_all_previously_missed_phrases():
    """
    Verify every phrase specifically called out in Finding 7 triggers an emergency:
    - 'सीने में दर्द'
    - Hinglish: 'seene mein dard', 'saans nahi aa rahi'
    - 'बलगम में खून'
    - seizures
    - suicidal statements
    - snake bite
    - pregnancy bleeding
    """
    phrases = [
        ("सीने में दर्द", "cardiac_chest_pain"),
        ("seene mein dard", "cardiac_chest_pain"),
        ("saans nahi aa rahi", "respiratory_distress"),
        ("बलगम में खून", "active_hemorrhage_hemoptysis"),
        ("patient is having seizures and convulsions", "seizures_convulsions"),
        ("I feel suicidal and want to end my life", "suicidal_ideation"),
        ("खेत में सांप ने काट लिया है", "snake_or_animal_bite"),
        ("heavy pregnancy bleeding", "obstetric_emergency"),
    ]

    for text, expected_cat in phrases:
        is_em, reasons, hits = SafetyService.scan_for_emergencies(text)
        assert is_em is True, f"Failed to detect emergency for: '{text}'"
        assert len(reasons) >= 1
        matched_cats = [h["category"] for h in hits]
        assert expected_cat in matched_cats, (
            f"Expected {expected_cat} in {matched_cats} for '{text}'"
        )


def test_finding_7_negation_no_false_positives():
    """
    Verify finding 7 false positive fix: 'no chest pain', 'सीने में दर्द नहीं है', etc.
    must NOT trigger an emergency.
    """
    negated_cases = [
        "no chest pain, just a mild sprain",
        "सीने में दर्द नहीं है",
        "छाती में कोई दर्द नहीं है",
        "seene mein dard nahi hai",
        "denies chest pain and denies breathlessness",
        "patient without chest pain, reports mild rash",
        "khoon ki ulti nahi hui hai",
        "saap nahi kata hai",
        "मरीज को कोई दौरा नहीं पड़ा",
    ]

    for text in negated_cases:
        is_em, reasons, _hits = SafetyService.scan_for_emergencies(text)
        assert is_em is False, (
            f"False positive triggered for negated phrase: '{text}', reasons: {reasons}"
        )


def test_full_corpus_100_percent_critical_positives():
    """
    Evaluate all test cases in data/redflag_test_cases.json:
    Critical positives MUST achieve 100% recall.
    """
    cases = load_test_cases()
    false_negatives = []
    false_positives = []

    for case in cases:
        text = case["text"]
        expected = case["expected_emergency"]
        is_em, reasons, _hits = SafetyService.scan_for_emergencies(text)

        if expected and not is_em:
            false_negatives.append((case["id"], text, case.get("category")))
        elif not expected and is_em:
            false_positives.append((case["id"], text, reasons))

    assert len(false_negatives) == 0, f"Critical emergencies missed: {false_negatives}"
    assert len(false_positives) == 0, f"False positives detected: {false_positives}"


def test_vlm_service_uses_safetyservice():
    """Verify VLMService.scan_safety_tripwires properly uses SafetyService."""
    vlm = VLMService()
    is_em, reasons = vlm.scan_safety_tripwires("सीने में बहुत तेज दर्द हो रहा है और सांस लेने में भारी तकलीफ है")
    assert is_em is True
    assert len(reasons) >= 1

    # Negation
    is_em_neg, _ = vlm.scan_safety_tripwires("no chest pain")
    assert is_em_neg is False


def test_tele_manas_helpline_in_suicidal_response():
    """Verify Tele-MANAS helpline 14416 is provided in suicidal crisis guidance."""
    is_em, reasons, hits = SafetyService.scan_for_emergencies(
        "I want to kill myself, feeling suicidal"
    )
    assert is_em is True
    response = SafetyService.build_emergency_directive_response(reasons, hits)
    assert "14416" in response
    assert "Tele-MANAS" in response or "टेली-मानस" in response
