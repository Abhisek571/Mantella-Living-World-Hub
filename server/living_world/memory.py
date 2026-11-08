"""Each NPC's memory from their own point of view, replacing Mantella's summary files when the Hub is installed.

Memory = {recent: [Entry], long_term: {section: text}, feeling: str}; Entry = {day, hour, text, witnesses} or a
reference {day, hour, shared: id, witnesses} to a group talk stored once in shared/<id>.json. Dates come from the
game clock, never from the model. Talks under MIN_SUMMARY_MESSAGES lines get one line without a model call. The
summary itself goes through Mantella's own summary call, so it uses the player's chosen summary model.

Files: <conversations folder>/<world id>/living_world/<name> - <ref id>.json (+ shared/, legacy_backup/)."""
import glob
import hashlib
import json
import logging
import os
import re
import shutil
import time

from . import lw_state

logger = logging.getLogger('Mantella')

MIN_SUMMARY_MESSAGES = 5
MAX_RECENT = 30
FOLD_COUNT = 10
EARLIER_CHARS = 2400
DEFAULT_BUDGET = 1500
MAX_ENTRY_CHARS = 1200  # one memory entry; a model reply that isn't clean JSON is cut to this
COMPACT_CHARS = 600  # normal-menu dialogue this long is summarized, not kept word for word
MAX_DIALOGUE_CHARS = 12000  # the newest part of that dialogue that goes to the summary model
COMPACTED = 'Remembered from ordinary talk:'  # starts an event that replaced normal-menu dialogue
FACT_TOKENS = 200  # definite facts sit on top of the memory budget, up to this many tokens per conversation
MAX_FACTS = 30  # stored per NPC: open promises always stay, then the newest settled ones
MIN_GROUP_FACT_TOKENS = 90  # in a group each NPC still gets at least this many tokens of facts
MAX_OPEN = 10  # open promises per NPC; older ones lapse
LAPSE_DAYS = 60  # a promise this long past due lapses
UNDATED_LAPSE_DAYS = 120  # a promise with no date lapses this long after it was made
MAX_FACT_CHARS = 200
MAX_FEELING_CHARS = 300  # how one NPC feels: a few words, never a whole reply
LONG_KNOWN_TALKS = 20  # from this many talks a close NPC remembers more...
LONG_KNOWN_BONUS = 300  # ...by this many tokens...
HARD_CAP_TOKENS = 2000  # ...but the bonus and facts never take a close NPC's memory past this
MANTELLA_DAY = 1  # Mantella dates its talks, and so these memories, GameDaysPassed + 1; the game side's days have no + 1

SUMMARY_PROMPT = (
    "You keep the memories of {names} in {game}. Below is a conversation they just had with {player}.\n"
    "Write what they will remember, from their own point of view, in {language}: 2 to 4 sentences, facts and promises "
    "first, no dates or day numbers. Keep only what was actually said or done in this conversation; never add "
    "details nobody said (where something came from, names, reasons), and keep doubts as doubts. "
    "Then how each of them now feels about {player}, in a few words.\n"
    "Also list every clear promise or debt made here: something specific that someone said they will do or owes. "
    "\"by\" is who promised it ({player} or a name), \"due_in_days\" is the days until it is due if they said when "
    "(tomorrow is 1), otherwise null. Leave out vague talk like \"someday\" unless it is a real promise. In \"kept\", "
    "copy word for word any open promise below that this conversation shows was done.\n"
    "Answer only with JSON: {{\"memory\": \"...\", \"feelings\": {{\"<name>\": \"...\"}}, "
    "\"promises\": [{{\"text\": \"...\", \"by\": \"...\", \"due_in_days\": null}}], \"kept\": []}}\n\n"
    "Open promises: {promises}\n\n"
    "Who they are:\n{bios}")

CHANNELS = ('talk', 'deeds', 'care', 'gifts', 'physical')
CHANNEL_WORDS = {'talk': 'good conversation', 'deeds': 'brave deeds done together', 'care': 'being looked after',
                 'gifts': 'gifts', 'physical': 'physical closeness'}
PROFILE_ASK = (
    "\n\nAlso rate, from who they are, what wins each of them over, from 1 (little) to 3 (most), and add it to the JSON as "
    "\"values\": {{\"<name>\": {{\"talk\": 2, \"deeds\": 2, \"care\": 2, \"gifts\": 2, \"physical\": 2}}}}, for: {names}.")

COMPRESS_PROMPT = (
    "Below are the older memories of {name} in {game}, from their own point of view. Rewrite them as one shorter text, "
    "at most {chars} characters. Keep promises, gifts, how they met, and anything that changed how they feel; drop small "
    "talk. Keep day numbers where they are given, and never add anything new. Answer with only the text.")

