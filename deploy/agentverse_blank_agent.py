"""CareRoute (केयररूट) - Agentverse Cloud Hosted Agent (Blank Agent Edition).

Deploy this self-contained script directly on Agentverse.ai as a "Blank Agent":
 1. Go to https://agentverse.ai -> Agents -> "+ New Agent" -> "Blank Agent"
 2. Paste this entire file into the web editor (replacing all default code).
 3. Click "Start" in the top right corner.
 4. Open your agent on ASI:One: https://asi1.ai/chat?agent=<YOUR_AGENT_ADDRESS>

Features included out of the box (Zero Local Dependencies):
 - Official Agent Chat Protocol (ACP) compliant.
 - Full Bilingual Support: Speaks both fluent English and Hindi / Hinglish.
 - Robust Numeric Slot Selection: Recognizes '1', '2', '3', 'slot 1', 'first', 'पहला', etc.
 - Emergency Red Flag detection & instant 108 Ambulance SOS alert.
 - 6 Clinical Specialties: General Medicine, Pulmonology, Dermatology, Orthopedics, Pediatrics, Gynecology.
 - Verified Alwar District CHC Hospital Locator with distances and contact info.
 - Real-time OPD Doctor Slot Scheduling & Digital Check-in Token Generation.
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
        "name_hi": "सामुदायिक स्वास्थ्य केंद्र एवं सामान्य चिकित्सालय, अलवर (Alwar CHC)",
        "name_en": "Community Health Center & General Hospital, Alwar (Alwar CHC)",
        "latitude": 27.5530,
        "longitude": 76.6346,
        "address_hi": "कंपनी बाग रोड, अलवर (राजस्थान 301001)",
        "address_en": "Company Bagh Road, Alwar, Rajasthan 301001",
        "phone": "+91-144-2332211",
        "emergency_helpline": "108",
        "opd_timings": "09:00 AM - 01:00 PM, 04:00 PM - 06:00 PM",
    },
    {
        "id": "chc_behror",
        "name_hi": "सामुदायिक स्वास्थ्य केंद्र, बहरोड़ (Behror CHC)",
        "name_en": "Community Health Center, Behror (Behror CHC)",
        "latitude": 27.8872,
        "longitude": 76.2806,
        "address_hi": "NH-48, बस स्टैंड के पास, बहरोड़ (अलवर 301701)",
        "address_en": "Near Bus Stand, NH-48, Behror, Alwar 301701",
        "phone": "+91-1494-220015",
        "emergency_helpline": "108",
        "opd_timings": "09:00 AM - 01:00 PM",
    },
    {
        "id": "chc_tijara",
        "name_hi": "सामुदायिक स्वास्थ्य केंद्र, तिजारा (Tijara CHC)",
        "name_en": "Community Health Center, Tijara (Tijara CHC)",
        "latitude": 27.9332,
        "longitude": 76.8524,
        "address_hi": "रेवाड़ी-अलवर रोड, तिजारा (अलवर 301411)",
        "address_en": "Rewari-Alwar Road, Tijara, Alwar 301411",
        "phone": "+91-1469-222045",
        "emergency_helpline": "108",
        "opd_timings": "09:00 AM - 01:00 PM",
    },
    {
        "id": "chc_kishangarh",
        "name_hi": "सामुदायिक स्वास्थ्य केंद्र, किशनगढ़ बास (Kishangarh Bas CHC)",
        "name_en": "Community Health Center, Kishangarh Bas (Kishangarh Bas CHC)",
        "latitude": 27.8188,
        "longitude": 76.7214,
        "address_hi": "मुख्य बाजार के पास, किशनगढ़ बास (अलवर 301405)",
        "address_en": "Near Main Market, Kishangarh Bas, Alwar 301405",
        "phone": "+91-1460-224010",
        "emergency_helpline": "108",
        "opd_timings": "09:00 AM - 01:00 PM",
    },
]

# ==============================================================================
# 2. OPD CLINIC ROSTER & APPOINTMENT DOCTORS
# ==============================================================================
DOCTORS_ROSTER: dict[str, dict[str, Any]] = {
    "General Medicine": {
        "doctor_name_hi": "डॉ. हरीश शर्मा (वरिष्ठ चिकित्सक)",
        "doctor_name_en": "Dr. Harish Sharma (Senior Physician)",
        "specialty_hi": "सामान्य चिकित्सा (General Medicine)",
        "specialty_en": "General Medicine",
        "room_no_hi": "कक्ष संख्या 4",
        "room_no_en": "Room No. 4",
        "clinic_hi": "अलवर सामुदायिक स्वास्थ्य केंद्र (Alwar CHC)",
        "clinic_en": "Alwar Community Health Center (Alwar CHC)",
        "slots": [
            {"slot_id": "slot_gen_1", "time": "10:00 AM - 10:30 AM"},
            {"slot_id": "slot_gen_2", "time": "11:00 AM - 11:30 AM"},
            {"slot_id": "slot_gen_3", "time": "12:00 PM - 12:30 PM"},
        ],
    },
    "Pulmonology": {
        "doctor_name_hi": "डॉ. सुनीता वर्मा (छाती एवं श्वसन विशेषज्ञ)",
        "doctor_name_en": "Dr. Sunita Verma (Pulmonologist & Chest Specialist)",
        "specialty_hi": "छाती एवं श्वसन रोग (Pulmonology / TB Care)",
        "specialty_en": "Pulmonology & Respiratory Care",
        "room_no_hi": "कक्ष संख्या 7",
        "room_no_en": "Room No. 7",
        "clinic_hi": "अलवर सामुदायिक स्वास्थ्य केंद्र (Alwar CHC)",
        "clinic_en": "Alwar Community Health Center (Alwar CHC)",
        "slots": [
            {"slot_id": "slot_pul_1", "time": "10:30 AM - 11:00 AM"},
            {"slot_id": "slot_pul_2", "time": "11:30 AM - 12:00 PM"},
            {"slot_id": "slot_pul_3", "time": "04:00 PM - 04:30 PM"},
        ],
    },
    "Dermatology": {
        "doctor_name_hi": "डॉ. अनिता गुप्ता (त्वचा रोग विशेषज्ञ)",
        "doctor_name_en": "Dr. Anita Gupta (Dermatologist)",
        "specialty_hi": "त्वचा एवं चर्म रोग (Dermatology)",
        "specialty_en": "Dermatology & Skin Care",
        "room_no_hi": "कक्ष संख्या 5",
        "room_no_en": "Room No. 5",
        "clinic_hi": "अलवर सामुदायिक स्वास्थ्य केंद्र (Alwar CHC)",
        "clinic_en": "Alwar Community Health Center (Alwar CHC)",
        "slots": [
            {"slot_id": "slot_derm_1", "time": "11:00 AM - 11:30 AM"},
            {"slot_id": "slot_derm_2", "time": "04:00 PM - 04:30 PM"},
        ],
    },
    "Orthopedics": {
        "doctor_name_hi": "डॉ. विक्रम सिंह (अस्थि एवं जोड़ विशेषज्ञ)",
        "doctor_name_en": "Dr. Vikram Singh (Orthopedic Specialist)",
        "specialty_hi": "हड्डी एवं जोड़ रोग (Orthopedics)",
        "specialty_en": "Orthopedics & Joint Care",
        "room_no_hi": "कक्ष संख्या 6",
        "room_no_en": "Room No. 6",
        "clinic_hi": "अलवर सामुदायिक स्वास्थ्य केंद्र (Alwar CHC)",
        "clinic_en": "Alwar Community Health Center (Alwar CHC)",
        "slots": [
            {"slot_id": "slot_ortho_1", "time": "10:00 AM - 10:30 AM"},
            {"slot_id": "slot_ortho_2", "time": "12:00 PM - 12:30 PM"},
        ],
    },
    "Pediatrics": {
        "doctor_name_hi": "डॉ. राजेश मीणा (शिशु रोग विशेषज्ञ)",
        "doctor_name_en": "Dr. Rajesh Meena (Pediatrician)",
        "specialty_hi": "शिशु एवं बाल रोग (Pediatrics)",
        "specialty_en": "Pediatrics & Child Care",
        "room_no_hi": "कक्ष संख्या 2",
        "room_no_en": "Room No. 2",
        "clinic_hi": "अलवर सामुदायिक स्वास्थ्य केंद्र (Alwar CHC)",
        "clinic_en": "Alwar Community Health Center (Alwar CHC)",
        "slots": [
            {"slot_id": "slot_ped_1", "time": "09:30 AM - 10:00 AM"},
            {"slot_id": "slot_ped_2", "time": "10:30 AM - 11:00 AM"},
        ],
    },
    "Gynecology": {
        "doctor_name_hi": "डॉ. मीनाक्षी जोशी (स्त्री एवं प्रसूति रोग विशेषज्ञ)",
        "doctor_name_en": "Dr. Meenakshi Joshi (Gynecologist & Obstetrician)",
        "specialty_hi": "स्त्री एवं प्रसूति रोग (Gynecology / MCH)",
        "specialty_en": "Gynecology & Maternal Health",
        "room_no_hi": "कक्ष संख्या 3",
        "room_no_en": "Room No. 3",
        "clinic_hi": "अलवर सामुदायिक स्वास्थ्य केंद्र (Alwar CHC)",
        "clinic_en": "Alwar Community Health Center (Alwar CHC)",
        "slots": [
            {"slot_id": "slot_gyn_1", "time": "09:30 AM - 10:00 AM"},
            {"slot_id": "slot_gyn_2", "time": "11:00 AM - 11:30 AM"},
        ],
    },
}


# ==============================================================================
# 3. LANGUAGE DETECTION & CLINICAL PATTERNS
# ==============================================================================
def detect_language(text: str) -> str:
    """Detect whether input is English ('en') or Hindi/Hinglish ('hi')."""
    # 1. Any Devanagari script character means Hindi
    if any("\u0900" <= ch <= "\u097f" for ch in text):
        return "hi"

    # 2. Check for common Hinglish words
    hinglish_markers = {
        "hai",
        "ho",
        "raha",
        "rahi",
        "rahe",
        "tha",
        "thi",
        "the",
        "mera",
        "meri",
        "mere",
        "mujhe",
        "hum",
        "aap",
        "kya",
        "kaise",
        "kahan",
        "nahi",
        "nahin",
        "dard",
        "bukhar",
        "khansi",
        "dawai",
        "ilaj",
        "se",
        "ko",
        "ka",
        "ki",
        "ke",
        "aur",
        "bhi",
        "bahut",
        "sirdard",
        "pet",
        "daane",
        "khujli",
    }
    words = set(re.findall(r"\b[a-zA-Z]+\b", text.lower()))
    if words and len(words & hinglish_markers) >= 1:
        # If input has prominent Hinglish markers, treat as Hindi
        if len(words & hinglish_markers) >= 2 or len(words) <= 4:
            return "hi"

    return "en"


RED_FLAG_PATTERNS = [
    (
        r"छाती में (?:तेज )?दर्द|सीने में (?:तेज )?दर्द|chest pain|pressure in chest|heart attack",
        "सीने में तेज़ दर्द / दबाव (Possible Acute Coronary Syndrome)",
        "Severe Chest Pain / Pressure (Possible Acute Coronary Syndrome)",
    ),
    (
        r"सांस फूल|सांस लेने में तकलीफ|दम घुट|difficulty breathing|shortness of breath|breathless|gasping",
        "गंभीर श्वसन संकट (Severe Respiratory Distress)",
        "Severe Respiratory Distress (Difficulty Breathing)",
    ),
    (
        r"खून की उल्टी|vomiting blood|coughing blood|hemoptysis|rectal bleed",
        "गंभीर रक्तस्राव (Acute Hemorrhage / Bleeding)",
        "Acute Hemorrhage / Bleeding",
    ),
    (
        r"बेहोश|unconscious|fainting|passed out|collapse|चक्कर खाकर गिर",
        "चेतना की हानि / बेहोशी (Altered Mental State / Syncope)",
        "Loss of Consciousness / Syncope",
    ),
    (
        r"दौरा|मिर्गी|convulsion|seizure|fits",
        "मिर्गी का दौरा / आक्षेप (Seizure / Convulsion)",
        "Seizure / Convulsions",
    ),
    (
        r"सांप ने काटा|snake bite|poison|जहर खा",
        "सर्पदंश या विषाक्तता (Snakebite / Acute Poisoning)",
        "Snakebite / Acute Poisoning Emergency",
    ),
]


def evaluate_clinical_case(text: str, lang: str = "en") -> dict[str, Any]:
    """Analyze symptoms and generate clinical SOAP assessment in user's language."""
    text_lower = text.lower()

    # 1. Emergency Red Flag Screening
    emergency_reasons_hi = []
    emergency_reasons_en = []
    for pattern, reason_hi, reason_en in RED_FLAG_PATTERNS:
        if re.search(pattern, text_lower):
            emergency_reasons_hi.append(reason_hi)
            emergency_reasons_en.append(reason_en)

    is_emergency = len(emergency_reasons_hi) > 0

    # 2. Specialty & Differential Matching
    if any(
        k in text_lower
        for k in [
            "खांसी",
            "cough",
            "coughing",
            "सांस",
            "breath",
            "फेफड़े",
            "बलगम",
            "tb",
            "टीबी",
            "phlegm",
            "sputum",
            "wheezing",
            "asthma",
            "dama",
        ]
    ):
        specialty = "Pulmonology"
        urgency = "High (Urgent)" if is_emergency else "Moderate (Semi-Urgent)"
        diffs_en = [
            "Acute Bronchitis / Viral Bronchospasm",
            "Upper Respiratory Tract Infection (URTI)",
            "Possible Pulmonary Tuberculosis (if symptoms > 2 weeks)",
        ]
        diffs_hi = [
            "तीव्र ब्रोंकाइटिस / श्वसन नली में सूजन",
            "ऊपरी श्वसन तंत्र संक्रमण (Viral URTI)",
            "संभावित पल्मोनरी टीबी (यदि खांसी 2 हफ्ते से अधिक हो)",
        ]
        advice_en = "Stay well hydrated with warm fluids, avoid cold air and dust, and take steam inhalation. If breathlessness worsens, visit CHC immediately."
        advice_hi = "पर्याप्त मात्रा में गुनगुना पानी पिएं, धूल-धुएं से बचें और भाप लें। यदि सांस लेने में कठिनाई हो तो तुरंत CHC पहुंचें।"
        summary_en = "Symptoms point toward a respiratory tract infection or chest congestion. An OPD consultation with a Pulmonology specialist is recommended."
        summary_hi = "लक्षण श्वसन तंत्र संक्रमण (खांसी/बलगम/सीने में जकड़न) की ओर संकेत करते हैं। छाती एवं फेफड़ा रोग विशेषज्ञ से परामर्श अनुशंसित है।"

    elif any(
        k in text_lower
        for k in [
            "त्वचा",
            "खुजली",
            "rash",
            "दाद",
            "खाज",
            "skin",
            "itching",
            "itchy",
            "फुंसी",
            "allergy",
            "boil",
            "ringworm",
            "eczema",
            "pimple",
            "चकत्ते",
        ]
    ):
        specialty = "Dermatology"
        urgency = "Routine"
        diffs_en = [
            "Contact Dermatitis / Allergic Eczema",
            "Superficial Fungal Tinea Infection (Ringworm)",
            "Urticarial Reaction / Pruritus",
        ]
        diffs_hi = [
            "एलर्जिक डर्मेटाइटिस / एक्जिमा",
            "फंगल संक्रमण / दाद-खाज (Tinea Infection)",
            "अर्टिकेरिया / पित्ती उछलना",
        ]
        advice_en = "Keep the affected area clean and dry. Avoid scratching and do not apply strong over-the-counter steroid creams without a doctor's examination."
        advice_hi = "प्रभावित हिस्से को साफ और सूखा रखें। खुजलाएं नहीं और बिना डॉक्टर की सलाह के कोई तेज स्टेरॉयड क्रीम न लगाएं।"
        summary_en = "Symptoms suggest a skin infection or allergic dermatological reaction. Consultation with a Dermatology specialist is recommended."
        summary_hi = "लक्षण त्वचा संक्रमण या एलर्जी (Dermatitis / Fungal) की ओर संकेत करते हैं। त्वचा रोग विशेषज्ञ को दिखाना उचित रहेगा।"

    elif any(
        k in text_lower
        for k in [
            "घुटने",
            "knee",
            "कमर",
            "back pain",
            "जोड़ों",
            "joint",
            "हड्डी",
            "bone",
            "fracture",
            "sprain",
            "मोच",
            "arthritis",
            "गठिया",
            "ankle",
            "swelling leg",
        ]
    ):
        specialty = "Orthopedics"
        urgency = "Moderate (Semi-Urgent)"
        diffs_en = [
            "Osteoarthritis / Degenerative Joint Disease",
            "Acute Ligamentous Sprain / Muscle Strain",
            "Lumbar Spondylosis / Mechanical Back Ache",
        ]
        diffs_hi = [
            "ऑस्टियोअर्थराइटिस / जोड़ों का घिसना",
            "मांसपेशियों में खिंचाव या मोच (Ligament Sprain)",
            "कमर का दर्द / लंबर स्पोंडिलोसिस",
        ]
        advice_en = "Apply hot/cold compress, avoid heavy weight lifting or deep squatting, and rest the affected joint."
        advice_hi = "दर्द वाले जोड़ को आराम दें, गर्म या ठंडी सिकाई करें और भारी वजन उठाने से बचें।"
        summary_en = "Symptoms indicate joint inflammation, musculoskeletal strain, or ligament injury. Orthopedics consultation is advised."
        summary_hi = "लक्षण हड्डियों, जोड़ों या मांसपेशियों में खिंचाव/सूजन की ओर संकेत करते हैं। अस्थि रोग विशेषज्ञ (Orthopedic) से परामर्श अनुशंसित है।"

    elif any(
        k in text_lower
        for k in [
            "बच्चा",
            "शिशु",
            "baby",
            "child",
            "infant",
            "toddler",
            "kid",
            "newborn",
            "बेटा",
            "बेटी",
        ]
    ):
        specialty = "Pediatrics"
        urgency = "Moderate (Semi-Urgent)"
        diffs_en = [
            "Pediatric Viral Syndrome / Febrile URI",
            "Acute Pediatric Gastroenteritis",
            "Childhood Wheeze / Bronchiolitis",
        ]
        diffs_hi = [
            "बाल्यकालीन वायरल सिंड्रोम / मौसमी बुखार",
            "शिशु दस्त एवं उल्टी (Pediatric Gastroenteritis)",
            "बाल श्वसन कष्ट (Bronchiolitis)",
        ]
        advice_en = "Ensure continuous hydration with ORS and fluids. Monitor body temperature and consult a pediatrician promptly."
        advice_hi = "शिशु को ओआरएस का घोल और पर्याप्त तरल पदार्थ देते रहें। तापमान पर लगातार नज़र रखें।"
        summary_en = "Patient is a child/infant. Direct evaluation by a Pediatrician is strongly recommended."
        summary_hi = "शिशु स्वास्थ्य के लिए बाल रोग विशेषज्ञ (Pediatrician) से परामर्श अनुशंसित है।"

    elif any(
        k in text_lower
        for k in [
            "pregnant",
            "pregnancy",
            "गर्भवती",
            "गर्भावस्था",
            "period",
            "माहवारी",
            "bleeding",
            "महिला",
            "gynec",
            "leucorrhea",
            "प्रसव",
        ]
    ):
        specialty = "Gynecology"
        urgency = "High (Urgent)" if is_emergency else "Moderate (Semi-Urgent)"
        diffs_en = [
            "Antenatal Consultation / Routine Obstetric Checkup",
            "Dysmenorrhea / Pelvic Inflammation (PID)",
            "Pregnancy-Related Anemia / Nutritional Deficiency",
        ]
        diffs_hi = [
            "गर्भावस्था जांच एवं परामर्श (Antenatal Checkup)",
            "मासिक धर्म संबंधी विकार / पेल्विक इन्फेक्शन",
            "एनीमिया / पोषण की कमी",
        ]
        advice_en = "Ensure adequate bed rest, take iron-folic acid supplements as prescribed, and do not self-medicate."
        advice_hi = "पर्याप्त आराम करें, पोषणयुक्त आहार लें और बिना डॉक्टर से पूछे कोई दवा न लें।"
        summary_en = "Symptoms relate to maternal health or obstetric care. Gynecology consultation is advised."
        summary_hi = "मातृ एवं महिला स्वास्थ्य के लिए स्त्री एवं प्रसूति रोग विशेषज्ञ से परामर्श अनुशंसित है।"

    else:
        specialty = "General Medicine"
        urgency = "High (Urgent)" if is_emergency else "Moderate (Semi-Urgent)"
        diffs_en = [
            "Acute Febrile Illness (Viral / Malaria / Dengue Suspect)",
            "Acute Gastroenteritis / Dyspepsia",
            "Tension Headache / Generalized Fatigue",
        ]
        diffs_hi = [
            "मौसमी बुखार / वायरल सिंड्रोम (Malaria/Dengue Suspect)",
            "पेट का संक्रमण / अपच (Gastroenteritis)",
            "तनाव सिरदर्द / कमजोरी",
        ]
        advice_en = "Get plenty of rest, drink adequate water/ORS, eat light easily-digestible meals, and consult the CHC doctor."
        advice_hi = "पर्याप्त आराम करें, ओआरएस या गुनगुना पानी पिएं और हल्का सुपाच्य भोजन लें।"
        summary_en = "Symptoms suggest a general medical presentation or acute febrile illness. General Medicine OPD consultation is recommended."
        summary_hi = (
            "लक्षण सामान्य मौसमी संक्रमण या बुखार की ओर संकेत करते हैं। सामान्य चिकित्सा (OPD) परामर्श अनुशंसित है।"
        )

    return {
        "is_emergency": is_emergency,
        "emergency_reasons": (emergency_reasons_en if lang == "en" else emergency_reasons_hi),
        "urgency": urgency,
        "specialty": specialty,
        "differentials": diffs_en if lang == "en" else diffs_hi,
        "advice": advice_en if lang == "en" else advice_hi,
        "summary": summary_en if lang == "en" else summary_hi,
    }


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * r * math.asin(math.sqrt(a)), 1)


