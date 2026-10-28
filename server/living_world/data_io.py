"""Export / import of the user's Living World data as one zip with a folder per part, so they can pick what to move:
  overrides/   NPC overrides            <user>/data/Skyrim/character_overrides
  player/      description + presets    (description set through Mantella's setting) + living_world_player_presets.json
  memory/<save>/  memories and Mantella's summaries of one save  <user>/data/Skyrim/conversations/<save>
  settings/    Living World settings    extensions/living_world/settings.json
  mantella/    Mantella's config.ini    (only when asked)
API key files are never exported. Import writes only the ticked parts and backs up every file it replaces."""
import os
import shutil
import time
import zipfile
from dataclasses import dataclass

PARTS = ('overrides', 'player', 'memory', 'settings', 'mantella_config')
PART_NAMES = {'overrides': 'NPC overrides', 'player': 'Player description and presets', 'memory': 'Memory and conversation summaries',
              'settings': 'Living World settings', 'mantella_config': "Mantella's config.ini"}
README = """Living World export
overrides/  NPC overrides (character_overrides)
player/     your player description and your own presets
memory/     one folder per save: Living World memories and Mantella's conversation summaries
settings/   Living World settings
mantella/   Mantella's config.ini (only if you ticked it)
Import it from Living World Prompt Rules and Settings > Import, ticking what you want. API keys are never included.
"""


@dataclass
class Paths:
    user: str           # Mantella's user folder (Documents/My Games/Mantella)
    hub_settings: str   # extensions/living_world/settings.json

    @property
    def overrides(self):
        return os.path.join(self.user, 'data', 'Skyrim', 'character_overrides')

    @property
    def presets(self):
        return os.path.join(self.user, 'data', 'Skyrim', 'living_world_player_presets.json')

    @property
    def conversations(self):
        return os.path.join(self.user, 'data', 'Skyrim', 'conversations')

    @property
    def config(self):
        return os.path.join(self.user, 'config.ini')


def _secret(name: str) -> bool:
    low = os.path.basename(name).lower()
    return 'secret_key' in low or low == 'secret_keys.json'


def _add_tree(z, folder, prefix):
    for root, _, files in os.walk(folder):
        for f in files:
            if _secret(f) or f.endswith('.tmp'):
                continue
            full = os.path.join(root, f)
            z.write(full, prefix + os.path.relpath(full, folder).replace('\\', '/'))


def export_zip(out_path, paths: Paths, parts, saves, player_description=None) -> str:
    """Writes the zip with the parts asked (memory: only the saves listed); returns its path."""
    with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('README.txt', README)
        if 'overrides' in parts and os.path.isdir(paths.overrides):
            _add_tree(z, paths.overrides, 'overrides/')
        if 'player' in parts:
            if player_description:
                z.writestr('player/description.txt', player_description)
            if os.path.isfile(paths.presets):
                z.write(paths.presets, 'player/living_world_player_presets.json')
        if 'memory' in parts:
            for save in saves or []:
                folder = os.path.join(paths.conversations, save)
                if os.path.isdir(folder):
                    _add_tree(z, folder, f'memory/{save}/')
        if 'settings' in parts and os.path.isfile(paths.hub_settings):
            z.write(paths.hub_settings, 'settings/living_world_settings.json')
        if 'mantella_config' in parts and os.path.isfile(paths.config):
            z.write(paths.config, 'mantella/config.ini')
    return out_path


TOP = {'overrides': 'overrides', 'player': 'player', 'memory': 'memory', 'settings': 'settings', 'mantella': 'mantella_config'}


def inspect_zip(path) -> dict:
    """{parts: [...], saves: [...]} found in the zip, or {error: ...}."""
    try:
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if not n.endswith('/')]
    except (OSError, zipfile.BadZipFile) as e:
        return {'error': f'Not a Living World export: {e}'}
    parts = sorted({TOP[n.split('/')[0]] for n in names if n.split('/')[0] in TOP})
    saves = sorted({n.split('/')[1] for n in names if n.startswith('memory/') and n.count('/') >= 2})
    return {'parts': parts, 'saves': saves}


def _target(name, paths: Paths, parts, saves):
    """Where one zip entry goes, or None (not ticked, unknown, unsafe or a key file)."""
    bits = name.split('/')
    if _secret(name) or any(b in ('', '.', '..') for b in bits[1:]) or ':' in name or name.startswith(('/', '\\')):
        return None
    top, rest = bits[0], bits[1:]
    if top == 'overrides' and 'overrides' in parts and rest:
        return os.path.join(paths.overrides, *rest)
    if top == 'player' and 'player' in parts and rest == ['living_world_player_presets.json']:
        return paths.presets
    if top == 'memory' and 'memory' in parts and len(rest) >= 2 and rest[0] in (saves or []):
        return os.path.join(paths.conversations, *rest)
    if top == 'settings' and 'settings' in parts and rest == ['living_world_settings.json']:
        return paths.hub_settings
    if top == 'mantella' and 'mantella_config' in parts and rest == ['config.ini']:
        return paths.config
    return None


def import_zip(path, paths: Paths, parts, saves, backup_root) -> dict:
    """Copies the ticked parts in. Every file it would replace is first copied to backup_root/<time>/ (keeping its
    place under the user folder). Returns {files, replaced, backup, player_description}; the description is handed
    back because it is set through Mantella's own setting, not a file."""
    report = {'files': 0, 'replaced': 0, 'backup': '', 'player_description': None}
    backup = os.path.join(backup_root, time.strftime('%Y%m%d-%H%M%S'))
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if name.endswith('/'):
                continue
            if name == 'player/description.txt' and 'player' in parts:
                report['player_description'] = z.read(name).decode('utf-8', 'replace').strip()
                continue
            target = _target(name, paths, parts, saves)
            if not target:
                continue
            if os.path.exists(target):
                keep = os.path.join(backup, name.replace('/', os.sep))
                os.makedirs(os.path.dirname(keep), exist_ok=True)
                shutil.copy2(target, keep)
                report['replaced'] += 1
                report['backup'] = backup
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(name) as src, open(target, 'wb') as dst:
                shutil.copyfileobj(src, dst)
            report['files'] += 1
    return report
