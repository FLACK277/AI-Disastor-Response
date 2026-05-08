"""
Communication Agent
Generates clear incident alerts without pretending unverified reports are confirmed.
"""

import logging

from sqlalchemy.orm import Session

from backend.llm_client import llm_client
from backend.models import AlertDB, IncidentDB

logger = logging.getLogger(__name__)


def build_fallback_alert_message(incident: IncidentDB) -> str:
    """Create a clear non-AI alert when the LLM cannot respond."""
    location = incident.location_name or "location not confirmed"
    summary = incident.ai_summary or incident.description
    return (
        f"Unverified emergency report: {incident.title}. "
        f"Location: {location}. Severity level: {incident.severity}/5. "
        f"Summary: {summary[:240]}. "
        "Verify details with local authorities before public action. Responders should assess "
        "the scene, protect life safety, and update incident status after confirmation."
    )


class CommunicationAgent:
    """Generates alerts and manages notification dispatch."""

    def __init__(self):
        logger.info("Communication Agent initialized")

    async def generate_alert(self, incident: IncidentDB, db: Session) -> AlertDB:
        """Generate an alert for an incident."""
        incident_data = {
            "title": incident.title,
            "description": incident.description,
            "disaster_type": incident.disaster_type,
            "severity": incident.severity,
            "location": incident.location_name,
            "affected_population": incident.affected_population,
            "verification_status": incident.status,
            "source": incident.source,
        }

        alert_message = llm_client.generate_alert(incident_data)
        if not alert_message:
            alert_message = build_fallback_alert_message(incident)

        severity_labels = {1: "LOW", 2: "MODERATE", 3: "HIGH", 4: "SEVERE", 5: "CRITICAL"}
        source_label = "SIMULATED" if incident.source == "mock_feed" else "UNVERIFIED"
        alert_title = f"{source_label} {severity_labels.get(incident.severity, 'ALERT')}: {incident.title}"

        alert = AlertDB(
            incident_id=incident.id,
            title=alert_title,
            message=alert_message,
            severity=incident.severity,
            alert_type="evacuation" if incident.severity >= 4 else "general",
            target_role=None,
        )
        db.add(alert)
        db.commit()
        db.refresh(alert)

        logger.info(f"Alert generated for Incident #{incident.id}: {alert_title}")
        return alert

    async def generate_deployment_message(self, incident_data: dict, resource_data: dict) -> str:
        """Generate a deployment engagement message."""
        message = llm_client.generate_engagement_message(incident_data, resource_data)
        if message:
            return message
        return (
            f"Resource {resource_data.get('name', 'team')} assigned to incident "
            f"{incident_data.get('id', incident_data.get('title', 'unknown'))}. "
            "Proceed according to dispatch protocol and confirm status on arrival."
        )


comm_agent = CommunicationAgent()
