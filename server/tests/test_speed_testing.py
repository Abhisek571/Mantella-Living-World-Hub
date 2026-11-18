"""Offline tests for speed testing (round 17): stage times on both sides, off by default, and preparing an NPC's file
ahead of the talk with only the changing fields refreshed at talk start.
Run with a Python 3.11: test_speed_testing.py <repo server dir>"""
import json, logging, os, re, sys, tempfile
from pathlib import Path

SERVER = Path(sys.argv[1]).resolve()
REPO = SERVER.parent
CODING = REPO.parent
sys.path.insert(0, str(SERVER))
from living_world import lw_state, settings, stage_timing

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)[:700]) if not cond else ''))
    if not cond:
        FAILS.append(name)


# Mantella's own log lines from live session 17 (17:10:55 - 17:10:59), as its logger writes them
LINES = ['Matched Gerdur in CSV by name, ID, race', 'Prompt sent to LLM (2198 tokens): # Overview',
         'LLM took 1.9278 seconds to respond', "Synthesizing voiceline: Oh, it's you.",
         'Anthropic (Native): prompt tokens cached (read) 3363, written to cache 4154, uncached 825 (cache points at about 2146)',
         'Gerdur should speak', "Full raw response (36 tokens): Oh, it's you. Keep your voice down, will you?",
         'Vision enabled for this LLM call']


def part_backend(tmp):
    check('off by default', settings.DEFAULTS['stage_timing'] is False and settings.DEFAULTS['prepare_npc_data'] is False)
    found = [stage_timing.stage_of(l) for l in LINES]
    check("each stage is read from Mantella's own line (other lines are none)",
          [f[0] if f else None for f in found] == ['start_received', 'prompt_built', 'first_token', 'first_sentence',
                                                    'tokens_in', 'handed_to_game', 'tokens_out', None]
          and found[4][1] == '3363 4154 825' and found[6][1] == '36', found)
    old = lw_state.DATA_DIR
    lw_state.DATA_DIR = str(tmp)
    try:
        log = logging.getLogger('Mantella')
        log.setLevel(logging.INFO)
        log.info(LINES[0])
        check('nothing is written while off', not (tmp / stage_timing.BACKEND_FILE).exists())
        lw_state.write_json(stage_timing.TALK_FILE, {'int': {'talk': 7}})
        stage_timing.apply(True)
        for line in LINES:
            log.info(line)
        stage_timing.mark('voice_audio')
        stage_timing.apply(False)
        log.info(LINES[0])
        rows = [r.split(',') for r in (tmp / stage_timing.BACKEND_FILE).read_text(encoding='utf-8').splitlines()]
        check('on: one row per stage with the game\'s talk number, tokens included; off again: nothing more',
              [r[2] for r in rows] == ['start_received', 'prompt_built', 'first_token', 'first_sentence', 'tokens_in',
                                       'handed_to_game', 'tokens_out', 'voice_audio'] and all(r[1] == '7' for r in rows)
              and len(rows[0]) == 4, rows)
        check('...the wall time has milliseconds (to join the game side by talk and order)',
              re.match(r'\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3}$', rows[0][0]), rows[0][0])
        from living_world import ui_overrides
        said = ui_overrides.set_speed_testing(True, True, str(tmp / 'settings.json'))
        perf = json.load(open(tmp / stage_timing.PERF, encoding='utf-8'))
        check('the Settings page switches write perf.json for the game side', perf == {'int': {'timing': 1, 'prepare': 1}}
              and settings.load(str(tmp / 'settings.json'))['prepare_npc_data'] is True and 'next NPC' in said, (perf, said))
        ui_overrides.set_speed_testing(False, False, str(tmp / 'settings.json'))
        check('...and back off', json.load(open(tmp / stage_timing.PERF, encoding='utf-8')) == {'int': {'timing': 0, 'prepare': 0}}
              and not stage_timing._state['on'])
    finally:
        lw_state.DATA_DIR = old
    src = (SERVER / 'living_world' / '__init__.py').read_text(encoding='utf-8')
    check('the backend timers follow the setting at every talk start', "stage_timing.apply(settings.load()['stage_timing'])" in src)


