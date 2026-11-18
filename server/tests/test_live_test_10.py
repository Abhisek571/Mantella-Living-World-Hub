"""Offline tests for the defects found by live test 10 (2026-11-16), built from the real files that run left: the silent
appetite rating spoken as dialogue, a merchant's wares list gone stale after his barter menu restocked, the player put
down for damage and kills in fights he never joined, and three short-bio leftovers (Adrianne, Valerica, Elisif).
The user's own bios and the run's files are read from the live test's folder when it is on this PC (never copied into
the repository); a part that needs them is skipped without them.
Run with a Python 3.11: test_live_test_10.py <repo server dir>"""
import copy, json, os, sys, tempfile
from pathlib import Path

SERVER = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(SERVER))
import living_world as LW
from living_world import battle, bio_optimise as BO, embed, lw_state, memory, prompt_rules, silent_requests as SR, trade
memory.SUMMARY_RETRY_SECONDS = 0
embed.use(None)

LIVE10 = os.path.join(os.environ.get('MLW_EVIDENCE', ''), r'lw-live-test-10-2026-11-16')
FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)[:700]) if not cond else ''))
    if not cond:
        FAILS.append(name)


def _json(*parts):
    try:
        with open(os.path.join(LIVE10, *parts), encoding='utf-8-sig') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _bio(name):
    data = _json('character_overrides-before', name + '.json')
    return (data[0] if isinstance(data, list) else data)['bio'] if data else None


# the real turn of live test 10 (logging.log 07:55:50): the events Arousal and the Hub sent with "Lira, could you lend me
# 30 gold?"; the model's reply was "I'll rate her appetite silently and hand over the gold." with RateAppetite and Trade
RATING_TURN = ['lira sees the player as a trusted ally. ', 'lira seems noticeably aroused, though she keeps it to herself.',
               "lira's sexual appetite has not been rated yet. Give the rating only as the number in the RateAppetite action: "
               "never say, hint at or describe it, or mention this note; the spoken reply goes on with the talk exactly as it "
               "would without it.", 'Brom looks a little flushed.']
POSITIONS = ("Lydia's favourite sex positions have not been rated yet. Give them only in the RateFavoritePositions action: "
             "never say, hint at or list them, or mention this note; the spoken reply goes on with the scene as usual.")


# --- 1. a silent rating asked for as an event ---------------------------------------------------------------------------
def part_rating(tmp):
    ch = tmp / 'channel'
    ch.mkdir()
    real_dir = lw_state.DATA_DIR
    lw_state.DATA_DIR = str(ch)
    try:
        (ch / 'conversation.json').write_text(json.dumps({'string': {'player': 'Brom'}, 'int': {'day': 1}}), encoding='utf-8')
        SR.clear()
        out = LW._dialogue_events(list(RATING_TURN), {'player': 'Brom', 'characters': [], 'game_days': 1.7})
        check('the real turn: the rating request is no longer an event of the scene', not any('rated' in str(e) for e in out), out)
        check('...the other three events stay as they were, in order', [e.strip() for e in out] ==
              [RATING_TURN[0].strip(), RATING_TURN[1], RATING_TURN[3]], out)
        request = [{'role': 'user', 'content': '(' + ')\n('.join(e.strip() for e in out) + ')\nNyri, could you lend me 30 gold?'}]
        extra = LW._extra_text({'messages': request})
        note = next((line for line in extra.splitlines() if 'RateAppetite' in line), '')
        check('...a note goes after the player\'s words instead: not part of the scene, not to be answered, the action named',
              note.startswith('Action note, not part of the scene and not something to answer:') and 'RateAppetite action' in note
              and "lira's sexual appetite" in note, extra)
        check('...it says the spoken reply answers the player and never mentions a rating, an action or what comes next',
              "answers Brom's words" in note and 'never mentions a rating, an action, this note or what the speaker is about to do' in note, note)
        check('...the note is no line in parentheses (Mantella says lines in parentheses happened and are to be reacted to)',
              not note.startswith('('), note)
        check('...and goes with that one reply only', 'RateAppetite' not in LW._extra_text({'messages': request}))
        out = SR.take([POSITIONS, 'Lydia smiles.'])
        check("OStim Expansion's positions request is taken the same way, with its own action",
              out == ['Lydia smiles.'] and 'RateFavoritePositions action' in SR.note('Brom'), out)
        old = "lira's sexual appetite has not been rated yet. Rate it with the action without a word about it."
        check('a request naming no action (an older Arousal) stays an event, as before', SR.take([old]) == [old] and SR.note() == '')
        SR.take(list(RATING_TURN))
        SR.clear()
        check('a request no reply took is not carried into the next talk', SR.note() == '')
        src = (SERVER / 'living_world' / '__init__.py').read_text(encoding='utf-8')
        check('the hooks: dialogue_events takes the request first, the newest message gets the note, a talk end clears it',
              src.find('events = silent_requests.take(events)') < src.find('events = custom_events.process(')
              and 'silent_requests.note(lw_state.load_player_name())' in src and 'silent_requests.clear()' in src)
    finally:
        lw_state.DATA_DIR = real_dir
        SR.clear()
    rules = (SERVER.parent / 'SKSE' / 'Plugins' / 'MantellaSoftware' / 'data' / 'prompt_rules' / '01_talk.txt').read_text(encoding='utf-8-sig')
    line = next((l for l in rules.splitlines() if 'announce' in l), '')
    check('a shared rule: a reply never announces actions in place of dialogue',
          "in place of dialogue" in line and "I'm rating" in line and 'let the action happen' in line, rules)
    flat = '\n'.join(l.strip() for l in rules.splitlines() if l.strip())
    check(f'...and the rule file stays within {prompt_rules.MAX_CHARS} characters ({len(flat)})', len(flat) <= prompt_rules.MAX_CHARS)


