"""Custom events: what the player types with Mantella's "Add Custom Game Event" hotkey (N by default).

Mantella's game side adds a line break to the end of a typed event, which no other in-game event has; that is how one is
told apart here. Each one is kept in a per-save journal (<conversations>/<world>/living_world/custom_events.json) so it
can be looked at, edited or taken back in the Memory tab.

What the player types:
    Lydia trips into the river          narrated: the NPCs react to it (the default)
    silent: Lydia trips into the river  silent: everyone present knows it happened and remembers it, nobody is asked
                                        to answer it
    react: Lydia trips into the river   narrated even when the setting makes every custom event silent
    undo                                takes back the newest custom event of this talk

Taking an event back or editing it: while the talk goes on, every request is sent with the event changed or left out
(fix_request) and the talk itself is changed before it is summarized (fix_thread). Once a memory was written from it,
that memory is hidden (memory.hide_matching, so Unhide on the Memory page brings it back) and, when the model is
reachable, replaced by the same memory rewritten without the event, or with the edited one."""
import copy
import json
import logging
import os
import re
import threading
import time
import uuid

from . import archive, embed, lw_state, memory, timeline

logger = logging.getLogger('Mantella')

FILE = 'custom_events.json'
SILENT = 'silent'
NARRATED = 'narrated'
SILENT_PREFIX = 'silent:'
REACT_PREFIX = 'react:'
UNDO_WORDS = {'undo', 'undo last', 'undo event', 'undo last event'}
MAX_EVENTS = 300  # kept per save; the oldest go first
MAX_TEXT = 600
SILENT_NOTE = ("(Everyone here knows this happened and remembers it. It needs no answer: nobody remarks on it unless it "
               "matters to what is said next.)")
HIDDEN_BY = 'custom event'
DONE_MARK = 'Already happened, and complete:'  # opens every custom event the model reads

REWRITE_REMOVE = (
    "Below is one memory of {name} in Skyrim, from their own point of view. This part of it never happened: \"{old}\". "
    "Rewrite the memory without it and without anything that only follows from it; keep everything else as it is, in the "
    "same voice, no longer than it was. Answer with only the memory.")
REWRITE_EDIT = (
    "Below is one memory of {name} in Skyrim, from their own point of view. One thing in it happened differently: not "
    "\"{old}\" but \"{new}\". Rewrite the memory with what really happened; keep everything else as it is, in the same "
    "voice, about as long as it was. Answer with only the memory.")

_lock = threading.RLock()
_talk = {'id': None}  # the talk going on now: its custom events can still be changed in the live conversation


# --- what the player typed ----------------------------------------------------------------------------------------------

def is_custom(event) -> bool:
    """A typed custom event: Mantella's game side ends it with a line break; other events have none."""
    return isinstance(event, str) and event.endswith('\n') and bool(event.strip())


def parse(event: str, silent_default: bool = False) -> tuple[str, str]:
    """(kind, text): kind 'undo', SILENT or NARRATED, text without the prefix."""
    text = ' '.join(str(event).split())[:MAX_TEXT]
    if text.lower().rstrip('.!') in UNDO_WORDS:
        return 'undo', ''
    if text.startswith(DONE_MARK):  # already handled once (sent_text): never marked twice
        text = text[len(DONE_MARK):].strip()
        if text.endswith(SILENT_NOTE):
            return SILENT, text[:-len(SILENT_NOTE)].strip()
        return NARRATED, text
    low = text.lower()
    if low.startswith(SILENT_PREFIX):
        return SILENT, text[len(SILENT_PREFIX):].strip()
    if low.startswith(REACT_PREFIX):
        return NARRATED, text[len(REACT_PREFIX):].strip()
    return (SILENT if silent_default else NARRATED), text


def sent_text(text: str, mode: str) -> str:
    """The event as the model reads it: marked as already happened and complete (the shared rule in 00_hub.txt says no
    action makes it happen again or checks it)."""
    return f"{DONE_MARK} {text} {SILENT_NOTE}" if mode == SILENT else f"{DONE_MARK} {text}"


