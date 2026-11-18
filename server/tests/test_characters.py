"""Offline tests for the Characters page facts, factions and flags (server/living_world/characters.py), the Intimacy
check, and where they reach: the prompt, the action gates, absolute commands, the game's channel files, presets.
Run with a Python 3.11: test_characters.py <repo server dir>"""
import json, os, sys, tempfile
from pathlib import Path

SERVER = Path(sys.argv[1])
sys.path.insert(0, str(SERVER))
from living_world import action_filter, characters as C, command, data_io, lw_state, settings, ui_overrides as U, ui_tab

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)) if not cond else ''))
    if not cond:
        FAILS.append(name)


def ref(value):
    try:
        return int(str(value), 16) & 0xFFFFFF
    except (TypeError, ValueError):
        return None


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    C.PATH = str(tmp / 'living_world_characters.json')
    lw_state.DATA_DIR = str(tmp / 'channel')
    os.makedirs(lw_state.DATA_DIR)

    # --- storage -------------------------------------------------------------------------------------------------
    check('no file: empty', C.load() == {'version': 1, 'npcs': {}})
    entry = {'locked': {'race': 'Nord', 'sex': 'female'}, 'pinned': {'home': 'Breezehome'}, 'stances': {'Thalmor': 'hates', 'X': 'adores'},
             'custom': 'Favourite food: sweetrolls\n\n', 'flags': {'never_intimate': True, 'bogus': True, 'always_close': 'yes'}}
    check('saved', C.save_entry('Lydia', 'Nord', entry))
    got = C.entry_for('Lydia', 'Nord')
    check('clean keeps known parts only', got['stances'] == {'Thalmor': 'hates'} and got['flags'] == {'never_intimate': True}
          and got['custom'] == 'Favourite food: sweetrolls', got)
    check('same entry again is not rewritten', not C.save_entry('Lydia', 'Nord', entry))
    check('race spelled differently still found', C.entry_for('lydia', 'NORD') is not None)
    check('race unknown: the only entry with that name', C.entry_for('Lydia', '') is not None)
    check('flag read by name', C.flag({'name': 'Lydia'}, 'never_intimate') and not C.flag({'name': 'Lydia'}, 'always_close'))
    check('trades_without_asking getter, by name too', C.trades_without_asking('Lydia') is False)
    C.save_entry('Aela the Huntress', 'Nord', {'flags': {'trades_without_asking': True, 'ignore_commands': True}})
    check('trades_without_asking getter on', C.trades_without_asking('Aela the Huntress') and C.trades_without_asking({'name': 'Aela the Huntress'}))
    flags_file = json.loads((tmp / 'channel' / C.FLAGS_FILE).read_text(encoding='utf-8'))
    check('game flag file by lowercase name', flags_file == {'int': {'lydia|never_intimate': 1, 'aela the huntress|trades_without_asking': 1,
                                                                     'aela the huntress|ignore_commands': 1}}, flags_file)
    check('an empty entry is removed', C.save_entry('Lydia', 'Nord', {}) and C.entry_for('Lydia', 'Nord') is None)
    flags_file = json.loads((tmp / 'channel' / C.FLAGS_FILE).read_text(encoding='utf-8'))
    check('and its flags leave the game file', 'lydia|never_intimate' not in flags_file['int'], flags_file)
    Path(C.PATH).write_text('{broken', encoding='utf-8')
    check('a broken file reads as empty', C.load()['npcs'] == {})

    # --- live values and stances ---------------------------------------------------------------------------------
    npc = {'name': 'Lydia', 'race': 'NORD', 'sex': 'female', 'hold': 'Whiterun', 'home': 'Breezehome', 'follower': 1,
           'housecarl': 1, 'maras': 3, 'factions': ['Imperial Legion'], 'guard': 0}
    live = C.live_values(npc, 'Inga')
    check('married from M.A.R.A.S', live['partner'] == 'married to Inga', live)
    check('home with its hold, named as a hold (never as a town)', live['home'] == 'Breezehome, in Whiterun Hold', live)
    check('follower and housecarl role', live['follower'].startswith('yes') and live['role'] == 'housecarl to Inga', live)
    check('dating from the status name', C.live_partner({'maras_status': 'Dating'}, 'Inga') == 'dating Inga')
    check('vanilla spouse', C.live_partner({'spouse': 1}, 'Inga') == 'married to Inga')
    check('nobody: no partner', C.live_partner({'rank': 1}, 'Inga') == '')
    check('no follower field: nothing said', C.live_follower({}, 'Inga') == '')
    st = C.auto_stances(['Stormcloaks'])
    check('Stormcloak hates Legion and Thalmor', st == {'Stormcloaks': 'loves', 'Imperial Legion': 'hates', 'Thalmor': 'hates'}, st)
    check('Talos temple hates the Thalmor', C.auto_stances(['Temple of Talos'])['Thalmor'] == 'hates')
    guard = {'guard': 1, 'hold': 'Eastmarch'}
    check('guard members include their hold', C.live_members(guard) == ['Guards of Eastmarch'])
    check('Eastmarch guard sides with the Stormcloaks', C.auto_stances([], guard) == {'Stormcloaks': 'likes', 'Imperial Legion': 'dislikes'})
    world = {'events': [{'id': 'cw_finale_legion'}]}
    check('after the Legion won, every guard sides with it', C.auto_stances([], guard, world)['Imperial Legion'] == 'likes')

    # --- the prompt ----------------------------------------------------------------------------------------------
    C.save_entry('Lydia', 'Nord', {'pinned': {'home': 'Lakeview Manor'}, 'stances': {'Thalmor': 'neutral'},
                                   'custom': 'Favourite food: sweetrolls', 'locked': {'race': 'Nord'}})
    text = C.prompt_text([npc, {'name': 'Stranger', 'maras': 0}], 'Inga')
    check('facts block for the NPC with an entry', text.startswith('Facts about Lydia (always true'), text)
    check('pinned home wins over the game', '- Home: Lakeview Manor' in text and 'Breezehome' not in text, text)
    check('locked race kept, sex from the game until stored', '- Race: Nord' in text and '- Sex: female' in text, text)
    check('live partner, follower, member of', 'Partner: married to Inga' in text and 'Follower: yes' in text and 'Member of: Imperial Legion' in text, text)
    check('stances: pinned neutral wins over automatic', 'neutral Thalmor' in text and 'loves Imperial Legion' in text, text)
    check('custom fact line', '- Favourite food: sweetrolls' in text)
    check('no block for a stranger with nothing known', 'Stranger' not in text)
    spouse_only = C.prompt_text([{'name': 'Ysolda', 'maras': 3}], 'Inga')
    check('a spouse without an entry still gets the partner fact only', spouse_only.endswith('- Partner: married to Inga'), spouse_only)
    parts = C.add_to_parts({'background': '# Background\nLydia is a housecarl.'}, 'FACTS')
    check('facts above the bio, after the header', parts['background'] == '# Background\nFACTS\n\nLydia is a housecarl.', parts)
    check('remember_locked fills the sex once', C.remember_locked([npc]) == 1 and C.entry_for('Lydia', 'Nord')['locked'] == {'race': 'Nord', 'sex': 'female'})
    check('and not again', C.remember_locked([npc]) == 0)

    # --- action gates --------------------------------------------------------------------------------------------
    C.save_entry('Camilla Valerius', '', {'flags': {'bypass_intimacy': True}})
    C.save_entry('Mjoll', '', {'flags': {'always_close': True, 'never_intimate': True}})
    speakers = [{'name': 'Camilla Valerius', 'minor': 0, 'close': 0, 'intimate': 0}, {'name': 'Mjoll', 'minor': 0, 'close': 0, 'intimate': 0},
                {'name': 'Dorthe', 'minor': 1, 'close': 0, 'intimate': 0}, {'name': 'Faendal', 'minor': 0, 'close': 1, 'intimate': 0},
                {'name': 'Brenuin', 'minor': 0, 'close': 0, 'intimate': 0}]
    strict = {s['name']: s for s in C.final_limits(C.for_actions(speakers, 'lovers_only'))}
    check('always willing opens intimate', strict['Camilla Valerius']['intimate'] == 1)
    check('always close opens close', strict['Mjoll']['close'] == 1)
    check('lovers only: a friend is not intimate', strict['Faendal']['intimate'] == 0 and strict['Brenuin']['intimate'] == 0)
    adult = {s['name']: s for s in C.final_limits(C.for_actions(speakers, 'npc_decides'))}
    check('NPC decides: a friend and a stranger are offered it', adult['Brenuin']['intimate'] == 1 and adult['Faendal']['intimate'] == 1)
    check('Intimacy: never beats NPC decides', adult['Mjoll']['intimate'] == 0)
    check('a child is never close or intimate', adult['Dorthe']['intimate'] == 0 and adult['Dorthe']['close'] == 0)
    check('choice: never, willing (flag or hotkey), default',
          C.intimacy_choice({'name': 'Mjoll'}) == 'never' and C.intimacy_choice({'name': 'Camilla Valerius'}) == 'willing'
          and C.intimacy_choice({'name': 'Brenuin', 'allow_intimacy': 1}) == 'willing' and C.intimacy_choice({'name': 'Brenuin'}) == 'default')
    check('never wins over the hotkey', C.intimacy_choice({'name': 'Mjoll', 'allow_intimacy': 1}) == 'never')
    commanded = C.final_limits([dict(s, intimate=1, close=1) for s in speakers])
    check('never intimate beats a command, a child stays shut', {s['name']: s['intimate'] for s in commanded}['Mjoll'] == 0
          and {s['name']: s['close'] for s in commanded}['Dorthe'] == 0)
    gates = {'SexWithPlayer': 'intimate'}
    offered = action_filter.filter_actions([{'function': {'name': 'SexWithPlayer'}}], [adult['Mjoll']], gates)
    check('the filter keeps the scene from a never-intimate NPC', offered == [])
    check('the child rule still takes adult actions out', action_filter.filter_actions(
        [{'function': {'name': 'SexWithPlayer'}}], list(adult.values()), gates) == [])

    # an NPC the game has not confirmed as an adult (npc file missing, broken or without minor) is never intimate
    # (the reviewer's case: the greeting request of a first talk, before the game writes npc/<base>.json)
    for label, who in (('no file', {'base_id': '01A2B3'}), ('broken file / no minor key', {'name': 'Brenuin', 'close': 1}),
                       ('junk minor', {'name': 'Brenuin', 'minor': 'x'})):
        got = C.final_limits(C.for_actions([who], 'npc_decides'))[0]
        check(f'unknown age ({label}): not intimate, not close in NPC decides', got.get('intimate', 0) == 0 and got.get('close', 0) == 0, got)
        check(f'unknown age ({label}): the scene is not offered', action_filter.filter_actions(
            [{'function': {'name': 'SexWithPlayer'}}], [got], gates := {'SexWithPlayer': 'intimate'}) == [])
    flagged = C.final_limits(C.for_actions([{'name': 'Camilla Valerius', 'close': 1, 'intimate': 1}], 'npc_decides'))[0]
    check('unknown age: Always willing and a set gate are shut too', flagged['intimate'] == 0 and flagged['close'] == 0, flagged)
    group = C.final_limits(C.for_actions([speakers[4], {'base_id': '01A2B3'}], 'npc_decides'))
    check('group with one unknown speaker: nothing intimate for anyone', action_filter.filter_actions(
        [{'function': {'name': 'SexWithPlayer'}}], group, {'SexWithPlayer': 'intimate'}) == [])

    # --- the Intimacy setting ------------------------------------------------------------------------------------
    check('setting default NPC decides', settings.DEFAULTS['intimacy_check'] == 'npc_decides')
    sp = tmp / 'settings.json'
    sp.write_text(json.dumps({'intimacy_check': 'whatever'}), encoding='utf-8')
    check('unknown mode falls back', settings.load(str(sp))['intimacy_check'] == 'npc_decides')
    for old_value, new_value in (('strict', 'lovers_only'), ('relaxed', 'npc_decides'), ('any_adult', 'npc_decides'), ('lovers_only', 'lovers_only')):
        sp.write_text(json.dumps({'intimacy_check': old_value}), encoding='utf-8')
        check(f'stored {old_value} becomes {new_value}', settings.load(str(sp))['intimacy_check'] == new_value)
    check('mode from settings without the channel file', C.intimacy_mode({'intimacy_check': 'lovers_only'}) == 'lovers_only'
          and C.intimacy_mode({'intimacy_check': 'strict'}) == 'lovers_only' and C.intimacy_mode({}) == 'npc_decides')
    check('written for the game', C.write_intimacy_mode('lovers_only'))
    check('as 0', json.loads((tmp / 'channel' / C.INTIMACY_FILE).read_text(encoding='utf-8'))['int']['intimacy_check'] == 0)
    check('channel file wins (the MCM writes it too)', C.intimacy_mode({'intimacy_check': 'npc_decides'}) == 'lovers_only')
    check('old modes are not written', not C.write_intimacy_mode('any_adult'))
    for number, mode in ((0, 'lovers_only'), (1, 'npc_decides'), (2, 'npc_decides')):  # 2 = an older save's Any adult
        (tmp / 'channel' / C.INTIMACY_FILE).write_text(json.dumps({'int': {'intimacy_check': number}}), encoding='utf-8')
        check(f'the MCM value {number} is read back as {mode}', C.intimacy_mode({}) == mode)
    check('radio label to mode', ui_tab.intimacy_value('Lovers only') == 'lovers_only' and ui_tab.intimacy_value('NPC decides') == 'npc_decides'
          and ui_tab.intimacy_value(None, 'lovers_only') == 'lovers_only')
    # the MCM path end to end on this side: MLW_Channel.SetIntimacyCheck / SyncIntimacy save the file the way JsonUtil
    # writes it (tabs, other keys); the very next request offers by the new value, no restart and no cached copy
    adult_stranger = {'name': 'Hilde', 'minor': 0, 'close': 0}
    offered = lambda: action_filter.filter_actions([{'function': {'name': 'SexWithPlayer'}}],
                                                   C.final_limits(C.for_actions([adult_stranger], C.intimacy_mode({}))), {'SexWithPlayer': 'intimate'})
    jsonutil = lambda number: '{\n\t"float" : \n\t{\n\t},\n\t"int" : \n\t{\n\t\t"intimacy_check" : %d\n\t}\n}' % number
    (tmp / 'channel' / C.INTIMACY_FILE).write_text(jsonutil(1), encoding='utf-8')
    check('MCM NPC decides (file from the game): the scene is offered to an adult stranger', len(offered()) == 1)
    (tmp / 'channel' / C.INTIMACY_FILE).write_text(jsonutil(0), encoding='utf-8')
    check('MCM switched to Lovers only mid-session: the next request no longer offers it', offered() == [])
    check('the web page reads the same file (both sides in step)', C.intimacy_mode({'intimacy_check': 'npc_decides'}) == 'lovers_only')
    C.write_intimacy_mode('npc_decides')
    check('a web page save is written in the shape the game reads (int.intimacy_check = 1)',
          json.loads((tmp / 'channel' / C.INTIMACY_FILE).read_text(encoding='utf-8')) == {'int': {'intimacy_check': 1}} and len(offered()) == 1)
    os.remove(tmp / 'channel' / C.INTIMACY_FILE)

    # --- absolute commands ---------------------------------------------------------------------------------------
    C.save_entry('Aela the Huntress', 'Nord', {'flags': {'ignore_commands': True}})
    entry = {'refs': ['0001A2B3', '0001A2B4'], 'names': ['Aela the Huntress', 'Farkas']}
    bound = command.targets(entry, [], [], ref)
    check('a command never binds an NPC who ignores commands', [n['name'] for n in bound] == ['Farkas'], bound)
    check('ignores_commands by name', C.ignores_commands({'name': 'Aela the Huntress'}) and not C.ignores_commands({'name': 'Farkas'}))

    class Store:
        root = str(tmp / 'store')
    os.makedirs(Store.root, exist_ok=True)
    data = command.load(Store)
    data['commands'].append({'id': 'c1', 'status': 'active', 'text': 'Kneel.', 'npcs': [{'name': 'Aela the Huntress', 'ref_id': '1A2B3'},
                                                                                       {'name': 'Farkas', 'ref_id': '1A2B4'}]})
    command.save(Store, data)
    here = [{'name': 'Aela the Huntress', 'ref_id': '0001A2B3', 'minor': 0}, {'name': 'Farkas', 'ref_id': '0001A2B4', 'minor': 0}]
    found = command.in_force(Store, here, ref)
    check('a command given before the tick no longer applies to them', found and found[0][1] == ['Farkas'], found)
    unlocked = {s['name']: s for s in command.unlocked(Store, here, ref)}
    check('and opens no gate for them', 'commanded' not in unlocked['Aela the Huntress'] and unlocked['Farkas'].get('commanded') == 1)

    # --- the page's fields ---------------------------------------------------------------------------------------
    game = {'name': 'Lydia', 'race': 'Nord', 'sex': 'female', 'factions': ['Imperial Legion'], 'follower': 1, 'hold': 'Whiterun'}
    rows = C.stance_rows(None, game)
    check('stance table from the game', ['Imperial Legion', 'loves', False] in rows and ['Stormcloaks', 'hates', False] in rows, rows)
    pinned = C.pinned_stances(rows + [['Thalmor', 'hates', False], ['Stormcloaks', 'dislikes', 'false'], ['', 'hates', True],
                                      ['Imperial Legion', 'loves', True]], C.auto_stances(['Imperial Legion']))
    check('changed, added and ticked rows are pinned', pinned == {'Thalmor': 'hates', 'Stormcloaks': 'dislikes', 'Imperial Legion': 'loves'}, pinned)
    live = C.live_values(game, 'Inga')
    from living_world import npc_page_ui as P

    class PageNpc:  # what the NPCs page's Background section works on
        name, race, player, speaker = 'Lydia', 'Nord', 'Inga', game

        def entry(self):
            return C.entry_for('Lydia', 'Nord') or {}
    C.save_entry('Lydia', 'Nord', {})
    said = P.save_background(PageNpc(), 'Nord', 'female', live['role'], False, '', '', rows, '', [False] * len(C.FLAGS))
    check('nothing edited: no entry made of the game race and sex', 'Nothing to save' in said and C.entry_for('Lydia', 'Nord') is None, said)
    said = P.save_background(PageNpc(), 'Nord', 'female', 'Thane of Whiterun', False, 'follows Mara', '', rows, '',
                             [False] * (len(C.FLAGS) - 1) + [True])
    made = C.entry_for('Lydia', 'Nord')
    check('an edited role keeps itself', made['pinned'] == {'role': 'Thane of Whiterun'} and made['stances'] == {}, made)
    check('flags from the boxes', made['flags'] == {C.FLAG_KEYS[-1]: True}, made)
    check('religion saved', made.get('religion') == 'follows Mara', made)
    C.save_entry('Lydia', 'Nord', {})

    # --- presets carry all four parts; old ones still load ---------------------------------------------------------
    presets = tmp / 'npc_presets.json'
    presets.write_text(json.dumps({'npcs': {'lydia|nord': {'Old': 'An old bio.'}}, 'Shared': 'Any NPC bio.'}), encoding='ascii')
    row = {'name': 'Lydia', 'race': 'Nord'}
    check('old string preset still listed', U.npc_presets(str(presets), row) == {'Old': 'An old bio.', 'Shared (any NPC)': 'Any NPC bio.'})
    check('old preset has no profile', U.npc_preset_profile(str(presets), row, 'Old') is None)
    check('new preset saved with profile', U.save_npc_preset(str(presets), row, 'Wife', 'Lydia is my wife.', made) == '')
    check('new preset bio listed like the others', U.npc_presets(str(presets), row)['Wife'] == 'Lydia is my wife.')
    check('new preset profile back', U.npc_preset_profile(str(presets), row, 'Wife') == made)
    check('the old preset is kept', U.npc_presets(str(presets), row)['Old'] == 'An old bio.')
    check('deleting a new preset works', U.delete_npc_preset(str(presets), row, 'Wife') and 'Wife' not in U.npc_presets(str(presets), row))

    # --- game_npc finds the npc file by name ---------------------------------------------------------------------
    os.makedirs(tmp / 'channel' / 'npc', exist_ok=True)
    (tmp / 'channel' / 'npc' / '0A2C94.json').write_text(json.dumps({'string': {'name': 'Lydia', 'race': 'Nord'}, 'int': {'follower': 1},
                                                                      'stringList': {'factions': ['Imperial Legion']}}), encoding='utf-8')
    found = C.game_npc('lydia', 'Nord')
    check('game file by name, factions list flattened', found.get('follower') == 1 and found.get('factions') == ['Imperial Legion'], found)

    # --- export takes the characters file along with the overrides ---------------------------------------------
    user = tmp / 'user'
    paths = data_io.Paths(user=str(user), hub_settings=str(sp))
    os.makedirs(os.path.dirname(paths.characters), exist_ok=True)
    Path(paths.characters).write_text('{"version": 1, "npcs": {}}', encoding='utf-8')
    z = data_io.export_zip(str(tmp / 'out.zip'), paths, {'overrides'}, [])
    check('exported with the overrides part', 'overrides' in data_io.inspect_zip(z)['parts'])
    os.remove(paths.characters)
    data_io.import_zip(z, paths, {'overrides'}, [], str(tmp / 'backups'))
    check('imported back', os.path.isfile(paths.characters))