# Talks among NPCs only (radiant): no player, so no feelings about them.
RADIANT_PROMPT = (
    "You keep the memories of {names} in {game}. Below is a conversation they just had among themselves.\n"
    "Write what they will remember, from their own point of view, in {language}: 2 to 4 sentences, facts and promises "
    "first, no dates or day numbers. Keep only what was actually said or done in this conversation; never add "
    "details nobody said, and keep doubts as doubts.\n"
    "Answer only with JSON: {{\"memory\": \"...\"}}\n\n"
    "Who they are:\n{bios}")


def empty() -> dict:
    return {'recent': [], 'long_term': {}, 'feeling': '', 'asked': {}, 'facts': [], 'talks': 0, 'profile': {}}


def _int(value, default=-1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):  # OverflowError: a hand-edited Infinity
        return default


def clean(data) -> dict:
    """A memory dict with the expected shapes, whatever the file held (hand edits, old versions)."""
    memory = empty()
    if not isinstance(data, dict):
        return memory
    for entry in data.get('recent') if isinstance(data.get('recent'), list) else []:
        if not isinstance(entry, dict) or not isinstance(entry.get('text', entry.get('shared')), str):
            continue
        kept = dict(entry, day=_int(entry.get('day')), hour=_int(entry.get('hour')))
        if isinstance(kept.get('text'), str):
            kept['text'] = kept['text'][:MAX_ENTRY_CHARS]
        memory['recent'].append(kept)
    if isinstance(data.get('long_term'), dict):
        memory['long_term'] = {str(k): v for k, v in data['long_term'].items() if isinstance(v, str)}
    if isinstance(data.get('feeling'), str):
        memory['feeling'] = data['feeling']
    if isinstance(data.get('asked'), dict):
        memory['asked'] = data['asked']
    if isinstance(data.get('asked_day'), dict):
        memory['asked_day'] = data['asked_day']
    if 'feeling_day' in data:
        memory['feeling_day'] = _int(data.get('feeling_day'))
    for fact in data.get('facts') if isinstance(data.get('facts'), list) else []:
        if isinstance(fact, dict) and isinstance(fact.get('text'), str) and fact['text'].strip():
            memory['facts'].append(dict(fact, text=fact['text'][:MAX_FACT_CHARS], day=_int(fact.get('day')),
                                        due_day=_int(fact.get('due_day')), status=str(fact.get('status', 'open')),
                                        by=str(fact.get('by') or '')))
    memory['talks'] = max(0, _int(data.get('talks'), 0))
    memory['profile'] = clean_profile(data.get('profile'))
    return memory


def clean_profile(data) -> dict:
    """One rating from 1 to 3 per channel, or nothing: a partial or broken profile is asked for again."""
    if not isinstance(data, dict):
        return {}
    values = {channel: _whole(data.get(channel)) for channel in CHANNELS}
    if all(v is not None and 1 <= v <= 3 for v in values.values()):
        return values
    return {}


def _whole(value) -> int | None:
    """A whole number from what a model may send: 3, 3.0 or "3"; anything else (true, "soon", 2.5) is None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.strip()
        return int(value) if value.isdecimal() else None  # isdigit() also takes '²', which int() refuses
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}
MAX_NAME_CHARS = 80


def safe_part(text: str, fallback: str = 'unnamed') -> str:
    """One folder or file name part that Windows accepts and that cannot leave its folder. A name that had to change
    gets a short hash of the original, so two different odd names don't end up in the same file."""
    text = str(text)
    safe = _UNSAFE.sub('_', text).replace('..', '_').strip().rstrip('. ')[:MAX_NAME_CHARS].rstrip('. ')
    if not safe or safe.upper().split('.')[0] in _RESERVED:
        safe = fallback if not safe else f'_{safe}'
    if safe != text:
        safe += '~' + hashlib.sha1(text.encode('utf-8')).hexdigest()[:6]
    return safe


def file_name(name: str) -> str:
    """Like Mantella: a trailing number is dropped ("Whiterun Guard 2" is the same person as "Whiterun Guard")."""
    return re.sub(r'\s+\d+$', '', name.strip())


def tokens(text: str) -> int:
    return (len(text) + 3) // 4


def day_hour(game_days: float | None) -> tuple[int, int]:
    if game_days is None:
        return -1, -1
    days = int(game_days)
    return days, int((game_days - days) * 24)  # truncated like Mantella's own dates: 23:46 is still 11 at night


def time_group(hour: int) -> str:
    if hour < 0:
        return ''
    if hour < 5:
        return 'at night'
    if hour < 12:
        return 'in the morning'
    if hour < 18:
        return 'in the afternoon'
    if hour < 22:
        return 'in the evening'
    return 'at night'


def header(day: int, hour: int) -> str:
    if day < 0:
        return ''
    twelve = hour - 12 if hour > 12 else (12 if hour == 0 else hour)
    return f"[Day {day}, {twelve} {time_group(hour)}]"


