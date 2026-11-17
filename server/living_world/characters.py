"""Facts, factions and flags for each NPC, set on the Characters page and kept in the user's Mantella folder
(data/Skyrim/living_world_characters.json, next to their override presets; never part of the mod).

Facts go to the model as each NPC's Background, after their bio (the per-save facts history, facts_history.py, keeps
them dated):
    locked   race and sex: read from the game the first time, then only changed by hand
    live     partner (married to / dating), home, follower, role, member of: read from the game every talk (the npc file
             MLW_Channel writes, with Relationships' M.A.R.A.S fields). Marriage, home, follower and membership belong
             to the game (GAME_OWNED): a value typed over one of them is what the NPC believes, it never changes the
             game, and the page shows it as a mismatch
    custom   free "key: value" lines the user types
    values   what they care about and will not do (when empty, a short one is written from the bio, per save)
    religion set by the user; a temple or priest faction the game reports wins
Stances (loves / likes / neutral / dislikes / hates) toward factions are filled in from the factions where the game makes
them clear (a Stormcloak hates the Legion and the Thalmor, a guard sides with whoever holds their hold, ordinary Nords
and village folk dislike the Thalmor); the user can change one and pin it.

Flags are obeyed, not just shown: Intimacy: always willing and Always close open the intimate and close gates;
Intimacy: never shuts the intimate gate whatever else says yes (absolute commands, the Intimacy setting); neither
ticked is Default (intimacy_choice). Ignores Absolute Commands keeps commands off them (command.py); Trades without
asking is kept for the trading feature (trades_without_asking). A child is never close or intimate: every child check
runs after these and wins. The game side reads the flags from npc_flags.json and the Intimacy setting from
intimacy_settings.json, both channel files next to the npc files."""
import json
import os
import threading

from . import action_filter, lw_state, settings
from .ui_overrides import user_folder

PATH = os.path.join(user_folder(), 'data', 'Skyrim', 'living_world_characters.json')
FLAGS_FILE = 'npc_flags.json'          # channel file the game reads (MLW_Channel.NpcFlag)
INTIMACY_FILE = 'intimacy_settings.json'  # channel file both sides write (MLW_Channel, MLW_MCM)

LOCKED = (('race', 'Race'), ('sex', 'Sex'))
LIVE = (('partner', 'Married to / dating'), ('home', 'Home'), ('follower', 'Follower'), ('role', 'Role'),
        ('member_of', 'Member of'))
GAME_OWNED = ('partner', 'home', 'follower', 'member_of')  # the game is the truth; typed text is only a belief
FLAGS = (
    ('bypass_intimacy', 'Intimacy: always willing',
     'Always willing with you, whatever the Intimacy setting says, like Always willing on the hotkey. Never for a child.'),
    ('always_close', 'Always close to the player', 'Counts as close (friend level) at all times. Never for a child.'),
    ('never_intimate', 'Intimacy: never',
     'Never offered anything intimate, whatever else says yes: lover, Always willing, the Intimacy setting, absolute commands.'),
    ('trades_without_asking', 'Trades without asking', 'Kept for trading: they trade with you without being talked into it.'),
    ('ignore_commands', 'Ignores Absolute Commands', 'Absolute commands never bind them, here and in the game.'),
)
FLAG_KEYS = tuple(k for k, _, _ in FLAGS)
STANCES = ('loves', 'likes', 'neutral', 'dislikes', 'hates')
# by index: the number in intimacy_settings.json and the MCM's global (0 Lovers only, 1 NPC decides; an old 2 is NPC
# decides too). NPC decides: every adult is offered the scene action and decides in the talk. Lovers only: the old
# Strict rule (a lover, dating or closer, an Arousal open group, Always willing).
INTIMACY_MODES = settings.INTIMACY_MODES
INTIMACY_LABELS = {'npc_decides': 'NPC decides', 'lovers_only': 'Lovers only'}

