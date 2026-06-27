"""Plan B museum guide entry point."""
from __future__ import annotations

import argparse
import importlib
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from typing import Callable

from app_controller import AppController
from arduino_serial_manager import ArduinoSerialManager
from arrival_detector import SimulatedEncoderSource
from env_utils import get_env_first, load_project_dotenv
from keyboard_driver import KeyboardDriver
import ui
from logging_utils import safe_print
from museum_chatbot_engine import MuseumChatbotEngine
from speech import (
    SpeechRecognizer,
    TextToSpeech,
    list_audio_devices,
    recognize_pcm_with_vosk,
    print_stt_environment,
    record_microphone,
    resolve_vosk_model_path,
)


CHATBOT_DEPENDENCY_HELP = (
    "Install Windows/laptop heavy chatbot dependencies with: "
    "python -m pip install -r NLP1.1\\requirements.txt pyaudio"
)
CHATBOT_RPI_HELP = (
    "Install Raspberry Pi lightweight chatbot dependencies with: "
    "python3 -m pip install -r requirements-rpi.txt"
)
EMBEDDING_MODEL_HELP = (
    "If the embedding model is missing, pre-download it with: "
    "python -c \"from sentence_transformers import SentenceTransformer; "
    "SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')\""
)


def _run_check_with_timeout(label: str, callback: Callable[[], object], timeout_seconds: float = 45.0) -> bool:
    result_queue: "queue.Queue[tuple[bool, str]]" = queue.Queue()

    def worker() -> None:
        try:
            callback()
            result_queue.put((True, "OK"))
        except Exception as exc:
            result_queue.put((False, f"{type(exc).__name__}: {exc}"))

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    try:
        ok, message = result_queue.get(timeout=timeout_seconds)
    except queue.Empty:
        safe_print(f"{label}: TIMEOUT after {timeout_seconds:.0f} seconds")
        return False
    safe_print(f"{label}: {'OK' if ok else 'FAILED'}")
    if not ok:
        safe_print(f"{label} exception: {message}")
    return ok


def _run_value_with_timeout(label: str, callback: Callable[[], object], timeout_seconds: float = 90.0) -> object | None:
    result_queue: "queue.Queue[tuple[bool, object]]" = queue.Queue()

    def worker() -> None:
        try:
            result_queue.put((True, callback()))
        except Exception as exc:
            result_queue.put((False, f"{type(exc).__name__}: {exc}"))

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    try:
        ok, value = result_queue.get(timeout=timeout_seconds)
    except queue.Empty:
        safe_print(f"{label}: TIMEOUT after {timeout_seconds:.0f} seconds")
        return None
    if not ok:
        safe_print(f"{label}: FAILED")
        safe_print(f"{label} exception: {value}")
        return None
    return value


def test_integrated_chatbot_env() -> None:
    os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "5")
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "15")
    base = Path(__file__).resolve().parent
    chatbot_root = base / "NLP1.1"
    engine = MuseumChatbotEngine(chatbot_root)

    safe_print(f"NLP1.1 folder exists: {chatbot_root.is_dir()}")
    safe_print(f"NLP1.1/vectorstore exists: {(chatbot_root / 'vectorstore').is_dir()}")
    safe_print(f"NLP1.1/Data exists: {(chatbot_root / 'Data').is_dir()}")
    safe_print(f"Heavy RAG available: {engine.heavy_rag_available}")
    safe_print(f"Lightweight RAG mode: {engine.lightweight_mode}")
    if engine.lightweight_mode:
        safe_print(f"Heavy RAG available: {'False or skipped'}")
        light_engine = engine.load_lightweight_rag()
        safe_print(f"Loaded document chunks: {light_engine.chunk_count}")
    else:
        safe_print(f"Heavy RAG unavailable reason: {engine.heavy_unavailable_reason}")
    safe_print(f"GROQ_API_KEY exists: {bool(get_env_first('GROQ_API_KEY'))}")
    safe_print(f"ElevenLabs API key exists: {bool(get_env_first('ELEVEN_API_KEY', 'ELEVENLABS_API_KEY'))}")
    safe_print(f"ElevenLabs voice id exists: {bool(get_env_first('ELEVEN_VOICE_ID', 'ELEVENLABS_VOICE_ID'))}")

    for module_name in (
        "faiss",
        "sentence_transformers",
        "langchain",
        "langchain_community",
        "langchain_huggingface",
        "deep_translator",
        "gtts",
        "requests",
    ):
        try:
            importlib.import_module(module_name)
            safe_print(f"Import {module_name}: OK")
        except Exception as exc:
            safe_print(f"Import {module_name}: FAILED")
            safe_print(f"Import {module_name} exception: {type(exc).__name__}: {exc}")

    if engine.lightweight_mode:
        embedding_ok = False
        vectorstore_ok = False
        safe_print("Embedding model load: SKIPPED because lightweight RAG mode is active")
        safe_print("Vectorstore load: SKIPPED because lightweight RAG mode is active")
    else:
        embedding_ok = _run_check_with_timeout(
            "Embedding model load",
            engine.load_embedding_model,
            timeout_seconds=45.0,
        )
        if embedding_ok:
            vectorstore_ok = _run_check_with_timeout(
                "Vectorstore load",
                engine.load_vectorstore,
                timeout_seconds=45.0,
            )
        else:
            vectorstore_ok = False
            safe_print("Vectorstore load: SKIPPED because embedding model did not load")
    safe_print(f"Embedding model loaded: {embedding_ok}")
    safe_print(f"Vectorstore loaded: {vectorstore_ok}")
    if engine.lightweight_mode:
        safe_print(CHATBOT_RPI_HELP)
        safe_print("Set Pi light mode with: export PLANB_LIGHT_RAG=1")
    if (not engine.lightweight_mode and (not embedding_ok or not vectorstore_ok)) or not get_env_first("GROQ_API_KEY"):
        safe_print(CHATBOT_DEPENDENCY_HELP)
        safe_print(EMBEDDING_MODEL_HELP)
        safe_print("Set Groq key with: $env:GROQ_API_KEY=\"your-groq-key\"")
        safe_print("Optional ElevenLabs setup: $env:ELEVEN_API_KEY=\"your-key\"; $env:ELEVEN_VOICE_ID=\"your-voice-id\"")


