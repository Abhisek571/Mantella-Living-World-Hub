"""Offline tests for live session 17 (2026-11-16), from the real files it left: the kept scene re-sent to talk 2 although
already stored (shown to the model again), the scene wording copied into a first-person memory ("minuteS", "Climaxes:
The Player 2 times and Gerdur once."), the greeting built before the menu memory, and the after-scene talk that gave up
without a word. The session's files are read from its folder when it is on this PC (never copied into the repository).
Run with a Python 3.11: test_live_test_17.py <repo server dir>"""
import json, os, re, sys, tempfile
from pathlib import Path
from types import SimpleNamespace

SERVER = Path(sys.argv[1]).resolve()
REPO = SERVER.parent
CODING = REPO.parent
sys.path.insert(0, str(SERVER))
from living_world import memory, menu_dialogue as MD

LIVE17 = os.path.join(os.environ.get('MLW_EVIDENCE', ''), r'lw-live-test-17-2026-11-16')
FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)[:700]) if not cond else ''))
    if not cond:
        FAILS.append(name)


GERDUR = SimpleNamespace(name='Gerdur', ref_id='013489', base_id='01347C', bio='')
# the scene line as OStim Expansion sent it (talk 2, 17:10:55), acts shortened
RESENT = ('Earlier (less than an hour ago), with no conversation going on: Gerdur and the player finished having sex in '
          'Riverwood after about 2 minuteS. They did a blowjob and vaginal sex. Climaxes: The Player 2 times and Gerdur once. '
          '{t=0.550439}')


def _memory():
    try:
        return json.load(open(os.path.join(LIVE17, 'session-created', 'conversations-Brom1-final', 'living_world',
                                           'Gerdur - 013489.json'), encoding='utf-8'))
    except OSError:
        return None


def part_resent(tmp):
    mem = _memory()
    if not mem:
        return print('SKIP the live session 17 memory is not on this PC')
    check('the real menu memory holds the scene time', mem['recent'][0].get('scene_times') == [0.550439])
    store = memory.MemoryStore(str(tmp / 'resent'), 'w')
    store.save('Gerdur', '013489', mem)
    events = [RESENT, "Gerdur's favourite positions: kneeling."]
    check('a re-sent scene already in her memory is dropped from the events; other events stay',
          MD.stored_scene_indexes(events, [GERDUR], store) == {0})
    check('a scene not stored yet stays', MD.stored_scene_indexes([RESENT.replace('0.550439', '0.6')], [GERDUR], store) == set())
    src = (SERVER / 'living_world' / '__init__.py').read_text(encoding='utf-8')
    body = src[src.index('def _menu_memories('):src.index('def _menu_before_prompt(')]
    check('...before anything else uses them (and it is still acknowledged)', 'stored_scene_indexes(raw,' in body
          and body.index('stored_scene_indexes(raw,') < body.index('if ctx.get(\'is_first\')') and 'acknowledge_scenes(raw,' in body)


def part_wording():
    mem = _memory()
    then = mem['recent'][0]['text'].split(' Then: ', 1)[1] if mem else ('Brom and I finished having sex in Riverwood after about 2 '
                                                                         'minuteS. We did a blowjob. Climaxes: The Player 2 times and Gerdur once.')
    check('the real stored line has the typo and the third-person list', 'minuteS' in then and 'Climaxes: The Player 2 times and Gerdur once.' in then)
    text = MD.first_person(MD.SCENE_EVENT.match(MD.SCENE_TIME.sub('', RESENT)).group(2), 'Gerdur', 'Brom')
    check('now: "minutes", and a plain first-person sentence instead of the list',
          text == 'Brom and I finished having sex in Riverwood after about 2 minutes. We did a blowjob and vaginal sex. '
                  'Brom climaxed twice and I climaxed once.', text)
    hooded = MD.first_person('Gerdur and the player finished having sex. Climaxes: The Player once.', 'Gerdur', 'the hooded stranger')
    check('...the hooded stranger for someone who does not know him', hooded == 'The hooded stranger and I finished having sex. '
          'The hooded stranger climaxed once.', hooded)
    psc = CODING / 'Mantella-Living-World-OStim-Expansion' / 'Source' / 'Scripts' / 'MAE_Live.psc'
    if psc.is_file():
        src = psc.read_text(encoding='utf-8')
        check('the typo is fixed at its source (whole-word literals, no lone "s")', 'line += "s"' not in src
              and '" minutes"' in src and '" after about 1 minute"' in src)


def part_greeting():
    src = (SERVER / 'living_world' / '__init__.py').read_text(encoding='utf-8')
    text_hook = src[src.index('def _memory_text('):src.index('def _pages(')]
    check('the menu lines are put in her memory block in the memory_text hook, before it is built (the greeting has them)',
          '_menu_before_prompt(store, ctx, speakers)' in text_hook
          and text_hook.index('_menu_before_prompt(') < text_hook.index('return memory.memory_text('))
    events = src[src.index('def _menu_memories('):src.index('def _menu_before_prompt(')]
    check('...and a scene at the first message (or a later one) still goes with them', events.count('pair_late_scenes(raw,') == 1
          and 'if scenes and store is not None:' in events[events.index("if ctx.get('is_first')"):])


def part_after_scene():
    psc = CODING / 'Mantella-Living-World-Relationships' / 'Source' / 'Scripts' / 'MRB_Ledger.psc'
    if not psc.is_file():
        return print('SKIP the Relationships repository is not next to this one')
    src = psc.read_text(encoding='utf-8')
    start = src[src.index('Function StartTalk('):src.index('EndFunction', src.index('Function StartTalk('))]
    check('the after-scene talk gives up when the player is farther than a talk distance from her',
          'PlayerRef.GetDistance(akPartner) > TALK_DISTANCE' in start and 'TALK_DISTANCE = 1500.0' in src)
    reasons = ('the player went too far away', 'timed out after', 'a talk was already open', 'the partner is dead or in combat',
               'the setting is off')
    check('...and every give-up writes why to the Papyrus log', all(r in src for r in reasons)
          and 'Debug.Trace("Mantella Living World - Relationships: no after-scene talk with "' in src
          and src.count('NotStarted(') >= 7)


with tempfile.TemporaryDirectory() as tmp:
    for part in (lambda: part_resent(Path(tmp)), part_wording, part_greeting, part_after_scene):
        try:
            part()
        except Exception as e:
            import traceback
            traceback.print_exc()
            check(f'{getattr(part, "__name__", "part")} ran without an error', False, e)
        MD.talk_over()

print(f"\n{len(FAILS)} failure(s)" if FAILS else '\nall passed')
sys.exit(1 if FAILS else 0)
