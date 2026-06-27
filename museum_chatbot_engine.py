"""Direct adapter for the NLP1.1 chatbot inside the Plan B Tkinter app."""
from __future__ import annotations

import base64
import importlib.util
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from env_utils import get_env_first
from lightweight_rag_engine import LightweightRAGEngine
from logging_utils import safe_print
from speech import SAMPLE_RATE, record_microphone


def normalize_stt_language(language: str) -> str:
    normalized = str(language or "en").strip().lower()
    return "ar" if normalized == "ar" else "en"


class MuseumChatbotEngine:
    def __init__(self, chatbot_root: str | Path, *, enabled: bool = True) -> None:
        self.chatbot_root = Path(chatbot_root)
        self.vectorstore_path = self.chatbot_root / "vectorstore"
        self.enabled = enabled
        self._vectordb: Any | None = None
        self._retriever: Any | None = None
        self._embeddings: Any | None = None
        self._lightweight_rag: LightweightRAGEngine | None = None
        self._force_lightweight = os.getenv("PLANB_LIGHT_RAG", "").strip().lower() in {"1", "true", "yes", "on"}
        self._heavy_reason = "available"
        self._heavy_available = self._detect_heavy_rag_available()
        safe_print(f"Added chatbot folder found: {self.chatbot_root}")
        for relative in ("backend.py", "rag_utils.py", "requirements.txt"):
            path = self.chatbot_root / relative
            if path.exists():
                safe_print(f"Reading chatbot file: {path}")
        safe_print(f"Expected vectorstore path: {self.vectorstore_path}")
        safe_print(f"Heavy RAG available: {self._heavy_available}")
        if self._force_lightweight:
            safe_print("Heavy RAG available: False or skipped")
        elif not self._heavy_available:
            safe_print(f"Heavy RAG unavailable reason: {self._heavy_reason}")
        safe_print(f"Lightweight RAG mode: {self.lightweight_mode}")
        if self.lightweight_mode:
            safe_print("Using lightweight Raspberry Pi RAG")

    @property
    def available(self) -> bool:
        return self.enabled and self.chatbot_root.is_dir()

    @property
    def heavy_rag_available(self) -> bool:
        return self._heavy_available

    @property
    def lightweight_mode(self) -> bool:
        return self._force_lightweight or not self._heavy_available

    @property
    def heavy_unavailable_reason(self) -> str:
        return self._heavy_reason

    @property
    def lightweight_chunk_count(self) -> int:
        return 0 if self._lightweight_rag is None else self._lightweight_rag.chunk_count

    def listen(self, language: str, mic_device_index: int | None = None) -> str | None:
        if not self.available:
            safe_print("Using integrated chatbot STT failed: chatbot folder unavailable")
            return None
        stt_language = normalize_stt_language(language)
        safe_print("Using integrated chatbot STT")
        safe_print(f"Selected UI language: {stt_language}")
        safe_print(f"Selected STT language: {stt_language}")
        safe_print("Recording started")
        wav_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as wav_file:
                wav_path = Path(wav_file.name)
            result = record_microphone(seconds=5.0, mic_device_index=mic_device_index, output_wav=wav_path)
            safe_print("Recording stopped")
            if not result.get("pcm"):
                safe_print("Recognized question before translation: ")
                return None
            recognized = self._transcribe_audio(wav_path, stt_language)
            safe_print(f"Recognized question before translation: {recognized}")
            return recognized.strip() or None
        except Exception as exc:
            safe_print("Recording stopped")
            safe_print(f"Integrated chatbot STT exception: {exc}")
            safe_print(self._dependency_help())
            return None
        finally:
            if wav_path:
                try:
                    wav_path.unlink(missing_ok=True)
                except Exception as exc:
                    safe_print(f"Temporary audio cleanup exception: {exc}")

    def answer(self, question: str, language: str) -> str | None:
        if not question.strip():
            return None
        if not self.available:
            safe_print("Integrated chatbot unavailable: chatbot folder was not found")
            return None
        safe_print("Sending question to integrated chatbot engine")
        safe_print(f"Selected language: {language}")
        try:
            detected_language = self.detect_language(question) or language
            safe_print(f"Detected question language: {detected_language}")
            question_for_rag = question
            if detected_language == "ar":
                question_for_rag = self.translate_to_english(question)
                safe_print(f"Translated to English: {question_for_rag}")
            else:
                safe_print(f"Using English directly: {question_for_rag}")

            context = self.retrieve_context(question_for_rag)
            safe_print("Generating answer with Groq")
            english_answer = self._ask_groq(
                "You are an expert assistant for a museum tour guide robot.\n"
                "Use the following context to answer the question in about 50 words.\n\n"
                f"Context:\n{context}\n\nQuestion:\n{question_for_rag}\n"
            )
            if not english_answer:
                return None
            if language == "ar" or detected_language == "ar":
                answer = self.translate_to_arabic(english_answer)
            else:
                answer = english_answer
            safe_print(f"Chatbot answer: {answer}")
            return answer.strip() or None
        except Exception as exc:
            safe_print(f"Integrated chatbot answer exception: {exc}")
            safe_print(self._dependency_help())
            return None

    def speak(self, text: str, language: str) -> None:
        if not text.strip():
            return
        safe_print(f"TTS speaking: {text}")
        try:
            audio_b64 = self.synthesize_audio_base64(text, language)
            if not audio_b64:
                safe_print("Integrated chatbot TTS returned no audio.")
        except Exception as exc:
            safe_print(f"Integrated chatbot TTS exception: {exc}")
            safe_print(self._dependency_help())

    @staticmethod
    def detect_language(text: str) -> str:
        arabic_chars = sum(1 for char in text if "\u0600" <= char <= "\u06ff")
        total_chars = len([char for char in text if char.isalpha()])
        if total_chars == 0:
            return "en"
        return "ar" if arabic_chars / total_chars > 0.3 else "en"

    @staticmethod
    def translate_to_english(text: str) -> str:
        try:
            from deep_translator import GoogleTranslator  # type: ignore
            return GoogleTranslator(source="auto", target="en").translate(text)
        except Exception as exc:
            safe_print(f"Translation to English failed: {exc}")
            return text

    @staticmethod
    def translate_to_arabic(text: str) -> str:
        try:
            from deep_translator import GoogleTranslator  # type: ignore
            return GoogleTranslator(source="auto", target="ar").translate(text)
        except Exception as exc:
            safe_print(f"Translation to Arabic failed: {exc}")
            return text

    def retrieve_context(self, question_for_rag: str) -> str:
        safe_print("Retrieving context")
        if self.lightweight_mode:
            engine = self.load_lightweight_rag()
            chunks = engine.retrieve(question_for_rag, top_k=4)
            return engine.format_context(chunks)
        retriever = self._load_retriever()
        docs = retriever.invoke(question_for_rag)
        safe_print(f"Retrieved {len(docs)} context chunks.")
        return "\n".join(doc.page_content for doc in docs[:5])

    def load_lightweight_rag(self) -> LightweightRAGEngine:
        if self._lightweight_rag is None:
            self._lightweight_rag = LightweightRAGEngine(self.chatbot_root / "Data", ask_groq=self._ask_groq)
        self._lightweight_rag.load_documents()
        return self._lightweight_rag

    def load_embedding_model(self) -> Any:
        if self.lightweight_mode:
            raise RuntimeError(f"Heavy RAG skipped: {self._heavy_reason}")
        if self._embeddings is not None:
            return self._embeddings
        try:
            from langchain_huggingface import HuggingFaceEmbeddings  # type: ignore
        except Exception as exc:
            safe_print(f"Embedding dependency import failed: {exc}")
            raise
        self._embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
        return self._embeddings

    def load_vectorstore(self) -> Any:
        if self.lightweight_mode:
            raise RuntimeError(f"Heavy RAG skipped: {self._heavy_reason}")
        if self._vectordb is not None:
            return self._vectordb
        safe_print("Loading vectorstore")
        if not self.vectorstore_path.exists():
            safe_print(f"Vectorstore missing. Expected path: {self.vectorstore_path}")
            raise FileNotFoundError(f"Vectorstore missing at {self.vectorstore_path}")
        try:
            from langchain_community.vectorstores import FAISS  # type: ignore
        except Exception as exc:
            safe_print(f"Vectorstore dependency import failed: {exc}")
            raise
        self._vectordb = FAISS.load_local(
            str(self.vectorstore_path),
            self.load_embedding_model(),
            allow_dangerous_deserialization=True,
        )
        return self._vectordb

    def _load_retriever(self) -> Any:
        if self._retriever is not None:
            return self._retriever
        self._retriever = self.load_vectorstore().as_retriever()
        return self._retriever

    def _detect_heavy_rag_available(self) -> bool:
        if self._force_lightweight:
            self._heavy_reason = "PLANB_LIGHT_RAG=1"
            return False
        required_modules = (
            "torch",
            "faiss",
            "sentence_transformers",
            "langchain_community",
            "langchain_huggingface",
        )
        missing = [name for name in required_modules if importlib.util.find_spec(name) is None]
        if missing:
            self._heavy_reason = "missing modules: " + ", ".join(missing)
            return False
        if not self.vectorstore_path.exists():
            self._heavy_reason = f"missing vectorstore: {self.vectorstore_path}"
            return False
        return True

    def _transcribe_audio(self, wav_path: Path, language: str) -> str:
        stt_language = normalize_stt_language(language)
        api_key = get_env_first("GROQ_API_KEY")
        if not api_key:
            safe_print("GROQ_API_KEY is missing. Set it before using integrated STT.")
            return ""
        try:
            import requests  # type: ignore
        except Exception as exc:
            safe_print(f"requests import failed: {exc}")
            raise
        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        safe_print(f"Groq Whisper transcription language: {stt_language}")
        safe_print("Groq Whisper endpoint: transcriptions")
        headers = {"Authorization": f"Bearer {api_key}"}
        with wav_path.open("rb") as audio_file:
            files = {"file": (str(wav_path), audio_file, "audio/wav")}
            data = {"model": "whisper-large-v3", "language": stt_language}
            response = requests.post(url, headers=headers, files=files, data=data, timeout=60)
        safe_print(f"Transcription response status: {response.status_code}")
        if response.status_code != 200:
            safe_print(f"ERROR: Transcription failed - {response.text}")
            return ""
        return str(response.json().get("text", ""))

    def _ask_groq(self, prompt: str) -> str:
        api_key = get_env_first("GROQ_API_KEY")
        if not api_key:
            safe_print("GROQ_API_KEY is missing. Set it before using integrated chatbot answer generation.")
            return ""
        try:
            import requests  # type: ignore
        except Exception as exc:
            safe_print(f"requests import failed: {exc}")
            raise
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

    def synthesize_audio_base64(self, text: str, language: str = "ar") -> str | None:
        eleven_api_key = get_env_first("ELEVEN_API_KEY", "ELEVENLABS_API_KEY")
        voice_id = get_env_first("ELEVEN_VOICE_ID", "ELEVENLABS_VOICE_ID")
        if eleven_api_key and voice_id:
            audio = self._elevenlabs_tts(text, language, eleven_api_key, voice_id)
            if audio:
                return audio
        return self._gtts_audio(text, language)

    def _elevenlabs_tts(self, text: str, language: str, api_key: str, voice_id: str) -> str | None:
        try:
            import requests  # type: ignore
            payload_text = self._convert_numbers_to_arabic_words(text) if language == "ar" else text
            response = requests.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                headers={"xi-api-key": api_key, "Content-Type": "application/json"},
                json={
                    "text": payload_text,
                    "model_id": "eleven_multilingual_v2",
                    "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
                },
                timeout=60,
            )
            safe_print(f"TTS response status: {response.status_code}")
            if response.status_code == 200:
                return "data:audio/mpeg;base64," + base64.b64encode(response.content).decode("ascii")
            safe_print(f"ElevenLabs TTS Error: {response.text}")
            return None
        except Exception as exc:
            safe_print(f"ElevenLabs TTS exception: {exc}")
            return None

    @staticmethod
    def _gtts_audio(text: str, language: str) -> str | None:
        try:
            from gtts import gTTS  # type: ignore
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as audio_file:
                temp_audio_path = Path(audio_file.name)
            gTTS(text=text, lang=language, slow=False).save(str(temp_audio_path))
            audio_bytes = temp_audio_path.read_bytes()
            temp_audio_path.unlink(missing_ok=True)
            return "data:audio/mpeg;base64," + base64.b64encode(audio_bytes).decode("ascii")
        except Exception as exc:
            safe_print(f"gTTS Error: {exc}")
            return None

    @staticmethod
    def _convert_numbers_to_arabic_words(text: str) -> str:
        ones = ["", "واحد", "اثنان", "ثلاثة", "أربعة", "خمسة", "ستة", "سبعة", "ثمانية", "تسعة"]
        tens = ["", "", "عشرون", "ثلاثون", "أربعون", "خمسون", "ستون", "سبعون", "ثمانون", "تسعون"]

        def number_to_words(value: int) -> str:
            if value == 0:
                return "صفر"
            if value < 10:
                return ones[value]
            if value < 100:
                return tens[value // 10] + ((" و" + ones[value % 10]) if value % 10 else "")
            return str(value)

        return re.sub(r"\d+", lambda match: number_to_words(int(match.group())), text)

    @staticmethod
    def _dependency_help() -> str:
        return (
            "For Windows/laptop heavy RAG install: python -m pip install -r NLP1.1\\requirements.txt pyaudio. "
            "For Raspberry Pi lightweight RAG install: python3 -m pip install -r requirements-rpi.txt "
            "and set PLANB_LIGHT_RAG=1."
        )
