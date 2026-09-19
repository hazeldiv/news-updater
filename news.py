import hashlib
import json
import logging
import os
import re
import tempfile
import time
from datetime import datetime, timedelta, timezone

import requests

import config

log = logging.getLogger("news-updater.news")

SEEN_NEWS_TTL_DAYS = 14


class LLMError(Exception):
    pass


SYSTEM_PROMPT = f"""You write a short spoken news briefing for a text-to-speech reader.

Report ANY new model or version release from these labs: Qwen, DeepSeek, GLM (Zhipu), Kimi (Moonshot), and Claude (Anthropic). For [OI] GPT and Google Gemini, report MAJOR versions only (for example GPT-6 or Gemini 3); ignore sub-models, minor updates, and point releases.

You are given an ALREADY ANNOUNCED MODEL RELEASES list. Never report a release that is the same model as any entry on that list, even if the headline uses a different name or wording. Only report a release that is genuinely new. Never report a release that came out more than {config.MODEL_HISTORY_DAYS} days ago.

For markets, only mention an entry when it is marked "first sighting" or when its move is at least {config.PRICE_THRESHOLD_PCT:g} percent. All percentages and prices are already computed for you; never calculate anything yourself. Narrate them naturally, for example "up 6.2 percent to 2650 dollars". When an entry includes a "since" time, always state that period in the narration, for example "bitcoin is up 6.2 percent since about 2 hours ago, now 74000 dollars".

Output ONLY a JSON object of the form {{"narration": "...", "releases": [{{"name": "...", "release_date": "YYYY-MM-DD"}}]}}. The narration must be plain spoken English, under {config.MAX_WORDS} words, with no URLs, no markdown, and no emoji. Use a specific full model name with vendor and version in each release entry. If nothing qualifies, output exactly {{"narration": null, "releases": []}}."""


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def _empty_state():
    return {"prices": {}, "seen_news": {}, "models": {}, "last_run": None}


def load_state():
    path = config.STATE_FILE
    if not path.exists():
        return _empty_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("state is not a JSON object")
        state = _empty_state()
        state.update(data)
        if not isinstance(state["prices"], dict):
            state["prices"] = {}
        if not isinstance(state["seen_news"], dict):
            state["seen_news"] = {}
        if not isinstance(state["models"], dict):
            state["models"] = {}
        return state
    except Exception:
        try:
            os.replace(path, path.with_name(path.name + ".bak"))
        except OSError:
            pass
        return _empty_state()


def save_state(state):
    config.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=str(config.STATE_FILE.parent), prefix="state-", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2)
        os.replace(tmp, config.STATE_FILE)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def price_change_pct(previous_price, current_price):
    if not previous_price:
        return None
    return (current_price - previous_price) / previous_price * 100.0


def title_hash(title):
    normalized = re.sub(r"\s+", " ", title.strip().lower())
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def prune_seen(state, days=SEEN_NEWS_TTL_DAYS):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    kept = {}
    for key, timestamp in state.get("seen_news", {}).items():
        try:
            seen_at = datetime.fromisoformat(timestamp)
        except (TypeError, ValueError):
            continue
        if seen_at.tzinfo is None:
            seen_at = seen_at.replace(tzinfo=timezone.utc)
        if seen_at >= cutoff:
            kept[key] = timestamp
    state["seen_news"] = kept


def _normalize(text):
    return re.sub(r"\s+", " ", text.strip().lower())


def _known_pattern(name):
    name = _normalize(name)
    if not name:
        return None
    return re.compile(r"(?<![a-z0-9.])" + re.escape(name) + r"(?![a-z0-9.])")


def filter_known_models(news_items, models):
    patterns = [p for p in (_known_pattern(name) for name in models) if p]
    if not patterns:
        return list(news_items)
    kept = []
    for item in news_items:
        title = _normalize(item["title"])
        if any(pattern.search(title) for pattern in patterns):
            log.info("skipping known model release: %s", item["title"])
            continue
        kept.append(item)
    return kept