class MemoryStore:
    def __init__(self, conversations_dir: str, world_id: str):
        world = safe_part(world_id, 'world')
        self.root = os.path.join(conversations_dir, world, 'living_world')
        self.legacy_root = os.path.join(conversations_dir, world)

    def _path(self, name: str, ref_id: str):
        from pathlib import Path
        return Path(self.root) / f"{safe_part(file_name(name))} - {safe_part(ref_id, '0')}.json"

    def load(self, name: str, ref_id: str) -> dict:
        path = self._path(name, ref_id)
        if path.exists():
            try:
                memory = clean(json.loads(_read_text(path)))
                for entry in memory['recent']:
                    if 'shared' in entry:
                        entry['text'] = self.shared_text(entry['shared'])
                return memory
            except OSError as e:
                # locked (sync, antivirus), not broken: starting empty here would let the next save replace it
                logger.warning(f"Living World: memory file for {name} could not be opened ({e}); left as it is")
                raise
            except (ValueError, RecursionError):
                # kept aside, so the next save can't overwrite the only copy
                aside = path.with_name(f"{path.name}.unreadable-{time.strftime('%Y%m%d-%H%M%S')}")
                try:
                    shutil.copy2(path, aside)
                except OSError:
                    pass
                logger.warning(f"Living World: memory file for {name} could not be read; copied to {aside.name}, starting empty")
                return empty()
        return self.convert_legacy(name, ref_id)

    def save(self, name: str, ref_id: str, memory: dict) -> None:
        path = self._path(name, ref_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = lw_state.temp_path(path)
        stored = dict(memory, recent=[{k: v for k, v in e.items() if not ('shared' in e and k == 'text')} for e in memory['recent']])
        with open(tmp, 'w', encoding='utf-8', errors='replace') as f:  # a lone surrogate from a model reply becomes '?'
            f.write(json.dumps(stored, ensure_ascii=False, indent=1))
        lw_state.replace_file(tmp, path)

    def save_shared(self, entry: dict) -> str:
        key = hashlib.sha1(json.dumps(entry, sort_keys=True).encode('utf-8')).hexdigest()[:16]
        folder = os.path.join(self.root, 'shared')
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, key + '.json')
        tmp = lw_state.temp_path(path)
        with open(tmp, 'w', encoding='utf-8', errors='replace') as f:
            json.dump(entry, f, ensure_ascii=False)
        lw_state.replace_file(tmp, path)
        return key

    def shared_text(self, key: str) -> str:
        if not isinstance(key, str) or not re.fullmatch(r'[0-9a-f]{16}', key):  # save_shared's own keys only
            return ''
        try:
            with open(os.path.join(self.root, 'shared', key + '.json'), encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError, RecursionError):
            return ''
        text = data.get('text') if isinstance(data, dict) else None
        return text if isinstance(text, str) else ''

    def convert_legacy(self, name: str, ref_id: str) -> dict:
        """Mantella's own summary files become the 'earlier' section; they are copied to legacy_backup first and
        never changed."""
        base = file_name(name)
        if _UNSAFE.search(base) or '..' in base:  # Mantella's folder for such a name is not one we should read
            return empty()
        files = []
        for folder in (f"{base} - {ref_id}", base):  # Mantella's folders: "<name> - <ref id>", older ones "<name>"
            files = glob.glob(os.path.join(glob.escape(self.legacy_root), glob.escape(folder), f"{glob.escape(base)}_summary_*.txt"))
            if files:
                break
        files.sort(key=lambda f: _int(''.join(re.findall(r'_summary_(\d+)', f)[-1:]), 0))  # _2 before _10
        if not files:
            return empty()
        backup = os.path.join(self.root, 'legacy_backup')
        os.makedirs(backup, exist_ok=True)
        texts = []
        for f in files:
            shutil.copy2(f, os.path.join(backup, os.path.basename(f) + '.bak'))
            try:
                with open(f, encoding='utf-8') as fh:
                    texts.append(fh.read().strip())
            except OSError:
                continue
        memory = empty()
        memory['long_term']['earlier'] = '\n'.join(t for t in texts if t)[-EARLIER_CHARS:]
        self.save(name, ref_id, memory)
        logger.info(f"Living World: converted {len(files)} Mantella summary file(s) for {name}")
        return memory


def _read_text(path) -> str:
    """A memory file's text. On Windows a file being replaced cannot be opened for a moment; that is waited out, so a
    save going on elsewhere never makes a good memory look unreadable (and start empty)."""
    for attempt in range(lw_state.REPLACE_TRIES):
        try:
            return path.read_text(encoding='utf-8-sig')
        except PermissionError:
            if attempt == lw_state.REPLACE_TRIES - 1:
                raise
            time.sleep(0.02)


def entry_text(entry: dict, store: MemoryStore | None = None) -> str:
    if not entry.get('text') and 'shared' in entry and store is not None:
        return store.shared_text(entry['shared'])
    return entry.get('text', '')


