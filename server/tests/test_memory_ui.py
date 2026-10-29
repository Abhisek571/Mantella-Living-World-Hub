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
    # test_long_term_rows_never_dropped: same topic twice is joined (and reported); a note without topic goes to earlier
    lt, joined = M.long_term_from_rows([['earlier', 'Swore an oath.'], ['earlier', 'Carried my pack.'], ['', 'Hates Belethor.'], ['war', None]])
    check('same-topic and topic-less notes kept', lt == {'earlier': 'Swore an oath.\nCarried my pack.\nHates Belethor.'} and joined == ['earlier'], (lt, joined))
    check('from_tables keeps both same-topic notes', M.from_tables(current, '', [], [['oath', 'A'], ['oath', 'B']])['long_term'] == {'oath': 'A\nB'})

    # test_csv_ref_ids_like_mantella: short or long csv ref ids are filed the way the game looks them up
    check('ref ids normalised like Mantella', [M.mantella_ref(r) for r in ('837', '0002D63', '977fc', '0A2C94', 'FE001837', '')]
          == ['000837', '002D63', '0977FC', '0A2C94', '000837', ''])
    short = tmp / 'short.csv'
    with open(short, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['name', 'race', 'ref_id', 'base_id', 'bio'])
        w.writeheader()
        w.writerow({'name': 'Azadi', 'race': 'Redguard', 'ref_id': '837', 'base_id': '836', 'bio': ''})
    store.save('Azadi', '000837', dict(memory.empty(), recent=[{'day': 1, 'hour': 1, 'text': 'Met.'}]))
    azadi = [p for p in M.people(str(conv), 'CHAD1', str(short)) if p['name'] == 'Azadi']
    check('short csv ref: one entry, under the game id', [p['ref_id'] for p in azadi] == ['000837'], azadi)

    # test_reset_memory: moved to a backup, never deleted
    backups = tmp / 'removed'
    check('reset memory', M.reset_memory(store, 'Faendal', '01348C', str(backups)))
    check('file gone from memory', not (conv / 'CHAD1' / 'living_world' / 'Faendal - 01348C.json').exists())
    check('kept in backup', any(p.name == 'Faendal - 01348C.json' for p in backups.rglob('*.json')))
    check('reset with nothing there', not M.reset_memory(store, 'Hadvar', '02BFA1', str(backups)))

    # test_reset_takes_mantella_summaries: otherwise the next load converts them back into a memory
    legacy = conv / 'CHAD1' / 'Camilla Valerius - 01A694'
    legacy.mkdir(parents=True)
    (legacy / 'Camilla Valerius_summary_1.txt').write_text('CHAD asked about the claw.', encoding='utf-8')
    check('old Mantella summary becomes a memory', store.load('Camilla Valerius', '01A694')['long_term'].get('earlier'))
    check('reset takes the summary folder too', M.reset_memory(store, 'Camilla Valerius', '01A694', str(backups)) and not legacy.exists())
    check('memory does not come back after reset', store.load('Camilla Valerius', '01A694') == memory.empty())

    # test_delete_one: one memory forgotten, the rest kept, file copied first
    store.save('Ysolda', '01A69E', dict(memory.empty(), recent=[{'day': 1, 'hour': 9, 'text': 'Bought a tusk.'},
                                                                 {'day': 2, 'hour': 14, 'text': 'Sold her a ring.'}]))
    choices = M.memory_choices(store.load('Ysolda', '01A69E'))
    check('choices newest first, numbered', choices[0].startswith('2. [Day 2') and 'ring' in choices[0] and choices[1].startswith('1. '), choices)
    before = len(list(backups.rglob('Ysolda*')))
    check('delete one memory', M.delete_one(store, 'Ysolda', '01A69E', choices[0], str(backups)) == 'Sold her a ring.')
    check('only that one gone', [e['text'] for e in store.load('Ysolda', '01A69E')['recent']] == ['Bought a tusk.'])
    check('file copied before the change', len(list(backups.rglob('Ysolda*'))) == before + 1)
    check('stale label deletes nothing', M.delete_one(store, 'Ysolda', '01A69E', choices[0], str(backups)) == ''
          and len(store.load('Ysolda', '01A69E')['recent']) == 1)

    # test_purge_save: everyone in the save forgets, everything moved, other saves untouched
    other = memory.MemoryStore(str(conv), 'OTHER1')
    other.save('Lydia', '0A2C94', dict(memory.empty(), recent=[{'day': 1, 'hour': 1, 'text': 'Met.'}]))
    legacy2 = conv / 'CHAD1' / 'Sven - 01348A'
    legacy2.mkdir()
    (legacy2 / 'Sven_summary_1.txt').write_text('x', encoding='utf-8')
    npcs, memories = M.save_counts(str(conv), 'CHAD1')
    check('counts NPCs and memories without converting', npcs >= 3 and memories >= 2 and legacy2.exists()
          and not any(p.name.startswith('Sven') for p in (conv / 'CHAD1' / 'living_world').iterdir()), (npcs, memories))
    moved = M.purge_save(str(conv), 'CHAD1', str(backups))
    check('purge moves everything in the save', moved >= 2 and not any((conv / 'CHAD1').iterdir()), moved)
    check('purged save has nobody left', M.save_counts(str(conv), 'CHAD1') == (0, 0))
    check('other save untouched', other.load('Lydia', '0A2C94')['recent'][0]['text'] == 'Met.')
    check('purge refuses odd save names', M.purge_save(str(conv), '..', str(backups)) == 0 and M.purge_save(str(conv), '', str(backups)) == 0)

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
