"""Automated unit and integration test suite for CareRoute multi-agent codebase."""

import unittest

from agents.escrow_worker import execute_patient_checkin
from config import Config
from models.cards import (
    make_booking_receipt_card,
    make_emergency_sos_card,
    make_slot_picker_card,
    make_triage_detail_card,
)
from models.clinical_schemas import TriageUrgency
from services.clinic_roster import ClinicRosterService
from services.dossier_generator import DossierGeneratorService
from services.vlm_service import VLMService


class TestCareRouteClinicalSystem(unittest.TestCase):
    def setUp(self):
        Config.ensure_directories()
        self.vlm = VLMService()
        self.roster = ClinicRosterService()
        self.roster.reset_slot("ALW_CHEST_1000")
        self.dossier_gen = DossierGeneratorService()

    def test_emergency_tripwire_detection(self):
        text = "मरीज को अचानक सीने में बहुत तेज दर्द और दम घुट रहा है"
        is_em, reasons = self.vlm.scan_safety_tripwires(text)
        self.assertTrue(is_em)
        self.assertGreaterEqual(len(reasons), 1)

        dossier, summary, is_em2, reasons2 = self.vlm.analyze_case(
            session_id="test_em",
            patient_id="PAT_TEST",
            patient_name="Test Patient",
            text_transcript=text,
        )
        self.assertTrue(is_em2)
        self.assertEqual(dossier.assessment.triage_urgency, TriageUrgency.EMERGENCY)

    def test_respiratory_tb_triage(self):
        text = "दो हफ्ते से शाम को बुखार, खांसी और वजन घट रहा है"
        dossier, summary, is_em, reasons = self.vlm.analyze_case(
            session_id="test_tb",
            patient_id="PAT_TB",
            patient_name="Ram Kumar",
            text_transcript=text,
            image_type="prescription_slip",
        )
        self.assertFalse(is_em)
        self.assertIn("Pulmonology", dossier.assessment.recommended_specialty)
        self.assertGreaterEqual(len(dossier.assessment.differential_diagnoses), 1)
        self.assertGreaterEqual(len(dossier.plan.suggested_investigations), 1)

    def test_dermatology_triage(self):
        text = "हाथ पर गोल चकत्ते हैं और बहुत तेज खुजली हो रही है"
        dossier, summary, is_em, reasons = self.vlm.analyze_case(
            session_id="test_derm",
            patient_id="PAT_DERM",
            patient_name="Shanti Devi",
            text_transcript=text,
            image_type="lesion_photo",
        )
        self.assertFalse(is_em)
        self.assertIn("Dermatology", dossier.assessment.recommended_specialty)

    def test_cards_generation(self):
        t_card = make_triage_detail_card(
            urgency="High",
            specialty_hi="छाती रोग विशेषज्ञ",
            specialty_en="Pulmonology",
            pre_visit_advice="आराम करें",
            differentials=["TB"],
        )
        self.assertEqual(t_card["card_type"], "triage_detail")
        self.assertIn("actions", t_card)

        s_card = make_slot_picker_card(
            clinic_name="Alwar CHC",
            doctor_name="Dr. Sharma",
            specialty="Chest",
            room_no="Room 4",
            available_slots=[{"slot_id": "S1", "time": "10:00 AM", "capacity": 3}],
        )
        self.assertEqual(s_card["card_type"], "slot_picker")

        b_card = make_booking_receipt_card(
            ticket_id="CR-ALW-001",
            patient_name="Ram",
            doctor_name="Dr. Sharma",
            clinic_name="Alwar CHC",
            room_no="Room 4",
            slot_time="10:00 AM",
        )
        self.assertEqual(b_card["card_type"], "booking_receipt")

        e_card = make_emergency_sos_card(["Severe chest pain"])
        self.assertEqual(e_card["card_type"], "emergency_sos")

    def test_booking_and_escrow_lifecycle(self):
        # 1. Book appointment
        booking = self.roster.book_appointment(
            slot_id="ALW_CHEST_1000",
            patient_id="PAT_LIFECYCLE",
            patient_name="Test User",
            dossier_id="DOS_001",
        )
        ticket_id = booking["ticket_id"]
        self.assertTrue(ticket_id.startswith("CR-ALW-"))

        # 2. Check record in DB
        record = self.roster.get_booking(ticket_id)
        self.assertIsNotNone(record)
        self.assertEqual(record["booking_status"], "CONFIRMED")
        self.assertEqual(record["escrow_status"], "LOCKED")

        # 3. Simulate desk QR check-in & refund
        refund_resp = execute_patient_checkin(ticket_id, scanned_by="desk_test")
        self.assertEqual(refund_resp.status, "REFUNDED")
        self.assertEqual(refund_resp.refund_amount_fet, 0.5)

        # 4. Verify updated status
        updated_record = self.roster.get_booking(ticket_id)
        self.assertEqual(updated_record["booking_status"], "CHECKED_IN")
        self.assertEqual(updated_record["escrow_status"], "REFUNDED")


if __name__ == "__main__":
    unittest.main()
