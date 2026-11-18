"""The Player page (the player's description: Mantella's own setting, which then wins over the MCM's) and the override
helpers the NPCs page uses (npc_page_ui.py): look an NPC up in Mantella's character list (its csv plus the user's
override files on top), edit their bio or voice, and save an override with only the changed fields to the user's own character_overrides folder
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


def bio_state(row) -> str:
    """'override' (the user has one), 'default' (Mantella's own bio) or 'no bio' (nothing written about them yet)."""
    if row.get('_override') and (row.get('bio') or '').strip():
        return 'override'
    return 'default' if (row.get('bio') or '').strip() else 'no bio'


def tags(row) -> list[str]:
    return [bio_state(row)] + [t for t in ('custom', 'follower') if row.get('_' + t)]


def find_characters(query, csv_path=None, overrides_dir=None, limit=20, only_mine=False,
                    only_custom=False, only_followers=False, followers=None, everyone=False, only_nobio=False):
    """NPCs whose name contains query, as Mantella sees them (base row with the user's overrides applied). A blank
    query lists the NPCs the user has an override for and the followers (everyone=True: every NPC). Each row is marked
    _override (the user has one), _custom (not in Mantella's csv) and _follower; the only_* filters keep the rows with
    all the marks asked (only_nobio: no bio anywhere yet). limit=None returns them all."""
    csv_path, overrides_dir = csv_path or DEFAULT_CSV, overrides_dir or DEFAULT_OVERRIDES
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
    rows = [r for r in rows if (not only_mine or r['_override']) and (not only_custom or r['_custom']) and (not only_followers or r['_follower'])
            and (not only_nobio or bio_state(r) == 'no bio')]
    return rows[:limit]


def labels(rows) -> list[str]:
    """One dropdown label per NPC: "Name (Race) [default | override | no bio, custom, follower]", with the base id
    added where a name and race repeat."""
    plain = [f"{r['name']} ({r['race']})" if r.get('race') else r['name'] for r in rows]
    counts = collections.Counter(plain)
    out = []
    for text, r in zip(plain, rows):
        if counts[text] > 1:
            text = f"{r['name']} ({r.get('race', '') or '?'}, {r.get('base_id', '') or 'no id'})"
        out.append(f"{text} [{', '.join(tags(r))}]")
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


# What the player is like, nothing more: fame, Dragonborn status, guild ranks and how each NPC feels about the player
# come from World, Knowledge and Relationships, which know the real game state. Pick one, then edit it to fit.
PLAYER_PRESETS = {
    'Traveller (default)': "A traveller in practical, well-worn gear. Polite and even-tempered, quicker to ask questions "
                           "than to talk about themselves, and rarely says much about where they came from.",
    'Sellsword': "A sellsword in battered armour, carrying a weapon that has clearly seen use. Plain-spoken and "
                 "practical, and tends to ask about the work and the pay before anything else.",
    'Quiet stranger': "A hooded, soft-spoken stranger who gives short answers and seldom mentions their past. Watches "
                      "people closely before deciding whether to trust them.",
    'Scholar': "A bookish traveller in robes, more at home among ruins and old texts than in a fight. Curious about "
               "Dwemer machines, ancient Nord tombs and magic, and asks a lot of questions.",
}
DEFAULT_PRESET = 'Traveller (default)'


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


def save_my_preset(path, name, text, built_in=None) -> str:
    """Adds or replaces one of the user's own presets; '' when saved, else why not."""
    built_in = PLAYER_PRESETS if built_in is None else built_in
    name, text = (name or '').strip(), (text or '').strip()
    if name.endswith(MINE):
        name = name[:-len(MINE)].strip()
    if not name or not text:
        return 'Give the preset a name and a description first.'
    if name in built_in:
        return f"'{name}' is a built-in preset; pick another name."
    presets = _my_presets(path)
    presets[name] = text
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='ascii') as f:
        json.dump(presets, f, ensure_ascii=True, indent=2)
    os.replace(tmp, path)
    return ''


MY_NPC_PRESETS = os.path.join(user_folder(), 'data', 'Skyrim', 'living_world_npc_presets.json')
DEFAULT_VERSION = 'Default'
CURRENT_VERSION = 'Current override'
ANY_NPC = ' (any NPC)'
NPC_DEFAULT = DEFAULT_VERSION


