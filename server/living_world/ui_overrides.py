"""Characters section of the Living World tab: look up an NPC in Mantella's character list (its csv plus the user's
override files on top), edit their bio or voice, and save an override with only the changed fields to the user's own
character_overrides folder (Documents\\My Games\\Mantella\\data\\Skyrim\\character_overrides). Mantella's own csv is
never written. Mantella reads overrides at startup; "Apply now" re-reads them in the running Mantella."""
import configparser
import csv
import json
import os
import re

FIELDS = ('bio', 'voice_model')
DEFAULT_CSV = os.path.join('data', 'Skyrim', 'skyrim_characters.csv')


def user_folder(ini_text=None) -> str:
    """Mantella's user folder, found the way Mantella finds it: custom_user_folder.ini (in its working folder), else
    the Documents folder from the registry (it follows OneDrive or a moved Documents), + My Games\\Mantella."""
    parser = configparser.ConfigParser()
    try:
        if ini_text is None:
            with open('custom_user_folder.ini', encoding='utf-8') as f:
                ini_text = f.read()
        parser.read_string(ini_text)
        custom = parser.get('UserFolder', 'custom_user_folder', fallback='').strip()
        if custom:
            return custom
    except (OSError, configparser.Error):
        pass
    documents = os.path.join(os.path.expanduser('~'), 'Documents')
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders") as key:
            documents = winreg.QueryValueEx(key, 'Personal')[0]
    except (ImportError, OSError):
        pass
    return os.path.join(documents, 'My Games', 'Mantella')


DEFAULT_OVERRIDES = os.path.join(user_folder(), 'data', 'Skyrim', 'character_overrides')


def _base_rows(csv_path):
    try:
        with open(csv_path, encoding='utf-8-sig', newline='') as f:
            return list(csv.DictReader(f))
    except (OSError, csv.Error):
        return []


