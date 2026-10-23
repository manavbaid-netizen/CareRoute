"""
Tests for Phase 10: ASI:One Interactive Cards and Plain-Text Accessible Fallback.
Verifies Pydantic v2 card schema validation, MetadataContent ACP packaging,
clean plain-text markdown fallback ("Reply 1, 2 or 3"), and button action parsing.
"""

import json
import pytest
from uagents_core.contrib.protocols.chat import TextContent, MetadataContent, ChatMessage

from models.cards import (
    InteractiveCard,
    CardAction,
    CardHeader,
    CardSection,
    card_to_markdown,
    parse_card_action,
    create_card_chat,
    make_triage_detail_card,
    make_slot_picker_card,
    make_booking_receipt_card,
    make_emergency_sos_card,
)


def test_triage_detail_card_schema():
    """Verify triage detail card conforms to Pydantic v2 InteractiveCard schema."""
    card = make_triage_detail_card(
        urgency="High (Urgent)",
        specialty_hi="छाती एवं फेफड़ा रोग विशेषज्ञ",
        specialty_en="Pulmonology / Chest Medicine",
        pre_visit_advice="आराम करें और गुनगुना पानी पिएं।",
        differentials=["Pulmonary Tuberculosis", "Subacute Bronchitis"],
    )
    validated = InteractiveCard.model_validate(card)
    assert validated.card_type == "triage_detail"
    assert "छाती" in validated.sections[0].highlight
    assert len(validated.actions) >= 1
    assert validated.actions[0].action_id == "ACTION_VIEW_SLOTS"


def test_slot_picker_card_schema():
    """Verify slot picker card conforms to Pydantic v2 InteractiveCard schema."""
    slots = [
        {"slot_id": "S1", "time": "10:00 AM - 10:30 AM", "capacity": 5, "remaining_capacity": 3},
        {"slot_id": "S2", "time": "11:30 AM - 12:00 PM", "capacity": 4, "remaining_capacity": 0},
    ]
    card = make_slot_picker_card(
        clinic_name="अलवर CHC",
        doctor_name="Dr. Harish Sharma",
        specialty="Pulmonology",
        room_no="Room 4",
        available_slots=slots,
    )
    validated = InteractiveCard.model_validate(card)
    assert validated.card_type == "slot_picker"
    assert len(validated.actions) == 2
    assert validated.actions[0].style == "primary"
    assert validated.actions[1].style == "disabled"
    assert "S1" in validated.actions[0].action_id


def test_booking_receipt_card_schema():
    """Verify booking receipt card conforms to Pydantic v2 InteractiveCard schema."""
    card = make_booking_receipt_card(
        ticket_id="CR-ALW-9999",
        patient_name="मोहन लाल",
        doctor_name="Dr. Harish Sharma",
        clinic_name="अलवर सामुदायिक स्वास्थ्य केंद्र",
        room_no="कक्ष संख्या 4",
        slot_time="10:00 AM - 10:30 AM",
        deposit_fet=0.5,
        qr_data="CAREROUTE:CR-ALW-9999",
    )
    validated = InteractiveCard.model_validate(card)
    assert validated.card_type == "booking_receipt"
    assert "CR-ALW-9999" in validated.header.badge
    assert validated.actions[0].action_id == "ACTION_SIMULATE_CHECKIN"


def test_emergency_sos_card_schema():
    """Verify emergency SOS card conforms to Pydantic v2 InteractiveCard schema."""
    card = make_emergency_sos_card(reasons=["अचानक सीने में बहुत तेज दर्द (Severe acute chest pain)"])
    validated = InteractiveCard.model_validate(card)
    assert validated.card_type == "emergency_sos"
    assert "108" in validated.header.badge
    assert validated.theme.primary_color == "#DC2626"
    assert validated.actions[0].action_id == "ACTION_CALL_108"


def test_card_to_markdown_fallback_formatting():
    """Verify plain-text markdown fallback includes title, sections, and numbered choices."""
    slots = [
        {"slot_id": "S1", "time": "10:00 AM - 10:30 AM", "capacity": 5, "remaining_capacity": 3},
        {"slot_id": "S2", "time": "11:30 AM - 12:00 PM", "capacity": 4, "remaining_capacity": 2},
    ]
    card = make_slot_picker_card(
        clinic_name="अलवर CHC",
        doctor_name="Dr. Harish Sharma",
        specialty="Pulmonology",
        room_no="Room 4",
        available_slots=slots,
    )
    md = card_to_markdown(card)
    assert "### 🏥 अलवर CHC" in md
    assert "Dr. Harish Sharma" in md
    assert "चयन करने के लिए विकल्प संख्या" in md
    assert "[1]" in md
    assert "[2]" in md
    assert "10:00 AM" in md


def test_create_card_chat_with_interactive_enabled():
    """Verify create_card_chat emits both TextContent and MetadataContent when interactive is enabled."""
    card = make_emergency_sos_card(["सीने में तेज दर्द"])
    chat_msg = create_card_chat(text="तत्काल सहायता लें:", card=card, use_interactive=True)

    assert isinstance(chat_msg, ChatMessage)
    assert len(chat_msg.content) == 2

    # First block is accessible TextContent
    text_block = chat_msg.content[0]
    assert isinstance(text_block, TextContent)
    assert "तत्काल सहायता लें:" in text_block.text
    assert "108" in text_block.text

    # Second block is MetadataContent containing the card
    meta_block = chat_msg.content[1]
    assert isinstance(meta_block, MetadataContent)
    assert meta_block.metadata["card_kind"] == "emergency_sos"
    payload = json.loads(meta_block.metadata["card_payload"])
    assert payload["card_type"] == "emergency_sos"


def test_create_card_chat_with_interactive_disabled():
    """Verify create_card_chat emits ONLY TextContent when interactive cards are disabled."""
    card = make_emergency_sos_card(["सीने में तेज दर्द"])
    chat_msg = create_card_chat(text="तत्काल सहायता लें:", card=card, use_interactive=False)

    assert isinstance(chat_msg, ChatMessage)
    assert len(chat_msg.content) == 1
    assert isinstance(chat_msg.content[0], TextContent)
    # No MetadataContent present
    assert not any(isinstance(c, MetadataContent) for c in chat_msg.content)


def test_parse_card_action_native_json():
    """Verify parse_card_action extracts structured JSON payloads from button clicks."""
    payload = json.dumps({"action": "select_slot", "slot_id": "ALW_CHEST_1000", "option_num": "1"})
    parsed = parse_card_action(payload)
    assert parsed is not None
    assert parsed.get("action") == "select_slot"
    assert parsed.get("slot_id") == "ALW_CHEST_1000"


def test_parse_card_action_numeric_fallback():
    """Verify parse_card_action extracts numeric choice for plain text user responses."""
    assert parse_card_action("1") == {"action": "numeric_choice", "choice": 1}
    assert parse_card_action("2") == {"action": "numeric_choice", "choice": 2}
    assert parse_card_action("#3") == {"action": "numeric_choice", "choice": 3}
    assert parse_card_action("मुझे 1 नंबर चाहिए") is None  # Free text goes to NLP


def test_mobile_friendly_labels():
    """Verify action labels remain concise for mobile viewport constraints."""
    card = make_triage_detail_card(
        urgency="Moderate",
        specialty_hi="सामान्य चिकित्सा",
        specialty_en="General Medicine",
        pre_visit_advice="आराम करें",
    )
    for act in card["actions"]:
        # Touch targets should be readable without wrapping 3 lines
        assert len(act["label"]) <= 45
