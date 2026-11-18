"""The "Scan my dialogue mods" button: where the game's plugins are, where generated fact files go, and the scan run
in a background thread (mod_facts_gen does the reading; nothing is sent anywhere and no request is made).

Mod Organizer 2: the instance folder (the one holding ModOrganizer.ini). It is found by walking up from where this
extension runs (Mantella under <instance>\\mods\\<mod>\\..., or the game folder inside a portable instance, as the
Stock Game folder of a Wabbajack list is), then from the working folder, then the one instance under
%LOCALAPPDATA%\\ModOrganizer. Generated files go to the instance's overwrite folder:
<overwrite>\\SKSE\\Plugins\\StorageUtilData\\MantellaLivingWorld\\modfacts\\generated, which the game sees as
Data\\SKSE\\Plugins\\StorageUtilData\\MantellaLivingWorld\\modfacts\\generated, where the game side reads them.
Without Mod Organizer: the game's Data folder and its plugins.txt (%LOCALAPPDATA%\\Skyrim Special Edition\\plugins.txt
unless given); files go to Data\\SKSE\\Plugins\\StorageUtilData\\MantellaLivingWorld\\modfacts\\generated."""
import configparser
import glob
import json
import os
import threading
import time

from . import lw_state, mod_facts, mod_facts_gen

RELATIVE = os.path.join('SKSE', 'Plugins', 'StorageUtilData', 'MantellaLivingWorld', 'modfacts')


def find_instance(starts=None) -> str:
    """The MO2 instance folder, '' when none is found."""
    here = os.path.dirname(os.path.abspath(__file__))
    for start in list(starts or []) + [here, os.getcwd()]:
        path = os.path.abspath(start or '')
        for _ in range(12):
            if os.path.isfile(os.path.join(path, 'ModOrganizer.ini')):
                return path
            parent = os.path.dirname(path)
            if parent == path:
                break
            path = parent
    local = os.environ.get('LOCALAPPDATA', '')
    found = glob.glob(os.path.join(local, 'ModOrganizer', '*', 'ModOrganizer.ini')) if local else []
    return os.path.dirname(found[0]) if len(found) == 1 else ''


def instance_dirs(instance: str) -> dict:
    """{'mods', 'overwrite', 'profiles'} of an instance, from ModOrganizer.ini's [Settings] when it moves them."""
    out = {'mods': os.path.join(instance, 'mods'), 'overwrite': os.path.join(instance, 'overwrite'),
           'profiles': os.path.join(instance, 'profiles'), 'profile': 'Default'}
    parser = configparser.RawConfigParser(strict=False)
    try:
        parser.read(os.path.join(instance, 'ModOrganizer.ini'), encoding='utf-8')
    except (configparser.Error, OSError, UnicodeDecodeError):
        return out
    get = lambda section, key: parser.get(section, key, fallback='').strip().strip('"')
    base = get('Settings', 'base_directory').replace('%BASE_DIR%', instance) or instance
    for key, setting in (('mods', 'mod_directory'), ('overwrite', 'overwrite_directory'), ('profiles', 'profiles_directory')):
        value = get('Settings', setting).replace('%BASE_DIR%', base)
        out[key] = value.replace('/', os.sep) if value else os.path.join(base, key)
    profile = get('General', 'selected_profile')
    if profile.startswith('@ByteArray(') and profile.endswith(')'):
        profile = profile[len('@ByteArray('):-1]
    if profile and os.path.isdir(os.path.join(out['profiles'], profile)):
        out['profile'] = profile
    return out


def target(instance: str = '', data_dir: str = '', plugins_txt: str = '') -> dict:
    """Where to scan and write: {'kind': 'mo2' | 'data', 'out', 'sources' (a function), 'where'} or {'error'}."""
    if instance:
        if not os.path.isfile(os.path.join(instance, 'ModOrganizer.ini')):
            return {'error': f"No ModOrganizer.ini in {instance}."}
        dirs = instance_dirs(instance)
        if not os.path.isfile(os.path.join(dirs['profiles'], dirs['profile'], 'plugins.txt')):
            return {'error': f"No plugins.txt for the profile {dirs['profile']} in {dirs['profiles']}."}
        out = os.path.join(dirs['overwrite'], RELATIVE, 'generated')

        def sources():
            return mod_facts_gen.sources_mo2(instance, dirs['profile'], _game_data(instance), dirs['mods'], dirs['profiles'])
        return {'kind': 'mo2', 'out': out, 'sources': sources, 'where': f"Mod Organizer 2 profile {dirs['profile']} in {instance}"}
    if data_dir:
        plugins_txt = plugins_txt or os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Skyrim Special Edition', 'plugins.txt')
        if not os.path.isdir(data_dir):
            return {'error': f"No folder {data_dir}."}
        if not os.path.isfile(plugins_txt):
            return {'error': f"No plugins.txt at {plugins_txt}."}
        return {'kind': 'data', 'out': os.path.join(data_dir, RELATIVE, 'generated'),
                'sources': lambda: mod_facts_gen.sources_data(data_dir, plugins_txt), 'where': f"the Data folder {data_dir}"}
    return {'error': 'Set your Mod Organizer 2 folder (or, without Mod Organizer, your game\'s Data folder) first.'}


