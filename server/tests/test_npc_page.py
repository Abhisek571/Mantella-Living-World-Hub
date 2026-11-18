"""Offline tests for the NPCs page (server/living_world/npc_page_ui.py): every section's view and action with a
temporary save, the mismatch lines, the delete confirm step, and that the page builds with optional parts absent.
Run with a Python 3.11: test_npc_page.py <repo server dir>"""
import json, os, sys, tempfile
from pathlib import Path

SERVER = Path(sys.argv[1])
sys.path.insert(0, str(SERVER))
from living_world import (archive, arcs, bio_evolve, characters as C, command, embed, facts_history as F, lw_state, memory,
                          memory_ui, npc_page_ui as P, release, ui_overrides as U, ui_tab)
embed.use(None)

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)) if not cond else ''))
    if not cond:
        FAILS.append(name)


class Comp:
    def __init__(self, kind, *a, **k):
        self.kind, self.args, self.kwargs, self.fns = kind, a, k, []
    def __enter__(self):
        return self
    def __exit__(self, *e):
        return False
    def _on(self, event):
        def bind(fn=None, inputs=None, outputs=None, **k):
            self.fns.append((event, fn, inputs or [], outputs or []))
            return self
        return bind
    def __getattr__(self, event):  # click, change, then, submit
        return self._on(event)
