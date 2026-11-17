"""Absolute commands: an order the player types with the Absolute Command hotkey (MCM, G by default) during a Mantella
conversation. It goes to every NPC in that conversation (never a child) and overrides everything else in their prompt:
rules, personality, relationship, memories and story limits. It stays with each NPC until it is released (their NPC
page, or the Living World hotkey's menu in game; release.py), or for a number of game hours (the command's own "for two
hours", else the Commands last setting).

A command that makes the NPC forget something hides the memories that fit it (memory.hide_matching): they are never
shown to the model or recalled, but nothing is deleted, and they come back when the command is removed or wears off.
With the summary model each hidden memory is rewritten without the forgotten part, one short request per memory, and
the rewrite is shown in its place (memory.add_rewrite); unhiding the original, on the NPC page or by removing the
command, hides the rewrite again. Without the model, or when nothing would be left, the whole memory is hidden.

While a command is in force for an NPC they count as close and intimate for the action filter (unlocked()), so what
the command asks for can happen, never for a child. That ends here as soon as the command is removed or wears off. The
game side keeps its own flag for its re-checks (MLW_CommandUntil on the NPC, set by MLW_Command.psc): it lasts the
Commands last setting, or one game day when that is 0, from the newest command, and ends only by time.
What to forget, how long it lasts and whether the NPC knows something was done to them is read from the command in one
short request to the summary model (the Check commands with the model setting), else from its words.

An NPC ticked "Ignores Absolute Commands" on the Characters page is never bound: new commands leave them out, and one
given before the tick no longer applies to them (prompt, actions, memories). The game side leaves them out too.

Giving, lifting and releasing a command each mark the NPC's Now paragraph due (bio_evolve: it is written while a
command is in force too, as the NPC believes things), and a command adds a line to the NPC's facts history (cause
command:<id>; known to them only when the command says so) that ends with it. A forget always writes the true record
(release.py); it leaves a gap the NPC notices (a line after their Now paragraph) only when the words wipe a whole period
or ask them to notice. One forgotten thing is clean: they simply do not remember it.
Releasing with a choice (remembers, forgets the period, keeps believing) is release.py; a command that wears off or is
removed here gives back what it hid and puts the Now paragraph back as it was before it.

Files: the game writes commands.json next to the other channel files (keys, texts, NPC ref ids, game time, player
name; MLW_Command.psc); the commands in force live per save character in
<conversations folder>/<world id>/living_world/commands/commands.json."""
import hashlib
import json
import logging
import os
import re
import threading

from . import action_filter, bio_evolve, characters, contracts, events, facts_history, lw_state, memory
from .memory_ui import mantella_ref

logger = logging.getLogger('Mantella')

GAME_FILE = 'commands.json'
STORE_DIR = 'commands'
STORE_FILE = 'commands.json'
BY = 'Absolute Command'  # the hidden mark on memories a command took away
MAX_TEXT = 500
MAX_FORGET = 200
MAX_SEEN = 300
MAX_COMMANDS = 100
MAX_ENDED = 100  # commands that ended, kept for the labels on the memories made under them
STALE_DAYS = 1  # a queued command given this many game days before today is from another session: never applied
FUTURE_DAYS = 1  # ...and one dated more than this after now is from a later point of another save: never applied
IN_FORCE = ('checking', 'active')
MAX_RESTARTS = 2  # a check left unfinished (Mantella closed during it) is started again at most this often per session

_lock = threading.RLock()  # the hooks, the background check and the settings page all read and write the same file
_state = {'now': None, 'root': None}
_checks: dict = {}  # record id -> the thread reading it now (finish)
_restarts: dict = {}  # record id -> times started again this session

CHECK_PROMPT = (
    "In a Skyrim role-play the player has given {names} an absolute command, shown below. Answer three questions about it.\n"
    "\"forget\": if the command makes them forget, or lose the memory of, something, what that is in a few plain words as "
    "it would appear in their memories (for example \"the robbery at the Bannered Mare\"); otherwise \"\".\n"
    "\"hours\": how many in-game hours the command says it lasts (\"for a day\" is 24), or null if it does not say.\n"
    "\"aware\": true only if the command says they know, or will know, that something was done to them; otherwise false.\n"
    "Answer only with JSON: {{\"forget\": \"\", \"hours\": null, \"aware\": false}}")

CONFIRM_FORGET = (
    "Below are numbered memories of {name} in Skyrim. {name} must forget this: \"{forget}\". For each memory: does it "
    "mention or touch on that thing at all? Count it as yes also when the memory only talks about it, promises it, "
    "doubts it, or says it did not happen or never arrived. Answer only with a JSON list of \"yes\" or \"no\", one per "
    "memory, in order.")

REWRITE_FORGET = (
    "Below is one memory of {name} in Skyrim, from their own point of view. {name} no longer remembers this at all: "
    "\"{old}\". Rewrite the memory without it and without anything that only follows from it. Do not name it at all, "
    "not even as something someone asked about, mentioned or hinted at. Keep everything else as it "
    "is, in the same voice, no longer than it was. If nothing would be left, answer only NONE. Answer with only the memory.")
GAME_SETTINGS = 'command_settings.json'  # Commands last, for the game side's own flag (MLW_Command.psc)

