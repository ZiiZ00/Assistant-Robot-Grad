"""Pure-Python/lightweight RAG for Raspberry Pi chatbot use."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from env_utils import get_env_first
from logging_utils import safe_print


TokenList = list[list[str]]


class LightweightRAGEngine:
    def __init__(self, data_dir: Path, ask_groq: Callable[[str], str] | None = None) -> None:
        self.data_dir = Path(data_dir)
        self._ask_groq_callback = ask_groq
        self._chunks: list[str] = []
        self._tokenized_chunks: TokenList = []
        self._bm25: object | None = None
        self._loaded = False
        self._retriever_name = "keyword overlap"

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    @property
    def retriever_name(self) -> str:
        return self._retriever_name

    def load_documents(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        safe_print(f"Loading documents from {self.data_dir}")
        if not self.data_dir.is_dir():
            safe_print(f"Lightweight RAG data folder missing: {self.data_dir}")
            safe_print("Loaded document chunks: 0")
            return

        texts: list[str] = []
        for path in sorted(self.data_dir.iterdir()):
            if path.suffix.lower() == ".pdf":
                text = self._read_pdf(path)
            elif path.suffix.lower() == ".txt":
                text = self._read_text(path)
            else:
                continue
            if text.strip():
                texts.append(text)

        for text in texts:
            self._chunks.extend(self._split_text(text))

        self._tokenized_chunks = [self._tokenize(chunk) for chunk in self._chunks]
        self._build_bm25()
        safe_print(f"Loaded document chunks: {len(self._chunks)}")

    def retrieve(self, question: str, top_k: int = 4) -> list[str]:
        self.load_documents()
        if not self._chunks:
            safe_print("Retrieved context chunks: 0")
            return []
        top_k = max(1, min(top_k, len(self._chunks)))
        safe_print(f"Retrieving context with {self._retriever_name}")
        if self._bm25 is not None:
            scores = list(self._bm25.get_scores(self._tokenize(question)))  # type: ignore[attr-defined]
        else:
            scores = self._keyword_scores(question)
        ranked = sorted(enumerate(scores), key=lambda item: item[1], reverse=True)
        selected = [self._chunks[index] for index, score in ranked[:top_k] if score > 0]
        if not selected:
            selected = [self._chunks[index] for index, _score in ranked[:top_k]]
        safe_print(f"Retrieved context chunks: {len(selected)}")
        return selected

    def answer(self, question: str, language: str) -> str | None:
        chunks = self.retrieve(question, top_k=4)
        if not chunks:
            return None
        safe_print("Generating answer with Groq")
        prompt = (
            "You are an expert assistant for a museum tour guide robot.\n"
            f"Answer in {'Arabic' if language == 'ar' else 'English'} in about 50 words.\n"
            "Use only the following retrieved context when possible.\n\n"
            f"Context:\n{self.format_context(chunks)}\n\nQuestion:\n{question}\n"
        )
        answer = self._ask_groq(prompt)
        safe_print(f"Chatbot answer: {answer}")
        return answer.strip() or None

    @staticmethod
    def format_context(chunks: list[str]) -> str:
        return "\n\n".join(chunks)

    def _read_pdf(self, path: Path) -> str:
        try:
            from pypdf import PdfReader  # type: ignore
        except Exception as exc:
            safe_print(f"pypdf import failed; skipping {path.name}: {exc}")
            return ""
        try:
            reader = PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as exc:
            safe_print(f"PDF read failed for {path.name}: {exc}")
            return ""

    @staticmethod
    def _read_text(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:
            safe_print(f"Text read failed for {path.name}: {exc}")
            return ""

    @staticmethod
    def _split_text(text: str, chunk_words: int = 180, overlap_words: int = 35) -> list[str]:
        normalized = re.sub(r"\s+", " ", text).strip()
        words = normalized.split()
        if not words:
            return []
        chunks: list[str] = []
        step = max(1, chunk_words - overlap_words)
        for start in range(0, len(words), step):
            chunk = " ".join(words[start:start + chunk_words]).strip()
            if len(chunk) > 120:
                chunks.append(chunk)
        return chunks

    def _build_bm25(self) -> None:
        try:
            from rank_bm25 import BM25Okapi  # type: ignore
        except Exception as exc:
            safe_print(f"rank-bm25 import failed; using keyword overlap scoring: {exc}")
            self._retriever_name = "keyword overlap"
            self._bm25 = None
            return
        self._bm25 = BM25Okapi(self._tokenized_chunks)
        self._retriever_name = "BM25"

    def _keyword_scores(self, question: str) -> list[int]:
        query_tokens = set(self._tokenize(question))
        if not query_tokens:
            return [0 for _chunk in self._chunks]
        return [len(query_tokens.intersection(tokens)) for tokens in self._tokenized_chunks]

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return [token.lower() for token in re.findall(r"[A-Za-z0-9\u0600-\u06ff]+", text)]

    def _ask_groq(self, prompt: str) -> str:
        if self._ask_groq_callback is not None:
            return self._ask_groq_callback(prompt)
        api_key = get_env_first("GROQ_API_KEY")
        if not api_key:
            safe_print("GROQ_API_KEY is missing. Set it before using lightweight RAG answer generation.")
            return ""
        try:
            import requests  # type: ignore
        except Exception as exc:
            safe_print(f"requests import failed: {exc}")
            return ""
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
            },
            timeout=60,
        )
        safe_print(f"Answer generation response status: {response.status_code}")
        if response.status_code != 200:
            safe_print(f"Groq answer generation failed: {response.text}")
            return ""
        result = response.json()
        return str(result.get("choices", [{}])[0].get("message", {}).get("content", ""))