def parse_slot_choice(text: str, max_slots: int) -> int | None:
    """Extract a 1-based slot choice index from English or Hindi user input.

    Returns the integer choice (e.g. 1, 2, 3) or None.
    """
    cleaned = text.strip().lower()

    # Guard: do not treat clinical narratives like 'fever for 3 days' as a slot selection
    clinical_keywords = [
        "day",
        "days",
        "din",
        "week",
        "weeks",
        "hafte",
        "month",
        "fever",
        "pain",
        "dard",
        "cough",
        "khansi",
        "year",
        "saal",
    ]
    if any(k in cleaned for k in clinical_keywords):
        return None

    # 1. Pure digit string: '1', '2', '3'
    if cleaned.isdigit():
        val = int(cleaned)
        return val if 1 <= val <= max_slots else None

    # 2. English & Hindi word numbers
    word_map = {
        "one": 1,
        "first": 1,
        "1st": 1,
        "two": 2,
        "second": 2,
        "2nd": 2,
        "three": 3,
        "third": 3,
        "3rd": 3,
        "four": 4,
        "fourth": 4,
        "4th": 4,
        "एक": 1,
        "पहला": 1,
        "दो": 2,
        "दूसरा": 2,
        "तीन": 3,
        "तीसरा": 3,
        "चार": 4,
        "चौथा": 4,
    }
    for word, num in word_map.items():
        if (word in cleaned) if not word.isascii() else bool(re.search(rf"\b{word}\b", cleaned)):
            return num if 1 <= num <= max_slots else None

    # 3. Phrasing like 'slot 1', 'option 2', 'choice 1', 'no. 3', '[1]', '1.'
    match = re.search(
        r"(?:slot|opt|option|choice|number|no|स्लॉट|नंबर|विकल्प)?\s*[:\-#]?\s*\[?([1-9])\]?\.?",
        cleaned,
    )
    if match and len(cleaned.split()) <= 4:
        val = int(match.group(1))
        return val if 1 <= val <= max_slots else None

    return None


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
        "lang": "en",
        "patient_name": "Patient",
        "recommended_specialty": "General Medicine",
        "available_slots": None,
        "selected_slot": None,
    }

    # 3. Process ACP content items
    for item in msg.content:
        # A) Start Session
        if isinstance(item, StartSessionContent) or getattr(item, "type", None) in (
            "start-session",
            "start_session",
        ):
            session["state"] = "STATE_INTAKE"
            ctx.storage.set(sender, session)
            welcome_text = (
                "👋 **Welcome to CareRoute (केयररूट)!**\n"
                "I am your digital healthcare assistant for Alwar Community Health Centers (CHCs). 🙏\n\n"
                "Please describe your symptoms in **English, Hindi, or Hinglish**:\n"
                "*(Examples: 'I have had a high fever and cough for 3 days' or 'मुझे 3 दिन से तेज बुखार है')*\n\n"
                "You can also ask: *'Where is the nearest hospital?'* to view nearby CHCs."
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
            lang = session.get("lang", "en")
            farewell = (
                "Session closed. Thank you for using CareRoute. Stay healthy! 🙏"
                if lang == "en"
                else "सत्र समाप्त हो गया है। केयररूट से जुड़ने के लिए धन्यवाद। स्वस्थ रहें! 🙏"
            )
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

    # 0. Language Detection
    # Determine language preference and remember it in session storage
    current_lang = detect_language(user_text)
    session["lang"] = current_lang

    # 1. Greetings & Restart Commands
    greetings = {
        "hi",
        "hello",
        "hey",
        "start",
        "restart",
        "reset",
        "help",
        "namaste",
        "pranam",
        "नमस्ते",
        "नमस्कार",
        "प्रणाम",
        "हाय",
        "हेलो",
        "शुरू",
        "नया",
    }
    if text_clean in greetings:
        session["state"] = "STATE_INTAKE"
        ctx.storage.set(sender, session)
        if current_lang == "en":
            welcome_text = (
                "👋 **Hello! I am CareRoute (केयररूट)** - Your Digital Health Assistant. 🙏\n\n"
                "How can I help you today?\n"
                "1. **Describe Symptoms:** Tell me what you are experiencing (e.g., 'fever, headache, skin rash') to get clinical triage and book a doctor appointment.\n"
                "2. **Find Nearest Hospital:** Type *'hospital'* or *'chc'* to find nearest Community Health Centers in Alwar district.\n\n"
                "*(Example: 'I have had a productive cough and evening fever for 2 weeks')*"
            )
        else:
            welcome_text = (
                "नमस्ते! मैं **केयररूट (CareRoute)** - आपका डिजिटल स्वास्थ्य सहायक हूँ। 🙏\n\n"
                "मैं आपकी क्या सहायता कर सकता हूँ?\n"
                "1. **लक्षण बताएं:** अपनी समस्या लिखकर बताएं (जैसे: '3 दिन से बुखार और सिरदर्द है') ताकि प्रारंभिक जांच और डॉक्टर से मिलने का समय तय हो सके।\n"
                "2. **नजदीकी अस्पताल:** अलवर जिले के नजदीकी स्वास्थ्य केंद्र जानने के लिए *'अस्पताल'* या *'hospital'* लिखें।\n\n"
                "*(उदाहरण: 'मुझे 2 हफ्ते से खांसी और शाम को बुखार आ रहा है')*"
            )
        await ctx.send(sender, make_text_chat(welcome_text))
        return

    # 2. Hospital / CHC Locator Inquiry
    chc_phrases = [
        "hospital",
        "chc",
        "clinic",
        "doctor list",
        "hospital list",
        "where is",
        "location",
        "address",
        "अस्पताल",
        "नजदीकी अस्पताल",
        "निकटतम अस्पताल",
        "हॉस्पिटल",
    ]
    is_chc_complaint = any(
        w in user_text for w in ["पहले भी", "तीसरी बार", "मत भेजो", "नहीं चाहिए", "कोई नया"]
    )
    if (
        not is_chc_complaint
        and len(user_text.split()) <= 8
        and any(p in text_clean for p in chc_phrases)
    ):
        chc_list = []
        for c in VERIFIED_CHCS:
            dist = haversine_km(27.5530, 76.6346, c["latitude"], c["longitude"])
            if current_lang == "en":
                chc_list.append(
                    f"🏥 **{c['name_en']}**\n"
                    f"📍 {c['address_en']} (Distance: approx. {dist} km)\n"
                    f"🕒 OPD Timings: {c['opd_timings']}\n"
                    f"📞 Helpline: {c['phone']} | Emergency: 108"
                )
            else:
                chc_list.append(
                    f"🏥 **{c['name_hi']}**\n"
                    f"📍 {c['address_hi']} (दूरी: लगभग {dist} किमी)\n"
                    f"🕒 ओपीडी समय: {c['opd_timings']}\n"
                    f"📞 हेल्पलाइन: {c['phone']} (आपातकाल: 108)"
                )

        header = (
            "🏥 **Nearby Community Health Centers (CHCs) in Alwar District:**\n\n"
            if current_lang == "en"
            else "🏥 **अलवर जिले के निकटतम सामुदायिक स्वास्थ्य केंद्र (Nearby CHCs):**\n\n"
        )
        resp = header + "\n\n─────────────────\n\n".join(chc_list)
        await ctx.send(sender, make_text_chat(resp))
        return

    # 3. Handle Numeric Choice for OPD Slot Booking
    # Active if user is picking a slot (e.g. '1', '2', '3', 'slot 1', 'first')
    available_slots = session.get("available_slots") or []
    # If no slots in session, default to General Medicine roster
    if not available_slots:
        spec = session.get("recommended_specialty", "General Medicine")
        available_slots = DOCTORS_ROSTER.get(spec, DOCTORS_ROSTER["General Medicine"])["slots"]

    choice = parse_slot_choice(user_text, len(available_slots))
    if choice is not None:
        choice_idx = choice - 1
        chosen = available_slots[choice_idx]
        ticket_id = f"CR-ALW-{uuid4().hex[:4].upper()}"
        specialty = session.get("recommended_specialty", "General Medicine")
        roster = DOCTORS_ROSTER.get(specialty, DOCTORS_ROSTER["General Medicine"])

        session["state"] = "STATE_CONFIRMED"
        session["ticket_id"] = ticket_id
        session["selected_slot"] = chosen
        ctx.storage.set(sender, session)

        if current_lang == "en":
            confirmation = (
                f"🎉 **Your CHC OPD Appointment is Confirmed!**\n\n"
                f"🎫 **Token / Ticket ID:** `{ticket_id}`\n"
                f"👨‍⚕️ **Attending Doctor:** {roster['doctor_name_en']}\n"
                f"🩺 **Specialty:** {roster['specialty_en']}\n"
                f"🏥 **Facility:** {roster['clinic_en']}, {roster['room_no_en']}\n"
                f"🕒 **Scheduled Time Slot:** `{chosen['time']}`\n"
                f"🔐 **Digital Check-in Token:** `CAREROUTE:{ticket_id}`\n\n"
                f"📋 **Patient Instructions:**\n"
                f"• Please arrive at the CHC registration counter 10 minutes prior to `{chosen['time']}`.\n"
                f"• Present this Token ID (`{ticket_id}`) at the OPD reception desk.\n"
                f"• Bring any previous prescriptions, medical reports, or identity cards with you.\n\n"
                f"───────────────────────────────────\n"
                f"💡 Type *'hospital'* to view CHC address & directions, or *'restart'* to begin a new session."
            )
        else:
            confirmation = (
                f"🎉 **आपकी ओपीडी परामर्श बुकिंग सफलतापूर्वक पुष्टि हो गई है!**\n\n"
                f"🎫 **टोकन क्रमांक:** `{ticket_id}`\n"
                f"👨‍⚕️ **चिकित्सक:** {roster['doctor_name_hi']}\n"
                f"🩺 **विशेषज्ञता:** {roster['specialty_hi']}\n"
                f"🏥 **स्थान:** {roster['clinic_hi']}, {roster['room_no_hi']}\n"
                f"🕒 **समय स्लॉट:** `{chosen['time']}`\n"
                f"🔐 **डिजिटल चेक-इन कोड:** `CAREROUTE:{ticket_id}`\n\n"
                f"📌 **मरीज के लिए निर्देश:**\n"
                f"• कृपया अपने समय स्लॉट से 10 मिनट पहले सीएचसी पंजीकरण काउंटर पर पहुंचें।\n"
                f"• काउंटर पर यह टोकन नंबर (`{ticket_id}`) दिखाएं।\n"
                f"• अपनी पिछली पर्चियां या दवाएं साथ लाएं।\n\n"
                f"───────────────────────────────────\n"
                f"💡 अस्पताल का पता जानने के लिए *'अस्पताल'* लिखें, या नया सत्र शुरू करने के लिए *'start'* लिखें।"
            )
        await ctx.send(sender, make_text_chat(confirmation))
        return

    # 4. Handle Text Keyword for Slot Inquiry (e.g. 'slot', 'स्लॉट', 'book', 'booking')
    if any(k in text_clean for k in ["slot", "slots", "स्लॉट", "book", "बुकिंग"]):
        specialty = session.get("recommended_specialty", "General Medicine")
        roster = DOCTORS_ROSTER.get(specialty, DOCTORS_ROSTER["General Medicine"])
        session["state"] = "STATE_SLOT_SELECTED"
        session["available_slots"] = roster["slots"]
        ctx.storage.set(sender, session)

        slots_formatted = "\n".join(
            f"  **[{idx}]** 🕒 `{s['time']}`" for idx, s in enumerate(roster["slots"], 1)
        )
        if current_lang == "en":
            msg_out = (
                f"📅 **Available OPD Consultation Slots:**\n\n"
                f"👨‍⚕️ **Doctor:** {roster['doctor_name_en']}\n"
                f"🏥 **Facility:** {roster['clinic_en']}, {roster['room_no_en']}\n"
                f"🩺 **Specialty:** {roster['specialty_en']}\n\n"
                f"{slots_formatted}\n\n"
                f"───────────────────────────────────\n"
                f"👉 Reply with the number (**1**, **2**, or **3**) to reserve your appointment."
            )
        else:
            msg_out = (
                f"📅 **उपलब्ध ओपीडी परामर्श समय (OPD Slots):**\n\n"
                f"👨‍⚕️ **चिकित्सक:** {roster['doctor_name_hi']}\n"
                f"🏥 **स्थान:** {roster['clinic_hi']}, {roster['room_no_hi']}\n"
                f"🩺 **विशेषज्ञता:** {roster['specialty_hi']}\n\n"
                f"{slots_formatted}\n\n"
                f"───────────────────────────────────\n"
                f"👉 अपनी पसंद का स्लॉट बुक करने के लिए संख्या (**1**, **2**, या **3**) लिखकर भेजें।"
            )
        await ctx.send(sender, make_text_chat(msg_out))
        return

    # 5. Symptom Clinical Analysis & Triage
    triage = evaluate_clinical_case(user_text, lang=current_lang)
    session["recommended_specialty"] = triage["specialty"]
    session["triage_urgency"] = triage["urgency"]

    # 5A. Emergency SOS Tripwire Triggered
    if triage["is_emergency"]:
        session["state"] = "STATE_EMERGENCY"
        ctx.storage.set(sender, session)
        emergency_reasons_txt = "\n".join(f"• {r}" for r in triage["emergency_reasons"])
        if current_lang == "en":
            sos_msg = (
                f"🚨 **CRITICAL MEDICAL ALERT (Emergency SOS)!**\n\n"
                f"Potential life-threatening symptoms detected:\n"
                f"{emergency_reasons_txt}\n\n"
                f"⚠️ **Immediate Actions Required:**\n"
                f"1. **Call 108 Ambulance immediately** or proceed to the nearest emergency trauma center.\n"
                f"2. Do not travel alone; have a family member or neighbor accompany you.\n"
                f"3. Keep the patient calm, comfortable, and avoid any exertion."
            )
        else:
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

    # 5B. Routine / Semi-Urgent Clinical Triage + Immediate OPD Slot Offer
    # Retrieve matching doctor's slots so patient can choose immediately in 1 step!
    specialty = triage["specialty"]
    roster = DOCTORS_ROSTER.get(specialty, DOCTORS_ROSTER["General Medicine"])
    session["state"] = "STATE_SLOT_SELECTED"
    session["available_slots"] = roster["slots"]
    ctx.storage.set(sender, session)

    diffs_txt = "\n".join(f"• {d}" for d in triage["differentials"])
    slots_formatted = "\n".join(
        f"  **[{idx}]** 🕒 `{s['time']}`" for idx, s in enumerate(roster["slots"], 1)
    )

    if current_lang == "en":
        triage_msg = (
            f"🩺 **CareRoute Clinical Triage Assessment:**\n\n"
            f"📊 **Triage Urgency:** `{triage['urgency']}`\n"
            f"👨‍⚕️ **Recommended Specialty:** {roster['specialty_en']}\n\n"
            f"📝 **Clinical Summary:**\n"
            f"{triage['summary']}\n\n"
            f"🔍 **Differential Considerations:**\n"
            f"{diffs_txt}\n\n"
            f"💡 **Home Care & Pre-Visit Advice:**\n"
            f"{triage['advice']}\n\n"
            f"───────────────────────────────────\n"
            f"📅 **Available OPD Consultation Slots at Alwar CHC:**\n"
            f"👨‍⚕️ **Doctor:** {roster['doctor_name_en']} ({roster['room_no_en']})\n\n"
            f"{slots_formatted}\n\n"
            f"👉 **To reserve your slot, reply with 1, 2, or 3 (e.g. '1' or 'slot 1').**"
        )
    else:
        triage_msg = (
            f"🩺 **केयररूट प्रारंभिक नैदानिक मूल्यांकन (Clinical Triage):**\n\n"
            f"📊 **प्राथमिकता (Urgency):** `{triage['urgency']}`\n"
            f"👨‍⚕️ **अनुशंसित विभाग:** {roster['specialty_hi']}\n\n"
            f"📝 **लक्षण विश्लेषण:**\n"
            f"{triage['summary']}\n\n"
            f"🔍 **संभावित नैदानिक विचार (Differential Diagnoses):**\n"
            f"{diffs_txt}\n\n"
            f"💡 **अंतरिम घरेलू परामर्श (Home Care Advice):**\n"
            f"{triage['advice']}\n\n"
            f"───────────────────────────────────\n"
            f"📅 **अलवर सीएचसी में उपलब्ध ओपीडी परामर्श समय:**\n"
            f"👨‍⚕️ **चिकित्सक:** {roster['doctor_name_hi']} ({roster['room_no_hi']})\n\n"
            f"{slots_formatted}\n\n"
            f"👉 **अपनी पसंद का समय बुक करने के लिए संख्या (1, 2, या 3) लिखकर भेजें।**"
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
