"""Each NPC's memory from their own point of view, replacing Mantella's summary files when the Hub is installed.

Memory = {recent: [Entry], long_term: {section: text}, feeling: str}; Entry = {day, hour, text, witnesses} or a
reference {day, hour, shared: id, witnesses} to a group talk stored once in shared/<id>.json. Dates come from the
game clock, never from the model. Talks under MIN_SUMMARY_MESSAGES lines get one line without a model call. The
summary itself goes through Mantella's own summary call, so it uses the player's chosen summary model.

Each memory also says how they know it (source: seen, told by someone, a rumour, their own thought), which talk of the
save's timeline made it (timeline.py: memories made after the loaded save are set aside) and the story arc it belongs to
(arcs.py). The same summary call gives each NPC's mood as the talk ends; mood_line() carries it into the next talk and
lets it fade over a few game days.

Files: <conversations folder>/<world id>/living_world/<name> - <ref id>.json (+ shared/, legacy_backup/)."""
import glob
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import threading
import time

from . import archive, arcs, embed, lw_state, timeline

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
KEEP_FLAGS = ('intimacy', 'harmed', 'death_close', 'rescue', 'fought_beside', 'first_meeting', 'bond', 'follower', 'gift',
              'taken', 'recognised', 'broken_promise')  # stay in the list ('promise' only lifts importance: open promises are in the facts list)
ALWAYS_CAP = 8      # flagged memories (archive.FLAG_FLOORS) kept in the list per NPC; the rest merge into one line per flag
NEWEST_ALWAYS = 5  # the newest memories always go first; the rest of recent compete by how strongly they are remembered
RECALL_COUNT = 4  # older memories brought back by what the talk is about...
RECALL_SHARE = 0.3  # ...in at most this part of the memory budget
SHORT_IMPORTANCE = 0.2  # a talk too short for a summary is mostly small talk
CHATTER_REPEAT_DAYS = 3  # a normal-menu line heard on this many game days is chatter, not a memory
MAX_CHATTER_LINES = 3000  # lines counted per save character; the longest unheard go first
MAX_TAGS = 5
MAX_MOODS = 6  # moods kept per NPC (newest last), so loading an earlier save finds the mood it had then
MAX_MOOD_CHARS = 80
MOOD_MIN_DAYS = 1  # a mood fades back to neutral over this many game days...
MOOD_EXTRA_DAYS = 4  # ...plus this many times the talk's importance (a life-changing talk: about 5 days)
MAX_KEYS = 500  # keys of memories added from outside a talk (add_memory), so the same news never comes twice
MOOD_IN_MEMORY = True  # the mood line goes in each NPC's memory block; False when another part of the prompt carries mood_line()
SOURCE_WORDS = {'rumour': 'You heard a rumour: ', 'own': 'Your own thought: '}

# asked in the same summary call, so rating a memory costs no extra request
META_ASK = (
    "Also rate how much this will matter to them later as \"importance\" from 0 to 1 (0.1 small talk or a greeting, "
    "0.5 a useful fact or a favour, 0.8 a promise, a fight or a gift that matters, 1 something life-changing), the main "
    "\"emotion\" in one word, the \"type\" (one of experience, relationship, knowledge, trauma, joy) and up to 4 short "
    "\"tags\" (people, places, things).\n")
HOODED_ASK = ("\n\n{names} did not recognise {player} in this talk: a hood hid their face, and they never learned the name. "
              "In the memory and the feelings call {player} \"a hooded stranger\" (or \"the hooded stranger\"), never by name.")
META_JSON = ", \"importance\": 0.5, \"emotion\": \"...\", \"type\": \"experience\", \"tags\": []"

SUMMARY_PROMPT = (
    "You keep the memories of {names} in {game}. Below is a conversation they just had with {player}.\n"
    "Write what they will remember, from their own point of view, in {language}: 2 to 4 sentences, facts and promises "
    "first, no dates or day numbers. Keep only what was actually said or done in this conversation; never add "
    "details nobody said (where something came from, names, reasons), and keep doubts as doubts. A line starting "
    "\"Already happened, and complete:\" is a custom event: it is true; never write that it did not happen, even if a "
    "later line says a gift menu or offer came to nothing. "
    "Then how each of them now feels about {player}, in a few words, and the mood each of them is in as the "
    "conversation ends, in a few words (for example calm, cheerful, shaken, angry).\n"
    "Also list every clear promise or debt made here: something specific that someone said they will do or owes. "
    "Write a debt as \"<who> owes <whom> <amount> gold for <what>\" (gold still to pay after a trade or a deal), with "
    "\"by\" the one who owes. \"by\" is who promised it ({player} or a name), \"due_in_days\" is the days until it is due if they said when "
    "(tomorrow is 1), otherwise null. Leave out vague talk like \"someday\" unless it is a real promise. In \"kept\", "
    "copy word for word any open promise below that this conversation shows was done.\n" + META_ASK +
    "Answer only with JSON: {{\"memory\": \"...\", \"feelings\": {{\"<name>\": \"...\"}}, \"moods\": {{\"<name>\": \"...\"}}, "
    "\"promises\": [{{\"text\": \"...\", \"by\": \"...\", \"due_in_days\": null}}], \"kept\": []" + META_JSON + "}}\n\n"
    "Open promises: {promises}\n\n"
    "Who they are:\n{bios}")

# appended to the summary prompt (same call): which ongoing story this talk belongs to, for story arcs (arcs.py)
STORY_ASK = (
    "\n\nOngoing stories they are part of: {stories}\nIf this conversation is part of one of these stories, or clearly "
    "starts one that will go on (a courtship, a feud, a journey, a quest, a time under a spell), add to the JSON "
    "\"story\": {{\"label\": \"<that story's label word for word, or a short new one>\", \"so_far\": \"<one sentence: "
    "the whole story so far>\"}}; otherwise \"story\": null.")

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
    "details nobody said, and keep doubts as doubts. Also the mood each of them is in as it ends, in a few words.\n" + META_ASK +
    "Answer only with JSON: {{\"memory\": \"...\", \"moods\": {{\"<name>\": \"...\"}}" + META_JSON + "}}\n\n"
    "Who they are:\n{bios}")

DIARY_PROMPT = (
    "You keep the private diary of {name} in {game}. Below are their memories of one day. Write their diary entry for "
    "that day in {language}: one or two short sentences, first person, plain, only what the memories say, no dates. "
    "Answer with only the entry.")


_npc_locks: dict = {}  # one per memory file: every load-modify-save of it holds this (see MemoryStore.lock)
_npc_locks_guard = threading.Lock()


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
            kept['text'] = archive.unwrap_text(kept['text'])[:MAX_ENTRY_CHARS]  # a wrapped one stored before live test 12
        if 'hidden' in kept and not isinstance(kept['hidden'], dict):
            kept.pop('hidden')  # only {day, by, note} hides a memory
        memory['recent'].append(kept)
    if isinstance(data.get('long_term'), dict):
        memory['long_term'] = {str(k): v for k, v in data['long_term'].items() if isinstance(v, str)}
    if isinstance(data.get('feeling'), str):
        memory['feeling'] = data['feeling']
    if isinstance(data.get('asked'), dict):
        memory['asked'] = data['asked']
    if isinstance(data.get('asked_day'), dict):
        memory['asked_day'] = data['asked_day']
    for key in ('feeling_day', 'diary_day'):
        if key in data:
            memory[key] = _int(data.get(key))
    if isinstance(data.get('battles'), list):  # fights already remembered (battle.remember)
        memory['battles'] = [str(b) for b in data['battles'] if isinstance(b, (str, int))][-200:]
    for fact in data.get('facts') if isinstance(data.get('facts'), list) else []:
        if isinstance(fact, dict) and isinstance(fact.get('text'), str) and fact['text'].strip():
            memory['facts'].append(dict(fact, text=fact['text'][:MAX_FACT_CHARS], day=_int(fact.get('day')),
                                        due_day=_int(fact.get('due_day')), status=str(fact.get('status', 'open')),
                                        by=str(fact.get('by') or '')))
    memory['talks'] = max(0, _int(data.get('talks'), 0))
    memory['profile'] = clean_profile(data.get('profile'))
    moods = [m for m in data.get('moods') if isinstance(m, dict)] if isinstance(data.get('moods'), list) else []
    moods = [dict(m, day=_int(m.get('day')), hour=_int(m.get('hour')), mood=str(m.get('mood') or '')[:MAX_MOOD_CHARS],
                  feeling=str(m.get('feeling') or '')[:MAX_FEELING_CHARS]) for m in moods]
    if moods:
        memory['moods'] = [m for m in moods if m['mood'] or m['feeling']][-MAX_MOODS:]
    for key in ('feeling_talk',):
        if isinstance(data.get(key), str):
            memory[key] = data[key]
    if isinstance(data.get('feeling_seq'), int) and not isinstance(data.get('feeling_seq'), bool):
        memory['feeling_seq'] = data['feeling_seq']
    if isinstance(data.get('keys'), list):  # memories added from outside a talk (add_memory)
        memory['keys'] = [str(k) for k in data['keys'] if isinstance(k, (str, int))][-MAX_KEYS:]
    if data.get('earlier_redo') is True:  # 'earlier' was rebuilt after a forget and is shortened again after the talk
        memory['earlier_redo'] = True
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

    def lock(self, name: str, ref_id: str) -> threading.RLock:
        """The lock of one NPC's memory file (the same object for every store on that folder). Whatever loads, changes
        and saves it back holds this, so a hide on a background thread never saves over a talk saved meanwhile."""
        key = os.path.normcase(os.path.abspath(str(self._path(name, ref_id))))
        with _npc_locks_guard:
            return _npc_locks.setdefault(key, threading.RLock())

    def archive_path(self, name: str, ref_id: str):
        path = self._path(name, ref_id)
        return path.with_name(path.name[:-len('.json')] + '.archive.sqlite')

    def archive_for(self, name: str, ref_id: str) -> archive.Archive:
        return archive.Archive(self.archive_path(name, ref_id))

    def load(self, name: str, ref_id: str) -> dict:
        path = self._path(name, ref_id)
        if path.exists():
            try:
                memory = clean(json.loads(_read_text(path)))
                for entry in memory['recent']:
                    if 'shared' in entry:
                        entry['text'] = self.shared_text(entry['shared'])
                self._from_archive(name, ref_id, memory, path)
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
        self.sync_archive(name, ref_id, memory)

    def sync_archive(self, name: str, ref_id: str, memory: dict) -> None:
        """Every recent memory is also kept in the archive, so folding it later loses nothing. A memory hidden in the
        file is hidden there too; unhiding is done by unhide() on both, never here, so a save from a copy loaded before
        a memory was hidden cannot bring it back. Never raises: the memory file is already saved."""
        try:
            store = self.archive_for(name, ref_id)
            engine = embed.current()
            recent = memory.get('recent', [])
            store.add([(e, entry_text(e, self)) for e in recent], engine)
            stored = store.ids()
            for entry in recent:
                if entry.get('hidden') and not stored.get(archive.entry_id(entry)):
                    store.set_hidden([archive.entry_id(entry)], entry['hidden'])
            store.backfill(engine)
        except Exception as e:  # sqlite3.Error, OSError, or odd values from a hand-edited file
            logger.warning(f"Living World: could not update {name}'s memory archive ({e}); tried again on the next save")

    def _from_archive(self, name: str, ref_id: str, memory: dict, path) -> None:
        """On load: the first time (no archive yet) the memory file is copied to upgrade_backup and every memory in it
        goes into a new archive, at the default importance. After that the archive says which memories are hidden."""
        try:
            store = self.archive_for(name, ref_id)
            if not store.exists():
                backup = path.parent / 'upgrade_backup' / path.name
                if not backup.exists():
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, backup)
                self.sync_archive(name, ref_id, memory)
                logger.info(f"Living World: {name}'s {len(memory['recent'])} memory(s) copied into their new archive")
                return
            hidden = {i: h for i, h in store.ids().items() if h}
            for entry in memory['recent']:
                mark = hidden.get(archive.entry_id(entry))
                if mark and not entry.get('hidden'):
                    try:
                        entry['hidden'] = json.loads(mark)
                    except ValueError:
                        entry['hidden'] = {'day': -1, 'by': '', 'note': ''}
        except Exception as e:
            logger.warning(f"Living World: could not read {name}'s memory archive ({e})")

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