# --- what a custom event means for the turns after it -------------------------------------------------------------------

# Actions that move goods from one person to another (World's trade actions, Mantella's own menus). On the reply right
# after a custom event none of them is offered, so the model cannot open a gift menu to "do" a gift that already happened.
# World's one Trade action carries the kind inside: its kinds are blocked by name the same way (filter_tools takes them out
# of its "kind" choice). The separate action names of World 1.x stay for a World that is not updated yet.
ITEM_ACTIONS = ('TakeGift', 'AskItem', 'GiveItem', 'OfferTrade', 'Inventory', 'Barter',
                'take_gift', 'ask_item', 'give_item', 'offer_trade')
# Gold is a real game object and is never created by text: after a custom event that speaks of gold the gold actions stay,
# so the real hand-over can still happen; after any other custom event they go with the item actions.
GOLD_ACTIONS = ('AskGold', 'GiveGold', 'ask_gold', 'give_gold')
GOLD_WORDS = re.compile(r'\b(gold|septims?|coins?|drakes?)\b', re.I)
# Game-owned facts (marriage, home, follower) are never made true by text (facts_history records a mismatch instead)
GAME_OWNED = re.compile(r'\b(marr(y|ies|ied|iage)|wed(s|ded|ding)?|spouse|wife|husband|divorc\w*|engaged|home|house|'
                        r'moves? in|moved in|follower|follows? (?:you|the player|him|her)|joins? (?:you|the player))\b', re.I)


def _newest_user_text(messages) -> str:
    for message in reversed(messages if isinstance(messages, list) else []):
        if isinstance(message, dict) and message.get('role') == 'user':
            content = message.get('content')
            if isinstance(content, list):
                return '\n'.join(p.get('text', '') for p in content if isinstance(p, dict) and isinstance(p.get('text'), str))
            return content if isinstance(content, str) else ''
    return ''


def blocked_actions(messages) -> set[str]:
    """The transfer actions not offered on this request: the newest player message carries a custom event (it already
    happened and is complete), so nothing is handed over again for it. Gold actions stay when the event speaks of gold.
    Empty when there is no custom event in the newest message. Never raises."""
    try:
        text = _newest_user_text(messages)
        if DONE_MARK not in text:
            return set()
        events = [part.split(DONE_MARK, 1)[1] for part in text.split('\n') if DONE_MARK in part]
        blocked = set(ITEM_ACTIONS)
        if not any(GOLD_WORDS.search(e) for e in events):
            blocked |= set(GOLD_ACTIONS)
        return blocked
    except Exception:
        return set()


def _without_kinds(tool, blocked: set):
    """A tool whose "kind" choice (World's Trade) lists blocked kinds: a copy without them, None when no kind is left.
    Any other tool comes back as it is."""
    function = tool.get('function') or tool
    kind = ((function.get('parameters') or {}).get('properties') or {}).get('kind')
    choices = kind.get('enum') if isinstance(kind, dict) else None
    if not isinstance(choices, list) or not blocked & set(choices):
        return tool
    left = [c for c in choices if c not in blocked]
    if not left:
        return None
    tool = copy.deepcopy(tool)
    (tool.get('function') or tool)['parameters']['properties']['kind']['enum'] = left
    return tool


def filter_tools(tools, messages) -> list:
    """tools without blocked_actions(messages); a tool with a "kind" choice keeps only the kinds not blocked."""
    blocked = blocked_actions(messages)
    if not blocked:
        return tools
    name = lambda t: (t.get('function') or t).get('name') if isinstance(t, dict) else None
    kept = [_without_kinds(t, blocked) if isinstance(t, dict) else t for t in tools or [] if name(t) not in blocked]
    return [t for t in kept if t is not None]


