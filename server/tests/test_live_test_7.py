"""Offline tests for the defects found by live test 7 and the diagnostic session after it (2026-11-15), built from the
real files those runs left (copied into data_live_test_7.py): a follower's outfit swap, older-format short bios, the
short-bio checks (quotes, terms, length, rule lines, lost reasons), section labels in a saved Now paragraph, fight
magic put down to the player, the Status page timers, the spouse on the NPC page, tie kinds written with a capital,
and a first meeting's greeting (the game writes a new NPC's file in two steps).
Run with a Python 3.11: test_live_test_7.py <repo server dir>"""
import json, os, sys, tempfile, threading, time, types
from pathlib import Path

SERVER = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import living_world as LW
from living_world import (action_filter as AF, battle, bio_evolve as B, bio_optimise as BO, characters as C, contracts,
                          embed, lw_state, memory, npc_block, npc_page_ui as P, ui_help, ui_tab)
import data_live_test_7 as D
memory.SUMMARY_RETRY_SECONDS = 0
embed.use(None)

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)[:700]) if not cond else ''))
    if not cond:
        FAILS.append(name)


def write(base: Path, name: str, data, when=None):
    path = base / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding='utf-8')
    if when is not None:
        os.utime(path, (when, when))


# --- 1. outfit spam ---------------------------------------------------------------------------------------------------------
def part_outfits(tmp):
    out = npc_block.collapse_outfit_events(D.RECRUIT_BATCH)
    item = lambda e: any(w in e for w in (' equipped ', ' unequipped ', 'dropped/gave', 'picked up/took'))
    check('the recruit batch of live test 7 (34 lines, 33 about her items) becomes two lines', out == [
        "lira has joined the player's party.", out[1]] and len(out) == 2, out)
    check('...the outfit line is short and names only what she newly put on (no Glass Dagger, no earrings)',
          out[1].startswith("lira changed outfit, now wearing Cosplay Gala Gown 'Saturnalia' - Amber")
          and 'Glass Dagger' not in out[1] and "Nyxari" not in out[1] and 'and 2 more' in out[1] and len(out[1]) < 170, out[1])
    out2 = npc_block.collapse_outfit_events(D.FOLLOW_BATCH)
    check('the follow batch: the gold stays, the outfit is one line, the dagger draw keeps its own line',
          out2[:3] == D.FOLLOW_BATCH[:3] and 'changed outfit' in out2[3] and out2[4:] == ['lira equipped Glass Dagger'], out2)
    lower = ['Lira unequipped Elven Boots', 'lira dropped/gave Elven Boots', 'LIRA unequipped Elven Gloves', 'lira dropped/gave Elven Gloves']
    out3 = npc_block.collapse_outfit_events(lower)
    check('two unequip and two drop lines, the name in three spellings: one line', len(out3) == 1 and 'changed outfit' in out3[0], out3)
    check('a single meaningful equip and a weapon draw stay', npc_block.collapse_outfit_events(
        ['Lydia equipped Steel Sword', 'Lydia equipped Amulet of Mara']) == ['Lydia equipped Steel Sword', 'Lydia equipped Amulet of Mara'])
    check('no item line is left in the recruit batch', not any(item(e) for e in out), out)


