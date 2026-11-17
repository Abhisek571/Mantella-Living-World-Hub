"""Now: one short paragraph per NPC, their current situation as they believe it, sent after their bio and Background.

The bio itself (Mantella's character list or the player's own override files) is never changed or rewritten. The Now
paragraph is written by one summary call through the player's summary model, never per reply and never during a talk
(the NPC's part of the prompt stays the same all talk, so it stays cached): after a talk, when it is due. It is due
    - after enough talks with the player (every `every` talks) or once important memories add up (IMPORTANT_SUM),
    - when a reason was marked (mark_due): a custom event, a game-owned fact that changed since the last talk (found at
      talk start), an absolute command given, lifted or released, the first Now made from an old change note.
The writer is given the bio, the current Background facts, the Now so far and their recent memories, and is told to
keep only what is still true, so stale lines drop out. It is written while an absolute command is in force too: it says
what the NPC believes and never turns command text into their own idea unless the command says they believe it.
The same call may write a short note for OTHER NPCs (how others see this one, after a custom event changed that) and,
when the user set none, a values line (what they care about and will not do), cached here.

Lines kept apart from the paragraph and always sent after it: gaps a forget left ("has no memory of days 12 to 40, and
it frightens her"). In the Memory tab it can be read, edited, locked (never written again by itself) or reset.

Files: <conversations folder>/<world id>/living_world/bio_changes/<name> - <ref id>.json, per save character, like the
memories it comes from (the folder keeps its old name: a change note found there becomes the first Now)."""
import functools
import json
import logging
import os
import queue
import re
import threading
import time

from . import archive, lw_state, memory, timeline

logger = logging.getLogger('Mantella')

FOLDER = 'bio_changes'
MAX_CHARS = 500  # the paragraph, at most
MAX_OTHERS = 220
MAX_VALUES = 180
DEFAULT_EVERY = 5  # talks with the player between two updates...
IMPORTANT_SUM = 2.0  # ...or sooner, once the new memories' importance adds up to this
MIN_NEW = 2  # never from a single memory (unless a reason was marked)
MAX_INPUT_MEMORIES = 30
MAX_HISTORY = 5  # earlier texts kept in the file, for the player to look back at
MAX_REASONS = 8
MAX_GAPS = 5
OLD_NOTE = 'their old note on how they changed becomes their first Now paragraph'

PROMPT = (
    "You keep the \"Now\" paragraph of {name} in Skyrim: their current situation as {name} believes it, in the third "
    "person but only as {name} sees things. Below are their bio, their background facts, the paragraph so far, what "
    "happened that makes it due, any absolute command in force, and their recent memories (oldest first). Write the new "
    "paragraph: at most 4 short sentences and {chars} characters. Keep only what is still true now: drop anything the "
    "facts or newer memories show is over (a worry that was settled, someone who came back). Never repeat the bio or the "
    "background facts, never invent anything, change slowly (one talk rarely changes a person). The background facts "
    "come from the game: a custom event cannot change marriage, home, follower status or faction membership; write that "
    "they believe such a thing only when the event is plainly about a belief or an illusion. Custom events listed as "
    "really happened are true: never write that they did not happen, and a later gift menu, offer or \"(Nothing "
    "happened: ...)\" line about the same thing does not undo them. Memories marked as made "
    "under a command or a spell were not their own choice: say what they believe about that time, and never write a "
    "command's words as their own wish unless the command says they believe it. What they wear is their own choice "
    "unless a gift or an event says {player} gave it. Lines under \"Kept apart\" are sent anyway: do not repeat them. "
    "Never write how long ago something was (\"less than an hour ago\", \"earlier today\"): the paragraph is kept for "
    "days. If nothing needs to change, answer with the paragraph so far word for word, or NONE if there is none yet.{extra} "
    "Answer in {language}, with only the paragraph{lines}.")