def recent_models(models, days=config.MODEL_HISTORY_DAYS):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    recent = {}
    for name, record in models.items():
        announced = record.get("announced_at") if isinstance(record, dict) else None
        try:
            announced_at = datetime.fromisoformat(announced)
        except (TypeError, ValueError):
            continue
        if announced_at.tzinfo is None:
            announced_at = announced_at.replace(tzinfo=timezone.utc)
        if announced_at >= cutoff:
            recent[name] = record
    return recent


def fetch_hn_news():
    since = int(time.time()) - config.NEWS_WINDOW_HOURS * 3600
    headers = {"User-Agent": config.BROWSER_UA}
    items = []
    seen = set()
    for query in config.HN_QUERIES:
        params = {
            "query": query,
            "tags": "story",
            "numericFilters": f"created_at_i>{since}",
            "hitsPerPage": config.HN_HITS_PER_PAGE,
        }
        try:
            response = requests.get(
                config.HN_API_URL,
                params=params,
                headers=headers,
                timeout=config.HTTP_TIMEOUT,
            )
            response.raise_for_status()
            hits = response.json().get("hits", [])
        except Exception as exc:
            log.warning("HN query failed for %r: %s", query, exc)
            continue
        for hit in hits:
            title = (hit.get("title") or "").strip()
            if not title:
                continue
            key = title_hash(title)
            if key in seen:
                continue
            seen.add(key)
            items.append(
                {
                    "title": title,
                    "url": hit.get("url") or hit.get("story_url") or "",
                    "created_at": hit.get("created_at"),
                    "points": hit.get("points") or 0,
                    "query": query,
                }
            )
    log.info("HN news fetched: %d unique items", len(items))
    return items


def _yahoo_price(symbol):
    response = requests.get(
        config.YAHOO_CHART_URL.format(symbol=symbol),
        params={"range": "1d", "interval": "1d"},
        headers={"User-Agent": config.BROWSER_UA},
        timeout=config.HTTP_TIMEOUT,
    )
    response.raise_for_status()
    results = response.json().get("chart", {}).get("result") or []
    if not results:
        raise ValueError("empty chart result")
    price = results[0].get("meta", {}).get("regularMarketPrice")
    if price is None:
        raise ValueError("missing regularMarketPrice")
    return float(price)


def _coingecko_bitcoin_price():
    response = requests.get(
        config.COINGECKO_URL,
        params={"ids": "bitcoin", "vs_currencies": "usd"},
        headers={"User-Agent": config.BROWSER_UA},
        timeout=config.HTTP_TIMEOUT,
    )
    response.raise_for_status()
    return float(response.json()["bitcoin"]["usd"])


def fetch_market_prices():
    prices = {}
    for market in config.MARKETS:
        name = market["name"]
        price = None
        source = "yahoo"
        try:
            price = _yahoo_price(market["symbol"])
        except Exception as exc:
            log.warning("Yahoo fetch failed for %s: %s", market["symbol"], exc)
        if price is None and name == "bitcoin":
            try:
                price = _coingecko_bitcoin_price()
                source = "coingecko"
            except Exception as exc:
                log.warning("CoinGecko fallback failed for bitcoin: %s", exc)
        if price is None:
            log.warning("skipping market %s (no price)", name)
            continue
        prices[name] = {
            "name": name,
            "symbol": market["symbol"],
            "label": market["label"],
            "price": price,
            "source": source,
        }
    log.info("market prices fetched: %d/%d", len(prices), len(config.MARKETS))
    return prices


def humanize_age(timestamp):
    if not timestamp:
        return None
    try:
        then = datetime.fromisoformat(timestamp)
    except (TypeError, ValueError):
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    minutes = (datetime.now(timezone.utc) - then).total_seconds() / 60
    if minutes < 0:
        minutes = 0
    if minutes < 90:
        return f"about {max(1, round(minutes))} minutes ago"
    hours = minutes / 60
    if hours < 36:
        return f"about {round(hours)} hours ago"
    return f"about {round(hours / 24)} days ago"


