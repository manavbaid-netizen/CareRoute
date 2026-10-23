from __future__ import annotations

from typing import List, Dict, Any, Optional
from uagents import Model
from models.clinical_schemas import ClinicalDossier


# ==============================================================================
# AGENT CHAT PROTOCOL (ACP) - ASI:One Client Communication Models
# ==============================================================================

class ChatMessage(Model):
    """
    Standard message envelope conforming to the Agent Chat Protocol (ACP).
    Sent from the patient user (or ASI:One interface) to the CareRoute Dispatcher Agent.
    """
    session_id: str
    user_id: str = "patient_user_001"
    role: str = "user"  # "user" | "agent" | "system"
    text: str = ""
    media_url: Optional[str] = None
    media_type: Optional[str] = None  # e.g., "image/jpeg", "prescription/jpeg", "audio/wav"
    card: Optional[Dict[str, Any]] = None
    action_payload: Optional[Dict[str, Any]] = None  # Interactive button click payload
    timestamp: str = ""


class ChatResponse(Model):
    """
    Standard response envelope sent from the Dispatcher back to the ASI:One chat.
    Carries textual vernacular advice, conversation state, and optional interactive cards.
    """
    session_id: str
    recipient_id: str = "patient_user_001"
    role: str = "agent"
    text: str
    card: Optional[Dict[str, Any]] = None
    state: str = "STATE_INTAKE"
    timestamp: str = ""


# ==============================================================================
# INTERNAL MULTI-AGENT IPC ENVELOPES
# ==============================================================================

class TriageAnalysisRequest(Model):
    """
    Sent from DispatcherAgent -> DiagnosticWorkerAgent.
    Carries patient raw vernacular transcript and optional symptom/prescription images.
    """
    session_id: str
    patient_id: str
    patient_name: str = "Patient"
    text_transcript: str
    image_data: Optional[str] = None  # Base64 string or filename/mock token
    image_type: Optional[str] = None  # "lesion_photo" | "prescription_slip"


class TriageAnalysisResponse(Model):
    """
    Returned from DiagnosticWorkerAgent -> DispatcherAgent.
    Contains the full SOAP Clinical Dossier, empathetic Hindi summary, and safety flags.
    """
    session_id: str
    patient_id: str
    dossier: ClinicalDossier
    hindi_summary: str
    is_emergency: bool = False
    emergency_reasons: List[str] = []


class SlotQueryRequest(Model):
    """
    Sent from DispatcherAgent -> LogisticsWorkerAgent.
    Requests available appointment slots for the target clinical specialty.
    """
    session_id: str
    specialty: str
    clinic_id: Optional[str] = None


class SlotQueryResponse(Model):
    """
    Returned from LogisticsWorkerAgent -> DispatcherAgent.
    Supplies matching doctor information and currently available slots.
    """
    session_id: str
    clinic_name: str
    doctor_name: str
    specialty: str
    room_no: str
    slots: List[Dict[str, Any]]


class BookingCommitRequest(Model):
    """
    Sent from DispatcherAgent -> LogisticsWorkerAgent.
    Confirms an OPD appointment for a designated slot and attaches the clinical dossier.
    """
    session_id: str
    patient_id: str
    patient_name: str
    slot_id: str
    dossier_id: str


class BookingCommitResponse(Model):
    """
    Returned from LogisticsWorkerAgent -> DispatcherAgent.
    Supplies confirmed ticket ID, QR payload, and doctor room directions.
    """
    session_id: str
    ticket_id: str
    doctor_name: str
    clinic_name: str
    room_no: str
    slot_time: str
    qr_payload: str
    status: str = "CONFIRMED"


class EscrowLockRequest(Model):
    """
    Sent from DispatcherAgent -> EscrowWorkerAgent.
    Requests locking the anti-no-show deposit (e.g., 0.5 FET) for a booked appointment.
    """
    session_id: str
    patient_id: str
    ticket_id: str
    amount_fet: float = 0.5


class EscrowLockResponse(Model):
    """
    Returned from EscrowWorkerAgent -> DispatcherAgent.
    Confirms the commitment deposit has been locked in the escrow smart protocol.
    """
    session_id: str
    ticket_id: str
    tx_hash: str
    status: str  # "LOCKED" | "FAILED"
    amount_fet: float = 0.5


class EscrowReleaseRequest(Model):
    """
    Sent by clinic health worker or QR scanner -> EscrowWorkerAgent.
    Triggers physical check-in verification and unlocks/refunds the escrow deposit.
    """
    ticket_id: str
    scanned_by: str = "alwar_chc_reception_desk"


class EscrowReleaseResponse(Model):
    """
    Returned from EscrowWorkerAgent after completing check-in refund settlement.
    """
    ticket_id: str
    status: str  # "REFUNDED" | "NOT_FOUND" | "ALREADY_RELEASED"
    refund_tx_hash: str
    refund_amount_fet: float
    message: str
