# CareRoute (केयररूट) - Demo Video Script (3-5 Minutes)

**Target Duration:** 4 minutes 15 seconds  
**Format:** Split Screen (Left: ASI:One Mobile/Web Chat Interface; Right: Agentverse / CLI Logs / Clinic Dashboard)  
**Audio:** Bilingual (Hindi patient voiceover with English narrator explanations)

---

## Scene 1: The Rural Healthcare Challenge & Introduction (0:00 - 0:45)

**Visual:**
- Title slide: *CareRoute (केयररूट) - Hindi-First Rural Telehealth Bridge powered by Fetch.ai uAgents & ASI:One*.
- Map graphic showing rural Rajasthan (e.g., Alwar district) with Community Health Centers (CHCs) 25km away from remote villages.
- Text overlay: *Problem: 70% of rural Indian patients speak vernacular languages; CHC doctors are overwhelmed by unstructured queues; 35% no-show rates waste specialist hours.*

**Narrator (Voiceover - English):**
> "Welcome to CareRoute. In rural India, visiting a Community Health Center often means travelling dozens of kilometres without knowing if a specialist is available. Language barriers between patients speaking regional dialects and busy doctors create diagnostic bottlenecks, while high appointment no-show rates waste scarce specialist capacity.
>
> CareRoute solves this by deploying a decentralized multi-agent network natively integrated with ASI:One and the Fetch.ai Agent Chat Protocol (ACP). Patients chat naturally in Hindi or Hinglish, while CareRoute triages symptoms, generates evidence-backed English SOAP dossiers for doctors, books verified OPD slots, and eliminates no-shows using refundable 0.5 FET anti-no-show escrow."

---

## Scene 2: System Architecture & Agentverse Registration (0:45 - 1:15)

**Visual:**
- Display Agentverse Explorer showing `CareRoute Dispatcher` live and discoverable.
- Quick display of the Agent communication diagram:
  - User in ASI:One -> ACP Chat Protocol (`chat_protocol_spec`) -> Dispatcher Agent
  - Dispatcher -> Diagnostic Worker (ASI1 LLM / Gemini Vision) -> Clinical Dossier (SOAP)
  - Dispatcher -> Logistics Worker (SQLite Atomic Capacity & OpenStreetMap CHC Locator)
  - Dispatcher -> Escrow Worker (Fetch.ai Payment Protocol / 0.5 FET Lock & Refund)

**Narrator (Voiceover - English):**
> "CareRoute is built on pure Fetch.ai architecture. Our Dispatcher agent is registered on Agentverse with an active mailbox, implementing the official Agent Chat Protocol with standard ChatMessage, ChatAcknowledgement, and interactive MetadataContent cards.
>
> Behind the dispatcher, a bureau of specialized uAgents handles diagnostics, roster logistics, and escrow finance via internal protocol messages, completely decoupled from frontend vendor lock-in."

---

## Scene 3: Vernacular Patient Intake & ASI1 LLM Triage (1:15 - 2:15)

**Visual:**
- ASI:One chat interface opens.
- The patient receives the welcoming bilingual greeting:
  *नमस्ते! मैं CareRoute स्वास्थ्य सहायक हूँ। (Welcome! I am CareRoute health assistant. Please describe your symptoms or share a photo.)*
- Patient types in Hindi:
  `"मुझे पिछले 3 हफ्तों से लगातार खांसी आ रही है और शाम को हल्का बुखार रहता है। भूख भी कम लग रही है।"`
- Terminal shows: Dispatcher immediately fires `ChatAcknowledgement` (ACP protocol compliance), then delegates triage payload to `DiagnosticWorker`.
- Diagnostic Worker invokes the ASI1 LLM engine.
- Within 2 seconds, ASI:One renders:
  1. A clear, reassuring Hindi triage assessment:
     *प्राथमिक मूल्यांकन: आपके लक्षण श्वसन संबंधी (फेफड़े) संक्रमण के हो सकते हैं। हमने आपकी जानकारी सुरक्षित कर ली है।*
  2. An interactive ASI1 card suggesting consultation with a Pulmonologist (Chest Specialist).
- Right side of screen shows the generated doctor dossier stored under `data/dossiers/DOS-xxxx.json` and `.md`.
- Close-up highlight on the SOAP Dossier:
  - **Subjective:** Clean clinical translation of Hindi chief complaint.
  - **Objective:** Explicitly empty vital signs (zero hallucinated vitals!).
  - **Assessment:** Differential diagnoses (Pulmonary Tuberculosis rule-out, Chronic Bronchitis) with confidence rationale.
  - **Plan:** Recommended sputum AFB test and Chest X-ray PA view.