def sourced(entry: dict, text: str) -> str:
    """The text as the NPC knows it: plain for what they saw, "Lucan told you: ..." for what they were told, and so on."""
    source = archive.source_of(entry)
    if not text or source == 'seen':
        return text
    if source == 'told':
        by = ' '.join(str(entry.get('told_by') or '').split())[:80]
        return f"{by} told you: {text}" if by else f"You were told: {text}"
    return SOURCE_WORDS[source] + text


def spelled(entry: dict, text: str) -> str:
    """A memory made under an absolute command that was released with "remembers, and knows it was a spell" (the spell
    field, release.mark_spell): "(while under Vega's spell) " before the text."""
    spell = ' '.join(str(entry.get('spell') or '').split())[:80] if isinstance(entry, dict) else ''
    return f"({spell}) {text}" if spell and text else text


def _line(entry: dict, store: MemoryStore | None = None) -> str:
    return f"{header(entry.get('day', -1), entry.get('hour', -1))} {spelled(entry, sourced(entry, entry_text(entry, store)))}".strip()


def render(memory: dict, budget_tokens: int = DEFAULT_BUDGET, store: MemoryStore | None = None, today: int | None = None,
           recalled: list[dict] | None = None, branch=None) -> str:
    """What one NPC remembers, inside the budget, printed oldest to newest. In first: the NEWEST_ALWAYS newest memories;
    then older ones the talk brought back (recalled, from recall(), in at most RECALL_SHARE of the budget); then the
    other recent ones, the most strongly remembered first (importance and age, see archive.retention; with equal
    importance that is simply newest first); then the 'earlier' text. Hidden memories never show. With today (dated like
    the memories), entries and a feeling from a later day are left out: an earlier save was loaded, and loading forward
    again brings them back (the file is not changed). With branch (timeline.current), memories of talks made after the
    loaded save are left out the same way. A recalled row with an arc_line (recall) brings its story's line with it."""
    tail = []
    future = lambda day: today is not None and 0 <= today < _int(day)
    mood = mood_text(memory, today, branch) if MOOD_IN_MEMORY else ''
    if mood:
        tail.append(mood[:max(0, budget_tokens) * 4])
    feeling = _feeling(memory, branch)
    if feeling and not future(memory.get('feeling_day', -1) if feeling == memory.get('feeling') else -1):
        # a hand-edited essay of a feeling must not push every memory out, nor the text past the budget
        tail.append(f"How you feel now: {feeling[:MAX_FEELING_CHARS]}"[:max(0, budget_tokens) * 4])
    head = [text for section, text in memory.get('long_term', {}).items() if text]
    used = tokens('\n'.join(tail))
    visible = [e for e in memory.get('recent', []) if not e.get('hidden') and entry_text(e, store) and not future(e.get('day', -1))
               and timeline.usable(branch, e)]
    chosen = {}  # position in visible -> line

    def fits(line: str, limit: int) -> bool:
        nonlocal used
        if used + tokens(line) + 1 > limit:
            return False  # too long for what is left; shorter ones may still fit
        used += tokens(line) + 1
        return True

    split = max(0, len(visible) - NEWEST_ALWAYS)
    for pos in range(len(visible) - 1, split - 1, -1):
        line = _line(visible[pos], store)
        if fits(line, budget_tokens):
            chosen[pos] = line
    for pos in range(split - 1, -1, -1):  # then the flagged ones (always important), newest first
        if any(f in KEEP_FLAGS for f in visible[pos].get('flags') or []) and pos not in chosen:
            line = _line(visible[pos], store)
            if fits(line, budget_tokens):
                chosen[pos] = line
    brought_back = []
    share = used + int(budget_tokens * RECALL_SHARE)
    for row in recalled or []:
        line = _line(row)
        if row.get('arc_line'):
            line = f"{row['arc_line']}\n{line}"
        if fits(line, min(share, budget_tokens)):
            brought_back.append((row.get('day', -1), row.get('hour', -1), line))
    days = [e.get('day', -1) for e in visible if e.get('day', -1) >= 0]
    now = today if today is not None else (max(days) if days else None)
    still_open = {_norm(p) for p in open_promises(memory)}

    def strength(pos: int) -> float:
        entry = visible[pos]
        day = entry.get('day', -1)
        old = now - day if now is not None and day >= 0 else split - pos  # undated: by place in the list
        promised = any(_norm(p) in still_open for p in entry.get('promises') or [])
        return archive.retention(archive.importance_of(entry), old, promised)

    for pos in sorted((p for p in range(split) if p not in chosen), key=lambda p: (-strength(p), -p)):
        line = _line(visible[pos], store)
        if fits(line, budget_tokens):
            chosen[pos] = line
    lines = [chosen[pos] for pos in sorted(chosen)]
    recalled_lines = [line for _, _, line in sorted(brought_back, key=lambda r: (r[0], r[1]))]
    kept_head = []
    for text in head:
        if used + tokens(text) + 1 > budget_tokens:
            text = text[-max(0, (budget_tokens - used - 1) * 4):] if budget_tokens - used > 20 else ''
        if text:
            kept_head.append(text)
            used += tokens(text) + 1
    return '\n'.join(kept_head + recalled_lines + lines + tail)


def fold_old(memory: dict, store: MemoryStore | None = None, compress=None, branch=None) -> dict:
    """Keeps at most MAX_RECENT visible entries: the oldest FOLD_COUNT move into the 'earlier' section (each stays whole
    in the archive). A hidden entry among them just leaves the list: it is never written into 'earlier', and stays hidden
    in the archive. When 'earlier' outgrows its limit, compress(text) -> shorter text rewrites it; without it, or if it
    fails, the oldest characters are cut. With branch, a memory of another timeline (timeline.py) is neither counted
    nor folded: it stays in recent as it is."""
    shown = lambda e: not e.get('hidden') and timeline.usable(branch, e)
    stays = lambda e: shown(e) and any(f in KEEP_FLAGS for f in e.get('flags') or [])
    kept = lambda e: shown(e) and not stays(e)
    cap_flagged(memory)  # flagged memories stay in the list (bounded); they never fold into 'earlier'
    while len([e for e in memory['recent'] if shown(e)]) > MAX_RECENT and any(kept(e) for e in memory['recent']):
        count, cut = 0, 0
        for cut, entry in enumerate(memory['recent'], 1):
            count += kept(entry)
            if count == FOLD_COUNT:
                break
        old, rest = memory['recent'][:cut], memory['recent'][cut:]
        aside = [e for e in old if (not e.get('hidden') and not timeline.usable(branch, e)) or stays(e)]
        old = [e for e in old if not any(e is a for a in aside)]
        memory['recent'] = aside + rest
        moved = '\n'.join(_line(e, store) for e in old if not e.get('hidden'))
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


def earlier_from_archive(store: MemoryStore, name: str, ref_id: str, memory: dict, branch=None) -> str:
    """The 'earlier' text made again from the archive: every memory that has folded out of recent and is still in mind
    (not hidden, of the loaded save's timeline; diary entries never were in it), oldest first, one line each."""
    store_db = store.archive_for(name, ref_id)
    if not store_db.exists():
        return ''
    recent = {archive.entry_id(e) for e in memory.get('recent', [])}
    rows = [r for r in store_db.rows() if r.get('id') not in recent and r.get('type') != 'diary' and timeline.usable(branch, r)]
    return '\n'.join(line for line in (_line(r) for r in rows) if line)


def _forget_in_earlier(store: MemoryStore, name: str, ref_id: str, memory: dict, picked: list[dict], branch=None) -> None:
    """A hidden memory must leave 'earlier' too. Its own line is taken out while it is there word for word; when it is
    not (the text was compressed by the summary model, or the line was written differently), 'earlier' is made again
    from the archive without it (earlier_from_archive). Too long for the limit: the newest part is kept now and the
    whole is shortened by the summary model after the next talk (earlier_redo), never with the forgotten memory."""
    earlier = memory['long_term'].get('earlier', '')
    if not earlier:
        return
    recent = {archive.entry_id(e) for e in memory['recent']}
    whole = True  # every folded one was found word for word
    for row in picked:
        line = _line(row)
        if line and line in earlier:
            earlier = '\n'.join(part for part in earlier.split('\n') if part != line)
        elif row.get('id') not in recent:
            whole = False
    memory['long_term']['earlier'] = earlier
    if whole or not earlier:
        return
    rebuilt = earlier_from_archive(store, name, ref_id, memory, branch)
    if len(rebuilt) > EARLIER_CHARS:
        memory['earlier_redo'] = True
    memory['long_term']['earlier'] = rebuilt[-EARLIER_CHARS:]
    logger.log(23, f"Living World: {name}'s older memories were written again without what was forgotten")


def _fold_and_save(store: MemoryStore, name: str, ref_id: str, memory: dict, summaries, branch=None) -> None:
    """Saves after a new memory; whatever folds out of recent is put in the archive first, so it is kept whole even if
    an earlier save could not reach the archive. 'earlier' rebuilt after a forget (earlier_redo) is shortened here by
    the summary model, from the archive, once."""
    if len([e for e in memory['recent'] if not e.get('hidden')]) > MAX_RECENT:
        store.sync_archive(name, ref_id, memory)
    compress = _compressor(summaries, name)
    if memory.pop('earlier_redo', False):
        try:
            full = earlier_from_archive(store, name, ref_id, memory, branch)
            shorter = (compress(full) or '').strip() if len(full) > EARLIER_CHARS else full
            if shorter:
                memory['long_term']['earlier'] = shorter[-EARLIER_CHARS:]
        except Exception as e:
            logger.warning(f"Living World: could not shorten {name}'s older memories ({e}); the newest part is kept")
    store.save(name, ref_id, fold_old(memory, store, compress, branch))