def npc_key(row) -> str:
    return f"{(row.get('name') or '').strip().lower()}|{(row.get('race') or '').strip().lower()}"


def _preset_file(path) -> dict:
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_presets(path, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='ascii') as f:
        json.dump(data, f, ensure_ascii=True, indent=2)
    os.replace(tmp, path)


def npc_presets(path=None, row=None) -> dict:
    """Saved override presets: this NPC's own, under the names the user gave them, then presets an older version saved
    for any NPC, marked (any NPC). In the user's Mantella folder: they never ship with the mod."""
    data = _preset_file(path or MY_NPC_PRESETS)
    own = ((data.get('npcs') or {}).get(npc_key(row)) or {}) if row else {}
    out = {str(k): _preset_bio(v) for k, v in own.items() if _preset_bio(v) is not None} if isinstance(own, dict) else {}
    out.update({k + ANY_NPC: v for k, v in data.items() if isinstance(v, str)})
    return out


def _preset_bio(value):
    """A preset's bio: older presets are the bio text alone, newer ones {"bio": ..., "profile": {...}}."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and isinstance(value.get('bio'), str):
        return value['bio']
    return None


def npc_preset_profile(path, row, name) -> dict | None:
    """The facts, factions and flags saved with one of this NPC's presets (characters.py entry), or None for a preset
    that holds only a bio (an older one, or an any-NPC one)."""
    own = ((_preset_file(path or MY_NPC_PRESETS).get('npcs') or {}).get(npc_key(row)) or {}) if row else {}
    value = own.get(name) if isinstance(own, dict) else None
    return value['profile'] if isinstance(value, dict) and isinstance(value.get('profile'), dict) else None


def save_npc_preset(path, row, name, text, profile=None) -> str:
    """Saves the text as one of this NPC's override presets, with the facts, factions and flags when profile is given
    (a preset then applies all of them at once); '' when saved, else why not."""
    name, text = (name or '').strip(), (text or '').strip()
    if not row:
        return 'Pick an NPC first.'
    if not name or not text:
        return 'Give the override preset a name and write the bio first.'
    if name in (DEFAULT_VERSION, CURRENT_VERSION) or name.endswith(ANY_NPC):
        return f"'{name}' is taken; pick another name."
    data = _preset_file(path)
    npcs = data.get('npcs') if isinstance(data.get('npcs'), dict) else {}
    npcs.setdefault(npc_key(row), {})[name] = {'bio': text, 'profile': profile} if isinstance(profile, dict) else text
    data['npcs'] = npcs
    _write_presets(path, data)
    return ''


def delete_npc_preset(path, row, name) -> bool:
    """Removes one of the NPC's own override presets (or an any-NPC one); False when there was no such preset."""
    data = _preset_file(path)
    own = (data.get('npcs') or {}).get(npc_key(row)) if row else None
    if isinstance(own, dict) and name in own:
        del own[name]
        if not own:
            del data['npcs'][npc_key(row)]
    elif name.endswith(ANY_NPC) and isinstance(data.get(name[:-len(ANY_NPC)]), str):
        del data[name[:-len(ANY_NPC)]]
    else:
        return False
    _write_presets(path, data)
    return True


def versions(row, default, override=None, path=None) -> list[str]:
    """The Version dropdown for one NPC: Default (Mantella's bio, when there is one), the override in use when it is
    not one of the presets, then the NPC's saved override presets."""
    presets = npc_presets(path, row)
    out = [DEFAULT_VERSION] if (default or '').strip() else []
    if override and matching_preset(override, presets) is None and ' '.join(override.split()) != ' '.join((default or '').split()):
        out.append(CURRENT_VERSION)
    return out + list(presets)


def version_text(choice, row, default, override=None, path=None) -> str | None:
    if choice == DEFAULT_VERSION:
        return default or None
    if choice == CURRENT_VERSION:
        return override
    return npc_presets(path, row).get(choice)


def version_of(text, row, default, override=None, path=None) -> str | None:
    """Which version this bio text is (None: the user's own unsaved text)."""
    norm = ' '.join((text or '').split())
    if not norm:
        return None
    if norm == ' '.join((default or '').split()):
        return DEFAULT_VERSION
    found = matching_preset(text, npc_presets(path, row))
    if found:
        return found
    return CURRENT_VERSION if override and norm == ' '.join(override.split()) else None