# the names MLW_Channel writes into an NPC's "factions" list (vanilla and DLC factions, by form id)
FACTIONS = ('Companions', 'The Circle', 'Thieves Guild', 'Dark Brotherhood', 'Stormcloaks', 'Imperial Legion',
            'College of Winterhold', 'Thalmor', 'Forsworn', 'Blades', 'Greybeards', 'Penitus Oculatus', 'Silver Hand',
            'Vigilants of Stendarr', 'Bards College', 'Temple of the Divines', 'Temple of Kynareth', 'Temple of Mara',
            'Temple of Dibella', 'Temple of Talos', 'Priests of Arkay', 'Dawnguard', 'Volkihar vampires', 'Morag Tong')
HOLDS = ('Whiterun', 'Haafingar', 'Eastmarch', 'Rift', 'Reach', 'Pale', 'Falkreath', 'Hjaalmarch', 'Winterhold')
# who holds each hold when the war starts; World's finale outcome hands every hold to the winner
START_SIDE = {'Eastmarch': 'Stormcloaks', 'Rift': 'Stormcloaks', 'Winterhold': 'Stormcloaks', 'Pale': 'Stormcloaks'}
FINALE = {'cw_finale_legion': 'Imperial Legion', 'cw_finale_stormcloak': 'Stormcloaks'}
# stances a member of the key faction clearly has; the strongest wins when two memberships disagree
RULES = {
    'Stormcloaks': {'Stormcloaks': 'loves', 'Imperial Legion': 'hates', 'Thalmor': 'hates'},
    'Imperial Legion': {'Imperial Legion': 'loves', 'Stormcloaks': 'hates'},
    'Temple of Talos': {'Thalmor': 'hates'},
    'Thalmor': {'Thalmor': 'loves', 'Stormcloaks': 'hates', 'Blades': 'hates', 'Temple of Talos': 'hates'},
    'Blades': {'Blades': 'loves', 'Thalmor': 'hates'},
    'Penitus Oculatus': {'Dark Brotherhood': 'hates'},
    'Dark Brotherhood': {'Penitus Oculatus': 'hates'},
    'Companions': {'Silver Hand': 'hates'},
    'The Circle': {'Silver Hand': 'hates'},
    'Silver Hand': {'Companions': 'hates', 'The Circle': 'hates'},
    'Dawnguard': {'Volkihar vampires': 'hates'},
    'Volkihar vampires': {'Dawnguard': 'hates', 'Vigilants of Stendarr': 'hates'},
    'Vigilants of Stendarr': {'Volkihar vampires': 'hates'},
}
STRENGTH = {'hates': 2, 'loves': 2, 'dislikes': 1, 'likes': 1, 'neutral': 0}
# a religion the game makes clear from a faction
RELIGIONS = {'Temple of the Divines': 'the Nine Divines', 'Temple of Kynareth': 'Kynareth', 'Temple of Mara': 'Mara',
             'Temple of Dibella': 'Dibella', 'Temple of Talos': 'Talos', 'Priests of Arkay': 'Arkay',
             'Vigilants of Stendarr': 'Stendarr'}
# never "ordinary folk" for the Thalmor default: on the Thalmor's or the Empire's side
THALMOR_SIDE = {'Thalmor', 'Imperial Legion', 'Penitus Oculatus'}
CITIES = ('whiterun', 'solitude', 'windhelm', 'riften', 'markarth')

_lock = threading.RLock()
_cache: dict = {'path': None, 'stamp': None, 'data': None}


# ---------------------------------------------------------------------------
# The file
# ---------------------------------------------------------------------------

def key(name, race='') -> str:
    return f"{(name or '').strip().lower()}|{(race or '').strip().lower()}"


def _empty() -> dict:
    return {'version': 1, 'npcs': {}}


