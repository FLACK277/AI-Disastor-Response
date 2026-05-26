"""
AI Disaster Response Coordinator — FastAPI Main Application
REST API + WebSocket + Background Tasks
"""

import json
import logging
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
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
from backend.live_sources import live_source
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
        purge_example_history(db)
    finally:
        db.close()


def visible_incidents_query(db: Session, include_mock: bool = False):
    """Return incidents shown in normal app views."""
    query = db.query(IncidentDB)
    if not include_mock:
        query = query.filter(
            or_(
                IncidentDB.source.is_(None),
                IncidentDB.source != "example_history",
            )
        )
    return query


def visible_alerts_query(db: Session, include_mock: bool = False):
    """Return alerts shown in normal app views."""
    query = db.query(AlertDB)
    if not include_mock:
        query = query.outerjoin(IncidentDB, AlertDB.incident_id == IncidentDB.id).filter(
            or_(
                AlertDB.incident_id.is_(None),
                IncidentDB.source.is_(None),
                IncidentDB.source != "example_history",
            )
        )
    return query


def serialize_incident(record: IncidentDB | dict) -> dict:
    """Normalize DB and live-feed incidents into API response shape."""
    if isinstance(record, dict):
        return record
    return IncidentResponse.model_validate(record).model_dump()


def serialize_alert(record: AlertDB | dict) -> dict:
    """Normalize DB and live-feed alerts into API response shape."""
    if isinstance(record, dict):
        return record
    return AlertResponse.model_validate(record).model_dump()


