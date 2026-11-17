"""Menu dialogue World heard, turned into memories at the NPC's next talk (with World installed).

World's SKSE listener keeps every line an NPC speaks with the player in the game's dialogue menu, from game load, with
the topic the player chose, the game time, the place and the plugin (MantellaLivingWorld/menu_dialogue.json, at most 60
exchanges per NPC and 200 NPCs; nothing expires). When that NPC next joins a Mantella talk, however much later, all
their lines this save has not used yet go into her memory block as they were said, dated, BEFORE the prompt is built
(the memory_text hook, prepare), so the greeting already knows them; no model call is made for it. The lasting memory
(first person, dated, with the usual importance, mood and tags) is written by the talk's own end-of-talk summary, in
the same request (memory.summarize asks for "menu"; add_menu_entry, finish_menu). Lines from a mod whose scripts start
sex scenes (the same test as the scanner's) are saved with importance of at least INTIMATE_IMPORTANCE and make the Now
paragraph due. The save's memory folder notes the newest line used (menu_dialogue_seen.json), moved on only once that
memory is saved: a talk that ends without a summary, or whose summary fails, leaves the lines for the next talk, and a
reload or a restart never makes a second memory of the same lines. Mantella's own stored dialogue of the same NPC in
that talk is replaced by a short note (no second summary of it).
A store nearly full while Mantella runs: the oldest half of that NPC's lines is made into a memory in the background
(one summary request, at most once an hour per NPC, never during a talk), for NPCs whose memory file is known (they
talked through Mantella before). Without World (no file) nothing changes."""
import hashlib
import json
import logging
import os
import re
import threading
import time

from . import archive, bio_evolve, lw_state, memory

logger = logging.getLogger('Mantella')
FILE = 'menu_dialogue.json'
SEEN = 'menu_dialogue_seen.json'  # in the save's memory folder: per base id, the newest line time already remembered
INTIMATE_IMPORTANCE = 0.9  # a dialogue mod that starts sex scenes: kept for most of a year, never below about a third
DAY_CHARS = 6000           # one day's lines sent to the summary at most (the newest kept)
FULL_SHARE = 0.8           # a store this full (of World's 60) is made into a memory in the background
WORLD_PER_NPC = 60
OVERFLOW_EVERY = 3600.0    # seconds between two background summaries of one NPC
PROMPT_CHARS = 2400        # the lines shown in her memory block at a talk's start, at most (the newest kept)
_overflow_at: dict = {}    # base id -> time.time() of the last background summary
_sexual_cache: dict = {}   # plugin (lower case) -> bool
# NPC file name -> {name, base, ref, lines, knows, intimate, scenes, events, delivered, upto}: the lines this talk shows
# and that its end-of-talk summary makes into her memory
_talk_pending: dict = {}
_talk_gen = {'gen': None}  # npc_block's talk generation the state below belongs to
_seen_lock = threading.RLock()  # menu_dialogue_seen.json: talk start, the end-of-talk save and the background watch
_overflow_upto: dict = {}  # base id -> newest line time the background summary is making into a memory right now

# Asked in the end-of-talk summary (memory.summarize), with the lines of each NPC who has some this talk.
MENU_ASK = (
    "\n\nBefore this conversation, {names} also spoke with {player} in the game's own dialogue (shown first below, one "
    "part per NPC, only that NPC's own exchanges). Add to the JSON \"menu\": {{\"<name>\": {{\"memory\": \"...\", "
    "\"importance\": 0.5, \"emotion\": \"...\", \"type\": \"experience\", \"tags\": []}}}}: for each of them a separate "
    "memory of only those earlier exchanges, 1 to 3 sentences, in the first person as that NPC (\"I\", \"me\"), never how "
    "long ago, rated as above. Report only what those lines and records say; keep each exchange separate and in its "
    "order (\"first ..., then ...\"); never name an act, a place, a reason or a feeling no line or record states, never "
    "guess what a hint meant; a player line \"(topic not recorded)\" means the words were not kept: do not invent them. "
    "Leave that earlier dialogue out of \"memory\".")
TALK_HEAD = ("Said in the game's own dialogue since {name}'s last talk (true, {name} remembers it; not yet among the "
             "memories above):")


def _base(character, speakers=None) -> str:
    # Direct AI Connect's hub_base_id keeps a light plugin's digits (FE012ABC -> 012ABC), as World keys its lines;
    # Mantella's own base_id cuts them to 000ABC, which matches nobody
    base = str(getattr(character, 'hub_base_id', '') or getattr(character, 'base_id', '') or '')
    if not base:
        for s in speakers or []:
            if s.get('name') == getattr(character, 'name', None) and s.get('base_id'):
                base = str(s['base_id'])
                break
    return base.upper()[-6:].rjust(6, '0') if base else ''


def _seen_path(store) -> str | None:
    root = getattr(store, 'root', None)
    return os.path.join(root, SEEN) if root else None


def load_seen(store) -> dict:
    """{base id: newest line time remembered}; {} when there is none (a file that could not be read is then not saved
    over: lw_state.read_store_json)."""
    path = _seen_path(store)
    data = lw_state.read_store_json(path, encoding='utf-8') if path else None
    return data if isinstance(data, dict) else {}