def render(memory: dict, budget_tokens: int = DEFAULT_BUDGET, store: MemoryStore | None = None, today: int | None = None) -> str:
    """Newest entries first in, so cutting for the budget drops the oldest; printed oldest to newest. With today (dated
    like the memories), entries and a feeling from a later day are left out: an earlier save was loaded, and loading
    forward again brings them back (the file is not changed)."""
    tail = []
    future = lambda day: today is not None and 0 <= today < _int(day)
    if memory.get('feeling') and not future(memory.get('feeling_day', -1)):
        # a hand-edited essay of a feeling must not push every memory out, nor the text past the budget
        tail.append(f"How you feel now: {memory['feeling'][:MAX_FEELING_CHARS]}"[:max(0, budget_tokens) * 4])
    head = [text for section, text in memory.get('long_term', {}).items() if text]
    used = tokens('\n'.join(tail))
    lines = []
    for entry in reversed(memory.get('recent', [])):
        text = entry_text(entry, store)
        if not text or future(entry.get('day', -1)):
            continue
        line = f"{header(entry.get('day', -1), entry.get('hour', -1))} {text}".strip()
        if used + tokens(line) + 1 > budget_tokens:
            continue  # an entry too long for what is left; older, shorter ones may still fit
        lines.append(line)
        used += tokens(line) + 1
    kept_head = []
    for text in head:
        if used + tokens(text) + 1 > budget_tokens:
            text = text[-max(0, (budget_tokens - used - 1) * 4):] if budget_tokens - used > 20 else ''
        if text:
            kept_head.append(text)
            used += tokens(text) + 1
    return '\n'.join(kept_head + list(reversed(lines)) + tail)


def fold_old(memory: dict, store: MemoryStore | None = None, compress=None) -> dict:
    """Keeps at most MAX_RECENT entries: the oldest FOLD_COUNT move into the 'earlier' section. When that outgrows its
    limit, compress(text) -> shorter text rewrites it; without it, or if it fails, the oldest characters are cut."""
    while len(memory['recent']) > MAX_RECENT:
        old, memory['recent'] = memory['recent'][:FOLD_COUNT], memory['recent'][FOLD_COUNT:]
        moved = '\n'.join(f"{header(e.get('day', -1), e.get('hour', -1))} {entry_text(e, store)}".strip() for e in old)
        earlier = (memory['long_term'].get('earlier', '') + '\n' + moved).strip()
        if compress is not None and len(earlier) > EARLIER_CHARS:
            try:
                shorter = (compress(earlier) or '').strip()
            except Exception as e:
                logger.warning(f"Living World: could not compress old memories ({e}); the oldest are cut instead")
                shorter = ''
            earlier = shorter or earlier
        memory['long_term']['earlier'] = earlier[-EARLIER_CHARS:]
    return memory


def _compressor(summaries, name: str):
    prompt = COMPRESS_PROMPT.format(name=name, game='Skyrim', chars=EARLIER_CHARS - 400)
    return lambda text: summaries.summarize_conversation(text, prompt)


def _summary_data(reply: str) -> dict:
    text = (reply or '').strip()
    if text.startswith('```'):
        text = text.strip('`').split('\n', 1)[-1].rsplit('```', 1)[0].strip()
    start, end = text.find('{'), text.rfind('}')
    for candidate in (text, text[start:end + 1] if 0 <= start < end else ''):
        try:
            data = json.loads(candidate)
        except (ValueError, RecursionError):  # RecursionError: a reply nested too deep
            continue
        if isinstance(data, dict):
            return data
    return {}


def add_promises(memory: dict, reply: str, day: int) -> None:
    """Promises and debts the summary found: dates come from the game clock, the model only says how many days. These
    are the model's reading of the talk, so they are marked as such; anything the game recorded stays apart."""
    data = _summary_data(reply)
    done = [_norm(k) for k in data.get('kept') if isinstance(k, str)] if isinstance(data.get('kept'), list) else []
    for fact in memory['facts']:
        if fact.get('status') == 'open' and any(_same_promise(fact['text'], k) for k in done):
            fact.update(status='kept', settled_day=day)
    known = [_norm(f['text']) for f in memory['facts']]
    for item in data.get('promises') if isinstance(data.get('promises'), list) else []:
        text = str(item.get('text') or '').strip()[:MAX_FACT_CHARS] if isinstance(item, dict) else ''
        if not text or day < 0 or any(_same_promise(text, k) for k in known):
            continue
        known.append(_norm(text))
        due = _whole(item.get('due_in_days'))
        due_day = day + due if due is not None and 0 <= due <= 365 else -1
        memory['facts'].append({'kind': 'promise', 'text': text, 'by': str(item.get('by') or ''), 'day': day, 'due_day': due_day,
                                'status': 'open', 'source': 'ai'})
    if day >= 0:
        lapse_old_promises(memory, day)
    if len(memory['facts']) > MAX_FACTS:
        settled = [f for f in memory['facts'] if f.get('status') != 'open']
        still_open = [f for f in memory['facts'] if f.get('status') == 'open']
        room = MAX_FACTS - len(still_open)
        memory['facts'] = (settled[-room:] if room > 0 else []) + still_open


