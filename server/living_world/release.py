"""Forget and release, and the Hub's true record of them.

Forget (by an absolute command or from the Hub) keeps HIDING memories: nothing is deleted and Unhide brings them back.
Each forget writes one line to the true record (what was hidden, which game days, by whom) and has a choice:
    gap    the NPC notices: a line goes after their Now paragraph. A whole period wiped (a release that forgets the
           period, a day range) says which days ("has no memory of days 12 to 40, and it frightens her"); one forgotten
           thing only that something is missing. Pronouns follow the sex the game sends ("them" only when unknown).
    clean  they notice nothing: the default for one forgotten thing (they simply do not remember it)
Release ends an absolute command with one of three choices:
    spell    remembers, and knows it was a spell: the memories from that time are marked "(while under <player>'s
             spell)", what the command hid comes back, and the Now paragraph is told the spell lifted
    forget   forgets the whole period: the memories from that time are hidden (with a gap or clean)
    believe  keeps believing: memories and Now stay as they are
Every release ends the command's facts lines and brings back the lines it put on hold (facts_history.end_cause). When a
marriage was made under the command, an end_marriage request for the Relationships module is written only when asked
(end_marriage=True); Relationships asks the player once and calls M.A.R.A.S. The Hub never calls M.A.R.A.S itself.

In game, the Living World hotkey's menu on a commanded NPC offers the same three choices (MLW_Release.psc): it writes
releases.json in the channel folder, read here at the next request (poll_game). The in-game path always writes the
marriage request when there is a marriage to end: the Relationships box is the question.

The true record: <conversations>/<world>/living_world/true_record.json, per save; the NPC is never sent it."""
import json
import logging
import os
import threading
import time
import uuid

from . import bio_evolve, command, contracts, facts_history, lw_state, memory

logger = logging.getLogger('Mantella')

RECORD_FILE = 'true_record.json'
GAME_FILE = 'releases.json'
CHOICES = ('spell', 'forget', 'believe')
CHOICE_TEXT = {'spell': 'remembers, and knows it was a spell', 'forget': 'forgets the whole period',
               'believe': 'keeps believing'}
MODES = ('gap', 'clean')
WORLD_CHOICE = {'spell': 'aware', 'forget': 'forget', 'believe': 'keep'}  # worldlog.from_command_release's names
MAX_RECORD = 500
MAX_SEEN = 200
HIDDEN_BY = 'forget'

_lock = threading.RLock()
# releases whose effect is not complete yet, per NPC (_key): the line for their next request's newest message, and a
# release made while they were in the running talk, finished when that talk is saved (after_talk)
_pending = {'tell': {}, 'talk': {}}


# --- the true record -------------------------------------------------------------------------------------------------------

def record_path(store) -> str:
    return os.path.join(store.root, RECORD_FILE)


def load_record(store) -> dict:
    data = lw_state.read_store_json(record_path(store))  # a file that could not be read is then not saved over
    data = data if isinstance(data, dict) else {}
    rows = [r for r in data.get('rows') or [] if isinstance(r, dict) and r.get('id')]
    seen = [str(s) for s in data.get('seen') or [] if isinstance(s, (str, int))]
    return {'rows': rows, 'seen': seen}


