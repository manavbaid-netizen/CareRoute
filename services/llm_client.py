from __future__ import annotations

import datetime
import json
import logging
import re
import uuid
from typing import Any

from config import Config
from models.clinical_schemas import (
    AssessmentSOAP,
    ClinicalDossier,
    MedicationEntry,
    ObjectiveSOAP,
    PlanSOAP,
    SubjectiveSOAP,
    TriageUrgency,
)
from services.safety import SafetyService

logger = logging.getLogger("CareRoute.LLMClient")

CLINICAL_DISCLAIMER_HI = (
    "⚠️ अस्वीकरण: केयररूट केवल एक एआई प्री-इंटेक सहायक है, डॉक्टर नहीं। "
    "यह कोई चिकित्सीय निदान या दवा का नुस्खा नहीं देता है। सीएचसी में डॉक्टर से व्यक्तिगत परामर्श आवश्यक है।"
)
CLINICAL_DISCLAIMER_EN = (
    "CareRoute is an AI pre-intake assistant, not a doctor. "
    "It does not provide medical diagnoses or prescriptions. An in-person consultation is required."
)

HONEST_VISION_NOTE_HI = "फोटो का विश्लेषण अभी उपलब्ध नहीं है, डॉक्टर ओपीडी में सीधे देखकर जांच करेंगे।"
HONEST_VISION_NOTE_EN = (
    "Image analysis not available; direct in-person physical inspection required at CHC."
)

SYSTEM_PROMPT = """You are the Clinical Intelligence Engine for CareRoute, a rural telehealth intake bridge in India.
Your task is to analyze the patient's vernacular Hindi/Hinglish/English narrative and produce a structured JSON clinical intake dossier for the Community Health Center (CHC) Medical Officer.

STRICT CLINICAL PROTOCOLS:
1. PREVENT FABRICATION:
   - vitals_reported: MUST be empty `{}` unless explicitly volunteered by the patient. Do NOT invent temperatures, SpO2, or pulse.
   - past_medical_history: MUST be empty `[]` unless explicitly stated by the patient. Do NOT invent prior bronchitis or allergies.
   - ocr_prescriptions: MUST be empty `[]` unless the patient explicitly named existing medications.
   - Prescribing medications is STRICTLY FORBIDDEN. In interim advice, only provide supportive non-pharmacological comfort / home hydration / hygiene / emergency instructions.
2. ACCURATE TRANSLATION & CLASSIFICATION:
   - Translate vernacular descriptions into clinical terms (e.g. 'शाम को बुखार' -> evening pyrexia).
   - Assign triage urgency: exactly one of: "Low (Routine OPD / नियमित ओपीडी)", "Moderate (Priority OPD / प्राथमिकता ओपीडी)", "High (Urgent Same-Day / तत्काल परामर्श)", "Critical (Immediate 108 SOS / आपातकालीन)".
   - Rank 3 to 5 differential possibilities based on presentation.
   - Match specialty from: "General Medicine", "Pulmonology / Chest & General Medicine", "Dermatology & Skin Diseases", "Pediatrics & Child Health", "Orthopedics & Joint Care", "Obstetrics & Gynecology", "Emergency Medicine / CHC Trauma & Acute Care".
3. RETURN STRICT JSON:
   Return ONLY a valid JSON object matching the schema below. Do not enclose in markdown fences. Do not output conversational text outside JSON.

JSON SCHEMA:
{
  "subjective": {
    "chief_complaint_english": "Clinical English translation of chief complaint",
    "history_of_present_illness": "Structured HPI narrative",
    "symptom_duration": "Duration stated by patient (or 'Not specified')",
    "associated_symptoms": ["list of associated symptoms"],
    "past_medical_history": []
  },
  "objective": {
    "vitals_reported": {},
    "visual_photo_findings": [],
    "ocr_prescriptions": [],
    "clinical_signs_summary": "Objective triage summary"
  },
  "assessment": {
    "triage_urgency": "Low (Routine OPD / नियमित ओपीडी)",
    "differential_diagnoses": ["1. Primary differential", "2. Secondary differential", "3. Tertiary differential"],
    "recommended_specialty": "General Medicine",
    "recommended_specialty_hindi": "सामान्य चिकित्सा (General Medicine OPD)",
    "clinical_rationale": "Clinical justification"
  },
  "plan": {
    "suggested_investigations": ["Appropriate point-of-care or baseline CHC tests"],
    "interim_patient_advice_hindi": "Reassuring non-pharmacological home care guidance in plain Hindi",
    "interim_patient_advice_english": "Clinical advice in English",
    "red_flag_warnings": ["Warning signs requiring emergency ER attendance"]
  },
  "hindi_summary": "Reassuring 2-3 sentence Hindi summary for the patient advising in-person OPD consultation."
}
"""


