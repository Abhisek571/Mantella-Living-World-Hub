"""Console: the third hotkey. N tells the NPCs something happened (a custom event), G gives them an absolute command,
and Console makes something real in the game ("give me 2000 gold", "make it rain", "set my one-handed skill to 50").

The game side (MLW_Console.psc) writes the wish the player typed into console.json next to the other channel files
(key, text, NPC ref ids and names, game time, player name, ConsoleUtil's version) and asks Mantella for an NPC turn.
On that turn only, the Console action (data/actions/mantella_mlwh_console.json) is offered to the model with one note in
the newest message: the wish, the ref ids of the NPCs here (never a child's) and the few facts about the console it cannot know. The
model writes the commands from its own knowledge of Skyrim's console; no command list is sent. The game shows every
command in a Run / Cancel box before anything runs, then tells the talk the result as a fact (from the summary).

The action is never offered on any other request: it is taken out of the tool list in filter_tools and put back only
while a wish waits for its turn, and only on requests of that one turn (the same number of user messages as the first
request after the wish) in that one talk. Once the model has called it, only the request that answers that call (Direct
AI Connect's follow-up after an action result, sent with tool use off) still carries it, so the call completes and the
cached tool list stays the same; nothing after that. Never for "Name:" keywords, never with the Console setting off,
never when the game said ConsoleUtil is missing. A wish nobody answered is dropped after WAIT_SECONDS; one whose turn
began is dropped after TURN_SECONDS, at the end of the talk, or when another talk is seen.

Cost: on normal turns the tool list is exactly as before (cache untouched). The console turn sends one more tool, so
that one request (and any follow-up of the same turn) misses the cached prefix once; the next turn's list is the old
one again and reads the old cache.

With a Direct AI Connect that has the server_actions hook (server mode, set by register), the NPC model no longer
decides anything: the turn the game asks for after a wish is an answer to an action result, sent with tool use off, so
the model could never call the action there. Instead the server asks the summary model once (build_call: strict JSON,
the same helper path the forget parsing and note writing use) for the commands and the summary, and hands the game the
Console action itself on that turn (server_actions). The game still shows every command in the Run / Cancel box first.
The Console tool is then never in the tool list at all (the cached tool list never changes for it), and the NPC is only
told to say one short neutral line.

Log, per save character: <conversations folder>/<world id>/living_world/console/console.json (each wish, whether it
was offered, and what the game reports it ran or that it was cancelled), for troubleshooting."""
import json
import logging
import os
import re
import sys
import threading
import time

from . import lw_state

logger = logging.getLogger('Mantella')

GAME_FILE = 'console.json'
STORE_DIR = 'console'
STORE_FILE = 'console.json'
ACTION = 'Console'  # the tool's name (the action file's "name")
IDENTIFIER = 'mantella_mlwh_console'
MAX_COMMANDS = 5
MAX_COMMAND = 200  # a longer command is dropped, never cut: a cut command is another command
MAX_SUMMARY = 200
MAX_WISH = 300
MAX_LOG = 50
MAX_SEEN = 100
WAIT_SECONDS = 300  # a wish its turn never came for (the player walked away) is dropped
TURN_SECONDS = 120  # a wish whose turn began is dropped this long after (its turn is over)
HELPER_SECONDS = 12  # the helper model call is cut off after this (the server stops waiting for the hook at 20)
STALE_DAYS = 1      # a wish dated this many game days before today is from another session

_CONTROL = re.compile(r'[\x00-\x1f\x7f-\x9f  ]')
_lock = threading.RLock()
_state = {'pending': None, 'seen': set(), 'done': set(), 'server': False}

NOTE = (
    "({player} pressed the Console button, outside the story, to make this real in the game: \"{wish}\". Call the "
    "Console action once, with the Skyrim console commands that do exactly this and nothing more (at most "
    f"{MAX_COMMANDS}), and a one-line summary of what they make true, as a plain fact (\"{{player}} now has 2000 more "
    "gold.\"). Each command runs on its own as if typed in the console with nothing selected, so one that acts on "
    "someone needs a prefix: player.<command> for {player}{refs}, or prid <ref id> as a command before the ones meant "
    "for that person. An item, spell or other form needs its exact form id (gold is f): use one only if you are sure "
    "of it. If you do not know a safe, exact command for this, call the action with an empty list and say why in the "
    "summary. {player} sees every command and decides whether it runs; the result is told afterwards. The wish and the "
    "button are not something {names} saw or heard: in this reply say one short line that simply carries on the talk, "
    "without mentioning the wish or anything appearing.)")


