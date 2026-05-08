"""
Mock Disaster Feed Generator
Generates realistic simulated disaster events for demo/development.
"""

import random
import logging
import asyncio
from backend.config import settings

logger = logging.getLogger(__name__)

DISASTER_TEMPLATES = [
    {
        "text": "Major earthquake of magnitude {mag} struck {city} at {time}. Buildings collapsed in {area} area. Estimated {pop} people affected. Rescue teams urgently needed.",
        "params": {
            "mag": lambda: round(random.uniform(4.5, 7.8), 1),
            "city": lambda: random.choice(["Delhi", "Mumbai", "Shimla", "Guwahati", "Imphal", "Patna", "Jaipur"]),
            "time": lambda: f"{random.randint(1,12)}:{random.randint(10,59)} {'AM' if random.random()>0.5 else 'PM'}",
            "area": lambda: random.choice(["residential", "commercial", "old city", "downtown", "suburban"]),
            "pop": lambda: random.randint(500, 50000),
        },
    },
    {
        "text": "Severe flooding reported in {city} after {hours} hours of continuous rainfall. Water level at {level} feet in {area}. {pop} families displaced. Road access cut off to {roads} areas.",
        "params": {
            "city": lambda: random.choice(["Mumbai", "Chennai", "Kolkata", "Patna", "Guwahati", "Bhubaneswar", "Hyderabad"]),
            "hours": lambda: random.randint(12, 72),
            "level": lambda: random.randint(3, 12),
            "area": lambda: random.choice(["low-lying", "riverside", "coastal", "urban", "slum"]),
            "pop": lambda: random.randint(200, 15000),
            "roads": lambda: random.randint(3, 15),
        },
    },
    {
        "text": "Massive fire broke out at {place} in {city}. {floors} floors engulfed. Fire tenders deployed. {trapped} people reportedly trapped. Cause suspected: {cause}.",
        "params": {
            "place": lambda: random.choice(["factory", "residential complex", "shopping mall", "warehouse", "hotel", "hospital"]),
            "city": lambda: random.choice(["Delhi", "Mumbai", "Bangalore", "Ahmedabad", "Lucknow", "Pune", "Surat"]),
            "floors": lambda: random.randint(2, 15),
            "trapped": lambda: random.randint(5, 200),
            "cause": lambda: random.choice(["electrical short circuit", "gas leak", "chemical storage", "unknown"]),
        },
    },
    {
        "text": "Cyclone {name} making landfall near {city} with wind speeds of {speed} km/h. Storm surge of {surge} meters expected. Evacuation ordered for {pop} coastal residents.",
        "params": {
            "name": lambda: random.choice(["Biparjoy", "Tauktae", "Yaas", "Amphan", "Fani", "Michaung", "Remal"]),
            "city": lambda: random.choice(["Vizag", "Puri", "Chennai", "Mangalore", "Kochi", "Thiruvananthapuram"]),
            "speed": lambda: random.randint(120, 220),
            "surge": lambda: round(random.uniform(2, 6), 1),
            "pop": lambda: random.randint(10000, 200000),
        },
    },
    {
        "text": "Landslide reported in {city} district after heavy rains. {houses} houses buried under debris. National highway blocked at {km}km mark. {pop} people feared trapped.",
        "params": {
            "city": lambda: random.choice(["Shimla", "Uttarakhand", "Munnar", "Wayanad", "Darjeeling", "Sikkim", "Aizawl"]),
            "houses": lambda: random.randint(10, 80),
            "km": lambda: random.randint(20, 150),
            "pop": lambda: random.randint(20, 500),
        },
    },
    {
        "text": "Industrial gas leak at {factory} in {city}. Toxic fumes spreading in {radius}km radius. {pop} residents evacuated. Medical teams treating {injured} for respiratory distress.",
        "params": {
            "factory": lambda: random.choice(["chemical plant", "fertilizer factory", "refinery", "pharmaceutical unit", "LPG bottling plant"]),
            "city": lambda: random.choice(["Bhopal", "Vizag", "Jamnagar", "Haldia", "Ankleshwar", "Vadodara"]),
            "radius": lambda: random.randint(2, 10),
            "pop": lambda: random.randint(1000, 20000),
            "injured": lambda: random.randint(50, 500),
        },
    },
]


def generate_event() -> str:
    """Generate a single random disaster event report."""
    template = random.choice(DISASTER_TEMPLATES)
    params = {k: v() for k, v in template["params"].items()}
    return template["text"].format(**params)


async def run_mock_feed(process_callback):
    """
    Background task: generates disaster events at configured interval.
    process_callback should be an async function that accepts (report_text: str).
    """
    logger.info(f"🔄 Mock feed started (interval: {settings.MOCK_FEED_INTERVAL}s)")
    # Initial delay to let the app start up
    await asyncio.sleep(10)

    while True:
        try:
            if settings.MOCK_FEED_ENABLED:
                report = generate_event()
                logger.info(f"📡 Mock feed generated: {report[:60]}...")
                await process_callback(report)
        except Exception as e:
            logger.error(f"Mock feed error: {e}")
        await asyncio.sleep(settings.MOCK_FEED_INTERVAL)
