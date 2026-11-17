"""Save-and-reload safety for memories: what an NPC remembers follows the save the player has loaded.

The game side (MLW_Timeline.psc) keeps a talk counter in the save itself (StorageUtil, in the SKSE co-save), so it rolls
back when an older save is loaded, and writes it into conversation.json with each talk:

    talk_seq     this talk's number in this save's line (while a talk runs), else the next talk's number
    talk_id      a random id of the running talk ('' between talks)
    talk_parent  the id of the last talk that ended in this save's line ('' before the first)
    talk_open    1 while the talk runs, 0 after it ended
    talk_time    the game time the talk started (game days, as GetCurrentGameTime)

Every memory made during a talk is stamped with that talk's id and seq. This side keeps, per save folder
(<conversations>/<world>/living_world/timeline.json), which talk followed which ({id: [parent, seq]}), so the talks
leading up to the loaded save are known. A memory from any other talk (made after the loaded save, on a line the
player went back from) is set aside: not sent, not recalled, not folded, never deleted. Loading the newer save again
brings it back. Once a memory is written on the new line, the set-aside talks are marked as another timeline ('gone',
and 'other' on their memories; still listable). That mark only says how they stand from the line in use: the loaded
save's own line always decides first, so a save whose line holds those talks (the newer save loaded again, even after
a talk on the older one) has them back. The mark is worked out again at each talk start.

Without the counter (an older game side) nothing is stamped or set aside: everything works as before.

The first request of a talk goes out before the game writes that talk's counter, so right after an older save was loaded
conversation.json still holds the counter of the save the player went back from. When Mantella's time of the request
is known (the server gives it with the talk's memory text, note_time) and that counter's talk started later than it,
the loaded save is judged by game time instead (Cut): every talk that started after now, and every memory dated after
now, is set aside until the game writes the new talk's counter. The start time of each talk is kept for that ('times'
in timeline.json)."""
import json
import logging
import os
import threading
import time

from . import lw_state

logger = logging.getLogger('Mantella')

FILE = 'timeline.json'
MANTELLA_DAY = 1  # Mantella's game time is GetCurrentGameTime + 1 (see memory.MANTELLA_DAY)
STALE_SLACK = 0.02  # game days: a talk_time later than the request's own time by more than this is from another save
MAX_LINKS = 20000  # talks kept in timeline.json; the oldest go first (their memories then count by seq alone)
MAX_WALK = 20000

OK, ASIDE, OTHER = 'ok', 'aside', 'other'

_locks: dict = {}
_locks_guard = threading.Lock()
_cache: dict = {}  # path -> (stamp, data)
_clock = {'days': None}  # Mantella's time of the talk going on (note_time), None between talks


def note_time(game_days) -> None:
    """Mantella's time of this talk's newest request (GameDaysPassed + 1), or None when the talk is over: used by current()
    when its caller gives no time."""
    days = _number(game_days)
    _clock['days'] = days if days is not None and days > 0 else None


def _lock(path: str) -> threading.Lock:
    key = os.path.normcase(os.path.abspath(path))
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and value == value else None


def read_game(game_days: float | None = None) -> dict | None:
    """The talk counter the game side wrote, or None: no counter (older game side), or one that cannot be from the
    save now loaded (its talk started later than game_days, Mantella's own time of this request: the file still holds
    the save the player went back from)."""
    from . import contracts
    data = contracts.game_flat(lw_state._read('conversation.json'))  # keys without case (Papyrus strings)
    seq = data.get('talk_seq')
    if not isinstance(seq, int) or isinstance(seq, bool) or seq < 0:
        return None
    talk_id = data.get('talk_id') if isinstance(data.get('talk_id'), str) else ''
    parent = data.get('talk_parent') if isinstance(data.get('talk_parent'), str) else ''
    is_open = data.get('talk_open') == 1 and bool(talk_id.strip())
    started = _number(data.get('talk_time'))
    days = _number(game_days)
    if days is not None and started is not None and started + MANTELLA_DAY > days + STALE_SLACK:
        return None
    return {'seq': seq, 'id': talk_id.strip() if is_open else '', 'parent': parent.strip(), 'open': is_open,
            'time': started}


