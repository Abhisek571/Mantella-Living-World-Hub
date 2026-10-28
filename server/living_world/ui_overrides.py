"""The "Living World Overrides" tab: the player's description (Mantella's own setting, which then wins over the MCM's),
and NPCs: look one up in Mantella's character list (its csv plus the user's override files on top), edit their bio or
voice, and save an override with only the changed fields to the user's own character_overrides folder
(Documents\\My Games\\Mantella\\data\\Skyrim\\character_overrides). Mantella's own csv is never written. Mantella reads
overrides at startup; "Apply now" re-reads them in the running Mantella."""
import collections
import configparser
import csv
import html
import json
import os
import re
import shutil
import time

from . import lw_state, ui_help

FIELDS = ('bio', 'voice_model')
PLAYER_SETTING = 'player_character_description'
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
# where reset overrides go; next to the folder, not in it, so Mantella never loads them
DEFAULT_BACKUPS = os.path.join(user_folder(), 'data', 'Skyrim', 'character_overrides_removed')


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


def followers_seen(data_dir=None) -> set:
    """Names of the NPCs Living World has seen as followers (its per-NPC state; only NPCs talked to through Mantella)."""
    folder = os.path.join(data_dir or lw_state.DATA_DIR, 'npc')
    names = set()
    try:
        files = os.listdir(folder)
    except OSError:
        return names
    for name in files:
        try:
            with open(os.path.join(folder, name), 'rb') as f:
                data = json.loads(lw_state.decode(f.read()))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and (data.get('int') or {}).get('follower') and (data.get('string') or {}).get('name'):
            names.add(data['string']['name'])
    return names


def tags(row) -> list[str]:
    return [t for t in ('override', 'custom', 'follower') if row.get('_' + t)]


def find_characters(query, csv_path=DEFAULT_CSV, overrides_dir=DEFAULT_OVERRIDES, limit=20, only_mine=False,
                    only_custom=False, only_followers=False, followers=None, everyone=False):
    """NPCs whose name contains query, as Mantella sees them (base row with the user's overrides applied). A blank
    query lists the NPCs the user has an override for and the followers (everyone=True: every NPC). Each row is marked
    _override (the user has one), _custom (not in Mantella's csv) and _follower; the only_* filters keep the rows with
    all the marks asked. limit=None returns them all."""
    q = (query or '').strip().lower()
    followers = {f for f in (followers if followers is not None else followers_seen())}
    follower_names = {f.lower() for f in followers}
    base = _base_rows(csv_path)
    base_names = {r.get('name', '').lower() for r in base}
    extra = [o for o in _override_rows(overrides_dir) if q in o.get('name', '').lower()]
    mine = {o['name'].lower() for o in extra}
    wanted = lambda n: q in n if q else (everyone or n in mine or n in follower_names)
    rows = [dict(r) for r in base if wanted(r.get('name', '').lower())]
    for o in extra:
        match = next((r for r in rows if _same(r, o)), None)
        if match is None:
            rows.append(dict(o))
        else:
            match.update({k: v for k, v in o.items() if v})
    seen = {r['name'].lower() for r in rows}
    rows += [{'name': f, 'race': '', 'base_id': '', 'bio': '', 'voice_model': ''} for f in sorted(followers)
             if f.lower() not in seen and wanted(f.lower())]
    for r in rows:
        n = r['name'].lower()
        r['_override'], r['_custom'], r['_follower'] = n in mine, n not in base_names, n in follower_names
    rows = [r for r in rows if (not only_mine or r['_override']) and (not only_custom or r['_custom']) and (not only_followers or r['_follower'])]
    return rows[:limit]


def labels(rows) -> list[str]:
    """One dropdown label per row: "Name (Race) [tags]", with the base id added where a name and race repeat."""
    plain = [f"{r['name']} ({r.get('race', '') or '?'})" for r in rows]
    counts = collections.Counter(plain)
    out = []
    for text, r in zip(plain, rows):
        if counts[text] > 1:
            text = f"{r['name']} ({r.get('race', '') or '?'}, {r.get('base_id', '') or 'no id'})"
        out.append(text + (f" [{', '.join(tags(r))}]" if tags(r) else ''))
    seen = {}
    for i, text in enumerate(out):  # still the same (same name, race and id): number them
        seen[text] = seen.get(text, 0) + 1
        if seen[text] > 1:
            out[i] = f"{text} #{seen[text]}"
    return out


