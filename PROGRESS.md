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
| Phase 2 | Real ACP in Dispatcher | ⏳ NEXT | Replace custom chat with real `uagents_core` ACP spec |
| Phase 3 | Agentverse registration & discoverability | ⏳ PENDING | Mailbox mode, agentverse_readme.md, check_registration.py |
| Phase 4 | Doctor dossier persistence | ⏳ PENDING | Save before booking, Pydantic v2 model_dump_json/model_validate |
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
- **Tests Passing**: 5/5 passing in `test_careroute.py` under `pytest`.
- **Open Items**: Proceeding to Phase 2 (Real ACP in dispatcher).
- **Exact Next Step**: Phase 2 — Replace custom `ChatMessage`/`ChatResponse` with real `uagents_core.contrib.protocols.chat` Protocol (`chat_protocol_spec`), implement `ChatAcknowledgement`, process `StartSessionContent`, `TextContent`, `EndSessionContent`, map sender addresses as session keys, and dispatch replies back to `session["user_address"]`.