def _save_seen(store, seen: dict) -> None:
    path = _seen_path(store)
    if not path:
        return
    try:
        lw_state.guard_save(path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = lw_state.temp_path(path)  # a temp file of this thread's own: the background watch writes here too
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(seen, f)
        lw_state.replace_file(tmp, path)
    except OSError as e:
        logger.warning(f"Living World: could not note the menu dialogue remembered ({e})")


def advance_seen(store, base: str, upto: float) -> None:
    """Notes that this NPC's lines up to upto are in a memory: read, moved on and written under one lock, so the talk
    and the background watch never undo each other's mark."""
    if not base or not isinstance(upto, (int, float)):
        return
    with _seen_lock:
        seen = load_seen(store)
        old = seen.get(base, 0)
        if not isinstance(old, (int, float)) or upto > old:
            seen[base] = upto
            _save_seen(store, seen)


ACK = 'menu_ack.json'  # next to menu_dialogue.json: per player, per NPC key, the newest real capture time stored as a memory
_ack_lock = threading.Lock()


def acknowledge_lines(file_player, base: str, lines: list[dict], player: str = '') -> bool:
    """Tells World's plugin that these lines are in a lasting memory, so it may prune them: {"<player>": {"<npc key>":
    <real capture time of the newest line>}} in menu_ack.json (the lines' "time", as World writes it: the same value the
    seen marks use, so loading an older save, whose game days are lower, never covers a line not stored yet), merged with
    the rest of the file, never moved back. Called only after that memory was saved. Never raises; False when nothing
    was written."""
    try:
        who = file_player if isinstance(file_player, str) and file_player.strip() else player
        times = [float(l['time']) for l in lines or [] if isinstance(l.get('time'), (int, float)) and not isinstance(l.get('time'), bool)]
        if not who or not base or not times:
            return False
        upto = max(times)
        with _ack_lock:
            try:
                with open(os.path.join(lw_state.DATA_DIR, ACK), 'rb') as f:
                    data = json.loads(lw_state.decode(f.read()))
                data = data if isinstance(data, dict) else {}
            except FileNotFoundError:
                data = {}
            except ValueError:
                data = {}  # unreadable: the plugin reads it as nothing acknowledged too
            mine = data.get(who) if isinstance(data.get(who), dict) else {}
            old = mine.get(base)
            if isinstance(old, (int, float)) and not isinstance(old, bool) and old >= upto:
                return True
            data[who] = dict(mine, **{base: upto})
            lw_state.write_json(ACK, data)
        return True
    except Exception as e:  # an OSError reading it (locked): written with the next memory, never over a file not read
        logger.warning(f"Living World: the menu dialogue acknowledgement could not be written ({e})")
        return False


def _after(store, base: str) -> float:
    """The newest line time already used for this NPC: the saved mark, or what the background watch is on right now."""
    with _seen_lock:
        seen = load_seen(store).get(base, 0)
        seen = seen if isinstance(seen, (int, float)) else 0
        return max(seen, _overflow_upto.get(base, 0))


def pending(data: dict, base: str, after: float, player: str = '') -> list[dict]:
    """This NPC's lines newer than after, oldest first; none from another character's file."""
    npcs = data.get('npcs') if isinstance(data, dict) else None
    if not isinstance(npcs, dict) or (player and lw_state.other_character(data.get('player'), player)):
        return []
    npc = npcs.get(base)
    lines = npc.get('lines') if isinstance(npc, dict) else None
    out = [l for l in lines or [] if isinstance(l, dict) and isinstance(l.get('time'), (int, float)) and l['time'] > after
           and str(l.get('line') or '').strip()]
    return sorted(out, key=lambda l: l['time'])


def _sexual(plugin: str) -> bool:
    """Whether the plugin's mod has scripts that start sex scenes (the scanner's test), found through the Mod Organizer
    folder the Scan button uses; False when it cannot be told."""
    key = str(plugin or '').lower()
    if not key or key in _sexual_cache:
        return _sexual_cache.get(key, False)
    result = False
    try:
        from . import mod_facts_gen, mod_facts_scan, settings
        instance = settings.load().get('mod_facts_mo2') or mod_facts_scan.find_instance()
        if instance:
            dirs = mod_facts_scan.instance_dirs(instance)
            _, mods = mod_facts_gen.mo2_plugins(instance, dirs['profile'], dirs['profiles'])
            for mod in mods:
                if os.path.isfile(os.path.join(dirs['mods'], mod, plugin)):
                    result = mod_facts_gen.sexual_mod(os.path.join(dirs['mods'], mod))
                    break
    except Exception:
        result = False
    _sexual_cache[key] = result
    return result


EXCHANGE_GAP = 20.0  # seconds of real time between two lines that start a new exchange

# Live test 14: the general summary merged two exchanges into one favour and named an act no line stated. The menu
# dialogue gets these rules in front of the usual summary request (its JSON shape stays the same).
MENU_RULES = (
    "These are lines {name} spoke with {player} in the game's own dialogue, in order and split into numbered exchanges; "
    "a line \"Then: ...\" is what the game recorded happening right after that exchange. Write the memory from {name}'s "
    "point of view reporting only what these lines and records say. Keep every exchange separate and in its order "
    "(\"first ..., then ...\"). Never name an act, a place, a reason or a feeling that no line or record states, and "
    "never guess what was meant by a hint. A player line shown as \"(topic not recorded)\" means {player} chose a "
    "topic whose words were not kept: do not invent them.\n\n")


def exchanges(lines: list[dict], scenes=None) -> list[dict]:
    """The lines split into exchanges (a gap of EXCHANGE_GAP seconds, or a scene record between two lines), each with the
    scene records that ended after it and before the next one: [{'lines': [...], 'scenes': [text, ...]}]."""
    scenes = sorted((t, text) for t, text in scenes or [] if isinstance(t, (int, float)))
    out = []
    for l in lines:
        day = float(l.get('day') or 0)
        if out:
            last = out[-1]['lines'][-1]
            between = [x for x in scenes if float(last.get('day') or 0) <= x[0] <= day]
            if l['time'] - last['time'] > EXCHANGE_GAP or between:
                out[-1]['scenes'] += [text for _, text in between]
                scenes = [x for x in scenes if x not in between]
                out.append({'lines': [l], 'scenes': []})
                continue
            out[-1]['lines'].append(l)
        else:
            out.append({'lines': [l], 'scenes': []})
    if out:  # records after the last line belong to the last exchange
        last_day = float(out[-1]['lines'][-1].get('day') or 0)
        out[-1]['scenes'] += [text for t, text in scenes if t >= last_day]
    return out


def _day_text(lines: list[dict], name: str, player: str, scenes=None) -> str:
    place = next((str(l.get('place')) for l in lines if l.get('place')), '')
    parts = [f"(In the game's own dialogue{', at ' + place if place else ''}.)"]
    for n, ex in enumerate(exchanges(lines, scenes), 1):
        parts.append(f"Exchange {n}:")
        for l in ex['lines']:
            said = str(l.get('said') or '').strip()
            if said:
                parts.append(f"{player}: {said}")
            elif not l.get('vanilla') and str(l.get('plugin') or '').lower() not in ('skyrim.esm', 'update.esm'):
                parts.append(f"{player}: (topic not recorded)")
            parts.append(f"{name}: {str(l['line']).strip()}")
        parts += [f"Then: {re.sub(r'(?i)the player', player, text)}" for text in ex['scenes']]
    return '\n'.join(parts)[-DAY_CHARS:]


def _dated_text(lines: list[dict], name: str, player: str, scenes=None, limit: int = DAY_CHARS * 2) -> str:
    """_day_text for each game day of the lines, each day under its date ("[Day 17, 9 in the morning]"); the newest
    limit characters."""
    days = {}
    for l in lines:
        days.setdefault(int(float(l.get('day') or 0)), []).append(l)
    parts = []
    for day, group in sorted(days.items()):
        mday, hour = game_day_hour(float(group[0].get('day') or 0))
        day_scenes = [(t, text) for t, text in scenes or [] if isinstance(t, (int, float)) and int(t) == day]
        parts.append(f"{memory.header(mday, hour)} {_day_text(group, name, player, day_scenes)}".strip())
    return '\n'.join(parts)[-limit:]


def remember(store, character, player: str, summaries, language: str = 'English', data: dict | None = None,
             speakers=None, limit: int | None = None, sexual=None, scenes=None, knows: bool = True,
             events=None) -> list[str]:
    """Makes this NPC's unused menu lines into one memory with one summary request (the background overflow; a talk
    makes them part of its own summary instead, see prepare); returns the memory lines. limit: only the oldest that many
    lines. A failed summary marks nothing (the lines wait for the next try). Never touches the state of the talk going
    on. Never raises."""
    sexual = sexual or _sexual
    base = ''
    try:
        data = lw_state._read(FILE) if data is None else data
        base = _base(character, speakers)
        if not base or summaries is None or store is None:
            return []
        with _seen_lock:
            if any(e.get('base') == base for e in list(_talk_pending.values())):
                return []  # a talk shows these lines now; its end-of-talk summary makes them into her memory
            lines = pending(data, base, _after(store, base), player)[:limit]
            if not lines:
                return []
            _overflow_upto[base] = max(l['time'] for l in lines)  # a talk starting meanwhile shows only newer lines
        lines = merge_said(lines, events, player)
        name = memory.file_name(getattr(character, 'name', '') or '')
        day = int(float(lines[-1].get('day') or 0))
        line = _remember_day(store, character, name, player, summaries, language, day, lines, sexual, list(scenes or []), knows)
        if not line:
            return []
        advance_seen(store, base, max(l['time'] for l in lines))
        acknowledge_lines(data.get('player') if isinstance(data, dict) else '', base, lines, player)
        logger.info(f"Living World: a memory of {name} made from {len(lines)} menu dialogue line(s)")
        return [line]
    except Exception as e:
        logger.warning(f"Living World: menu dialogue could not be remembered ({e}); kept for the next talk")
        return []
    finally:
        with _seen_lock:
            _overflow_upto.pop(base, None)


def _same_talk(store) -> None:
    """The talk state below belongs to one talk: when npc_block's talk generation moved on (the last talk's summary ran,
    or a long quiet spell or another save began a new talk without one), an earlier talk's pending lines are dropped.
    They were never marked used, so this talk shows them again."""
    from . import npc_block
    npc_block.touch(store)
    gen = npc_block._talk['gen']
    if _talk_gen['gen'] != gen:
        if _talk_gen['gen'] is not None:
            talk_over()
        _talk_gen['gen'] = gen


def prepare(store, character, player: str, speakers=None, knows=True, data: dict | None = None, sexual=None) -> dict | None:
    """At a talk's start (the memory_text hook, before the prompt is built): this NPC's menu lines not yet in a memory
    are kept for this talk, to be shown in her memory block as they were said (talk_text) and made into her memory by
    the talk's own end-of-talk summary (summary_text, menu_entry, finish_menu). No model call. Once per NPC per talk,
    so the block stays the same all talk. knows: a bool, or a callable giving it (asked only when needed). Never
    raises."""
    sexual = sexual or _sexual
    try:
        if store is None:
            return None
        _same_talk(store)
        name = memory.file_name(getattr(character, 'name', '') or '')
        if not name or name in _talk_pending or name in _talk_tried:
            return _talk_pending.get(name)
        _talk_tried.add(name)
        data = lw_state._read(FILE) if data is None else data
        base = _base(character, speakers)
        if not base:
            return None
        with _seen_lock:
            lines = pending(data, base, _after(store, base), player)
        if not lines:
            return None
        intimate = any(sexual(l.get('plugin', '')) for l in lines)
        knows = knows() if callable(knows) else knows
        entry = {'name': name, 'base': base, 'ref': getattr(character, 'ref_id', '') or '', 'lines': lines,
                 'knows': bool(knows) or intimate,  # face to face and intimate: she knows who he is (live test 14 decision)
                 'intimate': intimate, 'scenes': [], 'events': [], 'delivered': 0, 'upto': max(l['time'] for l in lines),
                 'player': data.get('player') if isinstance(data.get('player'), str) else player}
        _talk_pending[name] = entry
        logger.info(f"Living World: {len(lines)} menu dialogue line(s) of {name} shown in this talk, remembered at its end")
        return entry
    except Exception as e:
        logger.warning(f"Living World: menu dialogue could not be read for this talk ({e}); kept for the next talk")
        return None


def intimate(name: str) -> bool:
    """This talk shows menu lines of a dialogue mod that starts sex scenes for this NPC (she knows who the player is)."""
    entry = _talk_pending.get(name)
    return bool(entry and entry['intimate'])


def _newest(text: str, limit: int) -> str:
    """The newest limit characters of text, cut at a line start."""
    if len(text) <= limit:
        return text
    cut = text[-limit:]
    return '(...)\n' + cut[cut.find('\n') + 1:] if '\n' in cut else cut


def talk_text(name: str, player: str) -> str:
    """This talk's menu lines of this NPC for her memory block, dated, as said; '' when she has none."""
    entry = _talk_pending.get(name)
    if not entry:
        return ''
    who = player if entry['knows'] else 'the hooded stranger'
    return TALK_HEAD.format(name=name) + '\n' + _newest(_dated_text(entry['lines'], name, who), PROMPT_CHARS)


def pending_names(names) -> list[str]:
    """Of these NPCs, the ones whose menu lines this talk shows and has not made into a memory yet."""
    return [n for n in names or [] if n in _talk_pending]


def summary_text(names, player: str) -> str:
    """These NPCs' menu lines for the end-of-talk summary: one part per NPC, only her own exchanges, with the player's
    words World missed taken from Mantella's own copy of the same dialogue (merge_said)."""
    parts = []
    for name in names:
        entry = _talk_pending.get(name)
        if entry:
            who = player if entry['knows'] else 'the hooded stranger'
            lines = merge_said(entry['lines'], entry['events'], player)
            parts.append(f"{name}'s earlier dialogue with {who}:\n" + _dated_text(lines, name, who))
    return '\n\n'.join(parts)


def parse_menu(reply: str, names) -> dict:
    """{name: (memory text, meta)} from the summary reply's "menu" part, for these NPCs only."""
    data = memory._summary_data(reply).get('menu') if reply else None
    if not isinstance(data, dict):
        return {}
    out = {}
    for key, value in data.items():
        name = next((n for n in names if n.lower() == str(key).strip().lower()), None)
        if name is None and len(names) == 1 and len(data) == 1:
            name = names[0]
        if name is None:
            continue
        text, meta = (value, {}) if isinstance(value, str) else \
            (value.get('memory'), memory.parse_meta(json.dumps(value))) if isinstance(value, dict) else (None, {})
        if isinstance(text, str) and text.strip():
            out[name] = (text.strip(), meta)
    return out


def menu_entry(name: str, text: str, meta: dict, player: str) -> dict | None:
    """Her lasting memory of this talk's menu lines, from the summary's "menu" text: first person, dated by the newest
    line, each kept scene that followed added as a "Then:" line in her own words, kept long when intimate."""
    entry = _talk_pending.get(name)
    if not entry or not text:
        return None
    line = memory.strip_relative(text)
    if not entry['knows']:
        line = memory.mask_player(line, player)
    for _, scene in entry['scenes']:
        who = player if (entry['knows'] or INTIMATE_SCENE.search(scene)) else 'the hooded stranger'
        line = line.rstrip() + ' Then: ' + memory.strip_relative(first_person(scene, name, who))
    lines = entry['lines']
    mday, hour = game_day_hour(float(lines[-1].get('day') or 0))  # the same days as talk memories (GameDaysPassed + 1)
    source = 'menu-' + hashlib.sha1(_day_text(lines, name, player).encode('utf-8')).hexdigest()[:12]
    out = {'day': mday, 'hour': hour, 'text': line[:memory.MAX_ENTRY_CHARS], 'witnesses': [name], 'dialogue': source, **meta}
    if entry['scenes']:
        out['scene_times'] = [float(t) for t, _ in entry['scenes']]
    if not entry['knows']:
        out['unrecognised'] = True
    if entry['intimate'] or entry['scenes']:
        out['importance'] = max(float(out.get('importance') or 0), INTIMATE_IMPORTANCE)
        archive.add_flag(out, 'intimacy')
    return out


def finish_menu(store, name: str) -> None:
    """Her menu memory of this talk is saved: its lines (and any spoken later that the talk showed as events) are marked
    used, and an intimate one makes her Now paragraph due."""
    entry = _talk_pending.pop(name, None)
    if not entry:
        return
    advance_seen(store, entry['base'], max(entry['upto'], entry.get('delivered') or 0))
    acknowledge_lines(entry.get('player'), entry['base'], entry['lines'])
    _talk_scenes.add(name)
    logger.info(f"Living World: a memory of {name} made from {len(entry['lines'])} menu dialogue line(s) at the end of the talk")
    if entry['intimate'] or entry['scenes']:
        bio_evolve.mark_due(store, name, entry['ref'], 'something important happened in ordinary talk')


def merge_said(lines: list[dict], events, player: str) -> list[dict]:
    """World's lines with no player topic get the player's words from Mantella's own stored copy of the same dialogue
    ("CHAD: I need help with my problem again.;\n Gerdur: By Ysmir's beard... CHAD: ..."), matched by the NPC's line
    (live test 15: 8 of 11 lines had no topic while Mantella's copy had the words). Copies; never raises."""
    try:
        pairs = []
        p = re.escape(player or '')
        for event in events or []:
            text = str(event)
            if not p or f'{player}:' not in text:
                continue
            for m in re.finditer(rf"(?:^|\s){p}:\s*(.*?);\s*\n?\s*[^:;\n]{{1,60}}?:\s*(.*?)(?=\s{p}:|$)", text, re.S):
                said, line = ' '.join(m.group(1).split()), ' '.join(m.group(2).split())
                if said and said.strip('. ') and line:
                    pairs.append((said, _norm(line)))
        if not pairs:
            return lines
        out = []
        for l in lines:
            l = dict(l)
            if not str(l.get('said') or '').strip() and not l.get('vanilla'):
                key = _norm(l.get('line', ''))[:40]
                hit = next((s for s, line in pairs if key and (line.startswith(key) or key in line)), '')
                if hit:
                    l['said'] = hit
            out.append(l)
        return out
    except Exception:
        return lines


def _norm(text: str) -> str:
    return ' '.join(re.sub(r"[^a-z0-9]+", ' ', str(text or '').lower()).split())


def scene_stored(mem: dict, t: float) -> bool:
    """A kept scene of this game time is already in one of her memories (a menu memory's "Then:" or its own)."""
    return any(abs(float(x) - t) < 1e-5 for e in mem.get('recent') or [] for x in e.get('scene_times') or []
               if isinstance(x, (int, float)))


def stored_scene_indexes(events: list, characters, store) -> set:
    """Indexes of the kept-scene events whose scene (by its {t=...} time) is already in the memory of every NPC here it
    names. Never raises."""
    out = set()
    try:
        for i, event in enumerate(events if isinstance(events, list) else []):
            tag = SCENE_TIME.search(str(event))
            found = SCENE_EVENT.match(SCENE_TIME.sub('', str(event)).strip())
            if not tag or not found or store is None:
                continue
            named = [c for c in characters or [] if getattr(c, 'name', '') and
                     re.search(rf"(?<!\w){re.escape(c.name)}(?!\w)", found.group(2), re.I)]
            if named and all(scene_stored(store.load(memory.file_name(c.name), getattr(c, 'ref_id', '') or ''),
                                          float(tag.group(1))) for c in named):
                out.add(i)
    except Exception:
        return set()
    return out


def acknowledge_scenes(events: list, characters, store) -> list:
    """For every kept scene in these events now stored in the memory of an NPC it names: "<name>|<time as tagged>",
    written for OStim Expansion (lw_state.ack_scenes), which then stops sending it. Returns the keys. Never raises."""
    keys = []
    try:
        for event in events if isinstance(events, list) else []:
            tag = SCENE_TIME.search(str(event))
            found = SCENE_EVENT.match(SCENE_TIME.sub('', str(event)).strip())
            if not tag or not found or store is None:
                continue
            for character in characters or []:
                name = getattr(character, 'name', '') or ''
                if name and re.search(rf"(?<!\w){re.escape(name)}(?!\w)", found.group(2), re.I) and \
                        scene_stored(store.load(memory.file_name(name), getattr(character, 'ref_id', '') or ''), float(tag.group(1))):
                    keys.append(f"{name}|{tag.group(1)}")
        if keys:
            lw_state.ack_scenes(keys)
    except Exception as e:
        logger.warning(f"Living World: stored scenes could not be acknowledged ({e}); they are sent again next talk")
    return keys


def pair_late_scenes(events: list, characters, store, player: str) -> set:
    """OStim Expansion's kept scenes arrive with the talk's first or second message (live test 15: after the player's
    first line). A scene (dated by its {t=...} tag) that ended on the same game day as this talk's menu lines of that NPC,
    after they began, goes with them: the end-of-talk summary adds it to her menu memory as a "Then:" line in her own
    words, once. A scene already stored is only noted. Returns the scene texts paired (they get no memory of their own).
    Nothing is written here: a talk that ends without its summary leaves the scene unacknowledged, so OStim Expansion
    sends it again."""
    paired = set()
    for event in events if isinstance(events, list) else []:
        tag = SCENE_TIME.search(str(event))
        found = SCENE_EVENT.match(SCENE_TIME.sub('', str(event)).strip())
        if not tag or not found or store is None:
            continue
        t, text = float(tag.group(1)), found.group(2).strip()
        for character in characters or []:
            name = memory.file_name(getattr(character, 'name', '') or '')
            entry = _talk_pending.get(name)
            if not name or not entry or not re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text, re.I):
                continue
            start = float(entry['lines'][0].get('day') or 0)
            if not any(int(float(l.get('day') or 0)) == int(t) for l in entry['lines']) or t < start - 0.001:
                continue
            if any(abs(s - t) < 1e-5 for s, _ in entry['scenes']):
                paired.add(text)
                continue
            if scene_stored(store.load(name, entry['ref']), t):  # sent again: already in a memory
                paired.add(text)
                continue
            entry['scenes'].append((t, text))
            _talk_scenes.add(name)
            paired.add(text)
    return paired


