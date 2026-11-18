"""Reads what the game side writes for Mantella: PapyrusUtil JSON under SKSE/Plugins/StorageUtilData/MantellaLivingWorld/.
Every reader returns an empty value on any problem (missing, half-written, not JSON), never an error."""
import copy
import json
import os
import re
import sys
import threading
import time

BASE_ID = re.compile(r'^[0-9A-Fa-f]{1,8}\Z')


def default_data_dir() -> str:
    # Mantella runs with SKSE/Plugins/MantellaSoftware as its working folder
    return os.path.normpath(os.path.join(os.getcwd(), '..', 'StorageUtilData', 'MantellaLivingWorld'))


DATA_DIR = default_data_dir()


def decode(raw: bytes) -> str:
    """PapyrusUtil may write names in the game's codepage rather than UTF-8; either way the file stays readable."""
    try:
        return raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        return raw.decode('cp1252', errors='replace')


READ_MEMO_SECONDS = 1.0  # one reply reads the same channel files many times: kept this long while unchanged on disk
_memo: dict = {}  # full path -> (monotonic time read, (mtime_ns, size), parsed data)
_memo_lock = threading.Lock()


def _read(name: str, retry: bool = True) -> dict:
    """A channel file, parsed ({} on any problem). A file read less than READ_MEMO_SECONDS ago whose time and size on
    disk are unchanged is not read again (a copy is returned, so callers may change it)."""
    path = os.path.join(DATA_DIR, name)
    try:
        st = os.stat(path)
        stamp = (st.st_mtime_ns, st.st_size)
    except OSError:
        stamp = None
    now = time.monotonic()
    if stamp is not None:
        with _memo_lock:
            hit = _memo.get(path)
        if hit and hit[1] == stamp and now - hit[0] < READ_MEMO_SECONDS:
            return copy.deepcopy(hit[2])
    data = _read_file(path, retry)
    if data and stamp is not None:
        with _memo_lock:
            _memo[path] = (now, stamp, copy.deepcopy(data))
    return data


def _read_file(path: str, retry: bool = True) -> dict:
    for _ in range(REPLACE_TRIES if retry else 1):
        try:
            with open(path, 'rb') as f:
                data = json.loads(decode(f.read()))
            return data if isinstance(data, dict) else {}
        except PermissionError:  # on Windows a file being replaced cannot be opened for a moment
            time.sleep(0.02)
        except ValueError:
            if retry:  # the game may be halfway through saving it
                time.sleep(0.05)
                return _read_file(path, False)
            return {}
        except (OSError, RecursionError):
            return {}
    return {}


REPLACE_TRIES = 50


def temp_path(path) -> str:
    """A temp file of this thread's own next to path, so two writers never share one."""
    return f"{path}.{os.getpid()}-{threading.get_ident()}.tmp"


def replace_file(temp, path) -> None:
    """os.replace that waits out a reader: on Windows a file someone has open cannot be replaced for that moment.
    The temp file is removed if it still fails."""
    for attempt in range(REPLACE_TRIES):
        try:
            os.replace(temp, path)
            return
        except PermissionError:
            if attempt == REPLACE_TRIES - 1:
                try:
                    os.remove(temp)
                except OSError:
                    pass
                raise
            time.sleep(0.02)


_unread = threading.local()  # this thread's store files that exist but could not be read: never saved over until read


def _unread_marks() -> set:
    if not hasattr(_unread, 'paths'):
        _unread.paths = set()
    return _unread.paths


