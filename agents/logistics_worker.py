from __future__ import annotations

import logging
from uagents import Agent, Context
from config import Config
from services.clinic_roster import ClinicRosterService
from services.dossier_generator import DossierGeneratorService
from models.chat_models import (
    SlotQueryRequest,
    SlotQueryResponse,
    BookingCommitRequest,
    BookingCommitResponse,
)

logger = logging.getLogger("CareRoute.LogisticsWorker")

# Initialize Logistics Worker Agent
logistics_worker = Agent(
    name="logistics_worker",
    seed=Config.LOGISTICS_SEED,
    port=Config.LOGISTICS_PORT,
    endpoint=Config.get_agent_endpoint(Config.LOGISTICS_PORT),
)

roster_service = ClinicRosterService()
dossier_service = DossierGeneratorService()


@logistics_worker.on_event("startup")
async def startup_handler(ctx: Context) -> None:
    ctx.logger.info(
        f"🏥 CareRoute Logistics & Roster Worker Agent is online! Address: {logistics_worker.address}"
    )


@logistics_worker.on_message(model=SlotQueryRequest)
async def handle_slot_query(
    ctx: Context, sender: str, msg: SlotQueryRequest
) -> None:
    """
    Handle appointment slot search request from Dispatcher.
    Matches the recommended clinical specialty to available CHC doctors and OPD timings.
    """
    ctx.logger.info(
        f"📅 Querying available slots for specialty: '{msg.specialty}' (Session: {msg.session_id})"
    )
    result = roster_service.get_available_slots(msg.specialty)

    response = SlotQueryResponse(
        session_id=msg.session_id,
        clinic_name=result["clinic_name"],
        doctor_name=result["doctor_name"],
        specialty=result["specialty"],
        room_no=result["room_no"],
        slots=result["slots"],
    )
    ctx.logger.info(
        f"✅ Found doctor: {result['doctor_name']} ({result['room_no']}) with {len(result['slots'])} slots."
    )
    await ctx.send(sender, response)


@logistics_worker.on_message(model=BookingCommitRequest)
async def handle_booking_commit(
    ctx: Context, sender: str, msg: BookingCommitRequest
) -> None:
    """
    Handle confirmed appointment booking and register patient in CHC roster.
    Triggers generation of the Doctor's 3-minute OPD Clinical Dossier.
    """
    ctx.logger.info(
        f"📝 Committing OPD booking for patient {msg.patient_name} (Slot: {msg.slot_id})"
    )

    booking = roster_service.book_appointment(
        slot_id=msg.slot_id,
        patient_id=msg.patient_id,
        patient_name=msg.patient_name,
        dossier_id=msg.dossier_id,
    )

    # Persist and render Doctor's Clinical Dossier for the assigned ticket
    dossier = dossier_service.load_dossier(msg.dossier_id)
    dossier_path = None
    if dossier:
        saved_paths = dossier_service.save_dossier(dossier, ticket_id=booking["ticket_id"])
        dossier_path = saved_paths["md_path"]
        roster_service.update_dossier_path(booking["ticket_id"], dossier_path)
        ctx.logger.info(
            f"📄 Doctor's Clinical Intake Dossier generated at: {dossier_path}"
        )
    else:
        ctx.logger.error(
            f"❌ Failed to locate clinical dossier '{msg.dossier_id}' for booking ticket {booking['ticket_id']}!"
        )

    response = BookingCommitResponse(
        session_id=msg.session_id,
        ticket_id=booking["ticket_id"],
        patient_name=msg.patient_name,
        doctor_name=booking["doctor_name"],
        clinic_name=booking["clinic_name"],
        room_no=booking["room_no"],
        slot_time=booking["slot_time"],
        qr_payload=booking["qr_payload"],
        status="CONFIRMED" if dossier else "ERROR_MISSING_DOSSIER",
        dossier_path=dossier_path,
    )
    ctx.logger.info(f"🎉 Appointment successfully confirmed! Ticket: {booking['ticket_id']}")
    await ctx.send(sender, response)


if __name__ == "__main__":
    logistics_worker.run()
