"""Discord webhook delivery for trade alerts and reports.

All Bull notifications funnel through lib.clickup._post_task → send_discord.
Messages are plain Discord markdown so they read like a chat/text thread on
desktop and mobile.
"""

import os

import requests

# Discord rejects message content longer than 2000 characters, so we chunk
# below that with headroom for the bold title wrapper.
_MAX_CONTENT = 1900


def discord_enabled() -> bool:
    return bool(os.environ.get("DISCORD_WEBHOOK_URL"))


def _chunks(text: str, size: int = _MAX_CONTENT) -> list[str]:
    """Split text into <=size pieces, preferring newline boundaries."""
    if len(text) <= size:
        return [text]
    pieces, current = [], ""
    for line in text.split("\n"):
        # A single line longer than the limit: hard-split it.
        while len(line) > size:
            if current:
                pieces.append(current)
                current = ""
            pieces.append(line[:size])
            line = line[size:]
        if len(current) + len(line) + 1 > size:
            pieces.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        pieces.append(current)
    return pieces


def send_discord(title: str, description: str) -> bool:
    """Post a message to the configured Discord webhook. Never raises.

    Returns True if every chunk was delivered, False otherwise.
    """
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not url:
        return False

    body = f"**{title}**\n{description}" if description else f"**{title}**"
    ok = True
    try:
        for chunk in _chunks(body):
            resp = requests.post(
                url,
                json={"content": chunk},
                timeout=10,
            )
            # Discord webhooks return 204 No Content on success.
            if resp.status_code not in (200, 204):
                print(f"Discord error {resp.status_code}: {resp.text[:200]}")
                ok = False
    except Exception as e:
        print(f"Discord request failed: {e}")
        return False
    return ok
