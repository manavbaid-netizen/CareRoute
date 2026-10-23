# CareRoute (केयररूट) — Rural Telehealth & Clinical Pre-Intake Bridge

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

**CareRoute** is an autonomous rural telehealth bridge built on Fetch.ai uAgents and discoverable directly within **ASI:One**. It connects underserved rural patients in India to their local Community Health Center (CHC) doctors.

Patients converse naturally in **Hindi, Hinglish, or English** (voice, text, or prescription photos). CareRoute screens for life-threatening emergencies, triages symptoms, synthesizes a concise English **SOAP Clinical Dossier** for the visiting doctor, reserves a verified OPD consultation slot, and manages an anti-no-show deposit of **0.5 FET** held in escrow and refunded upon QR check-in at the clinic desk.

---

## 🌟 Capabilities & Features
1. **Vernacular Hindi-First Intake**: Speaks native Hindi, Hinglish, and English with compassionate bedside manner.
2. **Clinical Safety Tripwires**: Detects 16+ acute red-flag life threats (cardiac chest pain, breathlessness, seizures, obstetric bleeding, snake bites) and halts intake to trigger immediate **108 Ambulance SOS**.
3. **Structured SOAP Dossier**: Translates patient symptoms into a professional English SOAP summary (Subjective, Objective, Assessment, Plan) with differential diagnoses and recommended investigations.
4. **OPD Scheduling**: Books real-time available time slots at the nearest Community Health Center (CHC Alwar).
5. **Anti-No-Show Escrow**: Locks 0.5 FET anti-no-show commitment deposit via Fetch.ai; automatically refunded 100% when the patient checks in at the clinic desk.
6. **Agent Chat Protocol (ACP)**: Native compatibility with ASI:One with interactive cards and text fallback.

---

## 💬 Sample Invocations & Prompts

### Hindi (हिन्दी)
- *"नमस्ते डॉक्टर साहब, मुझे दो हफ्ते से शाम को हल्का बुखार आ रहा है, खांसी है और वजन घट गया है।"*
- *"मेरे चेहरे और बांह पर लाल चकत्ते हैं और बहुत खुजली हो रही है।"*
- *"सीएचसी में कल ओपीडी के लिए कौन सा समय उपलब्ध है?"*

### Hinglish
- *"Mujhe 2 weeks se evening mein fever aur balgam wali cough hai, weight bhi kam hua hai."*
- *"Doctor se milne ke liye slot book karna hai Alwar CHC mein."*

### English
- *"I have had a productive cough with evening fever and night sweats for over two weeks."*
- *"I need to see a specialist at the community health center."*

### Emergency Red-Flag Trigger (Immediate 108 SOS)
- *"मरीज को अचानक सीने में बहुत तेज दर्द हो रहा है और सांस लेने में भारी तकलीफ है।"*
- *"Patient collapsed, having convulsions and blue lips."*

---

## 📋 Interaction Inputs & Outputs
- **Input Channels**: ASI:One text prompt, button click actions, uploaded prescription images or skin lesion photos.
- **Output Formats**:
  - Empathetic Hindi conversational guidance.
  - Interactive Triage Card with urgency badge and specialty recommendation.
  - Interactive OPD Slot Picker with date/time selections.
  - Booking Confirmation Slip with unique Ticket ID, clinic room number, and check-in QR code.
  - Instant 108 Emergency Alert with first-aid guidance.

---

## 🏥 Clinical Disclaimer
CareRoute provides automated clinical pre-intake and triage decision support. It does not provide medical diagnoses or replace physical clinical examinations. All diagnoses, prescriptions, and treatment plans are determined exclusively by licensed government medical officers at the Community Health Center.
