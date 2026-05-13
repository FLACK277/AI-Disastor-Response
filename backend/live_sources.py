"""
Live incident sources for the Uttarakhand-focused dashboard.
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

BHUDEV_URL = "https://bhudev.uk/"
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
}


@dataclass
class LiveFeedBundle:
    incidents: list[dict]
    alerts: list[dict]


class UttarakhandLiveSource:
    """Fetch live Uttarakhand incidents from public official or institutional feeds."""

    def fetch(self, limit: int = 10) -> LiveFeedBundle:
        earthquakes = self._fetch_bhudev_earthquakes(limit=limit)
        alerts = [self._incident_to_alert(incident) for incident in earthquakes]
        return LiveFeedBundle(incidents=earthquakes, alerts=alerts)

    def _fetch_bhudev_earthquakes(self, limit: int = 10) -> list[dict]:
        """Read recent Uttarakhand earthquakes from the IIT Roorkee / USDMA feed page."""
        html = self._fetch_html_via_powershell(BHUDEV_URL)
        if not html:
            return []

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
            latitude, longitude = self._lookup_coords(region)
            incidents.append(
                {
                    "id": self._stable_live_id("bhudev", region, timestamp),
                    "title": f"Earthquake reported near {region}",
                    "description": (
                        f"Live earthquake reading from the IIT Roorkee / USDMA Bhudev system. "
                        f"Magnitude {magnitude}, depth {depth_km} km."
                    ),
                    "disaster_type": "earthquake",
                    "severity": self._magnitude_to_severity(magnitude),
                    "status": "reported",
                    "latitude": latitude,
                    "longitude": longitude,
                    "location_name": region,
                    "reported_by": "Bhudev / IIT Roorkee",
                    "source": "live_bhudev",
                    "affected_population": 0,
                    "ai_summary": (
                        f"Recent Uttarakhand earthquake event for {region}. "
                        f"Magnitude {magnitude}, depth {depth_km} km."
                    ),
                    "created_at": created_at.isoformat(),
                }
            )

            if len(incidents) >= limit:
                break

        return incidents

    @staticmethod
    def _fetch_html_via_powershell(url: str) -> str:
        """Use PowerShell web request to avoid local Python SSL issues on this Windows runtime."""
        command = [
            "powershell",
            "-NoProfile",
            "-Command",
            f"Invoke-WebRequest -Uri '{url}' -UseBasicParsing | Select-Object -ExpandProperty Content",
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=25,
                check=True,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.error(f"Failed to fetch live feed HTML from {url}: {e}")
            return ""
        return result.stdout

    @staticmethod
    def _stable_live_id(source: str, location: str, timestamp: str) -> int:
        raw = f"{source}:{location}:{timestamp}"
        return abs(hash(raw)) % 900_000_000 + 100_000_000

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
    def _incident_to_alert(incident: dict) -> dict:
        return {
            "id": incident["id"] + 1,
            "incident_id": incident["id"],
            "title": f"LIVE EARTHQUAKE: {incident['location_name']}",
            "message": incident["description"],
            "severity": incident["severity"],
            "alert_type": "live_feed",
            "created_at": incident["created_at"],
        }


live_source = UttarakhandLiveSource()