def parse_meta(reply: str) -> dict:
    """importance, emotion, type and tags from the summary reply, each only when it is usable: importance a number
    from 0 to 1 (a 0-10 rating is scaled down), emotion a word or two, type one of archive.TYPES, a few short tags."""
    data = _summary_data(reply)
    meta = {}
    value = data.get('importance')
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            value = None
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value == value and abs(value) != float('inf'):
        value = value / 10 if 1 < value <= 10 else value
        meta['importance'] = round(min(1.0, max(0.0, float(value))), 2)
    emotion = data.get('emotion')
    if isinstance(emotion, str) and emotion.strip() and len(emotion.split()) <= 3:
        meta['emotion'] = emotion.strip().lower()[:30]
    kind = str(data.get('type') or '').strip().lower()
    if kind in archive.TYPES and kind != 'diary':
        meta['type'] = kind
    tags = data.get('tags')
    if isinstance(tags, list):
        clean_tags = []
        for tag in tags:
            tag = str(tag).strip().lower()[:30] if isinstance(tag, (str, int, float)) and not isinstance(tag, bool) else ''
            if tag and tag not in clean_tags:
                clean_tags.append(tag)
        if clean_tags:
            meta['tags'] = clean_tags[:MAX_TAGS]
    return meta


def _unfence(reply) -> str:
    text = str(reply or '').strip()
    if text.startswith('```'):
        text = text.strip('`').split('\n', 1)[-1].rsplit('```', 1)[0].strip()
    return text


def _cut_short(text: str) -> dict:
    """A JSON object cut off before its end (live test 12: the reply stopped at '"values": {"Gerdur": {..."physical":'):
    every top-level member that is complete, the rest dropped. {} when nothing whole is there."""
    start = text.find('{')
    if start < 0:
        return {}
    depth, inside, escaped, ends = 0, False, False, []
    for i in range(start, len(text)):
        ch = text[i]
        if inside:
            escaped, inside = (False, inside) if escaped else (ch == '\\', ch != '"')
            continue
        if ch == '"':
            inside = True
        elif ch in '{[':
            depth += 1
        elif ch in '}]':
            depth -= 1
            if depth == 0:
                break
        elif ch == ',' and depth == 1:
            ends.append(i)
    for end in reversed(ends):
        try:
            data = json.loads(text[start:end] + '}')
        except (ValueError, RecursionError):
            continue
        if isinstance(data, dict):
            return data
    return {}


def _summary_data(reply: str) -> dict:
    text = _unfence(reply)
    start, end = text.find('{'), text.rfind('}')
    for candidate in (text, text[start:end + 1] if 0 <= start < end else ''):
        try:
            data = json.loads(candidate)
        except (ValueError, RecursionError):  # RecursionError: a reply nested too deep
            continue
        if isinstance(data, dict):
            return data
    return _cut_short(text)


def add_promises(memory: dict, reply: str, day: int, stamp: dict | None = None) -> None:
    """Promises and debts the summary found: dates come from the game clock, the model only says how many days. These
    are the model's reading of the talk, so they are marked as such; anything the game recorded stays apart."""
    data = _summary_data(reply)
    done = [_norm(k) for k in data.get('kept') if isinstance(k, str)] if isinstance(data.get('kept'), list) else []
    stamp = stamp or {}
    for fact in memory['facts']:
        if fact.get('status') == 'open' and any(_same_promise(fact['text'], k) for k in done):
            fact.update(status='kept', settled_day=day)
            if stamp:
                fact.update(settled_talk=stamp['talk'], settled_seq=stamp['seq'])
    known = [_norm(f['text']) for f in memory['facts']]
    for item in data.get('promises') if isinstance(data.get('promises'), list) else []:
        text = str(item.get('text') or '').strip()[:MAX_FACT_CHARS] if isinstance(item, dict) else ''
        if not text or day < 0 or any(_same_promise(text, k) for k in known):
            continue
        known.append(_norm(text))
        due = _whole(item.get('due_in_days'))
        due_day = day + due if due is not None and 0 <= due <= 365 else -1
        memory['facts'].append({'kind': 'promise', 'text': text, 'by': str(item.get('by') or ''), 'day': day, 'due_day': due_day,
                                'status': 'open', 'source': 'ai', **stamp})
    if day >= 0:
        before = {id(f) for f in memory['facts'] if f.get('status') == 'lapsed'}
        lapse_old_promises(memory, day)
        for fact in memory['facts']:
            unkept = (fact.get('due_day', -1) >= 0 and day - fact['due_day'] > LAPSE_DAYS) or (
                fact.get('due_day', -1) < 0 and fact.get('day', -1) >= 0 and day - fact['day'] > UNDATED_LAPSE_DAYS)
            if fact.get('status') == 'lapsed' and id(fact) not in before and unkept:  # lapsed by time, not by the open cap
                memory['recent'].append({'day': day, 'hour': -1, 'text': f"A promise was not kept: {fact['text']}",
                                         'witnesses': [], 'type': 'relationship', 'flags': ['broken_promise'], 'source': 'own'})
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
    return [f['text'] for f in memory.get('facts', []) if f.get('status') == 'open' and not f.get('hidden_with')]


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
               profile: dict | None = None, branch=None) -> str:
    """Definite facts, most important first, up to the budget: when you last talked, promises, then what the game
    recorded, then what wins them over. game_facts are lw_state.game_facts() rows, already checked for expiry, dated
    by the game side; today is dated like the memories (MANTELLA_DAY)."""
    rows = []  # (priority, block, line); the budget goes to the highest priority first, ties keep this order
    last = next((e.get('day', -1) for e in reversed(memory.get('recent', [])) if e.get('day', -1) >= 0 and not e.get('radiant')
                 and not e.get('hidden') and timeline.usable(branch, e)), -1)
    if today is not None and last >= 0 and today > last:
        rows.append((3, 0, f"You last talked with {player} {_ago(today - last)}."))
    # after loading an earlier save: a promise made on a later day is not shown, one settled on a later day is open again
    later = lambda day: today is not None and 0 <= today < _int(day)
    # the same for a promise made, or kept, in a talk after the loaded save (timeline.py)
    settled_aside = lambda f: not timeline.usable(branch, {'talk': f.get('settled_talk'), 'seq': f.get('settled_seq')})
    promises = [f for f in memory.get('facts', []) if not later(f.get('day', -1)) and not f.get('hidden_with') and timeline.usable(branch, f)
                and (f.get('status') == 'open' or (f.get('status') == 'kept' and settled_aside(f))
                     or (f.get('status') in ('kept', 'lapsed') and later(f.get('settled_day', -1))))]
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
    """Remembered talks with the player in which the NPC knew who it was; radiant ones (NPCs among themselves), trims
    mid-talk, fights (World's battle accounts), memories added from outside a talk (news, things told: they carry a
    source) and talks with the player hooded and not recognised don't count."""
    return len([e for e in memory.get('recent', []) if not e.get('radiant') and not e.get('reload') and not e.get('battle')
                and not e.get('source') and not e.get('unrecognised')])


HOODED = 'a hooded stranger'  # who the player is in the memory of a talk where the NPC did not recognise them
_STRANGER_WORDS = r'(?:hooded\s+)?(?:stranger|figure|man|woman|traveller|traveler|fellow|visitor|customer)'


def mask_player(text: str, player: str) -> str:
    """text with the player's name taken out, for an NPC who did not know who the player was: "A hooded stranger, Player,
    came in" -> "A hooded stranger came in", "gave Player the key" -> "gave the hooded stranger the key". Never raises."""
    try:
        name = ' '.join(str(player or '').split())
        if not text or not name or name.lower() == 'the player':
            return text
        p = re.escape(name)
        # "a hooded stranger, Player," / "a hooded stranger named Player" / "the stranger Player": the name goes, the words stay
        text = re.sub(rf"\b((?:an?|the)\s+{_STRANGER_WORDS})(?:\s*,\s*|\s+(?:named|called)\s+|\s+){p}\b\s*,?", r"\1 ", text,
                      flags=re.I)
        text = re.sub(rf",\s*{p}\b(?=\s*[!?.,])", '', text, flags=re.I)  # spoken to by name: "Well met, Player!"
        text = re.sub(rf"\b{p}'s\b", "the hooded stranger's", text, flags=re.I)
        text = re.sub(rf"\b{p}\b", "the hooded stranger", text, flags=re.I)
        text = re.sub(r'\s+([,.;:!?])', r'\1', re.sub(r'[ \t]{2,}', ' ', text)).strip()
        return re.sub(r'(^|[.!?]\s+)the hooded', lambda m: m.group(1) + 'The hooded', text)
    except Exception:
        return text


def connection_line(memory: dict, name: str, player: str, branch=None) -> str:
    """For an NPC who now knows who the player is: one line linking the hooded stranger of their earlier memories to
    the player; '' when they have no such memory."""
    if any(e.get('unrecognised') and not e.get('hidden') and timeline.usable(branch, e) for e in memory.get('recent', [])):
        return f"(The hooded stranger in these memories was {player}; {name} knows that now.)"
    return ''


def parse_summary(reply: str, names: list[str]) -> tuple[str, dict[str, str]]:
    text = _unfence(reply)
    start, end = text.find('{'), text.rfind('}')
    for candidate in (text, text[start:end + 1] if 0 <= start < end else '', None):
        if candidate is None:  # a reply cut off before its end: its complete members (live test 12)
            data = _cut_short(text)
        else:
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
    unwrapped = archive.unwrap_text(text)  # cut off even inside its first member: at least the memory, never the wrapper
    if unwrapped != text:
        return unwrapped[:MAX_ENTRY_CHARS], {}
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


