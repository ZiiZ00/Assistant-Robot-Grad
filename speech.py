"""Fail-safe speech output and input abstractions."""
from __future__ import annotations

import json
import math
import os
import asyncio
import importlib.util
from pathlib import Path
import queue
import shutil
import subprocess
import struct
import tempfile
import threading
import time
import wave
from typing import Callable, Optional

from env_utils import get_env_first
from logging_utils import safe_print


SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2
CHUNK_FRAMES = 4000
EXPECTED_VOSK_DIRS = ("am", "conf", "graph", "ivector")


class TextToSpeech:
    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self.engine_name = "timed simulation"
        self._pyttsx3_engine = None
        self._espeak_ng = shutil.which("espeak-ng")
        self._requested_engine = (get_env_first("PLANB_TTS_ENGINE") or "").strip().lower()
        self._edge_voice_en = get_env_first("PLANB_TTS_VOICE_EN") or "en-US-GuyNeural"
        self._edge_voice_ar = get_env_first("PLANB_TTS_VOICE_AR") or "ar-EG-ShakirNeural"
        self._edge_available = importlib.util.find_spec("edge_tts") is not None
        self._eleven_api_key = get_env_first("ELEVEN_API_KEY", "ELEVENLABS_API_KEY")
        self._eleven_voice_id = get_env_first("ELEVEN_VOICE_ID", "ELEVENLABS_VOICE_ID")
        self._jobs: "queue.Queue[tuple[str, str, Callable[[], None]]]" = queue.Queue()
        self._cancelled = threading.Event()
        safe_print(f"TTS enabled: {enabled}")
        safe_print(f"TTS engine requested: {self._requested_engine or 'auto'}")
        safe_print(f"edge-tts available: {self._edge_available}")
        safe_print(f"ElevenLabs API key exists: {bool(self._eleven_api_key)}")
        safe_print(f"ElevenLabs voice id exists: {bool(self._eleven_voice_id)}")
        if self._eleven_voice_id:
            safe_print("Using chatbot selected voice")
        if enabled:
            try:
                import pyttsx3  # type: ignore
                self._pyttsx3_engine = pyttsx3.init()
            except Exception as exc:
                safe_print(f"TTS exception: {exc}")
        safe_print(f"TTS engine selected: {self._engine_for_language('en')}")
        if self._espeak_ng:
            safe_print(f"TTS Arabic fallback available: espeak-ng at {self._espeak_ng}")
        threading.Thread(target=self._worker, daemon=True).start()

    def speak(self, text: str, language: str = "en", on_done: Callable[[], None] | None = None) -> None:
        self._cancelled.clear()
        self._jobs.put((text, language, on_done or (lambda: None)))

    def stop(self) -> None:
        self._cancelled.set()
        if self._pyttsx3_engine:
            try:
                self._pyttsx3_engine.stop()
            except Exception:
                pass
        while not self._jobs.empty():
            try:
                self._jobs.get_nowait()
            except queue.Empty:
                break

    def _worker(self) -> None:
        while True:
            text, language, on_done = self._jobs.get()
            selected_engine = self._engine_for_language(language)
            safe_print(f"TTS language: {language}")
            safe_print(f"TTS engine selected: {selected_engine}")
            safe_print(f"TTS speaking: {text}")
            try:
                self._speak_with_fallbacks(text, language, selected_engine)
            except Exception as exc:
                safe_print(f"TTS exception: {exc}")
                safe_print("TTS fallback: timed simulation")
                self._simulate_speech_delay(text)
            if not self._cancelled.is_set():
                on_done()

    def _engine_for_language(self, language: str) -> str:
        if not self.enabled:
            return "timed simulation"
        if self._requested_engine == "edge":
            return "edge-tts"
        if self._requested_engine == "elevenlabs" and self._eleven_api_key and self._eleven_voice_id:
            return "elevenlabs"
        if self._requested_engine == "gtts":
            return "gTTS"
        if self._requested_engine in {"pyttsx3", "espeak-ng", "timed simulation"}:
            return self._requested_engine
        if not self._requested_engine and self._eleven_api_key and self._eleven_voice_id:
            return "elevenlabs"
        if self._edge_available:
            return "edge-tts"
        return "gTTS"

    def _fallback_engine_for_language(self, language: str) -> str:
        if self._edge_available:
            return "edge-tts"
        return self._local_fallback_engine_for_language(language)

    def _local_fallback_engine_for_language(self, language: str) -> str:
        if language == "ar" and self._espeak_ng:
            return "espeak-ng"
        if language != "ar" and self._pyttsx3_engine:
            return "pyttsx3"
        return "timed simulation"

    def _speak_with_fallbacks(self, text: str, language: str, selected_engine: str) -> None:
        if selected_engine == "elevenlabs" and not self._cancelled.is_set():
            if self._speak_elevenlabs(text, language):
                return
            selected_engine = self._fallback_engine_for_language(language)
            safe_print(f"TTS fallback: {selected_engine}")

        if selected_engine == "edge-tts" and not self._cancelled.is_set():
            if self._speak_edge_tts(text, language):
                return
            selected_engine = "gTTS"
            safe_print(f"TTS fallback: {selected_engine}")

        if selected_engine == "gTTS" and not self._cancelled.is_set():
            if self._speak_gtts(text, language):
                return
            selected_engine = self._local_fallback_engine_for_language(language)
            safe_print(f"TTS fallback: {selected_engine}")

        if selected_engine == "pyttsx3" and not self._cancelled.is_set():
            try:
                self._speak_pyttsx3(text, language)
                return
            except Exception as exc:
                safe_print(f"TTS exception: {exc}")
                selected_engine = "espeak-ng" if language == "ar" and self._espeak_ng else "timed simulation"
                safe_print(f"TTS fallback: {selected_engine}")

        if selected_engine == "espeak-ng" and not self._cancelled.is_set():
            try:
                self._speak_espeak_ng(text)
                return
            except Exception as exc:
                safe_print(f"TTS exception: {exc}")
                safe_print("TTS fallback: timed simulation")

        safe_print("TTS fallback: timed simulation")
        self._simulate_speech_delay(text)

    def _speak_edge_tts(self, text: str, language: str) -> bool:
        if not self._edge_available:
            safe_print("edge-tts exception: module is not installed")
            return False
        voice = self._edge_voice_ar if language == "ar" else self._edge_voice_en
        safe_print(f"edge-tts voice selected: {voice}")
        audio_path: Path | None = None
        try:
            import edge_tts  # type: ignore
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as audio_file:
                audio_path = Path(audio_file.name)

            async def save_audio() -> None:
                communicate = edge_tts.Communicate(text, voice)
                await communicate.save(str(audio_path))

            asyncio.run(save_audio())
            safe_print(f"edge-tts output file: {audio_path}")
            self._play_audio_file(audio_path)
            return True
        except Exception as exc:
            safe_print(f"edge-tts exception: {exc}")
            return False
        finally:
            if audio_path:
                try:
                    audio_path.unlink(missing_ok=True)
                except Exception as exc:
                    safe_print(f"TTS audio cleanup exception: {exc}")

    def _speak_gtts(self, text: str, language: str) -> bool:
        audio_path: Path | None = None
        try:
            from gtts import gTTS  # type: ignore
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as audio_file:
                audio_path = Path(audio_file.name)
            gTTS(text=text, lang=language, slow=False).save(str(audio_path))
            safe_print(f"gTTS output file: {audio_path}")
            self._play_audio_file(audio_path)
            return True
        except Exception as exc:
            safe_print(f"gTTS exception: {exc}")
            return False
        finally:
            if audio_path:
                try:
                    audio_path.unlink(missing_ok=True)
                except Exception as exc:
                    safe_print(f"TTS audio cleanup exception: {exc}")

    def _speak_elevenlabs(self, text: str, language: str) -> bool:
        safe_print("ElevenLabs request started")
        audio_path: Path | None = None
        try:
            import requests  # type: ignore
            response = requests.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{self._eleven_voice_id}",
                headers={
                    "xi-api-key": self._eleven_api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "text": text,
                    "model_id": "eleven_multilingual_v2",
                    "voice_settings": {
                        "stability": 0.5,
                        "similarity_boost": 0.75,
                    },
                },
                timeout=60,
            )
            safe_print(f"ElevenLabs response status: {response.status_code}")
            if response.status_code != 200:
                safe_print(f"ElevenLabs exception: {response.text}")
                return False
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as audio_file:
                audio_file.write(response.content)
                audio_path = Path(audio_file.name)
            safe_print(f"TTS audio file created: {audio_path}")
            self._play_audio_file(audio_path)
            return True
        except Exception as exc:
            safe_print(f"ElevenLabs exception: {exc}")
            return False
        finally:
            if audio_path:
                try:
                    audio_path.unlink(missing_ok=True)
                except Exception as exc:
                    safe_print(f"TTS audio cleanup exception: {exc}")

    def _play_audio_file(self, audio_path: Path) -> None:
        safe_print("TTS playback started")
        try:
            if os.name == "nt":
                self._play_audio_windows(audio_path)
            else:
                self._play_audio_posix(audio_path)
            safe_print("TTS playback finished")
        except Exception as exc:
            safe_print(f"TTS playback exception: {exc}")
            raise

    @staticmethod
    def _play_audio_windows(audio_path: Path) -> None:
        escaped_path = str(audio_path).replace("'", "''")
        script = (
            "Add-Type -AssemblyName presentationCore; "
            "$player = New-Object System.Windows.Media.MediaPlayer; "
            f"$player.Open([Uri]'{escaped_path}'); "
            "$player.Play(); "
            "while (-not $player.NaturalDuration.HasTimeSpan) { Start-Sleep -Milliseconds 100 }; "
            "$duration = [int]$player.NaturalDuration.TimeSpan.TotalMilliseconds + 500; "
            "Start-Sleep -Milliseconds $duration; "
            "$player.Close()"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            check=True,
            timeout=120,
        )

    @staticmethod
    def _play_audio_posix(audio_path: Path) -> None:
        suffix = audio_path.suffix.lower()
        if suffix == ".wav":
            players = (
                ("aplay", ["aplay", str(audio_path)]),
                ("ffplay", ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(audio_path)]),
            )
        else:
            players = (
                ("mpg123", ["mpg123", "-q", str(audio_path)]),
                ("ffplay", ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(audio_path)]),
                ("mpg321", ["mpg321", "-q", str(audio_path)]),
                ("cvlc", ["cvlc", "--play-and-exit", "--quiet", str(audio_path)]),
            )
        for executable, command in players:
            if shutil.which(executable):
                safe_print(f"edge-tts playback command: {' '.join(command)}")
                subprocess.run(command, check=True, timeout=120)
                return
        if suffix == ".wav":
            raise RuntimeError("No WAV playback command found. Install aplay or ffmpeg/ffplay.")
        raise RuntimeError("No MP3 playback command found. Install mpg123 or ffmpeg/ffplay.")

    def _speak_pyttsx3(self, text: str, language: str) -> None:
        if not self._pyttsx3_engine:
            raise RuntimeError("pyttsx3 engine is unavailable")
        self._select_voice(language)
        self._pyttsx3_engine.say(text)
        self._pyttsx3_engine.runAndWait()

    def _speak_espeak_ng(self, text: str) -> None:
        subprocess.run(
            [self._espeak_ng or "espeak-ng", "-v", "ar", text],
            check=True,
            timeout=max(4.0, min(30.0, len(text) / 8)),
        )

    def _simulate_speech_delay(self, text: str) -> None:
        deadline = time.monotonic() + min(6.0, max(1.2, len(text) / 28))
        while time.monotonic() < deadline and not self._cancelled.wait(0.1):
            pass

    def _has_voice(self, language: str) -> bool:
        if not self._pyttsx3_engine:
            return False
        target = "ar" if language == "ar" else "en"
        try:
            return any(self._voice_matches(voice, target)
                       for voice in self._pyttsx3_engine.getProperty("voices"))
        except Exception as exc:
            safe_print(f"TTS exception: {exc}")
            return False

    def _select_voice(self, language: str) -> None:
        if not self._pyttsx3_engine:
            return
        target = "ar" if language == "ar" else "en"
        try:
            for voice in self._pyttsx3_engine.getProperty("voices"):
                if self._voice_matches(voice, target):
                    self._pyttsx3_engine.setProperty("voice", voice.id)
                    safe_print(f"TTS pyttsx3 voice selected: {voice.id}")
                    break
        except Exception as exc:
            safe_print(f"TTS exception: {exc}")

    @staticmethod
    def _voice_matches(voice: object, target: str) -> bool:
        descriptor = f"{getattr(voice, 'id', '')} {getattr(voice, 'name', '')} {getattr(voice, 'languages', '')}".lower()
        if target == "ar":
            return any(token in descriptor for token in ("arab", "arabic", "ar-", "ar_", "ar "))
        return any(token in descriptor for token in ("english", "en-", "en_", "en-us", "en-gb", " en "))


