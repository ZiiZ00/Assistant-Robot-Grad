"""Plan B UI state machine. No navigation, maps, or coordinates."""
from __future__ import annotations

import json
import platform
import queue
import subprocess
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox
from typing import Any, Callable

import ui
from arrival_detector import ArrivalDetector, EncoderSource
from face_animation import PharaohFace
from feedback_storage import FeedbackStorage
from logging_utils import safe_print
from museum_chatbot_engine import MuseumChatbotEngine
from speech import TextToSpeech


class AppController:
    def get_tts_language(self) -> str:
        """
        Return the current GUI language as the code used by centralized TTS.
        """
        lang = str(getattr(self, "language", "ar")).lower().strip()

        if lang in ["ar", "arabic", "عربي", "العربية"]:
            return "ar"

        if lang in ["en", "english", "انجليزي", "english language"]:
            return "en"

        return "ar"

    def _cancel_current_speech(self) -> None:
        """
        Stop/ignore the current TTS job when the screen changes, emergency is pressed,
        or the app exits.
        """
        with self._tts_lock:
            self._speech_token += 1
            process = self._tts_process
            self._tts_process = None

        if hasattr(self, "tts"):
            self.tts.stop()

        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except Exception as exc:
                print(f"TTS process stop warning: {exc}")

        if platform.system().lower().startswith("win"):
            try:
                import winsound
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass

    def _play_audio_blocking(self, audio_file: str, token: int) -> None:
        """
        Play generated WAV without freezing Tkinter.
        This function runs inside a background thread.
        """
        if platform.system().lower().startswith("win"):
            import winsound
            winsound.PlaySound(audio_file, winsound.SND_FILENAME)
            return

        process = subprocess.Popen(["aplay", audio_file])

        with self._tts_lock:
            if token == self._speech_token:
                self._tts_process = process

        try:
            while process.poll() is None:
                with self._tts_lock:
                    cancelled = token != self._speech_token
                if cancelled:
                    try:
                        process.terminate()
                    except Exception:
                        pass
                    return
                time.sleep(0.05)
        finally:
            with self._tts_lock:
                if self._tts_process is process:
                    self._tts_process = None

    def _speak_with_tts(self, text: str, done: Callable[[], None] | None = None) -> None:
        """
        Speak without blocking Tkinter and call done() on the UI thread.
        """
        text = (text or "").strip()

        if not text:
            if done:
                self.run_on_ui(done)
            return

        if not self.enable_tts:
            safe_print("TTS disabled; skipping speech.")
            if done:
                self.run_on_ui(done)
            return

        language = self.get_tts_language()
        safe_print(f"TTS requested. language={language}")
        self.tts.speak(text, language, lambda: self.run_on_ui(done) if done else None)

    def __init__(self, root: tk.Tk, *, encoder_source: EncoderSource | None,
                 debug_arrived_button: bool, enable_tts: bool, enable_stt: bool,
                 mic_device_index: int | None = None) -> None:
        self.root = root
        base = Path(__file__).resolve().parent
        self.artifacts = json.loads((base / "data/artifacts.json").read_text(encoding="utf-8"))["artifacts"]
        self.tours = json.loads((base / "data/manual_tours.json").read_text(encoding="utf-8"))["tours"]
        self.artifacts_by_id = {item["id"]: item for item in self.artifacts}
        self.chatbot_engine = MuseumChatbotEngine(base / "NLP1.1")
        self.feedback_storage = FeedbackStorage(base / "data/feedback/feedback.xlsx")
        self.arrival = ArrivalDetector(encoder_source)
        self.debug_arrived_button = debug_arrived_button
        self.enable_tts = enable_tts
        self.enable_stt = enable_stt
        self.tts = TextToSpeech(enable_tts)
        self.mic_device_index = mic_device_index
        self.language = "en"
        self.tour_type = "short"
        self.route: list[str] = []
        self.point_index = 0
        self.frame: tk.Frame | None = None
        self.face: PharaohFace | None = None
        self._screen_id = 0
        self._timeout_id: str | None = None
        self._stt_result = ""
        self._listening = False
        self._ui_queue: "queue.Queue[Callable[[], None]]" = queue.Queue()
        self._ui_pump_after_id: str | None = None
        self._shutdown_callbacks: list[Callable[[], None]] = []
        self._emergency_callbacks: list[Callable[[], None]] = []
        self._speech_token = 0
        self._tts_process: subprocess.Popen | None = None
        self._tts_lock = threading.Lock()
        self.root.protocol("WM_DELETE_WINDOW", self.exit_app)
        self._ui_pump_after_id = self.root.after(50, self._pump_ui_queue)
        self.show_welcome()

    def register_shutdown(self, callback: Callable[[], None]) -> None:
        self._shutdown_callbacks.append(callback)

    def register_emergency(self, callback: Callable[[], None]) -> None:
        self._emergency_callbacks.append(callback)

    def run_on_ui(self, callback: Callable[[], None]) -> None:
        self._ui_queue.put(callback)

    def _pump_ui_queue(self) -> None:
        while True:
            try:
                callback = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                callback()
            except Exception as exc:
                print(f"UI callback warning: {exc}")
        try:
            self._ui_pump_after_id = self.root.after(50, self._pump_ui_queue)
        except tk.TclError:
            pass

    def _new_screen(self, emergency: bool = True) -> tk.Frame:
        self._screen_id += 1
        self._listening = False
        if self._timeout_id:
            self.root.after_cancel(self._timeout_id)
            self._timeout_id = None
        if self.frame:
            self.frame.destroy()
        self.frame = tk.Frame(self.root, bg=ui.BG)
        self.frame.pack(fill="both", expand=True)
        self.face = None
        if emergency:
            ui.emergency_button(self.frame, ui.TEXT[self.language]["emergency"], self.show_emergency)
        return self.frame

    def show_welcome(self) -> None:
        self.arrival.stop()
        self._cancel_current_speech()
        frame = self._new_screen(emergency=False)
        tk.Label(frame, text="𓂀", font=("Arial", 65), bg=ui.BG, fg=ui.GOLD).pack(pady=(28, 0))
        ui.title(frame, "Welcome to the Grand Egyptian Museum", 28).pack(pady=6)
        ui.body(frame, "أهلاً بكم في المتحف المصري الكبير", 24).pack(pady=5)
        controls = tk.Frame(frame, bg=ui.BG)
        controls.pack(pady=24)
        ui.button(controls, "Next / التالي", self.show_language, width=18).pack()

    def show_language(self) -> None:
        frame = self._new_screen()
        ui.title(frame, "Choose Language / اختر اللغة", 28).pack(pady=(80, 35))
        controls = tk.Frame(frame, bg=ui.BG)
        controls.pack()
        ui.button(controls, "English", lambda: self.select_language("en")).pack(side="left", padx=18)
        ui.button(controls, "عربي", lambda: self.select_language("ar")).pack(side="left", padx=18)

    def select_language(self, language: str) -> None:
        self.language = language
        self.show_tour_selection()

    def show_tour_selection(self) -> None:
        frame = self._new_screen()
        prompt = "Choose your tour" if self.language == "en" else "اختر جولتك"
        ui.title(frame, prompt).pack(pady=(80, 35))
        controls = tk.Frame(frame, bg=ui.BG)
        controls.pack()
        for key in ("short", "long"):
            ui.button(controls, ui.TEXT[self.language][key], lambda k=key: self.start_tour(k)).pack(
                side="left", padx=18
            )

    def start_tour(self, tour_type: str) -> None:
        self.tour_type = tour_type
        self.route = list(self.tours[tour_type]["artifact_ids"])
        self.point_index = 0
        self.show_moving(returning=False)

    def show_moving(self, returning: bool) -> None:
        frame = self._new_screen()
        self.face = PharaohFace(frame, height=360)
        self.face.pack(fill="both", expand=True, padx=90, pady=(25, 8))

        if self.debug_arrived_button:
            ui.button(
                frame,
                ui.TEXT[self.language]["arrived"],
                lambda: self.arrival.trigger("manual"),
                width=18,
                font_size=22
            ).pack(pady=(0, 12))

        current_screen = self._screen_id

        def arrived(reason: str) -> None:
            self.run_on_ui(
                lambda: self._on_arrival(returning, reason) if current_screen == self._screen_id else None
            )

        self.arrival.start(arrived)

    def _on_arrival(self, returning: bool, reason: str) -> None:
        self.arrival.stop()
        print(f"Arrival detected ({reason})")
        if returning:
            self.show_goodbye()
        else:
            self.show_artifact()

    def show_artifact(self) -> None:
        artifact = self.artifacts_by_id[self.route[self.point_index]]
        frame = self._new_screen()
        ui.title(frame, artifact["name"][self.language], 25).pack(pady=(14, 2))

        self.face = PharaohFace(frame, height=225)
        self.face.pack(fill="x", padx=180)

        ui.body(frame, artifact["explanation"][self.language], 15).pack(padx=24, pady=5)
        ui.body(frame, "🔊", 18).pack()

        self.face.set_speaking(True)
        current_screen = self._screen_id

        safe_print("Artifact speech using local TTS fallback stack")
        self._speak_with_tts(
            artifact["explanation"][self.language],
            lambda: self._explanation_done(current_screen)
        )

    def _explanation_done(self, screen_id: int) -> None:
        if screen_id != self._screen_id:
            return

        if self.face:
            self.face.set_speaking(False)

        self.start_question_loop()

    def _current_artifact_id(self) -> str:
        if not self.route:
            return ""
        return self.route[self.point_index]

    def start_question_loop(self) -> None:
        artifact_id = self._current_artifact_id()
        safe_print("Question loop started")
        safe_print(f"Current artifact ID during question loop: {artifact_id}")
        self.show_qa_prompt()

    def show_qa_prompt(self) -> None:
        frame = self._new_screen()
        self._stt_result = ""

        ui.title(frame, ui.TEXT[self.language]["question"], 28).pack(pady=(62, 22))

        entry = tk.Entry(frame, font=("Arial", 20), justify="right" if self.language == "ar" else "left")
        entry.configure(font=ui.ui_font(frame, "عربي" if self.language == "ar" else "English", 20))
        entry.pack(fill="x", padx=70, ipady=10)

        placeholder = ui.TEXT[self.language]["question_placeholder"]
        shown_placeholder = ui.shape_arabic_text(placeholder)

        def show_placeholder() -> None:
            entry.delete(0, "end")
            entry.insert(0, shown_placeholder)
            entry.configure(fg="#94a3b8")

        def focus_in(_event: object = None) -> None:
            if entry.cget("fg") == "#94a3b8":
                entry.delete(0, "end")
                entry.configure(fg=ui.WHITE)

        def focus_out(_event: object = None) -> None:
            if not entry.get().strip():
                show_placeholder()

        def typed_question() -> str:
            if entry.cget("fg") == "#94a3b8":
                return ""
            raw_text = entry.get().strip()
            return "" if raw_text and raw_text == self._stt_result else raw_text

        show_placeholder()
        entry.bind("<FocusIn>", focus_in)
        entry.bind("<FocusOut>", focus_out)

        status = ui.body(frame, "", 14)
        status.pack(pady=8)

        controls = tk.Frame(frame, bg=ui.BG)
        controls.pack(pady=8)

        ui.button(
            controls,
            ui.TEXT[self.language]["ask"],
            lambda: self._listen(entry, status, focus_in),
            width=12
        ).pack(side="left", padx=12)

        ui.button(
            controls,
            ui.TEXT[self.language]["submit"],
            lambda: self.submit_question(typed_question(), entry, status),
            width=12
        ).pack(side="left", padx=12)

        entry.bind("<Return>", lambda _event: self.submit_question(typed_question(), entry, status))

    def _listen(self, entry: tk.Entry, status: tk.Label, clear_placeholder: Callable[[], None]) -> None:
        safe_print("Ask button pressed")
        ui.configure_text(status, ui.TEXT[self.language]["listening"], 14)
        clear_placeholder()
        entry.focus_set()

        if not self.enable_stt:
            ui.configure_text(status, ui.TEXT[self.language]["stt_unavailable"], 14)
            safe_print("Using integrated chatbot STT skipped: --enable-stt was not set")
            return

        screen = self._screen_id
        self._listening = True

        def listen_worker() -> None:
            text = self.chatbot_engine.listen(self.language, self.mic_device_index)

            def update() -> None:
                if screen != self._screen_id:
                    return

                self._listening = False
                recognized = (text or "").strip()

                if not recognized:
                    ui.configure_text(status, ui.TEXT[self.language]["not_heard"], 14)
                    return

                self._stt_result = recognized
                entry.delete(0, "end")
                entry.insert(0, recognized)
                entry.configure(fg=ui.WHITE)
                ui.configure_text(status, "", 14)

            self.run_on_ui(update)

        threading.Thread(target=listen_worker, daemon=True).start()

    def submit_question(self, typed_question: str, entry: tk.Entry, status: tk.Label) -> None:
        typed = typed_question.strip()

        if typed:
            safe_print(f"Using typed question: {typed}")
            self.answer_question(typed)
            return

        if self._listening:
            ui.configure_text(status, ui.TEXT[self.language]["listening"], 14)
            entry.focus_set()
            return

        question = self._stt_result.strip()

        if not question:
            ui.configure_text(status, ui.TEXT[self.language]["not_heard"], 14)
            entry.focus_set()
            return

        safe_print(f"Recognized question before translation: {question}")
        self.answer_question(question)

    def answer_question(self, question: str) -> None:
        if not question.strip():
            return

        safe_print(f"Chatbot question: {question}")

        artifact_id = self._current_artifact_id()
        safe_print(f"Current artifact ID during question loop: {artifact_id}")

        frame = self._new_screen()

        self.face = PharaohFace(frame, height=230)
        self.face.pack(fill="x", padx=180, pady=(15, 0))

        ui.body(frame, question, 14).pack(padx=35, pady=(2, 0))

        answer_label = ui.body(frame, "...", 17)
        answer_label.pack(padx=35, pady=5)

        current_screen = self._screen_id

        def lookup() -> None:
            answer = self.chatbot_engine.answer(question, self.language)

            if answer is None:
                answer = ui.TEXT[self.language]["no_data_answer"]

            safe_print(f"Chatbot answer: {answer}")

            self.run_on_ui(
                lambda: self._speak_answer(current_screen, answer_label, answer)
            )

        threading.Thread(target=lookup, daemon=True).start()

    def _speak_answer(self, screen_id: int, answer_label: tk.Label, answer: str) -> None:
        if screen_id != self._screen_id:
            return

        ui.configure_text(answer_label, answer, 17)

        if self.face:
            self.face.set_speaking(True)

        def done() -> None:
            self.run_on_ui(lambda: self._answer_done(screen_id))

        safe_print("Chatbot answer speech using local TTS fallback stack")
        self._speak_with_tts(answer, done)

    def _answer_done(self, screen_id: int) -> None:
        if screen_id != self._screen_id:
            return

        if self.face:
            self.face.set_speaking(False)

        controls = tk.Frame(self.frame, bg=ui.BG)
        controls.pack(pady=6)

        ui.button(
            controls,
            ui.TEXT[self.language]["ask_another_question"],
            self.ask_another_question,
            width=20
        ).pack(side="left", padx=10)

        ui.button(
            controls,
            ui.TEXT[self.language]["continue_tour"],
            self.continue_tour_from_question_loop,
            width=16
        ).pack(side="left", padx=10)

    def ask_another_question(self) -> None:
        safe_print("Visitor selected Ask another question")
        safe_print(f"Current artifact ID during question loop: {self._current_artifact_id()}")
        self.show_qa_prompt()

    def continue_tour_from_question_loop(self) -> None:
        safe_print("Visitor selected Continue tour")
        safe_print(f"Current artifact ID during question loop: {self._current_artifact_id()}")
        safe_print("Question loop ended")
        self.finish_qa()

    def finish_qa(self) -> None:
        if self.point_index >= len(self.route) - 1:
            self.show_feedback()
        else:
            self.point_index += 1
            self.show_moving(returning=False)

    def show_feedback(self) -> None:
        frame = self._new_screen()
        ui.title(frame, ui.TEXT[self.language]["feedback"], 23).pack(pady=(12, 3))

        ratings: dict[str, tk.IntVar] = {}

        for key, label_key in (
            ("rating_tour", "tour_rating"),
            ("rating_explanation", "clear_rating"),
            ("rating_robot", "robot_rating"),
        ):
            row = tk.Frame(frame, bg=ui.BG)
            row.pack(pady=2)

            question_text = ui.TEXT[self.language][label_key]

            tk.Label(
                row,
                text=ui.shape_arabic_text(question_text),
                font=ui.ui_font(row, question_text, 14),
                bg=ui.BG,
                fg=ui.WHITE,
                width=31,
                anchor="e" if self.language == "ar" else "w"
            ).pack(side="left")

            ratings[key] = tk.IntVar(value=5)

            for value in range(1, 6):
                tk.Radiobutton(
                    row,
                    text=str(value),
                    variable=ratings[key],
                    value=value,
                    font=("Arial", 13, "bold"),
                    bg=ui.BG,
                    fg=ui.GOLD,
                    selectcolor=ui.PANEL,
                    activebackground=ui.BG
                ).pack(side="left")

        ui.body(frame, ui.TEXT[self.language]["comments"], 14).pack(pady=(5, 1))

        comment = tk.Entry(frame, font=("Arial", 16), justify="right" if self.language == "ar" else "left")
        comment.configure(font=ui.ui_font(frame, "عربي" if self.language == "ar" else "English", 16))
        comment.pack(fill="x", padx=90, ipady=5)

        ui.button(
            frame,
            ui.TEXT[self.language]["save"],
            lambda: self.save_feedback(ratings, comment.get()),
            width=18,
            font_size=16
        ).pack(pady=8)

    def save_feedback(self, ratings: dict[str, tk.IntVar], comment: str) -> None:
        payload: dict[str, Any] = {name: variable.get() for name, variable in ratings.items()}
        payload.update(language=self.language, tour_type=self.tour_type, comment=comment)

        try:
            path = self.feedback_storage.save(payload)
            print(f"Feedback saved to {path}")
        except Exception as exc:
            messagebox.showerror("Feedback", f"Could not save feedback: {exc}")
            return

        self.show_moving(returning=True)

    def show_goodbye(self) -> None:
        frame = self._new_screen()

        text = (
            "Thank you for visiting the Grand Egyptian Museum"
            if self.language == "en"
            else "شكرًا لزيارتكم المتحف المصري الكبير"
        )

        tk.Label(frame, text="𓂀", font=("Arial", 70), bg=ui.BG, fg=ui.GOLD).pack(pady=(50, 10))
        ui.title(frame, text, 28).pack(padx=25, pady=10)
        ui.button(frame, ui.TEXT[self.language]["home"], self.show_welcome, width=18, font_size=16).pack(pady=15)

    def show_emergency(self) -> None:
        self.arrival.stop()
        self._cancel_current_speech()

        for callback in self._emergency_callbacks:
            try:
                callback()
            except Exception as exc:
                print(f"Emergency stop warning: {exc}")

        frame = self._new_screen(emergency=False)

        tk.Label(
            frame,
            text="!",
            font=("Arial", 90, "bold"),
            bg=ui.RED,
            fg=ui.WHITE,
            width=4
        ).pack(pady=(40, 15))

        ui.title(frame, ui.TEXT[self.language]["emergency_title"], 26).pack(pady=10)

        controls = tk.Frame(frame, bg=ui.BG)
        controls.pack(pady=12)

        ui.button(controls, ui.TEXT[self.language]["home"], self.show_welcome, width=17).pack(
            side="left", padx=10
        )
        ui.button(controls, ui.TEXT[self.language]["exit"], self.exit_app, danger=True, width=10).pack(
            side="left", padx=10
        )

    def exit_app(self) -> None:
        self.arrival.stop()
        self._cancel_current_speech()

        if self._ui_pump_after_id:
            try:
                self.root.after_cancel(self._ui_pump_after_id)
            except tk.TclError:
                pass
            self._ui_pump_after_id = None

        callbacks, self._shutdown_callbacks = self._shutdown_callbacks, []

        for callback in callbacks:
            try:
                callback()
            except Exception as exc:
                print(f"Shutdown warning: {exc}")

        self.root.destroy()