def load(path=None) -> dict:
    """The whole file ({version, npcs: {name|race: entry}}); re-read when it changed on disk. Never raises. A file that
    exists but cannot be opened (a sync tool or an antivirus holding it) gives the last good read and is never cached
    or saved over (lw_state.read_store_json); a file that is not JSON is copied aside first, then starts empty."""
    path = path or PATH
    with _lock:
        try:
            stamp = os.path.getmtime(path)
        except OSError:
            return _empty()
        if _cache['path'] == path and _cache['stamp'] == stamp:
            return _cache['data']
        data = lw_state.read_store_json(path)
        if lw_state.read_failed(path):
            return _cache['data'] if _cache['path'] == path and _cache['data'] is not None else _empty()
        if not isinstance(data, dict) or not isinstance(data.get('npcs'), dict):
            data = _empty()
        data['npcs'] = {k: clean(v) for k, v in data['npcs'].items() if isinstance(k, str) and isinstance(v, dict)}
        _cache.update(path=path, stamp=stamp, data=data)
        return data


def _write(path, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = lw_state.temp_path(path)
    with open(temp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    lw_state.replace_file(temp, path)
    _cache['stamp'] = None


def _text(value, limit=300) -> str:
    return ' '.join(str(value).split())[:limit] if isinstance(value, (str, int, float)) and not isinstance(value, bool) else ''


def clean(entry) -> dict:
    """An entry with only known parts and plain values (a hand edit can leave anything there)."""
    entry = entry if isinstance(entry, dict) else {}
    locked = entry.get('locked') if isinstance(entry.get('locked'), dict) else {}
    pinned = entry.get('pinned') if isinstance(entry.get('pinned'), dict) else {}
    stances = entry.get('stances') if isinstance(entry.get('stances'), dict) else {}
    flags = entry.get('flags') if isinstance(entry.get('flags'), dict) else {}
    custom = entry.get('custom')
    return {
        'name': _text(entry.get('name'), 120), 'race': _text(entry.get('race'), 60),
        'locked': {k: _text(locked.get(k), 60) for k, _ in LOCKED if _text(locked.get(k), 60)},
        'pinned': {k: _text(pinned.get(k)) for k, _ in LIVE if k in pinned and isinstance(pinned.get(k), str)},
        'stances': {_text(f, 80): s for f, s in stances.items() if _text(f, 80) and s in STANCES},
        'custom': '\n'.join(l.strip() for l in custom.splitlines() if l.strip())[:2000] if isinstance(custom, str) else '',
        'flags': {k: True for k in FLAG_KEYS if flags.get(k) is True},
        **{k: _text(entry.get(k)) for k in ('values', 'religion') if _text(entry.get(k))},
    }


def is_empty(entry: dict) -> bool:
    e = clean(entry)
    return not (e['locked'] or e['pinned'] or e['stances'] or e['custom'] or e['flags'] or e.get('values') or e.get('religion'))


def save_entry(name, race, entry, path=None) -> bool:
    """Saves (or, when it holds nothing, removes) one NPC's entry and rewrites the game's flag file. True when written."""
    path = path or PATH
    name = (name or '').strip()
    if not name:
        return False
    with _lock:
        _cache['stamp'] = None  # read now: this thread's own read decides whether the file may be saved over
        data = json.loads(json.dumps(load(path)))  # a copy: the cache must not change before the write succeeds
        if lw_state.read_failed(path):
            return False  # the file could not be read: saving this copy over it would lose the other NPCs
        k = key(name, race)
        new = dict(clean(entry), name=name, race=(race or '').strip())
        if is_empty(new):
            if k not in data['npcs']:
                return False
            del data['npcs'][k]
        else:
            if data['npcs'].get(k) == new:
                return False
            data['npcs'][k] = new
        _write(path, data)
        write_game_flags(path)
        return True


def entry_for(name, race='', path=None, data=None) -> dict | None:
    """This NPC's entry: by name and race, else by name alone when only one entry has that name (the game and Mantella
    can spell a race differently: "IMPERIAL", "Imperial")."""
    data = data if data is not None else load(path)
    npcs = data.get('npcs') or {}
    found = npcs.get(key(name, race))
    if found is not None:
        return found
    low = (name or '').strip().lower()
    same = [e for k, e in npcs.items() if k.split('|', 1)[0] == low]
    if len(same) == 1:
        return same[0]
    race_low = (race or '').strip().lower()
    return next((e for e in same if e.get('race', '').lower() == race_low), None) if race_low else None


def _name_race(npc):
    get = (lambda k: npc.get(k)) if isinstance(npc, dict) else (lambda k: getattr(npc, k, None))
    return str(get('name') or ''), str(get('race') or '')


def flag(npc, flag_key, path=None) -> bool:
    """One flag of an NPC (a dict or a Mantella character, by name and race). Never raises."""
    try:
        name, race = _name_race(npc)
        entry = entry_for(name, race, path)
        return bool(entry and entry.get('flags', {}).get(flag_key))
    except Exception:
        return False


def trades_without_asking(npc, path=None) -> bool:
    """Trades without asking, for the trading feature: npc is a speaker dict, a Mantella character or a name."""
    return flag({'name': npc} if isinstance(npc, str) else npc, 'trades_without_asking', path)


def ignores_commands(npc, path=None) -> bool:
    return flag(npc, 'ignore_commands', path)


# ---------------------------------------------------------------------------
# Live values from the game
# ---------------------------------------------------------------------------

def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def hold_text(hold: str) -> str:
    return 'the ' + hold if hold in ('Reach', 'Pale', 'Rift') else hold


MODULE_FIELDS = (('maras', 'Relationships'), ('nff', 'Followers'))  # npc file fields an optional module writes


def without_removed(npc: dict, installed=None) -> dict:
    """npc without the fields of a Living World module that is no longer installed (maras*: Relationships, nff*:
    Followers): the npc file keeps them after that module is removed, and they would stay true forever. installed:
    the module names (ui_tab.installed_modules); not given and no action folder to read them from: unchanged."""
    if not isinstance(npc, dict):
        return {}
    if installed is None:
        from . import ui_tab
        if not os.path.isdir('data/actions'):
            return npc  # not running inside Mantella: nothing to tell
        installed = ui_tab.installed_modules()
    gone = [prefix for prefix, owner in MODULE_FIELDS if owner not in installed]
    if not gone:
        return npc
    return {k: v for k, v in npc.items() if not any(k == p or k.startswith(p + '_') for p in gone)}


def player_kind(npc: dict, installed=None) -> str:
    """How this NPC stands with the player, by one rule: M.A.R.A.S when it is present (maras_on or its fields in the
    npc file), else the vanilla player marriage (spouse: PlayerMarriedFaction). NFF's elope (nff_eloped) is its own
    kind; a vanilla lover rank is 'lover'. married / engaged / eloped / dating / lover, or ''. Fields of a module no
    longer installed are not read (without_removed)."""
    npc = without_removed(npc or {}, installed)
    status = str(npc.get('maras_status') or '').strip().lower()
    maras = _int(npc.get('maras'))
    if _int(npc.get('nff_eloped')) > 0 and status != 'married' and maras not in (3, 4):
        return 'eloped'
    if _int(npc.get('maras_on')) > 0 or status or maras:
        if status == 'married' or maras in (3, 4):
            return 'married'
        if status == 'engaged' or maras == 2:
            return 'engaged'
        if status == 'dating':
            return 'dating'
        if status == 'lover':
            return 'lover'
    elif _int(npc.get('spouse')) > 0:
        return 'married'
    if _int(npc.get('rank')) >= 4:
        return 'lover'
    return ''


def kind_text(kind: str, player: str) -> str:
    return {'married': f"married to {player}", 'engaged': f"engaged to {player}", 'eloped': f"eloped with {player}",
            'dating': f"dating {player}", 'lover': f"{player}'s lover"}.get(kind, '')


def live_partner(npc: dict, player: str) -> str:
    """Married to / engaged to / dating the player (player_kind), as text."""
    return kind_text(player_kind(npc or {}), player)


def live_home(npc: dict) -> str:
    """The game's home line as the facts history words it (the town, never the hold used as a town)."""
    from . import facts_history
    return facts_history.home_text(npc)


def live_follower(npc: dict, player: str, installed=None) -> str:
    """In the party: the Hub's follower value, or Followers' nff (in Nether's Follower Framework's party, which the
    game's own follower checks do not always see; not read once Followers is removed)."""
    npc = without_removed(npc or {}, installed)
    if 'follower' not in npc and 'nff' not in npc:
        return ''
    inside = _int(npc.get('follower')) > 0 or _int(npc.get('nff')) > 0
    return f"yes, travels with {player}" if inside else f"no, not travelling with {player}"


def live_role(npc: dict, player: str) -> str:
    if _int(npc.get('housecarl')) > 0:
        return f"housecarl to {player}"
    work = str(npc.get('work') or '').strip()
    hold = str(npc.get('hold') or '').strip()
    if work:
        return work
    if _int(npc.get('guard')) > 0:
        return f"guard of {hold_text(hold)}" if hold else 'guard'
    return ''


def live_members(npc: dict) -> list[str]:
    """The factions the game wrote, plus the hold's guards for a guard."""
    found = [f for f in npc.get('factions') or [] if isinstance(f, str) and f.strip()]
    hold = str(npc.get('hold') or '').strip()
    if _int(npc.get('guard')) > 0 and hold:
        found.append(f"Guards of {hold_text(hold)}")
    out = []
    for f in found:
        if f not in out:
            out.append(f)
    return out


def live_values(npc: dict, player: str) -> dict:
    npc = npc or {}
    return {'partner': live_partner(npc, player), 'home': live_home(npc), 'follower': live_follower(npc, player),
            'role': live_role(npc, player), 'member_of': ', '.join(live_members(npc))}


def hold_side(hold: str, world: dict | None) -> str:
    events = (world or {}).get('events') if isinstance((world or {}).get('events'), list) else []
    for event in events:
        if isinstance(event, dict) and event.get('id') in FINALE:
            return FINALE[event['id']]
    return START_SIDE.get(hold, 'Imperial Legion') if hold in HOLDS else ''


def auto_stances(members: list[str], npc: dict | None = None, world: dict | None = None) -> dict:
    """Stances the factions make clear: each member faction is liked, then RULES (the strongest feeling wins), then a
    guard's side in the war (whoever holds their hold, after World's finale the winner)."""
    out: dict[str, str] = {}

    def put(faction, stance):
        if STRENGTH[stance] >= STRENGTH.get(out.get(faction, 'neutral'), 0):
            out[faction] = stance
    for m in members:
        put(m, 'likes')
    for m in members:
        for faction, stance in RULES.get(m, {}).items():
            put(faction, stance)
    npc = npc or {}
    side = ''
    if _int(npc.get('guard')) > 0 and not ({'Stormcloaks', 'Imperial Legion'} & set(members)):
        side = hold_side(str(npc.get('hold') or ''), world)
        if side:
            put(side, 'likes')
            put('Imperial Legion' if side == 'Stormcloaks' else 'Stormcloaks', 'dislikes')
    if 'Thalmor' not in out and ordinary_folk(npc, members, side):
        out['Thalmor'] = 'dislikes'  # the Talos ban; any membership's own stance came first and wins
    return out


def ordinary_folk(npc: dict, members: list[str], side: str = '') -> bool:
    """An ordinary Nord, or village folk (a commoner with no faction, living outside the five cities), who is not on the
    Thalmor's or the Empire's side (no such membership, no guard of an Imperial hold, no Altmer)."""
    npc = npc or {}
    race = str(npc.get('race') or '').strip().lower()
    if not race or 'altmer' in race or 'high elf' in race or THALMOR_SIDE & set(members) or side == 'Imperial Legion':
        return False
    if 'nord' in race:
        return True
    home = f"{npc.get('home') or ''} {npc.get('location') or ''}".lower()
    return not members and _int(npc.get('guard')) <= 0 and bool(home.strip()) and not any(c in home for c in CITIES)


def religion_for(members: list[str], entry: dict | None = None) -> str:
    """Religion: from a temple or priest faction the game reports, else the one the user set."""
    found = [RELIGIONS[m] for m in members or [] if m in RELIGIONS]
    if found:
        return f"follows {' and '.join(dict.fromkeys(found))}"
    return ((entry or {}).get('religion') or '').strip()


def stances_for(entry: dict | None, npc: dict | None, world: dict | None = None, members: list[str] | None = None) -> dict:
    """The stances in use: the automatic ones, with the user's pinned ones on top."""
    if members is None:
        members = members_for(entry, npc)
    out = auto_stances(members, npc, world)
    out.update((entry or {}).get('stances') or {})
    return out


def members_for(entry: dict | None, npc: dict | None) -> list[str]:
    pinned = ((entry or {}).get('pinned') or {})
    if 'member_of' in pinned:
        return [m.strip() for m in pinned['member_of'].split(',') if m.strip()]
    return live_members(npc or {})


# ---------------------------------------------------------------------------
# The prompt
# ---------------------------------------------------------------------------

def custom_lines(text: str) -> list[str]:
    return [line.strip() for line in (text or '').splitlines() if line.strip()]


def fact_lines(npc: dict, entry: dict | None, player: str, world: dict | None = None) -> list[str]:
    """The fact lines of one NPC, locked first, then live (pinned ones as the user wrote them), stances and custom."""
    entry = entry or {}
    npc = npc or {}
    lines = []
    for k, label in LOCKED:
        value = (entry.get('locked') or {}).get(k) or (str(npc.get(k) or '').strip() if entry else '')
        if value:
            lines.append(f"- {label}: {value.capitalize() if k == 'race' and value.isupper() else value}")
    live = live_values(npc, player)
    pinned = entry.get('pinned') or {}
    labels = {'partner': 'Partner', 'home': 'Home', 'follower': 'Follower', 'role': 'Role', 'member_of': 'Member of'}
    for k, _ in LIVE:
        value = pinned[k] if k in pinned else live.get(k, '')
        if value:
            lines.append(f"- {labels[k]}: {value}")
    stances = stances_for(entry, npc, world)
    if stances:
        parts = []
        for stance in STANCES:
            names = sorted(f for f, s in stances.items() if s == stance)
            if names:
                parts.append(f"{stance} {', '.join(names)}")
        lines.append(f"- Feelings toward groups: {'; '.join(parts)}")
    lines += [f"- {line}" for line in custom_lines(entry.get('custom', ''))]
    return lines


def prompt_text(speakers: list[dict], player: str, world: dict | None = None, path=None) -> str:
    """The Facts block for the NPCs in the talk: each NPC with an entry on the Characters page, and anyone whose
    partner the game knows (a spouse is told so even without an entry)."""
    data = load(path)
    blocks = []
    for npc in speakers or []:
        name = str(npc.get('name') or '').strip()
        if not name:
            continue
        entry = entry_for(name, npc.get('race', ''), data=data)
        if entry is None:
            partner = live_partner(npc, player)
            lines = [f"- Partner: {partner}"] if partner else []
        else:
            lines = fact_lines(npc, entry, player, world)
        if lines:
            blocks.append(f"Facts about {name} (always true; never contradict them, whatever the bio, memories or "
                          f"anyone in the talk says):\n" + '\n'.join(lines))
    return '\n\n'.join(blocks)


def add_to_parts(ordered: dict, text: str) -> dict:
    """The Facts go above the bios: at the start of Mantella's background part (after its header), else of its text."""
    if not text:
        return ordered
    for k in ('background', 'mantella', 'overview'):
        part = ordered.get(k)
        if isinstance(part, str) and part.strip():
            head, sep, rest = part.partition('\n')
            if head.startswith('# ') and sep:
                ordered[k] = f"{head}\n{text}\n\n{rest.lstrip()}"
            else:
                ordered[k] = f"{text}\n\n{part}"
            return ordered
    return ordered


def remember_locked(speakers: list[dict], path=None) -> int:
    """Race and sex read from the game once, for NPCs with an entry that has none yet. Returns how many were filled."""
    filled = 0
    data = load(path)
    for npc in speakers or []:
        name = str(npc.get('name') or '').strip()
        entry = entry_for(name, npc.get('race', ''), data=data) if name else None
        if entry is None:
            continue
        locked = dict(entry.get('locked') or {})
        new = {k: str(npc.get(k)).strip() for k, _ in LOCKED if not locked.get(k) and str(npc.get(k) or '').strip()}
        if new:
            locked.update(new)
            if save_entry(entry.get('name') or name, entry.get('race', ''), dict(entry, locked=locked), path):
                filled += 1
                data = load(path)
    return filled


# ---------------------------------------------------------------------------
# The action gates
# ---------------------------------------------------------------------------

def intimacy_mode(values: dict | None = None) -> str:
    """The Intimacy setting in force: the channel file both sides write (the MCM writes it too), else the setting.
    Older values: 0 or Strict is Lovers only, 1, 2, Relaxed or Any adult is NPC decides."""
    number = (lw_state._read(INTIMACY_FILE).get('int') or {}).get('intimacy_check')
    if isinstance(number, int) and not isinstance(number, bool) and 0 <= number <= 2:
        return INTIMACY_MODES[min(number, 1)]
    mode = (values or {}).get('intimacy_check')
    mode = settings.OLD_INTIMACY.get(mode, mode)
    return mode if mode in INTIMACY_MODES else settings.DEFAULTS['intimacy_check']


def intimacy_choice(npc: dict, data=None, path=None) -> str:
    """This NPC's own Intimacy choice: 'never' (the Characters page flag), 'willing' (the flag, or Always willing on the
    game's hotkey: allow_intimacy in their file) or 'default'. Never wins when both are set."""
    entry = entry_for(str((npc or {}).get('name') or ''), (npc or {}).get('race', ''), path, data) or {}
    flags = entry.get('flags') or {}
    if flags.get('never_intimate'):
        return 'never'
    if flags.get('bypass_intimacy') or _int((npc or {}).get('allow_intimacy')) == 1:
        return 'willing'
    return 'default'


def write_intimacy_mode(mode: str) -> bool:
    """Tells the game the Intimacy setting (it keeps it in the MCM's global). False when unknown or not written."""
    if mode not in INTIMACY_MODES:
        return False
    try:
        lw_state.write_json(INTIMACY_FILE, {'int': {'intimacy_check': INTIMACY_MODES.index(mode)}})
        return True
    except OSError:
        return False


def for_actions(speakers: list[dict], mode: str = 'lovers_only', path=None) -> list[dict]:
    """The speakers as the action filter sees them before absolute commands: the Intimacy setting (NPC decides: every
    adult) and the Intimacy: always willing and Always close flags. Children, and speakers the game has not confirmed as
    adults yet (no npc file, a broken one, no minor key: action_filter.adult), are left as they are. Copies."""
    data = load(path)
    out = []
    for s in speakers or []:
        s = dict(s)
        if action_filter.adult(s):
            entry = entry_for(str(s.get('name') or ''), s.get('race', ''), data=data) or {}
            flags = entry.get('flags') or {}
            if flags.get('always_close'):
                s['close'] = max(1, _int(s.get('close')))
            if flags.get('bypass_intimacy') or mode == 'npc_decides':
                s['intimate'] = 1
        out.append(s)
    return out


def final_limits(speakers: list[dict], path=None) -> list[dict]:
    """What nothing overrides, applied last: Never intimate shuts the intimate gate (also under a command), and a child
    is never close or intimate, nor is anyone the game has not confirmed as an adult (action_filter.adult). Copies."""
    data = load(path)
    out = []
    for s in speakers or []:
        s = dict(s)
        if not action_filter.adult(s):
            s['close'], s['intimate'] = 0, 0
        elif ((entry_for(str(s.get('name') or ''), s.get('race', ''), data=data) or {}).get('flags') or {}).get('never_intimate'):
            s['intimate'] = 0
        out.append(s)
    return out


def write_game_flags(path=None) -> None:
    """The flags for the game side (MLW_Channel.NpcFlag): "<name>|<flag>" = 1 in lowercase, as JsonUtil looks keys
    up; by name, the way the game knows them. Rewritten only when they changed. Never raises."""
    try:
        values = {}
        with _lock:
            _cache['stamp'] = None  # read now, on this thread: a read that fails here is never written out
            npcs = load(path).get('npcs') or {}
            lw_state.guard_save(path or PATH)  # never rewrite the game's flags from a read that failed
        for entry in npcs.values():
            name = (entry.get('name') or '').strip().lower()
            for k in FLAG_KEYS:
                if name and (entry.get('flags') or {}).get(k):
                    values[f"{name}|{k}"] = 1
        current = lw_state._read(FLAGS_FILE, retry=False).get('int')
        if current != values and (values or current):
            lw_state.write_json(FLAGS_FILE, {'int': values})
    except Exception:
        pass


# ---------------------------------------------------------------------------
# The Characters page
# ---------------------------------------------------------------------------

def game_npc(name, race='', data_dir=None) -> dict:
    """The newest npc file the game wrote for this name (race first when several share it), flattened; {} if none."""
    folder = os.path.join(data_dir or lw_state.DATA_DIR, 'npc')
    low, race_low = (name or '').strip().lower(), (race or '').strip().lower()
    if not low:
        return {}
    found = []
    try:
        files = os.listdir(folder)
    except OSError:
        return {}
    for f in files:
        if not f.endswith('.json'):
            continue
        try:
            with open(os.path.join(folder, f), 'rb') as fh:
                data = lw_state._flatten(json.loads(lw_state.decode(fh.read())))
            stamp = os.path.getmtime(os.path.join(folder, f))
        except (OSError, ValueError, AttributeError):
            continue
        if str(data.get('name') or '').strip().lower() == low:
            data.setdefault('base_id', f[:-5].upper())  # as lw_state.load_npc: their ties are found by it
            found.append((str(data.get('race') or '').strip().lower() == race_low, stamp, data))
    if not found:
        return {}
    found.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return found[0][2]


def stance_rows(entry: dict | None, npc: dict | None, world: dict | None = None) -> list[list]:
    """[faction, stance, pinned] for the stance table: the automatic ones and the pinned ones."""
    entry = entry or {}
    auto = auto_stances(members_for(entry, npc), npc, world)
    pinned = entry.get('stances') or {}
    names = list(auto) + [f for f in pinned if f not in auto]
    return [[f, pinned.get(f, auto.get(f, 'neutral')), f in pinned] for f in names]


def pinned_stances(rows, auto: dict) -> dict:
    """The stances to keep from the table: a row ticked Pin, or one whose stance is not the automatic one (the user
    changed or added it). Rows with no faction or an unknown stance are dropped."""
    out = {}
    for row in rows or []:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        faction, stance = _text(row[0], 80), str(row[1] or '').strip().lower()
        pin = row[2] if len(row) > 2 else False
        pin = pin is True or str(pin).strip().lower() in ('true', '1', 'yes', 'x')
        if faction and stance in STANCES and (pin or auto.get(faction) != stance):
            out[faction] = stance
    return out


def editor_entry(locked: dict, live: dict, pins: dict, stance_table, custom: str, flags: dict, npc: dict | None = None,
                 world: dict | None = None) -> dict:
    """An entry from the page's fields: live values are kept only where Pin is ticked."""
    pinned = {k: _text(live.get(k)) for k, _ in LIVE if pins.get(k)}
    members = [m.strip() for m in pinned['member_of'].split(',') if m.strip()] if 'member_of' in pinned else live_members(npc or {})
    return clean({'locked': locked, 'pinned': pinned,
                  'stances': pinned_stances(stance_table, auto_stances(members, npc, world)),
                  'custom': custom or '', 'flags': {k: bool(flags.get(k)) for k in FLAG_KEYS}})
