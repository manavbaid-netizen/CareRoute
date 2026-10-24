# CareRoute Engineering Progress Tracker (Fetch-a-thon 3.0)

## Overview
- Project: CareRoute (केयररूट) - Hindi-first rural telehealth bridge connecting patients on ASI:One to CHC doctors
- Python Version: >= 3.10 (Running 3.11.2)
- Framework: Fetch.ai uAgents 0.26.1, uAgents-core 0.4.12, Pydantic v2 (2.14.1), Pytest 9.1.1, Ruff 0.17.2

---

## Phase Status Summary

| Phase | Description | Status | Commit / Notes |
|---|---|---|---|
| Step 0 | Setup, clean venv, baseline run | ✅ DONE | Baseline 5 tests pass, demo baseline verified |
| Phase 1 | Repo hygiene, secret removal, .gitignore, config safety | ✅ DONE | Leaked seeds removed, seed generator created, .gitignore active |
| Phase 2 | Real ACP in Dispatcher | ✅ DONE | Real `chat_protocol_spec` included, ACKs + ChatMessage replies at every step, sessions keyed by sender address, SQLite session persistence |
| Phase 3 | Agentverse registration & discoverability | ✅ DONE | Mailbox mode parameters verified & wired, agentverse_readme.md, topology documented, check_registration.py |
| Phase 4 | Doctor dossier persistence | ✅ DONE | Dossier saved right after triage, real dossier_id propagated, Pydantic v2 model_validate_json/model_dump, retention cleanup, verified agent-driven flow |
| Phase 7 | Emergency detection & 108 SOS tripwires | ✅ DONE | Layered regex + Devanagari/Hinglish safety rules + Tele-MANAS/108 helplines + 65-case red flag corpus (100% recall) |
| Phase 6 | Clinical safety, zero fabrication | ✅ DONE | Zero fabricated vitals/PMH/Rx, NTEP TB criteria (cough > 2w + B-symptoms), General Medicine default for unclassified, disclaimers, clarifying questions |
| Phase 5 | ASI1 LLM core reasoning engine | ✅ DONE | OpenAI-compatible ASI:One client with multi-tier fallback (ASI1 -> Gemini -> OpenAI -> Deterministic), error correction retry, honest vision handling, provenance |
| Phase 8 | Real Payment Protocol & secure escrow | ✅ DONE | Official `payment_protocol_spec` with `seller` role, `CommitPayment` handler, SQLite `escrow` table (single source of truth), clinic desk auth, double-refund prevention, honest simulation labelling |
| Phase 9 | Booking logic & capacity | ✅ DONE | Atomic capacity decrement, per-date slots, Specialty enum, honest slot errors, foreign keys, deterministic patient identity |
| Phase 10 | ASI1 Interactive Cards | ✅ DONE | Pydantic v2 InteractiveCard schema, MetadataContent ACP packaging, mobile touch labels, robust numbered text fallback, action parsing |
| Phase 11 | Orchestration & Tools | ✅ DONE | Correlation IDs, timeout & 1-retry watchdog, OpenStreetMap Overpass CHC locator with caching/fallback, health check, rate limits |
| Phase 12 | Tests, CI, Docs & README | ✅ DONE | GitHub Actions CI workflow, honest README with Innovation Lab badges, demo script, Devpost submission, main.py check, 74/74 tests passing |

---

## Phase 1 Detail
- **Phases Done**: Step 0, Phase 1
- **Files Changed**:
  - `requirements.txt`: Added rich, pytest, ruff, pinned versions, python >= 3.10.
  - `.gitignore`: Created; excludes `.venv`, `.env`, `data/*.db`, `data/dossiers/`, `data/bookings/`, `__MACOSX/`, `.DS_Store`.
  - `.env.example`: Sanitized all leaked seeds to `CHANGE_ME`, added all config keys.
  - `config.py`: Hardcoded seed defaults removed; dynamic property lookup with clear `ValueError` on missing seeds.
  - `scripts/generate_seeds.py`: Created high-entropy 12-word cryptographic seed generator.
  - `data/clinic_roster.json` & `data/seed/clinic_roster.json`: Structured CHC doctor & slot roster created.
  - `pyproject.toml`: Ruff & pytest configurations added.
  - `Makefile`: `test`, `run`, `demo`, `lint`, `check`, `generate-seeds`, `clean`.
  - `PROGRESS.md`: Initialized.