def _path(store) -> str:
    return os.path.join(store.root, FILE)


def _stamp(path: str):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


def load(store) -> dict:
    """{links: {id: [parent, seq]}, gone: {id: seq}} for this save folder; empty on any problem."""
    path = _path(store)
    stamp = _stamp(path)
    cached = _cache.get(path)
    if cached is not None and stamp is not None and cached[0] == stamp:
        return cached[1]
    data = {'links': {}, 'gone': {}, 'times': {}}
    try:
        with open(path, encoding='utf-8') as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            for key in ('links', 'gone', 'times'):
                if isinstance(raw.get(key), dict):
                    data[key] = raw[key]
    except (OSError, ValueError, RecursionError):
        pass
    data['links'] = {str(k): v for k, v in data['links'].items()
                     if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and isinstance(v[1], int)}
    data['gone'] = {str(k): v for k, v in data['gone'].items() if isinstance(v, int) or v is None}
    data['times'] = {str(k): v for k, v in data['times'].items() if _number(v) is not None}
    if stamp is not None:
        _cache[path] = (stamp, data)
    return data


def _save(store, data: dict) -> None:
    if len(data['links']) > MAX_LINKS:
        data['links'] = dict(sorted(data['links'].items(), key=lambda kv: kv[1][1])[-MAX_LINKS:])
    if 'times' in data:
        data['times'] = {k: v for k, v in data['times'].items() if k in data['links']}
    os.makedirs(store.root, exist_ok=True)
    path = _path(store)
    tmp = lw_state.temp_path(path)
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    lw_state.replace_file(tmp, path)
    _cache.pop(path, None)


class Branch:
    """The line of talks that leads to the save now loaded. state(item) says whether a memory belongs to it."""

    def __init__(self, talk: dict, data: dict):
        self.seq, self.id, self.parent, self.open = talk['seq'], talk['id'], talk['parent'], talk['open']
        self.time = talk.get('time')  # game time the running talk started (game days), or None
        self.links = data['links']
        self.gone = set(data['gone'])
        self.ancestors, self.broken = set(), False
        at, steps = self.parent, 0
        while at and steps < MAX_WALK:
            self.ancestors.add(at)
            link = self.links.get(at)
            if link is None:
                self.broken = True  # a talk this side never saw: older talks are judged by seq alone
                break
            at, steps = link[0], steps + 1

    def stamp(self) -> dict:
        """What a memory made now carries: the running talk, or nothing between talks."""
        return {'talk': self.id, 'seq': self.seq} if self.open else {}

    def mine(self, talk_id) -> bool:
        """A talk on the line of the save now loaded (the running talk or one that led to it)."""
        return isinstance(talk_id, str) and bool(talk_id) and (talk_id == self.id or talk_id in self.ancestors)

    def state_of(self, talk_id, seq) -> str:
        if not isinstance(talk_id, str) or not talk_id:
            return OK  # made before the counter existed, or between talks
        if self.mine(talk_id):
            return OK  # the loaded save's own line wins over any 'other timeline' mark
        if talk_id in self.gone:
            return OTHER
        if isinstance(seq, int) and not isinstance(seq, bool) and seq >= self.seq:
            return ASIDE  # numbered at or after the talk now: never one that led here
        if talk_id in self.links and not self.broken:
            return ASIDE  # a talk this side saw, and not on the way to this save
        return OK  # older than this side knows of: by its number it came before

    def state(self, item: dict) -> str:
        if not isinstance(item, dict):
            return OK
        if self.mine(item.get('talk')):
            return OK
        if item.get('timeline') == OTHER or item.get('branch') == OTHER:
            return OTHER
        return self.state_of(item.get('talk'), item.get('seq'))


def state(branch: Branch | None, item: dict) -> str:
    """OK, ASIDE or OTHER for a memory entry or archive row; without a counter only memories already marked as another
    timeline are left out (there are none unless a counter was there before)."""
    if branch is not None:
        return branch.state(item)
    if isinstance(item, dict) and (item.get('timeline') == OTHER or item.get('branch') == OTHER):
        return OTHER
    return OK


