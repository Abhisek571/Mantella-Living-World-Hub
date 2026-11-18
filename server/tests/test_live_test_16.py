"""Offline tests for live session 16 (2026-11-16): the voice server was down, so the after-scene talk ended after its
first reply and the two kept scenes handed to it were lost. OStim Expansion now keeps a scene until the Hub has stored
it (the Hub acknowledges "<name>|<scene time>" in scene_ack.json); the Hub never stores a re-sent scene twice. Also
kept as checks: every captured line had the player's topic, and the menu memory was first person and marked as how they
met. The session's files are read from its folder when it is on this PC (never copied into the repository).
Run with a Python 3.11: test_live_test_16.py <repo server dir>"""
import json, os, sys, tempfile
from pathlib import Path
from types import SimpleNamespace

SERVER = Path(sys.argv[1]).resolve()
REPO = SERVER.parent
sys.path.insert(0, str(SERVER))
from living_world import lw_state, memory, menu_dialogue as MD
memory.SUMMARY_RETRY_SECONDS = 0

LIVE16 = os.path.join(os.environ.get('MLW_EVIDENCE', ''), r'lw-live-test-16-2026-11-16')
FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)[:700]) if not cond else ''))
    if not cond:
        FAILS.append(name)


GERDUR = SimpleNamespace(name='Gerdur', ref_id='013489', base_id='01347C', bio='')
SCENES = ('Gerdur and the player finished having sex in Riverwood. They did a handjob.',
          'Gerdur and the player finished having sex in Riverwood after about 1 minute. They did vaginal sex.')


def sent(ago, t, text):
    return f"Earlier ({ago}), with no conversation going on: {text} {{t={t}}}"


class Summaries:
    _Summaries__language_name = 'English'

    def __init__(self, fail=False):
        self.fail, self.calls = fail, 0

    def summarize_conversation(self, text, prompt):
        self.calls += 1
        return '' if self.fail else json.dumps({'memory': 'First Brom asked and I gave in.', 'feelings': {}})


def _world():
    try:
        return json.load(open(os.path.join(LIVE16, 'captured', 'menu_dialogue.json'), encoding='utf-8'))
    except OSError:
        return None


def part_kept_until_stored(tmp):
    data_dir = tmp / 'channel'
    data_dir.mkdir()
    old = lw_state.DATA_DIR
    lw_state.DATA_DIR = str(data_dir)
    try:
        store = memory.MemoryStore(str(tmp / 'kept'), 'w')
        world = _world() or {'player': 'Brom', 'npcs': {}}
        MD.prepare(store, GERDUR, 'Brom', data=world, knows=True)
        MD.talk_over()  # the talk died after its first reply: the scenes (second message) never came, no summary ran
        check('the talk that died acknowledged nothing', not (data_dir / lw_state.SCENE_ACK).exists())
        first = [sent('less than an hour ago', '0.51520', SCENES[0]), sent('less than an hour ago', '0.51900', SCENES[1])]
        # the next talk: OStim Expansion sends them again (here with its first message)
        saved = MD.remember_scene_events(first, [GERDUR], store, 0, None, player='Brom')
        keys = MD.acknowledge_scenes(first, [GERDUR], store)
        ack = json.load(open(data_dir / lw_state.SCENE_ACK, encoding='utf-8'))
        check('sent again at the next talk: both stored, and acknowledged in the shape the game reads',
              saved == 2 and keys == ['Gerdur|0.51520', 'Gerdur|0.51900'] and ack == {'stringList': {'stored': keys}}, (saved, ack))
        later = [sent('about 3 hours ago', '0.51520', SCENES[0]), sent('about 3 hours ago', '0.51900', SCENES[1])]
        check('sent once more (the Expansion had not read the acknowledgement yet, other "ago" wording): never stored twice',
              MD.remember_scene_events(later, [GERDUR], store, 0, None, player='Brom') == 0
              and len([e for e in store.load('Gerdur', '013489')['recent'] if e.get('scene_times')]) == 2)
        check('...acknowledged again, no duplicate key', MD.acknowledge_scenes(later, [GERDUR], store) == keys
              and json.load(open(data_dir / lw_state.SCENE_ACK, encoding='utf-8'))['stringList']['stored'] == keys)
        check('a scene not stored is not acknowledged', MD.acknowledge_scenes([sent('x', '0.9', 'Lydia and the player finished.')],
                                                                              [GERDUR], store) == [])
        MD.talk_over()
        store2 = memory.MemoryStore(str(tmp / 'paired'), 'w')
        if _world():
            from menu_talk import end_talk
            MD.prepare(store2, GERDUR, 'Brom', data=world, knows=True)
            MD.pair_late_scenes(first, [GERDUR], store2, 'Brom')
            end_talk(store2, [GERDUR], Summaries())
            MD.talk_over()
            text = [e for e in store2.load('Gerdur', '013489')['recent'] if e.get('dialogue')][0]['text']
            check('paired into the menu memory then sent again: no second "Then:"', MD.pair_late_scenes(later, [GERDUR], store2, 'Brom')
                  == set() and text.count(' Then: ') == 2
                  and sum(' Then: ' in e['text'] for e in store2.load('Gerdur', '013489')['recent']) == 1)
            check('...nor a memory of its own', MD.remember_scene_events(later, [GERDUR], store2, 0, None, paired=set(),
                                                                       player='Brom') == 0)
            check('...and acknowledged then, so OStim Expansion stops sending it', MD.acknowledge_scenes(later, [GERDUR], store2) == keys)
            MD.talk_over()
    finally:
        lw_state.DATA_DIR = old
    src = (SERVER / 'living_world' / '__init__.py').read_text(encoding='utf-8')
    check('the Hub acknowledges on every message that carries kept scenes, also without World',
          'menu_dialogue.acknowledge_scenes(raw,' in src and "{'World', 'OStim Expansion'} & _installed()" in src)


