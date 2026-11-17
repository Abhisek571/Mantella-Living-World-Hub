"""Facts history: each NPC's facts as a dated history, per save (<conversations>/<world>/living_world/facts_history.json).

The game is the truth for marriage, home, follower status and faction membership (GAME_OWNED): those lines are
derived from the live game values at the start of each talk and are read-only for the user. What the user types on
the Characters page (custom lines, and a value typed over a game-owned one) is what the NPC believes; it never changes
the game. Each line:

    fact       partner / home / follower / role / member_of / custom / enchanted / ...
    value      the text
    since      game day it began (GameDaysPassed; -1 unknown)
    cause      original (first seen) / game / user / event:<id> / command:<id>
    status     current / on_hold / ended
    visible    whether the NPC knows it (an invisible line is shown in the Hub only, never sent)
    owner      game / user
    displaced_by, displaced_link   the cause (and link) that put a line on hold; ended, why   when and why it ended

Original lines are never deleted. A line a new one replaces goes on hold; ending a cause (a released command, a custom
event taken back) ends every line that cause made and returns the lines it put on hold.

Relationships are links between two people, stored once, so both sheets agree: {kind, a, b, ...} with each side
{key, base, name} or the player. Several partners at once are allowed. Marriage to the player follows one rule:
M.A.R.A.S when it is present (maras_on in the npc file), else the vanilla player marriage; NFF's elope is its own kind.
An NPC's own spouse (the game's NPC-to-NPC spouse, from Relationships' ties.json) stays their spouse; when the NPC
marries the player, that link goes on hold ("whom she left to marry the player"), and comes back if the marriage
ends or the command that made it is released.

Only current, visible lines are sent to the model (background_lines)."""
import json
import logging
import os
import re
import threading
import time
import uuid

from . import action_filter, characters, contracts, lw_state, memory

logger = logging.getLogger('Mantella')

FILE = 'facts_history.json'
GAME_OWNED = characters.GAME_OWNED
GAME_FACTS = ('home', 'follower', 'role', 'member_of')  # game lines kept as lines (the partner is a link)
LABELS = {'partner': 'Partner', 'home': 'Home', 'follower': 'Follower', 'role': 'Role', 'member_of': 'Member of'}
PLAYER = 'player'
PLAYER_KINDS = ('married', 'engaged', 'eloped', 'dating', 'lover')
NPC_KINDS = ('spouse', 'courting')
MAX_ENDED = 60  # ended lines kept per NPC (current and on-hold lines are never dropped)
MAX_MISMATCHES = 100

_lock = threading.RLock()


# --- who -----------------------------------------------------------------------------------------------------------------

def short_ref(value) -> str:
    """A reference id cut the way Mantella keeps it (last 6 hex digits, a light plugin's FE id its last 3), as hex;
    '' when it is not one."""
    try:
        number = value if isinstance(value, int) and not isinstance(value, bool) else int(str(value).strip(), 16)
    except (TypeError, ValueError):
        return ''
    number %= 1 << 32
    return format(number & 0xFFF if number >> 24 == 0xFE else number & 0xFFFFFF, 'X')


def npc_key(name, ref_id='') -> str:
    return f"{memory.file_name(str(name or '')).lower()}|{short_ref(ref_id)}"


def _person(speaker: dict) -> dict:
    return {'key': npc_key(speaker.get('name'), speaker.get('ref_id')), 'base': contracts.base_key(speaker.get('base_id')),
            'name': str(speaker.get('name') or '').strip()}


def _ref_of(key) -> str:
    return str(key).rpartition('|')[2] if isinstance(key, str) and '|' in key else ''


def _is(side, person: dict) -> bool:
    """One person on a link: the individual (name|ref key) decides when both sides have a reference id, so generic NPCs
    sharing one base id (guards, templated NPCs) never share a partner; the base id only for a side without one (a
    ties.json side, an old link)."""
    if side == PLAYER or not isinstance(side, dict) or not isinstance(person, dict):
        return False
    mine, theirs = _ref_of(side.get('key')), _ref_of(person.get('key'))
    if mine and theirs:
        return mine == theirs
    if side.get('key') and side['key'] == person.get('key'):
        return True
    return bool(side.get('base')) and side['base'] == person.get('base')


# --- the file ------------------------------------------------------------------------------------------------------------

def path(store) -> str:
    return os.path.join(store.root, FILE)


def empty() -> dict:
    return {'version': 1, 'npcs': {}, 'links': [], 'mismatches': []}