def clip(text: str, limit: int) -> str:
    """text cut to at most limit characters, never mid-word or mid-event: at the last sentence end that fits (or the last
    whole word, with "..."), and a bracketed event line the cut left open ("(Gerdur does not recognise CH") is dropped
    whole."""
    text = ' '.join(str(text or '').split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    ends = [m.end() for m in re.finditer(r'[.!?]["\')]*(?=\s|$)', cut)]
    if ends and ends[-1] >= limit // 3:
        cut = cut[:ends[-1]]
    else:
        cut = cut.rsplit(' ', 1)[0].rstrip(',;:') + '...' if ' ' in cut else cut
    opened = cut.rfind('(')
    if opened > cut.rfind(')'):  # an event line in brackets that the cut left open: drop it whole
        cut = cut[:opened].rstrip(' ,;:')
    return cut.strip()


def one_line(talk: list[str], player: str, name: str = '') -> str:
    """player: the name, or HOODED for an NPC who did not recognise them. The player's last words and the NPC's last
    reply (live test 14: the stub kept only her greeting and lost her answer)."""
    # Mantella messages are objects; an NPC's words are in its sentences (get_formatted_content), not in .text
    said = lambda line: str(line.get_formatted_content() if hasattr(line, 'get_formatted_content') else getattr(line, 'text', line)).strip()
    theirs = [said(l) for l in talk if 'user' not in type(l).__name__.lower() and said(l)]
    # a player message carries the game's event lines in brackets before the words (live test 15: they were kept as
    # what the player "said" and the words were cut off)
    mine = [w for w in (spoken_words(said(l)) for l in talk if 'user' in type(l).__name__.lower()) if w]
    if not mine:
        return f"Spoke briefly with {player}: " + clip(' '.join(theirs), 240)
    reply = f" {name or 'They'} answered: \"{clip(theirs[-1], 200)}\"" if theirs else ''
    return f"Spoke briefly with {player}, who said: \"{clip(mine[-1], 160)}\"." + reply


def spoken_words(text: str) -> str:
    """A player message without the bracketed event lines Mantella puts before the words ("(Sigrid's ties: ...)")."""
    text = str(text or '')
    for _ in range(3):  # nested brackets: "((Player handed Faendal 600 gold; it was handed over.))"
        text = re.sub(r"\([^()]*\)", ' ', text)
    return ' '.join(text.split())


# no stored relative time (live test 15: "the last time less than an hour ago" kept in a memory for good); the memory's
# day and hour are its data, and how long ago is worked out when it is shown
_RELATIVE = re.compile(r"(?:,\s*|\s+)?(?:\(\s*)?(?:the last time(?: was)?\s+|just\s+)?(?:less than an hour|about an hour|an hour|"
                       r"half an hour|a few minutes|a few hours|about \w+ hours?|\w+ hours?|\w+ minutes?|moments?)\s+ago"
                       r"(?:,? before we talked)?(?:\s*\))?", re.I)


def strip_relative(text: str) -> str:
    """text with "less than an hour ago" and the like taken out (the clause it closes kept). Never raises."""
    try:
        out = _RELATIVE.sub('', str(text or ''))
        out = re.sub(r"\s+([,.;:!?])", r"\1", out)
        out = re.sub(r",\s*([.;:!?])", r"\1", out)
        return ' '.join(out.split())
    except Exception:
        return text


FIRST_PERSON = (" Write {name}'s memory in the first person, as {name} (\"I\", \"me\", \"my\"), never \"{name}\", \"she\" "
                "or \"he\" for {name}.")
NO_RELATIVE = (" Never write how long ago something was (\"less than an hour ago\", \"earlier today\"): the memory keeps "
               "its own day and hour.")


def first_contact(memory: dict) -> bool:
    """No earlier memory of the player: no talk, no memory of the game's own dialogue with them or a scene with them
    (those are memories of the player too; live test 15), only news, fights among others or memories of others."""
    return not memory.get('talks') and not any(
        e.get('witnesses') and not e.get('radiant') and not e.get('battle') and not e.get('key') and not e.get('hidden')
        for e in memory.get('recent') or [])


# a short talk is still summarised for real when it holds something that matters (live test 14)
RELATIONSHIP_QUESTION = re.compile(r"\b(?:regret|love|between us|what we did|what happened|how many times|feel about|miss me|"
                                   r"marry|together|forgive|still want|are we)\b", re.I)


def short_but_important(texts: list[str], player_lines: list[str], flags_found: dict, recent_memories: bool) -> bool:
    """A talk too short for the usual summary that holds a flagged event (a gift, a theft line, a trade, a promise word),
    follows menu dialogue or scene memories made at its start, or where the player asked about the relationship."""
    joined = ' '.join(texts)
    return bool(flags_found or recent_memories or re.search(r"it was handed over|\bpromise|\bswear\b|finished having sex|"
                                                            r"Remembered from ordinary talk", joined, re.I)
                or any(RELATIONSHIP_QUESTION.search(l) and '?' in l for l in player_lines))


def vanilla_dialogue(thread, player: str, store: MemoryStore | None = None, day: int = -1, chatter: bool = True) -> list[str]:
    """Lines said in the normal dialogue menu that Mantella handed over for this talk. It sends them only once, as
    in-game events on its automatic greeting, a system-generated message that get_talk_only() leaves out. With a store
    and chatter on, stock barks and lines heard over and over are left out (filter_chatter)."""
    try:
        messages = thread.get_talk_only(include_system_generated_messages=True)
    except TypeError:
        return []
    events = []
    for message in messages:
        if getattr(message, 'is_system_generated_message', False):
            # vanilla exchanges read "Player: line;\n NPC: reply"; other events (location, equipment) have no "Player:"
            events += [str(e) for e in getattr(message, '_UserMessage__ingame_events', None) or []
                       if f'{player}:' in str(e) and not str(e).startswith(COMPACTED)]
    if store is not None and chatter and events:
        events = filter_chatter(events, player, store, day)
    return [_flat_dialogue(e) for e in events if e]


# Stock lines every guard and townsperson says; never a memory of this player. Matched inside the NPC's reply.
BARKS = re.compile(
    r"used to be an adventurer like you|arrow in the knee|stole your sweetroll|cloud district very often|no lollygaggin|"
    r"watch the skies,? traveler|disrespect the law,? and you disrespect me|sworn to carry your burdens|"
    r"my cousin'?s out fighting dragons|fus\W+ro\W+dah|i'?ve got my eyes on you|everything'?s on fire|"
    r"by ysmir,? you|what'?s that,? a skeever|keep your nose clean|i mostly deal with petty thievery|"
    r"psst\W+hey,? i know who you are|only burden i bear is", re.I)
# A whole reply that is only a greeting or a brush-off.
GREETINGS = re.compile(
    r"(hail|greetings|hello|what is it|what do you want|what do you need|need something|hmm+|hmph|"
    r"can i help you|move along|citizen|traveler|outlander|stranger|well met|good day|leave me be)"
    r"[\s,.!?\-]*(\w+[.!?]*)?", re.I)


def _exchanges(text: str, player: str) -> list[str]:
    """One NPC's normal-menu dialogue cut into exchanges, each starting at "Player:" ("Player: line;\\n NPC: reply")."""
    parts = re.split(r'(?<!\S)(?=' + re.escape(player) + ':)', text)
    return [p for p in parts if p]


def _reply(exchange: str) -> str:
    """The NPC's words in one exchange, without their name."""
    _, separator, reply = exchange.partition(';\n')
    reply = reply if separator else ''
    return reply.split(':', 1)[1].strip() if ':' in reply else reply.strip()


def chatter_path(store: MemoryStore) -> str:
    return os.path.join(store.root, 'chatter.json')


def _load_chatter(store: MemoryStore) -> dict:
    try:
        with open(chatter_path(store), encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError, RecursionError):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}


def _save_chatter(store: MemoryStore, table: dict) -> None:
    if len(table) > MAX_CHATTER_LINES:  # the lines not heard for longest go first
        table = dict(sorted(table.items(), key=lambda kv: -_int(kv[1].get('day'), -1))[:MAX_CHATTER_LINES])
    os.makedirs(store.root, exist_ok=True)
    path = chatter_path(store)
    tmp = lw_state.temp_path(path)
    with open(tmp, 'w', encoding='utf-8', errors='replace') as f:
        json.dump(table, f, ensure_ascii=False)
    lw_state.replace_file(tmp, path)


def filter_chatter(events: list[str], player: str, store: MemoryStore, day: int, count: bool = True) -> list[str]:
    """Normal-menu dialogue with the chatter left out: a stock bark, or a reply this save has heard on
    CHATTER_REPEAT_DAYS game days (any NPC), goes with the player's line that asked for it; so does the same exchange a
    second time in one talk. The count table (chatter.json in the save's living_world folder) counts each reply once per
    game day, so the start and the end of the same talk never count it twice. An event left with nothing is ''."""
    try:
        table = _load_chatter(store)
    except Exception:
        table = {}
    changed, out = False, []
    for event in events:
        kept, seen = [], set()
        for exchange in _exchanges(str(event), player):
            reply = _reply(exchange)
            key = _norm(reply)[:200]
            if not key:
                kept.append(exchange)  # not an exchange (text before the first "Player:")
                continue
            heard = table.get(key) or {'n': 0, 'day': -1}
            if count and day >= 0 and _int(heard.get('day')) != day:
                heard = {'n': _int(heard.get('n'), 0) + 1, 'day': day}
                table[key] = heard
                changed = True
            stock = bool(BARKS.search(reply)) or bool(GREETINGS.fullmatch(reply.strip()))
            if stock or key in seen or _int(heard.get('n'), 0) >= CHATTER_REPEAT_DAYS:
                continue
            seen.add(key)
            kept.append(exchange)
        text = ''.join(kept).strip()
        out.append(text if any(_reply(k) for k in kept) else '')
    if changed:
        try:
            _save_chatter(store, table)
        except OSError as e:
            logger.warning(f"Living World: could not save the chatter count ({e})")
    return out


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
    day, hour = day_hour(ctx.get('game_days'))
    branch = timeline.current(store, ctx.get('game_days'))
    for event in events:
        text = _flat_dialogue(event)
        npc = next((c for c in ctx.get('characters') or [] if f' {file_name(c.name)}:' in text), None)
        if not npc or f'{player}:' not in text or len(text) < COMPACT_CHARS or str(event).startswith(COMPACTED):
            result.append(event)
            continue
        # chatter never becomes a memory; the event itself still goes to the model as it was
        said = _flat_dialogue(filter_chatter([str(event)], player, store, day)[0]) if ctx.get('chatter_filter', True) else text
        if len(said) < COMPACT_CHARS:
            result.append(event)
            continue
        with store.lock(npc.name, npc.ref_id):
            result.append(_compact_one(event, text, said, npc, player, day, hour, ctx, store, branch))
    return result


def _compact_one(event, text: str, said: str, npc, player: str, day: int, hour: int, ctx: dict, store: MemoryStore, branch=None):
    """compact_dialogue for one NPC's dialogue event, with their memory file's lock held: what goes to the model."""
    try:
        memory = store.load(npc.name, npc.ref_id)
    except OSError as e:
        logger.warning(f"Living World: {npc.name}'s memory is locked ({e}); the earlier dialogue is kept word for word")
        return event
    source = hashlib.sha1(text.encode('utf-8')).hexdigest()[:12]
    known = next((e for e in memory['recent'] if e.get('dialogue') == source and isinstance(e.get('text'), str)), None)
    if known and known.get('hidden'):
        # a hidden memory (forgotten, taken back) is never sent again: its rewrite if it has one, else only that they talked
        rewrite = (known['hidden'] or {}).get('replaced_by')
        shown = next((e for e in memory['recent'] if rewrite and archive.entry_id(e) == rewrite and not e.get('hidden')), None)
        if shown is not None:
            return _compacted_event(npc.name, player, entry_text(shown, store), memory['feeling'])
        return f"{COMPACTED} {npc.name} talked with {player} earlier."
    if known:  # a loaded save hands the same lines over again
        return _compacted_event(npc.name, player, known['text'], memory['feeling'])
    prompt = SUMMARY_PROMPT.format(names=npc.name, game='Skyrim', player=player, language=ctx.get('language', 'English'),
                                   promises=json.dumps(open_promises(memory), ensure_ascii=False),
                                   bios=f"{npc.name}: {getattr(npc, 'bio', '')}")
    reply = _ask_summary(ctx['summaries'], said[-MAX_DIALOGUE_CHARS:], prompt, f"the earlier dialogue of {npc.name}")
    memory_line, feelings = parse_summary(reply, [npc.name]) if reply else ('', {})
    if not memory_line:
        return event
    stamp = branch.stamp() if branch is not None else {}
    entry = {'day': day, 'hour': hour, 'text': memory_line, 'witnesses': [npc.name], 'dialogue': source, **parse_meta(reply), **stamp}
    memory['recent'].append(entry)
    _link_promises(entry, memory, reply, day, stamp)
    feeling = feelings.get(npc.name, '')
    if feeling:
        _set_feeling(memory, feeling, day, stamp)
    record_mood(memory, parse_moods(reply, [npc.name]).get(npc.name, ''), feeling, day, hour, entry.get('importance'), stamp)
    if stamp:
        _settle_timeline(store, npc.name, npc.ref_id, memory, branch)
    _fold_and_save(store, npc.name, npc.ref_id, memory, ctx['summaries'], branch)
    return _compacted_event(npc.name, player, memory_line, feeling)


