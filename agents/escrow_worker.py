from __future__ import annotations

import logging
import uuid
import datetime
from typing import Dict, Any, Optional
from uagents import Agent, Context
from config import Config
from services.clinic_roster import ClinicRosterService
from models.chat_models import (
    EscrowLockRequest,
    EscrowLockResponse,
    EscrowReleaseRequest,
    EscrowReleaseResponse,
)

logger = logging.getLogger("CareRoute.EscrowWorker")

# Initialize Escrow Worker Agent
escrow_worker = Agent(
    name="escrow_worker",
    seed=Config.ESCROW_SEED,
    port=Config.ESCROW_PORT,
    endpoint=Config.get_agent_endpoint(Config.ESCROW_PORT),
)

roster_service = ClinicRosterService()

# In-memory escrow ledger with persistence link to SQLite appointments table
_ESCROW_LEDGER: Dict[str, Dict[str, Any]] = {}


@escrow_worker.on_event("startup")
async def startup_handler(ctx: Context) -> None:
    ctx.logger.info(
        f"💰 CareRoute Escrow & Anti-No-Show Payment Agent is online! Address: {escrow_worker.address}"
    )


@escrow_worker.on_message(model=EscrowLockRequest)
async def handle_escrow_lock(
    ctx: Context, sender: str, msg: EscrowLockRequest
) -> None:
    """
    Handle request to lock anti-no-show deposit (0.5 FET) into escrow.
    Simulates a Fetch.ai native smart contract / ledger commitment.
    """
    ctx.logger.info(
        f"🔒 Locking commitment deposit: {msg.amount_fet} FET for Ticket {msg.ticket_id} (Patient: {msg.patient_id})"
    )

    # Generate deterministic mock cryptographic transaction hash
    tx_hash = f"0x{uuid.uuid4().hex}"

    _ESCROW_LEDGER[msg.ticket_id] = {
        "session_id": msg.session_id,
        "patient_id": msg.patient_id,
        "ticket_id": msg.ticket_id,
        "amount_fet": msg.amount_fet,
        "denom": Config.ESCROW_TOKEN_DENOM,
        "status": "LOCKED",
        "lock_tx_hash": tx_hash,
        "locked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "refund_tx_hash": None,
    }

    ctx.logger.info(f"✅ Escrow deposit locked successfully. TxHash: {tx_hash}")

    response = EscrowLockResponse(
        session_id=msg.session_id,
        ticket_id=msg.ticket_id,
        tx_hash=tx_hash,
        status="LOCKED",
        amount_fet=msg.amount_fet,
    )
    await ctx.send(sender, response)


@escrow_worker.on_message(model=EscrowReleaseRequest)
async def handle_escrow_release(
    ctx: Context, sender: str, msg: EscrowReleaseRequest
) -> None:
    """
    Handle physical QR code check-in scan from clinic desk.
    Releases and refunds the 0.5 FET anti-no-show deposit back to the patient.
    """
    ctx.logger.info(
        f"📲 Processing check-in refund verification for Ticket: {msg.ticket_id} (Scanner: {msg.scanned_by})"
    )

    response = execute_patient_checkin(msg.ticket_id, scanned_by=msg.scanned_by)
    await ctx.send(sender, response)


def execute_patient_checkin(ticket_id: str, scanned_by: str = "clinic_reception_desk") -> EscrowReleaseResponse:
    """
    Synchronous / programmatic helper to process physical clinic QR check-in,
    unlocking escrow and releasing 0.5 FET refund.
    """
    escrow_entry = _ESCROW_LEDGER.get(ticket_id)

    # Check if entry in memory, or verify in SQLite database
    if not escrow_entry:
        db_booking = roster_service.get_booking(ticket_id)
        if not db_booking:
            return EscrowReleaseResponse(
                ticket_id=ticket_id,
                status="NOT_FOUND",
                refund_tx_hash="",
                refund_amount_fet=0.0,
                message=f"Ticket {ticket_id} not found in clinic registry.",
            )
        escrow_entry = {
            "ticket_id": ticket_id,
            "amount_fet": Config.ESCROW_DEPOSIT_FET,
            "status": db_booking.get("escrow_status", "LOCKED"),
        }
        _ESCROW_LEDGER[ticket_id] = escrow_entry

    if escrow_entry.get("status") == "REFUNDED":
        return EscrowReleaseResponse(
            ticket_id=ticket_id,
            status="ALREADY_RELEASED",
            refund_tx_hash=escrow_entry.get("refund_tx_hash", "0xALREADY_SETTLED"),
            refund_amount_fet=escrow_entry.get("amount_fet", 0.5),
            message="Escrow deposit was already refunded on prior scan.",
        )

    # Generate refund transaction hash
    refund_tx = f"0x{uuid.uuid4().hex}"
    escrow_entry["status"] = "REFUNDED"
    escrow_entry["refund_tx_hash"] = refund_tx
    escrow_entry["released_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    escrow_entry["scanned_by"] = scanned_by

    # Update database status
    roster_service.mark_checked_in(ticket_id)

    logger.info(
        f"💸 Escrow deposit refunded! 0.5 FET returned to patient. Refund Tx: {refund_tx}"
    )

    return EscrowReleaseResponse(
        ticket_id=ticket_id,
        status="REFUNDED",
        refund_tx_hash=refund_tx,
        refund_amount_fet=escrow_entry.get("amount_fet", 0.5),
        message=(
            f"✅ चेक-इन सफल! 0.5 FET अमानत राशि सफलतापूर्वक मरीज के वॉलेट में रिफंड कर दी गई है। "
            f"(Tx: {refund_tx[:16]}...)"
        ),
    )


if __name__ == "__main__":
    escrow_worker.run()
