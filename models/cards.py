from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field
from uagents_core.contrib.protocols.chat import (
    ChatMessage,
    MetadataContent,
    TextContent,
)

from config import Config

# ------------------------------------------------------------------------------
# Pydantic v2 Models for ASI:One Interactive Cards
# ------------------------------------------------------------------------------


class CardAction(BaseModel):
    """Interactive button or CTA element on an ASI:One card."""

    type: str = "button"
    action_id: str
    label: str
    style: str = "primary"  # "primary", "secondary", "danger", "disabled"
    payload: dict[str, Any] = Field(default_factory=dict)
    url: str | None = None


class CardHeader(BaseModel):
    """Title and badge banner for an interactive card."""

    title: str
    badge: str | None = None


class CardFact(BaseModel):
    """Key-value datum for receipt or summary sections."""

    label: str
    value: str


class CardSection(BaseModel):
    """Content section within an interactive card."""

    title: str | None = None
    highlight: str | None = None
    subtitle: str | None = None
    content: str | None = None
    items: list[str] | None = None
    facts: list[dict[str, str]] | None = None
    qr_payload: str | None = None
    qr_visual: str | None = None


class CardTheme(BaseModel):
    """Visual branding theme for ASI:One card drawer."""

    primary_color: str = "#2563EB"
    badge_bg: str | None = None
    badge_text: str | None = None


class InteractiveCard(BaseModel):
    """Official ASI:One Interactive Card schema."""

    card_type: str
    version: str = "1.0"
    theme: CardTheme = Field(default_factory=CardTheme)
    header: CardHeader
    sections: list[CardSection] = Field(default_factory=list)
    actions: list[CardAction] = Field(default_factory=list)


# ------------------------------------------------------------------------------
# Plain-Text & Accessible Markdown Fallback Renderer
# ------------------------------------------------------------------------------


def card_to_markdown(card: dict[str, Any]) -> str:
    """
    Render an ASI interactive card dictionary into clean, accessible Markdown
    for text-based ACP clients or fallback display when cards are disabled.
    Provides clear numeric prompts ("Reply 1, 2 or 3") for mobile navigation.
    """
    header = card.get("header", {})
    title = header.get("title", "")
    badge = header.get("badge", "")
    sections = card.get("sections", [])
    actions = card.get("actions", [])

    lines = []
    if title:
        lines.append(f"### {title}")
    if badge:
        lines.append(f"**[{badge}]**\n")

    for sec in sections:
        sec_title = sec.get("title")
        if sec_title:
            lines.append(f"**{sec_title}**")
        if "highlight" in sec and sec["highlight"]:
            lines.append(f"👉 **{sec['highlight']}**")
        if "subtitle" in sec and sec["subtitle"]:
            lines.append(f"_{sec['subtitle']}_")
        if "content" in sec and sec["content"]:
            lines.append(sec["content"])
        if "items" in sec and sec["items"]:
            for item in sec["items"]:
                lines.append(f"• {item}")
        if "facts" in sec and sec["facts"]:
            for fact in sec["facts"]:
                lines.append(f"• **{fact['label']}:** {fact['value']}")
        if "qr_payload" in sec and sec["qr_payload"]:
            lines.append(f"\n🔐 **चेक-इन टोकन (Check-in Token):** `{sec['qr_payload']}`")
        lines.append("")

    if actions:
        lines.append("───────────────────────────────────")
        lines.append("📲 **चयन करने के लिए विकल्प संख्या (1, 2, 3...) भेजें:**")
        for idx, act in enumerate(actions, 1):
            label = act.get("label", "")
            lines.append(f"  **[{idx}]** {label}")

    return "\n".join(lines).strip()


# ------------------------------------------------------------------------------
# Action Parsing & Fallback Extraction
# ------------------------------------------------------------------------------


