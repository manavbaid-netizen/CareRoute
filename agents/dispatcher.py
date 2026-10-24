from __future__ import annotations

import logging
import re
import time
from typing import Any
from uuid import uuid4

from uagents import Agent, Context, Protocol
from uagents.asgi import ASGIServer
from uagents.crypto import Identity

from config import Config
from models.cards import (
    create_card_chat,
    make_booking_receipt_card,
    make_emergency_sos_card,
    make_slot_picker_card,
    make_triage_detail_card,
    parse_card_action,
)
from models.chat_models import (
    BookingCommitRequest,
    BookingCommitResponse,
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    EscrowLockRequest,
    EscrowLockResponse,
    EscrowReleaseRequest,
    EscrowReleaseResponse,
    ResourceContent,
    SlotQueryRequest,
    SlotQueryResponse,
    StartSessionContent,
    TextContent,
    TriageAnalysisRequest,
    TriageAnalysisResponse,
    chat_protocol_spec,
    create_ack,
    create_text_chat,
)
from services.clinic_roster import ClinicRosterService
from services.dossier_generator import DossierGeneratorService
from services.geo_service import GeoService
from services.session_store import SessionStore
from services.swarm_resolver import make_swarm_resolver
from services.vlm_service import VLMService

# CORS & Chromium Private Network Access handler for Agentverse Local Inspector
_orig_asgi_send = ASGIServer._asgi_send


async def _cors_asgi_send(self, send, status_code=200, headers=None, body=None):
    merged = {
        "access-control-allow-origin": "*",
        "access-control-allow-methods": "GET, POST, OPTIONS, HEAD",
        "access-control-allow-headers": "*",
        "access-control-allow-private-network": "true",
    }
    if headers:
        merged.update(headers)
    elif body is not None or status_code != 204:
        merged["content-type"] = "application/json"
    return await _orig_asgi_send(
        self, send=send, status_code=status_code, headers=merged, body=body
    )


ASGIServer._asgi_send = _cors_asgi_send


class Mailbox401Filter(logging.Filter):
    """
    Agentverse returns 401 until the mailbox is activated in Step 2.
    Suppress the 1-second interval error flooding and show a clean guidance notice instead.
    """

    _warned = False

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if "401" in msg and "Could not validate credentials" in msg:
            if not Mailbox401Filter._warned:
                Mailbox401Filter._warned = True
                record.levelno = logging.INFO
                record.levelname = "INFO"
                record.msg = (
                    "Agentverse Mailbox waiting for browser activation.\n"
                    "👉 STEP 2: Open the Inspector URL in your browser and click 'Connect' (select 'Mailbox') to authorize this agent."
                )
                return True
            return False  # Suppress repetitive 401 polling flood
        return True


logger = logging.getLogger("CareRoute.Dispatcher")

# Session store backed by SQLite
session_store = SessionStore()
geo_service = GeoService()
vlm_service = VLMService()
dossier_service = DossierGeneratorService()
roster_service = ClinicRosterService()


def is_worker_online(port: int) -> bool:
    """Fast non-blocking check if a local worker agent is listening."""
    import os
    import socket

    if "PYTEST_CURRENT_TEST" in os.environ or os.getenv("CAREROUTE_TEST_MODE") == "1":
        return True

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.05)
            return sock.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        return False


# Security & Traffic Controls
MAX_INPUT_LENGTH = 1500
RATE_LIMIT_WINDOW_SECS = 60.0
MAX_REQUESTS_PER_WINDOW = 20
_SENDER_MESSAGE_TIMESTAMPS: dict[str, list[float]] = {}


def _get_dispatcher_endpoint() -> str | None:
    if Config.AGENT_ENDPOINT:
        return Config.AGENT_ENDPOINT
    if not Config.USE_AGENTVERSE:
        return Config.get_agent_endpoint(Config.DISPATCHER_PORT)
    return None


def _is_test_env() -> bool:
    import os
    import sys

    return (
        "pytest" in sys.modules
        or "PYTEST_CURRENT_TEST" in os.environ
        or os.getenv("CAREROUTE_TEST_MODE") == "1"
    )


def _get_dispatcher_mailbox() -> bool:
    if _is_test_env():
        return False
    # When a public endpoint is configured, mailbox polling is disabled
    if Config.AGENT_ENDPOINT:
        return False
    return Config.USE_AGENTVERSE


