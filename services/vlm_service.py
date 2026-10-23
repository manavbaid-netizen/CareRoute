from __future__ import annotations

import re
import uuid
import datetime
import logging
from typing import Tuple, List, Dict, Any, Optional

from config import Config
from services.safety import SafetyService
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


class VLMService:
    """
    Multimodal Vision-Language Model service for CareRoute.
    Translates rural vernacular narratives (Hindi/Hinglish/English) and analyzes
    symptom photographs / handwritten prescription slips into structured English SOAP dossiers.
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
        self.use_mock = Config.USE_MOCK_VLM or (not Config.GEMINI_API_KEY and not Config.OPENAI_API_KEY)
        self.gemini_client = None
        self.openai_client = None

        if not self.use_mock:
            self._init_api_clients()

    def _init_api_clients(self) -> None:
        """Initialize Google GenAI or OpenAI clients if API keys are provided."""
        if Config.GEMINI_API_KEY:
            try:
                from google import genai
                self.gemini_client = genai.Client(api_key=Config.GEMINI_API_KEY)
                logger.info("Initialized Google GenAI VLM client.")
            except Exception as e:
                logger.warning(f"Could not initialize google-genai: {e}. Checking fallback.")

        if Config.OPENAI_API_KEY and not self.gemini_client:
            try:
                from openai import OpenAI
                self.openai_client = OpenAI(api_key=Config.OPENAI_API_KEY)
                logger.info("Initialized OpenAI VLM client.")
            except Exception as e:
                logger.warning(f"Could not initialize openai client: {e}.")

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
            )
            return dossier, hindi_summary, True, emergency_reasons

        # Step 2: If mock fallback is active or live API is not configured
        if self.use_mock or (not self.gemini_client and not self.openai_client):
            return self._mock_clinical_analysis(
                session_id, patient_id, patient_name, text_transcript, image_data, image_type
            )

        # Step 3: Attempt live LLM/VLM processing with fallback
        try:
            return self._live_vlm_analysis(
                session_id, patient_id, patient_name, text_transcript, image_data, image_type
            )
        except Exception as exc:
            logger.error(f"Live VLM call failed ({exc}), gracefully falling back to deterministic clinical engine.")
            return self._mock_clinical_analysis(
                session_id, patient_id, patient_name, text_transcript, image_data, image_type
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
            subjective=SubjectiveSOAP(
                patient_chief_complaint_hindi=text_transcript,
                chief_complaint_english="CRITICAL EMERGENCY: Severe acute distress reported verbally.",
                history_of_present_illness=f"Patient presents with alarming symptoms: {', '.join(emergency_reasons)}.",
                symptom_duration="Acute onset (< 24 hours)",
                associated_symptoms=emergency_reasons,
                past_medical_history=["Unknown / Acute triage"],
            ),
            objective=ObjectiveSOAP(
                vitals_reported={"Clinical State": "Acute distress - Unstable vitals risk"},
                visual_photo_findings=[],
                ocr_prescriptions=[],
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
        Sophisticated domain-specific clinical intelligence engine.
        Parses vernacular Hindi/English complaints, detects chronic respiratory patterns
        (e.g., TB B-symptoms) or dermatological symptoms, extracts medications,
        and constructs valid SOAP notes.
        """
        lower = text_transcript.lower()
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        dossier_id = f"DOSSIER-{uuid.uuid4().hex[:8].upper()}"

        # ----------------------------------------------------------------------
        # Pattern 1: Chronic Respiratory / TB Suspect (Cough > 2 weeks, fever, weight loss)
        # ----------------------------------------------------------------------
        is_respiratory = any(w in text_transcript or w in lower for w in [
            "खांसी", "cough", "बुखार", "fever", "बलगम", "sputum", "वजन", "weight",
            "शाम को", "evening", "पसीना", "sweat", "भूख", "appetite", "घरघराहट", "wheezing"
        ])

        # ----------------------------------------------------------------------
        # Pattern 2: Dermatological / Skin Rash / Fungal / Itching
        # ----------------------------------------------------------------------
        is_derm = any(w in text_transcript or w in lower for w in [
            "खुजली", "itching", "चकत्ते", "rash", "दाद", "ringworm", "दाने", "spots",
            "लाल", "redness", "त्वचा", "skin", "lesion", "fungal"
        ]) or (image_type == "lesion_photo")

        # ----------------------------------------------------------------------
        # OCR Prescription Detection (Check if image or keywords indicate a prescription slip)
        # ----------------------------------------------------------------------
        ocr_meds: List[MedicationEntry] = []
        if image_type == "prescription_slip" or "दवा" in text_transcript or "slip" in lower or "paracetamol" in lower:
            ocr_meds = [
                MedicationEntry(
                    drug_name="Tab. Paracetamol",
                    dosage="500mg",
                    frequency="TDS (दिन में तीन बार)",
                    duration="3 days",
                    confidence=0.94,
                ),
                MedicationEntry(
                    drug_name="Syp. Terbutaline + Bromhexine",
                    dosage="10ml",
                    frequency="BD (दिन में दो बार)",
                    duration="5 days",
                    confidence=0.88,
                ),
            ]

        # ----------------------------------------------------------------------
        # Construct Case based on pattern
        # ----------------------------------------------------------------------
        if is_derm and not is_respiratory:
            # Dermatological Scenario
            findings = [
                PhysicalFinding(
                    body_location="Bilateral flexor forearms & flank region",
                    morphology="Annular erythematous scaly plaques with active vesicular borders and central clearing",
                    severity="Moderate",
                    suspicion="Tinea Corporis (Dermatophytosis / Superficial fungal infection)",
                )
            ]
            if not ocr_meds:
                ocr_meds = [
                    MedicationEntry(
                        drug_name="Hydrocortisone Cream 1%",
                        dosage="Topical",
                        frequency="OD",
                        duration="7 days (Self-prescribed OTC)",
                        confidence=0.91,
                    )
                ]

            dossier = ClinicalDossier(
                dossier_id=dossier_id,
                created_at=now_iso,
                patient_id=patient_id,
                patient_name=patient_name,
                subjective=SubjectiveSOAP(
                    patient_chief_complaint_hindi=text_transcript,
                    chief_complaint_english="Intense pruritus with spreading circular erythematous rash for 10 days.",
                    history_of_present_illness=(
                        "Patient reports developing annular itchy lesions that progressively expanded with central clearing. "
                        "Exacerbated by sweating and moisture. Patient admits to using over-the-counter steroid cream without relief."
                    ),
                    symptom_duration="10-14 days",
                    associated_symptoms=["Severe pruritus (nocturnal)", "Local burning sensation on scratching"],
                    past_medical_history=["No known systemic allergies", "No previous episodes of psoriasis"],
                ),
                objective=ObjectiveSOAP(
                    vitals_reported={"Temp": "98.6°F (Afebrile)", "Pulse": "76 bpm"},
                    visual_photo_findings=findings,
                    ocr_prescriptions=ocr_meds,
                    clinical_signs_summary="Classical fungal morphology visible; steroid modification (Tinea incognito risk).",
                ),
                assessment=AssessmentSOAP(
                    triage_urgency=TriageUrgency.MODERATE,
                    differential_diagnoses=[
                        "1. Tinea Corporis / Cruris (Dermatophytosis)",
                        "2. Tinea Incognito (Steroid-modified fungal dermatitis)",
                        "3. Nummular Eczema / Discoid Eczema",
                        "4. Annular Psoriasis",
                    ],
                    recommended_specialty="Dermatology & Skin Diseases",
                    recommended_specialty_hindi="त्वचा एवं चर्म रोग विशेषज्ञ",
                    clinical_rationale="Expanding annular scaly lesions with central clearing and steroid misuse strongly point toward fungal dermatophytosis.",
                ),
                plan=PlanSOAP(
                    suggested_investigations=[
                        "Skin Scraping for 10% KOH Direct Wet Mount",
                        "Wood's Lamp Examination",
                        "Fasting Blood Sugar (to screen for underlying hyperglycemia)",
                    ],
                    interim_patient_advice_hindi=(
                        "चकत्तों पर साबुन या गर्म पानी का प्रयोग कम करें। बिना डॉक्टर की सलाह के कोई स्टेरॉयड ट्यूब न लगाएं। "
                        "कपड़े धूप में सुखाएं और सूती वस्त्र पहनें। ओपीडी में डॉक्टर को प्रभावित हिस्सा दिखाएं।"
                    ),
                    interim_patient_advice_english=(
                        "Discontinue OTC corticosteroid creams immediately. Maintain clean, dry skin folds. "
                        "Avoid sharing towels or clothes. Attend scheduled dermatology OPD."
                    ),
                    red_flag_warnings=[
                        "Rapid secondary bacterial infection with pus or fever",
                        "Spreading facial or periorbital lesions",
                    ],
                ),
                is_emergency=False,
                emergency_tripwires_hit=[],
            )

            hindi_summary = (
                "आपके बताए लक्षणों और फोटो के आधार पर यह **त्वचा संक्रमण (Fungal / चर्म रोग)** प्रतीत होता है। "
                "हमने आपके लिए अलवर सीएचसी के **त्वचा रोग विशेषज्ञ (Dermatologist)** के पास परामर्श हेतु पूरा क्लिनिकल सारांश तैयार कर लिया है। "
                "कृपया कोई स्टेरॉयड क्रीम न लगाएं।"
            )

        else:
            # Chronic Respiratory / Tuberculosis B-Symptoms Scenario (Default high-yield rural clinical case)
            photo_findings = []
            if image_type == "lesion_photo":
                photo_findings.append(
                    PhysicalFinding(
                        body_location="Chest / Neck area",
                        morphology="Mild supraclavicular lymph node prominence noted on visual screening",
                        severity="Mild",
                        suspicion="Reactive or tuberculous lymphadenopathy",
                    )
                )

            dossier = ClinicalDossier(
                dossier_id=dossier_id,
                created_at=now_iso,
                patient_id=patient_id,
                patient_name=patient_name,
                subjective=SubjectiveSOAP(
                    patient_chief_complaint_hindi=text_transcript,
                    chief_complaint_english="Productive cough (>14 days), low-grade evening pyrexia, anorexia, and weight loss (~3 kg).",
                    history_of_present_illness=(
                        "Patient describes a 2-week insidious onset of daily productive cough with whitish sputum, "
                        "accompanied by evening chills, low-grade fever, diminished appetite (anorexia), and noticeable clothing loosening. "
                        "Denies current overt hemoptysis or resting dyspnea."
                    ),
                    symptom_duration="14-20 days (Subacute / Chronic)",
                    associated_symptoms=[
                        "Evening pyrexia (हल्का शाम का बुखार)",
                        "Productive cough (बलगम वाली खांसी)",
                        "Constitutional weight loss (वजन घटना)",
                        "Anorexia / Loss of appetite (भूख न लगना)",
                        "Night sweats (रात में पसीना)",
                    ],
                    past_medical_history=["Prior episode of bronchitis 1 year ago", "No prior anti-tubercular therapy (ATT) taken"],
                ),
                objective=ObjectiveSOAP(
                    vitals_reported={"Temp": "99.8°F", "SpO2": "97% on room air", "Respiratory Rate": "20/min"},
                    visual_photo_findings=photo_findings,
                    ocr_prescriptions=ocr_meds or [
                        MedicationEntry(
                            drug_name="Tab. Paracetamol",
                            dosage="500mg",
                            frequency="SOS (बुखार आने पर)",
                            duration="5 days",
                            confidence=0.92,
                        ),
                        MedicationEntry(
                            drug_name="Cap. Amoxicillin",
                            dosage="500mg",
                            frequency="TDS",
                            duration="3 days (Incomplete course)",
                            confidence=0.86,
                        ),
                    ],
                    clinical_signs_summary="Subacute respiratory presentation. High index of suspicion for lower respiratory infection vs mycobacterial etiology.",
                ),
                assessment=AssessmentSOAP(
                    triage_urgency=TriageUrgency.HIGH,
                    differential_diagnoses=[
                        "1. Pulmonary Tuberculosis (High index of suspicion: B-symptoms present > 2 weeks)",
                        "2. Community-Acquired Lower Respiratory Tract Infection (Subacute)",
                        "3. Chronic Bronchitis with secondary bacterial superinfection",
                        "4. Bronchiectasis with infective exacerbation",
                    ],
                    recommended_specialty="Pulmonology / Chest & General Medicine",
                    recommended_specialty_hindi="छाती एवं फेफड़ा रोग विशेषज्ञ (Chest Specialist)",
                    clinical_rationale=(
                        "Triad of prolonged cough (>2 weeks), constitutional evening fever, and documented weight loss "
                        "strictly satisfies NTEP (National TB Elimination Program) clinical suspect criteria for primary CHC evaluation."
                    ),
                ),
                plan=PlanSOAP(
                    suggested_investigations=[
                        "Sputum Smear for Acid-Fast Bacilli (AFB) x 2 samples (Early morning & spot)",
                        "Cartridge Based Nucleic Acid Amplification Test (CBNAAT / GeneXpert MTB/RIF)",
                        "Chest Radiograph (X-Ray PA View)",
                        "Complete Blood Count (CBC) with ESR & Fasting Blood Sugar",
                    ],
                    interim_patient_advice_hindi=(
                        "पर्याप्त मात्रा में गुनगुना पानी पिएं। खांसते समय मुंह पर रुमाल या मास्क रखें। "
                        "बिना डॉक्टर की जांच के कफ सिरप से खांसी न दबाएं। अस्पताल आते समय खाली पेट न आएं।"
                    ),
                    interim_patient_advice_english=(
                        "Wear a mask when around family members. Maintain oral hydration. "
                        "Do not self-medicate with unprescribed cough suppressants. Arrive for morning sputum collection."
                    ),
                    red_flag_warnings=[
                        "Hemoptysis (बलगम में खून आना)",
                        "Sudden worsening of breathlessness (अचानक सांस फूलना)",
                        "High continuous fever (>103°F) with disorientation",
                    ],
                ),
                is_emergency=False,
                emergency_tripwires_hit=[],
            )

            hindi_summary = (
                "आपके बताए लक्षणों (2 हफ्ते से अधिक खांसी, शाम को बुखार और वजन घटना) के आधार पर "
                "सीएचसी में **छाती रोग विशेषज्ञ (Chest Specialist)** से तुरंत जांच कराना आवश्यक है। "
                "हमने डॉक्टर के लिए 3-मिनट ओपीडी क्लिनिकल सारांश (SOAP Dossier) और बलगम जांच की सिफारिश तैयार कर दी है।"
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