## Phase 2 Detail
- **Phases Done**: Step 0, Phase 1, Phase 2
- **Files Changed**:
  - `models/chat_models.py`: Removed custom `ChatMessage`/`ChatResponse`; re-exported official `uagents_core.contrib.protocols.chat` ACP types; added `create_text_chat` and `create_ack` helpers.
  - `models/cards.py`: Added `card_to_markdown` renderer for accessible plain-text ACP fallback rendering.
  - `services/session_store.py`: Created SQLite-backed `SessionStore` ensuring restart persistence and sessions keyed by sender address.
  - `agents/dispatcher.py`: Attached `chat_proto` with `chat_protocol_spec` and `publish_manifest=True`; immediate `ChatAcknowledgement` for every message; processed `StartSessionContent`, `EndSessionContent`, `ResourceContent`, `TextContent`; updated all worker handlers to send user-facing `ChatMessage` to `session["user_address"]`; implemented watchdog timeout/retry on interval.
  - `run_all.py`: Multi-process agent launcher avoiding port override collisions.
  - `tests/test_phase2_acp.py`: 6 tests verifying digest equality with uagents-core, ACP helpers, ACK dispatch, symptom routing, and full worker-to-user dispatch.
## Phase 3 Detail
- **Phases Done**: Step 0, Phase 1, Phase 2, Phase 3
- **Files Changed**:
  - `agents/dispatcher.py`: Wired `mailbox` and `agentverse` parameters dynamically; logged inspector and profile URLs; enabled UTF-8 support.
  - `agentverse_readme.md`: Created complete profile description with Hindi, Hinglish, English sample queries, clinical disclaimer, and Innovation Lab badges for ASI:One discovery.
  - `docs/topology.md`: Documented hybrid gateway pattern (public Dispatcher on Agentverse mailbox, internal workers on local IPC).
  - `scripts/check_registration.py`: Created script to query Almanac, inspect agent addresses, check discovery status, and output submission URLs.
## Phase 4 Detail
- **Phases Done**: Step 0, Phase 1, Phase 2, Phase 3, Phase 4
- **Files Changed**:
  - `services/dossier_generator.py`: Updated `save_dossier` with Pydantic v2 `model_dump()`; `load_dossier` with `model_validate_json()`; added `cleanup_old_dossiers` for `DATA_RETENTION_DAYS`.
  - `models/clinical_schemas.py`: Added `engine`, `session_id`, and `disclaimer` fields to `ClinicalDossier`.
  - `agents/diagnostic_worker.py`: Immediately persists the synthesized dossier after triage; silenced full raw transcripts from INFO logs.
  - `agents/logistics_worker.py`: Loads the real dossier by `msg.dossier_id`, saves ticket-indexed slip, updates DB `dossier_path`, returns `ERROR_MISSING_DOSSIER` on failure.
  - `services/clinic_roster.py`: Added schema migration for `dossier_path`, `slot_date`, `qr_hash` and `update_dossier_path` method.
  - `tests/test_phase4_dossier.py`: 4 tests verifying Pydantic v2 roundtrip, data retention cleanup, agent-driven file persistence, and rejection of missing dossier IDs.
## Phase 7 Detail
- **Phases Done**: Step 0, Phase 1, Phase 2, Phase 3, Phase 4, Phase 7
- **Files Changed**:
  - `services/safety.py`: Created layered `SafetyService` covering 16+ acute life-threatening categories (cardiac chest pain, breathlessness, cyanosis, hemoptysis, unconsciousness, seizures, stroke, snake/animal bites, poisoning, burns, obstetric emergencies, suicidal crisis, meningitis). Added clause-aware negation handling preventing false positives (e.g. "no chest pain", "सीने में दर्द नहीं है") without cancelling distinct negative clauses (e.g. "बेहोश हो गया और उठ नहीं रहा"). Configured verified Indian national helplines: 108 Ambulance, 112 National Emergency, Tele-MANAS (14416 / 1800-891-4416), and Kiran (1800-599-0019).
  - `data/redflag_test_cases.json`: Created 65 labelled test cases in Hindi, Hinglish, and English covering all critical categories, negative controls, and negation variants.
  - `services/vlm_service.py`: Replaced crude keyword scan with `SafetyService.scan_for_emergencies()`; updated tripwire response generation to incorporate category-specific actions and Tele-MANAS mental health helplines.
  - `main.py`: Updated Scenario 2 to verify live detection of life-threatening emergencies with real assertions.
  - `tests/test_phase7_redflags.py`: Added 7 comprehensive tests verifying Finding 7 exact phrases, previously missed phrases, negation controls, Tele-MANAS routing, and full 65-case corpus achieving 100% recall.
