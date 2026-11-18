"""Offline tests for the natural NPCs core: prompt order (bio -> Background -> Now -> memories -> commands), the Now
paragraph (bio_evolve.py), the facts history (facts_history.py), the Relationships contract files (contracts.py) and
forget / release (release.py, command.py).
Run with a Python 3.11: test_natural_npcs.py <repo server dir>"""
import json, os, sys, tempfile
from pathlib import Path

SERVER = Path(sys.argv[1])
sys.path.insert(0, str(SERVER))
import living_world
from living_world import (bio_evolve as B, characters as C, command, contracts, embed, facts_history as F, lw_state, memory,
                          npc_block, prompt_rules, release as R)
memory.SUMMARY_RETRY_SECONDS = 0
embed.use(None)

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)) if not cond else ''))
    if not cond:
        FAILS.append(name)


def REF(value):
    return living_world._ref(value)


def write_channel(name, data):
    with open(os.path.join(lw_state.DATA_DIR, name), 'w', encoding='utf-8') as f:
        json.dump(data, f)


YSOLDA = {'name': 'Ysolda', 'ref_id': '0001A69F', 'base_id': '013BAB', 'race': 'Nord', 'sex': 'female', 'minor': 0,
          'home': 'Breezehome', 'hold': 'Whiterun', 'follower': 0, 'maras_on': 1, 'maras_status': ''}