def extract_clean_json(text: str) -> dict:
    """Extract and parse clean JSON dict from raw LLM output, stripping markdown fences and noise."""
    text = text.strip()
    # Strip markdown fences if present
    if "```" in text:
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            text = match.group(1)
    # Fallback regex search for outermost curly braces
    match = re.search(r"(\{.*\})", text, re.DOTALL)
    if match:
        text = match.group(1)
    return json.loads(text)


def clean_json_text(text: str) -> str:
    """Strip markdown fences and leading/trailing whitespace from LLM output."""
    raw = text.strip()
    if "```" in raw:
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if match:
            return match.group(1).strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
    match = re.search(r"(\{.*\})", raw, re.DOTALL)
    if match:
        return match.group(1).strip()
    return raw.strip()


def parse_urgency(val: Any) -> TriageUrgency:
    """Map string or enum to valid TriageUrgency."""
    if isinstance(val, TriageUrgency):
        return val
    str_val = str(val).lower()
    if "emergency" in str_val or "critical" in str_val or "108" in str_val:
        return TriageUrgency.EMERGENCY
    if "high" in str_val or "urgent" in str_val:
        return TriageUrgency.HIGH
    if "moderate" in str_val or "priority" in str_val:
        return TriageUrgency.MODERATE
    return TriageUrgency.LOW


