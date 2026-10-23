from __future__ import annotations

import datetime
from typing import List, Dict, Any, Optional
from uuid import uuid4, UUID
from uagents import Model, Field
from models.clinical_schemas import ClinicalDossier

# ==============================================================================
# REAL AGENT CHAT PROTOCOL (ACP) - Re-exported from uagents_core
# ==============================================================================
from uagents_core.contrib.protocols.chat import (
    ChatMessage,
    ChatAcknowledgement,
    TextContent,
    StartSessionContent,
    EndSessionContent,
    ResourceContent,
    Resource,
    MetadataContent,
    chat_protocol_spec,
)


def create_text_chat(
    text: str,
    end_session: bool = False,
    msg_id: Optional[UUID] = None,
) -> ChatMessage:
    """
    Construct a valid, real Agent Chat Protocol (ACP) ChatMessage envelope
    with timezone-aware UTC timestamp and standard TextContent.
    """
    content = [TextContent(type="text", text=text)]
    if end_session:
        content.append(EndSessionContent())
    return ChatMessage(
        timestamp=datetime.datetime.now(datetime.timezone.utc),
        msg_id=msg_id or uuid4(),
        content=content,
    )


def create_ack(acknowledged_msg_id: UUID | str) -> ChatAcknowledgement:
    """Construct a real ACP ChatAcknowledgement envelope for an incoming message."""
    if isinstance(acknowledged_msg_id, str):
        acknowledged_msg_id = UUID(acknowledged_msg_id)
    return ChatAcknowledgement(
        timestamp=datetime.datetime.now(datetime.timezone.utc),
        acknowledged_msg_id=acknowledged_msg_id,
    )


# ==============================================================================
# INTERNAL MULTI-AGENT IPC ENVELOPES (Between Dispatcher and Workers)
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
    user_address: Optional[str] = None


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
    emergency_reasons: List[str] = Field(default_factory=list)


class SlotQueryRequest(Model):
    """
    Sent from DispatcherAgent -> LogisticsWorkerAgent.
    Requests available appointment slots for the target clinical specialty.
    """
    session_id: str
    specialty: str
    clinic_id: Optional[str] = None
    user_address: Optional[str] = None


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
    user_address: Optional[str] = None


class BookingCommitResponse(Model):
    """
    Returned from LogisticsWorkerAgent -> DispatcherAgent.
    Confirms booking registration and provides appointment ticket & check-in token.
    """
    session_id: str
    ticket_id: str
    patient_name: str
    doctor_name: str
    clinic_name: str
    room_no: str
    slot_time: str
    qr_payload: str
    status: str = "CONFIRMED"
    dossier_path: Optional[str] = None


class EscrowLockRequest(Model):
    """
    Sent from DispatcherAgent -> EscrowWorkerAgent.
    Requests locking of refundable anti-no-show deposit (0.5 FET).
    """
    session_id: str
    patient_id: str
    ticket_id: str
    amount_fet: float = 0.5
    user_address: Optional[str] = None


class EscrowLockResponse(Model):
    """
    Returned from EscrowWorkerAgent -> DispatcherAgent.
    Acknowledges receipt & lock of the anti-no-show commitment deposit.
    """
    session_id: str
    ticket_id: str
    status: str
    amount_fet: float
    tx_hash: str
    created_at: str


class EscrowReleaseRequest(Model):
    """
    Sent to EscrowWorkerAgent upon physical clinic check-in.
    """
    ticket_id: str
    scanned_by: str
    qr_token: Optional[str] = None
    sender_address: Optional[str] = None


class EscrowReleaseResponse(Model):
    """
    Returned from EscrowWorkerAgent after refund settlement.
    """
    ticket_id: str
    status: str
    refund_amount_fet: float
    refund_tx_hash: str
    message: str