def established(store, name: str, limit: int = 8) -> list[str]:
    """The custom events this NPC was there for, as established facts (newest last, at most limit): they happened, and
    nothing that follows (a cancelled menu, a "(Nothing happened: ...)" line, what the NPC said) takes them back. Events
    that speak of gold or claim a game-owned fact (marriage, home, follower) are left out: those are only true when the
    game says so. For the Now writer and the memory writer."""
    if store is None or not name:
        return []
    rows = [r for r in load(store) if r.get('status') == 'active' and any(n.get('name') == name for n in r.get('npcs') or [])
            and not GOLD_WORDS.search(r['text']) and not GAME_OWNED.search(r['text'])]
    return [r['text'] for r in rows[-limit:]]


def established_text(store, name: str) -> str:
    """established() as one block for a writer's prompt ('' when there is none)."""
    facts = established(store, name)
    if not facts:
        return ''
    return ("Custom events that really happened to " + name + " (true and complete; never write that they did not happen, "
            "even if a later line says a gift menu or offer came to nothing):\n" + '\n'.join(f"- {f}" for f in facts))


# A trade action that came to nothing ("(Nothing happened: ...)", "...opened the gift menu but gave X nothing."), seen
# in a talk that has a custom event: it never undoes that event, and the model is told so with the line itself.
NOTHING = re.compile(r'^\(?\s*(nothing happened\b|.*\bgave \S.* nothing\b)', re.I)
NOTHING_NOTE = ' (This does not undo anything that already happened earlier in this talk.)'


# --- the journal ------------------------------------------------------------------------------------------------------

def journal_path(store) -> str:
    return os.path.join(store.root, FILE)


def load(store) -> list[dict]:
    """Every custom event of this save, oldest first; [] on any problem (a file that could not be read is then not
    saved over: lw_state.read_store_json)."""
    data = lw_state.read_store_json(journal_path(store), encoding='utf-8')
    rows = data.get('events') if isinstance(data, dict) else None
    return [r for r in rows if isinstance(r, dict) and isinstance(r.get('id'), str) and isinstance(r.get('text'), str)] \
        if isinstance(rows, list) else []


def save(store, rows: list[dict]) -> None:
    os.makedirs(store.root, exist_ok=True)
    path = journal_path(store)
    lw_state.guard_save(path)
    tmp = lw_state.temp_path(path)
    with open(tmp, 'w', encoding='utf-8', errors='replace') as f:
        json.dump({'events': rows[-MAX_EVENTS:]}, f, ensure_ascii=False, indent=1)
    lw_state.replace_file(tmp, path)


def current_talk() -> str:
    with _lock:
        if _talk['id'] is None:
            _talk['id'] = uuid.uuid4().hex[:12]
        return _talk['id']


def end_talk() -> None:
    with _lock:
        _talk['id'] = None


def live(row: dict) -> bool:
    """Still in the conversation going on now (not yet only in a memory)."""
    return row.get('talk') is not None and row.get('talk') == _talk['id']


# --- the dialogue_events hook -------------------------------------------------------------------------------------------

