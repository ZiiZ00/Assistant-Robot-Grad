"""Fail-safe Gemini REST fallback with no required third-party dependency."""
from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request

from env_utils import get_env_first
from logging_utils import safe_print


class GeminiClient:
    def __init__(self, model: str | None = None) -> None:
        self.model = model or os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

    def answer(self, *, question: str, artifact_id: str, artifact_name: str,
               artifact_description: str, language: str) -> str | None:
        api_key = get_env_first("GEMINI_API_KEY")
        if not api_key:
            safe_print("Gemini unavailable: missing GEMINI_API_KEY")
            return None
        try:
            with socket.create_connection(("generativelanguage.googleapis.com", 443), timeout=2):
                pass
        except OSError:
            safe_print("Gemini unavailable: no internet")
            return None

        prompt = f"""You are a museum tour guide robot inside the Grand Egyptian Museum.
The visitor is asking about the current artifact.

Current artifact ID: {artifact_id}
Current artifact name: {artifact_name}
Local artifact description: {artifact_description}
Visitor question: {question}

Answer as a museum guide.
Keep the answer factual, friendly, and short, about 2 to 4 sentences.
If the selected language is Arabic, answer in Arabic.
If the selected language is English, answer in English.
Selected language: {language}
"""
        body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
               f"?key={api_key}")
        request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
            parts = payload.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            answer = " ".join(part.get("text", "").strip() for part in parts).strip()
            if answer:
                safe_print("Gemini answer found")
                return answer
            safe_print("Gemini unavailable: empty response")
        except Exception as exc:
            safe_print(f"Gemini unavailable: {exc}")
        return None
