"""Normalized, artifact-first matching over the local bilingual Q&A data."""
from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Any

from logging_utils import safe_print


class LocalChatbot:
    def __init__(self, qa_data: dict[str, Any], threshold: float = 0.58) -> None:
        self.qa_data = qa_data
        self.threshold = threshold

    @staticmethod
    def normalize(text: str, language: str) -> str:
        text = unicodedata.normalize("NFKC", text).casefold()
        if language == "ar":
            text = re.sub(r"[\u064b-\u065f\u0670\u06d6-\u06ed\u0640]", "", text)
            text = text.translate(str.maketrans({
                "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",
                "ى": "ي", "ؤ": "و", "ئ": "ي",
            }))
        text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
        return " ".join(text.split())

    @staticmethod
    def _score(query: str, candidate: str, language: str) -> float:
        fuzzy = difflib.SequenceMatcher(None, query, candidate).ratio()
        stopwords = ({"a", "an", "the", "is", "are", "was", "were", "what", "who", "why",
                      "how", "where", "when", "this", "that", "it", "of", "in", "on", "for"}
                     if language == "en" else
                     {"ما", "ماذا", "من", "هو", "هي", "هذا", "هذه", "في", "على", "عن", "لماذا",
                      "كيف", "اين", "متي", "هل"})
        query_tokens = set(query.split()) - stopwords
        candidate_tokens = set(candidate.split()) - stopwords
        overlap = len(query_tokens & candidate_tokens) / max(1, len(query_tokens | candidate_tokens))
        score = (0.80 * fuzzy) + (0.20 * overlap)
        if not query_tokens.intersection(candidate_tokens) and fuzzy < 0.82:
            score *= 0.65
        return score

    def answer(self, question: str, artifact_id: str, language: str) -> str | None:
        query = self.normalize(question, language)
        current = self._best_match(query, [artifact_id], language)
        if current[0] >= self.threshold:
            self._print_match(current)
            return current[2]

        other_ids = [item_id for item_id in self.qa_data if item_id != artifact_id]
        elsewhere = self._best_match(query, other_ids, language)
        best = current if current[0] >= elsewhere[0] else elsewhere
        if best[0] >= self.threshold:
            self._print_match(best)
            return best[2]

        safe_print("Local QA no answer found")
        return None

    def _best_match(self, query: str, artifact_ids: list[str], language: str) -> tuple[float, str, str | None]:
        best: tuple[float, str, str | None] = (0.0, "", None)
        for artifact_id in artifact_ids:
            groups = self.qa_data.get(artifact_id, {}).get(language, [])
            for group in groups:
                for variation in group.get("questions", []):
                    normalized = self.normalize(variation, language)
                    score = self._score(query, normalized, language)
                    if score > best[0]:
                        best = (score, variation, group.get("answer"))
        return best

    @staticmethod
    def _print_match(match: tuple[float, str, str | None]) -> None:
        safe_print(f"Local QA best match: {match[1]}")
        safe_print(f"Local QA score: {match[0]:.2f}")
        safe_print("Local QA answer found")
