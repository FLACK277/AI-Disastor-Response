"""
AI Disaster Response Coordinator — Data Models
SQLAlchemy ORM models + Pydantic schemas for API validation.
"""

import enum
from datetime import datetime
from typing import Optional, List
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, ForeignKey
from sqlalchemy.sql import func
from pydantic import BaseModel
from backend.database import Base


# ─── Enums ────────────────────────────────────────────────────────────────────

class UserRole(str, enum.Enum):
    AUTHORITY = "authority"
    NGO = "ngo"
    CIVILIAN = "civilian"


class DisasterType(str, enum.Enum):
    EARTHQUAKE = "earthquake"
    FLOOD = "flood"
    FIRE = "fire"
    CYCLONE = "cyclone"
    LANDSLIDE = "landslide"
    TSUNAMI = "tsunami"
    INDUSTRIAL = "industrial"
    OTHER = "other"


class IncidentStatus(str, enum.Enum):
    REPORTED = "reported"
    VERIFIED = "verified"
    RESPONDING = "responding"
    CONTAINED = "contained"
    RESOLVED = "resolved"


class ResourceStatus(str, enum.Enum):
    AVAILABLE = "available"
    DEPLOYED = "deployed"
    EN_ROUTE = "en_route"
    MAINTENANCE = "maintenance"


class ResourceType(str, enum.Enum):
    NDRF_TEAM = "ndrf_team"
    AMBULANCE = "ambulance"
    FIRE_TRUCK = "fire_truck"
    RESCUE_BOAT = "rescue_boat"
    HELICOPTER = "helicopter"
    MEDICAL_UNIT = "medical_unit"
    VOLUNTEER_GROUP = "volunteer_group"


# ─── SQLAlchemy ORM Models ────────────────────────────────────────────────────

class UserDB(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    role = Column(String, default=UserRole.CIVILIAN)
    full_name = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class IncidentDB(Base):
    __tablename__ = "incidents"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    description = Column(Text)
    disaster_type = Column(String)
    severity = Column(Integer, default=1)
    status = Column(String, default=IncidentStatus.REPORTED)
    latitude = Column(Float)
    longitude = Column(Float)
    location_name = Column(String)
    reported_by = Column(String, nullable=True)
    source = Column(String, default="user")
    affected_population = Column(Integer, default=0)
    ai_summary = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class ResourceDB(Base):
    __tablename__ = "resources"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    resource_type = Column(String)
    status = Column(String, default=ResourceStatus.AVAILABLE)
    latitude = Column(Float)
    longitude = Column(Float)
    capacity = Column(Integer, default=1)
    assigned_incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=True)
    contact = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class AlertDB(Base):
    __tablename__ = "alerts"
    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=True)
    title = Column(String)
    message = Column(Text)
    severity = Column(Integer, default=1)
    alert_type = Column(String, default="general")
    target_role = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


# ─── Pydantic Schemas ─────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    username: str
    email: str
    password: str
    role: UserRole = UserRole.CIVILIAN
    full_name: Optional[str] = None


class UserLogin(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    role: str
    full_name: Optional[str] = None
    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class IncidentCreate(BaseModel):
    title: str
    description: str
    disaster_type: Optional[str] = None
    severity: Optional[int] = None
    location_name: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class IncidentResponse(BaseModel):
    id: int
    title: str
    description: str
    disaster_type: Optional[str] = None
    severity: int
    status: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_name: str
    reported_by: Optional[str] = None
    source: str
    affected_population: int
    ai_summary: Optional[str] = None
    created_at: datetime
    data_age: str = "Current"
    is_old: bool = False
    model_config = {"from_attributes": True}


class ResourceResponse(BaseModel):
    id: int
    name: str
    resource_type: str
    status: str
    latitude: float
    longitude: float
    capacity: int
    assigned_incident_id: Optional[int] = None
    contact: Optional[str] = None
    model_config = {"from_attributes": True}


class AlertResponse(BaseModel):
    id: int
    incident_id: Optional[int] = None
    title: str
    message: str
    severity: int
    alert_type: str
    created_at: datetime
    data_age: str = "Current"
    is_old: bool = False
    model_config = {"from_attributes": True}


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    response: str
    sources: List[str] = []


class StatsResponse(BaseModel):
    total_incidents: int
    active_incidents: int
    resolved_incidents: int
    total_resources: int
    deployed_resources: int
    total_alerts: int
    severity_distribution: dict
    type_distribution: dict
    recent_trend: List[dict]
