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
| Phase 4 | Doctor dossier persistence | ⏳ NEXT | Save before booking, Pydantic v2 model_dump_json/model_validate |
| Phase 5 | ASI1 LLM core reasoning engine | ⏳ PENDING | Official ASI:One LLM API integration with fallback |
| Phase 6 | Clinical safety, zero fabrication | ⏳ PENDING | Remove fake vitals/history/Rx from fallback, ask clarifications |
| Phase 7 | Emergency detection & 108 SOS tripwires | ⏳ PENDING | Layered regex + Devanagari/Hinglish safety rules + 60+ test cases |
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
- **Tests Passing**: 11/11 tests passing.
- **Open Items**: Proceeding to Phase 4 (Doctor dossier persistence).
- **Exact Next Step**: Phase 4 — Persist dossier (.json + .md) immediately after triage, pass real `dossier_id` into booking, replace `.json()` with `model_dump_json(indent=2)` and `parse_obj` with `model_validate_json`, add `DATA_RETENTION_DAYS` cleanup helper, assert dossier files exist from agent interactions.