def _remember_day(store, character, name, player, summaries, language, day, group, sexual, scenes=(), knows=True) -> str:
    ref_id = getattr(character, 'ref_id', '') or ''
    intimate = bool(scenes) or any(sexual(l.get('plugin', '')) for l in group)
    knows = knows or intimate  # face to face and intimate: she knows who he is (live test 14 decision)
    who = player if knows else 'the hooded stranger'  # the same words as the hood events and the fact lines
    text = _dated_text(group, name, who, scenes)
    source = 'menu-' + hashlib.sha1(_day_text(group, name, player).encode('utf-8')).hexdigest()[:12]
    with store.lock(name, ref_id):
        mem = store.load(name, ref_id)
        known = next((e for e in mem['recent'] if e.get('dialogue') == source), None)
        if known:
            return str(known.get('text') or '')
        promises = json.dumps(memory.open_promises(mem), ensure_ascii=False)
    prompt = MENU_RULES.format(name=name, player=who) + memory.SUMMARY_PROMPT.format(
        names=name, game='Skyrim', player=who, language=language, promises=promises,
        bios=f"{name}: {getattr(character, 'bio', '')}")
    if not knows:
        prompt += memory.HOODED_ASK.format(names=name, player=player)
    prompt += memory.FIRST_PERSON.format(name=name) + memory.NO_RELATIVE
    # the model call holds no lock: a talk reading or saving her memory meanwhile is never held up by it
    reply = memory._ask_summary(summaries, text, prompt, f"the menu dialogue of {name}")
    line, feelings = memory.parse_summary(reply, [name]) if reply else ('', {})
    if not line:
        return ''
    line = memory.strip_relative(line)
    if not knows:
        line = memory.mask_player(line, player)
    with store.lock(name, ref_id):
        mem = store.load(name, ref_id)
        known = next((e for e in mem['recent'] if e.get('dialogue') == source), None)
        if known:
            return str(known.get('text') or '')
        # dated by the newest of its lines, the same days as talk memories (GameDaysPassed + 1)
        mday, hour = game_day_hour(float(group[-1].get('day') or 0))
        entry = {'day': mday, 'hour': hour, 'text': line, 'witnesses': [name], 'dialogue': source, **memory.parse_meta(reply)}
        if scenes:
            entry['scene_times'] = [float(t) for t, _ in scenes]
        if not knows:
            entry['unrecognised'] = True
        if intimate:
            entry['importance'] = max(float(entry.get('importance') or 0), INTIMATE_IMPORTANCE)
            entry['flags'] = ['intimacy']
        if memory.first_contact(mem):
            archive.add_flag(entry, 'first_meeting')  # the earliest memory of the player is how they met (live test 15)
        mem['recent'].append(entry)
        memory._link_promises(entry, mem, reply, mday)
        feeling = feelings.get(name, '')
        if feeling:
            memory._set_feeling(mem, feeling, mday, {})
        memory._fold_and_save(store, name, ref_id, mem, summaries)
    if intimate:
        bio_evolve.mark_due(store, name, ref_id, 'something important happened in ordinary talk')
    return line


