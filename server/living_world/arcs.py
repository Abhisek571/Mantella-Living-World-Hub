"""Story arcs: memories that belong to one ongoing story (a courtship, a feud, a journey, a time under a spell) carry
the same arc id, and the arc has a short label and a one-line summary of the story so far. When a memory of an arc is
recalled, that one line comes with it instead of scattered pieces of the story.

No model call of its own. An arc is assigned when a memory goes into the archive (archive.Archive.add calls assign):
- by the story label the end-of-talk summary already gave ("story": {"label", "so_far"} in the same reply; memory.py
  asks for it and lists the NPC's arcs in that prompt), or
- by meaning and time: a new memory close in meaning to a recent one of an arc joins it; two very close memories a
  few days apart start a new arc together.

Arcs live in the NPC's archive (arcs table, memories.arc). The functions at the bottom are for the Hub's pages: list,
rename, merge, add to and remove from an arc, delete an arc. Every change by hand is kept (by_hand): the summary model
then no longer rewrites that arc's label or summary."""
import hashlib
import logging
import re
import sqlite3
import time

from . import embed

logger = logging.getLogger('Mantella')

JOIN_MEANING = 0.6   # a new memory this close to a member of an arc joins it...
JOIN_DAYS = 30       # ...when that member is at most this many days older
NEW_MEANING = 0.75   # two memories at least this close...
NEW_DAYS = 10        # ...and this close in time start an arc together
MAX_LABEL = 60
MAX_SUMMARY = 300
SCAN_ROWS = 300      # newest rows looked at for a match by meaning


def _norm(text) -> str:
    return ' '.join(re.sub(r'[^\w]+', ' ', str(text).lower()).split())


def clean_label(text) -> str:
    return ' '.join(str(text or '').split())[:MAX_LABEL].strip(' .,;:')


def clean_summary(text) -> str:
    return ' '.join(str(text or '').split())[:MAX_SUMMARY]


def new_id(label: str) -> str:
    return hashlib.sha1(f'{label}|{time.time()}|{id(label)}'.encode('utf-8')).hexdigest()[:12]


def _first_sentence(text: str, limit: int = 120) -> str:
    text = ' '.join(str(text or '').split())
    cut = re.split(r'(?<=[.!?])\s', text, maxsplit=1)[0]
    return cut[:limit].rstrip() + ('...' if len(cut) > limit else '')


def auto_summary(members: list[dict]) -> str:
    """For an arc the summary model did not describe: how it began and where it stands, from its own memories."""
    dated = sorted(members, key=lambda r: (r.get('day', -1), r.get('hour', -1)))
    if not dated:
        return ''
    first, last = _first_sentence(dated[0].get('text')), _first_sentence(dated[-1].get('text'))
    return clean_summary(first if len(dated) == 1 or first == last else f'It began: {first} Lately: {last}')


def _auto_label(a: dict, b: dict) -> str:
    shared = [t for t in a.get('tags') or [] if t in (b.get('tags') or [])]
    if shared:
        return clean_label(' and '.join(shared[:2]))
    return clean_label(' '.join(_first_sentence(a.get('text'), 40).split()[:5]))


def _vector(row, np):
    if row.get('vector') is not None:
        return row['vector']
    blob = row.get('embedding')
    if row.get('model') == embed.MODEL_ID and isinstance(blob, bytes) and len(blob) == embed.DIM * 4:
        return np.frombuffer(blob, dtype=np.float32)
    return None


