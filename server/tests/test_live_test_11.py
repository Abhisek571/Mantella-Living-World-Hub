"""Offline tests for the leftovers of live test 11 (2026-11-16), built from the real files that run left: a log line when
a rating request becomes an action note, the purse line that came back spoken as reasoning about the NPC, the merchant
line that made Lucan refuse wares his chest held, and the cheap short-bio checks ({player_name} added, a rumour stated
as fact, a spoken word listed as an insult). The run's files are read from the live test's folder when it is on this PC
(never copied into the repository); a part that needs them is skipped without them.
Run with a Python 3.11: test_live_test_11.py <repo server dir>"""
import json, logging, os, sys
from pathlib import Path

SERVER = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(SERVER))
from living_world import action_args, bio_optimise as BO, silent_requests as SR, trade

LIVE11 = os.path.join(os.environ.get('MLW_EVIDENCE', ''), r'lw-live-test-11-2026-11-16')
FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)[:700]) if not cond else ''))
    if not cond:
        FAILS.append(name)


def _json(*parts):
    try:
        with open(os.path.join(LIVE11, *parts), encoding='utf-8-sig') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _bio(name):
    data = _json('character_overrides-before', name + '.json')
    return (data[0] if isinstance(data, list) else data)['bio'] if data else None


class Catch(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []
    def emit(self, record):
        self.lines.append(record.getMessage())


# --- 1. the rating request did leave the events: now a log line says so -----------------------------------------------
# logging.log 08:58:31: Mantella's "Received in-game events" (written before the dialogue_events hook) still lists the
# request, while "In-game events since previous exchange" (after the hook) does not: the hook ran
TURN = ['lira sees the player as a trusted ally. ', 'Brom looks a little flushed.', 'lira seems noticeably aroused, though she keeps it to herself.',
        "lira's sexual appetite has not been rated yet. Give the rating only as the number in the RateAppetite action: never say, "
        "hint at or describe it, or mention this note; the spoken reply goes on with the talk exactly as it would without it.",
        'lira picked up/took 100 Gold']


def part_log():
    catch = Catch()
    log = logging.getLogger('Mantella')
    log.addHandler(catch)
    log.setLevel(logging.INFO)
    try:
        SR.clear()
        out = SR.take(list(TURN))
        check('the real turn of 08:58: the request leaves the events', len(out) == 4 and not any('rated' in e for e in out), out)
        check('...and the Hub logs it, so the log shows it was moved',
              'Living World: rating request for lira sent as an action note (RateAppetite)' in catch.lines, catch.lines)
        SR.take(['lira smiles.'])
        check('...nothing is logged for a turn without a request', len(catch.lines) == 1, catch.lines)
    finally:
        log.removeHandler(catch)
        SR.clear()


# --- 2. the purse line spoken back as reasoning -------------------------------------------------------------------------
# logging.log 08:56:14: "(lira picked up/took 100 Gold)" then "Lira, could you lend me 30 gold?"; the Hub's line for her
# said "what the newest events say lira picked up or was handed is lira's now", and the reply spoken was "She just picked
# up 100 gold, so she can cover thirty and might as well use it to tease him."
def part_purse():
    lira = {'name': 'lira', 'carry_gold': 100, 'carry_items': 'Glass Dagger'}
    turn = [{'role': 'user', 'content': "(lira picked up/took 100 Gold)\n(lira changed outfit, now wearing Cosplay Gala Gown "
                                        "'Saturnalia' - Amber and 3 more.)\n(lira equipped Glass Dagger)\nNyri, could you lend me 30 gold?"}]
    trade._seen.clear()
    line = trade.carry_text([lira], turn)
    check('the real turn: her line is a plain fact, no events to reason from ("the newest events say ... is hers now")',
          line == "(lira's purse and pack hold what lira had plus what lira picked up or was handed in this talk.)"
          and 'events' not in line and ' now' not in line, line)
    trade._seen.clear()


# --- 3. Lucan refused wares his chest held ------------------------------------------------------------------------------
LUCAN = {'name': 'Lucan Valerius', 'carry_gold': 120, 'carry_items': '', 'merchant': 1, 'wares_complete': 1,  # his npc file of 09:03:49, in part
         'wares': ['Misc|2|7|Charcoal', 'Misc|3|61|Steel Ingot', 'WEAPON|1|76|Iron Sword', 'ARMOR|1|60|Iron Helmet',
                   'Misc|1|16|Goat Hide', 'potion|1|30|Potion of Minor Healing', 'food|3|3|Bread', 'misc|5|7|Lockpick']}


def part_wares():
    ask = [{'role': 'user', 'content': 'Sell me the Iron Helmet for 50 gold.'}]
    line = trade.carry_text([LUCAN], ask)
    # live test 15: a chest that fits is named in full, so the Iron Helmet is in the line and the line is the whole stock
    check('the whole stock is named and any of it is sold with Trade offer_trade (the Iron Helmet he was asked for too)',
          "Lucan Valerius's whole shop stock: Lucan Valerius sells any of it asked for with Trade offer_trade (no price "
          'agreed: shop price)' in line and 'Iron Helmet 60 gold' in line
          and 'offer to check' not in line and 'not a full list' not in line, line)
    after = [{'role': 'user', 'content': "(Lucan Valerius's barter menu opened.)\nThen sell me an Iron Sword for 30 gold."}]
    line = trade.carry_text([LUCAN], after)
    check('after the barter menu restocked: he still tries the sale and lets the result decide (no "checks before promising")',
          'still tries a sale asked for with Trade offer_trade and lets the result decide' in line and 'checks before promising' not in line, line)
    args = action_args.normalise({'kind': 'offer_trade', 'item': 'Iron Helmet', 'price': '50', 'count': 1},
                                 {'kind': {'type': 'string'}, 'item': {'type': 'string'}, 'price': {'type': 'integer'},
                                  'count': {'type': 'integer'}}, 'mantella_mlww_trade')
    check('nothing on the Hub side holds an unlisted ware back: the arguments reach the game as asked (only typed)',
          args.get('item') == 'Iron Helmet' and args.get('price') == 50, args)
    src = ''.join(open(SERVER / 'living_world' / f, encoding='utf-8').read() for f in os.listdir(SERVER / 'living_world') if f.endswith('.py'))
    check('...and no Hub code reads the wares list except to write the line', src.count("get('wares')") == 1, src.count("get('wares')"))


# --- 5. short bios: the cheap checks ------------------------------------------------------------------------------------
def part_bios():
    stored = _json('test-artifacts', 'living_world_bios.after.json')
    if not stored or not _bio('Lydia'):
        return print('SKIP the live test 11 bio files are not on this PC')
    done = {e['name']: e for e in stored['bios'].values() if e.get('status') == 'done'}
    judged = {}
    for name, entry in done.items():
        original = _bio(name)
        if original is not None:
            judged[name] = BO.problems(original, entry['text'], entry.get('covered') or '', name)[0]
    failing = sorted(n for n, bad in judged.items() if bad)
    check(f'over the {len(judged)} stored format-6 short bios of the run, exactly Aela, Lily, Lydia and Zeljka now fail',
          failing == ['Aela the Huntress', 'Lily', 'Lydia', 'Zeljka'], failing)
    check('Lydia and Lily: {player_name} added where the bio says "the player"',
          all(any('placeholders the sheet does not have: {player_name}' in b for b in judged[n]) for n in ('Lydia', 'Lily')),
          (judged.get('Lydia'), judged.get('Lily')))
    check('...a placeholder the bio itself has stays allowed', not BO.placeholders_added('Calls {player_name} friend.', 'Calls {player_name} friend.'))
    check('Zeljka: "Looks: tall, red" states as fact what the bio gives as a rumour (the rumoured Alchemist\'s Shack line is fine)',
          any('only as a rumour' in b and 'tall red woman' in b for b in judged['Zeljka']), judged['Zeljka'])
    check('...rumours kept as rumours pass (Iris, Gariel, Lenita: no false hit)',
          not any(judged.get(n) for n in ('Iris', 'Gariel', 'Kariel', 'Nariel', 'Lenita The Fragile')))
    check('Aela: "snowberries" listed after "Calls the unproven" is a word from a spoken line, not her insult',
          any('"snowberries"' in b for b in judged['Aela the Huntress']), judged['Aela the Huntress'])
    check('...only "snowberries": the other listed words are fine (the sheet uses them so, or the lines are samples)',
          all('"milk drinker"' not in b and '"whelps"' not in b for b in judged['Aela the Huntress']), judged['Aela the Huntress'])


for part in (part_log, part_purse, part_wares, part_bios):
    try:
        part()
    except Exception as e:
        import traceback
        traceback.print_exc()
        check(f'{part.__name__} ran without an error', False, e)

print(f"\n{len(FAILS)} failure(s)" if FAILS else '\nall passed')
sys.exit(1 if FAILS else 0)