# Initialize Dispatcher (Master Gateway Agent)
dispatcher = Agent(
    name="dispatcher",
    seed=Config.DISPATCHER_SEED,
    port=Config.DISPATCHER_PORT,
    endpoint=_get_dispatcher_endpoint(),
    mailbox=_get_dispatcher_mailbox(),
    resolve=make_swarm_resolver(),
    publish_agent_details=(
        False if _is_test_env() else (Config.USE_AGENTVERSE or bool(Config.AGENT_ENDPOINT))
    ),
    readme_path="agentverse_readme.md",
)

# Attach 401 suppressor to keep terminal clean until Step 2 is confirmed
_mb_filter = Mailbox401Filter()
dispatcher._logger.addFilter(_mb_filter)
logging.getLogger("dispatcher").addFilter(_mb_filter)
logging.getLogger("mailbox").addFilter(_mb_filter)


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
        ctx.logger.info(
            f"📬 Mailbox Mode ACTIVE. Connected to Agentverse at {Config.AGENTVERSE_URL}"
        )
    else:
        ctx.logger.info(
            f"🔌 Local Endpoint Mode: {Config.get_agent_endpoint(Config.DISPATCHER_PORT)}"
        )


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
        if isinstance(item, StartSessionContent) or getattr(item, "type", None) in (
            "start-session",
            "start_session",
        ):
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
        if isinstance(item, EndSessionContent) or getattr(item, "type", None) in (
            "end-session",
            "end_session",
        ):
            session["state"] = "STATE_CLOSED"
            session_store.save_session(sender, session)
            farewell = "सत्र समाप्त हो गया है। केयररूट से जुड़ने के लिए धन्यवाद। स्वस्थ रहें! 🙏"
            await ctx.send(sender, create_text_chat(farewell, end_session=True))
            return

        # (C) Resource content (images, prescriptions, photos)
        if isinstance(item, ResourceContent) or getattr(item, "type", None) == "resource":
            resource = item.resource if not isinstance(item.resource, list) else item.resource[0]
            uri = getattr(resource, "uri", "")
            if is_worker_online(Config.DIAGNOSTIC_PORT) and WORKER_ADDRESSES.get("diagnostic"):
                session["state"] = "STATE_ANALYZING"
                session["pending_request"] = {
                    "type": "triage",
                    "sent_at": time.time(),
                    "retries": 0,
                }
                session_store.save_session(sender, session)
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
            else:
                await _execute_direct_triage(
                    ctx,
                    sender,
                    session,
                    "[Attached clinical image/document]",
                    correlation_id=uuid4().hex[:8],
                    image_data=uri,
                    image_type="prescription_slip",
                )
            return

        # (D) TextContent
        if isinstance(item, TextContent) or getattr(item, "type", None) == "text":
            user_text = item.text.strip()
            await _process_user_text(ctx, sender, session, user_text)
            return

        # (E) Stream control markers from ASI:One (silently handled)
        if (
            getattr(item, "type", None) in ("end-stream", "end_stream")
            or "EndStream" in str(type(item))
            or "endstream" in str(type(item)).lower()
        ):
            continue

        ctx.logger.warning(f"Ignoring unrecognized ACP content item: {type(item)}")


@chat_proto.on_message(model=ChatAcknowledgement)
async def handle_acp_acknowledgement(ctx: Context, sender: str, msg: ChatAcknowledgement) -> None:
    """Receive delivery receipts / acknowledgements from client."""
    ctx.logger.debug(f"ACK received from {sender} for msg {msg.acknowledged_msg_id}")


async def _execute_direct_triage(
    ctx: Context,
    sender: str,
    session: dict[str, Any],
    user_text: str,
    correlation_id: str,
    image_data: str | None = None,
    image_type: str | None = None,
) -> None:
    """Execute direct in-process clinical triage without IPC overhead."""
    ctx.logger.info(
        f"🩺 [CID: {correlation_id}] Synthesizing clinical triage directly for {sender}"
    )
    dossier, hindi_summary, is_emergency, emergency_reasons = vlm_service.analyze_case(
        session_id=sender,
        patient_id=session.get("patient_id", "P-101"),
        patient_name=session.get("patient_name", "मरीज"),
        text_transcript=user_text,
        image_data=image_data,
        image_type=image_type,
    )
    dossier_service.save_dossier(dossier)

    session["dossier"] = dossier
    if getattr(dossier, "dossier_id", None):
        session["dossier_id"] = dossier.dossier_id

    assessment = getattr(dossier, "assessment", None)
    urgency_val = getattr(
        getattr(assessment, "triage_urgency", None), "value", "Moderate (Semi-Urgent)"
    )
    specialty_hi = getattr(assessment, "recommended_specialty_hindi", "सामान्य चिकित्सा")
    specialty_en = getattr(assessment, "recommended_specialty", "General Medicine")
    session["recommended_specialty"] = specialty_en

    plan = getattr(dossier, "plan", None)
    pre_visit = getattr(plan, "interim_patient_advice_hindi", "")
    differentials = getattr(assessment, "differential_diagnoses", [])

    if is_emergency:
        session["state"] = "STATE_EMERGENCY"
        card = make_emergency_sos_card(reasons=emergency_reasons)
        await ctx.send(sender, create_card_chat(hindi_summary, card))
        ctx.logger.warning(f"🚨 [CID: {correlation_id}] Dispatched Emergency SOS to user {sender}")
    else:
        session["state"] = "STATE_TRIAGE_PRESENTED"
        card = make_triage_detail_card(
            urgency=urgency_val,
            specialty_hi=specialty_hi,
            specialty_en=specialty_en,
            pre_visit_advice=pre_visit,
            differentials=differentials,
        )
        await ctx.send(sender, create_card_chat(hindi_summary, card))
        ctx.logger.info(f"✅ [CID: {correlation_id}] Dispatched Triage Card to user {sender}")

    session_store.save_session(sender, session)


