from __future__ import annotations

import logging
import sqlite3
from typing import Any

from config import Config
from services.clinic_roster import ClinicRosterService
from services.geo_service import GeoService

logger = logging.getLogger("CareRoute.HealthCheck")


def check_database() -> dict[str, Any]:
    """Verify SQLite database connectivity and schema tables."""
    try:
        with sqlite3.connect(Config.DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}
            expected = {"appointments", "slots", "escrow", "patient_sessions"}
            missing = expected - tables
            if missing:
                return {"status": "DEGRADED", "tables": list(tables), "missing": list(missing)}
            return {"status": "HEALTHY", "tables": list(tables)}
    except Exception as exc:
        return {"status": "UNHEALTHY", "error": str(exc)}


def check_roster() -> dict[str, Any]:
    """Verify clinic roster data loading."""
    try:
        service = ClinicRosterService()
        specs = service.roster_data.get("specialties", {})
        total_slots = sum(len(doc.get("slots", [])) for doc in specs.values())
        return {
            "status": "HEALTHY",
            "clinic_name": service.roster_data.get("clinic_name"),
            "specialties_count": len(specs),
            "total_slots": total_slots,
        }
    except Exception as exc:
        return {"status": "UNHEALTHY", "error": str(exc)}


def check_storage() -> dict[str, Any]:
    """Verify disk storage directory permissions."""
    try:
        Config.ensure_directories()
        test_file = Config.DOSSIERS_DIR / ".health_check.tmp"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink()
        return {"status": "HEALTHY", "storage_dir": str(Config.DATA_STORAGE_DIR)}
    except Exception as exc:
        return {"status": "UNHEALTHY", "error": str(exc)}


def check_geo_service() -> dict[str, Any]:
    """Verify GeoService returns verified CHCs (live or offline fallback)."""
    try:
        geo = GeoService()
        chcs = geo.find_nearest_chc(max_results=2)
        if len(chcs) >= 1:
            return {
                "status": "HEALTHY",
                "nearest_facility": chcs[0]["name"],
                "source": chcs[0]["source"],
            }
        return {"status": "DEGRADED", "nearest_facility": None}
    except Exception as exc:
        return {"status": "UNHEALTHY", "error": str(exc)}


def check_system_health() -> dict[str, Any]:
    """
    Comprehensive startup and operational health check for CareRoute.
    Returns status: HEALTHY, DEGRADED, or UNHEALTHY.
    """
    db_res = check_database()
    roster_res = check_roster()
    storage_res = check_storage()
    geo_res = check_geo_service()

    components = {
        "database": db_res,
        "roster": roster_res,
        "storage": storage_res,
        "geo_service": geo_res,
    }

    all_statuses = [c["status"] for c in components.values()]
    if all(s == "HEALTHY" for s in all_statuses):
        overall = "HEALTHY"
    elif any(s == "UNHEALTHY" for s in all_statuses):
        overall = "UNHEALTHY"
    else:
        overall = "DEGRADED"

    return {
        "status": overall,
        "components": components,
        "payment_mode": Config.PAYMENT_MODE,
        "use_agentverse": Config.USE_AGENTVERSE,
        "use_interactive_cards": Config.USE_INTERACTIVE_CARDS,
    }
