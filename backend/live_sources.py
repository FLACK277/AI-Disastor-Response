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

import hashlib
import html
import logging
import re
import time
import subprocess
import unicodedata
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus, urlparse

import httpx
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from backend.config import settings

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

# Uttarakhand bounding box for USGS earthquake queries.
USGS_URL = (
    "https://earthquake.usgs.gov/fdsnws/event/1/query"
    "?format=geojson&limit=30&orderby=time"
    "&minlatitude=28.7&maxlatitude=31.6"
    "&minlongitude=77.5&maxlongitude=81.2"
    "&minmagnitude=1.5"
)

# GDACS — earthquakes, floods, cyclones affecting India (last 30 days)
GDACS_URL = (
    "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
    "?alertlevel=green;orange;red"
    "&eventlist=EQ,TC,FL,VO,DR"
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

UTTARAKHAND_KEYWORDS = {
    "uttarakhand",
    "dehradun",
    "haridwar",
    "nainital",
    "almora",
    "bageshwar",
    "chamoli",
    "champawat",
    "pauri",
    "garhwal",
    "pithoragarh",
    "rudraprayag",
    "tehri",
    "udham singh nagar",
    "udhamsingh nagar",
    "uttarkashi",
    "rishikesh",
    "haldwani",
    "kedarnath",
    "badrinath",
    "joshimath",
}

DISASTER_KEYWORD_TYPES = {
    "earthquake": "earthquake",
    "tremor": "earthquake",
    "flood": "flood",
    "flash flood": "flood",
    "cloudburst": "flood",
    "waterlogging": "flood",
    "rainfall": "flood",
    "heavy rain": "flood",
    "landslide": "landslide",
    "rockfall": "landslide",
    "forest fire": "fire",
    "wildfire": "fire",
    "fire": "fire",
    "avalanche": "landslide",
    "glacier": "other",
    "heatwave": "other",
    "heat wave": "other",
    "industrial": "industrial",
    "chemical": "industrial",
    "gas leak": "industrial",
    "red alert": "other",
    "orange alert": "other",
}

TRUSTED_NEWS_SOURCES = {
    "PTI",
    "Press Trust of India",
    "ANI News",
    "The Hindu",
    "Hindustan Times",
    "Indian Express",
    "The Indian Express",
    "Times of India",
    "The Times of India",
    "NDTV",
    "India Today",
    "Business Standard",
    "Deccan Herald",
    "The Economic Times",
    "News18",
    "Down To Earth Magazine",
    "News On AIR",
    "The Statesman",
    "Garhwal Post",
    "Zee News",
    "Daily Pioneer",
    "News24",
    "Uttarakhand News Network",
    "Mid-day",
}

TRUSTED_NEWS_DOMAINS = {
    "aninews.in",
    "thehindu.com",
    "hindustantimes.com",
    "indianexpress.com",
    "timesofindia.indiatimes.com",
    "ndtv.com",
    "indiatoday.in",
    "business-standard.com",
    "deccanherald.com",
    "economictimes.indiatimes.com",
    "news18.com",
    "downtoearth.org.in",
    "newsonair.gov.in",
    "thestatesman.com",
    "garhwalpost.in",
    "zeenews.india.com",
    "dailypioneer.com",
    "news24online.com",
    "uttarakhandnewsnetwork.com",
    "mid-day.com",
}

def _fold_text(value: str) -> str:
    """Aggressively normalize text for source-name comparison.

    Google News RSS frequently returns publisher names containing lookalike
    Unicode characters (smart dashes, NBSPs, curly quotes, fullwidth digits).
    Without folding these, an item with source "Mid\u2013day" will not match
    the trusted entry "Mid-day", and a publisher that legitimately belongs to a
    trusted domain may be silently dropped.
    """
    if not value:
        return ""
    # NFKC folds compatibility characters (fullwidth -> ASCII, etc.).
    value = unicodedata.normalize("NFKC", value)
    # Fold dashes and hyphens to a plain ASCII dash.
    value = re.sub(r"[\u2010-\u2015\u2212]", "-", value)
    # Strip stray punctuation that some publishers append.
    value = re.sub(r"\s+", " ", value.strip()).lower()
    return value


NORMALIZED_TRUSTED_NEWS_SOURCES = {_fold_text(source) for source in TRUSTED_NEWS_SOURCES}

NORMALIZED_TRUSTED_NEWS_DOMAINS = {
    domain.strip().lower().removeprefix("www.").rstrip("/")
    for domain in TRUSTED_NEWS_DOMAINS
}

# Display labels derived from trusted domains (e.g. "zeenews.india.com" -> "zee news").
# Lets a publisher-name match succeed when only the domain is trusted.
_TRUSTED_DOMAIN_LABELS: set[str] = set()
for _d in TRUSTED_NEWS_DOMAINS:
    _label = _d.split(".")[0].replace("-", " ")
    _TRUSTED_DOMAIN_LABELS.add(_label)

NEWS_QUERIES = [
    'Uttarakhand (landslide OR "red alert" OR "orange alert" OR rainfall OR flood OR cloudburst OR earthquake OR "forest fire" OR wildfire OR avalanche OR heatwave OR disaster) when:2d',
]

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
DEFAULT_CACHE_TTL = 60  # 1 minute
RECENT_EVENT_WINDOW_DAYS = 7
DEFAULT_MAX_EVENT_AGE_HOURS = 24 * RECENT_EVENT_WINDOW_DAYS
DEFAULT_NEWS_CUTOFF_HOURS = 36
DEFAULT_NEWS_CACHE_TTL_SECONDS = 300

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
        self._news_cache: _CacheEntry | None = None
        self._news_cache_ttl = max(0, int(getattr(settings, "NEWS_CACHE_TTL_SECONDS", DEFAULT_NEWS_CACHE_TTL_SECONDS)))

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

        # 5. Trusted recent news for very fresh local disaster reports
        try:
            news = self._fetch_recent_news()
            all_incidents.extend(news.incidents)
            all_alerts.extend(news.alerts)
        except Exception as e:
            logger.error(f"Recent news fetch failed: {e}")
            self._last_status["recent_news"] = {"ok": False, "error": str(e)}

        all_incidents = self._dedupe_incidents([item for item in all_incidents if self._is_recent(item)])
        all_alerts = [item for item in all_alerts if self._is_recent(item)]
        all_incidents = self._annotate_age(all_incidents)
        all_alerts = self._annotate_age(all_alerts)

        # Sort everything newest-first
        all_incidents.sort(key=self._sort_key, reverse=True)
        all_alerts.sort(key=self._sort_key, reverse=True)

        logger.info(
            f"📡 Live feed: {len(all_incidents)} incidents, {len(all_alerts)} alerts "
            f"from {sum(1 for s in self._last_status.values() if s.get('ok'))} sources"
        )
        return LiveFeedBundle(incidents=all_incidents, alerts=all_alerts)

    # ── Source 1: USGS Earthquake Hazards Program ─────────────────────────

    def _fetch_usgs(self) -> LiveFeedBundle:
        """Fetch recent earthquakes from USGS FDSN web-service (GeoJSON)."""
        start_time = (datetime.now(tz=timezone.utc) - timedelta(days=RECENT_EVENT_WINDOW_DAYS)).strftime("%Y-%m-%d")
        data = self._http_get_json(f"{USGS_URL}&starttime={start_time}")
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
            if not self._is_recent({"created_at": created_at}):
                continue

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
                "status_marker": "ACTIVE",
                "latitude": lat,
                "longitude": lng,
                "location_name": place,
                "reported_by": "USGS",
                "source": "live_usgs",
                "source_url": props.get("url"),
                "affected_population": 0,
                "ai_summary": (
                    f"Real-time earthquake M{mag} detected at {place}. "
                    f"Depth: {depth}km. Data from USGS."
                ),
                "latest_update": created_at,
                "created_at": created_at,
            }
            incidents.append(incident)

        alerts = [self._incident_to_alert(inc, "USGS EARTHQUAKE") for inc in incidents]
        return LiveFeedBundle(incidents=incidents, alerts=alerts)

    # ── Source 2: GDACS — Global Disaster Alerts ──────────────────────────

    def _fetch_gdacs(self) -> LiveFeedBundle:
        """Fetch recent disaster events from GDACS GeoJSON API."""
        now = datetime.now(tz=timezone.utc)
        from_date = (now - timedelta(days=RECENT_EVENT_WINDOW_DAYS)).strftime("%Y-%m-%d")
        to_date = now.strftime("%Y-%m-%d")
        url = f"{GDACS_URL}&fromDate={from_date}&toDate={to_date}"

        data = self._http_get_json(url)
        incidents: list[dict] = []
        event_type_map = {"EQ": "earthquake", "FL": "flood", "TC": "cyclone", "VO": "other", "DR": "other"}

        for feature in data.get("features", []):
            props = feature.get("properties", {})
            coords = feature.get("geometry", {}).get("coordinates", [None, None])
            lng = coords[0] if len(coords) >= 1 else None
            lat = coords[1] if len(coords) >= 2 else None

            from_date_str = props.get("fromdate", "")
            alert_level = props.get("alertlevel", "Green")
            severity_data = props.get("severitydata", {})
            mag = severity_data.get("severity", 0)
            event_type = event_type_map.get(props.get("eventtype", ""), "other")
            country = props.get("country", "Unknown")
            name = props.get("name", f"Disaster in {country}")
            description_text = f"{name} {country} {props.get('htmldescription', '')}"
            if not self._is_uttarakhand_item(description_text, lat, lng):
                continue

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
            if not self._is_recent({"created_at": created_at}):
                continue

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
                "status_marker": "ACTIVE" if alert_level in {"Green", "Orange"} else "ESCALATING",
                "latitude": lat,
                "longitude": lng,
                "location_name": country,
                "reported_by": "GDACS / UN",
                "source": "live_gdacs",
                "source_url": props.get("url", {}).get("report") if isinstance(props.get("url"), dict) else None,
                "affected_population": 0,
                "ai_summary": (
                    f"GDACS {alert_level} alert: {name}. "
                    f"{severity_data.get('severitytext', '')}."
                ),
                "latest_update": props.get("datemodified") or created_at,
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
                    "status_marker": "ACTIVE",
                    "latitude": point["lat"],
                    "longitude": point["lon"],
                    "location_name": f"{point['name']}, Uttarakhand",
                    "reported_by": "Open-Meteo",
                    "source": "live_weather",
                    "source_url": "https://open-meteo.com/",
                    "affected_population": 0,
                    "ai_summary": (
                        f"Current severe weather: {description} at {point['name']}. "
                        f"Temp {temp}°C, Rain {rain}mm, Wind {wind}km/h."
                    ),
                    "latest_update": current_time,
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
            if not self._is_recent({"created_at": created_at.isoformat()}):
                continue
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
                "status_marker": "ACTIVE",
                "latitude": lat,
                "longitude": lng,
                "location_name": region,
                "reported_by": "Bhudev / IIT Roorkee",
                "source": "live_bhudev",
                "source_url": BHUDEV_URL,
                "affected_population": 0,
                "ai_summary": (
                    f"Local earthquake near {region}: M{magnitude}, depth {depth_km}km. "
                    f"Data from IIT Roorkee EEW network."
                ),
                "latest_update": created_at.isoformat(),
                "created_at": created_at.isoformat(),
            })

            if len(incidents) >= 10:
                break

        alerts = [self._incident_to_alert(inc, "BHUDEV EEW") for inc in incidents]
        return LiveFeedBundle(incidents=incidents, alerts=alerts)

    def _fetch_recent_news(self) -> LiveFeedBundle:
        """Fetch last-7-days Uttarakhand disaster updates from trusted news RSS."""
        now = time.time()
        if self._news_cache and (now - self._news_cache.fetched_at) < self._news_cache_ttl:
            cached_status = dict(self._news_cache.source_status)
            cached_status["cached"] = True
            cached_status["cache_age_seconds"] = round(now - self._news_cache.fetched_at, 2)
            self._last_status["recent_news"] = cached_status
            return self._news_cache.data

        incidents: list[dict] = []
        seen_links: set[str] = set()
        cutoff_hours = max(1, int(getattr(settings, "CUTOFF_HOURS", DEFAULT_NEWS_CUTOFF_HOURS)))
        freshness_cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=cutoff_hours)
        debug_filters = bool(getattr(settings, "DEBUG_FILTERS", False))
        total_items = 0
        dropped_source = 0
        dropped_keyword = 0
        dropped_freshness = 0
        dropped_duplicate = 0
        dropped_historical = 0
        dropped_unparseable_date = 0
        source_filter_recovered = 0
        timing = {
            "rss_fetch_ms": 0.0,
            "source_filter_ms": 0.0,
            "keyword_filter_ms": 0.0,
            "freshness_cutoff_ms": 0.0,
        }
        source_debug_lines: list[str] = []
        status = {
            "ok": True,
            "count": 0,
            "cutoff_hours": cutoff_hours,
            "cached": False,
            "cache_ttl_seconds": self._news_cache_ttl,
            "no_fresh_alerts": False,
            "message": "",
            "dropped": {},
            "timing_ms": {},
            "source_filter_recovered_by_fixed_match": 0,
        }
        if debug_filters:
            source_debug_lines.append(
                "Recent news trusted source names="
                f"{sorted(TRUSTED_NEWS_SOURCES, key=str.lower)} domains={sorted(TRUSTED_NEWS_DOMAINS)}"
            )

        for query in NEWS_QUERIES:
            url = (
                "https://news.google.com/rss/search"
                f"?q={quote_plus(query)}&hl=en-IN&gl=IN&ceid=IN:en"
            )
            rss_start = time.perf_counter()
            xml_text = self._http_get_text(url)
            timing["rss_fetch_ms"] += (time.perf_counter() - rss_start) * 1000
            root = ET.fromstring(xml_text)

            for item in root.findall("./channel/item"):
                total_items += 1
                raw_title = item.findtext("title", default="")
                raw_description = item.findtext("description", default="")
                source_el = item.find("source")
                source_name = source_el.text if source_el is not None and source_el.text else "Google News"
                source_url = source_el.get("url", "") if source_el is not None else ""
                link = item.findtext("link", default="")
                pub_date = item.findtext("pubDate", default="")

                title = self._clean_text(raw_title)
                description = self._clean_text(raw_description)
                source_name = self._clean_text(source_name)
                combined_text = f"{title} {description}"

                if link in seen_links:
                    dropped_duplicate += 1
                    continue
                source_start = time.perf_counter()
                source_match = self._trusted_news_source_match(source_name, source_url, link)
                timing["source_filter_ms"] += (time.perf_counter() - source_start) * 1000
                if debug_filters:
                    legacy_source_match = self._legacy_trusted_news_source_match(source_name)
                    if source_match["matched"] and not legacy_source_match:
                        source_filter_recovered += 1
                    source_debug_lines.append(
                        "Recent news source filter "
                        f"item={total_items} matched={source_match['matched']} "
                        f"legacy_matched={legacy_source_match} reason={source_match['reason']} "
                        f"raw_source={source_name!r} source_url={source_url!r} "
                        f"source_domain={source_match['source_domain']!r} "
                        f"link_domain={source_match['link_domain']!r} title={title[:140]!r}"
                    )
                if not source_match["matched"]:
                    dropped_source += 1
                    continue

                keyword_start = time.perf_counter()
                disaster_type = self._infer_disaster_type(combined_text)
                keyword_match = self._is_uttarakhand_item(combined_text, None, None) and disaster_type
                timing["keyword_filter_ms"] += (time.perf_counter() - keyword_start) * 1000
                if not keyword_match:
                    dropped_keyword += 1
                    continue
                if self._is_historical_or_drill(combined_text):
                    dropped_historical += 1
                    continue

                freshness_start = time.perf_counter()
                published_at = self._parse_rss_datetime(pub_date)
                if not published_at:
                    timing["freshness_cutoff_ms"] += (time.perf_counter() - freshness_start) * 1000
                    dropped_unparseable_date += 1
                    continue
                if published_at < freshness_cutoff:
                    timing["freshness_cutoff_ms"] += (time.perf_counter() - freshness_start) * 1000
                    dropped_freshness += 1
                    continue
                timing["freshness_cutoff_ms"] += (time.perf_counter() - freshness_start) * 1000

                seen_links.add(link)
                location_name, lat, lng = self._infer_location(combined_text)
                severity = self._news_severity(combined_text)
                status_marker = self._status_marker_from_text(combined_text)

                incidents.append({
                    "id": self._stable_id("news", link or title, published_at.isoformat()),
                    "title": title,
                    "description": (
                        f"{title}. Latest verified media update from {source_name}. "
                        f"{description[:280]}"
                    ).strip(),
                    "disaster_type": disaster_type,
                    "severity": severity,
                    "status": "verified",
                    "status_marker": status_marker,
                    "latitude": lat,
                    "longitude": lng,
                    "location_name": location_name,
                    "reported_by": source_name,
                    "source": "live_recent_news",
                    "source_url": link,
                    "affected_population": self._extract_people_count(combined_text),
                    "ai_summary": (
                        f"{status_marker}: {disaster_type.title()} update in {location_name}. "
                        f"Source: {source_name}."
                    ),
                    "latest_update": published_at.isoformat(),
                    "created_at": published_at.isoformat(),
                })

                if len(incidents) >= 12:
                    break

        incidents.sort(key=self._sort_key, reverse=True)
        alerts = [self._incident_to_alert(inc, "UTTARAKHAND UPDATE") for inc in incidents]
        alerts.sort(key=self._sort_key, reverse=True)

        status["count"] = len(incidents)
        status["dropped"] = {
            "source_filter": dropped_source,
            "keyword_filter": dropped_keyword,
            "freshness_cutoff": dropped_freshness,
            "duplicate": dropped_duplicate,
            "historical_or_drill": dropped_historical,
            "unparseable_pubdate": dropped_unparseable_date,
        }
        status["timing_ms"] = {name: round(value, 2) for name, value in timing.items()}
        status["source_filter_recovered_by_fixed_match"] = source_filter_recovered
        if debug_filters and source_debug_lines:
            logger.info("\n".join(source_debug_lines))

        if not incidents:
            status["no_fresh_alerts"] = True
            status["message"] = f"No fresh alerts in the last {cutoff_hours} hours"
            logger.info(
                "Recent news: no fresh alerts in the last %s hours "
                "(items=%s, dropped_source=%s, dropped_keyword=%s, dropped_freshness=%s, "
                "dropped_duplicate=%s, dropped_historical=%s, dropped_unparseable_date=%s, "
                "source_filter_recovered_by_fixed_match=%s)",
                cutoff_hours,
                total_items,
                dropped_source,
                dropped_keyword,
                dropped_freshness,
                dropped_duplicate,
                dropped_historical,
                dropped_unparseable_date,
                source_filter_recovered,
            )
        else:
            logger.info(
                "Recent news: %s fresh alerts accepted from %s RSS items "
                "(cutoff_hours=%s, dropped_source=%s, dropped_keyword=%s, "
                "dropped_freshness=%s, dropped_duplicate=%s, dropped_historical=%s, "
                "dropped_unparseable_date=%s, source_filter_recovered_by_fixed_match=%s)",
                len(incidents),
                total_items,
                cutoff_hours,
                dropped_source,
                dropped_keyword,
                dropped_freshness,
                dropped_duplicate,
                dropped_historical,
                dropped_unparseable_date,
                source_filter_recovered,
            )
        logger.info("Recent news timing: %s", status["timing_ms"])

        self._last_status["recent_news"] = status
        bundle = LiveFeedBundle(incidents=incidents, alerts=alerts)
        self._news_cache = _CacheEntry(data=bundle, fetched_at=time.time(), source_status=status)
        return bundle

    # ── HTTP helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _http_get_json(url: str) -> dict:
        """Synchronous HTTP GET returning JSON. Uses httpx for reliability."""
        headers = {"User-Agent": "AI-Disaster-Response/1.0"}
        with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True, headers=headers) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.json()

    @staticmethod
    def _http_get_text(url: str) -> str:
        headers = {"User-Agent": "AI-Disaster-Response/1.0"}
        with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True, headers=headers) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.text

    @staticmethod
    def _fetch_html_via_powershell(url: str) -> str:
        """Fetch a page as HTML, preferring httpx and falling back to PowerShell.

        The PowerShell path exists to work around local SSL/TLS issues on some
        Windows hosts; httpx is tried first so the same code path also works on
        Linux/macOS where ``powershell`` is unavailable.
        """
        # 1. Try httpx first (cross-platform).
        try:
            headers = {"User-Agent": "AI-Disaster-Response/1.0"}
            with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True, headers=headers, verify=False) as client:
                resp = client.get(url)
                resp.raise_for_status()
                return resp.text
        except Exception as e:
            logger.debug(f"httpx fetch failed for {url}: {e}; trying PowerShell fallback")

        # 2. Windows-only PowerShell fallback.
        command = [
            "powershell", "-NoProfile", "-Command",
            f"Invoke-WebRequest -Uri '{url}' -UseBasicParsing | Select-Object -ExpandProperty Content",
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=25, check=True)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.error(f"PowerShell fetch failed for {url}: {e}")
            return ""
        return result.stdout

    # ── Utilities ─────────────────────────────────────────────────────────

    @staticmethod
    def _stable_id(source: str, key1: str, key2: str) -> int:
        raw = f"{source}:{key1}:{key2}"
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return int(digest[:12], 16) % 900_000_000 + 100_000_000

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

    @staticmethod
    def _parse_rss_datetime(value: str) -> datetime | None:
        if not value:
            return None
        try:
            dt = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def _is_recent(self, item: dict) -> bool:
        created_at = self._parse_created_at(item.get("created_at"))
        if created_at is None:
            return True
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=RECENT_EVENT_WINDOW_DAYS)
        return created_at >= cutoff

    def _sort_key(self, item: dict) -> tuple[datetime, int]:
        created_at = self._parse_created_at(item.get("created_at"))
        if created_at is None:
            created_at = datetime.min.replace(tzinfo=timezone.utc)
        return created_at, int(item.get("severity") or 0)

    def _dedupe_incidents(self, incidents: list[dict]) -> list[dict]:
        deduped: list[dict] = []
        seen: set[str] = set()
        for incident in incidents:
            created_at = self._parse_created_at(incident.get("created_at"))
            day = created_at.strftime("%Y-%m-%d") if created_at else ""
            key = "|".join([
                str(incident.get("source_url") or ""),
                str(incident.get("disaster_type") or ""),
                str(incident.get("location_name") or "").lower(),
                str(incident.get("title") or "").lower()[:80],
                day,
            ])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(incident)
        return deduped

    @staticmethod
    def _clean_text(value: str) -> str:
        text = re.sub(r"<[^>]+>", " ", value or "")
        text = html.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @staticmethod
    def _normalize_source_name(source_name: str) -> str:
        return _fold_text(source_name)

    @staticmethod
    def _normalize_domain(domain: str) -> str:
        normalized = (domain or "").strip().lower()
        if normalized.startswith("www."):
            normalized = normalized[4:]
        return normalized.rstrip("/")

    @classmethod
    def _domain_from_url(cls, value: str) -> str:
        if not value:
            return ""
        parsed = urlparse(value if re.match(r"^[a-z][a-z0-9+.-]*://", value, re.I) else f"https://{value}")
        return cls._normalize_domain(parsed.netloc)

    @classmethod
    def _trusted_domain_match(cls, domain: str) -> bool:
        normalized = cls._normalize_domain(domain)
        if not normalized:
            return False
        return any(
            normalized == trusted or normalized.endswith(f".{trusted}")
            for trusted in NORMALIZED_TRUSTED_NEWS_DOMAINS
        )

    @classmethod
    def _legacy_trusted_news_source_match(cls, source_name: str) -> bool:
        source = (source_name or "").strip().lower()
        return source in NORMALIZED_TRUSTED_NEWS_SOURCES

    @classmethod
    def _trusted_news_source_match(cls, source_name: str, source_url: str = "", link: str = "") -> dict:
        source = cls._normalize_source_name(source_name)
        source_domain = cls._domain_from_url(source_url)
        link_domain = cls._domain_from_url(link)

        if source in NORMALIZED_TRUSTED_NEWS_SOURCES:
            return {
                "matched": True,
                "reason": "source_name",
                "source_domain": source_domain,
                "link_domain": link_domain,
            }
        # Match publisher names that are the bare label of a trusted domain
        # (e.g. <source>"Zee News"</source> for trusted domain zeenews.india.com).
        if source and source in _TRUSTED_DOMAIN_LABELS:
            return {
                "matched": True,
                "reason": "source_name_domain_label",
                "source_domain": source_domain,
                "link_domain": link_domain,
            }
        if cls._trusted_domain_match(source_domain):
            return {
                "matched": True,
                "reason": "source_url_domain",
                "source_domain": source_domain,
                "link_domain": link_domain,
            }
        if cls._trusted_domain_match(link_domain):
            return {
                "matched": True,
                "reason": "link_domain",
                "source_domain": source_domain,
                "link_domain": link_domain,
            }
        return {
            "matched": False,
            "reason": "no_match",
            "source_domain": source_domain,
            "link_domain": link_domain,
        }

    @classmethod
    def _is_trusted_news_source(cls, source_name: str) -> bool:
        return cls._trusted_news_source_match(source_name)["matched"]

    @staticmethod
    def _is_uttarakhand_item(text: str, lat: float | None, lng: float | None) -> bool:
        if lat is not None and lng is not None:
            if 28.7 <= float(lat) <= 31.6 and 77.5 <= float(lng) <= 81.2:
                return True
        normalized = (text or "").lower()
        return any(keyword in normalized for keyword in UTTARAKHAND_KEYWORDS)

    @staticmethod
    def _infer_disaster_type(text: str) -> str | None:
        normalized = (text or "").lower()
        for keyword, disaster_type in DISASTER_KEYWORD_TYPES.items():
            if keyword in normalized:
                return disaster_type
        return None

    @staticmethod
    def _is_historical_or_drill(text: str) -> bool:
        normalized = (text or "").lower()
        blocked_terms = [
            "anniversary",
            "on this day",
            "2013 kedarnath",
            "kedarnath tragedy",
            "mock drill",
            "preparedness drill",
            "recap",
        ]
        return any(term in normalized for term in blocked_terms)

    @staticmethod
    def _infer_location(text: str) -> tuple[str, float | None, float | None]:
        normalized = (text or "").lower()
        for region, coords in REGION_COORDS.items():
            if region in normalized:
                return f"{region.title()}, Uttarakhand", coords[0], coords[1]
        return "Uttarakhand", UTTARAKHAND_WEATHER_POINTS[0]["lat"], UTTARAKHAND_WEATHER_POINTS[0]["lon"]

    @staticmethod
    def _news_severity(text: str) -> int:
        normalized = (text or "").lower()
        # Match on word boundaries so substrings like "dead" inside "deadline"
        # or "warning" inside "forewarning" do not inflate severity.
        def _has(*phrases: str) -> bool:
            return any(re.search(rf"\b{re.escape(phrase)}\b", normalized) for phrase in phrases)

        if _has("red alert", "dead", "deaths", "death", "deadly", "killed", "missing", "evacuated", "trapped"):
            return 4
        if _has("orange alert", "warning", "landslide", "cloudburst", "flash flood", "forest fire"):
            return 3
        return 2

    @staticmethod
    def _status_marker_from_text(text: str) -> str:
        normalized = (text or "").lower()
        if any(word in normalized for word in ["worsen", "rising", "red alert", "evacuated", "trapped", "missing"]):
            return "ESCALATING"
        if any(word in normalized for word in ["contained", "under control"]):
            return "CONTAINED"
        if any(word in normalized for word in ["reopened", "restored", "rescued", "no longer"]):
            return "RESOLVED"
        return "ACTIVE"

    @staticmethod
    def _extract_people_count(text: str) -> int:
        normalized = (text or "").lower()
        patterns = [
            r"(\d+)\s+(?:people\s+)?evacuated",
            r"(\d+)\s+(?:people\s+)?trapped",
            r"(\d+)\s+(?:people\s+)?missing",
            r"(\d+)\s+(?:people\s+)?killed",
            r"(\d+)\s+(?:people\s+)?dead",
        ]
        total = 0
        for pattern in patterns:
            for match in re.findall(pattern, normalized):
                total += int(match)
        return total

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
        try:
            magnitude = float(magnitude or 0)
        except (TypeError, ValueError):
            magnitude = 0.0
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
            "status_marker": incident.get("status_marker", "ACTIVE"),
            "source_url": incident.get("source_url"),
            "created_at": incident["created_at"],
        }


# ── Module-level singleton ────────────────────────────────────────────────────

live_source = RealTimeLiveSource(cache_ttl=settings.LIVE_CACHE_TTL_SECONDS)
