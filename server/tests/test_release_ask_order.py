"""Offline test: releasing an absolute command (release.py) hands the Now paragraph writer (bio_evolve) an asker in
the order it calls it, ask(text, prompt), while the callers pass ask(prompt, text) (the summary call, the page's
model asker).
Run with a Python 3.11: test_release_ask_order.py <repo server dir>"""
import json, os, sys, tempfile
from pathlib import Path

SERVER = Path(sys.argv[1])
sys.path.insert(0, str(SERVER))
import living_world
from living_world import bio_evolve as B, command, contracts, embed, lw_state, memory, release as R
memory.SUMMARY_RETRY_SECONDS = 0
embed.use(None)

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)) if not cond else ''))
    if not cond:
        FAILS.append(name)


def write_channel(name, data):
    with open(os.path.join(lw_state.DATA_DIR, name), 'w', encoding='utf-8') as f:
        json.dump(data, f)


SIGRID = {'name': 'Sigrid', 'ref_id': '00013BA1', 'base_id': '013BA1', 'race': 'Nord', 'sex': 'female', 'minor': 0}

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    lw_state.DATA_DIR = str(tmp / 'channel')
    os.makedirs(lw_state.DATA_DIR)
    write_channel('conversation.json', {'string': {'player': 'Inga'}, 'int': {'day': 40}})
    store = memory.MemoryStore(str(tmp / 'conversations'), 'P1')
    write_channel('commands.json', {'stringList': {'key': ['41.6-1'], 'text': ['Follow me'], 'refs': ['00013BA1'],
                                                   'names': ['Sigrid'], 'time': ['41.6'], 'player': ['Inga']}})
    command.poll(store, [('Sigrid', '013BA1')], {'command_hours': 0, 'command_model_check': False, 'command_forget_limit': 3},
                 None, living_world._ref, 41, 'Inga', [SIGRID], background=False)
    rec = command.load(store)['commands'][0]

    handed = []
    original = B.write_now
    B.write_now = lambda store_, people, ask, language='English', **kw: handed.append(ask) or list(people)
    calls = []
    def caller_ask(prompt, text):  # the shape __init__._commands and ui_overrides.model_asker pass
        calls.append((prompt, text))
        return 'reply'
    try:
        out = R.release_command(store, rec['id'], 'spell', player='Inga', today=43, speakers=[SIGRID], ask=caller_ask)
    finally:
        B.write_now = original
    check('release ok', out.get('ok'), out)
    check('the Now writer is handed an asker', len(handed) == 1, handed)
    if handed:
        reply = handed[0]('THE TEXT', 'THE PROMPT')  # bio_evolve.write calls ask(text, prompt)
        check('the caller gets (prompt, text), not swapped', calls == [('THE PROMPT', 'THE TEXT')], calls)
        check("the caller's reply comes back", reply == 'reply', reply)

    # REL-2: a request row never names the display fallback "the player"; an unknown name is '' (any character)
    write_channel('conversation.json', {'int': {'day': 40}})
    write_channel('commands.json', {'stringList': {'key': ['44.6-1'], 'text': ['Marry me'], 'refs': ['00013BA1'],
                                                   'names': ['Sigrid'], 'time': ['44.6'], 'player': ['']}})
    command.poll(store, [('Sigrid', '013BA1')], {'command_hours': 0, 'command_model_check': False, 'command_forget_limit': 3},
                 None, living_world._ref, 44, '', [SIGRID], background=False)
    rec = next((c for c in command.load(store)['commands'] if c['text'] == 'Marry me'), None)
    check('a second command to release', rec is not None, command.load(store))
    if rec is not None:
        original_under = R.marriage_under
        R.marriage_under = lambda record, n, speaker: {'base': '013BA1', 'name': 'Sigrid'}
        try:
            out = R.release_command(store, rec['id'], 'spell', end_marriage=True, player='', today=45, speakers=[SIGRID])
        finally:
            R.marriage_under = original_under
        rows = contracts.load_requests()
        check('release with no known player name ok, one request', out.get('ok') and len(rows) == 1, (out, rows))
        check("the request row's player is '' (not 'the player')", bool(rows) and rows[0].get('player') == '', rows)

print(f"\n{len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
