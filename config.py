from __future__ import annotations

import builtins
import os
from pathlib import Path

from dotenv import load_dotenv

# Ensure default UTF-8 text encoding on Windows (prevents cp1252 decode errors on Devanagari text)
_orig_open = builtins.open


def _safe_open(file, mode="r", *args, **kwargs):
    if "b" not in mode and "encoding" not in kwargs:
        kwargs["encoding"] = "utf-8"
    return _orig_open(file, mode, *args, **kwargs)


builtins.open = _safe_open

BASE_DIR = Path(__file__).resolve().parent
# Load .env file if present
load_dotenv(BASE_DIR / ".env")


def _get_seed(env_var_name: str) -> str:
    """Retrieve an agent seed from environment or raise an explicit configuration error."""
    val = os.getenv(env_var_name)
    if not val or val.strip() in ("", "CHANGE_ME"):
        # If running inside pytest or test mode, provide an explicit test-only seed
        if "PYTEST_CURRENT_TEST" in os.environ or os.getenv("CAREROUTE_TEST_MODE") == "1":
            return f"test_mock_seed_phrase_for_{env_var_name.lower()}_only"
        raise ValueError(
            f"CRITICAL SECURITY CONFIGURATION ERROR: Missing required seed '{env_var_name}'. "
            f"Never commit private keys to git. Please run 'python scripts/generate_seeds.py' "
            f"and paste the generated phrases into your local .env file."
        )
    return val.strip()


class ConfigMeta(type):
    """Metaclass allowing class-level property access for dynamic seed lookup."""
    @property
    def DISPATCHER_SEED(cls) -> str:
        return _get_seed("DISPATCHER_SEED")

    @property
    def DIAGNOSTIC_SEED(cls) -> str:
        return _get_seed("DIAGNOSTIC_SEED")

    @property
    def LOGISTICS_SEED(cls) -> str:
        return _get_seed("LOGISTICS_SEED")

    @property
    def ESCROW_SEED(cls) -> str:
        return _get_seed("ESCROW_SEED")


class Config(metaclass=ConfigMeta):
    """Central configuration for CareRoute multi-agent telehealth network."""

    # Host & Port Configurations
    AGENT_HOST: str = os.getenv("AGENT_HOST", "127.0.0.1")
    DISPATCHER_PORT: int = int(os.getenv("DISPATCHER_PORT", "8000"))
    DIAGNOSTIC_PORT: int = int(os.getenv("DIAGNOSTIC_PORT", "8001"))
    LOGISTICS_PORT: int = int(os.getenv("LOGISTICS_PORT", "8002"))
    ESCROW_PORT: int = int(os.getenv("ESCROW_PORT", "8003"))

    # Cryptographic Seed Phrases for Fetch.ai Agents (Must be in .env)
    @classmethod
    def get_dispatcher_seed(cls) -> str:
        return _get_seed("DISPATCHER_SEED")

    @classmethod
    def get_diagnostic_seed(cls) -> str:
        return _get_seed("DIAGNOSTIC_SEED")

    @classmethod
    def get_logistics_seed(cls) -> str:
        return _get_seed("LOGISTICS_SEED")

    @classmethod
    def get_escrow_seed(cls) -> str:
        return _get_seed("ESCROW_SEED")

    # Agentverse / ASI:One Gateway Configuration
    AGENTVERSE_API_KEY: str = os.getenv("AGENTVERSE_API_KEY", "")
    AGENT_MAILBOX_KEY: str = os.getenv("AGENT_MAILBOX_KEY", "")
    USE_AGENTVERSE: bool = os.getenv("USE_AGENTVERSE", "false").lower() in ("true", "1", "yes")
    AGENTVERSE_URL: str = os.getenv("AGENTVERSE_URL", "https://agentverse.ai")

    # Primary ASI:One LLM API (OpenAI-compatible)
    ASI1_API_KEY: str = os.getenv("ASI1_API_KEY", "")
    ASI1_BASE_URL: str = os.getenv("ASI1_BASE_URL", "https://api.asi1.ai/v1")
    ASI1_MODEL: str = os.getenv("ASI1_MODEL", "asi1-mini")

    # Optional Fallback Engines
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    USE_MOCK_VLM: bool = os.getenv("USE_MOCK_VLM", "true").lower() in ("true", "1", "yes")

    # Escrow & Payment Protocol Parameters
    PAYMENT_MODE: str = os.getenv("PAYMENT_MODE", "simulation").lower()
    ESCROW_DEPOSIT_FET: float = float(os.getenv("ESCROW_DEPOSIT_FET", "0.5"))
    ESCROW_TOKEN_DENOM: str = os.getenv("ESCROW_TOKEN_DENOM", "atestfet")
    FETCH_TESTNET_RPC: str = os.getenv("FETCH_TESTNET_RPC", "https://rpc-dorado.fetch.ai:443")

    # Clinic Authentication & Anti-Fraud Security
    DEFAULT_CLINIC_ID: str = os.getenv("DEFAULT_CLINIC_ID", "chc_alwar_01")
    CLINIC_DESK_ADDRESSES: list[str] = [
        addr.strip()
        for addr in os.getenv(
            "CLINIC_DESK_ADDRESSES",
            "alwar_chc_reception_desk,clinic_reception_desk,desk_test,chc_desk_01",
        ).split(",")
        if addr.strip()
    ]
    CLINIC_DESK_TOKEN: str = os.getenv("CLINIC_DESK_TOKEN", "")

    # UI Options
    USE_INTERACTIVE_CARDS: bool = os.getenv("USE_INTERACTIVE_CARDS", "true").lower() in (
        "true", "1", "yes"
    )

    # Data Storage Paths
    DATA_STORAGE_DIR: Path = BASE_DIR / os.getenv("DATA_STORAGE_DIR", "data")
    DATA_DIR: Path = DATA_STORAGE_DIR
    DOSSIERS_DIR: Path = DATA_STORAGE_DIR / "dossiers"
    BOOKINGS_DIR: Path = DATA_STORAGE_DIR / "bookings"
    DB_PATH: Path = DATA_STORAGE_DIR / "careroute.db"
    ROSTER_PATH: Path = DATA_STORAGE_DIR / "clinic_roster.json"
    DATA_RETENTION_DAYS: int = int(os.getenv("DATA_RETENTION_DAYS", "30"))

    @classmethod
    def ensure_directories(cls) -> None:
        """Create local data storage directories if they do not exist."""
        cls.DATA_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        cls.DOSSIERS_DIR.mkdir(parents=True, exist_ok=True)
        cls.BOOKINGS_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def get_agent_endpoint(cls, port: int) -> str:
        """Format an agent HTTP endpoint."""
        return f"http://{cls.AGENT_HOST}:{port}/submit"


# Initialize storage directories on load
Config.ensure_directories()