def _norm(text) -> str:
    return ' '.join(re.sub(r'[^\w]+', ' ', str(text).lower()).split())


def _same_promise(a: str, b: str) -> bool:
    """The model may copy a promise back a little differently ("take Lydia to Solitude." / "Take her to Solitude"
    is still too loose; this only forgives case, punctuation and one text containing the other)."""
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return False
    return a == b or (min(len(a), len(b)) >= 12 and (a in b or b in a))


def lapse_old_promises(memory: dict, day: int) -> None:
    """Promises don't stay open forever: one LAPSE_DAYS past due, or UNDATED_LAPSE_DAYS old with no date, lapses, and
    only the MAX_OPEN newest stay open. A lapsed one is kept as history but no longer shown or sent to the model."""
    open_ones = [f for f in memory['facts'] if f.get('status') == 'open']
    for fact in open_ones:
        due, made = fact.get('due_day', -1), fact.get('day', -1)
        if (due >= 0 and day - due > LAPSE_DAYS) or (due < 0 and made >= 0 and day - made > UNDATED_LAPSE_DAYS):
            fact.update(status='lapsed', settled_day=day)
    still_open = [f for f in memory['facts'] if f.get('status') == 'open']
    for fact in still_open[:max(0, len(still_open) - MAX_OPEN)]:
        fact.update(status='lapsed', settled_day=day)


def add_profile(memory: dict, reply: str, name: str) -> None:
    """The profile is rated once, from the bio, in the summary call that was happening anyway."""
    if memory.get('profile'):
        return
    values = _summary_data(reply).get('values')
    if isinstance(values, dict):
        memory['profile'] = clean_profile(values.get(name, values))


def open_promises(memory: dict) -> list[str]:
    return [f['text'] for f in memory.get('facts', []) if f.get('status') == 'open']


def _ago(days: int) -> str:
    return 'today' if days <= 0 else ('yesterday' if days == 1 else f'{days} days ago')


def _promise_line(fact: dict, player: str, name: str, today: int | None) -> str:
    by = fact.get('by') or ''
    who = f"{player} promised" if by.lower() == player.lower() or by.lower() == 'the player' else (
        'You promised' if not by or by == name else f"{by} promised")
    due = fact.get('due_day', -1)
    line = f"{who}: {fact['text']}"
    if today is None or due < 0:
        return line
    if today > due:
        return f"{line} (overdue by {today - due} day{'s' if today - due != 1 else ''})"
    return f"{line} (due {'today' if due == today else ('tomorrow' if due == today + 1 else f'in {due - today} days')})"


def facts_text(memory: dict, game_facts: list[dict], today: int | None, player: str, name: str, budget_tokens: int = FACT_TOKENS,
               profile: dict | None = None) -> str:
    """Definite facts, most important first, up to the budget: when you last talked, promises, then what the game
    recorded, then what wins them over. game_facts are lw_state.game_facts() rows, already checked for expiry, dated
    by the game side; today is dated like the memories (MANTELLA_DAY)."""
    rows = []  # (priority, block, line); the budget goes to the highest priority first, ties keep this order
    last = next((e.get('day', -1) for e in reversed(memory.get('recent', [])) if e.get('day', -1) >= 0 and not e.get('radiant')), -1)
    if today is not None and last >= 0 and today > last:
        rows.append((3, 0, f"You last talked with {player} {_ago(today - last)}."))
    # after loading an earlier save: a promise made on a later day is not shown, one settled on a later day is open again
    later = lambda day: today is not None and 0 <= today < _int(day)
    promises = [f for f in memory.get('facts', []) if not later(f.get('day', -1))
                and (f.get('status') == 'open' or (f.get('status') in ('kept', 'lapsed') and later(f.get('settled_day', -1))))]
    overdue = lambda f: today is not None and 0 <= f.get('due_day', -1) < today
    rows += [(3 if overdue(f) else 2, 1, _promise_line(f, player, name, today)) for f in sorted(promises, key=lambda f: not overdue(f))]
    for fact in game_facts:
        dated = '' if fact['day'] < 0 or today is None else f" ({_ago(today - MANTELLA_DAY - fact['day'])})"
        rows.append((fact.get('priority', 1), 0, fact['text'] + dated))
    top = [CHANNEL_WORDS[c] for c in CHANNELS if (profile or {}).get(c) == 3]
    if top:
        rows.append((1, 0, f"What wins you over most: {', '.join(top)}."))
    rows = [(block, row) for _, block, row in sorted(rows, key=lambda r: -r[0])]
    # promises are read from the talk, not recorded by the game, so they sit under their own heading
    headings = ('What you know for certain:', 'Promises as you remember them:')
    kept, used = ([], []), sum(tokens(h) for h in headings)
    for block, row in rows:
        if used + tokens(row) + 1 > budget_tokens:
            continue  # a long fact should not stop shorter, less important ones
        kept[block].append(f"- {row}")
        used += tokens(row) + 1
    return '\n'.join(f"{headings[b]}\n" + '\n'.join(kept[b]) for b in (0, 1) if kept[b])


