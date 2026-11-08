"""Reads what the game side writes for Mantella: PapyrusUtil JSON under SKSE/Plugins/StorageUtilData/MantellaLivingWorld/.
Every reader returns an empty value on any problem (missing, half-written, not JSON), never an error."""
import json
import os
import re
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


def _read(name: str, retry: bool = True) -> dict:
    for _ in range(REPLACE_TRIES if retry else 1):
        try:
            with open(os.path.join(DATA_DIR, name), 'rb') as f:
                data = json.loads(decode(f.read()))
            return data if isinstance(data, dict) else {}
        except PermissionError:  # on Windows a file being replaced cannot be opened for a moment
            time.sleep(0.02)
        except ValueError:
            if retry:  # the game may be halfway through saving it
                time.sleep(0.05)
                return _read(name, False)
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


def _flatten(data: dict) -> dict:
    """JsonUtil keeps values by type ({"int": {...}, "string": {...}, ...}); one dict is easier to use."""
    flat = {}
    for kind in ('int', 'float', 'string', 'form', 'stringList'):
        values = data.get(kind)
        if isinstance(values, dict):
            flat.update(values)
    return flat


def load_npc(base_id: str) -> dict:
    if not base_id or not BASE_ID.match(base_id):
        return {}
    data = _flatten(_read(os.path.join('npc', base_id.upper() + '.json')))
    if data:
        data['base_id'] = base_id.upper()
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
    if player and isinstance(world.get('player'), str) and world['player'] and world['player'] != player:
        return False
    day = world.get('day')
    if today is not None and isinstance(day, (int, float)) and not isinstance(day, bool) and int(day) > today:
        return False
    return True


def load_said_nearby() -> list[dict]:
    lines = _read('said_nearby.json').get('lines')
    return [line for line in lines if isinstance(line, dict)] if isinstance(lines, list) else []


def load_banter() -> dict:
    """Why World's banter or initiative started the current talk: {seed, active}."""
    return _flatten(_read('banter.json'))


def load_player_name() -> str:
    name = _flatten(_read('conversation.json')).get('player')
    return name if isinstance(name, str) else ''


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


def game_facts(npc: dict, today: int | None, installed=None) -> list[dict]:
    """Definite facts any module wrote into this NPC's file, with no module depending on another. A string value named
    fact_<anything> holding "day|expires_day|priority|text": day and expires_day are game days (-1 = no date, never
    expires), priority 1 to 3 (3 first). Expired or malformed ones are left out; newest first within a priority.
    installed: the module names present; facts of a module not in it are left out (None = no check)."""
    rows = []
    for key, value in (npc or {}).items():
        if not str(key).lower().startswith('fact_') or not isinstance(value, str):
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


def load_conversation() -> list[dict]:
    """Who is in the current Mantella conversation, each with their npc state. A speaker whose file is missing or
    broken is kept with no state, so the action filter treats them as a stranger instead of forgetting them."""
    ids = (_read('conversation.json').get('stringList') or {}).get('speakers')
    if not isinstance(ids, list):
        return []
    speakers = []
    for i in ids:
        base_id = str(i)
        if BASE_ID.match(base_id):
            speakers.append(load_npc(base_id) or {'base_id': base_id.upper()})
    return speakers


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