async def _execute_direct_slots(
    ctx: Context,
    sender: str,
    session: dict[str, Any],
    specialty: str,
    correlation_id: str,
) -> None:
    """Execute direct in-process slot query without IPC overhead."""
    ctx.logger.info(
        f"📅 [CID: {correlation_id}] Fetching OPD slots directly for {sender} ({specialty})"
    )
    result = roster_service.get_available_slots(specialty)
    session["state"] = "STATE_SLOT_SELECTED"
    session["available_slots"] = result["slots"]

    card = make_slot_picker_card(
        clinic_name=result["clinic_name"],
        doctor_name=result["doctor_name"],
        specialty=result["specialty"],
        room_no=result["room_no"],
        available_slots=result["slots"],
    )
    intro_text = (
        f"🏥 **{result['clinic_name']}** में {result['doctor_name']} ({result['room_no']}) "
        f"के परामर्श के लिए निम्नलिखित ओपीडी समय उपलब्ध हैं:"
    )
    await ctx.send(sender, create_card_chat(intro_text, card))
    ctx.logger.info(f"📅 [CID: {correlation_id}] Dispatched Slot Picker to user {sender}")
    session_store.save_session(sender, session)


async def _execute_direct_booking(
    ctx: Context,
    sender: str,
    session: dict[str, Any],
    slot_id: str,
    dossier_id: str,
    correlation_id: str,
) -> None:
    """Execute direct in-process appointment booking without IPC overhead."""
    ctx.logger.info(
        f"📝 [CID: {correlation_id}] Booking appointment directly for {sender} (slot {slot_id})"
    )
    booking = roster_service.book_appointment(
        slot_id=slot_id,
        patient_id=session.get("patient_id", "P-101"),
        patient_name=session.get("patient_name", "अनाम मरीज"),
        dossier_id=dossier_id,
        user_address=sender,
    )
    if not booking:
        session["state"] = "STATE_SLOT_SELECTED"
        session_store.save_session(sender, session)
        err_text = (
            "⚠️ **स्लॉट अनुपलब्ध**: क्षमा करें, यह समय स्लॉट भर चुका है। कृपया अन्य उपलब्ध समय स्लॉट में से चयन करें।"
        )
        await ctx.send(sender, create_text_chat(err_text))
        return

    session["booking_details"] = booking
    ticket_id = booking.get("ticket_id", "CR-TKT-101")
    session["ticket_id"] = ticket_id
    session["state"] = "STATE_CONFIRMED"

    doctor_name = booking.get("doctor_name", "Dr. Harish Sharma")
    clinic_name = booking.get("clinic_name", "अलवर सामुदायिक स्वास्थ्य केंद्र (Alwar CHC)")
    room_no = booking.get("room_no", "कक्ष संख्या 4")
    slot_time = booking.get("slot_time", "10:00 AM - 10:30 AM")
    qr_payload = booking.get("qr_payload", f"CAREROUTE:{ticket_id}")

    card = make_booking_receipt_card(
        ticket_id=ticket_id,
        patient_name=session.get("patient_name", "अनाम मरीज"),
        doctor_name=doctor_name,
        clinic_name=clinic_name,
        room_no=room_no,
        slot_time=slot_time,
        qr_token=booking.get("qr_token", ""),
        qr_payload=qr_payload,
    )
    intro_text = (
        f"🎉 **आपकी ओपीडी परामर्श बुकिंग सफलतापूर्वक पुष्टि हो गई है!**\n\n"
        f"🎫 **टोकन क्रमांक:** `{ticket_id}`\n"
        f"👨‍⚕️ **चिकित्सक:** {doctor_name} ({room_no})\n"
        f"🏥 **स्थान:** {clinic_name}\n"
        f"🕒 **समय:** {slot_time}"
    )
    await ctx.send(sender, create_card_chat(intro_text, card))
    ctx.logger.info(f"🎫 [CID: {correlation_id}] Dispatched Booking Receipt to user {sender}")
    session_store.save_session(sender, session)


