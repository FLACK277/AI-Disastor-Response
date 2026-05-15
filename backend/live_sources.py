"""
Live incident sources for the Uttarakhand-focused dashboard.

Aggregates REAL-TIME data from multiple free, no-API-key sources:
  1. USGS Earthquake Hazards Program  — global seismic events (GeoJSON)
  2. GDACS (UN)                       — global disaster alerts  (GeoJSON)
  3. Open-Meteo                       — severe weather warnings  (JSON)
  4. Bhudev / IIT Roorkee             — Uttarakhand local EEW   (HTML scrape)

All feeds are cached in-memory with a configurable TTL so the dashboard
stays responsive without hammering upstream APIs on every page load.
"""

from __future__ import annotations

import logging
import re
import time
import subprocess
import httpx
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from backend.config import settings

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

# South-Asia bounding box for USGS (India + neighbours)
USGS_URL = (
    "https://earthquake.usgs.gov/fdsnws/event/1/query"
    "?format=geojson&limit=20&orderby=time"
    "&minlatitude=6&maxlatitude=38"
    "&minlongitude=68&maxlongitude=98"
)

# GDACS — earthquakes, floods, cyclones affecting India (last 30 days)
GDACS_URL = (
    "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
    "?alertlevel=green;orange;red"
    "&eventlist=EQ,TC,FL"
    "&country=IND"
)

# Bhudev — Uttarakhand local EEW
BHUDEV_URL = "https://bhudev.uk/"

# Open-Meteo — weather for key Uttarakhand districts
UTTARAKHAND_WEATHER_POINTS = [
    {"name": "Dehradun", "lat": 30.3165, "lon": 78.0322},
    {"name": "Chamoli", "lat": 30.4090, "lon": 79.3200},
    {"name": "Pithoragarh", "lat": 29.5829, "lon": 80.2182},
    {"name": "Nainital", "lat": 29.3919, "lon": 79.4542},
    {"name": "Uttarkashi", "lat": 30.7268, "lon": 78.4354},
    {"name": "Rudraprayag", "lat": 30.2850, "lon": 78.9820},
]

REGION_COORDS = {
    "chamoli": (30.4090, 79.3200),
    "pithoragarh": (29.5829, 80.2182),
    "bageshwar": (29.8374, 79.7714),
    "pauri garhwal": (30.1524, 78.7771),
    "pauri": (30.1524, 78.7771),
    "dehradun": (30.3165, 78.0322),
    "uttarkashi": (30.7268, 78.4354),
    "rudraprayag": (30.2850, 78.9820),
    "tehri garhwal": (30.3782, 78.4804),
    "tehri": (30.3782, 78.4804),
    "almora": (29.5892, 79.6467),
    "nainital": (29.3919, 79.4542),
    "nepal": (28.3949, 81.0000),
}

# WMO weather codes that indicate severe/dangerous conditions
SEVERE_WEATHER_CODES = {
    55: "Heavy drizzle",
    57: "Freezing drizzle",
    65: "Heavy rain",
    67: "Freezing rain",
    75: "Heavy snowfall",
    77: "Snow grains",
    82: "Violent rain showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail",
    99: "Severe thunderstorm with hail",
}

# Default cache TTL (seconds)
DEFAULT_CACHE_TTL = 300  # 5 minutes
DEFAULT_MAX_EVENT_AGE_HOURS = 24

HTTP_TIMEOUT = 20  # seconds


# ─── Data Structures ─────────────────────────────────────────────────────────

@dataclass
class LiveFeedBundle:
    incidents: list[dict] = field(default_factory=list)
    alerts: list[dict] = field(default_factory=list)


@dataclass
class _CacheEntry:
    data: LiveFeedBundle
    fetched_at: float  # time.time()
    source_status: dict = field(default_factory=dict)


# ─── Main Aggregator ─────────────────────────────────────────────────────────

