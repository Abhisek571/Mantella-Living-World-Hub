"""What the last request looked like, for the tab's prompt preview: system parts with token estimates, the number
of actions offered, and who was speaking."""
import time

_last: dict = {'speakers': [], 'parts': [], 'total': 0, 'tools': 0, 'time': 0.0}


def tokens(text: str) -> int:
    return (len(text) + 3) // 4


def record_system(parts: dict[str, str], speakers: list[str]) -> None:
    rows = [(name, tokens(text)) for name, text in parts.items() if not name.startswith('__') and isinstance(text, str)]
    _last.update(speakers=list(speakers), parts=rows, total=sum(t for _, t in rows), time=time.time())


def record_tools(count: int, speakers: list[str]) -> None:
    _last.update(tools=count, speakers=list(speakers) or _last['speakers'])


def latest() -> dict:
    return dict(_last)