def replace_events(events: list, player: str, strangers=()) -> list:
    """Mantella's own stored dialogue of an NPC whose menu lines this talk already shows in her memory block: a short note
    instead (the lines are not shown twice, nor summarised a second time at the end; the note says only that they
    talked, so the others in a group learn nothing more). Mantella's copy is kept for the end-of-talk summary, for the
    player's words World missed (merge_said). strangers: NPCs who do not know who the hooded player is; to them the
    player in such an event is "the hooded stranger", never the name (live test 14)."""
    if not isinstance(events, list) or (not _talk_pending and not strangers):
        return events
    out = []
    for event in events:
        text = ' '.join(str(event).replace(';\n', ' ').split())
        name = next((n for n in _talk_pending if f' {n}:' in f' {text}' and f'{player}:' in text), None)
        if name and not str(event).startswith(memory.COMPACTED):
            who = 'the hooded stranger' if name in strangers or not _talk_pending[name]['knows'] else player
            if str(event) not in _talk_pending[name]['events']:
                _talk_pending[name]['events'].append(str(event))
            out.append(f"{memory.COMPACTED} {name} and {who} talked in the game's own dialogue before this; {name}'s "
                       f"memories hold what was said.")
        else:
            out += mask_strangers([event], player, strangers)
    return out


