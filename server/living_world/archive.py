"""Every memory an NPC ever had, kept for good, so folding old memories into the short 'earlier' text no longer loses
them. One SQLite file per NPC next to their memory file: <name> - <ref id>.archive.sqlite.

SQLite (Python's own sqlite3) rather than JSON: each memory carries 384 numbers for meaning search, stored as a small
binary block; adding a memory is one row, not rewriting a file that keeps growing; and a write is all or nothing. One
file per NPC, so resetting or backing up one NPC moves their files as before.

Each row: id (from the entry itself, see entry_id), day, hour, text, witnesses, importance 0-1, emotion, type, tags,
the promises that talk made, hidden {day, by, note} or nothing, the day it last came to mind, and its embedding. Also:
how they know it (source: seen, told with told_by, rumour, own), the talk that made it (talk id and seq, see
timeline.py; branch 'other' once it is marked as an abandoned timeline; the loaded save's own line still wins) and the
story arc it belongs to (arc, an id in the arcs table, see arcs.py). Archives from before these columns get them on
first open (source 'seen').

Also here: how memories fade (retention) and how they are ranked against a query (search), by meaning when the model
is loaded, else by shared words."""
import hashlib
import json
import logging
import math
import os
import re
import sqlite3
import threading
import time
from collections import Counter
from contextlib import closing

from . import embed

logger = logging.getLogger('Mantella')

DEFAULT_IMPORTANCE = 0.5  # memories from before importance was rated, and ones added by hand
TYPES = ('experience', 'relationship', 'knowledge', 'trauma', 'joy', 'diary')
MIN_MEANING = 0.25  # cosine similarity below this is a different subject (this model puts unrelated text near 0.1)
MIN_WORDS = 0.12  # the same for shared words
MIN_HIDE_MEANING = 0.4  # hiding (a forget, a take-back) needs a much closer fit than bringing a memory back...
HIDE_MARGIN = 0.1  # ...and no further than this below the best fit
MAX_SEARCH_ROWS = 600  # rows one search looks at: the newest, then the most important of the older ones
SEARCH_IMPORTANT = 150  # of those, this many are the most important older ones
MAX_EMBED_AT_SEARCH = 64  # rows a search may embed on the spot; more and it uses words this time
BACKFILL = 32  # rows without numbers embedded per save (the model was not ready when they were added)

SOURCES = ('seen', 'told', 'rumour', 'own')  # how they know it: were there, were told (told_by), heard it, thought it
SCHEMA = """CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY, day INTEGER, hour INTEGER, text TEXT, witnesses TEXT, importance REAL, emotion TEXT, type TEXT,
    tags TEXT, promises TEXT, shared TEXT, radiant INTEGER, hidden TEXT, recalled_day INTEGER DEFAULT -1, added REAL,
    embedding BLOB, model TEXT, source TEXT DEFAULT 'seen', told_by TEXT, talk TEXT, seq INTEGER, branch TEXT, arc TEXT,
    command TEXT, spell TEXT)"""
ARC_SCHEMA = """CREATE TABLE IF NOT EXISTS arcs (
    id TEXT PRIMARY KEY, label TEXT, summary TEXT, day INTEGER DEFAULT -1, made REAL, by_hand INTEGER DEFAULT 0)"""
# columns added after the first release: (name, type as ALTER TABLE adds it); existing rows get the default
ADDED_COLUMNS = (('source', "TEXT DEFAULT 'seen'"), ('told_by', 'TEXT'), ('talk', 'TEXT'), ('seq', 'INTEGER'),
                 ('branch', 'TEXT'), ('arc', 'TEXT'), ('command', 'TEXT'), ('spell', 'TEXT'))
COLUMNS = ('id', 'day', 'hour', 'text', 'witnesses', 'importance', 'emotion', 'type', 'tags', 'promises', 'shared',
           'radiant', 'hidden', 'recalled_day', 'added', 'embedding', 'model', 'source', 'told_by', 'talk', 'seq', 'branch',
           'arc', 'command', 'spell')  # command: the absolute command in force when it was made; spell: its release mark