# --- 2. a merchant's wares after his barter menu opened -----------------------------------------------------------------
LUCAN = {'name': 'Lucan Valerius', 'base_id': '01347A', 'carry_gold': 120, 'carry_items': '', 'merchant': 1,
         'wares': ['Misc|1|16|Goat Hide', 'Misc|1|7|Charcoal', 'spell tome|1|152|Spell Tome (Novice): Flames']}


def part_wares(tmp):
    start = [{'role': 'user', 'content': '(Characters nearby: lira)\nDo you have any goat hides? I need one, I will buy it.'}]
    line = trade.carry_text([LUCAN], start)
    check('before the barter menu: the wares line as before, no stock note', 'Goat Hide' in line and 'stock has changed' not in line, line)
    barter = start + [{'role': 'assistant', 'content': 'Let me open up my wares.'},
                      {'role': 'user', 'content': "(Lucan Valerius's barter menu opened.)\n((Nothing happened: Lucan Valerius has "
                                                  'nothing called "Goat Hide" for sale.))\nHm, so about that goat hide?'}]
    line = trade.carry_text([LUCAN], barter)
    check('the real turn after the barter menu ("for sale" in the refusal makes it a trade turn): the list still names the '
          'Goat Hide, so the line says his stock changed and to check before promising',
          "Lucan Valerius's stock has changed during this talk" in line, line)
    quiet = barter[:-1] + [{'role': 'user', 'content': "(Lucan Valerius's barter menu opened.)" + chr(10) + 'Hm, so about that goat hide?'}]
    check('...the barter menu line itself makes it a trade turn, so the note always comes with the list on that turn',
          'stock has changed during this talk' in trade.carry_text([LUCAN], quiet))
    later = barter + [{'role': 'assistant', 'content': "I'm out of goat hides."},
                      {'role': 'user', 'content': 'How much for the charcoal? I want to buy some.'}]
    line = trade.carry_text([LUCAN], later)
    check('a later trade turn in the same talk: the wares line says his stock changed', 'stock has changed during this talk' in line, line)
    check('...a turn with neither trade words nor the barter menu in its newest message adds nothing',
          trade.carry_text([LUCAN], later[:-1] + [{'role': 'user', 'content': 'Nice weather.'}]) == '')
    sale = start + [{'role': 'user', 'content': '(Brom bought Charcoal from Lucan Valerius for 7 gold; the goods and the gold '
                                                'were handed over.)\nWhat else do you sell?'}]
    line = trade.carry_text([LUCAN], sale)
    check("after a sale by talk the old list is never shown as it was (the stock note, or no numbers at all)",
          'stock has changed' in line or ('purse and pack hold' in line and 'Goat Hide' not in line), line)
    check("...World's own sale result line counts as a change", trade.stock_changed('Lucan Valerius', sale))
    check('another merchant in the talk is not marked by Lucan\'s barter menu',
          'stock has changed' not in trade.carry_line(dict(LUCAN, name='Camilla Valerius'), later))


