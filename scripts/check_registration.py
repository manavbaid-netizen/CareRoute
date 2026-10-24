#!/usr/bin/env python3
"""
CareRoute Agentverse Registration & Discoverability Verification Script.
Checks whether the Dispatcher agent is registered on Agentverse and discoverable by ASI:One.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure UTF-8 console encoding on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import requests
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from uagents.crypto import Identity

from config import Config

console = Console()


def check_agentverse_almanac(address: str, base_url: str = "https://agentverse.ai") -> dict | None:
    """Query the Agentverse Almanac API for agent registration details."""
    endpoint = f"{base_url}/v1/almanac/agents/{address}"
    try:
        resp = requests.get(endpoint, timeout=5)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 404:
            return None
        return {"status_code": resp.status_code, "text": resp.text}
    except Exception as exc:
        return {"error": str(exc)}


def main() -> None:
    console.print(
        Panel("[bold green]CareRoute Agentverse & ASI:One Discoverability Checker[/bold green]")
    )

    disp_addr = Identity.from_seed(Config.DISPATCHER_SEED, 0).address
    diag_addr = Identity.from_seed(Config.DIAGNOSTIC_SEED, 0).address
    logi_addr = Identity.from_seed(Config.LOGISTICS_SEED, 0).address
    escr_addr = Identity.from_seed(Config.ESCROW_SEED, 0).address

    table = Table(title="Agent Address Table")
    table.add_column("Agent", style="cyan", no_wrap=True)
    table.add_column("Address", style="green")
    table.add_column("Role", style="magenta")

    table.add_row("Dispatcher", disp_addr, "Public Gateway & ACP Host")
    table.add_row("Diagnostic", diag_addr, "Clinical VLM & SOAP Worker")
    table.add_row("Logistics", logi_addr, "OPD Slot Booking Worker")
    table.add_row("Escrow", escr_addr, "FET Anti-No-Show Escrow Worker")

    console.print(table)
    console.print()

    console.print(f"• [bold]USE_AGENTVERSE:[/bold] {Config.USE_AGENTVERSE}")
    console.print(
        f"• [bold]AGENT_ENDPOINT:[/bold] {Config.AGENT_ENDPOINT if Config.AGENT_ENDPOINT else 'Not set (using localhost:8000)'}"
    )
    console.print(f"• [bold]AGENTVERSE_URL:[/bold] {Config.AGENTVERSE_URL}")
    has_key = bool(Config.AGENTVERSE_API_KEY and Config.AGENTVERSE_API_KEY != "CHANGE_ME")
    console.print(
        f"• [bold]AGENTVERSE_API_KEY:[/bold] {'Configured (***)' if has_key else 'Missing or CHANGE_ME'}"
    )
    has_mb_key = bool(Config.AGENT_MAILBOX_KEY and Config.AGENT_MAILBOX_KEY != "CHANGE_ME")
    console.print(
        f"• [bold]AGENT_MAILBOX_KEY:[/bold] {'Configured (***)' if has_mb_key else 'Not set'}"
    )

    console.print("\n[bold]Checking Dispatcher Registration Status on Agentverse Almanac...[/bold]")
    almanac_data = check_agentverse_almanac(disp_addr, Config.AGENTVERSE_URL)

    if almanac_data and "error" not in almanac_data and "status_code" not in almanac_data:
        console.print(
            "[bold green]✅ Dispatcher is successfully registered on Agentverse Almanac![/bold green]"
        )
        console.print(f"Endpoints registered: {almanac_data.get('endpoints')}")
        console.print(f"Expiry: {almanac_data.get('expiry')}")
    elif almanac_data and "error" in almanac_data:
        console.print(
            f"[yellow]⚠️ Could not query Agentverse Almanac: {almanac_data['error']}[/yellow]"
        )
    else:
        if Config.USE_AGENTVERSE:
            console.print(
                "[yellow]⚠️ Agent not yet visible on Almanac. If you just started the agent, registration propagates within 30-60 seconds.[/yellow]"
            )
        else:
            console.print(
                "[cyan]ℹ️ Agent is currently in LOCAL ENDPOINT mode (USE_AGENTVERSE=false).[/cyan]"  # noqa: RUF001
            )
            console.print(
                "[dim]To enable Agentverse mailbox discovery for ASI:One, set USE_AGENTVERSE=true and add your AGENTVERSE_API_KEY in .env.[/dim]"
            )

    console.print("\n[bold]Helpful Links for Hackathon Submission:[/bold]")
    console.print(
        f"• [bold cyan]Agentverse Profile:[/bold cyan] https://agentverse.ai/agents/{disp_addr}"
    )
    console.print(
        f"• [bold cyan]Agent Inspector:[/bold cyan]     https://agentverse.ai/inspect/?address={disp_addr}"
    )
    console.print(
        f"• [bold cyan]ASI:One Direct Chat:[/bold cyan] https://asi1.ai/chat?agent={disp_addr}"
    )
    console.print()


if __name__ == "__main__":
    main()