def _game_data(instance: str) -> str | None:
    """The game's Data folder of an instance (gamePath in ModOrganizer.ini), for plugins no mod provides."""
    parser = configparser.RawConfigParser(strict=False)
    try:
        parser.read(os.path.join(instance, 'ModOrganizer.ini'), encoding='utf-8')
        game = parser.get('General', 'gamePath', fallback='').strip()
    except (configparser.Error, OSError, UnicodeDecodeError):
        return None
    if game.startswith('@ByteArray(') and game.endswith(')'):
        game = game[len('@ByteArray('):-1]
    game = game.replace('\\\\', '\\').replace('/', os.sep)
    return os.path.join(game, 'Data') if game and os.path.isdir(os.path.join(game, 'Data')) else None


class Scan:
    """One scan at a time, in its own thread; the page reads status() while it runs."""

    def __init__(self):
        self._lock = threading.Lock()
        self._state = {'running': False, 'done': 0, 'total': 0, 'plugin': '', 'result': None, 'error': '', 'out': ''}

    def status(self) -> dict:
        with self._lock:
            return dict(self._state)

    def start(self, where: dict) -> bool:
        """Starts a scan of where (target()); False when one is already running."""
        with self._lock:
            if self._state['running']:
                return False
            self._state = {'running': True, 'done': 0, 'total': 0, 'plugin': '', 'result': None, 'error': '', 'out': where.get('out', '')}
        threading.Thread(target=self._run, args=(where,), daemon=True, name='lw-modfacts-scan').start()
        return True

    def _step(self, done, total, plugin):
        with self._lock:
            self._state.update(done=done, total=total, plugin=plugin)

    def _run(self, where):
        try:
            drafts = mod_facts_gen.generate_from(where['sources'](), step=self._step)
            written = mod_facts_gen.write(drafts, where['out'])
            result = {'drafts': drafts, 'written': written}
            save_last(where['out'], result)
            with self._lock:
                self._state.update(result=result)
        except Exception as e:  # a scan error must never reach the talk
            with self._lock:
                self._state.update(error=str(e))
        finally:
            with self._lock:
                self._state['running'] = False


SCAN = Scan()


def result_table(result: dict) -> str:
    """Markdown: the plugins with facts (NPCs, facts), then those with dialogue that gave none and why, then counts."""
    drafts = result.get('drafts') or {}
    found = [(p, d) for p, d in drafts.items() if isinstance(d, dict)]
    rows = ['| Plugin | NPCs | Facts |', '|---|---|---|']
    rows += [f"| {p} | {len(d['npcs'])} | {sum(len(n['facts']) for n in d['npcs'])} |" for p, d in found]
    skipped = [(p, r) for p, r in drafts.items() if isinstance(r, str) and r != 'no dialogue']
    text = '\n'.join(rows) if found else 'No plugin gave any fact.'
    if skipped:
        text += '\n\n| Skipped plugin | Why |\n|---|---|\n' + '\n'.join(f"| {p} | {r} |" for p, r in skipped)
    quiet = sum(1 for r in drafts.values() if r == 'no dialogue')
    npcs = sum(len(d['npcs']) for _, d in found)
    return text + f"\n\n{len(found)} file(s) written, {npcs} NPC(s) get facts; {quiet} plugin(s) have no dialogue."


def preview(base_id: str, out_dir: str) -> list[tuple[str, str, list[str]]]:
    """(mod, folder, lines) of the fact files next to out_dir (user, shipped there, generated) naming this NPC by its
    base id: what the game reads for them from their next talk (which line depends on the game's values then)."""
    if not base_id or not out_dir:
        return []
    try:
        number = int(str(base_id), 16) & 0xFFFFFF
    except ValueError:
        return []
    out = []
    for data in mod_facts.load_folder(os.path.dirname(out_dir)).values():
        for npc in data['npcs']:
            ref = mod_facts.form_ref(npc['npc'])
            if ref and (ref[1] == number or (ref[1] <= 0xFFF and ref[1] == number & 0xFFF)):
                out.append((data['mod'], data['folder'], [l['text'] for f in npc['facts'] for l in f['lines']]))
    return out


LAST = 'last_scan.md'  # next to generated/: the last scan's table, for the page and the API after a restart


def save_last(out_dir: str, result: dict) -> None:
    try:
        with open(os.path.join(os.path.dirname(out_dir), LAST), 'w', encoding='utf-8') as f:
            f.write(f"Last scan: {time.strftime('%Y-%m-%d %H:%M')}, written to {out_dir}\n\n" + result_table(result))
    except OSError:
        pass


def last_result(out_dir: str) -> str:
    """The last scan's table (this session's run, else the one saved next to generated/), '' when there is none."""
    state = SCAN.status()
    if state.get('running'):
        return f"A scan is running: plugin {state['done']} of {state['total'] or '?'} ({state['plugin']})."
    try:
        with open(os.path.join(os.path.dirname(out_dir), LAST), encoding='utf-8') as f:
            return f.read()
    except OSError:
        return ''


USE_FLAG = 'use_generated.json'  # the game side reads scanned files only while this says on (the Hub's setting)


def set_use_generated(out_dir: str, on: bool) -> bool:
    """Writes the switch the game side reads (PapyrusUtil's shape), in one step; False when it could not be written."""
    try:
        root = os.path.dirname(out_dir)
        os.makedirs(root, exist_ok=True)
        path = os.path.join(root, USE_FLAG)
        temp = lw_state.temp_path(path)
        with open(temp, 'w', encoding='utf-8') as f:
            json.dump({'int': {'on': 1 if on else 0}}, f)
        lw_state.replace_file(temp, path)
        return True
    except OSError:
        return False
