from __future__ import annotations

import re
import unicodedata
from typing import Tuple, List, Dict, Any, Optional

# Verified Government of India National Helplines
HELPLINE_AMBULANCE = "108"
HELPLINE_NATIONAL_EMERGENCY = "112"
HELPLINE_TELE_MANAS = "14416"          # Tele Mental Health Assistance and Networking Across States
HELPLINE_TELE_MANAS_TOLLFREE = "1800-891-4416"
HELPLINE_KIRAN_MENTAL_HEALTH = "1800-599-0019"

# ==============================================================================
# 1. CRITICAL EMERGENCY TRIPWIRE SPECIFICATIONS
# ==============================================================================

EMERGENCY_DEFINITIONS = [
    {
        "category": "cardiac_chest_pain",
        "reason_hi": "तीव्र सीने में दर्द / संभावित हृदयघात (Acute Chest Pain / Heart Attack Suspicion)",
        "reason_en": "Acute chest pain, pressure, or suspected acute coronary syndrome",
        "patterns": [
            r"(?:सीन[ेा]|छ[ाा]ती)\s*(?:म[ेै][ंँ]?|पर)?\s*(?:\S+\s*){0,3}(?:दर्द|भारीपन|जकड़न|दबाव|त[ेै]ज)",
            r"ह[ृद]दय\s*(?:रोग|घात|दौरा)",
            r"\b(?:chest|chhati|seena|seene)\s*(?:me|mein|pe|par)?\s*(?:\w+\s*){0,3}(?:pain|pressure|tightness|heavy|dard)\b",
            r"\bheart\s*attack\b",
            r"\bangina\b",
            r"\bseene\s*m\w*\s*(?:\w+\s*){0,2}dard\b",
            r"\bchhati\s*m\w*\s*(?:\w+\s*){0,2}dard\b",
        ],
    },
    {
        "category": "respiratory_distress",
        "reason_hi": "गंभीर श्वसन संकट / सांस लेने में अत्यधिक तकलीफ (Severe Respiratory Distress)",
        "reason_en": "Severe respiratory distress, gasping, or blue lips/cyanosis",
        "patterns": [
            r"स[ाा][ंँ]स\s*(?:ल[ेे]न[ेे]\s*म[ेै][ंँ]?|नह[ीीं]|न\s*आ|रुक|फूल|घुट|तकलीफ|दिक्कत)",
            r"दम\s*घुट",
            r"न[ीि]ल[ेे]\s*ह[ोंो]ठ",
            r"\b(?:unable\s*to\s*breathe|cannot\s*breathe|gasping|breathlessness|stridor|choking)\b",
            r"\b(?:blue\s*lips|cyanosis)\b",
            r"\bsaans\s*(?:nahi|ni)\s*(?:aa\s*rahi|le\s*pa\s*raha)\b",
            r"\bsaans\s*(?:lene)?\s*m\w*\s*(?:\w+\s*){0,2}(?:takleef|dikkat|pareshani|problem)\b",
            r"\bdam\s*ghut\b",
        ],
    },
    {
        "category": "active_hemorrhage_hemoptysis",
        "reason_hi": "गंभीर रक्तस्राव / बलगम अथवा उल्टी में खून (Severe Hemorrhage / Coughing Blood)",
        "reason_en": "Coughing or vomiting blood, or uncontrolled heavy bleeding",
        "patterns": [
            r"बलगम\s*(?:म[ेै][ंँ]?\s*)?ख[ूु]न",
            r"ख[ूु]न\s*क[ीि]\s*उल्ट[ीि]",
            r"उल्ट[ीि]\s*(?:म[ेै][ंँ]?\s*)?ख[ूु]न",
            r"म[ुु]ंह\s*स[ेे]\s*ख[ूु]न",
            r"(?:ब[ेे]तह[ाा]श[ाा]|अत्यधिक|लगातार)\s*ख[ूु]न",
            r"\b(?:coughing|vomiting)\s*(?:\w+\s*){0,8}blood\b",
            r"\b(?:hemoptysis|hematemesis|profuse\s*bleeding)\b",
            r"\bbalgam\s*m\w*\s*khoon\b",
            r"\bkhoon\s*ki\s*ulti\b",
            r"\bulti\s*m\w*\s*khoon\b",
        ],
    },
    {
        "category": "unconsciousness_coma_shock",
        "reason_hi": "बेहोशी / अचेत अवस्था अथवा भ्रम (Unconsciousness / Altered Sensorium)",
        "reason_en": "Unconsciousness, coma, or profound confusion",
        "patterns": [
            r"ब[ेे]ह[ोे]श",
            r"अच[ेे]त",
            r"ह[ोे]श\s*(?:म[ेै][ंँ]?\s*)?नह[ीीं]",
            r"\b(?:unconscious|fainted|passed\s*out|unresponsive|coma|stupor)\b",
            r"\bbehosh\b",
            r"\bhosh\s*m\w*\s*nahi\b",
        ],
    },
    {
        "category": "seizures_convulsions",
        "reason_hi": "दौरे पड़ना / मिर्गी का झटका (Seizures / Convulsions)",
        "reason_en": "Active seizures, fits, or epileptic status",
        "patterns": [
            r"द[ौो]र[ेा]\s*पड़",
            r"मिर?ग[ीि]",
            r"झटक[ेे]\s*आ\s*रह[ेे]",
            r"\b(?:seizure|seizures|convulsion|convulsions|epilepsy|jerking|fits)\b",
            r"\bdaur[ea]\s*pad\b",
            r"\bmirgi\b",
        ],
    },
    {
        "category": "stroke_signs",
        "reason_hi": "लकवा / स्ट्रोक के लक्षण (Stroke Symptoms / Paralysis)",
        "reason_en": "Signs of acute stroke, face droop, slurred speech, or hemiplegia",
        "patterns": [
            r"लकव[ाा]",
            r"पक?ष[ाा]घ[ाा]त",
            r"म[ुु]ंह\s*ट[ेे]ढ़[ाा]",
            r"च[ेे]हर[ाे]\s*ट[ेे]ढ़[ाा]",
            r"बोल[ीि]\s*लड़खड़ा",
            r"आध[ाा]\s*शर[ीि]र\s*स[ुु]न्न",
            r"\b(?:stroke|facial\s*droop|paralysis|slurred\s*speech|hemiplegia)\b",
            r"\blakwa\b",
        ],
    },
    {
        "category": "snake_or_animal_bite",
        "reason_hi": "सर्प दंश / जहरीले जीव का काटना (Snake Bite / Envenomation)",
        "reason_en": "Snake bite, scorpion sting, or deep animal bite",
        "patterns": [
            r"स[ाा][ंँ]प\s*(?:न[ेे]\s*)?क[ाा]ट",
            r"सर्प\s*दंश",
            r"जहर[ीि]ल[ेे]\s*क[ीि]ड़[ेे]\s*न[ेे]\s*क[ाा]ट",
            r"\b(?:snake\s*bite|bitten\s*by\s*snake|scorpion\s*sting|venomous\s*bite)\b",
            r"\bsaap\s*(?:ne)?\s*kat\b",
            r"\bsnake\s*(?:ne)?\s*kat\b",
        ],
    },
    {
        "category": "poisoning_overdose",
        "reason_hi": "विषाक्तता / जहरीला पदार्थ निगलना (Poisoning / Toxic Ingestion)",
        "reason_en": "Poisoning, pesticide ingestion, or drug overdose",
        "patterns": [
            r"जह?र\s*(?:ख[ाा]|प[ीि]|निगल)",
            r"क[ीि]टन[ाा]शक",
            r"फिन[ाा]इल\s*प[ीि]",
            r"\b(?:poison|poisoning|pesticide|ingested\s*acid|overdose|swallowed\s*pesticide)\b",
            r"\bzeher\b",
        ],
    },
    {
        "category": "severe_burns",
        "reason_hi": "गंभीर जलन / आग से झुलसना (Severe Burns / Inhalation Burns)",
        "reason_en": "Extensive burns, chemical burns, or inhalation injury",
        "patterns": [
            r"झ[ुु]लस",
            r"ब[ुु]र[ीि]\s*तरह\s*जल",
            r"\b(?:burn|burns|burned|scald)\b",
            r"\bjhulas\b",
        ],
    },
    {
        "category": "obstetric_emergency",
        "reason_hi": "गर्भावस्था में आपातकालीन रक्तस्राव अथवा प्रसव पीड़ा (Obstetric Emergency)",
        "reason_en": "Pregnancy with heavy vaginal bleeding, extreme pain, or lack of fetal movement",
        "patterns": [
            r"गर्भ\w*\s*(?:म[ेै][ंँ]?\s*)?(?:ख[ूु]न|रक्तस्राव|bleeding)",
            r"गर्भवती\s*(?:\S+\s*){0,4}(?:रक्तस्राव|ख[ूु]न|bleeding)",
            r"बच[्\s]?च[ाे]\s*(?:हिल\s*नह[ीीं]|नह[ीीं]\s*हिल)",
            r"\b(?:pregnancy\s*bleeding|vaginal\s*bleeding|fetal\s*movement)\b",
            r"\bgarbh\w*\s*(?:\w+\s*){0,3}(?:khoon|bleeding)\b",
            r"\bbachh?a\s*hil\s*nahi\b",
        ],
    },
    {
        "category": "suicidal_ideation",
        "reason_hi": "आत्महत्या अथवा स्वयं को नुकसान पहुंचाने का विचार (Suicidal Crisis / Self-Harm)",
        "reason_en": "Suicidal ideation, acute crisis, or intent of self-harm",
        "patterns": [
            r"आत्मह?त्या",
            r"ख[ुु]दक[ुु]श[ीि]",
            r"म[ाा]र\s*ड[ाा]लन[ेे]\s*क[ाा]\s*मन",
            r"ज[ीि]न[ाा]\s*नह[ीीं]\s*च[ाा]ह",
            r"मरन[ेे]\s*क[ाा]\s*मन",
            r"\b(?:suicide|suicidal|kill\s*myself|end\s*my\s*life|want\s*to\s*die)\b",
            r"\baatmahatya\b",
            r"\bkhudkushi\b",
            r"\bmarne\s*ka\s*man\b",
        ],
    },
    {
        "category": "severe_allergic_anaphylaxis",
        "reason_hi": "तीव्र एलर्जी / एनाफिलेक्सिस (Severe Allergic Reaction / Anaphylaxis)",
        "reason_en": "Anaphylaxis, airway swelling, or severe acute allergic reaction",
        "patterns": [
            r"गले\s*म[ेै][ंँ]?\s*स[ूु]जन\s*और\s*स[ाा][ंँ]स",
            r"चेहर[ेे]\s*पर\s*अचानक\s*भारी\s*स[ूु]जन",
            r"\b(?:anaphylaxis|throat\s*(?:closing|swelling)|allergic\s*reaction)\b",
        ],
    },
    {
        "category": "meningitis_signs",
        "reason_hi": "गर्दन अकड़ना और तेज बुखार / मेनिनजाइटिस (Meningitis Signs / Stiff Neck)",
        "reason_en": "High fever with neck stiffness and photophobia/confusion",
        "patterns": [
            r"गर्द?दन\s*(?:\S+\s*){0,3}अकड़",
            r"\b(?:stiff\s*neck|neck\s*stiffness|meningitis)\b",
            r"\bgardan\s*(?:\w+\s*){0,2}akad\b",
        ],
    },
]

