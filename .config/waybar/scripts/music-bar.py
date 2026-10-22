#!/usr/bin/env python3
"""waybar `custom/music`: now-playing text with a marquee for long titles.

Runs as a single long-lived process and streams one JSON line per update
(waybar's "looping script" mode), which is far cheaper than re-spawning.
"""

import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import music_lib  # noqa: E402

PERIOD = 0.5        # seconds between updates
WIDTH = 24          # visible characters; longer titles start scrolling
GAP = "   •   "
STATE = os.path.join(music_lib.CACHE_DIR, "scroll.state")


def marquee(text, key):
    """Return the next WIDTH-character window of a looping title."""
    if len(text) <= WIDTH:
        return text

    saved_key, offset = "", 0
    try:
        with open(STATE, encoding="utf-8") as handle:
            saved_key, saved_offset = handle.read().split("\t")
        if saved_key == key:
            offset = int(saved_offset)
    except (OSError, ValueError):
        pass

    cycle = len(text) + len(GAP)
    view = (text + GAP + text)[offset:offset + WIDTH]

    try:
        os.makedirs(music_lib.CACHE_DIR, exist_ok=True)
        with open(STATE, "w", encoding="utf-8") as handle:
            handle.write(f"{key}\t{(offset + 1) % cycle}")
    except OSError:
        pass

    return view


def payload():
    nfo = music_lib.info()
    if not nfo or not nfo["title"]:
        music_lib.clear_cover()
        return {"text": "", "tooltip": "", "class": "stopped"}

    music_lib.update_cover(nfo["art"])

    key = hashlib.sha1(f"{nfo['title']}\t{nfo['artist']}".encode()).hexdigest()[:16]
    tooltip = "\n".join(p for p in (nfo["title"], nfo["artist"], nfo["album"]) if p)

    return {
        "text": marquee(nfo["title"], key),
        "tooltip": tooltip,
        "class": nfo["status"],
    }


def main():
    while True:
        try:
            sys.stdout.write(json.dumps(payload()) + "\n")
            sys.stdout.flush()
        except BrokenPipeError:
            return
        except Exception:
            pass
        time.sleep(PERIOD)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
