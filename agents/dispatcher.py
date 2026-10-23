from __future__ import annotations

import logging
import uuid
import datetime
from typing import Dict, Any, Optional

from uagents import Agent, Context
from config import Config
from models.clinical_schemas import ClinicalDossier
from models.cards import (
    make_triage_detail_card,
    make_slot_picker_card,
    make_booking_receipt_card,
    make_emergency_sos_card,
)
from models.chat_models import (
    ChatMessage,
    ChatResponse,
    TriageAnalysisRequest,
    TriageAnalysisResponse,
    SlotQueryRequest,
    SlotQueryResponse,
    BookingCommitRequest,
    BookingCommitResponse,
    EscrowLockRequest,
    EscrowLockResponse,
    EscrowReleaseRequest,
    EscrowReleaseResponse,
)

logger = logging.getLogger("CareRoute.Dispatcher")

# Initialize Dispatcher (Master Gateway Agent)
dispatcher = Agent(
    name="dispatcher",
    seed=Config.DISPATCHER_SEED,
    port=Config.DISPATCHER_PORT,
    endpoint=Config.get_agent_endpoint(Config.DISPATCHER_PORT),
)

# Target worker agent addresses (configured dynamically or from seeds)
WORKER_ADDRESSES = {
    "diagnostic": None,
    "logistics": None,
    "escrow": None,
}

# Per-session conversation state tracking
# States:
#   STATE_INTAKE: Initial greeting & vernacular gathering
#   STATE_ANALYZING: VLM clinical analysis & SOAP synthesis in progress
#   STATE_TRIAGE_PRESENTED: Triage card rendered, awaiting slot view
#   STATE_SLOT_SELECTED: Slot picker card rendered, awaiting slot choice
#   STATE_PAYMENT_PENDING: 0.5 FET escrow locking in progress
#   STATE_CONFIRMED: Booking confirmed, QR receipt card dispatched
#   STATE_EMERGENCY: Red-flag tripped, emergency card dispatched
SESSION_STORE: Dict[str, Dict[str, Any]] = {}