## Phase 6 Detail
- **Phases Done**: Step 0, Phase 1, Phase 2, Phase 3, Phase 4, Phase 7, Phase 6
- **Files Changed**:
  - `services/vlm_service.py`: Removed all fabricated clinical data: vitals default to empty `{}`; past medical history defaults to `[]`; OCR prescriptions default to `[]`. Prohibited medication prescribing in plan advice (non-pharmacological home care & comfort measures only). Replaced crude substring matching with robust Devanagari/English regexes. Enforced NTEP clinical criteria for TB suspect (strictly cough >= 2 weeks AND constitutional B-symptoms). Defaulted all unclassified and non-TB presentations to `General Medicine` ("Unclassified symptom presentation; needs in-person evaluation") instead of defaulting to TB. Added `get_clarifying_questions()` returning up to 3 polite Hindi questions when duration, name/age, or chronic conditions are missing. Added mandatory clinical disclaimers in Hindi and English (`CLINICAL_DISCLAIMER_HI` and `CLINICAL_DISCLAIMER_EN`) to every patient-facing message and doctor dossier.
  - `tests/test_phase6_safety.py`: Added 8 tests asserting: 10 unrelated symptoms (leg injury, headache/dizziness, acute fever 2d, rash, knee pain, stomach ache, sore throat, back strain, eye irritation, acute gastroenteritis) never trigger a TB workup; zero fabricated vitals; zero fabricated past medical history; zero fabricated prescriptions; NTEP criteria precision; word boundary safety; clinical disclaimers everywhere; and clarifying questions generation.
## Phase 5 Detail
- **Phases Done**: Step 0, Phase 1, Phase 2, Phase 3, Phase 4, Phase 7, Phase 6, Phase 5
- **Files Changed**:
  - `services/llm_client.py`: Created `LLMClient` with unified multi-tier fallback architecture: Primary ASI:One OpenAI-compatible endpoint (`ASI1_API_KEY`, `ASI1_BASE_URL`, `ASI1_MODEL`) -> Secondary Google Gemini (`gemini-2.5-flash`) -> Tertiary OpenAI (`gpt-4o-mini`) -> Deterministic clinical intelligence engine. Added clean JSON fence stripper and 1-attempt error correction retry prompt on schema validation failures. Implemented honest vision handling (`HONEST_VISION_NOTE_HI` / `HONEST_VISION_NOTE_EN`), honestly informing users when visual models are unavailable without hallucinating morphological lesions. Implemented strict provenance recording in `dossier.engine`.
  - `services/vlm_service.py`: Integrated `LLMClient` into `VLMService.analyze_case()`; removed fake morphological hallucination from lesion photo branch.
  - `tests/test_phase5_llm.py`: Added 7 tests covering valid JSON parsing, markdown fence stripping, malformed JSON retry recovery, persistent malformed fallback to deterministic engine, APITimeoutError handling, 401 AuthenticationError handling, honest vision fallback, and provenance tracking.