# --- 2. older-format short bios ------------------------------------------------------------------------------------------
def part_old_formats(tmp):
    if not (D.BIOS_AFTER and D.BREVAL_BIO):
        return print('SKIP the live test 7 bio files are not on this PC')
    path = str(tmp / 'bios.json')
    Path(path).write_text(json.dumps(D.BIOS_AFTER), encoding='utf-8')
    olds = [k for k, v in D.BIOS_AFTER['bios'].items() if v.get('format') != BO.FORMAT_VERSION]
    # the real file: 63 entries, of which Breval and Nia (format 1, done), Gerdur (format 1, kept), Lucan, Alvor,
    # Gerdur, Hod (format 2, done), Camilla, Sigrid, Dorthe (format 2, kept)
    check('the real file holds older-format entries (Breval, Nia, Gerdur, Alvor, Hod, Camilla, Sigrid, Dorthe)', len(olds) >= 9, olds)
    loaded = BO.load(path)['bios']
    check('older-format entries are never loaded (so never used)', not any(k in loaded for k in olds), sorted(loaded))
    values = {'bio_optimise': True}
    check("Breval's old format-1 short text is never sent: the original is", BO.used_bio('Breval', D.BREVAL_BIO, values, path) == D.BREVAL_BIO)
    # the entry under the old hash is never read, even if a key matched
    raw = json.loads(Path(path).read_text(encoding='utf-8'))
    old_key = next(k for k, v in raw['bios'].items() if v['name'] == 'Breval')
    real_hash = BO.bio_hash
    BO.bio_hash = lambda text, version=None: old_key
    BO._cache.update(path=None, stamp=None, data=None)
    try:
        check('an older-format entry is not used even under a matching key', BO.entry('Breval', D.BREVAL_BIO, path) is None)
    finally:
        BO.bio_hash = real_hash
    detail = BO.optimise_detail(D.BREVAL_BIO, [], 'Breval', lambda p, t: 'Personality: x.')
    check("this run's decision for Breval is 'nothing to gain'", detail['status'] == 'short', detail)
    BO.remember('Breval', D.BREVAL_BIO, detail, path=path)
    raw = json.loads(Path(path).read_text(encoding='utf-8'))
    breval = [v for v in raw['bios'].values() if v['name'] == 'Breval']
    check("the 'nothing to gain' decision replaces Breval's old entry (kept, current format)",
          len(breval) == 1 and breval[0]['status'] == 'kept' and breval[0]['format'] == BO.FORMAT_VERSION, breval)
    check('every older-format entry is pruned from the file on that write',
          all(v.get('format') == BO.FORMAT_VERSION for v in raw['bios'].values()), [(v['name'], v.get('format')) for v in raw['bios'].values()])
    check("the page says the original is kept for Breval, not 'no short bio yet'",
          BO.page_view('Breval', D.BREVAL_BIO, values, path)['status'].startswith('The original is kept'),
          BO.page_view('Breval', D.BREVAL_BIO, values, path))


# --- 3. the checker ---------------------------------------------------------------------------------------------------------
def part_checker(tmp):
    if not (D.AELA_BIO and D.FARALDA_BIO and D.CANAS_BIO):
        return print('SKIP the live test 7 override bios are not on this PC')
    aela = ('Personality: proud, fierce huntress.\nVoice: blunt; scorns outsiders as "milk drinkers".\n'
            'History: Companion of Jorrvaskr.')
    check('Aela: "milk drinkers" matches the original\'s "milk drinker" (plural, case, quote style do not count)',
          BO.invented_quotes(D.AELA_BIO, aela) == [], BO.invented_quotes(D.AELA_BIO, aela))
    check('...but a quote with a word the original does not have is still caught',
          BO.invented_quotes(D.AELA_BIO, 'Voice: "We take any milk drinker gladly."') != [])
    check('...and curly quotes and punctuation do not count', BO.invented_quotes(
        D.AELA_BIO, 'Sample lines: “We don\'t just take any milk drinker who stumbles in!”') == [])
    faralda = ("Voice: often says 'I suppose'.\nKnows: Ancano holds an 'advisor' position.")
    found = BO.explained_terms(D.FARALDA_BIO, faralda)
    check('Faralda: the filler phrase "I suppose" is no term; "advisor" (a title stated as fact from a rumour) is still caught',
          'advisor' in found and 'I suppose' not in found, found)
    # the length rule: the own text, labels, rules and lines copied word for word left out on both sides, 10% shorter
    rest = BO.without_rules(D.CANAS_BIO)
    body = rest[:int(len(rest) * 0.84)].rsplit(' ', 1)[0] + '.'
    result = 'Personality: x.\nHistory: ' + body
    size, base = BO.own_sizes(D.CANAS_BIO, result)
    check('length rule: labels are not counted as its own text', size == len(result) - len('Personality: ') - len('History: '), (size, len(result)))
    check('length rule: a result 15% shorter in its own text passes', not any('not clearly shorter' in b for b in BO.problems(D.CANAS_BIO, result, '', 'Canas The Silver')[0]))
    long_result = 'History: ' + rest[:int(len(rest) * 0.95)]
    check('length rule: one only 5% shorter is still refused', any('not clearly shorter' in b for b in BO.problems(D.CANAS_BIO, long_result, '', 'Canas The Silver')[0]))