def process(events: list, ctx: dict, store=None, silent_default: bool = False, ask=None) -> list:
    """The in-game events about to go on a message: each custom event is written to the journal and replaced by what
    the model should read (a silent one gets SILENT_NOTE); 'undo' takes back the newest one of this talk (one in the same
    batch first) and never reaches the model. An undone event a trim mid-talk already put into a memory is taken out of
    that memory too (as a take-back on the Memory page; ask is the summary model for the rewrite), on a background
    thread. Other events pass unchanged. Never raises."""
    try:
        if ctx.get('is_first'):
            end_talk()  # a new talk, custom events or not: what came before belongs to the last one
        if not any(is_custom(e) for e in events or []):
            return _note_nothing(events, store)
        talk = current_talk()
        day, hour = memory.day_hour(ctx.get('game_days'))
        npcs = [{'name': c.name, 'ref_id': str(c.ref_id)} for c in ctx.get('characters') or [] if getattr(c, 'name', None)]
        out, added, taken_back, undone = [], [], [], 0
        for event in events:
            if not is_custom(event):
                out.append(event)
                continue
            kind, text = parse(event, silent_default)
            if kind == 'undo':
                if added:  # typed in the same batch: it never reaches the model
                    row, index = added.pop()
                    row.update(status='removed', removed_by='undo', removed_at=time.time(), gone=True)
                    out[index] = None
                    taken_back.append(row)
                else:
                    undone += 1
                continue
            if not text:
                continue
            shown = sent_text(text, kind)
            row = {'id': uuid.uuid4().hex[:12], 'text': text, 'original': text, 'mode': kind, 'shown': shown, 'day': day,
                   'hour': hour, 'at': time.time(), 'talk': talk, 'npcs': npcs, 'status': 'active', 'remembered': []}
            added.append((row, len(out)))
            out.append(shown + '\n')
        remembered = []  # (row, places): undone events already in a memory (a trim mid-talk wrote it)
        if store is not None:
            with _lock:
                rows = load(store)
                for _ in range(undone):
                    target = next((r for r in reversed(rows) if r.get('talk') == talk and r.get('status') == 'active'), None)
                    if target is None:
                        logger.log(23, 'Living World: undo typed, but this talk has no custom event to take back')
                        break
                    target.update(status='removed', removed_by='undo', removed_at=time.time())
                    logger.log(23, f"Living World: custom event taken back: {target['text']}")
                    if target.get('remembered'):
                        remembered.append((dict(target), [dict(p) for p in target['remembered']]))
                rows += taken_back + [row for row, _ in added]
                rows.sort(key=lambda r: r.get('at', 0))
                save(store, rows)
        for row, places in remembered:  # model requests: never on the request thread
            threading.Thread(target=_fix_places, args=(store, row, places, row['text'], None, ask), daemon=True,
                             name='living-world-undo').start()
        return _note_nothing([e for e in out if e is not None], store)
    except Exception as e:
        logger.warning(f"Living World: custom events could not be handled ({e}); they go on as typed")
        return events


def _nothing(event) -> bool:
    return isinstance(event, str) and not is_custom(event) and bool(NOTHING.match(event.strip()))


def _note_nothing(events: list, store) -> list:
    """A trade action that came to nothing, in a talk with an active custom event: the line says it undoes nothing
    (NOTHING_NOTE), so neither the reply nor the memory written from the talk takes the event back. Never raises."""
    try:
        talk = _talk['id']
        if store is None or talk is None or not any(_nothing(e) for e in events or []):
            return events
        if not any(r.get('talk') == talk and r.get('status') == 'active' for r in load(store)):
            return events
        return [e + NOTHING_NOTE if _nothing(e) and NOTHING_NOTE not in e else e for e in events]
    except Exception:
        return events


# --- the live talk ------------------------------------------------------------------------------------------------------

def _body_pattern(text: str) -> str:
    return r'\s+'.join(re.escape(word) for word in text.split())


def _changed(row: dict) -> bool:
    return row.get('status') == 'removed' or sent_text(row['text'], row.get('mode')) != row.get('shown')


def _rewrite(content: str, row: dict) -> str:
    body = _body_pattern(row.get('shown') or '')
    if not body:
        return content
    if row.get('status') == 'removed':
        # the event with Mantella's narration marks around it ([...], *...* or (...))
        return re.sub(r'(?:[*(\[]\s*)?' + body + r'(?:\s*[*)\]])?\s*', '', content, count=1)
    return re.sub(body, lambda m: sent_text(row['text'], row.get('mode')), content, count=1)


def _rewrite_message(content, rows: list) -> tuple:
    """One user message's content (a string, or content blocks changed in place) with each row's change applied, and
    whether a taken-back event was removed from it."""
    dropping = False
    for row in rows:
        if isinstance(content, str):
            changed = _rewrite(content, row)
            dropping |= row.get('status') == 'removed' and changed != content
            content = changed
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and isinstance(part.get('text'), str):
                    changed = _rewrite(part['text'], row)
                    dropping |= row.get('status') == 'removed' and changed != part['text']
                    part['text'] = changed
    return content, dropping