def assign(archive, added: list) -> None:
    """added: (id, entry, vector or None) for rows just stored."""
    if not added:
        return
    arcs = archive.arcs()
    by_label = {_norm(a['label']): a for a in arcs if a['label']}
    rows = None
    for row_id, entry, vector in added:
        label = clean_label(entry.get('arc_label'))
        if label:
            arc = by_label.get(_norm(label))
            if arc is None:
                arc = {'id': new_id(label), 'label': label, 'summary': '', 'day': -1, 'made': time.time(), 'by_hand': False}
                by_label[_norm(label)] = arc
            summary = clean_summary(entry.get('arc_summary'))
            if summary and not arc['by_hand']:
                arc['summary'] = summary
            arc['day'] = max(arc.get('day', -1), _int(entry.get('day')))
            archive.save_arc(arc)
            archive.set_arc([row_id], arc['id'])
            if not arc['summary']:
                _refresh_auto(archive, arc)
            continue
        if vector is None or entry.get('hidden') or entry.get('type') == 'diary':
            continue
        if rows is None:
            rows = [r for r in archive.rows()[-SCAN_ROWS:] if r.get('branch') != 'other']
        match = _closest(rows, row_id, entry, vector)
        if match is None:
            continue
        sim, other = match
        if other.get('arc') and sim >= JOIN_MEANING and _days_apart(other, entry) <= JOIN_DAYS:
            archive.set_arc([row_id], other['arc'])
            arc = next((a for a in archive.arcs() if a['id'] == other['arc']), None)
            if arc is not None:
                arc['day'] = max(arc.get('day', -1), _int(entry.get('day')))
                archive.save_arc(arc)
                if not arc['by_hand'] and (not arc['summary'] or arc['summary'].startswith('It began:')):
                    _refresh_auto(archive, arc)
        elif not other.get('arc') and sim >= NEW_MEANING and _days_apart(other, entry) <= NEW_DAYS:
            label = _auto_label(other, entry)
            if not label:
                continue
            arc = {'id': new_id(label), 'label': label, 'summary': '', 'day': _int(entry.get('day')), 'made': time.time(),
                   'by_hand': False}
            archive.save_arc(arc)
            archive.set_arc([row_id, other['id']], arc['id'])
            other['arc'] = arc['id']
            _refresh_auto(archive, arc)


