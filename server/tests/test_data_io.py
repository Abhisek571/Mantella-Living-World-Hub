"""Offline tests for Living World export / import (server/living_world/data_io.py).
Run with a Python 3.11: test_data_io.py <repo server dir>"""
import json, sys, tempfile, zipfile
from pathlib import Path

SERVER = Path(sys.argv[1])
sys.path.insert(0, str(SERVER))
from living_world import data_io as D

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)) if not cond else ''))
    if not cond:
        FAILS.append(name)


def tree(root: Path) -> dict:
    return {str(p.relative_to(root)).replace('\\', '/'): p.read_text(encoding='utf-8') for p in sorted(root.rglob('*')) if p.is_file()}


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    src = tmp / 'src'
    (src / 'data/Skyrim/character_overrides').mkdir(parents=True)
    (src / 'data/Skyrim/character_overrides/Lydia.json').write_text('{"name": "Lydia"}', encoding='utf-8')
    (src / 'data/Skyrim/conversations/Player1/living_world').mkdir(parents=True)
    (src / 'data/Skyrim/conversations/Player1/living_world/Lydia - 0A2C94.json').write_text('{"recent": []}', encoding='utf-8')
    (src / 'data/Skyrim/conversations/Player1/Lydia - 0A2C94').mkdir()
    (src / 'data/Skyrim/conversations/Player1/Lydia - 0A2C94/Lydia_summary_1.txt').write_text('Sworn.', encoding='utf-8')
    (src / 'data/Skyrim/conversations/OTHER2').mkdir()
    (src / 'data/Skyrim/conversations/OTHER2/a.txt').write_text('other save', encoding='utf-8')
    (src / 'data/Skyrim/living_world_player_presets.json').write_text('{"Mine": "x"}', encoding='utf-8')
    (src / 'config.ini').write_text('[Game]\n', encoding='utf-8')
    (src / 'ANTHROPIC_SECRET_KEY.txt').write_text('sk-secret', encoding='utf-8')
    hub_settings = tmp / 'settings.json'
    hub_settings.write_text('{"memory_budget": 900}', encoding='utf-8')
    paths = D.Paths(user=str(src), hub_settings=str(hub_settings))

    zpath = D.export_zip(str(tmp / 'out.zip'), paths, parts={'overrides', 'player', 'memory', 'settings'}, saves=['Player1'],
                         player_description='A tall Nord.')
    names = zipfile.ZipFile(zpath).namelist()
    check('folders per part', any(n.startswith('overrides/') for n in names) and any(n.startswith('memory/Player1/') for n in names)
          and 'player/description.txt' in names and 'settings/living_world_settings.json' in names, names)
    check('only the saves asked', not any('OTHER2' in n for n in names), names)
    check('Mantella config only when asked', not any(n.endswith('config.ini') for n in names))
    check('never a key file', not any('SECRET' in n.upper() for n in names))
    check('a readme says what is inside', 'README.txt' in names)
    with_cfg = zipfile.ZipFile(D.export_zip(str(tmp / 'out2.zip'), paths, parts={'mantella_config'}, saves=[])).namelist()
    check('Mantella config when asked', 'mantella/config.ini' in with_cfg and not any('SECRET' in n.upper() for n in with_cfg), with_cfg)

    # test_inspect: the import shows what the zip holds, to tick
    found = D.inspect_zip(zpath)
    check('inspect: parts and saves', found['parts'] == ['memory', 'overrides', 'player', 'settings'] and found['saves'] == ['Player1'], found)

    # test_import_selected: only what is ticked comes in; anything replaced is backed up first
    dst = tmp / 'dst'
    (dst / 'data/Skyrim/character_overrides').mkdir(parents=True)
    (dst / 'data/Skyrim/character_overrides/Lydia.json').write_text('{"name": "old Lydia"}', encoding='utf-8')
    dpaths = D.Paths(user=str(dst), hub_settings=str(tmp / 'dst_settings.json'))
    report = D.import_zip(zpath, dpaths, parts={'overrides'}, saves=[], backup_root=str(tmp / 'backup'))
    got = tree(dst)
    check('overrides imported', got.get('data/Skyrim/character_overrides/Lydia.json') == '{"name": "Lydia"}', got)
    check('nothing else imported', not any('conversations' in k for k in got) and not (tmp / 'dst_settings.json').exists(), got)
    check('replaced file backed up', any(p.read_text(encoding='utf-8') == '{"name": "old Lydia"}' for p in (tmp / 'backup').rglob('Lydia.json')))
    check('report counts', report['files'] == 1 and report['replaced'] == 1, report)
    report = D.import_zip(zpath, dpaths, parts={'memory', 'player', 'settings'}, saves=['Player1'], backup_root=str(tmp / 'backup'))
    got = tree(dst)
    check('memory per save imported', got.get('data/Skyrim/conversations/Player1/Lydia - 0A2C94/Lydia_summary_1.txt') == 'Sworn.', got)
    check('presets and settings imported', 'data/Skyrim/living_world_player_presets.json' in got and json.loads((tmp / 'dst_settings.json').read_text())['memory_budget'] == 900)
    check('player description handed back to set through Mantella', report['player_description'] == 'A tall Nord.', report)

    # test_unsafe_zip: paths that climb out of the folder are skipped
    bad = tmp / 'bad.zip'
    with zipfile.ZipFile(bad, 'w') as z:
        z.writestr('overrides/../../evil.json', 'x')
        z.writestr('overrides/ok.json', '{}')
    D.import_zip(str(bad), dpaths, parts={'overrides'}, saves=[], backup_root=str(tmp / 'backup'))
    check('no file written outside', not (tmp / 'evil.json').exists() and not (dst / 'evil.json').exists())
    check('safe file still imported', (dst / 'data/Skyrim/character_overrides/ok.json').exists())
    check('not a zip: reported, not raised', 'error' in D.inspect_zip(str(hub_settings)))

print('RESULT: ' + ('ALL PASS' if not FAILS else f'{len(FAILS)} FAILED: {FAILS}'))
sys.exit(1 if FAILS else 0)
