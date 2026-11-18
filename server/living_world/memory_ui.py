"""Memory helpers for the NPCs page (npc_page_ui.py: what an NPC remembers about the player, edited there) and the
save-wide delete on the Events page. Memories live with Mantella's conversations: <user folder>/data/Skyrim/conversations/<save>/
living_world/<NPC> - <ref id>.json (see memory.py). Deleting one memory, one NPC's memories or a whole save's moves
the files to a dated backup folder, never erases them."""
import collections
import html
import json
import os
import re
import shutil
import time

from . import archive, memory, ui_help, ui_overrides

DEFAULT_CONVERSATIONS = os.path.join(ui_overrides.user_folder(), 'data', 'Skyrim', 'conversations')
DEFAULT_BACKUPS = os.path.join(ui_overrides.user_folder(), 'data', 'Skyrim', 'living_world_memory_removed')
FILE = re.compile(r'^(.+) - ([0-9A-Fa-f]{1,8})$')

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


def status_text(mem, name, kept: int | None = None, hidden: int = 0) -> str:
    """kept: memories in the archive (every memory ever, older ones too); hidden: how many of them are hidden."""
    recent = [e for e in mem.get('recent') or [] if not e.get('hidden')]
    if not recent and not mem.get('long_term') and not mem.get('feeling') and not kept:
        return f"{name} has no memories of you yet. Add some below, or they start after your first conversation."
    notes = len(mem.get('long_term') or {})
    lines = [(f"{len(recent)} memory" if len(recent) == 1 else f"{len(recent)} memories")
             + (f", plus {notes} long-term note{'s' if notes != 1 else ''}" if notes else '') + '.']
    if kept:
        lines[0] += (f" {kept} kept in all; older ones come back when a talk is about them"
                     + (f", except {hidden} hidden" if hidden else '') + '.')
    promises = memory.open_promises(mem)
    if promises:
        lines.append('Open promises: ' + '; '.join(promises))
    return '\n\n'.join(lines)


def to_tables(mem) -> tuple[str, list, list]:
    """Hidden memories stay out of the table; they are listed apart, greyed out, with Unhide."""
    recent = [[e.get('day', -1), e.get('hour', -1), e.get('text', '')] for e in mem.get('recent') or [] if not e.get('hidden')]
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
    """The NPC forgets the player in this save: their memory file, their archive of older memories and Mantella's own
    summary folders for them move to a dated backup folder (never deleted). False when there was nothing."""
    path = store._path(name, ref_id)
    kept = store.archive_path(name, ref_id)
    legacy = _legacy_folders(store, name, ref_id)
    if not path.exists() and not kept.exists() and not legacy:
        return False
    folder = _backup_folder(backup_root)
    for f in (path, kept):
        if f.exists():
            shutil.move(str(f), os.path.join(folder, f.name))
    for old in legacy:
        shutil.move(old, os.path.join(folder, 'mantella_summaries', os.path.basename(old)))
    return True


def memory_choices(mem) -> list[str]:
    """One label per memory, newest first, for the Delete one memory list."""
    out = []
    recent = mem.get('recent') or []
    for i in range(len(recent) - 1, -1, -1):
        e = recent[i]
        if e.get('hidden'):
            continue
        when = memory.header(e.get('day', -1), e.get('hour', -1)) or '[undated]'
        text = ' '.join(str(e.get('text') or '').split())
        out.append(f"{i + 1}. {when} {text[:90]}{'...' if len(text) > 90 else ''}")
    return out


def with_hidden(recent: list[dict], hidden: list[dict]) -> list[dict]:
    """recent (the table's rows) with the hidden memories put back where they were by time: each goes after the last
    shown memory not later than it. Appended at the end, an old one would read as the newest once it is unhidden."""
    out = list(recent)
    when = lambda e: (memory._int(e.get('day')), memory._int(e.get('hour')))
    for entry in hidden:
        at = len(out)
        while at > 0 and when(out[at - 1]) > when(entry):
            at -= 1
        out.insert(at, entry)
    return out


def delete_one(store, name, ref_id, label, backup_root=DEFAULT_BACKUPS) -> str:
    """Removes the memory a memory_choices label points at; the file as it was is copied to a dated backup folder
    first. Returns the removed text, or '' when the label no longer matches (the memory changed meanwhile)."""
    with store.lock(name, ref_id):
        return _delete_one(store, name, ref_id, label, backup_root)


def _delete_one(store, name, ref_id, label, backup_root) -> str:
    mem = store.load(name, ref_id)
    recent = mem.get('recent') or []
    match = re.match(r'(\d+)\. ', label or '')
    index = int(match.group(1)) - 1 if match else -1
    if not (0 <= index < len(recent)) or label not in memory_choices(mem):
        return ''
    path, kept = store._path(name, ref_id), store.archive_path(name, ref_id)
    if path.exists() or kept.exists():
        folder = _backup_folder(backup_root)
        for f in (path, kept):
            if f.exists():
                shutil.copy2(str(f), os.path.join(folder, f.name))
    removed = recent.pop(index)
    forget_in_archive(store, name, ref_id, [removed])  # or it would come back when a talk is about it
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


