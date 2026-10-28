"""The "Living World Memory" tab: pick a save and an NPC, see what they remember about the player, and edit it as
tables (no JSON). Memories live with Mantella's conversations: <user folder>/data/Skyrim/conversations/<save>/
living_world/<NPC> - <ref id>.json (see memory.py). Reset moves the file to a dated backup folder, never deletes."""
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

EXAMPLE_NAME = 'Hadvar (example, never saved)'
EXAMPLE_FEELING = 'Trusts CHAD after Helgen; a little protective of them.'
EXAMPLE_RECENT = [
    [1, 9, 'CHAD and I escaped Helgen together when the dragon attacked. I told them to go to my uncle Alvor in Riverwood.'],
    [2, 18, 'CHAD came by Alvor\'s forge. I thanked them for getting word to Whiterun about the dragon.'],
]
EXAMPLE_LONG = [['earlier', 'Served in the Legion with Ralof once, before the war split us.']]


def saves(conversations_dir=DEFAULT_CONVERSATIONS) -> list[str]:
    """Save characters (Mantella's world ids) that have a conversations folder."""
    try:
        return sorted(d for d in os.listdir(conversations_dir) if os.path.isdir(os.path.join(conversations_dir, d)))
    except OSError:
        return []


def people(conversations_dir, world, csv_path=ui_overrides.DEFAULT_CSV) -> list[dict]:
    """[{label, name, ref_id, has}] for the Find NPC list: NPCs with memories in this save first (Living World's
    files and Mantella's own summary folders), then every NPC in Mantella's list with a ref id (memories are filed by
    name and ref id, so one is needed to start a memory)."""
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
    others = []
    for row in ui_overrides._base_rows(csv_path):
        ref, name = (row.get('ref_id') or '').strip(), (row.get('name') or '').strip()
        if ref and name and (name.lower(), ref.upper()) not in found:
            found[(name.lower(), ref.upper())] = None
            others.append({'name': name, 'ref_id': ref, 'has': False})
    out = with_memories + others
    for p in out:
        p['label'] = f"{p['name']} ({p['ref_id']})" + (' [memories]' if p['has'] else '')
    return out


def status_text(mem, name) -> str:
    recent = mem.get('recent') or []
    if not recent and not mem.get('long_term') and not mem.get('feeling'):
        return f"{name} has no memories of you yet. Add some below, or they start after your first conversation."
    lines = [f"**{name}** feels: {mem.get('feeling') or '(not set yet)'}",
             f"{len(recent)} memories" + (f", plus {len(mem['long_term'])} long-term note(s)" if mem.get('long_term') else '') + '.']
    if recent:
        newest = recent[-1]
        lines.append(f"Newest {memory.header(newest.get('day', -1), newest.get('hour', -1))}: {(newest.get('text') or '')[:220]}")
    return '\n\n'.join(lines)


def to_tables(mem) -> tuple[str, list, list]:
    recent = [[e.get('day', -1), e.get('hour', -1), e.get('text', '')] for e in mem.get('recent') or []]
    long_term = [[k, v] for k, v in (mem.get('long_term') or {}).items()]
    return mem.get('feeling') or '', recent, long_term


def _num(value) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return -1


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
    long_term = {str(r[0]).strip(): str(r[1]).strip() for r in long_rows or [] if len(r) > 1 and str(r[0]).strip() and str(r[1]).strip()}
    return dict(current, recent=recent, long_term=long_term, feeling=(feeling or '').strip())


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
    except ValueError:
        data = None
    items = data.get('memories') if isinstance(data, dict) else None
    if not isinstance(items, list):
        return [], None, 'The model did not answer in the expected form; try again or add the rows by hand.'
    rows = [[_num(i.get('day', -1)), _num(i.get('hour', -1)), str(i['text']).strip()[:memory.MAX_ENTRY_CHARS]]
            for i in items if isinstance(i, dict) and str(i.get('text') or '').strip()]
    feeling = str(data.get('feeling') or '').strip() or None
    return rows, feeling, ''


def reset_memory(store, name, ref_id, backup_root=DEFAULT_BACKUPS) -> bool:
    """Moves this NPC's memory file to a dated backup folder. False when there was none."""
    path = store._path(name, ref_id)
    if not path.exists():
        return False
    folder = os.path.join(backup_root, time.strftime('%Y%m%d-%H%M%S'))
    os.makedirs(folder, exist_ok=True)
    shutil.move(str(path), os.path.join(folder, path.name))
    return True