OTHERS_ASK = (" If an event changed how OTHER people see {name} (an illusion over their clothes, a disguise), add a line "
              "\"OTHERS: <one sentence for everyone else, at most {others} characters>\"; if such a note exists and no "
              "longer holds, add \"OTHERS: NONE\".")
HOODED_ASK = (" {name} has only met {player} hooded and never learned who it was: write \"a hooded stranger\", never the "
              "name {player}.")
VALUES_ASK = (" Also add a line \"VALUES: <what {name} cares about most and will not do, from the bio, at most {values} "
              "characters>\".")

_lock = threading.Lock()
_running: set = set()  # (root, name, ref id) being written now
_file_locks: dict = {}  # Now file path -> its lock (as memory.MemoryStore.lock does for memory files)
_file_locks_guard = threading.Lock()
TALK_IDLE_SECONDS = 180  # a talk with no request for this long counts as over (Mantella closed during it)
WAIT_STEP = 2.0
_talk = {'last': 0.0, 'ended': True}  # the conversation going on: bio requests wait until it is over


def _path(store, name: str, ref_id: str) -> str:
    return os.path.join(store.root, FOLDER, f"{memory.safe_part(memory.file_name(name))} - {memory.safe_part(str(ref_id), '0')}.json")


def file_lock(store, name: str, ref_id: str) -> threading.RLock:
    """The lock of one NPC's Now file (the same object for every caller on that path). Whatever loads, changes and saves
    it back holds this, so a reason marked due by the reply path is never lost to the background writer's save."""
    key = os.path.normcase(os.path.abspath(_path(store, name, ref_id)))
    with _file_locks_guard:
        return _file_locks.setdefault(key, threading.RLock())


def _locked(fn):
    """Runs fn(store, name, ref_id, ...) holding that NPC's Now file lock (its whole load, change and save)."""
    @functools.wraps(fn)
    def run(store, name, ref_id, *args, **kwargs):
        with file_lock(store, name, ref_id):
            return fn(store, name, ref_id, *args, **kwargs)
    return run


def empty() -> dict:
    return {'text': '', 'locked': False, 'auto': False, 'day': -1, 'talks': 0, 'after': None, 'version': 0, 'history': [],
            'now': True, 'due': [], 'notes': [], 'gaps': [], 'others': '', 'values': '', 'talk': '', 'seq': None}


def _strings(value, limit: int, count: int) -> list[str]:
    return [' '.join(v.split())[:limit] for v in value if isinstance(v, str) and v.strip()][-count:] if isinstance(value, list) else []


def load(store, name: str, ref_id: str) -> dict:
    state = empty()
    try:
        with open(_path(store, name, ref_id), encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError, RecursionError):
        return state
    if not isinstance(data, dict):
        return state
    if isinstance(data.get('text'), str):
        state['text'] = data['text'][:MAX_CHARS * 2]
    for key in ('locked', 'auto'):
        state[key] = data.get(key) is True
    for key in ('day', 'talks', 'version'):
        state[key] = memory._int(data.get(key), state[key])
    after = data.get('after')
    if isinstance(after, list) and len(after) == 2:
        state['after'] = [memory._int(after[0]), memory._int(after[1])]
    if isinstance(data.get('history'), list):
        state['history'] = [h for h in data['history'] if isinstance(h, dict) and isinstance(h.get('text'), str)][-MAX_HISTORY:]
    state['due'] = _strings(data.get('due'), 300, MAX_REASONS)
    state['notes'] = _strings(data.get('notes'), 400, MAX_REASONS)
    state['gaps'] = [g for g in data.get('gaps') or [] if isinstance(g, dict) and isinstance(g.get('text'), str)][-MAX_GAPS:] \
        if isinstance(data.get('gaps'), list) else []
    for key, limit in (('others', MAX_OTHERS), ('values', MAX_VALUES)):
        state[key] = ' '.join(data[key].split())[:limit] if isinstance(data.get(key), str) else ''
    state['talk'] = data['talk'][:64] if isinstance(data.get('talk'), str) else ''
    state['seq'] = data['seq'] if isinstance(data.get('seq'), int) and not isinstance(data.get('seq'), bool) else None
    if data.get('now') is not True:  # an old "how they have changed" note: the first Now is written from it
        state['now'] = True
        if state['text'] and OLD_NOTE not in state['due']:
            state['due'] = (state['due'] + [OLD_NOTE])[-MAX_REASONS:]
    return state