async def _process_user_text(
    ctx: Context, sender: str, session: dict[str, Any], user_text: str
) -> None:
    """Process incoming text narrative, button action JSON, or fallback selection with security controls."""
    now = time.time()

    # 1. Enforce Input Length Limits (Prevent buffer bloat / prompt injection)
    if len(user_text) > MAX_INPUT_LENGTH:
        ctx.logger.warning(f"⚠️ Input exceeded {MAX_INPUT_LENGTH} chars from {sender}")
        err_msg = (
            f"⚠️ आपका संदेश बहुत लंबा है ({len(user_text)} अक्षर)। "
            f"कृपया संक्षेप में अपने मुख्य लक्षण बताएं (अधिकतम {MAX_INPUT_LENGTH} अक्षर)।"
        )
        await ctx.send(sender, create_text_chat(err_msg))
        return

    # 2. Enforce Per-Sender Rate Limits
    timestamps = _SENDER_MESSAGE_TIMESTAMPS.setdefault(sender, [])
    _SENDER_MESSAGE_TIMESTAMPS[sender] = [t for t in timestamps if now - t < RATE_LIMIT_WINDOW_SECS]
    if len(_SENDER_MESSAGE_TIMESTAMPS[sender]) >= MAX_REQUESTS_PER_WINDOW:
        ctx.logger.warning(
            f"🛑 Rate limit exceeded for {sender} ({len(_SENDER_MESSAGE_TIMESTAMPS[sender])} reqs/min)"
        )
        rate_msg = (
            "⚠️ आपके पते से बहुत अधिक संदेश प्राप्त हुए हैं। कृपया एक मिनट प्रतीक्षा करने के बाद पुनः प्रयास करें।"
        )
        await ctx.send(sender, create_text_chat(rate_msg))
        return
    _SENDER_MESSAGE_TIMESTAMPS[sender].append(now)

    # Correlation ID for distributed tracing across agent graph
    correlation_id = uuid4().hex[:8]
    session["correlation_id"] = correlation_id
    ctx.logger.info(
        f"💬 [CID: {correlation_id}] User text from {sender}: '{user_text[:60]}...' [State: {session['state']}]"
    )

    # 3. Check for greeting (e.g. "hi", "hello", "नमस्ते", "hey", "start")
    greetings = {
        "hi",
        "hello",
        "hey",
        "नमस्ते",
        "नमस्कार",
        "pranam",
        "प्रणाम",
        "start",
        "shuru",
        "शुरू",
        "हाय",
        "हेलो",
    }
    cleaned_input = re.sub(r"[^\w\s]", "", user_text.lower()).strip()
    if cleaned_input in greetings or any(user_text.lower().strip() == g for g in greetings):
        welcome_text = (
            "नमस्ते! मैं **केयररूट (CareRoute)** - आपका डिजिटल स्वास्थ्य सहायक हूँ। 🙏\n\n"
            "कृपया अपनी समस्या या लक्षण बताएं। आप बोलकर या लिखकर (हिंदी / English) बता सकते हैं, "
            "या पुरानी पर्ची की फोटो भेज सकते हैं।\n\n"
            "*(उदाहरण: 'मुझे 3 दिन से तेज़ बुखार और खांसी आ रही है')*"
        )
        await ctx.send(sender, create_text_chat(welcome_text))
        ctx.logger.info(f"👋 [CID: {correlation_id}] Dispatched welcome greeting to {sender}")
        return

    # 4. Check for explicit nearby CHC / Hospital location inquiry
    hospital_inquiry_phrases = [
        "नजदीकी अस्पताल",
        "निकटतम अस्पताल",
        "nearest chc",
        "nearest hospital",
        "अस्पताल कहाँ है",
        "अस्पताल की सूची",
        "chc कहाँ है",
        "hospital list",
        "पास का अस्पताल",
        "आसपास का अस्पताल",
        "हॉस्पिटल कहाँ है",
    ]
    is_complaint_or_long = len(user_text.split()) > 10 or any(
        neg in user_text
        for neg in [
            "पहले भी",
            "तीसरी बार",
            "मत भेजो",
            "नहीं चाहिए",
            "कोई नया",
            "यही सूची",
            "बार आई",
        ]
    )
    is_hospital_inquiry = not is_complaint_or_long and (
        any(p in user_text.lower() for p in hospital_inquiry_phrases)
        or (user_text.lower().strip() in ("अस्पताल", "hospital", "chc", "निकटतम chc", "हॉस्पिटल"))
    )
    if is_hospital_inquiry:
        facilities = geo_service.find_nearest_chc(max_results=3)
        chc_header = "🏥 **अलवर जिले के निकटतम सामुदायिक स्वास्थ्य केंद्र (Nearby CHCs):**\n\n"
        chc_body = "\n\n─────────────────\n\n".join(
            geo_service.format_chc_recommendation_hindi(f) for f in facilities
        )
        await ctx.send(sender, create_text_chat(f"{chc_header}{chc_body}"))
        ctx.logger.info(
            f"📍 [CID: {correlation_id}] Dispatched nearest CHC information to {sender}"
        )
        return

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
        ctx.logger.info(f"👤 [CID: {correlation_id}] Patient name identified: {extracted}")

    # 4. Parse JSON button action or numeric choice
    action_data: dict[str, Any] | None = parse_card_action(user_text)

    # 5. Check for action triggers
    if action_data and "action" in action_data:
        action = action_data.get("action")

        if action == "view_slots":
            specialty = action_data.get(
                "specialty", session.get("recommended_specialty", "General Medicine")
            )
            if is_worker_online(Config.LOGISTICS_PORT) and WORKER_ADDRESSES.get("logistics"):
                session["state"] = "STATE_SLOT_SELECTED"
                session["pending_request"] = {
                    "type": "slots",
                    "sent_at": now,
                    "retries": 0,
                    "correlation_id": correlation_id,
                    "specialty": specialty,
                }
                session_store.save_session(sender, session)
                await ctx.send(
                    WORKER_ADDRESSES["logistics"],
                    SlotQueryRequest(
                        session_id=sender,
                        specialty=specialty,
                        user_address=sender,
                        correlation_id=correlation_id,
                    ),
                )
            else:
                await _execute_direct_slots(ctx, sender, session, specialty, correlation_id)
            return

        if action == "select_slot":
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

            if is_worker_online(Config.LOGISTICS_PORT) and WORKER_ADDRESSES.get("logistics"):
                session["pending_request"] = {
                    "type": "booking",
                    "sent_at": now,
                    "retries": 0,
                    "correlation_id": correlation_id,
                    "slot_id": slot_id,
                    "dossier_id": dossier_id,
                }
                session_store.save_session(sender, session)
                await ctx.send(
                    WORKER_ADDRESSES["logistics"],
                    BookingCommitRequest(
                        session_id=sender,
                        patient_id=session["patient_id"],
                        patient_name=session["patient_name"],
                        slot_id=slot_id,
                        dossier_id=dossier_id,
                        user_address=sender,
                        correlation_id=correlation_id,
                    ),
                )
            else:
                await _execute_direct_booking(
                    ctx, sender, session, slot_id, dossier_id, correlation_id
                )
            return

        if action == "clinic_checkin":
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
                        correlation_id=correlation_id,
                    ),
                )
            return

        if (
            action == "numeric_choice"
            and session["state"] == "STATE_SLOT_SELECTED"
            and session.get("available_slots")
        ):
            choice_num = action_data.get("choice", 1)
            slots = session["available_slots"]
            if 1 <= choice_num <= len(slots):
                chosen = slots[choice_num - 1]
                session["selected_slot"] = chosen
                session["state"] = "STATE_PAYMENT_PENDING"
                dossier_id = session.get("dossier_id")
                if not dossier_id:
                    await ctx.send(sender, create_text_chat("कृपया पहले अपने लक्षण बताएं।"))
                    return

                session["pending_request"] = {
                    "type": "booking",
                    "sent_at": now,
                    "retries": 0,
                    "correlation_id": correlation_id,
                    "slot_id": chosen["slot_id"],
                    "dossier_id": dossier_id,
                }
                session_store.save_session(sender, session)

                if is_worker_online(Config.LOGISTICS_PORT) and WORKER_ADDRESSES.get("logistics"):
                    session["pending_request"] = {
                        "type": "booking",
                        "sent_at": now,
                        "retries": 0,
                        "correlation_id": correlation_id,
                        "slot_id": chosen["slot_id"],
                        "dossier_id": dossier_id,
                    }
                    session_store.save_session(sender, session)
                    await ctx.send(
                        WORKER_ADDRESSES["logistics"],
                        BookingCommitRequest(
                            session_id=sender,
                            patient_id=session["patient_id"],
                            patient_name=session["patient_name"],
                            slot_id=chosen["slot_id"],
                            dossier_id=dossier_id,
                            user_address=sender,
                            correlation_id=correlation_id,
                        ),
                    )
                else:
                    await _execute_direct_booking(
                        ctx, sender, session, chosen["slot_id"], dossier_id, correlation_id
                    )
                return

    # 3. Handle fallback numeric slot choices (e.g. user typed '1', '2', or 'स्लॉट')
    if session["state"] == "STATE_SLOT_SELECTED" and session.get("available_slots"):
        slots = session["available_slots"]
        choice_idx = None

        fallback_action = parse_card_action(user_text)
        if fallback_action and fallback_action.get("action") == "numeric_choice":
            c_num = fallback_action.get("choice", 1)
            if 1 <= c_num <= len(slots):
                choice_idx = c_num - 1

        if choice_idx is None:
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

            if is_worker_online(Config.LOGISTICS_PORT) and WORKER_ADDRESSES.get("logistics"):
                session["pending_request"] = {
                    "type": "booking",
                    "sent_at": time.time(),
                    "retries": 0,
                }
                session_store.save_session(sender, session)
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
            else:
                await _execute_direct_booking(
                    ctx, sender, session, chosen["slot_id"], dossier_id, correlation_id
                )
            return

    # 4. Handle text command to view slots if triage already presented
    if session["state"] == "STATE_TRIAGE_PRESENTED" and any(
        kw in user_text.lower() for kw in ["slot", "स्लॉट", "book", "बुकिंग", "1", "डॉक्टर"]
    ):
        specialty = session.get("recommended_specialty", "General Medicine")
        if is_worker_online(Config.LOGISTICS_PORT) and WORKER_ADDRESSES.get("logistics"):
            session["state"] = "STATE_SLOT_SELECTED"
            session["pending_request"] = {"type": "slots", "sent_at": time.time(), "retries": 0}
            session_store.save_session(sender, session)
            await ctx.send(
                WORKER_ADDRESSES["logistics"],
                SlotQueryRequest(session_id=sender, specialty=specialty, user_address=sender),
            )
        else:
            await _execute_direct_slots(ctx, sender, session, specialty, correlation_id)
        return

    # 5. Symptom narrative input -> route to Diagnostic Worker if online, else direct
    if is_worker_online(Config.DIAGNOSTIC_PORT) and WORKER_ADDRESSES.get("diagnostic"):
        session["state"] = "STATE_ANALYZING"
        session["pending_request"] = {
            "type": "triage",
            "sent_at": now,
            "retries": 0,
            "correlation_id": correlation_id,
            "text_transcript": user_text,
        }
        session_store.save_session(sender, session)

        ctx.logger.info(
            f"🔍 [CID: {correlation_id}] Routing symptom intake to DiagnosticWorkerAgent for {sender}"
        )
        await ctx.send(
            WORKER_ADDRESSES["diagnostic"],
            TriageAnalysisRequest(
                session_id=sender,
                patient_id=session["patient_id"],
                patient_name=session["patient_name"],
                text_transcript=user_text,
                user_address=sender,
                correlation_id=correlation_id,
            ),
        )
    else:
        await _execute_direct_triage(ctx, sender, session, user_text, correlation_id)