# --- module pages in the Living World tab (Knowledge's World Knowledge) -----------------------------------------
class Comp:
    def __init__(self, kind, *a, **k):
        self.kind, self.args, self.kwargs = kind, a, k
    def __enter__(self):
        return self
    def __exit__(self, *e):
        return False
    def click(self, *a, **k):
        return self
    def change(self, *a, **k):
        return self
    def then(self, *a, **k):
        return self
    def submit(self, *a, **k):
        return self
class Gr:
    def __init__(self):
        self.made = []
    def __getattr__(self, kind):
        def make(*a, **k):
            c = Comp(kind, *a, **k)
            self.made.append(c)
            return c
        return make
class Api:
    def usage_log(self):
        return []
class Cfg:
    class definitions:
        @staticmethod
        def get_config_value_definition(identifier):
            class V:
                value = ''
            return V
built = []
ui_tab.add_page('World Knowledge', lambda gr: built.append(gr.Markdown('packs')))
ui_tab.add_page('Broken', lambda gr: 1 / 0)
gr = Gr()
ui_tab.build_pages(gr, Api(), Cfg, lambda: None)
tabs = [c.args[0] for c in gr.made if c.kind == 'Tab']
check('module pages after Events, before Settings', tabs == ['Living World', 'Status', 'NPCs', 'Player', 'Events', 'World Knowledge', 'Broken', 'Settings'], tabs)
check('a module page that fails says so and the rest builds', built and any(c.kind == 'Markdown' and 'Broken could not be shown' in str(c.args[0]) for c in gr.made))
ui_tab.add_page('World Knowledge', lambda gr: None)
check('adding a page twice replaces it', [n for n, _ in ui_tab.MODULE_PAGES].count('World Knowledge') == 1)
ui_tab.MODULE_PAGES.clear()
gr = Gr()
ui_tab.build_pages(gr, Api(), Cfg, lambda: None)
check('without Knowledge: the pages', [c.args[0] for c in gr.made if c.kind == 'Tab'] == ['Living World', 'Status', 'NPCs', 'Player', 'Events', 'Settings'])
SECTIONS = ('Prompt preview', 'Personality', 'Background', 'Now', 'Facts history', 'Memories', 'Commands', 'Knows about')
tab_at = [i for i, c in enumerate(gr.made) if c.kind == 'Tab']
npcs = gr.made[next(i for i in tab_at if gr.made[i].args[0] == 'NPCs'):next(i for i in tab_at if gr.made[i].args[0] == 'Player')]
check('NPCs page has its sections in order', [c.args[0] for c in npcs if c.kind == 'Accordion' and c.args and c.args[0] in SECTIONS] == list(SECTIONS))
check('no second per-NPC editor elsewhere', not any(c.kind == 'Accordion' and c.args and c.args[0] in ('Facts (background)', 'Now (how they see things)') for c in gr.made))
check('settings page has the Intimacy check', any(c.kind == 'Radio' and c.kwargs.get('label') == 'Intimacy' for c in gr.made))

# D05: fields of a module that was removed are not trusted (Relationships: maras*, Followers: nff*)
spouse = {'maras_on': 1, 'maras_status': 'married', 'spouse': 0, 'nff': 1, 'follower': 0}
everything = [m[0] for m in ui_tab.MODULES]
check('M.A.R.A.S marriage and NFF party read while their modules are installed',
      C.player_kind(spouse, everything) == 'married' and C.live_follower(spouse, 'P', everything).startswith('yes'))
hub_only = ['Integration Hub']
check('...and not once Relationships and Followers are removed', C.player_kind(spouse, hub_only) == ''
      and C.live_follower(spouse, 'P', hub_only).startswith('no'))
check('...the vanilla marriage still counts then', C.player_kind(dict(spouse, spouse=1), hub_only) == 'married')

print(f"\n{len(FAILS)} failed" if FAILS else "\nall passed")
sys.exit(1 if FAILS else 0)