def fix_request(messages: list, store) -> None:
    """The 'extra_user_text' hook's messages (built new for each request): custom events of this talk that were edited
    or taken back are changed or left out in place. Never raises."""
    try:
        if store is None or _talk['id'] is None:
            return
        rows = [r for r in load(store) if live(r) and not r.get('gone') and _changed(r)]
        if not rows or not isinstance(messages, list):
            return
        users = [i for i, m in enumerate(messages) if isinstance(m, dict) and m.get('role') == 'user']
        kept, dropping = [], False
        for index, message in enumerate(messages):
            role = message.get('role') if isinstance(message, dict) else None
            if role != 'user':
                # the NPC's answer to an event that was taken back goes too (with its tool results), up to the next
                # user message: otherwise the model still hears them react to what never happened
                if not (dropping and role in ('assistant', 'tool')):
                    kept.append(message)
                continue
            content, dropping = _rewrite_message(message.get('content'), rows)
            if isinstance(content, str):
                message['content'] = content
            if dropping and index != users[-1] and not _has_text(content):
                continue  # nothing else was said in it: the whole message goes (never the newest one)
            kept.append(message)
        messages[:] = _join_users(kept)
    except Exception as e:
        logger.warning(f"Living World: could not apply custom event changes to this reply ({e})")


def _has_text(content) -> bool:
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        return any(not (isinstance(p, dict) and isinstance(p.get('text'), str) and not p['text'].strip()) for p in content)
    return content is not None


def _join_users(messages: list) -> list:
    """Two user messages in a row (an answer between them was left out) become one, as every service expects turns."""
    out = []
    for message in messages:
        last = out[-1] if out else None
        if (isinstance(message, dict) and isinstance(last, dict) and message.get('role') == 'user' and last.get('role') == 'user'
                and isinstance(message.get('content'), str) and isinstance(last.get('content'), str)):
            out[-1] = dict(last, content=(last['content'].rstrip() + '\n' + message['content'].lstrip()).strip())
            continue
        out.append(message)
    return out


def _thread_list(thread):
    """The list inside Mantella's message_thread (or a test's), so messages can be taken out; None if there is none."""
    for name in ('_message_thread__messages', 'messages'):
        found = getattr(thread, name, None)
        if isinstance(found, list):
            return found
    return None


def _is_user(message) -> bool:
    return isinstance(getattr(message, '_UserMessage__ingame_events', None), list)


def fix_thread(thread, store) -> int:
    """Before a talk is summarized: the custom events of this talk that were edited or taken back are changed in, or
    taken out of, Mantella's own conversation, so the memory and the rest of the talk see the change. Returns how many
    were changed. Never raises."""
    try:
        if store is None or thread is None:
            return 0
        with _lock:
            rows = load(store)
            todo = [r for r in rows if live(r) and not r.get('gone') and _changed(r)]
            if not todo:
                return 0
            changed, emptied = 0, []
            for i in range(len(thread)):
                events = getattr(thread[i], '_UserMessage__ingame_events', None)
                if not isinstance(events, list):
                    continue
                removed_here = False
                for row in todo:
                    shown = ' '.join((row.get('shown') or '').split())
                    for j, event in enumerate(events):
                        if ' '.join(str(event).split()) != shown:
                            continue
                        if row.get('status') == 'removed':
                            del events[j]
                            row['gone'] = True
                            removed_here = True
                        else:
                            row['shown'] = sent_text(row['text'], row.get('mode'))
                            events[j] = row['shown'] + '\n'
                        changed += 1
                        break
                if removed_here:
                    emptied.append((i, not events and not str(getattr(thread[i], 'text', '') or '').strip()))
            _drop_answers(thread, emptied)
            save(store, rows)
            return changed
    except Exception as e:
        logger.warning(f"Living World: could not apply custom event changes before the memory was written ({e})")
        return 0


def _drop_answers(thread, removed: list) -> None:
    """After events were taken out of user messages (removed: (index, now empty)): the NPC's answers to each, up to the
    next user message, leave the talk too, and so does a user message nothing is left in, so the memory written from
    it never holds a reaction to what never happened."""
    messages = _thread_list(thread)
    if messages is None or not removed:
        return
    gone = set()
    for index, empty in removed:
        if empty:
            gone.add(index)
        for after in range(index + 1, len(messages)):
            if _is_user(messages[after]) or type(messages[after]).__name__ == 'SystemMessage':
                break
            gone.add(after)
    messages[:] = [m for i, m in enumerate(messages) if i not in gone]