# --- 3. the player put down for fights he never joined -----------------------------------------------------------------
def part_battle(tmp):
    data = _json('test-artifacts', 'overwrite-StorageUtilData-MLW', 'battles.json')
    if not data:
        return print('SKIP the live test 10 battles.json is not on this PC')
    fights = data['fights']
    check('the real file: three fights, the player "dealt 23" and the killer in each', len(fights) == 3 and all(
        f['fighters'][0]['dealt'] == 23 and f['fighters'][2]['killer'] == '00000014' for f in fights))
    old = copy.deepcopy(fights[2])
    lira = next(f for f in battle.fighters(old) if f['name'] == 'Lira')
    text = battle.account(old, lira, 1)
    check('an older World record (no "struck") is told as it is', 'Brom killed Wolf' in text, text)
    new = copy.deepcopy(fights[2])
    new['fighters'][0]['struck'] = 0  # the newer plugin: the player landed no real blow
    for f in new['fighters'][1:]:
        f['struck'] = 1 if f['name'] == 'Lira' else 0
    lira = next(f for f in battle.fighters(new) if f['name'] == 'Lira')
    text = battle.account(new, lira, 1)
    check('newer record, the player landed nothing and cast nothing: no kill, no "killed by" and no share told for him',
          'Brom killed' not in text and 'killed by Brom' not in text and 'of the fighting' not in text.split('\n')[1]
          and 'Wolf (killed)' in text, text)
    player = next(f for f in battle.fighters(new) if f.get('role') == 'player')
    check('...his record reads no damage and no kills, the wolf no killer', player['dealt'] == 0 and player['kills'] == []
          and next(f for f in battle.fighters(new) if f['name'] == 'Wolf')['killer'] == '', player)
    struck = copy.deepcopy(fights[2])
    struck['fighters'][0]['struck'] = 1
    lira = next(f for f in battle.fighters(struck) if f['name'] == 'Lira')
    check('a player who landed a real blow keeps his kill', 'Brom killed Wolf' in battle.account(struck, lira, 1))
    cast = copy.deepcopy(fights[2])
    cast['fighters'][0]['struck'] = 0
    cast['fighters'][2]['harm'] = {'fire': ['00000014']}
    lira = next(f for f in battle.fighters(cast) if f['name'] == 'Lira')
    check('...and so does one whose cast hit a foe (no blow, a real spell)', 'Brom killed Wolf' in battle.account(cast, lira, 1))
    summon = copy.deepcopy(fights[2])
    summon['fighters'][0]['struck'] = 0
    summon['fighters'].append({'name': 'Flame Atronach', 'ref_id': 'FF000999', 'role': 'summon', 'owner': '00000014', 'side': 0,
                               'struck': 1, 'dealt': 20, 'kills': [], 'harm': {}, 'help': {}})
    lira = next(f for f in battle.fighters(summon) if f['name'] == 'Lira')
    check('...and one whose summon fought (its kill is put down to him)', 'Brom killed Wolf' in battle.account(summon, lira, 1))
    memory_text = battle.memory_line(copy.deepcopy(new), next(f for f in battle.fighters(copy.deepcopy(new)) if f['name'] == 'Lira'))
    check('the fight memory for Lira does not credit him either', 'Brom killed' not in memory_text, memory_text)