# ==============================================================================
# WORKER IPC RESPONSES -> DISPATCH TO USER ADDRESS
# ==============================================================================


@dispatcher.on_message(model=TriageAnalysisResponse)
async def handle_triage_response(ctx: Context, _sender: str, msg: TriageAnalysisResponse) -> None:
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
    urgency_val = getattr(
        getattr(assessment, "triage_urgency", None), "value", "Moderate (Semi-Urgent)"
    )
    specialty_hi = getattr(assessment, "recommended_specialty_hindi", "सामान्य चिकित्सा")
    specialty_en = getattr(assessment, "recommended_specialty", "General Medicine")
    session["recommended_specialty"] = specialty_en

    plan = getattr(msg.dossier, "plan", None)
    pre_visit = getattr(plan, "interim_patient_advice_hindi", "")
    differentials = getattr(assessment, "differential_diagnoses", [])

    if msg.is_emergency:
        session["state"] = "STATE_EMERGENCY"
        card = make_emergency_sos_card(reasons=msg.emergency_reasons)
        await ctx.send(user_addr, create_card_chat(msg.hindi_summary, card))
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
        await ctx.send(user_addr, create_card_chat(msg.hindi_summary, card))
        ctx.logger.info(f"✅ Dispatched Triage Card to user {user_addr}")

    session_store.save_session(user_addr, session)


