"""The Living World Memory page: pick a save and an NPC, see what they remember about the player, and edit it as
tables (no JSON). Memories live with Mantella's conversations: <user folder>/data/Skyrim/conversations/<save>/
living_world/<NPC> - <ref id>.json (see memory.py). Deleting one memory, one NPC's memories or a whole save's moves
the files to a dated backup folder, never erases them."""
import collections
import html
import json
import os
import re
import shutil
import time

from . import memory, ui_help, ui_overrides

DEFAULT_CONVERSATIONS = os.path.join(ui_overrides.user_folder(), 'data', 'Skyrim', 'conversations')
DEFAULT_BACKUPS = os.path.join(ui_overrides.user_folder(), 'data', 'Skyrim', 'living_world_memory_removed')
FILE = re.compile(r'^(.+) - ([0-9A-Fa-f]{1,8})$')

TICKS = ('Talked with', 'Custom NPCs', 'Followers')  # the Find NPC filters, counts added
EXAMPLE_NAME = 'Hadvar (example, never saved)'
EXAMPLE_FEELING = 'Trusts Player after Helgen; a little protective of them.'
EXAMPLE_RECENT = [
    [1, 9, 'Player and I escaped Helgen together when the dragon attacked. I told them to go to my uncle Alvor in Riverwood.'],
    [2, 18, 'Player came by Alvor\'s forge. I thanked them for getting word to Whiterun about the dragon.'],
]
EXAMPLE_LONG = [['earlier', 'Served in the Legion with Ralof once, before the war split us.']]


def saves(conversations_dir=DEFAULT_CONVERSATIONS) -> list[str]:
    """Save characters (Mantella's world ids) that have a conversations folder."""
    try:
        return sorted(d for d in os.listdir(conversations_dir) if os.path.isdir(os.path.join(conversations_dir, d)))
    except OSError:
        return []


def mantella_ref(ref_id) -> str:
    """A ref id the way Mantella files NPCs (Mantella - Direct AI Connect, game_manager.load_character): the last 6
    hex digits, zero padded; a light plugin's 'FE' id keeps its last 3. Mantella's csv often has short ids ('837')."""
    ref = (ref_id or '').strip().upper()
    if len(ref) == 8 and ref.startswith('FE'):
        return ref[-3:].rjust(6, '0')
    return ref[-6:].rjust(6, '0') if ref else ''


def people(conversations_dir, world, csv_path=ui_overrides.DEFAULT_CSV, followers=None) -> list[dict]:
    """[{label, name, ref_id, has, custom, follower}] for the Find NPC list: NPCs with memories in this save first
    (Living World's files and Mantella's own summary folders), then every NPC in Mantella's list with a ref id (memories
    are filed by name and ref id, so one is needed to start a memory). custom: not in Mantella's list (so only listed
    once they have a memory); follower: Living World saw them follow you (followers: names, default from its state)."""
    found = {}
    world_dir = os.path.join(conversations_dir, world or '')
    for folder, strip in ((os.path.join(world_dir, 'living_world'), '.json'), (world_dir, '')):
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for entry in names:
            if strip and not entry.endswith(strip):
                continue
            match = FILE.match(entry[:-len(strip)] if strip else entry)
            if match and (strip or os.path.isdir(os.path.join(folder, entry))):
                key = (match.group(1).lower(), match.group(2).upper())
                found.setdefault(key, {'name': match.group(1), 'ref_id': match.group(2), 'has': True})
    with_memories = sorted(found.values(), key=lambda p: p['name'].lower())
    others, listed = [], set()
    for row in ui_overrides._base_rows(csv_path):
        ref, name = mantella_ref(row.get('ref_id')), (row.get('name') or '').strip()
        if ref and name:
            listed.add((name.lower(), ref.upper()))
        if ref and name and (name.lower(), ref.upper()) not in found:
            found[(name.lower(), ref.upper())] = None
            others.append({'name': name, 'ref_id': ref, 'has': False})
    out = with_memories + others
    follows = {f.lower() for f in (ui_overrides.followers_seen() if followers is None else followers)}
    names = collections.Counter(p['name'].lower() for p in out)
    for p in out:  # the ref id only where two NPCs share a name
        p['label'] = f"{p['name']} ({p['ref_id']})" if names[p['name'].lower()] > 1 else p['name']
        p['custom'] = (p['name'].lower(), p['ref_id'].upper()) not in listed
        p['follower'] = p['name'].lower() in follows
    return out


