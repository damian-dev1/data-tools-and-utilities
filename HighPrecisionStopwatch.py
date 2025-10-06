import tkinter as tk
from tkinter import ttk
import time

class HighPrecisionStopwatch:
    def __init__(self, root):
        self.root = root
        self.root.title("High Precision Stopwatch")
        self.root.geometry("400x180")
        self.root.resizable(False, False)

        self.start_time = None
        self.elapsed = 0.0
        self.running = False

        self._build_ui()
        self._update_display()

    def _build_ui(self):
        # Display
        self.time_var = tk.StringVar(value="00:00.00")
        time_label = ttk.Label(self.root, textvariable=self.time_var, font=("Segoe UI", 32, "bold"))
        time_label.pack(pady=(20, 10))

        # Buttons
        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(pady=(0, 10))

        self.start_btn = ttk.Button(btn_frame, text="Start", command=self.start)
        self.pause_btn = ttk.Button(btn_frame, text="Pause", command=self.pause)
        self.resume_btn = ttk.Button(btn_frame, text="Resume", command=self.resume)
        self.reset_btn = ttk.Button(btn_frame, text="Reset", command=self.reset)

        self.start_btn.grid(row=0, column=0, padx=5)
        self.pause_btn.grid(row=0, column=1, padx=5)
        self.resume_btn.grid(row=0, column=2, padx=5)
        self.reset_btn.grid(row=0, column=3, padx=5)

        self._update_buttons()

    def _update_display(self):
        if self.running:
            current = time.perf_counter()
            self.elapsed = current - self.start_time
        mins, secs = divmod(self.elapsed, 60)
        self.time_var.set(f"{int(mins):02}:{secs:05.2f}")
        self.root.after(10, self._update_display)

    def _update_buttons(self):
        self.start_btn["state"] = "normal" if not self.running and self.elapsed == 0 else "disabled"
        self.pause_btn["state"] = "normal" if self.running else "disabled"
        self.resume_btn["state"] = "normal" if not self.running and self.elapsed > 0 else "disabled"
        self.reset_btn["state"] = "normal" if self.elapsed > 0 else "disabled"

    def start(self):
        self.start_time = time.perf_counter()
        self.running = True
        self._update_buttons()

    def pause(self):
        self.running = False
        self.elapsed = time.perf_counter() - self.start_time
        self._update_buttons()

    def resume(self):
        self.start_time = time.perf_counter() - self.elapsed
        self.running = True
        self._update_buttons()

    def reset(self):
        self.running = False
        self.elapsed = 0.0
        self.start_time = None
        self._update_buttons()

if __name__ == "__main__":
    root = tk.Tk()
    HighPrecisionStopwatch(root)
    root.mainloop()