# Server mode: the newest-message note on the wish turn (the NPC only carries on the talk), and the helper call.
SERVER_NOTE = "(Say one short, neutral line that simply carries on the talk.)"
HELPER_PROMPT = (
    "You turn a Skyrim player's wish into Skyrim (Special Edition) console commands. The player pressed the Console "
    "button, outside the story, to make this real in the game. Answer ONLY with one JSON object, no other text: "
    f"{{{{\"commands\": [at most {MAX_COMMANDS} console commands, each exactly as typed in the console], \"summary\": "
    "\"one plain line saying what they make true, as a fact, e.g. '{player} now has 2000 more gold.'\"}}. Use only "
    "commands that do exactly what is wished and nothing more. Each command runs on its own with nothing selected, so "
    "one that acts on someone needs a prefix: player.<command> for {player}{refs}, or prid <ref id> as a command before "
    "the ones meant for that person. An item, spell or other form needs its exact form id (gold is f): use one only if "
    "you are sure of it. If you do not know a safe, exact command for this, give an empty list and say why in the "
    "summary. The player sees every command and decides whether it runs.")


# ---------------------------------------------------------------------------
# Cleaning
# ---------------------------------------------------------------------------

def clean_text(value, limit: int) -> str:
    """One line: control characters and line breaks become spaces, runs of spaces one, cut to limit."""
    if not isinstance(value, str):
        return ''
    return ' '.join(_CONTROL.sub(' ', value).split())[:limit]


def clean_commands(value) -> list[str]:
    """At most MAX_COMMANDS commands, each one line with no control characters; empty ones and ones longer than
    MAX_COMMAND are dropped (never cut). A single text counts as one command."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        if not isinstance(item, str):
            continue
        command = ' '.join(_CONTROL.sub(' ', item).split())
        if command and len(command) <= MAX_COMMAND:
            out.append(command)
        if len(out) == MAX_COMMANDS:
            break
    return out


def _float(value, default: float = -1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number == number and abs(number) < 1e9 else default


def _int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default


# ---------------------------------------------------------------------------
# What the game wrote
# ---------------------------------------------------------------------------

def _lists(data) -> dict:
    from . import contracts  # keys and the section name in any case: Papyrus strings are case-insensitive
    return contracts.game_lists(data)


def read_queue(data: dict | None = None) -> list[dict]:
    """[{key, text, refs, names, time, player, tool}] from the game's console.json (PapyrusUtil string lists), oldest
    first. tool is ConsoleUtil's version as the game saw it (0 or less = missing)."""
    lists = _lists(lw_state._read(GAME_FILE) if data is None else data)
    get = lambda key: lists[key] if isinstance(lists.get(key), list) else []
    at = lambda values, i: str(values[i]) if i < len(values) and values[i] is not None else ''
    keys, texts, refs, names, times, players, tools = (get(k) for k in ('key', 'text', 'refs', 'names', 'time', 'player', 'tool'))
    out = []
    for i in range(len(keys)):
        key, text = clean_text(at(keys, i), 60), clean_text(at(texts, i), MAX_WISH)
        if not key or not text:
            lw_state._rejected_once('a Console wish in console.json without a key or text was left out')
            continue
        ref_list = [r.strip() for r in at(refs, i).split(',') if re.fullmatch(r'[0-9A-Fa-f]{1,8}', r.strip())]
        name_list = [clean_text(n, 60) for n in at(names, i).split('|')]
        out.append({'key': key, 'text': text, 'refs': ref_list, 'names': name_list[:len(ref_list)],
                    'time': _float(at(times, i)), 'player': clean_text(at(players, i), 60), 'tool': _int(at(tools, i))})
    return out


def read_done(data: dict | None = None) -> list[dict]:
    """[{key, text}]: what the game reports after the confirm box (what ran, what failed, or cancelled)."""
    lists = _lists(lw_state._read(GAME_FILE) if data is None else data)
    keys = lists.get('done_key') if isinstance(lists.get('done_key'), list) else []
    texts = lists.get('done_text') if isinstance(lists.get('done_text'), list) else []
    out = []
    for i, key in enumerate(keys):
        key = clean_text(str(key) if key is not None else '', 60)
        if key:
            out.append({'key': key, 'text': clean_text(str(texts[i]) if i < len(texts) and texts[i] is not None else '', 600)})
    return out