class RealTimeLiveSource:
    """Aggregates multiple real-time disaster feeds with TTL caching."""

    def __init__(self, cache_ttl: int = DEFAULT_CACHE_TTL):
        self._cache_ttl = cache_ttl
        self._cache: _CacheEntry | None = None

    # ── Public API ────────────────────────────────────────────────────────

    def fetch(self, limit: int = 30) -> LiveFeedBundle:
        """Return cached or freshly-fetched live incidents + alerts."""
        now = time.time()
        if self._cache and (now - self._cache.fetched_at) < self._cache_ttl:
            bundle = self._cache.data
            return LiveFeedBundle(
                incidents=bundle.incidents[:limit],
                alerts=bundle.alerts[:limit],
            )

        bundle = self._fetch_all()
        self._cache = _CacheEntry(data=bundle, fetched_at=now, source_status=self._last_status)
        return LiveFeedBundle(
            incidents=bundle.incidents[:limit],
            alerts=bundle.alerts[:limit],
        )

    @property
    def source_status(self) -> dict:
        """Report which sources are live and when they were last fetched."""
        if self._cache:
            return {
                "last_fetched": datetime.fromtimestamp(self._cache.fetched_at, tz=timezone.utc).isoformat(),
                "cache_ttl_seconds": self._cache_ttl,
                "sources": self._cache.source_status,
            }
        return {"last_fetched": None, "sources": {}}

    # ── Internal: aggregate all sources ───────────────────────────────────

    def _fetch_all(self) -> LiveFeedBundle:
        all_incidents: list[dict] = []
        all_alerts: list[dict] = []
        self._last_status: dict = {}

        # 1. USGS Earthquakes
        try:
            usgs = self._fetch_usgs()
            all_incidents.extend(usgs.incidents)
            all_alerts.extend(usgs.alerts)
            self._last_status["usgs"] = {"ok": True, "count": len(usgs.incidents)}
        except Exception as e:
            logger.error(f"USGS fetch failed: {e}")
            self._last_status["usgs"] = {"ok": False, "error": str(e)}

        # 2. GDACS Global Disasters
        try:
            gdacs = self._fetch_gdacs()
            all_incidents.extend(gdacs.incidents)
            all_alerts.extend(gdacs.alerts)
            self._last_status["gdacs"] = {"ok": True, "count": len(gdacs.incidents)}
        except Exception as e:
            logger.error(f"GDACS fetch failed: {e}")
            self._last_status["gdacs"] = {"ok": False, "error": str(e)}

        # 3. Open-Meteo Severe Weather
        try:
            weather = self._fetch_weather_alerts()
            all_incidents.extend(weather.incidents)
            all_alerts.extend(weather.alerts)
            self._last_status["open_meteo"] = {"ok": True, "count": len(weather.incidents)}
        except Exception as e:
            logger.error(f"Open-Meteo fetch failed: {e}")
            self._last_status["open_meteo"] = {"ok": False, "error": str(e)}

        # 4. Bhudev local EEW
        try:
            bhudev = self._fetch_bhudev()
            all_incidents.extend(bhudev.incidents)
            all_alerts.extend(bhudev.alerts)
            self._last_status["bhudev"] = {"ok": True, "count": len(bhudev.incidents)}
        except Exception as e:
            logger.error(f"Bhudev fetch failed: {e}")
            self._last_status["bhudev"] = {"ok": False, "error": str(e)}

        all_incidents = self._annotate_age(all_incidents)
        all_alerts = self._annotate_age(all_alerts)

        # Sort everything newest-first
        all_incidents.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        all_alerts.sort(key=lambda x: x.get("created_at", ""), reverse=True)

        logger.info(
            f"📡 Live feed: {len(all_incidents)} incidents, {len(all_alerts)} alerts "
            f"from {sum(1 for s in self._last_status.values() if s.get('ok'))} sources"
        )
        return LiveFeedBundle(incidents=all_incidents, alerts=all_alerts)

    # ── Source 1: USGS Earthquake Hazards Program ─────────────────────────

    def _fetch_usgs(self) -> LiveFeedBundle:
        """Fetch recent earthquakes from USGS FDSN web-service (GeoJSON)."""
        data = self._http_get_json(USGS_URL)
        incidents: list[dict] = []

        for feature in data.get("features", []):
            props = feature.get("properties", {})
            coords = feature.get("geometry", {}).get("coordinates", [None, None, None])
            lng, lat = coords[0], coords[1]
            depth = coords[2] if len(coords) > 2 else None
            mag = props.get("mag", 0)
            place = props.get("place", "Unknown")
            event_time = props.get("time")

            if event_time:
                created_at = datetime.fromtimestamp(event_time / 1000, tz=timezone.utc).isoformat()
            else:
                created_at = datetime.now(tz=timezone.utc).isoformat()

            incident = {
                "id": self._stable_id("usgs", props.get("code", place), str(event_time)),
                "title": props.get("title", f"M{mag} Earthquake near {place}"),
                "description": (
                    f"USGS detected earthquake: magnitude {mag}, depth {depth}km. "
                    f"Location: {place}. Source: USGS Earthquake Hazards Program."
                ),
                "disaster_type": "earthquake",
                "severity": self._magnitude_to_severity(mag),
                "status": "reported",
                "latitude": lat,
                "longitude": lng,
                "location_name": place,
                "reported_by": "USGS",
                "source": "live_usgs",
                "affected_population": 0,
                "ai_summary": (
                    f"Real-time earthquake M{mag} detected at {place}. "
                    f"Depth: {depth}km. Data from USGS."
                ),
                "created_at": created_at,
            }
            incidents.append(incident)

        alerts = [self._incident_to_alert(inc, "USGS EARTHQUAKE") for inc in incidents]
        return LiveFeedBundle(incidents=incidents, alerts=alerts)

    # ── Source 2: GDACS — Global Disaster Alerts ──────────────────────────

    def _fetch_gdacs(self) -> LiveFeedBundle:
        """Fetch recent disaster events from GDACS GeoJSON API."""
        # Build dynamic date range: last 30 days
        now = datetime.now(tz=timezone.utc)
        from_date = now.replace(day=1).strftime("%Y-%m-%d") if now.day < 30 else (
            now.replace(month=now.month - 1 if now.month > 1 else 12, year=now.year if now.month > 1 else now.year - 1)
        ).strftime("%Y-%m-%d")
        to_date = now.strftime("%Y-%m-%d")
        url = f"{GDACS_URL}&fromDate={from_date}&toDate={to_date}"

        data = self._http_get_json(url)
        incidents: list[dict] = []
        event_type_map = {"EQ": "earthquake", "FL": "flood", "TC": "cyclone", "VO": "other"}

        for feature in data.get("features", []):
            props = feature.get("properties", {})
            coords = feature.get("geometry", {}).get("coordinates", [None, None])
            lng, lat = coords[0], coords[1] if len(coords) >= 2 else (None, None)

            from_date_str = props.get("fromdate", "")
            alert_level = props.get("alertlevel", "Green")
            severity_data = props.get("severitydata", {})
            mag = severity_data.get("severity", 0)
            event_type = event_type_map.get(props.get("eventtype", ""), "other")
            country = props.get("country", "Unknown")
            name = props.get("name", f"Disaster in {country}")

            # Map GDACS alert level to severity
            severity = {"Green": 2, "Orange": 4, "Red": 5}.get(alert_level, 1)
            # For earthquakes, also consider magnitude
            if event_type == "earthquake" and mag:
                severity = max(severity, self._magnitude_to_severity(float(mag)))

            created_at = from_date_str if from_date_str else datetime.now(tz=timezone.utc).isoformat()
            # Ensure ISO format
            if created_at and not created_at.endswith("Z") and "+" not in created_at:
                try:
                    created_at = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%S").replace(
                        tzinfo=timezone.utc
                    ).isoformat()
                except ValueError:
                    created_at = datetime.now(tz=timezone.utc).isoformat()

            incident = {
                "id": self._stable_id("gdacs", str(props.get("eventid", "")), from_date_str),
                "title": name,
                "description": (
                    f"{props.get('htmldescription', name)}. "
                    f"Alert level: {alert_level}. {severity_data.get('severitytext', '')}. "
                    f"Source: GDACS / UN."
                ),
                "disaster_type": event_type,
                "severity": severity,
                "status": "reported",
                "latitude": lat,
                "longitude": lng,
                "location_name": country,
                "reported_by": "GDACS / UN",
                "source": "live_gdacs",
                "affected_population": 0,
                "ai_summary": (
                    f"GDACS {alert_level} alert: {name}. "
                    f"{severity_data.get('severitytext', '')}."
                ),
                "created_at": created_at,
            }
            incidents.append(incident)

        alerts = [self._incident_to_alert(inc, "GDACS ALERT") for inc in incidents]
        return LiveFeedBundle(incidents=incidents, alerts=alerts)

    # ── Source 3: Open-Meteo — Severe Weather ─────────────────────────────

    def _fetch_weather_alerts(self) -> LiveFeedBundle:
        """Check current weather conditions for Uttarakhand districts; generate
        incidents only for genuinely severe weather codes."""
        incidents: list[dict] = []

        for point in UTTARAKHAND_WEATHER_POINTS:
            try:
                url = (
                    f"https://api.open-meteo.com/v1/forecast"
                    f"?latitude={point['lat']}&longitude={point['lon']}"
                    f"&current=temperature_2m,rain,weather_code,wind_speed_10m"
                    f"&daily=weather_code,rain_sum"
                    f"&timezone=Asia/Kolkata&forecast_days=1"
                )
                data = self._http_get_json(url)
                current = data.get("current", {})
                weather_code = current.get("weather_code", 0)

                if weather_code not in SEVERE_WEATHER_CODES:
                    continue

                description = SEVERE_WEATHER_CODES[weather_code]
                rain = current.get("rain", 0)
                wind = current.get("wind_speed_10m", 0)
                temp = current.get("temperature_2m", 0)
                current_time = current.get("time", datetime.now(tz=timezone.utc).isoformat())

                # Determine severity from weather code
                if weather_code >= 95:
                    severity = 4
                elif weather_code >= 75:
                    severity = 3
                elif weather_code >= 65:
                    severity = 3
                else:
                    severity = 2

                # Boost severity for extreme rain / wind
                if rain > 50:
                    severity = min(severity + 1, 5)
                if wind > 80:
                    severity = min(severity + 1, 5)

                incident = {
                    "id": self._stable_id("weather", point["name"], current_time),
                    "title": f"⚠️ {description} in {point['name']}",
                    "description": (
                        f"Severe weather in {point['name']}, Uttarakhand: {description}. "
                        f"Temperature: {temp}°C, Rain: {rain}mm, Wind: {wind}km/h. "
                        f"Source: Open-Meteo."
                    ),
                    "disaster_type": "flood" if rain > 30 else "cyclone" if wind > 60 else "other",
                    "severity": severity,
                    "status": "reported",
                    "latitude": point["lat"],
                    "longitude": point["lon"],
                    "location_name": f"{point['name']}, Uttarakhand",
                    "reported_by": "Open-Meteo",
                    "source": "live_weather",
                    "affected_population": 0,
                    "ai_summary": (
                        f"Current severe weather: {description} at {point['name']}. "
                        f"Temp {temp}°C, Rain {rain}mm, Wind {wind}km/h."
                    ),
                    "created_at": current_time if "T" in str(current_time) else datetime.now(tz=timezone.utc).isoformat(),
                }
                incidents.append(incident)

            except Exception as e:
                logger.warning(f"Weather check failed for {point['name']}: {e}")

        alerts = [self._incident_to_alert(inc, "WEATHER ALERT") for inc in incidents]
        return LiveFeedBundle(incidents=incidents, alerts=alerts)

    # ── Source 4: Bhudev / IIT Roorkee ────────────────────────────────────

    def _fetch_bhudev(self) -> LiveFeedBundle:
        """Read recent Uttarakhand earthquakes from the Bhudev page."""
        html = self._fetch_html_via_powershell(BHUDEV_URL)
        if not html:
            return LiveFeedBundle()

        text = re.sub(r"<[^>]+>", "\n", html)
        lines = [line.strip() for line in text.splitlines() if line.strip()]

        incidents: list[dict] = []
        for idx, line in enumerate(lines):
            if not line.startswith("Region: "):
                continue

            match = re.match(
                r"Region:\s*(?P<region>[^|]+)\|\s*Magnitude:\s*(?P<magnitude>[0-9.]+)\s*\|\s*Depth:\s*(?P<depth>[0-9.]+)",
                line,
            )
            if not match:
                continue

            timestamp = None
            for offset in range(1, 5):
                if idx + offset >= len(lines):
                    break
                candidate = lines[idx + offset]
                if re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", candidate):
                    timestamp = candidate
                    break
            if not timestamp:
                continue

            region = match.group("region").strip()
            magnitude = float(match.group("magnitude"))
            depth_km = float(match.group("depth"))
            created_at = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
            lat, lng = self._lookup_coords(region)

            incidents.append({
                "id": self._stable_id("bhudev", region, timestamp),
                "title": f"Earthquake near {region}",
                "description": (
                    f"Bhudev / IIT Roorkee EEW detection: Magnitude {magnitude}, depth {depth_km}km. "
                    f"Region: {region}, Uttarakhand."
                ),
                "disaster_type": "earthquake",
                "severity": self._magnitude_to_severity(magnitude),
                "status": "reported",
                "latitude": lat,
                "longitude": lng,
                "location_name": region,
                "reported_by": "Bhudev / IIT Roorkee",
                "source": "live_bhudev",
                "affected_population": 0,
                "ai_summary": (
                    f"Local earthquake near {region}: M{magnitude}, depth {depth_km}km. "
                    f"Data from IIT Roorkee EEW network."
                ),
                "created_at": created_at.isoformat(),
            })

            if len(incidents) >= 10:
                break

        alerts = [self._incident_to_alert(inc, "BHUDEV EEW") for inc in incidents]
        return LiveFeedBundle(incidents=incidents, alerts=alerts)

    # ── HTTP helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _http_get_json(url: str) -> dict:
        """Synchronous HTTP GET returning JSON. Uses httpx for reliability."""
        with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.json()

    @staticmethod
    def _fetch_html_via_powershell(url: str) -> str:
        """Fallback for Bhudev: use PowerShell to avoid local SSL issues."""
        command = [
            "powershell", "-NoProfile", "-Command",
            f"Invoke-WebRequest -Uri '{url}' -UseBasicParsing | Select-Object -ExpandProperty Content",
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=25, check=True)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.error(f"PowerShell fetch failed for {url}: {e}")
            return ""
        return result.stdout

    # ── Utilities ─────────────────────────────────────────────────────────

    @staticmethod
    def _stable_id(source: str, key1: str, key2: str) -> int:
        raw = f"{source}:{key1}:{key2}"
        return abs(hash(raw)) % 900_000_000 + 100_000_000

    @staticmethod
    def _parse_created_at(value: object) -> datetime | None:
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, str) and value:
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        else:
            return None

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def _is_old(self, item: dict) -> bool:
        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=DEFAULT_MAX_EVENT_AGE_HOURS)
        created_at = self._parse_created_at(item.get("created_at"))
        return created_at is not None and created_at < cutoff

    def _annotate_age(self, items: list[dict]) -> list[dict]:
        for item in items:
            is_old = self._is_old(item)
            item["is_old"] = is_old
            item["data_age"] = "Old" if is_old else "Current"
        return items

    @staticmethod
    def _magnitude_to_severity(magnitude: float) -> int:
        if magnitude >= 6.0:
            return 5
        if magnitude >= 5.0:
            return 4
        if magnitude >= 4.0:
            return 3
        if magnitude >= 3.0:
            return 2
        return 1

    @staticmethod
    def _lookup_coords(region: str) -> tuple[float | None, float | None]:
        return REGION_COORDS.get(region.strip().lower(), (None, None))

    @staticmethod
    def _incident_to_alert(incident: dict, prefix: str = "LIVE") -> dict:
        return {
            "id": incident["id"] + 1,
            "incident_id": incident["id"],
            "title": f"{prefix}: {incident['location_name']}",
            "message": incident["description"],
            "severity": incident["severity"],
            "alert_type": "live_feed",
            "created_at": incident["created_at"],
        }


# ── Module-level singleton ────────────────────────────────────────────────────

live_source = RealTimeLiveSource(cache_ttl=settings.LIVE_CACHE_TTL_SECONDS)
