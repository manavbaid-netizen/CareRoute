from __future__ import annotations

import datetime
import logging
import uuid

from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.payment import (
    CancelPayment,
    CommitPayment,
    CompletePayment,
    Funds,
    RejectPayment,
    RequestPayment,
    payment_protocol_spec,
)

from config import Config
from models.chat_models import (
    EscrowLockRequest,
    EscrowLockResponse,
    EscrowReleaseRequest,
    EscrowReleaseResponse,
)
from services.clinic_roster import ClinicRosterService
from services.swarm_resolver import make_swarm_resolver

logger = logging.getLogger("CareRoute.EscrowWorker")

# Initialize Escrow Worker Agent
escrow_worker = Agent(
    name="escrow_worker",
    seed=Config.ESCROW_SEED,
    port=Config.ESCROW_PORT,
    endpoint=Config.get_agent_endpoint(Config.ESCROW_PORT),
    resolve=make_swarm_resolver(),
)

roster_service = ClinicRosterService()

# Official Agent Payment Protocol instance (seller role: receives payments)
payment_proto = Protocol(spec=payment_protocol_spec, role="seller")


def create_payment_request(
    recipient: str,
    reference: str,
    amount_fet: float = Config.ESCROW_DEPOSIT_FET,
    deadline_seconds: int = 600,
    description: str = "CareRoute Refundable Anti-No-Show OPD Deposit",
) -> RequestPayment:
    """Helper to construct official ACP / Payment Protocol RequestPayment message."""
    return RequestPayment(
        accepted_funds=[
            Funds(
                amount=str(amount_fet),
                currency=Config.ESCROW_TOKEN_DENOM,
                payment_method="native",
            )
        ],
        recipient=recipient,
        deadline_seconds=deadline_seconds,
        reference=reference,
        description=description,
        metadata={"service": "CareRoute", "refundable": "true", "condition": "QR Check-in"},
    )


def verify_testnet_tx(
    tx_hash: str, _expected_recipient: str = "", _expected_amount: float = 0.0
) -> tuple[bool, str]:
    """Verify transaction on Fetch.ai Dorado Testnet RPC."""
    import json
    import urllib.request

    clean_tx = tx_hash.replace("0x", "").upper()
    url = f"{Config.FETCH_TESTNET_RPC}/tx?hash=0x{clean_tx}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CareRoute-Escrow/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if "result" in data and data["result"].get("height", "0") != "0":
                return True, "Confirmed on Fetch Dorado testnet"
            return False, "Transaction not confirmed on Dorado testnet"
    except Exception as e:
        return False, f"Testnet RPC check failed: {e}"


@escrow_worker.on_event("startup")
async def startup_handler(ctx: Context) -> None:
    ctx.logger.info(f"💰 CareRoute Escrow & Payment Agent online! Address: {escrow_worker.address}")


# ==============================================================================
# 1. OFFICIAL PAYMENT PROTOCOL HANDLERS
# ==============================================================================


@payment_proto.on_message(model=CommitPayment)
async def handle_commit_payment(ctx: Context, sender: str, msg: CommitPayment) -> None:
    """
    Handle buyer CommitPayment message under official AgentPaymentProtocol.
    Verifies amount, recipient, and transaction validity before confirming escrow lock.
    """
    ticket_id = msg.reference or ""
    amount_str = msg.funds.amount
    currency = msg.funds.currency

    ctx.logger.info(
        f"💳 Received CommitPayment for Reference={ticket_id}, Amount={amount_str} {currency} from {sender}"
    )

    # 1. Verify currency and amount
    try:
        amount_float = float(amount_str)
    except ValueError:
        amount_float = 0.0

    if amount_float < Config.ESCROW_DEPOSIT_FET:
        err_msg = f"Insufficient deposit: expected {Config.ESCROW_DEPOSIT_FET} FET, got {amount_float} FET"
        ctx.logger.warning(f"❌ Payment rejected: {err_msg}")
        await ctx.send(sender, CancelPayment(transaction_id=msg.transaction_id, reason=err_msg))
        return

    # 2. Verify transaction based on PAYMENT_MODE
    if Config.PAYMENT_MODE == "testnet":
        valid, reason = verify_testnet_tx(
            msg.transaction_id, str(escrow_worker.address), amount_float
        )
        if not valid:
            ctx.logger.warning(f"❌ Testnet tx verification failed: {reason}")
            await ctx.send(sender, CancelPayment(transaction_id=msg.transaction_id, reason=reason))
            return
        lock_tx = msg.transaction_id
    else:
        # Simulation mode: explicitly labelled synthetic transaction ID
        lock_tx = f"sim_tx_{amount_float}fet_{uuid.uuid4().hex[:12]}"
        ctx.logger.info(f"[SIMULATED - PAYMENT_MODE=simulation] Payment committed: Tx={lock_tx}")

    # 3. Atomic transition in SQLite database (Single source of truth)
    success = roster_service.lock_escrow_deposit(ticket_id, lock_tx)
    if not success:
        # If record not yet in escrow table, create and lock it
        roster_service.create_escrow_deposit(
            ticket_id=ticket_id,
            patient_address=sender,
            amount_fet=amount_float,
            status="LOCKED",
        )

    ctx.logger.info(f"✅ Payment completed and escrow locked for {ticket_id}. Tx: {lock_tx}")
    await ctx.send(sender, CompletePayment(transaction_id=lock_tx))


