"""
AI Disaster Response Coordinator — FastAPI Main Application
REST API + WebSocket + Background Tasks
"""

import json
import logging
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import func as sql_func, or_

from backend.config import settings
from backend.database import get_db, init_db, SessionLocal
from backend.models import (
    UserDB, IncidentDB, ResourceDB, AlertDB,
    UserCreate, UserLogin, TokenResponse, UserResponse,
    IncidentCreate, IncidentResponse, ResourceResponse, AlertResponse,
    ChatRequest, ChatResponse, StatsResponse,
    IncidentStatus, ResourceStatus,
)
from backend.auth import (
    hash_password, verify_password, create_access_token,
    get_current_user, require_auth, require_role,
)
from backend.websocket_manager import ws_manager
from backend.agents.orchestrator import orchestrator
from backend.agents.rag_knowledge import rag_agent
from backend.mock_feed.generator import run_mock_feed

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


# ─── Seed Database ────────────────────────────────────────────────────────────

def seed_database():
    """Load seed data (hospitals, resources) into the database."""
    db = SessionLocal()
    try:
        data_dir = Path(__file__).parent.parent / "data" / "seed"

        # Only seed resources if the resource table is empty.
        resources_file = data_dir / "resources.json"
        if resources_file.exists() and db.query(ResourceDB).count() == 0:
            resources = json.loads(resources_file.read_text(encoding="utf-8"))
            for r in resources:
                db.add(ResourceDB(
                    name=r["name"],
                    resource_type=r["resource_type"],
                    status=r.get("status", "available"),
                    latitude=r["latitude"],
                    longitude=r["longitude"],
                    capacity=r.get("capacity", 1),
                    contact=r.get("contact"),
                ))
            db.commit()
            logger.info(f"✅ Seeded {len(resources)} resources")

        # Create default users
        for role, name in [("authority", "admin"), ("ngo", "rescuer"), ("civilian", "citizen")]:
            if not db.query(UserDB).filter(UserDB.username == name).first():
                db.add(UserDB(
                    username=name,
                    email=f"{name}@disaster.gov.in",
                    hashed_password=hash_password("password123"),
                    role=role,
                    full_name=f"Demo {role.title()} User",
                ))
        db.commit()
        logger.info("✅ Default demo users created (admin/rescuer/citizen — password: password123)")
        clear_hidden_mock_allocations(db)
        seed_example_history(db)
    finally:
        db.close()


def visible_incidents_query(db: Session, include_mock: bool = False):
    """Return incidents shown in normal app views."""
    query = db.query(IncidentDB)
    if not include_mock:
        query = query.filter(or_(IncidentDB.source.is_(None), IncidentDB.source != "mock_feed"))
    return query


def visible_alerts_query(db: Session, include_mock: bool = False):
    """Return alerts shown in normal app views."""
    query = db.query(AlertDB)
    if not include_mock:
        query = query.outerjoin(IncidentDB, AlertDB.incident_id == IncidentDB.id).filter(
            or_(AlertDB.incident_id.is_(None), IncidentDB.source != "mock_feed")
        )
    return query


def clear_hidden_mock_allocations(db: Session):
    """Release resources that were tied to hidden mock incidents."""
    mock_ids = [
        row[0]
        for row in db.query(IncidentDB.id).filter(IncidentDB.source == "mock_feed").all()
    ]
    if not mock_ids:
        return

    updated = (
        db.query(ResourceDB)
        .filter(ResourceDB.assigned_incident_id.in_(mock_ids))
        .update(
            {
                ResourceDB.status: ResourceStatus.AVAILABLE,
                ResourceDB.assigned_incident_id: None,
            },
            synchronize_session=False,
        )
    )
    if updated:
        db.commit()
        logger.info(f"Released {updated} resources assigned to hidden mock incidents")