ALVOR = {'name': 'Alvor', 'ref_id': '00013BA0', 'base_id': '013BA0', 'race': 'Nord', 'sex': 'male', 'home': "Alvor's house", 'minor': 0}
SIGRID = {'name': 'Sigrid', 'ref_id': '00013BA1', 'base_id': '013BA1', 'race': 'Nord', 'sex': 'female', 'home': "Alvor's house", 'minor': 0,
          'maras_on': 1, 'maras_status': ''}

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    C.PATH = str(tmp / 'living_world_characters.json')
    lw_state.DATA_DIR = str(tmp / 'channel')
    os.makedirs(lw_state.DATA_DIR)
    write_channel('conversation.json', {'string': {'player': 'Inga'}, 'int': {'day': 40}})
    store = memory.MemoryStore(str(tmp / 'conversations'), 'P1')

    # --- contract files absent: nothing breaks --------------------------------------------------------------------
    check('no ties.json: empty', contracts.load_ties() == {})
    check('no marriages.json: empty', contracts.load_marriages() == [])
    check('no results: empty', contracts.load_results() == {})
    check('no marriage under a command without the file', contracts.made_under_command('013BA1') is None)

    # --- contract shapes (spec 12a) -------------------------------------------------------------------------------
    write_channel('ties.json', {'013BA1': {'name': 'Sigrid', 'home': "Alvor's house", 'day': 41,
                                           'ties': [{'kind': 'spouse', 'base': '013BA0', 'name': 'Alvor'},
                                                    {'kind': 'child', 'base': '013BA2', 'name': 'Dorthe'},
                                                    {'kind': 'bogus', 'base': '1', 'name': 'x'}]}})
    ties = contracts.load_ties()
    check('ties read, unknown kinds dropped', len(ties['013BA1']['ties']) == 2, ties)
    alvor_ties = contracts.ties_of('013BA0', ties)
    check('the other side of a tie: Alvor has a spouse Sigrid', {'kind': 'spouse', 'base': '013BA1', 'name': 'Sigrid'} in alvor_ties, alvor_ties)
    write_channel('marriages.json', {'marriages': [
        {'base': '013BA1', 'name': 'Sigrid', 'status': 'married', 'day': 41.5, 'commanded': 0, 'player': 'Other'},
        {'base': '13BA1', 'name': 'Sigrid', 'status': 'engaged', 'day': 41.2, 'commanded': 1, 'player': 'Inga'}]})
    rows = contracts.load_marriages()
    check("marriages: only this character's rows, base padded", len(rows) == 1 and rows[0]['base'] == '013BA1'
          and rows[0]['status'] == 'engaged', rows)
    rid = contracts.write_request('end_marriage', '13ba1', 'Sigrid', 'test')
    data = json.load(open(os.path.join(lw_state.DATA_DIR, 'requests.json'), encoding='utf-8'))
    check('requests.json: object with requests list', data['requests'][0]['id'] == rid and data['requests'][0]['base'] == '013BA1', data)
    check('a request row names the player character it is for', data['requests'][0].get('player') == 'Inga'
          and data['stringList']['player'] == ['Inga'], data)
    other = contracts.write_request('end_marriage', '013BA1', 'Sigrid', 'other', player='Mira')
    check("another character's waiting request is not reused", other and other != rid, other)
    data = json.load(open(os.path.join(lw_state.DATA_DIR, 'requests.json'), encoding='utf-8'))
    check('...and its row names that character', [r.get('player') for r in data['requests']] == ['Inga', 'Mira'], data)
    check('a waiting request is not added twice', contracts.write_request('end_marriage', '013BA1', 'Sigrid', 'again') == rid)
    write_channel('request_results.json', {'results': [{'id': rid, 'result': 'done'}]})
    check('results read', contracts.load_results() == {rid: 'done'})
    check('a handled request may be asked again', contracts.write_request('end_marriage', '013BA1', 'Sigrid', 'new') != rid)
    os.remove(os.path.join(lw_state.DATA_DIR, 'requests.json'))
    os.remove(os.path.join(lw_state.DATA_DIR, 'marriages.json'))

    # --- migration from the Characters page (old format), first talk -------------------------------------------------
    C.save_entry('Ysolda', 'Nord', {'pinned': {'home': 'Lakeview Manor'}, 'custom': 'Favourite food: sweetrolls',
                                    'values': 'honest trade; will not steal'})
    changes = F.sync_talk(store, [YSOLDA], 'Inga', 40)
    hist = F.history(store, 'Ysolda', '0001A69F')
    lines = {(l['fact'], l['owner']): l for l in hist['lines']}
    check('first sight writes lines down and reports no change', changes == {}, changes)
    check('custom line migrated as original', lines[('custom', 'user')]['cause'] == 'original'
          and lines[('custom', 'user')]['value'] == 'Favourite food: sweetrolls', hist)
    check('a pinned home becomes a belief; the game home stays, unknown to her', lines[('home', 'user')]['value'] == 'Lakeview Manor'
          and lines[('home', 'game')]['value'] == 'Breezehome, in Whiterun Hold' and not lines[('home', 'game')]['visible'], hist)
    bg = F.background_lines(store, YSOLDA, 'Inga', C.entry_for('Ysolda', 'Nord'))
    check('background: the belief, not the hidden game home', any('Home (as Ysolda sees it): Lakeview Manor' in l for l in bg)
          and not any('Breezehome' in l for l in bg), bg)
    check('background: values line, custom line, Thalmor default for a Nord', any('Cares about and will not do: honest trade' in l for l in bg)
          and '- Favourite food: sweetrolls' in bg and any('dislikes Thalmor' in l for l in bg), bg)
    found = F.mismatches(store, YSOLDA, 'Inga')
    check('mismatch: the believed home differs from the game', any(m['fact'] == 'home' and m['where'] == 'belief' for m in found), found)

    # --- a game-owned fact changes: displacement, Now due at talk start --------------------------------------------
    npc_block.talk_over()
    married = dict(YSOLDA, maras_status='married')
    text1 = npc_block.text(store, [married], [('Ysolda', '01A69F')], 'Inga', today=41)
    check('marriage to the player shows in Background', '- Partner: married to Inga' in text1, text1)
    check('a game-owned change marks Now due', any('Partner' in r for r in B.load(store, 'Ysolda', '01A69F')['due']),
          B.load(store, 'Ysolda', '01A69F'))
    hist = F.history(store, 'Ysolda', '0001A69F')
    link = next(l for l in hist['links'] if l['kind'] == 'married')
    check('the marriage link has cause game (no marriages.json)', link['cause'] == 'game', link)

    # cache stability: the same talk keeps the same text even when things change
    B.edit(store, 'Ysolda', '01A69F', text='Ysolda is newly married and happy.')
    text2 = npc_block.text(store, [dict(married, home='Somewhere else')], [('Ysolda', '01A69F')], 'Inga', today=41)
    check('the NPC part does not change mid-talk', text1 == text2)
    npc_block.talk_over()
    text3 = npc_block.text(store, [married], [('Ysolda', '01A69F')], 'Inga', today=41)
    check('the next talk sends the new Now after Background', 'Now, as Ysolda sees it: Ysolda is newly married' in text3
          and text3.index('Background facts about Ysolda') < text3.index('Now, as Ysolda sees it'), text3)

    # --- NPC spouse + marriage to the player under a command; release returns the on-hold line ----------------------
    write_channel('ties.json', {'013BA1': {'name': 'Sigrid', 'home': "Alvor's house",
                                           'ties': [{'kind': 'spouse', 'base': '013BA0', 'name': 'Alvor'},
                                                    {'kind': 'child', 'base': '013BA2', 'name': 'Dorthe'}]}})
    npc_block.talk_over()
    F.sync_talk(store, [SIGRID, ALVOR], 'Inga', 41)
    bg = F.background_lines(store, SIGRID, 'Inga')
    check("an NPC's own spouse and family show from ties.json", '- Spouse: Alvor' in bg and any('Dorthe (child)' in l for l in bg), bg)
    check('both sheets agree (one link)', '- Spouse: Sigrid' in F.background_lines(store, ALVOR, 'Inga'))
    # a command is given to Sigrid
    write_channel('commands.json', {'stringList': {'key': ['41.6-1'], 'text': ['Marry me'], 'refs': ['00013BA1'],
                                                   'names': ['Sigrid'], 'time': ['41.6'], 'player': ['Inga']}})
    values = {'command_hours': 0, 'command_model_check': False, 'command_forget_limit': 3}
    command.poll(store, [('Sigrid', '013BA1')], values, None, REF, 41, 'Inga', [SIGRID], background=False)
    rec = command.load(store)['commands'][0]
    check('a command marks Now due', any('absolute command was given' in r for r in B.load(store, 'Sigrid', '013BA1')['due']))
    hist = F.history(store, 'Sigrid', '00013BA1')
    check('a command adds an invisible facts line', any(l['fact'] == 'enchanted' and not l['visible'] and l['cause'] == f"command:{rec['id']}"
                                                        for l in hist['lines']), hist['lines'])
    check('the invisible line is not sent', not any('absolute command' in l for l in F.background_lines(store, SIGRID, 'Inga')))
    write_channel('marriages.json', {'marriages': [{'base': '013BA1', 'name': 'Sigrid', 'status': 'married', 'day': 41.7,
                                                    'commanded': 1, 'player': 'Inga'}]})
    F.sync_talk(store, [dict(SIGRID, maras_status='married'), ALVOR], 'Inga', 41)
    hist = F.history(store, 'Sigrid', '00013BA1')
    wed = next(l for l in hist['links'] if l['kind'] == 'married' and l['status'] == 'current')
    spouse = next(l for l in hist['links'] if l['kind'] == 'spouse')
    check('marriage under a command: its cause is the command', wed['cause'] == f"command:{rec['id']}", wed)
    check('her own spouse goes on hold, displaced by it', spouse['status'] == 'on_hold' and spouse['displaced_by'] == wed['cause'], spouse)
    sig_bg = F.background_lines(store, dict(SIGRID, maras_status='married'), 'Inga')
    check("Sigrid's sheet: whom she left to marry the player", '- Spouse: Alvor, whom Sigrid left to marry Inga' in sig_bg, sig_bg)
    alv_bg = F.background_lines(store, ALVOR, 'Inga')
    check("Alvor's sheet: who left him to marry the player (never 'former')", '- Spouse: Sigrid, who left him to marry Inga' in alv_bg
          and not any('Former' in l for l in alv_bg), alv_bg)
    # several partners
    F.sync_talk(store, [married, dict(SIGRID, maras_status='married')], 'Inga', 41)
    data = F.load(store)
    check('several partners of the player at once', sum(1 for l in data['links'] if l['kind'] == 'married' and l['status'] == 'current') == 2)
    check('the page knows a marriage was made under the command', R.releasable(store, [SIGRID])[0]['marriages'][0]['base'] == '013BA1')

    # memories under the command, then release: remembers, knows it was a spell
    mem = store.load('Sigrid', '013BA1')
    mem['recent'] = [{'day': 42, 'hour': 10, 'text': 'I married Inga in a daze.', 'command': rec['id'], 'importance': 0.9}]
    store.save('Sigrid', '013BA1', mem)
    out = R.release_command(store, rec['id'], 'spell', end_marriage=False, player='Inga', today=43, speakers=[SIGRID])
    check('release ok', out['ok'], out)
    hist = F.history(store, 'Sigrid', '00013BA1')
    spouse = next(l for l in hist['links'] if l['kind'] == 'spouse')
    wed = next(l for l in hist['links'] if l['kind'] == 'married')
    check('release ends the lines the command made', wed['status'] == 'ended' and
          all(l['status'] == 'ended' for l in hist['lines'] if l['cause'] == f"command:{rec['id']}"), hist)
    check('...and the on-hold spouse line comes back', spouse['status'] == 'current', spouse)
    check('memories of that time are marked as a spell', store.load('Sigrid', '013BA1')['recent'][0].get('spell') == "while under Inga's spell")
    state = B.load(store, 'Sigrid', '013BA1')
    check('Now is told the spell lifted', any('has lifted' in n for n in state['notes']) and state['due'], state)
    check('no marriage request unless asked', out['requests'] == [] and not os.path.exists(os.path.join(lw_state.DATA_DIR, 'requests.json')))
    check('the true record has the release', R.record_rows(store, 'Sigrid', '00013BA1')[0]['choice'] == 'spell')
    check('the command is gone, kept as ended with its choice', command.load(store)['commands'] == []
          and command.load(store)['ended'][-1]['choice'] == 'spell')
    check('memory labels follow the release choice', command.memory_labels(store, 'Inga')[rec['id']] == "while under Inga's spell")
    # the next sync while the game still says married: a game line again, not the command's
    F.sync_talk(store, [dict(SIGRID, maras_status='married')], 'Inga', 43)
    again = [l for l in F.load(store)['links'] if l['kind'] == 'married' and l['status'] == 'current' and F._is(l['a'], F._person(SIGRID))]
    check('a marriage still in the game after release comes back with cause game', again and again[0]['cause'] == 'game', again)

    # --- release with "forgets the whole period" and the marriage request ------------------------------------------
    write_channel('commands.json', {'stringList': {'key': ['44.0-2'], 'text': ['Love me'], 'refs': ['0001A69F'],
                                                   'names': ['Ysolda'], 'time': ['44.0'], 'player': ['Inga']}})
    write_channel('marriages.json', {'marriages': [{'base': '013BAB', 'name': 'Ysolda', 'status': 'married', 'day': 44.2,
                                                    'commanded': 1, 'player': 'Inga'}]})
    write_channel('conversation.json', {'string': {'player': 'Inga'}, 'int': {'day': 44}})
    command.poll(store, [('Ysolda', '01A69F')], values, None, REF, 44, 'Inga', [married], background=False)
    rec2 = command.load(store)['commands'][0]
    mem = store.load('Ysolda', '01A69F')
    mem['recent'] = [{'day': 40, 'hour': 9, 'text': 'Met Inga at the market.'},
                     {'day': 45, 'hour': 10, 'text': 'Inga and I kissed by the river.', 'command': rec2['id']},
                     {'day': 45, 'hour': 18, 'text': 'We danced all night.'}]
    store.save('Ysolda', '01A69F', mem)
    out = R.release_command(store, rec2['id'], 'forget', end_marriage=True, player='Inga', today=46, speakers=[married])
    shown = [e['text'] for e in store.load('Ysolda', '01A69F')['recent'] if not e.get('hidden')]
    check('forget the period: memories from the command on are hidden, older kept', shown == ['Met Inga at the market.'], shown)
    state = B.load(store, 'Ysolda', '01A69F')
    check('forget leaves a gap after Now by default', state['gaps'] and 'has no memory of day' in state['gaps'][0]['text']
          and 'frightens' in state['gaps'][0]['text'], state['gaps'])
    check('the gap is sent with Now', 'has no memory of' in B.now_text(store, 'Ysolda', '01A69F'))
    reqs = json.load(open(os.path.join(lw_state.DATA_DIR, 'requests.json'), encoding='utf-8'))['requests']
    check('end_marriage request written when asked', out['requests'] and reqs[-1]['kind'] == 'end_marriage' and reqs[-1]['base'] == '013BAB', reqs)
    rows = R.record_rows(store, 'Ysolda', '01A69F')
    check('the true record: the forget (days, by whom) and the release', any(r['kind'] == 'forget' and r['days'] and r['by'] for r in rows)
          and any(r['kind'] == 'release' and r['choice'] == 'forget' for r in rows), rows)

    # --- a plain forget from the Hub: clean leaves no gap -----------------------------------------------------------
    mem = store.load('Alvor', '013BA0')
    mem['recent'] = [{'day': 30, 'hour': 9, 'text': 'Inga bought a steel sword from me.'}]
    store.save('Alvor', '013BA0', mem)
    ids = [memory.archive.entry_id(mem['recent'][0])]
    res = R.forget(store, 'Alvor', '013BA0', 'the sword sale', ids=ids, mode='clean')
    check('forget by id hides it, clean: no gap', res['hidden'] and not B.load(store, 'Alvor', '013BA0')['gaps'])
    check('forget writes one record line', R.record_rows(store, 'Alvor', '013BA0')[0]['what'] == 'the sword sale')
    check('commands: "never notice" means clean', not command.leaves_gap('Forget the duel and never notice anything missing'))
    check('commands: one forgotten thing is clean, a whole period or words that ask to notice leave a gap',
          not command.leaves_gap('Forget the duel') and command.leaves_gap('Forget the last three days', 40)
          and command.leaves_gap('Forget the duel. You will notice something is missing.'), '')

    # --- the in-game release (releases.json) -------------------------------------------------------------------------
    write_channel('commands.json', {'stringList': {'key': ['47.0-3'], 'text': ['Follow me'], 'refs': ['00013BA0'],
                                                   'names': ['Alvor'], 'time': ['47.0'], 'player': ['Inga']}})
    command.poll(store, [('Alvor', '013BA0')], values, None, REF, 47, 'Inga', [ALVOR], background=False)
    write_channel('releases.json', {'stringList': {'key': ['47.5-9'], 'ref': ['00013BA0'], 'name': ['Alvor'], 'base': ['013BA0'],
                                                   'choice': ['believe'], 'time': ['47.5'], 'player': ['Inga']}})
    done = R.poll_game(store, 'Inga', 47, [ALVOR])
    check('in-game release handled', done and done[0]['ok'] and command.load(store)['commands'] == [], done)
    check('...only once', R.poll_game(store, 'Inga', 47, [ALVOR]) == [])

    # --- Now writer: triggers, input, parsing --------------------------------------------------------------------------
    s = []
    def ask(text, prompt):
        s.append((text, prompt))
        return 'Sigrid knows Inga bewitched her and is shaken.\nOTHERS: She appears to you in plain clothes.\nVALUES: family first'
    got = B.write(store, 'Sigrid', '013BA1', 'Sigrid is a farmer.', ask, context={'facts': '- Spouse: Alvor', 'player': 'Inga',
                                                                                  'labels': command.memory_labels(store, 'Inga')})
    state = B.load(store, 'Sigrid', '013BA1')
    check('a marked reason writes Now even without new talks', got and state['text'].startswith('Sigrid knows Inga'), got)
    check('the writer gets facts, reasons, the spell note and labelled memories', '- Spouse: Alvor' in s[0][0] and 'has lifted' in s[0][0]
          and "(while under Inga's spell)" in s[0][0], s[0][0])
    check('the writer is told to keep only what is still true', 'Keep only what is still true' in s[0][1])
    check('note for others and values parsed and kept', state['others'] == 'She appears to you in plain clothes.' and state['values'] == 'family first', state)
    check('reasons and notes cleared after writing', state['due'] == [] and state['notes'] == [])
    others = B.others_text(store, [('Sigrid', '013BA1'), ('Alvor', '013BA0')], [])
    check('others in a group talk get the note', 'For everyone here except Sigrid: She appears to you in plain clothes.' in others, others)
    check('alone with her: no note', B.others_text(store, [('Sigrid', '013BA1')], []) == '')
    check('a talk about her elsewhere gets it', 'About Sigrid' in B.others_text(store, [('Alvor', '013BA0')], [{'role': 'user', 'content': 'Where is Sigrid?'}]))
    B.edit(store, 'Sigrid', '013BA1', locked=True)
    B.mark_due(store, 'Sigrid', '013BA1', 'something')
    check('locked: never written', B.write(store, 'Sigrid', '013BA1', '', ask, force=True) is None)

    # old change note becomes the first Now
    path = B._path(store, 'Lydia', '0A2C94')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump({'text': 'Lydia trusts her Thane.', 'auto': True, 'version': 2}, open(path, 'w', encoding='utf-8'))
    old = B.load(store, 'Lydia', '0A2C94')
    check('migration: the old note is the first Now and a rewrite is due', old['text'] == 'Lydia trusts her Thane.' and B.OLD_NOTE in old['due'], old)

    # --- mismatches from custom events and Now text --------------------------------------------------------------------
    plain = dict(YSOLDA, maras_status='')
    check('an event claiming a marriage is a mismatch', F.event_claims('Ysolda marries Inga at the temple', plain, 'Inga'))
    check('an event about an illusion is not', F.event_claims('Ysolda believes she married Inga (an illusion)', plain, 'Inga') == [])
    check('Now saying she lives elsewhere is a mismatch', any(m['fact'] == 'home' for m in F.check_text('She lives in Riften now.', plain, 'Inga')))
    check('Now matching the game is fine', F.check_text('She lives in Breezehome.', plain, 'Inga') == [])
    check('a faction claim is a mismatch', any(m['fact'] == 'member_of' for m in F.check_text('She joined the Companions.', plain, 'Inga')))
    # only claims that THIS NPC is married to / lives with / follows the player count, not sentences about others
    partner = lambda found: [m for m in found if m['fact'] == 'partner']
    for text in ("Ysolda is happy that Carlotta married Inga's friend Mikael.", 'Inga told her that Lydia married Farkas.',
                 "She sold flowers at Inga's wedding to Lydia.", 'Inga married Lydia last spring, and Ysolda gave them a gift.',
                 "Lydia is Inga's wife now.", 'Her brother lives in Riften.', 'Lydia travels with Inga.', 'Farkas joined the Companions.',
                 'Lydia, she says, is not married.'):
        check(f'not about her: no mismatch ({text})', F.check_text(text, plain, 'Inga') == [], F.check_text(text, plain, 'Inga'))
    check('custom event about someone else: no mismatch for her', F.event_claims('Lydia married Inga at the temple', plain, 'Inga') == [])
    check('custom event: a pronoun alone does not name her', F.event_claims('She married Inga at the temple', plain, 'Inga') == [])
    for text in ('Ysolda married Inga last week.', 'She is married to Inga.', 'I am now married to Inga.', 'Ysolda and Inga were wed at the temple.',
                 "She is Inga's wife.", 'Inga married her in Riften.', 'She is engaged to Inga.', 'Inga and Ysolda are married.'):
        check(f'true claim still caught ({text})', partner(F.check_text(text, plain, 'Inga')), text)
    wed = dict(YSOLDA, maras_status='married')
    check('true reverse claim caught: she says she is not married', partner(F.check_text('She is not married.', wed, 'Inga')))
    check('true reverse claim caught: divorced', partner(F.check_text('Ysolda divorced Inga.', wed, 'Inga')))
    check('not the reverse: someone else is unmarried', F.check_text('Her sister is unmarried. Lydia is not married.', wed, 'Inga') == [])
    check('not the reverse: still married', F.check_text('She is still married to Inga.', wed, 'Inga') == [])
    check('home claim needs her as the subject', any(m['fact'] == 'home' for m in F.check_text('Ysolda now lives in Riften.', plain, 'Inga')))
    check('follower claim about her is caught', any(m['fact'] == 'follower' for m in F.check_text('She travels with Inga now.', plain, 'Inga')))

    # --- partner links key on the individual: generic NPCs sharing one base id (guards) -------------------------------
    guard_a = {'name': 'Whiterun Guard', 'ref_id': '000011AA', 'base_id': '0AAAAA', 'race': 'Nord', 'sex': 'female', 'minor': 0,
               'maras_on': 1, 'maras_status': 'dating'}
    guard_b = dict(guard_a, ref_id='000022BB', maras_status='')
    F.sync_talk(store, [guard_a], 'Inga', 5)
    F.sync_talk(store, [guard_a], 'Inga', 6)
    lines_b = F.link_lines(F.load(store), guard_b, 'Inga')
    check("guards: B never shows A's partner", not any('Partner' in l for l in lines_b), lines_b)
    changes = F.sync_talk(store, [guard_b], 'Inga', 7)
    lines_a = F.link_lines(F.load(store), guard_a, 'Inga')
    check("guards: B talking does not end A's link", any('Partner: dating Inga' in l for l in lines_a), lines_a)
    again = F.sync_talk(store, [guard_a], 'Inga', 8)
    check("guards: A's next talk is no change", not any(again.values()), again)
    old_side = {'key': '', 'base': '0CCCCC', 'name': 'Old'}  # a link written before keys had refs (ties side): base still counts
    check('a side without a reference id still matches by base', F._is(old_side, {'key': 'old|1A2B', 'base': '0CCCCC'}))

    # --- religion, Thalmor, stances ------------------------------------------------------------------------------------
    priest = {'name': 'Danica', 'race': 'Nord', 'factions': ['Temple of Kynareth']}
    check('religion from a temple faction', C.religion_for(C.live_members(priest)) == 'follows Kynareth')
    check('religion set by the user otherwise', C.religion_for([], {'religion': 'Akatosh'}) == 'Akatosh')
    check('a Thalmor never dislikes the Thalmor', C.auto_stances(['Thalmor'], {'race': 'Altmer'})['Thalmor'] == 'loves')
    check('a Legion Nord gets no Thalmor default', 'Thalmor' not in C.auto_stances(['Imperial Legion'], {'race': 'Nord'}))
    check('a Stormcloak still hates them', C.auto_stances(['Stormcloaks'], {'race': 'Nord'})['Thalmor'] == 'hates')
    check('village folk dislike them', C.auto_stances([], {'race': 'Breton', 'home': 'Riverwood'}).get('Thalmor') == 'dislikes')
    check('a city Breton gets no default', 'Thalmor' not in C.auto_stances([], {'race': 'Breton', 'home': 'Solitude'}))

    # --- one rule for "married" ---------------------------------------------------------------------------------------
    check('M.A.R.A.S present decides over the faction', C.player_kind({'maras_on': 1, 'spouse': 1}) == '')
    check('without M.A.R.A.S the vanilla marriage counts', C.player_kind({'spouse': 1}) == 'married')
    check("NFF's elope is its own kind", C.player_kind({'nff_eloped': 1, 'spouse': 1}) == 'eloped')

    # --- the shared rule line ------------------------------------------------------------------------------------------
    rules = prompt_rules.load_rules(str(SERVER.resolve().parent / 'SKSE' / 'Plugins' / 'MantellaSoftware' / 'data' / 'prompt_rules'), 'Inga')
    check('the later part is the current truth, said once', rules.count('the later part is the current truth') == 1, rules)
    check('the outfit rule is there', 'never blamed for looking' in rules and '{player_name}' not in rules)

    # --- prompt order in system_parts ----------------------------------------------------------------------------------
    npc_block.talk_over()
    living_world._last_store.update(store=store, people=[('Ysolda', '01A69F')])
    real_conv = lw_state.load_conversation
    lw_state.load_conversation = lambda: [married]
    try:
        mantella = ('# Overview\nYou are in Skyrim.\n\n# Background\nYsolda is a merchant.\n\n# History\nBelow is a summary of past events.\n\n'
                    '# Current Scene\nIt is noon.\nRespond as Ysolda.')
        parts = living_world._system_parts({'mantella': mantella}, {})
        bg = parts['background']
        check('order: bio, then Background, then Now', bg.index('Ysolda is a merchant.') < bg.index('Background facts about Ysolda')
              < bg.index('Now, as Ysolda sees it'), bg)
        check('memories come after the NPC part', parts['__order__'].index('background') < parts['__order__'].index('history'))
        again = living_world._system_parts({'mantella': mantella}, {})
        check('the same request twice: the same text (cache)', again['background'] == bg)
    finally:
        lw_state.load_conversation = real_conv
    preview = npc_block.preview(store, 'Alvor', '013BA0', bio='Alvor is a smith.', speaker=ALVOR, player='Inga')
    check('prompt preview for one NPC: bio first, background next', preview['text'].startswith('Alvor is a smith.')
          and 'Background facts about Alvor' in preview['text'], preview)