# --- 4. rule lines ----------------------------------------------------------------------------------------------------------
def part_rules(tmp):
    if not (D.SERANA_BIO and D.ADRIANNE_BIO and D.VALERICA_BIO):
        return print('SKIP the live test 7 override bios are not on this PC')
    serana = BO.rule_items(D.SERANA_BIO)
    for s in ("but this is her interpretation of what she feels, not confirmed knowledge of his true nature.",
              "Her initial knowledge does not include his origins",
              "supersede this initial uncertainty.", "Her growing warmth and trust come from how he treats her, not simply from his power.",
              "She retains her wit, independence, and boundaries.", "but does not constantly bring up his aura"):
        check(f'Serana: rule lifted out word for word: "{s[:50]}..."', any(s in r for r in serana), serana)
    adrianne = BO.rule_items(D.ADRIANNE_BIO)
    gate = 'Until she has reason to believe the player is the Dragonborn or touched by the divine, they are just another customer.'
    beyond = next((i for i, r in enumerate(adrianne) if r.startswith('Whatever grows between them beyond that')), -1)
    check('Adrianne: the gate lines are rules', gate in adrianne and any(r.startswith('She will not pretend someone is legendary') for r in adrianne), adrianne)
    check('Adrianne: "beyond that" carries the sentence it points at, just before it', beyond > 0 and adrianne[beyond - 1] == gate, adrianne)
    valerica = BO.rule_items(D.VALERICA_BIO)
    desire = 'She does not admit it or act on it with the player until she is sure Serana approves; until then she shows only rare, small hints.'
    i = valerica.index(desire) if desire in valerica else -1
    check("Valerica: the desire rule is lifted word for word ('with the player', 'does not admit it or act on it')", i >= 0, valerica)
    check('Valerica: and the sentence "it" points at goes with it', i > 0 and valerica[i - 1].startswith('Beneath her composure Valerica has a strong desire'), valerica)
    rest = BO.without_rules(D.SERANA_BIO)
    check('Serana: the lifted rules are not in what the helper rewrites', 'not confirmed knowledge' not in rest and 'does not constantly' not in rest)
    out = BO.with_rules('Personality: witty.', serana)
    check('Serana: every rule is appended word for word', BO.rules_missing(D.SERANA_BIO, out) == [])


# --- 5. lost reasons ----------------------------------------------------------------------------------------------------------
def part_reasons(tmp):
    if not D.ALANNA_BIO:
        return print('SKIP the live test 7 override bios are not on this PC')
    sentence = "She respects Myriani's craftsmanship because enchanted objects still require competent physical construction"
    kept_reason = 'Personality: Respects Myriani\'s craftsmanship because enchanted objects still need competent physical construction.'
    lost = 'Personality: Respects Myriani\'s craftsmanship.'
    check('Alanna: a fact kept with its reason passes', BO.lost_reasons(D.ALANNA_BIO, kept_reason, 'Alanna') == [], BO.lost_reasons(D.ALANNA_BIO, kept_reason, 'Alanna'))
    found = BO.lost_reasons(D.ALANNA_BIO, lost, 'Alanna')
    check('Alanna: the same fact without its reason is caught', any(sentence in f for f in found), found)
    check('...and named in the retry', any('drops the reason' in b for b in BO.problems(D.ALANNA_BIO, lost, '', 'Alanna')[0]))
    check('a dropped fact is no lost reason', BO.lost_reasons(D.ALANNA_BIO, 'Personality: argues theory.', 'Alanna') == [])
    check('"Since then ..." is time, not a reason', BO._reasons('Since then Lyn has worked hard to keep them fed, and is proud.') == [])
    asked = []
    def ask(prompt, text):
        asked.append(prompt)
        return lost if len(asked) == 1 else kept_reason
    BO.optimise_detail(D.ALANNA_BIO, [], 'Alanna', ask)
    check('a lost reason is asked again once, with the sentence listed', len(asked) == 2 and 'drops the reason' in asked[1], asked[-1][-400:] if asked else asked)


# --- 6. Now paragraph labels ---------------------------------------------------------------------------------------------------
def part_now_labels(tmp):
    text, others, values = B.parse_reply(D.LIRA_NOW_REPLY)
    check('the real writer reply: no leading "Now:" and no VALUES in the paragraph', text.startswith('Lira is travelling') and 'VALUES' not in text, text)
    check('...VALUES parsed apart', values and values.startswith('Fiercely loyal'), values)
    text, others, values = B.parse_reply(D.LIRA_STORED + ' VALUES: Fiercely loyal. OTHERS: NONE')
    check('labels in the middle of a line, in any order, are split', 'VALUES' not in text and 'OTHERS' not in text and values == 'Fiercely loyal.'
          and others == '' and not text.startswith('Now:'), (text, others, values))
    text, others, values = B.parse_reply('values: Kind.\nothers: Wears a hood.\nnow: Lydia waits.')
    check('lower-case labels at the start of lines, Now last', (text, others, values) == ('Lydia waits.', 'Wears a hood.', 'Kind.'), (text, others, values))
    check('a word "now:" inside a sentence is kept', B.parse_reply('She knows now: things change.')[0] == 'She knows now: things change.')


