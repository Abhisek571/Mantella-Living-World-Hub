"""Offline tests for asked-before notes (server/living_world/asked_before.py).
Run with a Python 3.11: test_asked_before.py <repo server dir>"""
import sys, tempfile
from pathlib import Path

SERVER = Path(sys.argv[1])
sys.path.insert(0, str(SERVER))
from living_world import asked_before, memory

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)) if not cond else ''))
    if not cond:
        FAILS.append(name)


def msgs(*lines):
    return [{'role': 'user' if i % 2 == 0 else 'assistant', 'content': line} for i, line in enumerate(lines)]


# topics: names in the player's line, not the people talking and not a capital at the start of a sentence
t = asked_before.topics('What do you know about Bleak Falls Barrow? And the Jarl of Whiterun?', exclude={'Camilla Valerius', 'Player'})
check('multi-word place found', 'Bleak Falls Barrow' in t, t)
check('single name found', 'Whiterun' in t or 'Jarl of Whiterun' in t, t)
check('sentence-start words ignored', 'What' not in t and 'And' not in t, t)
check('speakers and player ignored', not asked_before.topics('Camilla, tell Player a story.', exclude={'Camilla Valerius', 'Player'}))
check("Mantella's instruction words ignored", not asked_before.topics('Greet them. Ensure you Respond in character, Keep it short.', exclude=set()),
      asked_before.topics('Greet them. Ensure you Respond in character, Keep it short.', exclude=set()))
check('parenthesized events ignored', not asked_before.topics('Hi. (The location is now Riverwood.)', exclude=set()))

with tempfile.TemporaryDirectory() as tmp:
    store = memory.MemoryStore(str(Path(tmp) / 'conversations'), 'Player1')
    people = [('Camilla Valerius', '013488')]
    tracker = asked_before.Tracker()

    # test_same_topic_counted: one count per conversation, however often it comes up
    first = tracker.notes(msgs('What do you know about Bleak Falls Barrow?'), people, store, 'Player')
    check('first ask: no note', first == '', first)
    tracker.notes(msgs('What do you know about Bleak Falls Barrow?', 'Not much.', 'Bleak Falls Barrow, really?'), people, store, 'Player')
    asked = store.load('Camilla Valerius', '013488').get('asked', {})
    check('same topic counted once per talk', asked.get('Bleak Falls Barrow') == 1, asked)

    # test_note_after_second_ask: a new conversation (the message list starts over) about the same place
    note = tracker.notes(msgs('Tell me about Bleak Falls Barrow again.'), people, store, 'Player')
    check('note after second ask', note.startswith('(Player asked Camilla Valerius about Bleak Falls Barrow before;') and 'add something new' in note, note)
    check('count is two now', store.load('Camilla Valerius', '013488')['asked']['Bleak Falls Barrow'] == 2)
    check('other NPCs do not know', 'asked' not in store.load('Lucan Valerius', '01347C') or not store.load('Lucan Valerius', '01347C')['asked'])
    check('nothing without a store', tracker.notes(msgs('Bleak Falls Barrow'), people, None, 'Player') == '')

print('RESULT: ' + ('ALL PASS' if not FAILS else f'{len(FAILS)} FAILED: {FAILS}'))
sys.exit(1 if FAILS else 0)