@dispatcher.on_message(model=SlotQueryResponse)
async def handle_slot_response(ctx: Context, _sender: str, msg: SlotQueryResponse) -> None:
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
    await ctx.send(user_addr, create_card_chat(intro_text, card))
    ctx.logger.info(f"📅 Dispatched Slot Picker to user {user_addr} ({len(msg.slots)} slots)")
    session_store.save_session(user_addr, session)


@dispatcher.on_message(model=BookingCommitResponse)
async def handle_booking_commit_response(
    ctx: Context, _sender: str, msg: BookingCommitResponse
) -> None:
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
        ctx.logger.warning(
            f"❌ Booking failed for user {user_addr}: {msg.error_message or msg.status}"
        )
        return

    session["booking_details"] = msg.model_dump()
    session["ticket_id"] = msg.ticket_id

    ctx.logger.info(
        f"💳 Booking reserved for {msg.ticket_id}. Coordinating with EscrowWorkerAgent..."
    )

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
async def handle_escrow_lock_response(ctx: Context, _sender: str, msg: EscrowLockResponse) -> None:
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

    intro_text = "🎉 **आपकी ओपीडी बुकिंग सफलतापूर्वक सुनिश्चित हो गई है!**"
    await ctx.send(user_addr, create_card_chat(intro_text, card))
    ctx.logger.info(
        f"🎟️ Final Booking Receipt dispatched to user {user_addr} for Ticket {ticket_id}"
    )
    session_store.save_session(user_addr, session)


