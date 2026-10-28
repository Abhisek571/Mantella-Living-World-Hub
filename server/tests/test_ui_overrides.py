"""Offline tests for the character overrides editor (server/living_world/ui_overrides.py).
Run with a Python 3.11: test_ui_overrides.py <repo server dir>"""
import csv, json, sys, tempfile, time
from pathlib import Path

SERVER = Path(sys.argv[1])
sys.path.insert(0, str(SERVER))
from living_world import ui_overrides as U

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)) if not cond else ''))
    if not cond:
        FAILS.append(name)


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    base = tmp / 'skyrim_characters.csv'
    with open(base, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['name', 'voice_model', 'bio', 'race', 'base_id', 'ref_id'])
        w.writeheader()
        w.writerow({'name': 'Lucan Valerius', 'voice_model': 'MaleEvenToned', 'bio': 'Lucan runs the shop.', 'race': 'Imperial', 'base_id': '01347A', 'ref_id': '013487'})
        w.writerow({'name': 'Camilla Valerius', 'voice_model': 'FemaleYoungEager', 'bio': 'Camilla flirts.', 'race': 'Imperial', 'base_id': '01347B', 'ref_id': '013488'})
    before = base.read_bytes()
    overrides = tmp / 'character_overrides'

    # test_find: by part of the name, base CSV first, then the user's overrides on top
    found = U.find_characters('lucan', str(base), str(overrides))
    check('found by part of the name', [r['name'] for r in found] == ['Lucan Valerius'], found)
    check('fields from the base csv', found[0]['bio'] == 'Lucan runs the shop.' and found[0]['voice_model'] == 'MaleEvenToned', found[0])

    # test_writes_only_changed_fields
    path = U.save_override(str(overrides), found[0], {'bio': 'Lucan runs the shop and frets about the claw.', 'voice_model': 'MaleEvenToned'}, str(base))
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    check('only the changed field plus the match keys', data == {'name': 'Lucan Valerius', 'race': 'Imperial', 'base_id': '01347A', 'bio': 'Lucan runs the shop and frets about the claw.'}, data)
    check('the override is seen next time', U.find_characters('lucan', str(base), str(overrides))[0]['bio'].endswith('frets about the claw.'))

    # test_mod_npc_without_base_id: NPCs not in the base csv are matched by name and race only (short light-plugin
    # base ids made one override replace another NPC's row)
    mod_npc = {'name': 'Nyri', 'race': 'Nord', 'base_id': '000821', 'bio': '', 'voice_model': ''}
    data = json.loads(Path(U.save_override(str(overrides), mod_npc, {'bio': 'Nyri hunts.'}, str(base))).read_text(encoding='utf-8'))
    check('mod NPC: no base id written', 'base_id' not in data and data['name'] == 'Nyri', data)

    # test_never_touches_base_csv
    check('base csv untouched', base.read_bytes() == before)
    check('nothing changed = nothing written', U.save_override(str(overrides), found[0], {'bio': 'Lucan runs the shop.'}, str(base)) is None)
    # review fixes: Mantella reads overrides with the system codepage, so only ASCII on disk; same names kept apart;
    # the user's list files never replaced
    p = U.save_override(str(overrides), mod_npc, {'bio': 'Nyri’s café “friend”.'}, str(base))
    check('written as ASCII (escaped)', Path(p).read_bytes().isascii() and json.loads(Path(p).read_text(encoding='ascii'))['bio'] == 'Nyri’s café “friend”.')
    bandit_a, bandit_b = {'name': 'Bandit', 'race': 'Nord', 'bio': 'a'}, {'name': 'Bandit', 'race': 'Redguard', 'bio': 'b'}
    pa, pb = U.save_override(str(overrides), bandit_a, {'bio': 'A Nord bandit.'}), U.save_override(str(overrides), bandit_b, {'bio': 'A Redguard bandit.'})
    check('two NPCs with one name get two files', pa != pb and json.loads(Path(pa).read_text())['race'] == 'Nord', (pa, pb))
    (overrides / 'Gang.json').write_text(json.dumps([{'name': 'Gang', 'bio': 'x'}, {'name': 'Gang2', 'bio': 'y'}]), encoding='utf-8')
    pg = U.save_override(str(overrides), {'name': 'Gang', 'bio': 'x'}, {'bio': 'z'})
    check('a list override file is never replaced', json.loads((overrides / 'Gang.json').read_text())[1]['name'] == 'Gang2' and Path(pg).name != 'Gang.json', pg)
    # test_blank_search_lists_my_overrides: an empty search shows every NPC the user has an override for
    mine = U.find_characters('', str(base), str(overrides), limit=100)
    names = [r['name'] for r in mine]
    check('blank search = all my overrides', 'Lucan Valerius' in names and 'Nyri' in names and 'Gang2' in names and 'Camilla Valerius' not in names, names)
    check('blank search: base fields kept', next(r for r in mine if r['name'] == 'Lucan Valerius')['voice_model'] == 'MaleEvenToned')

    # test_filters: my overrides / custom (not in Mantella's csv) / followers (Living World's npc state), combinable
    followers = {'nyri', 'Vega', 'Camilla Valerius'}  # names as Living World saw them in game
    find = lambda q='', **kw: [r['name'] for r in U.find_characters(q, str(base), str(overrides), limit=100, followers=followers, **kw)]
    check('followers shown on a blank search, even without an override', 'Vega' in find() and 'Camilla Valerius' in find(), find())
    check('only my overrides', 'Vega' not in find(only_mine=True) and 'Lucan Valerius' in find(only_mine=True), find(only_mine=True))
    check('only custom NPCs', 'Lucan Valerius' not in find(only_custom=True) and 'Nyri' in find(only_custom=True) and 'Vega' in find(only_custom=True), find(only_custom=True))
    check('only followers', sorted(find(only_followers=True)) == ['Camilla Valerius', 'Nyri', 'Vega'], find(only_followers=True))
    check('filters combine', find(only_followers=True, only_custom=True, only_mine=True) == ['Nyri'], find(only_followers=True, only_custom=True, only_mine=True))
    check('search + filter', find('val', only_followers=True) == ['Camilla Valerius'], find('val', only_followers=True))
    tags = {r['name']: U.tags(r) for r in U.find_characters('', str(base), str(overrides), limit=100, followers=followers)}
    check('row tags', 'override' in tags['Nyri'] and 'custom' in tags['Nyri'] and 'follower' in tags['Nyri'] and 'custom' not in tags['Lucan Valerius'], tags)

    # test_default_bio: Mantella's own bio for an NPC (what an override replaces); '' for custom NPCs
    check('default bio from csv', U.default_bio({'name': 'Lucan Valerius', 'race': 'Imperial'}, str(base)) == 'Lucan runs the shop.')
    check('custom NPC: no default bio', U.default_bio({'name': 'Nyri', 'race': 'Nord'}, str(base)) == '')

    # test_reset_npc: the NPC's own override files move to a dated backup folder (never deleted); list files stay
    backups = tmp / 'removed'
    moved = U.reset_override(str(overrides), {'name': 'Lucan Valerius', 'race': 'Imperial'}, str(backups))
    check('reset NPC: file moved out', moved and not any('Lucan' in p.name for p in overrides.glob('*.json')), list(overrides.glob('*.json')))
    check('reset NPC: kept in backup', any('Lucan' in p.name for p in backups.rglob('*.json')), list(backups.rglob('*')))
    check('reset NPC: list file untouched', (overrides / 'Gang.json').exists() and U.reset_override(str(overrides), {'name': 'Gang2'}, str(backups)) == [])
    # test_reset_all
    count = len(list(overrides.glob('*.json')))
    check('reset all: every file moved', U.reset_all(str(overrides), str(backups)) == count and not list(overrides.glob('*.json')))
    check('reset all: nothing lost', len(list(backups.rglob('*.json'))) == count + len(moved))

