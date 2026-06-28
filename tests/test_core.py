import json
import tempfile
import threading
import time
import unittest
import json as json_module
from pathlib import Path
from unittest.mock import patch

import main as main_module
from arrival_detector import ArrivalDetector
from arduino_serial_manager import ArduinoSerialManager
from arabic_support import contains_arabic, shape_arabic_text
from chatbot import LocalChatbot
from feedback_storage import FeedbackStorage
from gemini_client import GeminiClient
from lightweight_rag_engine import LightweightRAGEngine
from main import parse_args
from museum_chatbot_engine import MuseumChatbotEngine
from env_utils import get_env_first
from speech import SpeechRecognizer, TextToSpeech, resolve_vosk_model_path
from ui import TEXT


ROOT = Path(__file__).resolve().parents[1]


class MovingThenStill:
    def __init__(self):
        self.value = 0
        self.reads = 0

    def read(self):
        self.reads += 1
        if self.reads < 5:
            self.value += 10
        return self.value, self.value


class CoreTests(unittest.TestCase):
    def test_arrival_requires_movement_then_stability(self):
        arrived = threading.Event()
        detector = ArrivalDetector(MovingThenStill(), stable_seconds=0.12, poll_seconds=0.02)
        detector.start(lambda _reason: arrived.set())
        self.assertTrue(arrived.wait(1.0))
        detector.stop()

    def test_static_encoder_does_not_arrive(self):
        arrived = threading.Event()
        source = type("Static", (), {"read": lambda self: (0, 0)})()
        detector = ArrivalDetector(source, stable_seconds=0.05, poll_seconds=0.01)
        detector.start(lambda _reason: arrived.set())
        self.assertFalse(arrived.wait(0.18))
        detector.stop()

    def test_chatbot_local_answer(self):
        qa_data = json.loads((ROOT / "data/qa.json").read_text(encoding="utf-8"))
        bot = LocalChatbot(qa_data)
        answer = bot.answer("what material is the mask made of", "tutankhamun_mask", "en")
        self.assertIn("gold", answer)

    def test_chatbot_searches_current_artifact_before_all_artifacts(self):
        qa_data = {
            "artifact": {"en": [{"questions": ["where is it"], "answer": "Artifact answer"}]},
            "other": {"en": [{"questions": ["where is it"], "answer": "Other answer"}]},
        }
        self.assertEqual(LocalChatbot(qa_data).answer(
            "Where is it?", "artifact", "en"), "Artifact answer")

    def test_chatbot_searches_other_artifacts_after_current(self):
        qa_data = json.loads((ROOT / "data/qa.json").read_text(encoding="utf-8"))
        answer = LocalChatbot(qa_data).answer(
            "who built the great pyramid?", "ramses_ii_statue", "en")
        self.assertIn("Khufu", answer)

    def test_unrelated_question_does_not_false_match_local_data(self):
        qa_data = json.loads((ROOT / "data/qa.json").read_text(encoding="utf-8"))
        answer = LocalChatbot(qa_data).answer(
            "what is the weather on mars", "ramses_ii_statue", "en")
        self.assertIsNone(answer)

    def test_arabic_local_question_matches(self):
        qa_data = json.loads((ROOT / "data/qa.json").read_text(encoding="utf-8"))
        answer = LocalChatbot(qa_data).answer(
            "مَنْ اكتشف مقبرة توت عنخ آمون؟", "tutankhamun_mask", "ar")
        self.assertIn("هوارد كارتر", answer)

    def test_chatbot_normalizes_arabic_letters_and_punctuation(self):
        normalized = LocalChatbot.normalize("  أَيْنَ، إِبْنُ خُوفُو؟ ", "ar")
        self.assertEqual(normalized, "اين ابن خوفو")

    def test_integrated_chatbot_engine_loads_without_heavy_dependencies(self):
        engine = MuseumChatbotEngine(ROOT / "NLP1.1")
        self.assertTrue(engine.available)
        self.assertEqual(engine.detect_language("What is this statue?"), "en")
        self.assertEqual(engine.detect_language("ما هذا التمثال؟"), "ar")

    def test_integrated_chatbot_can_force_lightweight_rag(self):
        with patch.dict("os.environ", {"PLANB_LIGHT_RAG": "1"}, clear=False):
            engine = MuseumChatbotEngine(ROOT / "NLP1.1")
        self.assertTrue(engine.available)
        self.assertFalse(engine.heavy_rag_available)
        self.assertTrue(engine.lightweight_mode)

    def test_integrated_chatbot_transcription_sends_selected_language(self):
        engine = MuseumChatbotEngine(ROOT / "NLP1.1")
        response = type("Response", (), {
            "status_code": 200,
            "json": lambda self: {"text": "Who is King Khufu?"},
            "text": "ok",
        })()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as wav_file:
            wav_path = Path(wav_file.name)
        try:
            with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}, clear=False), \
                 patch("requests.post", return_value=response) as post:
                recognized = engine._transcribe_audio(wav_path, "en")
        finally:
            wav_path.unlink(missing_ok=True)
        self.assertEqual(recognized, "Who is King Khufu?")
        self.assertEqual(post.call_args.kwargs["data"]["language"], "en")
        self.assertIn("/audio/transcriptions", post.call_args.args[0])

    def test_integrated_chatbot_transcription_sends_arabic_language(self):
        engine = MuseumChatbotEngine(ROOT / "NLP1.1")
        response = type("Response", (), {
            "status_code": 200,
            "json": lambda self: {"text": "من هو الملك خوفو؟"},
            "text": "ok",
        })()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as wav_file:
            wav_path = Path(wav_file.name)
        try:
            with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}, clear=False), \
                 patch("requests.post", return_value=response) as post:
                recognized = engine._transcribe_audio(wav_path, "ar")
        finally:
            wav_path.unlink(missing_ok=True)
        self.assertEqual(recognized, "من هو الملك خوفو؟")
        self.assertEqual(post.call_args.kwargs["data"]["language"], "ar")
        self.assertIn("/audio/transcriptions", post.call_args.args[0])

    def test_lightweight_rag_reads_txt_and_retrieves_without_heavy_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory) / "Data"
            data_dir.mkdir()
            (data_dir / "museum.txt").write_text(
                "Ramses II was a powerful pharaoh of ancient Egypt. "
                "The Tutankhamun mask is made of gold and precious stones. " * 20,
                encoding="utf-8",
            )
            engine = LightweightRAGEngine(data_dir)
            chunks = engine.retrieve("Who was Ramses II?", top_k=2)
        self.assertTrue(chunks)
        self.assertIn("Ramses II", chunks[0])

    def test_tour_uses_three_requested_artifact_ids(self):
        tours = json.loads((ROOT / "data/manual_tours.json").read_text(encoding="utf-8"))["tours"]
        expected = ["ramses_ii_statue", "tutankhamun_mask", "king_khufu"]
        self.assertEqual(tours["short"]["artifact_ids"], expected)
        self.assertEqual(tours["long"]["artifact_ids"], expected)

    def test_simulation_cli_keeps_speech_flags_and_serial_arg_separate(self):
        with patch("sys.argv", [
            "main.py", "--simulate", "--serial-port", "COM4",
            "--enable-tts", "--enable-stt", "--mic-device-index", "1", "--no-fullscreen",
        ]):
            args = parse_args()
        self.assertTrue(args.simulate)
        self.assertEqual(args.serial_port, "COM4")
        self.assertTrue(args.enable_tts)
        self.assertTrue(args.enable_stt)
        self.assertEqual(args.mic_device_index, 1)

    def test_direct_stt_test_cli_flags(self):
        with patch("sys.argv", ["main.py", "--test-mic-record", "--mic-device-index", "2"]):
            args = parse_args()
        self.assertTrue(args.test_mic_record)
        self.assertEqual(args.mic_device_index, 2)
        with patch("sys.argv", ["main.py", "--test-stt-once", "--stt-language", "ar"]):
            args = parse_args()
        self.assertTrue(args.test_stt_once)
        self.assertEqual(args.stt_language, "ar")

    def test_question_loop_labels_are_bilingual(self):
        self.assertEqual(TEXT["en"]["question"], "Do you have a question?")
        self.assertEqual(TEXT["ar"]["question"], "هل لديك سؤال؟")
        self.assertEqual(TEXT["en"]["ask_another_question"], "Ask another question")
        self.assertEqual(TEXT["ar"]["ask_another_question"], "اسأل سؤال آخر")
        self.assertEqual(TEXT["en"]["continue_tour"], "Continue tour")
        self.assertEqual(TEXT["ar"]["continue_tour"], "استكمال الجولة")

    def test_integrated_chatbot_cli_flags(self):
        with patch("sys.argv", ["main.py", "--test-integrated-chatbot-env"]):
            args = parse_args()
        self.assertTrue(args.test_integrated_chatbot_env)
        with patch("sys.argv", [
            "main.py", "--test-integrated-chatbot-typed",
            "--language", "ar", "--question", "من هو رمسيس الثاني؟", "--speak-answer",
        ]):
            args = parse_args()
        self.assertTrue(args.test_integrated_chatbot_typed)
        self.assertEqual(args.language, "ar")
        self.assertIn("رمسيس", args.question)
        self.assertTrue(args.speak_answer)
        with patch("sys.argv", [
            "main.py", "--test-integrated-chatbot-voice",
            "--language", "en", "--mic-device-index", "1",
        ]):
            args = parse_args()
        self.assertTrue(args.test_integrated_chatbot_voice)
        self.assertEqual(args.language, "en")
        self.assertEqual(args.mic_device_index, 1)

    def test_tts_prefers_elevenlabs_when_keys_exist(self):
        with patch.dict("os.environ", {
            "ELEVEN_API_KEY": "test-key",
            "ELEVEN_VOICE_ID": "test-voice",
        }, clear=True):
            tts = TextToSpeech(enabled=True)
            try:
                self.assertEqual(tts._engine_for_language("en"), "elevenlabs")
                self.assertEqual(tts._engine_for_language("ar"), "elevenlabs")
            finally:
                tts.stop()

    def test_tts_accepts_elevenlabs_alias_names(self):
        with patch.dict("os.environ", {
            "ELEVENLABS_API_KEY": "test-key",
            "ELEVENLABS_VOICE_ID": "test-voice",
        }, clear=True):
            tts = TextToSpeech(enabled=True)
            try:
                self.assertEqual(tts._engine_for_language("en"), "elevenlabs")
                self.assertEqual(tts._engine_for_language("ar"), "elevenlabs")
            finally:
                tts.stop()

    def test_tts_forced_edge_uses_edge_first(self):
        with patch.dict("os.environ", {
            "PLANB_TTS_ENGINE": "edge",
            "PLANB_TTS_VOICE_EN": "en-US-GuyNeural",
            "PLANB_TTS_VOICE_AR": "ar-EG-ShakirNeural",
        }, clear=True):
            tts = TextToSpeech(enabled=True)
            try:
                self.assertEqual(tts._engine_for_language("en"), "edge-tts")
                self.assertEqual(tts._engine_for_language("ar"), "edge-tts")
                self.assertEqual(tts._edge_voice_en, "en-US-GuyNeural")
                self.assertEqual(tts._edge_voice_ar, "ar-EG-ShakirNeural")
            finally:
                tts.stop()

    def test_tts_default_prefers_edge_when_available_without_elevenlabs(self):
        with patch.dict("os.environ", {}, clear=True), \
             patch("speech.importlib.util.find_spec", return_value=object()):
            tts = TextToSpeech(enabled=True)
            try:
                self.assertEqual(tts._engine_for_language("en"), "edge-tts")
                self.assertEqual(tts._engine_for_language("ar"), "edge-tts")
            finally:
                tts.stop()

    def test_get_env_first_uses_priority_order(self):
        with patch.dict("os.environ", {
            "ELEVEN_API_KEY": "primary",
            "ELEVENLABS_API_KEY": "secondary",
        }, clear=True):
            self.assertEqual(get_env_first("ELEVEN_API_KEY", "ELEVENLABS_API_KEY"), "primary")

    def test_tts_disabled_uses_timed_simulation(self):
        with patch.dict("os.environ", {}, clear=True):
            tts = TextToSpeech(enabled=False)
            try:
                self.assertEqual(tts._engine_for_language("en"), "timed simulation")
            finally:
                tts.stop()

    def test_simulation_main_does_not_open_serial(self):
        class FakeRoot:
            def title(self, _text):
                pass
            def geometry(self, _geometry):
                pass
            def configure(self, **_kwargs):
                pass
            def attributes(self, *_args):
                pass
            def bind(self, *_args):
                pass
            def mainloop(self):
                pass

        with patch("sys.argv", ["main.py", "--simulate", "--serial-port", "COM4"]), \
             patch.object(main_module, "ArduinoSerialManager") as arduino_cls, \
             patch.object(main_module.tk, "Tk", return_value=FakeRoot()), \
             patch.object(main_module, "AppController"):
            main_module.main()
        arduino_cls.assert_not_called()

    def test_gemini_missing_key_is_safe(self):
        with patch.dict("os.environ", {}, clear=True):
            answer = GeminiClient().answer(
                question="Unknown", artifact_id="king_khufu", artifact_name="King Khufu",
                artifact_description="Description", language="en")
        self.assertIsNone(answer)

    def test_gemini_response_is_parsed(self):
        class FakeSocket:
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                return False

        class FakeResponse:
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                return False
            def read(self):
                return json_module.dumps({
                    "candidates": [{"content": {"parts": [{"text": "Museum answer"}]}}]
                }).encode("utf-8")

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}, clear=True), \
             patch("gemini_client.socket.create_connection", return_value=FakeSocket()), \
             patch("gemini_client.urllib.request.urlopen", return_value=FakeResponse()):
            answer = GeminiClient().answer(
                question="Question", artifact_id="king_khufu", artifact_name="King Khufu",
                artifact_description="Description", language="en")
        self.assertEqual(answer, "Museum answer")

    def test_stt_disabled_is_safe_typed_fallback(self):
        recognizer = SpeechRecognizer(enabled=False)
        self.assertFalse(recognizer.available)
        result = []
        recognizer.listen("en", result.append)
        for _ in range(50):
            if result:
                break
            time.sleep(0.01)
        self.assertEqual(result, [None])

    def test_stt_missing_model_is_safe_typed_fallback(self):
        recognizer = SpeechRecognizer(enabled=True, model_path=str(ROOT / "missing-vosk-model"))
        self.assertTrue(recognizer.available)
        result = []
        recognizer.listen("en", result.append)
        for _ in range(50):
            if result:
                break
            time.sleep(0.01)
        self.assertEqual(result, [None])

    def test_vosk_language_specific_model_resolution(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "models" / "vosk"
            ar = Path(directory) / "models" / "vosk_ar"
            en = Path(directory) / "models" / "vosk_en"
            ar.mkdir(parents=True)
            en.mkdir(parents=True)
            self.assertEqual(resolve_vosk_model_path(base, "ar"), ar)
            self.assertEqual(resolve_vosk_model_path(base, "en"), en)

    def test_arabic_stt_does_not_fallback_to_default_vosk_model(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "models" / "vosk"
            base.mkdir(parents=True)
            self.assertEqual(resolve_vosk_model_path(base, "ar"),
                             Path(directory) / "models" / "vosk_ar")
            self.assertEqual(resolve_vosk_model_path(base, "en"), base)

    def test_qa_copy_matches_demo_requirements(self):
        self.assertEqual(TEXT["en"]["ask"], "Ask")
        self.assertEqual(TEXT["ar"]["ask"], "اسأل")
        self.assertEqual(TEXT["en"]["question_placeholder"],
                         "Type or speak your question here...")
        self.assertEqual(TEXT["ar"]["question_placeholder"],
                         "اكتب أو قل سؤالك هنا...")
        self.assertEqual(TEXT["en"]["no_data_answer"],
                         "Sorry, I do not have enough data to answer this question right now.")
        self.assertEqual(TEXT["ar"]["no_data_answer"],
                         "عذرًا، لا توجد لدي بيانات كافية للإجابة على هذا السؤال الآن.")

    def test_feedback_workbook(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "feedback.xlsx"
            FeedbackStorage(path).save({"language": "en", "tour_type": "short",
                                        "rating_tour": 5, "rating_explanation": 4,
                                        "rating_robot": 5, "comment": "Great"})
            self.assertTrue(path.exists())

    def test_arduino_encoder_protocol(self):
        self.assertEqual(ArduinoSerialManager.parse_encoder_line("ENC L=12345 R=-12350"),
                         (12345, -12350))
        self.assertIsNone(ArduinoSerialManager.parse_encoder_line("debug text"))

    def test_arduino_motor_command_protocol(self):
        class FakeSerial:
            def __init__(self):
                self.output = b""
            def write(self, payload):
                self.output += payload
            def flush(self):
                pass
        manager = ArduinoSerialManager("TEST")
        fake = FakeSerial()
        manager._serial = fake
        self.assertTrue(manager.send_motor_command("F", 120))
        self.assertEqual(fake.output, b"CMD F 120\n")

    def test_arabic_shaping_and_english_passthrough(self):
        phrases = [
            "اهلا بكم في المتحف المصري الكبير",
            "عربي",
            "جولة قصيرة",
            "جولة طويلة",
            "هل لديك أي سؤال؟",
            "شكرًا لزيارتكم المتحف المصري الكبير",
        ]
        self.assertTrue(contains_arabic(phrases[0]))
        self.assertFalse(contains_arabic("Grand Egyptian Museum 2026"))
        self.assertEqual(shape_arabic_text("Grand Egyptian Museum 2026"),
                         "Grand Egyptian Museum 2026")
        for phrase in phrases:
            shaped = shape_arabic_text(phrase)
            self.assertIsInstance(shaped, str)
            self.assertNotEqual(shaped, phrase)
            self.assertTrue(any("\ufb50" <= char <= "\ufeff" for char in shaped))

    def test_arabic_json_stays_unshaped_utf8(self):
        raw = (ROOT / "data/artifacts.json").read_text(encoding="utf-8")
        self.assertIn("تمثال رمسيس الثاني", raw)
        self.assertFalse(any("\ufb50" <= char <= "\ufeff" for char in raw))


if __name__ == "__main__":
    unittest.main()
