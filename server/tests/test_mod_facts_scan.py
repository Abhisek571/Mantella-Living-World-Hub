"""Offline tests for the Scan my dialogue mods button: finding the Mod Organizer 2 folder, the folders an instance moves,
the non-MO2 Data folder, the button handler on a fake instance (writes only generated/), and that a scan running in its
thread never blocks the reply path.
Run with a Python 3.11: test_mod_facts_scan.py <repo server dir>"""
import json, os, shutil, sys, tempfile, threading, time
from pathlib import Path

SERVER = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(SERVER))
from living_world import mod_facts, mod_facts_gen as G, mod_facts_scan as S, npc_block, ui_overrides

GERDUR = os.path.join(os.environ.get('MLW_MO2', ''), 'mods', r'[NoDelete] Shadowmans NPCs 68 - Gerdur Handling Wood - Ostim Conversion and Redux\shadowman_gerdur.esp')
FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)[:700]) if not cond else ''))
    if not cond:
        FAILS.append(name)


def instance(root: Path, ini: str = '[General]\nselected_profile=@ByteArray(Default)\n') -> Path:
    (root / 'profiles' / 'Default').mkdir(parents=True)
    (root / 'ModOrganizer.ini').write_text(ini, encoding='utf-8')
    return root


def part_find(tmp: Path):
    inst = instance(tmp / 'inst')
    ext = inst / 'mods' / 'Mantella' / 'SKSE' / 'Plugins' / 'MantellaSoftware' / 'extensions' / 'living_world'
    ext.mkdir(parents=True)
    stock = inst / 'Stock Game' / 'Data' / 'SKSE' / 'Plugins' / 'MantellaSoftware'
    stock.mkdir(parents=True)
    old_env, old_cwd = os.environ.get('LOCALAPPDATA'), os.getcwd()
    os.environ['LOCALAPPDATA'] = str(tmp / 'nolocal')
    os.chdir(tmp)
    try:
        check('found from Mantella in a mod folder (<instance>\\mods\\<mod>\\...)', S.find_instance([str(ext)]) == str(inst))
        check('found from the game folder inside a portable instance (Stock Game)', S.find_instance([str(stock)]) == str(inst))
        (tmp / 'outside').mkdir()
        found = S.find_instance([str(tmp / 'outside')])
        check('not found: empty (then the box stays empty with one line of help)', found == '' or os.path.isfile(os.path.join(found, 'ModOrganizer.ini')), found)
        local = tmp / 'local' / 'ModOrganizer' / 'Skyrim'
        local.mkdir(parents=True)
        (local / 'ModOrganizer.ini').write_text('[General]\n', encoding='utf-8')
        os.environ['LOCALAPPDATA'] = str(tmp / 'local')
        check('...else the one instance under %LOCALAPPDATA%\\ModOrganizer', S.find_instance([str(tmp / 'outside')]) in (str(local), str(S.find_instance([]))))
    finally:
        os.chdir(old_cwd)
        if old_env is None:
            os.environ.pop('LOCALAPPDATA', None)
        else:
            os.environ['LOCALAPPDATA'] = old_env


def part_dirs(tmp: Path):
    inst = instance(tmp / 'moved', '[General]\nselected_profile=@ByteArray(Play)\n[Settings]\nmod_directory=%BASE_DIR%/MyMods\noverwrite_directory=E:/ow\n')
    (inst / 'profiles' / 'Play').mkdir()
    dirs = S.instance_dirs(str(inst))
    check("ModOrganizer.ini's own folders and the selected profile are used", dirs['mods'] == str(inst / 'MyMods').replace('/', os.sep)
          and dirs['overwrite'] == 'E:' + os.sep + 'ow' and dirs['profile'] == 'Play', dirs)
    plain = instance(tmp / 'plain')
    (plain / 'profiles' / 'Default' / 'plugins.txt').write_text('*a.esp\n', encoding='utf-8')
    where = S.target(str(plain))
    check('MO2: files go to <instance>\\overwrite\\SKSE\\Plugins\\StorageUtilData\\MantellaLivingWorld\\modfacts\\generated',
          where.get('out') == str(plain / 'overwrite' / 'SKSE' / 'Plugins' / 'StorageUtilData' / 'MantellaLivingWorld' / 'modfacts' / 'generated'), where)
    check('a folder with no ModOrganizer.ini is refused with a reason', 'No ModOrganizer.ini' in S.target(str(tmp)).get('error', ''))
    check('nothing set: one line of help', 'Set your Mod Organizer 2 folder' in S.target().get('error', ''))


def part_data(tmp: Path):
    data = tmp / 'Game' / 'Data'
    data.mkdir(parents=True)
    (data / 'mine.esp').write_bytes(b'TES4' + b'\0' * 20)
    txt = tmp / 'plugins.txt'
    txt.write_text('*Skyrim.esm\n*mine.esp\nnot_enabled.esp\n*missing.esp\n', encoding='utf-8')
    where = S.target('', str(data), str(txt))
    check('without MO2: the Data folder and its plugins.txt, files under Data\\SKSE\\...\\modfacts\\generated',
          where.get('kind') == 'data' and where['out'] == str(data / 'SKSE' / 'Plugins' / 'StorageUtilData' / 'MantellaLivingWorld' / 'modfacts' / 'generated'), where)
    got = [(p, bool(path)) for p, path, _, _ in where['sources']()]
    check('...only enabled plugins, the base game left out, a missing one marked', got == [('mine.esp', True), ('missing.esp', False)], got)
    check('...a missing plugins.txt is refused with a reason', 'No plugins.txt' in S.target('', str(data), str(tmp / 'none.txt')).get('error', ''))