def seed_example_history(db: Session):
    """Create a small visible incident history for demos without fake live alerts."""
    if visible_incidents_query(db).count() > 0:
        return

    now = datetime.utcnow()
    examples = [
        {
            "title": "Example: Yamuna flood watch",
            "description": "Historical example only. River levels rose near low-lying Yamuna areas after heavy rain.",
            "disaster_type": "flood",
            "severity": 3,
            "status": IncidentStatus.CONTAINED,
            "latitude": 28.6506,
            "longitude": 77.2303,
            "location_name": "Delhi",
            "affected_population": 4200,
            "ai_summary": "Flood response teams monitored embankments and assisted temporary relocation.",
            "created_at": now - timedelta(days=5, hours=3),
        },
        {
            "title": "Example: Warehouse fire response",
            "description": "Historical example only. Smoke was reported from an industrial warehouse; fire services contained the site.",
            "disaster_type": "fire",
            "severity": 4,
            "status": IncidentStatus.RESOLVED,
            "latitude": 19.0760,
            "longitude": 72.8777,
            "location_name": "Mumbai",
            "affected_population": 180,
            "ai_summary": "Fire tenders, ambulance support, and perimeter control were coordinated.",
            "created_at": now - timedelta(days=12, hours=6),
        },
        {
            "title": "Example: Hillside landslide report",
            "description": "Historical example only. Road blockage was reported after slope failure during rainfall.",
            "disaster_type": "landslide",
            "severity": 2,
            "status": IncidentStatus.VERIFIED,
            "latitude": 31.1048,
            "longitude": 77.1734,
            "location_name": "Shimla",
            "affected_population": 75,
            "ai_summary": "Road clearance and route diversion were tracked until access improved.",
            "created_at": now - timedelta(days=20, hours=2),
        },
    ]

    for item in examples:
        created_at = item.pop("created_at")
        incident = IncidentDB(
            **item,
            source="example_history",
            reported_by="system_example",
            created_at=created_at,
            updated_at=created_at,
        )
        db.add(incident)
        db.flush()
        db.add(AlertDB(
            incident_id=incident.id,
            title=f"EXAMPLE HISTORY: {incident.title.replace('Example: ', '')}",
            message=(
                f"Example historical record for {incident.location_name}. "
                f"Severity level {incident.severity}/5. {incident.ai_summary}"
            ),
            severity=incident.severity,
            alert_type="example",
            created_at=created_at,
        ))
    db.commit()
    logger.info(f"Seeded {len(examples)} visible example incidents")


# ─── Mock Feed Callback ──────────────────────────────────────────────────────

async def process_mock_event(report_text: str):
    """Process a mock feed event through the orchestrator."""
    db = SessionLocal()
    try:
        await orchestrator.process_report(report_text, db, source="mock_feed")
    except Exception as e:
        logger.error(f"Error processing mock event: {e}")
    finally:
        db.close()


# ─── App Lifespan ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("🚀 Starting AI Disaster Response Coordinator...")
    init_db()
    seed_database()

    mock_task = None
    if settings.MOCK_FEED_ENABLED:
        mock_task = asyncio.create_task(run_mock_feed(process_mock_event))
        logger.warning("Mock feed is enabled; generated incidents will be marked as source=mock_feed")
    else:
        logger.info("Mock feed disabled; waiting for real user/API reports")
    logger.info("✅ All systems operational")

    yield

    # Shutdown
    if mock_task:
        mock_task.cancel()
    logger.info("🛑 Shutting down...")


# ─── FastAPI App ──────────────────────────────────────────────────────────────

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Auth Endpoints ──────────────────────────────────────────────────────────