def sort_datetime(value) -> datetime:
    """Return a timezone-aware datetime for mixed DB/live feed timestamps."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return datetime.min.replace(tzinfo=timezone.utc)
    else:
        return datetime.min.replace(tzinfo=timezone.utc)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_data_age(record: dict) -> dict:
    """Mark records outside the last 7 days without hiding them from the UI."""
    item = dict(record)
    is_old = sort_datetime(item.get("created_at")) < datetime.now(tz=timezone.utc) - timedelta(days=7)
    item["is_old"] = is_old
    item["data_age"] = "Old" if is_old else "Current"
    return item


def combined_incidents(db: Session, limit: int = 50, include_mock: bool = False) -> list[dict]:
    """Return live Uttarakhand incidents plus stored user incidents."""
    stored = [
        add_data_age(serialize_incident(incident))
        for incident in visible_incidents_query(db, include_mock).order_by(IncidentDB.created_at.desc()).all()
    ]
    live = [add_data_age(incident) for incident in live_source.fetch(limit=limit).incidents]
    combined = sorted(stored + live, key=lambda item: sort_datetime(item.get("created_at")), reverse=True)
    return combined[:limit]


def combined_alerts(db: Session, limit: int = 30, include_mock: bool = False) -> list[dict]:
    """Return live-source alerts plus stored alerts."""
    stored = [
        add_data_age(serialize_alert(alert))
        for alert in visible_alerts_query(db, include_mock).order_by(AlertDB.created_at.desc()).all()
    ]
    live = [add_data_age(alert) for alert in live_source.fetch(limit=limit).alerts]
    combined = sorted(stored + live, key=lambda item: sort_datetime(item.get("created_at")), reverse=True)
    return combined[:limit]


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


def purge_example_history(db: Session):
    """Remove previously-seeded example incidents and their alerts."""
    example_ids = [
        row[0]
        for row in db.query(IncidentDB.id).filter(IncidentDB.source == "example_history").all()
    ]
    if not example_ids:
        return

    db.query(AlertDB).filter(AlertDB.incident_id.in_(example_ids)).delete(synchronize_session=False)
    db.query(IncidentDB).filter(IncidentDB.id.in_(example_ids)).delete(synchronize_session=False)
    db.commit()
    logger.info(f"Removed {len(example_ids)} example incidents from the local database")


def purge_stale_mock_incidents(db: Session):
    """Remove mock-feed incidents older than 24 hours to keep the dashboard fresh."""
    cutoff = datetime.utcnow() - timedelta(hours=24)
    stale_ids = [
        row[0]
        for row in db.query(IncidentDB.id)
        .filter(IncidentDB.source == "mock_feed", IncidentDB.created_at < cutoff)
        .all()
    ]
    if not stale_ids:
        return

    # Release resources tied to stale mock incidents
    db.query(ResourceDB).filter(ResourceDB.assigned_incident_id.in_(stale_ids)).update(
        {ResourceDB.status: ResourceStatus.AVAILABLE, ResourceDB.assigned_incident_id: None},
        synchronize_session=False,
    )
    db.query(AlertDB).filter(AlertDB.incident_id.in_(stale_ids)).delete(synchronize_session=False)
    db.query(IncidentDB).filter(IncidentDB.id.in_(stale_ids)).delete(synchronize_session=False)
    db.commit()
    logger.info(f"🧹 Purged {len(stale_ids)} stale mock incidents (older than 24h)")


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
    return combined_incidents(db, limit=limit, include_mock=include_mock)


@app.get("/api/incidents/{incident_id}", response_model=IncidentResponse)
def get_incident(incident_id: int, db: Session = Depends(get_db)):
    incident = db.query(IncidentDB).filter(IncidentDB.id == incident_id).first()
    if incident:
        return incident
    for live_incident in live_source.fetch(limit=25).incidents:
        if live_incident["id"] == incident_id:
            return live_incident
    raise HTTPException(status_code=404, detail="Incident not found")


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
    return combined_alerts(db, limit=limit, include_mock=include_mock)


# ─── Chat (RAG) Endpoint ─────────────────────────────────────────────────────

@app.post("/api/chat", response_model=ChatResponse)
async def chat(data: ChatRequest):
    result = await rag_agent.query(data.message)
    return ChatResponse(**result)


# ─── Stats Endpoint ──────────────────────────────────────────────────────────

@app.get("/api/stats", response_model=StatsResponse)
def get_stats(db: Session = Depends(get_db)):
    incidents = combined_incidents(db, limit=100)
    total = len(incidents)
    active = sum(1 for incident in incidents if incident["status"] in [IncidentStatus.REPORTED, IncidentStatus.VERIFIED, IncidentStatus.RESPONDING])
    resolved = sum(1 for incident in incidents if incident["status"] == IncidentStatus.RESOLVED)

    total_res = db.query(ResourceDB).count()
    deployed_res = db.query(ResourceDB).filter(
        ResourceDB.status.in_([ResourceStatus.DEPLOYED, ResourceStatus.EN_ROUTE])
    ).count()

    alerts = combined_alerts(db, limit=100)
    total_alerts = len(alerts)

    # Severity distribution
    severity_dist = {}
    for incident in incidents:
        severity_key = str(incident["severity"])
        severity_dist[severity_key] = severity_dist.get(severity_key, 0) + 1

    # Type distribution
    type_dist = {}
    for incident in incidents:
        incident_type = incident.get("disaster_type") or "unknown"
        type_dist[incident_type] = type_dist.get(incident_type, 0) + 1

    # Recent incidents (last 10)
    recent_trend = [
        {"id": i["id"], "title": i["title"], "severity": i["severity"], "type": i.get("disaster_type"), "created_at": str(i["created_at"])}
        for i in incidents[:10]
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
    incidents = [
        incident
        for incident in combined_incidents(db, limit=100)
        if incident.get("latitude") is not None and incident.get("longitude") is not None
    ]
    return [
        {"lat": i["latitude"], "lng": i["longitude"], "intensity": i["severity"] / 5.0}
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
        "live_sources": ["USGS Uttarakhand bbox", "GDACS", "Open-Meteo", "Bhudev", "Recent trusted news"],
    }


# ─── Live Source Status ───────────────────────────────────────────────────────

@app.get("/api/live-status")
def get_live_status():
    """Report which real-time data sources are active and their last fetch time."""
    return live_source.source_status


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
