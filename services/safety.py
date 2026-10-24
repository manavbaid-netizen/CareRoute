from __future__ import annotations

import re
import unicodedata
from typing import Any

# Verified Government of India National Helplines
HELPLINE_AMBULANCE = "108"
HELPLINE_NATIONAL_EMERGENCY = "112"
HELPLINE_TELE_MANAS = "14416"  # Tele Mental Health Assistance and Networking Across States
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
    norm = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"\s+", " ", norm).strip()


def is_negated(text: str, match_start: int, match_end: int) -> bool:
    """
    Check if a matched symptom pattern is negated in context.
    Restricts search strictly to the enclosing clause so that secondary negated
    actions (e.g. 'बेहोश हो गया और उठ नहीं रहा' or 'behosh hai, aankhein nahi khol raha')
    do NOT falsely cancel life-threatening emergency detections.
    """
    pre_raw = text[:match_start]
    delims_pre = list(CLAUSE_DELIMITERS.finditer(pre_raw))
    pre_clause = pre_raw[delims_pre[-1].end() :] if delims_pre else pre_raw[-35:]

    post_raw = text[match_end:]
    delim_post = CLAUSE_DELIMITERS.search(post_raw)
    post_clause = post_raw[: delim_post.start()] if delim_post else post_raw[:35]

    # Check English/prefix negations (e.g., "no chest pain", "denies breathlessness")
    if any(re.search(np, pre_clause, re.IGNORECASE) for np in NEGATION_PREFIXES):
        return True

    # Check suffix negations (e.g., "सीने में दर्द नहीं है", "dard nahi hai", "nahi hui hai")
    return any(re.search(ns, post_clause, re.IGNORECASE) for ns in NEGATION_SUFFIXES)