def long_known_bonus(memory: dict, budget_tokens: int) -> int:
    """A close NPC you have talked to a lot remembers more, never past the hard cap (facts included)."""
    talks = max(memory.get('talks', 0), _player_talks(memory))
    if talks < LONG_KNOWN_TALKS:
        return 0
    return max(0, min(LONG_KNOWN_BONUS, HARD_CAP_TOKENS - FACT_TOKENS - budget_tokens))


def _player_talks(memory: dict) -> int:
    """Remembered talks with the player; radiant ones (NPCs among themselves) and trims mid-talk don't count."""
    return len([e for e in memory.get('recent', []) if not e.get('radiant') and not e.get('reload')])


def parse_summary(reply: str, names: list[str]) -> tuple[str, dict[str, str]]:
    text = (reply or '').strip()
    if text.startswith('```'):
        text = text.strip('`').split('\n', 1)[-1].rsplit('```', 1)[0].strip()
    start, end = text.find('{'), text.rfind('}')
    for candidate in (text, text[start:end + 1] if 0 <= start < end else ''):
        try:
            data = json.loads(candidate)
        except (ValueError, RecursionError):  # RecursionError: a reply nested too deep
            continue
        if isinstance(data, dict) and isinstance(data.get('memory'), str):
            feelings = data.get('feelings')
            if len(names) == 1:  # only one NPC it can be about, whatever label the model put on it
                only = next(iter(feelings.values()), '') if isinstance(feelings, dict) and len(feelings) == 1 else feelings
                if isinstance(only, str) and only.strip():
                    feelings = {names[0]: only}
            feelings = feelings if isinstance(feelings, dict) else {}
            return data['memory'].strip()[:MAX_ENTRY_CHARS], {k: str(v).strip()[:MAX_FEELING_CHARS] for k, v in feelings.items() if k in names}
    return _plain_summary(text, names)


def _plain_summary(text: str, names: list[str]) -> tuple[str, dict[str, str]]:
    """A reply that isn't JSON, sometimes ending in a 'Feelings:' part: "Name: how they feel" or just how they feel."""
    match = re.search(r'(?:^|\n)\s*\**Feelings?\**\s*:\**\s*(.*)$', text, re.I | re.S)
    if not match:
        return text[:MAX_ENTRY_CHARS], {}
    feelings = {}
    for line in match.group(1).splitlines():
        name, separator, feeling = line.strip(' -*').partition(':')
        if separator and name.strip() in names and feeling.strip():
            feelings[name.strip()] = feeling.strip()[:MAX_FEELING_CHARS]
    if not feelings and len(names) == 1 and match.group(1).strip():
        feelings[names[0]] = match.group(1).strip()[:MAX_FEELING_CHARS]
    return text[:match.start()].strip()[:MAX_ENTRY_CHARS], feelings


def one_line(talk: list[str], player: str) -> str:
    # Mantella messages are objects; an NPC's words are in its sentences (get_formatted_content), not in .text
    said = [str(line.get_formatted_content() if hasattr(line, 'get_formatted_content') else getattr(line, 'text', line)).strip()
            for line in talk]
    said = [s for s in said if s]
    return f"Spoke briefly with {player}: " + ' '.join(said)[:240]


def vanilla_dialogue(thread, player: str) -> list[str]:
    """Lines said in the normal dialogue menu that Mantella handed over for this talk. It sends them only once, as
    in-game events on its automatic greeting, a system-generated message that get_talk_only() leaves out."""
    try:
        messages = thread.get_talk_only(include_system_generated_messages=True)
    except TypeError:
        return []
    lines = []
    for message in messages:
        if getattr(message, 'is_system_generated_message', False):
            # vanilla exchanges read "Player: line;\n NPC: reply"; other events (location, equipment) have no "Player:"
            lines += [_flat_dialogue(e) for e in getattr(message, '_UserMessage__ingame_events', None) or []
                      if f'{player}:' in str(e) and not str(e).startswith(COMPACTED)]
    return lines


def _flat_dialogue(event) -> str:
    return ' '.join(str(event).replace(';\n', ' ').split())


SUMMARY_TRIES = 3  # a failed or empty summary call is tried again this many times in all...
SUMMARY_RETRY_SECONDS = 5  # ...this far apart


def _ask_summary(summaries, said: str, prompt: str, who: str) -> str:
    """Mantella's summary call; an empty reply or an error (an outage, a rate limit) is tried again a few times."""
    for attempt in range(1, SUMMARY_TRIES + 1):
        try:
            reply = summaries.summarize_conversation(said, prompt)
            if reply:
                return reply
            logger.warning(f"Living World: the summary of {who} came back empty (try {attempt} of {SUMMARY_TRIES})")
        except Exception as e:
            logger.warning(f"Living World: could not summarize {who} ({e}) (try {attempt} of {SUMMARY_TRIES})")
        if attempt < SUMMARY_TRIES:
            time.sleep(SUMMARY_RETRY_SECONDS)
    return ''