def parse_card_action(user_text: str) -> dict[str, Any] | None:
    """
    Parse an incoming client message to determine if it is an interactive
    card action payload (JSON from a button tap) or a numeric text selection.
    """
    cleaned = user_text.strip()
    if not cleaned:
        return None

    # 1. Native JSON action payload from button click
    if cleaned.startswith("{") and cleaned.endswith("}"):
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict) and "action" in parsed:
                return parsed
        except Exception:
            pass

    # 2. Check for numeric choice (e.g. "1", "2", "#1")
    num_match = re.match(r"^#?(\d+)$", cleaned)
    if num_match:
        return {"action": "numeric_choice", "choice": int(num_match.group(1))}

    return None


# ------------------------------------------------------------------------------
# ACP Message Builder with Native Interactive Card & Text Fallback
# ------------------------------------------------------------------------------


def create_card_chat(
    text: str,
    card: dict[str, Any],
    use_interactive: bool | None = None,
    end_session: bool = False,
) -> ChatMessage:
    """
    Construct an official ACP ChatMessage delivering an interactive card.

    If use_interactive is True (defaulting to Config.USE_INTERACTIVE_CARDS):
      - Emits TextContent containing the readable text & Markdown fallback.
      - Emits MetadataContent containing the structured card payload so
        ASI:One clients render the native visual drawer.
    If use_interactive is False:
      - Emits only TextContent containing readable Markdown.
    """
    from datetime import datetime, timezone
    from uuid import uuid4

    from uagents_core.contrib.protocols.chat import EndSessionContent

    if use_interactive is None:
        use_interactive = getattr(Config, "USE_INTERACTIVE_CARDS", True)

    markdown_view = card_to_markdown(card)
    full_text = f"{text.strip()}\n\n{markdown_view}".strip() if text else markdown_view

    contents = [TextContent(text=full_text, type="text")]

    if use_interactive:
        # Wrap card in MetadataContent for ASI:One native renderer
        card_metadata = {
            "card_kind": card.get("card_type", "card"),
            "card_payload": json.dumps(card, ensure_ascii=False),
            "card_version": str(card.get("version", "1.0")),
            "title": card.get("header", {}).get("title", ""),
        }
        contents.append(MetadataContent(metadata=card_metadata, type="metadata"))

    if end_session:
        contents.append(EndSessionContent())

    return ChatMessage(
        msg_id=uuid4(),
        timestamp=datetime.now(timezone.utc),
        content=contents,
    )


# ------------------------------------------------------------------------------
# Card Builders (Optimized with short mobile labels)
# ------------------------------------------------------------------------------


def make_triage_detail_card(
    urgency: str,
    specialty_hi: str,
    specialty_en: str,
    pre_visit_advice: str,
    differentials: list[str] | None = None,
) -> dict[str, Any]:
    """
    Build an ASI Interactive Card presenting the patient triage result.
    Allows the user to view clinical assessment and proceed to OPD slot booking.
    """
    is_urgent = "High" in urgency or "Critical" in urgency or "Emergency" in urgency
    theme_color = "#EF4444" if is_urgent else ("#F59E0B" if "Moderate" in urgency else "#10B981")
    badge_label = (
        "प्राथमिकता (Priority)"
        if "Moderate" in urgency
        else ("अति आवश्यक (Urgent)" if is_urgent else "सामान्य (Routine)")
    )

    differentials_list = differentials or ["Clinical assessment pending physical exam"]

    card_dict = {
        "card_type": "triage_detail",
        "version": "1.0",
        "theme": {
            "primary_color": theme_color,
            "badge_bg": "#FEF3C7"
            if "Moderate" in urgency
            else ("#FEE2E2" if is_urgent else "#D1FAE5"),
            "badge_text": theme_color,
        },
        "header": {
            "title": "केयररूट क्लिनिकल ट्राइएज (Triage Result)",
            "badge": f"{badge_label} • {urgency}",
        },
        "sections": [
            {
                "title": "अनुशंसित विशेषज्ञ (Recommended Specialty)",
                "highlight": f"{specialty_hi} ({specialty_en})",
            },
            {
                "title": "संभावित क्लिनिकल आकलन (Differential Triage)",
                "items": differentials_list[:3],
            },
            {
                "title": "ओपीडी पूर्व सलाह (Pre-Visit Advice)",
                "content": pre_visit_advice,
            },
        ],
        "actions": [
            {
                "type": "button",
                "action_id": "ACTION_VIEW_SLOTS",
                "label": "📅 स्लॉट देखें (View Slots)",
                "style": "primary",
                "payload": {
                    "action": "view_slots",
                    "specialty": specialty_en,
                },
            },
            {
                "type": "button",
                "action_id": "ACTION_RESTART",
                "label": "🔄 लक्षण जोड़ें (Add Symptoms)",
                "style": "secondary",
                "payload": {"action": "add_symptom"},
            },
        ],
    }

    # Validate against Pydantic schema
    InteractiveCard.model_validate(card_dict)
    return card_dict