## Phase 8 Detail
- **Phases Done**: Step 0, Phase 1, Phase 2, Phase 3, Phase 4, Phase 7, Phase 6, Phase 5, Phase 8
- **Files Changed**:
  - `agents/escrow_worker.py`: Integrated official `uagents_core.contrib.protocols.payment` (`payment_protocol_spec`, `role="seller"`) with handlers for `CommitPayment` and `RejectPayment`. Implemented `create_payment_request()` ACP helper. Eliminated in-memory `_ESCROW_LEDGER` dict; unified all state into SQLite `escrow` table with atomic transitions (`PENDING` -> `LOCKED` -> `REFUNDED` / `CANCELLED`). Added strict clinic reception desk authentication (`CLINIC_DESK_ADDRESSES`) preventing patients from self-refunding (`status="UNAUTHORIZED"`). Added QR token integrity checks (`INVALID_TOKEN`) and atomic double-refund prevention (`ALREADY_RELEASED`). Replaced fake `0x{uuid4}` hashes with honest simulation labels: `[SIMULATED - PAYMENT_MODE=simulation]` and synthetic `sim_tx_...` / `sim_refund_...` hashes.
  - `services/clinic_roster.py`: Created SQLite `escrow` table schema; implemented atomic `create_escrow_deposit()`, `lock_escrow_deposit()`, `release_escrow_refund()`, `get_escrow()`, and `cancel_escrow()`.
  - `config.py`: Added default authorized clinic desk addresses in `CLINIC_DESK_ADDRESSES`.
  - `tests/test_phase8_escrow.py`: Added 8 tests covering official payment protocol inclusion, `RequestPayment` construction, `CommitPayment` verification and deposit locking, insufficient deposit cancellation, unauthorized patient check-in rejection, authorized clinic refund, double-refund prevention, invalid token rejection, and slot cancellation.
- **Tests Passing**: 45/45 tests passing at Phase 8.
## Phase 9 Detail
- **Phases Done**: Step 0, Phase 1, Phase 2, Phase 3, Phase 4, Phase 7, Phase 6, Phase 5, Phase 8, Phase 9
- **Files Changed**:
  - `services/clinic_roster.py`:
    - Loaded roster configuration dynamically from `data/clinic_roster.json` with fallback.
    - Defined explicit `Specialty` enum (`PULMONOLOGY`, `DERMATOLOGY`, `GENERAL_MEDICINE`, `EMERGENCY`) and mapping function `map_specialty()`.
    - Added per-date slots schema in SQLite (`slots` table) with `capacity` and `booked_count`.
    - Implemented atomic capacity decrement: `UPDATE slots SET booked_count = booked_count + 1 WHERE slot_id = ? AND slot_date = ? AND booked_count < capacity`.
    - Replaced silent fallback to pulmonology slot 0 with explicit `ValueError` raises (`SLOT_NOT_FOUND` and `SLOT_FULL`).
    - Enforced SQLite foreign keys (`PRAGMA foreign_keys = ON;`) linking `appointments`, `slots`, and `escrow` tables.
    - Added `reset_slot(slot_id, slot_date)` helper for deterministic tests and administration.
  - `services/session_store.py`:
    - Derived patient ID deterministically from user address (`PAT_{user_address[:10]}`) instead of session UUID.
    - Defaulted patient name to `"मरीज (Patient)"` rather than hardcoding to `"रामकुमार"`.
  - `agents/dispatcher.py`:
    - Added `extract_patient_name()` from conversational intro.
    - Handled `SLOT_FULL` and `SLOT_NOT_FOUND` with polite Hindi notices and prompt to select another slot.
  - `agents/logistics_worker.py`:
    - Validated clinical dossier existence *prior* to booking slot to prevent slot capacity leak on invalid bookings.
    - Caught `ValueError` from `book_appointment`, setting response status to `SLOT_FULL` or `SLOT_NOT_FOUND`.
  - `tests/test_phase9_booking.py`: Added 7 tests covering JSON roster loading, specialty enum mapping, atomic capacity limit, per-date slot isolation, unknown slot rejection, patient identity derivation, and SQLite foreign key constraints.
  - `tests/test_phase4_dossier.py`, `tests/test_phase8_escrow.py`, `test_careroute.py`: Reset test slot capacities in test fixtures.
  - `pyproject.toml`: Configured `norecursedirs` to ignore `.venv`, preventing pytest recursive scan delays.