def _peek(store: MemoryStore, name: str, ref_id: str) -> dict:
    """A memory only read, never saved back: a locked file reads as empty here."""
    try:
        return store.load(name, ref_id)
    except OSError:
        return empty()


def compact_dialogue(events: list, ctx: dict, store: MemoryStore) -> list:
    """The 'dialogue_events' hook, as a talk starts: Mantella hands over each NPC's normal-menu dialogue as one event. A
    long one is summarized now, saved into that NPC's memory with how they feel, and replaced by the short version. If
    that fails the event stays, and the talk's end still saves it (vanilla_dialogue). Only the talk's first message
    (ctx is_first, from Direct AI Connect) carries that dialogue; a later event shaped like dialogue (a typed custom
    event) is left as it is and never becomes a memory."""
    player = ctx.get('player')
    if not player or not ctx.get('is_first'):
        return events
    result = []
    for event in events:
        text = _flat_dialogue(event)
        npc = next((c for c in ctx.get('characters') or [] if f' {file_name(c.name)}:' in text), None)
        if not npc or f'{player}:' not in text or len(text) < COMPACT_CHARS or str(event).startswith(COMPACTED):
            result.append(event)
            continue
        try:
            memory = store.load(npc.name, npc.ref_id)
        except OSError as e:
            logger.warning(f"Living World: {npc.name}'s memory is locked ({e}); the earlier dialogue is kept word for word")
            result.append(event)
            continue
        source = hashlib.sha1(text.encode('utf-8')).hexdigest()[:12]
        known = next((e for e in memory['recent'] if e.get('dialogue') == source and isinstance(e.get('text'), str)), None)
        if known:  # a loaded save hands the same lines over again
            result.append(_compacted_event(npc.name, player, known['text'], memory['feeling']))
            continue
        prompt = SUMMARY_PROMPT.format(names=npc.name, game='Skyrim', player=player, language=ctx.get('language', 'English'),
                                       promises=json.dumps(open_promises(memory), ensure_ascii=False),
                                       bios=f"{npc.name}: {getattr(npc, 'bio', '')}")
        reply = _ask_summary(ctx['summaries'], text[-MAX_DIALOGUE_CHARS:], prompt, f"the earlier dialogue of {npc.name}")
        memory_line, feelings = parse_summary(reply, [npc.name]) if reply else ('', {})
        if not memory_line:
            result.append(event)
            continue
        day, hour = day_hour(ctx.get('game_days'))
        memory['recent'].append({'day': day, 'hour': hour, 'text': memory_line, 'witnesses': [npc.name], 'dialogue': source})
        add_promises(memory, reply, day)
        feeling = feelings.get(npc.name, '')
        if feeling:
            memory['feeling'] = feeling
            memory['feeling_day'] = day
        store.save(npc.name, npc.ref_id, fold_old(memory, store, _compressor(ctx['summaries'], npc.name)))
        result.append(_compacted_event(npc.name, player, memory_line, feeling))
    return result


def _compacted_event(name: str, player: str, memory_line: str, feeling: str) -> str:
    return f"{COMPACTED} {name} recalls this about {player}. {memory_line}" + (f" {name} now feels: {feeling}" if feeling else '')