def new_npc_problem(name, csv_path=DEFAULT_CSV) -> str:
    """Why a new NPC override with this name should not be made ('' = fine). NPCs in Mantella's list are picked
    from the list instead; a second entry with their name would clash with theirs."""
    name = (name or '').strip()
    if not name:
        return 'Type the NPC name first, exactly as it shows in game.'
    if any(r.get('name', '').lower() == name.lower() for r in _base_rows(csv_path)):
        return f"{name} is already in Mantella's list: pick them in Find NPC and edit that instead."
    return ''


EXAMPLE_OVERRIDE = """Hadvar is a Nord soldier of the Imperial Legion, born and raised in Riverwood. His uncle Alvor is the village blacksmith, married to Sigrid, with a young daughter, Dorthe. Hadvar was at Helgen when the dragon attacked and helped a stranger escape the burning keep; he sent them to Alvor for food and shelter.

He is steady, decent and plain-spoken: loyal to the Legion and the Empire, but uneasy with orders that feel unjust, like the near execution at Helgen. He believes Skyrim is stronger united under the Empire and sees Ulfric's rebellion as reckless, yet he never forgets that the men on the other side are Nords too. He jokes a little to ease tension, worries about his family, and treats people by what they do rather than where they come from.

Example lines [use as inspiration but avoid parroting]: "Gods, what was that thing? A dragon? Here?" "My uncle Alvor will help you. Tell him I sent you." "The Legion is the only thing holding Skyrim together right now." "Stick close to me. We get through this together." """


def default_bio(row, csv_path=DEFAULT_CSV) -> str:
    """Mantella's own bio for this NPC, the one an override replaces ('' for NPCs not in its csv)."""
    return next((r.get('bio', '') for r in _base_rows(csv_path) if _same(r, row)), '')


PLAYER_PRESETS = {
    'Dragonborn (default)': "A capable adventurer who carries themselves with quiet confidence. Word has spread of a "
                            "Dragonborn who devours dragon souls and speaks with the Voice; those who have heard the "
                            "tales may wonder if this is them. To most people they are simply a traveller with a "
                            "weapon, worth respect and a little caution.",
    'Lore-friendly sellsword': "A weathered sellsword who has seen most of Skyrim's holds. Practical, plain-spoken and "
                               "not easily impressed; works for coin but keeps their word. Most people take them for "
                               "exactly what they look like: someone useful in a fight.",
    'Mysterious stranger': "A quiet stranger who says little about where they come from. Polite but guarded, with an "
                           "air that makes people curious and a little uneasy. Rumours about them differ from town to "
                           "town, and they never confirm any of them.",
    'Scholar of the College': "A scholar and mage associated with the College of Winterhold, curious about ruins, "
                              "Dwemer machines and old magic. Speaks thoughtfully, asks a lot of questions, and is "
                              "treated with the usual Nord suspicion of magic users.",
}
DEFAULT_PRESET = 'Dragonborn (default)'


# the user's own presets: in their Mantella folder, so they never ship with the mod
MY_PRESETS = os.path.join(user_folder(), 'data', 'Skyrim', 'living_world_player_presets.json')
MINE = ' (mine)'


def _my_presets(path) -> dict:
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def all_presets(path=MY_PRESETS) -> dict:
    """The built-in presets, then the user's own, each marked (mine)."""
    return dict(PLAYER_PRESETS, **{name + MINE: text for name, text in _my_presets(path).items()})


def save_my_preset(path, name, text) -> str:
    """Adds or replaces one of the user's own presets; '' when saved, else why not."""
    name, text = (name or '').strip(), (text or '').strip()
    if name.endswith(MINE):
        name = name[:-len(MINE)].strip()
    if not name or not text:
        return 'Give the preset a name and a description first.'
    if name in PLAYER_PRESETS:
        return f"'{name}' is a built-in preset; pick another name."
    presets = _my_presets(path)
    presets[name] = text
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='ascii') as f:
        json.dump(presets, f, ensure_ascii=True, indent=2)
    os.replace(tmp, path)
    return ''


def reset_player_description(config) -> bool:
    """Back to the default preset (not empty: an empty description makes Mantella use the MCM's text)."""
    return save_player_description(config, PLAYER_PRESETS[DEFAULT_PRESET])


