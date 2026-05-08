"""
RAG Knowledge Agent
Keyword retrieval over curated emergency SOPs with Groq answer synthesis.
"""

import logging
import re
from pathlib import Path
from backend.llm_client import llm_client

logger = logging.getLogger(__name__)

SOPS_DIR = Path(__file__).parent.parent.parent / "data" / "sops"

STOPWORDS = {
    "about", "after", "again", "also", "during", "from", "have", "into", "more",
    "need", "please", "procedure", "procedures", "response", "should", "that",
    "their", "there", "this", "what", "when", "where", "which", "with", "your",
}

QUERY_EXPANSIONS = {
    "landslide": {"landslide", "slope", "debris", "roadblock", "evacuation", "geotechnical"},
    "earthquake": {"earthquake", "aftershock", "collapsed", "seismic", "search", "rescue"},
    "flood": {"flood", "water", "rainfall", "river", "inundation", "boat", "evacuation"},
    "fire": {"fire", "smoke", "burn", "evacuation", "hazmat", "tender"},
    "cyclone": {"cyclone", "storm", "wind", "surge", "coastal", "shelter"},
    "tsunami": {"tsunami", "coastal", "wave", "shoreline", "evacuation", "harbor"},
    "industrial": {"industrial", "chemical", "gas", "leak", "hazmat", "decontamination"},
    "chemical": {"industrial", "chemical", "gas", "leak", "hazmat", "decontamination"},
    "triage": {"triage", "medical", "injury", "casualty", "hospital", "ambulance"},
    "shelter": {"shelter", "relief", "camp", "water", "sanitation", "food"},
    "evacuation": {"evacuation", "route", "shelter", "transport", "warning", "public"},
}


class RAGKnowledgeAgent:
    """Simple RAG pipeline over emergency SOP documents."""

    def __init__(self):
        self.documents: list[dict] = []  # {"text": str, "source": str, "chunk_id": int}
        self._load_sops()
        logger.info(f"✅ RAG Knowledge Agent initialized ({len(self.documents)} chunks)")

    def _load_sops(self):
        """Load and chunk SOP documents."""
        if not SOPS_DIR.exists():
            logger.warning(f"SOPs directory not found: {SOPS_DIR}")
            return

        for fpath in SOPS_DIR.glob("*.txt"):
            text = fpath.read_text(encoding="utf-8")
            chunks = self._chunk_text(text, chunk_size=500, overlap=100)
            for i, chunk in enumerate(chunks):
                self.documents.append({
                    "text": chunk,
                    "source": fpath.name,
                    "chunk_id": i,
                })

    @staticmethod
    def _chunk_text(text: str, chunk_size: int = 500, overlap: int = 100) -> list[str]:
        """Split text into overlapping chunks by character count."""
        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end]
            if chunk.strip():
                chunks.append(chunk.strip())
            start += chunk_size - overlap
        return chunks

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {
            token
            for token in re.findall(r"[a-z0-9]+", text.lower())
            if len(token) > 2 and token not in STOPWORDS
        }

    def _expand_query(self, query: str) -> set[str]:
        tokens = self._tokens(query)
        expanded = set(tokens)
        for token in tokens:
            expanded.update(QUERY_EXPANSIONS.get(token, set()))
        return expanded

    def _keyword_search(self, query: str, top_k: int = 5) -> list[dict]:
        """Simple keyword-based retrieval as primary search method."""
        query_words = self._expand_query(query)
        scored = []
        for doc in self.documents:
            doc_words = self._tokens(f"{doc['source']} {doc['text']}")
            overlap = len(query_words & doc_words)
            if overlap > 0:
                source_bonus = 2 if any(word in doc["source"].lower() for word in query_words) else 0
                scored.append((overlap + source_bonus, doc))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [doc for _, doc in scored[:top_k]]

    @staticmethod
    def _local_answer(question: str, relevant: list[dict]) -> str:
        """Build a useful SOP-grounded answer when the LLM service is unavailable."""
        source_list = ", ".join(sorted(set(doc["source"] for doc in relevant)))
        excerpts = []
        for doc in relevant[:3]:
            excerpt = " ".join(doc["text"].split())
            excerpts.append(f"- {excerpt[:260]}")

        return (
            f"Based on the available SOP notes ({source_list}), use these steps as guidance:\n"
            + "\n".join(excerpts)
            + "\n\nThis is a local SOP lookup response, not a live AI-generated operational order."
        )

    async def query(self, question: str) -> dict:
        """Answer a question using RAG over SOPs."""
        # Retrieve relevant chunks
        relevant = self._keyword_search(question, top_k=5)

        if not relevant:
            return {
                "response": "I couldn't find relevant emergency procedures for your question. "
                            "Please try rephrasing or ask about earthquake, flood, fire, landslide, "
                            "cyclone, tsunami, industrial, triage, shelter, or evacuation procedures.",
                "sources": [],
            }

        # Build context from retrieved chunks
        context = "\n\n---\n\n".join([
            f"[Source: {doc['source']}]\n{doc['text']}" for doc in relevant
        ])
        sources = list(set(doc["source"] for doc in relevant))

        # Generate answer using LLM
        answer = llm_client.answer_sop_question(question, context)
        if not answer:
            answer = self._local_answer(question, relevant)

        return {
            "response": answer,
            "sources": sources,
        }


rag_agent = RAGKnowledgeAgent()