# --- 7. fight magic -----------------------------------------------------------------------------------------------------------
def part_battle(tmp):
    fight = D.BATTLES['fights'][0]
    lira = next(f for f in fight['fighters'] if f['name'] == 'Lira')
    text = battle.account(fight, lira, 1)
    check('the real wolf fight: harm the player put on his own follower and the wolf is an aura, not a spell',
          '00000014' in battle.area_casters(fight), battle.area_casters(fight))
    check("Lira's account does not say the player used drain or slow magic on her", 'Magic put on you' not in text and 'drain' not in text, text)
    one_sided = json.loads(json.dumps(fight))
    for f in one_sided['fighters']:
        if f['name'] == 'Lira':
            f['harm'] = {}
        if f['name'] == 'Wolf':
            f['harm'] = {'fire': ['00000014']}
            f['side'] = 1
    wolf = next(f for f in one_sided['fighters'] if f['name'] == 'Wolf')
    check('a spell on a foe only is still told', 'fire from' in battle.account(one_sided, wolf, 1), battle.account(one_sided, wolf, 1))


# --- 8. the Status page loads ---------------------------------------------------------------------------------------------------
def part_page(tmp):
    src = (SERVER / 'living_world' / 'ui_tab.py').read_text(encoding='utf-8')
    check('no every= timer on any page (Gradio 4 runs it forever on the event loop and holds a queue slot per open page)',
          'every=' not in src.replace("every= runs", ''), [l for l in src.splitlines() if 'every=' in l])
    bad = ui_help.safe(lambda: 1 / 0, 'fallback')
    check('a page value that raises shows its fallback instead of stopping the page', bad() == 'fallback')


# --- 9 and C. the spouse on the NPC page; tie kinds with a capital ---------------------------------------------------------------
def part_ties(tmp):
    t7 = contracts.load_ties(D.TIES_TEST7)
    check("live test 7's ties.json has no entry for Alvor or Sigrid (Relationships had not listed them in that run)",
          '013475' not in t7 and '013476' not in t7 and contracts.ties_of('013475', t7) == [], sorted(t7))
    t6 = contracts.load_ties(D.TIES_TEST6)
    check('the real "Spouse" (capital S) is read as spouse', {'kind': 'spouse', 'base': '013476', 'name': 'Sigrid'} in t6['013475']['ties'], t6['013475'])
    check("...and mirrored: Sigrid's own list gives Alvor as spouse", any(t['kind'] == 'spouse' and t['name'] == 'Alvor' for t in contracts.ties_of('013476', t6)))
    hod = contracts.ties_of('01347C', t7)  # Gerdur: only Hod's list names her, "Spouse" and "Child" capitalised
    check("test 7's Hod lists Gerdur as \"Spouse\": Gerdur's mirrored tie is spouse", any(t['kind'] == 'spouse' and t['name'] == 'Hod' for t in hod), hod)
    for label, ties in (('test 7', D.TIES_TEST7), ('test 6', D.TIES_TEST6)):
        ch = tmp / f'ties-{label[-1]}'
        lw_state.DATA_DIR = str(ch)
        write(ch, 'ties.json', ties)
        write(ch, 'npc/013475.json', D.ALVOR_NPC)

        class Fake:
            store, player = None, 'Brom'
            def __init__(self, name, race):
                self.name, self.speaker = name, C.game_npc(name, race)
            def entry(self):
                return {}
        parts = P.summary_parts(Fake('Alvor', 'Nord'))
        if label == 'test 7':
            check("Alvor's summary with test 7's files: no spouse to show (the data is not there)", not any('married' in p for p in parts), parts)
        else:
            check("Alvor's summary with his real npc file and a ties.json that lists him: married to Sigrid", 'married to Sigrid' in parts, parts)


# --- B. a first meeting's greeting ------------------------------------------------------------------------------------------------
def installed_gates():
    gates = {}
    for path in SERVER.parent.parent.glob('Mantella-Living-World-*/SKSE/Plugins/MantellaSoftware/data/actions/*.json'):
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        for a in data if isinstance(data, list) else [data]:
            if isinstance(a, dict) and a.get('lw_gate') and a.get('name'):
                gates[a['name']] = a['lw_gate']
    return gates


