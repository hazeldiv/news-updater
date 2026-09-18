import argparse
import logging
import os

import audio
import config
import news

log = logging.getLogger("news-updater")


def run_briefing(no_play):
    current_state = news.load_state()
    news.prune_seen(current_state)

    items = news.fetch_hn_news()
    prices = news.fetch_market_prices()

    candidates = [
        item
        for item in items
        if news.title_hash(item["title"]) not in current_state["seen_news"]
    ]
    events = news.build_market_events(current_state, prices)
    log.info("candidates: %d news, %d market events", len(candidates), len(events))

    narration = None
    if candidates or events:
        narration = news.narrate(candidates, events)
    spoken = narration or config.NO_NEWS_MESSAGE

    audio_path = audio.synthesize(spoken)

    timestamp = news.now_iso()
    for item in candidates:
        current_state["seen_news"][news.title_hash(item["title"])] = timestamp
    if narration:
        for event in events:
            current_state["prices"][event["name"]] = {
                "symbol": event["symbol"],
                "price": event["price"],
                "announced_at": timestamp,
                "source": event["source"],
            }
    current_state["last_run"] = timestamp
    news.save_state(current_state)
    log.info("state saved")

    if no_play:
        log.info("dry run: skipping activity wait and playback")
        return 0

    audio.wait_for_activity()
    audio.play_wav(audio_path)
    log.info("playback finished")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Spoken news briefing at logon")
    parser.add_argument("--tts", metavar="TEXT", help="synthesize TEXT and exit")
    parser.add_argument("--no-play", action="store_true", help="dry run, no playback")
    args = parser.parse_args(argv)

    config.setup_logging()
    log.info("run start (pid=%s)", os.getpid())
    try:
        if args.tts is not None:
            audio_path = audio.synthesize(args.tts)
            if not args.no_play:
                audio.play_wav(audio_path)
            return 0
        return run_briefing(args.no_play)
    except Exception:
        log.exception("fatal error, exiting quietly")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