def save(store, name: str, ref_id: str, state: dict) -> None:
    path = _path(store, name, ref_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = lw_state.temp_path(path)
    with open(tmp, 'w', encoding='utf-8', errors='replace') as f:
        json.dump(dict(state, now=True), f, ensure_ascii=False, indent=1)
    lw_state.replace_file(tmp, path)


def _key(entry: dict) -> tuple[int, int]:
    return memory._int(entry.get('day')), memory._int(entry.get('hour'))


def _quick(store, name: str, ref_id: str) -> dict:
    """The memory file only read, without its archive or shared texts: enough to tell whether a note is due, cheaply,
    after every talk. A file being replaced right now reads as empty: the note waits for a later talk."""
    try:
        with open(store._path(name, ref_id), encoding='utf-8-sig') as f:
            return memory.clean(json.load(f))
    except (OSError, ValueError, RecursionError):
        return memory.empty()


def _shown(mem: dict, store=None) -> list[dict]:
    """The memories a paragraph may be written from: shown ones of the loaded save's timeline only, the same filter talks
    use (live test 15: a Now was written from a memory of a later, set-aside timeline)."""
    branch = timeline.current(store) if store is not None else None
    return [e for e in mem.get('recent', []) if not e.get('hidden') and not e.get('reload') and timeline.usable(branch, e)
            and (e.get('shared') or memory.entry_text(e, store))]


def new_memories(mem: dict, state: dict, store=None) -> list[dict]:
    """The memories since the paragraph was last written: shown ones (not hidden), not trims mid-talk. Memories saved
    under an absolute command count too (the writer is told which ones they are)."""
    after = tuple(state['after']) if state.get('after') else None
    out = _shown(mem, store)
    if after is not None:
        out = [e for e in out if _key(e) > after]
    return out[-MAX_INPUT_MEMORIES:]


def due(state: dict, mem: dict, every: int = DEFAULT_EVERY, store=None) -> bool:
    if state.get('locked') or every <= 0:
        return False
    if state.get('due'):
        return True
    new = new_memories(mem, state, store)
    if len(new) < MIN_NEW:
        return False
    talks = memory._int(mem.get('talks'), 0) - memory._int(state.get('talks'), 0)
    return talks >= every or sum(archive.importance_of(e) for e in new) >= IMPORTANT_SUM


def clip(text: str, limit: int = MAX_CHARS) -> str:
    """At most limit characters, cut after the last whole sentence that fits."""
    text = ' '.join(str(text or '').split()).strip('"')
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind('. '), cut.rfind('! '), cut.rfind('? '))
    return cut[:end + 1] if end > limit // 3 else cut.rstrip() + '...'


def parse_reply(reply: str) -> tuple[str, str | None, str | None]:
    """(paragraph, others note or None when not given ('' = NONE), values line or None). The parts are found whatever
    their order, case or place: a label at the start of a line, or one in capitals (or after a full stop) inside a line
    (live test 7 stored "Now: Lydia is travelling ... VALUES: Fiercely loyal ..."); a leading "Now:" label is dropped."""
    others = values = None
    text = str(reply or '')
    marks = [m for m in _PART.finditer(text)
             if m.group('line') is not None or m.group('name').isupper() or m.group('after') is not None]
    pieces, start, label = [], 0, 'NOW'
    for m in marks:
        pieces.append((label, text[start:m.start()]))
        label, start = m.group('name').upper(), m.end()
    pieces.append((label, text[start:]))
    kept = []
    for label, body in pieces:
        body = ' '.join(body.split()).strip('"* ')
        if label == 'NOW':
            if body:
                kept.append(body)
        elif label == 'OTHERS':
            others = '' if body.upper().strip('. ') == 'NONE' else clip(body, MAX_OTHERS)
        else:
            values = clip(body, MAX_VALUES)
    return clip(' '.join(kept)), others, values