class Gr:
    def __init__(self):
        self.made = []
    def update(self, **k):
        return k
    def Info(self, text):
        pass
    def __getattr__(self, kind):
        def make(*a, **k):
            c = Comp(kind, *a, **k)
            self.made.append(c)
            return c
        return make


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    conv = tmp / 'conversations'
    (conv / 'P1').mkdir(parents=True)
    lw_state.DATA_DIR = str(tmp / 'channel')
    os.makedirs(tmp / 'channel' / 'npc')
    C.PATH = str(tmp / 'chars.json')
    csv = tmp / 'skyrim_characters.csv'
    csv.write_text('name,voice_model,bio,race,base_id,ref_id\n'
                   'Lydia,FemaleEvenToned,Lydia is a housecarl.,Nord,0A2C94,0A2C8E\n'
                   'Hulda,FemaleSultry,Hulda runs the Bannered Mare.,Nord,013BA3,013BA4\n', encoding='utf-8')
    P.CSV, P.OVERRIDES, P.PRESETS = str(csv), str(tmp / 'overrides'), str(tmp / 'presets.json')
    U.DEFAULT_BACKUPS = str(tmp / 'overrides_removed')
    memory_ui.DEFAULT_BACKUPS = str(tmp / 'memory_removed')
    memory_ui.delete_one.__defaults__ = (str(tmp / 'memory_removed'),)
    (tmp / 'channel' / 'npc' / '0A2C94.json').write_text(json.dumps({
        'string': {'name': 'Lydia', 'race': 'Nord', 'sex': 'female', 'home': 'Breezehome', 'hold': 'Whiterun',
                   'ref_id': '000A2C8E', 'maras_status': ''},
        'int': {'follower': 1, 'maras_on': 1, 'minor': 0}}), encoding='utf-8')
    store = memory.MemoryStore(str(conv), 'P1')
    store.save('Lydia', '0A2C8E', dict(memory.empty(), recent=[
        {'day': 3, 'hour': 9, 'text': 'We fought a dragon at the western watchtower.', 'witnesses': ['Lydia']},
        {'day': 4, 'hour': 20, 'text': 'The player bought me a sweetroll.', 'witnesses': ['Lydia'], 'spell': "while under the player's spell"},
        {'day': 5, 'hour': 12, 'text': 'Hulda told me about the Companions.', 'witnesses': ['Lydia'], 'source': 'told', 'told_by': 'Hulda'}]))
    # an NPC of your own, not in Mantella's list and with no memories: listed, without a reference id
    U.save_override(P.OVERRIDES, {'name': 'Auri', 'race': 'Wood Elf', 'base_id': '', 'bio': '', 'voice_model': ''},
                    {'bio': 'Auri is a ranger.'}, str(csv))

    # --- who --------------------------------------------------------------------------------------------------------
    people = P.npc_list(str(conv), 'P1', followers=set())
    labels = [p['label'] for p in people]
    check('who remembers you comes first', labels[0] == 'Lydia' and people[0]['has'] and people[0]['ref_id'] == '0A2C8E', people[:2])
    check("everyone in Mantella's list is listed", 'Hulda' in labels)
    check('your own NPC is listed without a reference id', any(p['name'] == 'Auri' and p['ref_id'] == '' for p in people), people)
    check('only who remembers you', [p['label'] for p in P.npc_list(str(conv), 'P1', True, followers=set())] == ['Lydia'])
    ctx = P.context(str(conv), 'P1', 'Lydia')
    check('picked NPC resolved with their row and save', ctx.row.get('bio') == 'Lydia is a housecarl.' and ctx.store is not None)
    check('live game values read', ctx.speaker.get('home') == 'Breezehome' and ctx.speaker['ref_id'] == '0A2C8E', ctx.speaker)
    check('an unknown label is no NPC', P.context(str(conv), 'P1', 'Nobody') is None)
    empty = P.load_view(None)
    check('no NPC: editor hidden', empty['editor'] == {'__update__': {'visible': False}})
    full = P.load_view(ctx)
    check('every section filled', all(k in full for k in ('pv_text', 'bio', 'b_race', 'n_text', 'f_table', 'm_table', 'c_list', 'k_text')),
          sorted(full))
    check('per-save part shown with a reference id', full['saved_part'] == {'__update__': {'visible': True}} and not full['no_ref'])
    auri = P.context(str(conv), 'P1', 'Auri')
    view = P.load_view(auri)
    check('no reference id: per-save part hidden, told why', view['saved_part'] == {'__update__': {'visible': False}}
          and 'reference id' in view['no_ref'] and view['bio'] == 'Auri is a ranger.', view.get('no_ref'))
    check('no reference id: per-save actions refuse', P.save_now(auri, 'x', False, '') == P.NO_REF_NOTE
          and P.delete_memory(auri, 'x #1', True) == P.NO_REF_NOTE)
    check('knows about: nothing in the world log yet', full['k_text'] == 'They know of no event in the world log yet.'
          and full['k_table'] == [], full['k_text'])

    # --- 1. preview ---------------------------------------------------------------------------------------------------
    pv = P.preview_view(ctx)
    check('preview says it is rebuilt', pv['pv_note'] == P.REBUILT_NOTE, pv['pv_note'])
    check('preview in order: personality, background, memories', pv['pv_text'].index('=== Personality ===') <
          pv['pv_text'].index('=== Background and Now ===') < pv['pv_text'].index('=== Memories ===')
          and 'Lydia is a housecarl.' in pv['pv_text'], pv['pv_text'][:400])

    # --- 2. personality -------------------------------------------------------------------------------------------------
    check('empty bio not saved', 'empty' in P.save_personality(ctx, '  ', ''))
    check('unchanged bio: nothing changed', P.save_personality(ctx, 'Lydia is a housecarl.', 'FemaleEvenToned') == 'Nothing changed.')
    said = P.save_personality(ctx, 'Lydia is my housecarl and sworn sword.', 'FemaleEvenToned')
    check('bio saved as an override', 'Saved' in said and U._own_bio({'name': 'Lydia', 'race': 'Nord'}, P.OVERRIDES), said)
    ctx = P.context(str(conv), 'P1', 'Lydia')
    pers = P.personality_view(ctx)
    check('page shows the override', pers['bio'] == 'Lydia is my housecarl and sworn sword.' and 'Override' in pers['badge'], pers['badge'])
    check('versions offer the default', U.DEFAULT_VERSION in pers['version']['__update__']['choices'])
    check('preset saved', 'Saved as' in P.save_preset(ctx, 'Sworn', 'Lydia is sworn to me.'))
    check('preset listed', 'Sworn' in P.personality_view(ctx)['version']['__update__']['choices'])
    check('preset deleted', 'deleted' in P.delete_preset(ctx, 'Sworn') and 'Sworn' not in P.personality_view(ctx)['version']['__update__']['choices'])
    check('default is not a preset to delete', 'Pick one' in P.delete_preset(ctx, U.DEFAULT_VERSION))
    text, said = P.optimize(ctx, None, 'x')
    check('optimize without a model says so', text == '' and 'newer' in said)
    text, said = P.optimize(ctx, lambda s, t: 'Lydia is a loyal housecarl.', 'x')
    check('optimize proposes, saves nothing', text == 'Lydia is a loyal housecarl.' and 'Proposal' in said
          and U._own_bio({'name': 'Lydia', 'race': 'Nord'}, P.OVERRIDES) == 'Lydia is my housecarl and sworn sword.')
    check('reset to default', 'back to' in P.reset_personality(ctx) and not U._own_bio({'name': 'Lydia', 'race': 'Nord'}, P.OVERRIDES))
    check('reset again: nothing to reset', 'no override' in P.reset_personality(P.context(str(conv), 'P1', 'Lydia')))
    check("new NPC: one in Mantella's list refused", 'already' in P.new_npc('Hulda', 'Nord', 'x'))
    check('new NPC saved', P.new_npc('Serana Two', 'Nord', 'A vampire.') == '' and
          any(p['name'] == 'Serana Two' for p in P.npc_list(str(conv), 'P1', followers=set())))
    check('apply now without Mantella running', 'next start' in P.apply_overrides(None))
    ctx = P.context(str(conv), 'P1', 'Lydia')

    # --- 3. background --------------------------------------------------------------------------------------------------
    bg = P.background_view(ctx)
    check('background from the game', bg['b_race'] == 'Nord' and bg['b_sex'] == 'female' and 'Breezehome' in bg['b_game'], bg)
    flags = [False] * len(C.FLAGS)
    flags[C.FLAG_KEYS.index('never_intimate')] = True
    said = P.save_background(ctx, 'Nord', 'female', bg['b_role'], False, 'follows Kynareth', 'loyalty; will not steal',
                             bg['b_stances'], 'Favourite food: sweetrolls', flags)
    entry = C.entry_for('Lydia', 'Nord')
    check('background saved', 'Saved' in said and entry['religion'] == 'follows Kynareth' and entry['values'] == 'loyalty; will not steal'
          and entry['custom'] == 'Favourite food: sweetrolls' and entry['flags'] == {'never_intimate': True}, (said, entry))
    check('background view reads it back', P.background_view(ctx)['b_values'] == 'loyalty; will not steal'
          and P.background_view(ctx)['flag_never_intimate'] is True)
    check('reset background keeps flags', 'back to' in P.reset_background(ctx) and C.entry_for('Lydia', 'Nord') == dict(
        C.clean({'flags': {'never_intimate': True}}), name='Lydia', race='Nord'), C.entry_for('Lydia', 'Nord'))

    # --- 4. now and its mismatch line -----------------------------------------------------------------------------------
    said = P.save_now(ctx, 'Lydia is married to the player and lives in Breezehome.', True, 'She looks tired.')
    state = bio_evolve.load(store, 'Lydia', '0A2C8E')
    check('Now saved and locked', 'Saved' in said and state['text'].startswith('Lydia is married') and state['locked']
          and state['others'] == 'She looks tired.', state)
    now = P.now_view(ctx)
    check('mismatch line beside Now', 'Now says married to the player; the game says not married' in now['n_mismatch'], now['n_mismatch'])
    check('mismatch line is red', 'lw-red' in now['n_mismatch'])
    check('locked Now is not marked to rewrite', 'locked' in P.rewrite_soon(ctx))
    P.save_now(ctx, 'Lydia guards the player.', False, '')
    check('no mismatch when Now agrees', P.now_view(ctx)['n_mismatch'] == '')
    check('rewrite after next talk', 'rewritten' in P.rewrite_soon(ctx) and bio_evolve.load(store, 'Lydia', '0A2C8E')['due'])
    check('status shows the reason', 'Rewritten after the next talk' in P.now_view(ctx)['n_status'])
    bio_evolve.add_gap(store, 'Lydia', '0A2C8E', 'Lydia has no memory of day 3, and it frightens her.', 3)
    check('gap lines shown', 'no memory of day 3' in P.now_view(ctx)['n_gaps'])
    check('gap lines cleared', P.clear_gaps(ctx) == '1 gap line(s) cleared.' and P.clear_gaps(ctx) == 'There were no gap lines.')
    check('Now reset', 'cleared' in P.reset_now(ctx) and bio_evolve.load(store, 'Lydia', '0A2C8E')['text'] == '')

    # --- 5. facts history ------------------------------------------------------------------------------------------------
    fv = P.facts_view(ctx)
    check('empty history explains itself', fv['f_table'] == [] and 'next talk' in fv['f_note'])
    said = P.add_fact(ctx, 'Custom line', 'Afraid of spiders', True, 10)
    fv = P.facts_view(ctx)
    values = [r[1] for r in fv['f_table']]
    check('custom line added, dated, and the game lines written down', 'Added' in said and 'Afraid of spiders' in values
          and any('Breezehome' in v for v in values), fv['f_table'])
    check('custom line kept in Background for the next talk', 'Afraid of spiders' in C.entry_for('Lydia', 'Nord')['custom'])
    mine = next(c for c in fv['f_pick']['__update__']['choices'] if 'Afraid of spiders' in c)
    game_line = next(c for c in fv['f_pick']['__update__']['choices'] if 'Breezehome' in c)
    check('hide a line from them', 'no longer know' in P.set_fact_visible(ctx, mine, False) and not P.fact_visible(ctx, mine))
    check('a hidden line is not sent', 'Afraid of spiders' not in '\n'.join(F.background_lines(store, ctx.speaker, ctx.player, C.entry_for('Lydia', 'Nord'))))
    check("the game's lines cannot be hidden", 'cannot be hidden' in P.set_fact_visible(ctx, game_line, False))
    check("the game's lines cannot be ended", 'belongs to the game' in P.end_fact(ctx, game_line, 11))
    check('your line ended', P.end_fact(ctx, mine, 11).startswith('Ended') and 'Afraid' not in C.entry_for('Lydia', 'Nord').get('custom', ''))
    check('an ended line stays in the table as ended', any(r[1] == 'Afraid of spiders' and r[4] == 'ended' for r in P.facts_view(ctx)['f_table']))
    said = P.add_fact(ctx, 'Belief: home', 'Lakeview Manor', True, 12)
    fv = P.facts_view(ctx)
    check('a belief over the game is noted', 'game is not changed' in said and C.entry_for('Lydia', 'Nord')['pinned'].get('home') == 'Lakeview Manor')
    check('belief mismatch shown in red', 'A belief line says Lakeview Manor; the game says Breezehome' in fv['f_mismatch'], fv['f_mismatch'])
    check('belief mismatch beside Background too', 'Lakeview Manor' in P.background_view(ctx)['b_mismatch'])
    check('empty line refused', 'Write the line' in P.add_fact(ctx, 'Custom line', ' ', True, 12))

    # --- 6. memories -----------------------------------------------------------------------------------------------------
    mv = P.memories_view(ctx)
    rows = {r[2]: r for r in mv['m_table']}
    check('memories listed newest first', mv['m_table'][0][2] == 'Hulda told me about the Companions.', mv['m_table'][0])
    check('source shown', rows['Hulda told me about the Companions.'][3] == 'told by Hulda' and rows['We fought a dragon at the western watchtower.'][3] == 'seen')
    check('spell label shown', rows['The player bought me a sweetroll.'][4] == "while under the player's spell")
    check('state and importance shown', rows['We fought a dragon at the western watchtower.'][5] == 'in mind' and isinstance(rows['We fought a dragon at the western watchtower.'][6], float))
    check('spell label reaches the prompt', "(while under the player's spell) The player bought me a sweetroll." in memory.render(store.load('Lydia', '0A2C8E')))
    check('search', [r[2] for r in P.memories_view(ctx, 'dragon')['m_table']] == ['We fought a dragon at the western watchtower.']
          and '1 match' in P.memories_view(ctx, 'dragon')['m_count'])
    check('mood line shown', mv['m_mood'].startswith('**Mood:**'))
    pick = lambda text: next(c for c in P.memories_view(ctx)['m_pick']['__update__']['choices'] if text in c)
    check('picked memory text for editing', P.memory_text(ctx, pick('dragon')) == 'We fought a dragon at the western watchtower.')
    said = P.edit_memory(ctx, pick('dragon'), 'We fought a dragon at the western watchtower; I nearly fell.')
    check('memory edited, day kept', 'Saved' in said and any(e['text'].endswith('I nearly fell.') and e['day'] == 3 for e in store.load('Lydia', '0A2C8E')['recent']))
    check('empty edit refused', 'empty' in P.edit_memory(ctx, pick('dragon'), ''))
    said = P.hide_memory(ctx, pick('sweetroll'))
    check('memory hidden', said.startswith('Hidden') and 'sweetroll' not in memory.render(store.load('Lydia', '0A2C8E')))
    check('hidden state shown', any(r[5] == 'hidden' for r in P.memories_view(ctx)['m_table']))
    check('hide is in the true record', any(r['kind'] == 'forget' for r in release.record_rows(store, 'Lydia', '0A2C8E')))
    check('memory unhidden', 'again' in P.unhide_memory(ctx, pick('sweetroll')) and 'sweetroll' in memory.render(store.load('Lydia', '0A2C8E')))
    check('unhide twice: told', 'not hidden' in P.unhide_memory(ctx, pick('sweetroll')))
    check('delete asks first: cancelled deletes nothing', P.delete_memory(ctx, pick('Hulda told'), False) == 'Nothing deleted.'
          and any('Hulda told' in e['text'] for e in store.load('Lydia', '0A2C8E')['recent']))
    said = P.delete_memory(ctx, pick('Hulda told'), True)
    check('delete after yes', said.startswith('Deleted') and not any('Hulda told' in m['text'] for m in P.all_memories(store, 'Lydia', '0A2C8E')), said)
    check('delete is in the true record', any(r['kind'] == 'delete' for r in release.record_rows(store, 'Lydia', '0A2C8E')))
    check('delete keeps a backup', os.listdir(memory_ui.DEFAULT_BACKUPS))
    P.hide_memory(ctx, pick('sweetroll'))
    said = P.delete_memory(ctx, pick('sweetroll'), True)
    check('a hidden memory can be deleted too', said.startswith('Deleted') and not any('sweetroll' in m['text'] for m in P.all_memories(store, 'Lydia', '0A2C8E')), said)
    said = P.add_memory(ctx, '7 | 18 | We watched the sunset over Whiterun.\nThe player gave me a shield.', 'told', 'Farengar')
    texts = {e['text']: e for e in store.load('Lydia', '0A2C8E')['recent']}
    check('memories added, one per line', said.startswith('2 memory') and texts['We watched the sunset over Whiterun.']['day'] == 7
          and texts['The player gave me a shield.']['told_by'] == 'Farengar', said)
    lines, said = P.notes_to_lines(ctx, lambda s, t: '{"memories": [{"day": 8, "hour": 9, "text": "We drank mead."}], "feeling": ""}', 'we drank')
    check('notes become lines to check first', lines == '8 | 9 | We drank mead.' and 'Check them' in said, (lines, said))
    check('feeling saved', 'Saved' in P.save_feeling(ctx, 'Trusts the player.') and store.load('Lydia', '0A2C8E')['feeling'] == 'Trusts the player.')
    check('long-term notes saved', 'Saved' in P.save_long_term(ctx, [['oath', 'Sworn at Dragonsreach.'], ['', '']])
          and store.load('Lydia', '0A2C8E')['long_term'] == {'oath': 'Sworn at Dragonsreach.'})
    # stories
    check('new story with the picked memory', 'made' in P.new_arc(ctx, 'The shield', pick('shield')))
    arc = lambda name: next(c for c in P.memories_view(ctx)['a_pick']['__update__']['choices'] if c.startswith(name))
    check('story listed with its memory', '(1)' in arc('The shield'))
    check('story renamed', 'saved' in P.rename_arc(ctx, arc('The shield'), 'Gifts', 'Things the player gave her.')
          and P.arc_fields(ctx, arc('Gifts')) == ('Gifts', 'Things the player gave her.'))
    check('memory moved in', 'moved' in P.move_to_arc(ctx, pick('sunset'), arc('Gifts')) and '(2)' in arc('Gifts'))
    check('memory taken out', 'taken out' in P.take_from_arc(ctx, pick('sunset')) and '(1)' in arc('Gifts'))
    P.new_arc(ctx, 'Sunsets', pick('sunset'))
    check('stories merged', 'merged' in P.merge_arcs(ctx, arc('Gifts'), [arc('Sunsets')]) and '(2)' in arc('Gifts')
          and not any(c.startswith('Sunsets') for c in P.memories_view(ctx)['a_pick']['__update__']['choices']))
    check('story removed, memories stay', 'stay' in P.delete_arc(ctx, arc('Gifts')) and any('shield' in m['text'] for m in P.all_memories(store, 'Lydia', '0A2C8E')))
    check('story column shown', all(r[7] == '' for r in P.memories_view(ctx)['m_table']))

    # --- 7. commands ----------------------------------------------------------------------------------------------------
    cv = P.commands_view(ctx)
    check('no command: says so', 'No absolute command' in cv['c_list'] and cv['c_marriage']['__update__']['visible'] is False)
    data = command.load(store)
    data['commands'].append({'id': 'cmd1', 'key': 'k1', 'text': 'You love me.', 'given': 6.0, 'until': -1.0, 'hours': 0,
                             'npcs': [{'name': 'Lydia', 'ref_id': '0A2C8E'}], 'hidden': [], 'status': 'active'})
    command.save(store, data)
    cv = P.commands_view(ctx)
    check('command listed', 'You love me.' in cv['c_list'] and cv['c_pick']['__update__']['choices'] == ['You love me. #cmd1'])
    check('marriage tick hidden without Relationships', cv['c_marriage']['__update__']['visible'] is False)
    check('release asks first', P.release_one(ctx, 'You love me. #cmd1', 'Keeps believing', P.MODE_LABELS and next(iter(P.MODE_LABELS)),
                                              False, False, False) == 'Nothing released.' and command.load(store)['commands'])
    said = P.release_one(ctx, 'You love me. #cmd1', 'Keeps believing', next(iter(P.MODE_LABELS)), False, False, True)
    check('released', 'Released' in said and not command.load(store)['commands'], said)
    rec = P.commands_view(ctx)['c_record']
    check('true record shows the release', any(r[1] == 'release' and r[2] == 'You love me.' for r in rec), rec)
    check('forget asks first', P.forget_now(ctx, 'sunset', next(iter(P.MODE_LABELS)), False) == 'Nothing forgotten.')
    said = P.forget_now(ctx, 'We watched the sunset over Whiterun', next(iter(P.MODE_LABELS)), True)
    check('forget hides with a gap line', 'hidden' in said and bio_evolve.load(store, 'Lydia', '0A2C8E')['gaps'], said)
    check('forget all of them asks first', P.forget_everything(ctx, False) == 'Nothing deleted.')

    # --- 8. knows about -------------------------------------------------------------------------------------------------
    from living_world import news, worldlog
    lydia_p = worldlog.person('Lydia', '0A2C94', '0A2C8E')
    hulda_p = worldlog.person('Hulda', '013BA3', '013BA4')
    ev_seen = worldlog.log_event(store, 'custom', 'A dragon burned the Whiterun stables.', 'A dragon burned the Whiterun stables.',
                                 day=2, place={'town': 'Whiterun', 'hold': 'Whiterun'}, present=[lydia_p], size='big',
                                 event_id='ev-dragon')
    ev_other = worldlog.log_event(store, 'custom', 'Hulda threw a drunk out of the Bannered Mare.',
                                  'Hulda threw a drunk out of the Bannered Mare.', day=3, present=[hulda_p], event_id='ev-drunk')
    ev_wed = worldlog.log_event(store, 'marriage', 'Hulda has married the player.', 'Hulda has married the player.', day=3,
                                involved=[hulda_p], present=[hulda_p], event_id='ev-wed')
    check('knows: events logged', ev_seen and ev_other and ev_wed)
    kv = P.knows_view(ctx)
    texts = [r[2] for r in kv['k_table']]
    check('knows: the event they saw is listed with how', any('dragon' in t for t in texts)
          and any(r[3] == 'saw it' for r in kv['k_table']) and not any('drunk' in t for t in texts), kv['k_table'])
    check('knows: count line', kv['k_text'].startswith('They know of'), kv['k_text'])
    tell_choices = kv['k_tell_pick']['__update__']['choices']
    check('knows: events they could be told', any(c.endswith('#ev-drunk') for c in tell_choices)
          and not any(c.endswith('#ev-dragon') for c in tell_choices), tell_choices)
    dragon = next(c for c in kv['k_pick']['__update__']['choices'] if c.endswith('#ev-dragon'))
    who = P.who_knows(ctx, dragon)
    check('knows: who else knows, with the true record', 'Lydia' in who and 'What really happened' in who, who)
    check('knows: forget asks first', P.forget_known(ctx, dragon, False) == 'Nothing forgotten.')
    said = P.forget_known(ctx, dragon, True)
    kv = P.knows_view(ctx)
    check('knows: forgotten, shown as taken', 'no longer knows' in said
          and any('dragon' in r[2] and r[6] == 'taken from them' for r in kv['k_table']), (said, kv['k_table']))
    check('knows: forget needs a pick', P.forget_known(ctx, '', True) == 'Pick an event they know first.')
    drunk = next(c for c in tell_choices if c.endswith('#ev-drunk'))
    said = P.tell_known(ctx, drunk, 'Hulda')
    mem_texts = [e.get('text') for e in store.load('Lydia', '0A2C8E')['recent']]
    check('knows: told, one memory told by Hulda', 'told by Hulda' in said and any('drunk' in str(t) for t in mem_texts)
          and any(e.get('told_by') == 'Hulda' for e in store.load('Lydia', '0A2C8E')['recent']), (said, mem_texts))
    check('knows: told again adds nothing', 'Nothing added' in P.tell_known(ctx, drunk, 'Hulda'))
    check('knows: now listed as told', any('drunk' in r[2] and r[3] == 'told' and r[4] == 'Hulda' for r in P.knows_view(ctx)['k_table']))
    check('knows: a gone event is said', P.tell_known(ctx, 'x #nope', '') == 'That event is no longer in the world log.'
          and P.who_knows(ctx, 'x #nope') == 'That event is no longer in the world log.')
    wed = next(c for c in tell_choices if c.endswith('#ev-wed'))
    ctx._speaker = dict(ctx.speaker, minor=1)  # the same page with a child picked
    check('knows: a child is never told of a wedding', P.tell_known(ctx, wed, '') == 'A child is never told about that.')
    ctx._speaker = None
    noref = P.knows_view(auri)
    check('knows: no reference id, empty', noref['k_table'] == [] and noref['k_text'] == 'Nothing recorded yet.')

    # --- mismatch helper --------------------------------------------------------------------------------------------------
    lines = P.mismatch_lines([{'where': 'now', 'says': 'married to Inga', 'game': 'not married'},
                              {'where': 'custom', 'says': 'lives in Riften', 'game': 'Breezehome', 'text': 'Lives in Riften'},
                              {'where': 'now', 'says': 'married to Inga', 'game': 'not married'}])
    check('mismatch sentences, once each', lines == ['Now says married to Inga; the game says not married',
                                                     'A custom line says lives in Riften; the game says Breezehome ("Lives in Riften")'], lines)
    check('mismatch filter by place', P.mismatch_lines([{'where': 'event', 'says': 'x', 'game': 'y'}], ('now',)) == [])

    # --- the page builds and its buttons answer -----------------------------------------------------------------------------
    gr = Gr()
    P.build(gr, None, lambda: None, str(conv))
    buttons = {c.args[0]: c for c in gr.made if c.kind == 'Button' and c.args}
    check('page builds', {'Save bio', 'Save background', 'Save', 'Add line', 'Save edit', 'Delete', 'Release', 'Forget',
                          'Who else knows', 'Make them forget it', 'Tell them'} <= set(buttons), sorted(buttons))
    _, forget_k, inputs, _ = buttons['Make them forget it'].fns[0]
    check('knows: forget button has the confirm step', inputs[0].kind == 'Checkbox')
    out = forget_k(False, 'P1', 'Lydia', 'x #ev-drunk')
    check('knows: forget cancelled from the page', out[0] == 'Nothing forgotten.', out[:1])
    _, who_fn, _, _ = buttons['Who else knows'].fns[0]
    check('knows: who button answers', 'Hulda' in who_fn('P1', 'Lydia', 'x #ev-drunk'))
    check('warning on Now, Facts history and Memories', sum(1 for c in gr.made if c.kind == 'HTML' and c.args and 'This changes what they believe, not the game' in str(c.args[0])) == 4)  # and on Knows about
    pick_drop = next(c for c in gr.made if c.kind == 'Dropdown' and c.kwargs.get('label') == 'NPC (type to search)')
    check('NPC list filled at start', 'Lydia' in pick_drop.kwargs['choices'])
    _, save_now_fn, inputs, outputs = buttons['Save'].fns[0]
    out = save_now_fn('P1', 'Lydia', 'Lydia keeps watch.', False, '')
    check('a button reports in its status line and refreshes its section', 'Saved' in out[0] and len(out) == len(outputs)
          and bio_evolve.load(store, 'Lydia', '0A2C8E')['text'] == 'Lydia keeps watch.', out[:2])
    out = save_now_fn('P1', '', 'x', False, '')
    check('a button without an NPC says so and changes nothing', out[0] == P.NO_PICK and all(o == {} for o in out[1:]))
    _, delete_fn, inputs, outputs = buttons['Delete'].fns[0]
    check('delete has the confirm step', any(kind == 'click' for kind, *_ in buttons['Delete'].fns) and inputs[0].kind == 'Checkbox')
    out = delete_fn(False, 'P1', 'Lydia', pick('shield'))
    check('delete cancelled from the page', out[0] == 'Nothing deleted.')
    old = P.save_now
    P.save_now = lambda *a: 1 / 0
    gr2 = Gr()
    P.build(gr2, None, lambda: None, str(conv))
    broken = next(c for c in gr2.made if c.kind == 'Button' and c.args and c.args[0] == 'Save').fns[0][1]
    out = broken('P1', 'Lydia', 'Text I typed', False, '')
    check('a failing save says so and leaves the typed text alone', 'did not work' in out[0] and all(o == {} for o in out[1:]), out[:2])
    P.save_now = old

# no save at all and no optional modules (no Relationships, no World, no Knowledge): the page and the tab still build
with tempfile.TemporaryDirectory() as tmp:
    lw_state.DATA_DIR = str(Path(tmp) / 'channel')
    gr = Gr()
    P.build(gr, None, lambda: None, str(Path(tmp) / 'none'))
    check('builds with no save', any(c.kind == 'Dropdown' and c.kwargs.get('label') == 'Save (your character)' for c in gr.made))
    ui_tab.MODULE_PAGES.clear()
    class Api:
        def usage_log(self):
            return []
    gr = Gr()
    ui_tab.build_pages(gr, Api(), None, lambda: None)
    check('tab builds without optional modules', [c.args[0] for c in gr.made if c.kind == 'Tab'] ==
          ['Living World', 'Status', 'NPCs', 'Player', 'Events', 'Settings'])

print(f"\n{len(FAILS)} failed" if FAILS else "\nall passed")
sys.exit(1 if FAILS else 0)