def after_summary(ctx: dict, store) -> None:
    """After memory.summarize: each custom event of this talk notes which memory entry it went into, per NPC, so a
    later edit can find it. The talk ends here unless this was a trim mid-talk or an NPC leaving a talk that goes on."""
    try:
        talk = _talk['id']
        if store is not None and talk is not None:
            day, hour = memory.day_hour(ctx.get('end_timestamp'))
            with _lock:
                rows = load(store)
                mine = [r for r in rows if r.get('talk') == talk and r.get('status') == 'active']
                if mine:
                    for npc in ctx.get('npcs_to_summarize') or []:
                        mem = memory._peek(store, npc.name, npc.ref_id)
                        entry = next((e for e in reversed(mem['recent']) if not e.get('hidden')
                                      and (e.get('day'), e.get('hour')) == (day, hour)), None)
                        if entry is None:
                            continue
                        memory_id = archive.entry_id(entry)
                        for row in mine:
                            known = [m for m in row.setdefault('remembered', []) if m.get('memory_id') == memory_id]
                            if not known:
                                row['remembered'].append({'name': npc.name, 'ref_id': str(npc.ref_id), 'memory_id': memory_id})
                    save(store, rows)
        if not ctx.get('is_reload') and not ctx.get('departed'):
            end_talk()
    except Exception as e:
        logger.warning(f"Living World: could not note which memories hold this talk's custom events ({e})")


# --- edits from the Memory tab ------------------------------------------------------------------------------------------

def find(store, event_id: str) -> dict | None:
    return next((r for r in load(store) if r.get('id') == event_id), None)


def _memory_entry(store, name: str, ref_id: str, memory_id: str) -> tuple[dict | None, str, bool]:
    """(entry, its text, still in recent) for a memory id, from the memory file or the archive."""
    mem = store.load(name, ref_id)
    for entry in mem['recent']:
        if archive.entry_id(entry) == memory_id and not entry.get('hidden'):
            return entry, memory.entry_text(entry, store), True
    try:
        db = store.archive_for(name, ref_id)
        for row in db.rows() if db.exists() else []:
            if row.get('id') == memory_id:
                return row, row.get('text') or '', False
    except Exception:
        pass
    return None, '', False


def _rewritten(ask, name: str, text: str, old: str, new: str | None, prompt: str | None = None) -> str:
    """One memory rewritten by the summary model (ask) without old, or with new in its place; prompt, when given, is
    another such request with {name} and {old}. '' when there is no model, it fails or it changed nothing."""
    if ask is None:
        return ''
    if prompt is not None:
        prompt = prompt.format(name=name, old=old)
    else:
        prompt = (REWRITE_EDIT.format(name=name, old=old, new=new) if new is not None else REWRITE_REMOVE.format(name=name, old=old))
    try:
        reply = ' '.join(str(ask(prompt, text) or '').split()).strip('"')
    except Exception as e:
        logger.warning(f"Living World: could not rewrite {name}'s memory ({e})")
        return ''
    if not reply or memory._norm(reply) == memory._norm(text):
        return ''
    return reply[:memory.MAX_ENTRY_CHARS]


def _hide_one(store, name: str, ref_id: str, memory_id: str, note: str, day: int = -1) -> bool:
    """Hides exactly that memory through memory.hide_matching (its own text is the closest match); a different one it
    picked is unhidden again at once."""
    entry, text, _ = _memory_entry(store, name, ref_id, memory_id)
    if entry is None or not text:
        return False
    hit = memory.hide_matching(store, name, ref_id, text, limit=1, by=HIDDEN_BY, note=note, day=day)
    for wrong in [h for h in hit if h['id'] != memory_id]:
        memory.unhide(store, name, ref_id, wrong['id'])
    return bool(hit) and hit[0]['id'] == memory_id