# A memory saved as the summary model's raw JSON reply ('{"memory": "...", "feelings": ...'): live test 12, a reply cut
# off before its end could not be read as JSON and was kept whole. Shown and used as its memory text.
_WRAPPED = re.compile(r'^\s*(?:```(?:json)?\s*)?\{\s*"memory"\s*:\s*"((?:[^"\\]|\\.)*)"', re.S)


_WRAPPED_OPEN = re.compile(r'^\s*(?:```(?:json)?\s*)?\{\s*"memory"\s*:\s*"((?:[^"\\]|\\.)*)$', re.S)


def unwrap_text(text):
    """The memory text inside a stored summary wrapper; any other text (or a value that is not text) unchanged."""
    if not isinstance(text, str) or '"memory"' not in text[:60]:
        return text
    found = _WRAPPED.match(text) or _WRAPPED_OPEN.match(text)  # the second: cut off inside the memory text itself
    if not found:
        return text
    raw = found.group(1).rstrip('\\')
    try:
        inner = json.loads('"' + raw + '"').strip()
    except ValueError:
        inner = raw.replace('\\"', '"').strip()
    return inner or text


JSON_COLUMNS = ('witnesses', 'tags', 'promises', 'hidden')


def entry_id(entry: dict) -> str:
    """The same entry always gets the same id, so the memory file needs no new field: day, hour and its text (or, for a
    shared group memory, its shared key). An edited text is a new memory."""
    body = 'shared:' + str(entry['shared']) if entry.get('shared') else str(entry.get('text') or '')
    return hashlib.sha1(f"{entry.get('day', -1)}|{entry.get('hour', -1)}|{body}".encode('utf-8')).hexdigest()[:16]


# Fixed "always important" flags on a memory (entry['flags']), set from game facts and event kinds, never by the model:
# each lifts the memory's importance to at least its floor, and a flagged memory stays in the memory list (memory.py
# ALWAYS_CAP per NPC; older ones of the same flag merge into one line) instead of folding into the older-memories text.
FLAG_FLOORS = {
    'intimacy': 0.9,        # intimate with the player (a scene record, or dialogue from a mod whose scripts start scenes)
    'harmed': 0.9,          # the player fought against them (a battle account with them on the other side)
    'death_close': 0.85,    # a death or killing they saw, or a household member told them about
    'rescue': 0.85,         # the player saved them in a fight, or they saved the player
    'promise': 0.8,         # a promise or debt made in the talk (kept while open by the promises field already)
    'fought_beside': 0.6,   # fought on the player's side
    'first_meeting': 0.6,   # their first talk with the player: how they met
    'bond': 0.9,            # married, engaged, eloped, dating, lover with the player, or that ended (facts history)
    'follower': 0.6,        # became or stopped being the player's follower (facts history)
    'gift': 0.8,            # gold of real value from the player (World's trade lines): 500 or more, or a quarter of their purse
    'taken': 0.8,           # the player was caught stealing from them or picking their pocket (World's line on them)
    'recognised': 0.7,      # the talk in which they learned that the hooded stranger was the player
    'broken_promise': 0.8,  # a promise to or by the player lapsed unkept
}


def importance_of(entry: dict) -> float:
    value = entry.get('importance')
    base = min(1.0, max(0.0, float(value))) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) \
        else DEFAULT_IMPORTANCE
    flags = entry.get('flags') if isinstance(entry.get('flags'), list) else []
    return max([base] + [FLAG_FLOORS[f] for f in flags if f in FLAG_FLOORS])


def add_flag(entry: dict, flag: str) -> dict:
    """Puts a flag on a memory entry (once); returns the entry."""
    if flag in FLAG_FLOORS:
        flags = entry.get('flags') if isinstance(entry.get('flags'), list) else []
        if flag not in flags:
            entry['flags'] = flags + [flag]
    return entry


