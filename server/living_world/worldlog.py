"""World log: what really happened in this save, written once, and the people the server has met.

Per save, next to the memories: <conversations folder>/<world id>/living_world/world/
    log.json      {version, seq, events: [Event]}
    people.json   {people: {key: Person}}  (who the server has seen in a talk or a fight: name, ids, town, hold, home)

Event = {id, kind, day (game days, GameDaysPassed), place: {location, town, hold}, involved: [P], present: [P],
         true_text (the Hub's record, never sent to an NPC), public_text (what an onlooker would say; '' = private,
         never spreads), size (small / big), importance, flags..., wipes: [Wipe], known: {key: Known}, retracted}
P = {key, base, ref, name}; the player is {key: 'player', name}.
Known = {how: seen / told / rumour / hearsay / own, since (game day it reached them), by (who told them), mem (memory
         id, '' when they remember it from the talk itself), name, ref, town, reentry (wipe seq it came back after)}
Wipe = {id, seq, scope, members: [idents], town, day, by, note, hidden: [{name, ref, id}]}

Nothing here calls a model, and every public function returns an empty value instead of raising. Size (small / big)
is decided by rules (decide_size). Children are never named in marriage or intimate events: such an event naming a
child is not logged at all.

Place data comes from what the game already sends (npc files: home, hold, location, here_hold; and, with
MLW_WorldFacts.psc, town / home_town), the Knowledge module's shipped profiles.json / places.json when it is installed
(read as files, never imported), and ties.json (Relationships)."""
import copy
import hashlib
import json
import logging
import os
import re
import threading
import time

from . import action_filter, lw_state

logger = logging.getLogger('Mantella')

DIR = 'world'
LOG_FILE = 'log.json'
PEOPLE_FILE = 'people.json'
MAX_EVENTS = 1000  # per save; the oldest go first
MAX_PEOPLE = 4000
MAX_TEXT = 400
PLAYER = 'player'
KINDS = ('marriage', 'engagement', 'divorce', 'breakup', 'death', 'killing', 'crime', 'wipe', 'release', 'custom',
         'fight', 'intimate')
NO_CHILD_KINDS = ('marriage', 'engagement', 'divorce', 'breakup', 'intimate')  # a child is never named in these
# Who learns of an event. Public kinds spread through the news rings (news.py); 'intimate' reaches only those present;
# a wipe or a release by the player's magic is never news: nobody knows it happened, so it is logged for the Hub's true
# record and the mechanics (stopping spread, strangeness) only. The NPC herself may know (a release she remembers) and
# can tell others in a later talk; that travels as her talk's own memory, never through the rings.
PRIVATE_KINDS = ('intimate',)
NEVER_NEWS_KINDS = ('wipe', 'release')
BIG_KINDS = ('marriage', 'divorce', 'killing')
TOWN_KINDS = ('city', 'town', 'settlement', 'village')
# Where the Knowledge module's data sits when it is installed: extensions/lw_knowledge/data (next to this extension)
KNOWLEDGE_DIRS = [os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'lw_knowledge', 'data')]

_lock = threading.RLock()
_cache: dict = {}  # path -> (stamp, data): reads share one parsed copy until the file changes
_static: dict = {}  # knowledge data, read once


# --- small helpers -----------------------------------------------------------------------------------------------------

def _text(value, limit=MAX_TEXT) -> str:
    return ' '.join(str(value).split())[:limit] if isinstance(value, (str, int, float)) and not isinstance(value, bool) else ''