# ==============================================================================
# 2. NEGATION PATTERNS AND CLAUSE BOUNDARIES
# ==============================================================================

CLAUSE_DELIMITERS = re.compile(
    r"[,;.\!?|\n]|\s+(?:aur|और|tatha|तथा|lekin|लेकिन|kintu|किन्तु|magar|मगर|par|पर|and|but|yet)\s+",
    re.IGNORECASE,
)

NEGATION_PREFIXES = [
    r"\bno\b",
    r"\bnot\b",
    r"\bwithout\b",
    r"\bdenies\b",
    r"\bruled\s*out\b",
    r"\bfree\s*of\b",
    r"\bzero\b",
    r"\bnahi\s+(?:hai\s+)?",
    r"नह[ीीं]\s*(?:है\s*)?",
]

NEGATION_SUFFIXES = [
    r"नह[ीीं]",
    r"\bnahi\b",
    r"\bna\b",
    r"\babsent\b",
    r"\bruled\s*out\b",
    r"\bzero\b",
]


def normalize_text(text: str) -> str:
    """Normalize unicode characters, accents, and spacing."""
    if not text:
        return ""
    norm = unicodedata.normalize("NFKC", text)
    norm = norm.lower()
    norm = re.sub(r"\s+", " ", norm).strip()
    return norm


