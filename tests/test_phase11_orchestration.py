"""
Tests for Phase 11: Orchestration Quality & Real Tools.
Verifies distributed correlation IDs, request timeout watchdog & retry recovery,
graceful degradation, rate limits, input length controls, system health check,
and OpenStreetMap / Overpass GeoService with offline fallback.
"""

import time
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from config import Config
from services.geo_service import GeoService, haversine_distance_km, VERIFIED_CHC_DIRECTORY
from services.health_check import check_system_health, check_database, check_roster
from models.chat_models import (
    TriageAnalysisRequest,
    TriageAnalysisResponse,
    SlotQueryRequest,
    SlotQueryResponse,
    BookingCommitRequest,
    BookingCommitResponse,
    EscrowLockRequest,
    EscrowLockResponse,
)
from agents.dispatcher import (
    _process_user_text,
    request_timeout_watchdog,
    session_store,
    MAX_INPUT_LENGTH,
    _SENDER_MESSAGE_TIMESTAMPS,
    WORKER_ADDRESSES,
)


def test_correlation_id_presence():
    """Verify all worker IPC models include correlation_id for distributed tracing."""
    t_req = TriageAnalysisRequest(
        session_id="user1", patient_id="p1", text_transcript="cough"
    )
    assert t_req.correlation_id is not None
    assert len(t_req.correlation_id) == 8

    s_req = SlotQueryRequest(session_id="user1", specialty="Pulmonology")
    assert s_req.correlation_id is not None

    b_req = BookingCommitRequest(
        session_id="user1", patient_id="p1", patient_name="Ram", slot_id="S1", dossier_id="D1"
    )
    assert b_req.correlation_id is not None


@pytest.mark.anyio
async def test_input_length_limit():
    """Verify input text exceeding 1500 chars is rejected with length warning."""
    ctx = MagicMock()
    ctx.send = AsyncMock()
    ctx.logger = MagicMock()

    user_addr = "agent1q_test_length_limit"
    session = session_store.get_or_create_session(user_addr)

    long_text = "खांसी " * 400  # > 1500 characters
    assert len(long_text) > MAX_INPUT_LENGTH

    await _process_user_text(ctx, user_addr, session, long_text)

    assert ctx.send.call_count == 1
    _, chat_msg = ctx.send.call_args[0]
    assert "बहुत लंबा है" in chat_msg.content[0].text
    assert "1500" in chat_msg.content[0].text


@pytest.mark.anyio
async def test_rate_limit_per_sender():
    """Verify exceeding 20 requests per minute triggers rate limit warning."""
    ctx = MagicMock()
    ctx.send = AsyncMock()
    ctx.logger = MagicMock()

    user_addr = "agent1q_test_rate_limit"
    session = session_store.get_or_create_session(user_addr)

    # Pre-fill timestamps to threshold
    now = time.time()
    _SENDER_MESSAGE_TIMESTAMPS[user_addr] = [now - 10] * 20

    await _process_user_text(ctx, user_addr, session, "नमस्ते डॉक्टर साहब")

    assert ctx.send.call_count == 1
    _, chat_msg = ctx.send.call_args[0]
    assert "बहुत अधिक संदेश" in chat_msg.content[0].text

    # Clear rate limit table
    _SENDER_MESSAGE_TIMESTAMPS.pop(user_addr, None)


@pytest.mark.anyio
async def test_watchdog_timeout_and_single_retry():
    """Verify timeout watchdog detects overdue requests and retries exactly once."""
    ctx = MagicMock()
    ctx.send = AsyncMock()
    ctx.logger = MagicMock()

    user_addr = "agent1q_test_timeout_retry"
    session = session_store.get_or_create_session(user_addr)
    # Simulate an overdue triage request sent 12 seconds ago
    session["pending_request"] = {
        "type": "triage",
        "sent_at": time.time() - 12.0,
        "retries": 0,
        "correlation_id": "test_c01",
        "text_transcript": "मुझे बुखार है",
    }
    session_store.save_session(user_addr, session)

    with patch.dict(WORKER_ADDRESSES, {"diagnostic": "agent1q_diagnostic_mock"}):
        await request_timeout_watchdog(ctx)

    # Verify a retry request was dispatched
    assert ctx.send.call_count == 1
    target, req = ctx.send.call_args[0]
    assert target == "agent1q_diagnostic_mock"
    assert isinstance(req, TriageAnalysisRequest)
    assert req.correlation_id == "test_c01"

    # Verify session updated retry count
    updated = session_store.get_or_create_session(user_addr)
    assert updated["pending_request"]["retries"] == 1


