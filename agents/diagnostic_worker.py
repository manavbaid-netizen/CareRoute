from __future__ import annotations

import logging

from uagents import Agent, Context

from config import Config
from models.chat_models import TriageAnalysisRequest, TriageAnalysisResponse
from services.dossier_generator import DossierGeneratorService
from services.vlm_service import VLMService

logger = logging.getLogger("CareRoute.DiagnosticWorker")

# Initialize the Diagnostic Worker Agent
diagnostic_worker = Agent(
    name="diagnostic_worker",
    seed=Config.DIAGNOSTIC_SEED,
    port=Config.DIAGNOSTIC_PORT,
    endpoint=Config.get_agent_endpoint(Config.DIAGNOSTIC_PORT),
)

vlm_service = VLMService()
dossier_service = DossierGeneratorService()


@diagnostic_worker.on_event("startup")
async def startup_handler(ctx: Context) -> None:
    ctx.logger.info(
        f"🔬 CareRoute Diagnostic Worker Agent is online! Address: {diagnostic_worker.address}"
    )


@diagnostic_worker.on_message(model=TriageAnalysisRequest)
async def handle_triage_request(ctx: Context, sender: str, msg: TriageAnalysisRequest) -> None:
    """
    Handle triage and clinical synthesis request from DispatcherAgent.
    Runs VLM multimodal triage, generates Hindi guidance, and formats the English SOAP dossier.
    """
    ctx.logger.info(
        f"📋 Received clinical triage request for session {msg.session_id} (Patient: {msg.patient_name})"
    )
    ctx.logger.debug(f'🗣️ Raw Vernacular Transcript: "{msg.text_transcript[:60]}..."')

    # Execute Clinical Reasoning & SOAP Generation via VLM Service
    dossier, hindi_summary, is_emergency, emergency_reasons = vlm_service.analyze_case(
        session_id=msg.session_id,
        patient_id=msg.patient_id,
        patient_name=msg.patient_name,
        text_transcript=msg.text_transcript,
        image_data=msg.image_data,
        image_type=msg.image_type,
    )

    # Save the dossier immediately after triage synthesis so it exists for logistics worker
    saved_paths = dossier_service.save_dossier(dossier)
    ctx.logger.info(f"💾 Dossier saved: ID={dossier.dossier_id} at {saved_paths['json_path']}")

    if is_emergency:
        ctx.logger.warning(
            f"🚨 EMERGENCY RED FLAG TRIGGERED for session {msg.session_id}: {emergency_reasons}"
        )
    else:
        ctx.logger.info(
            f"✅ Clinical SOAP generated: Urgency={dossier.assessment.triage_urgency.value}, "
            f"Specialty={dossier.assessment.recommended_specialty}"
        )

    # Return response back to Dispatcher
    response = TriageAnalysisResponse(
        session_id=msg.session_id,
        patient_id=msg.patient_id,
        dossier=dossier,
        hindi_summary=hindi_summary,
        is_emergency=is_emergency,
        emergency_reasons=emergency_reasons,
        correlation_id=getattr(msg, "correlation_id", ""),
    )
    await ctx.send(sender, response)


if __name__ == "__main__":
    diagnostic_worker.run()