def status_text(mem, name) -> str:
    recent = mem.get('recent') or []
    if not recent and not mem.get('long_term') and not mem.get('feeling'):
        return f"{name} has no memories of you yet. Add some below, or they start after your first conversation."
    notes = len(mem.get('long_term') or {})
    lines = [(f"{len(recent)} memory" if len(recent) == 1 else f"{len(recent)} memories")
             + (f", plus {notes} long-term note{'s' if notes != 1 else ''}" if notes else '') + '.']
    promises = memory.open_promises(mem)
    if promises:
        lines.append('Open promises: ' + '; '.join(promises))
    return '\n\n'.join(lines)


def to_tables(mem) -> tuple[str, list, list]:
    recent = [[e.get('day', -1), e.get('hour', -1), e.get('text', '')] for e in mem.get('recent') or []]
    long_term = [[k, v] for k, v in (mem.get('long_term') or {}).items()]
    return mem.get('feeling') or '', recent, long_term


def _num(value) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):  # OverflowError: 'inf' typed into a number cell
        return -1


def _entry_key(entry: dict) -> tuple:
    """What tells one memory entry from another when the file is read again."""
    return entry.get('day'), entry.get('hour'), entry.get('text') or '', entry.get('shared')


def from_tables(current, feeling, recent_rows, long_rows) -> dict:
    """The memory to save from the edited tables. A row whose text is unchanged keeps what it had (a shared group
    memory stays shared); an edited one becomes this NPC's own text. Blank rows are dropped."""
    old = {(e.get('text') or ''): e for e in current.get('recent') or []}
    recent = []
    for row in recent_rows or []:
        row = list(row) + ['', '', ''][len(row):]
        text = str(row[2] or '').strip()
        if not text:
            continue
        day, hour = _num(row[0]), _num(row[1])
        before = old.get(text)
        if before is not None and before.get('day') == day and before.get('hour') == hour:
            recent.append(dict(before))
        else:
            recent.append({'day': day, 'hour': hour, 'text': text[:memory.MAX_ENTRY_CHARS]})
    long_term, _ = long_term_from_rows(long_rows)
    return dict(current, recent=recent, long_term=long_term, feeling=(feeling or '').strip())


def long_term_from_rows(long_rows) -> tuple[dict, list[str]]:
    """({topic: text}, topics that had more than one row). Rows with the same topic are joined, never dropped; a note
    without a topic goes under 'earlier'."""
    long_term, joined = {}, []
    for r in long_rows or []:
        text = str((r[1] if len(r) > 1 else '') or '').strip()
        if not text:
            continue
        topic = str(r[0] or '').strip() or 'earlier'
        if topic in long_term:
            long_term[topic] += '\n' + text
            if topic not in joined:
                joined.append(topic)
        else:
            long_term[topic] = text
    return long_term, joined


NOTES_PROMPT = ("You keep the memories of an NPC in Skyrim for Mantella, an AI mod. Turn the user's notes into memories "
                "from the NPC's own point of view, first person, one short paragraph each, in the order they happened. "
                "Keep only what the notes say; never invent details. Give the in-game day and hour (0-23) only when "
                "the notes say them, else -1. Only if the notes say outright how the NPC feels about the player, add "
                "that in a few words; otherwise leave feeling empty. Answer only with JSON: {\"memories\": [{\"day\": -1, \"hour\": -1, \"text\": \"...\"}], \"feeling\": \"\"}")


def notes_to_rows(ask, name, player, notes) -> tuple[list, str | None, str]:
    """(memory rows, feeling or None, problem): the model turns plain-word notes into rows for the Memories table.
    Nothing is saved here; the rows are added to the table for the user to check. Never raises."""
    if not (notes or '').strip():
        return [], None, 'Write what happened first.'
    try:
        reply = ask(NOTES_PROMPT, f"NPC: {name}\nPlayer: {player}\n\nNOTES:\n{notes}") or ''
    except Exception as e:
        return [], None, f"Could not ask the model: {e}"
    match = re.search(r'\{.*\}', reply, re.S)
    try:
        data = json.loads(match.group(0)) if match else None
    except (ValueError, RecursionError):  # RecursionError: a reply nested too deep
        data = None
    items = data.get('memories') if isinstance(data, dict) else None
    if not isinstance(items, list):
        return [], None, 'The model did not answer in the expected form; try again or add the rows by hand.'
    rows = [[_num(i.get('day', -1)), _num(i.get('hour', -1)), str(i['text']).strip()[:memory.MAX_ENTRY_CHARS]]
            for i in items if isinstance(i, dict) and str(i.get('text') or '').strip()]
    feeling = str(data.get('feeling') or '').strip() or None
    return rows, feeling, ''


