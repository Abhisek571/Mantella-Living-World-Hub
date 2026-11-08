"""Offline tests for the bug report's server side and the game-side channel writes.
Run with a Python 3.11: test_server_status.py <repo server dir>"""
import json, logging, sys, tempfile
from pathlib import Path

SERVER = Path(sys.argv[1])
sys.path.insert(0, str(SERVER))
from living_world import lw_state, server_status

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)) if not cond else ''))
    if not cond:
        FAILS.append(name)

with tempfile.TemporaryDirectory() as tmp:
    lw_state.DATA_DIR = str(Path(tmp) / 'channel')
    versions = Path(tmp) / 'versions'
    versions.mkdir()
    (versions / 'hub.json').write_text(json.dumps({'module': 'Integration Hub', 'version': '1.2.0', 'nexus_id': 1}), encoding='utf-8')
    report = lambda: json.loads((Path(lw_state.DATA_DIR) / server_status.FILE).read_text(encoding='utf-8'))['stringList']

    server_status.write([], str(versions))
    check('versions written', report()['versions'] == ['Integration Hub 1.2.0'], report())
    check('no warnings yet', report()['errors'] == [])

    log = logging.getLogger('status-test')
    log.propagate = False
    handler = server_status.RecentWarnings(str(versions))
    log.addHandler(handler)
    log.warning('Something else entirely')
    check('other warnings are left out', not handler.lines)
    log.info('Living World: only information')
    check('information is left out', not handler.lines)
    for i in range(15):
        log.warning(f'Living World: problem {i}')
    check('only the last ten kept', report()['errors'][0] == 'Living World: problem 5' and len(report()['errors']) == 10, report())
    log.warning('Living World: ' + 'x' * 500)
    check('long warnings cut', len(report()['errors'][-1]) == server_status.MAX_CHARS)
    log.warning("Extension 'living_world' failed in memory_text: boom")  # how Mantella logs a hook of ours that raised
    check('a hook of ours that raised is kept', report()['errors'][-1].endswith('failed in memory_text: boom'), report())
    log.warning("Extension 'lw_knowledge' failed in memory_text: boom")
    check("another extension's failure is left out", 'lw_knowledge' not in report()['errors'][-1], report())

    weights = {'talk': 1, 'deeds': 3, 'care': 2, 'gifts': 2, 'physical': 1}
    lw_state.write_profile('000A2C94', weights)
    profiles = json.loads((Path(lw_state.DATA_DIR) / lw_state.PROFILES).read_text(encoding='utf-8'))['int']
    check('profile keys lowercase for the game', profiles['000a2c94_deeds'] == 3, profiles)
    lw_state.write_profile('ABC', weights)
    profiles = json.loads((Path(lw_state.DATA_DIR) / lw_state.PROFILES).read_text(encoding='utf-8'))['int']
    check('other NPCs are kept', '000a2c94_deeds' in profiles and 'abc_talk' in profiles)
    lw_state.write_profile('../nope', weights)
    lw_state.write_profile('', weights)
    check('a bad id writes nothing', not any('nope' in k for k in json.loads((Path(lw_state.DATA_DIR) / lw_state.PROFILES).read_text(encoding='utf-8'))['int']))

print('RESULT: ' + ('ALL PASS' if not FAILS else f'{len(FAILS)} FAILED: {FAILS}'))
sys.exit(1 if FAILS else 0)