class SafetyService:
    """
    Layered clinical emergency detection service:
    1. Comprehensive regex on normalized text (Devanagari, Hinglish, English)
    2. Precision negation handling (prevents false positives like 'no chest pain')
    3. Category-specific emergency labeling
    4. Culturally tuned, action-oriented crisis guidance (108 Ambulance / Tele-MANAS)
    """

    @classmethod
    def scan_for_emergencies(cls, text: str) -> tuple[bool, list[str], list[dict[str, Any]]]:
        """
        Scan input text for life-threatening emergencies.
        Returns:
            (is_emergency: bool, reasons_list: List[str], hits_metadata: List[Dict])
        """
        if not text or not text.strip():
            return False, [], []

        norm = normalize_text(text)
        reasons: list[str] = []
        hits: list[dict[str, Any]] = []

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
                    hits.append(
                        {
                            "category": category,
                            "matched_text": match.group(0),
                            "reason": reason_str,
                        }
                    )
                    break  # Hit confirmed for this pattern

                if category_hit:
                    reasons.append(reason_str)
                    break  # Category satisfied

        is_emergency = len(reasons) > 0
        return is_emergency, reasons, hits

    @classmethod
    def build_emergency_directive_response(
        cls,
        reasons: list[str],
        hits: list[dict[str, Any]] | None = None,
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

    @classmethod
    def check_acute_respiratory_risk(cls, text: str) -> dict[str, Any]:
        """
        Check for acute high-acuity respiratory markers:
        If complaint includes cough (even < 2 weeks) AND explicit indicators of severe
        breathlessness ("सांस फूलना", "दम घुटना", "breathlessness", "difficulty breathing")
        OR high fever ("तेज़ बुखार", "high fever", ">102"), escalate urgency to Moderate-to-High
        under General Medicine / Emergency evaluation.
        Preserves clause-aware negation rules (e.g., 'सांस नहीं फूल रही' is not flagged).
        """
        if not text or not text.strip():
            return {
                "is_acute_respiratory_risk": False,
                "has_cough": False,
                "has_breathlessness": False,
                "has_high_fever": False,
                "has_blood_in_sputum": False,
                "markers_detected": [],
            }

        norm = normalize_text(text)

        # 1. Cough detection (with negation check)
        cough_patterns = [
            r"(?:खांसी|खंखा|कफ|बलगम)",
            r"\b(?:cough|coughing|khansi|balgam|sputum)\b",
        ]
        has_cough = False
        for pat in cough_patterns:
            for match in re.finditer(pat, norm, re.IGNORECASE):
                if not is_negated(norm, match.start(), match.end()):
                    has_cough = True
                    break
            if has_cough:
                break

        # 2. Severe breathlessness indicators (with negation check)
        breathlessness_patterns = [
            r"स[ाा][ंँ]स\s*(?:फूल|घुट|तकलीफ|दिक्कत|ल[ेे]न[ेे]\s*म[ेै][ंँ]?\s*(?:दिक्कत|तकलीफ)|नह[ीीं]\s*आ)",
            r"दम\s*घुट",
            r"\b(?:breathlessness|difficulty\s*breathing|shortness\s*of\s*breath|dyspnea|gasping|cannot\s*breathe)\b",
            r"\bsaans\s*(?:phool|ghut|lene\s*m\w*\s*(?:takleef|dikkat)|nahi\s*aa\s*rahi)\b",
            r"\bdam\s*ghut\b",
        ]
        has_breathlessness = False
        matched_breathlessness = None
        for pat in breathlessness_patterns:
            for match in re.finditer(pat, norm, re.IGNORECASE):
                if not is_negated(norm, match.start(), match.end()):
                    has_breathlessness = True
                    matched_breathlessness = match.group(0)
                    break
            if has_breathlessness:
                break

        # 3. High fever indicators (with negation check)
        high_fever_patterns = [
            r"त[ेै]ज़\s*ब[ुु]ख[ाा]र",
            r"त[ेै]ज\s*ब[ुु]ख[ाा]र",
            r"अत्यधिक\s*ब[ुु]ख[ाा]र",
            r"त[ेै]ज\s*ताप",
            r"\b(?:high\s*(?:grade\s*)?fever|high\s*temp(?:erature)?|severe\s*fever|tez\s*bukhar)\b",
            r"(?:> ?102|102|103|104)\s*(?:°?\s*[fc]|degree|डिग्री)?",
        ]
        has_high_fever = False
        matched_high_fever = None
        for pat in high_fever_patterns:
            for match in re.finditer(pat, norm, re.IGNORECASE):
                if not is_negated(norm, match.start(), match.end()):
                    has_high_fever = True
                    matched_high_fever = match.group(0)
                    break
            if has_high_fever:
                break

        # 4. Blood in sputum indicators (with negation check)
        blood_sputum_patterns = [
            r"बलगम\s*(?:म[ेै][ंँ]?\s*)?ख[ूु]न",
            r"ख[ूु]न\s*क[ेे]\s*छींट[ेे]",
            r"\b(?:blood\s*(?:in|streaked|stained)?\s*(?:sputum|phlegm)|hemoptysis|balgam\s*m\w*\s*khoon)\b",
        ]
        has_blood_in_sputum = False
        matched_blood = None
        for pat in blood_sputum_patterns:
            for match in re.finditer(pat, norm, re.IGNORECASE):
                if not is_negated(norm, match.start(), match.end()):
                    has_blood_in_sputum = True
                    matched_blood = match.group(0)
                    break
            if has_blood_in_sputum:
                break

        markers = []
        if has_breathlessness:
            markers.append(f"Severe Breathlessness / सांस फूलना ({matched_breathlessness})")
        if has_high_fever:
            markers.append(f"High Fever / तेज़ बुखार ({matched_high_fever})")
        if has_blood_in_sputum:
            markers.append(f"Blood in Sputum / बलगम में खून ({matched_blood})")

        is_risk = has_cough and (has_breathlessness or has_high_fever or has_blood_in_sputum)

        guidance_hi = (
            "⚠️ **तीव्र श्वसन मूल्यांकन आवश्यक (Urgent Respiratory Evaluation):**\n"
            "खांसी के साथ सांस फूलने या तेज़ बुखार के लक्षण संभावित गंभीर निमोनिया, ब्रोंकाइटिस या फेफड़ों के तीव्र संक्रमण का संकेत हो सकते हैं। "
            "कृपया नियमित ओपीडी में देरी न करें और आज ही नजदीकी सामुदायिक स्वास्थ्य केंद्र (CHC) के डॉक्टर को दिखाएं। "
            "मरीज को आरामदायक स्थिति में सीधा बैठाएं और पर्याप्त पानी पिलाएं। यदि सांस लेने में अत्यधिक कठिनाई हो तो तुरंत 108 पर संपर्क करें।"
        )
        guidance_en = (
            "High-acuity respiratory markers detected (cough accompanied by breathlessness, high-grade fever, or blood-streaked sputum). "
            "This presentation warrants urgent same-day in-person medical evaluation to assess for severe lower respiratory infection, "
            "pneumonia, or bronchospasm. Sit upright in a comfortable position, maintain hydration, and consult the CHC Medical Officer today. "
            "Call 108 immediately if respiratory distress intensifies."
        )

        return {
            "is_acute_respiratory_risk": is_risk,
            "has_cough": has_cough,
            "has_breathlessness": has_breathlessness,
            "has_high_fever": has_high_fever,
            "has_blood_in_sputum": has_blood_in_sputum,
            "markers_detected": markers,
            "recommended_urgency": "High (Urgent Same-Day / तत्काल परामर्श)",
            "recommended_specialty": "General Medicine",
            "recommended_specialty_hindi": "सामान्य चिकित्सा एवं श्वसन रोग (General Medicine / Chest)",
            "guidance_hi": guidance_hi,
            "guidance_en": guidance_en,
        }