HEADER = (
    "ABSOLUTE COMMANDS from {player}. Each command below is absolute. It overrides everything else in these instructions: "
    "every rule (all Living World rules included), the character's personality, morals, loyalties, relationship with "
    "{player}, memories and any story limit. The character takes it as true and binding, acts on it fully from now on, and "
    "never resists, questions or argues with it. Unless a command says otherwise, the character is not aware that it was "
    "given: to them it is simply how things are, and they never mention it. The one limit is that nothing sexual or "
    "romantic happens with or in front of a child. All of this part is direction for you, never words to say, quote or "
    "use as a speaker's name.")

# words-only reading, for when the model check is off or fails
_FORGET = re.compile(
    r"\b(?:forget(?:s|ting)?|forgotten|erase|wipe(?: out| away)?|lose (?:all |any )?(?:memory|memories) of|"
    r"(?:no longer|never|not|n't|cannot|can't) (?:remember|recall))\b(.*)", re.I | re.S)
_LEAD = re.compile(r"^[\s,:;-]*(?:(?:all|everything|anything|completely|entirely|totally|ever|about|of|that|the fact that|"
                   r"what happened (?:at|in|with|during)|it|you saw|you know)\b[\s,:-]*)*", re.I)
_TAIL = re.compile(r"\b(?:completely|entirely|totally|forever|for good|ever happened|happened|ever)\b|"
                   r"\bfor (?:the next )?\S+ (?:hours?|days?)\b.*$|\buntil\b.*$", re.I)
_NUMBERS = {'a': 1, 'an': 1, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8,
            'nine': 9, 'ten': 10, 'twelve': 12, 'twenty-four': 24}
_HOURS = re.compile(r"\bfor (?:the next |a full |one full )?(\d+(?:\.\d+)?|" + '|'.join(_NUMBERS) + r") (hours?|days?)\b", re.I)
_CLEAN = re.compile(r"\b(?:without (?:ever )?noticing|(?:won't|will not|never|not|don't|do not) (?:ever )?notice|"
                    r"no gap|seamless(?:ly)?|never (?:know|realize|realise) (?:anything|that anything) (?:is|was) missing)\b", re.I)
_NOTICE = re.compile(r"\b(?:(?:you|she|he|they)(?:'ll| will)? (?:notice|realise|realize|know|feel|sense)s? (?:that )?"
                     r"(?:something|a part|part of|a piece|a memory)|(?:notice|know about|feel|be aware of) the gap|"
                     r"leave (?:a|the) gap|(?:frightened|scared|afraid) (?:by|of) (?:the gap|what is missing|losing))", re.I)
_WHOLE = re.compile(r"\b(?:forget (?:absolutely )?everything|all (?:of )?(?:your|her|his|their) memor(?:y|ies)|"
                    r"(?:your|her|his|their) (?:whole|entire) (?:life|past)|who (?:you are|i am))\b", re.I)
_AWARE = re.compile(r"\b(?:you(?:'ll| will)? (?:know|realize|realise|be aware|remember) (?:that )?(?:i|someone|something)"
                    r" (?:did|cast|made|changed|put|took)|you know (?:that )?i (?:did|cast|made)|aware that)\b", re.I)