# --- 4. short bios: Adrianne, Valerica, Elisif --------------------------------------------------------------------------
def part_bios(tmp):
    check('the short-bio format is 6 (stored format-5 entries are written again)', BO.FORMAT_VERSION == 6)
    adrianne, valerica, elisif = _bio('Adrianne Avenicci'), _bio('Valerica'), _bio('Jarl Elisif the Fair')
    stored = _json('test-artifacts', 'living_world_bios.after.json')
    if not (adrianne and valerica and elisif and stored):
        return print('SKIP the live test 10 bio files are not on this PC')
    done = {e['name']: e for e in stored['bios'].values() if e.get('status') == 'done'}
    rules = BO.rule_items(adrianne)
    stirs = next((r for r in rules if r.endswith('stirs her like nothing else.')), '')
    such = next((r for r in rules if r.startswith('To such a person')), '')
    check("Adrianne: \"To such a person\" takes the sentence it points at with it, word for word, just before it",
          stirs.startswith('She grew up on tales of Tiber Septim') and stirs in adrianne and rules.index(stirs) + 1 == rules.index(such), rules)
    bad, _ = BO.problems(adrianne, done['Adrianne Avenicci']['text'], done['Adrianne Avenicci'].get('covered', ''), 'Adrianne Avenicci')
    check('...her stored short bio (that sentence reworded under History) now fails: it is written again',
          any('rule lines word for word' in b and 'She grew up on tales' in b for b in bad), bad)
    fixed = BO.with_rules(BO._body(done['Adrianne Avenicci']['text']), rules)
    check('...with the sentence carried in Rules her rule check passes', not BO.rules_missing(adrianne, fixed), BO.rules_missing(adrianne, fixed))

    sits = BO.situations(elisif)
    check('Elisif: her Embassy line is a situation with a reaction (surprised), nothing else of hers is',
          [(s[0], s[3]) for s in sits] == [('If approached at the Thalmor Embassy', ['surprised'])], sits)
    bad, _ = BO.problems(elisif, done['Jarl Elisif the Fair']['text'], done['Jarl Elisif the Fair'].get('covered', ''), 'Jarl Elisif the Fair')
    check('...her stored short bio (only "sometimes attends parties at the Thalmor Embassy") fails and the retry names it',
          any('how they react in these situations' in b and 'If approached at the Thalmor Embassy (surprised)' in b for b in bad), bad)
    kept = done['Jarl Elisif the Fair']['text'].replace(
        'Sometimes attends parties at the Thalmor Embassy west of Solitude, hosted by Ambassador Elenwen.',
        'Sometimes attends parties at the Thalmor Embassy west of Solitude, hosted by Ambassador Elenwen; if approached at the '
        'Thalmor Embassy she is surprised to see the player, since those parties are for jarls and business leaders.')
    check('...a short bio that keeps the situation and the reaction in one sentence passes that check', not BO.situations_missing(elisif, kept),
          BO.situations_missing(elisif, kept))
    split = done['Jarl Elisif the Fair']['text'] + ' She is surprised by many things.'
    check('...the reaction word in another sentence than the situation does not count', BO.situations_missing(elisif, split))

    text = done['Valerica']['text']
    bad, _ = BO.problems(valerica, text, done['Valerica'].get('covered', ''), 'Valerica')
    check('Valerica: her stored short bio passes every check (the two lines are facts, not rules)', not bad, bad)
    sentences = [BO._word_set(s) for s in text.replace('\n', '. ').split('. ')]
    holds = lambda *words: any(all(BO._has(s, w) for w in words) for s in sentences)
    check('...the meaning of both holds: her composure breaking when pushed past what satisfies her, and Serana\'s '
          'happiness and freedom of choice mattering to her',
          holds('pushed', 'satisfies', 'composure', 'breaks', 'frank') and holds('Serana', 'happiness', 'freedom', 'choice'))
    check('...and neither is a rule line (no instruction words: they say what she is and values)',
          not any('composure breaks' in r or "happiness and freedom" in r for r in BO.rule_items(valerica)))

    # the whole real file: which stored short bios the new checks reject
    newly = []
    for name, entry in done.items():
        original = _bio(name)
        if original is None:
            continue
        bad, _ = BO.problems(original, entry['text'], entry.get('covered', ''), name)
        if bad:
            newly.append(name)
    # live test 11 added the rumour check: Zeljka's "Looks: tall, red" (a rumour in her bio) fails it in this run's text too
    check('over the 37 stored format-5 short bios of the run, only Adrianne, Elisif and (since live test 11) Zeljka now fail',
          sorted(newly) == ['Adrianne Avenicci', 'Jarl Elisif the Fair', 'Zeljka'], newly)
    clean = set(done) - {'Zeljka', 'Senna', 'Lisarin', 'Iris', 'Celcia', 'Alanna', 'Lenita The Fragile', 'Lyn Lauet', 'Rebecca Montclair',
                         'Valerica', 'Adrianne Avenicci', 'Jarl Elisif the Fair'}
    check(f'...none of the {len(clean)} the review found clean is rejected', not clean & set(newly), clean & set(newly))
    for name in ('Aela the Huntress', 'Faralda', 'Senna'):
        check(f"{name}: lines like \"I'm afraid\", \"don't put on that angry look\", \"he's worried\" are no reaction of theirs",
              not BO.situations(_bio(name)), BO.situations(_bio(name)))


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    for part in (part_rating, part_wares, part_battle, part_bios):
        try:
            part(tmp)
        except Exception as e:
            import traceback
            traceback.print_exc()
            check(f'{part.__name__} ran without an error', False, e)

print(f"\n{len(FAILS)} failure(s)" if FAILS else '\nall passed')
sys.exit(1 if FAILS else 0)