def _save_record(store, data: dict) -> None:
    path = record_path(store)
    lw_state.guard_save(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = lw_state.temp_path(path)
    with open(temp, 'w', encoding='utf-8') as f:
        json.dump({'rows': data['rows'][-MAX_RECORD:], 'seen': data['seen'][-MAX_SEEN:]}, f, ensure_ascii=False, indent=1)
    lw_state.replace_file(temp, path)


def write_record(store, kind: str, name: str, ref_id: str, what: str, by: str, days=None, **extra) -> dict:
    """One line of the true record: {id, kind, name, ref_id, what, by, days: [from, to], at, ...}."""
    row = {'id': uuid.uuid4().hex[:10], 'kind': kind, 'name': name, 'ref_id': str(ref_id), 'what': str(what)[:400],
           'by': by, 'days': list(days) if days else [], 'at': time.time(), **extra}
    with _lock:
        data = load_record(store)
        data['rows'].append(row)
        _save_record(store, data)
    return row


def record_rows(store, name: str | None = None, ref_id: str | None = None) -> list[dict]:
    """The true record, newest first; with name (and ref id) only that NPC's."""
    rows = list(reversed(load_record(store)['rows']))
    if name:
        key = facts_history.npc_key(name, ref_id or '')
        rows = [r for r in rows if facts_history.npc_key(r.get('name'), r.get('ref_id') if ref_id else '') ==
                (key if ref_id else facts_history.npc_key(name, ''))]
    return rows


# --- forget ------------------------------------------------------------------------------------------------------------------

def _days(rows: list[dict]) -> list[int]:
    days = sorted(memory._int(r.get('day')) for r in rows if memory._int(r.get('day')) >= 0)
    return [days[0], days[-1]] if days else []


def pronouns(store=None, name: str = '', ref_id: str = '', speakers=None) -> tuple[str, str]:
    """(object, possessive) for this NPC from the sex the game sends: ('her', 'her'), ('him', 'his'), and ('them',
    'their') only when it is unknown. Looked up in the speakers given (game speaker dicts), then the world log's people
    (worldlog.read_people, kept from the game's npc files). Never raises."""
    sex = ''
    key = facts_history.short_ref(ref_id)
    for s in speakers or []:
        if isinstance(s, dict) and ((key and facts_history.short_ref(s.get('ref_id')) == key)
                                    or (not key and str(s.get('name') or '').lower() == str(name or '').lower())):
            sex = contracts.low(s.get('sex'))
            break
    if sex not in ('male', 'female') and store is not None:
        try:
            from . import worldlog
            known = worldlog.lookup(worldlog.read_people(store), worldlog.person(name, '', key)) or {}
            sex = contracts.low(known.get('sex'))
        except Exception:
            sex = ''
    return {'female': ('her', 'her'), 'male': ('him', 'his')}.get(sex, ('them', 'their'))


def gap_text(name: str, days: list[int], pronoun: str = 'them', period: bool = True) -> str:
    """The line after the Now paragraph when a forget leaves a gap. period: a whole time was wiped (a release that
    forgets the whole period, a day range): "has no memory of days 12 to 40"; else only that something is missing."""
    possessive = {'her': 'her', 'him': 'his'}.get(pronoun, 'their')
    if not period or not days:
        return f"{name} knows something is missing from {possessive} memory, and it frightens {pronoun}."
    span = f"day {days[0]}" if days[0] == days[1] else f"days {days[0]} to {days[1]}"
    return f"{name} has no memory of {span}, and it frightens {pronoun}."


def note_forget(store, name: str, ref_id: str, hidden: list[dict], what: str, by: str, mode: str = 'clean',
                pronoun: str = '', period: bool = False, speakers=None, days=None, always: bool = False, **extra) -> dict | None:
    """After memories were hidden: the true record's line and, with mode gap, the gap after the Now paragraph. A single
    forgotten thing is clean by default (they simply do not remember it and do not notice); gap is for a whole period
    wiped (period=True) or words that ask them to notice. pronoun: '' looks it up from the game's sex (pronouns). days:
    the period's [first, last] day (else the hidden memories' days); always: written even with nothing hidden (a period
    whose only trace was the talk going on)."""
    if not hidden and not always:
        return None
    mode = mode if mode in MODES else 'clean'
    days = list(days) if days else _days(hidden)
    row = write_record(store, 'forget', name, ref_id, what, by, days, mode=mode, memories=[h.get('id') for h in hidden], **extra)
    if mode == 'gap':
        pronoun = pronoun or pronouns(store, name, ref_id, speakers)[0]
        bio_evolve.add_gap(store, name, ref_id, gap_text(name, days, pronoun, period), days[-1] if days else -1)
    return row


def forget(store, name: str, ref_id: str, what: str = '', ids: list[str] | None = None, mode: str = 'clean', by: str = 'you',
           limit: int = 3, pronoun: str = '') -> dict:
    """Hides memories of one NPC: the ones with these ids, else up to limit closest to what. Writes the true record and,
    with mode gap, a line after their Now paragraph that something is missing; clean (the default) they do not notice.
    Returns {hidden: [...], record}."""
    hidden = []
    if ids:
        for memory_id in ids:
            hidden += _hide_id(store, name, ref_id, memory_id, f"forgotten: {what}" if what else 'forgotten')
    elif what:
        hidden = memory.hide_matching(store, name, ref_id, what, limit=max(1, limit), by=HIDDEN_BY, note=f"forgotten: {what}")
    if not hidden:
        return {'hidden': [], 'record': None}
    if not what:
        what = '; '.join(' '.join(str(h.get('text') or '').split())[:80] for h in hidden[:3])
    row = note_forget(store, name, ref_id, hidden, what, by, mode, pronoun)
    first = min((memory._int(h.get('day')) for h in hidden if memory._int(h.get('day')) >= 0), default=-1)
    if first >= 0:
        bio_evolve.roll_back(store, name, ref_id, first)
    bio_evolve.mark_due(store, name, ref_id, f"some memories were taken away ({row['what'][:80]})" if mode == 'gap'
                        else 'some memories are gone; they do not notice')
    return {'hidden': hidden, 'record': row}


def _hide_id(store, name: str, ref_id: str, memory_id: str, note: str) -> list[dict]:
    """Hides exactly one memory by id (its own text is the closest match); a different one picked is unhidden at once."""
    text = ''
    mem = store.load(name, ref_id)
    for entry in mem['recent']:
        if memory.archive.entry_id(entry) == memory_id and not entry.get('hidden'):
            text = memory.entry_text(entry, store)
    if not text:
        try:
            db = store.archive_for(name, ref_id)
            text = next((r.get('text') or '' for r in (db.rows() if db.exists() else []) if r.get('id') == memory_id), '')
        except Exception:
            text = ''
    if not text:
        return []
    hit = memory.hide_matching(store, name, ref_id, text, limit=1, by=HIDDEN_BY, note=note, only={memory_id})
    return [h for h in hit if h['id'] == memory_id]


def delete_memory(store, name: str, ref_id: str, memory_id: str) -> str:
    """The Hub's Delete (the user only; commands never delete): removes one memory for good, through the memory page's
    own delete (a backup is kept), and writes the true record. Returns the removed text, '' when it was not found."""
    from . import memory_ui
    mem = store.load(name, ref_id)
    choices = memory_ui.memory_choices(mem)
    index = next((i for i, e in enumerate(mem['recent']) if memory.archive.entry_id(e) == memory_id), None)
    if index is None:
        return ''
    label = next((c for c in choices if c.startswith(f"{index + 1}. ")), None)
    removed = memory_ui.delete_one(store, name, ref_id, label) if label else ''
    if removed:
        write_record(store, 'delete', name, ref_id, removed.split('\n')[0][:200], 'you',
                     [memory._int(mem['recent'][index].get('day'))])
    return removed


# --- release -----------------------------------------------------------------------------------------------------------------

def _record_npcs(record: dict, npc=None) -> list[dict]:
    if npc is None:
        return list(record['npcs'])
    name, ref = (npc.get('name'), npc.get('ref_id')) if isinstance(npc, dict) else (getattr(npc, 'name', ''), getattr(npc, 'ref_id', ''))
    key = facts_history.short_ref(ref)
    return [n for n in record['npcs'] if (key and facts_history.short_ref(n['ref_id']) == key)
            or (not key and str(n['name']).lower() == str(name or '').lower())]


def marriage_under(record: dict, npc: dict, speaker: dict | None = None, rows=None) -> dict | None:
    """The marriage (or engagement) of this NPC made while this command was in force, still their latest status, from
    Relationships' marriages.json; None when there is none or the NPC's base id is unknown."""
    base = contracts.base_key((speaker or {}).get('base_id') or npc.get('base_id'))
    if not base:
        return None
    return contracts.made_under_command(base, command._float(record.get('given')), None, rows)


def release_command(store, command_id: str, choice: str, npc=None, end_marriage: bool = False, mode: str = 'gap',
                    player: str = '', today=None, speakers=None, by: str = 'you', ask=None, language: str = 'English',
                    in_talk=None) -> dict:
    """Releases an absolute command (for every NPC it binds, or only npc: {name, ref_id}) with one of CHOICES. Returns
    {ok, message, npcs, ended, returned, requests}. speakers: game speaker dicts (for base ids); end_marriage writes the
    Relationships request for a marriage made under the command. ask (the summary model) writes the Now paragraphs at
    once, on the background worker; without it they are written after the next talk. It acts at once: the NPC's next
    request is told what just happened (newest_text). in_talk: the speakers of the talk going on (None: read from the
    game while a talk is going on); an NPC released in it has that talk's memory marked or hidden when it is saved
    (after_talk), and a forget's gap line waits for it."""
    choice = contracts.low(choice)
    if choice not in CHOICES:
        logger.warning(f"Living World: a release with an unknown choice ({choice}) was not used")
        return {'ok': False, 'message': f"Unknown choice: {choice}"}
    player = player or lw_state.load_player_name()
    request_player = player  # the real name or '' (any character), never the display fallback below
    player = player or 'the player'
    today = lw_state.load_today() if today is None else today
    with command._lock:
        data = command.load(store)
        record = next((c for c in data['commands'] if c['id'] == command_id), None)
        if record is None:
            return {'ok': False, 'message': 'That command is no longer in force.'}
        npcs = _record_npcs(record, npc)
        if not npcs:
            return {'ok': False, 'message': 'That command does not bind them.'}
        keep = [n for n in record['npcs'] if n not in npcs]
        hidden_mine = [h for h in record['hidden'] if any(h['name'] == n['name'] and h['ref_id'] == n['ref_id'] for n in npcs)]
        if keep:
            record['npcs'] = keep
            record['hidden'] = [h for h in record['hidden'] if h not in hidden_mine]
        else:
            data['commands'].remove(record)
            if choice == 'spell':  # what the command's words wiped beyond them comes back with the spell lifting
                command.undo_scope(store, record)
        command.add_ended(data, record, npcs, choice, today)
        command.save(store, data)
    given_day = int(command._float(record.get('given'))) + memory.MANTELLA_DAY if command._float(record.get('given')) >= 0 else -1
    today_m = today + memory.MANTELLA_DAY if isinstance(today, int) else -1
    days = [given_day, today_m] if given_day >= 0 else []
    label = f"while under {player}'s spell"
    keys = [facts_history.npc_key(n['name'], n['ref_id']) for n in npcs]
    facts = facts_history.end_cause(store, f"command:{record['id']}", today, keys)
    requests, notes = [], []
    talking = {_key(t) for t in (_talk_speakers() if in_talk is None else in_talk or [])}
    for n in npcs:
        name, ref = n['name'], n['ref_id']
        here = _key(n) in talking
        if choice in ('spell', 'forget'):
            pron = pronouns(store, name, ref, speakers)[0]
            with _lock:
                _pending['tell'][_key(n)] = lifted_text(name, player, choice, pron, days[0] if days else -1, here)
                if here:
                    _pending['talk'][_key(n)] = {'name': name, 'ref_id': ref, 'command': record['id'], 'choice': choice,
                                                 'label': label, 'mode': mode, 'days': days, 'by': by, 'hidden': [],
                                                 'what': f"everything while under the command \"{record['text'][:80]}\"",
                                                 'speakers': list(speakers or [])}
        if choice == 'spell':
            for h in hidden_mine:
                if h['name'] == name and h['ref_id'] == ref:
                    memory.unhide(store, name, ref, h['id'])
            marked = mark_spell(store, name, ref, record['id'], label)
            bio_evolve.mark_due(store, name, ref, f"the absolute command was released: {name} {CHOICE_TEXT['spell']}",
                                note=f"The spell {player} cast on {name} has lifted{' (game days ' + str(days[0]) + ' to ' + str(days[1]) + ')' if days else ''}: "
                                     f"{name} now knows that everything {name} did and felt then was {player}'s doing, remembers it, "
                                     f"and reacts in character.")
            notes.append(f"{name}: {marked} memories marked")
        elif choice == 'forget':
            period = _period_memories(store, name, ref, record['id'], given_day)
            hidden = []
            for memory_id in period:
                hidden += _hide_id(store, name, ref, memory_id, f"released command forgotten: {record['text'][:80]}")
            if here:  # the talk going on is part of the period: the gap is written when its memory is saved
                with _lock:
                    _pending['talk'][_key(n)]['hidden'] = hidden
            else:
                note_forget(store, name, ref, hidden, f"everything while under the command \"{record['text'][:80]}\"",
                            by, mode, period=True, speakers=speakers, command_id=record['id'], days=days or None)
            for snap in record.get('bio_before') or []:
                if snap.get('name') == name and snap.get('ref_id') == ref:
                    bio_evolve.restore(store, name, ref, snap)
            bio_evolve.mark_due(store, name, ref, f"the absolute command was released: {name} {CHOICE_TEXT['forget']}")
            notes.append(f"{name}: {len(hidden)} memories hidden")
        else:
            notes.append(f"{name}: nothing changes")
        speaker = next((s for s in speakers or [] if facts_history.short_ref(s.get('ref_id')) == facts_history.short_ref(ref)), None)
        married = marriage_under(record, n, speaker)
        rid = ''
        if married is not None and end_marriage:
            rid = contracts.write_request('end_marriage', married['base'], married.get('name') or name,
                                          f"made while an absolute command was in force; released ({CHOICE_TEXT[choice]})",
                                          request_player)
            if rid:
                requests.append(rid)
        write_record(store, 'release', name, ref, record['text'], by, days, choice=choice, command_id=record['id'],
                     mode=mode if choice == 'forget' else '', marriage=bool(married), end_marriage_request=rid)
    try:  # the world log: the Hub's record of the release (never news: nobody is told through the rings)
        from . import worldlog
        worldlog.from_command_release(store, dict(record, npcs=npcs), WORLD_CHOICE[choice], player, today, speakers)
    except Exception as e:
        logger.warning(f"Living World: the release could not be written to the world log ({e})")
    if ask is not None and choice != 'believe':
        people = [type('NPC', (), {'name': n['name'], 'ref_id': n['ref_id'], 'bio': ''})() for n in npcs]
        # callers pass ask(prompt, text); bio_evolve calls ask(text, prompt)
        bio_evolve.write_now(store, people, lambda text, prompt: ask(prompt, text), language)
    logger.log(23, f"Living World: absolute command released ({CHOICE_TEXT[choice]}) for "
                   f"{', '.join(n['name'] for n in npcs)}: {record['text'][:60]}")
    return {'ok': True, 'message': f"Released ({CHOICE_TEXT[choice]}). " + '; '.join(notes), 'npcs': npcs,
            'ended': facts['ended'], 'returned': facts['returned'], 'requests': requests}


def _period_memories(store, name: str, ref_id: str, command_id: str, given_day: int) -> list[str]:
    """Ids of this NPC's shown memories saved under the command, or dated on or after the day it was given."""
    out = []
    for entry in store.load(name, ref_id)['recent']:
        if entry.get('hidden'):
            continue
        if entry.get('command') == command_id or (given_day >= 0 and memory._int(entry.get('day')) >= given_day):
            out.append(memory.archive.entry_id(entry))
    return out


def _key(npc) -> str:
    """One NPC, as a game speaker dict, {name, ref_id}, (name, ref) or a Mantella character: their short ref id, else
    their name."""
    if isinstance(npc, (tuple, list)):
        name, ref = (list(npc) + ['', ''])[:2]
    elif isinstance(npc, dict):
        name, ref = npc.get('name'), npc.get('ref_id')
    else:
        name, ref = getattr(npc, 'name', ''), getattr(npc, 'ref_id', '')
    return facts_history.short_ref(ref) or 'name:' + str(name or '').strip().lower()


def _talk_speakers() -> list:
    """The game's speakers of the talk going on, [] when none is."""
    try:
        return lw_state.load_conversation() if bio_evolve.busy() else []
    except Exception:
        return []


def lifted_text(name: str, player: str, choice: str, pronoun: str = 'them', day: int = -1, in_talk: bool = False) -> str:
    """The one line for the newest message of the NPC's next request after a release (plain direction, never a
    "Name: line" pattern): spell, they remember and know it was a spell; forget, they remember nothing of the period,
    and with in_talk the lines already said in this talk are named as forgotten too."""
    subject = {'her': 'she', 'him': 'he'}.get(pronoun, 'they')
    verb = 'react' if subject == 'they' else 'reacts'
    if choice == 'spell':
        return (f"(The spell {player} had on {name} has just lifted. {name} remembers all of it and knows it was a "
                f"spell, not {name}'s own choice; {subject} {verb} to that in character.)")
    since = f"day {day}" if isinstance(day, int) and day >= 0 else 'the moment the spell began'
    text = f"(The spell {player} had on {name} has just lifted. {name} has no memory of anything from {since} until now."
    if in_talk:
        text += (f" That includes everything {name} said earlier in this talk: those words were spoken, but {name} no "
                 f"longer remembers them and must not refer to them.")
    return text + ')'


def newest_text(speakers) -> str:
    """The lines for the newest message: each NPC here released since their last request, once."""
    lines = []
    with _lock:
        for s in speakers or []:
            line = _pending['tell'].pop(_key(s), None)
            if line:
                lines.append(line)
    return '\n'.join(lines)


def released_in_talk(character) -> str:
    """The id of the command this NPC was released from during the talk going on ('' when none): the talk's memory is
    made under it (memory.summarize tags it, after_talk marks or hides it)."""
    with _lock:
        found = _pending['talk'].get(_key(character))
    return found['command'] if found else ''


def after_talk(store, characters, final: bool = True) -> int:
    """The talk was just saved into memory: for each NPC released during it, its memory made under the command (tagged
    by released_in_talk) is marked "(while under <player>'s spell)" (spell) or hidden, with the forget's true record
    line and gap (forget). final=False (a summary in the middle of a long talk) keeps the release for the rest of the
    talk. Returns how many NPCs were finished. Never raises."""
    done = 0
    for character in characters or []:
        try:
            with _lock:
                item = _pending['talk'].get(_key(character))
            if item is None:
                continue
            name, ref = item['name'], item['ref_id']
            if item['choice'] == 'spell':
                mark_spell(store, name, ref, item['command'], item['label'])
            else:
                for memory_id in _period_memories(store, name, ref, item['command'], -1):
                    item['hidden'] = item['hidden'] + _hide_id(store, name, ref, memory_id, 'released command forgotten')
            if not final:
                continue
            with _lock:
                _pending['talk'].pop(_key(character), None)
            if item['choice'] == 'forget':
                note_forget(store, name, ref, item['hidden'], item['what'], item['by'], item['mode'], period=True,
                            speakers=item['speakers'], command_id=item['command'], days=item['days'] or None, always=True)
            done += 1
        except Exception as e:
            logger.warning(f"Living World: a release could not be finished after the talk ({e})")
    return done


def mark_spell(store, name: str, ref_id: str, command_id: str, label: str) -> int:
    """Marks this NPC's memories saved under the command with label ("while under <player>'s spell"), as the spell
    field on the entry (its id does not change), in the memory file and in the archive (memory.mark_spell), so the mark
    stays when a memory is folded away. Returns how many."""
    return memory.mark_spell(store, name, ref_id, command_id, label)


def releasable(store, speakers=None) -> list[dict]:
    """Commands that can be released: [{id, text, npcs, given, until, marriages: [{name, base}]}] (for the page)."""
    out = []
    for record in command.load(store)['commands']:
        marriages = []
        for n in record['npcs']:
            speaker = next((s for s in speakers or [] if facts_history.short_ref(s.get('ref_id')) == facts_history.short_ref(n['ref_id'])), None)
            found = marriage_under(record, n, speaker)
            if found:
                marriages.append({'name': n['name'], 'base': found['base']})
        out.append({'id': record['id'], 'text': record['text'], 'npcs': record['npcs'], 'given': record.get('given'),
                    'until': record.get('until'), 'marriages': marriages})
    return out


# --- the in-game release (MLW_Release.psc) -----------------------------------------------------------------------------------

def read_game() -> list[dict]:
    """[{key, ref, name, base, choice, time, player}] from releases.json (PapyrusUtil string lists), oldest first. Keys
    and the choice are read without case (Papyrus may store "spell" as "SPELL"); a row that cannot be used is logged,
    never dropped silently."""
    lists = contracts.game_lists(lw_state._read(GAME_FILE))
    if not lists:
        return []
    get = lambda k: lists[k] if isinstance(lists.get(k), list) else []
    at = lambda values, i: str(values[i]).strip() if i < len(values) and values[i] is not None else ''
    keys, refs, names, bases, choices, times, players = (get(k) for k in ('key', 'ref', 'name', 'base', 'choice', 'time', 'player'))
    out = []
    for i in range(len(keys)):
        key, choice = at(keys, i), contracts.low(at(choices, i))
        if not key or choice not in CHOICES:
            contracts._rejected(f"a release chosen in game was not used ({GAME_FILE} row {i + 1}: key '{key}', "
                                f"choice '{at(choices, i)}', name '{at(names, i)}')", ('release', key, choice))
            continue
        out.append({'key': key, 'ref': at(refs, i), 'name': at(names, i), 'base': at(bases, i),
                    'choice': choice, 'time': command._float(at(times, i)), 'player': at(players, i)})
    return out


def poll_game(store, player: str = '', today=None, speakers=None, ask=None, language: str = 'English',
              in_talk=None) -> list[dict]:
    """Releases the player chose in game since the last request; each is handled once. Returns the results. in_talk:
    the speakers of the talk this request belongs to. Never raises."""
    if store is None:
        return []
    try:
        rows = read_game()
        if not rows:
            return []
        with _lock:
            data = load_record(store)
            fresh = [r for r in rows if r['key'] not in data['seen']]
            if not fresh:
                return []
            data['seen'] += [r['key'] for r in fresh]
            _save_record(store, data)
        out = []
        for row in fresh:
            if player and row['player'] and not contracts.same_name(row['player'], player):
                logger.log(23, f"Living World: a release chosen in game by another character ({row['player']}) is left for that save")
                continue  # another save character
            npc = {'name': row['name'], 'ref_id': row['ref'], 'base_id': row['base']}
            known = [s for s in speakers or []] + [npc]
            records = [c for c in command.load(store)['commands'] if _record_npcs(c, npc)]
            if not records:
                logger.log(23, f"Living World: {row['name'] or 'an NPC'} was released in game, but no absolute command binds them")
            for record in records:
                out.append(release_command(store, record['id'], row['choice'], npc=npc, end_marriage=True, player=player,
                                           today=today, speakers=known, by='you, in game', ask=ask, language=language,
                                           in_talk=in_talk))
        return out
    except Exception as e:
        logger.warning(f"Living World: could not read the releases chosen in game ({e})")
        return []