- **Tests Passing**: 52/52 tests passing at Phase 9.
## Phase 10 Detail
- **Phases Done**: Step 0, Phase 1, Phase 2, Phase 3, Phase 4, Phase 7, Phase 6, Phase 5, Phase 8, Phase 9, Phase 10
- **Files Changed**:
  - `models/cards.py`:
    - Defined Pydantic v2 schemas: `CardAction`, `CardHeader`, `CardFact`, `CardSection`, `CardTheme`, `InteractiveCard`.
    - Rebuilt all 4 card generators (`make_triage_detail_card`, `make_slot_picker_card`, `make_booking_receipt_card`, `make_emergency_sos_card`) with strict Pydantic model validation.
    - Implemented `card_to_markdown()` for plain-text fallback with explicit numbered touch targets (`[1]`, `[2]`, `[3]`).
    - Implemented `create_card_chat()` ACP helper emitting both accessible `TextContent` and `MetadataContent(card_kind, card_payload)` for native ASI:One UI rendering when `USE_INTERACTIVE_CARDS=True` (or text-only when `False`).
    - Added `parse_card_action()` to parse native JSON button tap payloads or numeric text choices ("1", "2", "#3").
    - Formatted concise, mobile-friendly button labels (e.g. `🕒 10:00 AM - 10:30 AM (3 बचे)`).
  - `agents/dispatcher.py`:
    - Replaced raw text calls with `create_card_chat()` across triage, slot query, and escrow lock responses.
    - Wired `parse_card_action()` into user message loop, cleanly handling button action JSON and numeric slot choices.
  - `tests/test_phase10_cards.py`: Added 10 tests covering schema validation for all 4 card types, markdown fallback formatting, ACP dual-content packaging (`TextContent` + `MetadataContent`), disabled interactive flag fallback, button JSON action parsing, numeric fallback choices, and mobile label length constraints.
- **Tests Passing**: 62/62 tests passing at Phase 10.
## Phase 11 Detail
- **Phases Done**: Step 0, Phase 1, Phase 2, Phase 3, Phase 4, Phase 7, Phase 6, Phase 5, Phase 8, Phase 9, Phase 10, Phase 11
- **Files Changed**:
  - `models/chat_models.py`: Added 8-char `correlation_id` default factory across all worker IPC models (`TriageAnalysisRequest/Response`, `SlotQueryRequest/Response`, `BookingCommitRequest/Response`, `EscrowLockRequest/Response`, `EscrowReleaseRequest/Response`).
  - `agents/diagnostic_worker.py`, `agents/logistics_worker.py`, `agents/escrow_worker.py`: Propagated `correlation_id` back in all worker responses.
  - `services/geo_service.py`: Created real-data tool using OpenStreetMap Overpass API (`https://overpass-api.de/api/interpreter`) with disk cache (`data/cache/osm_geo_cache.json`) and verified offline fallback directory of Alwar / Rajasthan CHCs with Haversine distance sorting.
  - `services/health_check.py`: Created comprehensive multi-subsystem health check (`check_system_health()`) validating SQLite tables, clinic roster, storage permissions, and geo service.
  - `agents/dispatcher.py`:
    - Enforced `MAX_INPUT_LENGTH = 1500` characters with polite Hindi notification.
    - Enforced per-sender rate limiting (`MAX_REQUESTS_PER_WINDOW = 20` requests / 60 seconds).
    - Distributed `correlation_id` generation and tracking in sessions and logs (`[CID: {cid}]`).
    - Implemented request timeout watchdog (`@dispatcher.on_interval(period=3.0)`) with 1-retry recovery and graceful degradation message upon retry exhaustion.
    - Routed natural language inquiries for nearby hospitals/CHCs to `GeoService`.
  - `tests/test_phase11_orchestration.py`: Added 9 tests covering correlation IDs, input length limits, per-sender rate limiting, watchdog timeout with single retry, graceful degradation on exhausted retry, Haversine formula calculation, offline verified CHC fallback, Overpass response caching, and system health checks.
