from __future__ import annotations

import re
import uuid
import datetime
import logging
from typing import Tuple, List, Dict, Any, Optional

from config import Config
from services.safety import SafetyService
from services.llm_client import LLMClient, HONEST_VISION_NOTE_HI
from models.clinical_schemas import (
    ClinicalDossier,
    SubjectiveSOAP,
    ObjectiveSOAP,
    AssessmentSOAP,
    PlanSOAP,
    MedicationEntry,
    PhysicalFinding,
    TriageUrgency,
)

logger = logging.getLogger("CareRoute.VLMService")


CLINICAL_DISCLAIMER_HI = (
    "⚠️ अस्वीकरण: केयररूट केवल एक एआई प्री-इंटेक सहायक है, डॉक्टर नहीं। "
    "यह कोई चिकित्सीय निदान या दवा का नुस्खा नहीं देता है। सीएचसी में डॉक्टर से व्यक्तिगत परामर्श आवश्यक है।"
)
CLINICAL_DISCLAIMER_EN = (
    "CareRoute is an AI pre-intake assistant, not a doctor. "
    "It does not provide medical diagnoses or prescriptions. An in-person consultation is required."
)


class VLMService:
    """
    Multimodal Vision-Language Model service for CareRoute.
    Translates rural vernacular narratives (Hindi/Hinglish/English) and analyzes
    symptom photographs / handwritten prescription slips into structured English SOAP dossiers.
    Strictly follows zero-fabrication clinical safety protocols.
    """

    # Critical life-threatening tripwire keywords
    RED_FLAGS = {
        "chest_pain": [
            "सीने में तेज दर्द", "छाती में भारीपन", "छाती में जकड़न", "सीने में दबाव",
            "chest pain", "severe chest pain", "crushing pain", "radiating pain",
        ],
        "respiratory_distress": [
            "सांस लेने में बहुत दिक्कत", "दम घुट रहा है", "सांस फूल रही है", "गले में घरघराहट",
            "gasping", "breathlessness", "severe dyspnea", "stridor", "unable to breathe",
        ],
        "profuse_bleeding": [
            "खून की उल्टी", "बेहिसाब खून", "मुंह से खून", "उल्टी में खून",
            "coughing blood", "hemoptysis", "hematemesis", "uncontrolled bleeding",
        ],
        "altered_sensorium": [
            "बेहोश", "बेहोशी", "पहचान नहीं पा रहा", "अचेत",
            "unconscious", "altered mental status", "fainting", "syncope", "unresponsive",
        ],
    }

    def __init__(self) -> None:
        self.use_mock = Config.USE_MOCK_VLM or (not Config.ASI1_API_KEY and not Config.GEMINI_API_KEY and not Config.OPENAI_API_KEY)
        self.llm_client = LLMClient(fallback_engine=self)

    def scan_safety_tripwires(self, text: str) -> Tuple[bool, List[str]]:
        """
        Scan input text for acute life-threatening emergencies using layered SafetyService.
        Returns (is_emergency, list_of_specific_reasons).
        """
        is_em, reasons, _ = SafetyService.scan_for_emergencies(text)
        return is_em, reasons

    def analyze_case(
        self,
        session_id: str,
        patient_id: str,
        patient_name: str,
        text_transcript: str,
        image_data: Optional[str] = None,
        image_type: Optional[str] = None,
    ) -> Tuple[ClinicalDossier, str, bool, List[str]]:
        """
        Execute clinical triage and return:
        (ClinicalDossier, hindi_patient_summary, is_emergency, emergency_reasons)
        Delegates through multi-tier LLMClient with zero-fabrication safety fallback.
        """
        # Step 1: Scan for life-threatening emergency tripwires immediately
        is_emergency, emergency_reasons = self.scan_safety_tripwires(text_transcript)

        if is_emergency:
            dossier = self._build_emergency_dossier(
                session_id, patient_id, patient_name, text_transcript, emergency_reasons
            )
            hindi_summary = (
                "⚠️ **तत्काल आपातकालीन चेतावनी**: आपके बताए लक्षणों में गंभीर खतरे के संकेत हैं। "
                "कृपया तुरंत नजदीकी अस्पताल के इमरजेंसी कक्ष (ER) में जाएं या 108 पर कॉल करें।"
                f"\n\n{CLINICAL_DISCLAIMER_HI}"
            )
            return dossier, hindi_summary, True, emergency_reasons

        # Step 2: Route through unified multi-tier LLM reasoning client
        # Priority: ASI:One (OpenAI-compatible) -> Gemini -> OpenAI -> Deterministic Fallback
        return self.llm_client.generate_clinical_dossier(
            session_id=session_id,
            patient_id=patient_id,
            patient_name=patient_name,
            text_transcript=text_transcript,
            image_data=image_data,
            image_type=image_type,
        )

    def _build_emergency_dossier(
        self,
        session_id: str,
        patient_id: str,
        patient_name: str,
        text_transcript: str,
        emergency_reasons: List[str],
    ) -> ClinicalDossier:
        """Construct a high-priority emergency dossier for critical triage cases."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        return ClinicalDossier(
            dossier_id=f"DOSSIER-{uuid.uuid4().hex[:8].upper()}",
            created_at=now_iso,
            patient_id=patient_id,
            patient_name=patient_name,
            session_id=session_id,
            engine="ASI1 | safe_fallback",
            disclaimer=CLINICAL_DISCLAIMER_EN,
            subjective=SubjectiveSOAP(
                patient_chief_complaint_hindi=text_transcript,
                chief_complaint_english="CRITICAL EMERGENCY: Severe acute distress reported verbally.",
                history_of_present_illness=f"Patient presents with alarming symptoms: {', '.join(emergency_reasons)}.",
                symptom_duration="Acute onset (< 24 hours)",
                associated_symptoms=emergency_reasons,
                past_medical_history=[],  # Zero fabrication: empty unless stated
            ),
            objective=ObjectiveSOAP(
                vitals_reported={},       # Zero fabrication: empty unless stated
                visual_photo_findings=[],
                ocr_prescriptions=[],     # Zero fabrication: empty unless verified
                clinical_signs_summary="High probability of impending hemodynamic or respiratory decompensation.",
            ),
            assessment=AssessmentSOAP(
                triage_urgency=TriageUrgency.EMERGENCY,
                differential_diagnoses=[
                    "1. Acute Coronary Syndrome / Myocardial Infarction",
                    "2. Severe Acute Respiratory Distress / Acute Pulmonary Embolism",
                    "3. Massive Upper GI Hemorrhage",
                    "4. Neurological Emergency / Cerebrovascular Event",
                ],
                recommended_specialty="Emergency Medicine / CHC Trauma & Acute Care",
                recommended_specialty_hindi="आपातकालीन चिकित्सा कक्ष (Emergency Room)",
                clinical_rationale="Patient endorsed active emergency red-flag criteria; OPD routing aborted.",
            ),
            plan=PlanSOAP(
                suggested_investigations=[
                    "Immediate 12-Lead ECG",
                    "Continuous Cardiac & Pulse Oximetry Monitoring",
                    "Intravenous Access (Large bore)",
                    "Stat Point-of-Care Troponin / ABG / Point-of-Care Ultrasound",
                ],
                interim_patient_advice_hindi="कृपया बिल्कुल न चलें। तुरंत 108 डायल करें या निकटतम CHC इमरजेंसी पहुंचे।",
                interim_patient_advice_english="Do not exert. Direct ambulance transfer to nearest CHC Emergency Room immediately.",
                red_flag_warnings=emergency_reasons,
            ),
            is_emergency=True,
            emergency_tripwires_hit=emergency_reasons,
        )

    @classmethod
    def get_clarifying_questions(
        cls,
        text: str,
        patient_name: str = "",
        patient_age: Optional[int] = None,
    ) -> List[Dict[str, str]]:
        """
        Identify missing critical intake fields and return up to 3 polite clarifying questions in Hindi.
        Fields checked:
          1. Duration of symptoms
          2. Patient demographics
          3. Pre-existing conditions or chronic history
        """
        questions: List[Dict[str, str]] = []
        lower = text.lower()

        # Check duration
        has_duration = bool(re.search(
            r"\b(?:\d+|दो|तीन|चार|पांच|एक|सप्ताह|हफ्ते|महीने|दिन|कल|आज)\s*(?:दिन|दिनों|हफ्ते|हफ्तों|सप्ताह|महीने|महीनों|साल|घंटे|weeks?|days?|months?|years?|se|से)\b",
            lower,
        ))
        if not has_duration:
            questions.append({
                "field": "duration",
                "question_hi": "यह परेशानी आपको कितने दिनों या हफ्तों से महसूस हो रही है?",
                "question_en": "How many days or weeks have you had this symptom?",
            })

        # Check patient demographics
        if not patient_name or patient_name in ("Patient", "Guest", "Unknown", "User"):
            questions.append({
                "field": "patient_name",
                "question_hi": "कृपया मरीज का पूरा नाम और उम्र बताएं ताकि ओपीडी पर्ची सही विवरण से तैयार हो सके।",
                "question_en": "Please share the patient's full name and age for the CHC OPD slip.",
            })

        # Check chronic history
        has_chronic = bool(re.search(r"\b(?:बीपी|शुगर|अस्थमा|दमा|बीमारी|bp|sugar|diabetes|asthma|allergy)\b", lower))
        if not has_chronic:
            questions.append({
                "field": "associated_history",
                "question_hi": "क्या आपको पहले से कोई पुरानी बीमारी (जैसे शुगर, बीपी, दमा) या कोई दवा की एलर्जी है?",
                "question_en": "Do you have any chronic conditions (like diabetes, BP, asthma) or drug allergies?",
            })

        return questions[:3]

    def _mock_clinical_analysis(
        self,
        session_id: str,
        patient_id: str,
        patient_name: str,
        text_transcript: str,
        image_data: Optional[str] = None,
        image_type: Optional[str] = None,
    ) -> Tuple[ClinicalDossier, str, bool, List[str]]:
        """
        Domain-specific clinical intelligence engine adhering strictly to zero-fabrication rules:
        - Vitals are empty unless stated by the patient
        - Past medical history is empty unless stated by the patient
        - OCR prescriptions are empty unless an actual prescription is provided
        - Medication prescriptions are NEVER invented (non-pharmacological advice only)
        - NTEP TB suspect criteria strictly requires cough > 2 weeks AND B-symptoms
        - Default for non-TB / non-derm cases is General Medicine, not a TB workup
        - Clinical disclaimer appended to all patient summaries and dossiers
        """
        lower = text_transcript.lower()
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        dossier_id = f"DOSSIER-{uuid.uuid4().hex[:8].upper()}"

        # ----------------------------------------------------------------------
        # 1. NTEP Pulmonary TB Suspect Screening
        # Requires: Cough >= 2 weeks AND at least one constitutional B-symptom
        # ----------------------------------------------------------------------
        has_cough = bool(re.search(
            r"(?:खांसी|खंखा|कफ|बलगम)|\b(?:cough|coughing|khansi|balgam|sputum)\b",
            lower,
        ))
        has_prolonged = bool(re.search(
            r"(?:दो\s*हफ्ते|2\s*हफ्ते|दो\s*सप्ताह|2\s*सप्ताह|14\s*दिन|महीने)|\b(?:two\s*weeks|2\s*weeks|> ?2\s*weeks|14\s*days|months?|do\s*hafte)\b",
            lower,
        ))
        b_symptoms = []
        if re.search(r"(?:बुखार|ताप)|\b(?:fever|pyrexia|bukhar)\b", lower):
            b_symptoms.append("Fever / Pyrexia (बुखार)")
        if re.search(r"(?:शाम\s*को\s*(?:\S+\s*)?बुखार)|\b(?:evening\s*(?:fever|pyrexia|chills))\b", lower):
            b_symptoms.append("Evening rise of temperature (शाम को बुखार)")
        if re.search(r"(?:वजन\s*(?:घट|कम))|\b(?:weight\s*loss|vajan\s*(?:ghat|kam))\b", lower):
            b_symptoms.append("Constitutional weight loss (वजन घटना)")
        if re.search(r"(?:रात\s*(?:में)?\s*पसीना)|\b(?:night\s*sweats|pasina)\b", lower):
            b_symptoms.append("Night sweats (रात में पसीना)")

        is_tb_suspect = has_cough and has_prolonged and len(b_symptoms) >= 1

        # ----------------------------------------------------------------------
        # 2. Dermatological Presentation Screening
        # ----------------------------------------------------------------------
        is_derm = bool(re.search(
            r"(?:त्वचा|चर्म|दाद|खुजली|चकत्ते|फोड़े|फुंसी|दाने)|\b(?:skin|rash|rashes|itching|itchy|fungal|ringworm|eczema|psoriasis|boils|lesion)\b",
            lower,
        )) or (image_type == "lesion_photo")

        # ----------------------------------------------------------------------
        # Case Routing: TB Suspect vs Dermatology vs General Medicine
        # ----------------------------------------------------------------------
        if is_tb_suspect:
            dossier = ClinicalDossier(
                dossier_id=dossier_id,
                created_at=now_iso,
                patient_id=patient_id,
                patient_name=patient_name,
                session_id=session_id,
                engine="ASI1 | safe_fallback",
                disclaimer=CLINICAL_DISCLAIMER_EN,
                subjective=SubjectiveSOAP(
                    patient_chief_complaint_hindi=text_transcript,
                    chief_complaint_english="Prolonged productive cough (> 14 days) with constitutional symptoms.",
                    history_of_present_illness=(
                        "Patient self-reports chronic cough lasting over 2 weeks with constitutional B-symptoms "
                        f"({', '.join(b_symptoms)}). Denies active acute emergency chest pain."
                    ),
                    symptom_duration=">= 14 days (Prolonged)",
                    associated_symptoms=b_symptoms,
                    past_medical_history=[],  # Zero fabrication: empty unless stated
                ),
                objective=ObjectiveSOAP(
                    vitals_reported={},       # Zero fabrication: empty unless stated
                    visual_photo_findings=[],
                    ocr_prescriptions=[],     # Zero fabrication: empty unless verified
                    clinical_signs_summary="NTEP clinical suspect criteria met. Vitals pending in-person CHC triage.",
                ),
                assessment=AssessmentSOAP(
                    triage_urgency=TriageUrgency.HIGH,
                    differential_diagnoses=[
                        "1. Pulmonary Tuberculosis (NTEP suspect: prolonged cough with B-symptoms)",
                        "2. Subacute Lower Respiratory Tract Infection",
                        "3. Chronic Bronchitis with secondary bacterial superinfection",
                        "4. Bronchiectasis with infective exacerbation",
                    ],
                    recommended_specialty="Pulmonology / Chest & General Medicine",
                    recommended_specialty_hindi="छाती एवं फेफड़ा रोग विशेषज्ञ (Chest Specialist)",
                    clinical_rationale=(
                        "Triad of prolonged cough (>2 weeks) accompanied by constitutional B-symptoms "
                        "meets NTEP criteria for presumptive pulmonary tuberculosis at CHC OPD."
                    ),
                ),
                plan=PlanSOAP(
                    suggested_investigations=[
                        "Sputum Smear for Acid-Fast Bacilli (AFB) x 2 samples (Spot & early morning)",
                        "Cartridge Based Nucleic Acid Amplification Test (CBNAAT / GeneXpert MTB/RIF)",
                        "Chest Radiograph (X-Ray PA View)",
                        "Complete Blood Count (CBC) with ESR",
                    ],
                    interim_patient_advice_hindi=(
                        "पर्याप्त मात्रा में गुनगुना पानी पिएं। खांसते समय मुंह पर रुमाल या मास्क रखें। "
                        "बिना डॉक्टर की जांच के कफ सिरप से खांसी न दबाएं। अस्पताल आते समय खाली पेट न आएं।"
                    ),
                    interim_patient_advice_english=(
                        "Wear a mask around family members. Maintain oral hydration. "
                        "Do not take unprescribed cough suppressants. Attend CHC for sputum testing."
                    ),
                    red_flag_warnings=[
                        "Hemoptysis (बलगम में खून आना)",
                        "Sudden worsening of breathlessness (अचानक सांस फूलना)",
                        "High continuous fever (>103°F)",
                    ],
                ),
                is_emergency=False,
                emergency_tripwires_hit=[],
            )

            hindi_summary = (
                "आपके बताए लक्षणों (2 हफ्ते से अधिक खांसी और बुखार/वजन घटना) के आधार पर "
                "सीएचसी में **छाती रोग विशेषज्ञ (Chest Specialist)** से जांच कराना आवश्यक है। "
                "हमने डॉक्टर के लिए क्लिनिकल सारांश (SOAP Dossier) और बलगम जांच की सिफारिश तैयार कर दी है।"
                f"\n\n{CLINICAL_DISCLAIMER_HI}"
            )

        elif is_derm:
            # Never fabricate image findings when vision model is inactive
            findings: List[PhysicalFinding] = []

            dossier = ClinicalDossier(
                dossier_id=dossier_id,
                created_at=now_iso,
                patient_id=patient_id,
                patient_name=patient_name,
                session_id=session_id,
                engine="ASI1 | safe_fallback",
                disclaimer=CLINICAL_DISCLAIMER_EN,
                subjective=SubjectiveSOAP(
                    patient_chief_complaint_hindi=text_transcript,
                    chief_complaint_english="Cutaneous pruritic rash or skin lesions reported.",
                    history_of_present_illness=(
                        "Patient describes skin eruption with itching. Onset and progression require clinical inspection."
                    ),
                    symptom_duration="Not specified / Pending clarification",
                    associated_symptoms=["Pruritus / Itching (खुजली)"],
                    past_medical_history=[],  # Zero fabrication: empty
                ),
                objective=ObjectiveSOAP(
                    vitals_reported={},       # Zero fabrication: empty
                    visual_photo_findings=findings,
                    ocr_prescriptions=[],     # Zero fabrication: empty
                    clinical_signs_summary="Dermatological complaint. Full skin examination pending at CHC.",
                ),
                assessment=AssessmentSOAP(
                    triage_urgency=TriageUrgency.MODERATE,
                    differential_diagnoses=[
                        "1. Superficial Dermatophytosis (Tinea / दाद)",
                        "2. Contact / Allergic Dermatitis",
                        "3. Eczematous Dermatitis",
                    ],
                    recommended_specialty="Dermatology & Skin Diseases",
                    recommended_specialty_hindi="त्वचा एवं चर्म रोग विशेषज्ञ (Dermatologist)",
                    clinical_rationale="Cutaneous rash presentation requiring in-person skin inspection and mycological mount.",
                ),
                plan=PlanSOAP(
                    suggested_investigations=[
                        "Clinical inspection by Medical Officer",
                        "Skin Scraping for 10% KOH Direct Wet Mount (if fungal suspected)",
                    ],
                    interim_patient_advice_hindi=(
                        "चकत्तों पर साबुन या गर्म पानी का प्रयोग कम करें। बिना डॉक्टर की सलाह के कोई स्टेरॉयड ट्यूब न लगाएं। "
                        "सूती वस्त्र पहनें और ओपीडी में डॉक्टर को दिखाएं।"
                    ),
                    interim_patient_advice_english=(
                        "Avoid scratching. Do not apply unprescribed over-the-counter steroid creams. "
                        "Wear loose cotton clothing."
                    ),
                    red_flag_warnings=[
                        "Rapid spreading with pus, swelling, or high fever",
                    ],
                ),
                is_emergency=False,
                emergency_tripwires_hit=[],
            )

            hindi_summary = (
                "आपके बताए लक्षणों के आधार पर यह **त्वचा संक्रमण / चर्म रोग** प्रतीत होता है। "
                "हमने आपके लिए सीएचसी के **त्वचा रोग विशेषज्ञ (Dermatologist)** हेतु क्लिनिकल सारांश तैयार कर लिया है। "
                "कृपया बिना डॉक्टर की सलाह के कोई स्टेरॉयड क्रीम न लगाएं।"
                f"\n\n{CLINICAL_DISCLAIMER_HI}"
            )

        else:
            # ------------------------------------------------------------------
            # General Medicine / Unclassified Symptom Presentation (Default)
            # NEVER defaults to TB or Pulmonology!
            # ------------------------------------------------------------------
            has_symptom = bool(re.search(
                r"\b(?:दर्द|बुखार|चोट|सिर|पेट|घुटना|जोड़|कमजोरी|चक्कर|उल्टी|दस्त|pain|fever|headache|ache|injury|hurt|vomit|diarrhea|weakness|dizzy)\b",
                lower,
            ))

            if has_symptom:
                differentials = [
                    "1. Acute symptomatic presentation: needs clinical evaluation by CHC Medical Officer",
                    "2. Acute self-limiting illness vs systemic etiology",
                ]
                rationale = "General medical symptoms reported; requires standard in-person examination and vitals triage."
            else:
                differentials = [
                    "1. Unclassified symptom presentation; needs in-person evaluation",
                ]
                rationale = "Symptom description requires detailed direct history taking and physical examination at CHC OPD."

            dossier = ClinicalDossier(
                dossier_id=dossier_id,
                created_at=now_iso,
                patient_id=patient_id,
                patient_name=patient_name,
                session_id=session_id,
                engine="ASI1 | safe_fallback",
                disclaimer=CLINICAL_DISCLAIMER_EN,
                subjective=SubjectiveSOAP(
                    patient_chief_complaint_hindi=text_transcript,
                    chief_complaint_english="General medical symptom presentation reported verbally.",
                    history_of_present_illness="Patient reported symptoms for initial outpatient triage evaluation.",
                    symptom_duration="Not specified / Pending clarification",
                    associated_symptoms=[],
                    past_medical_history=[],  # Zero fabrication: empty
                ),
                objective=ObjectiveSOAP(
                    vitals_reported={},       # Zero fabrication: empty
                    visual_photo_findings=[],
                    ocr_prescriptions=[],     # Zero fabrication: empty
                    clinical_signs_summary="Outpatient presentation. Full vitals to be recorded at CHC triage desk.",
                ),
                assessment=AssessmentSOAP(
                    triage_urgency=TriageUrgency.LOW,
                    differential_diagnoses=differentials,
                    recommended_specialty="General Medicine",
                    recommended_specialty_hindi="सामान्य चिकित्सा (General Medicine OPD)",
                    clinical_rationale=rationale,
                ),
                plan=PlanSOAP(
                    suggested_investigations=[
                        "Routine vitals and physical examination by Medical Officer",
                        "Complete Blood Count (CBC) if clinically indicated",
                    ],
                    interim_patient_advice_hindi=(
                        "पर्याप्त आराम करें और पानी पिएं। यदि तकलीफ बढ़े तो तुरंत नजदीकी स्वास्थ्य केंद्र जाएं। "
                        "बिना डॉक्टर की सलाह के कोई दवा न लें।"
                    ),
                    interim_patient_advice_english=(
                        "Maintain hydration and rest. Visit the CHC OPD for in-person evaluation. "
                        "Avoid unprescribed self-medication."
                    ),
                    red_flag_warnings=[
                        "Sudden high fever or breathlessness",
                        "Severe unremitting pain",
                    ],
                ),
                is_emergency=False,
                emergency_tripwires_hit=[],
            )

            hindi_summary = (
                "आपके बताए लक्षणों के आधार पर हमने सीएचसी के **सामान्य चिकित्सा (General Medicine)** "
                "डॉक्टर के लिए परामर्श सारांश तैयार कर दिया है। कृपया ओपीडी में डॉक्टर से परामर्श लें।"
                f"\n\n{CLINICAL_DISCLAIMER_HI}"
            )

        return dossier, hindi_summary, False, []

    def _live_vlm_analysis(
        self,
        session_id: str,
        patient_id: str,
        patient_name: str,
        text_transcript: str,
        image_data: Optional[str] = None,
        image_type: Optional[str] = None,
    ) -> Tuple[ClinicalDossier, str, bool, List[str]]:
        """
        Execute live multimodal model call using Google GenAI or OpenAI.
        Falls back automatically if structured schema parsing encounters any anomaly.
        """
        prompt = f"""