def _float(value, default: float = -1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number == number and abs(number) < 1e9 else default


def note_time(mantella_days) -> None:
    """Mantella's game time (GameDaysPassed + 1, as its in-game events and summaries carry it), for durations."""
    days = _float(mantella_days, None)
    if days is not None and days > 0:
        _state['now'] = days - memory.MANTELLA_DAY


def current_time(today: int | None, queue: list[dict] = ()) -> float | None:
    """The game time now (GameDaysPassed): Mantella's clock while it fits today's day (the game side's, written with
    this conversation), else today's day; None if neither is known. Never the time of a queued command: one from
    another save or a later point of this one would make every timed command wear off at once. (queue is ignored; kept
    for old callers.)"""
    now = _state['now']
    if today is None:
        return now
    if now is None or not (today - 0.01 <= now < today + 1.01):  # another save's clock, or an earlier save was loaded
        return float(today)
    return now


def _new_save(mem_store) -> None:
    """Another save character (another world folder): the clock noted for the last one is not this one's."""
    root = getattr(mem_store, 'root', None)
    if root != _state['root']:
        if _state['root'] is not None:
            _state['now'] = None
        _state['root'] = root


# ---------------------------------------------------------------------------
# What the game wrote
# ---------------------------------------------------------------------------

def read_queue(data: dict | None = None) -> list[dict]:
    """[{key, text, refs, names, time, player}] from the game's commands.json (PapyrusUtil string lists), oldest first."""
    if data is None:
        data = lw_state._read(GAME_FILE)
    lists = contracts.game_lists(data)  # keys without case: Papyrus may store "key" as "Key"
    if not lists:
        return []
    get = lambda key: lists[key] if isinstance(lists.get(key), list) else []
    at = lambda values, i: str(values[i]) if i < len(values) and values[i] is not None else ''
    keys, texts, refs, names, times, players = (get(k) for k in ('key', 'text', 'refs', 'names', 'time', 'player'))
    out = []
    for i in range(len(keys)):
        key, text = at(keys, i).strip(), ' '.join(at(texts, i).split())[:MAX_TEXT]
        if not key or not text:
            contracts._rejected(f"an absolute command in {GAME_FILE} was not used (row {i + 1}: no "
                                f"{'key' if not key else 'text'})", ('command', key, text[:40]))
            continue
        out.append({'key': key, 'text': text, 'refs': [r.strip() for r in at(refs, i).split(',') if r.strip()],
                    'names': [n.strip() for n in at(names, i).split('|') if n.strip()],
                    'time': _float(at(times, i)), 'player': at(players, i).strip()})
    return out


def targets(entry: dict, people, speakers, ref_fn) -> list[dict]:
    """The NPCs a command was given to, as memory files know them: {name, ref_id} with Mantella's name and ref id where
    the conversation has them (people: [(name, ref id)] from Mantella), else the game's name. Children never."""
    out = []
    # a speaker the game has not confirmed as an adult (no npc file, a broken one, no minor key) counts as a child
    minor = {ref_fn(s.get('ref_id')) for s in speakers or [] if not action_filter.adult(s)}
    minor_names = {str(s.get('name', '')).lower() for s in speakers or [] if not action_filter.adult(s) and s.get('name')}
    for i, ref in enumerate(entry['refs']):
        short = ref_fn(ref)
        if short is None:
            continue
        game_name = entry['names'][i] if i < len(entry['names']) else ''
        if short in minor or game_name.lower() in minor_names:
            continue
        if _ignored({'name': game_name, 'ref_id': ref}, speakers, ref_fn):
            continue
        name, mref = next(((n, r) for n, r in people or [] if ref_fn(r) == short), (game_name, mantella_ref(ref)))
        if name and mref and not any(ref_fn(o['ref_id']) == short for o in out):
            out.append({'name': str(name), 'ref_id': str(mref)})
    return out


def _ignored(npc, speakers=None, ref_fn=None) -> bool:
    """Ticked "Ignores Absolute Commands" on the Characters page; looked up with the game's race when the speaker is
    known."""
    get = (lambda k: npc.get(k)) if isinstance(npc, dict) else (lambda k: getattr(npc, k, None))
    match = None
    if speakers and ref_fn:
        match = next((s for s in speakers if ref_fn(s.get('ref_id')) is not None and ref_fn(s.get('ref_id')) == ref_fn(get('ref_id'))), None)
    return characters.ignores_commands({'name': get('name') or (match or {}).get('name') or '', 'race': (match or {}).get('race') or get('race') or ''})


def _int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Reading the command: what to forget, how long, does the NPC know
# ---------------------------------------------------------------------------

def read_words(text: str) -> dict:
    """{forget, hours, aware} from the command's words alone."""
    forget = ''
    found = _FORGET.search(text)
    if found:
        rest = re.split(r'[.;!?\n]|,? but\b|,? and (?:you|then|now|from now)\b', found.group(1), maxsplit=1)[0]
        rest = _TAIL.sub('', _LEAD.sub('', rest))
        forget = ' '.join(rest.strip(' ,:-"\'').split())[:MAX_FORGET]
        if not re.search(r'\w', forget):
            forget = ''
    hours = None
    span = _HOURS.search(text)
    if span:
        count = span.group(1).lower()
        hours = _float(count, None) if count[0].isdigit() else float(_NUMBERS[count])
        if hours is not None and span.group(2).lower().startswith('day'):
            hours *= 24
    return {'forget': forget, 'hours': hours, 'aware': bool(_AWARE.search(text))}


def leaves_gap(text: str, today: int | None = None) -> bool:
    """A forget leaves a gap the NPC notices only when a whole period is wiped (a day range or "everything" in the
    words: whole_period) or the words ask them to notice; one forgotten thing is clean: they simply do not remember it.
    Words that say they never notice always mean clean."""
    text = str(text or '')
    if _CLEAN.search(text):
        return False
    return bool(_NOTICE.search(text)) or whole_period(text, today)


def whole_period(text: str, today: int | None = None) -> bool:
    """The command wipes a whole stretch of time ("the last three days", "between day 12 and 40", "today",
    "everything"), not one thing."""
    text = str(text or '')
    if _WHOLE.search(text):
        return True
    try:
        from . import news
        return news.parse_days(text, today if today is not None else lw_state.load_today()) is not None
    except Exception:
        return False


def parse_check(reply: str) -> dict | None:
    """The model's {forget, hours, aware}, or None when the reply is not that JSON."""
    found = re.search(r'\{.*\}', str(reply or ''), re.S)
    try:
        data = json.loads(found.group(0)) if found else None
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    forget = data.get('forget')
    hours = data.get('hours')
    hours = float(hours) if isinstance(hours, (int, float)) and not isinstance(hours, bool) and 0 <= hours < 100000 else None
    return {'forget': ' '.join(forget.split())[:MAX_FORGET] if isinstance(forget, str) else '',
            'hours': hours, 'aware': data.get('aware') is True}


def read_command(text: str, names: list[str], ask=None) -> tuple[dict, str]:
    """({forget, hours, aware}, how it was read: 'model' or 'words'). ask(prompt, text) -> reply is the summary model;
    without it, or when its answer is no use, the words decide."""
    if ask is not None:
        try:
            checked = parse_check(ask(CHECK_PROMPT.format(names=', '.join(names) or 'an NPC'), f"Command: {text}"))
        except Exception as e:
            logger.warning(f"Living World: could not check an absolute command with the model ({e}); its words are used")
            checked = None
        if checked is not None:
            return checked, 'model'
    return read_words(text), 'words'


# ---------------------------------------------------------------------------
# The commands in force, per save character
# ---------------------------------------------------------------------------

def store_path(mem_store) -> str:
    return os.path.join(mem_store.root, STORE_DIR, STORE_FILE)


def load(mem_store) -> dict:
    """{commands: [...], seen: [game keys already read]}; empty on any problem (a file that could not be read is then
    not saved over: lw_state.read_store_json)."""
    data = lw_state.read_store_json(store_path(mem_store))
    if not isinstance(data, dict):
        data = {}
    commands = [c for c in data.get('commands') or [] if isinstance(c, dict) and isinstance(c.get('id'), str)
                and isinstance(c.get('text'), str) and isinstance(c.get('npcs'), list)]
    for c in commands:
        c['npcs'] = [n for n in c['npcs'] if isinstance(n, dict) and n.get('name') and n.get('ref_id')]
        c['hidden'] = [h for h in c.get('hidden') or [] if isinstance(h, dict) and h.get('id') and h.get('name')]
    seen = [str(s) for s in data.get('seen') or [] if isinstance(s, (str, int))]
    ended = [e for e in data.get('ended') or [] if isinstance(e, dict) and isinstance(e.get('id'), str)]
    return {'commands': commands, 'seen': seen, 'ended': ended}


def save(mem_store, data: dict) -> None:
    path = store_path(mem_store)
    lw_state.guard_save(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = lw_state.temp_path(path)
    with open(temp, 'w', encoding='utf-8') as f:
        json.dump({'commands': data['commands'][-MAX_COMMANDS:], 'seen': data['seen'][-MAX_SEEN:],
                   'ended': data.get('ended', [])[-MAX_ENDED:]}, f, ensure_ascii=False, indent=1)
    lw_state.replace_file(temp, path)


def _record(entry: dict, npcs: list[dict], values: dict) -> dict:
    words = read_words(entry['text'])
    record = {'id': hashlib.sha1(entry['key'].encode('utf-8')).hexdigest()[:12], 'key': entry['key'], 'text': entry['text'],
              'given': entry['time'], 'npcs': npcs, 'forget': words['forget'], 'aware': words['aware'],
              'status': 'checking', 'announced': False, 'hidden': [], 'read_by': ''}
    _set_hours(record, words['hours'], values)
    return record


def _set_hours(record: dict, hours, values: dict) -> None:
    """Hours the command lasts: its own words, else the setting (0 = until removed); until is the game time it ends."""
    if hours is None:
        hours = max(0, _int(values.get('command_hours'), 0))
    record['hours'] = float(hours)
    record['until'] = record['given'] + hours / 24 if hours > 0 and record['given'] >= 0 else -1.0


def poll(mem_store, people, values: dict, ask, ref_fn, today: int | None, player: str = '', speakers=None,
         background: bool = True) -> list[dict]:
    """Reads new commands from the game, ends the ones that wore off, and starts reading each new one (finish(): the
    model check, then hiding what it makes the NPC forget). Returns the new records. Never raises."""
    try:
        _new_save(mem_store)
        queue = read_queue()
        with _lock:
            data = load(mem_store)
            seen = set(data['seen'])
            now = current_time(today)
            changed = expire(mem_store, data, now)
            added = []
            for entry in queue:
                if entry['key'] in seen:
                    continue
                seen.add(entry['key'])
                data['seen'].append(entry['key'])
                changed = True
                if player and entry['player'] and not contracts.same_name(entry['player'], player):
                    logger.log(23, f"Living World: an absolute command given by another character ({entry['player']}) is left for that save")
                    continue  # given by another save character
                if now is not None and entry['time'] > now + FUTURE_DAYS:
                    logger.log(23, f"Living World: an absolute command from a later point of another save was not used: {entry['text'][:60]}")
                    continue  # from a later point of another save: never applied here
                if today is not None and 0 <= entry['time'] < today - STALE_DAYS:
                    logger.log(23, f"Living World: an old absolute command that never reached Mantella was not used: {entry['text'][:60]}")
                    continue  # from an earlier session that never reached this side
                npcs = targets(entry, people, speakers, ref_fn)
                if not npcs:
                    logger.log(23, f"Living World: an absolute command binds nobody here (a child, someone who ignores "
                                   f"commands, or no one in this talk): {entry['text'][:60]}")
                if npcs:
                    record = _record(entry, npcs, values)
                    record['bio_before'] = _bio_snapshot(mem_store, npcs)
                    data['commands'].append(record)
                    added.append(record)
            if changed:
                save(mem_store, data)
            # a check that never finished (Mantella was closed during it) is started again
            stuck = [c for c in data['commands'] if c.get('status') == 'checking' and c not in added
                     and not _alive(_checks.get(c['id'])) and _restarts.get(c['id'], 0) < MAX_RESTARTS]
            for record in stuck:
                _restarts[record['id']] = _restarts.get(record['id'], 0) + 1
    except Exception as e:
        logger.warning(f"Living World: could not read absolute commands ({e})")
        return []
    for record in added:
        logger.log(23, f"Living World: absolute command for {', '.join(n['name'] for n in record['npcs'])}: {record['text']}")
        _began(mem_store, record, player or 'the player', today)
    for record in stuck:
        logger.log(23, f"Living World: reading an absolute command again, its check never finished ({record['text'][:60]})")
    for record in added + stuck:
        if background:
            thread = threading.Thread(target=finish, args=(mem_store, record['id'], values, ask), daemon=True)
            _checks[record['id']] = thread
            thread.start()
        else:
            finish(mem_store, record['id'], values, ask)
    return added


def _began(mem_store, record: dict, player: str, today) -> None:
    """A new command: a facts line for each NPC (known to them only when the command says so) and their Now paragraph
    is due. Never raises."""
    for npc in record['npcs']:
        try:
            day = int(record['given']) if record['given'] >= 0 else -1
            facts_history.add_line(mem_store, npc['name'], npc['ref_id'], 'enchanted',
                                   f"under {player}'s absolute command since day {day}" if day >= 0 else f"under {player}'s absolute command",
                                   f"command:{record['id']}", today, visible=bool(record.get('aware')), owner='command')
            bio_evolve.mark_due(mem_store, npc['name'], npc['ref_id'], f"an absolute command was given to them: \"{record['text'][:200]}\"")
        except Exception as e:
            logger.warning(f"Living World: could not note a new command for {npc.get('name')} ({e})")


def _ended(mem_store, record: dict, why: str, today=None, data: dict | None = None) -> None:
    """A command wore off or was removed: its facts lines end, what they put on hold comes back, the Now paragraph is
    due, and it is kept in 'ended' (data, when given, is saved by the caller). Never raises."""
    try:
        facts_history.end_cause(mem_store, f"command:{record['id']}", today)
        for npc in record['npcs']:
            bio_evolve.mark_due(mem_store, npc['name'], npc['ref_id'], f"the absolute command \"{record['text'][:120]}\" {why}")
        if data is not None:
            add_ended(data, record, record['npcs'], why, today)
    except Exception as e:
        logger.warning(f"Living World: could not end a command's facts ({e})")


def add_ended(data: dict, record: dict, npcs: list[dict], choice: str, today=None) -> None:
    """Keeps an ended command (or its part for some NPCs) with how it ended: release choice, 'wore off' or 'removed'."""
    data.setdefault('ended', []).append({'id': record['id'], 'text': record['text'], 'given': record.get('given'),
                                         'npcs': [dict(n) for n in npcs], 'choice': choice,
                                         'day': today if isinstance(today, int) else -1})
    data['ended'] = data['ended'][-MAX_ENDED:]


def memory_labels(mem_store, player: str) -> dict:
    """{command id: label} for memories made under a command, for the Now writer: in force, released as a spell the NPC
    knows of, or kept believing ('' = no label)."""
    data = load(mem_store) if mem_store is not None else {'commands': [], 'ended': []}
    out = {}
    for e in data.get('ended', []):
        out[e['id']] = {'spell': f"while under {player}'s spell", 'believe': ''}.get(e.get('choice'), 'while under an absolute command')
    for record in data['commands']:
        out[record['id']] = f"while under an absolute command from {player}"
    return out


def _alive(thread) -> bool:
    is_alive = getattr(thread, 'is_alive', None)
    return bool(callable(is_alive) and is_alive())


def _bio_snapshot(mem_store, npcs: list[dict]) -> list[dict]:
    """Each NPC's 'how they have changed' note as the command found it, so it can be put back when the command ends:
    nothing the NPC did under the command becomes part of who they are."""
    out = []
    for npc in npcs:
        try:
            state = bio_evolve.load(mem_store, npc['name'], npc['ref_id'])
        except Exception:
            continue
        out.append({'name': npc['name'], 'ref_id': npc['ref_id'], 'text': state['text'], 'version': state['version'],
                    'after': state['after'], 'day': state['day'], 'talks': state['talks']})
    return out


def _bio_back(mem_store, record: dict) -> None:
    """The command is over: each NPC's note written while it was in force goes back to what it was (bio_evolve)."""
    for snap in record.get('bio_before') or []:
        if isinstance(snap, dict) and snap.get('name') and snap.get('ref_id'):
            try:
                bio_evolve.restore(mem_store, snap['name'], snap['ref_id'], snap)
            except Exception as e:
                logger.warning(f"Living World: could not put back how {snap['name']} has changed ({e})")


def active_for(mem_store, character, ref_fn, now: float | None = None) -> str:
    """The id of a command in force for this Mantella character (not worn off by now), else ''. Children never."""
    if mem_store is None:
        return ''
    with _lock:
        for record in load(mem_store)['commands']:
            if record.get('status') not in IN_FORCE or (now is not None and 0 < _float(record.get('until')) <= now):
                continue
            if any(_same(n, character, ref_fn) for n in record['npcs']) and not _ignored(character):
                return record['id']
    return ''


def finish(mem_store, record_id: str, values: dict, ask) -> None:
    """Reads a new command (model or words) and hides what it makes each NPC forget. Never raises."""
    try:
        with _lock:
            record = next((c for c in load(mem_store)['commands'] if c['id'] == record_id), None)
        if record is None or record.get('status') != 'checking':
            return
        use = ask if values.get('command_model_check', True) else None
        read, how = read_command(record['text'], [n['name'] for n in record['npcs']], use)
        hidden = _hide(mem_store, record, read['forget'], values, ask=use)
        with _lock:
            data = load(mem_store)
            current = next((c for c in data['commands'] if c['id'] == record_id), None)
            if current is None:  # removed while it was being read: give back what was just hidden
                for h in hidden:
                    memory.unhide(mem_store, h['name'], h['ref_id'], h['id'])
                return
            current.update(forget=read['forget'], aware=read['aware'], status='active', read_by=how,
                           forget_mode='gap' if leaves_gap(record['text'], _day_of(record)) else 'clean')  # the world log reads it
            _set_hours(current, read['hours'], values)
            current['hidden'] = current['hidden'] + hidden
            save(mem_store, data)
        _bio_forgot(mem_store, hidden)
        _note_forgets(mem_store, record, hidden, read['forget'])
        _scope(mem_store, record_id, dict(record, forget=read['forget']))
    except Exception as e:
        logger.warning(f"Living World: could not finish an absolute command ({e})")


def _scope(mem_store, record_id: str, record: dict) -> None:
    """"and everyone in Riverwood", "everyone who was there", "her brother": the world log's events (or the days) the
    command names are wiped from that scope too, absent NPCs included (news.apply_command_scope). Words that name no
    scope wipe them for the commanded NPCs only, so they stop passing on what they forgot. The wipes are kept on the
    record, so removing the command or letting it wear off gives them back. Never raises."""
    if not record.get('forget'):
        return  # an order to do or feel something: obeying still needs them present, nothing is wiped
    try:
        from . import news
        out = news.apply_command_scope(mem_store, record, lw_state.load_player_name(), lw_state.load_conversation(),
                                       current_time(lw_state.load_today()), fallback='npc')
        if not out or not out.get('wipes'):
            return
        with _lock:
            data = load(mem_store)
            current = next((c for c in data['commands'] if c['id'] == record_id), None)
            if current is None:  # removed meanwhile: give the wipes back at once
                for w in out['wipes']:
                    news.undo_wipe(mem_store, w)
                return
            current['scope_wipes'] = list(current.get('scope_wipes') or []) + list(out['wipes'])
            save(mem_store, data)
        logger.log(23, f"Living World: the command's words reach further ({out['scope']}): "
                       f"{out['hidden']} memories hidden for {', '.join(out['targets'][:8]) or 'nobody yet'}")
    except Exception as e:
        logger.warning(f"Living World: the command's scope could not be applied ({e})")


def undo_scope(mem_store, record: dict) -> int:
    """Gives back what the command's scope wiped from the world log (news.undo_wipe). Returns memories given back."""
    wipes = record.get('scope_wipes') or []
    if not wipes:
        return 0
    try:
        from . import news
        return sum(news.undo_wipe(mem_store, w) for w in wipes if isinstance(w, str))
    except Exception as e:
        logger.warning(f"Living World: the command's scope could not be given back ({e})")
        return 0


def _note_forgets(mem_store, record: dict, hidden: list[dict], what: str, once: bool = False) -> None:
    """Each NPC's forget goes into the true record, with a gap after their Now paragraph unless the command says they
    never notice (release.note_forget). once: only for an NPC this command has no forget line for yet (what a later
    talk said about the forgotten thing; the command came before anything was there to hide). Never raises."""
    try:
        from . import release
        day = _day_of(record)
        gap = 'gap' if leaves_gap(record['text'], day) else 'clean'
        period = whole_period(record['text'], day)
        speakers = lw_state.load_conversation()  # the sex the game sends, for the gap line's pronoun
        for npc in record['npcs']:
            mine = [h for h in hidden if h['name'] == npc['name'] and h['ref_id'] == npc['ref_id']]
            if once and any(r.get('kind') == 'forget' and r.get('command_id') == record['id']
                            for r in release.record_rows(mem_store, npc['name'], npc['ref_id'])):
                continue
            release.note_forget(mem_store, npc['name'], npc['ref_id'], mine, what, 'Absolute Command', gap, period=period,
                                speakers=speakers, command_id=record['id'])
    except Exception as e:
        logger.warning(f"Living World: could not note what a command made them forget ({e})")


def _day_of(record: dict) -> int | None:
    """The game day the command was given (for "today" and "the last three days" in its words), None when unknown."""
    given = _float(record.get('given'))
    return int(given) if given >= 0 else None


def _bio_forgot(mem_store, hidden: list[dict]) -> None:
    """Memories a command took away may already be in an NPC's 'how they have changed' note: it goes back to a text
    from before the oldest of them, and is written again from what they still remember."""
    oldest = {}
    for h in hidden:
        key = (h['name'], h['ref_id'])
        day = memory._int(h.get('day'))
        if day >= 0 and (key not in oldest or day < oldest[key]):
            oldest[key] = day
    for (name, ref_id), day in oldest.items():
        try:
            bio_evolve.roll_back(mem_store, name, ref_id, day)
        except Exception as e:
            logger.warning(f"Living World: could not put back how {name} has changed ({e})")


def _hide(mem_store, record: dict, forget: str, values: dict, npcs=None, ask=None, only=None) -> list[dict]:
    """Hides what the command makes each NPC forget; with ask (the summary model) each hidden memory gets a rewrite
    without the forgotten part in its place ('added': its id). The command's own rewrites are never picked again.
    only: {(name, ref id): memory ids} to choose from (the talk just saved), else every memory they have."""
    if not forget:
        return []
    strip = [n['name'] for n in record['npcs']] + [lw_state.load_player_name() or '', 'the player', 'Dragonborn']
    limit = max(1, _int(values.get('command_forget_limit'), 3))
    day = int(record['given']) + memory.MANTELLA_DAY if record['given'] >= 0 else -1
    own = {h['added'] for h in record.get('hidden') or [] if h.get('added')}
    hidden = []
    for npc in npcs if npcs is not None else record['npcs']:
        allowed = None if only is None else only.get((npc['name'], npc['ref_id']))
        if only is not None and not allowed:
            continue
        for row in memory.hide_matching(mem_store, npc['name'], npc['ref_id'], forget, limit=limit, by=BY,
                                        note=record['text'], day=day, skip=own, strip=strip, only=allowed,
                                        confirm=_confirmer(ask, npc['name'], forget)):
            item = {'name': npc['name'], 'ref_id': npc['ref_id'], 'id': row['id'], 'day': row.get('day', -1),
                    'hour': row.get('hour', -1), 'text': row.get('text', '')}
            rewrite = _rewrite(ask, npc['name'], row.get('text', ''), forget)
            added = memory.add_rewrite(mem_store, npc['name'], npc['ref_id'], row['id'], rewrite) if rewrite else ''
            if added:
                item['added'] = added
            hidden.append(item)
    return hidden


def _confirmer(ask, name: str, forget: str):
    """confirm(texts) -> [True/False per text] for memory.hide_matching: one short summary-model request asking which
    of the looser matches really hold the forgotten thing; None without the model. A reply that is not such a list
    confirms nothing."""
    if ask is None:
        return None

    def confirm(texts):
        listing = '\n'.join(f"{i + 1}. {' '.join(str(t).split())}" for i, t in enumerate(texts))
        return parse_confirm(ask(CONFIRM_FORGET.format(name=name, forget=forget), listing), len(texts))
    return confirm


def parse_confirm(reply, count: int) -> list[bool] | None:
    """["yes", "no", ...] (or true/false) from the model, as one bool per memory; None when it is not that list."""
    found = re.search(r'\[.*\]', str(reply or ''), re.S)
    try:
        data = json.loads(found.group(0)) if found else None
    except ValueError:
        return None
    if not isinstance(data, list) or len(data) != count:
        return None
    return [item is True or (isinstance(item, str) and item.strip().lower().startswith('yes')) for item in data]


def _rewrite(ask, name: str, text: str, forget: str) -> str:
    """The memory without the forgotten part, by the summary model; '' without the model, on a failure, or when
    nothing would be left (the whole memory stays hidden then)."""
    if ask is None or not text:
        return ''
    reply = events._rewritten(ask, name, text, forget, None, prompt=REWRITE_FORGET)
    if re.fullmatch(r'\W*none\W*', reply, re.I):
        return ''
    return reply


def _give_back(mem_store, record: dict) -> int:
    back = sum(1 for h in record['hidden'] if memory.unhide(mem_store, h['name'], h['ref_id'], h['id']))
    return back + undo_scope(mem_store, record)


def expire(mem_store, data: dict, now: float | None) -> bool:
    """Drops commands whose hours are over and gives back what they hid. True when something changed."""
    if now is None:
        return False
    ended = [c for c in data['commands'] if _float(c.get('until')) > 0 and now >= _float(c.get('until'))]
    for record in ended:
        _give_back(mem_store, record)
        _bio_back(mem_store, record)
        _ended(mem_store, record, 'wore off', int(now), data)
        data['commands'].remove(record)
        logger.log(23, f"Living World: an absolute command wore off ({record['text'][:60]})")
    return bool(ended)


def remove(mem_store, record_id: str) -> int | None:
    """Removes one command and gives back every memory it hid. The number given back, or None if it was not there."""
    with _lock:
        data = load(mem_store)
        record = next((c for c in data['commands'] if c['id'] == record_id), None)
        if record is None:
            return None
        back = _give_back(mem_store, record)
        _bio_back(mem_store, record)
        _ended(mem_store, record, 'was removed', lw_state.load_today(), data)
        data['commands'].remove(record)
        save(mem_store, data)
        return back


def unhide_one(mem_store, record_id: str, memory_id: str) -> bool:
    """Gives back one memory a command hid; the command stays."""
    with _lock:
        data = load(mem_store)
        record = next((c for c in data['commands'] if c['id'] == record_id), None)
        row = next((h for h in record['hidden'] if h['id'] == memory_id), None) if record else None
        if row is None:
            return False
        ok = memory.unhide(mem_store, row['name'], row['ref_id'], row['id'])
        record['hidden'].remove(row)
        save(mem_store, data)
        return ok


def talk_entries(mem_store, npc: dict, talk_time=None) -> set[str]:
    """The ids of the memories the talk just saved left in this NPC's file: the ones at talk_time ((day, hour), as
    memory.summarize dates them), else the newest one shown."""
    try:
        recent = memory._peek(mem_store, npc['name'], npc['ref_id'])['recent']
    except Exception:
        return set()
    shown = [e for e in recent if not e.get('hidden')]
    if talk_time is not None:
        return {memory.archive.entry_id(e) for e in shown if (e.get('day'), e.get('hour')) == tuple(talk_time)}
    return {memory.archive.entry_id(shown[-1])} if shown else set()


def after_summary(mem_store, people, ref_fn, values: dict, ask=None, talk_time=None) -> int:
    """A talk was just saved into memory: for each forget command in force on its NPCs, what this talk said about the
    forgotten thing (the command itself, someone bringing it up) is hidden too, rewritten without it when ask (the
    summary model) is given and Check commands with the model is on. Only the memory of this talk is looked at
    (talk_entries; talk_time is the talk's (day, hour)): older ones were dealt with when the command came. Returns how
    many memories. Never raises."""
    try:
        use = ask if values.get('command_model_check', True) else None
        with _lock:
            work = [(record, [n for n in record['npcs'] if any(_same(n, c, ref_fn) for c in people or []) and not _ignored(n)])
                    for record in load(mem_store)['commands']
                    if record.get('status') in IN_FORCE and record.get('forget')]
        found = {}  # outside the lock: model requests must not hold up a prompt that reads the commands
        for record, npcs in work:
            if npcs:
                only = {(n['name'], n['ref_id']): talk_entries(mem_store, n, talk_time) for n in npcs}
                found[record['id']] = _hide(mem_store, record, record['forget'], values, npcs, ask=use, only=only)
        count, kept = 0, []
        with _lock:
            data = load(mem_store)
            for record_id, hidden in found.items():
                current = next((c for c in data['commands'] if c['id'] == record_id), None)
                if current is None:  # removed meanwhile: give back what was just hidden
                    for h in hidden:
                        memory.unhide(mem_store, h['name'], h['ref_id'], h['id'])
                    continue
                current['hidden'] = current['hidden'] + hidden
                count += len(hidden)
                kept.append(record_id)
            if count:
                save(mem_store, data)
        # a command given during the talk whose thing happened in that same talk hid nothing when it came: its forget
        # line goes into the true record now (live test 6: Gerdur's necklace was hidden and rewritten, no line)
        for record, _npcs in work:
            hidden = found.get(record['id']) or []
            if hidden and record['id'] in kept:
                _note_forgets(mem_store, record, hidden, record['forget'], once=True)
        return count
    except Exception as e:
        logger.warning(f"Living World: could not hide what a talk said about a forgotten thing ({e})")
        return 0


def _same(npc: dict, other, ref_fn) -> bool:
    """npc ({name, ref_id}) is other (a Mantella character or a game speaker dict)."""
    get = (lambda k: other.get(k)) if isinstance(other, dict) else (lambda k: getattr(other, k, None))
    a, b = ref_fn(npc.get('ref_id')), ref_fn(get('ref_id'))
    if a is not None and b is not None:
        return a == b
    return str(npc.get('name', '')).lower() == str(get('name') or '').lower()


# ---------------------------------------------------------------------------
# Gated actions: a command overrides every limit, but never for a child
# ---------------------------------------------------------------------------

def unlocked(mem_store, speakers, ref_fn, now: float | None = None) -> list[dict]:
    """The speakers as the action filter sees them: each NPC with a command in force (not worn off by now, the game
    time in GameDaysPassed) counts as close and intimate. A child (minor in their file) never does, nor anyone the game
    has not confirmed as an adult yet (action_filter.adult). Copies; the list
    as it was when there is no store or no command."""
    speakers = list(speakers or [])
    if mem_store is None or not speakers:
        return speakers
    with _lock:
        records = [c for c in load(mem_store)['commands'] if c.get('status') in IN_FORCE
                   and not (now is not None and 0 < _float(c.get('until')) <= now)]
    out = []
    for s in speakers:
        if action_filter.adult(s) and not _ignored(s) and any(_same(n, s, ref_fn) for r in records for n in r['npcs']):
            s = dict(s, close=max(1, _int(s.get('close'))), intimate=1, commanded=1)
        out.append(s)
    return out


def write_game_settings(values: dict) -> None:
    """Commands last (game hours) for the game side's own flag, in a channel file it reads when a command is given;
    written only when it changed. Never raises."""
    try:
        hours = max(0, _int(values.get('command_hours'), 0))
        current = (lw_state._read(GAME_SETTINGS).get('int') or {}).get('command_hours')
        if current != hours:
            lw_state.write_json(GAME_SETTINGS, {'int': {'command_hours': hours}})
    except Exception as e:
        logger.warning(f"Living World: could not tell the game how long absolute commands last ({e})")


# ---------------------------------------------------------------------------
# The prompt
# ---------------------------------------------------------------------------

def in_force(mem_store, speakers, ref_fn) -> list[tuple[dict, list[str]]]:
    """(command, names of the NPCs here it binds) for every command in force on someone in this talk; children never."""
    here = [s for s in speakers or [] if action_filter.adult(s) and not _ignored(s)]
    out = []
    with _lock:
        for record in load(mem_store)['commands']:
            if record.get('status') not in IN_FORCE:
                continue
            names = [n['name'] for n in record['npcs'] if any(_same(n, s, ref_fn) for s in here)]
            if names:
                out.append((record, names))
    return out


def _line(record: dict, names: list[str], player: str) -> str:
    who = ', '.join(names)
    line = f'- {who} must obey {player}\'s command "{record["text"]}".'
    if record.get('forget'):
        line += (f" {who} {'has' if len(names) == 1 else 'have'} no memory at all of {record['forget']}; if it comes up, "
                 f"they truly do not remember it.")
    if record.get('aware'):
        line += f" {who} {'knows' if len(names) == 1 else 'know'} that {player} did this."
    return line


def system_text(mem_store, speakers, player: str, ref_fn) -> str:
    """The ABSOLUTE COMMANDS part of the system prompt, or '' when nobody here has one."""
    found = in_force(mem_store, speakers, ref_fn)
    if not found:
        return ''
    return HEADER.format(player=player) + '\n' + '\n'.join(_line(r, names, player) for r, names in found)


def newest_text(mem_store, speakers, player: str, ref_fn) -> str:
    """The line for the newest message: a command given just now in full (once), else a short reminder."""
    found = in_force(mem_store, speakers, ref_fn)
    if not found:
        return ''
    fresh = [(r, names) for r, names in found if not r.get('announced')]
    if fresh:
        with _lock:
            data = load(mem_store)
            for c in data['commands']:
                if any(c['id'] == r['id'] for r, _ in fresh):
                    c['announced'] = True
            save(mem_store, data)
        return '\n'.join(f"({player} has just given {', '.join(names)} an absolute command, in these words \"{r['text']}\". "
                         f"From this reply on they obey it fully, as set out under ABSOLUTE COMMANDS. This note is "
                         f"direction, not something they saw or heard and not words to say.)" for r, names in fresh)
    names = sorted({n for _, ns in found for n in ns})
    return (f"(Absolute commands from {player} are in force for {', '.join(names)}. They obey them above everything else, "
            f"as set out under ABSOLUTE COMMANDS. This note is direction, not words to say.)")
