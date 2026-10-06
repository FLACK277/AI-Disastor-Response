# 🚨 AI Disaster Response Coordinator

An intelligent, multi-agent emergency response and disaster management system built with **FastAPI**, **Groq LLM (Llama 3)**, **Retrieval-Augmented Generation (RAG)**, and **real-time spatial/weather API integrations**.

---

## 📌 Executive Summary

The **AI Disaster Response Coordinator** synthesizes raw disaster reports, live seismic data, weather warnings, and emergency Standard Operating Procedures (SOPs) into actionable operational orders for first responders, NGOs, and government authorities.

By combining a **Multi-Agent Orchestration Engine** with a **Multi-Source Retrieval-Augmented Generation (RAG)** pipeline, the platform eliminates single-source bias, reduces response latency, and ensures all emergency recommendations are grounded in verified protocols and real-time field telemetry.

---

## 🧠 Retrieval-Augmented Generation (RAG) & Multi-Source Information Extraction

The core intelligence engine uses RAG to pull contextual data from **three distinct information tiers**:

```
                              ┌───────────────────────────────────────┐
                              │           USER QUERY / PROMPT         │
                              └───────────────────┬───────────────────┘
                                                  │
                                                  ▼
                       ┌─────────────────────────────────────────────────────┐
                       │             RAG KNOWLEDGE AGENT / FUSION            │
                       └───────────┬──────────────┬──────────────┬───────────┘
                                   │              │              │
                                   ▼              ▼              ▼
         ┌───────────────────────────┐  ┌──────────────────┐  ┌───────────────────────────┐
         │     TIER 1: SOP DOCS      │  │ TIER 2: LIVE APIS│  │ TIER 3: SYSTEM DATABASE   │
         │ - Earthquake SOP          │  │ - USGS (Seismic) │  │ - Resource Status         │
         │ - Flood Inundation SOP    │  │ - GDACS (UN)     │  │ - Active Incidents        │
         │ - Landslide Response SOP  │  │ - Open-Meteo     │  │ - Hospital Capacities     │
         │ - Hazmat / Fire SOP       │  │ - Bhudev Scrape  │  │ - Response Vehicles       │
         └─────────────┬─────────────┘  └────────┬─────────┘  └─────────────┬─────────────┘
                       │                         │                          │
                       └──────────────────┐      │      ┌───────────────────┘
                                          ▼      ▼      ▼
                               ┌──────────────────────────────────┐
                               │   GROQ LLM (LLAMA 3 SYNTHESIS)   │
                               └─────────────────┬────────────────┘
                                                 │
                                                 ▼
                               ┌──────────────────────────────────┐
                               │ VERIFIED OPERATIONAL INSTRUCTION │
                               │   WITH SOURCE CITATIONS & DATA   │
                               └──────────────────────────────────┘
```

### 🔍 Information Sources Extracted by RAG

