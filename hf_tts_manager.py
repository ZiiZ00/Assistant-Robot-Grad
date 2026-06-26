import threading
import queue
import traceback

from hf_local_tts import speak as hf_speak


def normalize_language(language):
    """
    Convert GUI language value to TTS language code.
    Accepted outputs:
        ar
        en
    """
    if language is None:
        return "ar"

    lang = str(language).lower().strip()

    if lang in ["ar", "arabic", "عربي", "العربية"]:
        return "ar"

    if lang in ["en", "english", "انجليزي", "english language"]:
        return "en"

    # Default fallback
    return "ar"


class HFTTSManager:
    """
    Queue-based TTS manager.
    It prevents overlapping voices and keeps the GUI responsive.
    """

    def __init__(self):
        self._queue = queue.Queue()
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True
        )
        self._worker_thread.start()

    def say(self, text, language="ar"):
        """
        Add text to the speaking queue.
        This returns immediately and does not freeze the GUI.
        """
        if not text or not str(text).strip():
            print("[HF TTS Manager] Empty text, skipping.")
            return

        lang = normalize_language(language)

        print(f"[HF TTS Manager] Queued speech. language={lang}")
        self._queue.put((str(text), lang))

    def _worker_loop(self):
        while True:
            text, language = self._queue.get()

            try:
                print(f"[HF TTS Manager] Speaking. language={language}")
                hf_speak(text, language=language, play=True)

            except Exception as e:
                print("[HF TTS Manager] TTS failed:", e)
                traceback.print_exc()

            finally:
                self._queue.task_done()


# Global object used by the GUI/controller
tts_manager = HFTTSManager()


def speak_async(text, language="ar"):
    """
    Simple function to call from GUI/controller.
    """
    tts_manager.say(text, language)