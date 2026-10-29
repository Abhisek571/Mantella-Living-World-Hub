"""Reads what the game side writes for Mantella: PapyrusUtil JSON under SKSE/Plugins/StorageUtilData/MantellaLivingWorld/.
Every reader returns an empty value on any problem (missing, half-written, not JSON), never an error."""
import json
import os
import re

BASE_ID = re.compile(r'^[0-9A-Fa-f]{1,8}$')


def default_data_dir() -> str:
    # Mantella runs with SKSE/Plugins/MantellaSoftware as its working folder
    return os.path.normpath(os.path.join(os.getcwd(), '..', 'StorageUtilData', 'MantellaLivingWorld'))


DATA_DIR = default_data_dir()


def decode(raw: bytes) -> str:
    """PapyrusUtil may write names in the game's codepage rather than UTF-8; either way the file stays readable."""
    try:
        return raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        return raw.decode('cp1252', errors='replace')


def _read(name: str) -> dict:
    try:
        with open(os.path.join(DATA_DIR, name), 'rb') as f:
            data = json.loads(decode(f.read()))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _flatten(data: dict) -> dict:
    """JsonUtil keeps values by type ({"int": {...}, "string": {...}, ...}); one dict is easier to use."""
    flat = {}
    for kind in ('int', 'float', 'string', 'form'):
        values = data.get(kind)
        if isinstance(values, dict):
            flat.update(values)
    return flat


def load_npc(base_id: str) -> dict:
    if not base_id or not BASE_ID.match(base_id):
        return {}
    data = _flatten(_read(os.path.join('npc', base_id.upper() + '.json')))
    if data:
        data['base_id'] = base_id.upper()
    return data


def load_world() -> dict:
    return _flatten(_read('world.json'))


def load_said_nearby() -> list[dict]:
    lines = _read('said_nearby.json').get('lines')
    return [line for line in lines if isinstance(line, dict)] if isinstance(lines, list) else []


def load_banter() -> dict:
    """Why World's banter or initiative started the current talk: {seed, active}."""
    return _flatten(_read('banter.json'))


def load_player_name() -> str:
    name = _flatten(_read('conversation.json')).get('player')
    return name if isinstance(name, str) else ''


def load_conversation() -> list[dict]:
    """Who is in the current Mantella conversation, each with their npc state. A speaker whose file is missing or
    broken is kept with no state, so the action filter treats them as a stranger instead of forgetting them."""
    ids = (_read('conversation.json').get('stringList') or {}).get('speakers')
    if not isinstance(ids, list):
        return []
    speakers = []
    for i in ids:
        base_id = str(i)
        if BASE_ID.match(base_id):
            speakers.append(load_npc(base_id) or {'base_id': base_id.upper()})
    return speakers


def jobs_text(speakers: list[dict]) -> str:
    """Missives board jobs the speakers posted ("job" in their file, written by Mantella Living World - Missives)."""
    blocks = []
    for s in speakers:
        job = s.get('job')
        if isinstance(job, str) and job.strip():
            name = s.get('name', '?')
            blocks.append(f"Job board notices {name} posted ({name} knows this):\n- {job.strip()}")
    return '\n\n'.join(blocks)
