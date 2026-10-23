from __future__ import annotations

from enum import Enum
from typing import List, Dict, Optional
from uagents import Model, Field


class TriageUrgency(str, Enum):
    """Clinical triage urgency classifications."""
    LOW = "Low (Routine OPD / नियमित ओपीडी)"
    MODERATE = "Moderate (Priority OPD / प्राथमिकता ओपीडी)"
    HIGH = "High (Urgent Same-Day / तत्काल परामर्श)"
    EMERGENCY = "Critical (Immediate 108 SOS / आपातकालीन)"


class MedicationEntry(Model):
    """Medication extracted from handwritten prescription slip or verbal report."""
    drug_name: str = Field(..., description="Generic or brand name of the drug")
    dosage: str = Field(..., description="Strength/dosage, e.g., 500mg, 10ml")
    frequency: str = Field(..., description="Administration frequency: OD, BD, TDS, QID, SOS")
    duration: Optional[str] = Field(None, description="Course duration, e.g., 5 days")
    confidence: float = Field(0.9, ge=0.0, le=1.0, description="OCR/VLM extraction confidence score")


class PhysicalFinding(Model):
    """Objective morphological finding detected from patient-uploaded symptom photograph."""
    body_location: str = Field(..., description="Anatomical site (e.g., Forearm, Scalp, Malar region)")
    morphology: str = Field(..., description="Clinical dermatological or physical description (e.g., Erythematous plaque, Central clearing)")
    severity: str = Field("Moderate", description="Mild / Moderate / Severe")
    suspicion: str = Field(..., description="Primary clinical suspicion for this lesion")


class SubjectiveSOAP(Model):
    """Subjective component of SOAP format - patient narrative and history."""
    patient_chief_complaint_hindi: str = Field(..., description="Raw patient transcript in Hindi/Hinglish")
    chief_complaint_english: str = Field(..., description="Standard clinical English translation of chief complaint")
    history_of_present_illness: str = Field(..., description="Detailed HPI narrative covering onset, progression, and character")
    symptom_duration: str = Field(..., description="Duration timeline (e.g., '14 days', '3 weeks')")
    associated_symptoms: List[str] = Field(default_factory=list, description="Associated systemic findings")
    past_medical_history: List[str] = Field(default_factory=list, description="Prior illnesses, chronic conditions or allergies")


class ObjectiveSOAP(Model):
    """Objective component of SOAP format - observable, measurable, and OCR extracted data."""
    vitals_reported: Dict[str, str] = Field(default_factory=dict, description="Reported or recorded vital signs")
    visual_photo_findings: List[PhysicalFinding] = Field(default_factory=list, description="Lesion or physical exam findings from uploaded images")
    ocr_prescriptions: List[MedicationEntry] = Field(default_factory=list, description="Medications parsed from paper prescription slips")
    clinical_signs_summary: str = Field("No overt signs of systemic shock.", description="Summary of objective observations")


class AssessmentSOAP(Model):
    """Assessment component of SOAP format - triage, differential diagnoses and specialty matching."""
    triage_urgency: TriageUrgency = Field(..., description="Assigned urgency level")
    differential_diagnoses: List[str] = Field(..., description="Ranked differential diagnoses based on clinical presentation")
    recommended_specialty: str = Field(..., description="Target clinical specialty (e.g., Pulmonology / Chest Medicine)")
    recommended_specialty_hindi: str = Field(..., description="Target clinical specialty in Hindi")
    clinical_rationale: str = Field(..., description="Brief reasoning supporting the differential and urgency rating")


class PlanSOAP(Model):
    """Plan component of SOAP format - diagnostics, pre-visit instructions and safety warnings."""
    suggested_investigations: List[str] = Field(..., description="Baseline point-of-care lab tests (e.g., CBC, Sputum AFB, X-Ray)")
    interim_patient_advice_hindi: str = Field(..., description="Culturally sensitive and reassuring patient guidance in Hindi")
    interim_patient_advice_english: str = Field(..., description="Clinical action plan in English")
    red_flag_warnings: List[str] = Field(..., description="Warning symptoms that require immediate emergency intervention")


class ClinicalDossier(Model):
    """Complete English Clinical Intake Record generated for the rural Community Health Center doctor."""
    dossier_id: str = Field(..., description="Unique UUID for this clinical intake dossier")
    created_at: str = Field(..., description="ISO 8601 creation timestamp")
    patient_id: str = Field(..., description="Patient identifier or session ID")
    patient_name: str = Field("Patient", description="Patient name if provided")
    subjective: SubjectiveSOAP
    objective: ObjectiveSOAP
    assessment: AssessmentSOAP
    plan: PlanSOAP
    is_emergency: bool = Field(False, description="Flag indicating critical emergency tripwire was triggered")
    emergency_tripwires_hit: List[str] = Field(default_factory=list, description="List of detected life-threatening warning signs")