def _fix_memory(store, row: dict, place: dict, old: str, new: str | None, ask) -> str:
    """One NPC's memory of a changed custom event: hidden (Unhide brings it back) and, with the model, replaced by the
    same memory rewritten. Without the model an edit adds a short correction instead and leaves the memory as it was;
    a take-back also hides such corrections. Each change is noted in place['fixes'], so restore() can undo it."""
    name, ref_id = place['name'], place['ref_id']
    before = place.get('memory_id', '')
    entry, text, in_recent = _memory_entry(store, name, ref_id, before)
    if entry is None:
        return f"{name}: that memory is no longer there (deleted or already hidden)."
    replacement = _rewritten(ask, name, text, old, new)
    keep_old = new is not None and not replacement
    if keep_old:  # an edit with no model: add what really happened, hide nothing
        replacement = f"What really happened that day: {new} (not: {old})"
    hidden = []
    if not keep_old:
        note = f"custom event {'edited' if new is not None else 'taken back'}: {old}"
        if not _hide_one(store, name, ref_id, before, note, row.get('day', -1)):
            return f"{name}: could not find that memory to hide; nothing changed."
        hidden.append(before)
        if new is None:  # corrections added by earlier edits go too
            for fix in place.get('fixes', []):
                if fix.get('correction') and fix.get('added') and _hide_one(store, name, ref_id, fix['added'], note, row.get('day', -1)):
                    hidden.append(fix['added'])
    new_id = ''
    if replacement:
        added = {k: entry.get(k) for k in memory.REWRITE_KEYS if entry.get(k) is not None}
        added.update(text=replacement, custom_event=row['id'])
        try:  # stamped with the running talk, so it rolls back with the save like any memory
            branch = timeline.current(store)
            added.update(branch.stamp() if branch is not None else {})
        except Exception:
            pass
        new_id = archive.entry_id(added)
        with store.lock(name, ref_id):
            mem = store.load(name, ref_id)
            if in_recent:
                spot = next((i for i, e in enumerate(mem['recent']) if archive.entry_id(e) == before), len(mem['recent']) - 1)
                mem['recent'].insert(spot + 1, added)
                store.save(name, ref_id, mem)
            else:
                store.archive_for(name, ref_id).add([(added, replacement)], embed.current())
    place.setdefault('fixes', []).append({'kind': 'edit' if new is not None else 'remove', 'before': before, 'hidden': hidden,
                                          'added': new_id, 'correction': keep_old})
    if new_id and not keep_old:
        place['memory_id'] = new_id  # a later change works on the rewritten one
    if keep_old:
        return f"{name}: no model reachable, so a correction was added to their memory."
    if replacement:
        return f"{name}: the memory was rewritten (the old one is hidden; Unhide in Memories on the NPCs page brings it back)."
    return (f"{name}: the memory of that talk is hidden (no model reachable to rewrite it without the event); Unhide in "
            f"Memories on the NPCs page brings it back.")


def change(store, event_id: str, text: str | None = None, mode: str | None = None, remove: bool = False, ask=None) -> str:
    """Edits a custom event's text or mode, or takes it back (remove). In the talk going on now the change applies from
    the next reply and goes into its memory; for a memory already written, see _fix_memory. Returns what was done."""
    with _lock:
        rows = load(store)
        row = next((r for r in rows if r.get('id') == event_id), None)
        if row is None:
            return 'That custom event is no longer in the list.'
        if row.get('status') == 'removed':
            return 'That custom event was already taken back.'
        old = row['text']
        new_text = ' '.join(str(text or '').split())[:MAX_TEXT] if text is not None else old
        new_mode = mode if mode in (SILENT, NARRATED) else row.get('mode', NARRATED)
        if not remove and not new_text:
            remove = True
        if not remove and new_text == old and new_mode == row.get('mode'):
            return 'Nothing changed.'
        if remove:
            row.update(status='removed', removed_by='tab', removed_at=time.time())
        else:
            row.update(text=new_text, mode=new_mode, edited_at=time.time())
        notes = []
        if live(row) and not row.get('remembered'):
            notes.append('Applies from the next reply of this talk and goes into its memory.')
        save(store, rows)
        places = [dict(p) for p in row.get('remembered') or []]
        snapshot = dict(row)
    if new_text != old or remove:  # outside the lock: a model call must not hold up a talk's events
        notes += _fix_places(store, snapshot, places, old, None if remove else new_text, ask)
    done = 'Taken back.' if remove else 'Saved.'
    return ' '.join([done] + notes)


