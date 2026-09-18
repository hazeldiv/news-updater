import ctypes
import logging
import time
import winsound
from ctypes import wintypes
from pathlib import Path

import config

log = logging.getLogger("news-updater.audio")

_engine = None


class _TolerantTextCleaner:
    def __init__(self, dummy=None):
        import styletts2.text_utils as text_utils

        self.word_index_dictionary = text_utils.dicts

    def __call__(self, text):
        indexes = []
        for char in text:
            index = self.word_index_dictionary.get(char)
            if index is not None:
                indexes.append(index)
        return indexes


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def ensure_reference_voice(voice=None):
    voice = config.REFERENCE_VOICE if voice is None else voice
    if not voice:
        return None
    path = Path(voice)
    if not path.is_absolute():
        path = config.VOICE_DIR / path
    if not path.exists() and not path.suffix:
        path = path.with_suffix(".wav")
    if not path.exists():
        log.warning("reference voice not found: %s", path)
        return None
    return path


def _prepare_styletts2():
    import torch

    original_load = torch.load

    def load(*args, **kwargs):
        kwargs.setdefault("weights_only", False)
        return original_load(*args, **kwargs)

    torch.load = load

    import styletts2.tts as styletts_tts

    styletts_tts.TextCleaner = _TolerantTextCleaner


def _get_engine():
    global _engine
    if _engine is None:
        _prepare_styletts2()
        from styletts2 import tts

        log.info("loading StyleTTS2 (first run downloads checkpoints)")
        _engine = tts.StyleTTS2()
    return _engine


def truncate(text, max_words=config.MAX_WORDS):
    words = text.split()
    if len(words) <= max_words:
        return text
    clipped = " ".join(words[:max_words]).rstrip(" .,;:")
    return clipped + "."


def synthesize(text, output_path=config.AUDIO_FILE, voice=None):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    engine = _get_engine()
    reference = ensure_reference_voice(voice)
    target = str(reference) if reference is not None else None
    engine.inference(
        truncate(text), target_voice_path=target, output_wav_file=str(output_path)
    )
    log.info("wav written: %s", output_path)
    return output_path


def get_last_input_tick():
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        raise ctypes.WinError()
    return info.dwTime & 0xFFFFFFFF


def wait_for_activity():
    last_tick = get_last_input_tick()
    count = 0
    last_event = None
    started = time.monotonic()
    log.info("polling for %d activity events", config.REQUIRED_EVENTS)
    while True:
        if time.monotonic() - started >= config.SAFETY_TIMEOUT:
            log.info("safety timeout reached, playing anyway")
            return True
        time.sleep(config.POLL_INTERVAL)
        now = time.monotonic()
        current_tick = get_last_input_tick()
        if current_tick == last_tick:
            if count and last_event is not None and now - last_event >= config.IDLE_RESET:
                log.info("idle reset after %ds", config.IDLE_RESET)
                count = 0
                last_event = None
            continue
        last_tick = current_tick
        if count == 0 or last_event is None or now - last_event >= config.EVENT_MIN_GAP:
            count += 1
            last_event = now
            log.info("activity event %d/%d", count, config.REQUIRED_EVENTS)
            if count >= config.REQUIRED_EVENTS:
                return True


def play_wav(path):
    log.info("playing %s", path)
    winsound.PlaySound(str(path), winsound.SND_FILENAME)