def _override_rows(overrides_dir):
    rows = []
    try:
        names = sorted(os.listdir(overrides_dir))
    except OSError:
        return rows
    for name in names:
        if not name.endswith('.json'):
            continue
        try:
            with open(os.path.join(overrides_dir, name), encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        rows.extend(d for d in (data if isinstance(data, list) else [data]) if isinstance(d, dict) and d.get('name'))
    return rows


def _same(a, b):
    return a.get('name', '').lower() == b.get('name', '').lower() and (not a.get('race') or not b.get('race') or a['race'].lower() == b['race'].lower())


def find_characters(query, csv_path=DEFAULT_CSV, overrides_dir=DEFAULT_OVERRIDES, limit=20):
    """NPCs whose name contains query, as Mantella sees them (base row with the user's overrides applied)."""
    q = (query or '').strip().lower()
    if not q:
        return []
    rows = [dict(r) for r in _base_rows(csv_path) if q in r.get('name', '').lower()]
    extra = [o for o in _override_rows(overrides_dir) if q in o.get('name', '').lower()]
    for o in extra:
        match = next((r for r in rows if _same(r, o)), None)
        if match is None:
            rows.append(dict(o))
        else:
            match.update({k: v for k, v in o.items() if v})
    return rows[:limit]


def save_override(overrides_dir, current, changes, csv_path=DEFAULT_CSV):
    """Writes <name>.json with the fields that differ from what Mantella has now; returns its path, or None when
    nothing changed. base_id is written only for NPCs in Mantella's csv (mod NPCs match by name and race)."""
    changed = {k: v for k, v in changes.items() if k in FIELDS and isinstance(v, str) and v.strip() and v != current.get(k, '')}
    if not changed:
        return None
    keys = {'name': current['name']}
    if current.get('race'):
        keys['race'] = current['race']
    in_csv = any(r.get('name') == current['name'] and r.get('base_id') == current.get('base_id') for r in _base_rows(csv_path))
    if in_csv and current.get('base_id'):
        keys['base_id'] = current['base_id']
    os.makedirs(overrides_dir, exist_ok=True)
    path, data = _own_file(overrides_dir, keys)
    data.update(keys)
    data.update(changed)
    tmp = path + '.tmp'
    # ASCII only: Mantella reads override files with the system codepage, so é or curly quotes would turn to mojibake
    with open(tmp, 'w', encoding='ascii') as f:
        json.dump(data, f, ensure_ascii=True, indent=2)
    os.replace(tmp, path)
    return path


def _own_file(overrides_dir, keys):
    """(path, existing data) of this NPC's single-NPC override file: one already matching name, race and base id, else
    a new name that no other file uses. A file holding a list (the user's own, several NPCs) is never rewritten."""
    for name in sorted(os.listdir(overrides_dir)):
        if not name.endswith('.json'):
            continue
        path = os.path.join(overrides_dir, name)
        try:
            with open(path, encoding='utf-8-sig') as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and all(str(data.get(k, '')).lower() == str(v).lower() for k, v in keys.items()) \
                and str(data.get('race', '')).lower() == str(keys.get('race', '')).lower():
            return path, data
    stem = re.sub(r'[^\w\- ]', '_', ' - '.join(v for v in (keys['name'], keys.get('race', ''), keys.get('base_id', '')) if v))
    path, n = os.path.join(overrides_dir, stem + '.json'), 2
    while os.path.exists(path):
        path, n = os.path.join(overrides_dir, f"{stem} ({n}).json"), n + 1
    return path, {}


def apply_now(game, overrides_dir=DEFAULT_OVERRIDES):
    """Re-reads the user's overrides in the running Mantella (its own loader). False when Mantella's game object is
    not reachable yet (before the first conversation of the session)."""
    loader = getattr(game, '_Gameable__apply_character_overrides', None)
    df = getattr(game, 'character_df', None)
    if loader is None or df is None:
        return False
    loader(overrides_dir, df.columns.values.tolist())
    return True


def build(gr, game_fn):
    gr.Markdown('## Characters')
    gr.Markdown("Change an NPC's bio or voice. Saved to your own character_overrides folder; Mantella's character list "
                "is never changed. Applies at the next Mantella start, or now with Apply now.")
    query = gr.Textbox(label='Search NPC by name')
    pick = gr.Dropdown(label='NPC', choices=[])
    bio = gr.Textbox(label='Bio', lines=8)
    voice = gr.Textbox(label='Voice model')
    status = gr.Markdown('')
    found = {'rows': []}

    def search(q):
        found['rows'] = find_characters(q)
        # numbered, so two NPCs with the same name stay apart
        labels = [f"{i + 1}. {r['name']} ({r.get('race', '')}, {r.get('base_id', '') or 'no id'})" for i, r in enumerate(found['rows'])]
        return gr.update(choices=labels, value=labels[0] if labels else None)

    def picked(label):
        number = re.match(r'(\d+)\. ', label or '')
        index = int(number.group(1)) - 1 if number else -1
        return found['rows'][index] if 0 <= index < len(found['rows']) else None

    def show(label):
        row = picked(label)
        return (row or {}).get('bio', ''), (row or {}).get('voice_model', '')

    def save(label, b, v):
        row = picked(label)
        if not row:
            return 'Pick an NPC first.'
        path = save_override(DEFAULT_OVERRIDES, row, {'bio': b, 'voice_model': v})
        return f'Saved {os.path.basename(path)}.' if path else 'Nothing changed.'

    def apply():
        return 'Applied.' if apply_now(game_fn()) else 'Mantella reads it at its next start (or after your first conversation, press again).'

    query.submit(search, inputs=[query], outputs=[pick])
    pick.change(show, inputs=[pick], outputs=[bio, voice])
    gr.Button('Save character').click(save, inputs=[pick, bio, voice], outputs=[status])
    gr.Button('Apply now').click(apply, outputs=[status])