class Cut(Branch):
    """The loaded save, judged by game time (see the module note): a talk that started after game_days, or a memory
    dated after it, is set aside; an item marked as another timeline stays out. Nothing is stamped with it."""

    def __init__(self, game_days: float, data: dict):
        super().__init__({'seq': 0, 'id': '', 'parent': '', 'open': False, 'time': None}, data)
        self.days = float(game_days)
        whole = int(self.days)
        self.cut = (whole, int((self.days - whole) * 24))  # Mantella's (day, hour), as memories are dated
        self.late = {i for i, t in (data.get('times') or {}).items() if t + MANTELLA_DAY > self.days + STALE_SLACK}

    def stamp(self) -> dict:
        return {}

    def state_of(self, talk_id, seq) -> str:
        return ASIDE if isinstance(talk_id, str) and talk_id in self.late else OK

    def state(self, item: dict) -> str:
        if not isinstance(item, dict):
            return OK
        if item.get('timeline') == OTHER or item.get('branch') == OTHER:
            return OTHER
        when = item.get('after') if isinstance(item.get('after'), list) and len(item['after']) == 2 else [item.get('day'), item.get('hour')]
        day, hour = when
        if isinstance(day, int) and isinstance(hour, int) and not isinstance(day, bool) and day >= 0 and (day, max(hour, 0)) > self.cut:
            return ASIDE
        return self.state_of(item.get('talk'), item.get('seq'))


def usable(branch: Branch | None, item: dict) -> bool:
    return state(branch, item) == OK


def current(store, game_days: float | None = None) -> Branch | None:
    """The branch for this save folder, or None without a counter. A running talk is noted in timeline.json (which talk
    it follows), once. Never raises."""
    if store is None:
        return None
    try:
        days = _number(game_days) if game_days is not None else _clock['days']
        talk = read_game(days)
        if talk is None:
            if days is not None and read_game() is not None:  # a newer save's counter: judge by game time
                return Cut(days, load(store))
            return None
        data = load(store)
        noted = data['links'].get(talk['id']) == [talk['parent'], talk['seq']] and \
            (talk['time'] is None or data['times'].get(talk['id']) == talk['time'])
        if talk['open'] and not noted:
            with _lock(_path(store)):
                old = load(store)
                data = {'links': dict(old['links']), 'gone': dict(old['gone']), 'times': dict(old['times'])}
                data['links'][talk['id']] = [talk['parent'], talk['seq']]
                if talk['time'] is not None:
                    data['times'][talk['id']] = talk['time']
                _save(store, data)
        return Branch(talk, data)
    except Exception as e:
        logger.warning(f"Living World: the save's talk counter could not be read ({e}); memories are not checked against it")
        return None


def stamp_now(store) -> dict:
    """What something made now outside a memory carries (a Now paragraph, a world log event): the running talk, else the
    last talk that ended in the loaded save's line, so loading a save from before it sets it aside; {} without the game's
    talk counter. Never raises."""
    branch = current(store)
    if branch is None:
        return {}
    if branch.open:
        return branch.stamp()
    return {'talk': branch.parent, 'seq': branch.seq - 1} if branch.parent and branch.seq > 0 else {}


def abandon(store, branch: Branch | None) -> list[str]:
    """A memory was just written on this branch: every talk that is set aside now is marked as another timeline (a save
    whose own line holds it still has it back: Branch.state checks the line first). Returns the talk ids newly marked.
    Never raises."""
    if branch is None or not branch.open:
        return []
    try:
        with _lock(_path(store)):
            data = load(store)
            fresh = Branch({'seq': branch.seq, 'id': branch.id, 'parent': branch.parent, 'open': True}, data)
            new = [i for i, (_, seq) in data['links'].items() if i not in fresh.gone and fresh.state_of(i, seq) == ASIDE]
            if not new:
                return []
            data = {'links': dict(data['links']), 'gone': dict(data['gone']), 'times': dict(data.get('times') or {})}
            for i in new:
                data['gone'][i] = data['links'][i][1]
            _save(store, data)
            branch.gone.update(new)
            logger.info(f"Living World: {len(new)} talk(s) from a save the player went back from are now another timeline")
            return new
    except Exception as e:
        logger.warning(f"Living World: could not note the abandoned timeline ({e})")
        return []
