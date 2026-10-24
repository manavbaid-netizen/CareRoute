"""
CareRoute (केयररूट) - Agentverse Cloud Hosted Agent (Blank Agent Edition).

Deploy this self-contained script directly on Agentverse.ai as a "Blank Agent":
 1. Go to https://agentverse.ai -> Agents -> "+ New Agent" -> "Blank Agent"
 2. Paste this entire file into the web editor.
 3. Click "Start" in the top right corner.
 4. Open your agent on ASI:One: https://asi1.ai/chat?agent=<YOUR_AGENT_ADDRESS>

Features included out of the box (Zero Local Dependencies):
 - Official Agent Chat Protocol (ACP) compliant.
 - Full Clinical Vernacular Triage (Hindi / Hinglish / English).
 - Emergency Red Flag detection & SOS alert (108 Ambulance).
 - Verified Alwar District CHC Hospital Locator.
 - OPD Doctor Slot Scheduling & Digital Token Generation.
 - Persistent session memory via Agentverse ctx.storage.
"""

from __future__ import annotations

import datetime
import logging
import math
import re
from typing import Any
from uuid import UUID, uuid4

from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    StartSessionContent,
    TextContent,
    chat_protocol_spec,
)

logger = logging.getLogger("CareRoute.CloudAgent")

# ==============================================================================
# 1. VERIFIED ALWAR DISTRICT CHC DIRECTORY
# ==============================================================================
VERIFIED_CHCS: list[dict[str, Any]] = [
    {
        "id": "chc_alwar_main",
        "name": "सामुदायिक स्वास्थ्य केंद्र एवं सामान्य चिकित्सालय, अलवर (Alwar CHC)",
        "latitude": 27.5530,
        "longitude": 76.6346,
        "address": "कंपनी बाग रोड, अलवर (Company Bagh Road, Alwar, Rajasthan 301001)",
        "phone": "+91-144-2332211",
        "emergency_helpline": "108",
        "opd_timings": "09:00 AM - 01:00 PM, 04:00 PM - 06:00 PM",
        "specialties": [
            "सामान्य चिकित्सा (General Medicine)",
            "छाती एवं फेफड़ा रोग (Pulmonology)",
            "त्वचा एवं चर्म रोग (Dermatology)",
            "शिशु रोग (Pediatrics)",
        ],
    },
    {
        "id": "chc_behror",
        "name": "सामुदायिक स्वास्थ्य केंद्र, बहरोड़ (Behror CHC)",
        "latitude": 27.8872,
        "longitude": 76.2806,
        "address": "NH-48, बस स्टैंड के पास, बहरोड़ (Behror, Alwar 301701)",
        "phone": "+91-1494-220015",
        "emergency_helpline": "108",
        "opd_timings": "09:00 AM - 01:00 PM",
        "specialties": [
            "सामान्य चिकित्सा (General Medicine)",
            "आपातकालीन सेवा (Trauma Care)",
            "शिशु रोग (Pediatrics)",
        ],
    },
    {
        "id": "chc_tijara",
        "name": "सामुदायिक स्वास्थ्य केंद्र, तिजारा (Tijara CHC)",
        "latitude": 27.9332,
        "longitude": 76.8524,
        "address": "रेवाड़ी-अलवर रोड, तिजारा (Tijara, Alwar 301411)",
        "phone": "+91-1469-222045",
        "emergency_helpline": "108",
        "opd_timings": "09:00 AM - 01:00 PM",
        "specialties": [
            "सामान्य चिकित्सा (General Medicine)",
            "श्वसन तंत्र एवं टीबी नियंत्रण (Chest / RNTCP)",
            "मातृ एवं शिशु स्वास्थ्य (MCH)",
        ],
    },
]

