"""
Phase 8 Tests: Real Payment Protocol & Secure Escrow Validation.
Verifies:
1. Official AgentPaymentProtocol inclusion and CommitPayment handling.
2. Insufficient deposit rejection via CancelPayment.
3. Check-in security: unauthorized patient self-refund is strictly rejected (status="UNAUTHORIZED").
4. Authorized clinic desk check-in releases refund and marks SQLite escrow as REFUNDED.
5. Double-refund prevention: repeated check-in scan returns ALREADY_RELEASED.
6. QR token verification: mismatched QR token is rejected with INVALID_TOKEN.
7. Atomic state transitions in SQLite escrow table (single source of truth).
8. Explicit simulation labelling ([SIMULATED - PAYMENT_MODE=simulation]).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from uagents_core.contrib.protocols.payment import (
    payment_protocol_spec,
    RequestPayment,
    CommitPayment,
    CompletePayment,
    CancelPayment,
    Funds,
)
from config import Config
from services.clinic_roster import ClinicRosterService
from agents.escrow_worker import (
    escrow_worker,
    payment_proto,
    create_payment_request,
    execute_patient_checkin,
    handle_commit_payment,
)


@pytest.fixture
def roster():
    service = ClinicRosterService()
    service.reset_slot("ALW_GEN_0930")
    service.reset_slot("ALW_CHEST_1000")
    return service


def test_payment_protocol_spec_included():
    """Verify official AgentPaymentProtocol is included in escrow_worker."""
    assert payment_proto.spec == payment_protocol_spec
    assert payment_protocol_spec.name == "AgentPaymentProtocol"
    assert payment_protocol_spec.version == "0.1.0"


def test_create_payment_request_helper():
    """Verify create_payment_request builds a valid official RequestPayment message."""
    req = create_payment_request(
        recipient="agent1q_escrow_addr",
        reference="CR-ALW-TEST01",
        amount_fet=0.5,
    )
    assert isinstance(req, RequestPayment)
    assert req.recipient == "agent1q_escrow_addr"
    assert req.reference == "CR-ALW-TEST01"
    assert req.accepted_funds[0].amount == "0.5"
    assert req.accepted_funds[0].currency == Config.ESCROW_TOKEN_DENOM


@pytest.mark.anyio
async def test_commit_payment_valid_flow(roster):
    """Verify CommitPayment with 0.5 FET locks escrow in SQLite and replies with CompletePayment."""
    ticket_id = "CR-TEST-COMMIT-01"
    # Pre-register pending escrow
    roster.create_escrow_deposit(
        ticket_id=ticket_id,
        patient_address="patient_addr_123",
        amount_fet=0.5,
        status="PENDING",
    )

    ctx = MagicMock()
    ctx.send = AsyncMock()

    commit_msg = CommitPayment(
        funds=Funds(amount="0.5", currency=Config.ESCROW_TOKEN_DENOM, payment_method="native"),
        recipient="agent1q_escrow_addr",
        transaction_id="test_sim_tx_initial",
        reference=ticket_id,
        description="OPD Deposit",
    )

    await handle_commit_payment(ctx, "patient_addr_123", commit_msg)

    # Assert CompletePayment was sent back
    assert ctx.send.call_count == 1
    sent_msg = ctx.send.call_args[0][1]
    assert isinstance(sent_msg, CompletePayment)
    assert sent_msg.transaction_id.startswith("sim_tx_0.5fet_")

    # Assert SQLite escrow table was updated
    escrow_record = roster.get_escrow(ticket_id)
    assert escrow_record is not None
    assert escrow_record["status"] == "LOCKED"
    assert escrow_record["lock_tx"].startswith("sim_tx_")


@pytest.mark.anyio
async def test_commit_payment_insufficient_amount_rejected(roster):
    """Verify CommitPayment with insufficient amount (< 0.5 FET) is cancelled."""
    ticket_id = "CR-TEST-INSUFFICIENT-02"
    ctx = MagicMock()
    ctx.send = AsyncMock()

    commit_msg = CommitPayment(
        funds=Funds(amount="0.1", currency=Config.ESCROW_TOKEN_DENOM, payment_method="native"),
        recipient="agent1q_escrow_addr",
        transaction_id="tx_small",
        reference=ticket_id,
    )

    await handle_commit_payment(ctx, "patient_addr_123", commit_msg)

    # Assert CancelPayment was sent
    assert ctx.send.call_count == 1
    sent_msg = ctx.send.call_args[0][1]
    assert isinstance(sent_msg, CancelPayment)
    assert "Insufficient deposit" in sent_msg.reason


def test_unauthorized_patient_checkin_rejected(roster):
    """Assert patient cannot refund themselves: check-in is rejected with UNAUTHORIZED."""
    booking = roster.book_appointment(
        slot_id="ALW_GEN_0930",
        patient_id="PAT_FRAUD",
        patient_name="Fraud Patient",
        dossier_id="DOS_FRAUD",
    )
    ticket_id = booking["ticket_id"]

    # Patient attempts to check in directly
    resp = execute_patient_checkin(
        ticket_id=ticket_id,
        scanned_by="patient",
        sender_address="patient_wallet_address",
    )

    assert resp.status == "UNAUTHORIZED"
    assert "Only authorized CHC reception desks" in resp.message
    assert resp.refund_amount_fet == 0.0

    # Verify status in SQLite remains LOCKED (not refunded)
    escrow_record = roster.get_escrow(ticket_id)
    assert escrow_record["status"] == "LOCKED"


def test_authorized_clinic_desk_checkin_and_double_refund_prevention(roster):
    """Assert authorized clinic desk releases refund, and repeat scan returns ALREADY_RELEASED."""
    booking = roster.book_appointment(
        slot_id="ALW_GEN_0930",
        patient_id="PAT_VALID",
        patient_name="Legit Patient",
        dossier_id="DOS_VALID",
    )
    ticket_id = booking["ticket_id"]

    # 1. First authorized check-in
    resp1 = execute_patient_checkin(
        ticket_id=ticket_id,
        scanned_by="alwar_chc_reception_desk",
        qr_token=booking["qr_payload"],
    )

    assert resp1.status == "REFUNDED"
    assert resp1.refund_amount_fet == 0.5
    assert resp1.refund_tx_hash.startswith("sim_refund_0.5fet_")
    assert "[SIMULATED - PAYMENT_MODE=simulation]" in resp1.message

    # Verify SQLite record is REFUNDED
    escrow_record = roster.get_escrow(ticket_id)
    assert escrow_record["status"] == "REFUNDED"
    assert escrow_record["refund_tx"] == resp1.refund_tx_hash

    # 2. Second scan (Double-refund attempt)
    resp2 = execute_patient_checkin(
        ticket_id=ticket_id,
        scanned_by="alwar_chc_reception_desk",
        qr_token=booking["qr_payload"],
    )

    assert resp2.status == "ALREADY_RELEASED"
    assert "already refunded" in resp2.message.lower()


def test_invalid_qr_token_rejected(roster):
    """Assert incorrect QR token is rejected with INVALID_TOKEN."""
    booking = roster.book_appointment(
        slot_id="ALW_GEN_0930",
        patient_id="PAT_TOKEN",
        patient_name="Token Patient",
        dossier_id="DOS_TOKEN",
    )
    ticket_id = booking["ticket_id"]

    resp = execute_patient_checkin(
        ticket_id=ticket_id,
        scanned_by="alwar_chc_reception_desk",
        qr_token="WRONG_FAKE_QR_TOKEN",
    )

    assert resp.status == "INVALID_TOKEN"
    assert "Invalid check-in QR token" in resp.message


def test_escrow_cancellation(roster):
    """Assert pending escrow can be cancelled atomically upon expiry."""
    ticket_id = "CR-CANCEL-TEST-01"
    roster.create_escrow_deposit(
        ticket_id=ticket_id,
        patient_address="patient_addr_expired",
        amount_fet=0.5,
        status="PENDING",
    )

    cancelled = roster.cancel_escrow(ticket_id, reason="expired_10min")
    assert cancelled is True

    escrow = roster.get_escrow(ticket_id)
    assert escrow["status"] == "CANCELLED"
