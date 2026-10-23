"""
Tests for Phase 2: Real Agent Chat Protocol (ACP) integration.
Verifies protocol digests, schema compatibility with uagents-core, and
proper request/response/acknowledgement routing in the dispatcher.
"""

import datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import uagents_core.contrib.protocols.chat as official_chat

from agents.dispatcher import (
    WORKER_ADDRESSES,
    chat_proto,
    handle_acp_chat_message,
    handle_escrow_lock_response,
    handle_slot_response,
    handle_triage_response,
    session_store,
)
from models.chat_models import (
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    EscrowLockResponse,
    SlotQueryResponse,
    StartSessionContent,
    TextContent,
    TriageAnalysisResponse,
    create_ack,
    create_text_chat,
)
from models.clinical_schemas import (
    AssessmentSOAP,
    ClinicalDossier,
    ObjectiveSOAP,
    PlanSOAP,
    SubjectiveSOAP,
    TriageUrgency,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_acp_schema_digest_equality():
    """Assert that ChatMessage digest precisely equals uagents_core official digest."""
    our_digest = ChatMessage.build_schema_digest(ChatMessage)
    core_digest = official_chat.ChatMessage.build_schema_digest(official_chat.ChatMessage)
    assert our_digest == core_digest, f"Digest mismatch! {our_digest} != {core_digest}"
    assert chat_proto.digest == official_chat.chat_protocol_spec.digest


def test_create_text_chat_helper():
    """Verify helper constructs a valid timezone-aware ACP ChatMessage."""
    text = "नमस्ते डॉक्टर साहब"
    msg = create_text_chat(text)
    assert isinstance(msg, ChatMessage)
    assert msg.timestamp.tzinfo is not None
    assert len(msg.content) == 1
    assert isinstance(msg.content[0], TextContent)
    assert msg.content[0].text == text

    # Test end_session flag
    end_msg = create_text_chat("अलविदा", end_session=True)
    assert len(end_msg.content) == 2
    assert isinstance(end_msg.content[1], EndSessionContent)


def test_create_ack_helper():
    """Verify helper constructs a valid ACP ChatAcknowledgement."""
    test_id = uuid4()
    ack = create_ack(test_id)
    assert isinstance(ack, ChatAcknowledgement)
    assert ack.acknowledged_msg_id == test_id
    assert ack.timestamp.tzinfo is not None


@pytest.mark.anyio
async def test_acp_start_session_dispatch():
    """Verify that StartSessionContent sends both an ACK and the Hindi greeting to the user."""
    user_address = "agent1q_test_patient_user_addr_001"
    msg_id = uuid4()
    start_msg = ChatMessage(
        timestamp=datetime.datetime.now(datetime.timezone.utc),
        msg_id=msg_id,
        content=[StartSessionContent()],
    )

    mock_ctx = MagicMock()
    mock_ctx.send = AsyncMock()
    mock_ctx.logger = MagicMock()

    await handle_acp_chat_message(mock_ctx, user_address, start_msg)

    # Must have sent at least 2 messages: ACK first, then Greeting
    assert mock_ctx.send.call_count == 2

    # Call 1: ACK
    call1_target, call1_msg = mock_ctx.send.call_args_list[0][0]
    assert call1_target == user_address
    assert isinstance(call1_msg, ChatAcknowledgement)
    assert call1_msg.acknowledged_msg_id == msg_id

    # Call 2: Greeting
    call2_target, call2_msg = mock_ctx.send.call_args_list[1][0]
    assert call2_target == user_address
    assert isinstance(call2_msg, ChatMessage)
    assert "केयररूट" in call2_msg.content[0].text


@pytest.mark.anyio
async def test_acp_symptom_routing_and_session_persistence():
    """Verify incoming text symptom message sends ACK and routes to diagnostic worker."""
    user_address = "agent1q_test_patient_symptom_user"
    msg_id = uuid4()
    symptom_text = "मुझे दो हफ्ते से खांसी और बुखार है"
    chat_msg = ChatMessage(
        timestamp=datetime.datetime.now(datetime.timezone.utc),
        msg_id=msg_id,
        content=[TextContent(type="text", text=symptom_text)],
    )

    mock_ctx = MagicMock()
    mock_ctx.send = AsyncMock()
    mock_ctx.logger = MagicMock()

    await handle_acp_chat_message(mock_ctx, user_address, chat_msg)

    # Call 1: ACK
    assert mock_ctx.send.call_count == 2
    ack_target, ack_msg = mock_ctx.send.call_args_list[0][0]
    assert ack_target == user_address
    assert isinstance(ack_msg, ChatAcknowledgement)

    # Call 2: Worker IPC
    ipc_target, ipc_msg = mock_ctx.send.call_args_list[1][0]
    assert ipc_target == WORKER_ADDRESSES["diagnostic"]
    assert ipc_msg.text_transcript == symptom_text
    assert ipc_msg.user_address == user_address

    # Verify session persisted in session_store with user_address key
    session = session_store.get_or_create_session(user_address)
    assert session["user_address"] == user_address
    assert session["state"] == "STATE_ANALYZING"


@pytest.mark.anyio
async def test_all_worker_responses_dispatch_chat_to_user():
    """
    Verify finding #3 fix: every worker response handler MUST dispatch
    a user-facing ChatMessage to session['user_address'].
    """
    user_address = "agent1q_test_patient_flow_complete"
    session = session_store.get_or_create_session(user_address)
    session["user_address"] = user_address
    session_store.save_session(user_address, session)

    mock_ctx = MagicMock()
    mock_ctx.send = AsyncMock()
    mock_ctx.logger = MagicMock()

    # 1. Triage response
    dummy_dossier = ClinicalDossier(
        dossier_id="DOS-TEST01",
        session_id=user_address,
        patient_id="PAT-TEST",
        patient_name="Ram Kumar",
        created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        subjective=SubjectiveSOAP(
            patient_chief_complaint_hindi="खांसी और बुखार",
            chief_complaint_english="Productive cough and fever",
            history_of_present_illness="Patient reports 2 weeks of evening fever and cough.",
            symptom_duration="14 days",
            associated_symptoms=["Fever"],
            past_medical_history=[],
        ),
        objective=ObjectiveSOAP(),
        assessment=AssessmentSOAP(
            triage_urgency=TriageUrgency.HIGH,
            recommended_specialty="Pulmonology",
            recommended_specialty_hindi="छाती रोग विशेषज्ञ",
            differential_diagnoses=["Tuberculosis suspicion"],
            clinical_rationale="Patient meets symptomatic criteria for pulmonology evaluation.",
        ),
        plan=PlanSOAP(
            suggested_investigations=["Sputum AFB smear", "Chest X-Ray PA view"],
            interim_patient_advice_hindi="गुनगुना पानी पिएं। खांसते समय मास्क लगाएं।",
            interim_patient_advice_english="Drink warm water and wear a mask when coughing.",
            red_flag_warnings=["सीने में तेज दर्द", "बलगम में खून आना"],
        ),
    )
    triage_resp = TriageAnalysisResponse(
        session_id=user_address,
        patient_id="PAT-TEST",
        dossier=dummy_dossier,
        hindi_summary="जांच के अनुसार छाती विशेषज्ञ को दिखाएं",
        is_emergency=False,
    )
    await handle_triage_response(mock_ctx, "diagnostic_worker_addr", triage_resp)
    assert mock_ctx.send.call_count == 1
    target, chat = mock_ctx.send.call_args_list[-1][0]
    assert target == user_address
    assert isinstance(chat, ChatMessage)
    assert "छाती रोग विशेषज्ञ" in chat.content[0].text

    # 2. Slot response
    slot_resp = SlotQueryResponse(
        session_id=user_address,
        clinic_name="अलवर सीएचसी",
        doctor_name="Dr. Harish Sharma",
        specialty="Pulmonology",
        room_no="कक्ष 4",
        slots=[{"slot_id": "SLOT_1", "time": "10:00 AM", "capacity": 5}],
    )
    await handle_slot_response(mock_ctx, "logistics_worker_addr", slot_resp)
    assert mock_ctx.send.call_count == 2
    target, chat = mock_ctx.send.call_args_list[-1][0]
    assert target == user_address
    assert isinstance(chat, ChatMessage)
    assert "अलवर सीएचसी" in chat.content[0].text

    # 3. Escrow lock response
    escrow_resp = EscrowLockResponse(
        session_id=user_address,
        ticket_id="TICKET-1234",
        status="LOCKED",
        amount_fet=0.5,
        tx_hash="0xsimulated_lock_tx",
        created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    )
    await handle_escrow_lock_response(mock_ctx, "escrow_worker_addr", escrow_resp)
    assert mock_ctx.send.call_count == 3
    target, chat = mock_ctx.send.call_args_list[-1][0]
    assert target == user_address
    assert isinstance(chat, ChatMessage)
    assert "बुकिंग सफलतापूर्वक सुनिश्चित" in chat.content[0].text
