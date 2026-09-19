import logging
import tkinter as tk
import winsound

import config

log = logging.getLogger("news-updater.overlay")


def _position(root):
    root.update_idletasks()
    screen_width = root.winfo_screenwidth()
    width = config.OVERLAY_WIDTH
    x = (screen_width - width) // 2
    root.geometry(f"{width}x{config.OVERLAY_HEIGHT}+{x}+{config.OVERLAY_TOP_OFFSET}")


def _build(root, has_news, audio_path):
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.configure(bg=config.OVERLAY_BG)

    frame = tk.Frame(root, bg=config.OVERLAY_BG)
    frame.pack(expand=True, fill="both", padx=16, pady=12)

    title = tk.Label(
        frame,
        text="There is news" if has_news else "No news",
        bg=config.OVERLAY_BG,
        fg=config.OVERLAY_FG,
        font=("Segoe UI", 13, "bold"),
    )
    title.pack(pady=(4, 12))

    buttons = tk.Frame(frame, bg=config.OVERLAY_BG)
    buttons.pack()

    if has_news:
        play = tk.Button(
            buttons,
            text="Play",
            width=10,
            command=lambda: _play(audio_path),
        )
        play.pack(side="left", padx=4)

    close = tk.Button(buttons, text="Close", width=10, command=root.destroy)
    close.pack(side="left", padx=4)

    _position(root)


def _play(audio_path):
    try:
        winsound.PlaySound(str(audio_path), winsound.SND_FILENAME | winsound.SND_ASYNC)
    except Exception as exc:
        log.warning("overlay playback failed: %s", exc)


def show(has_news, audio_path):
    log.info("showing overlay (has_news=%s)", has_news)
    try:
        root = tk.Tk()
    except Exception as exc:
        log.warning("overlay unavailable: %s", exc)
        return
    _build(root, has_news, audio_path)
    root.mainloop()
    log.info("overlay closed")
