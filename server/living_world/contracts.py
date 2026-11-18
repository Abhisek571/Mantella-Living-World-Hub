"""Files shared with the Relationships module, in the game channel folder (SKSE/Plugins/StorageUtilData/
MantellaLivingWorld/). Both sides tolerate a missing file and unknown keys; nothing here fails when Relationships is
not installed: the readers return nothing and no request is written.

    ties.json            Relationships writes it: per NPC base id (6 hex digits) a name, a home and their ties
                         {kind, base, name}, kind one of TIE_KINDS. Base-game data, shared by every save.
    marriages.json       Relationships appends one row per M.A.R.A.S status change it sees:
                         {base, name, status, day (game day), commanded (1 when an absolute command was in force)}.
    requests.json        the Hub writes it: [{id, kind: "end_marriage", base, name, why, player}]. player: the player
                         character it was asked for (the game skips another character's rows). Relationships handles
                         each id once (one box for the player) and writes request_results.json: {id, result}.

The game side writes JsonUtil files, so every reader also accepts JsonUtil's typed shape (parallel string lists, or
"kind|base|name" strings) besides plain JSON lists and objects."""
import json
import logging
import os
import threading
import time
import uuid

from . import lw_state

TIES = 'ties.json'
MARRIAGES = 'marriages.json'
REQUESTS = 'requests.json'
RESULTS = 'request_results.json'
TIE_KINDS = ('spouse', 'courting', 'parent', 'child', 'sibling', 'cousin', 'works_for', 'employs', 'household', 'enemy')
FAMILY = ('parent', 'child', 'sibling', 'cousin')
MARRIED = ('married', 'engaged')
MAX_REQUESTS = 50

_lock = threading.Lock()
logger = logging.getLogger('Mantella')
_told: set = set()  # rejection notes already logged this session (one line each, not one per read)


def _rejected(text: str, key=None) -> None:
    key = text if key is None else key
    if key in _told:
        return
    _told.add(key)
    if len(_told) > 500:
        _told.clear()
    logger.warning(f"Living World: {text}")


def base_key(value) -> str:
    """A base id the way the Hub's npc files are named: hex, upper case, at least 6 digits ("A2C94" -> "0A2C94"); ''
    when it is not one."""
    text = str(value or '').strip()
    if text.lower().startswith('0x'):
        text = text[2:]
    if not text or not lw_state.BASE_ID.match(text):
        return ''
    return text.upper().rjust(6, '0')[-8:]


def _text(value, limit=120) -> str:
    return ' '.join(str(value).split())[:limit] if isinstance(value, (str, int, float)) and not isinstance(value, bool) else ''