def retention(importance: float, age_days: float | None, promise_open: bool = False) -> float:
    """How strongly a memory is still there, 1 (fresh) to near 0 (gone). Small talk (0.1) is mostly gone within a
    week, an ordinary talk (0.5) within a few months, a life-changing one (1.0) fades over the better part of a year and
    never below 0.4. An open promise or debt never fades."""
    if promise_open or age_days is None or age_days <= 0:
        return 1.0
    strength = 2 + 240 * importance ** 2  # days to fade to about a third
    floor = 0.4 * importance ** 3
    return max(floor, math.exp(-age_days / strength))


def age(day: int, today: int | None, recalled_day: int = -1) -> float | None:
    """Days since the memory, or None when either date is unknown. Remembering it again since then counts half: a
    memory that keeps coming to mind fades more slowly."""
    if today is None or day is None or day < 0 or today < 0:
        return None
    full = today - day
    if 0 <= day <= recalled_day <= today:
        return min(full, (today - recalled_day) + (recalled_day - day) / 2)
    return full


_STOP = set("""a an and are as at be been but by did do does for from had has have he her him his i if in into is it its
me my no not of on or our she so than that the their them then there they this to too up us was we were what when where
which who will with you your yours yourself said says say just about all any can could would should very also more
some one out over now here been being after before again talked told asked""".split())


def words(text: str) -> set[str]:
    """Plain word stems for keyword search: lower case, small words left out, simple English endings cut."""
    out = set()
    for word in re.findall(r"[^\W\d_]{3,}", str(text).lower()):
        if word in _STOP:
            continue
        for ending in ('ing', 'ed', 'es', 's'):
            if word.endswith(ending) and len(word) - len(ending) >= 3:
                word = word[:-len(ending)]
                break
        out.add(word)
    return out


def word_scores(query: str, texts: list[str]) -> list[float]:
    """0-1 per text: the shared words, the rarer the more they count, over the size of both. How many texts hold each
    word is counted once, so this stays linear in the number of texts."""
    query_words = words(query)
    docs = [words(t) for t in texts]
    if not query_words or not docs:
        return [0.0] * len(texts)
    count = len(docs)
    held = Counter(w for d in docs for w in d)
    weights: dict = {}

    def weight2(w):
        if w not in weights:
            weights[w] = math.log(1 + (count + 1) / (1 + held.get(w, 0))) ** 2
        return weights[w]
    query_size = math.sqrt(sum(weight2(w) for w in query_words))
    scores = []
    for doc in docs:
        shared = sum(weight2(w) for w in query_words & doc)
        size = math.sqrt(sum(weight2(w) for w in doc)) * query_size
        scores.append(shared / size if size else 0.0)
    return scores


def search_rows(rows: list[dict], limit: int = MAX_SEARCH_ROWS, important: int = SEARCH_IMPORTANT) -> list[dict]:
    """At most limit of rows (oldest first, as Archive.rows gives them), for a search on the request thread: the newest,
    and of the older ones the most important. A huge archive then costs no more per reply than a big one."""
    if len(rows) <= limit:
        return rows
    split = len(rows) - (limit - important)
    older = sorted(rows[:split], key=lambda r: -importance_of(r))[:important]
    keep = {id(r) for r in older}
    return [r for r in rows[:split] if id(r) in keep] + rows[split:]


_warned: set = set()


def _warn_once(kind: str, text: str) -> None:
    """A warning that would come with every reply is logged once per session, then only at debug level."""
    if kind in _warned:
        logger.debug(text)
        return
    _warned.add(kind)
    logger.warning(text)