# a part label: at the start of a line (any case), or inside a line in capitals or right after a sentence's end
_PART = re.compile(r'(?:(?P<line>(?:^|(?<=\n))[ \t]*)|(?P<after>(?<=[.!?"])[ \t]+)|(?<=[ \t]))\**[ \t]*'
                   r'(?P<name>now|others|values)[ \t]*\**[ \t]*:[ \t]*', re.I)


def _label(entry: dict, labels: dict) -> str:
    if isinstance(entry.get('spell'), str) and entry['spell'].strip():
        return f"({entry['spell'].strip()}) "
    tag = entry.get('command')
    if tag and tag in labels:
        return f"({labels[tag]}) " if labels[tag] else ''
    return '(while under an absolute command) ' if tag else ''


def write(store, name: str, ref_id: str, bio: str, ask, language: str = 'English', every: int = DEFAULT_EVERY,
          force: bool = False, blocked=None, context: dict | None = None) -> str | None:
    """Writes the paragraph anew when it is due (or force), with ask(text, prompt) -> reply (Mantella's summary call).
    Returns the new text, '' when nothing needed to change, None when nothing was asked. A paragraph the player locked,
    or edited while the request ran, is never replaced. context: {facts, commands, player, values_given, labels
    (command id -> memory label)}. blocked is kept for old callers: an absolute command no longer stops it."""
    context = context or {}
    key = (store.root, memory.file_name(name), str(ref_id))
    with _lock:
        if key in _running:
            return None
        _running.add(key)
    try:
        state = load(store, name, ref_id)
        mem = _quick(store, name, ref_id)
        if state['locked'] or not (force or due(state, mem, every, store)):
            return None
        new = new_memories(mem, state, store)
        recent = _shown(mem, store)[-MAX_INPUT_MEMORIES:]
        if not new and not state['due'] and not force:
            return None
        labels = context.get('labels') or {}
        lines = '\n'.join(_label(e, labels) + memory._line(e, store) for e in recent) or '(none)'
        player = context.get('player') or 'the player'
        reasons = state['due'] + state['notes']
        gaps = '\n'.join(f"- {g['text']}" for g in state['gaps'])
        text = (f"Bio:\n{(bio or '(none)').strip()[:3000]}\n\n"
                f"Background facts (from the game and the player's notes):\n{context.get('facts') or '(none)'}\n\n"
                + (f"{context['events']}\n\n" if context.get('events') else '')  # custom events: true, never undone
                + f"The paragraph so far:\n{state['text'] or '(none yet)'}\n\n"
                + (f"Kept apart (sent anyway):\n{gaps}\n\n" if gaps else '')
                + (f"Why it is due now:\n" + '\n'.join(f"- {r}" for r in reasons) + '\n\n' if reasons else '')
                + (f"Absolute commands in force on them (they obey; unless a command says so they do not know it was "
                   f"given):\n{context['commands']}\n\n" if context.get('commands') else '')
                + (f"How others see them now (note for others):\n{state['others']}\n\n" if state['others'] else '')
                + f"Recent memories:\n{lines}")
        ask_values = not context.get('values_given') and not state['values']
        extra = OTHERS_ASK.format(name=name, others=MAX_OTHERS) + (VALUES_ASK.format(name=name, values=MAX_VALUES) if ask_values else '')
        if context.get('hooded'):  # they have only met the player hooded and never learned the name
            extra += HOODED_ASK.format(name=name, player=player)
        prompt = PROMPT.format(name=name, chars=MAX_CHARS, language=language, player=player, extra=extra,
                               lines=' and the extra lines asked for' if extra else '')
        try:
            reply = ask(text, prompt)
        except Exception as e:
            logger.warning(f"Living World: could not write {name}'s Now paragraph ({e}); tried again after a later talk")
            return None
        if not reply or not str(reply).strip():
            return None
        paragraph, others, values = parse_reply(reply)
        if paragraph:
            paragraph = memory.strip_relative(paragraph)  # stored for good: no "less than an hour ago" (live test 15)
        if context.get('hooded') and paragraph:
            paragraph = memory.mask_player(paragraph, player)
        nothing = not paragraph or paragraph.upper().strip('. ') == 'NONE'
        stamp = _now_stamp(store)
        with file_lock(store, name, ref_id):
            latest = load(store, name, ref_id)
            if latest['locked'] or latest['version'] != state['version']:
                return None  # the player locked or edited it meanwhile: theirs wins
            if not nothing and paragraph != latest['text']:
                _keep_old(latest)
                latest.update(text=paragraph, auto=True, **stamp)
            if others is not None:
                latest['others'] = others
            if values and not latest['values']:
                latest['values'] = values
            last = new[-1] if new else (recent[-1] if recent else None)
            done = set(state['due']) | set(state['notes'])
            latest['due'] = [r for r in latest['due'] if r not in done]
            latest['notes'] = [n for n in latest['notes'] if n not in done]
            latest.update(talks=memory._int(mem.get('talks'), 0), version=latest['version'] + 1)
            if last is not None:
                latest.update(day=_key(last)[0], after=list(_key(last)))
            save(store, name, ref_id, latest)
        if not nothing:
            logger.log(23, f"Living World: {name} now: {paragraph}")
        return '' if nothing else paragraph
    finally:
        with _lock:
            _running.discard(key)


