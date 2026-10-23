#!/usr/bin/env python3
"""
CareRoute Multi-Process Agent Runner.
Starts all 4 Fetch.ai agents as independent processes without port overriding:
 - Dispatcher (Master ACP Gateway)
 - Diagnostic Worker (Clinical Triage & SOAP)
 - Logistics Worker (OPD Slot Scheduling)
 - Escrow Worker (Anti-No-Show Escrow & QR Check-in)
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from uagents.crypto import Identity

from config import Config

console = Console()
ROOT_DIR = Path(__file__).resolve().parent


def print_banner() -> None:
    disp_addr = Identity.from_seed(Config.DISPATCHER_SEED, 0).address
    diag_addr = Identity.from_seed(Config.DIAGNOSTIC_SEED, 0).address
    logi_addr = Identity.from_seed(Config.LOGISTICS_SEED, 0).address
    escr_addr = Identity.from_seed(Config.ESCROW_SEED, 0).address

    mode_text = (
        f"[bold magenta]AGENTVERSE MAILBOX ACTIVE[/bold magenta] ({Config.AGENTVERSE_URL})"
        if Config.USE_AGENTVERSE
        else f"[bold cyan]LOCAL ENDPOINT MODE[/bold cyan] ({Config.AGENT_HOST})"
    )

    content = (
        f"[bold green]CareRoute (केयररूट) - Rural Telehealth Swarm[/bold green]\n"
        f"Mode: {mode_text}\n\n"
        f"[bold]Active Agents & Addresses:[/bold]\n"
        f" • [cyan]Dispatcher (Port {Config.DISPATCHER_PORT}):[/cyan] {disp_addr}\n"
        f" • [cyan]Diagnostic (Port {Config.DIAGNOSTIC_PORT}):[/cyan] {diag_addr}\n"
        f" • [cyan]Logistics  (Port {Config.LOGISTICS_PORT}):[/cyan] {logi_addr}\n"
        f" • [cyan]Escrow     (Port {Config.ESCROW_PORT}):[/cyan] {escr_addr}\n\n"
        f"[dim]Press Ctrl+C to terminate all agents cleanly.[/dim]"
    )
    console.print(Panel(content, title="🚀 CareRoute Multi-Agent Network", border_style="green"))


def main() -> None:
    Config.ensure_directories()
    print_banner()

    python_executable = sys.executable
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    agent_modules = [
        ("DiagnosticWorker", [python_executable, "-m", "agents.diagnostic_worker"]),
        ("LogisticsWorker", [python_executable, "-m", "agents.logistics_worker"]),
        ("EscrowWorker", [python_executable, "-m", "agents.escrow_worker"]),
        ("Dispatcher", [python_executable, "-m", "agents.dispatcher"]),
    ]

    processes = []

    try:
        for name, cmd in agent_modules:
            console.print(f"[bold blue]Starting {name}...[/bold blue]")
            p = subprocess.Popen(
                cmd,
                cwd=str(ROOT_DIR),
                env=env,
            )
            processes.append((name, p))
            time.sleep(0.5)

        console.print("\n[bold green]✅ All 4 CareRoute agents running concurrently![/bold green]\n")

        # Keep parent process alive to monitor children
        while True:
            time.sleep(1)
            for name, p in processes:
                ret = p.poll()
                if ret is not None:
                    console.print(f"[bold red]Agent {name} exited unexpectedly with code {ret}![/bold red]")
                    return

    except KeyboardInterrupt:
        console.print("\n[bold yellow]Stopping CareRoute agents...[/bold yellow]")
    finally:
        for _name, p in processes:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    p.kill()
        console.print("[bold green]All agents terminated cleanly.[/bold green]")


if __name__ == "__main__":
    main()
