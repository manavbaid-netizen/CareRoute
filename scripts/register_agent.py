#!/usr/bin/env python3
"""
CareRoute Direct Agentverse Registration Script.
Directly registers the Dispatcher agent on Agentverse using AGENTVERSE_API_KEY,
completely bypassing the browser Local Agent Inspector and private network CORS issues.
"""

from __future__ import annotations

import asyncio
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

from rich.console import Console
from rich.panel import Panel
from uagents.agent import register_in_agentverse
from uagents.mailbox import AgentverseConnectRequest
from uagents_core.registration import RegistrationRequest

from agents.dispatcher import dispatcher
from config import Config

console = Console()


async def main() -> None:
    console.print(
        Panel(
            "[bold cyan]CareRoute Direct Agentverse Registration Tool[/bold cyan]\n"
            "Directly establishes Mailbox & Almanac registration on Agentverse via API."
        )
    )

    if not Config.AGENTVERSE_API_KEY or Config.AGENTVERSE_API_KEY == "CHANGE_ME":
        console.print(
            "[bold red]❌ Error: AGENTVERSE_API_KEY is not configured in .env![/bold red]"
        )
        console.print("Please add your Agentverse API Key to your .env file.")
        return

    console.print(f"• [bold]Agent Name:[/bold] {dispatcher.name}")
    console.print(f"• [bold]Agent Address:[/bold] {dispatcher.address}")
    console.print(f"• [bold]Agentverse URL:[/bold] {dispatcher.agentverse.url}")
    console.print(
        f"• [bold]Mailbox Endpoint:[/bold] {dispatcher.agentverse.mailbox_endpoint}"
    )

    request = AgentverseConnectRequest(
        user_token=Config.AGENTVERSE_API_KEY,
        agent_type="mailbox",
        endpoint=dispatcher.agentverse.mailbox_endpoint,
    )

    profile = dispatcher._build_registration_profile()
    registration_data = RegistrationRequest(
        address=dispatcher.address,
        name=dispatcher.name,
        handle=dispatcher._handle,
        url=dispatcher.agentverse.mailbox_endpoint,
        profile=profile,
        endpoints=dispatcher._endpoints,
        protocols=list(dispatcher.protocols.keys()),
        metadata=dispatcher.metadata,
    )

    console.print(
        "\n[bold yellow]Submitting cryptographic proof to Agentverse...[/bold yellow]"
    )
    try:
        response = await register_in_agentverse(
            request=request,
            identity=dispatcher._identity,
            prefix=dispatcher._prefix,
            agentverse=dispatcher._agentverse,
            agent_details=registration_data,
        )

        if response.success:
            console.print(
                "\n[bold green]🎉 SUCCESS! Agent is now registered on Agentverse Mailbox![/bold green]"
            )
            console.print(
                "Your agent is now linked to your Agentverse account and discoverable on ASI:One."
            )
            console.print(
                f"\n• [bold cyan]Agentverse Profile:[/bold cyan] https://agentverse.ai/agents/{dispatcher.address}"
            )
            console.print(
                f"• [bold cyan]ASI:One Direct Chat:[/bold cyan] https://asi1.ai/chat?agent={dispatcher.address}"
            )
            console.print("\nYou can now start the 4-agent swarm:")
            console.print("[bold green]python run_all.py[/bold green]")
        else:
            console.print(
                f"\n[bold red]❌ Registration failed:[/bold red] {response.detail}"
            )
    except Exception as exc:
        console.print(
            f"\n[bold red]❌ Unexpected error during registration:[/bold red] {exc}"
        )


if __name__ == "__main__":
    asyncio.run(main())