def known_voices(csv_path=DEFAULT_CSV) -> list[str]:
    """Mantella's voice types, from its character list (each NPC's voice_model)."""
    return sorted({r.get('voice_model', '').strip() for r in _base_rows(csv_path)} - {''}, key=str.lower)


def known_races(csv_path=DEFAULT_CSV) -> list[str]:
    """The races in Mantella's character list, for the race dropdown (a custom one can still be typed)."""
    return sorted({r.get('race', '').strip() for r in _base_rows(csv_path)} - {''}, key=str.lower)


def custom_voice_warning(voice, known, tts_service='') -> str:
    """A heads-up when the voice is not one of Mantella's voice types ('' when it is, or empty)."""
    voice = (voice or '').strip()
    if not voice or voice.lower() in {k.lower() for k in known}:
        return ''
    tts = tts_service or 'your text-to-speech'
    return (f"Heads up: '{voice}' looks like a custom voice model. It only works once that voice is installed in "
            f"{tts} (your TTS on this or another PC); otherwise Mantella falls back to a default voice.")


OPTIMIZE_PROMPT = ("You write NPC bios for Mantella, a Skyrim AI mod: the bio is the NPC's whole character sheet in the "
                   "prompt. Rewrite the bio you are given so the NPC works as intended and stays in character: keep "
                   "every fact from the default bio (role, home, family, quest knowledge, way of speaking) unless the "
                   "user's version changes it on purpose, keep the user's personality changes, stay lore-accurate to "
                   "The Elder Scrolls, and cut repetition so it uses fewer tokens (at most about 300 words). Keep a "
                   "few example lines marked [use as inspiration but avoid parroting]. Write in plain prose, third "
                   "person, no headings, no '#'. Answer with the bio only.")
CREATE_PROMPT = ("You write NPC bios for Mantella, a Skyrim AI mod: the bio is the NPC's whole character sheet in the "
                 "prompt. Turn the user's notes into a complete bio for a custom NPC: who they are, where they come "
                 "from, personality, how they speak, how they see the player. Stay in character and lore-accurate to "
                 "The Elder Scrolls, keep it under about 300 words to save tokens, and end with a few example lines "
                 "marked [use as inspiration but avoid parroting]. Plain prose, third person, no headings, no '#'. "
                 "Answer with the bio only.")
PLAYER_PROMPT = ("You write the player character's description for Mantella, a Skyrim AI mod. NPCs read it to know how "
                 "they perceive the player when they meet. Turn the user's notes into a lore-accurate description for "
                 "The Elder Scrolls: first what ordinary mortals see; then what only spiritually attuned or very "
                 "experienced beings can sense (priests, mages, ancient or Daedric beings), and how carefully they "
                 "react; then any hidden truth NPCs must never state or guess unless the player reveals it. Use "
                 "Elder Scrolls names and cosmology where the notes borrow from elsewhere. Write in the third person "
                 "(he, she or they, as the notes use), never 'you'. At most about 160 words, plain prose, no headings, "
                 "no '#'. Answer with the description only.")
MAX_BIO_CHARS = 3000


def _clean_reply(reply) -> str:
    text = (reply or '').strip()
    text = re.sub(r'^(here is|here\'s)[^\n]*:\s*\n', '', text, flags=re.I)  # "Here is the bio:" preface
    text = re.sub(r'^```[a-z]*\n|\n?```$', '', text.strip()).strip()
    return text[:MAX_BIO_CHARS]


def optimize_bio(ask, name, default, current) -> str:
    """The model's proposal for this NPC's bio: an optimized merge of the default and the user's text, or, for a
    custom NPC (no default), a full bio from the user's notes. Never raises."""
    if (default or '').strip():
        system, text = OPTIMIZE_PROMPT, f"NPC: {name}\n\nDEFAULT BIO:\n{default}\n\nUSER'S VERSION:\n{current or default}"
    else:
        system, text = CREATE_PROMPT, f"NPC: {name}\n\nNOTES:\n{current}"
    try:
        return _clean_reply(ask(system, text)) or 'The model gave no answer.'
    except Exception as e:
        return f"Could not ask the model: {e}"


def optimize_player(ask, notes) -> str:
    try:
        return _clean_reply(ask(PLAYER_PROMPT, f"NOTES:\n{notes}")) or 'The model gave no answer.'
    except Exception as e:
        return f"Could not ask the model: {e}"