def _int(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else -1


def _days_apart(a: dict, b: dict) -> int:
    x, y = _int(a.get('day')), _int(b.get('day'))
    return abs(x - y) if x >= 0 and y >= 0 else 0


def _closest(rows: list[dict], row_id: str, entry: dict, vector):
    np = getattr(embed.current(), 'np', None)
    if np is None:
        try:
            import numpy as np
        except ImportError:
            return None
    best = None
    for row in rows:
        if row['id'] == row_id or row.get('hidden') or row.get('type') == 'diary':
            continue
        other = _vector(row, np)
        if other is None:
            continue
        sim = float(np.dot(other, vector))
        if best is None or sim > best[0]:
            best = (sim, row)
    return best


def _refresh_auto(archive, arc: dict) -> None:
    members = [r for r in archive.rows(hidden=None) if r.get('arc') == arc['id']]
    arc['summary'] = auto_summary(members)
    archive.save_arc(arc)


def lines_for(archive, rows: list[dict], usable) -> dict:
    """{arc id: "(An ongoing story ...)" or ''} for the arcs these rows belong to. An arc whose members include a hidden
    memory, or one not of the loaded save's timeline (usable(row) False), gives '': its summary could tell what the NPC
    must not know."""
    wanted = {r.get('arc') for r in rows if r.get('arc')}
    if not wanted:
        return {}
    arcs = {a['id']: a for a in archive.arcs() if a['id'] in wanted}
    blocked = set()
    for row in archive.rows(hidden=None):
        if row.get('arc') in wanted and (row.get('hidden') or not usable(row)):
            blocked.add(row['arc'])
    out = {}
    for arc_id in wanted:
        arc = arcs.get(arc_id)
        if arc is None or arc_id in blocked or not (arc['summary'] or arc['label']):
            out[arc_id] = ''
            continue
        out[arc_id] = (f"(Part of an ongoing story, {arc['label']}: {arc['summary']})" if arc['summary'] and arc['label']
                       else f"(Part of an ongoing story: {arc['summary'] or arc['label']})")
    return out


def prompt_list(store, names_refs: list, limit: int = 6) -> list[str]:
    """The newest arcs of these NPCs as "label: summary", for the end-of-talk summary prompt (so it can say which
    story a talk belongs to). Arcs with hidden members, or members not of the loaded save's timeline, are left out, as
    in lines_for."""
    from . import timeline
    out = []
    branch = timeline.current(store)
    for name, ref_id in names_refs:
        try:
            archive = store.archive_for(name, ref_id)
            if not archive.exists():
                continue
            blocked = {r.get('arc') for r in archive.rows(hidden=None)
                       if r.get('arc') and (r.get('hidden') or not timeline.usable(branch, r))}
            for arc in sorted(archive.arcs(), key=lambda a: -a.get('day', -1))[:limit]:
                if arc['id'] in blocked or not arc['label']:
                    continue
                text = f"{arc['label']}: {arc['summary']}" if arc['summary'] else arc['label']
                if text not in out:
                    out.append(text)
        except (sqlite3.Error, OSError) as e:
            logger.warning(f"Living World: could not read {name}'s story arcs ({e})")
    return out[:limit]


# For the Hub's pages. Each takes the NPC's memory store, name and ref id, holds their lock and never raises.

def list_arcs(store, name: str, ref_id: str) -> list[dict]:
    """[{id, label, summary, day, by_hand, memories: [{id, day, hour, text, hidden}]}], newest first."""
    try:
        archive = store.archive_for(name, ref_id)
        if not archive.exists():
            return []
        rows = archive.rows(hidden=None)
        out = []
        for arc in archive.arcs():
            members = [{'id': r['id'], 'day': r.get('day', -1), 'hour': r.get('hour', -1), 'text': r.get('text', ''),
                        'hidden': bool(r.get('hidden'))} for r in rows if r.get('arc') == arc['id']]
            out.append({'id': arc['id'], 'label': arc['label'], 'summary': arc['summary'], 'day': arc['day'],
                        'by_hand': arc['by_hand'], 'memories': members})
        return sorted(out, key=lambda a: -a['day'])
    except (sqlite3.Error, OSError) as e:
        logger.warning(f"Living World: could not list {name}'s story arcs ({e})")
        return []


def _edit(store, name: str, ref_id: str, change) -> bool:
    with store.lock(name, ref_id):
        try:
            archive = store.archive_for(name, ref_id)
            if not archive.exists():
                return False
            return bool(change(archive))
        except (sqlite3.Error, OSError) as e:
            logger.warning(f"Living World: could not change {name}'s story arcs ({e})")
            return False


def rename_arc(store, name: str, ref_id: str, arc_id: str, label: str | None = None, summary: str | None = None) -> bool:
    """A new label and/or summary, kept from then on (by_hand)."""
    def change(archive):
        arc = next((a for a in archive.arcs() if a['id'] == arc_id), None)
        if arc is None:
            return False
        if label is not None and clean_label(label):
            arc['label'] = clean_label(label)
        if summary is not None:
            arc['summary'] = clean_summary(summary)
        arc['by_hand'] = True
        archive.save_arc(arc)
        return True
    return _edit(store, name, ref_id, change)


def merge_arcs(store, name: str, ref_id: str, into_id: str, other_ids: list[str]) -> bool:
    """Every memory of other_ids joins into_id; the other arcs are removed."""
    def change(archive):
        known = {a['id'] for a in archive.arcs()}
        if into_id not in known:
            return False
        moved = False
        for other in other_ids or []:
            if other == into_id or other not in known:
                continue
            ids = [r['id'] for r in archive.rows(hidden=None) if r.get('arc') == other]
            archive.set_arc(ids, into_id)
            archive.delete_arc(other)
            moved = True
        return moved
    return _edit(store, name, ref_id, change)


def remove_from_arc(store, name: str, ref_id: str, memory_id: str) -> bool:
    return _edit(store, name, ref_id, lambda archive: archive.set_arc([memory_id], None) > 0)


def add_to_arc(store, name: str, ref_id: str, memory_id: str, arc_id: str) -> bool:
    def change(archive):
        if arc_id not in {a['id'] for a in archive.arcs()}:
            return False
        return archive.set_arc([memory_id], arc_id) > 0
    return _edit(store, name, ref_id, change)


def new_arc(store, name: str, ref_id: str, label: str, summary: str = '', memory_ids=()) -> str:
    """A new arc made by hand, with these memories in it. Returns its id ('' when nothing was made)."""
    label = clean_label(label)
    if not label:
        return ''
    made = {'id': new_id(label), 'label': label, 'summary': clean_summary(summary), 'day': -1, 'made': time.time(), 'by_hand': True}

    def change(archive):
        archive.save_arc(made)
        archive.set_arc(list(memory_ids or ()), made['id'])
        return True
    return made['id'] if _edit(store, name, ref_id, change) else ''


def delete_arc(store, name: str, ref_id: str, arc_id: str) -> bool:
    """The arc goes; its memories stay, in no arc."""
    return _edit(store, name, ref_id, lambda archive: archive.delete_arc(arc_id) > 0)
