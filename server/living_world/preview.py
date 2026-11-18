"""What the last request looked like, for the tab's prompt preview: system parts with token estimates, the number
of actions offered, and who was speaking."""
import time

_last: dict = {'speakers': [], 'parts': [], 'total': 0, 'tools': 0, 'time': 0.0}
_by_npc: dict = {}  # name -> [(part, text)] in the order sent, from the last request with that NPC alone


def tokens(text: str) -> int:
    return (len(text) + 3) // 4


def record_system(parts: dict[str, str], speakers: list[str]) -> None:
    rows = [(name, tokens(text)) for name, text in parts.items() if not name.startswith('__') and isinstance(text, str)]
    _last.update(speakers=list(speakers), parts=rows, total=sum(t for _, t in rows), time=time.time())
    if len(speakers) == 1:
        order = [k for k in parts.get('__order__') or [] if isinstance(parts.get(k), str)]
        order = order or [k for k in parts if not k.startswith('__') and isinstance(parts[k], str)]
        _by_npc[speakers[0]] = [(k, parts[k]) for k in order]


def last_for(name: str) -> list:
    """The system prompt parts last sent for this NPC alone, in order; [] when none this session."""
    return list(_by_npc.get(name) or [])


def record_tools(count: int, speakers: list[str]) -> None:
    _last.update(tools=count, speakers=list(speakers) or _last['speakers'])


def latest() -> dict:
    return dict(_last)


_sections: dict = {'speakers': [], 'rows': {}, 'time': 0.0}  # the last request, part by part, per NPC (sizes_report)


def record_sections(speakers: list[str], rows: dict) -> None:
    """The last request's size by section, per NPC: rows {name: [(section, tokens or None, note)]}."""
    _sections.update(speakers=list(speakers), rows={k: list(v) for k, v in rows.items()}, time=time.time())


def sections_for(name: str) -> list:
    """[(section, tokens or None, note)] of the last request with this NPC in it this session; [] when none."""
    return list(_sections['rows'].get(name) or [])


def sections_text() -> str:
    """The last request's sections and their size in tokens, per NPC, for the Status page."""
    if not _sections['rows']:
        return 'Nothing sent yet this session.'
    out = []
    for name, rows in _sections['rows'].items():
        out.append(f"{name}: " + ', '.join(f"{section} {count:,}" + (f" ({note})" if note else '') if count is not None
                                           else f"{section}: {note}" for section, count, note in rows))
    return '\n\n'.join(out)