def _link_promises(entry: dict, memory: dict, reply: str, day: int, stamp: dict | None = None) -> None:
    """Adds the reply's promises to the facts and notes on the entry the ones it made: while any of them is still open,
    that memory does not fade, and it carries the 'promise' flag."""
    before = {id(f) for f in memory['facts']}
    add_promises(memory, reply, day, stamp)
    made = [f['text'] for f in memory['facts'] if id(f) not in before and f.get('status') == 'open']
    if made:
        entry['promises'] = made
        archive.add_flag(entry, 'promise')


GIFT_GOLD = 500       # gold from the player that is a gift worth remembering, whatever their purse...
GIFT_SHARE = 0.25     # ...or this share of what they carried
TAKEN_DAYS = 30       # World tells the theft line for 30 days: one 'taken' memory for it
_HANDED_GOLD = r"(?<![\w']){p} handed {n} ([\d,]+) gold"
_CAUGHT = (r"(?<![\w']){p} was caught stealing from {n}(?![\w'])", r"(?<![\w']){n} caught {p} picking their pocket")


def talk_flags(texts: list[str], name: str, player: str, purse=None) -> dict:
    """Fixed flags from a talk's own lines (World's trade results and its line on what the player did to them): {'gift':
    gold given, 'taken': True}. gift needs GIFT_GOLD, or GIFT_SHARE of purse (their gold before the talk) when known."""
    joined = ' '.join(str(t) for t in texts or [])
    p, n = re.escape(player or 'the player'), re.escape(name or '')
    if not n:
        return {}
    lines = {m.group(0): m.group(1) for t in texts or [] for m in re.finditer(r"\(?[^()]*?" + _HANDED_GOLD.format(p=p, n=n) + r"[^()]*\)?", str(t), re.I)}
    gold = sum(int(v.replace(',', '')) for v in {(re.sub(r"\W+", ' ', k).strip().lower()): v for k, v in lines.items()}.values())
    out = {}
    if gold >= GIFT_GOLD or (isinstance(purse, int) and purse > 0 and gold >= purse * GIFT_SHARE):
        out['gift'] = gold
    if any(re.search(c.format(p=p, n=n), joined, re.I) for c in _CAUGHT):
        out['taken'] = True
    return out


def _player_lines(talk) -> list[str]:
    said = lambda line: str(line.get_formatted_content() if hasattr(line, 'get_formatted_content') else getattr(line, 'text', line))
    return [said(l) for l in talk or [] if 'user' in type(l).__name__.lower()]


def _menu_made(group) -> bool:
    """Menu dialogue this talk showed (made into a memory by this summary), or a scene that became a memory at this talk's
    start, for someone in this group."""
    try:
        from . import menu_dialogue
        return any(name in menu_dialogue._talk_pending or name in menu_dialogue._talk_scenes for name in group)
    except Exception:
        return False


def _thread_texts(thread) -> list[str]:
    """Every event and line of a Mantella thread as text (for talk_flags); [] when it cannot be read."""
    try:
        messages = thread.get_talk_only(include_system_generated_messages=True)
    except (TypeError, AttributeError):
        return []
    out = []
    for message in messages:
        out += [str(e) for e in getattr(message, '_UserMessage__ingame_events', None) or []]
        out.append(str(message.get_formatted_content() if hasattr(message, 'get_formatted_content') else getattr(message, 'text', message)))
    return out


def apply_talk_flags(memory: dict, entry: dict, found: dict, today: int, recognised: bool = False) -> None:
    """Puts talk_flags' findings and the recognition on this talk's memory entry (taken once per TAKEN_DAYS, recognised
    once ever), then keeps only the latest two gift memories flagged (the older ones merged into the newer's count and
    total)."""
    if found.get('taken') and not any('taken' in (e.get('flags') or []) and 0 <= today - _int(e.get('day', -1)) <= TAKEN_DAYS
                                      for e in memory['recent']):
        archive.add_flag(entry, 'taken')
    if found.get('gift'):
        archive.add_flag(entry, 'gift')
        entry['gift_gold'] = int(found['gift'])
        entry['importance'] = max(archive.importance_of(entry), archive.FLAG_FLOORS['gift'])
        if str(found['gift']) not in str(entry.get('text') or '') and isinstance(entry.get('text'), str):
            entry['text'] = (entry['text'] + f" (A gift of {found['gift']} gold.)")[:MAX_ENTRY_CHARS]
    if recognised and not any('recognised' in (e.get('flags') or []) for e in memory['recent']):
        archive.add_flag(entry, 'recognised')


def thin_flag(memory: dict, flag: str, keep_first: bool = False, keep_last: int = 1, total_key: str = '') -> None:
    """Only the first (keep_first) and the latest keep_last memories of a flag stay flagged; the ones between lose the
    flag (keeping its importance) and are counted, with total_key's sum, on the latest: "(and N earlier ...)"."""
    items = [e for e in memory['recent'] if flag in (e.get('flags') or []) and not e.get('hidden')]
    middle = items[(1 if keep_first else 0):len(items) - keep_last]
    if not middle:
        return
    latest = items[-1]
    count = latest.get(f'{flag}_merged', 0) + len(middle)
    total = latest.get(total_key, 0) + sum(e.get(total_key, 0) for e in middle) if total_key else 0
    for e in middle:
        e['flags'] = [f for f in e['flags'] if f != flag]
        e['importance'] = max(archive.importance_of(e), archive.FLAG_FLOORS[flag])
        count += e.pop(f'{flag}_merged', 0)
    latest[f'{flag}_merged'] = count
    if total_key:
        latest[total_key] = total
    body = str(latest.get('text') or '').split(' (and ', 1)[0]
    extra = f", {total} gold in all" if total_key else ''
    latest['text'] = (body + f" (and {count} earlier time{'s' if count > 1 else ''}{extra})")[:MAX_ENTRY_CHARS]


def cap_flagged(memory: dict) -> None:
    """At most ALWAYS_CAP flagged memories in the list: past that, the oldest of the flag with the most entries merge
    into its newest older one, "(and N earlier times: day a, day b)", keeping the text of the newest of them."""
    while True:
        flagged = [e for e in memory['recent'] if any(f in KEEP_FLAGS for f in e.get('flags') or []) and not e.get('hidden')]
        if len(flagged) <= ALWAYS_CAP:
            return
        by_flag = {}
        for e in flagged:
            by_flag.setdefault(next(f for f in e['flags'] if f in KEEP_FLAGS), []).append(e)
        flag, items = max(by_flag.items(), key=lambda kv: len(kv[1]))
        if len(items) < 2:
            return  # every flag has one memory: nothing to merge (the cap is soft then)
        oldest, into = items[0], items[1]
        days = [d for d in (oldest.get('merged_days') or [oldest.get('day', -1)]) + (into.get('merged_days') or [into.get('day', -1)]) if d is not None]
        into['merged_days'] = days
        count = len(days) - 1
        body = str(into.get('text') or '').split(' (and ', 1)[0]
        into['text'] = (body + f" (and {count} earlier time{'s' if count > 1 else ''}: day {', day '.join(str(d) for d in days[:-1])})")[:MAX_ENTRY_CHARS]
        memory['recent'].remove(oldest)


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
    diary_for = ctx.get('diary_for') or (lambda character: False)  # the follower diary setting, off unless asked for
    # unrecognised(character) -> True: the game said they did not know who the player was in this talk (a hood)
    unrecognised = ctx.get('unrecognised') or (lambda character: False)
    branch = timeline.current(store, ctx.get('end_timestamp'))  # the save's talk counter, or None (older game side)
    from . import menu_dialogue
    for group in summaries.group_shared_threads(threads):
        try:
            _summarize_group(group, threads, wanted, store, ctx, summaries, player, day, hour, is_minor, diary_for,
                             unrecognised, branch, menu_dialogue)
        except Exception as e:  # one group's failure must not cost the other groups their memories
            logger.warning(f"Living World: the talk of {', '.join(group)} could not be saved ({e}); the others are kept")
    return True


def _summarize_group(group, threads, wanted, store, ctx, summaries, player, day, hour, is_minor, diary_for, unrecognised,
                     branch, menu_dialogue) -> None:
    """summarize for one group of NPCs who share a thread. Menu dialogue this talk showed for them (menu_dialogue.prepare)
    is made into a separate memory of each in the same request; a talk with no line at all, a trim mid-talk, a talk among
    NPCs or a summary that fails leaves those lines for the next talk."""
    params = threads[group[0]]
    hooded = {name for name in group if unrecognised(wanted[name])}
    who = HOODED if hooded and len(hooded) == len(group) else player  # the name, unless nobody here knew it
    talk = params.messages.get_talk_only()
    earlier = vanilla_dialogue(params.messages, player, store, day, ctx.get('chatter_filter', True))
    feelings = {}
    reply = ''
    story = {}
    menu, menu_names = {}, []
    if talk and not ctx.get('is_radiant') and not ctx.get('is_reload'):
        menu_names = menu_dialogue.pending_names(group)
    long_earlier = len(' '.join(earlier)) >= COMPACT_CHARS
    if len(talk) < 2 and not ctx.get('is_radiant') and not long_earlier and not menu_names:
        if not earlier:
            return
        text = f"Talked with {who} in passing: " + ' '.join(earlier)
    elif len(params.messages) < MIN_SUMMARY_MESSAGES and not ctx.get('is_radiant') and not long_earlier and not \
            short_but_important(_thread_texts(params.messages), _player_lines(talk),
                                talk_flags(_thread_texts(params.messages), group[0], player), _menu_made(group)):
        text = one_line(talk, who, group[0] if len(group) == 1 else '')
        if earlier:
            text = f"Talked with {who} in passing: " + ' '.join(earlier) + ' Then: ' + text
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
        if who == HOODED:
            prompt += HOODED_ASK.format(names=', '.join(group), player=player)
        if len(group) == 1 and not ctx.get('is_radiant'):
            prompt += FIRST_PERSON.format(name=group[0])
        prompt += NO_RELATIVE
        stories = arcs.prompt_list(store, [(name, wanted[name].ref_id) for name in group])
        prompt += STORY_ASK.format(stories=json.dumps(stories, ensure_ascii=False) if stories else 'none yet')
        said = params.messages.transform_to_dict_representation(talk)
        if earlier:
            vanilla = 'Earlier, in the normal dialogue menu:\n' + '\n'.join(earlier)[-MAX_DIALOGUE_CHARS:]
            said = vanilla + '\n\nThen this conversation:\n' + said if said else vanilla
        if menu_names:  # shown at the talk's start, made into each NPC's own memory here (one request for all)
            prompt += menu_dialogue.MENU_ASK.format(names=', '.join(menu_names), player=player)
            said = menu_dialogue.summary_text(menu_names, player) + '\n\nThen this conversation:\n' + said
        # one failed call must not cost the other groups their memories
        reply = _ask_summary(summaries, said, prompt, f"the talk of {', '.join(group)}")
        text, feelings = parse_summary(reply, group)
        menu = menu_dialogue.parse_menu(reply, menu_names) if menu_names else {}
        story = parse_story(reply)
        if not text and earlier:  # handed over only once: keep the words if the model gave nothing back
            text = f"Talked with {who} in passing: " + clip(' '.join(earlier), MAX_ENTRY_CHARS)
    for name, (line, meta) in menu.items():  # saved first: her earliest memory of the player is how they met
        if _save_menu(store, name, wanted[name], menu_dialogue.menu_entry(name, line, meta, player), summaries, branch):
            menu_dialogue.finish_menu(store, name)
    if not text:
        return
    text = strip_relative(text)
    if who == HOODED:  # they never knew the name: it stays out of this memory and their feeling
        text = mask_player(text, player)
        feelings = {k: mask_player(v, player) for k, v in feelings.items()}
    meta = parse_meta(reply) if reply else {'importance': SHORT_IMPORTANCE}
    entry = {'day': day, 'hour': hour, 'text': text, 'witnesses': list(group)}
    if len(group) > 1:
        entry = {'day': day, 'hour': hour, 'shared': store.save_shared(entry), 'witnesses': list(group)}
    entry.update(meta)
    entry.update(story)
    if ctx.get('is_radiant'):
        entry['radiant'] = True  # among NPCs only: not a talk with the player
    if ctx.get('is_reload'):
        entry['reload'] = True  # saved by a trim mid-talk: the same talk goes on
    for name in group:
        npc = wanted[name]
        try:  # one NPC's file failing must not cost the others this talk
            with store.lock(name, npc.ref_id):
                _save_talk(store, name, npc, entry, reply, feelings, day, dict(ctx, talk_texts=_thread_texts(params.messages),
                                                                               player=player), summaries, is_minor, diary_for,
                           parse_moods(reply, group) if reply else {}, branch)
        except Exception as e:
            logger.warning(f"Living World: this talk could not be saved for {name} ({e}); the others are kept")