# ==============================================================================
# 2. OPD CLINIC ROSTER & APPOINTMENT DOCTORS
# ==============================================================================
DOCTORS_ROSTER: dict[str, dict[str, Any]] = {
    "General Medicine": {
        "doctor_name": "डॉ. हरीश शर्मा (Dr. Harish Sharma)",
        "specialty": "सामान्य चिकित्सा (General Medicine)",
        "room_no": "कक्ष संख्या 4",
        "clinic_name": "अलवर सामुदायिक स्वास्थ्य केंद्र (Alwar CHC)",
        "slots": [
            {"slot_id": "slot_gen_1", "time": "10:00 AM - 10:30 AM"},
            {"slot_id": "slot_gen_2", "time": "11:00 AM - 11:30 AM"},
            {"slot_id": "slot_gen_3", "time": "12:00 PM - 12:30 PM"},
        ],
    },
    "Pulmonology": {
        "doctor_name": "डॉ. सुनीता वर्मा (Dr. Sunita Verma)",
        "specialty": "छाती एवं श्वसन रोग (Pulmonology)",
        "room_no": "कक्ष संख्या 7",
        "clinic_name": "अलवर सामुदायिक स्वास्थ्य केंद्र (Alwar CHC)",
        "slots": [
            {"slot_id": "slot_pul_1", "time": "10:30 AM - 11:00 AM"},
            {"slot_id": "slot_pul_2", "time": "11:30 AM - 12:00 PM"},
        ],
    },
    "Dermatology": {
        "doctor_name": "डॉ. अनिता गुप्ता (Dr. Anita Gupta)",
        "specialty": "त्वचा एवं चर्म रोग (Dermatology)",
        "room_no": "कक्ष संख्या 5",
        "clinic_name": "अलवर सामुदायिक स्वास्थ्य केंद्र (Alwar CHC)",
        "slots": [
            {"slot_id": "slot_derm_1", "time": "11:00 AM - 11:30 AM"},
            {"slot_id": "slot_derm_2", "time": "04:00 PM - 04:30 PM"},
        ],
    },
    "Pediatrics": {
        "doctor_name": "डॉ. राजेश मीणा (Dr. Rajesh Meena)",
        "specialty": "शिशु रोग विशेषज्ञ (Pediatrics)",
        "room_no": "कक्ष संख्या 2",
        "clinic_name": "अलवर सामुदायिक स्वास्थ्य केंद्र (Alwar CHC)",
        "slots": [
            {"slot_id": "slot_ped_1", "time": "09:30 AM - 10:00 AM"},
            {"slot_id": "slot_ped_2", "time": "10:30 AM - 11:00 AM"},
        ],
    },
}

# ==============================================================================
# 3. CLINICAL TRIAGE & RED FLAG REASONING
# ==============================================================================
RED_FLAG_PATTERNS = [
    (r"छाती में दर्द|सीने में दर्द|chest pain", "सीने में तेज़ दर्द (Possible Acute Coronary Syndrome)"),
    (
        r"सांस फूल|सांस लेने में तकलीफ|difficulty breathing|breathless",
        "गंभीर श्वसन संकट (Severe Respiratory Distress)",
    ),
    (r"खून की उल्टी|vomiting blood|hemoptysis", "आंतरिक रक्तस्राव (Internal Hemorrhage)"),
    (r"बेहोश|unconscious|fainting|चक्कर खाकर गिर", "चेतना की हानि (Altered Mental State / Syncope)"),
    (r"गर्दन में अकड़न|stiff neck.*fever", "संभावित मेनिन्जाइटिस (Suspected Meningitis)"),
]