def summarize(ctx: dict, store: MemoryStore) -> bool:
    """The 'summarize' hook: saves this conversation into each witness's memory. Always handles the save."""
    summaries = ctx['summaries']
    threads = summaries.get_threads_for_summarization(ctx['messages'], ctx['npcs_in_conversation'])
    wanted = {c.name: c for c in ctx['npcs_to_summarize']}
    threads = {name: p for name, p in threads.items() if name in wanted}
    player = ctx['npcs_in_conversation'].get_player_name() or 'the player'
    day, hour = day_hour(ctx.get('end_timestamp'))
    is_minor = ctx.get('is_minor') or (lambda character: False)
    for group in summaries.group_shared_threads(threads):
        params = threads[group[0]]
        talk = params.messages.get_talk_only()
        earlier = vanilla_dialogue(params.messages, player)
        feelings = {}
        reply = ''
        long_earlier = len(' '.join(earlier)) >= COMPACT_CHARS
        if len(talk) < 2 and not ctx.get('is_radiant') and not long_earlier:
            if not earlier:
                continue
            text = f"Talked with {player} in passing: " + ' '.join(earlier)
        elif len(params.messages) < MIN_SUMMARY_MESSAGES and not ctx.get('is_radiant') and not long_earlier:
            text = one_line(talk, player)
            if earlier:
                text = f"Talked with {player} in passing: " + ' '.join(earlier) + ' Then: ' + text
        else:
            bios = '\n'.join(f"{c.name}: {getattr(c, 'bio', '')}" for c in params.characters)
            template = RADIANT_PROMPT if ctx.get('is_radiant') else SUMMARY_PROMPT
            known = sorted({p for name in group for p in open_promises(_peek(store, name, wanted[name].ref_id))})
            prompt = template.format(names=', '.join(group), game='Skyrim', player=player, promises=json.dumps(known, ensure_ascii=False),
                                     language=ctx.get('language', 'English'), bios=bios)
            # a child is never rated on what wins them over
            unrated = [name for name in group if not _peek(store, name, wanted[name].ref_id).get('profile') and not is_minor(wanted[name])]
            if unrated and not ctx.get('is_radiant'):
                prompt += PROFILE_ASK.format(names=', '.join(unrated))
            said = params.messages.transform_to_dict_representation(talk)
            if earlier:
                menu = 'Earlier, in the normal dialogue menu:\n' + '\n'.join(earlier)[-MAX_DIALOGUE_CHARS:]
                said = menu + '\n\nThen this conversation:\n' + said if said else menu
            # one failed call must not cost the other groups their memories
            reply = _ask_summary(summaries, said, prompt, f"the talk of {', '.join(group)}")
            text, feelings = parse_summary(reply, group)
            if not text and earlier:  # handed over only once: keep the words if the model gave nothing back
                text = f"Talked with {player} in passing: " + ' '.join(earlier)[:MAX_ENTRY_CHARS]
        if not text:
            continue
        entry = {'day': day, 'hour': hour, 'text': text, 'witnesses': list(group)}
        if len(group) > 1:
            entry = {'day': day, 'hour': hour, 'shared': store.save_shared(entry), 'witnesses': list(group)}
        if ctx.get('is_radiant'):
            entry['radiant'] = True  # among NPCs only: not a talk with the player
        if ctx.get('is_reload'):
            entry['reload'] = True  # saved by a trim mid-talk: the same talk goes on
        for name in group:
            npc = wanted[name]
            try:
                memory = store.load(name, npc.ref_id)
            except OSError as e:  # locked: saving now would replace the whole file with this one talk
                logger.warning(f"Living World: {name}'s memory is locked ({e}); this talk is not saved for them")
                continue
            memory['recent'].append(dict(entry))
            if not ctx.get('is_radiant') and not ctx.get('is_reload'):  # a trim mid-talk is not a new talk
                memory['talks'] = max(memory.get('talks', 0), _player_talks(memory) - 1) + 1
            if reply and not ctx.get('is_radiant'):
                add_promises(memory, reply, day)
                if not is_minor(npc):
                    add_profile(memory, reply, name)
            if feelings.get(name):
                memory['feeling'] = feelings[name]
                memory['feeling_day'] = day
            store.save(name, npc.ref_id, fold_old(memory, store, _compressor(summaries, name)))
    return True


def memory_text(text: str, ctx: dict, store: MemoryStore, budget_tokens: int = DEFAULT_BUDGET, budget_for=None) -> str:
    """The 'memory_text' hook: our memories in the prompt; Mantella's text for anyone we have nothing for.
    budget_for(character) -> tokens, when each NPC has their own limit (strangers remember less of the player).
    ctx may also hold today (the game side's day, GameDaysPassed), player, facts_for(character) -> rows from
    lw_state.game_facts(), and profile_seen(character, profile), told each NPC's profile: the player's override if there
    is one, else the rated one."""
    characters = ctx.get('characters') or []
    blocks = []
    today = None if ctx.get('today') is None else ctx['today'] + MANTELLA_DAY
    share = max(1, len(characters))
    player = ctx.get('player') or 'the player'
    facts_for = ctx.get('facts_for') or (lambda character: [])
    overrides = ctx.get('profile_overrides') or {}
    is_minor = ctx.get('is_minor') or (lambda character: False)
    for character in characters:
        try:
            memory = store.load(character.name, character.ref_id)
        except OSError:  # locked: this NPC goes without memories for this reply (load logged it)
            continue
        budget = budget_for(character) if budget_for else budget_tokens
        budget = min(budget, budget_tokens)
        if budget >= budget_tokens:
            budget += long_known_bonus(memory, budget_tokens)
        profile = clean_profile(overrides.get(character.name)) or memory.get('profile') or {}
        if is_minor(character):
            profile = {}  # no "what wins you over" line for a child
        if profile and ctx.get('profile_seen'):
            ctx['profile_seen'](character, profile)
        known = facts_text(memory, facts_for(character), today, player, character.name, max(FACT_TOKENS // share, MIN_GROUP_FACT_TOKENS), profile)
        body = '\n'.join(part for part in (known, render(memory, budget // share, store, today)) if part)
        if not body:
            continue
        if len(characters) > 1:
            body = (f"[This is the beginning of {character.name}'s memory. Only {character.name} knows what is in this block; "
                    f"the others here learn it only if {character.name} says it aloud.]\n{body}\n[This is the end of {character.name}'s memory]")
        blocks.append(body)
    if not blocks:
        return text
    return "Below is a summary of past events:\n" + '\n\n'.join(blocks)
