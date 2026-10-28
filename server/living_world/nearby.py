"""What was just said nearby (voiced lines from the World module's listener plugin, said_nearby.json) and why an
ambient talk started (banter.json, written by World's banter and initiative), as short lines for the newest message."""

MAX_AGE = 300.0   # seconds: older lines are not "just said" any more
MAX_LINES = 3


def said_nearby(lines: list, now: float) -> str:
    recent = []
    for line in lines or []:
        if not isinstance(line, dict):
            continue
        t, speaker, text = line.get('time'), line.get('speaker'), line.get('text')
        if not isinstance(t, (int, float)) or not isinstance(speaker, str) or not isinstance(text, str):
            continue
        if 0 <= now - t <= MAX_AGE and text.strip():
            recent.append((t, speaker, text.strip()))
    if not recent:
        return ''
    recent.sort()
    said = ' '.join(f'{speaker}: "{text}"' for _, speaker, text in recent[-MAX_LINES:])
    return f"(Said nearby a moment ago: {said} React to it if it fits, but do not repeat it.)"


def seed(banter: dict) -> str:
    text = banter.get('seed') if isinstance(banter, dict) else None
    if not isinstance(text, str) or not text.strip() or banter.get('active') != 1:
        return ''
    return f"({text.strip()})"