- **Tests Passing**: 71/71 tests passing across entire suite.
## Phase 12 Detail
- **Phases Done**: Step 0, Phase 1, Phase 2, Phase 3, Phase 4, Phase 7, Phase 6, Phase 5, Phase 8, Phase 9, Phase 10, Phase 11, Phase 12 (ALL 12 PHASES COMPLETE)
- **Files Changed**:
  - `main.py`: Added `--check` diagnostic flag executing `check_system_health()`, transparent simulation labeling (`[SIMULATED - PAYMENT_MODE=simulation]`), slot reset in demo, and OpenStreetMap CHC locator panel.
  - `tests/test_phase12_e2e.py`: 3 end-to-end integration tests verifying full primary patient lifecycle (intake -> triage -> slot query -> escrow lock -> booking -> desk check-in -> 100% refund), concurrent atomic capacity booking race condition handling, and graceful degradation during external LLM outages.
  - `.github/workflows/ci.yml`: Production GitHub Actions CI running on `ubuntu-latest` with Python 3.11, running ruff linter and full pytest test suite.
  - `docs/demo_script.md`: Comprehensive 4-minute bilingual demo recording script with timing, split-screen layout, voiceover, and visual cues.
  - `docs/devpost_description.md`: Full Devpost hackathon submission text covering problem, architecture, Fetch.ai stack, innovations, and deliverables checklist.
  - `README.md`: Completely rewritten with Innovation Lab badges (`tag:innovationlab`, `tag:hackathon`), truthful capability disclosures, agent topology table, Mermaid diagrams, step-by-step ASI:One testing scenarios, and judging alignment matrix.
  - `pyproject.toml` & code hygiene: Configured Ruff linter and resolved all warnings (`All checks passed!`).
- **Tests Passing**: 74/74 tests passing across the entire test suite.
- **Verification**:
  - `python main.py --check` -> System Status: HEALTHY.
  - `python main.py --demo` -> Full simulated walkthrough verified with zero errors.
  - `ruff check .` -> All checks passed.
  - `pytest -v` -> 74 passed in 14.00s.
- **Open Items**: None. All 17 reviewer findings addressed and verified.
- **Exact Next Step**: Project is fully ready for Fetch-a-thon 3.0 submission, Git commit, and deployment to GitHub.

---

## Stability Update Detail (Hackathon Demo Resilience)
- **Status**: ✅ COMPLETED & VERIFIED
- **Files Changed**:
  - `services/llm_client.py`: Added `extract_clean_json()` with robust markdown fence and outermost brace extraction regex, integrated prior to schema parsing in `_parse_and_validate_json()`.
  - `services/vlm_service.py`: Re-exported `extract_clean_json()`, integrated acute respiratory risk triage routing into `_mock_clinical_analysis()`.
  - `services/geo_service.py`: Enforced strict `timeout=2.5` on Overpass network requests with `(requests.Timeout, requests.RequestException)` catch, logging brief warnings and fast fallback to local clinic records from `clinic_roster.json` and verified directory.
  - `services/safety.py`: Added `check_acute_respiratory_risk()` detecting acute cough accompanied by severe breathlessness, high fever (>102°F), or blood in sputum with clause-aware negation rules (`is_negated`), escalating urgency to High under General Medicine.
  - `tests/test_stability_updates.py`: 10 targeted tests verifying robust JSON parsing with fences/preambles, sub-second timeout fallback, acute respiratory risk escalation, and negation guardrails.
- **Tests Passing**: 84/84 tests passing across the entire test suite (`pytest -v`).
- **Demo Verification**: `python main.py --demo` verified running cleanly end-to-end.

## Agentverse Mailbox & Local Inspector Integration Update
- **Issue Diagnosed**: Agentverse returns `401: {"detail": "Could not validate credentials"}` when an agent polls its mailbox before Step 2 activation in Agentverse. Furthermore, modern Chromium browsers (Chrome, Edge, Brave) enforce Private Network Access and CORS preflight checks that blocked the Agentverse web UI from contacting `http://127.0.0.1:8000`.
- **Patches Applied**:
  - `agents/dispatcher.py`:
    - Injected CORS (`access-control-allow-origin: *`) and Private Network Access (`access-control-allow-private-network: true`) headers on `ASGIServer._asgi_send`.
    - Added `Mailbox401Filter` to suppress repetitive 401 polling logs and output a clean user guidance notice until activation completes.
  - `config.py`:
    - Dynamic `USE_AGENTVERSE` override for test runners to maintain clean offline unit test execution.
  - `agents/dispatcher.py`:
    - Added `_get_dispatcher_mailbox()` to support direct `AGENT_MAILBOX_KEY` injection (`mailbox=f"{Config.AGENT_MAILBOX_KEY}@https://agentverse.ai"`), bypassing local browser network restrictions completely.
  - `scripts/check_registration.py`:
    - Added display of `AGENT_MAILBOX_KEY` configuration status.