def _now_stamp(store) -> dict:
    """The talk a paragraph written now follows (timeline.py): the running talk, else the last one that ended in the
    loaded save's line; {talk: '', seq: None} without the game's talk counter."""
    try:
        found = timeline.stamp_now(store)
    except Exception:
        found = {}
    return {'talk': found.get('talk') or '', 'seq': found.get('seq')}


def _keep_old(state: dict) -> None:
    """The paragraph being replaced goes into the history, with the talk it followed."""
    if state['text']:
        state['history'] = (state['history'] + [{'text': state['text'], 'day': state['day'], 'talk': state.get('talk') or '',
                                                 'seq': state.get('seq')}])[-MAX_HISTORY:]


def _for_save(store, state: dict) -> str:
    """The paragraph that belongs to the save now loaded: one written after a talk the loaded save never had (an older
    save was loaded) is left out for the newest earlier one that fits; without the game's talk counter, the paragraph."""
    text = state['text'].strip()
    if not text or not state.get('talk'):
        return text
    try:
        branch = timeline.current(store)
    except Exception:
        return text
    if timeline.usable(branch, state):
        return text
    for old in reversed(state['history']):
        if timeline.usable(branch, old):
            return str(old.get('text') or '').strip()
    return ''


def mark_due(store, name: str, ref_id: str, reason: str, note: str = '') -> bool:
    """A reason to write the paragraph again after the next talk with them (or at once, write_now). note: something the
    writer must fold in (the spell lifted). True when written. Never raises."""
    try:
        with file_lock(store, name, ref_id):
            state = load(store, name, ref_id)
            reason = ' '.join(str(reason or '').split())[:300]
            changed = False
            if reason and reason not in state['due']:
                state['due'] = (state['due'] + [reason])[-MAX_REASONS:]
                changed = True
            note = ' '.join(str(note or '').split())[:400]
            if note and note not in state['notes']:
                state['notes'] = (state['notes'] + [note])[-MAX_REASONS:]
                changed = True
            if changed:
                save(store, name, ref_id, state)
            return changed
    except Exception as e:
        logger.warning(f"Living World: could not mark {name}'s Now paragraph as due ({e})")
        return False