def _save_menu(store: MemoryStore, name: str, npc, entry: dict | None, summaries, branch=None) -> bool:
    """Her memory of the menu dialogue this talk showed, saved on its own (menu_dialogue.menu_entry); True once it is in
    her file (also when it already was). Never raises."""
    if not entry:
        return False
    try:
        with store.lock(name, npc.ref_id):
            memory = store.load(name, npc.ref_id)
            if any(e.get('dialogue') == entry['dialogue'] for e in memory['recent']):
                return True
            added = dict(entry, **(branch.stamp() if branch is not None else {}))
            if first_contact(memory):
                archive.add_flag(added, 'first_meeting')  # the earliest memory of the player is how they met (live test 15)
            memory['recent'].append(added)
            _fold_and_save(store, name, npc.ref_id, memory, summaries, branch)
        return True
    except Exception as e:
        logger.warning(f"Living World: the menu dialogue memory of {name} could not be saved ({e}); kept for the next talk")
        return False


def _save_talk(store: MemoryStore, name: str, npc, entry: dict, reply: str, feelings: dict, day: int, ctx: dict, summaries,
               is_minor, diary_for, moods: dict | None = None, branch=None) -> None:
    """One witness's part of summarize, with their memory file's lock held."""
    try:
        memory = store.load(name, npc.ref_id)
    except OSError as e:  # locked: saving now would replace the whole file with this one talk
        logger.warning(f"Living World: {name}'s memory is locked ({e}); this talk is not saved for them")
        return
    added = dict(entry)
    stamp = branch.stamp() if branch is not None else {}
    added.update(stamp)
    if ctx.get('command_for'):
        tag = ctx['command_for'](npc)  # an absolute command in force for them: this talk was under it (command.py)
        if tag:
            added['command'] = tag
    if ctx.get('unrecognised') and ctx['unrecognised'](npc):
        added['unrecognised'] = True  # a talk with a hooded stranger: never counts toward knowing the player
    if stamp:
        _stamp_pending(store, name, npc.ref_id, memory, branch)
    if not ctx.get('is_radiant') and ctx.get('talk_texts') is not None:
        purse = ctx.get('purse_for')(npc) if callable(ctx.get('purse_for')) else None
        known_before = any(e.get('unrecognised') for e in memory['recent'])
        apply_talk_flags(memory, added, talk_flags(ctx['talk_texts'], name, ctx.get('player') or '', purse), day,
                         recognised=known_before and not added.get('unrecognised'))
    if not ctx.get('is_radiant') and not ctx.get('is_reload') and first_contact(memory):
        archive.add_flag(added, 'first_meeting')  # their first talk with the player: how they met
    memory['recent'].append(added)
    if not ctx.get('is_radiant') and not ctx.get('is_reload'):  # a trim mid-talk is not a new talk
        memory['talks'] = max(memory.get('talks', 0), _player_talks(memory) - 1) + 1
    if reply and not ctx.get('is_radiant'):
        _link_promises(added, memory, reply, day, stamp)
        if not is_minor(npc):
            add_profile(memory, reply, name)
    thin_flag(memory, 'gift', keep_last=2, total_key='gift_gold')
    if feelings.get(name):
        _set_feeling(memory, feelings[name], day, stamp)
    record_mood(memory, (moods or {}).get(name, ''), feelings.get(name, ''), day, added.get('hour', -1), added.get('importance'), stamp)
    if stamp:
        _settle_timeline(store, name, npc.ref_id, memory, branch)
    if diary_for(npc):
        write_diary(store, name, npc.ref_id, memory, summaries, day, ctx.get('language', 'English'), stamp)
    _fold_and_save(store, name, npc.ref_id, memory, summaries, branch)


