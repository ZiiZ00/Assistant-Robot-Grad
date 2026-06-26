"""Lightweight robot-pharaoh Canvas animation."""
from __future__ import annotations

import random
import tkinter as tk


class PharaohFace(tk.Canvas):
    def __init__(self, parent: tk.Misc, **kwargs) -> None:
        super().__init__(parent, bg="#07111f", highlightthickness=0, **kwargs)
        self.speaking = False
        self._blink = False
        self._mouth_open = False
        self._destroyed = False
        self._mouth_after_id: str | None = None
        self._eyes_after_id: str | None = None
        self._blink_after_id: str | None = None
        self.bind("<Configure>", lambda _e: self.draw())
        self.bind("<Destroy>", self._on_destroy)
        self._mouth_after_id = self.after(180, self._animate_mouth)
        self._eyes_after_id = self.after(1200, self._animate_eyes)

    def _on_destroy(self, _event: tk.Event) -> None:
        self._destroyed = True
        for after_id in (self._mouth_after_id, self._eyes_after_id, self._blink_after_id):
            if after_id:
                try:
                    self.after_cancel(after_id)
                except tk.TclError:
                    pass

    def set_speaking(self, speaking: bool) -> None:
        self.speaking = speaking
        if not speaking:
            self._mouth_open = False
        self.draw()

    def _animate_mouth(self) -> None:
        if self._destroyed:
            return
        if self.speaking:
            self._mouth_open = not self._mouth_open
            self.draw()
        self._mouth_after_id = self.after(170, self._animate_mouth)

    def _animate_eyes(self) -> None:
        if self._destroyed:
            return
        self._blink = True
        self.draw()
        self._blink_after_id = self.after(140, self._end_blink)

    def _end_blink(self) -> None:
        if self._destroyed:
            return
        self._blink = False
        self.draw()
        self._eyes_after_id = self.after(random.randint(1800, 4200), self._animate_eyes)

    def draw(self) -> None:
        if self._destroyed:
            return
        self.delete("all")
        w, h = max(self.winfo_width(), 320), max(self.winfo_height(), 240)
        cx = w / 2
        # Nemes headcloth and crown
        self.create_polygon(cx-150, 35, cx+150, 35, cx+120, h-20, cx-120, h-20,
                            fill="#154b8b", outline="#d9a928", width=5)
        for offset in (-110, -65, 65, 110):
            self.create_line(cx+offset, 45, cx+offset*0.75, h-30, fill="#d9a928", width=9)
        self.create_polygon(cx-25, 35, cx, 2, cx+25, 35, fill="#d9a928")
        # Metallic face
        self.create_oval(cx-105, 42, cx+105, h-25, fill="#d9a928", outline="#f5e5a4", width=4)
        self.create_rectangle(cx-72, 95, cx+72, 145, fill="#111827", outline="#e8f6ff", width=3)
        eye_h = 3 if self._blink else 20
        for ex in (cx-42, cx+42):
            self.create_oval(ex-22, 120-eye_h/2, ex+22, 120+eye_h/2,
                             fill="#f8fafc", outline="#44c7ff", width=3)
            if not self._blink:
                self.create_oval(ex-7, 113, ex+7, 127, fill="#07111f")
        # Nose plate and animated mouth
        self.create_polygon(cx, 142, cx-18, 178, cx+18, 178, fill="#b98918", outline="#fff1ad")
        if self._mouth_open:
            self.create_oval(cx-43, 195, cx+43, 232, fill="#25c6ff", outline="#ffffff", width=3)
            self.create_oval(cx-32, 202, cx+32, 225, fill="#07111f")
        else:
            self.create_line(cx-42, 213, cx+42, 213, fill="#07111f", width=8)
        if self.speaking:
            self.create_text(cx, h-8, text="SPEAKING", fill="#67e8f9", font=("Arial", 11, "bold"))