def _float(value, default=-1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number == number and abs(number) < 1e9 else default


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def base_key(value) -> str:
    """A base id as the game's npc files name it: the last 6 hex digits, upper case ('' when it is not one)."""
    text = str(value or '').strip()
    if text.lower().startswith('0x'):
        text = text[2:]
    if not text or not re.fullmatch(r'[0-9A-Fa-f]{1,8}', text):
        return ''
    return text.upper()[-6:].rjust(6, '0')


def ref_key(value) -> str:
    """A reference id the way Mantella files NPCs: the last 6 hex digits; a light plugin's FE id keeps its last 3."""
    text = str(value or '').strip()
    if isinstance(value, int) and not isinstance(value, bool):
        text = format(value % (1 << 32), '08X')
    if text.lower().startswith('0x'):
        text = text[2:]
    if not text or not re.fullmatch(r'[0-9A-Fa-f]{1,8}', text):
        return ''
    text = text.upper()
    if len(text) == 8 and text.startswith('FE'):
        return text[-3:].rjust(6, '0')
    return text[-6:].rjust(6, '0')


def norm(text) -> str:
    return ' '.join(str(text or '').lower().split())


def _get(obj, key):
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def person(name='', base='', ref='', minor=False) -> dict:
    """{key, base, ref, name}: key is the base id when known, else 'r<ref>', else 'n:<name>'."""
    name, base, ref = _text(name, 80), base_key(base), ref_key(ref)
    key = base or ('r' + ref if ref else ('n:' + norm(name) if name else ''))
    out = {'key': key, 'base': base, 'ref': ref, 'name': name}
    if minor:
        out['minor'] = 1
    return out


def player_person(name: str) -> dict:
    return {'key': PLAYER, 'base': '', 'ref': '', 'name': _text(name, 80) or 'the player'}


def idents(p: dict) -> set:
    """What one person can be matched by: base id, reference id; the name only when neither is known."""
    if not isinstance(p, dict):
        return set()
    if p.get('key') == PLAYER:
        return {PLAYER}
    out = set()
    if p.get('base'):
        out.add('b:' + p['base'])
    if p.get('ref'):
        out.add('r:' + p['ref'])
    if not out and p.get('name'):
        out.add('n:' + norm(p['name']))
    return out


def known_idents(key: str, entry: dict) -> set:
    """The idents of an event's known entry: its key (a base id, 'r'<ref> or 'n:'<name>), its ref and base, its name."""
    out = set()
    key = str(key or '')
    if re.fullmatch(r'[0-9A-F]{6}', key):
        out.add('b:' + key)
    elif key.startswith('r') and re.fullmatch(r'r[0-9A-F]{6}', key):
        out.add('r:' + key[1:])
    elif key.startswith('n:'):
        out.add(key)
    if isinstance(entry, dict):
        if entry.get('ref'):
            out.add('r:' + str(entry['ref']))
        if entry.get('base'):
            out.add('b:' + str(entry['base']))
        if entry.get('name'):
            out.add('n:' + norm(entry['name']))
    return out


def weak_idents(p: dict) -> set:
    """idents plus the name: for matching a tie or a listed name against people known by id."""
    out = idents(p)
    if isinstance(p, dict) and p.get('name') and p.get('key') != PLAYER:
        out.add('n:' + norm(p['name']))
    return out


def ident_match(a, b) -> bool:
    """Whether two ident sets (idents / weak_idents) are one person. Generic NPCs share names and often a base id
    (guards), so the reference id decides when both sides have one, else the base id; the name only counts when one
    side has no id at all, never when both have ids."""
    a, b = set(a or ()), set(b or ())
    if PLAYER in a or PLAYER in b:
        return PLAYER in a and PLAYER in b
    pick = lambda s, kind: {i for i in s if isinstance(i, str) and i.startswith(kind)}
    ar, br = pick(a, 'r:'), pick(b, 'r:')
    if ar and br:
        return bool(ar & br)
    ab, bb = pick(a, 'b:'), pick(b, 'b:')
    if ab and bb:
        return bool(ab & bb)
    if (ar or ab) and (br or bb):
        return False
    return bool(pick(a, 'n:') & pick(b, 'n:'))


def same(a: dict, b: dict) -> bool:
    """One person (ident_match): by reference id when both have it, else by base id, else by name when one side has no
    id."""
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False
    if a.get('key') == PLAYER or b.get('key') == PLAYER:
        return a.get('key') == b.get('key')
    return ident_match(weak_idents(a), weak_idents(b))


def known_key(p: dict) -> str:
    """The key an event's known entry is kept under: the individual (reference id) when known, so two generic NPCs
    sharing a base id never share one entry; else the person's key."""
    return ('r' + p['ref']) if isinstance(p, dict) and p.get('ref') else (p or {}).get('key', '')


def jitter(*parts) -> float:
    """A fixed number in [0, 1) for these parts (an NPC and an event): delays differ per NPC but never per call."""
    digest = hashlib.sha1('|'.join(str(p) for p in parts).encode('utf-8')).hexdigest()
    return int(digest[:8], 16) / 0x100000000


# --- files -------------------------------------------------------------------------------------------------------------

def folder(store) -> str:
    return os.path.join(getattr(store, 'root', '') or '', DIR)


def _path(store, name) -> str:
    return os.path.join(folder(store), name)


def _stamp(path):
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _read(path, empty):
    """The parsed file, shared with other readers until it changes: callers must not change it (use _fresh)."""
    stamp = _stamp(path)
    if stamp is None:
        return empty()
    hit = _cache.get(path)
    if hit and hit[0] == stamp:
        return hit[1]
    data = lw_state.read_store_json(path)  # a file that could not be read is then not saved over (_write)
    if data is None and _key_unread(path):
        return empty()  # not kept: the next read tries the file again
    if not isinstance(data, dict):
        data = empty()
    _cache[path] = (stamp, data)
    return data


def _fresh(path, empty):
    return copy.deepcopy(_read(path, empty))


def _key_unread(path) -> bool:
    try:
        lw_state.guard_save(path)
        return False
    except OSError:
        return True


def _write(path, data) -> bool:
    try:
        lw_state.guard_save(path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        temp = f"{path}.{os.getpid()}-{threading.get_ident()}.tmp"
        with open(temp, 'w', encoding='utf-8', errors='replace') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        for attempt in range(50):
            try:
                os.replace(temp, path)
                break
            except PermissionError:
                if attempt == 49:
                    raise
                time.sleep(0.02)
        _cache[path] = (_stamp(path), copy.deepcopy(data))
        return True
    except OSError as e:
        logger.warning(f"Living World: could not save the world log ({e})")
        return False


def _empty_log() -> dict:
    return {'version': 0, 'seq': 0, 'events': []}


def _empty_people() -> dict:
    return {'people': {}}


def read_log(store) -> dict:
    """The world log (read-only; shared). {version, seq, events}."""
    if store is None:
        return _empty_log()
    data = _read(_path(store, LOG_FILE), _empty_log)
    if not isinstance(data.get('events'), list):
        return _empty_log()
    return data


def events(store) -> list[dict]:
    return [e for e in read_log(store)['events'] if isinstance(e, dict) and e.get('id')]


def find(store, event_id: str) -> dict | None:
    return next((e for e in events(store) if e['id'] == event_id), None)


def change_log(store, fn, events_changed=True):
    """Runs fn(log) on a fresh copy under the lock and saves it when fn returns a true value; returns that value.
    events_changed=False: only who-knows marks changed (the per-talk cache of news.catch_up stays valid)."""
    if store is None:
        return None
    with _lock:
        path = _path(store, LOG_FILE)
        data = _fresh(path, _empty_log)
        if not isinstance(data.get('events'), list):
            data = _empty_log()
        result = fn(data)
        if result:
            data['version'] = _int(data.get('version')) + 1
            if events_changed:
                data['eversion'] = _int(data.get('eversion')) + 1
            data['events'] = data['events'][-MAX_EVENTS:]
            _write(path, data)
        return result


def read_people(store) -> dict:
    if store is None:
        return {}
    data = _read(_path(store, PEOPLE_FILE), _empty_people)
    return data.get('people') if isinstance(data.get('people'), dict) else {}


# --- the Knowledge module's static data (optional) -----------------------------------------------------------------------

def _knowledge_file(name):
    dirs = list(KNOWLEDGE_DIRS)
    if os.environ.get('LW_KNOWLEDGE_DATA'):
        dirs.insert(0, os.environ['LW_KNOWLEDGE_DATA'])
    for d in dirs:
        path = os.path.join(d, name)
        if os.path.isfile(path):
            return path
    return ''


def _load_static(name):
    path = _knowledge_file(name)
    hit = _static.get(name)
    if hit and hit[0] == path:
        return hit[1]
    data = {}
    if path:
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
    _static[name] = (path, data if isinstance(data, dict) else {})
    return _static[name][1]


def places() -> dict:
    """{lower name: {name, town, hold, kind}} from Knowledge's places.json; {} without it."""
    raw = _load_static('places.json')
    key = ('places-index', id(raw))
    if _static.get('places-index', (None,))[0] != key:
        index = {}
        for name, value in raw.items():
            if isinstance(value, dict):
                index[norm(name)] = {'name': name, 'town': _text(value.get('town'), 80), 'hold': norm_hold(value.get('hold')),
                                     'kind': norm(value.get('kind'))}
        _static['places-index'] = (key, index)
    return _static['places-index'][1]


def profiles() -> dict:
    """{base id int: {home, hold, profession, name}} from Knowledge's profiles.json; {} without it."""
    raw = _load_static('profiles.json')
    key = ('profiles-index', id(raw))
    if _static.get('profiles-index', (None,))[0] != key:
        index = {}
        table = raw.get('profiles') if isinstance(raw.get('profiles'), dict) else {}
        for value in table.values():
            if not isinstance(value, dict):
                continue
            base = base_key(value.get('base_id'))
            if base:
                index[base] = {'home': _text(value.get('home'), 80), 'hold': norm_hold(value.get('hold')),
                               'profession': norm(value.get('profession')), 'name': _text(value.get('name'), 80)}
        _static['profiles-index'] = (key, index)
    return _static['profiles-index'][1]


HOLDS = {'whiterun': 'Whiterun', 'haafingar': 'Haafingar', 'eastmarch': 'Eastmarch', 'rift': 'Rift', 'reach': 'Reach',
         'pale': 'Pale', 'falkreath': 'Falkreath', 'hjaalmarch': 'Hjaalmarch', 'winterhold': 'Winterhold',
         'solstheim': 'Solstheim'}


def norm_hold(name) -> str:
    """'The Reach', 'Reach', 'Whiterun Hold' -> the Hub's hold names ('Reach', 'Whiterun'); '' when unknown."""
    text = norm(name)
    if text.startswith('the '):
        text = text[4:]
    if text.endswith(' hold'):
        text = text[:-5]
    return HOLDS.get(text, '')


def hold_text(hold: str) -> str:
    return 'the ' + hold if hold in ('Reach', 'Pale', 'Rift') else (hold or '')


def town_of_place(name) -> str:
    """The town a place is in ('Sleeping Giant Inn' -> 'Riverwood'), the place itself when it is a town; '' unknown."""
    if not name:
        return ''
    found = places().get(norm(name))
    if not found:
        return ''
    if found['town']:
        return found['town']
    if found['kind'] in TOWN_KINDS:
        return found['name']
    return ''


def hold_of_place(name) -> str:
    found = places().get(norm(name)) if name else None
    return found['hold'] if found else ''


# --- ties (Relationships' ties.json) -----------------------------------------------------------------------------------

def load_ties() -> dict:
    """{base: {name, home, day, ties: [{kind, base, name}]}} from ties.json (Relationships); {} without it."""
    try:
        from . import contracts
        return contracts.load_ties()
    except Exception:
        pass
    try:  # the same shape read directly (spec 12a), for when contracts.py is not there
        from . import lw_state
        data = lw_state._read('ties.json')
    except Exception:
        return {}
    out = {}
    for key, value in (data or {}).items():
        base = base_key(key)
        if base and isinstance(value, dict):
            ties = [{'kind': norm(t.get('kind')), 'base': base_key(t.get('base')), 'name': _text(t.get('name'), 80)}
                    for t in value.get('ties') or [] if isinstance(t, dict)]
            out[base] = {'name': _text(value.get('name'), 80), 'home': _text(value.get('home'), 160), 'ties': ties}
    return out


TIE_ORDER = ('spouse', 'parent', 'child', 'sibling', 'household', 'courting', 'works_for', 'employs', 'cousin')
NEAR_KINDS = set(TIE_ORDER)  # 'enemy' is a tie, but never someone who passes news on


def ties_for(me: dict, ties: dict | None = None, people: dict | None = None) -> list[dict]:
    """This person's circle (ring 2): their ties from ties.json both ways (spouse, family, household, boss/workers;
    never enemies), plus everyone with the same home there or in the people seen (a household when "household" ties are
    missing). Each {kind, base, name}, the closest kind first."""
    if not isinstance(me, dict) or me.get('key') == PLAYER:
        return []
    ties = load_ties() if ties is None else ties
    out = []
    base = me.get('base')
    if base:
        try:
            from . import contracts
            listed = contracts.ties_of(base, ties)
        except Exception:
            listed = list((ties.get(base) or {}).get('ties') or [])
            for other, entry in ties.items():
                for t in entry.get('ties') or []:
                    if t.get('base') == base and other != base:
                        listed.append({'kind': t.get('kind'), 'base': other, 'name': entry.get('name') or ''})
        out = [dict(t) for t in listed if isinstance(t, dict) and t.get('kind') in NEAR_KINDS]
    home = norm(me.get('home') or (ties.get(base) or {}).get('home') if base else me.get('home'))
    if home:
        for other, entry in ties.items():
            if other != base and norm(entry.get('home')) == home:
                out.append({'kind': 'household', 'base': other, 'name': entry.get('name') or ''})
        for key, entry in (people or {}).items():
            if isinstance(entry, dict) and norm(entry.get('home')) == home and key != me.get('key') \
                    and (not base or entry.get('base') != base):
                out.append({'kind': 'household', 'base': entry.get('base') or '', 'name': entry.get('name') or ''})
    seen, unique = set(), []
    for t in sorted(out, key=lambda t: TIE_ORDER.index(t['kind']) if t['kind'] in TIE_ORDER else 99):
        ident = 'b:' + t['base'] if t.get('base') else 'n:' + norm(t.get('name'))
        if ident in seen or ident in ('b:', 'n:'):
            continue
        seen.add(ident)
        unique.append(t)
    return unique


# --- people: who the server has seen -----------------------------------------------------------------------------------

def place_of(speaker=None, base='', ties=None, known=None) -> dict:
    """{town, hold, home} of an NPC: the game's npc file first (home_town from MLW_WorldFacts, else the town of their
    home), then the Knowledge profile, then ties.json's home, then what was known before. '' where unknown."""
    speaker = speaker if isinstance(speaker, dict) else {}
    known = known if isinstance(known, dict) else {}
    base = base_key(base or speaker.get('base_id'))
    profile = profiles().get(base, {}) if base else {}
    tie = (ties or {}).get(base, {}) if base else {}
    home = _text(speaker.get('home'), 160) or _text(tie.get('home'), 160) or known.get('home', '')
    town = (_text(speaker.get('home_town'), 80) or town_of_place(speaker.get('home')) or town_of_place(profile.get('home'))
            or _text(profile.get('home'), 80) or town_of_place(tie.get('home')) or known.get('town', ''))
    hold = (norm_hold(speaker.get('hold')) or profile.get('hold', '') or hold_of_place(town) or known.get('hold', ''))
    return {'town': town, 'hold': hold, 'home': home}


def talk_place(speakers) -> dict:
    """Where a talk happens: the first speaker's current town / location / hold."""
    for s in speakers or []:
        if not isinstance(s, dict):
            continue
        location = _text(s.get('location'), 120)
        town = _text(s.get('town'), 80) or town_of_place(location)
        hold = norm_hold(s.get('here_hold')) or hold_of_place(location) or hold_of_place(town)
        if location or town or hold:
            return {'location': location, 'town': town, 'hold': hold}
    return {'location': '', 'town': '', 'hold': ''}


def magic_trained(speaker: dict, base: str = '') -> bool:
    """Has magic training: MLW_WorldFacts' magic flag, a mage class, the College, or a mage profession in Knowledge."""
    if not isinstance(speaker, dict):
        speaker = {}
    if _int(speaker.get('magic')) > 0:
        return True
    cls = norm(speaker.get('class'))
    if any(w in cls for w in ('mage', 'wizard', 'sorcer', 'necromancer', 'conjurer', 'spellsword', 'nightblade',
                              'battlemage', 'witch', 'illusionist', 'priest of', 'warlock')):
        return True
    groups = speaker.get('groups') if isinstance(speaker.get('groups'), list) else []
    if any(norm(g) == 'college of winterhold' for g in groups):
        return True
    profile = profiles().get(base_key(base or speaker.get('base_id')), {})
    return profile.get('profession') in ('mage', 'court_wizard', 'necromancer')


def identify(npc, context=None, people=None, ties=None) -> dict:
    """A person (person()) with town, hold, home and minor, for a Mantella character, a speaker dict or {name, ref_id,
    base_id}. Mantella's own name and ref (the memory file's) win; the game's speaker adds base id and place."""
    context = context or {}
    name = _text(_get(npc, 'name'), 80)
    ref = ref_key(_get(npc, 'ref_id'))
    base = base_key(_get(npc, 'base_id'))
    speakers = [s for s in context.get('speakers') or [] if isinstance(s, dict)]
    other_ref = lambda s: bool(ref and ref_key(s.get('ref_id')) and ref_key(s.get('ref_id')) != ref)
    # the reference id first: generic NPCs (guards) share a base id and a name
    speaker = next((s for s in speakers if ref and ref_key(s.get('ref_id')) == ref), None)
    if speaker is None and base:
        speaker = next((s for s in speakers if base_key(s.get('base_id')) == base and not other_ref(s)), None)
    if speaker is None and name:
        speaker = next((s for s in speakers if norm(s.get('name')) == norm(name) and not other_ref(s)), None)
    game = speaker
    if isinstance(npc, dict):  # what the caller gives wins over the same person's speaker entry
        speaker = {**(speaker or {}), **{k: v for k, v in npc.items() if v not in (None, '')}}
    speaker = speaker or {}
    base = base or base_key(speaker.get('base_id'))
    ref = ref or ref_key(speaker.get('ref_id'))
    name = name or _text(speaker.get('name'), 80)
    for mname, mref in context.get('people') or []:  # Mantella's name for the memory file ("Whiterun Guard 2")
        if ref and ref_key(mref) == ref:
            name = _text(mname, 80) or name
            break
    people = read_people(context.get('store')) if people is None and context.get('store') is not None else (people or {})
    known = lookup(people, person(name, base, ref)) or {}
    base = base or known.get('base', '')
    ref = ref or known.get('ref', '')
    if not name:
        name = known.get('mname') or known.get('name') or ''
    me = person(name, base, ref, minor=_int(speaker.get('minor')) > 0 or bool(known.get('minor'))
                or profiles().get(base, {}).get('profession') == 'child')
    # someone in the talk (a Mantella character, a game speaker, or a caller giving minor) the game has not confirmed as
    # an adult yet (no npc file, a broken one, no minor key): treated like a child for news and the like; never stored
    in_talk = game is not None or (isinstance(npc, dict) and 'minor' in npc) or \
        (not isinstance(npc, dict) and context.get('speakers') is not None)
    if in_talk and not me.get('minor') and not action_filter.adult(speaker):
        me['unconfirmed'] = 1
    me.update(place_of(speaker, base, ties, known))
    me['magic'] = 1 if magic_trained(speaker, base) or known.get('magic') else 0
    if isinstance(speaker.get('illusion'), (int, float)) and not isinstance(speaker.get('illusion'), bool):
        me['illusion'] = int(speaker['illusion'])
    elif isinstance(known.get('illusion'), int):
        me['illusion'] = known['illusion']
    sex = norm(speaker.get('sex'))  # the game's word, compared without case
    if sex in ('male', 'female'):
        me['sex'] = sex
    elif known.get('sex') in ('male', 'female'):
        me['sex'] = known['sex']
    return me


def lookup(people: dict, p: dict) -> dict | None:
    """The people.json entry of this person: by reference id, then base id (never the entry of another individual with
    that base: generic NPCs share one), then a unique name when one side has no id."""
    if not people or not isinstance(p, dict):
        return None
    ref, base = p.get('ref') or '', p.get('base') or ''
    entries = lambda: ((k, e) for k, e in people.items() if isinstance(e, dict))
    if ref:
        for hit in (people.get('r' + ref), people.get(base) if base else None):
            if isinstance(hit, dict) and hit.get('ref') == ref:
                return hit
        for k, e in entries():
            if e.get('ref') == ref or k == 'r' + ref:
                return e
    other = lambda e: bool(ref and e.get('ref') and e['ref'] != ref)
    if base:
        if isinstance(people.get(base), dict) and not other(people[base]):
            return people[base]
        for k, e in entries():
            if e.get('base') == base and not other(e):
                return e
    if p.get('key') and isinstance(people.get(p['key']), dict) and not other(people[p['key']]):
        return people[p['key']]
    if p.get('name'):
        has_id = lambda e: bool(e.get('ref') or e.get('base'))
        found = [e for k, e in entries() if norm(e.get('name')) == norm(p['name']) and not ((ref or base) and has_id(e))]
        if len(found) == 1:
            return found[0]
    return None


def note_people(store, persons, day=None) -> int:
    """Remembers these people (identify() results): ids, Mantella name, town, hold, home, minor, magic. Saved only when
    something changed. Returns how many changed."""
    if store is None:
        return 0
    persons = [p for p in persons or [] if isinstance(p, dict) and p.get('key') and p.get('key') != PLAYER]
    if not persons:
        return 0
    current = read_people(store)

    def merged(entry, p):
        new = dict(entry or {})
        for field in ('base', 'ref', 'town', 'hold', 'home'):
            if p.get(field):
                new[field] = p[field]
        if p.get('name'):
            new.setdefault('name', p['name'])
            new['mname'] = p['name']
        for field in ('minor', 'magic'):
            if p.get(field):
                new[field] = 1
        if p.get('sex') in ('male', 'female'):
            new['sex'] = p['sex']
        if isinstance(p.get('illusion'), int):
            new['illusion'] = p['illusion']
        return new

    if all(merged(lookup(current, p), p) == (lookup(current, p) or {}) for p in persons):
        return 0
    with _lock:
        path = _path(store, PEOPLE_FILE)
        data = _fresh(path, _empty_people)
        table = data.get('people') if isinstance(data.get('people'), dict) else {}
        changed = 0
        for p in persons:
            old = lookup(table, p)
            key = next((k for k, v in table.items() if v is old), None) if old is not None else None
            if key is None:  # the base id, unless another individual with that base (a generic NPC) holds it
                holder = table.get(p['base']) if p['base'] else None
                taken = isinstance(holder, dict) and bool(holder.get('ref')) and bool(p['ref']) and holder['ref'] != p['ref']
                key = p['base'] if p['base'] and not taken else ('r' + p['ref'] if p['ref'] else p['key'])
            new = merged(old, p)
            if day is not None:
                new['seen'] = _float(day)
            if new != old:
                if old is not None:
                    for k in [k for k, v in table.items() if v is old]:
                        table.pop(k)
                table[key] = new
                changed += 1
        if len(table) > MAX_PEOPLE:
            table = dict(sorted(table.items(), key=lambda kv: _float(kv[1].get('seen')))[-MAX_PEOPLE:])
        data['people'] = table
        if changed:
            _write(path, data)
        return changed


# --- size rules --------------------------------------------------------------------------------------------------------

BIG_WORDS = re.compile(
    r"\b(?:died|dies|dead|death|killed|kills|murder(?:ed|s)?|slain|slew|executed|beheaded|assassinat\w*|"
    r"dragons?|burn(?:ed|t|s)? down|burned to the ground|destroyed|razed|married|marries|wedding|wed|divorc\w*|"
    r"crowned|exiled|banished|overthrown|jarl\b|war\b|invaded|attacked the town|plague|kidnapp\w*|abducted|vanished|"
    r"pregnant|gave birth|born)\b", re.I)
SMALL_WORDS = re.compile(
    r"\b(?:fight|fought|brawl\w*|punch\w*|stole|stolen|steals?|robbed|theft|thief|arrested|jailed|fined|bounty|"
    r"wounded|injured|hurt|sick|ill\b|insult\w*|slapped|threaten\w*|engaged|proposed|kiss\w*|eloped|fired|"
    r"quit|left town|moved|bought|sold the|lost (?:her|his|their) job|drunk|caught|shouted|screamed|argued|argument|"
    r"duel|bitten|vampire|werewolf|cursed)\b", re.I)
INTIMATE_WORDS = re.compile(r"\b(?:kiss\w*|slept with|bed(?:ded)?|sex|made love|naked|undress\w*|seduc\w*|lover)\b", re.I)


def classify_text(text: str) -> tuple[str, str] | None:
    """(kind, size) for a typed event, or None when it is not news (an outfit, a sight, a small mishap)."""
    if not text:
        return None
    if INTIMATE_WORDS.search(text):
        return ('intimate', 'small')
    if BIG_WORDS.search(text):
        if re.search(r"\b(?:married|marries|wedding|wed)\b", text, re.I):
            return ('marriage', 'big')
        return ('custom', 'big')
    if SMALL_WORDS.search(text):
        return ('custom', 'small')
    return None


def decide_size(kind: str, **facts) -> str:
    """big or small by rules: marriages, divorces and killings are big; a death is big when it was a named person,
    by the player or in a town; a fight is big with a dragon, a named foe, a death on the player's side or six foes;
    a release is big when the spell came to light; everything else small unless facts say big=True."""
    if facts.get('big'):
        return 'big'
    if kind in BIG_KINDS:
        return 'big'
    if kind == 'death':
        return 'big' if facts.get('unique') or facts.get('by_player') or facts.get('town') else 'small'
    if kind == 'fight':
        return 'big' if facts.get('dragon') or facts.get('unique') or facts.get('death') or _int(facts.get('foes')) >= 6 else 'small'
    if kind == 'release':
        return 'big' if facts.get('came_to_light') else 'small'
    if kind == 'crime':
        return 'big' if facts.get('crime') == 'murder' else 'small'
    return 'small'


def importance_of(size: str) -> float:
    return 0.65 if size == 'big' else 0.4


# --- logging an event --------------------------------------------------------------------------------------------------

def _clean_person(p) -> dict | None:
    if isinstance(p, dict) and p.get('key') == PLAYER:
        return player_person(p.get('name'))
    if isinstance(p, dict):
        out = person(p.get('name') or '', p.get('base') or p.get('base_id') or '', p.get('ref') or p.get('ref_id') or '',
                     minor=bool(p.get('minor')))
        return out if out['key'] else None
    return None


def _people_list(items) -> list[dict]:
    out = []
    for p in items or []:
        c = _clean_person(p)
        if c and not any(same(c, o) for o in out):
            out.append(c)
    return out


def _names_child(event: dict, people: dict) -> bool:
    """A child is named in this event: listed as involved, flagged minor, or a known child's name in its text."""
    texts = norm(event.get('public_text', '')) + ' ' + norm(event.get('true_text', ''))
    for p in event['involved']:
        entry = lookup(people, p) or {}
        if p.get('minor') or entry.get('minor') or profiles().get(p.get('base', ''), {}).get('profession') == 'child':
            return True
    for p in event['present']:
        entry = lookup(people, p) or {}
        if (p.get('minor') or entry.get('minor')) and p.get('name') and re.search(r'\b' + re.escape(norm(p['name'])) + r'\b', texts):
            return True
    return False


def log_event(store, kind: str, true_text: str, public_text: str = '', day=None, place=None, involved=(), present=(),
              size: str | None = None, importance: float | None = None, event_id: str = '', known=(), how_known='seen',
              flags: dict | None = None) -> dict | None:
    """Writes one event (once: the same event_id again only adds people present / known) and returns it, or None when
    nothing was logged (no store, no text, unknown kind, or a child named in a marriage or intimate event).
    known: people who already remember it (from the talk itself or another module): they get no memory from the news
    and count as knowing it since day. Never raises."""
    try:
        if store is None or kind not in KINDS:
            return None
        true_text = _text(true_text)
        public_text = _text(public_text)
        if not true_text and not public_text:
            return None
        day = _float(day, -1.0)
        place = place if isinstance(place, dict) else {}
        event = {'id': _text(event_id, 80) or (kind + '-' + hashlib.sha1(f"{kind}|{day:.3f}|{true_text}".encode('utf-8')).hexdigest()[:12]),
                 'kind': kind, 'day': day,
                 'place': {'location': _text(place.get('location'), 120), 'town': _text(place.get('town'), 80),
                           'hold': norm_hold(place.get('hold')) or _text(place.get('hold'), 40)},
                 'involved': _people_list(involved), 'present': _people_list(present),
                 'true_text': true_text or public_text, 'public_text': public_text,
                 'size': size if size in ('small', 'big') else decide_size(kind, **(flags or {})),
                 'wipes': [], 'known': {}, 'retracted': False, 'logged': time.time()}
        event.update(_stamp_now(store))  # loading a save from before this sets it aside (timeline.py)
        event['importance'] = importance if isinstance(importance, (int, float)) else importance_of(event['size'])
        for k, v in (flags or {}).items():
            if k not in event and isinstance(v, (str, int, float, bool)):
                event[k] = v
        if kind in NO_CHILD_KINDS and _names_child(event, read_people(store)):
            logger.log(23, f"Living World: a {kind} event naming a child is not kept in the world log")
            return None
        children = [p for p in event['present'] + event['involved'] if p.get('minor')]
        if children:  # remembered as children, so news about them and to them follows the child rules
            note_people(store, children)
        knowers = _people_list(known)

        def apply(log):
            old = next((e for e in log['events'] if e.get('id') == event['id']), None)
            if old is not None and old.get('retracted'):
                return False
            target = old if old is not None else event
            changed = old is None
            if old is not None:
                for p in event['present']:
                    if not any(same(p, o) for o in old.setdefault('present', [])):
                        old['present'].append(p)
                        changed = True
            for p in knowers:
                key = known_key(p)
                if p['key'] == PLAYER or key in target.setdefault('known', {}) or any(
                        isinstance(v, dict) and ident_match(weak_idents(p), known_idents(k, v)) for k, v in target['known'].items()):
                    continue
                target['known'][key] = {'how': how_known, 'since': event['day'], 'by': '', 'mem': '', 'name': p['name'],
                                        'ref': p['ref'], 'base': p['base']}
                if p.get('minor'):
                    target['known'][key]['minor'] = 1
                changed = True
            if old is None:
                log['events'].append(event)
                log['events'].sort(key=lambda e: _float(e.get('day')))
            return changed
        change_log(store, apply)
        found = find(store, event['id'])
        return copy.deepcopy(found) if found and not found.get('retracted') else None
    except Exception as e:
        logger.warning(f"Living World: could not log a world event ({e})")
        return None


def _stamp_now(store) -> dict:
    try:
        from . import timeline
        return timeline.stamp_now(store)
    except Exception:
        return {}


def branch_of(store):
    """The loaded save's line of talks (timeline.current), or None without the game's talk counter."""
    try:
        from . import timeline
        return timeline.current(store)
    except Exception:
        return None


def usable(event: dict, branch) -> bool:
    """The event belongs to the save now loaded: not logged in a talk the loaded save never had (an older save was
    loaded); always true without the talk counter or for an event logged before it existed."""
    try:
        from . import timeline
        return timeline.usable(branch, event)
    except Exception:
        return True


def retract(store, event_id: str, by: str = 'taken back') -> int:
    """An event that did not happen after all (a custom event taken back): it stops spreading, and every memory the news
    gave of it is hidden. Returns how many memories were hidden. Never raises."""
    try:
        event = find(store, event_id)
        if event is None or event.get('retracted'):
            return 0
        hidden = 0
        try:
            from . import memory
        except Exception:
            memory = None
        for key, k in (event.get('known') or {}).items():
            if memory is not None and k.get('mem') and k.get('name') and k.get('ref'):
                found = memory.hide_matching(store, k['name'], k['ref'], k.get('text') or event.get('public_text') or '',
                                             limit=1, by='world news', note=by, only={k['mem']})
                hidden += len(found)

        def apply(log):
            for e in log['events']:
                if e.get('id') == event_id:
                    e['retracted'] = True
                    return True
            return False
        change_log(store, apply)
        return hidden
    except Exception as e:
        logger.warning(f"Living World: could not take back a world event ({e})")
        return 0


# --- adapters: one call from what other parts already have -------------------------------------------------------------

def _game_day(mantella_day, hour) -> float:
    """A memory's date (Mantella's day = game day + 1, and an hour) as game days."""
    day = _float(mantella_day, -1.0)
    if day < 0:
        return -1.0
    return day - 1 + max(0, min(23, _int(hour, 12) if _int(hour, -1) >= 0 else 12)) / 24


def from_custom_event(store, row: dict, speakers=None, player: str = '') -> dict | None:
    """A custom event (events.py journal row) into the log when its words make it news (classify_text); a taken-back
    row retracts it. The people in that talk remember it from the talk, so they count as knowing it."""
    if not isinstance(row, dict) or not row.get('id'):
        return None
    event_id = 'ce-' + _text(row['id'], 40)
    if row.get('status') != 'active':
        if find(store, event_id):
            retract(store, event_id)
        return None
    text = _text(row.get('text'))
    found = classify_text(text)
    if found is None:
        return None
    kind, size = found
    present = [person(n.get('name'), '', n.get('ref_id')) for n in row.get('npcs') or [] if isinstance(n, dict)]
    people = read_people(store)
    for p in present:
        entry = lookup(people, p)
        if entry:
            p['base'] = p['base'] or entry.get('base', '')
    involved = [p for p in present if p['name'] and re.search(r'\b' + re.escape(p['name']) + r'\b', text)]
    for entry in people.values():  # someone the server knows, named in it, though not in the talk
        name = (entry.get('mname') or entry.get('name')) if isinstance(entry, dict) else ''
        if name and len(name) > 2 and len(involved) < 6 and re.search(r'\b' + re.escape(name) + r'\b', text) \
                and not any(norm(p['name']) == norm(name) for p in involved):
            involved.append(person(name, entry.get('base'), entry.get('ref')))
    if player and re.search(r'\b' + re.escape(player) + r'\b', text):
        involved.append(player_person(player))
    place = talk_place(speakers)
    if not place['town']:  # a town named in the words ("A dragon attacked Riverwood")
        for word in re.findall(r"[A-Z][\w'-]+(?: [A-Z][\w'-]+)?", text):
            found = places().get(norm(word)) or places().get(norm(word.split(' ')[0]))
            if found and found['kind'] in TOWN_KINDS:
                place = {'location': place['location'] or found['name'], 'town': found['name'],
                         'hold': place['hold'] or found['hold']}
                break
    return log_event(store, kind, text, text, _game_day(row.get('day'), row.get('hour')), place, involved,
                     present + ([player_person(player)] if player else []), size, event_id=event_id, known=present)


MARRIAGE_STATUS = {'married': 'marriage', 'engaged': 'engagement', 'divorced': 'divorce', 'jilted': 'breakup'}


def from_marriage(store, row: dict, player: str, speaker=None) -> dict | None:
    """One marriages.json row (spec 12a: {base, name, status, day, commanded, player}) of this player character.
    married / engaged / divorced / jilted become events; commanded marks a marriage made under an Absolute Command."""
    if not isinstance(row, dict):
        return None
    if row.get('player') and player and norm(row.get('player')) != norm(player):
        return None  # the file is shared by every save: another character's
    status = norm(row.get('status'))
    kind = MARRIAGE_STATUS.get(status)
    base = base_key(row.get('base'))
    name = _text(row.get('name'), 80)
    if not kind or not (base or name):
        return None
    who = person(name, base)
    pname = player or 'the player'
    texts = {'marriage': f"{name} has married {pname}.", 'engagement': f"{name} is engaged to {pname}.",
             'divorce': f"{name} and {pname} have ended their marriage.", 'breakup': f"{name}'s engagement to {pname} is off."}
    commanded = _int(row.get('commanded')) > 0
    true_text = texts[kind] + (f" It happened while {pname}'s Absolute Command held {name}." if commanded else '')
    place = place_of(speaker, base, load_ties(), lookup(read_people(store), who))
    day = _float(row.get('day'))
    return log_event(store, kind, true_text, texts[kind], day, {'location': '', 'town': place['town'], 'hold': place['hold']},
                     [who, player_person(pname)], [who, player_person(pname)],
                     event_id=f"mar-{base or norm(name)}-{status}-{day:.2f}", known=[who],
                     flags={'strange': bool(commanded and kind in ('marriage', 'engagement')), 'player_named': True})


def from_marriages(store, player: str, rows=None) -> int:
    """Every marriages.json row of this character into the log (once each). Returns how many were new."""
    if rows is None:
        try:  # the same reader the release flow uses (contracts.py): plain lists and JsonUtil's typed shape
            from . import contracts
            rows = contracts.load_marriages(player=player or '')
        except Exception:
            rows = []
    if not player:
        rows = [r for r in rows if isinstance(r, dict) and not r.get('player')]
    before = {e['id'] for e in events(store)}
    for row in rows:
        from_marriage(store, row, player)
    return len({e['id'] for e in events(store)} - before)


def from_battle(store, fight: dict, player: str = '') -> list[dict]:
    """A memorable fight from World's battles.json: one fight event (everyone in it knows; battle.py gives them their
    own memory), and one killing event for each person who was no enemy and died by the player's hand. A fight still
    going on gives only its killings, at once: those in it so far saw it and learn it at their next talk as seen (the
    fight's own account says nothing of a killing until it is over), however long the fight goes on."""
    out = []
    try:
        from . import battle
    except Exception:
        return out
    if not isinstance(fight, dict) or not fight.get('id'):
        return out
    going_on = bool(_int(fight.get('active')))
    fighters = battle.fighters(fight)
    if not fighters:
        return out
    place_name = _text(fight.get('place'), 120)
    place = {'location': place_name, 'town': town_of_place(place_name), 'hold': hold_of_place(place_name)}
    present = [player_person(f['name']) if f.get('role') == 'player' else person(f['name'], f.get('base_id'), f['ref_id'])
               for f in fighters if f.get('role') != 'summon']
    pname = player or next((f['name'] for f in fighters if f.get('role') == 'player'), 'the player')
    end = _float(fight.get('end'))
    if battle.memorable(fight) and not going_on:
        ours, theirs = battle._sides(fight, 0)
        flags = {'dragon': any(_int(f.get('dragon')) for f in theirs), 'unique': any(_int(f.get('unique')) for f in theirs),
                 'death': any(_int(f.get('dead')) for f in ours), 'foes': len(theirs), 'player_named': True}
        at = f" at {place_name}" if place_name else ''
        text = f"There was a fight{at}: {battle._sides_text(fight, None)}. {battle._dead_text(fight, None)}"
        involved = [player_person(pname)] + [person(f['name'], f.get('base_id'), f['ref_id']) for f in theirs
                                              if _int(f.get('unique')) or _int(f.get('dragon'))][:4]
        event = log_event(store, 'fight', text, text, end, place, involved, present, event_id='fight-' + str(fight['id']),
                          known=[p for p in present if p['key'] != PLAYER], flags=flags)
        if event:
            out.append(event)
    player_refs = {f['ref_id'] for f in fighters if f.get('role') == 'player'}
    for f in fighters:
        if _int(f.get('dead')) and not _int(f.get('hostile')) and f.get('killer') in player_refs and f.get('role') != 'player':
            if not find(store, f"kill-{fight['id']}-{ref_key(f['ref_id'])}") and _killing_logged(store, ref_key(f['ref_id'])):
                _add_present(store, ref_key(f['ref_id']), present)  # World's murder row came first: one killing, logged once
                continue
            victim = person(f['name'], f.get('base_id'), f['ref_id'])
            at = f" at {place_name}" if place_name else ''
            text = f"{pname} killed {f['name']}{at}, who was no threat."
            witnesses = [p for p in present if p['key'] != PLAYER and not same(p, victim)]
            public = text if witnesses else f"{f['name']} was found dead{at}."
            when = _float(fight.get('start'), end) if going_on else end  # a fight still going on: its end is only "now"
            event = log_event(store, 'killing', text, public, when, place, [player_person(pname), victim], present,
                              event_id=f"kill-{fight['id']}-{ref_key(f['ref_id'])}", known=[] if going_on else witnesses,
                              flags={'player_named': bool(witnesses), 'by_player': True})
            if event:
                out.append(event)
    return out


def from_battles(store, fights=None, player: str = '') -> int:
    if fights is None:
        try:
            from . import lw_state
            fights = lw_state.load_battles()
        except Exception:
            fights = []
    count = 0
    for fight in fights or []:
        count += len(from_battle(store, fight, player))
    return count


def _names(npcs) -> str:
    names = [n.get('name') for n in npcs or [] if isinstance(n, dict) and n.get('name')]
    return ', '.join(names[:-1]) + ' and ' + names[-1] if len(names) > 1 else (names[0] if names else 'someone')


def _npcs_of(record) -> list[dict]:
    return [person(n.get('name'), n.get('base_id') or n.get('base'), n.get('ref_id')) for n in record.get('npcs') or []
            if isinstance(n, dict) and n.get('name')]


def from_command_wipe(store, record: dict, player: str = '', mode: str = 'gap', speakers=None, day_from=None,
                      day_to=None) -> dict | None:
    """An Absolute Command that made NPCs forget something (command.py record with forget). Never news (no public text):
    the player's magic was quiet, so nobody knows it happened. Logged for the Hub's true record and the mechanics; mode
    (gap / clean) is kept as a flag."""
    if not isinstance(record, dict) or not record.get('id') or not record.get('forget'):
        return None
    npcs = _npcs_of(record)
    names = _names(npcs)
    pname = player or 'the player'
    what = _text(record.get('forget'), 160)
    if day_from is not None and day_to is not None:
        what = f"days {int(_float(day_from))} to {int(_float(day_to))}"
    true_text = f"{pname} made {names} forget {what} with an Absolute Command."
    return log_event(store, 'wipe', true_text, '', _float(record.get('given')), talk_place(speakers),
                     npcs + [player_person(pname)], npcs + [player_person(pname)], 'small',
                     event_id='wipe-' + record['id'], known=npcs, how_known='own',
                     flags={'came_to_light': False, 'mode': mode if mode in ('gap', 'clean') else 'gap'})


RELEASE_CHOICES = ('aware', 'forget', 'keep', 'unknown')


def from_command_release(store, record: dict, choice: str = 'unknown', player: str = '', day=None, speakers=None) -> dict | None:
    """A released Absolute Command. Never news (no public text): only the Hub's record and the mechanics. 'aware'
    (remembers, and knows it was a spell): she knows (known, own) and came_to_light is set; others learn it only if she
    tells them in a later talk. 'forget', 'keep' and 'unknown' (wore off, removed): nobody knows."""
    if not isinstance(record, dict) or not record.get('id'):
        return None
    choice = choice if choice in RELEASE_CHOICES else 'unknown'
    npcs = _npcs_of(record)
    names = _names(npcs)
    pname = player or 'the player'
    text = _text(record.get('text'), 200)
    true_text = f"{pname}'s Absolute Command on {names} ended" + (f' ("{text}")' if text else '') + f" ({choice})."
    when = _float(day) if day is not None else max(_float(record.get('until')), _float(record.get('given')))
    return log_event(store, 'release', true_text, '', when, talk_place(speakers), npcs + [player_person(pname)],
                     npcs, event_id=f"release-{record['id']}", known=npcs, how_known='own',
                     flags={'came_to_light': choice == 'aware', 'choice': choice, 'player_named': choice == 'aware'})


def from_crime(store, row: dict, player: str = '', also_present=()) -> dict | None:
    """One crime row of World's crimes.json: {id, crime: murder / assault (/ theft), victim: {base, ref_id, name,
    thalmor}, day, place, town, hold, witnesses: [{base, ref_id, name} or {base, ref_id, minor: 1}], by_player, player,
    masked}. Without witnesses the public text does not name the player; a child witness keeps the minor flag (never
    named). masked: a hood hid the player's face there: the public text says "a hooded stranger" and the version with
    the name (named_text) goes only to a witness who knows the player personally (news.catch_up).
    The witnesses (and also_present: the people in the talk when it happened, or in the fight it was part of) are
    present: ring 1, the news reaches them as "seen" at their next talk."""
    if not isinstance(row, dict) or not row.get('id'):
        return None
    crime = norm(row.get('crime'))
    victim = row.get('victim') if isinstance(row.get('victim'), dict) else {}
    vname = _text(victim.get('name'), 80)
    if crime not in ('murder', 'assault', 'theft') or not vname:
        return None
    pname = player or 'the player'
    witnesses = [w for w in _people_list(row.get('witnesses')) if not _follower(w)]
    victim_p = person(vname, victim.get('base'), victim.get('ref_id') or victim.get('ref'))
    present = witnesses + [p for p in _people_list(also_present) if not same(p, victim_p) and p.get('key') != PLAYER
                           and not any(same(p, w) for w in witnesses)]
    place_name = _text(row.get('place'), 120)
    at = f" at {place_name}" if place_name else ''
    verb = {'murder': 'murdered', 'assault': 'attacked', 'theft': 'robbed'}[crime]
    true_text = f"{pname} {verb} {vname}{at}."
    masked = _int(row.get('masked')) > 0
    public = (f"A hooded stranger {verb} {vname}{at}." if masked else true_text) if witnesses else \
        {'murder': f"{vname} was found dead{at}.", 'assault': f"Someone attacked {vname}{at}.", 'theft': f"{vname} was robbed{at}."}[crime]
    place = {'location': place_name, 'town': _text(row.get('town'), 80) or town_of_place(place_name),
             'hold': norm_hold(row.get('hold')) or hold_of_place(place_name)}
    thalmor = _int(victim.get('thalmor')) > 0
    return log_event(store, 'killing' if crime == 'murder' else 'crime', true_text, public, _float(row.get('day')), place,
                     [player_person(pname), victim_p],
                     present, event_id='crime-' + _text(row['id'], 60),  # witnesses get a "seen" memory at their next talk
                     flags={'crime': crime, 'player_named': bool(witnesses) and not masked, 'by_player': True, 'thalmor': thalmor,
                            'masked': masked, 'named_text': true_text if masked and witnesses else ''})


def _memorable(fight: dict) -> bool:
    """A closed fight from_battle logs as a fight event (battle.memorable). Never raises."""
    try:
        from . import battle
        return bool(battle.memorable(fight))
    except Exception:
        return False


def _follower(p: dict) -> bool:
    """One of the player's followers, as the Hub's game side writes it in their file (an older World listed them as
    witnesses): they were with the player, not onlookers who spread it. Never raises."""
    try:
        from . import lw_state
        state = lw_state.load_npc(p.get('base')) if p.get('base') else None
        flag = (state or {}).get('follower')
        return isinstance(flag, int) and not isinstance(flag, bool) and flag > 0
    except Exception:
        return False


def from_death(store, base='', name='', day=None, place_name='', by_player=False, unique=False, witnesses=(), ref='',
               town='', hold='', event_id='') -> dict | None:
    """A death the game reports (World's crimes.json death rows: named people who died, not by the player's hand)."""
    name = _text(name, 80)
    if not name:
        return None
    at = f" at {place_name}" if place_name else ''
    place = {'location': _text(place_name, 120), 'town': _text(town, 80) or town_of_place(place_name),
             'hold': norm_hold(hold) or hold_of_place(place_name)}
    witnesses = [w for w in _people_list(witnesses) if not same(w, person(name, base, ref))]
    return log_event(store, 'death', f"{name} died{at}.", f"{name} has died{at}.", day, place, [person(name, base, ref)],
                     witnesses, event_id=_text(event_id, 80) or f"death-{base_key(base) or norm(name)}",
                     flags={'unique': bool(unique), 'by_player': bool(by_player), 'town': bool(place['town'])})


def _add_present(store, ref: str, people) -> bool:
    """Adds people (who were there) to the logged killing of this person, so they know it as seen. Never raises."""
    people = [p for p in _people_list(people) if p.get('key') != PLAYER and p.get('ref') != ref]
    if not ref or not people:
        return False

    def apply(log):
        changed = False
        for e in log['events']:
            if e.get('kind') != 'killing' or e.get('retracted') or not any(p.get('ref') == ref for p in e.get('involved') or []):
                continue
            for p in people:
                if not any(same(p, o) for o in e.setdefault('present', [])):
                    e['present'].append(p)
                    changed = True
        return changed
    try:
        change_log(store, apply)
        return True
    except Exception:
        return False


def _killing_logged(store, ref: str) -> bool:
    """A killing of this person is in the log already (from a fight or a murder row)."""
    if not ref:
        return False
    return any(e.get('kind') == 'killing' and not e.get('retracted')
               and any(p.get('ref') == ref for p in e.get('involved') or []) for e in events(store))


def _fight_of(fights, ref: str, day: float) -> dict | None:
    """The recorded fight (battles.json, open or closed) this person died in around this day, else None."""
    try:
        from . import battle
    except Exception:
        return None
    for fight in fights or []:
        if not isinstance(fight, dict):
            continue
        start, end = _float(fight.get('start')), _float(fight.get('end'))
        first, last = (start if start >= 0 else end), (end if end >= 0 else start)
        for f in battle.fighters(fight):
            if ref and ref_key(f.get('ref_id')) == ref and (day < 0 or first < 0 or first - 1 <= day <= max(first, last) + 1):
                return fight
    return None


def _fight_people(fight, but=None) -> list[dict]:
    """Everyone in a recorded fight who saw it (not the player, not summons, not this victim)."""
    try:
        from . import battle
    except Exception:
        return []
    out = []
    for f in battle.fighters(fight) if isinstance(fight, dict) else []:
        if f.get('role') in ('player', 'summon'):
            continue
        p = person(f['name'], f.get('base_id'), f['ref_id'])
        if but is not None and same(p, but):
            continue
        out.append(p)
    return out


def _talk_people(talk, day: float) -> list[dict]:
    """The people in the talk that was running when something happened at this game day: talk = {open, time, speakers}
    (the game's conversation file), else nobody."""
    if not isinstance(talk, dict) or not talk.get('open') or day < 0:
        return []
    started = _float(talk.get('time'))
    if started < 0 or started > day + 0.001:
        return []
    return [person(s.get('name'), s.get('base_id'), s.get('ref_id')) for s in talk.get('speakers') or []
            if isinstance(s, dict) and s.get('name')]


def from_crimes(store, player: str, data=None, fights=None, talk=None) -> int:
    """World's crimes.json ({player, crimes: [...], deaths: [...]}, shared by every save) into the log: only rows of
    this character (their player field, without case), each id once. A crime is logged at once, also while the fight
    it was part of is still going on (battles.json): its witnesses, the people in that fight and the people in the talk
    running when it happened (talk: {open, time, speakers}) are present. A murder replaces an attack on the same person
    that day; a killing already logged (from a closed fight, or this row before) is not logged twice (from_battle adds
    the fight's people to it when the fight closes). A death row is skipped only when a closed fight that is already in
    the log tells it. Returns how many events are new."""
    if store is None or not player:
        return 0
    if data is None:
        try:
            from . import lw_state
            data = lw_state._read('crimes.json')
        except Exception:
            data = {}
    if not isinstance(data, dict):
        return 0
    lowered = {str(k).lower(): v for k, v in data.items()}
    mine = lambda r: isinstance(r, dict) and r.get('id') and norm(r.get('player')) == norm(player)
    crimes = [r for r in (lowered.get('crimes') if isinstance(lowered.get('crimes'), list) else []) if mine(r)]
    deaths = [r for r in (lowered.get('deaths') if isinstance(lowered.get('deaths'), list) else []) if mine(r)]
    if fights is None:
        try:
            from . import lw_state
            fights = lw_state.load_battles()
        except Exception:
            fights = []
    victim_ref = lambda r: ref_key((r.get('victim') or {}).get('ref_id')) if isinstance(r.get('victim'), dict) else ''
    day_of = lambda r: int(max(0.0, _float(r.get('day'), 0.0)))
    murders = {(victim_ref(r), day_of(r)) for r in crimes if norm(r.get('crime')) == 'murder'}
    before = {e['id'] for e in events(store)}
    for row in crimes:
        crime, ref = norm(row.get('crime')), victim_ref(row)
        if crime == 'assault' and ref and (ref, day_of(row)) in murders:
            old = find(store, 'crime-' + _text(row['id'], 60))
            if old is not None:  # logged before the murder row came: the killing is the news now
                retract(store, old['id'], 'became a killing')
            continue
        if crime == 'murder' and not find(store, 'crime-' + _text(row['id'], 60)) and _killing_logged(store, ref):
            # a fight already logged this killing (closed, or still going on): its witnesses are there too
            _add_present(store, ref, [w for w in _people_list(row.get('witnesses')) if not _follower(w)])
            continue
        day = _float(row.get('day'))
        fight = _fight_of(fights, ref, day) if ref else None
        also = _talk_people(talk, day) + (_fight_people(fight) if fight else [])
        from_crime(store, row, player, also)
    for row in deaths:
        ref, day = ref_key(row.get('ref_id')), _float(row.get('day'))
        fight = _fight_of(fights, ref, day) if ref else None
        if fight is not None and not _int(fight.get('active')) and (find(store, 'fight-' + str(fight.get('id'))) or _memorable(fight)):
            continue  # died in a closed fight that is (or is about to be) in the log: the fight event tells it
        witnesses = list(row.get('witnesses') or []) + _talk_people(talk, day) + (_fight_people(fight) if fight else [])
        from_death(store, row.get('base'), row.get('name'), day, _text(row.get('place'), 120),
                   bool(row.get('by_player')), bool(row.get('unique')), witnesses, row.get('ref_id'),
                   row.get('town'), row.get('hold'), _text(row['id'], 60) if str(row['id']).startswith('death-') else 'death-' + _text(row['id'], 60))
    return len({e['id'] for e in events(store)} - before)


# --- reading other parts' files at talk start (no hook needed in them) -------------------------------------------------

_ingested: dict = {}  # (root, source) -> stamp of what was read last


def _once(store, source, stamp) -> bool:
    key = (getattr(store, 'root', ''), source)
    if stamp is not None and _ingested.get(key) == stamp:
        return False
    _ingested[key] = stamp
    return True


def _running_talk(speakers) -> dict:
    """{open, time, speakers}: the talk the game says is running now (conversation.json), for who was there."""
    try:
        from . import contracts, lw_state
        data = contracts.game_flat(lw_state._read('conversation.json'))
        if speakers is None:
            speakers = lw_state.load_conversation()
        return {'open': _int(data.get('talk_open')) == 1, 'time': _float(data.get('talk_time')),
                'speakers': [s for s in speakers or [] if isinstance(s, dict)]}
    except Exception:
        return {}


def ingest(store, player: str = '', speakers=None) -> int:
    """Reads what other parts already keep, once per change: marriages.json (Relationships), battles.json and crimes.json
    (World), the custom events journal and the Absolute Commands store (wipes; a command that is gone without a release record is
    logged as a private release). Returns how many events are new. Never raises."""
    if store is None:
        return 0
    before = len(events(store))
    try:
        from . import lw_state
        data_dir = getattr(lw_state, 'DATA_DIR', '')
        if _once(store, 'marriages', (_stamp(os.path.join(data_dir, 'marriages.json')), player)):
            from_marriages(store, player)
        # crimes first: World's murder row (its witnesses, the hood) is the killing; a fight that has it adds its people
        crimes_stamp = (_stamp(os.path.join(data_dir, 'crimes.json')), _stamp(os.path.join(data_dir, 'battles.json')), player)
        if _once(store, 'crimes', crimes_stamp):
            from_crimes(store, player, talk=_running_talk(speakers))
        if _once(store, 'battles', (_stamp(os.path.join(data_dir, 'battles.json')), player)):
            from_battles(store, None, player)
    except Exception as e:
        logger.warning(f"Living World: the world log could not read marriages, fights or crimes ({e})")
    try:
        path = os.path.join(store.root, 'custom_events.json')
        if _once(store, 'custom', _stamp(path)):
            from . import events as custom
            for row in custom.load(store):
                from_custom_event(store, row, speakers, player)
    except Exception as e:
        logger.warning(f"Living World: the world log could not read custom events ({e})")
    try:
        path = os.path.join(store.root, 'commands', 'commands.json')
        if _once(store, 'commands', _stamp(path)):
            from . import command
            records = command.load(store)['commands']
            ids = set()
            for record in records:
                ids.add(record['id'])
                if record.get('status') == 'active' and record.get('forget'):
                    from_command_wipe(store, record, player, record.get('forget_mode') or 'gap', speakers)
            state_path = _path(store, 'commands_seen.json')
            seen = _fresh(state_path, lambda: {'active': {}})
            gone = [r for rid, r in (seen.get('active') or {}).items() if rid not in ids and isinstance(r, dict)]
            for record in gone:
                if not find(store, 'release-' + record['id']):
                    from_command_release(store, record, 'unknown', player)
            seen['active'] = {r['id']: {k: r.get(k) for k in ('id', 'text', 'npcs', 'given', 'until', 'forget')}
                              for r in records if r.get('status') in ('checking', 'active')}
            _write(state_path, seen)
    except Exception as e:
        logger.warning(f"Living World: the world log could not read absolute commands ({e})")
    return max(0, len(events(store)) - before)