def expected_vosk_structure_text(base: str | Path = "models/vosk") -> str:
    base_path = Path(base)
    return "\n".join(str(base_path / name) for name in EXPECTED_VOSK_DIRS)


def resolve_vosk_model_path(base_model_path: str | Path, language: str) -> Path:
    base = Path(base_model_path)
    parent = base.parent
    if language == "ar":
        language_model = parent / "vosk_ar"
        return language_model
    language_model = parent / "vosk_en"
    if language_model.is_dir():
        return language_model
    return base


def print_stt_environment(base_model_path: str | Path = "models/vosk") -> None:
    base = Path(base_model_path)
    parent = base.parent
    safe_print(f"models/vosk_en exists: {(parent / 'vosk_en').is_dir()}")
    safe_print(f"models/vosk_ar exists: {(parent / 'vosk_ar').is_dir()}")
    safe_print(f"models/vosk fallback exists: {base.is_dir()}")
    print_microphone_devices()


def missing_model_message(language: str, model_path: str | Path) -> str:
    if language == "ar":
        return "Arabic Vosk model missing at models/vosk_ar. Typed input is still available."
    return "English Vosk model missing. Typed input is still available."


def model_has_expected_structure(model_path: str | Path) -> bool:
    path = Path(model_path)
    return path.is_dir() and all((path / name).exists() for name in EXPECTED_VOSK_DIRS)