def forget_in_archive(store, name, ref_id, entries) -> None:
    """Memories the user deleted leave the archive too (moving them out of recent alone would not forget them)."""
    try:
        if entries and store.archive_path(name, ref_id).exists():
            store.archive_for(name, ref_id).delete([archive.entry_id(e) for e in entries])
    except Exception:
        pass  # the archive is extra; the memory file is already saved


def archive_counts(store, name, ref_id) -> tuple[int | None, int]:
    """(memories in the archive, hidden ones) for the status line; (None, 0) without an archive."""
    try:
        if not store.archive_path(name, ref_id).exists():
            return None, 0
        ids = store.archive_for(name, ref_id).ids()
        return len(ids), sum(1 for h in ids.values() if h)
    except Exception:
        return None, 0


def hidden_choices(rows) -> list[str]:
    """One label per hidden memory (memory.list_hidden rows), for the Unhide list; the id is at the end."""
    out = []
    for r in rows:
        when = memory.header(r.get('day', -1), r.get('hour', -1)) or '[undated]'
        text = ' '.join(str(r.get('text') or '').split())
        out.append(f"{when} {text[:80]}{'...' if len(text) > 80 else ''} #{r['id']}")
    return out


def hidden_html(rows) -> str:
    """Hidden memories greyed out, with who hid them and why."""
    if not rows:
        return '<div style="opacity:.6">No hidden memories.</div>'
    items = []
    for r in rows:
        mark = r.get('hidden') or {}
        by = ' by ' + html.escape(str(mark.get('by'))) if mark.get('by') else ''
        note = ': ' + html.escape(str(mark.get('note'))) if mark.get('note') else ''
        day = f" on day {mark['day']}" if isinstance(mark.get('day'), int) and mark['day'] >= 0 else ''
        when = memory.header(r.get('day', -1), r.get('hour', -1))
        items.append(f'<li style="opacity:.45"><s>{html.escape(when)} {html.escape(str(r.get("text") or ""))}</s>'
                     f'<br><small>Hidden{day}{by}{note}</small></li>')
    return '<ul style="margin:0;padding-left:18px">' + ''.join(items) + '</ul>'


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


def build_save(gr, conversations_dir=DEFAULT_CONVERSATIONS) -> None:
    """Deleting every NPC's memories in one save. One NPC's memories are shown and edited on the NPCs page."""
    worlds = saves(conversations_dir)
    with gr.Accordion("Delete every NPC's memories in a save", open=False):
        gr.HTML(ui_help.about('Everyone in one save forgets you. It asks twice first.', "Everyone in the chosen save forgets you: "
                              "memories, feelings, long-term notes and Mantella's own summaries. Asks twice. The files "
                              "move to living_world_memory_removed. One NPC's memories: the NPCs page."))
        with gr.Row():
            world = gr.Dropdown(choices=worlds, value=worlds[0] if worlds else None, label='Save (your character)', interactive=True, scale=3)
            purge_btn = gr.Button("Delete every NPC's memories in this save...", variant='stop', size='sm', elem_classes=['lw-danger'], scale=0, min_width=160)
        with gr.Column(visible=False) as purge_box:
            purge_text = gr.Markdown('')
            with gr.Row():
                purge_yes = gr.Button('Yes, everyone forgets me in this save', variant='stop', size='sm', elem_classes=['lw-danger'])
                purge_no = gr.Button('Cancel')
        said = gr.Markdown('')
        sure = gr.Checkbox(visible=False)

    def purge_ask(w):
        if not w:
            return gr.update(visible=False), '', 'Pick a save first.'
        npcs, memories = save_counts(conversations_dir, w)
        if not npcs:
            return gr.update(visible=False), '', f"Nobody remembers you in {w}; nothing to delete."
        warning = (f"**Warning: {npcs} NPC(s) in {w} will forget you ({memories} memories).** Their feelings and long-term "
                   f"notes go too, and Mantella's own summaries for this save. The files move to "
                   f"living_world_memory_removed, so they can be copied back by hand, but not from the game.")
        return gr.update(visible=True), warning, ''

    def purge(ok, w, *_):
        if not ok:
            return gr.update(visible=False), 'Nothing deleted.'
        moved = purge_save(conversations_dir, w)
        return (gr.update(visible=False),
                ui_overrides._notify(gr, f"Every NPC in {w} has forgotten you ({moved} file(s)/folder(s) moved to living_world_memory_removed)."))

    purge_btn.click(purge_ask, inputs=[world], outputs=[purge_box, purge_text, said])
    purge_no.click(lambda: (gr.update(visible=False), 'Nothing deleted.'), outputs=[purge_box, said])
    purge_yes.click(purge, inputs=[sure, world], outputs=[purge_box, said],
                    js="(...a) => { a[0] = confirm('Last check: every NPC in save ' + a[1] + ' forgets you. Delete?'); return a; }")
    world.change(lambda: gr.update(visible=False), outputs=[purge_box])