def load(store) -> dict:
    """The whole file; empty on any problem (also without a store)."""
    if store is None:
        return empty()
    data = lw_state.read_store_json(path(store))  # a file that could not be read is then not saved over
    if not isinstance(data, dict):
        return empty()
    out = empty()
    if isinstance(data.get('npcs'), dict):
        for k, v in data['npcs'].items():
            if isinstance(k, str) and isinstance(v, dict):
                v['lines'] = [l for l in v.get('lines') or [] if isinstance(l, dict) and l.get('id') and l.get('fact')]
                out['npcs'][k] = v
    out['links'] = [l for l in data.get('links') or [] if isinstance(l, dict) and l.get('id') and l.get('kind')]
    out['mismatches'] = [m for m in data.get('mismatches') or [] if isinstance(m, dict)][-MAX_MISMATCHES:]
    return out


def save(store, data: dict) -> None:
    if store is None:
        return
    for entry in data['npcs'].values():  # ended lines are trimmed; nothing current or on hold ever is
        ended = [l for l in entry['lines'] if l.get('status') == 'ended']
        if len(ended) > MAX_ENDED:
            drop = {id(l) for l in ended[:len(ended) - MAX_ENDED]}
            entry['lines'] = [l for l in entry['lines'] if id(l) not in drop]
    data['mismatches'] = data['mismatches'][-MAX_MISMATCHES:]
    file = path(store)
    lw_state.guard_save(file)
    os.makedirs(os.path.dirname(file), exist_ok=True)
    temp = lw_state.temp_path(file)
    with open(temp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    lw_state.replace_file(temp, file)


def _new_id() -> str:
    return uuid.uuid4().hex[:10]


def _npc(data: dict, person: dict) -> dict:
    entry = data['npcs'].setdefault(person['key'], {'name': person['name'], 'base_id': person['base'], 'lines': [],
                                                     'migrated': False})
    if person['base'] and not entry.get('base_id'):
        entry['base_id'] = person['base']
    return entry


def _line(fact, value, since, cause, owner, visible=True, why='') -> dict:
    return {'id': _new_id(), 'fact': fact, 'value': value, 'since': since, 'cause': cause, 'status': 'current',
            'visible': bool(visible), 'owner': owner, 'why': why}


def _day(today) -> int:
    return today if isinstance(today, int) and not isinstance(today, bool) else -1


# --- the game's values ---------------------------------------------------------------------------------------------------

player_kind = characters.player_kind
kind_text = characters.kind_text


def game_values(npc: dict, player: str) -> dict:
    live = characters.live_values(npc or {}, player)
    live['home'] = home_text(npc or {})
    return {k: live.get(k, '') for k in GAME_FACTS}


HOLD_CITIES = ('Whiterun', 'Falkreath', 'Winterhold')  # holds named like their city: "Whiterun" alone means the city


def hold_place(hold: str) -> str:
    """A hold as a place in a sentence: "Whiterun Hold" (never bare "Whiterun", which is the city), "the Reach"."""
    hold = ' '.join(str(hold or '').split())
    if not hold or hold.lower().endswith(' hold'):
        return hold
    return f"{hold} Hold" if hold in HOLD_CITIES else characters.hold_text(hold)


def home_text(npc: dict) -> str:
    """The game's home line: "Hod and Gerdur's House, in Riverwood" with the town when it is known (the npc file's
    home_town, else the town the place belongs to), "..., in Whiterun Hold" when only the hold is known."""
    home = ' '.join(str(npc.get('home') or '').split())
    hold = ' '.join(str(npc.get('hold') or '').split())
    town = ' '.join(str(npc.get('home_town') or '').split())
    if not town and home:
        try:
            from . import worldlog
            town = worldlog.town_of_place(home)
        except Exception:
            town = ''
    if home:
        if town and town.lower() != home.lower():
            return home if town.lower() in home.lower() else f"{home}, in {town}"
        if town:
            return home
        return f"{home}, in {hold_place(hold)}" if hold and hold.lower() not in home.lower() else home
    return town or hold_place(hold)


def _same_home(old: str, new: str) -> bool:
    """The same home written two ways (the place before ", in ..."), or an older line that only named the hold
    ("Whiterun") now said better ("Riverwood", "Whiterun Hold")."""
    place = lambda v: str(v or '').split(', in ')[0].strip().lower()
    if bool(place(old)) and place(old) == place(new):
        return True
    try:
        from . import worldlog
        return bool(worldlog.norm_hold(old)) and ', in ' not in str(old)
    except Exception:
        return False


def _command_cause(commands, speaker: dict, day: float | None) -> str:
    """'command:<id>' of the command in force on this NPC at that game time (now when day is None), else ''."""
    ref = short_ref(speaker.get('ref_id'))
    name = str(speaker.get('name') or '').lower()
    for record in reversed(commands or []):
        if record.get('status') not in ('checking', 'active'):
            continue
        given = _float(record.get('given'))
        until = _float(record.get('until'))
        if day is not None and day >= 0 and (given > day + 0.01 or (until > 0 and day > until + 0.01)):
            continue
        for npc in record.get('npcs') or []:
            if (ref and short_ref(npc.get('ref_id')) == ref) or (not ref and str(npc.get('name', '')).lower() == name):
                return f"command:{record['id']}"
    return ''


def _float(value, default=-1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number == number and abs(number) < 1e9 else default


# --- keeping the history up to date (talk start) --------------------------------------------------------------------------

def _sync_lines(entry: dict, fact: str, wanted: list[str], owner: str, cause: str, day: int, changes: list) -> None:
    """The user's lines of one kind follow the Characters page: new ones begin today, removed ones end."""
    current = [l for l in entry['lines'] if l['fact'] == fact and l['owner'] == owner and l['status'] == 'current']
    for line in current:
        if line['value'] not in wanted:
            line.update(status='ended', ended=day, why='removed on the Characters page')
            changes.append({'fact': fact, 'old': line['value'], 'new': ''})
    have = {l['value'] for l in current}
    for value in wanted:
        if value not in have:
            entry['lines'].append(_line(fact, value, day, cause, owner))
            changes.append({'fact': fact, 'old': '', 'new': value})


def _set_game_line(entry: dict, fact: str, value: str, cause: str, day: int, visible: bool, changes: list) -> None:
    current = next((l for l in entry['lines'] if l['fact'] == fact and l['owner'] == 'game' and l['status'] == 'current'), None)
    if current is not None:
        current['visible'] = visible
        if current['value'] == value:
            return
        if fact == 'home' and _same_home(current['value'], value):
            current['value'] = value  # only the wording changed ("in Whiterun" -> "in Riverwood"): not a move
            return
        current.update(status='on_hold', displaced_by=cause, held=day)
    if value:
        back = next((l for l in entry['lines'] if l['fact'] == fact and l['owner'] == 'game' and l['status'] == 'on_hold'
                     and l['value'] == value and l.get('displaced_by') in ('game', 'original')), None)
        if back is not None:
            back.update(status='current', visible=visible)
            back.pop('displaced_by', None)
        else:
            entry['lines'].append(_line(fact, value, day, cause, 'game', visible))
    if current is not None or value:
        changes.append({'fact': fact, 'old': current['value'] if current is not None else '', 'new': value})


def _player_link(data: dict, person: dict):
    return next((l for l in data['links'] if l['status'] == 'current' and l['kind'] in PLAYER_KINDS
                 and ((l['b'] == PLAYER and _is(l['a'], person)) or (l['a'] == PLAYER and _is(l['b'], person)))), None)


def _end_link(data: dict, link: dict, day: int, why: str) -> None:
    link.update(status='ended', ended=day, why=why)
    for other in data['links']:  # what it put on hold comes back
        if other['status'] == 'on_hold' and other.get('displaced_link') == link['id']:
            other['status'] = 'current'
            other.pop('displaced_by', None)
            other.pop('displaced_link', None)


def _sync_partner(data: dict, person: dict, speaker: dict, player: str, day: int, first: bool, marriages, commands,
                  changes: list) -> None:
    kind = player_kind(speaker)
    link = _player_link(data, person)
    if link is not None and link['kind'] == kind:
        return
    if link is not None:
        _end_link(data, link, day, 'divorced or parted in the game' if not kind else f"now {kind}")
    if not kind:
        if link is not None:
            changes.append({'fact': 'partner', 'old': kind_text(link['kind'], player), 'new': ''})
        return
    cause = 'original' if first else 'game'
    if kind in ('married', 'engaged'):
        row = contracts.latest_marriage(person['base'], marriages) if person['base'] else None
        if row is not None and row['commanded'] and row['status'] in contracts.MARRIED:
            cause = _command_cause(commands, speaker, row['day']) or _command_cause(commands, speaker, None) or 'game'
    elif not first:
        cause = _command_cause(commands, speaker, None) or 'game'
    new = {'id': _new_id(), 'kind': kind, 'a': person, 'b': PLAYER, 'since': day, 'cause': cause, 'status': 'current',
           'visible': True}
    data['links'].append(new)
    changes.append({'fact': 'partner', 'old': kind_text(link['kind'], player) if link else '', 'new': kind_text(kind, player)})
    if kind in ('married', 'engaged', 'eloped'):
        for other in data['links']:  # their own spouse stays a fact of the game, on hold: "whom she left to marry ..."
            if other['status'] == 'current' and other['kind'] in NPC_KINDS and (_is(other['a'], person) or _is(other['b'], person)):
                other.update(status='on_hold', displaced_by=cause, displaced_link=new['id'], held=day)


def _sync_ties(data: dict, person: dict, ties: dict, day: int) -> None:
    if not person['base']:
        return
    married = _player_link(data, person)
    for tie in contracts.ties_of(person['base'], ties):
        if tie['kind'] not in NPC_KINDS:
            continue
        other = {'key': '', 'base': tie['base'], 'name': tie['name']}
        known = next((l for l in data['links'] if l['kind'] == tie['kind'] and PLAYER not in (l['a'], l['b'])
                      and ((_is(l['a'], person) and _same_side(l['b'], other)) or (_is(l['b'], person) and _same_side(l['a'], other)))), None)
        if known is not None:
            if not known['a'].get('key') and _is(known['a'], person):
                known['a']['key'] = person['key']
            if not known['b'].get('key') and _is(known['b'], person):
                known['b']['key'] = person['key']
            continue
        link = {'id': _new_id(), 'kind': tie['kind'], 'a': dict(person), 'b': other, 'since': -1, 'cause': 'original',
                'status': 'current', 'visible': True}
        if married is not None and married['kind'] in ('married', 'engaged', 'eloped'):
            link.update(status='on_hold', displaced_by=married['cause'], displaced_link=married['id'], held=day)
        data['links'].append(link)


def _same_side(side, other: dict) -> bool:
    if not isinstance(side, dict):
        return False
    if side.get('base') and other.get('base'):
        return side['base'] == other['base']
    return bool(side.get('name')) and side.get('name', '').lower() == other.get('name', '').lower()


def sync_one(data: dict, speaker: dict, player: str, entry: dict | None, today, marriages=None, ties=None,
             commands=None) -> list[dict]:
    """One NPC at the start of a talk: the first time in this save their Characters page lines are taken over
    (migration), then the user's lines follow the Characters page and the game's lines follow the live game values.
    Returns the changes [{fact, old, new}] (empty the first time: nothing changed, it was only written down)."""
    person = _person(speaker)
    if not person['name']:
        return []
    day = _day(today)
    record = _npc(data, person)
    first = not record.get('migrated')
    changes: list = []
    entry = entry or {}
    pinned = entry.get('pinned') or {}
    beliefs = {k: v for k, v in pinned.items() if k in LABELS and isinstance(v, str) and v.strip()}
    _sync_lines(record, 'custom', characters.custom_lines(entry.get('custom', '')), 'user', 'original' if first else 'user', day, changes)
    for k in LABELS:
        _sync_lines(record, k, [beliefs[k]] if k in beliefs else [], 'user', 'original' if first else 'user', day, changes)
    live = game_values(speaker, player)
    cause_now = 'original' if first else (_command_cause(commands, speaker, None) or 'game')
    for k in GAME_FACTS:
        _set_game_line(record, k, live[k], cause_now, day, visible=k not in beliefs, changes=changes)
    _sync_partner(data, person, speaker, player, day, first, marriages, commands, changes)
    _sync_ties(data, person, ties or {}, day)
    if first:
        record['migrated'] = True
        record['first_day'] = day
        return []
    return [c for c in changes if c['fact'] in GAME_OWNED or c['fact'] == 'role']


def sync_talk(store, speakers: list[dict], player: str, today, commands=None, data_path=None) -> dict:
    """Every NPC in the talk (sync_one), read and written once. Returns {npc key: changes}. Never raises."""
    try:
        if commands is None and store is not None:
            from . import command  # not at the top: command.py uses this module
            commands = command.load(store)['commands']
        marriages, ties = contracts.load_marriages(player=player or None), contracts.load_ties()
        out = {}
        with _lock:
            data = load(store)
            before = json.dumps(data, sort_keys=True)
            chars = characters.load(data_path)
            for s in speakers or []:
                if action_minor(s):
                    continue
                entry = characters.entry_for(str(s.get('name') or ''), s.get('race', ''), data=chars)
                changes = sync_one(data, s, player, entry, today, marriages, ties, commands)
                if changes:
                    out[_person(s)['key']] = changes
            if json.dumps(data, sort_keys=True) != before:
                save(store, data)
        return out
    except Exception as e:
        logger.warning(f"Living World: the facts history could not be updated ({e})")
        return {}


def action_minor(speaker: dict) -> bool:
    """A child, or not confirmed as an adult by the game yet (no npc file, a broken one, no minor key): left out."""
    return not action_filter.adult(speaker)


# --- causes: commands, custom events ---------------------------------------------------------------------------------------

def add_line(store, name: str, ref_id: str, fact: str, value: str, cause: str, today=None, visible: bool = True,
             owner: str = 'user', base_id: str = '') -> str:
    """A line made by a cause (a command, a custom event): current from today. Returns its id ('' on a failure)."""
    try:
        with _lock:
            data = load(store)
            record = _npc(data, {'key': npc_key(name, ref_id), 'base': contracts.base_key(base_id), 'name': name})
            line = _line(fact, ' '.join(str(value).split())[:300], _day(today), cause, owner, visible)
            record['lines'].append(line)
            save(store, data)
            return line['id']
    except Exception as e:
        logger.warning(f"Living World: could not add a fact line for {name} ({e})")
        return ''


def end_cause(store, cause: str, today=None, keys: list[str] | None = None) -> dict:
    """Ends every line and link this cause made and brings back what it put on hold; keys (npc keys) limits it to
    those NPCs. Returns {ended, returned}. Never raises."""
    result = {'ended': 0, 'returned': 0}
    if not cause:
        return result
    day = _day(today)
    try:
        with _lock:
            data = load(store)
            mine = lambda k: keys is None or k in keys
            for k, record in data['npcs'].items():
                if not mine(k):
                    continue
                for line in record['lines']:
                    if line.get('cause') == cause and line['status'] in ('current', 'on_hold'):
                        line.update(status='ended', ended=day, why='its cause ended')
                        result['ended'] += 1
                    elif line['status'] == 'on_hold' and line.get('displaced_by') == cause:
                        line['status'] = 'current'
                        line.pop('displaced_by', None)
                        result['returned'] += 1
            for link in data['links']:
                sides = [s.get('key') for s in (link['a'], link['b']) if isinstance(s, dict)]
                if keys is not None and not any(s in keys for s in sides):
                    continue
                if link.get('cause') == cause and link['status'] in ('current', 'on_hold'):
                    _end_link(data, link, day, 'its cause ended')
                    result['ended'] += 1
                elif link['status'] == 'on_hold' and link.get('displaced_by') == cause:
                    link['status'] = 'current'
                    link.pop('displaced_by', None)
                    link.pop('displaced_link', None)
                    result['returned'] += 1
            save(store, data)
    except Exception as e:
        logger.warning(f"Living World: could not end the fact lines of {cause} ({e})")
    return result


def set_visible(store, line_id: str, visible: bool) -> bool:
    """Whether the NPC knows a line (the page's switch). True when it changed."""
    with _lock:
        data = load(store)
        for record in data['npcs'].values():
            for line in record['lines']:
                if line['id'] == line_id:
                    if line.get('visible') == bool(visible):
                        return False
                    line['visible'] = bool(visible)
                    save(store, data)
                    return True
        for link in data['links']:
            if link['id'] == line_id:
                link['visible'] = bool(visible)
                save(store, data)
                return True
    return False


# --- the prompt ------------------------------------------------------------------------------------------------------------

def _pronouns(sex: str) -> tuple[str, str]:
    sex = str(sex or '').lower()
    return ('she', 'her') if sex == 'female' else (('he', 'him') if sex == 'male' else ('they', 'them'))


def _side_name(side, player: str) -> str:
    return player if side == PLAYER else (side.get('name') or 'someone')


def link_lines(data: dict, speaker: dict, player: str) -> list[str]:
    """The partner lines for this NPC's sheet: with the player and with other NPCs, from the same links both sheets
    read. An NPC's own spouse stays their spouse when one of them married the player: "whom X left to marry the
    player" on the sheet of the one who left, "who left her to marry the player" on the other; "former" only after a
    real divorce."""
    person = _person(speaker)
    _, her = _pronouns(speaker.get('sex'))
    out = []
    for link in data['links']:
        if not link.get('visible', True) or not (_is(link['a'], person) or _is(link['b'], person)):
            continue
        other = link['b'] if _is(link['a'], person) else link['a']
        if link['kind'] in PLAYER_KINDS:
            if link['status'] == 'current':
                out.append(f"- Partner: {kind_text(link['kind'], player)}")
            continue
        name = _side_name(other, player)
        if link['status'] == 'current':
            out.append(f"- {'Spouse' if link['kind'] == 'spouse' else 'Courting'}: {name}")
        elif link['status'] == 'on_hold' and link['kind'] == 'spouse':
            displaced = next((l for l in data['links'] if l['id'] == link.get('displaced_link')), None)
            left_by_other = displaced is not None and isinstance(other, dict) and (_is(displaced['a'], other) or _is(displaced['b'], other))
            if left_by_other:
                out.append(f"- Spouse: {name}, who left {her} to marry {player}")
            else:
                out.append(f"- Spouse: {name}, whom {speaker.get('name')} left to marry {player}")
        elif link['status'] == 'ended' and str(link.get('why', '')).startswith('divorce'):
            out.append(f"- Former {'spouse' if link['kind'] == 'spouse' else 'suitor'}: {name}")
    return out


def family_line(speaker: dict, ties: dict | None = None) -> str:
    base = contracts.base_key(speaker.get('base_id'))
    if not base:
        return ''
    names = [f"{t['name']} ({t['kind']})" for t in contracts.ties_of(base, ties) if t['kind'] in contracts.FAMILY and t['name']]
    return f"- Family: {', '.join(names)}" if names else ''


def background_lines(store, speaker: dict, player: str, entry: dict | None = None, world: dict | None = None,
                     values: str = '', data: dict | None = None, ties: dict | None = None) -> list[str]:
    """The Background lines of one NPC: race and sex, partners, home, follower, role, memberships, family, religion,
    values, feelings toward groups, the user's own lines. Only current, visible lines; a value the user typed over a
    game-owned one is what the NPC believes and takes its place."""
    data = load(store) if data is None else data
    entry = entry or {}
    speaker = speaker or {}
    person = _person(speaker)
    record = data['npcs'].get(person['key']) or {'lines': []}
    lines = []
    for k, label in characters.LOCKED:
        value = (entry.get('locked') or {}).get(k) or str(speaker.get(k) or '').strip()
        if value:
            lines.append(f"- {label}: {value.capitalize() if k == 'race' and value.isupper() else value}")
    beliefs = {l['fact']: l['value'] for l in record['lines'] if l['owner'] == 'user' and l['status'] == 'current'
               and l['fact'] in LABELS and l.get('visible', True)}
    if 'partner' in beliefs:
        lines.append(f"- Partner (as {speaker.get('name')} sees it): {beliefs['partner']}")
    elif record['lines'] or data['links']:
        lines += link_lines(data, speaker, player)
    else:  # nothing written down yet (no save folder): the live value
        kind = player_kind(speaker)
        if kind:
            lines.append(f"- Partner: {kind_text(kind, player)}")
    live = game_values(speaker, player)
    for k in GAME_FACTS:
        if k in beliefs:
            label = LABELS[k] if k == 'role' else f"{LABELS[k]} (as {speaker.get('name')} sees it)"
            lines.append(f"- {label}: {beliefs[k]}")
            continue
        game = next((l for l in record['lines'] if l['fact'] == k and l['owner'] == 'game' and l['status'] == 'current'), None)
        if game is not None:
            if game.get('visible', True) and game['value']:
                lines.append(f"- {LABELS[k]}: {game['value']}")
        elif live[k]:
            lines.append(f"- {LABELS[k]}: {live[k]}")
    family = family_line(speaker, ties)
    if family:
        lines.append(family)
    members = characters.live_members(speaker)
    religion = characters.religion_for(members, entry)
    if religion:
        lines.append(f"- Religion: {religion}")
    values = (entry.get('values') or values or '').strip()
    if values:
        lines.append(f"- Cares about and will not do: {values}")
    stances = characters.stances_for(entry, speaker, world)
    if stances:
        parts = []
        for stance in characters.STANCES:
            names = sorted(f for f, s in stances.items() if s == stance)
            if names:
                parts.append(f"{stance} {', '.join(names)}")
        lines.append(f"- Feelings toward groups: {'; '.join(parts)}")
    custom = [l['value'] for l in record['lines'] if l['fact'] == 'custom' and l['owner'] == 'user'
              and l['status'] == 'current' and l.get('visible', True)]
    if not record['lines']:
        custom = characters.custom_lines(entry.get('custom', ''))
    lines += [f"- {c}" for c in custom]
    lines += [f"- {l['value']}" for l in record['lines'] if l['owner'] != 'game' and l['fact'] not in LABELS
              and l['fact'] != 'custom' and l['status'] == 'current' and l.get('visible', True)]
    return lines


# --- for the NPC page ------------------------------------------------------------------------------------------------------

def history(store, name: str, ref_id: str) -> dict:
    """{lines: [...], links: [...]} of one NPC, every status, oldest first (for the page)."""
    data = load(store)
    key = npc_key(name, ref_id)
    record = data['npcs'].get(key) or {'lines': []}
    person = {'key': key, 'base': record.get('base_id', ''), 'name': name}
    links = [l for l in data['links'] if _is(l['a'], person) or _is(l['b'], person)]
    return {'lines': list(record['lines']), 'links': links}


# --- mismatches between beliefs and the game ---------------------------------------------------------------------------

BELIEF_WORDS = re.compile(r"\b(?:believes?|believed|thinks?|thought|convinced|illusions?|illusory|imagin\w*|dreams?|"
                          r"dreamt|dreamed|spell|enchant\w*|pretends?|seems?|appears?|as if|fooled|tricked)\b", re.I)


# A claim counts only when THIS NPC is its subject (their name, first name, or a pronoun that fits them; custom events,
# typed about anyone, only by name), within one sentence: "Carlotta married Vega's friend" says nothing about Ysolda.
_AUX = r"(?:(?:has|have|had|is|was|am|are|were|got|just|recently|now|already|finally|happily|newly|secretly|been|then|also)\s+)*"


def _subject(speaker: dict, pronouns: bool = True) -> str:
    """A regex for this NPC as the subject of a sentence ('' when there is nothing to match)."""
    name = ' '.join(str((speaker or {}).get('name') or '').split())
    words = [re.escape(name)] if name else []
    if name and ' ' in name:
        words.append(re.escape(name.split(' ')[0]))
    if pronouns:
        sex = str((speaker or {}).get('sex') or '').lower()
        words += ['I'] + (['she'] if sex == 'female' else ['he'] if sex == 'male' else ['she', 'he', 'they'])
    return r'(?i:' + '|'.join(words) + r')' if words else ''


def _sentences(text: str) -> list[str]:
    return [t for t in re.split(r'(?<=[.!?;])\s+|\s*[\n]+\s*', str(text or '')) if t.strip()]


def _claim(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, sentence, re.I) for sentence in _sentences(text) for p in patterns if p)


def _married_claim(text: str, player: str, speaker: dict | None = None, pronouns: bool = True) -> bool:
    """THIS NPC is married to (or engaged to, or wed) the player, in one sentence."""
    p = rf"(?:{re.escape(player)}|the player)" if player else r'the player'
    me = _subject(speaker or {}, pronouns)
    if not me:
        return False
    own = r'(?:her|his|my|their)' if pronouns else r'(?!)'
    return _claim(text, [
        rf"(?<![\w'])(?:{me})\s+{_AUX}(?:married|marries|marry|wed|weds|wedded)\s+(?:to\s+)?{p}\b",
        rf"(?<![\w'])(?:{me})\s+{_AUX}(?:married|wed|wedded|engaged|betrothed)\s+to\s+{p}\b",
        rf"(?<![\w'])(?:{me})\s+and\s+{p}\s+{_AUX}(?:married|wed|wedded|engaged)\b",
        rf"(?<![\w']){p}\s+and\s+(?:{me})\s+{_AUX}(?:married|wed|wedded|engaged)\b",
        rf"(?<![\w']){p}\s+{_AUX}(?:married|marries|wed|weds|wedded)\s+(?:{me if not pronouns else me + '|her|him|me'})\b",
        rf"(?<![\w'])(?:{me})\s+{_AUX}(?:the\s+)?{p}'s\s+(?:wife|husband|spouse|bride|groom)\b",
        rf"\b{own}\s+(?:husband|wife|spouse),?\s+{p}\b"])


def _unmarried_claim(text: str, player: str = '', speaker: dict | None = None, pronouns: bool = True) -> bool:
    """THIS NPC is not married (or no longer married to the player), in one sentence."""
    p = rf"(?:{re.escape(player)}|the player)" if player else r'the player'
    me = _subject(speaker or {}, pronouns)
    if not me:
        return False
    return _claim(text, [
        rf"(?<![\w'])(?:{me})\s+{_AUX}(?:not\s+|never\s+|no\s+longer\s+)+(?:been\s+)?married\b",
        rf"(?<![\w'])(?:{me})\s+{_AUX}(?:unmarried|single|divorced)\b",
        rf"(?<![\w'])(?:{me})\s+{_AUX}(?:has|have)\s+no\s+(?:husband|wife|spouse)\b",
        rf"(?<![\w'])(?:{me})\s+{_AUX}divorced\s+{p}\b",
        rf"(?<![\w'])(?:{me})\s+and\s+{p}\s+{_AUX}(?:divorced|no\s+longer\s+married|not\s+married)\b"])


_HOME = (r"(?<![\w'])(?:{me})(?:'s)?\s+{aux}(?:lives?|living|moved|moves|move|home\s+is)\s+(?:in|at|into|to)?\s*"
         r"((?:the )?[A-Z][\w']*(?:[ -](?:of |the )?[A-Z][\w']*)*)")
_MY_HOME = r"\b(?:my|her|his|their)\s+home\s+is\s+(?:in\s+|at\s+)?((?:the )?[A-Z][\w']*(?:[ -](?:of |the )?[A-Z][\w']*)*)"
_FOLLOW = (r"(?<![\w'])(?:{me})\s+{aux}(?:travels with|follows|travelling with|traveling with|following) {p}\b|"
           r"(?<![\w'])(?:{me})\s+{aux}(?:a |the |{p}'s )?follower\b")
_JOIN = r"(?<![\w'])(?:{me})\s+{aux}(?:joins?|joined|(?:becomes?|became)\s+(?:a\s+)?member\s+of|(?:a\s+)?member\s+of)\s+(?:the\s+)?([A-Z][\w' ]+)"


def _home_claim(text: str, speaker: dict, pronouns: bool = True):
    me = _subject(speaker, pronouns)
    if not me:
        return None
    patterns = [_HOME.replace('{me}', me).replace('{aux}', _AUX)] + ([_MY_HOME] if pronouns else [])
    for sentence in _sentences(text):
        for pattern in patterns:
            found = re.search(pattern, sentence)  # case kept: the place has capitals (the subject matches any case)
            if found:
                return found
    return None


def check_text(text: str, speaker: dict, player: str, data: dict | None = None, pronouns: bool = True) -> list[dict]:
    """What a text (the Now paragraph, a custom line, a custom event) says about THIS NPC against the game's own facts:
    [{fact, says, game}]. Marriage to the player, home, follower status and faction membership. Only sentences with
    this NPC as the subject count (pronouns=False: only their name, for text typed about anyone)."""
    text = ' '.join(str(text or '').split())
    if not text:
        return []
    out = []
    kind = player_kind(speaker)
    married = kind in ('married', 'engaged', 'eloped')
    says_married = _married_claim(text, player, speaker, pronouns)
    says_unmarried = _unmarried_claim(text, player, speaker, pronouns)
    if says_married and not married and not says_unmarried:
        out.append({'fact': 'partner', 'says': f"married to {player}", 'game': kind_text(kind, player) or 'not married'})
    elif says_unmarried and married:
        out.append({'fact': 'partner', 'says': 'not married', 'game': kind_text(kind, player)})
    live = game_values(speaker, player)
    found = _home_claim(text, speaker, pronouns)
    if found and live['home']:
        place = found.group(1).strip().lower()
        home = live['home'].lower()
        if place not in home and home.split(',')[0].strip() not in place:
            out.append({'fact': 'home', 'says': found.group(1).strip(), 'game': live['home']})
    me = _subject(speaker, pronouns)
    follow = _FOLLOW.replace('{me}', me).replace('{aux}', _AUX).replace('{p}', re.escape(player or 'the player')) if me else ''
    if follow and _claim(text, [follow]) and characters._int(speaker.get('follower')) <= 0 and 'follower' in speaker:
        out.append({'fact': 'follower', 'says': f"travels with {player}", 'game': 'not a follower'})
    join = _JOIN.replace('{me}', me).replace('{aux}', _AUX) if me else ''
    matches = [m for sentence in _sentences(text) for m in re.finditer(join, sentence)] if join else []
    for match in matches:
        group = next((f for f in characters.FACTIONS if match.group(1).lower().startswith(f.lower())), None)
        if group and group not in characters.live_members(speaker):
            out.append({'fact': 'member_of', 'says': f"member of the {group}", 'game': ', '.join(characters.live_members(speaker)) or 'no such membership'})
    return out


def event_claims(text: str, speaker: dict, player: str) -> list[dict]:
    """A custom event can never set a game-owned fact: what it claims against the game, unless it is plainly about
    a belief or an illusion (then the NPC may believe it, and nothing is recorded)."""
    if BELIEF_WORDS.search(str(text or '')):
        return []
    return check_text(text, speaker, player, pronouns=False)  # typed about anyone: only an NPC it names


def record_mismatches(store, name: str, ref_id: str, source: str, text: str, found: list[dict], today=None) -> int:
    """Notes mismatches for the page (once per source and fact). Returns how many were new."""
    if not found or store is None:
        return 0
    with _lock:
        data = load(store)
        key = npc_key(name, ref_id)
        known = {(m.get('key'), m.get('source'), m.get('fact')) for m in data['mismatches']}
        new = 0
        for m in found:
            if (key, source, m['fact']) in known:
                continue
            data['mismatches'].append({'key': key, 'name': name, 'source': source, 'text': str(text)[:300], 'fact': m['fact'],
                                       'says': m['says'], 'game': m['game'], 'day': _day(today), 'at': time.time()})
            new += 1
        if new:
            save(store, data)
        return new


def mismatches(store, speaker: dict, player: str, now_text: str = '', entry: dict | None = None) -> list[dict]:
    """Every place where what this NPC is told or believes differs from the game, for the page's red lines:
    [{where, text, fact, says, game}]. where: now / custom / belief / event (recorded from custom events)."""
    out = []
    for m in check_text(now_text, speaker, player):
        out.append(dict(m, where='now', text=now_text))
    data = load(store)
    key = _person(speaker)['key']
    record = data['npcs'].get(key) or {'lines': []}
    live = game_values(speaker, player)
    for line in record['lines']:
        if line['owner'] != 'user' or line['status'] != 'current':
            continue
        if line['fact'] == 'custom':
            out += [dict(m, where='custom', text=line['value']) for m in check_text(line['value'], speaker, player)]
        elif line['fact'] in GAME_OWNED:
            game = kind_text(player_kind(speaker), player) if line['fact'] == 'partner' else live.get(line['fact'], '')
            if ' '.join(line['value'].lower().split()) != ' '.join(game.lower().split()):
                out.append({'where': 'belief', 'text': line['value'], 'fact': line['fact'], 'says': line['value'], 'game': game or '(none)'})
    if store is not None and not record['lines'] and entry:  # not migrated yet: the page's own entry
        for k, v in (entry.get('pinned') or {}).items():
            if k in GAME_OWNED and isinstance(v, str) and v.strip():
                game = kind_text(player_kind(speaker), player) if k == 'partner' else live.get(k, '')
                if v.strip().lower() != game.lower():
                    out.append({'where': 'belief', 'text': v, 'fact': k, 'says': v, 'game': game or '(none)'})
    out += [dict(m, where='event') for m in data['mismatches'] if m.get('key') == key]
    return out
