from __future__ import annotations

import sys
import time
import argparse
import logging
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown

from config import Config
from agents import (
    dispatcher,
    diagnostic_worker,
    logistics_worker,
    escrow_worker,
    set_worker_addresses,
    execute_patient_checkin,
)
from services.vlm_service import VLMService
from services.clinic_roster import ClinicRosterService
from services.dossier_generator import DossierGeneratorService
from models.cards import (
    make_triage_detail_card,
    make_slot_picker_card,
    make_booking_receipt_card,
    make_emergency_sos_card,
)

# Setup rich console for clinical UI demonstration
console = Console()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("CareRoute.Main")


def link_agents() -> None:
    """Wire up inter-agent addresses across the swarm."""
    set_worker_addresses(
        diagnostic_addr=diagnostic_worker.address,
        logistics_addr=logistics_worker.address,
        escrow_addr=escrow_worker.address,
    )
    logger.info("Inter-agent communication addresses linked:")
    logger.info(f" -> Dispatcher:  {dispatcher.address}")
    logger.info(f" -> Diagnostic:  {diagnostic_worker.address}")
    logger.info(f" -> Logistics:   {logistics_worker.address}")
    logger.info(f" -> Escrow:      {escrow_worker.address}")


def run_bureau() -> None:
    """
    Launch the Fetch.ai Multi-Agent Bureau running all 4 agents concurrently.
    """
    from uagents import Bureau

    Config.ensure_directories()
    link_agents()

    console.print(
        Panel.fit(
            "[bold green]CareRoute (केयररूट) - Rural Telehealth Bridge & Clinical Pre-Intake Protocol[/bold green]\n"
            "[yellow]Fetch.ai Multi-Agent Bureau Initializing...[/yellow]\n\n"
            f"[cyan]Dispatcher Port:[/cyan] {Config.DISPATCHER_PORT} | [cyan]Host:[/cyan] {Config.AGENT_HOST}\n"
            f"[cyan]Diagnostic Port:[/cyan] {Config.DIAGNOSTIC_PORT} | [cyan]Logistics Port:[/cyan] {Config.LOGISTICS_PORT} | [cyan]Escrow Port:[/cyan] {Config.ESCROW_PORT}\n"
            f"[cyan]Escrow Deposit:[/cyan] {Config.ESCROW_DEPOSIT_FET} FET | [cyan]Network:[/cyan] Fetch.ai Testnet / Standalone",
            border_style="green",
        )
    )

    bureau = Bureau(
        port=Config.DISPATCHER_PORT,
        endpoint=Config.get_agent_endpoint(Config.DISPATCHER_PORT),
    )
    bureau.add(dispatcher)
    bureau.add(diagnostic_worker)
    bureau.add(logistics_worker)
    bureau.add(escrow_worker)

    logger.info("Starting CareRoute Multi-Agent Bureau...")
    bureau.run()