def rank(query: str, rows: list[dict], today: int | None, open_promises=(), engine=None, limit: int = 4,
         hiding: bool = False) -> list[tuple[float, dict]]:
    """(score, row), best first: how close in meaning to the query (or shared words, without the model) times how
    strongly it is still remembered. A faded memory that fits the query well can still come back, as for a person
    reminded of it; one on another subject never does. hiding: for hiding memories, where a wrong pick takes away a
    memory the player never meant: by meaning only a close fit (MIN_HIDE_MEANING) near the best one (HIDE_MARGIN)."""
    if not rows or not str(query).strip():
        return []
    open_set = {_norm(p) for p in open_promises}
    similarity = None
    if engine is not None:
        try:
            similarity = _meaning_scores(query, rows, engine)
            threshold = MIN_MEANING
            if hiding and similarity:
                threshold = max(MIN_HIDE_MEANING, max(similarity) - HIDE_MARGIN)
        except NotEmbedded as e:
            _warn_once('not embedded', f"Living World: {e}; keywords are used until they have their numbers")
            similarity = None
        except Exception as e:
            _warn_once('meaning failed', f"Living World: meaning search failed ({e}); keywords are used")
            similarity = None
    if similarity is None:
        similarity = word_scores(query, [r.get('text') or '' for r in rows])
        threshold = MIN_WORDS
    out = []
    for sim, row in zip(similarity, rows):
        if sim < threshold:
            continue
        promise_open = any(_norm(p) in open_set for p in row.get('promises') or [])
        kept = retention(importance_of(row), age(row.get('day', -1), today, row.get('recalled_day', -1)), promise_open)
        score = sim * (0.35 + 0.65 * kept)
        if score >= (threshold if hiding else threshold / 2):  # a faded memory needs a closer fit to come back
            out.append((score, row))
    out.sort(key=lambda pair: -pair[0])
    return out[:max(0, limit)]


def hide_candidates(query: str, rows: list[dict], engine=None, limit: int = 1) -> tuple[list[dict], list[dict]]:
    """(sure, unsure) for hiding: at most limit rows that fit the query, best first. By meaning: above MIN_MEANING;
    sure when also at least MIN_HIDE_MEANING and within HIDE_MARGIN of the best, the rest unsure (for the summary model
    to confirm). By shared words (no model, or it failed): every match above MIN_WORDS is sure, as before."""
    if not rows or not str(query).strip() or limit <= 0:
        return [], []
    if engine is not None:
        try:
            similarity = _meaning_scores(query, rows, engine)
        except Exception as e:
            _warn_once('meaning failed', f"Living World: meaning search failed ({e}); keywords are used")
            similarity = None
        if similarity:
            found = sorted(((s, r) for s, r in zip(similarity, rows) if s >= MIN_MEANING), key=lambda p: -p[0])[:limit]
            if not found:
                return [], []
            bar = max(MIN_HIDE_MEANING, found[0][0] - HIDE_MARGIN)
            return [r for s, r in found if s >= bar], [r for s, r in found if s < bar]
    return [r for _, r in rank(query, rows, None, (), None, limit)], []


class NotEmbedded(ValueError):
    pass


def _meaning_scores(query: str, rows: list[dict], engine) -> list[float]:
    np = engine.np
    missing = [r for r in rows if not _vector_ok(r)]
    if len(missing) > MAX_EMBED_AT_SEARCH:  # many rows still waiting for numbers: words this time, saves catch up
        raise NotEmbedded(f'{len(missing)} memories not embedded yet')
    if missing:  # rows the model has not seen yet are embedded now (and stored by the caller's next save)
        for row, vector in zip(missing, engine.embed([r.get('text') or '' for r in missing])):
            row['vector'] = vector
    matrix = np.stack([r['vector'] if r.get('vector') is not None else np.frombuffer(r['embedding'], dtype=np.float32)
                       for r in rows])
    return [float(x) for x in matrix @ engine.embed([query])[0]]


def _vector_ok(row: dict) -> bool:
    return row.get('vector') is not None or (row.get('model') == embed.MODEL_ID and isinstance(row.get('embedding'), bytes)
                                             and len(row['embedding']) == embed.DIM * 4)


def _norm(text) -> str:
    return ' '.join(re.sub(r'[^\w]+', ' ', str(text).lower()).split())


_cache: dict = {}  # (path, hidden) -> (file stamp, rows): every reply reads the same archives again
_cache_lock = threading.Lock()
CACHE_FILES = 64