@app.post("/api/auth/register", response_model=TokenResponse)
def register(data: UserCreate, db: Session = Depends(get_db)):
    if db.query(UserDB).filter(UserDB.username == data.username).first():
        raise HTTPException(status_code=400, detail="Username already taken")
    if db.query(UserDB).filter(UserDB.email == data.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = UserDB(
        username=data.username,
        email=data.email,
        hashed_password=hash_password(data.password),
        role=data.role,
        full_name=data.full_name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token({"sub": user.username, "role": user.role})
    return TokenResponse(
        access_token=token,
        user=UserResponse.model_validate(user),
    )


@app.post("/api/auth/login", response_model=TokenResponse)
def login(data: UserLogin, db: Session = Depends(get_db)):
    user = db.query(UserDB).filter(UserDB.username == data.username).first()
    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token({"sub": user.username, "role": user.role})
    return TokenResponse(
        access_token=token,
        user=UserResponse.model_validate(user),
    )


# ─── Incident Endpoints ──────────────────────────────────────────────────────

@app.get("/api/incidents", response_model=list[IncidentResponse])
def get_incidents(limit: int = 50, include_mock: bool = False, db: Session = Depends(get_db)):
    return visible_incidents_query(db, include_mock).order_by(IncidentDB.created_at.desc()).limit(limit).all()


@app.get("/api/incidents/{incident_id}", response_model=IncidentResponse)
def get_incident(incident_id: int, db: Session = Depends(get_db)):
    incident = db.query(IncidentDB).filter(IncidentDB.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident


@app.post("/api/incidents", response_model=IncidentResponse)
async def create_incident(data: IncidentCreate, db: Session = Depends(get_db)):
    """Submit a new incident / SOS report — triggers full agent pipeline."""
    result = await orchestrator.process_report(
        f"{data.title}: {data.description} Location: {data.location_name}",
        db,
        source="user",
        overrides={
            "title": data.title,
            "disaster_type": data.disaster_type,
            "severity": data.severity,
            "location_name": data.location_name,
            "latitude": data.latitude,
            "longitude": data.longitude,
        },
    )
    incident = db.query(IncidentDB).filter(IncidentDB.id == result["id"]).first()
    return incident


@app.patch("/api/incidents/{incident_id}/status")
def update_incident_status(
    incident_id: int,
    status: str,
    db: Session = Depends(get_db),
    user: UserDB = Depends(require_role("authority", "ngo")),
):
    incident = db.query(IncidentDB).filter(IncidentDB.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    incident.status = status
    db.commit()
    return {"message": f"Status updated to {status}"}


# ─── Resource Endpoints ──────────────────────────────────────────────────────

@app.get("/api/resources", response_model=list[ResourceResponse])
def get_resources(db: Session = Depends(get_db)):
    return db.query(ResourceDB).all()


@app.patch("/api/resources/{resource_id}/release")
def release_resource(
    resource_id: int,
    db: Session = Depends(get_db),
):
    resource = db.query(ResourceDB).filter(ResourceDB.id == resource_id).first()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
    resource.status = ResourceStatus.AVAILABLE
    resource.assigned_incident_id = None
    db.commit()
    return {"message": f"Resource {resource.name} released"}


# ─── Alert Endpoints ─────────────────────────────────────────────────────────

@app.get("/api/alerts", response_model=list[AlertResponse])
def get_alerts(limit: int = 30, include_mock: bool = False, db: Session = Depends(get_db)):
    return visible_alerts_query(db, include_mock).order_by(AlertDB.created_at.desc()).limit(limit).all()


# ─── Chat (RAG) Endpoint ─────────────────────────────────────────────────────

@app.post("/api/chat", response_model=ChatResponse)
async def chat(data: ChatRequest):
    result = await rag_agent.query(data.message)
    return ChatResponse(**result)


# ─── Stats Endpoint ──────────────────────────────────────────────────────────

@app.get("/api/stats", response_model=StatsResponse)
def get_stats(db: Session = Depends(get_db)):
    total = visible_incidents_query(db).count()
    active = visible_incidents_query(db).filter(
        IncidentDB.status.in_([IncidentStatus.REPORTED, IncidentStatus.VERIFIED, IncidentStatus.RESPONDING])
    ).count()
    resolved = visible_incidents_query(db).filter(IncidentDB.status == IncidentStatus.RESOLVED).count()

    total_res = db.query(ResourceDB).count()
    deployed_res = db.query(ResourceDB).filter(
        ResourceDB.status.in_([ResourceStatus.DEPLOYED, ResourceStatus.EN_ROUTE])
    ).count()

    total_alerts = visible_alerts_query(db).count()

    # Severity distribution
    sev_rows = visible_incidents_query(db).with_entities(
        IncidentDB.severity, sql_func.count()
    ).group_by(IncidentDB.severity).all()
    severity_dist = {str(s): c for s, c in sev_rows}

    # Type distribution
    type_rows = visible_incidents_query(db).with_entities(
        IncidentDB.disaster_type, sql_func.count()
    ).group_by(IncidentDB.disaster_type).all()
    type_dist = {t or "unknown": c for t, c in type_rows}

    # Recent incidents (last 10)
    recent = visible_incidents_query(db).order_by(IncidentDB.created_at.desc()).limit(10).all()
    recent_trend = [
        {"id": i.id, "title": i.title, "severity": i.severity, "type": i.disaster_type, "created_at": str(i.created_at)}
        for i in recent
    ]

    return StatsResponse(
        total_incidents=total,
        active_incidents=active,
        resolved_incidents=resolved,
        total_resources=total_res,
        deployed_resources=deployed_res,
        total_alerts=total_alerts,
        severity_distribution=severity_dist,
        type_distribution=type_dist,
        recent_trend=recent_trend,
    )


# ─── Heatmap Endpoint ────────────────────────────────────────────────────────

@app.get("/api/heatmap")
def get_heatmap(db: Session = Depends(get_db)):
    incidents = visible_incidents_query(db).filter(
        IncidentDB.latitude.isnot(None),
        IncidentDB.longitude.isnot(None),
    ).all()
    return [
        {"lat": i.latitude, "lng": i.longitude, "intensity": i.severity / 5.0}
        for i in incidents
    ]


# ─── WebSocket ────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Client can send ping/pong or room subscription
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


# ─── Health Check ─────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "model": settings.GROQ_MODEL,
        "mock_feed_enabled": settings.MOCK_FEED_ENABLED,
    }


# ─── Serve Frontend ───────────────────────────────────────────────────────────

frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        if full_path and not full_path.startswith("api/"):
            file_path = frontend_dir / full_path
            if file_path.is_file():
                return FileResponse(file_path)
        return FileResponse(frontend_dir / "index.html")
