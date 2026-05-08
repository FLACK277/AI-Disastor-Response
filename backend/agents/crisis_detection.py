"""
Crisis Detection Agent
Classifies disaster type, extracts entities, scores severity using Groq LLM.
"""

import logging
from backend.llm_client import llm_client

logger = logging.getLogger(__name__)


class CrisisDetectionAgent:
    """Analyzes incoming reports to classify disaster type and severity."""

    def __init__(self):
        logger.info("✅ Crisis Detection Agent initialized")

    async def analyze(self, report_text: str) -> dict:
        """
        Analyze a raw disaster report.
        Returns: dict with disaster_type, severity, location, affected_population, title, ai_summary
        """
        logger.info(f"🔍 Analyzing report: {report_text[:80]}...")
        result = llm_client.classify_disaster(report_text)
        logger.info(
            f"📋 Classification: type={result.get('disaster_type')}, "
            f"severity={result.get('severity')}, location={result.get('location')}"
        )
        return result


crisis_agent = CrisisDetectionAgent()