def part_button(tmp: Path):
    if not os.path.isfile(GERDUR):
        return print('SKIP the Gerdur plugin is not on this PC (the button test copies it into a fake instance)')
    inst = instance(tmp / 'fake')
    mod = inst / 'mods' / 'Gerdur Handling Wood'
    mod.mkdir(parents=True)
    shutil.copy(GERDUR, mod / 'shadowman_gerdur.esp')
    (inst / 'mods' / 'Other').mkdir()
    (inst / 'profiles' / 'Default' / 'plugins.txt').write_text('*Skyrim.esm\n*shadowman_gerdur.esp\n*gone.esp\n', encoding='utf-8')
    (inst / 'profiles' / 'Default' / 'modlist.txt').write_text('+Gerdur Handling Wood\n+Other\n', encoding='utf-8')
    root = inst / 'overwrite' / 'SKSE' / 'Plugins' / 'StorageUtilData' / 'MantellaLivingWorld' / 'modfacts'
    for folder in ('user', 'shipped', 'generated'):
        (root / folder).mkdir(parents=True)
    (root / 'user' / 'mine.json').write_text('{"plugin": "x.esp", "keep": 1}', encoding='utf-8')
    (root / 'shipped' / 'ship.json').write_text('{"plugin": "y.esp", "keep": 2}', encoding='utf-8')
    (root / 'generated' / 'stale.esp.json').write_text('{"plugin": "stale.esp", "source": "generated"}', encoding='utf-8')
    (root / 'generated' / 'by_hand.json').write_text('{"plugin": "z.esp", "source": "hand"}', encoding='utf-8')
    setting = tmp / 'settings.json'
    out = list(ui_overrides.scan_mod_facts(str(inst), wait=0.05, settings_path=str(setting)))
    final = out[-1]
    check('the button: progress lines, then where it wrote and the result table', len(out) >= 1 and final.startswith('Written to ')
          and '| shadowman_gerdur.esp | 1 | 1 |' in final and '| gone.esp | not found |' in final, out)
    made = json.load(open(root / 'generated' / 'shadowman_gerdur.esp.json', encoding='utf-8'))
    check('...the file is in generated/ and reads as a fact file', M_ok(made), made.get('plugin'))
    check('...user/ and shipped/ untouched, an old generated file replaced, a hand file in generated/ kept',
          (root / 'user' / 'mine.json').read_text(encoding='utf-8') == '{"plugin": "x.esp", "keep": 1}'
          and (root / 'shipped' / 'ship.json').read_text(encoding='utf-8') == '{"plugin": "y.esp", "keep": 2}'
          and not (root / 'generated' / 'stale.esp.json').exists() and (root / 'generated' / 'by_hand.json').exists())
    check('...the folder is saved with the settings', json.load(open(setting, encoding='utf-8')).get('mod_facts_mo2') == str(inst))
    files = S.preview('01347C', str(root / 'generated'))
    check("the NPC page's preview finds the scan's file for Gerdur at once (before the game has read it)",
          files and files[0][1] == 'generated' and 'gerdurfuckedstate' in files[0][2][1], files)


def M_ok(data) -> bool:
    return mod_facts.clean_file(data) is not None


def part_not_blocking(tmp: Path):
    gate = threading.Event()

    def slow_sources():
        gate.wait(3)  # a long scan
        return []
    where = {'out': str(tmp / 'slow' / 'generated'), 'sources': slow_sources, 'where': 'test'}
    check('a scan starts in its own thread', S.SCAN.start(where))
    check('...a second one is refused while it runs', not S.SCAN.start(where))
    speaker = {'name': 'Gerdur', 'ref_id': '0001347C', 'base_id': '01347C', 'modfact_1': 'M|Gerdur knows {player}.'}
    start = time.time()
    for _ in range(50):
        npc_block.npc_text(None, speaker, [('Gerdur', '01347C')], 'Brom', bio_changes=False)
    took = time.time() - start
    check(f'...while it runs, building the NPC part of a reply is not held up ({took:.3f} s for 50)', took < 1.0 and S.SCAN.status()['running'])
    gate.set()
    for _ in range(60):
        if not S.SCAN.status()['running']:
            break
        time.sleep(0.05)
    check('...and it finishes on its own', not S.SCAN.status()['running'] and S.SCAN.status()['error'] == '')


with tempfile.TemporaryDirectory() as tmp:
    for name, part in (('find', part_find), ('dirs', part_dirs), ('data', part_data), ('button', part_button), ('not blocking', part_not_blocking)):
        try:
            sub = Path(tmp) / name
            sub.mkdir()
            part(sub)
        except Exception as e:
            import traceback
            traceback.print_exc()
            check(f'part {name} ran without an error', False, e)

print(f"\n{len(FAILS)} failure(s)" if FAILS else '\nall passed')
sys.exit(1 if FAILS else 0)