def test_integrated_chatbot_typed(language: str, question: str | None, speak_answer: bool = False) -> None:
    if not question or not question.strip():
        safe_print("Missing typed question. Use: --question \"Who is Ramses II?\"")
        return
    engine = MuseumChatbotEngine(Path(__file__).resolve().parent / "NLP1.1")
    safe_print(f"Selected language: {language}")
    safe_print(f"Using typed question: {question}")
    answer = _run_value_with_timeout(
        "Integrated typed answer",
        lambda: engine.answer(question, language),
        timeout_seconds=90.0,
    )
    if answer:
        safe_print(f"Final answer: {answer}")
        if speak_answer:
            done = threading.Event()
            TextToSpeech(True).speak(str(answer), language, done.set)
            if not done.wait(120):
                safe_print("TTS test timed out.")
    else:
        safe_print("Final answer: unavailable")
        safe_print(CHATBOT_DEPENDENCY_HELP)
        safe_print(EMBEDDING_MODEL_HELP)
        safe_print("Set Groq key with: $env:GROQ_API_KEY=\"your-groq-key\"")


def test_integrated_chatbot_voice(language: str, mic_device_index: int | None) -> None:
    engine = MuseumChatbotEngine(Path(__file__).resolve().parent / "NLP1.1")
    safe_print(f"Selected language: {language}")
    recognized = engine.listen(language, mic_device_index)
    safe_print(f"Recognized question: {recognized or ''}")
    if not recognized:
        safe_print("No recognized voice question. Typed input in the UI will still work.")
        safe_print(CHATBOT_DEPENDENCY_HELP)
        safe_print("Set Groq key with: $env:GROQ_API_KEY=\"your-groq-key\"")
        return
    answer = _run_value_with_timeout(
        "Integrated voice answer",
        lambda: engine.answer(recognized, language),
        timeout_seconds=90.0,
    )
    if answer:
        safe_print(f"Final answer: {answer}")
    else:
        safe_print("Final answer: unavailable")
        safe_print(CHATBOT_DEPENDENCY_HELP)
        safe_print(EMBEDDING_MODEL_HELP)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plan B museum tour guide")
    parser.add_argument("--demo", action="store_true", help="visitor-only real demo mode")
    parser.add_argument("--simulate", action="store_true", help="simulate encoder movement and arrival")
    parser.add_argument("--no-fullscreen", action="store_true", help="run in an 800x480 window")
    parser.add_argument("--debug-arrived-button", action="store_true", help="show manual arrival test button")
    parser.add_argument("--test-arabic-ui", action="store_true", help="show the Arabic shaping test screen")
    parser.add_argument("--serial-port", help="Arduino serial device, for example /dev/serial/by-id/...")
    parser.add_argument("--keyboard-drive", action="store_true", help="read W/S/A/D/Space/Q from this terminal")
    parser.add_argument("--drive-speed", type=int, default=120, help="forward/backward PWM (0-255)")
    parser.add_argument("--turn-speed", type=int, default=100, help="turning PWM (0-255)")
    parser.add_argument("--enable-tts", action="store_true", help="enable centralized TTS speech")
    parser.add_argument("--enable-stt", action="store_true", help="enable microphone recognition if installed")
    parser.add_argument("--mic-device-index", type=int, help="PyAudio input device index")
    parser.add_argument("--stt-language", choices=("en", "ar"), default="en",
                        help="language model to use for --test-stt-once")
    parser.add_argument("--language", choices=("en", "ar"), default="en",
                        help="language to use for integrated chatbot non-UI tests")
    parser.add_argument("--question", help="typed question for --test-integrated-chatbot-typed")
    parser.add_argument("--speak-answer", action="store_true",
                        help="speak the final answer in integrated chatbot typed tests")
    parser.add_argument("--list-audio-devices", action="store_true",
                        help="print PyAudio input/output devices and exit")
    parser.add_argument("--test-tts-en", action="store_true",
                        help="speak a short English TTS test and exit")
    parser.add_argument("--test-tts-ar", action="store_true",
                        help="speak a short Arabic TTS test and exit")
    parser.add_argument("--test-stt-env", action="store_true",
                        help="print STT dependency/model/microphone diagnostics and exit")
    parser.add_argument("--test-mic-record", action="store_true",
                        help="record 5 seconds from the selected microphone to test_mic.wav and exit")
    parser.add_argument("--test-stt-once", action="store_true",
                        help="record 5 seconds from the selected microphone, run Vosk once, and exit")
    parser.add_argument("--test-integrated-chatbot-env", action="store_true",
                        help="print NLP1.1 integrated chatbot dependency and vectorstore diagnostics")
    parser.add_argument("--test-integrated-chatbot-typed", action="store_true",
                        help="send --question to the integrated chatbot engine without opening Tkinter")
    parser.add_argument("--test-integrated-chatbot-voice", action="store_true",
                        help="record a question and send it to the integrated chatbot engine without opening Tkinter")
    return parser.parse_args()