def _float(value, default=-1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number == number and abs(number) < 1e9 else default


# --- reading what the game side wrote ----------------------------------------------------------------------------------
# Papyrus strings are case-insensitive and the game reuses a spelling it already holds: a script that writes "spell"
# can store "SPELL", a key "key" can come out as "Key". Every key and every word value read from a game-side file is
# compared without case.

def low(value) -> str:
    """A word written by the game, for comparing: stripped, lower case; '' for anything that is not text or a number."""
    return str(value).strip().lower() if isinstance(value, (str, int, float)) and not isinstance(value, bool) else ''


def same_name(a, b) -> bool:
    """Two names written by the game (a player character's name) are the same, whatever their case."""
    return ' '.join(str(a or '').split()).lower() == ' '.join(str(b or '').split()).lower()


def _section(data, kind: str):
    found = next((v for k, v in data.items() if str(k).lower() == kind.lower()), None) if isinstance(data, dict) else None
    return found if isinstance(found, dict) else {}


def game_lists(data, kinds=('stringList',)) -> dict:
    """JsonUtil's parallel lists ({"stringList": {"key": [...], ...}}) as one dict with lower-case keys; {} when there
    are none."""
    out = {}
    for kind in kinds:
        for k, v in _section(data, kind).items():
            if isinstance(v, list):
                out.setdefault(str(k).strip().lower(), v)
    return out


def game_flat(data) -> dict:
    """JsonUtil's typed values ({"int": {...}, "string": {...}, ...}) as one dict with lower-case keys."""
    out = {}
    for kind in ('int', 'float', 'string', 'form', 'stringList'):
        for k, v in _section(data, kind).items():
            out[str(k).strip().lower()] = v
    return out


# --- ties.json ---------------------------------------------------------------------------------------------------------

def _tie(raw) -> dict | None:
    if isinstance(raw, str):  # "kind|base|name"
        parts = [p.strip() for p in raw.split('|')]
        raw = {'kind': parts[0] if parts else '', 'base': parts[1] if len(parts) > 1 else '',
               'name': parts[2] if len(parts) > 2 else ''}
    if not isinstance(raw, dict):
        return None
    raw = {str(k).strip().lower(): v for k, v in raw.items()}
    kind = low(raw.get('kind'))
    if kind not in TIE_KINDS:
        _rejected(f"a tie of unknown kind '{kind}' in {TIES} is left out", kind)
        return None
    base, name = base_key(raw.get('base')), _text(raw.get('name'))
    if not base and not name:
        return None
    return {'kind': kind, 'base': base, 'name': name}


def _npc_ties(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    raw = {str(k).strip().lower(): v for k, v in raw.items()}
    ties = [t for t in (_tie(t) for t in raw['ties']) if t] if isinstance(raw.get('ties'), list) else []
    return {'name': _text(raw.get('name')), 'home': _text(raw.get('home'), 160), 'ties': ties}


def load_ties(data: dict | None = None) -> dict:
    """{base id: {name, home, ties: [{kind, base, name}]}}; {} when the file is missing or unreadable."""
    data = lw_state._read(TIES) if data is None else data
    if not isinstance(data, dict):
        return {}
    out: dict = {}
    plain = data.get('npcs') if isinstance(data.get('npcs'), dict) else data
    for key, raw in plain.items():
        if str(key).lower() in ('stringlist', 'string', 'int', 'float', 'form', 'intlist', 'floatlist', 'formlist'):
            continue
        base = base_key(key)
        found = _npc_ties(raw) if base else None
        if found is not None:
            out[base] = found
    # JsonUtil's typed shape: stringList "<base>_ties" = ["kind|base|name", ...], string "<base>_name"/"<base>_home"
    lists = _section(data, 'stringList')
    strings = _section(data, 'string')
    for key, values in lists.items():
        if not str(key).lower().endswith('_ties') or not isinstance(values, list):
            continue
        base = base_key(str(key)[:-5])
        if not base:
            continue
        entry = out.setdefault(base, {'name': '', 'home': '', 'ties': []})
        entry['ties'] += [t for t in (_tie(v) for v in values) if t and t not in entry['ties']]
    for key, value in strings.items():
        low = str(key).lower()
        for suffix, field in (('_name', 'name'), ('_home', 'home')):
            if low.endswith(suffix) and base_key(str(key)[:-len(suffix)]):
                entry = out.setdefault(base_key(str(key)[:-len(suffix)]), {'name': '', 'home': '', 'ties': []})
                entry[field] = entry[field] or _text(value, 160)
    return out


def ties_of(base: str, ties: dict | None = None) -> list[dict]:
    """This NPC's ties: their own list, plus the other side of every tie someone else listed with them (a spouse is
    named on both sheets even when only one was seen)."""
    base = base_key(base)
    if not base:
        return []
    ties = load_ties() if ties is None else ties
    out = list((ties.get(base) or {}).get('ties') or [])
    mirror = {'spouse': 'spouse', 'courting': 'courting', 'parent': 'child', 'child': 'parent', 'sibling': 'sibling',
              'cousin': 'cousin', 'works_for': 'employs', 'employs': 'works_for', 'household': 'household', 'enemy': 'enemy'}
    for other, entry in ties.items():
        if other == base:
            continue
        for tie in entry.get('ties') or []:
            if tie.get('base') == base:
                back = {'kind': mirror[tie['kind']], 'base': other, 'name': entry.get('name') or ''}
                if not any(t['kind'] == back['kind'] and (t['base'] == other or (not t['base'] and t['name'] == back['name']))
                           for t in out):
                    out.append(back)
    return out


# --- marriages.json ----------------------------------------------------------------------------------------------------

def _marriage(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    raw = {str(k).strip().lower(): v for k, v in raw.items()}
    base = base_key(raw.get('base'))
    status = low(raw.get('status'))
    if not base or not status:
        _rejected(f"a row of {MARRIAGES} without a base id or status is left out: {json.dumps(raw)[:160]}")
        return None
    commanded = raw.get('commanded')
    return {'base': base, 'name': _text(raw.get('name')), 'status': status, 'day': _float(raw.get('day')),
            'commanded': 1 if commanded in (1, '1', True, 'true') or _float(commanded, 0) >= 1 else 0,
            'player': _text(raw.get('player'))}


def load_marriages(data=None, player: str | None = None) -> list[dict]:
    """Every M.A.R.A.S status change Relationships saw, oldest first: [{base, name, status, day, commanded, player}].
    The file is shared by every save, so only this character's rows are kept (player: the character's name; None
    reads it from the conversation file; a row without a name is kept)."""
    if player is None:
        player = lw_state.load_player_name()
    data = lw_state._read(MARRIAGES) if data is None else data
    rows = []
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        lowered = {str(k).lower(): v for k, v in data.items()}
        for key in ('marriages', 'rows', 'list', 'entries'):
            if isinstance(lowered.get(key), list):
                rows = lowered[key]
                break
        else:  # JsonUtil: parallel lists in stringList (and maybe floatList / intList)
            lists = game_lists(data, ('stringList', 'floatList', 'intList'))
            count = len(lists.get('base') or [])
            rows = [{k: (v[i] if i < len(v) else None) for k, v in lists.items()} for i in range(count)]
    out = [m for m in (_marriage(r) for r in rows) if m]
    if player:
        out = [m for m in out if not m['player'] or same_name(m['player'], player)]
    return out


def latest_marriage(base: str, rows: list[dict] | None = None) -> dict | None:
    """The newest status change for this NPC, or None."""
    base = base_key(base)
    rows = load_marriages() if rows is None else rows
    mine = [r for r in rows if r['base'] == base]
    return mine[-1] if mine else None


def made_under_command(base: str, since: float = -1.0, until: float | None = None, rows: list[dict] | None = None) -> dict | None:
    """The newest marriage or engagement of this NPC made while an absolute command was in force (commanded 1), at or
    after since and not after until (game days), when it is still their latest status; else None."""
    base = base_key(base)
    rows = load_marriages() if rows is None else rows
    mine = [r for r in rows if r['base'] == base]
    if not mine or mine[-1]['status'] not in MARRIED:
        return None
    for row in reversed(mine):
        if row['status'] not in MARRIED:
            return None
        if row['commanded'] and (row['day'] < 0 or since < 0 or row['day'] >= since - 0.01) \
                and (until is None or until < 0 or row['day'] < 0 or row['day'] <= until + 0.01):
            return row
    return None


# --- requests.json -----------------------------------------------------------------------------------------------------

def load_requests() -> list[dict]:
    data = lw_state._read(REQUESTS)
    rows = data.get('requests') if isinstance(data, dict) else None
    return [r for r in rows if isinstance(r, dict) and r.get('id')] if isinstance(rows, list) else []


def write_request(kind: str, base: str, name: str, why: str, player: str = '') -> str:
    """Adds one request for Relationships and returns its id ('' when the base id is unknown or the file could not be
    written). Written as a plain list and as JsonUtil string lists (id, kind, base, name, why, player), so either reader
    finds it. player: the character it is for ('' = the current one, lw_state.load_player_name). A request already
    waiting for the same NPC, kind and character is not added twice."""
    base = base_key(base)
    if not base or kind != 'end_marriage':
        return ''
    player = _text(player or lw_state.load_player_name())
    with _lock:
        rows = load_requests()
        done = load_results()
        for row in rows:
            if (row.get('kind') == kind and row.get('base') == base and row['id'] not in done
                    and lw_state._same_name(row.get('player') or '', player)):
                return row['id']
        row = {'id': uuid.uuid4().hex[:12], 'kind': kind, 'base': base, 'name': _text(name), 'why': _text(why, 300),
               'player': player, 'at': time.time()}
        rows = (rows + [row])[-MAX_REQUESTS:]
        lists = {k: [str(r.get(k) or '') for r in rows] for k in ('id', 'kind', 'base', 'name', 'why', 'player')}
        try:
            lw_state.write_json(REQUESTS, {'requests': rows, 'stringList': lists})
        except OSError:
            return ''
        return row['id']


def load_results() -> dict:
    """{request id: result} from request_results.json (done / refused / not_possible)."""
    data = lw_state._read(RESULTS)
    out = {}
    rows = data if isinstance(data, list) else (data.get('results') if isinstance(data, dict) else None)
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and row.get('id'):
                out[str(row['id'])] = low(row.get('result'))
    elif isinstance(data, dict):
        lists = game_lists(data)
        ids, results = lists.get('id') or [], lists.get('result') or []
        for i, rid in enumerate(ids if isinstance(ids, list) else []):
            if rid:
                out[str(rid)] = low(results[i]) if isinstance(results, list) and i < len(results) else ''
        strings = next((v for k, v in data.items() if str(k).lower() == 'string'), None)
        strings = strings if isinstance(strings, dict) else {}
        out.update({str(k): low(v) for k, v in strings.items() if isinstance(v, str)})
    return out


def present() -> bool:
    """Relationships has written one of its files (so it is installed in some form)."""
    return any(os.path.isfile(os.path.join(lw_state.DATA_DIR, f)) for f in (TIES, MARRIAGES, RESULTS))