def build(gr, conversations_dir=DEFAULT_CONVERSATIONS, config=None):
    gr.HTML(ui_help.heading('Living World Memory', "What each NPC remembers about you, per save character. Living World "
                            "writes a memory after each conversation; older ones fold into long-term notes. Edit them "
                            "here as plain tables, or write in plain words and let the AI turn it into memories. "
                            "Changes apply from the next conversation with that NPC.",
                            'Pick a save and an NPC: see what they remember, then edit it.'))
    worlds = saves(conversations_dir)
    state = {'people': [], 'pick': None}
    ask = ui_overrides.model_asker(config) if config is not None else None

    def listing(w):
        state['people'] = people(conversations_dir, w)
        return [p['label'] for p in state['people']]

    with gr.Row():
        world = gr.Dropdown(choices=worlds, value=worlds[0] if worlds else None, label='Save (your character)', interactive=True, scale=1)
        pick = gr.Dropdown(choices=listing(worlds[0] if worlds else None), value=None, label='Find NPC (type to search)',
                           filterable=True, interactive=True, scale=3,
                           info='[memories] = already remembers you in this save; anyone else can be given a first memory.')
    status = gr.Markdown('Pick an NPC to see what they remember.')
    gr.HTML(ui_help.label('How they feel about you', 'One line, from their point of view. The model reads it before every talk.'))
    feeling = gr.Textbox(show_label=False)
    with gr.Accordion('Add memories in plain words (AI)', open=True):
        gr.HTML(ui_help.label('What happened', "Write it however you like, e.g. 'On day 3 we drank at the Bannered Mare and I "
                              "gave her a ring'. Your current model turns it into memory rows from the NPC's point of view; "
                              "they are added to the table below for you to check, nothing is saved until Save memory. "
                              "Costs one short request."))
        notes = gr.Textbox(show_label=False, lines=3, placeholder='What happened, in plain words')
        to_rows = gr.Button('Turn into memories')
    with gr.Accordion('Memories', open=True):
        gr.HTML(ui_help.label('Memories', "One row per memory, oldest first: day and hour in game (-1 if unknown) and what "
                              "happened, from the NPC's point of view. Add a row to give them a new memory; clear a row's "
                              "text to forget it."))
        recent = gr.Dataframe(headers=['Day', 'Hour', 'What happened'], datatype=['number', 'number', 'str'], type='array',
                              row_count=(1, 'dynamic'), col_count=(3, 'fixed'), interactive=True, wrap=True)
    with gr.Accordion('Long-term notes', open=False):
        gr.HTML(ui_help.label('Long-term notes', "Older memories folded into short notes by topic ('earlier' is the general "
                              "one). Kept even when recent memories run out."))
        long_term = gr.Dataframe(headers=['Topic', 'What they remember'], datatype=['str', 'str'], type='array',
                                 row_count=(1, 'dynamic'), col_count=(2, 'fixed'), interactive=True, wrap=True)
    said = gr.Markdown('')
    sure = gr.Checkbox(visible=False)

    def store_for(w):
        return memory.MemoryStore(conversations_dir, w) if w else None

    def show(w, label):
        p = next((x for x in state['people'] if x['label'] == label), None)
        state['pick'] = p
        if not p or not w:
            return 'Pick an NPC to see what they remember.', '', [], [], ''
        mem = store_for(w).load(p['name'], p['ref_id'])
        f, r, l = to_tables(mem)
        return status_text(mem, p['name']), f, r or [], l or [], ''

    def save(w, f, r, l):
        p = state['pick']
        if not p or not w:
            return gr.update(), 'Pick an NPC first.'
        store = store_for(w)
        current = store.load(p['name'], p['ref_id'])
        new = from_tables(current, f, r, l)
        store.save(p['name'], p['ref_id'], memory.clean(new) | {k: v for k, v in new.items() if k not in memory.empty()})
        return status_text(store.load(p['name'], p['ref_id']), p['name']), ui_overrides._notify(gr, f"Saved {p['name']}'s memory. Used from your next conversation with them.")

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

    def reset(ok, w, *_):
        p = state['pick']
        if not p or not w:
            return gr.update(), gr.update(), gr.update(), gr.update(), 'Pick an NPC first.'
        if not ok:
            return gr.update(), gr.update(), gr.update(), gr.update(), 'Not reset.'
        if not reset_memory(store_for(w), p['name'], p['ref_id']):
            return gr.update(), gr.update(), gr.update(), gr.update(), f"{p['name']} has no Living World memory file to reset."
        return (status_text(memory.empty(), p['name']), '', [], [],
                ui_overrides._notify(gr, f"{p['name']}'s memory reset (moved to living_world_memory_removed)."))

    def example():
        state['pick'] = None  # so Save can never write the example into the NPC that was open
        return (f"**{EXAMPLE_NAME}**: this is how a memory looks. Nothing is saved; pick an NPC to get theirs back.",
                EXAMPLE_FEELING, EXAMPLE_RECENT, EXAMPLE_LONG)

    world.change(lambda w: gr.update(choices=listing(w), value=None), inputs=[world], outputs=[pick])
    pick.change(show, inputs=[world, pick], outputs=[status, feeling, recent, long_term, said])
    to_rows.click(turn, inputs=[notes, feeling, recent], outputs=[recent, feeling, notes, said])
    with gr.Row():
        gr.Button('Save memory', variant='primary').click(save, inputs=[world, feeling, recent, long_term], outputs=[status, said])
        gr.Button('Show example').click(example, outputs=[status, feeling, recent, long_term])
    with gr.Accordion('Reset', open=False):
        gr.HTML(ui_help.label('Reset this memory', "Makes the NPC forget you in this save. Never deletes: the file moves "
                              "to living_world_memory_removed in a dated folder."))
        gr.Button('Reset this memory', variant='stop').click(
            reset, inputs=[sure, world], outputs=[status, feeling, recent, long_term, said],
            js=ui_overrides._confirm_js("Reset this NPC's memory of you? The file is moved to living_world_memory_removed."))
