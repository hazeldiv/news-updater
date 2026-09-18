import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(str(BASE_DIR / ".env"))

LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "news-updater.log"
AUDIO_DIR = BASE_DIR / "audio"
AUDIO_FILE = AUDIO_DIR / "news.wav"
STATE_FILE = BASE_DIR / "state.json"
VOICE_DIR = BASE_DIR / "voice"
REFERENCE_VOICE = "narration"

HN_API_URL = "https://hn.algolia.com/api/v1/search_by_date"
HN_QUERIES = [
    "Qwen",
    "DeepSeek",
    "GLM",
    "Zhipu",
    "Kimi",
    "Moonshot",
    "Anthropic",
    "Claude",
    "OpenAI GPT",
    "Gemini",
]
NEWS_WINDOW_HOURS = 24
HN_HITS_PER_PAGE = 20

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
HTTP_TIMEOUT = 15

MARKETS = [
    {"name": "gold", "symbol": "GC=F", "label": "gold"},
    {"name": "oil", "symbol": "CL=F", "label": "oil"},
    {"name": "usd_idr", "symbol": "USDIDR=X", "label": "the US dollar against the Indonesian rupiah"},
    {"name": "bitcoin", "symbol": "BTC-USD", "label": "bitcoin"},
    {"name": "ihsg", "symbol": "^JKSE", "label": "the Jakarta Composite Index"},
    {"name": "spacex", "symbol": "SPCX", "label": "SpaceX stock"},
]
PRICE_THRESHOLD_PCT = float(os.getenv("PRICE_THRESHOLD_PERCENT", "5"))

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_MODELS = [
    model.strip()
    for model in os.getenv("OPENROUTER_MODELS", "").split(",")
    if model.strip()
]
MODEL_TIMEOUT = 60

POLL_INTERVAL = 0.7
IDLE_RESET = 60
EVENT_MIN_GAP = 5
REQUIRED_EVENTS = 3
SAFETY_TIMEOUT = 4 * 3600

MAX_WORDS = 130
NO_NEWS_MESSAGE = "No significant news today."


def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)
    if sys.stderr is not None:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(fmt)
        root.addHandler(stream_handler)
