from __future__ import annotations

import logging
import json
import re
import time
import datetime
from typing import Dict, Any, Optional
from uuid import UUID

from uagents import Agent, Context, Protocol
from config import Config
from models.cards import (
    make_triage_detail_card,
    make_slot_picker_card,
    make_booking_receipt_card,
    make_emergency_sos_card,
    card_to_markdown,
)
from models.chat_models import (
    ChatMessage,
    ChatAcknowledgement,
    TextContent,
    StartSessionContent,
    EndSessionContent,
    ResourceContent,
    chat_protocol_spec,
    create_text_chat,
    create_ack,
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
from services.session_store import SessionStore

logger = logging.getLogger("CareRoute.Dispatcher")

# Session store backed by SQLite
session_store = SessionStore()

# Initialize Dispatcher (Master Gateway Agent)
dispatcher = Agent(
    name="dispatcher",
    seed=Config.DISPATCHER_SEED,
    port=Config.DISPATCHER_PORT,
    endpoint=Config.get_agent_endpoint(Config.DISPATCHER_PORT) if not Config.USE_AGENTVERSE else None,
    mailbox=Config.USE_AGENTVERSE,
    agentverse=f"{Config.AGENTVERSE_API_KEY}@{Config.AGENTVERSE_URL.replace('https://', '')}" if Config.USE_AGENTVERSE and Config.AGENTVERSE_API_KEY else None,
)

from uagents.crypto import Identity

def get_deterministic_address(seed: str) -> str:
    return Identity.from_seed(seed, 0).address

# Target worker agent addresses (automatically derived from deterministic seeds)
WORKER_ADDRESSES = {
    "diagnostic": get_deterministic_address(Config.DIAGNOSTIC_SEED),
    "logistics": get_deterministic_address(Config.LOGISTICS_SEED),
    "escrow": get_deterministic_address(Config.ESCROW_SEED),
}

# Attach official Agent Chat Protocol (ACP)
chat_proto = Protocol(spec=chat_protocol_spec)


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
    if Config.USE_AGENTVERSE:
        ctx.logger.info(f"📬 Mailbox Mode ACTIVE. Connected to Agentverse at {Config.AGENTVERSE_URL}")
    else:
        ctx.logger.info(f"🔌 Local Endpoint Mode: {Config.get_agent_endpoint(Config.DISPATCHER_PORT)}")


# ==============================================================================
# REAL AGENT CHAT PROTOCOL (ACP) HANDLERS
# ==============================================================================

@chat_proto.on_message(model=ChatMessage)
async def handle_acp_chat_message(ctx: Context, sender: str, msg: ChatMessage) -> None:
    """
    Primary ACP entry point complying with official uagents-core AgentChatProtocol.
    Sends ChatAcknowledgement first, then processes message contents.
    """
    # 1. Send immediate ChatAcknowledgement back to sender
    try:
        ack = create_ack(msg.msg_id)
        await ctx.send(sender, ack)
        ctx.logger.info(f"Sent ChatAcknowledgement for msg_id={msg.msg_id} to {sender}")
    except Exception as exc:
        ctx.logger.error(f"Failed to dispatch ChatAcknowledgement: {exc}")

    # 2. Key session by sender address
    session = session_store.get_or_create_session(sender)
    session["user_address"] = sender

    # 3. Process each content item in ACP message
    for item in msg.content:
        # (A) Start of session
        if isinstance(item, StartSessionContent) or getattr(item, "type", None) in ("start-session", "start_session"):
            session["state"] = "STATE_INTAKE"
            session_store.save_session(sender, session)
            welcome_text = (
                "नमस्ते! मैं **केयररूट (CareRoute)** - आपका डिजिटल स्वास्थ्य सहायक हूँ। 🙏\n\n"
                "कृपया अपनी समस्या बताएं। आप बोलकर या लिखकर (हिंदी/Hinglish/English) बता सकते हैं, "
                "या पुरानी पर्ची / प्रभावित त्वचा की फोटो भेज सकते हैं।\n"
                "*(उदाहरण: 'मुझे 2 हफ्ते से शाम को बुखार और खांसी आ रही है')*"
            )
            await ctx.send(sender, create_text_chat(welcome_text))
            return

        # (B) End of session
        elif isinstance(item, EndSessionContent) or getattr(item, "type", None) in ("end-session", "end_session"):
            session["state"] = "STATE_CLOSED"
            session_store.save_session(sender, session)
            farewell = "सत्र समाप्त हो गया है। केयररूट से जुड़ने के लिए धन्यवाद। स्वस्थ रहें! 🙏"
            await ctx.send(sender, create_text_chat(farewell, end_session=True))
            return

        # (C) Resource content (images, prescriptions, photos)
        elif isinstance(item, ResourceContent) or getattr(item, "type", None) == "resource":
            resource = item.resource if not isinstance(item.resource, list) else item.resource[0]
            uri = getattr(resource, "uri", "")
            session["state"] = "STATE_ANALYZING"
            session["pending_request"] = {"type": "triage", "sent_at": time.time(), "retries": 0}
            session_store.save_session(sender, session)

            if WORKER_ADDRESSES["diagnostic"]:
                await ctx.send(
                    WORKER_ADDRESSES["diagnostic"],
                    TriageAnalysisRequest(
                        session_id=sender,
                        patient_id=session["patient_id"],
                        patient_name=session["patient_name"],
                        text_transcript="[Attached clinical image/document]",
                        image_data=uri,
                        image_type="prescription_slip",
                        user_address=sender,
                    ),
                )
            return

        # (D) TextContent
        elif isinstance(item, TextContent) or getattr(item, "type", None) == "text":
            user_text = item.text.strip()
            await _process_user_text(ctx, sender, session, user_text)
            return

        else:
            ctx.logger.warning(f"Ignoring unrecognized ACP content item: {type(item)}")


@chat_proto.on_message(model=ChatAcknowledgement)
async def handle_acp_acknowledgement(ctx: Context, sender: str, msg: ChatAcknowledgement) -> None:
    """Receive delivery receipts / acknowledgements from client."""
    ctx.logger.debug(f"ACK received from {sender} for msg {msg.acknowledged_msg_id}")


async def _process_user_text(ctx: Context, sender: str, session: Dict[str, Any], user_text: str) -> None:
    """Process incoming text narrative, button action JSON, or fallback selection."""
    ctx.logger.info(f"💬 User text from {sender}: '{user_text}' [State: {session['state']}]")

    # Extract patient name if explicitly volunteered
    name_match = re.search(
        r"(?:मेरा\s*नाम|my\s*name\s*is|patient\s*name\s*is|नाम\s*[:=])\s*([a-zA-Z\u0900-\u097f]+(?:\s+[a-zA-Z\u0900-\u097f]+)?)",
        user_text,
        re.IGNORECASE,
    )
    if name_match:
        extracted = name_match.group(1).strip()
        session["patient_name"] = extracted
        session_store.save_session(sender, session)
        ctx.logger.info(f"👤 Patient name identified: {extracted}")

    # 1. Parse JSON button action if present
    action_data: Optional[Dict[str, Any]] = None
    if user_text.startswith("{") and user_text.endswith("}"):
        try:
            action_data = json.loads(user_text)
        except json.JSONDecodeError:
            pass

    # 2. Check for action triggers
    if action_data and "action" in action_data:
        action = action_data.get("action")

        if action == "view_slots":
            specialty = action_data.get("specialty", "General Medicine")
            session["state"] = "STATE_SLOT_SELECTED"
            session["pending_request"] = {"type": "slots", "sent_at": time.time(), "retries": 0}
            session_store.save_session(sender, session)

            if WORKER_ADDRESSES["logistics"]:
                await ctx.send(
                    WORKER_ADDRESSES["logistics"],
                    SlotQueryRequest(session_id=sender, specialty=specialty, user_address=sender),
                )
            return

        elif action == "select_slot":
            slot_id = action_data.get("slot_id")
            session["selected_slot"] = action_data
            session["state"] = "STATE_PAYMENT_PENDING"

            dossier_id = session.get("dossier_id")
            if not dossier_id:
                # If no clinical dossier exists, ask patient to describe symptoms first
                warn_text = (
                    "⚠️ कृपया पहले अपने लक्षणों का विवरण दें ताकि डॉक्टर के लिए क्लिनिकल सारांश "
                    "(SOAP Dossier) तैयार किया जा सके।"
                )
                await ctx.send(sender, create_text_chat(warn_text))
                return

            session["pending_request"] = {"type": "booking", "sent_at": time.time(), "retries": 0}
            session_store.save_session(sender, session)

            if WORKER_ADDRESSES["logistics"]:
                await ctx.send(
                    WORKER_ADDRESSES["logistics"],
                    BookingCommitRequest(
                        session_id=sender,
                        patient_id=session["patient_id"],
                        patient_name=session["patient_name"],
                        slot_id=slot_id,
                        dossier_id=dossier_id,
                        user_address=sender,
                    ),
                )
            return

        elif action == "clinic_checkin":
            ticket_id = action_data.get("ticket_id")
            qr_token = action_data.get("qr_token")
            if WORKER_ADDRESSES["escrow"] and ticket_id:
                await ctx.send(
                    WORKER_ADDRESSES["escrow"],
                    EscrowReleaseRequest(
                        ticket_id=ticket_id,
                        scanned_by="alwar_chc_reception_desk",
                        qr_token=qr_token,
                        sender_address=sender,
                    ),
                )
            return

    # 3. Handle fallback numeric slot choices (e.g. user typed '1', '2', or 'स्लॉट')
    if session["state"] == "STATE_SLOT_SELECTED" and session.get("available_slots"):
        slots = session["available_slots"]
        choice_idx = None
        if user_text.isdigit() and 1 <= int(user_text) <= len(slots):
            choice_idx = int(user_text) - 1
        else:
            for i, s in enumerate(slots):
                if s.get("slot_id") == user_text or s.get("time", "").lower() in user_text.lower():
                    choice_idx = i
                    break

        if choice_idx is not None:
            chosen = slots[choice_idx]
            session["selected_slot"] = chosen
            session["state"] = "STATE_PAYMENT_PENDING"
            dossier_id = session.get("dossier_id")
            if not dossier_id:
                await ctx.send(sender, create_text_chat("कृपया पहले अपने लक्षण बताएं।"))
                return

            session["pending_request"] = {"type": "booking", "sent_at": time.time(), "retries": 0}
            session_store.save_session(sender, session)

            if WORKER_ADDRESSES["logistics"]:
                await ctx.send(
                    WORKER_ADDRESSES["logistics"],
                    BookingCommitRequest(
                        session_id=sender,
                        patient_id=session["patient_id"],
                        patient_name=session["patient_name"],
                        slot_id=chosen["slot_id"],
                        dossier_id=dossier_id,
                        user_address=sender,
                    ),
                )
            return

    # 4. Handle text command to view slots if triage already presented
    if session["state"] == "STATE_TRIAGE_PRESENTED" and any(
        kw in user_text.lower() for kw in ["slot", "स्लॉट", "book", "बुकिंग", "1", "डॉक्टर"]
    ):
        specialty = session.get("recommended_specialty", "General Medicine")
        session["state"] = "STATE_SLOT_SELECTED"
        session["pending_request"] = {"type": "slots", "sent_at": time.time(), "retries": 0}
        session_store.save_session(sender, session)
        if WORKER_ADDRESSES["logistics"]:
            await ctx.send(
                WORKER_ADDRESSES["logistics"],
                SlotQueryRequest(session_id=sender, specialty=specialty, user_address=sender),
            )
        return

    # 5. Symptom narrative input -> route to Diagnostic Worker
    session["state"] = "STATE_ANALYZING"
    session["pending_request"] = {"type": "triage", "sent_at": time.time(), "retries": 0}
    session_store.save_session(sender, session)

    ctx.logger.info(f"🔍 Routing symptom intake to DiagnosticWorkerAgent for {sender}")
    if WORKER_ADDRESSES["diagnostic"]:
        await ctx.send(
            WORKER_ADDRESSES["diagnostic"],
            TriageAnalysisRequest(
                session_id=sender,
                patient_id=session["patient_id"],
                patient_name=session["patient_name"],
                text_transcript=user_text,
                user_address=sender,
            ),
        )


# ==============================================================================
# WORKER IPC RESPONSES -> DISPATCH TO USER ADDRESS
# ==============================================================================

@dispatcher.on_message(model=TriageAnalysisResponse)
async def handle_triage_response(ctx: Context, sender: str, msg: TriageAnalysisResponse) -> None:
    """
    Handle clinical triage result from DiagnosticWorkerAgent.
    Dispatches user-facing ACP message with Hindi summary and interactive triage card.
    """
    user_addr = msg.session_id
    session = session_store.get_or_create_session(user_addr)
    session["pending_request"] = None

    # Store dossier
    session["dossier"] = msg.dossier
    dossier_id = getattr(msg.dossier, "dossier_id", None)
    if dossier_id:
        session["dossier_id"] = dossier_id

    assessment = getattr(msg.dossier, "assessment", None)
    urgency_val = getattr(getattr(assessment, "triage_urgency", None), "value", "Moderate (Semi-Urgent)")
    specialty_hi = getattr(assessment, "recommended_specialty_hindi", "सामान्य चिकित्सा")
    specialty_en = getattr(assessment, "recommended_specialty", "General Medicine")
    session["recommended_specialty"] = specialty_en

    plan = getattr(msg.dossier, "plan", None)
    pre_visit = getattr(plan, "interim_patient_advice_hindi", "")
    differentials = getattr(assessment, "differential_diagnoses", [])

    if msg.is_emergency:
        session["state"] = "STATE_EMERGENCY"
        card = make_emergency_sos_card(reasons=msg.emergency_reasons)
        full_text = f"{msg.hindi_summary}\n\n{card_to_markdown(card)}"
        await ctx.send(user_addr, create_text_chat(full_text))
        ctx.logger.warning(f"🚨 Dispatched Emergency SOS to user {user_addr}")
    else:
        session["state"] = "STATE_TRIAGE_PRESENTED"
        card = make_triage_detail_card(
            urgency=urgency_val,
            specialty_hi=specialty_hi,
            specialty_en=specialty_en,
            pre_visit_advice=pre_visit,
            differentials=differentials,
        )
        full_text = f"{msg.hindi_summary}\n\n{card_to_markdown(card)}"
        await ctx.send(user_addr, create_text_chat(full_text))
        ctx.logger.info(f"✅ Dispatched Triage Card to user {user_addr}")

    session_store.save_session(user_addr, session)


@dispatcher.on_message(model=SlotQueryResponse)
async def handle_slot_response(ctx: Context, sender: str, msg: SlotQueryResponse) -> None:
    """
    Handle available OPD slots returned from LogisticsWorkerAgent.
    Dispatches user-facing ACP message with slot picker card.
    """
    user_addr = msg.session_id
    session = session_store.get_or_create_session(user_addr)
    session["pending_request"] = None
    session["state"] = "STATE_SLOT_SELECTED"
    session["available_slots"] = msg.slots

    card = make_slot_picker_card(
        clinic_name=msg.clinic_name,
        doctor_name=msg.doctor_name,
        specialty=msg.specialty,
        room_no=msg.room_no,
        available_slots=msg.slots,
    )

    intro_text = (
        f"🏥 **{msg.clinic_name}** में {msg.doctor_name} ({msg.room_no}) "
        f"के परामर्श के लिए निम्नलिखित ओपीडी समय उपलब्ध हैं:"
    )
    full_text = f"{intro_text}\n\n{card_to_markdown(card)}"
    await ctx.send(user_addr, create_text_chat(full_text))
    ctx.logger.info(f"📅 Dispatched Slot Picker to user {user_addr} ({len(msg.slots)} slots)")
    session_store.save_session(user_addr, session)


@dispatcher.on_message(model=BookingCommitResponse)
async def handle_booking_commit_response(ctx: Context, sender: str, msg: BookingCommitResponse) -> None:
    """
    Handle booking confirmation from LogisticsWorkerAgent.
    Initiates 0.5 FET escrow lock coordination with EscrowWorkerAgent.
    """
    user_addr = msg.session_id
    session = session_store.get_or_create_session(user_addr)

    # Handle slot capacity or not found errors
    if msg.status in ("SLOT_FULL", "SLOT_NOT_FOUND"):
        session["pending_request"] = None
        session["state"] = "STATE_SLOT_SELECTED"
        session_store.save_session(user_addr, session)
        err_text = (
            "⚠️ **स्लॉट अनुपलब्ध**: क्षमा करें, यह समय स्लॉट भर चुका है या उपलब्ध नहीं है। "
            "कृपया डॉक्टर के अन्य उपलब्ध समय स्लॉट में से चयन करें।"
        )
        await ctx.send(user_addr, create_text_chat(err_text))
        ctx.logger.warning(f"❌ Booking failed for user {user_addr}: {msg.error_message or msg.status}")
        return

    session["booking_details"] = msg.model_dump()
    session["ticket_id"] = msg.ticket_id

    ctx.logger.info(f"💳 Booking reserved for {msg.ticket_id}. Coordinating with EscrowWorkerAgent...")

    if WORKER_ADDRESSES["escrow"]:
        session["pending_request"] = {"type": "escrow", "sent_at": time.time(), "retries": 0}
        session_store.save_session(user_addr, session)
        await ctx.send(
            WORKER_ADDRESSES["escrow"],
            EscrowLockRequest(
                session_id=user_addr,
                patient_id=session["patient_id"],
                ticket_id=msg.ticket_id,
                amount_fet=Config.ESCROW_DEPOSIT_FET,
                user_address=user_addr,
            ),
        )


@dispatcher.on_message(model=EscrowLockResponse)
async def handle_escrow_lock_response(ctx: Context, sender: str, msg: EscrowLockResponse) -> None:
    """
    Handle escrow deposit lock confirmation from EscrowWorkerAgent.
    Dispatches final Booking Receipt with QR payload to patient.
    """
    user_addr = msg.session_id
    session = session_store.get_or_create_session(user_addr)
    session["pending_request"] = None
    session["state"] = "STATE_CONFIRMED"

    booking = session.get("booking_details") or {}
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

    full_text = f"🎉 **आपकी ओपीडी बुकिंग सफलतापूर्वक सुनिश्चित हो गई है!**\n\n{card_to_markdown(card)}"
    await ctx.send(user_addr, create_text_chat(full_text))
    ctx.logger.info(f"🎟️ Final Booking Receipt dispatched to user {user_addr} for Ticket {ticket_id}")
    session_store.save_session(user_addr, session)


@dispatcher.on_message(model=EscrowReleaseResponse)
async def handle_escrow_release_response(ctx: Context, sender: str, msg: EscrowReleaseResponse) -> None:
    """
    Handle clinic desk QR check-in refund confirmation.
    Dispatches refund notification to user.
    """
    session = session_store.get_or_create_session(msg.ticket_id)
    user_addr = session.get("user_address", msg.ticket_id)

    reply_text = (
        f"💸 **अस्पताल चेक-इन सत्यापन एवं रिफंड सफल!**\n\n"
        f"{msg.message}\n"
        f"• रिफंड राशि: {msg.refund_amount_fet} FET\n"
        f"• ट्रांजैक्शन हैश: `{msg.refund_tx_hash}`\n\n"
        f"केयररूट का उपयोग करने के लिए धन्यवाद। आपका परामर्श शुभ हो!"
    )
    await ctx.send(user_addr, create_text_chat(reply_text))
    ctx.logger.info(f"🎉 Check-in refund confirmed for ticket {msg.ticket_id}")


# ==============================================================================
# WATCHDOG TIMER: TIMEOUTS & RETRIES
# ==============================================================================

@dispatcher.on_interval(period=5.0)
async def request_timeout_watchdog(ctx: Context) -> None:
    """
    Periodic watchdog checking for worker IPC request timeouts.
    Retries once, then notifies patient gracefully in Hindi.
    """
    now = time.time()
    for user_addr, session in list(session_store._cache.items()):
        pending = session.get("pending_request")
        if not pending:
            continue

        elapsed = now - pending.get("sent_at", now)
        if elapsed > 15.0:  # 15 seconds timeout
            retries = pending.get("retries", 0)
            if retries < 1:
                pending["retries"] = retries + 1
                pending["sent_at"] = now
                session_store.save_session(user_addr, session)
                ctx.logger.warning(
                    f"⏱️ Worker response timeout for {user_addr} (type: {pending.get('type')}). Retrying..."
                )
                # Resend request based on type
                if pending.get("type") == "triage" and WORKER_ADDRESSES["diagnostic"]:
                    await ctx.send(
                        WORKER_ADDRESSES["diagnostic"],
                        TriageAnalysisRequest(
                            session_id=user_addr,
                            patient_id=session["patient_id"],
                            patient_name=session["patient_name"],
                            text_transcript=session.get("last_symptom_text", "तबीयत खराब है"),
                            user_address=user_addr,
                        ),
                    )
            else:
                # Failed after retry
                session["pending_request"] = None
                session_store.save_session(user_addr, session)
                timeout_msg = (
                    "⚠️ सर्वर से संपर्क करने में अधिक समय लग रहा है। "
                    "कृपया पुनः प्रयास करें (Reply 'retry' या 'दोबारा')।"
                )
                await ctx.send(user_addr, create_text_chat(timeout_msg))
                ctx.logger.error(f"❌ Worker IPC request failed after retry for {user_addr}")


# Include real Agent Chat Protocol in dispatcher with published manifest
dispatcher.include(chat_proto, publish_manifest=True)


if __name__ == "__main__":
    dispatcher.run()