def _key(path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def read_store_json(path, encoding: str = 'utf-8-sig'):
    """A save's own JSON store file (custom events, commands, world log, ...), parsed; None when it does not exist or
    cannot be used. A file that exists but cannot be opened (locked by a sync tool, an antivirus or a backup) also reads
    as None for readers that only show it, but this thread may not save over it until a later read works (guard_save
    raises): one bad read used to replace the whole store with the little this request added. A file that is not JSON
    is copied aside first (like a memory file), so saving over it loses nothing."""
    key = _key(path)
    marks = _unread_marks()
    try:
        with open(path, encoding=encoding) as f:
            data = json.load(f)
        marks.discard(key)
        return data
    except FileNotFoundError:
        marks.discard(key)
        return None
    except OSError as e:
        marks.add(key)
        _log_warning(f"Living World: {os.path.basename(str(path))} could not be read ({e}); it is not saved over until it can be")
        return None
    except (ValueError, RecursionError, UnicodeDecodeError):
        aside = f"{path}.unreadable-{time.strftime('%Y%m%d-%H%M%S')}"
        try:
            import shutil
            shutil.copy2(path, aside)
            marks.discard(key)
            _log_warning(f"Living World: {os.path.basename(str(path))} could not be read; copied to {os.path.basename(aside)}, starting empty")
        except OSError:
            marks.add(key)  # no copy made: the broken file is the only one, never replaced
        return None


def read_failed(path) -> bool:
    """True while this thread's last read_store_json of path failed: the file exists but could not be opened."""
    return _key(path) in _unread_marks()


def guard_save(path) -> None:
    """Raises OSError when this thread's last read of path failed (read_store_json): the caller's data is not the file's."""
    if read_failed(path):
        raise OSError(f"{os.path.basename(str(path))} was not read, so it is not saved over")


def _log_warning(text: str) -> None:
    import logging
    logging.getLogger('Mantella').warning(text)


def _flatten(data: dict) -> dict:
    """JsonUtil keeps values by type ({"int": {...}, "string": {...}, ...}); one dict is easier to use. Papyrus strings
    are case-insensitive (a key can arrive as "Player" or "DAY"), so the sections and keys are read without case and
    the keys come back in lower case (contracts.game_flat)."""
    from . import contracts
    return contracts.game_flat(data)


def _same_name(a, b) -> bool:
    from . import contracts
    return contracts.same_name(a, b)


def _rejected_once(text: str) -> None:
    """One log line per kind of game row that is left out (never dropped silently)."""
    from . import contracts
    contracts._rejected(text)


# npc file values about the NPC's standing with the player. The file is shared by every save and character: until the
# game rewrites it at this talk's join (9 to 11 s after the greeting), values another character's save wrote are left
# out, so every gate reading them stays shut (the file names that character in 'player').
STANDING = ('close', 'intimate', 'follower', 'rank', 'spouse', 'housecarl', 'allow_intimacy', 'rated', 'scene', 'affection',
            'trades_free', 'home', 'job')
STANDING_PREFIXES = ('maras', 'nff')
NUMBERED_NAME = re.compile(r'^(.*\S)\s+\d+\Z')  # Mantella numbers two people of one name in a talk: "Guard 2"


def _name_fits(file_name, speaker_name) -> bool:
    if _same_name(file_name, speaker_name):
        return True
    m = NUMBERED_NAME.match(str(speaker_name or '').strip())
    return bool(m) and _same_name(file_name, m.group(1))


def other_npc(data: dict, name=None, full_id=None) -> bool:
    """The npc file holds another NPC than the speaker: npc/<6 hex>.json is shared by NPCs of different plugins whose
    base ids end in the same digits (xx000801 and yy000801, a light plugin's FE id). True when the file's full base id
    (base_full) and the speaker's both are known and differ, or the file's name and the speaker's both are known and
    differ. Anything less certain keeps the file."""
    stored = data.get('base_full')
    if full_id and isinstance(stored, str) and stored.strip():
        a, b = _id_number(stored.strip()), _id_number(str(full_id).strip())
        if a is not None and b is not None and a != b:
            return True
    found = data.get('name')
    return (isinstance(name, str) and bool(name.strip()) and isinstance(found, str) and bool(found.strip())
            and not _name_fits(found, name))


def load_npc(base_id: str, name: str | None = None, full_id: str | None = None) -> dict:
    """An NPC's file by base id (6 hex digits). name / full_id: the speaker's, when known; a file holding another NPC
    (other_npc) is then empty for this request, so a child never reads another plugin's adult (minor unknown)."""
    if not base_id or not BASE_ID.match(base_id):
        return {}
    data = _flatten(_read(os.path.join('npc', base_id.upper() + '.json')))
    if data and other_npc(data, name, full_id):
        _rejected_once(f"npc/{base_id.upper()}.json holds {data.get('name')!r}, not {name or full_id!r} (another plugin's NPC with "
                       f"the same last digits); left out until the game rewrites it")
        return {}
    if data:
        data['base_id'] = base_id.upper()
        owner = data.get('player')
        if isinstance(owner, str) and owner.strip():
            current = load_player_name()
            if current and not _same_name(owner, current):
                data = {k: v for k, v in data.items()
                        if k not in STANDING and not k.startswith(STANDING_PREFIXES)}
    return data


def load_world() -> dict:
    """World writes world.json as plain JSON (fame, bounty, events, ...); older files used JsonUtil's typed shape."""
    data = _read('world.json')
    plain = {k: v for k, v in data.items() if k not in ('int', 'float', 'string', 'form', 'stringList')}
    world = {**_flatten(data), **plain}
    return world if world_current(world, load_player_name(), load_today()) else {}


def world_current(world: dict, player: str, today: int | None) -> bool:
    """False while World is still rewriting world.json after a load (loading 1), or while it holds another character
    (player) or a later day (an earlier save was loaded): its titles and bounties are not this game's."""
    if world.get('loading') == 1:
        return False
    if other_character(world.get('player'), player):
        _rejected_once(f"world.json holds another character ({world['player']}); left out until World rewrites it")
        return False
    day = world.get('day')
    if today is not None and isinstance(day, (int, float)) and not isinstance(day, bool) and int(day) > today:
        return False
    return True


def load_said_nearby() -> list[dict]:
    lines = _read('said_nearby.json').get('lines')
    return [line for line in lines if isinstance(line, dict)] if isinstance(lines, list) else []


def load_battles() -> list[dict]:
    """World's battle accounts (battles.json, written by its SKSE plugin), newest first; none while the file holds
    another character's fights."""
    battles = _read('battles.json')
    fights = battles.get('fights')
    if not isinstance(fights, list):
        return []
    if other_character(battles.get('player'), load_player_name()):
        _rejected_once(f"battles.json holds another character's fights ({battles['player']}); left out")
        return []
    return [f for f in fights if isinstance(f, dict)]


def load_banter() -> dict:
    """Why World's banter or initiative started the current talk: {seed, active}."""
    return _flatten(_read('banter.json'))


def debug_log() -> bool:
    """The MCM's debug log switch (off by default), as the game wrote it into conversation.json at the talk's start."""
    from . import action_filter
    return action_filter._int(_flatten(_read('conversation.json')).get('debug_log'), 0) == 1


def load_children_near() -> list[str]:
    """Children near the player who are not in the talk (children_near.json, written by OStim Expansion while a talk
    with the player runs, emptied when it ends or a save loads): their names."""
    names = _flatten(_read('children_near.json')).get('names')
    return [n.strip() for n in names.split(',') if n.strip()] if isinstance(names, str) else []


PLAYER_FILES = ('world.json', 'battles.json')  # rewritten with the player's name right after every load


def _file_time(name: str) -> float | None:
    try:
        return os.path.getmtime(os.path.join(DATA_DIR, name))
    except OSError:
        return None


_live = {'player': '', 'time': None}  # the player's name as Mantella itself last named it, and when


def note_live_player(name) -> None:
    """Mantella's own name for the player in the talk going on (the game sends it with every talk): the freshest
    statement of who the player is, newer than any channel file written before this moment."""
    if isinstance(name, str) and name.strip():
        _live.update(player=name.strip(), time=time.time())


def load_player_name() -> str:
    """The current character's name: the freshest statement of it. conversation.json was once saved at the start of a
    talk (the talk counter) without its player line, so after loading another character's save its file was the newest
    and still named the previous character (live test 6: "Prisonerdax" from an older session, while world.json and
    battles.json named the current Player). Each source counts with its own time: conversation.json, World's world.json
    and battles.json (rewritten right after every load; one still marked loading 1 is skipped) and Mantella's own name
    for the player in the talk going on (note_live_player). '' when none names anyone."""
    name = _flatten(_read('conversation.json')).get('player')
    name = name if isinstance(name, str) and name.strip() else ''
    newest = _file_time('conversation.json') if name else None
    for other in PLAYER_FILES:
        when = _file_time(other)
        if when is None or (newest is not None and when <= newest):
            continue
        data = _read(other)
        flat = _flatten(data)
        if data.get('loading') == 1 or flat.get('loading') == 1:
            continue
        found = data.get('player') if isinstance(data.get('player'), str) else flat.get('player')
        if isinstance(found, str) and found.strip():
            name, newest = found, when
    if _live['player'] and (newest is None or (_live['time'] or 0) >= newest):
        name = _live['player']
    return name


def other_character(found, expected) -> bool:
    """A file names another character than the player: only when both names are known, not empty, and differ (case and
    surrounding space ignored). Anything less certain keeps the data."""
    return (isinstance(found, str) and isinstance(expected, str) and bool(found.strip()) and bool(expected.strip())
            and not _same_name(found, expected))


def write_json(name: str, data: dict) -> None:
    """Replaces a channel file in one step, so the game never reads half of it."""
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, name)
    temp = temp_path(path)
    with open(temp, 'w', encoding='utf-8', errors='replace') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    replace_file(temp, path)


