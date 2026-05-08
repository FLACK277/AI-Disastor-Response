"""
Orchestrator Agent
Coordinates the full agent pipeline: detect → geocode → allocate → communicate.
"""

import logging
from sqlalchemy.orm import Session
from backend.models import IncidentDB, IncidentStatus
from backend.agents.crisis_detection import crisis_agent
from backend.agents.geo_mapping import geo_agent
from backend.agents.resource_allocation import resource_agent
from backend.agents.communication import comm_agent
from backend.websocket_manager import ws_manager

logger = logging.getLogger(__name__)


class OrchestratorAgent:
    """Master agent — routes events through the full processing pipeline."""

    def __init__(self):
        logger.info("✅ Orchestrator Agent initialized")

    async def process_report(
        self,
        report_text: str,
        db: Session,
        source: str = "user",
        overrides: dict | None = None,
    ) -> dict:
        """
        Full pipeline: analyze → geocode → store → allocate → alert → broadcast.
        Returns the created incident data.
        """
        logger.info(f"🎯 Orchestrator processing report from {source}")

        # Step 1: Crisis Detection — classify type and severity
        classification = await crisis_agent.analyze(report_text)
        overrides = overrides or {}
        for source_key, target_key in {
            "title": "title",
            "disaster_type": "disaster_type",
            "severity": "severity",
            "location_name": "location",
            "affected_population": "affected_population",
        }.items():
            value = overrides.get(source_key)
            if value not in (None, ""):
                classification[target_key] = value
        logger.info(f"  → Classification: {classification.get('disaster_type')} (severity {classification.get('severity')})")

        # Step 2: Geo Mapping — convert location to coordinates
        location_str = classification.get("location", "Unknown")
        if overrides.get("latitude") is not None and overrides.get("longitude") is not None:
            lat, lng = overrides["latitude"], overrides["longitude"]
        else:
            lat, lng = await geo_agent.geocode(location_str)

        try:
            severity = min(max(int(classification.get("severity") or 1), 1), 5)
        except (TypeError, ValueError):
            severity = 1
        try:
            affected_population = max(int(classification.get("affected_population") or 0), 0)
        except (TypeError, ValueError):
            affected_population = 0

        # Step 3: Store incident in database
        incident = IncidentDB(
            title=classification.get("title", report_text[:80]),
            description=report_text,
            disaster_type=classification.get("disaster_type", "other"),
            severity=severity,
            status=IncidentStatus.REPORTED,
            latitude=lat,
            longitude=lng,
            location_name=location_str,
            reported_by=source,
            source=source,
            affected_population=affected_population,
            ai_summary=classification.get("ai_summary", ""),
        )
        db.add(incident)
        db.commit()
        db.refresh(incident)
        logger.info(f"  → Incident #{incident.id} created")

        # Step 4: Resource Allocation (for severity >= 3)
        allocated = []
        if incident.severity >= 3:
            allocated = await resource_agent.allocate(incident, db)
            if allocated:
                incident.status = IncidentStatus.RESPONDING
                db.commit()

        # Step 5: Communication — generate alert
        alert = await comm_agent.generate_alert(incident, db)

        # Step 6: Broadcast via WebSocket
        incident_data = {
            "id": incident.id,
            "title": incident.title,
            "description": incident.description,
            "disaster_type": incident.disaster_type,
            "severity": incident.severity,
            "status": incident.status,
            "latitude": incident.latitude,
            "longitude": incident.longitude,
            "location_name": incident.location_name,
            "source": incident.source,
            "affected_population": incident.affected_population,
            "ai_summary": incident.ai_summary,
            "created_at": str(incident.created_at),
        }

        await ws_manager.broadcast_all("new_incident", incident_data)
        await ws_manager.broadcast_all("new_alert", {
            "id": alert.id,
            "incident_id": alert.incident_id,
            "title": alert.title,
            "message": alert.message,
            "severity": alert.severity,
            "alert_type": alert.alert_type,
            "created_at": str(alert.created_at),
        })

        if allocated:
            await ws_manager.broadcast_all("resource_update", {
                "incident_id": incident.id,
                "allocated": allocated,
            })

        logger.info(f"✅ Pipeline complete for Incident #{incident.id}")
        return incident_data


orchestrator = OrchestratorAgent()