def add_gap(store, name: str, ref_id: str, text: str, day: int = -1) -> bool:
    """A line kept apart from the paragraph and always sent after it (a forget that leaves a gap)."""
    text = ' '.join(str(text or '').split())[:300]
    if not text:
        return False
    with file_lock(store, name, ref_id):
        state = load(store, name, ref_id)
        if any(g['text'] == text for g in state['gaps']):
            return False
        state['gaps'] = (state['gaps'] + [{'text': text, 'day': day, 'at': time.time()}])[-MAX_GAPS:]
        state['version'] += 1
        save(store, name, ref_id, state)
        return True


def clear_gaps(store, name: str, ref_id: str) -> int:
    with file_lock(store, name, ref_id):
        state = load(store, name, ref_id)
        count = len(state['gaps'])
        if count:
            state.update(gaps=[], version=state['version'] + 1)
            save(store, name, ref_id, state)
        return count


def _check(store, npc, ask, language: str, every: int, blocked=None, context_for=None):
    """One NPC after a talk: the paragraph is written when it is due. Never raises."""
    try:
        if due(load(store, npc.name, npc.ref_id), _quick(store, npc.name, npc.ref_id), every):
            context = None
            if context_for is not None:
                try:
                    context = context_for(npc)
                except Exception as e:
                    logger.warning(f"Living World: could not gather {npc.name}'s facts for the Now paragraph ({e})")
            return write(store, npc.name, npc.ref_id, getattr(npc, 'bio', '') or '', ask, language, every, context=context)
    except Exception as e:
        logger.warning(f"Living World: could not check {npc.name}'s Now paragraph ({e})")
    return None


def talk_going_on() -> None:
    """A request of a conversation is being built: bio requests wait (they share the summary model, often the main
    model's own client and its lock, and would hold up the reply)."""
    _talk.update(last=time.time(), ended=False)


def talk_over() -> None:
    _talk['ended'] = True


def busy(now: float | None = None) -> bool:
    """A conversation is going on (and not idle so long that Mantella must have been closed during it)."""
    return not _talk['ended'] and (now if now is not None else time.time()) - _talk['last'] < TALK_IDLE_SECONDS


_queue: queue.Queue = queue.Queue()
_worker = {'thread': None}
_pending: dict = {}  # (root, name, ref id) -> the newest job for that NPC; the queue holds each key once


def _work() -> None:
    while True:
        key = _queue.get()
        try:
            while busy():
                time.sleep(WAIT_STEP)
            with _lock:
                job = _pending.pop(key, None)
            if job is not None:
                job()
        except Exception as e:
            logger.warning(f"Living World: a Now paragraph job failed ({e})")
        finally:
            _queue.task_done()


def _enqueue(key, job) -> None:
    """At most one waiting job per NPC: a newer one replaces it in its place in the queue."""
    with _lock:
        waiting = key in _pending
        _pending[key] = job
    if not waiting:
        _queue.put(key)


def _start_worker() -> None:
    with _lock:
        if _worker['thread'] is None or not _worker['thread'].is_alive():
            _worker['thread'] = threading.Thread(target=_work, daemon=True, name='living-world-now')
            _worker['thread'].start()


def after_summary(ctx: dict, store, values: dict, background: bool = True) -> list:
    """The 'summarize' hook, after the memories are saved: each NPC of the talk is checked, and their paragraph written
    when it is due, one after another on a background worker, so the talk's end is not held up by reading files or by
    the request; while a conversation is going on the worker waits (busy). ctx now_context(npc) -> the write context
    (facts, commands, labels). With background False it runs here and returns the results (tests)."""
    if store is None or not values.get('bio_changes', True) or ctx.get('is_reload'):
        return []
    every = memory._int(values.get('bio_changes_talks'), DEFAULT_EVERY)
    summaries = ctx.get('summaries')
    if summaries is None or every <= 0:
        return []
    language = getattr(summaries, '_Summaries__language_name', 'English')
    ask = lambda text, prompt: memory._ask_summary(summaries, text, prompt, 'a Now paragraph')
    npcs = list(ctx.get('npcs_to_summarize') or [])
    context_for = ctx.get('now_context')
    if not background:
        return [r for r in (_check(store, n, ask, language, every, context_for=context_for) for n in npcs) if r is not None]
    _start_worker()
    for npc in npcs:
        _enqueue((store.root, memory.file_name(npc.name), str(npc.ref_id)),
                 lambda n=npc: _check(store, n, ask, language, every, context_for=context_for))
    return npcs