PROFILES = 'profiles.json'
_profiles_lock = threading.Lock()  # read, add, write back: two at once would drop one NPC's values


def write_profile(base_id: str, weights: dict) -> None:
    """What wins this NPC over, for the game side: "<base id>_<channel>" ints in lowercase, as JsonUtil looks keys up."""
    if not base_id or not BASE_ID.match(base_id):
        return
    with _profiles_lock:
        values = _read(PROFILES).get('int')
        values = dict(values) if isinstance(values, dict) else {}
        new = {f'{base_id.lower()}_{channel}': value for channel, value in weights.items()}
        if any(values.get(key) != value for key, value in new.items()):
            write_json(PROFILES, {'int': {**values, **new}})


SCENE_ACK = 'scene_ack.json'  # "<name>|<scene time>" of kept scenes the Hub has stored (OStim Expansion clears them)
SCENE_ACK_MAX = 200
_ack_lock = threading.Lock()


def ack_scenes(keys) -> bool:
    """Tells OStim Expansion which kept scenes are in a memory now ("<NPC name>|<scene time as tagged>"), so it stops
    sending them (live test 16: a talk that died after one reply took the scenes with it). Never raises."""
    keys = [str(k) for k in keys or [] if k]
    if not keys:
        return False
    try:
        with _ack_lock:
            old = _read(SCENE_ACK).get('stringList')
            stored = list((old or {}).get('stored') or []) if isinstance(old, dict) else []
            new = [k for k in keys if k not in stored]
            if not new:
                return True
            write_json(SCENE_ACK, {'stringList': {'stored': (stored + new)[-SCENE_ACK_MAX:]}})
        return True
    except Exception:
        return False