def main() -> None:
    load_project_dotenv()
    args = parse_args()
    tts_requested = args.enable_tts or args.test_tts_en or args.test_tts_ar or args.speak_answer
    stt_requested = (args.enable_stt or args.test_stt_env or args.test_mic_record or args.test_stt_once
                     or args.test_integrated_chatbot_voice)
    safe_print(f"TTS enabled: {tts_requested}")
    safe_print(f"STT enabled: {stt_requested}")
    if args.test_integrated_chatbot_env:
        test_integrated_chatbot_env()
        return
    if args.test_integrated_chatbot_typed:
        test_integrated_chatbot_typed(args.language, args.question, args.speak_answer)
        return
    if args.test_integrated_chatbot_voice:
        test_integrated_chatbot_voice(args.language, args.mic_device_index)
        return
    if args.list_audio_devices:
        list_audio_devices()
        return
    if args.test_stt_env:
        print_stt_environment("models/vosk")
        return
    if args.test_mic_record:
        record_microphone(seconds=5.0, mic_device_index=args.mic_device_index, output_wav="test_mic.wav")
        return
    if args.test_stt_once:
        result = record_microphone(seconds=5.0, mic_device_index=args.mic_device_index, output_wav="test_mic.wav")
        model_path = resolve_vosk_model_path("models/vosk", args.stt_language)
        recognize_pcm_with_vosk(result.get("pcm", b""), model_path, args.stt_language)
        return
    if args.test_tts_en or args.test_tts_ar:
        done = threading.Event()
        tts = TextToSpeech(True)
        if args.test_tts_ar:
            tts.speak("أهلا بكم في المتحف المصري الكبير", "ar", done.set)
        else:
            tts.speak("Welcome to the Grand Egyptian Museum", "en", done.set)
        if not done.wait(20):
            safe_print("TTS test timed out.")
            tts.stop()
        return
    arduino = (ArduinoSerialManager(args.serial_port)
               if args.serial_port and not args.simulate and not args.test_arabic_ui else None)
    if arduino:
        arduino.start()
    elif args.demo:
        print("WARNING: --demo has no --serial-port; automatic arrival and motor driving are unavailable.")
    encoder_source = SimulatedEncoderSource() if args.simulate else arduino
    root = tk.Tk()
    root.title("Grand Egyptian Museum - Plan B")
    root.geometry("800x480")
    root.configure(bg="#07111f")
    root.attributes("-fullscreen", not args.no_fullscreen)
    root.bind("<Escape>", lambda _event: root.attributes("-fullscreen", False))
    if args.test_arabic_ui:
        ui.show_arabic_test_screen(root)
        root.mainloop()
        return
    controller = AppController(
        root,
        encoder_source=encoder_source,
        debug_arrived_button=args.debug_arrived_button,
        enable_tts=args.enable_tts,
        enable_stt=args.enable_stt,
        mic_device_index=args.mic_device_index,
    )
    keyboard = None
    if args.keyboard_drive:
        if arduino is None:
            print("Keyboard drive requires --serial-port; keyboard driving was not started.")
        else:
            keyboard = KeyboardDriver(
                arduino,
                lambda: controller.run_on_ui(controller.show_emergency),
                speed=args.drive_speed,
                turn_speed=args.turn_speed,
            )
            keyboard.start()
    if keyboard:
        controller.register_shutdown(keyboard.close)
    if arduino:
        controller.register_emergency(lambda: arduino.send_motor_command("S", 0))
        controller.register_shutdown(arduino.close)
    try:
        root.mainloop()
    finally:
        if keyboard:
            keyboard.close()
        if arduino:
            arduino.close()


if __name__ == "__main__":
    main()