def part_greeting(tmp):
    gates = installed_gates()
    if not gates:
        print('SKIP no module action files next to this repository')
        return
    tools = [{'function': {'name': n, 'description': 'x'}} for n in sorted(gates)] + [{'function': {'name': 'Wave', 'description': 'y'}}]
    names = lambda ts: [t['function']['name'] for t in ts]
    fake = types.ModuleType('src.extensions')
    real_ext, real_gates, real_store = sys.modules.get('src.extensions'), LW._gates, dict(LW._last_store)
    sys.modules['src.extensions'] = fake
    LW._gates = lambda: gates
    C.PATH = str(tmp / 'characters.json')
    greet = {'messages': [{'role': 'system', 'content': 's'}, {'role': 'user', 'content': 'hi'}]}
    reply = {'messages': [{'role': 'user', 'content': 'hi'}, {'role': 'assistant', 'content': 'Hello.'}, {'role': 'user', 'content': 'Hi.'}]}
    try:
        for who, base, first, full in (('Sigrid', '013476', D.SIGRID_FIRST_SEEN, D.SIGRID_AFTER_REPLY1),
                                       ('Delphine', '013478', D.DELPHINE_FIRST_SEEN, D.DELPHINE_AFTER_REPLY1)):
            ch = tmp / f'greet-{who}'
            lw_state.DATA_DIR = str(ch)
            fake._registry = types.SimpleNamespace(speaking_ids=[base])
            LW._last_store.update(store=None, people=[(who, full['string']['ref_id'][-6:])])
            write(ch, 'conversation.json', {'string': {'player': 'Brom'}, 'int': {'day': 1}, 'stringList': {'speakers': []}})
            write(ch, f'npc/{base}.json', first)  # the partial file the game writes at once
            start = time.time()
            greeting = names(LW._filter_tools(tools, greet))
            waited = time.time() - start
            write(ch, f'npc/{base}.json', full)  # the rest, 9 to 11 s later
            first_reply = names(LW._filter_tools(tools, reply))
            check(f'{who}, first meeting (real partial file): the greeting does not wait for the rest of the file', waited < 0.5, waited)
            check(f'{who}: no scene-only action at the greeting (scene missing = not in a scene)',
                  not {'ChangePosition', 'RateFavoritePositions'} & set(greeting), greeting)
            check(f'{who}: the greeting offers nothing the first reply does not', set(greeting) <= set(first_reply),
                  sorted(set(greeting) - set(first_reply)))
            # a later talk in a new server session: the file is on disk, complete and old
            write(ch, f'npc/{base}.json', full, when=time.time() - 3600)
            start = time.time()
            again = names(LW._filter_tools(tools, greet))
            waited = time.time() - start
            check(f'{who}, a later talk in a new session: the greeting is built at once from the file on disk', waited < 0.2, waited)
            check(f'{who}: ...and offers exactly what the reply after it does (one cached prefix)', again == names(LW._filter_tools(tools, reply)),
                  {'greeting': again})
        write(ch, 'conversation.json', {'string': {'player': 'Brom'}, 'int': {'day': 1}, 'stringList': {'speakers': []}})
        fake._registry = types.SimpleNamespace(speaking_ids=['0BEEF0'])
        start = time.time()
        offered = names(LW._filter_tools(tools, greet))
        adult = [n for n in offered if set(gates.get(n, '').split('+')) & AF.ADULT_GATES]
        check('an NPC with no file at all: nothing adult, after at most the one-second wait', not adult and time.time() - start < LW.GREETING_WAIT + 0.4,
              (adult, time.time() - start))
    finally:
        LW._gates = real_gates
        LW._last_store.clear()
        LW._last_store.update(real_store)
        if real_ext is None:
            sys.modules.pop('src.extensions', None)
        else:
            sys.modules['src.extensions'] = real_ext


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    for part in (part_outfits, part_old_formats, part_checker, part_rules, part_reasons, part_now_labels, part_battle,
                 part_page, part_ties, part_greeting):
        try:
            part(tmp)
        except Exception as e:
            import traceback
            traceback.print_exc()
            check(f'{part.__name__} ran without an error', False, e)

print(f"\n{len(FAILS)} failure(s)" if FAILS else '\nall passed')
sys.exit(1 if FAILS else 0)