def get_or_create_session(session_id: str) -> Dict[str, Any]:
    """Retrieve or initialize state for a patient conversation session."""
    if session_id not in SESSION_STORE:
        SESSION_STORE[session_id] = {
            "session_id": session_id,
            "patient_id": f"PAT-{session_id[:6].upper()}",
            "patient_name": "रामकुमार (Ram Kumar)",
            "state": "STATE_INTAKE",
            "dossier": None,
            "selected_slot": None,
            "booking_details": None,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
    return SESSION_STORE[session_id]


def set_worker_addresses(diagnostic_addr: str, logistics_addr: str, escrow_addr: str) -> None:
    """Set destination worker addresses for inter-agent routing."""
    WORKER_ADDRESSES["diagnostic"] = diagnostic_addr
    WORKER_ADDRESSES["logistics"] = logistics_addr
    WORKER_ADDRESSES["escrow"] = escrow_addr


@dispatcher.on_event("startup")
async def startup_handler(ctx: Context) -> None:
    ctx.logger.info(
        f"🌐 CareRoute Master Gateway Agent (ACP) is online! Address: {dispatcher.address}"
    )


# ==============================================================================
# INCOMING ACP CHAT MESSAGE HANDLER (From User / ASI:One)
# ==============================================================================

@dispatcher.on_message(model=ChatMessage)
async def handle_chat_message(ctx: Context, sender: str, msg: ChatMessage) -> None:
    """
    Primary ACP entry point. Handles patient conversation turns, button actions,
    and photo/transcript submissions inside ASI:One.
    """
    session = get_or_create_session(msg.session_id)
    ctx.logger.info(
        f"💬 Incoming ACP message from {sender} [Session: {msg.session_id}, Current State: {session['state']}]"
    )

    # --------------------------------------------------------------------------
    # 1. Handle Interactive Card Button Actions
    # --------------------------------------------------------------------------
    if msg.action_payload:
        action = msg.action_payload.get("action")
        ctx.logger.info(f"⚡ Interactive card button triggered: '{action}'")

        if action == "view_slots":
            specialty = msg.action_payload.get("specialty", "General Medicine")
            session["state"] = "STATE_SLOT_SELECTED"

            if WORKER_ADDRESSES["logistics"]:
                await ctx.send(
                    WORKER_ADDRESSES["logistics"],
                    SlotQueryRequest(session_id=msg.session_id, specialty=specialty),
                )
            return

        elif action == "select_slot":
            slot_id = msg.action_payload.get("slot_id")
            session["selected_slot"] = msg.action_payload
            session["state"] = "STATE_PAYMENT_PENDING"

            dossier_id = (
                session["dossier"].dossier_id
                if session.get("dossier")
                else f"DOS-{uuid.uuid4().hex[:6].upper()}"
            )

            # Request booking commitment from Logistics Worker
            if WORKER_ADDRESSES["logistics"]:
                await ctx.send(
                    WORKER_ADDRESSES["logistics"],
                    BookingCommitRequest(
                        session_id=msg.session_id,
                        patient_id=session["patient_id"],
                        patient_name=session["patient_name"],
                        slot_id=slot_id,
                        dossier_id=dossier_id,
                    ),
                )
            return

        elif action == "clinic_checkin":
            ticket_id = msg.action_payload.get("ticket_id")
            if WORKER_ADDRESSES["escrow"] and ticket_id:
                await ctx.send(
                    WORKER_ADDRESSES["escrow"],
                    EscrowReleaseRequest(ticket_id=ticket_id, scanned_by="alwar_chc_reception_desk"),
                )
            return

    # --------------------------------------------------------------------------
    # 2. Handle Text & Symptom Narrative Inputs
    # --------------------------------------------------------------------------
    user_text = msg.text.strip() if msg.text else ""

    # Initial Greeting / First Contact
    if not user_text and not msg.media_url and session["state"] == "STATE_INTAKE":
        welcome_text = (
            "नमस्ते! मैं **केयररूट (CareRoute)** - आपका डिजिटल स्वास्थ्य सहायक हूँ। 🙏\n\n"
            "कृपया अपनी समस्या बताएं। आप बोलकर (वॉइस), लिखकर (हिंदी या अंग्रेजी में), "
            "या पुरानी पर्ची / प्रभावित त्वचा की फोटो भेज सकते हैं।\n"
            "*(उदाहरण: 'मुझे 2 हफ्ते से शाम को बुखार और खांसी है')*"
        )
        response = ChatResponse(
            session_id=msg.session_id,
            recipient_id=msg.user_id,
            text=welcome_text,
            state="STATE_INTAKE",
        )
        await ctx.send(sender, response)
        return

    # User provided symptom description or photo
    session["state"] = "STATE_ANALYZING"
    ctx.logger.info(
        f"🔍 Routing symptom intake to DiagnosticWorkerAgent (Worker: {WORKER_ADDRESSES['diagnostic']})"
    )

    if WORKER_ADDRESSES["diagnostic"]:
        await ctx.send(
            WORKER_ADDRESSES["diagnostic"],
            TriageAnalysisRequest(
                session_id=msg.session_id,
                patient_id=session["patient_id"],
                patient_name=session["patient_name"],
                text_transcript=user_text,
                image_data=msg.media_url,
                image_type=msg.media_type,
            ),
        )


# ==============================================================================
# WORKER IPC RESPONSES (Handled asynchronously by Dispatcher)
# ==============================================================================

@dispatcher.on_message(model=TriageAnalysisResponse)
async def handle_triage_response(ctx: Context, sender: str, msg: TriageAnalysisResponse) -> None:
    """
    Handle clinical triage result from DiagnosticWorkerAgent.
    Renders emergency SOS card or regular Triage Detail Card in ASI:One.
    """
    session = get_or_create_session(msg.session_id)
    session["dossier"] = msg.dossier

    if msg.is_emergency:
        session["state"] = "STATE_EMERGENCY"
        card = make_emergency_sos_card(reasons=msg.emergency_reasons)
        response = ChatResponse(
            session_id=msg.session_id,
            recipient_id=session["patient_id"],
            text=msg.hindi_summary,
            card=card,
            state="STATE_EMERGENCY",
        )
        ctx.logger.warning(f"🚨 Dispatched Emergency SOS Card to user for session {msg.session_id}")
    else:
        session["state"] = "STATE_TRIAGE_PRESENTED"
        card = make_triage_detail_card(
            urgency=msg.dossier.assessment.triage_urgency.value,
            specialty_hi=msg.dossier.assessment.recommended_specialty_hindi,
            specialty_en=msg.dossier.assessment.recommended_specialty,
            pre_visit_advice=msg.dossier.plan.interim_patient_advice_hindi,
            differentials=msg.dossier.assessment.differential_diagnoses,
        )
        response = ChatResponse(
            session_id=msg.session_id,
            recipient_id=session["patient_id"],
            text=msg.hindi_summary,
            card=card,
            state="STATE_TRIAGE_PRESENTED",
        )
        ctx.logger.info(f"✅ Dispatched Triage Detail Card to user for session {msg.session_id}")

    # Note: In standard uagents loop, response can be delivered back to the client or broadcast


@dispatcher.on_message(model=SlotQueryResponse)
async def handle_slot_response(ctx: Context, sender: str, msg: SlotQueryResponse) -> None:
    """
    Handle available OPD slots returned from LogisticsWorkerAgent.
    Renders the ASI Interactive Slot Picker Card.
    """
    session = get_or_create_session(msg.session_id)
    session["state"] = "STATE_SLOT_SELECTED"

    card = make_slot_picker_card(
        clinic_name=msg.clinic_name,
        doctor_name=msg.doctor_name,
        specialty=msg.specialty,
        room_no=msg.room_no,
        available_slots=msg.slots,
    )

    intro_text = (
        f"🏥 **{msg.clinic_name}** में {msg.doctor_name} ({msg.room_no}) "
        f"के परामर्श के लिए निम्नलिखित ओपीडी समय उपलब्ध हैं। कृपया उपयुक्त स्लॉट चुनें:"
    )

    ctx.logger.info(f"📅 Dispatched Slot Picker Card with {len(msg.slots)} slots.")


@dispatcher.on_message(model=BookingCommitResponse)
async def handle_booking_commit_response(ctx: Context, sender: str, msg: BookingCommitResponse) -> None:
    """
    Handle booking confirmation from LogisticsWorkerAgent.
    Initiates the 0.5 FET anti-no-show deposit locking with EscrowWorkerAgent.
    """
    session = get_or_create_session(msg.session_id)
    session["booking_details"] = msg.model_dump()

    ctx.logger.info(
        f"💳 Booking confirmed. Now coordinating with EscrowWorkerAgent for Ticket: {msg.ticket_id}"
    )

    if WORKER_ADDRESSES["escrow"]:
        await ctx.send(
            WORKER_ADDRESSES["escrow"],
            EscrowLockRequest(
                session_id=msg.session_id,
                patient_id=session["patient_id"],
                ticket_id=msg.ticket_id,
                amount_fet=Config.ESCROW_DEPOSIT_FET,
            ),
        )


@dispatcher.on_message(model=EscrowLockResponse)
async def handle_escrow_lock_response(ctx: Context, sender: str, msg: EscrowLockResponse) -> None:
    """
    Handle escrow deposit lock confirmation from EscrowWorkerAgent.
    Renders the final Patient Booking Receipt Card with clinic QR check-in data.
    """
    session = get_or_create_session(msg.session_id)
    session["state"] = "STATE_CONFIRMED"

    booking = session.get("booking_details", {})
    ticket_id = msg.ticket_id
    doctor_name = booking.get("doctor_name", "Dr. Harish Sharma")
    clinic_name = booking.get("clinic_name", "अलवर सामुदायिक स्वास्थ्य केंद्र (Alwar CHC)")
    room_no = booking.get("room_no", "कक्ष संख्या 4")
    slot_time = booking.get("slot_time", "10:00 AM - 10:30 AM")
    qr_payload = booking.get("qr_payload", f"CAREROUTE:{ticket_id}")

    card = make_booking_receipt_card(
        ticket_id=ticket_id,
        patient_name=session["patient_name"],
        doctor_name=doctor_name,
        clinic_name=clinic_name,
        room_no=room_no,
        slot_time=slot_time,
        deposit_fet=msg.amount_fet,
        qr_data=qr_payload,
    )

    ctx.logger.info(
        f"🎟️ Final Booking Receipt Card generated with Escrow Lock: {msg.tx_hash[:16]}..."
    )


@dispatcher.on_message(model=EscrowReleaseResponse)
async def handle_escrow_release_response(ctx: Context, sender: str, msg: EscrowReleaseResponse) -> None:
    """
    Handle clinic desk QR check-in refund confirmation from EscrowWorkerAgent.
    """
    ctx.logger.info(
        f"🎉 Clinic QR Check-in verified! Deposit refunded: {msg.refund_amount_fet} FET. Message: {msg.message}"
    )


if __name__ == "__main__":
    dispatcher.run()
