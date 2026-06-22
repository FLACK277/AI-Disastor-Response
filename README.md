# AI Disaster Response Coordinator

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688)
![SQLite](https://img.shields.io/badge/Database-SQLite-lightgrey)
![WebSocket](https://img.shields.io/badge/Realtime-WebSockets-purple)
![AI](https://img.shields.io/badge/AI-Groq%20LLM-orange)

AI Disaster Response Coordinator is an AI-powered emergency management platform that helps authorities, rescue teams, NGOs, and civilians coordinate disaster response in real time. It combines live incident monitoring, AI-based crisis analysis, geospatial mapping, resource allocation, emergency alerts, and SOP-guided assistance in one dashboard.

The current implementation is focused on Uttarakhand, India, using public disaster, earthquake, weather, and trusted news feeds to surface current emergency signals alongside user-submitted SOS reports.

## Why This Project Matters

During disasters, the biggest challenge is not only detecting what happened. It is quickly understanding severity, location, available resources, response priorities, and the correct procedure to follow. Information often arrives from many sources: citizens, news, weather feeds, earthquake feeds, rescue teams, and local authorities.

This project addresses that gap by creating a single coordination layer where:

- Emergency reports can be submitted and tracked.
- AI helps classify the type and severity of the crisis.
- Locations are mapped for faster situational awareness.
- Resources can be monitored and assigned.
- Alerts are generated and broadcast in real time.
- Standard operating procedures are available through a chatbot.

The goal is to reduce response delay, improve coordination, and support data-driven emergency decisions.

## What Makes It Unique

- Multi-agent AI workflow: A report is not just stored. It moves through separate agents for crisis detection, geocoding, resource allocation, communication, and SOP knowledge retrieval.
- Uttarakhand-focused live intelligence: The dashboard aggregates signals from USGS, GDACS, Open-Meteo, Bhudev/IIT Roorkee, and recent trusted news sources, filtered around Uttarakhand.
- Real-time operations dashboard: Incidents, alerts, resources, map markers, severity charts, and status updates are shown in one interface.
- SOP-aware assistant: The chatbot retrieves information from local emergency procedure files for floods, earthquakes, fires, landslides, cyclones, triage, evacuation, shelter, and hazmat response.
- Role-based emergency access: Demo users represent authority, NGO/rescue, and civilian workflows.
- Works locally with SQLite: The project can be run as a self-contained local prototype without requiring a heavy external database.
- Mock feed support: Simulated incidents can be enabled for demos, testing, and presentations.

## Key Features

| Area | Capability |
| --- | --- |
| Incident Management | Submit, view, classify, and track disaster reports |
| AI Classification | Detect disaster type, severity, location, affected population, and summary |
| Live Monitoring | Pull public disaster signals from multiple real-time sources |
| Mapping | Visualize incidents on a Leaflet map centered around Uttarakhand |
| Resource Coordination | Track emergency resources and release assigned resources |
| Alerts | Generate and display severity-based alerts |
| Realtime Updates | Broadcast new incidents, alerts, and resource changes over WebSockets |
| SOP Chatbot | Ask emergency procedure questions using local SOP documents |
| Dashboard Analytics | View incident counts, active cases, resolved cases, severity distribution, and disaster types |
| Authentication | JWT-based login with seeded demo users |

## Tech Stack

### Backend

- Python
- FastAPI
- Uvicorn
- SQLAlchemy
- Pydantic
- Pydantic Settings
- Python-JOSE for JWT authentication
- Passlib for password hashing
- HTTPX for external data fetching
- WebSockets for live dashboard updates

### Frontend

- HTML
- CSS
- JavaScript
- Leaflet.js for interactive maps
- Browser Fetch API
- Browser WebSocket API

### AI and Data

- Groq API for LLM-powered classification and SOP response generation
- Local RAG-style keyword retrieval over SOP text files
- SQLite local database
- Seeded emergency resources and demo users
- Live public data sources:
  - USGS Earthquake Hazards Program
  - GDACS disaster alerts
  - Open-Meteo severe weather data
  - Bhudev/IIT Roorkee local earthquake early warning page
  - Trusted recent news feeds

## System Architecture

```text
Citizen / Authority / NGO User
          |
          v
Frontend Dashboard (HTML, CSS, JS, Leaflet)
          |
          v
FastAPI Backend
          |
          |-- Authentication and role handling
          |-- Incident, resource, alert, stats APIs
          |-- WebSocket broadcast manager
          |
          v
AI Agent Pipeline
          |
          |-- Crisis Detection Agent
          |-- Geo Mapping Agent
          |-- Resource Allocation Agent
          |-- Communication Agent
          |-- RAG Knowledge Agent
          |
          v
SQLite Database + SOP Files + Live Public Sources
```

## AI Agent Pipeline

When a new emergency report is submitted, the orchestrator processes it through this pipeline:

1. Crisis Detection Agent analyzes the report using the LLM and extracts disaster type, severity, location, affected population, title, and summary.
2. Geo Mapping Agent converts the reported place into coordinates when latitude and longitude are not provided.
3. Database Layer stores the incident with status, source, severity, location, and AI summary.
4. Resource Allocation Agent assigns available resources for higher-severity incidents.
5. Communication Agent creates an alert for the incident.
6. WebSocket Manager broadcasts the new incident, alert, and resource update to connected dashboards.
7. RAG Knowledge Agent answers SOP questions using local emergency procedure files.

## Screens and Workflows

- Login screen with demo accounts
- Main dashboard with live statistics
- Uttarakhand incident map
- Incident list with severity, type, status, and data age
- Resource status page
- Alert history page
- Emergency SOS report form
- Emergency SOP assistant chatbot

## Project Structure

```text
AI_Disaster_Response/
|-- backend/
|   |-- agents/
|   |   |-- orchestrator.py
|   |   |-- crisis_detection.py
|   |   |-- geo_mapping.py
|   |   |-- resource_allocation.py
|   |   |-- communication.py
|   |   `-- rag_knowledge.py
|   |-- mock_feed/
|   |   `-- generator.py
|   |-- main.py
|   |-- models.py
|   |-- database.py
|   |-- auth.py
|   |-- config.py
|   |-- live_sources.py
|   |-- llm_client.py
|   |-- websocket_manager.py
|   `-- requirements.txt
|-- data/
|   |-- seed/
|   |   |-- resources.json
|   |   `-- hospitals.json
|   `-- sops/
|       |-- flood_response.txt
|       |-- fire_response.txt
|       |-- earthquake_response.txt
|       |-- cyclone_response.txt
|       |-- landslide_response.txt
|       |-- tsunami_response.txt
|       |-- industrial_hazmat_response.txt
|       |-- medical_triage_response.txt
|       `-- evacuation_shelter_response.txt
|-- frontend/
|   |-- index.html
|   |-- app.js
|   `-- style.css
|-- .env.example
|-- run_localhost.cmd
`-- README.md
```

## Getting Started

### 1. Clone the repository

```bash
git clone <your-repository-url>
cd AI_Disaster_Response
```

### 2. Create and activate a virtual environment

Windows:

```bash
python -m venv .venv
.venv\Scripts\activate
```

macOS/Linux:

```bash
python -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r backend/requirements.txt
```

### 4. Configure environment variables

Copy the sample environment file:

```bash
copy .env.example .env
```

On macOS/Linux:

```bash
cp .env.example .env
```

Update `.env`:

```env
APP_NAME=AI Disaster Response Coordinator
DEBUG=true
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile
JWT_SECRET=change-this-to-a-random-secret
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=480
DATABASE_URL=sqlite:///./disaster_response.db
CORS_ORIGINS=http://localhost:5173,http://localhost:3000,http://localhost:8000
MOCK_FEED_INTERVAL=25
MOCK_FEED_ENABLED=false
GEOCODER_USER_AGENT=disaster-response-coordinator
```

### 5. Run the app

```bash
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open the app:

```text
http://127.0.0.1:8000
```

On Windows, you can also run:

```bash
run_localhost.cmd
```

## Demo Accounts

The app seeds demo users automatically on startup:

| Role | Username | Password |
| --- | --- | --- |
| Authority | `admin` | `password123` |
| NGO / Rescue | `rescuer` | `password123` |
| Civilian | `citizen` | `password123` |

## API Endpoints

FastAPI interactive docs are available at:

```text
http://127.0.0.1:8000/docs
```

| Method | Endpoint | Description |
| --- | --- | --- |
| `POST` | `/api/auth/register` | Register a new user |
| `POST` | `/api/auth/login` | Log in and receive a JWT |
| `GET` | `/api/incidents` | List incidents |
| `GET` | `/api/incidents/{incident_id}` | Get one incident |
| `POST` | `/api/incidents` | Submit an emergency report |
| `PATCH` | `/api/incidents/{incident_id}/status` | Update incident status |
| `GET` | `/api/resources` | List resources |
| `PATCH` | `/api/resources/{resource_id}/release` | Release a resource |
| `GET` | `/api/alerts` | List alerts |
| `POST` | `/api/chat` | Ask the SOP assistant |
| `GET` | `/api/stats` | Dashboard statistics |
| `GET` | `/api/heatmap` | Incident heatmap data |
| `GET` | `/api/health` | Health check |
| `GET` | `/api/live-status` | Live source status |
| `WS` | `/ws` | Realtime dashboard updates |

## SOP Knowledge Base

The chatbot uses local SOP documents from `data/sops/`. It supports questions about:

- Flood response
- Fire response
- Earthquake response
- Cyclone response
- Landslide response
- Tsunami response
- Industrial hazmat response
- Medical triage
- Evacuation and shelter response

If the LLM service is unavailable, the RAG agent can still return a local SOP lookup response from the relevant documents.

## Mock Feed for Demonstrations

Mock feed generation is disabled by default. To enable simulated incidents:

```env
MOCK_FEED_ENABLED=true
MOCK_FEED_INTERVAL=25
```

Restart the server after changing environment variables.

## Real-World Use Cases

- Disaster management authority dashboard
- Emergency operation center prototype
- NGO/rescue team coordination tool
- Hackathon or academic AI-for-social-good project
- Local disaster monitoring system
- Training and simulation platform using mock incidents

## Future Improvements

- Add push notifications or SMS alert integration
- Add admin panel for creating and editing resources
- Add richer GIS layers for shelters, hospitals, roads, and blocked routes
- Add image or document upload for incident evidence
- Add production database support such as PostgreSQL
- Add unit and integration tests
- Add deployment templates for Docker or cloud platforms
- Add analytics for response time and resource utilization

## Security and Deployment Notes

- Do not commit your real `.env` file.
- Keep API keys private.
- Replace `JWT_SECRET` before production deployment.
- Review CORS settings before hosting publicly.
- Live public sources may fail or rate-limit; the app uses cached live feed results for responsiveness.
- SQLite is suitable for local demos and prototypes. Use a production database for real deployments.

## License

No license has been specified yet. Add a license before publishing or accepting external contributions.