# ---------------------------------------------------------------------------
# The per-save log
# ---------------------------------------------------------------------------

def store_path(mem_store) -> str:
    return os.path.join(mem_store.root, STORE_DIR, STORE_FILE)


def load(mem_store) -> dict:
    """{seen: [wish keys read], done: [result keys read], log: [...]}; empty on any problem (a file that could not be
    read is then not saved over: lw_state.read_store_json)."""
    data = lw_state.read_store_json(store_path(mem_store))
    if not isinstance(data, dict):
        data = {}
    pick = lambda key: [str(s) for s in data.get(key) or [] if isinstance(s, (str, int))]
    return {'seen': pick('seen'), 'done': pick('done'),
            'log': [e for e in data.get('log') or [] if isinstance(e, dict)]}


def save(mem_store, data: dict) -> None:
    path = store_path(mem_store)
    lw_state.guard_save(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = lw_state.temp_path(path)
    with open(temp, 'w', encoding='utf-8') as f:
        json.dump({'seen': data['seen'][-MAX_SEEN:], 'done': data['done'][-MAX_SEEN:], 'log': data['log'][-MAX_LOG:]},
                  f, ensure_ascii=False, indent=1)
    lw_state.replace_file(temp, path)


def _log(data: dict | None, row: dict) -> None:
    if data is not None:
        data['log'].append(row)


def _set_status(mem_store, key: str, status: str) -> None:
    """The log row of this wish gets a new status (offered, not used, dropped). Never raises."""
    if mem_store is None:
        return
    try:
        with _lock:
            data = load(mem_store)
            row = next((e for e in reversed(data['log']) if e.get('key') == key), None)
            if row is not None and row.get('status') != status:
                row['status'] = status
                save(mem_store, data)
    except Exception as e:
        logger.warning(f"Living World: could not write the Console log ({e})")


# ---------------------------------------------------------------------------
# Reading new wishes
# ---------------------------------------------------------------------------

def poll(mem_store, values: dict, player: str, today: int | None, now: float | None = None) -> dict | None:
    """Reads new wishes and results from the game. The newest new wish that may be answered waits for its turn
    (returned); the others are logged with why not. Never raises."""
    now = time.time() if now is None else now
    try:
        with _lock:
            data = load(mem_store) if mem_store is not None else None
            seen = _state['seen'] | set(data['seen'] if data else [])
            done = _state['done'] | set(data['done'] if data else [])
            changed = False
            for entry in read_queue():
                if entry['key'] in seen:
                    continue
                seen.add(entry['key'])
                _state['seen'].add(entry['key'])
                if data is not None:
                    data['seen'].append(entry['key'])
                changed = True
                why = _refused(entry, values, player, today)
                row = {'key': entry['key'], 'time': entry['time'], 'wish': entry['text'], 'status': why or 'waiting'}
                if why:
                    _log(data, row)
                    logger.log(23, f"Living World: Console wish not offered ({why}): {entry['text']}")
                    continue
                old = _state['pending']
                if old is not None:
                    _status_in(data, old['key'], 'replaced by a newer wish')
                _state['pending'] = dict(entry, at=now, turn=None, told=False)
                _log(data, row)
                logger.log(23, f"Living World: Console wish waits for its turn: {entry['text']}")
            for result in read_done():
                if _state['pending'] is not None and result['key'] == _state['pending']['key']:
                    _state['pending']['result'] = True  # the action ran (or was cancelled): never offered again
                if result['key'] in done:
                    continue
                done.add(result['key'])
                _state['done'].add(result['key'])
                if data is not None:
                    data['done'].append(result['key'])
                    _log(data, {'key': result['key'], 'status': 'game', 'result': result['text']})
                changed = True
                logger.log(23, f"Living World: Console result from the game: {result['text']}")
            if changed and data is not None:
                try:
                    save(mem_store, data)
                except OSError as e:  # the log could not be read (or written): the session's own state still holds it
                    logger.warning(f"Living World: could not write the Console log ({e})")
            return _state['pending']
    except Exception as e:
        logger.warning(f"Living World: could not read Console wishes ({e})")
        return None


def _status_in(data, key: str, status: str) -> None:
    for row in reversed(data['log'] if data else []):
        if row.get('key') == key:
            row['status'] = status
            return


def _refused(entry: dict, values: dict, player: str, today: int | None) -> str:
    """Why this wish is not answered, '' when it may be."""
    if not values.get('console_actions', True):
        return 'off in the Hub settings'
    if entry['tool'] <= 0:
        return 'ConsoleUtil is missing'
    if player and entry['player'] and not lw_state._same_name(entry['player'], player):
        return 'made by another save character'
    if today is None:
        return 'no game day known'
    if entry['time'] < 0 or entry['time'] < today - STALE_DAYS or entry['time'] > today + 1 + STALE_DAYS:
        return 'from another session'
    return ''


# ---------------------------------------------------------------------------
# The one turn the action is offered on
# ---------------------------------------------------------------------------

def _turn(messages) -> int | None:
    """The request's turn: how many user messages it holds (an answer after an action result adds none)."""
    if not isinstance(messages, list) or not messages:
        return None
    return sum(1 for m in messages if isinstance(m, dict) and m.get('role') == 'user')


def _is_console(tool) -> bool:
    return isinstance(tool, dict) and (tool.get('function') or tool).get('name') == ACTION


def _console_calls(messages) -> int:
    """How many times the model called the Console action in this request's messages."""
    count = 0
    for m in messages if isinstance(messages, list) else []:
        if isinstance(m, dict) and m.get('role') == 'assistant':
            count += sum(1 for c in m.get('tool_calls') or [] if isinstance(c, dict) and (c.get('function') or {}).get('name') == ACTION)
    return count


def _answers_call(messages) -> bool:
    """This request answers a Console call: the newest assistant message in it is the one that called the action."""
    last = next((m for m in reversed(messages if isinstance(messages, list) else []) if isinstance(m, dict)
                 and m.get('role') == 'assistant'), None)
    return last is not None and any(isinstance(c, dict) and (c.get('function') or {}).get('name') == ACTION
                                    for c in last.get('tool_calls') or [])


def _talk_id() -> str:
    """The game's id of the running talk ('' when there is none yet)."""
    try:
        data = lw_state._flatten(lw_state._read('conversation.json'))
        return data['talk_id'].strip() if data.get('talk_open') == 1 and isinstance(data.get('talk_id'), str) else ''
    except Exception:
        return ''


def _drop(mem_store, pending: dict, status: str) -> None:
    _state['pending'] = None
    if not pending.get('used'):
        _set_status(mem_store, pending['key'], status)


def _current(messages, mem_store, now: float) -> dict | None:
    """The waiting wish if this request belongs to its turn (binding the turn on its first request), else None; a
    wish whose turn has passed or never came is dropped. One turn of one talk only: dropped after TURN_SECONDS, when
    a talk with fewer messages or another talk id is seen, or once the model has called the action (only the request
    that answers that call keeps it, once)."""
    pending = _state['pending']
    if pending is None:
        return None
    turn = _turn(messages)
    if pending['turn'] is None:
        if now - pending['at'] > WAIT_SECONDS:
            _drop(mem_store, pending, 'dropped: its turn never came')
            return None
        if turn is None:
            return None
        pending.update(turn=turn, bound_at=now, calls=_console_calls(messages), size=len(messages), talk=_talk_id())
        _set_status(mem_store, pending['key'], 'offered')
        logger.log(23, f"Living World: Console action offered for: {pending['text']}")
        return pending
    talk = _talk_id()
    if now - pending.get('bound_at', now) > TURN_SECONDS or (isinstance(messages, list) and len(messages) < pending.get('size', 0)) \
            or (talk and pending.get('talk') and talk != pending['talk']):
        _drop(mem_store, pending, 'dropped: its turn is over')
        return None
    if _console_calls(messages) > pending.get('calls', 0) or pending.get('result'):
        pending['used'] = True
        if _answers_call(messages) and not pending.get('answered'):
            pending['answered'] = True  # the request that answers the call: kept so it completes, never again
            return pending
        _state['pending'] = None
        return None
    if turn == pending['turn']:
        return pending
    if turn is not None:  # the next turn: the action is gone for good
        _state['pending'] = None
    return None


def _refs_text(entry: dict) -> str:
    """', <ref id>.<command> for someone here (Lydia 000A2C94)' with the children's ref ids left out ('' with nobody)."""
    from .worldlog import ref_key  # the Hub's one way of cutting a reference id for comparing
    children = _child_refs(ref_key)
    pairs = [(n or '?', r.upper().zfill(8)) for n, r in zip(entry['names'], entry['refs']) if ref_key(r) not in children]
    return (', <ref id>.<command> for someone here (' + ', '.join(f"{n} {r}" for n, r in pairs) + ')') if pairs else ''


def parse_answer(text) -> tuple[list[str], str] | None:
    """(commands, summary) from the helper's JSON answer (a code fence or words around it are tolerated); None when no
    JSON object with a commands list or a summary is in it."""
    if not isinstance(text, str):
        return None
    start, end = text.find('{'), text.rfind('}')
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except (ValueError, RecursionError):
        return None
    if not isinstance(data, dict) or not ('commands' in data or 'summary' in data):
        return None
    return clean_commands(data.get('commands')), clean_text(data.get('summary'), MAX_SUMMARY)


TOO_SLOW = 'The console helper took too long; nothing was run.'
NEEDS_NEWER = 'Console needs a newer Direct AI Connect; nothing was run.'


def _on_event_loop() -> bool:
    """True when called on a running asyncio event loop: an older Direct AI Connect calls the hook there while it holds
    its generation lock, so a helper model call would freeze the whole server."""
    try:
        import asyncio
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


def _ask_bounded(ask, prompt: str, text: str):
    """ask(prompt, text) on its own thread, waited for at most HELPER_SECONDS; TOO_SLOW when it did not answer."""
    box = {}
    # Direct AI Connect runs the hook on a thread marked as a hook thread (a thread-local flag), so a model call from it
    # does not wait for the generation lock the reply in flight holds. This worker is a new thread: without the mark its
    # call waited for the whole reply and always timed out (live test 6: the answer came 25 s later, after the reply).
    flag = getattr(sys.modules.get('src.llm.client_base'), '_hook_thread', None)
    inherit = bool(flag is not None and getattr(flag, 'active', False))

    def work():
        if inherit:
            flag.active = True
        try:
            box['answer'] = ask(prompt, text)
        except Exception as e:
            box['error'] = e
    worker = threading.Thread(target=work, name='mlw-console-helper', daemon=True)
    worker.start()
    worker.join(HELPER_SECONDS)
    if worker.is_alive():
        logger.warning(f"Living World: the Console helper call took longer than {HELPER_SECONDS} seconds; nothing is run")
        return TOO_SLOW
    if 'error' in box:
        raise box['error']
    return box.get('answer')


def build_call(entry: dict, ask, player: str) -> dict:
    """The Console action call (the standard tool-call form) for this wish, from one helper call (cut off after
    HELPER_SECONDS); with no usable answer an empty list whose summary says so (the game then shows it and runs
    nothing). Refused at once, with no helper call, when it would run on the server's event loop."""
    commands, summary = [], ''
    try:
        if _on_event_loop():
            logger.warning("Living World: the Console action needs a newer Direct AI Connect (the hook runs on the server loop); nothing is run")
            found = ([], NEEDS_NEWER)
        elif ask:
            answer = _ask_bounded(ask, HELPER_PROMPT.format(player=player, refs=_refs_text(entry)), f"Wish: {entry['text']}")
            found = ([], TOO_SLOW) if answer is TOO_SLOW else parse_answer(answer)
        else:
            found = None
    except Exception as e:
        logger.warning(f"Living World: the Console helper call failed ({e})")
        found = None
    if found is not None:
        commands, summary = found
    if not commands and not summary:
        summary = 'No safe, exact console command was found for this wish.'
    arguments = json.dumps({'commands': commands, 'summary': summary}, ensure_ascii=False)
    return {'id': 'toolu_mlwconsole' + re.sub(r'[^0-9A-Za-z]', '', entry['key'])[:40], 'type': 'function',
            'function': {'name': ACTION, 'arguments': arguments}}


def use_server(on: bool = True) -> None:
    """Server mode on (Direct AI Connect has the server_actions hook): the server builds the Console action itself."""
    _state['server'] = bool(on)


def server_actions(tools, ctx, mem_store=None, ask=None, values: dict | None = None, player: str | None = None,
                   today=None, now: float | None = None) -> list[dict]:
    """The server_actions hook: [the Console action call] on the first request of a wish's turn (built once, by
    build_call), else []. tools are all the actions Mantella generated; nothing when Console is not among them, the
    setting is off, or the wish's turn has passed (the same expiry as before). Never raises."""
    try:
        if not any(_is_console(t) for t in tools or []):
            return []
        values = values if values is not None else _settings()
        if not values.get('console_actions', True):
            return []
        player = lw_state.load_player_name() if player is None else player
        today = lw_state.load_today() if today is None else today
        now = time.time() if now is None else now
        messages = (ctx or {}).get('messages')
        poll(mem_store, values, player, today, now)
        with _lock:
            pending = _current(messages, mem_store, now)
            if pending is None or pending.get('built') or pending.get('result') or _turn(messages) != pending['turn']:
                return []
            pending['built'] = True
            entry = dict(pending)
        call = build_call(entry, ask, player or 'the player')
        with _lock:
            if _state['pending'] is not None and _state['pending'].get('key') == entry['key']:
                _state['pending'] = None  # handed to the game: done here, the game's box decides
        _set_status(mem_store, entry['key'], 'sent to the game: ' + call['function']['arguments'][:300])
        logger.log(23, f"Living World: Console action built for: {entry['text']} -> {call['function']['arguments'][:300]}")
        return [call]
    except Exception as e:
        logger.warning(f"Living World: the Console action could not be built ({e}); nothing is sent")
        return []


def talk_ended() -> None:
    """The talk is over: a wish waiting for (or in) its turn never carries into another talk."""
    with _lock:
        _state['pending'] = None


def split(tools, ctx, mem_store=None, values: dict | None = None, player: str | None = None, today=None,
          now: float | None = None) -> tuple[list, list]:
    """(the tools without the Console action, [the Console action] on its one turn else []). Reads new wishes first.
    Never raises: on any problem the action is left out."""
    tools = list(tools or [])
    rest = [t for t in tools if not _is_console(t)]
    try:
        found = [t for t in tools if _is_console(t)]
        if not found:
            return rest, []
        ctx = ctx or {}
        values = values if values is not None else _settings()
        if not values.get('console_actions', True):
            return rest, []
        player = lw_state.load_player_name() if player is None else player
        today = lw_state.load_today() if today is None else today
        now = time.time() if now is None else now
        poll(mem_store, values, player, today, now)
        if ctx.get('keyword_actions'):  # "Console:" in an NPC's line never runs it
            return rest, []
        with _lock:
            offered = _current(ctx.get('messages'), mem_store, now) is not None
        return (rest, []) if _state['server'] or not offered else (rest, found[:1])  # server mode: never a tool
    except Exception as e:
        logger.warning(f"Living World: the Console action check failed ({e}); it is not offered")
        return rest, []


def newest_text(messages, player: str | None = None) -> str:
    """The note for the newest message, once, on the request the action was first offered with; '' otherwise."""
    try:
        with _lock:
            pending = _state['pending']
            turn = _turn(messages)
            if pending is None or pending.get('told') or pending['turn'] is None or turn != pending['turn']:
                return ''
            pending['told'] = True
            entry = dict(pending)
        if _state['server']:
            return SERVER_NOTE  # the server builds the action; the wish itself is never shown to the NPC
        player = (lw_state.load_player_name() if player is None else player) or 'the player'
        refs = _refs_text(entry)  # a child's ref id is never handed out
        people = [n or '?' for n in entry['names'][:len(entry['refs'])]]
        names = (', '.join(people[:-1]) + ' and ' + people[-1]) if len(people) > 1 else (people[0] if people else 'the people here')
        return NOTE.format(player=player, wish=entry['text'].replace('"', "'"), refs=refs, names=names)
    except Exception as e:
        logger.warning(f"Living World: the Console note failed ({e})")
        return ''


def _child_refs(ref_key) -> set[str]:
    """The short ref ids of the children in this talk: the speakers the game marks minor (the Hub's one child test,
    action_filter: the minor flag the game writes per speaker), and anyone the game has not confirmed as an adult yet."""
    try:
        from . import action_filter
        return {ref_key(s.get('ref_id')) for s in lw_state.load_conversation()
                if not action_filter.adult(s) and ref_key(s.get('ref_id'))}
    except Exception:
        return set()


def _settings() -> dict:
    from . import settings
    return settings.load()


def reset() -> None:
    """Forgets the waiting wish and what was read this session (tests)."""
    with _lock:
        _state.update(pending=None, seen=set(), done=set(), server=False)