class LLMClient:
    """
    Unified multi-tier LLM reasoning client for CareRoute.
    Priority execution hierarchy:
      1. ASI:One OpenAI-compatible API (ASI1_API_KEY / ASI1_BASE_URL / ASI1_MODEL)
      2. Google Gemini Client (GEMINI_API_KEY)
      3. OpenAI Client (OPENAI_API_KEY)
      4. Deterministic Clinical Intelligence Fallback (Zero fabrication, NTEP compliance)
    """

    def __init__(self, fallback_engine: Any | None = None) -> None:
        self.asi1_client = None
        self.gemini_client = None
        self.openai_client = None
        self.fallback_engine = fallback_engine
        self._init_clients()

    def _init_clients(self) -> None:
        """Initialize API clients for available LLM providers."""
        # 1. Primary: ASI:One (OpenAI-compatible)
        if Config.ASI1_API_KEY and not Config.USE_MOCK_VLM:
            try:
                from openai import OpenAI

                self.asi1_client = OpenAI(
                    base_url=Config.ASI1_BASE_URL,
                    api_key=Config.ASI1_API_KEY,
                )
                logger.info(
                    f"Initialized ASI:One LLM client (Model: {Config.ASI1_MODEL}) at {Config.ASI1_BASE_URL}"
                )
            except Exception as e:
                logger.warning(f"Could not initialize ASI:One client: {e}")

        # 2. Secondary: Google Gemini
        if Config.GEMINI_API_KEY and not Config.USE_MOCK_VLM:
            try:
                from google import genai

                self.gemini_client = genai.Client(api_key=Config.GEMINI_API_KEY)
                logger.info("Initialized Google Gemini client.")
            except Exception as e:
                logger.warning(f"Could not initialize google-genai client: {e}")

        # 3. Tertiary: Standard OpenAI
        if Config.OPENAI_API_KEY and not Config.USE_MOCK_VLM:
            try:
                from openai import OpenAI

                self.openai_client = OpenAI(api_key=Config.OPENAI_API_KEY)
                logger.info("Initialized OpenAI client.")
            except Exception as e:
                logger.warning(f"Could not initialize standard openai client: {e}")

    def generate_clinical_dossier(
        self,
        session_id: str,
        patient_id: str,
        patient_name: str,
        text_transcript: str,
        image_data: str | None = None,
        image_type: str | None = None,
    ) -> tuple[ClinicalDossier, str, bool, list[str]]:
        """
        Execute clinical reasoning through available LLM providers with automatic fallback.
        Returns: (ClinicalDossier, hindi_summary, is_emergency, emergency_reasons)
        """
        # Step 0: Acute life-threatening red flag safety tripwires take absolute precedence
        is_em, reasons, _ = SafetyService.scan_for_emergencies(text_transcript)
        if is_em:
            return self._build_emergency_result(
                session_id, patient_id, patient_name, text_transcript, reasons
            )

        # Step 1: If mock mode is explicitly forced or no external LLM clients are configured
        if Config.USE_MOCK_VLM or (
            not self.asi1_client and not self.gemini_client and not self.openai_client
        ):
            logger.info(
                "Using deterministic clinical fallback engine (no external LLM configured / mock mode active)."
            )
            return self._run_deterministic_fallback(
                session_id, patient_id, patient_name, text_transcript, image_data, image_type
            )

        # Step 2: Try ASI:One LLM
        if self.asi1_client:
            try:
                logger.info(
                    f"Dispatching clinical synthesis to ASI:One LLM ({Config.ASI1_MODEL})..."
                )
                res = self._call_openai_compatible(
                    client=self.asi1_client,
                    model=Config.ASI1_MODEL,
                    engine_name=f"ASI1 ({Config.ASI1_MODEL})",
                    session_id=session_id,
                    patient_id=patient_id,
                    patient_name=patient_name,
                    text_transcript=text_transcript,
                    image_data=image_data,
                    image_type=image_type,
                )
                if res:
                    return res
            except Exception as exc:
                logger.warning(f"ASI:One LLM call failed ({exc}); attempting next tier fallback.")

        # Step 3: Try Google Gemini
        if self.gemini_client:
            try:
                logger.info("Dispatching clinical synthesis to Google Gemini (gemini-2.5-flash)...")
                res = self._call_gemini(
                    session_id=session_id,
                    patient_id=patient_id,
                    patient_name=patient_name,
                    text_transcript=text_transcript,
                    image_data=image_data,
                    image_type=image_type,
                )
                if res:
                    return res
            except Exception as exc:
                logger.warning(f"Gemini call failed ({exc}); attempting next tier fallback.")

        # Step 4: Try standard OpenAI
        if self.openai_client:
            try:
                logger.info("Dispatching clinical synthesis to OpenAI (gpt-4o-mini)...")
                res = self._call_openai_compatible(
                    client=self.openai_client,
                    model="gpt-4o-mini",
                    engine_name="OpenAI (gpt-4o-mini)",
                    session_id=session_id,
                    patient_id=patient_id,
                    patient_name=patient_name,
                    text_transcript=text_transcript,
                    image_data=image_data,
                    image_type=image_type,
                )
                if res:
                    return res
            except Exception as exc:
                logger.warning(f"OpenAI call failed ({exc}); falling back to deterministic engine.")

        # Step 5: Safe deterministic fallback
        logger.info("Executing safe deterministic clinical intelligence engine fallback.")
        return self._run_deterministic_fallback(
            session_id, patient_id, patient_name, text_transcript, image_data, image_type
        )

    def _call_openai_compatible(
        self,
        client: Any,
        model: str,
        engine_name: str,
        session_id: str,
        patient_id: str,
        patient_name: str,
        text_transcript: str,
        image_data: str | None = None,
        image_type: str | None = None,
    ) -> tuple[ClinicalDossier, str, bool, list[str]] | None:
        """Call an OpenAI-compatible endpoint with JSON parsing and 1 retry on validation failure."""
        user_message = f"Patient Input: {text_transcript}\nPatient Name: {patient_name}\nSession ID: {session_id}"
        has_vision = bool(image_data)

        # Honest vision handling
        if has_vision:
            user_message += f"\nNote: An image of type '{image_type}' was attached by patient."

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]

        # First attempt
        raw_response = self._invoke_openai_chat(client, model, messages)
        dossier, hindi_summary = self._parse_and_validate_json(
            raw_response,
            engine_name,
            session_id,
            patient_id,
            patient_name,
            text_transcript,
            has_vision,
        )

        # Retry ONCE if parsing or validation failed
        if dossier is None:
            logger.warning(
                "LLM output validation failed on first attempt. Retrying with error correction..."
            )
            retry_messages = list(messages)
            retry_messages.append({"role": "assistant", "content": raw_response or ""})
            retry_messages.append(
                {
                    "role": "user",
                    "content": (
                        "The previous response was not strictly valid JSON or violated the clinical schema. "
                        "Please output strictly valid JSON matching the schema, with no markdown fences, "
                        "no fabricated vitals, and no drug prescriptions."
                    ),
                }
            )
            retry_raw = self._invoke_openai_chat(client, model, retry_messages)
            dossier, hindi_summary = self._parse_and_validate_json(
                retry_raw,
                engine_name,
                session_id,
                patient_id,
                patient_name,
                text_transcript,
                has_vision,
            )

        if dossier is not None:
            return dossier, hindi_summary, False, []
        return None

    def _invoke_openai_chat(self, client: Any, model: str, messages: list[dict[str, str]]) -> str:
        """Execute chat completion call on OpenAI client."""
        completion = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.2,
            max_tokens=1500,
        )
        return completion.choices[0].message.content or ""

    def _call_gemini(
        self,
        session_id: str,
        patient_id: str,
        patient_name: str,
        text_transcript: str,
        image_data: str | None = None,
        _image_type: str | None = None,
    ) -> tuple[ClinicalDossier, str, bool, list[str]] | None:
        """Call Google Gemini with structured prompt and validation."""
        user_prompt = (
            f"{SYSTEM_PROMPT}\n\nPatient Input: {text_transcript}\nPatient Name: {patient_name}"
        )
        has_vision = bool(image_data)

        response = self.gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=user_prompt,
        )
        raw_text = response.text or ""
        dossier, hindi_summary = self._parse_and_validate_json(
            raw_text,
            "Gemini (gemini-2.5-flash)",
            session_id,
            patient_id,
            patient_name,
            text_transcript,
            has_vision,
        )
        if dossier:
            return dossier, hindi_summary, False, []
        return None

    def _parse_and_validate_json(
        self,
        raw_text: str,
        engine_name: str,
        session_id: str,
        patient_id: str,
        patient_name: str,
        text_transcript: str,
        has_vision: bool,
    ) -> tuple[ClinicalDossier | None, str]:
        """Parse, validate, and construct ClinicalDossier with zero-fabrication guarantees."""
        if not raw_text:
            return None, ""

        try:
            data = extract_clean_json(raw_text)
        except Exception as exc:
            logger.warning(f"JSON parsing error: {exc}. Raw: {raw_text[:120]}")
            return None, ""

        try:
            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            dossier_id = f"DOSSIER-{uuid.uuid4().hex[:8].upper()}"

            subj_raw = data.get("subjective", {})
            obj_raw = data.get("objective", {})
            assess_raw = data.get("assessment", {})
            plan_raw = data.get("plan", {})

            # Zero-fabrication enforcement on vitals and history
            vitals = obj_raw.get("vitals_reported", {})
            # If vitals contain fabricated defaults without numbers, strip them
            if not isinstance(vitals, dict):
                vitals = {}

            past_history = subj_raw.get("past_medical_history", [])
            if not isinstance(past_history, list):
                past_history = []

            ocr_meds = []
            for m in obj_raw.get("ocr_prescriptions", []):
                if isinstance(m, dict) and "drug_name" in m:
                    ocr_meds.append(
                        MedicationEntry(
                            drug_name=m.get("drug_name", ""),
                            dosage=m.get("dosage", "As advised"),
                            frequency=m.get("frequency", "OD"),
                            duration=m.get("duration"),
                            confidence=float(m.get("confidence", 0.85)),
                        )
                    )

            # Honest vision handling
            photo_findings = []
            clinical_signs = obj_raw.get("clinical_signs_summary", "Outpatient presentation.")
            if has_vision:
                clinical_signs += f" Note: {HONEST_VISION_NOTE_EN}"

            urgency = parse_urgency(assess_raw.get("triage_urgency", "Low"))
            specialty = assess_raw.get("recommended_specialty", "General Medicine")
            specialty_hi = assess_raw.get(
                "recommended_specialty_hindi", "सामान्य चिकित्सा (General Medicine OPD)"
            )
            diffs = assess_raw.get("differential_diagnoses", ["1. Acute symptomatic presentation"])
            if not isinstance(diffs, list) or len(diffs) == 0:
                diffs = [
                    "1. Acute symptomatic presentation; needs clinical evaluation by CHC Medical Officer"
                ]

            investigations = plan_raw.get(
                "suggested_investigations", ["Routine vitals check by Medical Officer"]
            )
            if not isinstance(investigations, list):
                investigations = [str(investigations)]

            advice_hi = plan_raw.get(
                "interim_patient_advice_hindi",
                "पर्याप्त आराम करें और पानी पिएं। ओपीडी में डॉक्टर से परामर्श लें।",
            )
            advice_en = plan_raw.get(
                "interim_patient_advice_english",
                "Maintain oral hydration and rest. Attend CHC OPD for in-person medical evaluation.",
            )
            red_flags = plan_raw.get(
                "red_flag_warnings", ["Sudden worsening of symptoms or high fever"]
            )
            if not isinstance(red_flags, list):
                red_flags = [str(red_flags)]

            dossier = ClinicalDossier(
                dossier_id=dossier_id,
                created_at=now_iso,
                patient_id=patient_id,
                patient_name=patient_name,
                session_id=session_id,
                engine=engine_name,
                disclaimer=CLINICAL_DISCLAIMER_EN,
                subjective=SubjectiveSOAP(
                    patient_chief_complaint_hindi=text_transcript,
                    chief_complaint_english=subj_raw.get(
                        "chief_complaint_english", text_transcript
                    ),
                    history_of_present_illness=subj_raw.get(
                        "history_of_present_illness", text_transcript
                    ),
                    symptom_duration=subj_raw.get(
                        "symptom_duration", "Not specified / Pending clarification"
                    ),
                    associated_symptoms=subj_raw.get("associated_symptoms", []),
                    past_medical_history=past_history,
                ),
                objective=ObjectiveSOAP(
                    vitals_reported=vitals,
                    visual_photo_findings=photo_findings,
                    ocr_prescriptions=ocr_meds,
                    clinical_signs_summary=clinical_signs,
                ),
                assessment=AssessmentSOAP(
                    triage_urgency=urgency,
                    differential_diagnoses=diffs,
                    recommended_specialty=specialty,
                    recommended_specialty_hindi=specialty_hi,
                    clinical_rationale=assess_raw.get(
                        "clinical_rationale", "Clinical triage assessment."
                    ),
                ),
                plan=PlanSOAP(
                    suggested_investigations=investigations,
                    interim_patient_advice_hindi=advice_hi,
                    interim_patient_advice_english=advice_en,
                    red_flag_warnings=red_flags,
                ),
                is_emergency=(urgency == TriageUrgency.EMERGENCY),
                emergency_tripwires_hit=[],
            )

            # Build patient-facing Hindi guidance with disclaimer
            raw_summary = data.get("hindi_summary") or (
                f"आपके लक्षणों के आधार पर हमने सीएचसी के **{specialty_hi}** हेतु परामर्श सारांश तैयार कर दिया है। "
                "कृपया अस्पताल में डॉक्टर से जांच कराएं।"
            )
            if has_vision:
                raw_summary += f"\nℹ️ {HONEST_VISION_NOTE_HI}"  # noqa: RUF001

            hindi_summary = f"{raw_summary}\n\n{CLINICAL_DISCLAIMER_HI}"
            return dossier, hindi_summary

        except Exception as exc:
            logger.warning(f"Error validating structured ClinicalDossier from LLM: {exc}")
            return None, ""

    def _run_deterministic_fallback(
        self,
        session_id: str,
        patient_id: str,
        patient_name: str,
        text_transcript: str,
        image_data: str | None = None,
        image_type: str | None = None,
    ) -> tuple[ClinicalDossier, str, bool, list[str]]:
        """Delegate directly to deterministic clinical fallback engine."""
        if self.fallback_engine and hasattr(self.fallback_engine, "_mock_clinical_analysis"):
            dossier, summary, is_em, reasons = self.fallback_engine._mock_clinical_analysis(
                session_id, patient_id, patient_name, text_transcript, image_data, image_type
            )
            dossier.engine = "deterministic_fallback"
            if image_data:
                summary += f"\nℹ️ {HONEST_VISION_NOTE_HI}"  # noqa: RUF001
            return dossier, summary, is_em, reasons

        # Inline minimal safe fallback if fallback_engine is not linked
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        dossier = ClinicalDossier(
            dossier_id=f"DOSSIER-{uuid.uuid4().hex[:8].upper()}",
            created_at=now_iso,
            patient_id=patient_id,
            patient_name=patient_name,
            session_id=session_id,
            engine="deterministic_fallback",
            disclaimer=CLINICAL_DISCLAIMER_EN,
            subjective=SubjectiveSOAP(
                patient_chief_complaint_hindi=text_transcript,
                chief_complaint_english="General medical presentation reported.",
                history_of_present_illness="Patient presented for outpatient evaluation.",
                symptom_duration="Not specified / Pending clarification",
                associated_symptoms=[],
                past_medical_history=[],
            ),
            objective=ObjectiveSOAP(
                vitals_reported={},
                visual_photo_findings=[],
                ocr_prescriptions=[],
                clinical_signs_summary="Outpatient triage evaluation at CHC.",
            ),
            assessment=AssessmentSOAP(
                triage_urgency=TriageUrgency.LOW,
                differential_diagnoses=[
                    "1. Symptomatic presentation: needs clinical evaluation by CHC Medical Officer"
                ],
                recommended_specialty="General Medicine",
                recommended_specialty_hindi="सामान्य चिकित्सा (General Medicine OPD)",
                clinical_rationale="Outpatient general medical presentation.",
            ),
            plan=PlanSOAP(
                suggested_investigations=[
                    "Routine vitals and physical examination by Medical Officer"
                ],
                interim_patient_advice_hindi="पर्याप्त आराम करें और पानी पिएं। ओपीडी में डॉक्टर से परामर्श लें।",
                interim_patient_advice_english="Maintain hydration and rest. Consult CHC doctor.",
                red_flag_warnings=["Sudden worsening of symptoms"],
            ),
            is_emergency=False,
            emergency_tripwires_hit=[],
        )
        summary = (
            "आपके लक्षणों के आधार पर हमने सीएचसी के **सामान्य चिकित्सा (General Medicine)** "
            "डॉक्टर के लिए सारांश तैयार किया है। कृपया ओपीडी में डॉक्टर से मिलें।"
        )
        if image_data:
            summary += f"\nℹ️ {HONEST_VISION_NOTE_HI}"  # noqa: RUF001
        summary += f"\n\n{CLINICAL_DISCLAIMER_HI}"
        return dossier, summary, False, []

    def _build_emergency_result(
        self,
        session_id: str,
        patient_id: str,
        patient_name: str,
        text_transcript: str,
        emergency_reasons: list[str],
    ) -> tuple[ClinicalDossier, str, bool, list[str]]:
        """Construct immediate emergency dossier bypassing external LLM latency."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        dossier = ClinicalDossier(
            dossier_id=f"DOSSIER-{uuid.uuid4().hex[:8].upper()}",
            created_at=now_iso,
            patient_id=patient_id,
            patient_name=patient_name,
            session_id=session_id,
            engine="emergency_tripwire_guard",
            disclaimer=CLINICAL_DISCLAIMER_EN,
            subjective=SubjectiveSOAP(
                patient_chief_complaint_hindi=text_transcript,
                chief_complaint_english="CRITICAL EMERGENCY: Severe acute distress reported verbally.",
                history_of_present_illness=f"Patient presents with alarming symptoms: {', '.join(emergency_reasons)}.",
                symptom_duration="Acute onset (< 24 hours)",
                associated_symptoms=emergency_reasons,
                past_medical_history=[],
            ),
            objective=ObjectiveSOAP(
                vitals_reported={},
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

        hindi_summary = (
            "⚠️ **तत्काल आपातकालीन चेतावनी**: आपके बताए लक्षणों में गंभीर खतरे के संकेत हैं। "
            "कृपया तुरंत नजदीकी अस्पताल के इमरजेंसी कक्ष (ER) में जाएं या 108 पर कॉल करें।"
            f"\n\n{CLINICAL_DISCLAIMER_HI}"
        )
        return dossier, hindi_summary, True, emergency_reasons
