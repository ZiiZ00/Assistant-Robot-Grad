"""Shared touchscreen widgets and bilingual UI text."""
from __future__ import annotations

import tkinter as tk
from typing import Callable

from arabic_support import configure_text, shape_arabic_text, ui_font

BG = "#07111f"
PANEL = "#10233d"
GOLD = "#d9a928"
BLUE = "#1769aa"
WHITE = "#f8fafc"
RED = "#b91c1c"

TEXT = {
    "en": {
        "next": "Next", "short": "Short Tour", "long": "Long Tour",
        "arrived": "Arrived",
        "question": "Do you have a question?", "ask": "Ask", "submit": "Submit",
        "ask_another_question": "Ask another question", "continue_tour": "Continue tour",
        "question_placeholder": "Type or speak your question here...",
        "stt_unavailable": "Speech recognition is not available. Please type your question.",
        "not_heard": "Sorry, I did not hear the question clearly.",
        "no_data_answer": "Sorry, I do not have enough data to answer this question right now.",
        "continue": "Continue",
        "feedback": "Tour Feedback", "tour_rating": "How was the tour?",
        "clear_rating": "Was the explanation clear?", "robot_rating": "Was the robot helpful?",
        "comments": "Any comments?", "save": "Save and Continue",
        "emergency": "EMERGENCY",
        "emergency_title": "Emergency stop activated", "home": "Return to Welcome",
        "exit": "Exit", "saved": "Thank you. Your feedback was saved.",
        "listening": "Listening...",
    },
    "ar": {
        "next": "التالي", "short": "جولة قصيرة", "long": "جولة طويلة",
        "arrived": "وصلنا", "moving": "نتحرك إلى النقطة التالية",
        "moving_hint": "يمكن للمشغل تحريك الروبوت يدويًا.",
        "question": "هل لديك سؤال؟", "ask": "اسأل", "submit": "إرسال",
        "ask_another_question": "اسأل سؤال آخر", "continue_tour": "استكمال الجولة",
        "question_placeholder": "اكتب أو قل سؤالك هنا...",
        "stt_unavailable": "التعرف على الصوت غير متاح. من فضلك اكتب سؤالك.",
        "not_heard": "عذرًا، لم أسمع السؤال بوضوح.",
        "no_data_answer": "عذرًا، لا توجد لدي بيانات كافية للإجابة على هذا السؤال الآن.",
        "continue": "التالي", "feedback": "تقييم الجولة",
        "tour_rating": "ما رأيك في الجولة؟", "clear_rating": "هل كان الشرح واضحًا؟",
        "robot_rating": "هل كان الروبوت مفيدًا؟", "comments": "هل لديك أي ملاحظات؟",
        "save": "حفظ ومتابعة", "returning": "العودة إلى نقطة البداية",
        "emergency": "طوارئ", "emergency_title": "تم تفعيل إيقاف الطوارئ",
        "home": "العودة للترحيب", "exit": "خروج", "saved": "شكرًا، تم حفظ تقييمك.",
        "listening": "جاري الاستماع...",
    },
}


def button(parent: tk.Misc, text: str, command: Callable[[], None], *, danger: bool = False,
           width: int = 16, font_size: int = 18) -> tk.Button:
    return tk.Button(parent, text=shape_arabic_text(text), command=command,
                     font=ui_font(parent, text, font_size, True),
                     bg=RED if danger else BLUE, fg=WHITE, activebackground=GOLD,
                     activeforeground="#000000", relief="flat", width=width, height=2,
                     cursor="hand2")


def title(parent: tk.Misc, text: str, size: int = 30) -> tk.Label:
    return tk.Label(parent, text=shape_arabic_text(text), font=ui_font(parent, text, size, True), bg=BG, fg=GOLD,
                    wraplength=740, justify="center")


def body(parent: tk.Misc, text: str, size: int = 18) -> tk.Label:
    return tk.Label(parent, text=shape_arabic_text(text), font=ui_font(parent, text, size), bg=BG, fg=WHITE,
                    wraplength=740, justify="center")


def emergency_button(parent: tk.Misc, text: str, command: Callable[[], None]) -> tk.Button:
    widget = button(parent, text, command, danger=True, width=12, font_size=13)
    widget.configure(height=1)
    widget.place(relx=0.99, rely=0.02, anchor="ne")
    return widget


def show_arabic_test_screen(root: tk.Tk) -> None:
    """Visual shaping check containing the required Arabic phrases."""
    frame = tk.Frame(root, bg=BG)
    frame.pack(fill="both", expand=True)
    phrases = [
        "اهلا بكم في المتحف المصري الكبير",
        "عربي",
        "جولة قصيرة",
        "جولة طويلة",
        "هل لديك أي سؤال؟",
        "شكرًا لزيارتكم المتحف المصري الكبير",
    ]
    title(frame, "اختبار عرض اللغة العربية", 25).pack(pady=(22, 8))
    for phrase in phrases:
        body(frame, phrase, 20).pack(pady=5)
