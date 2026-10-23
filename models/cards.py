from __future__ import annotations

from typing import List, Dict, Any, Optional


def card_to_markdown(card: Dict[str, Any]) -> str:
    """
    Render an ASI interactive card dictionary into clean, accessible Markdown
    for text-based ACP clients or fallback display.
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
        if "highlight" in sec:
            lines.append(f"👉 **{sec['highlight']}**")
        if "subtitle" in sec:
            lines.append(f"_{sec['subtitle']}_")
        if "content" in sec:
            lines.append(sec["content"])
        if "items" in sec:
            for item in sec["items"]:
                lines.append(f"• {item}")
        if "facts" in sec:
            for fact in sec["facts"]:
                lines.append(f"• **{fact['label']}:** {fact['value']}")
        if "qr_payload" in sec:
            lines.append(f"\n🔐 **चेक-इन टोकन (Check-in Token):** `{sec['qr_payload']}`")
        lines.append("")

    if actions:
        lines.append("**चयन करने के लिए विकल्प संख्या या टेक्स्ट भेजें:**")
        for idx, act in enumerate(actions, 1):
            label = act.get("label", "")
            lines.append(f"[{idx}] {label}")

    return "\n".join(lines).strip()


def make_triage_detail_card(
    urgency: str,
    specialty_hi: str,
    specialty_en: str,
    pre_visit_advice: str,
    differentials: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Build an ASI Interactive Card presenting the patient triage result.
    Allows the user to view clinical assessment and proceed to OPD slot booking.
    """
    is_urgent = "High" in urgency or "Critical" in urgency or "Emergency" in urgency
    theme_color = "#EF4444" if is_urgent else ("#F59E0B" if "Moderate" in urgency else "#10B981")
    badge_label = "प्राथमिकता (Priority)" if "Moderate" in urgency else ("अति आवश्यक (Urgent)" if is_urgent else "सामान्य (Routine)")

    differentials_list = differentials or ["Clinical assessment pending physical exam"]

    return {
        "card_type": "triage_detail",
        "version": "1.0",
        "theme": {
            "primary_color": theme_color,
            "badge_bg": "#FEF3C7" if "Moderate" in urgency else ("#FEE2E2" if is_urgent else "#D1FAE5"),
            "badge_text": theme_color,
        },
        "header": {
            "title": "केयररूट प्रारंभिक क्लिनिकल ट्राइएज (CareRoute Triage)",
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
                "title": "ओपीडी परामर्श पूर्व सलाह (Pre-Visit Advice)",
                "content": pre_visit_advice,
            },
        ],
        "actions": [
            {
                "type": "button",
                "action_id": "ACTION_VIEW_SLOTS",
                "label": "📅 उपलब्ध CHC डॉक्टर स्लॉट देखें (View Available Slots)",
                "style": "primary",
                "payload": {
                    "action": "view_slots",
                    "specialty": specialty_en,
                },
            },
            {
                "type": "button",
                "action_id": "ACTION_RESTART",
                "label": "🔄 नया लक्षण जोड़ें (Add More Symptoms)",
                "style": "secondary",
                "payload": {"action": "add_symptom"},
            },
        ],
    }


def make_slot_picker_card(
    clinic_name: str,
    doctor_name: str,
    specialty: str,
    room_no: str,
    available_slots: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Build an ASI Interactive Card displaying CHC doctor appointment slots.
    Each slot is an interactive selection button.
    """
    slot_actions = []
    for idx, slot in enumerate(available_slots, 1):
        slot_actions.append(
            {
                "type": "button",
                "action_id": f"SELECT_SLOT_{slot['slot_id']}",
                "label": f"🕒 {slot['time']} (कमरा: {room_no})",
                "style": "primary" if slot.get("capacity", 1) > 0 else "disabled",
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

    return {
        "card_type": "slot_picker",
        "version": "1.0",
        "theme": {
            "primary_color": "#2563EB",
            "badge_bg": "#DBEAFE",
            "badge_text": "#1E40AF",
        },
        "header": {
            "title": f"🏥 सामुदायिक स्वास्थ्य केंद्र (CHC) {clinic_name}",
            "badge": "ओपीडी बुकिंग (OPD Booking)",
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


def make_booking_receipt_card(
    ticket_id: str,
    patient_name: str,
    doctor_name: str,
    clinic_name: str,
    room_no: str,
    slot_time: str,
    deposit_fet: float = 0.5,
    qr_data: str = "",
) -> Dict[str, Any]:
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

    return {
        "card_type": "booking_receipt",
        "version": "1.0",
        "theme": {
            "primary_color": "#059669",
            "badge_bg": "#D1FAE5",
            "badge_text": "#065F46",
        },
        "header": {
            "title": "✅ ओपीडी परामर्श पर्ची (OPD Confirmed Ticket)",
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
                "content": f"🔒 {deposit_fet} FET जमा लॉक किया गया है। ओपीडी रिसेप्शन / रूम {room_no} पर क्यूआर स्कैन करने पर तुरंत रिफंड मिलेगा।",
            },
            {
                "title": "चेक-इन डिजिटल टोकन (Scan QR Code at Clinic Desk)",
                "qr_payload": payload_str,
                "qr_visual": qr_ascii_preview,
            },
        ],
        "actions": [
            {
                "type": "button",
                "action_id": "ACTION_SIMULATE_CHECKIN",
                "label": "📲 अस्पताल चेक-इन सिमुलेट करें (Simulate Desk Check-in)",
                "style": "primary",
                "payload": {
                    "action": "clinic_checkin",
                    "ticket_id": ticket_id,
                },
            },
            {
                "type": "button",
                "action_id": "ACTION_VIEW_DOSSIER",
                "label": "📋 डॉक्टर क्लिनिकल डोजियर देखें (View Doctor's Dossier)",
                "style": "secondary",
                "payload": {
                    "action": "view_dossier",
                    "ticket_id": ticket_id,
                },
            },
        ],
    }


def make_emergency_sos_card(reasons: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Build an ASI Interactive Card triggered immediately upon life-threatening red flags.
    Halts regular intake and prioritizes 108 emergency service dispatch.
    """
    detected_reasons = reasons or ["गंभीर लक्षण पाए गए (Critical red flag symptoms detected)"]

    return {
        "card_type": "emergency_sos",
        "version": "1.0",
        "theme": {
            "primary_color": "#DC2626",
            "badge_bg": "#FEE2E2",
            "badge_text": "#991B1B",
        },
        "header": {
            "title": "🚨 आपातकालीन चेतावनी (CRITICAL EMERGENCY ALERT)",
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
                "label": "📞 108 एम्बुलेंस डायल करें (Call 108 Ambulance)",
                "style": "danger",
                "url": "tel:108",
                "payload": {"action": "emergency_call", "number": "108"},
            },
            {
                "type": "button",
                "action_id": "ACTION_FIND_ER",
                "label": "📍 निकटतम आपातकालीन अस्पताल खोजें (Find Nearest ER)",
                "style": "secondary",
                "payload": {"action": "find_emergency_center"},
            },
        ],
    }