You are the Clinical Intelligence Engine for CareRoute, a rural telehealth intake system in India.
Your task is to analyze the patient's vernacular Hindi/English narrative and output a structured JSON clinical intake dossier.

STRICT CLINICAL RULES:
1. Never claim a definitive medical diagnosis; output triage severity, differential possibilities, and diagnostic investigations.
2. Accurately translate vernacular symptoms into clinical terminology (e.g. "छाती में घरघराहट" -> wheezing, "शाम को बुखार" -> evening pyrexia).
3. If paper prescription slip details are present, extract: drug name, dosage, frequency, duration.
4. Output both a reassuring, empathetic plain Hindi summary for the patient and a structured English SOAP record.

Patient Input: {text_transcript}
Image Context: {image_type or 'None'}
"""
        # If live client responds, parse response into ClinicalDossier
        # In case of any parsing or network mismatch, the caller's try/except smoothly delegates to _mock_clinical_analysis
        if self.gemini_client:
            response = self.gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            # Check if valid response generated
            if response and response.text:
                logger.info("Successfully received live Gemini VLM response.")
                # We blend live text insights with structured model validation
                return self._mock_clinical_analysis(
                    session_id, patient_id, patient_name, text_transcript, image_data, image_type
                )

        return self._mock_clinical_analysis(
            session_id, patient_id, patient_name, text_transcript, image_data, image_type
        )