def load_today() -> int | None:
    """Today's game day, written by the Hub's game side with the conversation; None if it isn't there."""
    day = _flatten(_read('conversation.json')).get('day')
    return day if isinstance(day, int) and not isinstance(day, bool) and day >= 0 else None


# Which module writes a fact key (by prefix). A removed module never clears its facts (they never expire), so with
# installed given, a fact whose module is not installed is left out. New fact keys get an owner here.
FACT_OWNERS = (('fact_surv_', 'Survival'), ('fact_maras_', 'Relationships'), ('fact_affection', 'OStim Expansion'),
               ('fact_saved', 'World'), ('fact_fought', 'World'), ('fact_customer', 'World'), ('fact_defended', 'World'),
               ('fact_dungeons', 'World'), ('fact_friendly_fire', 'World'), ('fact_healed', 'World'),
               ('fact_kills', 'World'), ('fact_strongest', 'World'))


def fact_owner(key: str) -> str | None:
    key = str(key).lower()
    return next((owner for prefix, owner in FACT_OWNERS if key.startswith(prefix)), None)


def game_facts(npc: dict, today: int | None, installed=None, prefix: str = 'fact_') -> list[dict]:
    """Definite facts any module wrote into this NPC's file, with no module depending on another. A string value named
    fact_<anything> holding "day|expires_day|priority|text": day and expires_day are game days (-1 = no date, never
    expires), priority 1 to 3 (3 first). Expired or malformed ones are left out; newest first within a priority.
    installed: the module names present; facts of a module not in it are left out (None = no check). prefix: only the
    keys starting with it (one module's facts)."""
    rows = []
    for key, value in (npc or {}).items():
        if not str(key).lower().startswith('fact_') or not str(key).lower().startswith(prefix) or not isinstance(value, str):
            continue
        owner = fact_owner(key)
        if installed is not None and owner is not None and owner not in installed:
            continue
        parts = value.split('|', 3)
        if len(parts) != 4 or not parts[3].strip():
            continue
        try:
            day, expires, priority = int(parts[0]), int(parts[1]), int(parts[2])
        except ValueError:
            continue
        if expires >= 0 and today is not None and today > expires:
            continue
        rows.append({'day': day, 'priority': priority, 'text': parts[3].strip()})
    # an undated fact describes right now, so it sorts as newest within its priority
    return sorted(rows, key=lambda r: (-r['priority'], -(r['day'] if r['day'] >= 0 else 1 << 30)))