def _stamp(path: str):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


class Archive:
    def __init__(self, path):
        self.path = str(path)

    def _changed(self) -> None:
        """Every write here drops the cached rows of this file (the file stamp catches writes from elsewhere)."""
        with _cache_lock:
            for key in [k for k in _cache if k[0] == self.path]:
                _cache.pop(key, None)

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            connection.execute(SCHEMA)
            _migrate(connection)  # one small query; a file put back from a backup may be of the older kind again
        except Exception:
            connection.close()  # a broken file: never left open (Windows keeps it locked until the connection is collected)
            raise
        return connection

    def exists(self) -> bool:
        return os.path.exists(self.path)

    def rows(self, hidden: bool | None = False) -> list[dict]:
        """Every row (hidden=None), only visible ones (False) or only hidden ones (True), oldest first."""
        key, stamp = (self.path, hidden), _stamp(self.path)
        with _cache_lock:
            cached = _cache.get(key)
        if cached is not None and stamp is not None and cached[0] == stamp:
            return [dict(r) for r in cached[1]]  # copies: callers add keys of their own (vector)
        where = '' if hidden is None else (' WHERE hidden IS NOT NULL' if hidden else ' WHERE hidden IS NULL')
        with closing(self._connect()) as db:
            found = db.execute(f"SELECT {', '.join(COLUMNS)} FROM memories{where} ORDER BY day, hour, added").fetchall()
        rows = [self._row(values) for values in found]
        if stamp is not None and stamp == _stamp(self.path):
            with _cache_lock:
                if len(_cache) >= CACHE_FILES:
                    _cache.pop(next(iter(_cache)))
                _cache[key] = (stamp, rows)
            return [dict(r) for r in rows]
        return rows

    def ids(self) -> dict[str, str | None]:
        """{id: hidden as stored} for every row."""
        with closing(self._connect()) as db:
            return dict(db.execute('SELECT id, hidden FROM memories').fetchall())

    @staticmethod
    def _row(values) -> dict:
        row = dict(zip(COLUMNS, values))
        row['text'] = unwrap_text(row.get('text'))  # saved as the summary's raw JSON before live test 12's fix
        for key in JSON_COLUMNS:
            try:
                row[key] = json.loads(row[key]) if row[key] else ([] if key != 'hidden' else None)
            except (ValueError, TypeError):
                row[key] = [] if key != 'hidden' else None
        row['radiant'] = bool(row.get('radiant'))
        if row.get('source') not in SOURCES:
            row['source'] = 'seen'
        row['seq'] = _seq(row.get('seq'))
        return row

    def add(self, entries: list[tuple[dict, str]], engine=None) -> int:
        """Stores (entry, its text) pairs not stored yet; returns how many were new. With the model ready, their
        numbers are made now."""
        known = self.ids()
        new = [(entry_id(e), e, t) for e, t in entries if t and entry_id(e) not in known]
        unique = list({i: (i, e, t) for i, e, t in new}.values())
        if not unique:
            return 0
        vectors = _try_embed(engine, [t for _, _, t in unique])
        self._changed()
        with closing(self._connect()) as db, db:
            for n, (i, e, t) in enumerate(unique):
                vector = vectors[n] if vectors else None
                db.execute(f"INSERT OR IGNORE INTO memories ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})", (
                    i, _day(e.get('day')), _day(e.get('hour')), _text(t), _json(e.get('witnesses') or []),
                    importance_of(e), _text(e.get('emotion') or ''), e.get('type') if e.get('type') in TYPES else 'experience',
                    _json(e.get('tags') or []), _json(e.get('promises') or []),
                    _text(e['shared']) if isinstance(e.get('shared'), str) else None, 1 if e.get('radiant') else 0,
                    _json(e['hidden']) if e.get('hidden') else None, -1, time.time(),
                    vector.tobytes() if vector is not None else None, embed.MODEL_ID if vector is not None else None,
                    source_of(e), _text(e.get('told_by') or '')[:80] or None,
                    _text(e['talk'])[:64] if isinstance(e.get('talk'), str) and e['talk'] else None,
                    _seq(e.get('seq')), 'other' if e.get('timeline') == 'other' else None, None,
                    _text(e['command'])[:40] if isinstance(e.get('command'), str) and e['command'] else None,
                    _text(e['spell'])[:80] if isinstance(e.get('spell'), str) and e['spell'] else None))
        self._after_add([(i, e, vectors[n] if vectors else None) for n, (i, e, _) in enumerate(unique)])
        return len(unique)

    def _after_add(self, added: list) -> None:
        """New rows join a story arc (arcs.assign: by the label the summary gave, else by meaning and time). Never
        stops the add: the memory itself is already kept."""
        try:
            from . import arcs
            arcs.assign(self, added)
        except Exception as e:
            logger.warning(f"Living World: story arcs not updated ({e})")

    def set_branch(self, ids: list[str], branch: str | None) -> int:
        """Marks rows as belonging to another timeline ('other'); the loaded save's own line still wins (timeline.py)."""
        if not ids:
            return 0
        self._changed()
        with closing(self._connect()) as db, db:
            return sum(db.execute('UPDATE memories SET branch = ? WHERE id = ?', (branch, i)).rowcount for i in ids)

    def set_talk(self, ids: list[str], talk: str, seq: int | None) -> int:
        """Stamps rows made before their talk's id was known with that talk (timeline.py)."""
        if not ids:
            return 0
        self._changed()
        with closing(self._connect()) as db, db:
            return sum(db.execute('UPDATE memories SET talk = ?, seq = ? WHERE id = ? AND talk IS NULL', (talk, _seq(seq), i)).rowcount
                       for i in ids)

    def set_spell(self, ids: list[str], label: str | None) -> int:
        """Marks rows as made under a spell that was released knowingly (release.mark_spell), or clears the mark."""
        if not ids:
            return 0
        self._changed()
        with closing(self._connect()) as db, db:
            return sum(db.execute('UPDATE memories SET spell = ? WHERE id = ?', (_text(label)[:80] if label else None, i)).rowcount
                       for i in ids)

    def ids_of_command(self, command_id: str) -> list[str]:
        """The ids of the rows made while this absolute command was in force."""
        if not command_id:
            return []
        with closing(self._connect()) as db:
            return [r[0] for r in db.execute('SELECT id FROM memories WHERE command = ?', (str(command_id),)).fetchall()]

    def set_arc(self, ids: list[str], arc_id: str | None) -> int:
        if not ids:
            return 0
        self._changed()
        with closing(self._connect()) as db, db:
            return sum(db.execute('UPDATE memories SET arc = ? WHERE id = ?', (arc_id, i)).rowcount for i in ids)

    def arcs(self) -> list[dict]:
        """Every story arc: {id, label, summary, day, made, by_hand}, oldest first."""
        with closing(self._connect()) as db:
            found = db.execute('SELECT id, label, summary, day, made, by_hand FROM arcs ORDER BY made').fetchall()
        return [{'id': i, 'label': label or '', 'summary': summary or '', 'day': _day(day), 'made': made or 0.0,
                 'by_hand': bool(by_hand)} for i, label, summary, day, made, by_hand in found]

    def save_arc(self, arc: dict) -> None:
        self._changed()
        with closing(self._connect()) as db, db:
            db.execute('INSERT OR REPLACE INTO arcs (id, label, summary, day, made, by_hand) VALUES (?, ?, ?, ?, ?, ?)',
                       (str(arc['id']), _text(arc.get('label') or '')[:80], _text(arc.get('summary') or '')[:400],
                        _day(arc.get('day', -1)), arc.get('made') or time.time(), 1 if arc.get('by_hand') else 0))

    def delete_arc(self, arc_id: str) -> int:
        self._changed()
        with closing(self._connect()) as db, db:
            db.execute('UPDATE memories SET arc = NULL WHERE arc = ?', (arc_id,))
            return db.execute('DELETE FROM arcs WHERE id = ?', (arc_id,)).rowcount

    def set_hidden(self, ids: list[str], hidden: dict | None) -> int:
        self._changed()
        with closing(self._connect()) as db, db:
            if hidden:
                value = _json(hidden)
                return sum(db.execute('UPDATE memories SET hidden = ? WHERE id = ?', (value, i)).rowcount for i in ids)
            return sum(db.execute('UPDATE memories SET hidden = NULL WHERE id = ? AND hidden IS NOT NULL', (i,)).rowcount for i in ids)

    def delete(self, ids: list[str]) -> int:
        if not ids:
            return 0
        self._changed()
        with closing(self._connect()) as db, db:
            return sum(db.execute('DELETE FROM memories WHERE id = ?', (i,)).rowcount for i in ids)

    def mark_recalled(self, ids: list[str], day: int | None) -> None:
        if not ids or _day(day) < 0:
            return
        self._changed()
        with closing(self._connect()) as db, db:
            for i in ids:
                db.execute('UPDATE memories SET recalled_day = ? WHERE id = ? AND (recalled_day IS NULL OR recalled_day < ?)', (day, i, day))

    def store_vectors(self, rows: list[dict]) -> None:
        """Keeps the numbers search just made for rows that had none."""
        made = [r for r in rows if r.get('vector') is not None]
        if not made:
            return
        self._changed()
        with closing(self._connect()) as db, db:
            for r in made:
                db.execute('UPDATE memories SET embedding = ?, model = ? WHERE id = ?', (r['vector'].tobytes(), embed.MODEL_ID, r['id']))

    def backfill(self, engine, limit: int = BACKFILL) -> int:
        """Embeds rows added while the model was not ready (or made by another model)."""
        if engine is None:
            return 0
        with closing(self._connect()) as db:
            todo = db.execute('SELECT id, text FROM memories WHERE model IS NULL OR model != ? LIMIT ?', (embed.MODEL_ID, limit)).fetchall()
        vectors = _try_embed(engine, [t or '' for _, t in todo])
        if not vectors:
            return 0
        self.store_vectors([{'id': i, 'vector': v} for (i, _), v in zip(todo, vectors)])
        return len(todo)