def matching_preset(text, presets: dict) -> str | None:
    """The preset whose text this is (spacing and line breaks ignored), or None."""
    norm = ' '.join((text or '').split())
    return next((name for name, t in presets.items() if norm and ' '.join(t.split()) == norm), None)


def active_player_html(config, path=MY_PRESETS) -> str:
    """The line above the player box: which description NPCs read right now."""
    text = player_description(config)
    if not text.strip():
        return _state_html(('none', "Active now: the MCM's player description (nothing set here)"))
    name = matching_preset(text, all_presets(path))
    return _state_html(('active', f"Active now: preset '{name}'" if name else 'Active now: your own text (not a preset)'))


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
                 "prompt. The user gives you what they have about a custom NPC or follower: rough notes, or a whole "
                 "mod page pasted from Nexus with install steps, requirements, credits and changelogs mixed in. Use "
                 "it as guidance only: take what it says about the character (who they are, where they come from, "
                 "personality, voice, story, how they treat the player) and ignore everything about the mod itself. "
                 "Where it is silent, assume what fits best and stays lore-accurate to The Elder Scrolls. Write a "
                 "complete bio under about 300 words, third person, plain prose, no headings, no '#', ending with a "
                 "few example lines marked [use as inspiration but avoid parroting]. After the bio, on its own line, "
                 "write ASSUMED: and a short semicolon-separated list of the important things you had to assume "
                 "because the text did not say them (or ASSUMED: nothing).")
MIN_NOTES_WORDS = 25
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
    return text[:MAX_BIO_CHARS + 600]


def optimize_bio(ask, name, default, current) -> str:
    """The model's proposal for this NPC's bio: an optimized merge of the default and the user's text, or, for a
    custom NPC (no default), a full bio from the user's notes. Never raises."""
    if (default or '').strip():
        system, text = OPTIMIZE_PROMPT, f"NPC: {name}\n\nDEFAULT BIO:\n{default}\n\nUSER'S VERSION:\n{current or default}"
    else:
        system, text = CREATE_PROMPT, f"NPC: {name}\n\nWHAT THE USER HAS (notes or a pasted page):\n{(current or '')[:12000]}"
    try:
        return _clean_reply(ask(system, text)) or 'The model gave no answer.'
    except Exception as e:
        return f"Could not ask the model: {e}"


def bio_and_assumed(reply) -> tuple[str, str]:
    """(bio, what the model had to assume) from a reply that may end with an "ASSUMED: ..." line."""
    text = reply or ''
    m = re.search(r'\n\s*\**ASSUMED\**\s*:\s*(.*)\s*$', text, flags=re.I | re.S)
    if not m:
        return text.strip(), ''
    assumed = ' '.join(m.group(1).split()).strip(' .')
    return text[:m.start()].strip(), '' if assumed.lower() in ('nothing', 'none', 'n/a') else assumed


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


def override_state(row, overrides_dir=None, running_bio=None, started=None, presets_path=None) -> tuple[str, str]:
    """('none' | 'active' | 'pending', text): whether this NPC's override is what the running Mantella uses now.
    running_bio(row) -> the bio Mantella holds now (None when unknown); otherwise judged by when the file was saved
    against Mantella's start and the last Apply now."""
    overrides_dir = overrides_dir or DEFAULT_OVERRIDES
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
    name = matching_preset(mine, npc_presets(presets_path, row))
    which = f" (preset '{name}')" if name else ''
    return ('active', f'Override active right now{which}.') if active else \
        ('pending', f'Override saved{which}, not in use yet: press Apply now (or restart Mantella).')


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