def _backup_folder(backup_root, suffix=''):
    """A new folder each time: two deletes in the same second must not overwrite the first one's backup."""
    base = os.path.join(backup_root, time.strftime('%Y%m%d-%H%M%S') + suffix)
    folder, n = base, 1
    while os.path.exists(folder):
        n += 1
        folder = f"{base}-{n}"
    os.makedirs(folder)
    return folder


def _legacy_folders(store, name, ref_id) -> list[str]:
    """Mantella's own summary folders for this NPC ("<name> - <ref id>", older ones "<name>"). Living World turns
    them into a memory the first time it loads one, so a forgotten memory would come back unless they go too."""
    base = memory.file_name(name)
    if not base or base != os.path.basename(base) or '..' in base:
        return []
    return [p for p in (os.path.join(store.legacy_root, f"{base} - {ref_id}"), os.path.join(store.legacy_root, base))
            if os.path.isdir(p)]


def reset_memory(store, name, ref_id, backup_root=DEFAULT_BACKUPS) -> bool:
    """The NPC forgets the player in this save: their memory file and Mantella's own summary folders for them move to
    a dated backup folder (never deleted). False when there was nothing."""
    path = store._path(name, ref_id)
    legacy = _legacy_folders(store, name, ref_id)
    if not path.exists() and not legacy:
        return False
    folder = _backup_folder(backup_root)
    if path.exists():
        shutil.move(str(path), os.path.join(folder, path.name))
    for old in legacy:
        shutil.move(old, os.path.join(folder, 'mantella_summaries', os.path.basename(old)))
    return True


def memory_choices(mem) -> list[str]:
    """One label per memory, newest first, for the Delete one memory list."""
    out = []
    recent = mem.get('recent') or []
    for i in range(len(recent) - 1, -1, -1):
        e = recent[i]
        when = memory.header(e.get('day', -1), e.get('hour', -1)) or '[undated]'
        text = ' '.join(str(e.get('text') or '').split())
        out.append(f"{i + 1}. {when} {text[:90]}{'...' if len(text) > 90 else ''}")
    return out


def delete_one(store, name, ref_id, label, backup_root=DEFAULT_BACKUPS) -> str:
    """Removes the memory a memory_choices label points at; the file as it was is copied to a dated backup folder
    first. Returns the removed text, or '' when the label no longer matches (the memory changed meanwhile)."""
    mem = store.load(name, ref_id)
    recent = mem.get('recent') or []
    match = re.match(r'(\d+)\. ', label or '')
    index = int(match.group(1)) - 1 if match else -1
    if not (0 <= index < len(recent)) or label not in memory_choices(mem):
        return ''
    path = store._path(name, ref_id)
    if path.exists():
        shutil.copy2(str(path), os.path.join(_backup_folder(backup_root), path.name))
    removed = recent.pop(index)
    # the promises that talk added go with it (read from the same summary, same day); an open one would stay overdue
    day = removed.get('day', -1)
    before = len(mem.get('facts') or [])
    if isinstance(day, int) and day >= 0:
        mem['facts'] = [f for f in mem.get('facts') or []
                        if not (f.get('status') == 'open' and f.get('day') == day and f.get('source', 'ai') == 'ai')]
    gone = before - len(mem.get('facts') or [])
    store.save(name, ref_id, mem)
    text = removed.get('text') or '(a shared group memory)'
    return text + (f"\n(and {gone} promise{'s' if gone != 1 else ''} from that talk)" if gone else '')


