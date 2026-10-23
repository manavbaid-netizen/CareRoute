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
| Phase 5 | ASI1 LLM core reasoning engine | ⏳ NEXT | OpenAI-compatible client for ASI:One, structured JSON output, fallback engine |
| Phase 8 | Real Payment Protocol & secure escrow | ⏳ PENDING | `payment_protocol_spec`, SQLite source of truth, clinic auth |
| Phase 9 | Booking logic & capacity | ⏳ PENDING | Atomic capacity decrement, slot dates, json roster, foreign keys |
| Phase 10 | ASI1 Interactive Cards | ⏳ PENDING | Interactive Card schemas with robust text fallback |
| Phase 11 | Orchestration & Tools | ⏳ PENDING | Timeouts, correlation IDs, OpenStreetMap/Overpass CHC locator |
| Phase 12 | Tests, CI, Docs & README | ⏳ PENDING | GitHub CI, updated README with badges, Devpost demo script |

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
- **Tests Passing**: 30/30 tests passing across entire suite.
- **Open Items**: Proceeding to Phase 5 (ASI1 LLM core reasoning engine).
- **Exact Next Step**: Phase 5 — Create `services/llm_client.py` for official ASI:One API (OpenAI-compatible), implement strict JSON triage validation against `ClinicalDossier`, handle timeouts/retries, integrate with VLMService, vision fallback with honesty (never pretend an image was read).
