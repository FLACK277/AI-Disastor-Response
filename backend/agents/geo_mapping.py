"""
Geo Mapping Agent
Geocodes location strings to lat/lng and leaves unknown locations unset.
"""

import logging
import math
from typing import Optional, Tuple

from geopy.exc import GeocoderServiceError, GeocoderTimedOut
from geopy.geocoders import Nominatim

from backend.config import settings

logger = logging.getLogger(__name__)

# Fallback coordinates for known Indian cities/states. These are only used when
# the reported location explicitly contains the listed place name.
CITY_COORDS = {
    "delhi": (28.6139, 77.2090),
    "new delhi": (28.6139, 77.2090),
    "mumbai": (19.0760, 72.8777),
    "kolkata": (22.5726, 88.3639),
    "chennai": (13.0827, 80.2707),
    "bangalore": (12.9716, 77.5946),
    "bengaluru": (12.9716, 77.5946),
    "hyderabad": (17.3850, 78.4867),
    "ahmedabad": (23.0225, 72.5714),
    "pune": (18.5204, 73.8567),
    "jaipur": (26.9124, 75.7873),
    "lucknow": (26.8467, 80.9462),
    "bhopal": (23.2599, 77.4126),
    "patna": (25.6093, 85.1376),
    "indore": (22.7196, 75.8577),
    "shimla": (31.1048, 77.1734),
    "chandigarh": (30.7333, 76.7794),
    "guwahati": (26.1445, 91.7362),
    "bhubaneswar": (20.2961, 85.8245),
    "thiruvananthapuram": (8.5241, 76.9366),
    "kochi": (9.9312, 76.2673),
    "vizag": (17.6868, 83.2185),
    "visakhapatnam": (17.6868, 83.2185),
    "uttarakhand": (30.0668, 79.0193),
    "kedarnath": (30.7352, 79.0669),
    "assam": (26.2006, 92.9376),
    "rajasthan": (27.0238, 74.2179),
    "odisha": (20.9517, 85.0985),
}


class GeoMappingAgent:
    """Geocodes locations and provides spatial analysis."""

    def __init__(self):
        self.geocoder = None
        logger.info("Geo Mapping Agent initialized in local-only mode")

    async def geocode(self, location_str: str) -> Tuple[Optional[float], Optional[float]]:
        """Convert a location string to (latitude, longitude)."""
        if not location_str or location_str.strip().lower() in {"unknown", "not specified", "n/a"}:
            return None, None

        key = location_str.strip().lower()
        for city, coords in CITY_COORDS.items():
            if city in key:
                logger.info(f"Geocoded '{location_str}' via fallback -> {coords}")
                return coords

        logger.warning(f"Could not geocode '{location_str}', leaving coordinates unknown")
        return None, None

    @staticmethod
    def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate distance in km between two points."""
        radius_km = 6371.0
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(math.radians(lat1))
            * math.cos(math.radians(lat2))
            * math.sin(dlon / 2) ** 2
        )
        return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    async def find_nearest(self, lat: float, lng: float, locations: list, top_k: int = 5) -> list:
        """Find nearest locations from a list of dicts with latitude/longitude."""
        with_dist = []
        for loc in locations:
            d = self.haversine_distance(lat, lng, loc["latitude"], loc["longitude"])
            with_dist.append({**loc, "distance_km": round(d, 2)})
        with_dist.sort(key=lambda x: x["distance_km"])
        return with_dist[:top_k]


geo_agent = GeoMappingAgent()
