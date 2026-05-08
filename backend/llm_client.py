"""
AI Disaster Response Coordinator - LLM Client
Wrapper for Groq API with honest fallbacks when AI is unavailable.
"""

import json
import logging
import re
import urllib.error
import urllib.request

from backend.config import settings

logger = logging.getLogger(__name__)


class LLMClient:
    """Groq-powered LLM client for disaster response NLP tasks."""

    def __init__(self):
        self.model = settings.GROQ_MODEL
        self.api_key = settings.GROQ_API_KEY
        if self.api_key:
            logger.info(f"Groq REST client enabled (model: {self.model})")
        else:
            logger.warning("Groq API key missing; AI responses will use safe fallbacks")

    def _chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> str:
        if not self.api_key:
            return ""

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        request = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                body = json.loads(response.read().decode("utf-8"))
            return body["choices"][0]["message"]["content"] or ""
        except (urllib.error.URLError, urllib.error.HTTPError, KeyError, IndexError, json.JSONDecodeError) as e:
            logger.error(f"Groq API call failed: {e}")
            return ""

    def classify_disaster(self, text: str) -> dict:
        """Classify disaster type and extract key information."""
        system = (
            "You are a disaster classification AI. Analyze the report and return JSON only.\n"
            "Fields: disaster_type (earthquake|flood|fire|cyclone|landslide|tsunami|industrial|other), "
            "severity (1-5, where 5=critical), location (string), "
            "affected_population (estimated int), title (short summary), "
            "ai_summary (2-3 sentence analysis).\n"
            "Do not invent missing facts. If the report does not provide a clear location, use "
            "\"Unknown\". If the affected population is not stated, use 0. Mark uncertain facts "
            "as unverified in ai_summary.\n"
            "Return ONLY valid JSON, no markdown."
        )
        result = self._chat(system, text)
        json_text = result.strip()
        fenced = re.search(r"```(?:json)?\s*(.*?)```", json_text, re.DOTALL | re.IGNORECASE)
        if fenced:
            json_text = fenced.group(1).strip()

        try:
            return json.loads(json_text)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse classification JSON: {result[:200]}")
            return {
                "disaster_type": "other",
                "severity": 1,
                "location": "Unknown",
                "affected_population": 0,
                "title": text[:80],
                "ai_summary": "Automatic classification unavailable. Treat this as an unverified report until reviewed.",
            }

    def generate_alert(self, incident_data: dict) -> str:
        """Generate an alert message for an incident."""
        system = (
            "You are an emergency alert system. Generate a concise, actionable alert message "
            "for emergency responders and the public. Include: what happened, where, severity, "
            "and immediate action needed. Keep it under 200 words. Be direct and clear. "
            "Do not add facts that are not present in the incident data. State that the report "
            "is unverified unless the data explicitly says it is verified."
        )
        prompt = json.dumps(incident_data, default=str)
        return self._chat(system, prompt).strip()

    def answer_sop_question(self, question: str, context: str) -> str:
        """Answer a question about emergency procedures using RAG context."""
        system = (
            "You are an AI emergency response advisor. Answer the question using ONLY the "
            "provided SOP context. Be specific, actionable, and cite the relevant source file "
            "names or protocol headings from the context. Prefer concise responder checklists, "
            "public safety instructions, and escalation triggers. If the context doesn't contain "
            "the answer, say so clearly and do not invent facts."
        )
        prompt = f"Context:\n{context}\n\nQuestion: {question}"
        return self._chat(system, prompt, max_tokens=1500).strip()

    def generate_engagement_message(self, incident_data: dict, resource_data: dict) -> str:
        """Generate a deployment message for a resource assigned to an incident."""
        system = (
            "You are an emergency dispatch coordinator. Generate a brief deployment message "
            "for the resource being assigned to the incident. Include: incident details, "
            "deployment urgency, expected actions. Keep it under 100 words. Do not invent "
            "details that are not present in the input."
        )
        prompt = f"Incident: {json.dumps(incident_data, default=str)}\nResource: {json.dumps(resource_data, default=str)}"
        return self._chat(system, prompt, max_tokens=300).strip()


llm_client = LLMClient()