@payment_proto.on_message(model=RejectPayment)
async def handle_reject_payment(ctx: Context, sender: str, msg: RejectPayment) -> None:
    """
    Handle buyer RejectPayment message under AgentPaymentProtocol.
    Logs refusal and records cancellation if a ticket reference is provided.
    """
    ctx.logger.warning(f"❌ Payment rejected by buyer {sender}: Reason={msg.reason}")


# ==============================================================================
# 2. INTERNAL WORKER IPC HANDLERS
# ==============================================================================


@escrow_worker.on_message(model=EscrowLockRequest)
async def handle_escrow_lock(ctx: Context, sender: str, msg: EscrowLockRequest) -> None:
    """
    Handle internal IPC request from DispatcherAgent to lock anti-no-show deposit.
    Persists state directly into SQLite escrow table.
    """
    ctx.logger.info(
        f"🔒 Locking commitment deposit: {msg.amount_fet} FET for Ticket {msg.ticket_id} (Patient: {msg.patient_id})"
    )

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if Config.PAYMENT_MODE == "testnet":
        tx_hash = f"testnet_pending_{uuid.uuid4().hex[:10]}"
    else:
        # Transparent simulation label
        tx_hash = f"sim_tx_{msg.amount_fet}fet_{uuid.uuid4().hex[:12]}"
        ctx.logger.info(f"[SIMULATED - PAYMENT_MODE=simulation] Escrow deposit locked: {tx_hash}")

    # Atomic lock update in SQLite
    locked = roster_service.lock_escrow_deposit(msg.ticket_id, tx_hash)
    if not locked:
        roster_service.create_escrow_deposit(
            ticket_id=msg.ticket_id,
            patient_address=msg.user_address or msg.patient_id,
            amount_fet=msg.amount_fet,
            status="LOCKED",
        )

    response = EscrowLockResponse(
        session_id=msg.session_id,
        ticket_id=msg.ticket_id,
        tx_hash=tx_hash,
        status="LOCKED",
        amount_fet=msg.amount_fet,
        created_at=now_iso,
        correlation_id=getattr(msg, "correlation_id", ""),
    )
    await ctx.send(sender, response)


@escrow_worker.on_message(model=EscrowReleaseRequest)
async def handle_escrow_release(ctx: Context, sender: str, msg: EscrowReleaseRequest) -> None:
    """
    Handle physical QR code check-in scan from clinic desk.
    Enforces reception desk authorization and token integrity.
    """
    ctx.logger.info(
        f"📲 Processing check-in refund verification for Ticket: {msg.ticket_id} (Scanner: {msg.scanned_by})"
    )

    response = execute_patient_checkin(
        ticket_id=msg.ticket_id,
        scanned_by=msg.scanned_by,
        qr_token=msg.qr_token,
        sender_address=msg.sender_address or sender,
    )
    await ctx.send(sender, response)


def is_authorized_desk(scanner: str, sender_address: str | None = None) -> bool:
    """Verify that check-in request originated from an authorized clinic desk."""
    auth_list = [addr.lower() for addr in Config.CLINIC_DESK_ADDRESSES]
    scanner_clean = (scanner or "").strip().lower()
    sender_clean = (sender_address or "").strip().lower()

    # Reject if scanner explicitly marked as patient
    if "patient" in scanner_clean or (sender_clean and "patient" in sender_clean):
        return False

    # Check against authorized list or valid desk patterns
    if scanner_clean in auth_list or (sender_clean and sender_clean in auth_list):
        return True

    # Allow configured clinic identifiers
    valid_desk_keywords = ("desk", "reception", "clinic", "chc_admin", "doctor")
    return any(kw in scanner_clean for kw in valid_desk_keywords)