def memory_text(text: str, ctx: dict, store: MemoryStore, budget_tokens: int = DEFAULT_BUDGET, budget_for=None) -> str:
    """The 'memory_text' hook: our memories in the prompt; Mantella's text for anyone we have nothing for.
    budget_for(character) -> tokens, when each NPC has their own limit (strangers remember less of the player).
    ctx may also hold today (the game side's day, GameDaysPassed), player, facts_for(character) -> rows from
    lw_state.game_facts(), and profile_seen(character, profile), told each NPC's profile: the player's override if there
    is one, else the rated one. Older memories the talk is about come back (recall) unless ctx recall is False;
    recall_query(character) -> extra text for what the talk is about (who is near, what was just said)."""
    characters = ctx.get('characters') or []
    blocks = []
    today = None if ctx.get('today') is None else ctx['today'] + MANTELLA_DAY
    share = max(1, len(characters))
    player = ctx.get('player') or 'the player'
    facts_for = ctx.get('facts_for') or (lambda character: [])
    overrides = ctx.get('profile_overrides') or {}
    is_minor = ctx.get('is_minor') or (lambda character: False)
    # memories made after the loaded save are left out (None: older game side); game_days, when the caller has it, lets
    # a counter still holding a newer save be told apart
    branch = timeline.current(store, ctx.get('game_days'))
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
        known = facts_text(memory, facts_for(character), today, player, character.name, max(FACT_TOKENS // share, MIN_GROUP_FACT_TOKENS), profile,
                           branch)
        recalled = []
        if ctx.get('recall', True):
            extra = ctx['recall_query'](character) if ctx.get('recall_query') else ''
            others = [c.name for c in characters if c is not character] + [player]
            recalled = recall(store, character.name, character.ref_id, memory, recall_query(memory, others, extra, store, branch), today,
                              branch=branch)
        extra = ctx['extra_for'](character) if ctx.get('extra_for') else ''  # menu dialogue since her last talk, as said
        body = '\n'.join(part for part in (known, render(memory, budget // share, store, today, recalled, branch), extra) if part)
        if body and ctx.get('knows_player') and ctx['knows_player'](character):  # the hooded stranger was the player
            body = '\n'.join(part for part in (body, connection_line(memory, character.name, player, branch)) if part)
        if not body:
            continue
        if len(characters) > 1:
            body = (f"[This is the beginning of {character.name}'s memory. Only {character.name} knows what is in this block; "
                    f"the others here learn it only if {character.name} says it aloud.]\n{body}\n[This is the end of {character.name}'s memory]")
        blocks.append(body)
    if not blocks:
        return text
    return "Below is a summary of past events:\n" + '\n\n'.join(blocks)


def recall_query(memory: dict, people: list[str], extra: str = '', store: MemoryStore | None = None, branch=None) -> str:
    """What the coming talk is likely about: who is there, the newest few memories, and anything the caller adds."""
    newest = [entry_text(e, store) for e in memory.get('recent', []) if not e.get('hidden') and timeline.usable(branch, e)][-3:]
    return '\n'.join(part for part in (', '.join(p for p in people if p), *newest, extra) if part and part.strip())


def recall(store: MemoryStore, name: str, ref_id: str, memory: dict, query: str, today: int | None = None,
           limit: int = RECALL_COUNT, branch=None) -> list[dict]:
    """Older memories (in the archive, no longer in recent) that fit the query, by meaning when the model is ready,
    else by shared words, times how strongly each is still remembered (archive.rank). Hidden ones, ones from a later
    day and ones from talks after the loaded save (branch, timeline.py) never come back. Of several that belong to one
    story arc only the best one comes, with the arc's line (arc_line), so the rest of the limit goes to other things.
    Each one recalled counts as remembered again today. Never raises."""
    if store is None or not str(query).strip():
        return []
    try:
        store_db = store.archive_for(name, ref_id)
        if not store_db.exists():
            return []
        in_recent = {archive.entry_id(e) for e in memory.get('recent', [])}
        later = lambda day: today is not None and 0 <= today < _int(day)
        rows = [r for r in store_db.rows() if r['id'] not in in_recent and not later(r.get('day', -1)) and r.get('text')
                and timeline.usable(branch, r)]
        rows = archive.search_rows(rows)  # on the request thread: a huge archive must not hold up the reply
        ranked = archive.rank(query, rows, today, open_promises(memory), embed.current(), limit * 3)
        store_db.store_vectors(rows)
        lines = arcs.lines_for(store_db, [row for _, row in ranked], lambda r: timeline.usable(branch, r)) if any(
            row.get('arc') for _, row in ranked) else {}
        picked, told = [], set()
        for _, row in ranked:
            line = lines.get(row.get('arc')) if row.get('arc') else ''
            if line:
                if row['arc'] in told:
                    continue  # the story's line already covers it
                told.add(row['arc'])
                row['arc_line'] = line
            picked.append(row)
            if len(picked) >= limit:
                break
        store_db.mark_recalled([r['id'] for r in picked], today)
        return picked
    except Exception as e:  # the memory still works without old memories
        logger.warning(f"Living World: could not recall {name}'s older memories ({e})")
        return []


def write_diary(store: MemoryStore, name: str, ref_id: str, memory: dict, summaries, day: int, language: str = 'English',
                stamp: dict | None = None) -> str:
    """A follower's diary entry (follower diary setting, off by default): at most one per game day, written for the
    latest earlier day that has memories and no entry yet, in one extra summary call, and kept in the archive as a memory
    of its own (type diary). memory['diary_day'] is moved on even if the call fails, so a day is never asked twice."""
    if day < 0:
        return ''
    last = _int(memory.get('diary_day'), -1)
    past = [e for e in memory.get('recent', []) if last < _int(e.get('day')) < day and not e.get('hidden') and not e.get('reload')]
    if not past:
        return ''
    target = max(e['day'] for e in past)
    lines = [_line(e, store) for e in past if e['day'] == target]
    memory['diary_day'] = target
    try:
        reply = summaries.summarize_conversation('\n'.join(lines), DIARY_PROMPT.format(name=name, game='Skyrim', language=language))
    except Exception as e:
        logger.warning(f"Living World: {name}'s diary entry could not be written ({e})")
        return ''
    text = ' '.join(str(reply or '').split())[:MAX_FACT_CHARS * 2]
    if not text:
        return ''
    entry = {'day': target, 'hour': 23, 'text': text, 'witnesses': [name], 'type': 'diary', 'importance': 0.4, 'source': 'own',
             **(stamp or {})}
    try:
        store.archive_for(name, ref_id).add([(entry, text)], embed.current())
    except (sqlite3.Error, OSError) as e:
        logger.warning(f"Living World: {name}'s diary entry could not be kept ({e})")
        return ''
    return text


# Hidden memories: the NPC no longer has them in mind. A hidden memory is never shown to the model, never recalled, and
# never folded or compressed into 'earlier'; it stays in the archive, so unhide() brings it back as it was.

def _strip_names(query: str, names) -> str:
    """The query without these names (and their possessive): every memory of an NPC is about them and the player, so
    the names alone would make an unrelated memory look close."""
    for name in sorted({str(n) for n in names or () if n and str(n).strip()}, key=len, reverse=True):
        query = re.sub(r"\b" + re.escape(name.strip()) + r"(?:'s)?\b", ' ', query, flags=re.I)
    return ' '.join(query.split()).strip(' ,;:')


def hide_matching(store: MemoryStore, name: str, ref_id: str, query: str, limit: int = 1, by: str = '', note: str = '',
                  day: int = -1, skip=(), strip=(), only=None, confirm=None) -> list[dict]:
    """Hides up to limit of this NPC's memories closest in meaning to query (shared words without the model), recent or
    archived, and returns them as [{id, day, hour, text}]. hidden = {day, by, note} is kept on each. A memory already
    folded into 'earlier' is also taken out of that text (_forget_in_earlier: its line, or 'earlier' made again without
    it when the line is no longer there word for word). Memories whose id is in
    skip are never picked; with only (ids) nothing else is; the NPC's own name and the names in strip are left out of
    the query. A close match is hidden at once; a looser one (archive.hide_candidates) only when confirm(texts) -> one
    True/False per text (the summary model) says it holds the thing, never without confirm. confirm runs without the
    file's lock held. The promises a hidden memory made are hidden with it (hidden_with on the fact), so they leave the
    prompt too. Never raises."""
    with store.lock(name, ref_id):
        try:
            memory = store.load(name, ref_id)
            store.sync_archive(name, ref_id, memory)  # every recent memory is searchable
            store_db = store.archive_for(name, ref_id)
            skip = set(skip or ())
            branch = timeline.current(store)  # a memory of a talk after the loaded save is not in mind to forget
            rows = [r for r in store_db.rows() if r.get('id') not in skip and (only is None or r.get('id') in only)
                    and timeline.usable(branch, r)]
            query = _strip_names(str(query), [name, *strip]) or str(query)
            sure, unsure = archive.hide_candidates(query, rows, embed.current(), max(0, limit))
        except (sqlite3.Error, OSError) as e:
            logger.warning(f"Living World: could not hide {name}'s memories ({e})")
            return []
    if unsure and confirm is not None:
        try:
            answers = confirm([r.get('text') or '' for r in unsure])
        except Exception as e:
            logger.warning(f"Living World: could not check which of {name}'s memories to hide ({e})")
            answers = None
        if isinstance(answers, list) and len(answers) == len(unsure):
            sure = sure + [r for r, yes in zip(unsure, answers) if yes is True]
    with store.lock(name, ref_id):
        picked = sure
        if not picked:
            return []
        mark = {'day': _int(day), 'by': str(by or ''), 'note': str(note or '')[:MAX_FACT_CHARS]}
        ids = [r['id'] for r in picked]
        try:
            # read again: ranking can take a while (the model, a big archive), and whatever saved the file meanwhile
            # without this lock (an older caller) must not be lost by saving the copy read before it
            memory = store.load(name, ref_id)
            store_db.set_hidden(ids, mark)
            for entry in memory['recent']:
                if archive.entry_id(entry) in ids:
                    entry['hidden'] = dict(mark)
            for row in picked:
                made = list(row.get('promises') or []) + next((list(e.get('promises') or []) for e in memory['recent']
                                                              if archive.entry_id(e) == row['id']), [])
                for fact in memory['facts']:
                    if not fact.get('hidden_with') and any(_same_promise(fact['text'], p) for p in made if isinstance(p, str)):
                        fact['hidden_with'] = row['id']
            _forget_in_earlier(store, name, ref_id, memory, picked, branch)
            store.save(name, ref_id, memory)
        except (sqlite3.Error, OSError) as e:
            logger.warning(f"Living World: could not hide {name}'s memories ({e})")
            return []
        return [{'id': r['id'], 'day': r.get('day', -1), 'hour': r.get('hour', -1), 'text': r.get('text', '')} for r in picked]


def mark_spell(store: MemoryStore, name: str, ref_id: str, command_id: str, label: str, ids=()) -> int:
    """Marks this NPC's memories made under an absolute command (their command field, or these ids) with label
    ("while under <player>'s spell", shown before the text, see spelled), in the memory file and in the archive, so a
    memory folded away keeps it when a talk brings it back. Returns how many were marked. Never raises."""
    ids = set(ids or ())
    try:
        with store.lock(name, ref_id):
            mem = store.load(name, ref_id)
            count, marked = 0, set()
            for entry in mem['recent']:
                mine = (command_id and entry.get('command') == command_id) or archive.entry_id(entry) in ids
                if mine:
                    marked.add(archive.entry_id(entry))
                    if entry.get('spell') != label:
                        entry['spell'] = label
                        count += 1
            if count:
                store.save(name, ref_id, mem)
            db = store.archive_for(name, ref_id)
            if db.exists():
                rows = set(db.ids_of_command(command_id)) | ids | marked
                count += db.set_spell(sorted(rows - marked), label)
                db.set_spell(sorted(marked), label)
        return count
    except Exception as e:
        logger.warning(f"Living World: could not mark {name}'s memories from under the spell ({e})")
        return 0


def unhide(store: MemoryStore, name: str, ref_id: str, memory_id: str) -> bool:
    """Brings one hidden memory back (by the id hide_matching or list_hidden gave), with the promises hidden with it.
    False when nothing was hidden. A memory that was rewritten in its place (add_rewrite: replaced_by on its mark) is
    hidden again, so the two never show at once."""
    with store.lock(name, ref_id):
        try:
            store_db = store.archive_for(name, ref_id)
            memory = store.load(name, ref_id)
            marks = {r['id']: r.get('hidden') for r in (store_db.rows(hidden=True) if store_db.exists() else [])}
            marks.update({archive.entry_id(e): e['hidden'] for e in memory['recent'] if e.get('hidden')})
            changed = store_db.set_hidden([memory_id], None) > 0
            for entry in memory['recent']:
                if entry.get('hidden') and archive.entry_id(entry) == memory_id:
                    entry.pop('hidden')
                    changed = True
            if changed:
                for fact in memory['facts']:
                    if fact.get('hidden_with') == memory_id:
                        fact.pop('hidden_with')
                # the rewrite (or, when that was rewritten again, the newest one still shown) goes out of mind
                replaced, seen = (marks.get(memory_id) or {}).get('replaced_by'), {memory_id}
                while isinstance(replaced, str) and replaced not in seen:
                    seen.add(replaced)
                    if not marks.get(replaced):
                        mark = {'day': -1, 'by': (marks.get(memory_id) or {}).get('by', ''), 'note': 'the original memory is back'}
                        store_db.set_hidden([replaced], mark)
                        for entry in memory['recent']:
                            if archive.entry_id(entry) == replaced:
                                entry['hidden'] = dict(mark)
                        break
                    replaced = (marks.get(replaced) or {}).get('replaced_by')
                store.save(name, ref_id, memory)
            return changed
        except (sqlite3.Error, OSError) as e:
            logger.warning(f"Living World: could not unhide {name}'s memory ({e})")
            return False


REWRITE_KEYS = ('day', 'hour', 'importance', 'emotion', 'type', 'tags', 'witnesses', 'radiant', 'command', 'source', 'told_by',
                'talk', 'seq')


def add_rewrite(store: MemoryStore, name: str, ref_id: str, memory_id: str, text: str) -> str:
    """Puts text in place of the hidden memory memory_id: a new memory with its day, hour, importance and the rest,
    right after it in recent when it is still there, else in the archive. The original's mark gets replaced_by, so
    unhide() brings it back and hides the new one. Returns the new memory's id, '' when nothing was added. Never raises."""
    text = ' '.join(str(text or '').split())[:MAX_ENTRY_CHARS]
    if not text:
        return ''
    with store.lock(name, ref_id):
        return _add_rewrite(store, name, ref_id, memory_id, text)


def _add_rewrite(store: MemoryStore, name: str, ref_id: str, memory_id: str, text: str) -> str:
    try:
        store_db = store.archive_for(name, ref_id)
        memory = store.load(name, ref_id)
        spot = next((i for i, e in enumerate(memory['recent']) if archive.entry_id(e) == memory_id), None)
        if spot is not None:
            entry = memory['recent'][spot]
        else:
            entry = next((r for r in (store_db.rows(hidden=True) if store_db.exists() else []) if r['id'] == memory_id), None)
        if not entry or not entry.get('hidden'):
            return ''
        added = {k: entry.get(k) for k in REWRITE_KEYS if entry.get(k) is not None}
        added['text'] = text
        new_id = archive.entry_id(added)
        if new_id == memory_id:
            return ''
        mark = dict(entry['hidden'], replaced_by=new_id)
        store_db.set_hidden([memory_id], mark)
        if spot is not None:
            entry['hidden'] = mark
            memory['recent'].insert(spot + 1, added)
            store.save(name, ref_id, memory)
        else:
            store_db.add([(added, text)], embed.current())
        return new_id
    except (sqlite3.Error, OSError) as e:
        logger.warning(f"Living World: could not add {name}'s rewritten memory ({e})")
        return ''


def list_hidden(store: MemoryStore, name: str, ref_id: str) -> list[dict]:
    """[{id, day, hour, text, hidden: {day, by, note}}], oldest first."""
    try:
        store_db = store.archive_for(name, ref_id)
        rows = store_db.rows(hidden=True) if store_db.exists() else []
    except (sqlite3.Error, OSError):
        return []
    return [{'id': r['id'], 'day': r.get('day', -1), 'hour': r.get('hour', -1), 'text': r.get('text', ''), 'hidden': r.get('hidden')}
            for r in rows]


# Mood: how the NPC feels right now, from the end of their last talk (the summary call's "moods"), fading back to
# neutral over a few game days. Kept as a short history (moods), so loading an earlier save finds the mood it had then.

def clean_mood(value) -> str:
    return ' '.join(value.split())[:MAX_MOOD_CHARS].strip(' .') if isinstance(value, str) else ''


def parse_moods(reply: str, names: list[str]) -> dict[str, str]:
    """{name: mood} from the summary reply; with one NPC any single mood is theirs."""
    moods = _summary_data(reply).get('moods')
    if len(names) == 1:
        if isinstance(moods, str):
            moods = {names[0]: moods}
        elif isinstance(moods, dict) and len(moods) == 1:
            moods = {names[0]: next(iter(moods.values()))}
    if not isinstance(moods, dict):
        return {}
    return {k: clean_mood(v) for k, v in moods.items() if k in names and clean_mood(v)}


def parse_story(reply: str) -> dict:
    """{arc_label, arc_summary} from the summary reply's "story", or {} when this talk is no part of a story."""
    story = _summary_data(reply).get('story')
    if not isinstance(story, dict):
        return {}
    label = arcs.clean_label(story.get('label')) if isinstance(story.get('label'), str) else ''
    if not label:
        return {}
    so_far = arcs.clean_summary(story.get('so_far')) if isinstance(story.get('so_far'), str) else ''
    return {'arc_label': label, **({'arc_summary': so_far} if so_far else {})}


def _set_feeling(memory: dict, feeling: str, day: int, stamp: dict) -> None:
    memory['feeling'] = feeling
    memory['feeling_day'] = day
    memory.pop('feeling_talk', None)
    memory.pop('feeling_seq', None)
    if stamp:
        memory['feeling_talk'], memory['feeling_seq'] = stamp['talk'], stamp['seq']


def record_mood(memory: dict, mood: str, feeling: str, day: int, hour: int, importance, stamp: dict | None = None) -> None:
    mood = clean_mood(mood)
    if not mood and not feeling:
        return
    memory.setdefault('moods', []).append({'day': _int(day), 'hour': _int(hour), 'mood': mood, 'feeling': str(feeling or '')[:MAX_FEELING_CHARS],
                                           'importance': archive.importance_of({'importance': importance}), **(stamp or {})})
    memory['moods'] = memory['moods'][-MAX_MOODS:]


def _feeling(memory: dict, branch=None) -> str:
    """How they feel about the player. Without a counter, the stored feeling as before. With one, a feeling from a talk
    after the loaded save gives way to the newest one from before it."""
    feeling = memory.get('feeling') or ''
    if branch is None or not feeling:
        return feeling
    if timeline.usable(branch, {'talk': memory.get('feeling_talk'), 'seq': memory.get('feeling_seq')}):
        return feeling
    return next((m['feeling'] for m in reversed(memory.get('moods') or []) if m.get('feeling') and timeline.usable(branch, m)), '')


def mood_text(memory: dict, today: int | None = None, branch=None) -> str:
    """The mood line for the prompt (today dated like the memories), '' once it has faded or when there is none."""
    chosen = None
    for m in reversed(memory.get('moods') or []):
        if not m.get('mood') or not timeline.usable(branch, m) or (today is not None and 0 <= today < _int(m.get('day'))):
            continue
        chosen = m
        break
    if chosen is None:
        return ''
    day = _int(chosen.get('day'))
    old = today - day if today is not None and day >= 0 else 0
    if old >= MOOD_MIN_DAYS + MOOD_EXTRA_DAYS * archive.importance_of(chosen):
        return ''  # back to their usual self
    if old < 1:
        return f"Your mood since your last talk: {chosen['mood']}."
    return f"Your mood lately, slowly fading: {chosen['mood']}."


def _who(npc) -> tuple[str, str]:
    if isinstance(npc, (tuple, list)) and len(npc) == 2:
        return str(npc[0]), str(npc[1])
    if isinstance(npc, dict):
        return str(npc.get('name') or ''), str(npc.get('ref_id') or '')
    return str(getattr(npc, 'name', '') or ''), str(getattr(npc, 'ref_id', '') or '')


def mood_line(npc, store: MemoryStore, today: int | None = None) -> str:
    """One short line on how this NPC feels right now (a Mantella character, a {name, ref_id} dict or a (name, ref_id)
    pair). today is the game side's day (GameDaysPassed); None reads it from conversation.json. '' when neutral."""
    name, ref_id = _who(npc)
    if not name or store is None:
        return ''
    if today is None:
        today = lw_state.load_today()
    return mood_text(_peek(store, name, ref_id), None if today is None else today + MANTELLA_DAY, timeline.current(store))


# Memories from outside a talk (world news, rumours, things they were told): for an NPC who need not be in the talk.

def add_memory(store: MemoryStore, name: str, ref_id: str, text: str, source: str = 'seen', told_by: str = '',
               day: int | None = None, hour: int = -1, importance: float | None = None, key: str = '',
               kind: str = 'knowledge', tags=None, emotion: str = '', flags: dict | None = None) -> str:
    """Adds one memory to this NPC's memory (by name and ref id, as their memory file is named), in time order, and
    returns its id ('' when nothing was added). source: seen, told (told_by: who told them), rumour or own. day is dated
    like the memories (the game's day + 1); None takes today from conversation.json. key: an id of what it is about (a
    world event): a key this NPC already has is never added again. Stamped with the running talk of the save's timeline
    when there is one. No model call and no folding (the next talk's save folds). Never raises."""
    text = ' '.join(str(text or '').split())[:MAX_ENTRY_CHARS]
    if not text or not name:
        return ''
    source = source if source in archive.SOURCES else 'seen'
    if day is None:
        today = lw_state.load_today()
        day = today + MANTELLA_DAY if today is not None else -1
    with store.lock(name, ref_id):
        try:
            memory = store.load(name, ref_id)
        except OSError:
            return ''
        key = str(key or '')[:120]
        if key and (key in memory.get('keys', []) or any(e.get('key') == key for e in memory['recent'])):
            return ''
        entry = {'day': _int(day), 'hour': _int(hour), 'text': text, 'witnesses': [name], 'source': source,
                 'type': kind if kind in archive.TYPES and kind != 'diary' else 'knowledge'}
        if source == 'told' and str(told_by or '').strip():
            entry['told_by'] = ' '.join(str(told_by).split())[:80]
        if importance is not None:
            entry['importance'] = archive.importance_of({'importance': importance})
        if emotion:
            entry['emotion'] = str(emotion).strip().lower()[:30]
        if isinstance(tags, (list, tuple)):
            entry['tags'] = [str(t).strip().lower()[:30] for t in tags if str(t).strip()][:MAX_TAGS]
        if flags and flags.get('unrecognised'):
            entry['unrecognised'] = True  # names the player as a hooded stranger (connection_line)
        for flag in (f for f, on in (flags or {}).items() if on and f in archive.FLAG_FLOORS):
            archive.add_flag(entry, flag)  # a fixed "always important" flag (a death they saw or were told by family)
        branch = timeline.current(store)
        entry.update(branch.stamp() if branch is not None else {})
        if key:
            entry['key'] = key
            memory['keys'] = (memory.get('keys', []) + [key])[-MAX_KEYS:]
        at = len(memory['recent'])
        while at > 0 and (memory['recent'][at - 1].get('day', -1), memory['recent'][at - 1].get('hour', -1)) > (entry['day'], entry['hour']):
            at -= 1
        memory['recent'].insert(at, entry)
        try:
            if entry.get('talk'):
                _settle_timeline(store, name, ref_id, memory, branch)
            store.save(name, ref_id, memory)
        except OSError as e:
            logger.warning(f"Living World: could not add a memory for {name} ({e})")
            return ''
        return archive.entry_id(entry)


# Save-and-reload safety (timeline.py): memories of talks after the loaded save are set aside, and once the new
# timeline has a memory of its own they are marked as another timeline (the loaded save's own line always wins).

def _settle_timeline(store: MemoryStore, name: str, ref_id: str, memory: dict, branch) -> None:
    """A memory was just made on this timeline: what is set aside now is marked as another timeline (never deleted), and
    a mark on a memory of the loaded save's own line is taken off. Never raises."""
    if branch is None or not branch.open:
        return
    try:
        timeline.abandon(store, branch)
        for entry in memory['recent']:
            if entry.get('timeline') != timeline.OTHER and timeline.state(branch, entry) != timeline.OK:
                entry['timeline'] = timeline.OTHER
            elif entry.get('timeline') == timeline.OTHER and branch.mine(entry.get('talk')):
                entry.pop('timeline')  # the loaded save's own line again (the newer save was loaded back)
        store_db = store.archive_for(name, ref_id)
        if store_db.exists():
            store_db.set_branch([r['id'] for r in store_db.rows(hidden=None)
                                 if r.get('branch') != timeline.OTHER and timeline.state(branch, r) != timeline.OK], timeline.OTHER)
    except Exception as e:
        logger.warning(f"Living World: could not mark {name}'s memories of another timeline ({e})")


def _stamp_pending(store: MemoryStore, name: str, ref_id: str, memory: dict, branch) -> None:
    """The earlier dialogue a talk starts with is saved before the game has written that talk's id (its first request
    goes out first). At the talk's end those memories get the talk's stamp: unstamped dialogue memories from the hour
    before the talk started, or later."""
    if branch is None or not branch.open or branch.time is None:
        return
    start = day_hour(branch.time + MANTELLA_DAY - 1 / 24)
    ids = []
    for entry in memory['recent']:
        if entry.get('dialogue') and not entry.get('talk') and (entry.get('day', -1), entry.get('hour', -1)) >= start:
            entry.update(branch.stamp())
            ids.append(archive.entry_id(entry))
    if ids:
        try:
            store.archive_for(name, ref_id).set_talk(ids, branch.id, branch.seq)
        except (sqlite3.Error, OSError) as e:
            logger.warning(f"Living World: could not stamp {name}'s earlier dialogue with its talk ({e})")


def list_other_timeline(store: MemoryStore, name: str, ref_id: str) -> list[dict]:
    """[{id, day, hour, text, talk, seq, state}] of this NPC's memories that are not of the loaded save's timeline,
    oldest first: state 'aside' (made after the loaded save; loading the newer save brings them back) or 'other'
    (another timeline, seen from the loaded save). Never raises."""
    try:
        store_db = store.archive_for(name, ref_id)
        rows = store_db.rows(hidden=None) if store_db.exists() else []
    except (sqlite3.Error, OSError):
        return []
    branch = timeline.current(store)
    out = []
    for r in rows:
        state = timeline.state(branch, r)
        if state != timeline.OK:
            out.append({'id': r['id'], 'day': r.get('day', -1), 'hour': r.get('hour', -1), 'text': r.get('text', ''),
                        'talk': r.get('talk'), 'seq': r.get('seq'), 'state': state})
    return out