def model_asker(config, summary: bool = False, max_tokens: int = 1500):
    """ask(system, text) -> reply, using the model Mantella talks with (its client is made on first use). summary: the
    custom summary model instead, when one is set. The client is this asker's own copy, with room for max_tokens of
    reply and no stop sequence, so it never cuts a long answer short and never shares the conversation's client."""
    client = {}

    def ask(system, text):
        from src.llm.message_thread import message_thread
        from src.llm.messages import UserMessage
        if 'llm' not in client:
            if summary and getattr(config, 'summary_llm_enabled', False):
                from src.llm.summary_client import SummaryLLMClient
                client['llm'] = SummaryLLMClient(config)
            else:
                from src.llm.llm_client import LLMClient
                client['llm'] = LLMClient(config)
            # its own copy: room for a whole bio, and no stop sequence (Mantella's '#' would cut it short)
            params = dict(getattr(client['llm'], '_request_params', None) or {})
            params['max_tokens'] = max(int(params.get('max_tokens') or 0), max_tokens)
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
CHARACTERS_INTRO = ('How NPCs see you, and every NPC override at once. Each NPC has their own part on the NPCs page.', OVERRIDE_HELP)
PLAYER_HELP = ("How NPCs see your character, sent with every conversation. When this is set it is used instead of the "
               "text in the MCM. It is the same setting as Other > Player Character Description.\n\n"
               "Presets: picking one puts it in the box; edit it, then Save. "
               "Optimize with AI: your current model turns your text or notes into a lore-accurate description (one "
               "request); you see it before anything is saved. "
               "Save as my preset: keeps the box as your own preset, on this PC only, never part of the mod. "
               "Reset player description: puts the default (Traveller) back.")

STATE_STYLE = {'active': '#22c55e', 'pending': '#eab308', 'none': '#9ca3af'}


def _state_html(state):
    """A status box (ui_help.danger_css draws it: green when active, amber when something is waiting, grey otherwise);
    the text says the state in words too."""
    level, text = state
    level = level if level in STATE_STYLE else 'none'
    return f'<div class="lw-state lw-state-{level}">{html.escape(text)}</div>'


def build_page(gr, config, game_fn):
    """The Player page: the player's description, then Apply now / Reset ALL overrides for NPCs."""
    gr.HTML(ui_help.intro(*CHARACTERS_INTRO))
    gr.HTML(ui_help.heading('Player', PLAYER_HELP, 'How NPCs see you. Set here, it wins over the MCM.'))
    # functions: Gradio calls them on every page load, so nothing shows a stale description
    active = gr.HTML(value=ui_help.safe(lambda: active_player_html(config)))
    preset = gr.Dropdown(choices=list(all_presets()), value=ui_help.safe(lambda: matching_preset(player_description(config), all_presets()), None),
                         label='Presets', info='Picking one puts it in the box below. Edit it if you like, then Save.')
    text = gr.Textbox(show_label=False, lines=6, value=ui_help.safe(lambda: player_description(config)), placeholder='Describe your character, or rough notes for Optimize with AI.')
    proposal = gr.Textbox(label='AI proposal (not saved until you press Use this and Save)', lines=6, visible=False, interactive=True)
    with gr.Row():
        use_proposal = gr.Button('Use this', visible=False, scale=0, min_width=160)
    said = gr.Markdown('')
    sure = gr.Checkbox(visible=False)
    ask = model_asker(config)

    def reset_player(ok, *_):
        if not ok:
            return gr.update(), 'Not reset.'
        reset_player_description(config)
        return PLAYER_PRESETS[DEFAULT_PRESET], _notify(gr, 'Player description reset to the default. Used from the next conversation.')

    def load_preset(p, current):
        chosen = all_presets().get(p)
        if chosen is None or ' '.join(chosen.split()) == ' '.join((current or '').split()):
            return gr.update(), ''
        return chosen, f"Preset '{p}' is in the box. Edit it if you like; it is used once you press Save player description."

    def save_player(t):
        if save_player_description(config, t):
            return _notify(gr, 'Saved. Used from the next conversation.'), active_player_html(config)
        return 'Nothing changed.', active_player_html(config)

    def optimize(t):
        if not (t or '').strip():
            return gr.update(), gr.update(), 'Write a description or a few notes first.'
        out = optimize_player(ask, t)
        ok = not out.startswith(('Could not', 'The model gave'))
        return gr.update(value=out, visible=True), gr.update(visible=ok), _notify(gr, 'Proposal ready below. Use this, then Save.') if ok else out

    preset.change(load_preset, inputs=[preset, text], outputs=[text, said])

    def save_preset(n, t):
        problem = save_my_preset(MY_PRESETS, n, t)
        if problem:
            return gr.update(), problem
        return gr.update(choices=list(all_presets()), value=n.strip().removesuffix(MINE).strip() + MINE),                 _notify(gr, f"Saved as your preset '{n.strip()}'. It stays on this PC only.")
    use_proposal.click(lambda p: (p, gr.update(visible=False), gr.update(visible=False), 'Copied. Press Save player description to keep it.'),
                       inputs=[proposal], outputs=[text, proposal, use_proposal, said])
    with gr.Row():
        gr.Button('Save player description', variant='primary', scale=0, min_width=230).click(save_player, inputs=[text], outputs=[said, active])
        gr.Button('Optimize with AI', scale=0, min_width=160).click(optimize, inputs=[text], outputs=[proposal, use_proposal, said])
    with gr.Row():
        preset_name = gr.Textbox(show_label=False, placeholder='Name for your own preset, e.g. My Dragonborn', scale=3)
        gr.Button('Save as my preset', scale=0, min_width=160).click(save_preset, inputs=[preset_name, text], outputs=[preset, said]) \
            .then(lambda: active_player_html(config), outputs=[active])
        gr.Button('Reset player description', variant='stop', size='sm', elem_classes=['lw-danger'], scale=0, min_width=160).click(
            reset_player, inputs=[sure], outputs=[text, said],
            js=_confirm_js('Reset your player description to the default (Traveller)?')) \
            .then(lambda: (active_player_html(config), matching_preset(player_description(config), all_presets())), outputs=[active, preset])
    build_global(gr, game_fn, config)