def part_expansion():
    psc = REPO.parent / 'Mantella-Living-World-OStim-Expansion' / 'Source' / 'Scripts' / 'MAE_Live.psc'
    if not psc.is_file():
        return print('SKIP the OStim Expansion repository is not next to this one')
    src = psc.read_text(encoding='utf-8')
    added = src[src.index('Event OnNpcAdded('):src.index('EndEvent', src.index('Event OnNpcAdded('))]
    drop = src[src.index('Function DropStored('):src.index('EndFunction', src.index('Function DropStored('))]
    check('with the Hub: stored scenes are dropped first, the rest sent and KEPT until acknowledged',
          'If hub' in added and 'DropStored(npc)' in added and 'If !hub\n\t\tStorageUtil.StringListClear(npc, KEY_PENDING)' in added
          .replace('\r\n', '\n'))
    check('without the Hub: sent once and cleared, as before (no new dependency: a plugin check, a JSON file)',
          'Game.IsPluginInstalled(HUB_PLUGIN)' in added and 'MLW_' not in drop)
    check('the acknowledgement is read fresh and matched as "<name>|<scene time>"', 'JsonUtil.Unload(ACK_PATH, false)' in drop
          and 'JsonUtil.StringListFind(ACK_PATH, "stored", name + "|" + StringUtil.Substring(entry, 0, bar))' in drop
          and 'ACK_PATH = "MantellaLivingWorld/scene_ack.json"' in src)


def part_menu_failure(tmp):
    world = _world()
    if not world:
        return print('SKIP the live session 16 menu dialogue is not on this PC')
    from menu_talk import end_talk
    store = memory.MemoryStore(str(tmp / 'fail'), 'w')
    MD.prepare(store, GERDUR, 'Brom', data=world)
    end_talk(store, [GERDUR], Summaries(fail=True))
    check('no connection at the end of the talk: no memory, the lines stay pending', MD.load_seen(store) == {}
          and not any(e.get('dialogue') for e in store.load('Gerdur', '013489')['recent']))
    MD.talk_over()  # Mantella ended the talk right after its first reply
    again = Summaries()
    check('...the next talk shows all 9 lines again', len(MD.prepare(store, GERDUR, 'Brom', data=world)['lines']) == 9)
    end_talk(store, [GERDUR], again)
    check('...and makes the memory from them with its one request', again.calls == 1
          and len([e for e in store.load('Gerdur', '013489')['recent'] if e.get('dialogue')]) == 1)
    MD.talk_over()


def part_good_news():
    world = _world()
    path = os.path.join(LIVE16, 'captured', 'Brom1-1618', 'living_world', 'Gerdur - 013489.json')
    if not world or not os.path.isfile(path):
        return print('SKIP the live session 16 files are not on this PC')
    lines = world['npcs']['01347C']['lines']
    check("all 9 captured lines carry the player's topic (the DLL's topic fallback)", len(lines) == 9 and all(l['said'].strip() for l in lines))
    recent = json.load(open(path, encoding='utf-8'))['recent']
    check('the menu memory: first person, intimacy, and first_meeting on the only memory',
          len(recent) == 1 and recent[0]['flags'] == ['intimacy', 'first_meeting'] and ' me ' in f" {recent[0]['text']} "
          and not recent[0]['text'].startswith('Gerdur'))


with tempfile.TemporaryDirectory() as tmp:
    for part in (lambda: part_kept_until_stored(Path(tmp)), part_expansion, lambda: part_menu_failure(Path(tmp)), part_good_news):
        try:
            part()
        except Exception as e:
            import traceback
            traceback.print_exc()
            check(f'{getattr(part, "__name__", "part")} ran without an error', False, e)
        MD.talk_over()

print(f"\n{len(FAILS)} failure(s)" if FAILS else '\nall passed')
sys.exit(1 if FAILS else 0)