def part_voice(tmp):
    """voice_audio was never written: the timer wrapped TTSable.tts_synthesize, which XTTS overrides."""
    import types
    src, tts, mod = types.ModuleType('src'), types.ModuleType('src.tts'), types.ModuleType('src.tts.ttsable')

    class TTSable:
        def tts_synthesize(self, line, path, options):
            raise NotImplementedError

        def _generate_voiceline_files(self, line):
            self.tts_synthesize(line, 'x.wav', None)
            return 'lip'

    class XTTS(TTSable):  # as Direct AI Connect's tts/xtts.py: its own tts_synthesize
        def tts_synthesize(self, line, path, options):
            return 'wav'

    mod.TTSable = TTSable
    src.tts, tts.ttsable = tts, mod
    saved = {k: sys.modules.get(k) for k in ('src', 'src.tts', 'src.tts.ttsable')}
    sys.modules.update({'src': src, 'src.tts': tts, 'src.tts.ttsable': mod})
    old = lw_state.DATA_DIR
    lw_state.DATA_DIR = str(tmp / 'voice')
    try:
        class Later(TTSable):  # a service class loaded after the first switch-on, whose override calls the base one
            def tts_synthesize(self, line, path, options):
                try:
                    super().tts_synthesize(line, path, options)
                except NotImplementedError:
                    pass
                return 'wav'
        stage_timing.apply(False)
        stage_timing.apply(True)
        XTTS()._generate_voiceline_files('Hello.')
        Later()._generate_voiceline_files('Hello again.')
        stage_timing.apply(False)
        rows = [r.split(',')[2] for r in (tmp / 'voice' / stage_timing.BACKEND_FILE).read_text(encoding='utf-8').splitlines()]
        check('voice_audio is written for an XTTS line (the override is timed), then lip_done; an override calling the base '
              'method marks once', rows == ['voice_audio', 'lip_done', 'voice_audio', 'lip_done'], rows)
        stage_timing.apply(True)
        stage_timing.apply(False)
        XTTS()._generate_voiceline_files('Off.')
        rows2 = (tmp / 'voice' / stage_timing.BACKEND_FILE).read_text(encoding='utf-8').splitlines()
        check('switching on again does not wrap twice, and off writes nothing', len(rows2) == 4, rows2)
    finally:
        lw_state.DATA_DIR = old
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def _fields(text):
    return set(re.findall(r'JsonUtil\.Set(?:Int|String|Float)Value\((?:path|asPath), "(\w+)"', text))


def _func(src, head):
    i = src.index(head)
    return src[i:src.index('EndFunction', i)]