def _migrate(db) -> None:
    """Adds the columns and the arcs table an archive from an older version lacks; nothing in it is changed or lost.
    Two servers opening the same file at once may both try: a column that is already there is fine."""
    have = {row[1] for row in db.execute('PRAGMA table_info(memories)')}
    if all(name in have for name, _ in ADDED_COLUMNS):
        db.execute(ARC_SCHEMA)
        return
    for name, kind in ADDED_COLUMNS:
        if name not in have:
            try:
                db.execute(f'ALTER TABLE memories ADD COLUMN {name} {kind}')
            except sqlite3.OperationalError as e:
                if 'duplicate column' not in str(e).lower():
                    raise
    db.execute(ARC_SCHEMA)
    db.commit()


def source_of(entry: dict) -> str:
    source = entry.get('source') if isinstance(entry, dict) else None
    return source if source in SOURCES else 'seen'


def _seq(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 2 ** 31 else None


def _day(value) -> int:
    """A day or hour SQLite can hold; anything odd from a hand-edited file is -1 (unknown)."""
    return value if isinstance(value, int) and not isinstance(value, bool) and -2 ** 31 <= value < 2 ** 31 else -1


def _text(value) -> str:
    """Text SQLite can store: a lone surrogate from a model reply becomes '?' (as in the memory file)."""
    return str(value).encode('utf-8', 'replace').decode('utf-8')


def _json(value) -> str:
    try:
        return _text(json.dumps(value, ensure_ascii=False))
    except (TypeError, ValueError):
        return '[]'


def _try_embed(engine, texts: list[str]):
    if engine is None or not texts:
        return None
    try:
        return engine.embed(texts)
    except Exception as e:
        logger.warning(f"Living World: could not embed {len(texts)} memory(s) ({e}); they get numbers later")
        return None
