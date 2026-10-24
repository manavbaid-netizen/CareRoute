"""
Unit and integration tests for conversational intent handling in CareRoute.
Verifies that greetings, bot capability inquiries, gratitude/farewells, and off-topic queries
are handled intelligently without disturbing clinical triage pipelines.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.dispatcher import _process_user_text, classify_conversational_intent


def test_classify_greetings():
    """Verify various forms of greetings produce a warm introductory response."""
    for text in ["hi", "hello", "good morning", "good evening", "namaste ji", "नमस्ते", "राधे राधे", "ram ram"]:
        resp = classify_conversational_intent(text)
        assert resp is not None, f"Failed for '{text}'"
        assert "केयररूट (CareRoute)" in resp
        assert "डिजिटल स्वास्थ्य सहायक" in resp


def test_classify_capabilities_and_help():
    """Verify identity and capabilities questions explain CareRoute's features."""
    for text in ["who are you", "what can you do", "help me", "aap kaun ho", "tum kaun ho", "kya kar sakte ho"]:
        resp = classify_conversational_intent(text)
        assert resp is not None, f"Failed for '{text}'"
        assert "केयररूट (CareRoute) परिचय एवं सुविधाएं" in resp
        assert "लक्षणों का क्लिनिकल आकलन" in resp
        assert "ओपीडी स्लॉट" in resp


def test_classify_gratitude_and_farewell():
    """Verify thanks and goodbyes produce polite caring sign-offs."""
    for text in ["thank you", "thanks", "dhanyawad", "shukriya", "bye", "goodbye", "alvida"]:
        resp = classify_conversational_intent(text)
        assert resp is not None, f"Failed for '{text}'"
        assert "आपका बहुत-बहुत धन्यवाद" in resp
        assert "स्वस्थ रहें, सुरक्षित रहें" in resp


def test_classify_off_topic_queries():
    """Verify off-topic non-medical queries receive a polite clinical boundary redirect."""
    off_topics = [
        "tell me a joke",
        "chutkula sunao",
        "what is the weather today",
        "aaj barish hogi kya",
        "cricket score kya chal raha hai",
        "who is the prime minister",
        "write python code for sorting",
        "bitcoin price today",
        "recipe for biryani",
    ]
    for text in off_topics:
        resp = classify_conversational_intent(text)
        assert resp is not None, f"Failed for '{text}'"
        assert "केवल स्वास्थ्य एवं ओपीडी परामर्श" in resp or "CareRoute Health Assistant" in resp


def test_clinical_symptoms_not_intercepted():
    """Verify genuine medical complaints are NEVER intercepted as off-topic or greetings."""
    medical_queries = [
        "mujhe 3 din se tez bukhar aur khansi hai",
        "chhati me tez dard ho raha hai",
        "pet me dard aur ulti ho rahi hai",
        "dawai ka naam batao",
        "skin rash with severe itching",
        "sar dard aur chakkar aa rahe hain",
    ]
    for text in medical_queries:
        resp = classify_conversational_intent(text)
        assert resp is None, f"Medical query '{text}' was incorrectly intercepted as non-medical!"


@pytest.mark.anyio
async def test_off_topic_message_dispatch():
    """Verify _process_user_text dispatches off-topic explanation without entering triage."""
    mock_ctx = MagicMock()
    mock_ctx.send = AsyncMock()
    mock_ctx.logger = MagicMock()

    user = "agent1q_test_offtopic_user"
    session = {
        "user_address": user,
        "state": "STATE_IDLE",
        "patient_id": "P-OFFTOPIC",
        "patient_name": "Test User",
    }

    await _process_user_text(mock_ctx, user, session, "tell me a funny joke")

    assert mock_ctx.send.call_count == 1
    sent_text = mock_ctx.send.call_args[0][1].content[0].text
    assert "केवल स्वास्थ्य एवं ओपीडी परामर्श" in sent_text
    # State should remain IDLE (not transition to TRIAGE)
    assert session["state"] == "STATE_IDLE"