def part_game():
    channel = (REPO / 'Source' / 'Scripts' / 'MLW_Channel.psc').read_text(encoding='utf-8')
    world_facts = (REPO / 'Source' / 'Scripts' / 'MLW_WorldFacts.psc').read_text(encoding='utf-8')
    full = _fields(_func(channel, 'Function WriteNpc(')) | _fields(_func(channel, 'Function WriteWho(')) \
        | _fields(_func(world_facts, 'Function WriteNpc('))
    fast = _fields(_func(channel, 'Function WriteNpcChanging('))
    prepared = full - fast
    check('the talk-start refresh writes only fields the full path writes too (same file either way)', fast <= full, fast - full)
    check('...the time-sensitive ones', fast == {'close', 'intimate', 'follower', 'rated', 'rank', 'spouse', 'housecarl',
                                                  'allow_intimacy', 'home', 'trades_free', 'player',
                                                  'name', 'ref_id'}, sorted(fast))  # name, ref_id: whose file it is
    check('...the rest comes from the prepared file (who they are, factions, place, magic)',
          {'minor', 'guard', 'hold', 'location', 'here_hold', 'race', 'sex', 'class', 'work', 'illusion',
           'magic', 'town', 'home_town'} <= prepared, sorted(prepared))
    added = channel[channel.index('Event OnNpcAdded('):channel.index('EndEvent', channel.index('Event OnNpcAdded('))]
    check('talk start: the prepared path only with the switch on and a fresh file, else the full path as before',
          'If MLW_Timing.PrepareOn() && PreparedFresh(npc) && preparingNpc != npc' in added
          and '\t\tWriteNpcChanging(npc, BaseId(npc))' in added.replace('\r\n', '\n')
          and '\tElse\n\t\tWriteNpc(npc, BaseId(npc))' in added.replace('\r\n', '\n')
          and added.index('WriteMinorFirst(') < added.index('PreparedFresh(npc)'))  # the mod facts: every talk start
    fresh = _func(channel, 'bool Function PreparedFresh(')
    check('fresh = prepared within PREPARE_FRESH_DAYS of game time, never in the future, in the same location',
          'age >= 0.0 && age <= PREPARE_FRESH_DAYS' in fresh and 'akNpc.GetCurrentLocation()' in fresh
          and 'PREPARE_FRESH_DAYS = 0.05' in channel)
    cross = channel[channel.index('Event OnCrosshairRefChange('):channel.index('EndEvent', channel.index('Event OnCrosshairRefChange('))]
    later = channel[channel.index('Event OnUpdate()'):channel.index('EndEvent', channel.index('Event OnUpdate()'))]
    check('prepare: only a deliberate aim (still aimed after PREPARE_AIM_SECONDS, within PREPARE_DISTANCE), switch on, one at '
          'a time, never during a join or for someone in the talk, not fresh already, not in combat or a menu',
          all(k in cross for k in ('preparing', 'joining', 'MLW_Timing.PrepareOn()', 'PreparedFresh(npc)',
                                   'RegisterForSingleUpdate(PREPARE_AIM_SECONDS)'))
          and 'WriteNpc(' not in cross
          and all(k in later for k in ('Game.GetCurrentCrosshairRef() != npc', 'PREPARE_DISTANCE', 'InMantellaTalk(npc)', 'joining',
                                       'PlayerRef.IsInCombat()', 'Utility.IsInMenuMode()', 'npc.IsDead()', 'WriteNpc(npc, BaseId(npc))'))
          and later.index('PreparedFresh(npc)') < later.index('WriteNpc('))
    refresh = channel[channel.index('Event OnRefreshNpc('):channel.index('EndEvent', channel.index('Event OnRefreshNpc('))]
    check("a refresh from another module takes the cheap path; the mod facts are written once per join",
          'WriteNpcChanging(npc, BaseId(npc))' in refresh and 'MLW_ModFacts.WriteNpc(' not in _func(channel, 'Function WriteNpc(')
          and 'MLW_ModFacts.WriteNpc(' in _func(channel, 'Function WriteMinorFirst('))
    apply = _func(channel, 'Function ApplyPerf(')
    check('the switches are read again at each talk start and end (no restart), crosshair registered only when on',
          'MLW_Timing.ReadSettings()' in apply and 'RegisterForCrosshairRef()' in apply and 'ApplyPerf()' in _func(channel, 'Function Register(')
          and 'ApplyPerf()' in channel[channel.index('Event OnEnded('):] and 'ApplyPerf()' in channel[channel.index('Event OnStarted('):])
    check('a join re-registers events only on a save made before the current registration version',
          'If registeredVersion != REGISTER_VERSION' in added)
    timing = (REPO / 'Source' / 'Scripts' / 'MLW_Timing.psc').read_text(encoding='utf-8')
    check('game-side rows only while on, to timing_game.csv, with the talk number; talk number at the key',
          'If StorageUtil.GetIntValue(None, "MLW_TimingOn", 0) == 1' in _func(timing, 'Function Mark(')
          and 'timing_game.csv' in timing and 'timing_talk.json' in timing and 'MLW_Timing.NewTalk("talk_key")' in channel
          and 'MLW_Timing.Mark("hub", "started_request_sent")' in channel)
    handlers = [('Mantella-Living-World-World', 'MLWW_Meetings', 'OnNpcAdded'), ('Mantella-Living-World-World', 'MLWW_Trade', 'OnTalkStarted'),
                ('Mantella-Living-World-Relationships', 'MRB_MARAS', 'OnNpcAdded'), ('Mantella-Living-World-OStim-Expansion', 'MAE_Live', 'OnNpcAdded'),
                ('Mantella-Living-World-Followers', 'MLWF_Main', 'OnNpcAdded'), ('Mantella-Living-World-Knowledge', 'MLWK_Checks', 'OnNpcAdded'),
                ('Mantella-Living-World-Missives', 'MLWM_Jobs', 'OnNpcAdded'), ('Mantella-Living-World-Survival', 'MLWS_Facts', 'OnNpcAdded'),
                ('Mantella-Living-World-Arousal', 'MantellaOSLA_Main', 'OnMantellaStarted')]
    missing = []
    for repo, script, event in handlers:
        path = CODING / repo / 'Source' / 'Scripts' / f'{script}.psc'
        if not path.is_file():
            continue
        src = path.read_text(encoding='utf-8')
        if f',{script},{event}_start,' not in src or f',{script},{event}_end,' not in src or 'MLW_Timing.' in src:
            missing.append(script)
    check("each module writes its own start and end rows, with PapyrusUtil only (no call into the Hub)", not missing, missing)


with tempfile.TemporaryDirectory() as tmp:
    for part in (lambda: part_backend(Path(tmp)), lambda: part_voice(Path(tmp)), part_game):
        try:
            part()
        except Exception as e:
            import traceback
            traceback.print_exc()
            check(f'{getattr(part, "__name__", "part")} ran without an error', False, e)

print(f"\n{len(FAILS)} failure(s)" if FAILS else '\nall passed')
sys.exit(1 if FAILS else 0)