def mask_strangers(events: list, player: str, strangers=()) -> list:
    """Mantella's stored dialogue events of an NPC who does not know who the hooded player is: "The hooded stranger:"
    instead of the player's name as the speaker label."""
    if not strangers or not isinstance(events, list):
        return events
    out = []
    for event in events:
        text = ' '.join(str(event).replace(';\n', ' ').split())
        if isinstance(event, str) and f'{player}:' in event and any(f' {n}:' in f' {text}' for n in strangers):
            event = event.replace(f'{player}:', 'The hooded stranger:')
        out.append(event)
    return out


def player_word(character, knows=None, player: str | None = None) -> str:
    """The player's name, or "the hooded stranger" for an NPC who does not know who is under the hood."""
    player = player or lw_state.load_player_name() or 'the player'
    return player if knows is None or knows(character) else 'the hooded stranger'


def mark_delivered(events: list, characters, store, player: str, data: dict | None = None) -> int:
    """Menu lines Mantella already put into a live talk as events (spoken after the talk began): marked as used, so the
    next talk does not make them into a memory again (live test 14). Returns how many NPCs moved on."""
    if store is None or not isinstance(events, list) or not events:
        return 0
    joined = re.sub(r"[^a-z0-9]+", ' ', ' '.join(str(e) for e in events).lower())
    data = lw_state._read(FILE) if data is None else data
    moved = 0
    for character in characters or []:
        base = _base(character)
        if not base:
            continue
        # lines this talk shows from before it began wait for its end-of-talk summary: only later ones count here, and
        # they are marked with that memory (finish_menu), so a summary that fails never skips the earlier ones
        entry = next((e for e in list(_talk_pending.values()) if e.get('base') == base), None)
        after = entry['upto'] if entry else _after(store, base)
        hit = [l['time'] for l in pending(data, base, after, player)
               if len(re.sub(r"[^a-z0-9]+", ' ', l['line'].lower()).strip()) > 8
               and re.sub(r"[^a-z0-9]+", ' ', l['line'].lower()).strip() in joined]
        if hit:
            if entry:
                entry['delivered'] = max(entry.get('delivered') or 0, max(hit))
            else:
                advance_seen(store, base, max(hit))
            moved += 1
    return moved