def save_counts(conversations_dir, world) -> tuple[int, int]:
    """(NPCs who remember the player, memories in all) in one save, from Living World's files and Mantella's own
    summary folders. Only reads: loading would convert old summaries."""
    world_dir = os.path.join(conversations_dir, world or '')
    seen, memories = set(), 0
    try:
        files = os.listdir(os.path.join(world_dir, 'living_world'))
    except OSError:
        files = []
    for f in files:
        match = FILE.match(f[:-5]) if f.endswith('.json') else None
        if not match:
            continue
        seen.add((match.group(1).lower(), match.group(2).upper()))
        try:
            with open(os.path.join(world_dir, 'living_world', f), encoding='utf-8-sig') as fh:
                memories += len(memory.clean(json.load(fh))['recent'])
        except (OSError, ValueError):
            pass
    try:
        folders = os.listdir(world_dir)
    except OSError:
        folders = []
    for f in folders:
        match = FILE.match(f)
        if match and os.path.isdir(os.path.join(world_dir, f)) and (match.group(1).lower(), match.group(2).upper()) not in seen:
            seen.add((match.group(1).lower(), match.group(2).upper()))
            memories += len([s for s in os.listdir(os.path.join(world_dir, f)) if '_summary_' in s])
    return len(seen), memories


def purge_save(conversations_dir, world, backup_root=DEFAULT_BACKUPS) -> int:
    """Every NPC forgets the player in this save: everything in the save's conversations folder (Living World's
    memories and Mantella's own summaries) moves to a dated backup folder. Returns how many entries moved."""
    world_dir = os.path.join(conversations_dir, world or '')
    if not world or memory._UNSAFE.search(world) or world.strip('. ') == '' or not os.path.isdir(world_dir):
        return 0
    entries = os.listdir(world_dir)
    if not entries:
        return 0
    folder = _backup_folder(backup_root, f'-{world}-all')
    for entry in entries:
        shutil.move(os.path.join(world_dir, entry), os.path.join(folder, entry))
    return len(entries)