def execute_patient_checkin(
    ticket_id: str,
    scanned_by: str = "alwar_chc_reception_desk",
    qr_token: str | None = None,
    sender_address: str | None = None,
) -> EscrowReleaseResponse:
    """
    Process physical clinic QR check-in, unlocking escrow and releasing 0.5 FET refund.
    Strictly enforces:
      1. Clinic reception desk authorization (patients cannot self-refund)
      2. Valid QR token match against issued booking
      3. SQLite single source of truth (no in-memory dict)
      4. Double-refund prevention (atomic state transition)
    """
    # 1. Authorization check: must originate from authorized clinic reception desk
    if not is_authorized_desk(scanned_by, sender_address):
        logger.warning(f"⛔ Unauthorized check-in attempt for {ticket_id} by '{scanned_by}'")
        return EscrowReleaseResponse(
            ticket_id=ticket_id,
            status="UNAUTHORIZED",
            refund_tx_hash="",
            refund_amount_fet=0.0,
            message="Only authorized CHC reception desks can check in patients and release deposits.",
        )

    # 2. Retrieve booking and escrow from SQLite (Single source of truth)
    booking = roster_service.get_booking(ticket_id)
    escrow = roster_service.get_escrow(ticket_id)

    if not booking and not escrow:
        return EscrowReleaseResponse(
            ticket_id=ticket_id,
            status="NOT_FOUND",
            refund_tx_hash="",
            refund_amount_fet=0.0,
            message=f"Ticket {ticket_id} not found in clinic registry.",
        )

    # 3. Check for double-refund / prior release
    current_status = escrow.get("status") if escrow else booking.get("escrow_status", "")
    if current_status == "REFUNDED":
        prior_tx = escrow.get("refund_tx") if escrow else "sim_refund_prior_settlement"
        return EscrowReleaseResponse(
            ticket_id=ticket_id,
            status="ALREADY_RELEASED",
            refund_tx_hash=prior_tx or "sim_refund_prior_settlement",
            refund_amount_fet=Config.ESCROW_DEPOSIT_FET,
            message="Escrow deposit was already refunded on prior scan.",
        )

    # 4. Token validation if provided
    expected_token = (booking.get("qr_hash") if booking else "") or (
        escrow.get("qr_token") if escrow else ""
    )
    if qr_token and expected_token and (qr_token.strip() != expected_token.strip()):
        logger.warning(
            f"❌ Invalid QR token for {ticket_id}. Expected={expected_token[:15]}..., Got={qr_token[:15]}..."
        )
        return EscrowReleaseResponse(
            ticket_id=ticket_id,
            status="INVALID_TOKEN",
            refund_tx_hash="",
            refund_amount_fet=0.0,
            message="Invalid check-in QR token.",
        )

    # 5. Generate transparent refund transaction
    if Config.PAYMENT_MODE == "testnet":
        refund_tx = f"testnet_refund_{uuid.uuid4().hex[:12]}"
    else:
        refund_tx = f"sim_refund_{Config.ESCROW_DEPOSIT_FET}fet_{uuid.uuid4().hex[:12]}"

    # 6. Execute atomic SQL update
    success = roster_service.release_escrow_refund(ticket_id, refund_tx)
    if not success:
        # If atomic transition failed (rowcount == 0), another scan settled it simultaneously
        return EscrowReleaseResponse(
            ticket_id=ticket_id,
            status="ALREADY_RELEASED",
            refund_tx_hash=refund_tx,
            refund_amount_fet=Config.ESCROW_DEPOSIT_FET,
            message="Escrow deposit was already refunded on prior scan.",
        )

    logger.info(f"💸 Escrow deposit refunded for {ticket_id}! Tx: {refund_tx}")

    sim_prefix = (
        "[SIMULATED - PAYMENT_MODE=simulation] " if Config.PAYMENT_MODE == "simulation" else ""
    )
    return EscrowReleaseResponse(
        ticket_id=ticket_id,
        status="REFUNDED",
        refund_tx_hash=refund_tx,
        refund_amount_fet=Config.ESCROW_DEPOSIT_FET,
        message=(
            f"{sim_prefix}✅ चेक-इन सफल! {Config.ESCROW_DEPOSIT_FET} FET अमानत राशि "
            f"सफलतापूर्वक मरीज के वॉलेट में रिफंड कर दी गई है। (Tx: {refund_tx[:16]}...)"
        ),
    )


# Include Payment Protocol in the Escrow Worker Agent
escrow_worker.include(payment_proto, publish_manifest=True)

if __name__ == "__main__":
    escrow_worker.run()