# test_find_npc_list: the typeable dropdown lists everyone in Mantella's list plus custom NPCs, each label unique
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    base = tmp / 'c.csv'
    with open(base, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['name', 'voice_model', 'bio', 'race', 'base_id'])
        w.writeheader()
        w.writerow({'name': 'Hadvar', 'voice_model': 'MaleEvenToned', 'bio': 'A soldier.', 'race': 'Nord', 'base_id': '02BF9F'})
        w.writerow({'name': 'Bandit', 'voice_model': '', 'bio': 'x', 'race': 'Nord', 'base_id': '1'})
        w.writerow({'name': 'Bandit', 'voice_model': '', 'bio': 'y', 'race': 'Nord', 'base_id': '2'})
    ov = tmp / 'o'; ov.mkdir()
    (ov / 'Nyri.json').write_text(json.dumps({'name': 'Nyri', 'race': 'Dunmer', 'bio': 'Mod NPC.'}), encoding='utf-8')
    rows = U.find_characters('', str(base), str(ov), limit=None, followers=set(), everyone=True)
    labels = U.labels(rows)
    check('everyone listed', sorted(r['name'] for r in rows) == ['Bandit', 'Bandit', 'Hadvar', 'Nyri'], rows)
    check('labels unique', len(set(labels)) == len(labels), labels)
    check('label shows race and tags', any(l.startswith('Nyri (Dunmer)') and 'override' in l for l in labels), labels)
    # test_new_override_guard: a new NPC override is only for NPCs not already in Mantella's list
    check('new NPC: name already in the list is refused', U.new_npc_problem('hadvar', str(base)) and 'pick' in U.new_npc_problem('hadvar', str(base)).lower())
    check('new NPC: unknown name allowed', U.new_npc_problem('Vega', str(base)) == '')
    check('new NPC: empty name refused', U.new_npc_problem('  ', str(base)) != '')