STARTED = time.time()  # Mantella reads every override at startup; this module loads with it
_applied = {'at': 0.0}


def _own_bio(row, overrides_dir):
    for data in _override_rows(overrides_dir):
        if _same(data, row) and data.get('bio'):
            return data['bio']
    return None


def override_state(row, overrides_dir=DEFAULT_OVERRIDES, running_bio=None, started=None) -> tuple[str, str]:
    """('none' | 'active' | 'pending', text): whether this NPC's override is what the running Mantella uses now.
    running_bio(row) -> the bio Mantella holds now (None when unknown); otherwise judged by when the file was saved
    against Mantella's start and the last Apply now."""
    mine = _own_bio(row, overrides_dir)
    if mine is None:
        return 'none', "No override: Mantella's default bio is used."
    now = running_bio(row) if running_bio else None
    if now is not None:
        active = now == mine
    else:
        newest = max((os.path.getmtime(os.path.join(overrides_dir, n)) for n in os.listdir(overrides_dir)
                      if n.endswith('.json')), default=0)
        active = newest <= max(STARTED if started is None else started, _applied['at'])
    return ('active', 'Override active right now.') if active else \
        ('pending', 'Override saved, not in use yet: press Apply now (or restart Mantella).')


def running_bio_fn(game):
    """running_bio for override_state, read from Mantella's character list in memory (None when not reachable)."""
    def lookup(row):
        df = getattr(game, 'character_df', None)
        if df is None:
            return None
        try:
            hit = df[df['name'].astype(str).str.lower() == row['name'].lower()]
            if row.get('race'):
                same_race = hit[hit['race'].astype(str).str.lower() == row['race'].lower()]
                hit = same_race if len(same_race) else hit
            return str(hit.iloc[0]['bio']) if len(hit) else None
        except Exception:
            return None
    return lookup


def _backup_dir(backup_root):
    path = os.path.join(backup_root, time.strftime('%Y%m%d-%H%M%S'))
    os.makedirs(path, exist_ok=True)
    return path


def _move(path, folder):
    target, n = os.path.join(folder, os.path.basename(path)), 2
    while os.path.exists(target):
        stem, ext = os.path.splitext(os.path.basename(path))
        target, n = os.path.join(folder, f"{stem} ({n}){ext}"), n + 1
    shutil.move(path, target)


def reset_override(overrides_dir, row, backup_root=None) -> list[str]:
    """Back to Mantella's default for this NPC: their own single-NPC override files move to a dated backup folder
    (never deleted). A file holding a list of NPCs is left alone. Returns the moved file names."""
    backup_root = backup_root or DEFAULT_BACKUPS
    found = []
    for name in sorted(os.listdir(overrides_dir)) if os.path.isdir(overrides_dir) else []:
        path = os.path.join(overrides_dir, name)
        if not name.endswith('.json'):
            continue
        try:
            with open(path, encoding='utf-8-sig') as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and _same(data, row):
            found.append(path)
    if found:
        folder = _backup_dir(backup_root)
        for path in found:
            _move(path, folder)
    return [os.path.basename(p) for p in found]


def reset_all(overrides_dir, backup_root=None) -> int:
    """Every override file moves to a dated backup folder; returns how many."""
    files = [os.path.join(overrides_dir, n) for n in sorted(os.listdir(overrides_dir))] if os.path.isdir(overrides_dir) else []
    files = [p for p in files if p.endswith('.json') and os.path.isfile(p)]
    if files:
        folder = _backup_dir(backup_root or DEFAULT_BACKUPS)
        for path in files:
            _move(path, folder)
    return len(files)


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
    _applied['at'] = time.time()
    return True


def _player_value(config):
    try:
        return config.definitions.get_config_value_definition(PLAYER_SETTING)
    except Exception:
        return None


def player_description(config) -> str:
    """The player's description from Mantella's settings ('' when there is none yet)."""
    value = _player_value(config)
    return str(value.value or '') if value is not None else ''


def save_player_description(config, text) -> bool:
    """Sets Mantella's player description setting (Mantella writes config.ini and reloads before the next
    conversation). False when it is unchanged or the settings are not reachable."""
    value, text = _player_value(config), (text or '').strip()
    if value is None or text == str(value.value or ''):
        return False
    value.value = text
    return True