def pcm_rms(pcm: bytes) -> float:
    if len(pcm) < 2:
        return 0.0
    sample_count = len(pcm) // 2
    total = 0
    for (sample,) in struct.iter_unpack("<h", pcm[:sample_count * 2]):
        total += sample * sample
    return math.sqrt(total / max(1, sample_count))


def resample_pcm_nearest(pcm: bytes, source_rate: int, target_rate: int = SAMPLE_RATE) -> bytes:
    if source_rate == target_rate or len(pcm) < 2:
        return pcm
    samples = [sample for (sample,) in struct.iter_unpack("<h", pcm[:len(pcm) // 2 * 2])]
    if not samples:
        return b""
    output_count = max(1, int(len(samples) * target_rate / source_rate))
    output = bytearray()
    for out_index in range(output_count):
        source_index = min(len(samples) - 1, int(out_index * source_rate / target_rate))
        output.extend(struct.pack("<h", samples[source_index]))
    return bytes(output)


def print_microphone_devices() -> None:
    try:
        import pyaudio  # type: ignore
    except Exception as exc:
        safe_print(f"Available microphone devices: unavailable ({exc})")
        return
    audio = pyaudio.PyAudio()
    try:
        count = audio.get_device_count()
        safe_print("Available microphone devices:")
        safe_print(f"STT microphone devices found: {count}")
        for index in range(count):
            info = audio.get_device_info_by_index(index)
            inputs = int(info.get("maxInputChannels", 0))
            safe_print(f"{index}: {info.get('name', 'Unknown')} | "
                       f"inputs={inputs} | default_rate={info.get('defaultSampleRate', '')}")
    except Exception as exc:
        safe_print(f"Available microphone devices: unavailable ({exc})")
    finally:
        audio.terminate()


def record_microphone(seconds: float = 5.0, mic_device_index: int | None = None,
                      output_wav: str | Path | None = None) -> dict[str, object]:
    try:
        import pyaudio  # type: ignore
    except Exception as exc:
        safe_print(f"Microphone unavailable. Typed input is still available.")
        safe_print(f"STT exception: {exc}")
        return {"pcm": b"", "chunks": [], "duration": 0.0, "rms": 0.0, "sample_rate": SAMPLE_RATE}

    audio = pyaudio.PyAudio()
    stream = None
    chunks: list[bytes] = []
    selected_info: dict[str, object] = {}
    native_rate = SAMPLE_RATE
    try:
        if mic_device_index is None:
            selected_info = audio.get_default_input_device_info()
        else:
            selected_info = audio.get_device_info_by_index(mic_device_index)
        selected_index = int(selected_info.get("index", mic_device_index if mic_device_index is not None else -1))
        safe_print(f"Selected microphone device index: {selected_index if selected_index >= 0 else 'default'}")
        safe_print(f"Selected microphone name: {selected_info.get('name', 'Unknown')}")
        safe_print(f"Selected microphone sample rate: {selected_info.get('defaultSampleRate', '')}")

        open_args = {
            "format": pyaudio.paInt16,
            "channels": CHANNELS,
            "rate": SAMPLE_RATE,
            "input": True,
            "frames_per_buffer": CHUNK_FRAMES,
        }
        if mic_device_index is not None:
            open_args["input_device_index"] = mic_device_index
        try:
            stream = audio.open(**open_args)
            native_rate = SAMPLE_RATE
        except Exception as exc:
            safe_print(f"STT exception: could not open microphone at 16000 Hz mono: {exc}")
            native_rate = int(float(selected_info.get("defaultSampleRate", SAMPLE_RATE)))
            open_args["rate"] = native_rate
            open_args["frames_per_buffer"] = max(1000, int(native_rate / 4))
            stream = audio.open(**open_args)
            safe_print(f"STT recording at {native_rate} Hz and resampling to 16000 Hz for Vosk.")

        stream.start_stream()
        started = time.monotonic()
        while time.monotonic() - started < seconds:
            chunks.append(stream.read(int(open_args["frames_per_buffer"]), exception_on_overflow=False))
        duration = time.monotonic() - started
    except Exception as exc:
        safe_print("Microphone unavailable. Typed input is still available.")
        safe_print(f"STT exception: {exc}")
        duration = 0.0
    finally:
        if stream is not None:
            try:
                stream.stop_stream(); stream.close()
            except Exception:
                pass
        audio.terminate()

    native_pcm = b"".join(chunks)
    pcm = resample_pcm_nearest(native_pcm, native_rate, SAMPLE_RATE)
    rms = pcm_rms(pcm)
    safe_print(f"STT audio chunks captured: {len(chunks)}")
    safe_print(f"STT audio duration seconds: {duration:.2f}")
    safe_print(f"STT audio RMS: {rms:.2f}")
    safe_print(f"STT audio captured: {'yes' if rms > 50 else 'no or very quiet'}")
    if output_wav:
        wav_path = Path(output_wav)
        with wave.open(str(wav_path), "wb") as wav:
            wav.setnchannels(CHANNELS)
            wav.setsampwidth(SAMPLE_WIDTH)
            wav.setframerate(SAMPLE_RATE)
            wav.writeframes(pcm)
        safe_print(f"Saved microphone test WAV: {wav_path}")
    return {
        "pcm": pcm,
        "chunks": chunks,
        "duration": duration,
        "rms": rms,
        "sample_rate": SAMPLE_RATE,
        "selected_info": selected_info,
    }


def recognize_pcm_with_vosk(pcm: bytes, model_path: str | Path, language: str = "en") -> tuple[str, str]:
    model = Path(model_path)
    safe_print(f"Selected STT language: {language}")
    safe_print(f"Selected Vosk model path: {model}")
    safe_print(f"Vosk model exists: {model.is_dir()}")
    if not model.is_dir():
        safe_print(missing_model_message(language, model))
        safe_print("Expected Vosk folder structure:")
        safe_print(expected_vosk_structure_text(model))
        return "", ""
    if not model_has_expected_structure(model):
        safe_print("WARNING: Vosk model folder exists but expected subfolders were not all found.")
        safe_print("Expected Vosk folder structure:")
        safe_print(expected_vosk_structure_text(model))
    try:
        from vosk import KaldiRecognizer, Model  # type: ignore
        recognizer = KaldiRecognizer(Model(str(model)), SAMPLE_RATE)
        partials: list[str] = []
        for offset in range(0, len(pcm), CHUNK_FRAMES * SAMPLE_WIDTH):
            chunk = pcm[offset:offset + CHUNK_FRAMES * SAMPLE_WIDTH]
            if recognizer.AcceptWaveform(chunk):
                partials.append(recognizer.Result())
            else:
                partial = recognizer.PartialResult()
                if partial:
                    partials.append(partial)
        for partial in partials[-5:]:
            safe_print(f"STT raw partial result: {partial}")
        raw_result = recognizer.FinalResult()
        safe_print(f"STT raw final result: {raw_result}")
        recognized = json.loads(raw_result).get("text", "").strip()
        safe_print(f"STT recognized: {recognized}")
        return recognized, raw_result
    except Exception as exc:
        safe_print(f"STT exception: {exc}")
        return "", ""


class SpeechRecognizer:
    def __init__(self, enabled: bool = False, model_path: str = "models/vosk",
                 mic_device_index: int | None = None) -> None:
        self.enabled, self.base_model_path = enabled, Path(model_path)
        self.model_path = str(self.base_model_path)
        self.mic_device_index = mic_device_index
        self.available = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._result_callback: Callable[[Optional[str]], None] | None = None
        self._warned = False
        self._record_started_at = 0.0
        self._language = "en"
        safe_print(f"STT enabled: {enabled}")
        safe_print(f"STT model path: {self.base_model_path}")
        safe_print(f"STT model exists: {self.base_model_path.is_dir()}")
        if not enabled:
            safe_print("STT unavailable: disabled. Typed questions will still work.")
            return
        print_microphone_devices()
        try:
            import pyaudio  # type: ignore  # noqa: F401
            import vosk  # type: ignore  # noqa: F401
            self.available = True
            safe_print("STT engine selected: Vosk")
            safe_print(f"Selected microphone device index: {mic_device_index if mic_device_index is not None else 'default'}")
        except Exception as exc:
            self._warn_unavailable(exc)

    def _warn_unavailable(self, exc: object) -> None:
        self.available = False
        if not self._warned:
            safe_print(f"STT exception: {exc}")
            if "microphone" in str(exc).lower() or "input device" in str(exc).lower():
                safe_print("Microphone unavailable. Typed input is still available.")
            elif "models/vosk" in str(exc).lower() or "model" in str(exc).lower():
                safe_print("Vosk model missing at models/vosk. Typed input is still available.")
            else:
                safe_print("STT unavailable. Typed input is still available.")
            self._warned = True

    @property
    def active(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop_event.is_set()

    def cancel(self) -> None:
        """Silently cancel capture when leaving a screen."""
        self._result_callback = None
        self._stop_event.set()

    def stop(self) -> None:
        self.cancel()

    def start(self, language: str) -> bool:
        """Start microphone capture; recognition is deferred until Submit."""
        if not self.available:
            safe_print("STT listening not started: unavailable")
            return False
        self.cancel()
        self._stop_event = threading.Event()
        self._result_callback = None
        self._record_started_at = time.monotonic()
        self._language = language
        self.model_path = str(resolve_vosk_model_path(self.base_model_path, language))
        safe_print(f"Selected UI language: {language}")
        safe_print(f"Selected STT language: {language}")
        safe_print(f"Selected Vosk model path: {self.model_path}")
        safe_print(f"Vosk model exists: {Path(self.model_path).is_dir()}")
        if not Path(self.model_path).is_dir():
            safe_print(missing_model_message(language, self.model_path))
            safe_print("Expected Vosk folder structure:")
            safe_print(expected_vosk_structure_text(self.model_path))
            return False
        safe_print("STT listening started")
        self._thread = threading.Thread(
            target=self._record_worker, args=(self._stop_event,), daemon=True)
        self._thread.start()
        return True

    def stop_and_recognize(self, on_result: Callable[[Optional[str]], None]) -> None:
        """Stop capture now and recognize in the existing background thread."""
        safe_print("STT listening stopped")
        if not self.available or self._thread is None or not self._thread.is_alive():
            safe_print("STT raw result: ")
            safe_print("STT recognized: ")
            on_result(None)
            return
        self._result_callback = on_result
        self._stop_event.set()

    def listen(self, language: str, on_result: Callable[[Optional[str]], None], seconds: int = 8) -> None:
        """Compatibility helper for callers that still want timed recognition."""
        if not self.start(language):
            on_result(None)
            return
        timer = threading.Timer(seconds, lambda: self.stop_and_recognize(on_result))
        timer.daemon = True
        timer.start()

    def _record_worker(self, cancel_event: threading.Event) -> None:
        chunks: list[bytes] = []
        native_rate = SAMPLE_RATE
        started = time.monotonic()
        try:
            import pyaudio  # type: ignore
            audio = pyaudio.PyAudio()
            stream = None
            open_args = {
                "format": pyaudio.paInt16,
                "channels": CHANNELS,
                "rate": SAMPLE_RATE,
                "input": True,
                "frames_per_buffer": CHUNK_FRAMES,
            }
            try:
                if self.mic_device_index is not None:
                    open_args["input_device_index"] = self.mic_device_index
                    device_info = audio.get_device_info_by_index(self.mic_device_index)
                else:
                    device_info = audio.get_default_input_device_info()
                safe_print(f"Selected microphone device index: {self.mic_device_index if self.mic_device_index is not None else 'default'}")
                safe_print(f"Selected microphone name: {device_info.get('name', 'Unknown')}")
                safe_print(f"Selected microphone sample rate: {device_info.get('defaultSampleRate', '')}")
                try:
                    stream = audio.open(**open_args)
                except Exception as exc:
                    safe_print(f"STT exception: could not open microphone at 16000 Hz mono: {exc}")
                    native_rate = int(float(device_info.get("defaultSampleRate", SAMPLE_RATE)))
                    open_args["rate"] = native_rate
                    open_args["frames_per_buffer"] = max(1000, int(native_rate / 4))
                    stream = audio.open(**open_args)
                    safe_print(f"STT recording at {native_rate} Hz and resampling to 16000 Hz for Vosk.")
                stream.start_stream()
                while not cancel_event.is_set():
                    chunks.append(stream.read(int(open_args["frames_per_buffer"]), exception_on_overflow=False))
            finally:
                if stream is not None:
                    try:
                        stream.stop_stream(); stream.close()
                    except Exception:
                        pass
                audio.terminate()
        except Exception as exc:
            self._warn_unavailable(exc)
        callback = self._result_callback
        if callback is None:
            return
        duration = time.monotonic() - started
        native_pcm = b"".join(chunks)
        pcm = resample_pcm_nearest(native_pcm, native_rate, SAMPLE_RATE)
        safe_print(f"STT audio chunks captured: {len(chunks)}")
        safe_print(f"STT audio duration seconds: {duration:.2f}")
        safe_print(f"STT audio RMS: {pcm_rms(pcm):.2f}")
        recognized, _raw_result = recognize_pcm_with_vosk(pcm, self.model_path, self._language)
        safe_print(f"STT recognized: {recognized}")
        callback(recognized or None)


def list_audio_devices() -> None:
    """Print every PyAudio device and its input/output channel counts."""
    try:
        import pyaudio  # type: ignore
    except Exception as exc:
        safe_print(f"PyAudio unavailable: {exc}")
        return
    audio = pyaudio.PyAudio()
    try:
        for index in range(audio.get_device_count()):
            info = audio.get_device_info_by_index(index)
            safe_print(f"{index}: {info.get('name', 'Unknown')} | "
                       f"inputs={int(info.get('maxInputChannels', 0))} | "
                       f"outputs={int(info.get('maxOutputChannels', 0))} | "
                       f"default_rate={info.get('defaultSampleRate', '')}")
    finally:
        audio.terminate()