def build_market_events(current_state, prices):
    events = []
    for name, data in prices.items():
        previous = current_state["prices"].get(name)
        if previous is None:
            events.append({**data, "first_seen": True, "pct_change": None, "since": None})
            continue
        pct = price_change_pct(previous.get("price"), data["price"])
        if pct is not None and abs(pct) >= config.PRICE_THRESHOLD_PCT:
            events.append(
                {
                    **data,
                    "first_seen": False,
                    "pct_change": pct,
                    "since": humanize_age(previous.get("announced_at")),
                }
            )
    return events


def narrate(news_items, events, models):
    if not config.OPENROUTER_API_KEY:
        raise LLMError("OPENROUTER_API_KEY is not set")
    if not config.OPENROUTER_MODELS:
        raise LLMError("OPENROUTER_MODELS is not set")
    user_message = _build_user_message(news_items, events, models)
    last_error = None
    for model in config.OPENROUTER_MODELS:
        try:
            content = _call_model(model, user_message)
            log.info("model %s raw response: %s", model, content)
            narration, releases = _parse_response(content)
            log.info(
                "model %s responded (%s, %d releases)",
                model,
                "narration" if narration else "null",
                len(releases),
            )
            return {"narration": narration, "releases": releases}
        except Exception as exc:
            last_error = exc
            log.warning("model %s failed: %s", model, exc)
    raise LLMError(f"all OpenRouter models failed: {last_error}")


def _build_user_message(news_items, events, models):
    lines = []
    if news_items:
        lines.append("NEW MODEL RELEASES (candidates):")
        for item in news_items:
            lines.append(f"- {item['title']} (source: {item.get('url', '')})")
    else:
        lines.append("NEW MODEL RELEASES: none")
    lines.append("")
    recent = recent_models(models)
    if recent:
        lines.append("ALREADY ANNOUNCED MODEL RELEASES (do not report again):")
        for name, record in recent.items():
            release_date = record.get("release_date") or "unknown"
            lines.append(f"- {name} (released {release_date})")
    else:
        lines.append("ALREADY ANNOUNCED MODEL RELEASES: none")
    lines.append("")
    if events:
        lines.append("MARKET MOVES (already computed, report as given):")
        for event in events:
            if event["first_seen"]:
                lines.append(
                    f"- {event['label']}: first sighting, currently {event['price']:.2f}"
                )
            else:
                direction = "up" if event["pct_change"] >= 0 else "down"
                since = f" since {event['since']}" if event.get("since") else ""
                lines.append(
                    f"- {event['label']}: {direction} "
                    f"{abs(event['pct_change']):.2f} percent{since}, "
                    f"now {event['price']:.2f}"
                )
    else:
        lines.append("MARKET MOVES: none")
    return "\n".join(lines)


def _call_model(model, user_message):
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.3,
        "max_tokens": 500,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    response = requests.post(
        config.OPENROUTER_URL,
        json=payload,
        headers=headers,
        timeout=config.MODEL_TIMEOUT,
    )
    if response.status_code == 429:
        raise LLMError("rate limited (429)")
    response.raise_for_status()
    choices = response.json().get("choices") or []
    if not choices:
        raise LLMError("empty choices")
    content = (choices[0].get("message") or {}).get("content") or ""
    if not content.strip():
        raise LLMError("empty content")
    return content


def _parse_response(content):
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    data = None
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                data = None
    if not isinstance(data, dict):
        return None, []
    narration = data.get("narration")
    if narration is not None:
        narration = str(narration).strip() or None
    return narration, _parse_releases(data.get("releases"))


def _parse_releases(raw):
    releases = []
    if not isinstance(raw, list):
        return releases
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        releases.append(
            {"name": name, "release_date": str(entry.get("release_date") or "").strip()}
        )
    return releases