def build(gr, conversations_dir=DEFAULT_CONVERSATIONS, config=None):
    gr.HTML(ui_help.intro('Pick a save and an NPC: see what they remember, then edit it.',
                          "What each NPC remembers about you, per save character. Living World writes a memory after "
                          "each conversation; older ones fold into long-term notes. Edit them here as plain tables, or "
                          "write in plain words and let the AI turn it into memories. Changes apply from the next "
                          "conversation with that NPC.\n\nLong-term notes: older memories folded into short notes by "
                          "topic ('earlier' is the general one). Kept even when recent memories run out."))
    worlds = saves(conversations_dir)
    state = {'people': [], 'pick': None}
    ask = ui_overrides.model_asker(config) if config is not None else None

    def listing(w, t=True, c=False, f=False):
        everyone = people(conversations_dir, w)
        state['people'] = [p for p in everyone if (not t or p['has']) and (not c or p['custom']) and (not f or p['follower'])]
        state['talked'] = bool(t)
        state['counts'] = tuple(sum(1 for p in everyone if p[k]) for k in ('has', 'custom', 'follower'))
        return [p['label'] for p in state['people']]

    def idle_text():
        if state['people']:
            return 'Pick an NPC to see what they remember.'
        if state.get('talked'):
            return 'Nobody remembers you in this save yet. Untick Talked with to give someone a first memory.'
        return 'Nobody matches these ticks.'

    def relist(w, t, c, f, keep=None):
        """Find NPC's choices for these ticks, and the ticks with their counts. keep: the NPC to leave picked if still listed."""
        choices = listing(w, t, c, f)
        return (gr.update(choices=choices, value=keep if keep in choices else None),
                *(gr.update(label=f"{name} ({n})") for name, n in zip(TICKS, state['counts'])))

    first = listing(worlds[0] if worlds else None)
    with gr.Row():
        talked = gr.Checkbox(label=f"{TICKS[0]} ({state['counts'][0]})", value=True)
        custom = gr.Checkbox(label=f"{TICKS[1]} ({state['counts'][1]})", value=False)
        follows = gr.Checkbox(label=f"{TICKS[2]} ({state['counts'][2]})", value=False)
    ticks = [talked, custom, follows]
    with gr.Row():
        world = gr.Dropdown(choices=worlds, value=worlds[0] if worlds else None, label='Save (your character)', interactive=True, scale=1)
        pick = gr.Dropdown(choices=first, value=None, label='Find NPC (type to search)',
                           filterable=True, interactive=True, scale=3,
                           info='Untick Talked with to give someone a first memory.')
    status = gr.Markdown(idle_text())
    with gr.Row():
        example_btn = gr.Button('Show example', size='sm', scale=0, min_width=140)
    editor = gr.Column(visible=False)
    with editor:
        gr.HTML(ui_help.label('How they feel about you', 'One line, from their point of view. The model reads it before every talk.'))
        feeling = gr.Textbox(show_label=False)
    with editor, gr.Accordion('Add memories in plain words (AI)', open=False):
        gr.HTML(ui_help.label('What happened', "Write it however you like, e.g. 'On day 3 we drank at the Bannered Mare and I "
                              "gave her a ring'. Your current model turns it into memory rows from the NPC's point of view; "
                              "they are added to the table below for you to check, nothing is saved until Save memory. "
                              "Costs one short request."))
        notes = gr.Textbox(show_label=False, lines=3, placeholder='What happened, in plain words')
        with gr.Row():
            to_rows = gr.Button('Turn into memories', scale=0, min_width=160)
    with editor:
        gr.HTML(ui_help.label('Memories', "One row per memory, oldest first: day and hour in game (-1 if unknown) and what "
                              "happened, from the NPC's point of view. Add a row to give them a new memory; clear a row's "
                              "text to forget it."))
        recent = gr.Dataframe(headers=['Day', 'Hour', 'What happened'], datatype=['number', 'number', 'str'], type='array',
                              row_count=(1, 'dynamic'), col_count=(3, 'fixed'), interactive=True, wrap=True,
                              column_widths=['70px', '70px', 'auto'])
    with editor, gr.Accordion('Long-term notes', open=False):
        long_term = gr.Dataframe(headers=['Topic', 'What they remember'], datatype=['str', 'str'], type='array',
                                 row_count=(1, 'dynamic'), col_count=(2, 'fixed'), interactive=True, wrap=True)
    said = gr.Markdown('')
    sure = gr.Checkbox(visible=False)

    def store_for(w):
        return memory.MemoryStore(conversations_dir, w) if w else None

    # state is shared by every browser window and survives a page reload, so anything that writes or moves a file
    # checks that this window's Find NPC still shows the NPC held in state.
    def picked(label):
        p = state['pick']
        return p if p and label and p['label'] == label else None

    def show(w, label):
        p = next((x for x in state['people'] if x['label'] == label), None)
        if p is None and label and w:  # state is shared by every window: another one may have listed other ticks
            p = next((x for x in people(conversations_dir, w) if x['label'] == label), None)
        state['pick'] = p
        if not p or not w:
            return idle_text(), '', [], [], gr.update(), gr.update(visible=False), gr.update(visible=True), gr.update(visible=False)
        mem = store_for(w).load(p['name'], p['ref_id'])
        state['shown'] = [_entry_key(e) for e in mem['recent']]
        f, r, l = to_tables(mem)
        return (status_text(mem, p['name']), f, r or [], l or [], '', gr.update(visible=True), gr.update(visible=False),
                gr.update(visible=True))

    def save(w, f, r, l, label=None, t=True, c=False, fo=False):
        p = picked(label)
        if not p or not w:
            return gr.update(), 'Pick an NPC first.', gr.update(), gr.update(), gr.update(), gr.update()
        store = store_for(w)
        current = store.load(p['name'], p['ref_id'])
        new = from_tables(current, f, r, l)
        # memories the game wrote while the tables were open are not in them: kept, not dropped
        in_table = [_entry_key(e) for e in new['recent']]
        shown = (state.get('shown') or []) + in_table
        arrived = [dict(e) for e in current['recent'] if _entry_key(e) not in shown]
        new['recent'] = new['recent'] + arrived
        state['shown'] = in_table  # what the table holds now; the arrived ones are still not in it
        store.save(p['name'], p['ref_id'], memory.clean(new) | {k: v for k, v in new.items() if k not in memory.empty()})
        joined = long_term_from_rows(l)[1]
        extra = (f" Long-term notes with the same topic were joined into one: {', '.join(joined)}." if joined else '')
        if arrived:
            extra += f" {len(arrived)} newer memory(s) from the game were kept too; pick the NPC again to see them."
        return (status_text(store.load(p['name'], p['ref_id']), p['name']),
                ui_overrides._notify(gr, f"Saved {p['name']}'s memory.{extra} Used from your next conversation with them."),
                *relist(w, t, c, fo, keep=label))

    def turn(n, f, r):
        p = state['pick']
        if not p:
            return gr.update(), gr.update(), gr.update(), 'Pick an NPC first.'
        if ask is None:
            return gr.update(), gr.update(), gr.update(), 'This needs a newer Mantella - Direct AI Connect.'
        from . import lw_state
        rows, new_feeling, problem = notes_to_rows(ask, p['name'], lw_state.load_player_name() or 'the player', n)
        if problem:
            return gr.update(), gr.update(), gr.update(), problem
        kept = [row for row in (r or []) if len(row) > 2 and str(row[2] or '').strip()]
        # a feeling the user already wrote is never replaced by the model's
        return (kept + rows, f if (f or '').strip() else (new_feeling or ''), '',
                ui_overrides._notify(gr, f"{len(rows)} memory row(s) added below. Check them, then Save memory."))

    def forget_list(w):
        p = state['pick']
        choices = memory_choices(store_for(w).load(p['name'], p['ref_id'])) if p and w else []
        return gr.update(choices=choices, value=None)

    def reset(ok, w, label=None, t=True, c=False, f=False, *_):
        p = picked(label)
        keep = gr.update(), gr.update(), gr.update(), gr.update()
        same = gr.update(), gr.update(), gr.update(), gr.update()
        if not p or not w:
            return *keep, 'Pick an NPC first.', gr.update(), *same
        if not ok:
            return *keep, 'Nothing deleted.', gr.update(), *same
        if not reset_memory(store_for(w), p['name'], p['ref_id']):
            return *keep, f"{p['name']} has no memories of you to delete.", gr.update(), *same
        return (status_text(memory.empty(), p['name']), '', [], [],
                ui_overrides._notify(gr, f"{p['name']} no longer remembers you in {w}. The files were moved to "
                                         f"living_world_memory_removed in case you want them back."),
                gr.update(choices=[], value=None), *relist(w, t, c, f, keep=label))

    def delete_picked(ok, w, label, npc=None, *_):
        p = picked(npc)
        if not p or not w:
            return gr.update(), gr.update(), 'Pick an NPC first.', gr.update()
        if not label:
            return gr.update(), gr.update(), 'Pick the memory to delete first.', gr.update()
        if not ok:
            return gr.update(), gr.update(), 'Nothing deleted.', gr.update()
        removed = delete_one(store_for(w), p['name'], p['ref_id'], label)
        mem = store_for(w).load(p['name'], p['ref_id'])
        state['shown'] = [_entry_key(e) for e in mem['recent']]  # the table below now shows these
        if not removed:
            return status_text(mem, p['name']), to_tables(mem)[1], 'That memory changed meanwhile; pick it again.', forget_list(w)
        return (status_text(mem, p['name']), to_tables(mem)[1],
                ui_overrides._notify(gr, f"{p['name']} no longer remembers: {removed.partition(chr(10))[0][:120]} {removed.partition(chr(10))[2]}".strip()),
                forget_list(w))

    def purge_ask(w):
        if not w:
            return gr.update(visible=False), '', 'Pick a save first.'
        npcs, memories = save_counts(conversations_dir, w)
        if not npcs:
            return gr.update(visible=False), '', f"Nobody remembers you in {w}; nothing to delete."
        warning = (f"⚠️ **{npcs} NPC(s) in {w} will forget you ({memories} memories).** Their feelings and long-term "
                   f"notes go too, and Mantella's own summaries for this save. The files move to "
                   f"living_world_memory_removed, so they can be copied back by hand, but not from the game.")
        return gr.update(visible=True), warning, ''

    def purge(ok, w, t=True, c=False, f=False, *_):
        if not ok:
            return (gr.update(visible=False), 'Nothing deleted.', gr.update(), gr.update(), gr.update(), gr.update(),
                    gr.update(), gr.update(), gr.update(), gr.update())
        moved = purge_save(conversations_dir, w)
        state['pick'] = None
        pick_update, *tick_updates = relist(w, t, c, f)
        return (gr.update(visible=False),
                ui_overrides._notify(gr, f"Every NPC in {w} has forgotten you ({moved} file(s)/folder(s) moved to living_world_memory_removed)."),
                pick_update, idle_text(), gr.update(visible=False), gr.update(visible=True), gr.update(visible=False), *tick_updates)

    def example():
        state['pick'] = None  # so Save can never write the example into the NPC that was open
        return (f"**{EXAMPLE_NAME}**: this is how a memory looks. Nothing is saved; pick an NPC to get theirs back.",
                EXAMPLE_FEELING, EXAMPLE_RECENT, EXAMPLE_LONG, gr.update(visible=True), gr.update(visible=False))

    world.change(lambda w, t, c, f: (*relist(w, t, c, f), idle_text()), inputs=[world] + ticks, outputs=[pick] + ticks + [status])
    for box in ticks:
        box.change(lambda w, t, c, f: (*relist(w, t, c, f), idle_text()), inputs=[world] + ticks, outputs=[pick] + ticks + [status])
    to_rows.click(turn, inputs=[notes, feeling, recent], outputs=[recent, feeling, notes, said])
    with editor, gr.Row():
        saved = gr.Button('Save memory', variant='primary', scale=0, min_width=160).click(
            save, inputs=[world, feeling, recent, long_term, pick] + ticks, outputs=[status, said, pick] + ticks)
    with gr.Accordion('Delete memories', open=False):
        with gr.Column(visible=False) as npc_danger:  # only with an NPC open
            gr.HTML(ui_help.label('Delete one memory', "The NPC forgets this one thing. Their file as it was is copied to "
                                  "living_world_memory_removed first."))
            with gr.Row():
                forget = gr.Dropdown(choices=[], value=None, show_label=False, interactive=True, scale=3)
                forget_btn = gr.Button('Delete this memory', variant='stop', size='sm', elem_classes=['lw-danger'], scale=0, min_width=160)
            gr.HTML(ui_help.label("Delete all of this NPC's memories", "The NPC forgets you completely in this save: "
                                  "memories, feeling and long-term notes, plus Mantella's own summaries for them (otherwise "
                                  "those would turn back into a memory). The files move to living_world_memory_removed."))
            with gr.Row():
                reset_btn = gr.Button("Delete all of this NPC's memories", variant='stop', size='sm', elem_classes=['lw-danger'], scale=0, min_width=160)
        gr.HTML(ui_help.label("Delete every NPC's memories in this save", "Everyone in the chosen save forgets you. Asks "
                              "twice. The files move to living_world_memory_removed."))
        with gr.Row():
            purge_btn = gr.Button("Delete every NPC's memories in this save...", variant='stop', size='sm', elem_classes=['lw-danger'], scale=0, min_width=160)
        with gr.Column(visible=False) as purge_box:
            purge_text = gr.Markdown('')
            with gr.Row():
                purge_yes = gr.Button('Yes, everyone forgets me in this save', variant='stop', size='sm', elem_classes=['lw-danger'])
                purge_no = gr.Button('Cancel')
        sure_purge = gr.Checkbox(visible=False)
    pick.change(lambda l: 'Loading...' if l else gr.update(), inputs=[pick], outputs=[status]).then(
        show, inputs=[world, pick], outputs=[status, feeling, recent, long_term, said, editor, example_btn, npc_danger])
    example_btn.click(example, outputs=[status, feeling, recent, long_term, editor, npc_danger])
    forget_btn.click(delete_picked, inputs=[sure, world, forget, pick], outputs=[status, recent, said, forget],
                     js=ui_overrides._confirm_js("Delete this memory? The NPC will no longer remember it."))
    reset_btn.click(reset, inputs=[sure, world, pick] + ticks, outputs=[status, feeling, recent, long_term, said, forget, pick] + ticks,
                    js="(...a) => { a[0] = confirm('Delete all of this NPC\\'s memories of you in save ' + a[1] + '? "
                       "They forget you completely: memories, feeling and notes.'); return a; }")
    purge_btn.click(purge_ask, inputs=[world], outputs=[purge_box, purge_text, said])
    purge_no.click(lambda: (gr.update(visible=False), 'Nothing deleted.'), outputs=[purge_box, said])
    purge_yes.click(purge, inputs=[sure_purge, world] + ticks, outputs=[purge_box, said, pick, status, editor, example_btn, npc_danger] + ticks,
                    js="(...a) => { a[0] = confirm('Last check: every NPC in save ' + a[1] + ' forgets you. Delete?'); return a; }")
    pick.change(forget_list, inputs=[world], outputs=[forget])
    saved.then(forget_list, inputs=[world], outputs=[forget])
    world.change(lambda: gr.update(visible=False), outputs=[purge_box])