def _fix_places(store, row: dict, places: list[dict], old: str, new: str | None, ask) -> list[str]:
    """_fix_memory for every memory an event went into (places, copies of row['remembered']), then the journal row
    notes what was done. Returns a note per memory. Never raises."""
    notes = []
    try:
        for place in places:
            try:
                notes.append(_fix_memory(store, row, place, old, new, ask))
            except Exception as e:
                notes.append(f"{place.get('name', '?')}: could not change the memory ({e}).")
        with _lock:
            rows = load(store)
            current = next((r for r in rows if r.get('id') == row['id']), None)
            if current is not None:
                current['remembered'] = places
                save(store, rows)
    except Exception as e:
        logger.warning(f"Living World: could not change the memories of a custom event ({e})")
    return notes


def restore(store, event_id: str) -> str:
    """Brings a taken-back custom event back: hidden memories are unhidden and memories rewritten for it are hidden. In
    the talk going on now it is sent again, unless it was already taken out of the conversation."""
    with _lock:
        rows = load(store)
        row = next((r for r in rows if r.get('id') == event_id), None)
        if row is None or row.get('status') != 'removed':
            return 'Only a taken-back custom event can be restored.'
        if row.get('gone') and live(row):
            return 'That event was already taken out of this talk; type it again instead.'
        row.update(status='active', restored_at=time.time())
        notes = []
        for place in row.get('remembered') or []:
            fixes = place.get('fixes') or []
            if not fixes or fixes[-1].get('kind') != 'remove':
                continue
            fix = fixes.pop()  # undo the take-back only; earlier edits stay
            name, ref_id = place['name'], place['ref_id']
            if fix.get('added'):
                _hide_one(store, name, ref_id, fix['added'], 'custom event restored')
            for hidden_id in fix.get('hidden') or []:
                memory.unhide(store, name, ref_id, hidden_id)
            place['memory_id'] = fix.get('before') or place.get('memory_id')
            notes.append(f"{name}'s memory is back as it was.")
        save(store, rows)
    return ' '.join(['Restored.'] + notes)


# --- the Memory tab's list ----------------------------------------------------------------------------------------------

def when(row: dict) -> str:
    return memory.header(row.get('day', -1), row.get('hour', -1)).strip('[]') or 'unknown time'


def who(row: dict) -> str:
    return ', '.join(n.get('name', '?') for n in row.get('npcs') or []) or 'nobody'


def listing(store, npc: str | None = None, limit: int = 50) -> list[dict]:
    """Newest first; npc: only events with that NPC there."""
    rows = list(reversed(load(store))) if store is not None else []
    if npc:
        rows = [r for r in rows if any(n.get('name') == npc for n in r.get('npcs') or [])]
    return rows[:limit]


def npc_names(store) -> list[str]:
    return sorted({n.get('name') for r in load(store) for n in r.get('npcs') or [] if n.get('name')}) if store is not None else []


def label(row: dict) -> str:
    text = row['text'] if len(row['text']) <= 70 else row['text'][:67] + '...'
    return f"{when(row)} - {who(row)}: {text} [{row['id']}]"


def table(rows: list[dict]) -> list[list]:
    status = lambda r: 'taken back' if r.get('status') == 'removed' else (
        'in this talk' if live(r) and not r.get('remembered') else ('remembered' if r.get('remembered') else 'sent'))
    return [[when(r), who(r), 'silent' if r.get('mode') == SILENT else 'narrated', status(r), r['text']] for r in rows]