def request_reload(config) -> bool:
    """Makes Mantella rebuild its character list (csv + overrides) before the next conversation, the same way a changed
    setting does. Needed after a reset: re-applying overrides cannot bring back the default a removed one replaced."""
    if config is None or not hasattr(config, '_ConfigLoader__has_any_value_changed'):
        return False
    config._ConfigLoader__has_any_value_changed = True
    return True


def model_asker(config):
    """ask(system, text) -> reply, using the model Mantella talks with (its client is made on first use)."""
    client = {}

    def ask(system, text):
        from src.llm.llm_client import LLMClient
        from src.llm.message_thread import message_thread
        from src.llm.messages import UserMessage
        if 'llm' not in client:
            client['llm'] = LLMClient(config)
            # its own copy: room for a whole bio, and no stop sequence (Mantella's '#' would cut it short)
            params = dict(getattr(client['llm'], '_request_params', None) or {})
            params['max_tokens'] = max(int(params.get('max_tokens') or 0), 1500)
            params.pop('stop', None)
            client['llm']._request_params = params
        thread = message_thread(config, system)
        thread.add_message(UserMessage(config, text))
        return client['llm'].request_call(thread)
    return ask


def _confirm_js(question):
    # the browser's own "are you sure?" box. Gradio hands a js step the inputs first (then the outputs), so the
    # hidden checkbox is always the first input and gets the answer
    return "(...a) => { a[0] = confirm(" + json.dumps(question) + "); return a; }"


def _notify(gr, text):
    try:
        gr.Info(text)
    except Exception:
        pass
    return text


OVERRIDE_HELP = ("An override is your own version of a character for Mantella. For an NPC it replaces their default bio "
                 "(and voice) completely: the model only ever sees your version. For the player it is the description "
                 "every NPC reads when you talk. Overrides are your own files; Mantella's character list and your "
                 "game files are never changed, and Reset puts the default back.")
STATE_STYLE = {'active': '#22c55e', 'pending': '#eab308', 'none': '#9ca3af'}


def _state_html(state):
    level, text = state
    return f'<div style="margin:2px 0 6px"><b style="color:{STATE_STYLE[level]}">● {html.escape(text)}</b></div>'


def build_page(gr, config, game_fn):
    with gr.Tab('Living World Player and NPC Data'):
        gr.HTML(ui_help.heading('Living World Player and NPC Data', OVERRIDE_HELP,
                                'Your own versions of characters. Hover any ? for what it does.'))
        with gr.Accordion('Player', open=True):
            gr.HTML(ui_help.heading('Player', "How NPCs see your character, sent with every conversation. When this is set "
                                    "it is used instead of the text in the MCM. It is the same setting as Other > Player "
                                    "Character Description. Reset puts the Dragonborn default back.",
                                    'How NPCs see you. Set here, it wins over the MCM.'))
            with gr.Row():
                preset = gr.Dropdown(choices=list(all_presets()), value=DEFAULT_PRESET, label='Presets', scale=3)
                use_preset = gr.Button('Use preset', scale=1)
            # a function: Gradio calls it on every page load, so the box never shows a stale description
            text = gr.Textbox(show_label=False, lines=6, value=lambda: player_description(config), placeholder='Describe your character, or rough notes for Optimize with AI.')
            proposal = gr.Textbox(label='AI proposal (not saved until you press Use this and Save)', lines=6, visible=False, interactive=True)
            use_proposal = gr.Button('Use this', visible=False)
            said = gr.Markdown('')
            sure = gr.Checkbox(visible=False)
            ask = model_asker(config)

            def reset_player(ok, *_):
                if not ok:
                    return gr.update(), 'Not reset.'
                reset_player_description(config)
                return PLAYER_PRESETS[DEFAULT_PRESET], _notify(gr, 'Player description reset to the Dragonborn default. Used from the next conversation.')

            def optimize(t):
                if not (t or '').strip():
                    return gr.update(), gr.update(), 'Write a description or a few notes first.'
                out = optimize_player(ask, t)
                ok = not out.startswith(('Could not', 'The model gave'))
                return gr.update(value=out, visible=True), gr.update(visible=ok), _notify(gr, 'Proposal ready below. Use this, then Save.') if ok else out

            use_preset.click(lambda p: all_presets().get(p, ''), inputs=[preset], outputs=[text])

            def save_preset(n, t):
                problem = save_my_preset(MY_PRESETS, n, t)
                if problem:
                    return gr.update(), problem
                return gr.update(choices=list(all_presets()), value=n.strip().removesuffix(MINE).strip() + MINE),                 _notify(gr, f"Saved as your preset '{n.strip()}'. It stays on this PC only.")
            use_proposal.click(lambda p: (p, gr.update(visible=False), gr.update(visible=False), 'Copied. Press Save player description to keep it.'),
                               inputs=[proposal], outputs=[text, proposal, use_proposal, said])
            with gr.Row():
                gr.Button('Save player description', variant='primary').click(
                    lambda t: _notify(gr, 'Saved. Used from the next conversation.') if save_player_description(config, t) else 'Nothing changed.',
                    inputs=[text], outputs=[said])
                gr.Button('Optimize with AI').click(optimize, inputs=[text], outputs=[proposal, use_proposal, said])
                gr.Button('Reset player description', variant='stop').click(
                    reset_player, inputs=[sure], outputs=[text, said],
                    js=_confirm_js('Reset your player description to the Dragonborn default?'))
            with gr.Row():
                preset_name = gr.Textbox(show_label=False, placeholder='Name for your own preset, e.g. My Dragonborn', scale=3)
                gr.Button('Save as my preset', scale=1).click(save_preset, inputs=[preset_name, text], outputs=[preset, said])
            gr.HTML('<div style="display:flex;gap:18px;flex-wrap:wrap;opacity:.85">'
                    + ui_help.label('Optimize with AI', "Your current model turns your text or rough notes into a lore-accurate "
                                    "description: what ordinary people see, what only attuned beings sense, and what NPCs must "
                                    "never guess. Recommended: it keeps NPCs reacting the way you intend and uses fewer tokens. "
                                    "Costs one request; you see the result before anything is saved.")
                    + ui_help.label('Presets', "Ready-made descriptions. Use preset puts one in the box; edit it, then Save. "
                                    "Save as my preset keeps the text in the box as your own preset, in your Mantella folder "
                                    "on this PC only (marked 'mine'); it is never part of the mod.", right=True)
                    + '</div>')
        with gr.Accordion('NPCs', open=True):
            build(gr, game_fn, config, ask)