def evaluate_clinical_case(text: str) -> dict[str, Any]:
    """Analyze symptoms and generate clinical SOAP assessment & Hindi guidance."""
    text_lower = text.lower()

    # 1. Emergency Red Flag Screening
    emergency_reasons = []
    for pattern, reason in RED_FLAG_PATTERNS:
        if re.search(pattern, text_lower):
            emergency_reasons.append(reason)

    is_emergency = len(emergency_reasons) > 0

    # 2. Specialty & Differential Matching
    if any(
        k in text_lower for k in ["खांसी", "cough", "सांस", "breath", "फेफड़े", "बलगम", "tb", "टीबी"]
    ):
        specialty = "Pulmonology"
        urgency = "High (Urgent)" if is_emergency else "Moderate (Semi-Urgent)"
        diffs = [
            "Acute Bronchitis / Viral Bronchospasm",
            "Upper Respiratory Tract Infection",
            "Possible Pulmonary Tuberculosis (if >2 wks)",
        ]
        hindi_advice = "पर्याप्त मात्रा में गुनगुना पानी पिएं, धूल-धुएं से बचें और भाप लें। यदि सांस लेने में कठिनाई हो तो तुरंत CHC पहुंचें।"
        summary_hi = "लक्षण श्वसन तंत्र संक्रमण (खांसी/श्वसन कष्ट) की ओर संकेत करते हैं। छाती एवं फेफड़ा रोग विशेषज्ञ से परामर्श अनुशंसित है।"
    elif any(
        k in text_lower for k in ["त्वचा", "खुजली", "rash", "दाद", "खाज", "skin", "itching", "फुंसी"]
    ):
        specialty = "Dermatology"
        urgency = "Routine"
        diffs = [
            "Contact Dermatitis / Allergic Eczema",
            "Superficial Fungal Tinea Infection",
            "Urticarial Reaction",
        ]
        hindi_advice = (
            "प्रभावित हिस्से को साफ और सूखा रखें। उस पर बिना डॉक्टर की सलाह के कोई तेज स्टेरॉयड क्रीम न लगाएं।"
        )
        summary_hi = "लक्षण त्वचा संक्रमण या एलर्जी (Dermatitis/Fungal) की ओर संकेत करते हैं। त्वचा रोग विशेषज्ञ को दिखाना उचित रहेगा।"
    elif any(k in text_lower for k in ["बच्चा", "शिशु", "baby", "child", "infant"]):
        specialty = "Pediatrics"
        urgency = "Moderate (Semi-Urgent)"
        diffs = ["Pediatric Viral Syndrome", "Acute Pediatric Gastroenteritis / URI"]
        hindi_advice = "शिशु को ओआरएस का घोल और तरल पदार्थ देते रहें। तापमान पर नज़र रखें।"
        summary_hi = "शिशु स्वास्थ्य के लिए बाल रोग विशेषज्ञ (Pediatrician) से परामर्श अनुशंसित है।"
    else:
        specialty = "General Medicine"
        urgency = "High (Urgent)" if is_emergency else "Moderate (Semi-Urgent)"
        diffs = [
            "Acute Febrile Illness (Viral / Malaria / Dengue)",
            "Gastroenteritis / Dyspepsia",
            "Tension Headache / Fatigue",
        ]
        hindi_advice = "पर्याप्त आराम करें, ओआरएस या नारियल पानी का सेवन करें और हल्का सुपाच्य भोजन लें।"
        summary_hi = (
            "लक्षण सामान्य मौसमी संक्रमण या बुखार की ओर संकेत करते हैं। सामान्य चिकित्सा (OPD) परामर्श अनुशंसित है।"
        )

    return {
        "is_emergency": is_emergency,
        "emergency_reasons": emergency_reasons,
        "urgency": urgency,
        "specialty": specialty,
        "differentials": diffs,
        "hindi_advice": hindi_advice,
        "summary_hi": summary_hi,
    }


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * r * math.asin(math.sqrt(a)), 1)


# ==============================================================================
# 4. INITIALIZE AGENT & CHAT PROTOCOL
# ==============================================================================
agent = Agent(name="careroute_dispatcher")
chat_proto = Protocol(spec=chat_protocol_spec)


def make_text_chat(text: str, end_session: bool = False) -> ChatMessage:
    content = [TextContent(type="text", text=text)]
    if end_session:
        content.append(EndSessionContent())
    return ChatMessage(
        timestamp=datetime.datetime.now(datetime.timezone.utc),
        msg_id=uuid4(),
        content=content,
    )


def make_ack(msg_id: UUID | str) -> ChatAcknowledgement:
    if isinstance(msg_id, str):
        msg_id = UUID(msg_id)
    return ChatAcknowledgement(
        timestamp=datetime.datetime.now(datetime.timezone.utc),
        acknowledged_msg_id=msg_id,
    )


# ==============================================================================
# 5. PROTOCOL MESSAGE HANDLERS
# ==============================================================================
@chat_proto.on_message(model=ChatMessage)
async def handle_chat_message(ctx: Context, sender: str, msg: ChatMessage) -> None:
    # 1. Send ACP Acknowledgement
    try:
        await ctx.send(sender, make_ack(msg.msg_id))
    except Exception as e:
        ctx.logger.error(f"Ack failed: {e}")

    # 2. Load sender session from Agentverse persistent storage
    session = ctx.storage.get(sender) or {
        "state": "STATE_INTAKE",
        "patient_name": "मरीज",
        "recommended_specialty": "General Medicine",
        "selected_slot": None,
    }

    # 3. Process ACP content
    for item in msg.content:
        # A) Start Session
        if isinstance(item, StartSessionContent) or getattr(item, "type", None) in (
            "start-session",
            "start_session",
        ):
            session["state"] = "STATE_INTAKE"
            ctx.storage.set(sender, session)
            welcome_text = (
                "नमस्ते! मैं **केयररूट (CareRoute)** - आपका डिजिटल स्वास्थ्य सहायक हूँ। 🙏\n\n"
                "कृपया अपनी समस्या बताएं। आप बोलकर या लिखकर (हिंदी / English) बता सकते हैं:\n"
                "*(उदाहरण: 'मुझे 3 दिन से तेज़ बुखार और खांसी आ रही है')*"
            )
            await ctx.send(sender, make_text_chat(welcome_text))
            return

        # B) End Session
        if isinstance(item, EndSessionContent) or getattr(item, "type", None) in (
            "end-session",
            "end_session",
        ):
            session["state"] = "STATE_CLOSED"
            ctx.storage.set(sender, session)
            farewell = "सत्र समाप्त हो गया है। केयररूट से जुड़ने के लिए धन्यवाद। स्वस्थ रहें! 🙏"
            await ctx.send(sender, make_text_chat(farewell, end_session=True))
            return

        # C) Text Input
        if isinstance(item, TextContent) or getattr(item, "type", None) == "text":
            user_text = item.text.strip()
            await process_text_narrative(ctx, sender, session, user_text)
            return