def build_global(gr, game_fn, config=None):
    """What is left here for NPCs: Apply now and Reset ALL overrides. Each NPC's own bio, Background, Now and memories
    are on the NPCs page."""
    gr.HTML(ui_help.heading('NPC overrides', OVERRIDE_HELP, "Each NPC's bio, Background, Now and memories are on the "
                            "NPCs page. Here: load every saved override now, or reset them all."))
    said = gr.Markdown('')
    sure = gr.Checkbox(visible=False)

    def apply():
        return _notify(gr, 'Applied: the running Mantella uses your overrides from the next conversation.') if apply_now(game_fn()) else             "Mantella will read them at its next start (or press again after your first conversation this session)."

    def reset_every(ok, *_):
        if not ok:
            return 'Not reset.'
        count = reset_all(DEFAULT_OVERRIDES)
        request_reload(config)
        return _notify(gr, f"{count} override file(s) moved to character_overrides_removed. Every NPC uses Mantella's default from the next conversation.")
    with gr.Row():
        gr.Button('Apply now', scale=0, min_width=160).click(apply, outputs=[said])
        gr.Button('Reset ALL overrides', variant='stop', size='sm', elem_classes=['lw-danger'], scale=0, min_width=160).click(
            reset_every, inputs=[sure], outputs=[said],
            js=_confirm_js("Reset EVERY NPC override to Mantella's defaults? The files are moved to character_overrides_removed."))
    gr.HTML(ui_help.label('About resets', 'Reset never deletes: the files move to character_overrides_removed (next to your '
                          'overrides folder) in a dated folder, so you can put them back. The change applies from the next conversation.'))
    build_short_bios(gr, game_fn, sure)
    build_mod_facts(gr)
    build_speed_testing(gr)


SPEED_HELP = ("For measuring how long a talk takes to start. Stage times: the game writes timing_game.csv (talk key, "
              "each module's work when an NPC joins, the start request sent) and this side timing_backend.csv (request "
              "received, prompt built, first model token, first sentence, voice audio, lip file, line handed to the game, "
              "tokens), both in StorageUtilData/MantellaLivingWorld, joined by the talk number. Prepare NPC data ahead: the "
              "game fills an NPC's file when you aim at them, so a talk start only refreshes what changes from moment to "
              "moment. Both are off by default and take effect from the next NPC who joins a talk; no restart needed.")


def set_speed_testing(timing: bool, prepare: bool, settings_path: str | None = None) -> str:
    """Saves both switches and writes perf.json for the game side; the stage timers here switch at once."""
    from . import settings, stage_timing
    path = settings_path or settings.PATH
    values = settings.load(path)
    values.update(stage_timing=bool(timing), prepare_npc_data=bool(prepare))
    try:
        settings.save(path, values)
    except OSError:
        pass
    stage_timing.apply(bool(timing))
    if not stage_timing.settings_file(bool(timing), bool(prepare)):
        return 'Saved, but the game side could not be told (perf.json not written).'
    return (f"Stage times {'on' if timing else 'off'}, prepare ahead {'on' if prepare else 'off'}: "
            "from the next NPC who joins a talk.")