@pytest.mark.anyio
async def test_watchdog_graceful_degradation_on_exhausted_retries():
    """Verify watchdog notifies user and clears request when retry has also timed out."""
    ctx = MagicMock()
    ctx.send = AsyncMock()
    ctx.logger = MagicMock()

    user_addr = "agent1q_test_timeout_exhausted"
    session = session_store.get_or_create_session(user_addr)
    # Simulate retry attempt that has now also timed out
    session["pending_request"] = {
        "type": "triage",
        "sent_at": time.time() - 15.0,
        "retries": 1,
        "correlation_id": "test_c02",
    }
    session_store.save_session(user_addr, session)

    await request_timeout_watchdog(ctx)

    # Verify graceful degradation notification dispatched to user
    assert ctx.send.call_count == 1
    target, chat_msg = ctx.send.call_args[0]
    assert target == user_addr
    assert "अधिक समय लग रहा है" in chat_msg.content[0].text
    assert "108" in chat_msg.content[0].text

    # Verify pending request cleared
    updated = session_store.get_or_create_session(user_addr)
    assert updated.get("pending_request") is None


def test_haversine_distance_calculation():
    """Verify mathematical correctness of Haversine distance formula."""
    # Distance between Alwar (27.5530, 76.6346) and Behror (27.8872, 76.2806) is ~51.5 km
    dist = haversine_distance_km(27.5530, 76.6346, 27.8872, 76.2806)
    assert 50.0 < dist < 55.0


def test_geo_service_offline_verified_fallback(tmp_path):
    """Verify GeoService returns verified CHC directory sorted by distance when offline."""
    geo = GeoService(cache_dir=tmp_path, request_timeout=0.01)

    # Force live query to fail by using unrouteable IP
    with patch.object(geo, "OVERPASS_URL", "http://192.0.2.1:9999/dummy"):
        chcs = geo.find_nearest_chc(latitude=27.5530, longitude=76.6346, max_results=3)

    assert len(chcs) == 3
    # Nearest to Alwar CHC coordinates should be Alwar CHC itself (distance ~0 km)
    assert "Alwar" in chcs[0]["name"]
    assert chcs[0]["distance_km"] < 1.0
    assert chcs[0]["emergency_helpline"] == "108"
    assert chcs[0]["source"] == "verified_offline_directory"
    # Second should be within 55 km
    assert chcs[1]["distance_km"] > chcs[0]["distance_km"]


def test_geo_service_caching(tmp_path):
    """Verify GeoService writes to and reads from persistent cache."""
    geo = GeoService(cache_dir=tmp_path)
    mock_data = [
        {"id": "c1", "name": "Cached CHC", "latitude": 27.5, "longitude": 76.6, "distance_km": 2.5, "source": "osm_overpass_live"}
    ]

    with patch.object(geo, "query_overpass_chcs", return_value=mock_data):
        res1 = geo.find_nearest_chc(latitude=27.5, longitude=76.6, max_results=1)

    assert res1[0]["name"] == "Cached CHC"
    assert geo.cache_file.exists()

    # Second call should read from cache without calling query_overpass_chcs
    with patch.object(geo, "query_overpass_chcs", side_effect=Exception("Should not be called")):
        res2 = geo.find_nearest_chc(latitude=27.5, longitude=76.6, max_results=1)

    assert res2[0]["name"] == "Cached CHC"
    assert res2[0]["source"] == "osm_overpass_cached"


def test_system_health_check():
    """Verify system health check runs and validates core subsystems."""
    Config.ensure_directories()
    health = check_system_health()
    assert health["status"] in ("HEALTHY", "DEGRADED")
    assert "database" in health["components"]
    assert "roster" in health["components"]
    assert "storage" in health["components"]
    assert "geo_service" in health["components"]
    assert health["components"]["database"]["status"] == "HEALTHY"
    assert health["components"]["roster"]["status"] == "HEALTHY"
    assert health["components"]["storage"]["status"] == "HEALTHY"
