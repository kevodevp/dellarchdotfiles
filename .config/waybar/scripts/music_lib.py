"""Shared MPRIS helpers for the waybar music widget."""

import base64
import os
import shutil
import subprocess
import urllib.parse

CACHE_DIR = os.path.expanduser("~/.cache/waybar")
COVER = os.path.join(CACHE_DIR, "cover.img")
COVER_KEY = os.path.join(CACHE_DIR, "cover.key")

# 1x1 transparent PNG, used when there is nothing to show
BLANK = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)

SEP = "\x1f"
FIELDS = [
    "{{status}}",
    "{{title}}",
    "{{artist}}",
    "{{album}}",
    "{{mpris:artUrl}}",
    "{{playerName}}",
    "{{mpris:length}}",
]


def sh(args, timeout=3):
    """Run a command, return (ok, stdout)."""
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except Exception:
        return False, ""
    return proc.returncode == 0, proc.stdout.rstrip("\n")


def _read(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return ""


def info():
    """Return the active player's state, or None when nothing is playing."""
    ok, raw = sh(["playerctl", "metadata", "--format", SEP.join(FIELDS)])
    if not ok or not raw:
        return None

    parts = raw.split(SEP)
    parts += [""] * (len(FIELDS) - len(parts))
    status, title, artist, album, art, player, length = parts[:7]

    try:
        length = float(length) / 1e6
    except ValueError:
        length = 0.0

    ok, pos = sh(["playerctl", "position"])
    try:
        position = float(pos) if ok else 0.0
    except ValueError:
        position = 0.0

    return {
        "status": status.lower() or "stopped",
        "title": title,
        "artist": artist,
        "album": album,
        "art": art,
        "player": player,
        "length": length,
        "position": position,
    }


def update_cover(art):
    """Copy/download the current cover art to a stable cache path."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    if not art:
        clear_cover()
        return None

    if _read(COVER_KEY) == art and os.path.exists(COVER):
        return COVER

    if art.startswith("file://"):
        try:
            shutil.copyfile(urllib.parse.unquote(art[7:]), COVER)
        except OSError:
            return COVER if os.path.exists(COVER) else None
    elif art.startswith(("http://", "https://")):
        ok, _ = sh(["curl", "-fsSL", "--max-time", "8", "-o", COVER, art])
        if not ok:
            return COVER if os.path.exists(COVER) else None
    else:
        return COVER if os.path.exists(COVER) else None

    try:
        with open(COVER_KEY, "w", encoding="utf-8") as handle:
            handle.write(art)
    except OSError:
        pass
    return COVER if os.path.exists(COVER) else None


def clear_cover():
    """Blank the cached cover art when nothing is playing."""
    if _read(COVER_KEY) == "" and os.path.exists(COVER):
        return
    os.makedirs(CACHE_DIR, exist_ok=True)
    try:
        with open(COVER, "wb") as handle:
            handle.write(BLANK)
        with open(COVER_KEY, "w", encoding="utf-8"):
            pass
    except OSError:
        pass