def build_speed_testing(gr):
    from . import settings
    values = settings.load()
    gr.Markdown('### Speed testing')
    gr.HTML(ui_help.label('About speed testing', SPEED_HELP))
    with gr.Row():
        timing = gr.Checkbox(label='Write stage times (debug)', value=bool(values.get('stage_timing')))
        prepare = gr.Checkbox(label='Prepare NPC data ahead', value=bool(values.get('prepare_npc_data')))
    said = gr.Markdown('')
    timing.change(set_speed_testing, inputs=[timing, prepare], outputs=[said], show_api=False)
    prepare.change(set_speed_testing, inputs=[timing, prepare], outputs=[said], show_api=False)


MOD_FACTS_HELP = ("Reads your installed plugins (Shadowman's NPCs and other dialogue mods) and writes one fact file per "
                  "plugin: what the mod records about an NPC and you (a quest stage, a global), with the mod's own lines as "
                  "evidence. It uses no AI and costs nothing: it only reads the plugin files on this PC. Files you write "
                  "yourself (modfacts\\user) and the ones that come with the Hub win over these. Skim the generated lines "
                  "once: a few quotes may be odd. Scanned files are used only with Use scanned mod facts on "
                  "(experimental, off by default); your own and the Hub's files always are. An NPC gets them from the next "
                  "time they join a talk.")


def mod_facts_where(values=None) -> dict:
    """The scan target from the settings; the Mod Organizer folder is found by itself when none is set."""
    from . import mod_facts_scan, settings
    values = values or settings.load()
    instance = values.get('mod_facts_mo2') or ''
    if not instance and not values.get('mod_facts_data'):
        instance = mod_facts_scan.find_instance()
    return mod_facts_scan.target(instance, values.get('mod_facts_data', ''), values.get('mod_facts_plugins', ''))


def scan_mod_facts(instance: str, data_dir: str = '', plugins_txt: str = '', wait: float = 0.5, settings_path: str | None = None):
    """The button: saves the folders, starts the scan in its own thread and yields progress, then the result table."""
    from . import mod_facts_scan, settings
    path = settings_path or settings.PATH
    values = settings.load(path)
    values.update(mod_facts_mo2=(instance or '').strip(), mod_facts_data=(data_dir or '').strip(),
                  mod_facts_plugins=(plugins_txt or '').strip())
    try:
        settings.save(path, values)
    except OSError:
        pass
    where = mod_facts_where(values)
    if where.get('error'):
        yield where['error']
        return
    if not mod_facts_scan.SCAN.start(where):
        yield 'A scan is already running.'
    while True:
        state = mod_facts_scan.SCAN.status()
        if not state['running']:
            break
        yield f"Scanning {where['where']}: plugin {state['done']} of {state['total'] or '?'} ({state['plugin']})..."
        time.sleep(wait)
    state = mod_facts_scan.SCAN.status()
    if state['error']:
        yield f"The scan stopped: {state['error']}"
        return
    yield f"Written to {state['out']} (only that folder is changed).\n\n" + mod_facts_scan.result_table(state['result'] or {})


def use_scanned_facts(on: bool, settings_path: str | None = None) -> str:
    """The switch: saved with the settings and written where the game side reads it (next to generated/)."""
    from . import mod_facts_scan, settings
    path = settings_path or settings.PATH
    values = settings.load(path)
    values['mod_facts_generated'] = bool(on)
    try:
        settings.save(path, values)
    except OSError:
        pass
    where = mod_facts_where(values)
    if where.get('error'):
        return f"Saved. {where['error']}"
    if not mod_facts_scan.set_use_generated(where['out'], bool(on)):
        return 'Saved, but the switch file for the game could not be written.'
    return ('Scanned facts are used from the next time an NPC joins a talk.' if on else
            'Scanned facts are not used (your own and the Hub\'s files still are).')


def last_scan_result() -> str:
    """The last scan's table (also after a restart): the page button and the lw_scan_result API."""
    from . import mod_facts_scan
    where = mod_facts_where()
    return mod_facts_scan.last_result(where.get('out', '')) or 'No scan has run yet.'