def is_negated(text: str, match_start: int, match_end: int) -> bool:
    """
    Check if a matched symptom pattern is negated in context.
    Restricts search strictly to the enclosing clause so that secondary negated
    actions (e.g. 'बेहोश हो गया और उठ नहीं रहा' or 'behosh hai, aankhein nahi khol raha')
    do NOT falsely cancel life-threatening emergency detections.
    """
    pre_raw = text[:match_start]
    delims_pre = list(CLAUSE_DELIMITERS.finditer(pre_raw))
    pre_clause = pre_raw[delims_pre[-1].end():] if delims_pre else pre_raw[-35:]

    post_raw = text[match_end:]
    delim_post = CLAUSE_DELIMITERS.search(post_raw)
    post_clause = post_raw[:delim_post.start()] if delim_post else post_raw[:35]

    # Check English/prefix negations (e.g., "no chest pain", "denies breathlessness")
    for np in NEGATION_PREFIXES:
        if re.search(np, pre_clause, re.IGNORECASE):
            return True

    # Check suffix negations (e.g., "सीने में दर्द नहीं है", "dard nahi hai", "nahi hui hai")
    for ns in NEGATION_SUFFIXES:
        if re.search(ns, post_clause, re.IGNORECASE):
            return True

    return False


class SafetyService:
    """
    Layered clinical emergency detection service:
    1. Comprehensive regex on normalized text (Devanagari, Hinglish, English)
    2. Precision negation handling (prevents false positives like 'no chest pain')
    3. Category-specific emergency labeling
    4. Culturally tuned, action-oriented crisis guidance (108 Ambulance / Tele-MANAS)
    """

    @classmethod
    def scan_for_emergencies(cls, text: str) -> Tuple[bool, List[str], List[Dict[str, Any]]]:
        """
        Scan input text for life-threatening emergencies.
        Returns:
            (is_emergency: bool, reasons_list: List[str], hits_metadata: List[Dict])
        """
        if not text or not text.strip():
            return False, [], []

        norm = normalize_text(text)
        reasons: List[str] = []
        hits: List[Dict[str, Any]] = []

        for defn in EMERGENCY_DEFINITIONS:
            category = defn["category"]
            reason_str = defn["reason_hi"]

            category_hit = False
            for pat in defn["patterns"]:
                for match in re.finditer(pat, norm, re.IGNORECASE):
                    # Check for negation
                    if is_negated(norm, match.start(), match.end()):
                        continue  # Negated phrase, skip

                    category_hit = True
                    hits.append({
                        "category": category,
                        "matched_text": match.group(0),
                        "reason": reason_str,
                    })
                    break  # Hit confirmed for this pattern

                if category_hit:
                    reasons.append(reason_str)
                    break  # Category satisfied

        is_emergency = len(reasons) > 0
        return is_emergency, reasons, hits

    @classmethod
    def build_emergency_directive_response(
        cls,
        reasons: List[str],
        hits: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        Generate empathetic, high-urgency emergency directives.
        Dispatches 108 Ambulance directives, first-aid instructions, and
        Tele-MANAS for suicide/mental health crisis.
        """
        is_suicidal = False
        if hits:
            is_suicidal = any(h.get("category") == "suicidal_ideation" for h in hits)
        else:
            is_suicidal = any("आत्महत्या" in r or "suicide" in r.lower() for r in reasons)

        reasons_bullet = "\n".join([f"  🚨 **{r}**" for r in reasons])

        if is_suicidal:
            # Tele-MANAS crisis response
            return (
                "🚨 **आपातकालीन मानसिक स्वास्थ्य सहायता (CRITICAL MENTAL HEALTH CRISIS)**\n\n"
                "आप अकेले नहीं हैं, और आपकी ज़िंदगी बेहद अनमोल है। कृपया तुरंत बात करें:\n\n"
                f"📞 **टेली-मानस (Tele-MANAS) हेल्पलाइन (24x7 निःशुल्क):** `{HELPLINE_TELE_MANAS}` या `{HELPLINE_TELE_MANAS_TOLLFREE}`\n"
                f"📞 **किरण (KIRAN) राष्ट्रीय हेल्पलाइन:** `{HELPLINE_KIRAN_MENTAL_HEALTH}`\n"
                f"📞 **राष्ट्रीय आपातकालीन सेवा:** `{HELPLINE_NATIONAL_EMERGENCY}`\n\n"
                "कृपया तुरंत अपने किसी करीबी परिजन को बताएं या नजदीकी स्वास्थ्य केंद्र पहुंचे। "
                "हम आपके साथ हैं।"
            )

        # Standard Acute Physical Emergency (108 Ambulance)
        return (
            "🚨 **आपातकालीन चेतावनी (CRITICAL EMERGENCY ALERT)**\n\n"
            "आपके बताए लक्षणों में तत्काल जीवन-रक्षक देखभाल की आवश्यकता है:\n"
            f"{reasons_bullet}\n\n"
            f"📞 **कृपया तुरंत 108 एम्बुलेंस डायल करें (Call {HELPLINE_AMBULANCE} Ambulance Now)**\n"
            f"📞 **राष्ट्रीय आपातकालीन नंबर:** `{HELPLINE_NATIONAL_EMERGENCY}`\n\n"
            "⚠️ **तत्काल निर्देश:**\n"
            "• नियमित ओपीडी का इंतजार न करें। तुरंत निकटतम सीएचसी / जिला अस्पताल की इमरजेंसी में पहुंचे।\n"
            "• मरीज को अकेला न छोड़ें। सांस लेने में कठिनाई होने पर सीधा बैठाएं।\n"
            "• बेहोशी या छाती में दर्द होने पर कोई ठोस भोजन या पेय न दें।"
        )
