"""
Resource Allocation Agent
Assigns nearest available resources to incidents based on proximity and type.
"""

import logging
from typing import List, Optional
from sqlalchemy.orm import Session
from backend.models import ResourceDB, IncidentDB, ResourceStatus
from backend.agents.geo_mapping import geo_agent

logger = logging.getLogger(__name__)

# Maps disaster types to prioritized resource types
DISASTER_RESOURCE_MAP = {
    "earthquake": ["ndrf_team", "medical_unit", "ambulance", "helicopter", "volunteer_group"],
    "flood": ["rescue_boat", "ndrf_team", "helicopter", "ambulance", "volunteer_group"],
    "fire": ["fire_truck", "ambulance", "medical_unit", "volunteer_group"],
    "cyclone": ["ndrf_team", "rescue_boat", "helicopter", "ambulance", "medical_unit"],
    "landslide": ["ndrf_team", "helicopter", "ambulance", "medical_unit"],
    "tsunami": ["rescue_boat", "ndrf_team", "helicopter", "ambulance"],
    "industrial": ["fire_truck", "ambulance", "medical_unit", "ndrf_team"],
    "other": ["ndrf_team", "ambulance", "medical_unit", "volunteer_group"],
}


class ResourceAllocationAgent:
    """Greedy proximity-based resource allocation."""

    def __init__(self):
        logger.info("✅ Resource Allocation Agent initialized")

    async def allocate(self, incident: IncidentDB, db: Session, max_resources: int = 3) -> List[dict]:
        """
        Allocate nearest available resources to an incident.
        Returns list of allocated resource dicts.
        """
        if not incident.latitude or not incident.longitude:
            logger.warning(f"Incident {incident.id} has no coordinates, skipping allocation")
            return []

        disaster_type = incident.disaster_type or "other"
        priority_types = DISASTER_RESOURCE_MAP.get(disaster_type, DISASTER_RESOURCE_MAP["other"])

        available = db.query(ResourceDB).filter(
            ResourceDB.status == ResourceStatus.AVAILABLE
        ).all()

        if not available:
            logger.warning("No available resources for allocation")
            return []

        # Convert to dicts for distance calculation
        resource_dicts = [
            {
                "id": r.id, "name": r.name, "resource_type": r.resource_type,
                "latitude": r.latitude, "longitude": r.longitude,
                "capacity": r.capacity, "contact": r.contact,
            }
            for r in available
        ]

        # Find nearest resources
        nearest = await geo_agent.find_nearest(
            incident.latitude, incident.longitude, resource_dicts, top_k=10
        )

        # Prioritize by disaster-specific resource type ordering
        def priority_sort(r):
            try:
                return priority_types.index(r["resource_type"])
            except ValueError:
                return len(priority_types)

        nearest.sort(key=lambda r: (priority_sort(r), r["distance_km"]))

        # Allocate top N
        allocated = []
        for res in nearest[:max_resources]:
            db_resource = db.query(ResourceDB).filter(ResourceDB.id == res["id"]).first()
            if db_resource and db_resource.status == ResourceStatus.AVAILABLE:
                db_resource.status = ResourceStatus.EN_ROUTE
                db_resource.assigned_incident_id = incident.id
                db.commit()
                allocated.append({
                    **res,
                    "status": "en_route",
                    "assigned_incident_id": incident.id,
                })
                logger.info(f"🚀 Deployed {res['name']} → Incident #{incident.id} ({res['distance_km']}km)")

        return allocated


resource_agent = ResourceAllocationAgent()