def build(gr, game_fn, config=None, ask=None):
    gr.HTML(ui_help.heading('Characters', OVERRIDE_HELP,
                            'Pick an NPC, edit the bio, save, apply. The override replaces their default bio.'))
    with gr.Row():
        only_mine = gr.Checkbox(label='My overrides', value=False)
        only_custom = gr.Checkbox(label="Custom NPCs (not in Mantella's list)", value=False)
        only_followers = gr.Checkbox(label='Followers', value=False)
    state = {'rows': [], 'labels': [], 'new': False}
    voices = known_voices()
    tts = getattr(config, 'tts_service', '') if config is not None else ''
    tts = str(getattr(tts, 'display_name', tts) or '')  # Mantella's TTSEnum names itself ("XTTS", "Piper", ...)
    running = lambda: running_bio_fn(game_fn())

    def refresh(m=False, c=False, f=False):
        state['rows'] = find_characters('', limit=None, only_mine=m, only_custom=c, only_followers=f, everyone=True)
        state['labels'] = labels(state['rows'])
        return state['labels']

    gr.HTML(ui_help.label('Find NPC', "Click and type part of a name. Lists everyone in Mantella's list plus your "
                          "custom NPCs. Tags: override = you have one, custom = not in Mantella's list, follower = "
                          "Living World saw them follow you (only NPCs you have talked to through Mantella)."))
    pick = gr.Dropdown(choices=refresh(), value=None, show_label=False, filterable=True, interactive=True,
                       info=f"{len(state['labels'])} NPCs. Type to search.")
    with gr.Row():
        new_btn = gr.Button('New NPC override')
        example_btn = gr.Button('Show example')
    gr.HTML(ui_help.label('NPC', "The NPC being edited. For a new NPC override, type the name exactly as it shows in "
                          "game. Use New NPC override only for a new follower or NPC from a mod that is not in "
                          "Mantella's list; for anyone already in the list, pick them in Find NPC, or the two would clash."))
    with gr.Row():
        name = gr.Textbox(show_label=False, interactive=False, placeholder='Pick an NPC above', scale=3)
        race = gr.Dropdown(choices=known_races(), value=None, show_label=False, interactive=False, filterable=True,
                           allow_custom_value=True, scale=1)
    badge = gr.HTML('')
    gr.HTML(ui_help.label('Bio', "Who they are: role, home, family, personality, how they speak, how they see the "
                          "player. For a custom NPC, rough notes are fine: Optimize with AI turns them into a full bio."))
    bio = gr.Textbox(show_label=False, lines=12)
    gr.HTML(ui_help.label('Voice model', "Pick one of Mantella's voice types (type to search). Add custom voice is for "
                          "a voice you installed yourself in your text-to-speech, for example a follower's own voice."))
    with gr.Row():
        voice = gr.Dropdown(choices=voices, value=None, show_label=False, filterable=True, allow_custom_value=True, scale=3)
        add_voice = gr.Button('Add custom voice', scale=1)
    custom_voice = gr.Textbox(label='Custom voice name (as installed in your TTS)', visible=False)
    voice_warning = gr.Markdown('')
    example = gr.Textbox(value=EXAMPLE_OVERRIDE, label='Example override (Hadvar), for reference only, never saved',
                         lines=10, interactive=False, visible=False)
    proposal = gr.Textbox(label='AI proposal (not saved until you press Use this bio and Save override)', lines=10, visible=False, interactive=True)
    use_proposal = gr.Button('Use this bio', visible=False)
    status = gr.Markdown('')
    sure = gr.Checkbox(visible=False)
    if ask is None and config is not None:
        ask = model_asker(config)

    def badge_for(row):
        return _state_html(override_state(row, running_bio=running())) if row else ''

    def warn(v):
        text = custom_voice_warning(v, voices, tts)
        return f'⚠️ {text}' if text else ''

    def show(label):
        state['new'] = False
        try:
            row = state['rows'][state['labels'].index(label)]
        except ValueError:
            row = None
        state['row'] = row
        if not row:
            return gr.update(value='', interactive=False), gr.update(value=None, interactive=False), '', gr.update(value=None), '', '', ''
        v = row.get('voice_model', '') or None
        return (gr.update(value=row['name'], interactive=False), gr.update(value=row.get('race', '') or None, interactive=False),
                row.get('bio', ''), gr.update(value=v), warn(v), badge_for(row), '')

    def new_npc():
        state['new'], state['row'] = True, None
        return (gr.update(value=None), gr.update(value='', interactive=True, placeholder='NPC name, exactly as in game'),
                gr.update(value=None, interactive=True), '', gr.update(value=None), '',
                _state_html(('none', 'New NPC override: only for a new follower or NPC from a mod that is not in Mantella\'s list.')), '')

    def save(n, r, b, v, m, c, f):
        if state['new']:
            problem = new_npc_problem(n)
            if problem:
                return problem, gr.update(), gr.update()
            row = {'name': n.strip(), 'race': (r or '').strip(), 'base_id': '', 'bio': '', 'voice_model': ''}
        else:
            row = state.get('row')
            if not row:
                return 'Pick an NPC first.', gr.update(), gr.update()
        if not (b or '').strip():
            return 'The bio is empty; nothing saved.', gr.update(), gr.update()
        path = save_override(DEFAULT_OVERRIDES, row, {'bio': b, 'voice_model': v or ''})
        if not path:
            return 'Nothing changed.', gr.update(), badge_for(row)
        choices = refresh(m, c, f)
        found = next((l for l, x in zip(choices, state['rows']) if _same(x, row)), None)
        state['new'] = False
        state['row'] = state['rows'][choices.index(found)] if found else row
        hidden = '' if found else ' (not in the list right now: untick the filters to see them)'
        return (_notify(gr, f"Saved {os.path.basename(path)}{hidden}. Press Apply now to use it in the next conversation."),
                gr.update(choices=choices, value=found), badge_for(state['row']))

    def apply():
        row = state.get('row')
        msg = _notify(gr, 'Applied: the running Mantella uses your overrides from the next conversation.') if apply_now(game_fn()) else \
            "Mantella will read it at its next start (or press again after your first conversation this session)."
        return msg, badge_for(row)

    def optimize(b):
        row = state.get('row')
        if state['new']:
            row = {'name': '(new NPC)', 'race': ''}
        if not row:
            return gr.update(), gr.update(), 'Pick an NPC first.'
        if ask is None:
            return gr.update(), gr.update(), 'Optimize needs a newer Mantella - Direct AI Connect.'
        if not (b or '').strip() and not default_bio(row):
            return gr.update(), gr.update(), 'Write a few notes in the bio first.'
        out = optimize_bio(ask, row['name'], default_bio(row), b)
        ok = not out.startswith(('Could not', 'The model gave'))
        return gr.update(value=out, visible=True), gr.update(visible=ok), _notify(gr, 'Proposal ready below. Use this bio, then Save override.') if ok else out

    def reset_one(ok, *_):
        row = state.get('row')
        if not row:
            return 'Pick an NPC first.', gr.update()
        if not ok:
            return 'Not reset.', gr.update()
        moved = reset_override(DEFAULT_OVERRIDES, row)
        if not moved:
            return f"{row['name']} has no override file of their own to reset.", badge_for(row)
        request_reload(config)
        return (_notify(gr, f"{row['name']} is back to Mantella's default from the next conversation ({', '.join(moved)} moved to character_overrides_removed)."),
                badge_for(row))

    def reset_every(ok, *_):
        if not ok:
            return 'Not reset.'
        count = reset_all(DEFAULT_OVERRIDES)
        request_reload(config)
        return _notify(gr, f"{count} override file(s) moved to character_overrides_removed. Every NPC uses Mantella's default from the next conversation.")

    filters = [only_mine, only_custom, only_followers]
    for box in filters:
        box.change(lambda m, c, f: gr.update(choices=refresh(m, c, f), value=None, info=f"{len(state['labels'])} NPCs. Type to search."),
                   inputs=filters, outputs=[pick])
    pick.change(show, inputs=[pick], outputs=[name, race, bio, voice, voice_warning, badge, status])
    new_btn.click(new_npc, outputs=[pick, name, race, bio, voice, voice_warning, badge, status])
    example_btn.click(lambda: gr.update(visible=True), outputs=[example])
    voice.change(warn, inputs=[voice], outputs=[voice_warning])
    add_voice.click(lambda: gr.update(visible=True, value=''), outputs=[custom_voice])
    custom_voice.submit(lambda c: (gr.update(value=c.strip() or None), gr.update(visible=False), warn(c)),
                        inputs=[custom_voice], outputs=[voice, custom_voice, voice_warning])
    use_proposal.click(lambda p: (p, gr.update(visible=False), gr.update(visible=False), 'Copied into the bio. Press Save override to keep it.'),
                       inputs=[proposal], outputs=[bio, proposal, use_proposal, status])
    with gr.Row():
        gr.Button('Save override', variant='primary').click(save, inputs=[name, race, bio, voice] + filters, outputs=[status, pick, badge])
        gr.Button('Apply now').click(apply, outputs=[status, badge])
        gr.Button('Optimize with AI').click(optimize, inputs=[bio], outputs=[proposal, use_proposal, status])
    gr.HTML('<div style="display:flex;gap:18px;flex-wrap:wrap;opacity:.85">'
            + ui_help.label('Save override', 'Writes your override file. It is not in use until Apply now (or the next Mantella start); the dot above the bio shows which.')
            + ui_help.label('Apply now', 'Loads your saved overrides into the running Mantella, so the next conversation uses them without a restart.')
            + ui_help.label('Optimize with AI', "Your current model rewrites the bio so the NPC works as intended and stays "
                            "in character: it keeps the facts from their default bio, keeps your changes, stays lore-accurate "
                            "and uses fewer tokens. For a custom NPC it turns rough notes into a full bio. Recommended for "
                            "every new or custom follower. Costs one request; you see the result before anything is saved.", right=True)
            + '</div>')
    with gr.Accordion('Reset', open=False):
        with gr.Row():
            gr.Button('Reset this NPC to default', variant='stop').click(
                reset_one, inputs=[sure], outputs=[status, badge], js=_confirm_js("Reset this NPC to Mantella's default bio and voice?"))
            gr.Button('Reset ALL overrides', variant='stop').click(
                reset_every, inputs=[sure], outputs=[status],
                js=_confirm_js("Reset EVERY NPC override to Mantella's defaults? The files are moved to character_overrides_removed."))
        gr.HTML(ui_help.label('About resets', 'Reset never deletes: the files move to character_overrides_removed (next to your '
                              'overrides folder) in a dated folder, so you can put them back. The change applies from the next conversation.'))