def write_now(store, npcs: list, ask, language: str = 'English', context_for=None, background: bool = True) -> list:
    """Writes the paragraphs of these NPCs (objects with name, ref_id, bio) that are due, without waiting for a talk
    (a command released from the page); on the background worker, which waits while a talk goes on."""
    if store is None or ask is None:
        return []
    if not background:
        return [r for r in (_check(store, n, ask, language, DEFAULT_EVERY, context_for=context_for) for n in npcs) if r is not None]
    _start_worker()
    for npc in npcs:
        _enqueue((store.root, memory.file_name(npc.name), str(npc.ref_id)),
                 lambda n=npc: _check(store, n, ask, language, DEFAULT_EVERY, context_for=context_for))
    return list(npcs)


def now_text(store, name: str, ref_id: str, state: dict | None = None) -> str:
    """One NPC's Now paragraph with the lines kept apart after it, as sent; '' when there is none."""
    try:
        state = state or load(store, name, ref_id)
    except Exception:
        return ''
    body = ' '.join(t for t in [_for_save(store, state)] + [g['text'] for g in state['gaps']] if t)
    return f"Now, as {name} sees it: {body}" if body else ''


def prompt_text(store, people) -> str:
    """The Now paragraphs of the NPCs in the talk (people: (name, ref id) pairs), for after their bios."""
    if store is None:
        return ''
    return '\n'.join(t for t in (now_text(store, name, ref_id) for name, ref_id in people or []) if t)


def add_to_parts(ordered: dict, text: str) -> dict:
    """After the bios: at the end of Mantella's background part, else of its whole text."""
    if not text:
        return ordered
    for key in ('background', 'mantella', 'overview'):
        if isinstance(ordered.get(key), str) and ordered[key].strip():
            ordered[key] = ordered[key].rstrip() + '\n\n' + text
            return ordered
    return ordered


_others_cache: dict = {}  # path -> (mtime, name, note)


def _all_others(store) -> list[tuple[str, str, str]]:
    """(name, ref id, note for others) of every NPC in this save with one."""
    out = []
    for name, ref in people_with(store):
        path = _path(store, name, ref)
        try:
            stamp = os.path.getmtime(path)
        except OSError:
            continue
        cached = _others_cache.get(path)
        if not cached or cached[0] != stamp:
            cached = (stamp, load(store, name, ref)['others'])
            _others_cache[path] = cached
        if cached[1]:
            out.append((name, ref, cached[1]))
    return out


def others_text(store, people, messages=None) -> str:
    """For the newest message: the note about an NPC that OTHER NPCs receive, for each NPC in a group talk with others,
    and for an NPC not here whom the last few messages name. Never in the prompt part that stays cached."""
    if store is None:
        return ''
    here = [memory.file_name(n).lower() for n, _ in people or []]
    recent = ' '.join(str(m.get('content') or '') for m in (messages or [])[-4:] if isinstance(m, dict) and isinstance(m.get('content'), str))
    lines = []
    for name, _, note in _all_others(store):
        low = name.lower()
        if low in here:
            if len(here) > 1:
                lines.append(f"(For everyone here except {name}: {note})")
        elif recent and re.search(r'\b' + re.escape(name) + r'\b', recent, re.I):
            lines.append(f"(About {name}: {note})")
    return '\n'.join(lines)


# --- the Memory tab and the NPC page ---------------------------------------------------------------------------------