def build_mod_facts(gr):
    """Scan my dialogue mods: the Mod Organizer folder (or Data folder), the button, progress and the result."""
    from . import mod_facts_scan, settings
    gr.HTML(ui_help.heading('Facts from your dialogue mods', MOD_FACTS_HELP, 'Write fact files for your dialogue mods '
                            'from their own plugins. No AI, no cost.'))
    values = settings.load()
    found = values.get('mod_facts_mo2') or ('' if values.get('mod_facts_data') else mod_facts_scan.find_instance())
    with gr.Row():
        mo2 = gr.Textbox(label='Mod Organizer 2 folder (the one with ModOrganizer.ini)', value=found, scale=3,
                         placeholder='Not found by itself: paste your Mod Organizer 2 instance folder')
        data = gr.Textbox(label='Without Mod Organizer: game Data folder', value=values.get('mod_facts_data', ''), scale=2)
        plugins = gr.Textbox(label='plugins.txt (empty: the usual one)', value=values.get('mod_facts_plugins', ''), scale=2)
    said = gr.Markdown('' if found or values.get('mod_facts_data') else
                       'Mod Organizer 2 was not found by itself. Paste its folder, or your Data folder if you do not use it.')
    use = gr.Checkbox(label='Use scanned mod facts (experimental)', value=bool(values.get('mod_facts_generated')),
                      info='Off: only your own files and the ones that come with the Hub are used.')
    with gr.Row():
        gr.Button('Scan my dialogue mods', scale=0, min_width=240).click(scan_mod_facts, inputs=[mo2, data, plugins], outputs=[said],
                                                                         api_name='lw_scan_mod_facts')
        gr.Button('Show the last scan result', size='sm', scale=0, min_width=200).click(last_scan_result, outputs=[said],
                                                                                         api_name='lw_scan_result')
    use.change(use_scanned_facts, inputs=[use], outputs=[said], show_api=False)


SHORT_BIOS_HELP = ("Each long bio is rewritten once into a short sheet (Personality, Looks, Voice, History, Knows, Sample "
                   "lines) without what the Background facts already say, and sent instead of the original. Every result "
                   "is checked: no name or number the Background does not cover may be lost and nothing new added, else "
                   "the original is kept. This normally happens by itself after a talk; here you can do every override "
                   "now (one request per NPC). Your override files are not changed by that: the short bios are kept in "
                   "living_world_bios.json next to them. Write short bios into my override files is the only thing that "
                   "changes them, after copying them to a dated backup folder. Your overrides and the short bios stay on "
                   "this PC and are never part of the mod.")


def build_short_bios(gr, game_fn, sure):
    """Optimise all my overrides now (with progress and a summary) and Write short bios into my override files."""
    from . import bio_optimise
    gr.HTML(ui_help.heading('Short bios for your overrides', SHORT_BIOS_HELP, 'Shorten every override bio now, with a '
                            'summary. Each NPC page shows the original and the short version side by side.'))
    said = gr.Markdown('')

    def optimise_all(progress=gr.Progress()):
        def step(done, total, name):
            progress((done, total), desc=f"Short bio for {name}" if name else 'Done')
        from . import bio_evolve
        result = bio_optimise.optimise_overrides(DEFAULT_OVERRIDES, bio_optimise.pick_ask, bio_optimise.user_background, step,
                                                 wait=bio_evolve.busy)
        _notify(gr, f"Short bios: {result['shortened']} shortened, {len(result['kept'])} kept as they were.")
        return bio_optimise.summary_text(result)

    def write_all(ok, *_):
        if not ok:
            return 'Nothing written.'
        done = bio_optimise.write_into_overrides(DEFAULT_OVERRIDES)
        if not done['bios']:
            return 'No short bio to write (press Optimise all my overrides now first). Nothing was changed.'
        apply_now(game_fn())
        return _notify(gr, f"Wrote {done['bios']} short bio(s) into {done['files']} override file(s). The originals were "
                           f"copied to {done['backup']} first.")
    with gr.Row():
        gr.Button('Optimise all my overrides now', scale=0, min_width=240).click(
            optimise_all, outputs=[said], api_name='lw_optimise_overrides')
        gr.Button('Write short bios into my override files', variant='stop', size='sm', elem_classes=['lw-danger'], scale=0,
                  min_width=260).click(write_all, inputs=[sure], outputs=[said], show_api=False,
                                       js=_confirm_js('Write the short bios into your override files? Every override '
                                                      'file is copied to a dated backup folder next to them first.'))
