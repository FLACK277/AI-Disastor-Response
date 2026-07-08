"""
Geo Mapping Agent
Geocodes location strings to lat/lng and leaves unknown locations unset.
"""

import logging
import math
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Fallback coordinates for Uttarakhand places. These are only used when
# the reported location explicitly contains the listed place name.
CITY_COORDS = {
    "uttarakhand": (30.0668, 79.0193),
    "dehradun": (30.3165, 78.0322),
    "rishikesh": (30.0869, 78.2676),
    "haridwar": (29.9457, 78.1642),
    "haldwani": (29.2183, 79.5130),
    "nainital": (29.3919, 79.4542),
    "almora": (29.5892, 79.6467),
    "bageshwar": (29.8374, 79.7714),
    "pithoragarh": (29.5829, 80.2182),
    "champawat": (29.3364, 80.0910),
    "uttarkashi": (30.7268, 78.4354),
    "chamoli": (30.4090, 79.3200),
    "rudraprayag": (30.2850, 78.9820),
    "pauri": (30.1524, 78.7771),
    "pauri garhwal": (30.1524, 78.7771),
    "tehri": (30.3782, 78.4804),
    "tehri garhwal": (30.3782, 78.4804),
    "kedarnath": (30.7352, 79.0669),
    "badrinath": (30.7433, 79.4938),
    "joshimath": (30.5553, 79.5644),
    "gauchar": (30.2915, 79.2131),
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