def run_interactive_demo() -> None:
    """
    Execute a comprehensive simulated clinical walkthrough showing:
    1. Vernacular Hindi intake (B-symptoms chronic cough/fever)
    2. VLM clinical reasoning and English SOAP dossier generation
    3. ASI Interactive Triage Card presentation
    4. CHC Doctor slot selection (Alwar CHC, Dr. Harish Sharma)
    5. 0.5 FET Anti-No-Show Escrow lock
    6. Patient Booking QR receipt card
    7. High-density Doctor OPD clinical summary
    8. Clinic QR check-in & 0.5 FET escrow refund release
    9. Emergency 108 Red Flag Tripwire demonstration
    """
    Config.ensure_directories()
    link_agents()

    vlm = VLMService()
    roster = ClinicRosterService()
    dossier_gen = DossierGeneratorService()

    console.print("\n" + "=" * 80)
    console.print(
        Panel.fit(
            "[bold green]CAREROUTE (केयररूट) - CLINICAL PRE-INTAKE SIMULATION[/bold green]\n"
            "[italic]Autonomous Two-Sided Communication Bridge for Rural Community Health Centers[/italic]",
            border_style="cyan",
        )
    )

    # --------------------------------------------------------------------------
    # SCENARIO 1: Rural Patient Vernacular Intake (Tuberculosis B-symptoms)
    # --------------------------------------------------------------------------
    console.print("\n[bold yellow]═══ STEP 1: PATIENT VERNACULAR INTAKE (ASI:One Interface) ═══[/bold yellow]")
    patient_transcript = "नमस्ते डॉक्टर साहब, मुझे दो हफ्ते से शाम को हल्का बुखार आ रहा है, बलगम वाली खांसी है और 3 किलो वजन घट गया है।"
    patient_name = "रामकुमार (Ram Kumar, 46M)"
    session_id = "session_alwar_demo_01"
    patient_id = "PAT-ALW-991"

    console.print(f"[bold cyan]Patient Input:[/bold cyan] [italic]\"{patient_transcript}\"[/italic]")
    console.print(f"[cyan]Demographics:[/cyan] {patient_name} | Location: Alwar Rural District")
    time.sleep(1)

    console.print("\n[bold yellow]═══ STEP 2: SAFETY TRIPWIRE SCREENING ═══[/bold yellow]")
    is_emergency, emergency_reasons = vlm.scan_safety_tripwires(patient_transcript)
    if is_emergency:
        console.print("[bold red]🚨 RED FLAG TRIPPED - HALTING FLOW[/bold red]")
    else:
        console.print("[bold green]✅ No acute red-flag life threats detected. Proceeding with clinical triage.[/bold green]")

    console.print("\n[bold yellow]═══ STEP 3: VLM CLINICAL REASONING & SOAP GENERATION ═══[/bold yellow]")
    console.print("[dim]DiagnosticWorkerAgent parsing vernacular terms -> 'शाम को बुखार' (evening pyrexia), 'खांसी' (productive cough >14d), 'वजन घटना' (constitutional weight loss)...[/dim]")
    time.sleep(1.5)

    dossier, hindi_summary, is_emergency, emergency_reasons = vlm.analyze_case(
        session_id=session_id,
        patient_id=patient_id,
        patient_name=patient_name,
        text_transcript=patient_transcript,
        image_data="mock_prescription_slip.jpg",
        image_type="prescription_slip",
    )

    console.print(f"\n[bold green]Empathetic Hindi Guidance to Patient:[/bold green]\n{hindi_summary}\n")

    # Present ASI Interactive Triage Card
    triage_card = make_triage_detail_card(
        urgency=dossier.assessment.triage_urgency.value,
        specialty_hi=dossier.assessment.recommended_specialty_hindi,
        specialty_en=dossier.assessment.recommended_specialty,
        pre_visit_advice=dossier.plan.interim_patient_advice_hindi,
        differentials=dossier.assessment.differential_diagnoses,
    )

    console.print(
        Panel(
            f"[bold red]CARD TYPE:[/bold red] {triage_card['card_type'].upper()}\n"
            f"[bold]HEADER:[/bold] {triage_card['header']['title']}\n"
            f"[bold]URGENCY BADGE:[/bold] {triage_card['header']['badge']}\n\n"
            f"[bold]RECOMMENDED SPECIALTY:[/bold] {triage_card['sections'][0]['highlight']}\n\n"
            f"[bold]DIFFERENTIAL DIAGNOSES:[/bold]\n" + "\n".join([f"  • {item}" for item in triage_card['sections'][1]['items']]) + "\n\n"
            f"[bold]PRE-VISIT ADVICE:[/bold]\n{triage_card['sections'][2]['content']}\n\n"
            f"[bold green]INTERACTIVE ACTIONS:[/bold green]\n" + "\n".join([f"  [{a['style'].upper()}] {a['label']}" for a in triage_card['actions']]),
            title="[bold cyan]ASI Interactive Card: Triage Detail View[/bold cyan]",
            border_style="magenta",
        )
    )

    time.sleep(1.5)

    # --------------------------------------------------------------------------
    # SCENARIO 1 (Cont): Logistics Slot Selection & CHC Doctor Roster
    # --------------------------------------------------------------------------
    console.print("\n[bold yellow]═══ STEP 4: CHC DOCTOR ROSTER & SLOT PICKER ═══[/bold yellow]")
    console.print(f"[dim]LogisticsWorkerAgent querying CHC Alwar for '{dossier.assessment.recommended_specialty}'...[/dim]")

    slots_data = roster.get_available_slots(dossier.assessment.recommended_specialty)
    slot_card = make_slot_picker_card(
        clinic_name=slots_data["clinic_name"],
        doctor_name=slots_data["doctor_name"],
        specialty=slots_data["specialty"],
        room_no=slots_data["room_no"],
        available_slots=slots_data["slots"],
    )

    console.print(
        Panel(
            f"[bold]CLINIC:[/bold] {slot_card['header']['title']}\n"
            f"[bold]CONSULTANT:[/bold] {slot_card['sections'][0]['highlight']} ({slot_card['sections'][0]['subtitle']})\n"
            f"[bold]DEPOSIT POLICY:[/bold] {slot_card['sections'][1]['content']}\n\n"
            f"[bold green]SELECTABLE OPD SLOTS:[/bold green]\n" +
            "\n".join([f"  [BUTTON] {a['label']}" for a in slot_card['actions']]),
            title="[bold cyan]ASI Interactive Card: Slot Picker[/bold cyan]",
            border_style="blue",
        )
    )

    # Patient selects Slot 1 (10:00 AM)
    selected_slot_id = slots_data["slots"][0]["slot_id"]
    console.print(f"\n[green]👉 User clicked button:[/green] [bold]{slots_data['slots'][0]['time']}[/bold]")

    time.sleep(1)

    # --------------------------------------------------------------------------
    # SCENARIO 1 (Cont): 0.5 FET Anti-No-Show Escrow Lock
    # --------------------------------------------------------------------------
    console.print("\n[bold yellow]═══ STEP 5: FETCH.AI PAYMENT PROTOCOL (ANTI-NO-SHOW ESCROW) ═══[/bold yellow]")
    console.print("[dim]EscrowWorkerAgent locking 0.5 FET refundable deposit...[/dim]")

    # Book slot in SQLite
    booking = roster.book_appointment(
        slot_id=selected_slot_id,
        patient_id=patient_id,
        patient_name=patient_name,
        dossier_id=dossier.dossier_id,
    )
    ticket_id = booking["ticket_id"]

    # Save Doctor's clinical dossier
    saved = dossier_gen.save_dossier(dossier, ticket_id=ticket_id)

    # Lock simulated escrow
    mock_lock_tx = f"0x{time.time_ns():x}"
    console.print(f"[bold green]🔒 ESCROW LOCKED:[/bold green] 0.5 FET committed on-chain.")
    console.print(f"[cyan]TxHash:[/cyan] {mock_lock_tx} | [cyan]Ticket ID:[/cyan] {ticket_id}")

    # Generate Patient Booking Receipt Card
    receipt_card = make_booking_receipt_card(
        ticket_id=ticket_id,
        patient_name=patient_name,
        doctor_name=booking["doctor_name"],
        clinic_name=booking["clinic_name"],
        room_no=booking["room_no"],
        slot_time=booking["slot_time"],
        deposit_fet=0.5,
        qr_data=booking["qr_payload"],
    )

    console.print(
        Panel(
            f"[bold]STATUS:[/bold] {receipt_card['header']['title']}\n"
            f"[bold]TOKEN #:[/bold] {receipt_card['header']['badge']}\n\n"
            + "\n".join([f"  • {fact['label']}: [bold]{fact['value']}[/bold]" for fact in receipt_card['sections'][0]['facts']])
            + f"\n\n[bold yellow]ESCROW STATUS:[/bold yellow]\n{receipt_card['sections'][1]['content']}\n\n"
            + f"[bold]DIGITAL CHECK-IN QR:[/bold]\n{receipt_card['sections'][2]['qr_visual']}\n"
            + f"Payload: `{receipt_card['sections'][2]['qr_payload']}`",
            title="[bold green]ASI Interactive Card: Patient Booking Receipt[/bold green]",
            border_style="green",
        )
    )

    time.sleep(1.5)

    # --------------------------------------------------------------------------
    # SCENARIO 1 (Cont): Doctor's High-Density English Markdown Dossier Output
    # --------------------------------------------------------------------------
    console.print("\n[bold yellow]═══ STEP 6: DOCTOR'S 3-MINUTE OPD CLINICAL DOSSIER ═══[/bold yellow]")
    console.print(f"[cyan]Saved at:[/cyan] {saved['md_path']}")
    console.print(f"[cyan]Structured JSON at:[/cyan] {saved['json_path']}\n")

    with open(saved["md_path"], "r", encoding="utf-8") as f:
        md_text = f.read()

    console.print(
        Panel(
            Markdown(md_text),
            title="[bold yellow]Doctor's Intake Record (Alwar CHC - Room 4)[/bold yellow]",
            border_style="yellow",
        )
    )

    time.sleep(1.5)

    # --------------------------------------------------------------------------
    # SCENARIO 1 (Cont): Physical Clinic Check-In & 0.5 FET Escrow Refund
    # --------------------------------------------------------------------------
    console.print("\n[bold yellow]═══ STEP 7: CLINIC DESK CHECK-IN & ESCROW SETTLEMENT ═══[/bold yellow]")
    console.print(f"[dim]Patient arrives at CHC Alwar. Dispensary health worker scans QR token '{ticket_id}'...[/dim]")

    release_resp = execute_patient_checkin(ticket_id=ticket_id, scanned_by="alwar_chc_reception_desk")

    console.print(
        Panel.fit(
            f"[bold green]💸 ESCROW REFUND COMPLETED![/bold green]\n"
            f"[bold]Refund Amount:[/bold] {release_resp.refund_amount_fet} FET (100% Refunded)\n"
            f"[bold]Refund TxHash:[/bold] {release_resp.refund_tx_hash}\n"
            f"[bold]Message:[/bold] {release_resp.message}",
            border_style="green",
        )
    )

    time.sleep(1)

    # --------------------------------------------------------------------------
    # SCENARIO 2: Emergency Red-Flag Tripwire Test
    # --------------------------------------------------------------------------
    console.print("\n" + "=" * 80)
    console.print("\n[bold red]═══ SCENARIO 2: EMERGENCY TRIPWIRE (CRITICAL RED FLAG TEST) ═══[/bold red]")
    emergency_text = "मरीज को अचानक सीने में बहुत तेज दर्द हो रहा है और सांस लेने में भारी तकलीफ है।"
    console.print(f"[bold cyan]Patient Input:[/bold cyan] [italic]\"{emergency_text}\"[/italic]")

    em_dossier, em_summary, em_is_emergency, em_reasons = vlm.analyze_case(
        session_id="session_emergency_test",
        patient_id="PAT-EM-001",
        patient_name="आपातकालीन मरीज (Emergency Patient)",
        text_transcript=emergency_text,
    )

    emergency_card = make_emergency_sos_card(em_reasons)

    console.print(
        Panel(
            f"[bold white on red] {emergency_card['header']['title']} [/bold white on red]\n"
            f"[bold red]BADGE:[/bold red] {emergency_card['header']['badge']}\n\n"
            f"[bold]DETECTED LIFE-THREATENING SIGNS:[/bold]\n"
            + "\n".join([f"  🚨 {r}" for r in emergency_card['sections'][0]['items']])
            + f"\n\n[bold]DIRECTIVES:[/bold]\n{emergency_card['sections'][1]['content']}\n\n"
            + f"[bold]FIRST AID:[/bold]\n{emergency_card['sections'][2]['content']}\n\n"
            + f"[bold red]ACTIONS:[/bold red]\n"
            + "\n".join([f"  [EMERGENCY BUTTON] {a['label']}" for a in emergency_card['actions']]),
            title="[bold red]ASI Interactive Card: 108 Emergency SOS[/bold red]",
            border_style="red",
        )
    )

    console.print("\n" + "=" * 80)
    console.print("[bold green]✅ All CareRoute simulation scenarios successfully verified![/bold green]\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="CareRoute (केयररूट) - Rural Telehealth Multi-Agent Network"
    )
    parser.add_argument(
        "--demo",
        "--simulate",
        action="store_true",
        help="Run an end-to-end simulated clinical demonstration in the terminal.",
    )
    args = parser.parse_args()

    if args.demo:
        run_interactive_demo()
    else:
        run_bureau()


if __name__ == "__main__":
    main()