def speaking_ids() -> list[str]:
    """The base ids (hex, as the npc files are named) of the NPCs Mantella is answering for right now, as Direct AI
    Connect notes them for each request (its extension registry's speaking_ids); [] from an older one."""
    registry = getattr(sys.modules.get('src.extensions'), '_registry', None)
    ids = getattr(registry, 'speaking_ids', None)
    if not isinstance(ids, (list, tuple)):
        return []
    return [str(i).strip().upper() for i in ids if isinstance(i, (str, int)) and BASE_ID.match(str(i).strip())]


def speaking_names() -> dict:
    """{base id number: name} of the NPCs Mantella is answering for (Direct AI Connect's speaking, the names in the
    order of speaking_ids); {} when they do not line up one to one."""
    registry = getattr(sys.modules.get('src.extensions'), '_registry', None)
    ids, text = getattr(registry, 'speaking_ids', None), getattr(registry, 'speaking', None)
    if not isinstance(ids, (list, tuple)) or not isinstance(text, str) or not text.strip():
        return {}
    names = [n.strip() for n in text.split(', ')]
    numbers = [_id_number(str(i).strip()) if isinstance(i, (str, int)) and BASE_ID.match(str(i).strip()) else None for i in ids]
    if len(names) != len(numbers) or None in numbers or not all(names):
        return {}
    return dict(zip(numbers, names))


def _id_number(base_id: str) -> int | None:
    try:
        return int(str(base_id), 16)
    except ValueError:
        return None


def load_conversation() -> list[dict]:
    """Who is in the current Mantella conversation, each with their npc state. A speaker whose file is missing or
    broken is kept with no state, so the action filter treats them as a stranger instead of forgetting them.
    The game writes the speakers into conversation.json only after Mantella's greeting request has gone out, so the
    NPCs Direct AI Connect says it is answering for (speaking_ids) come first, in its order, and the file adds anyone
    else: the greeting and the turns after it then get the same speakers (same actions, same NPC facts, same cache)."""
    from . import contracts
    ids = contracts.game_lists(_read('conversation.json')).get('speakers')
    from_file = [str(i) for i in ids if BASE_ID.match(str(i))] if isinstance(ids, list) else []
    order, seen = [], set()
    for base_id in speaking_ids() + from_file:
        number = _id_number(base_id)
        if number is not None and number not in seen:
            seen.add(number)
            order.append(base_id)
    names = speaking_names()  # a file holding another plugin's NPC is left out (load_npc)
    return [load_npc(base_id, names.get(_id_number(base_id))) or {'base_id': base_id.upper()} for base_id in order]


def jobs_text(speakers: list[dict], installed=None) -> str:
    """Missives board jobs the speakers posted ("job" in their file, written by Mantella Living World - Missives);
    nothing when installed is given and Missives is not in it."""
    if installed is not None and 'Missives' not in installed:
        return ''
    blocks = []
    for s in speakers:
        job = s.get('job')
        if isinstance(job, str) and job.strip():
            name = s.get('name', '?')
            blocks.append(f"Job board notices {name} posted ({name} knows this):\n- {job.strip()}")
    return '\n\n'.join(blocks)
