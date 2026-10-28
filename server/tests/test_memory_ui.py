"""Offline tests for the Living World Memory tab logic (server/living_world/memory_ui.py): edit memories as tables.
Run with a Python 3.11: test_memory_ui.py <repo server dir>"""
import csv, json, sys, tempfile
from pathlib import Path

SERVER = Path(sys.argv[1])
sys.path.insert(0, str(SERVER))
from living_world import memory, memory_ui as M

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)) if not cond else ''))
    if not cond:
        FAILS.append(name)


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    conv = tmp / 'conversations'
    store = memory.MemoryStore(str(conv), 'CHAD1')
    store.save('Faendal', '01348C', {'recent': [{'day': 3, 'hour': 9, 'text': 'CHAD helped me with Sven.', 'witnesses': ['Faendal']}],
                                    'long_term': {'earlier': 'We met in Riverwood.'}, 'feeling': 'Grateful.', 'asked': {'x': 1}})
    key = store.save_shared({'day': 4, 'hour': 20, 'text': 'We drank at the Sleeping Giant.', 'witnesses': ['Faendal', 'Vega']})
    data = store.load('Faendal', '01348C')
    data['recent'].append({'day': 4, 'hour': 20, 'shared': key, 'witnesses': ['Faendal', 'Vega']})
    store.save('Faendal', '01348C', data)
    (conv / 'CHAD1' / 'Lydia - 0A2C94').mkdir(parents=True)  # Mantella's own summary folder, no Living World file yet
    (conv / 'CHAD1' / 'Lydia - 0A2C94' / 'Lydia_summary_1.txt').write_text('Lydia swore to carry burdens.', encoding='utf-8')
    (conv / 'OTHER2').mkdir()
    base = tmp / 'c.csv'
    with open(base, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['name', 'race', 'ref_id', 'base_id', 'bio'])
        w.writeheader()
        w.writerow({'name': 'Hadvar', 'race': 'Nord', 'ref_id': '02BFA1', 'base_id': '02BF9F', 'bio': ''})
        w.writerow({'name': 'Faendal', 'race': 'Bosmer', 'ref_id': '01348C', 'base_id': '01348C', 'bio': ''})
        w.writerow({'name': 'Nobody', 'race': 'Nord', 'ref_id': '', 'base_id': '1', 'bio': ''})

    check('saves listed', M.saves(str(conv)) == ['CHAD1', 'OTHER2'], M.saves(str(conv)))
    people = M.people(str(conv), 'CHAD1', str(base))
    labels = [p['label'] for p in people]
    check('NPCs with memories first, tagged', labels[0].startswith('Faendal') and 'memories' in labels[0] and any(l.startswith('Lydia') and 'memories' in l for l in labels[:2]), labels)
    check('anyone with an id can get a new memory', any(l.startswith('Hadvar') and 'memories' not in l for l in labels), labels)
    check('no id, no entry (Mantella files memories by id)', not any(l.startswith('Nobody') for l in labels))
    check('no duplicate for an NPC that has memories', sum(l.startswith('Faendal') for l in labels) == 1, labels)

    # test_status_first: readable summary of what they remember
    st = M.status_text(store.load('Faendal', '01348C'), 'Faendal')
    check('status: feeling, count and newest', 'Grateful.' in st and '2 memories' in st and 'Sleeping Giant' in st, st)
    check('status for nobody yet', 'no memories' in M.status_text(memory.empty(), 'Hadvar').lower())

    # test_tables_round_trip: tables in, same memory out; editing a shared memory makes it this NPC's own
    feeling, recent, long_term = M.to_tables(store.load('Faendal', '01348C'))
    check('recent as rows', recent == [[3, 9, 'CHAD helped me with Sven.'], [4, 20, 'We drank at the Sleeping Giant.']], recent)
    check('long-term as rows', long_term == [['earlier', 'We met in Riverwood.']], long_term)
    current = store.load('Faendal', '01348C')
    same = M.from_tables(current, feeling, recent, long_term)
    check('unchanged tables keep shared links and asked', same['recent'][1].get('shared') == key and same['asked'] == {'x': 1}, same)
    edited = M.from_tables(current, 'Fond of CHAD.', [[3, 9, 'CHAD helped me with Sven.'], ['4', '20', 'We drank and sang.'], ['', '', ''], [5, 'x', 'New one.']], [['earlier', 'We met.'], ['', '']])
    check('edited shared memory becomes own text', 'shared' not in edited['recent'][1] and edited['recent'][1]['text'] == 'We drank and sang.', edited['recent'])
    check('blank rows dropped, bad numbers cleaned', len(edited['recent']) == 3 and edited['recent'][2] == {'day': 5, 'hour': -1, 'text': 'New one.'}, edited['recent'])
    check('feeling and long-term from the tables', edited['feeling'] == 'Fond of CHAD.' and edited['long_term'] == {'earlier': 'We met.'}, edited)
    check('shared file untouched for the others', store.shared_text(key) == 'We drank at the Sleeping Giant.')

    # test_reset_memory: moved to a backup, never deleted
    backups = tmp / 'removed'
    check('reset memory', M.reset_memory(store, 'Faendal', '01348C', str(backups)))
    check('file gone from memory', not (conv / 'CHAD1' / 'living_world' / 'Faendal - 01348C.json').exists())
    check('kept in backup', any(p.name == 'Faendal - 01348C.json' for p in backups.rglob('*.json')))
    check('reset with nothing there', not M.reset_memory(store, 'Hadvar', '02BFA1', str(backups)))

# test_plain_words: the model turns the user's notes into memory rows (NPC's point of view) and maybe a feeling
asked = []
reply = 'Sure:\n```json\n{"memories": [{"day": 3, "hour": 21, "text": "CHAD and I shared mead."}, {"text": "He gave me a ring."}], "feeling": "Smitten."}\n```'
rows, feeling, problem = M.notes_to_rows(lambda s, t: asked.append((s, t)) or reply, 'Lydia', 'CHAD', 'we drank mead on day 3 at 9pm, he gave me a ring')
check('notes sent with names', 'Lydia' in asked[0][1] and 'CHAD' in asked[0][1] and 'ring' in asked[0][1], asked)
check('feeling only when the notes say it', 'outright' in asked[0][0], asked[0][0])
check('asks for point of view and JSON', 'point of view' in asked[0][0] and 'json' in asked[0][0].lower(), asked[0][0])
check('rows parsed, unknown time = -1', rows == [[3, 21, 'CHAD and I shared mead.'], [-1, -1, 'He gave me a ring.']], rows)
check('feeling parsed', feeling == 'Smitten.' and problem == '')
rows, feeling, problem = M.notes_to_rows(lambda s, t: 'no idea', 'Lydia', 'CHAD', 'x')
check('unreadable reply: told, nothing added', rows == [] and problem, problem)
rows, feeling, problem = M.notes_to_rows(lambda s, t: 1 / 0, 'Lydia', 'CHAD', 'x')
check('model error: told, not raised', rows == [] and 'Could not' in problem, problem)
check('empty notes: no call', M.notes_to_rows(lambda s, t: 1 / 0, 'Lydia', 'CHAD', '  ')[2] != '')

check('example memory is clean and has rows', M.EXAMPLE_RECENT and all(len(r) == 3 for r in M.EXAMPLE_RECENT) and 'Hadvar' in M.EXAMPLE_NAME)

print('RESULT: ' + ('ALL PASS' if not FAILS else f'{len(FAILS)} FAILED: {FAILS}'))
sys.exit(1 if FAILS else 0)