def make_slot_picker_card(
    clinic_name: str,
    doctor_name: str,
    specialty: str,
    room_no: str,
    available_slots: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Build an ASI Interactive Card displaying CHC doctor appointment slots.
    Each slot button is formatted with concise, mobile-friendly touch labels.
    """
    slot_actions = []
    for idx, slot in enumerate(available_slots, 1):
        cap = slot.get("capacity", 5)
        rem = slot.get("remaining_capacity", cap)
        is_avail = rem > 0 if rem is not None else cap > 0
        status_tag = f"({rem} बचे)" if rem is not None else ""

        slot_actions.append(
            {
                "type": "button",
                "action_id": f"SELECT_SLOT_{slot['slot_id']}",
                "label": f"🕒 {slot['time']} {status_tag}".strip(),
                "style": "primary" if is_avail else "disabled",
                "payload": {
                    "action": "select_slot",
                    "slot_id": slot["slot_id"],
                    "slot_time": slot["time"],
                    "doctor_name": doctor_name,
                    "clinic_name": clinic_name,
                    "room_no": room_no,
                    "option_num": str(idx),
                },
            }
        )

    card_dict = {
        "card_type": "slot_picker",
        "version": "1.0",
        "theme": {
            "primary_color": "#2563EB",
            "badge_bg": "#DBEAFE",
            "badge_text": "#1E40AF",
        },
        "header": {
            "title": f"🏥 {clinic_name}",
            "badge": "ओपीडी स्लॉट चयन (Select Slot)",
        },
        "sections": [
            {
                "title": "परामर्शदाता चिकित्सक (Consulting Doctor)",
                "highlight": f"{doctor_name}",
                "subtitle": f"{specialty} • {room_no}",
            },
            {
                "title": "अमानत जमा सूचना (Deposit Notice)",
                "content": "नो-शो रोकने हेतु 0.5 FET टोकन एस्क्रो में सुरक्षित किया जाएगा। अस्पताल पहुंचकर क्यूआर स्कैन करते ही 100% रिफंड!",
            },
        ],
        "actions": slot_actions,
    }

    # Validate against Pydantic schema
    InteractiveCard.model_validate(card_dict)
    return card_dict


def make_booking_receipt_card(
    ticket_id: str,
    patient_name: str,
    doctor_name: str,
    clinic_name: str,
    room_no: str,
    slot_time: str,
    deposit_fet: float = 0.5,
    qr_data: str = "",
) -> dict[str, Any]:
    """
    Build an ASI Interactive Card confirming the patient's OPD appointment,
    providing the clinic check-in QR payload and anti-no-show escrow receipt.
    """
    payload_str = qr_data or f"CAREROUTE-CHECKIN:{ticket_id}:{clinic_name}:{room_no}"

    qr_ascii_preview = (
        "┌─────────────────┐\n"
        "│  ██ ███ ███ ██  │\n"
        "│  ██ █ █ █ █ ██  │\n"
        "│  ██ ███ ███ ██  │\n"
        "│     ███   █     │\n"
        "│  ██ █ █ ███ ██  │\n"
        "└─────────────────┘"
    )

    card_dict = {
        "card_type": "booking_receipt",
        "version": "1.0",
        "theme": {
            "primary_color": "#059669",
            "badge_bg": "#D1FAE5",
            "badge_text": "#065F46",
        },
        "header": {
            "title": "✅ ओपीडी परामर्श पर्ची (Confirmed Ticket)",
            "badge": f"टोकन #: {ticket_id}",
        },
        "sections": [
            {
                "title": "अपॉइंटमेंट विवरण (Appointment Details)",
                "facts": [
                    {"label": "मरीज (Patient)", "value": patient_name},
                    {"label": "डॉक्टर (Doctor)", "value": doctor_name},
                    {"label": "स्वास्थ्य केंद्र (Facility)", "value": clinic_name},
                    {"label": "कक्ष संख्या (Room No)", "value": room_no},
                    {"label": "समय (Time Slot)", "value": slot_time},
                ],
            },
            {
                "title": "एस्क्रो अमानत स्थिति (Escrow Deposit Status)",
                "content": f"🔒 {deposit_fet} FET जमा लॉक किया गया है। ओपीडी रिसेप्शन पर क्यूआर स्कैन करने पर तुरंत रिफंड मिलेगा।",
            },
            {
                "title": "चेक-इन डिजिटल टोकन (Scan QR at Clinic Desk)",
                "qr_payload": payload_str,
                "qr_visual": qr_ascii_preview,
            },
        ],
        "actions": [
            {
                "type": "button",
                "action_id": "ACTION_SIMULATE_CHECKIN",
                "label": "📲 अस्पताल चेक-इन (Check-in)",
                "style": "primary",
                "payload": {
                    "action": "clinic_checkin",
                    "ticket_id": ticket_id,
                    "qr_token": payload_str,
                },
            },
            {
                "type": "button",
                "action_id": "ACTION_VIEW_DOSSIER",
                "label": "📋 डोजियर देखें (View Dossier)",
                "style": "secondary",
                "payload": {
                    "action": "view_dossier",
                    "ticket_id": ticket_id,
                },
            },
        ],
    }

    # Validate against Pydantic schema
    InteractiveCard.model_validate(card_dict)
    return card_dict


def make_emergency_sos_card(reasons: list[str] | None = None) -> dict[str, Any]:
    """
    Build an ASI Interactive Card triggered immediately upon life-threatening red flags.
    Halts regular intake and prioritizes 108 emergency service dispatch.
    """
    detected_reasons = reasons or ["गंभीर लक्षण पाए गए (Critical red flag symptoms detected)"]

    card_dict = {
        "card_type": "emergency_sos",
        "version": "1.0",
        "theme": {
            "primary_color": "#DC2626",
            "badge_bg": "#FEE2E2",
            "badge_text": "#991B1B",
        },
        "header": {
            "title": "🚨 आपातकालीन चेतावनी (EMERGENCY ALERT)",
            "badge": "108 SOS तत्काल कॉल करें",
        },
        "sections": [
            {
                "title": "जीवन रक्षक चेतावनी (Emergency Tripwires Triggered)",
                "items": detected_reasons,
            },
            {
                "title": "तत्काल निर्देश (Immediate Action Required)",
                "content": (
                    "यह स्थिति नियमित ओपीडी के लिए सुरक्षित नहीं है। कृपया तुरंत 108 एम्बुलेंस बुलाएं "
                    "या नजदीकी सामुदायिक स्वास्थ्य केंद्र (CHC) / जिला अस्पताल के इमरजेंसी कक्ष में जाएं। "
                    "मरीज को अकेला न छोड़ें।"
                ),
            },
            {
                "title": "प्राथमिक चिकित्सा (First-Aid Precautions)",
                "content": "मरीज को आरामदायक स्थिति में बैठाएं। सांस लेने में कठिनाई होने पर सीधा बैठाएं। कोई ठोस भोजन न दें।",
            },
        ],
        "actions": [
            {
                "type": "button",
                "action_id": "ACTION_CALL_108",
                "label": "📞 108 डायल करें (Call 108)",
                "style": "danger",
                "url": "tel:108",
                "payload": {"action": "emergency_call", "number": "108"},
            },
            {
                "type": "button",
                "action_id": "ACTION_FIND_ER",
                "label": "📍 निकटतम ER खोजें (Find ER)",
                "style": "secondary",
                "payload": {"action": "find_emergency_center"},
            },
        ],
    }

    # Validate against Pydantic schema
    InteractiveCard.model_validate(card_dict)
    return card_dict