**Narrator (Voiceover - English):**
> "Notice the clinical integrity: unlike generic chatbot wrappers that hallucinate fake vitals and unverified prescriptions, CareRoute adheres to zero-fabrication safety rules. The patient's Hindi description is transformed into a rigorous English SOAP clinical dossier that doctors can trust immediately."

---

## Scene 4: OpenStreetMap CHC Discovery & Atomic OPD Slot Booking (2:15 - 2:55)

**Visual:**
- Patient taps `[स्लॉट देखें (View Slots)]` on the interactive card in ASI:One.
- Dispatcher routes `SlotQueryRequest` to `LogisticsWorker`.
- The Logistics Worker queries the live OpenStreetMap Overpass API for public Community Health Centers around Alwar, Rajasthan, matching the patient's needed specialty.
- ASI:One displays available OPD slots with verified capacity:
  - `ALW_CHEST_1000`: डॉ. आर. के. गुप्ता (Pulmonology) - 10:00 AM (3 slots left)
  - `ALW_CHEST_1130`: डॉ. आर. के. गुप्ता (Pulmonology) - 11:30 AM (2 slots left)
- Patient selects Slot `ALW_CHEST_1000`.
- Terminal shows atomic SQLite transaction decrements remaining slot capacity to prevent race conditions or double-booking.

**Narrator (Voiceover - English):**
> "Next, CareRoute connects patient location with regional healthcare infrastructure using OpenStreetMap Overpass geospatial queries. Available OPD appointments are displayed as interactive buttons. Booking utilizes atomic SQLite row locking, ensuring slot capacity cannot be oversold even during high traffic."

---

## Scene 5: Verifiable Anti-No-Show Escrow & Desk QR Refund (2:55 - 3:45)

**Visual:**
- ASI:One displays the Escrow Deposit Card:
  - Deposit: `0.5 FET` (Refundable anti-no-show security deposit)
  - Clear Hindi explanation: *यह राशि आपकी ओपीडी उपस्थिति के समय 100% वापस कर दी जाएगी।*
- Escrow Worker creates a deterministic state record:
  - Status: `LOCKED`
  - Ticket: `CR-ALW-20261024-XXXX`
  - Payment Protocol tx: `0x...` (or transparently labelled `[SIMULATED - PAYMENT_MODE=simulation]`).
- Patient receives confirmed appointment ticket in ASI:One with encrypted QR check-in payload.
- Transition to Clinic Desk View:
  - Patient arrives at Alwar CHC OPD registration desk.
  - The receptionist scans the patient's QR code.
  - Clinic reception invokes check-in verification.
  - Escrow Worker triggers instant 100% release of the 0.5 FET deposit back to patient address:
    - Status: `REFUNDED`
    - Transaction hash logged on Fetch ledger.
  - Patient's ASI:One updates with refund confirmation notification.

**Narrator (Voiceover - English):**
> "To combat the 35% no-show crisis that wastes specialist hours in rural hospitals, CareRoute uses an anti-no-show micro-deposit of 0.5 FET. The deposit is locked in escrow until the patient arrives at the clinic.
>
> When the patient scans their QR code at the CHC desk, the Escrow Worker immediately executes a full 100% refund. Patients pay zero net cost for healthcare, while clinics achieve near-zero absenteeism."

---

## Scene 6: Safety First - Emergency 108 SOS Detection (3:45 - 4:05)

**Visual:**
- New chat session in ASI:One.
- Patient types red-flag phrase:
  `"सीने में बहुत तेज दर्द हो रहा है और सांस लेने में भारी तकलीफ है, पसीना आ रहा है"`
- CareRoute instant tripwire activates in under 50ms:
  - Bypasses normal appointment queue.
  - Does NOT book an OPD slot.
  - Instantly issues emergency 108 SOS Red Alert card with click-to-call `tel:108` and nearest Emergency Hospital locator.

**Narrator (Voiceover - English):**
> "Crucially, CareRoute is built with deterministic clinical tripwires. Acute emergencies like myocardial infarction, snake bites, or trauma immediately bypass OPD booking, delivering instantaneous 108 ambulance routing and life-saving guidance."

---

## Scene 7: Conclusion & Fetch-a-thon 3.0 Summary (4:05 - 4:15)

**Visual:**
- Summary slide with GitHub repo QR code, Agentverse badge, and technology icons:
  - Fetch.ai uAgents 0.26
  - Agent Chat Protocol (ACP)
  - Agentverse Mailbox
  - ASI1 LLM Reasoning Engine
  - Fetch.ai Payment Protocol
- Text: *CareRoute: Accessible, Trustworthy, and Decentralized Healthcare for Bharat.*

**Narrator (Voiceover - English):**
> "CareRoute brings the best of Fetch.ai uAgents, ASI:One, and on-chain escrow to the millions who need it most. Thank you!"