async def process_text_narrative(
    ctx: Context, sender: str, session: dict[str, Any], user_text: str
) -> None:
    text_clean = user_text.lower().strip()

    # 1. Greetings
    greetings = {"hi", "hello", "hey", "नमस्ते", "नमस्कार", "pranam", "प्रणाम", "start", "हाय", "हेलो"}
    if text_clean in greetings:
        welcome_text = (
            "नमस्ते! मैं **केयररूट (CareRoute)** - आपका डिजिटल स्वास्थ्य सहायक हूँ। 🙏\n\n"
            "कृपया अपने लक्षण बताएं (जैसे: बुखार, खांसी, सीने में दर्द, त्वचा रोग) या नजदीकी अस्पताल की जानकारी लें।\n"
            "*(उदाहरण: 'मुझे 3 दिन से तेज़ बुखार और सिरदर्द है')*"
        )
        await ctx.send(sender, make_text_chat(welcome_text))
        return

    # 2. Hospital / CHC Inquiry (strictly checking for non-complaint questions)
    chc_phrases = ["अस्पताल", "hospital", "chc", "नजदीकी अस्पताल", "निकटतम अस्पताल", "hospital list"]
    is_negation = any(
        w in user_text for w in ["पहले भी", "तीसरी बार", "मत भेजो", "नहीं चाहिए", "कोई नया"]
    )
    if (
        not is_negation
        and (len(user_text.split()) <= 8)
        and any(p in text_clean for p in chc_phrases)
    ):
        chc_list = []
        for c in VERIFIED_CHCS:
            dist = haversine_km(27.5530, 76.6346, c["latitude"], c["longitude"])
            chc_list.append(
                f"🏥 **{c['name']}**\n"
                f"📍 {c['address']} (दूरी: लगभग {dist} किमी)\n"
                f"🕒 ओपीडी समय: {c['opd_timings']}\n"
                f"📞 हेल्पलाइन: {c['phone']} (आपातकाल: 108)"
            )
        resp = (
            "🏥 **अलवर जिले के निकटतम सामुदायिक स्वास्थ्य केंद्र (Nearby CHCs):**\n\n"
            + "\n\n─────────────────\n\n".join(chc_list)
        )
        await ctx.send(sender, make_text_chat(resp))
        return

    # 3. Handle Slot Selection (e.g. user typed '1', '2', or 'स्लॉट')
    if session.get("state") == "STATE_TRIAGE_PRESENTED" and any(
        k in text_clean for k in ["slot", "स्लॉट", "book", "बुकिंग", "डॉक्टर"]
    ):
        specialty = session.get("recommended_specialty", "General Medicine")
        roster = DOCTORS_ROSTER.get(specialty, DOCTORS_ROSTER["General Medicine"])
        session["state"] = "STATE_SLOT_SELECTED"
        session["available_slots"] = roster["slots"]
        ctx.storage.set(sender, session)

        slots_formatted = "\n".join(
            f"  **[{idx}]** 🕒 समय: `{s['time']}`" for idx, s in enumerate(roster["slots"], 1)
        )
        msg_out = (
            f"📅 **उपलब्ध ओपीडी परामर्श समय (OPD Slots):**\n\n"
            f"👨‍⚕️ **चिकित्सक:** {roster['doctor_name']}\n"
            f"🏥 **स्थान:** {roster['clinic_name']}, {roster['room_no']}\n"
            f"🩺 **विशेषज्ञता:** {roster['specialty']}\n\n"
            f"{slots_formatted}\n\n"
            f"───────────────────────────────────\n"
            f"👉 अपनी पसंद का स्लॉट बुक करने के लिए संख्या (**1**, **2**, या **3**) लिखकर भेजें।"
        )
        await ctx.send(sender, make_text_chat(msg_out))
        return

    # 4. Handle Numeric Choice for Slot Booking (e.g. '1', '2')
    if session.get("state") == "STATE_SLOT_SELECTED" and user_text.isdigit():
        choice_idx = int(user_text) - 1
        available = session.get("available_slots", [])
        if 0 <= choice_idx < len(available):
            chosen = available[choice_idx]
            ticket_id = f"CR-ALW-{uuid4().hex[:4].upper()}"
            specialty = session.get("recommended_specialty", "General Medicine")
            roster = DOCTORS_ROSTER.get(specialty, DOCTORS_ROSTER["General Medicine"])

            session["state"] = "STATE_CONFIRMED"
            session["ticket_id"] = ticket_id
            ctx.storage.set(sender, session)

            confirmation = (
                f"🎉 **आपकी ओपीडी परामर्श बुकिंग सफलतापूर्वक पुष्टि हो गई है!**\n\n"
                f"🎫 **टोकन क्रमांक:** `{ticket_id}`\n"
                f"👨‍⚕️ **चिकित्सक:** {roster['doctor_name']}\n"
                f"🏥 **स्थान:** {roster['clinic_name']}, {roster['room_no']}\n"
                f"🕒 **समय स्लॉट:** {chosen['time']}\n"
                f"🔐 **डिजिटल चेक-इन कोड:** `CAREROUTE:{ticket_id}`\n\n"
                f"📌 **मरीज के लिए निर्देश:**\n"
                f"• कृपया अपने समय स्लॉट से 10 मिनट पहले सीएचसी पंजीकरण काउंटर पर पहुंचें।\n"
                f"• अपनी पिछली पर्चियां या दवाएं साथ लाएं।\n"
                f"• स्वास्थ्य केंद्र पहुँचने पर यह टोकन नंबर दिखाएं।"
            )
            await ctx.send(sender, make_text_chat(confirmation))
            return

    # 5. Symptom Clinical Analysis & Triage
    triage = evaluate_clinical_case(user_text)
    session["recommended_specialty"] = triage["specialty"]
    session["triage_urgency"] = triage["urgency"]

    if triage["is_emergency"]:
        session["state"] = "STATE_EMERGENCY"
        ctx.storage.set(sender, session)
        emergency_reasons_txt = "\n".join(f"• {r}" for r in triage["emergency_reasons"])
        sos_msg = (
            f"🚨 **आपातकालीन चेतावनी (Emergency SOS Alert)!**\n\n"
            f"आपके लक्षणों में गंभीर चिकित्सीय संकेत मिले हैं:\n"
            f"{emergency_reasons_txt}\n\n"
            f"⚠️ **तत्काल कदम उठाएं:**\n"
            f"1. सीधे **108 एम्बुलेंस** पर कॉल करें या तुरंत नजदीकी अस्पताल के आपातकालीन विभाग में पहुंचें।\n"
            f"2. अकेले यात्रा न करें, परिवार के सदस्य को साथ रखें।\n"
            f"3. कोई भी भारी काम न करें और शांत रहें।"
        )
        await ctx.send(sender, make_text_chat(sos_msg))
        return

    session["state"] = "STATE_TRIAGE_PRESENTED"
    ctx.storage.set(sender, session)

    diffs_txt = "\n".join(f"• {d}" for d in triage["differentials"])
    triage_msg = (
        f"🩺 **केयररूट प्रारंभिक नैदानिक मूल्यांकन (Clinical Triage):**\n\n"
        f"📊 **प्राथमिकता (Urgency):** `{triage['urgency']}`\n"
        f"👨‍⚕️ **अनुशंसित विभाग:** {triage['specialty']}\n\n"
        f"📝 **लक्षण विश्लेषण:**\n"
        f"{triage['summary_hi']}\n\n"
        f"🔍 **संभावित नैदानिक विचार (Differential Diagnoses):**\n"
        f"{diffs_txt}\n\n"
        f"💡 **अंतरिम घरेलू परामर्श (Home Care Advice):**\n"
        f"{triage['hindi_advice']}\n\n"
        f"───────────────────────────────────\n"
        f"👉 डॉक्टर से मिलने का समय चुनने के लिए **'स्लॉट'** या **'1'** लिखकर भेजें।"
    )
    await ctx.send(sender, make_text_chat(triage_msg))


@chat_proto.on_message(model=ChatAcknowledgement)
async def handle_chat_ack(ctx: Context, sender: str, msg: ChatAcknowledgement) -> None:
    """Handle incoming ACP message delivery receipts."""
    ctx.logger.debug(
        f"Received ChatAcknowledgement for msg {msg.acknowledged_msg_id} from {sender}"
    )


# ==============================================================================
# 6. INCLUDE CHAT PROTOCOL & RUN
# ==============================================================================
agent.include(chat_proto, publish_manifest=True)

if __name__ == "__main__":
    agent.run()