# --- recognition at the greeting (live test 3: greeting named the player, the hood event came afterwards) --------------
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    lw_state.DATA_DIR = str(tmp / 'channel'); (tmp / 'channel').mkdir()
    world = {'hold': 'Whiterun', 'fame': {'Whiterun': 0}, 'thane': []}
    people = [('Gerdur', '013489'), ('Faendal', '01348C')]
    speakers = [{'name': 'Gerdur', 'ref_id': '00013489', 'minor': 0}, {'name': 'Faendal', 'ref_id': '0001348C', 'minor': 0, 'observation': 2}]
    knows = lambda name, ref, speaker: name == 'Gerdur'
    check('recognition: no recognition file (World absent or face never covered): nothing', npc_block.recognition_text(people, speakers, 'Player', knows, world) == '')
    write_channel('recognition.json', {'int': {'face_hidden': 1}})
    text = npc_block.recognition_text(people, speakers, 'Player', knows, world)
    check('recognition at the greeting: a stranger does not recognise, someone who knows the player still does',
          '(Faendal does not recognise the hooded stranger: a hood hides their face.)' in text and '(Gerdur knows Player well and recognises them, hood or not.)' in text, text)
    uncanny = [speakers[0], dict(speakers[1], observation=4)]
    check('recognition: an uncanny observer sees through it', "Faendal sees through Player's hood" in npc_block.recognition_text(people, uncanny, 'Player', knows, world))
    check('recognition: famous in this hold or Thane, or outside any hold: the hood hides nothing',
          npc_block.recognition_text(people, speakers, 'Player', knows, dict(world, fame={'whiterun': 3})) == ''
          and npc_block.recognition_text(people, speakers, 'Player', knows, dict(world, thane=['Whiterun'])) == ''
          and npc_block.recognition_text(people, speakers, 'Player', knows, dict(world, hold='')) == '')
    write_channel('recognition.json', {'int': {'face_hidden': 0}})
    check('recognition: face not covered now: nothing', npc_block.recognition_text(people, speakers, 'Player', knows, world) == '')
    check('knows the player: follower, spouse, housecarl, friend rank, close, a command, several talks; a stranger not',
          all(npc_block.knows_player(s) for s in ({'follower': 1}, {'spouse': 1}, {'housecarl': 1}, {'rank': 1}, {'close': 1}))
          and npc_block.knows_player({}, commanded=True) and npc_block.knows_player({}, talks=3)
          and not npc_block.knows_player({'rank': 0}, talks=2) and not npc_block.knows_player(None))
    events = ['Gerdur does not recognise Player: a hood hides their face.', 'Faendal does not recognise Player: a hood hides their face.', 'Hod waves']
    fixed = npc_block.fix_recognition_events(events, lambda n: n == 'Gerdur', 'Player')
    check("World's event for someone who knows the player (spellbound, spouse, follower) becomes 'recognises them'",
          fixed[:2] == ['Gerdur knows Player well and recognises them, hood or not.',
                        'Faendal does not recognise the hooded stranger: a hood hides their face.'] and fixed[3:] == ['Hod waves']
          and "Faendal does not know the player's name and never says it" in fixed[2] and 'Player' not in fixed[1] + fixed[2], fixed)
    check('fix_recognition_events never raises', npc_block.fix_recognition_events([None, 5], lambda n: 1 / 0, 'Player') == [None, 5])

# --- Relationships' same-sex note only on marriage talk (live test 3: sent in every talk with Alvor) --------------------
note = 'Alvor cannot be courted for marriage through M.A.R.A.S, which is set to opposite-sex only; friendship and other affection are not affected.'
alvor = dict(ALVOR, marriage_note=note)
ask = lambda text: [{'role': 'system', 'content': 'x'}, {'role': 'user', 'content': text}]
check('marriage note: not in an ordinary talk', npc_block.marriage_text(ask('Hello Alvor, how is the forge?'), [alvor]) == '')
check('marriage note: added when the player proposes or asks about marriage',
      npc_block.marriage_text(ask('Alvor, would you marry me?'), [alvor]) == f'({note})'
      and npc_block.marriage_text(ask('I have an Amulet of Mara.'), [alvor]) == f'({note})')
check('marriage note: nobody with a note: nothing', npc_block.marriage_text(ask('Will you marry me?'), [ALVOR]) == '' and npc_block.marriage_text(None, None) == '')

print(f"\n{len(FAILS)} failure(s)" if FAILS else '\nall passed')
sys.exit(1 if FAILS else 0)