def done_this_talk(name: str) -> bool:
    return name in _talk_pending or name in _talk_tried


_talk_tried: set = set()   # NPC names whose menu lines this talk already looked for (prepare)
_talk_scenes: set = set()  # NPC names whose earlier scenes or menu lines became memories this talk


def talk_over() -> None:
    """The talk ended: what it still had pending was not made into a memory and stays unmarked (the next talk shows
    it again)."""
    _talk_pending.clear()
    _talk_tried.clear()
    _talk_scenes.clear()


def overflow_check(store, summaries, player: str, data: dict | None = None, now: float | None = None, sexual=None) -> int:
    """The background step: for each NPC whose World store is nearly full and whose memory file is known, the oldest half
    becomes a memory (once an hour per NPC, never during a talk). Returns how many NPCs were done."""
    if store is None or summaries is None or bio_evolve.busy():
        return 0
    data = lw_state._read(FILE) if data is None else data
    npcs = data.get('npcs') if isinstance(data, dict) else None
    if not isinstance(npcs, dict):
        return 0
    now = time.time() if now is None else now
    seen = load_seen(store)
    done = 0
    for base, npc in npcs.items():
        after = seen.get(base, 0) if isinstance(seen.get(base, 0), (int, float)) else 0
        lines = pending(data, base, after, player)
        if len(lines) < WORLD_PER_NPC * FULL_SHARE or now - _overflow_at.get(base, 0) < OVERFLOW_EVERY:
            continue
        state = lw_state.load_npc(base)
        ref = state.get('ref_id')
        if not ref:
            continue  # never talked through Mantella: no memory file to write to yet
        from .memory_ui import mantella_ref
        character = type('Npc', (), {'name': str(npc.get('name') or state.get('name') or ''), 'ref_id': mantella_ref(str(ref)),
                                     'base_id': base, 'bio': ''})()
        _overflow_at[base] = now
        if remember(store, character, player, summaries, data=data, limit=len(lines) // 2, sexual=sexual):
            done += 1
            logger.info(f"Living World: the menu dialogue store of {character.name} was nearly full; its oldest half is now a memory")
    return done


def start_overflow_watch(get_store, get_summaries, every: float = 60.0) -> threading.Thread:
    """A daemon thread that runs overflow_check every so often with the latest store and summary object."""
    def run():
        while True:
            time.sleep(every)
            try:
                overflow_check(get_store(), get_summaries(), lw_state.load_player_name() or 'the player')
            except Exception as e:
                logger.warning(f"Living World: the menu dialogue overflow check failed ({e})")
    thread = threading.Thread(target=run, daemon=True, name='lw-menu-overflow')
    thread.start()
    return thread


SCENE_EVENT = re.compile(r"^\(?\s*Earlier \(([^)]*)\), with no conversation going on: (.+?)\)?\s*$", re.S)
SCENE_TIME = re.compile(r"\s*\{t=([\d.]+)\}")  # the game time OStim Expansion adds to a kept scene, taken out before the model


def game_day_hour(game_days: float) -> tuple[int, int]:
    """A game-side time (GameDaysPassed, as World and OStim Expansion write it) as a memory's day and hour: the same
    days talk memories use (Mantella's GameDaysPassed + 1)."""
    return memory.day_hour(float(game_days) + memory.MANTELLA_DAY)


def scene_records(events: list) -> tuple[list, list]:
    """(events with the scene time tags taken out, [(game time or None, scene text)]) from OStim Expansion's kept scenes."""
    out, found = [], []
    for event in events if isinstance(events, list) else []:
        text = str(event)
        tag = SCENE_TIME.search(text)
        clean = SCENE_TIME.sub('', text) if tag else event
        m = SCENE_EVENT.match(str(clean).strip())
        if m:
            found.append((float(tag.group(1)) if tag else None, m.group(2).strip()))
        out.append(clean)
    return out, found


INTIMATE_SCENE = re.compile(r"having sex|\bintimate\b|They did ", re.I)


def first_person(text: str, name: str, player: str) -> str:
    """OStim Expansion's line about a scene ("Gerdur and the player finished ... They did ...") from her point of view."""
    text = re.sub(rf"(?<!\w){re.escape(name)},? and the player", f"{player} and I", text, flags=re.I)
    text = re.sub(r"(?<![\w])the player and (?:I|me)\b", f"{player} and I", text, flags=re.I)
    text = re.sub(r"\bminute(s?)\b", lambda m: 'minute' + ('s' if m.group(1) else ''), text, flags=re.I)  # "minuteS" (live test 17)
    text = re.sub(r"\bThey did\b", "We did", text)
    # "Climaxes: The Player 2 times and Gerdur once." -> "CHAD climaxed twice and I climaxed once." (live test 17)
    text = re.sub(r"\bClimaxes:\s*([^.]*)\.", lambda m: _climaxes(m.group(1), name, player), text, flags=re.I)
    return text[:1].upper() + text[1:]


def _climaxes(listed: str, name: str, player: str) -> str:
    """OStim Expansion's climax list as a plain sentence: the NPC is "I", the player by the word given."""
    parts = []
    for item in re.split(r",\s*(?:and\s+)?|\s+and\s+", listed.strip()):
        m = re.match(r"(.+?)\s+(once|twice|\d+ times)$", item.strip(), re.I)
        if not m:
            return f"Climaxes: {listed}."
        who, count = m.group(1).strip(), m.group(2).lower()
        count = {'1 times': 'once', '2 times': 'twice'}.get(count, count)
        if who.lower() == 'the player':
            who = player
        elif who.lower() == name.lower():
            who = 'I'
        parts.append(f"{who} climaxed {count}")
    joined = parts[0] if len(parts) == 1 else ', '.join(parts[:-1]) + ' and ' + parts[-1]
    return joined[0].upper() + joined[1:] + '.'


def remember_scene_events(events: list, characters, store, today, summaries=None, paired=(), knows=None,
                          player: str | None = None) -> int:
    """OStim Expansion's scenes that ended with no talk running come to the partner's next talk as events ("Earlier (about
    2 hours ago), with no conversation going on: ..."): each becomes a memory of hers at once, with importance of at least
    INTIMATE_IMPORTANCE, so it never depends on the end-of-talk summary mentioning it. Returns how many were saved."""
    saved = 0
    for event in events if isinstance(events, list) else []:
        tag = SCENE_TIME.search(str(event))
        found = SCENE_EVENT.match(SCENE_TIME.sub('', str(event)).strip())
        if not found or store is None:
            continue
        text = found.group(2).strip()
        if text in paired:
            continue  # already part of the memory of the dialogue it followed
        for character in characters or []:
            name = memory.file_name(getattr(character, 'name', '') or '')
            if not name or not re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text, re.I):
                continue
            source = 'scene-' + hashlib.sha1(str(event).encode('utf-8')).hexdigest()[:12]
            ref_id = getattr(character, 'ref_id', '') or ''
            with store.lock(name, ref_id):
                mem = store.load(name, ref_id)
                if any(e.get('dialogue') == source for e in mem['recent']) or (tag and scene_stored(mem, float(tag.group(1)))):
                    continue
                if tag:
                    day, hour = game_day_hour(float(tag.group(1)))
                else:
                    day, hour = (today + memory.MANTELLA_DAY if isinstance(today, int) else -1), -1
                # an intimate scene: she knows who he is from now on (live test 14 decision), so the name, never the hood
                who = player_word(character, None if INTIMATE_SCENE.search(text) else knows, player)
                added = {'day': day, 'hour': hour, 'text': first_person(text, name, who), 'witnesses': [name],
                         'dialogue': source, 'importance': INTIMATE_IMPORTANCE, 'type': 'relationship', 'flags': ['intimacy']}
                if tag:
                    added['scene_times'] = [float(tag.group(1))]
                if memory.first_contact(mem):
                    archive.add_flag(added, 'first_meeting')
                mem['recent'].append(added)
                memory._fold_and_save(store, name, ref_id, mem, summaries)
            bio_evolve.mark_due(store, name, ref_id, 'something important happened before this talk')
            _talk_scenes.add(name)
            saved += 1
    return saved