check('example override is there and clean', 'Hadvar' in U.EXAMPLE_OVERRIDE and len(U.EXAMPLE_OVERRIDE) > 400)
check('confirm answer goes to the first input', 'a[0] = confirm(' in U._confirm_js('Sure?'))

# test_player_presets: reset puts the default (Dragonborn) preset back, never an empty description
check('presets include the Dragonborn default', U.DEFAULT_PRESET in U.PLAYER_PRESETS and 'Dragonborn' in U.PLAYER_PRESETS[U.DEFAULT_PRESET])
check('every preset is a real description', all(len(t) > 80 for t in U.PLAYER_PRESETS.values()))
class _Val:
    value = 'Something else.'
class _Cfg:
    class definitions:
        v = _Val()
        @staticmethod
        def get_config_value_definition(identifier):
            return _Cfg.definitions.v
U.reset_player_description(_Cfg)
check('reset player = default preset', _Cfg.definitions.v.value == U.PLAYER_PRESETS[U.DEFAULT_PRESET], _Cfg.definitions.v.value)

# test_my_presets: personal presets live in the user's own folder (never in the mod); built-in names stay as shipped
with tempfile.TemporaryDirectory() as tmp:
    mine = str(Path(tmp) / 'player_presets.json')
    check('no file: only the built-in presets', U.all_presets(mine) == U.PLAYER_PRESETS)
    check('save my preset', U.save_my_preset(mine, 'Wandering Bard', 'A bard.') == '')
    allp = U.all_presets(mine)
    check('mine listed after the built-ins, marked', list(allp)[-1] == 'Wandering Bard (mine)' and allp['Wandering Bard (mine)'] == 'A bard.', list(allp))
    check('overwrite my own preset', U.save_my_preset(mine, 'Wandering Bard', 'A better bard.') == '' and U.all_presets(mine)['Wandering Bard (mine)'] == 'A better bard.')
    check('built-in name refused', U.save_my_preset(mine, U.DEFAULT_PRESET, 'x') != '' and U.all_presets(mine)[U.DEFAULT_PRESET] == U.PLAYER_PRESETS[U.DEFAULT_PRESET])
    check('empty name or text refused', U.save_my_preset(mine, ' ', 'x') != '' and U.save_my_preset(mine, 'A', ' ') != '')
    check('saved as ASCII JSON', Path(mine).read_bytes().isascii())
    Path(mine).write_text('not json', encoding='utf-8')
    check('broken file: built-ins still work', U.all_presets(mine) == U.PLAYER_PRESETS)
check('presets file is in the user folder, not the mod', U.MY_PRESETS.startswith(U.user_folder()))

# test_voices: Mantella's voice types listed; anything else is a custom voice with a TTS heads-up
with tempfile.TemporaryDirectory() as tmp:
    base = Path(tmp) / 'c.csv'
    with open(base, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['name', 'voice_model', 'bio', 'race', 'base_id'])
        w.writeheader()
        for n, v in (('A', 'MaleNord'), ('B', 'FemaleSultry'), ('C', 'MaleNord'), ('D', '')):
            w.writerow({'name': n, 'voice_model': v, 'bio': '', 'race': 'Nord', 'base_id': ''})
    voices = U.known_voices(str(base))
    check('known voices: unique, sorted, no blanks', voices == ['FemaleSultry', 'MaleNord'], voices)
    check('known voice: no warning (any case)', U.custom_voice_warning('malenord', voices, 'XTTS') == '')
    check('empty voice: no warning', U.custom_voice_warning('', voices, 'XTTS') == '')
    warn = U.custom_voice_warning('Cubbi', voices, 'XTTS')
    check('custom voice: heads-up naming the TTS', 'custom voice' in warn.lower() and 'XTTS' in warn, warn)