@dispatcher.on_message(model=EscrowReleaseResponse)
async def handle_escrow_release_response(
    ctx: Context, _sender: str, msg: EscrowReleaseResponse
) -> None:
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


@dispatcher.on_interval(period=3.0)
async def request_timeout_watchdog(ctx: Context) -> None:
    """
    Periodic watchdog checking for worker IPC request timeouts.
    Retries once, then gracefully delivers clinical assessment and next steps in Hindi
    via resilient in-process service execution so the user never gets an error deadlock.
    """
    now = time.time()
    for user_addr, session in list(session_store._cache.items()):
        pending = session.get("pending_request")
        if not pending:
            continue

        sent_at = pending.get("sent_at", now)
        elapsed = now - sent_at
        cid = pending.get("correlation_id", "none")
        req_type = pending.get("type", "")

        if elapsed > 5.0:  # 5 seconds timeout per attempt
            retries = pending.get("retries", 0)
            if retries < 1:
                pending["retries"] = retries + 1
                pending["sent_at"] = now
                session_store.save_session(user_addr, session)
                ctx.logger.warning(
                    f"⏱️ [CID: {cid}] Worker response timeout for {user_addr} (type: {req_type}). Retrying (attempt 2)..."
                )
                # Resend request based on type
                if req_type == "triage" and WORKER_ADDRESSES["diagnostic"]:
                    await ctx.send(
                        WORKER_ADDRESSES["diagnostic"],
                        TriageAnalysisRequest(
                            session_id=user_addr,
                            patient_id=session["patient_id"],
                            patient_name=session["patient_name"],
                            text_transcript=pending.get("text_transcript", "तबीयत खराब है"),
                            user_address=user_addr,
                            correlation_id=cid,
                        ),
                    )
                elif req_type == "slots" and WORKER_ADDRESSES["logistics"]:
                    await ctx.send(
                        WORKER_ADDRESSES["logistics"],
                        SlotQueryRequest(
                            session_id=user_addr,
                            specialty=pending.get("specialty", "General Medicine"),
                            user_address=user_addr,
                            correlation_id=cid,
                        ),
                    )
                elif req_type == "booking" and WORKER_ADDRESSES["logistics"]:
                    await ctx.send(
                        WORKER_ADDRESSES["logistics"],
                        BookingCommitRequest(
                            session_id=user_addr,
                            patient_id=session["patient_id"],
                            patient_name=session["patient_name"],
                            slot_id=pending.get("slot_id", ""),
                            dossier_id=pending.get("dossier_id", ""),
                            user_address=user_addr,
                            correlation_id=cid,
                        ),
                    )
            else:
                # Failed after retry -> graceful degradation with in-process self-healing
                session["pending_request"] = None
                ctx.logger.warning(
                    f"⏱️ [CID: {cid}] Worker IPC request failed after retry for {user_addr} (type: {req_type}). "
                    f"Activating resilient in-process service execution..."
                )
                base_timeout_msg = (
                    "⚠️ स्वास्थ्य केंद्र सर्वर से संपर्क करने में अधिक समय लग रहा है। "
                    "कृपया कुछ क्षण बाद पुनः प्रयास करें या सीधे 108 एम्बुलेंस / नजदीकी CHC पर संपर्क करें।"
                )

                transcript = pending.get("text_transcript")
                if req_type == "triage" and transcript:
                    try:
                        dossier, hindi_summary, _is_emergency, _emergency_reasons = (
                            vlm_service.analyze_case(
                                session_id=user_addr,
                                patient_id=session.get("patient_id", "P-101"),
                                patient_name=session.get("patient_name", "अनाम मरीज"),
                                text_transcript=transcript,
                                image_data=pending.get("image_data"),
                                image_type=pending.get("image_type"),
                            )
                        )
                        dossier_service.save_dossier(dossier)
                        session["dossier"] = dossier
                        session["dossier_id"] = dossier.dossier_id
                        assessment = getattr(dossier, "assessment", None)
                        specialty_en = getattr(
                            assessment, "recommended_specialty", "General Medicine"
                        )
                        session["recommended_specialty"] = specialty_en
                        session["state"] = "STATE_TRIAGE_PRESENTED"
                        base_timeout_msg += (
                            f"\n\n━━━━━━━━━━━━━━━━━━━━\n"
                            f"🩺 **स्थानीय प्राथमिक विश्लेषण (Preliminary Assessment):**\n\n"
                            f"{hindi_summary}\n\n"
                            f"👉 डॉक्टर से परामर्श के लिए **'स्लॉट'** या **'1'** लिखकर भेजें।"
                        )
                    except Exception as fb_exc:
                        ctx.logger.error(f"In-process triage fallback error: {fb_exc}")

                elif req_type == "slots":
                    try:
                        specialty = pending.get("specialty") or session.get(
                            "recommended_specialty", "General Medicine"
                        )
                        result = roster_service.get_available_slots(specialty)
                        session["available_slots"] = result["slots"]
                        session["state"] = "STATE_SLOT_SELECTED"
                        slots_text = "\n".join(
                            f"• {i + 1}. समय: {s['time']} ({result['doctor_name']}, {result['room_no']})"
                            for i, s in enumerate(result["slots"])
                        )
                        base_timeout_msg += (
                            f"\n\n━━━━━━━━━━━━━━━━━━━━\n"
                            f"📅 **उपलब्ध ओपीडी स्लॉट ({result['clinic_name']}):**\n\n"
                            f"{slots_text}\n\n"
                            f"👉 बुक करने के लिए स्लॉट नंबर (जैसे **'1'**) लिखकर भेजें।"
                        )
                    except Exception as fb_exc:
                        ctx.logger.error(f"In-process slot fallback error: {fb_exc}")

                elif req_type in ("booking", "escrow"):
                    try:
                        slot_id = pending.get("slot_id") or "slot_1"
                        dossier_id = pending.get("dossier_id") or session.get(
                            "dossier_id", "D-FALLBACK"
                        )
                        booking = roster_service.book_appointment(
                            slot_id=slot_id,
                            patient_id=session.get("patient_id", "P-101"),
                            patient_name=session.get("patient_name", "अनाम मरीज"),
                            dossier_id=dossier_id,
                            user_address=user_addr,
                        )
                        if booking:
                            session["booking_details"] = booking
                            ticket_id = booking.get("ticket_id", "CR-TKT-101")
                            session["ticket_id"] = ticket_id
                            session["state"] = "STATE_CONFIRMED"
                            base_timeout_msg = (
                                f"🎉 **आपकी ओपीडी परामर्श बुकिंग सुरक्षित कर ली गई है!**\n\n"
                                f"🎫 टोकन क्रमांक: `{ticket_id}`\n"
                                f"👨‍⚕️ डॉक्टर: {booking['doctor_name']} ({booking['room_no']})\n"
                                f"🕒 समय: {booking['slot_time']}\n"
                                f"🏥 स्वास्थ्य केंद्र: {booking['clinic_name']}\n\n"
                                f"*(स्वास्थ्य केंद्र पहुँचने पर यह टोकन काउंटर पर दिखाएं)*"
                            )
                    except Exception as fb_exc:
                        ctx.logger.error(f"In-process booking fallback error: {fb_exc}")

                session_store.save_session(user_addr, session)
                await ctx.send(user_addr, create_text_chat(base_timeout_msg))
                ctx.logger.info(
                    f"✅ [CID: {cid}] Fallback service execution dispatched for {user_addr}"
                )


# Include real Agent Chat Protocol in dispatcher with published manifest
dispatcher.include(chat_proto, publish_manifest=True)


if __name__ == "__main__":
    dispatcher.run()