1. **Curated Emergency Standard Operating Procedures (SOPs)** ([`data/sops/`](file:///c:/Users/rawat/AI-Disastor-Response/data/sops)):
   - Unstructured text files containing official guidance for earthquakes, floods, fires, landslides, cyclones, tsunamis, industrial chemical hazards, evacuation/shelter management, and field medical triage.
   - Text is chunked with character overlap, indexed, and retrieved dynamically using token expansion and keyword-weighted matching.

2. **Real-time Live Remote Feeds & Telemetry** ([`backend/live_sources.py`](file:///c:/Users/rawat/AI-Disastor-Response/backend/live_sources.py)):
   - **USGS Earthquake Hazards API**: Live GeoJSON feed of seismic events filtered by geographic bounding box (e.g., Uttarakhand / Northern India).
   - **GDACS (UN Global Disaster Alert System)**: Live disaster alerts for floods, cyclones, and landslides.
   - **Open-Meteo API**: Live weather forecasts and precipitation warnings across key mountain districts.
   - **Bhudev (IIT Roorkee EEW)**: Scraped regional Earthquake Early Warning data.

3. **Relational Database & Field Resource Telemetry** ([`backend/database.py`](file:///c:/Users/rawat/AI-Disastor-Response/backend/database.py)):
   - Structured SQLite/SQLAlchemy tables maintaining real-time status of rescue teams, fire tenders, ambulances, relief camp capacities, and verified incident reports.

---

## 🛠️ Demonstrating RAG Extraction: Use Cases & Examples

Below are concrete examples showing how the RAG engine retrieves and synthesizes information from different sources to answer operational queries.

---

### Use Case 1: Earthquake Response Query
> **User Question:** *"What should responders do for a magnitude 5.2 earthquake in Chamoli, and what nearby medical resources are available?"*

#### Multi-Source RAG Extraction Process:
1. **Source 1 Extraction (SOP Knowledge Base - [`earthquake_response.txt`](file:///c:/Users/rawat/AI-Disastor-Response/data/sops/earthquake_response.txt)):**
   - Retrieves structural damage assessment protocols, gas leak checks, and aftershock safety procedures.
2. **Source 2 Extraction (Live External API - USGS & Open-Meteo):**
   - Fetches recent seismic magnitude (5.2 M_w) and local weather conditions in Chamoli (lat 30.4090, lon 79.3200) to check for rain/landslide risks.
3. **Source 3 Extraction (System Database - `resources` table):**
   - Queries available hospitals and medical units near Chamoli (e.g., *Chamoli District Hospital*, *Joshimath First Aid Unit*).

#### Synthesized RAG Output:
```json
{
  "response": "According to the Earthquake Emergency Response SOP (earthquake_response.txt) and live field telemetry:\n\n1. Immediate Actions:\n   - Establish a 50m perimeter around structurally compromised buildings.\n   - Inspect gas and electrical mains before sending search units inside.\n   - Prepare for potential secondary landslides due to Chamoli's steep terrain.\n\n2. Live Telemetry:\n   - Seismic Event: M5.2 recorded in Chamoli district.\n\n3. Deployed/Available Resources:\n   - Chamoli District Hospital (Capacity: 45 beds, Status: Available)\n   - SDRF Battalion 2 (Distance: 12 km)",
  "sources": [
    "earthquake_response.txt",
    "USGS_Live_Feed",
    "Database_Resource_Registry"
  ]
}
```

---

### Use Case 2: Flash Flood & River Inundation Query
> **User Question:** *"A flash flood has occurred near Rishikesh. What is the evacuation protocol and where can we house displaced civilians?"*

#### Multi-Source RAG Extraction Process:
1. **Source 1 Extraction (SOP Knowledge Base - [`flood_response.txt`](file:///c:/Users/rawat/AI-Disastor-Response/data/sops/flood_response.txt) & [`evacuation_shelter_response.txt`](file:///c:/Users/rawat/AI-Disastor-Response/data/sops/evacuation_shelter_response.txt)):**
   - Extracts water level safety thresholds, boat deployment rules, and shelter sanitation requirements.
2. **Source 2 Extraction (Live Remote Weather Feed - Open-Meteo API):**
   - Pulls current 24-hour precipitation accumulation and river surge alerts for Dehradun/Rishikesh region.
3. **Source 3 Extraction (Database & Asset Registry):**
   - Identifies active relief shelters and evacuation transport vehicles currently in `available` status.

#### Synthesized RAG Output:
```json
{
  "response": "Based on flood_response.txt and evacuation_shelter_response.txt:\n\n1. Evacuation Protocol:\n   - Move residents to high ground above the 100-year flood line.\n   - Deploy inflatable rescue boats along low-lying river banks.\n   - Avoid crossing moving water deeper than 15 cm.\n\n2. Shelter Allocation:\n   - Direct evacuees to Rishikesh Community Relief Center (Capacity: 300 persons).\n   - Ensure drinking water testing (chlorination > 0.5 mg/L) upon intake.",
  "sources": [
    "flood_response.txt",
    "evacuation_shelter_response.txt",
    "OpenMeteo_Weather_Feed"
  ]
}
```

---

### Use Case 3: Chemical Spill / Industrial Hazmat Query
> **User Question:** *"An industrial tank leak of ammonia gas is reported. What decontamination steps should responders take?"*

#### Multi-Source RAG Extraction Process:
1. **Source 1 Extraction (SOP Knowledge Base - [`industrial_hazmat_response.txt`](file:///c:/Users/rawat/AI-Disastor-Response/data/sops/industrial_hazmat_response.txt)):**
   - Retrieves chemical exclusion zone distance (800m upwind), Level A/B PPE requirements, and neutralizer usage.
2. **Source 2 Extraction (Live Atmospheric Data):**
   - Retrieves wind direction and velocity to determine plume dispersion area.

#### Synthesized RAG Output:
```json
{
  "response": "Based on industrial_hazmat_response.txt:\n\n1. Safety Zones:\n   - Evacuate all personnel within an 800-meter radius UPWIND of the spill site.\n2. Responder Protection:\n   - Entry teams MUST wear Level A self-contained breathing apparatus (SCBA) suits.\n3. Decontamination:\n   - Set up primary wash station with copius water spray downwind of the warm zone.",
  "sources": [
    "industrial_hazmat_response.txt"
  ]
}
```

---

## 🤖 Multi-Agent Architecture

The backend orchestrates five specialized agents alongside the RAG Knowledge Engine:

```
                  ┌─────────────────────────────────────────┐
                  │          ORCHESTRATOR AGENT             │
                  │ (backend/agents/orchestrator.py)        │
                  └────────────────────┬────────────────────┘
                                       │
      ┌────────────────┬───────────────┼───────────────┬────────────────┐
      │                │               │               │                │
      ▼                ▼               ▼               ▼                ▼
┌───────────┐    ┌───────────┐   ┌───────────┐   ┌───────────┐    ┌───────────┐
│  CRISIS   │    │    GEO    │   │ RESOURCE  │   │   COMM    │    │    RAG    │
│ DETECTION │    │  MAPPING  │   │ALLOCATION │   │  ALERT    │    │ KNOWLEDGE │
└───────────┘    └───────────┘   └───────────┘   └───────────┘    └───────────┘
```

- **[`orchestrator.py`](file:///c:/Users/rawat/AI-Disastor-Response/backend/agents/orchestrator.py)**: Receives raw reports, coordinates workflow between all sub-agents, and broadcasts websocket updates.
- **[`crisis_detection.py`](file:///c:/Users/rawat/AI-Disastor-Response/backend/agents/crisis_detection.py)**: Uses Groq LLM to classify disaster types (1-5 severity scale) and extract structured entities.
- **[`geo_mapping.py`](file:///c:/Users/rawat/AI-Disastor-Response/backend/agents/geo_mapping.py)**: Performs reverse geocoding and maps landmark names to precise latitude/longitude coordinates.
- **[`resource_allocation.py`](file:///c:/Users/rawat/AI-Disastor-Response/backend/agents/resource_allocation.py)**: Calculates Haversine distances to match incidents with nearest available responders/hospitals.
- **[`communication.py`](file:///c:/Users/rawat/AI-Disastor-Response/backend/agents/communication.py)**: Generates public emergency warning broadcasts and responder dispatch alerts.
- **[`rag_knowledge.py`](file:///c:/Users/rawat/AI-Disastor-Response/backend/agents/rag_knowledge.py)**: Executes multi-source document & API retrieval and formats context for Groq AI queries.

---

## 💻 Tech Stack

- **Backend**: Python 3.10+, FastAPI, Uvicorn, SQLAlchemy, SQLite, Pydantic, HTTPX.
- **AI & NLP**: Groq REST Client (`llama-3.3-70b-versatile` / `llama3-70b-8192`), Custom Keyword Tokenization & RAG Expansion.
- **Frontend**: HTML5, Vanilla JavaScript, CSS3 (Glassmorphism UI), Leaflet.js (Interactive Geospatial Mapping).
- **Live APIs**: USGS Earthquake GeoJSON, UN GDACS, Open-Meteo Weather API, Bhudev Scraper.

---

## ⚡ Quick Start & Installation

### 1. Prerequisites
- Python 3.10 or higher
- Git

### 2. Clone Repository & Environment Setup
```bash
git clone https://github.com/FLACK277/AI-Disastor-Response.git
cd AI-Disastor-Response

# Create virtual environment
python -m venv .venv

# Activate virtual environment (Windows)
.venv\Scripts\activate
# Activate virtual environment (Linux/macOS)
# source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure Environment Variables
Create a `.env` file in the root directory:
```env
PORT=8000
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile
DATABASE_URL=sqlite:///./disaster_response.db
```

> **Note:** If `GROQ_API_KEY` is omitted, the system seamlessly uses local rule-based fallback handlers for RAG lookups and incident classification.

### 4. Run Development Server
```bash
# Windows launch script
run_localhost.cmd

# Or directly with Uvicorn:
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Open your browser to `http://localhost:8000` to view the interactive dashboard.

---

## 📡 REST API Reference

| Endpoint | Method | Description |
|---|---|---|
| `/api/chat` | `POST` | **RAG Query Endpoint** — Send questions to query SOPs & live sources |
| `/api/incidents` | `GET` / `POST` | Fetch all incidents or report a new incident |
| `/api/incidents/{id}/verify` | `POST` | Verify an incident & trigger automated resource dispatch |
| `/api/resources` | `GET` / `POST` | Manage response teams, ambulances, and shelter assets |
| `/api/alerts` | `GET` | Retrieve active public & responder emergency alerts |
| `/api/live-feed` | `GET` | Fetch real-time USGS seismic and Open-Meteo weather feeds |
| `/api/stats` | `GET` | Dashboard statistics & disaster type breakdown |
| `/ws` | `WebSocket` | Real-time incident updates and emergency push notifications |

### Example RAG API Call via `curl`:
```bash
curl -X POST "http://localhost:8000/api/chat" \
     -H "Content-Type: application/json" \
     -d '{"message": "What is the medical triage protocol during a landslide disaster?"}'
```

---

## 📁 Repository Structure

```
AI-Disastor-Response/
├── backend/
│   ├── agents/
│   │   ├── orchestrator.py        # Multi-agent coordinator
│   │   ├── crisis_detection.py    # LLM disaster classifier
│   │   ├── geo_mapping.py         # Geocoding & coordinate mapper
│   │   ├── resource_allocation.py # Nearest-resource dispatcher
│   │   ├── communication.py       # Alert generator
│   │   └── rag_knowledge.py       # RAG knowledge agent over SOPs
│   ├── auth.py                    # JWT Authentication & role RBAC
│   ├── config.py                  # Pydantic environment configuration
│   ├── database.py                # Database session & engine
│   ├── live_sources.py            # Live USGS, GDACS, Weather API integrations
│   ├── llm_client.py              # Groq REST API wrapper & fallbacks
│   ├── main.py                    # FastAPI application routes
│   └── models.py                  # SQLAlchemy & Pydantic models
├── data/
│   ├── sops/                      # Emergency SOP text documents for RAG
│   └── seed/                      # Initial database seed data (hospitals, resources)
├── frontend/                      # Web dashboard (HTML, CSS, JS, Leaflet maps)
├── .env.example                   # Environment variable template
├── requirements.txt               # Python package dependencies
└── README.md                      # Project documentation
```

---

## 🤝 License & Contributing

Distributed under the MIT License. See `LICENSE` for details. Contributions, issues, and feature requests are welcome!