# test_optimize: the model rewrites the bio (default facts kept, in character, fewer tokens); reply cleaned and capped
asked = []
out = U.optimize_bio(lambda s, t: asked.append((s, t)) or "Here is the optimized bio:\n```\nAdrianne smiths in Whiterun.\n```", 'Adrianne', 'Default: she smiths.', 'Mine: she smiths and flirts.')
check('optimize: both bios sent', 'Default: she smiths.' in asked[0][1] and 'Mine: she smiths and flirts.' in asked[0][1], asked)
check('optimize: asks to stay in character and save tokens', 'in character' in asked[0][0].lower() and 'token' in asked[0][0].lower(), asked[0][0])
check('optimize: preface and fences removed', out == 'Adrianne smiths in Whiterun.', out)
asked.clear()
U.optimize_bio(lambda s, t: asked.append((s, t)) or 'Nyri hunts.', 'Nyri', '', 'rough notes: dunmer hunter, shy')
check('optimize custom NPC: notes become a bio, no default block', 'DEFAULT BIO' not in asked[0][1] and 'rough notes' in asked[0][1], asked)
check('optimize: errors reported, not raised', U.optimize_bio(lambda s, t: 1 / 0, 'A', '', 'x').startswith('Could not'))
asked.clear()
U.optimize_player(lambda s, t: asked.append((s, t)) or 'A tall Nord.', 'travelling bard, world tree')
check('optimize player: third person, never you', 'third person' in asked[0][0] and "never 'you'" in asked[0][0], asked[0][0])
check('optimize player: lore and perception rules', 'lore' in asked[0][0].lower() and 'mortal' in asked[0][0].lower() and 'world tree' in asked[0][1], asked)

# test_override_state: whether the override is in use by the running Mantella right now
with tempfile.TemporaryDirectory() as tmp:
    ov = Path(tmp)
    (ov / 'Lydia.json').write_text(json.dumps({'name': 'Lydia', 'race': 'Nord', 'bio': 'Sworn.'}), encoding='utf-8')
    lydia, alvor_row = {'name': 'Lydia', 'race': 'Nord'}, {'name': 'Alvor', 'race': 'Nord'}
    check('no override: default bio', U.override_state(alvor_row, str(ov), None, 0)[0] == 'none')
    check('saved before Mantella started: active', U.override_state(lydia, str(ov), None, time.time() + 60)[0] == 'active')
    check('saved after start, not applied: pending', U.override_state(lydia, str(ov), None, 0)[0] == 'pending')
    check('running Mantella has it: active', U.override_state(lydia, str(ov), lambda r: 'Sworn.', 0)[0] == 'active')
    check('running Mantella has an older bio: pending', U.override_state(lydia, str(ov), lambda r: 'Old.', time.time() + 60)[0] == 'pending')



# test_player_description: read and written through Mantella's own setting, so config.ini and the reload follow
class Value:
    def __init__(self):
        self.sets = 0
        self._v = 'A tall Nord.'
    @property
    def value(self):
        return self._v
    @value.setter
    def value(self, v):
        self.sets += 1
        self._v = v
class Defs:
    def __init__(self):
        self.v = Value()
    def get_config_value_definition(self, identifier):
        if identifier != 'player_character_description':
            raise Exception('unknown ' + identifier)
        return self.v
class Config:
    def __init__(self):
        self.definitions = Defs()
cfg = Config()
check('player description read', U.player_description(cfg) == 'A tall Nord.')
check('player description saved', U.save_player_description(cfg, '  A short Breton.\n') and cfg.definitions.v.value == 'A short Breton.')
sets = cfg.definitions.v.sets
check('unchanged text: not written again', not U.save_player_description(cfg, 'A short Breton.') and cfg.definitions.v.sets == sets)
check('no config: empty, never raises', U.player_description(None) == '' and not U.save_player_description(None, 'x'))
# test_register_page_or_fallback: own tab when the exe knows ui_page; an older exe keeps the editor in the Living World tab
import living_world
class Api:
    def __init__(self, known):
        self.known, self.hooks = known, {}
    def on(self, hook, fn):
        if hook not in self.known:
            raise ValueError(hook)
        self.hooks[hook] = fn
    def usage_log(self):
        return []
new, old = Api({'system_parts', 'filter_tools', 'extra_user_text', 'summarize', 'memory_text', 'conversation_limit', 'ui_tab', 'ui_page'}), \
           Api({'system_parts', 'filter_tools', 'extra_user_text', 'summarize', 'memory_text', 'conversation_limit', 'ui_tab'})
living_world.register(new); living_world.register(old)
check('new exe: four tabs of our own, no extra Living World tab', 'ui_page' in new.hooks and 'ui_tab' not in new.hooks, list(new.hooks))
check('old exe: still registers, no own tab', 'ui_page' not in old.hooks and 'ui_tab' in old.hooks)
check('user folder follows custom_user_folder.ini', U.user_folder(ini_text='[UserFolder]\ncustom_user_folder = E:/MantellaUser\n') == 'E:/MantellaUser')

print('RESULT: ' + ('ALL PASS' if not FAILS else f'{len(FAILS)} FAILED: {FAILS}'))
sys.exit(1 if FAILS else 0)