@_locked
def edit(store, name: str, ref_id: str, text: str | None = None, locked: bool | None = None, others: str | None = None,
         values: str | None = None) -> dict:
    """The player's own text, lock, note for others or values line. Returns the saved state."""
    state = load(store, name, ref_id)
    if text is not None:
        clean = clip(text, MAX_CHARS * 2)
        if clean != state['text']:
            _keep_old(state)
            state.update(text=clean, auto=False, edited_at=time.time(), talk='', seq=None)
    if locked is not None:
        state['locked'] = bool(locked)
    if others is not None:
        state['others'] = clip(others, MAX_OTHERS)
    if values is not None:
        state['values'] = clip(values, MAX_VALUES)
    state['version'] += 1
    save(store, name, ref_id, state)
    return state


@_locked
def reset(store, name: str, ref_id: str) -> dict:
    """Clears the paragraph and starts counting again from now: only what happens from here on is written into it.
    The lock is kept."""
    state = load(store, name, ref_id)
    mem = _quick(store, name, ref_id)
    shown = [e for e in mem.get('recent', []) if not e.get('hidden')]
    _keep_old(state)
    state.update(text='', auto=False, talk='', seq=None, talks=memory._int(mem.get('talks'), 0), due=[], notes=[],
                 after=list(_key(shown[-1])) if shown else state.get('after'), version=state['version'] + 1)
    save(store, name, ref_id, state)
    return state


@_locked
def restore(store, name: str, ref_id: str, snapshot: dict) -> bool:
    """Puts the paragraph back as snapshot ({text, version, after, day, talks}, taken when an absolute command began)
    when it was written by itself since (a command released with "forgets the whole period", or worn off). A paragraph
    the player locked or wrote is left alone. True when it was put back."""
    state = load(store, name, ref_id)
    if state['locked'] or not state['auto'] or state['version'] == memory._int(snapshot.get('version'), -1):
        return False
    _keep_old(state)
    after = snapshot.get('after')
    state.update(talk='', seq=None, text=str(snapshot.get('text') or ''), auto=bool(snapshot.get('text')), day=memory._int(snapshot.get('day')),
                 talks=memory._int(snapshot.get('talks'), 0), after=list(after) if isinstance(after, list) and len(after) == 2 else None,
                 version=state['version'] + 1)
    save(store, name, ref_id, state)
    logger.log(23, f"Living World: {name}'s Now paragraph is back to how it was before an absolute command")
    return True


@_locked
def roll_back(store, name: str, ref_id: str, day: int) -> bool:
    """Memories from this day on were hidden (forgotten): a paragraph written by itself from them goes back to its
    newest earlier text written before that day (or none), and is written again from what they still remember. A
    paragraph the player locked or wrote is left alone. True when it changed."""
    state = load(store, name, ref_id)
    after = state.get('after')
    if state['locked'] or not state['auto'] or not after or memory._int(after[0]) < day:
        return False
    older = [h for h in state['history'] if memory._int(h.get('day')) < day]
    keep = older[-1] if older else None
    _keep_old(state)
    state.update(talk=str((keep or {}).get('talk') or ''), seq=(keep or {}).get('seq'), text=keep['text'] if keep else '', day=memory._int(keep.get('day')) if keep else -1,
                 after=[memory._int(keep.get('day')), -1] if keep else None, talks=0, version=state['version'] + 1)
    save(store, name, ref_id, state)
    logger.log(23, f"Living World: {name}'s Now paragraph was put back, memories in it were forgotten")
    return True


def people_with(store) -> list[tuple[str, str]]:
    """(name, ref id) of every NPC in this save with a Now file."""
    try:
        names = sorted(os.listdir(os.path.join(store.root, FOLDER)))
    except OSError:
        return []
    out = []
    for entry in names:
        if entry.endswith('.json') and ' - ' in entry:
            name, _, ref = entry[:-5].rpartition(' - ')
            out.append((name, ref))
    return out
