"""Offline tests for live session 20 (2026-11-20), from the lines that session logged:
  - Gerdur (no merchant, a stranger) acted out a sale on "How is your family doing" (no trade word, so the gate line was
    not in that request) and called give_item with no gold paid;
  - Hod (no merchant, a stranger) took the player's 10 gold through the gold box, then said "Here's your beef" with no
    give_item, so nothing reached the player;
  - Gerdur's memory and next talk said "You paid ten gold for that cheese and I handed it over" while no gold moved and
    she never handed the cheese over: the summary believed the spoken words over the game.
Run with a Python 3.11: test_live_test_20.py <repo server dir>"""
import json, logging, sys, tempfile
from pathlib import Path

SERVER = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(SERVER))
from living_world import embed, memory, trade
memory.SUMMARY_RETRY_SECONDS = 0
embed.use(None)

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)[:700]) if not cond else ''))
    if not cond:
        FAILS.append(name)


logging.getLogger('Mantella').setLevel(100)

PLAYER = 'Brom'
GERDUR = {'name': 'Gerdur', 'close': 0, 'follower': 0}
HOD = {'name': 'Hod', 'close': 0, 'follower': 0}
LUCAN = {'name': 'Lucan Valerius', 'close': 0, 'follower': 0, 'merchant': 1}


def user(text):
    return {'role': 'user', 'content': text}


def npc(text):
    return {'role': 'assistant', 'content': text}


# Gerdur's talk as the session sent it (the player's lines, her replies; the refused requests got no reply)
GERDUR_TALK = [
    user("(Gerdur's ties: child Frodnar; sibling Ralof; husband Hod; employs Sven, Faendal.)\n"
         "Could you spare me something to eat, Gerdur? I'm famished."),
    npc("Mara's mercy, you do look hungry, but I don't hand out food to folks I just met. I've got a wedge of goat cheese "
        "I could sell you for a fair price, or Alvor and Lucan in the village might have more for sale."),
    user('Fair enough, ten gold for the cheese then. Here you go.'),
    user('Fair enough, ten gold for the cheese then. Here you go.'),
    user('(Characters nearby (from nearest to furthest): Travelling Alchemist)\n'
         'Alright, I\'d like to buy that goat cheese. How much do you want for it?'),
    user('(The time is 1 in the afternoon.)\nHow is your family doing these days, Gerdur?'),
]
REFUSED_GERDUR = ("(Nothing happened: Gerdur does not know Brom well and hands over gold or goods only as payment for what "
                  "Brom gives first, and Brom has given nothing yet in this talk, and Goat Cheese Wedge is worth 13 gold.)")

# Hod's talk: the gold box moved 10 gold (World's line plus the game's own pick-up lines), no beef was handed over
PAID_LINE = '(Brom handed Hod 10 gold; it was handed over.)'
HOD_TALK = [
    user("(Hod's ties: child Frodnar; wife Gerdur.)\nCould you spare me something to eat, Hod? I'm famished."),
    npc("Famished, are ya? I ain't runnin' a charity, friend, but I'll sell ya a bit of cooked beef if ya got coin. Ten "
        "gold and it's yours, and I'll hold the ale for my own thirst."),
    user('Fair enough, ten gold for the beef then. Here you go.'),
    npc("I'll take that ten gold, then the beef is yours."),
    user('(Hod picked up/took 10 Gold)\n(Brom dropped/gave 10 Gold)\n(' + PAID_LINE + ')'),
    npc("Ten gold, fair and square. Here's your beef, and eat it slow so it don't come back on ya."),
    user('Thanks, Hod. Did you hand me the beef?'),
]


# --- the trade gate stays for the whole talk, with the game's record of it -----------------------------------------
def part_gate():
    line = trade.gate_text([GERDUR], GERDUR_TALK, PLAYER)
    check('a line with no trade word after a sale was asked about: the gate line is still there',
          'gold first with Trade ask_gold' in line and 'saying it was paid puts no gold there' in line, line)
    check('...with what really changed hands: nothing',
          '(In this talk so far, no gold or goods changed hands between Brom and Gerdur.)' in line, line)
    check('...no "goods only once handed" sentence when nothing was paid',
          trade.PAID_NOTHING_BACK.format(player=PLAYER, name='Gerdur') not in line, line)
    check('...no game or record words an NPC could read out',
          not any(word in line.lower() for word in ('game', 'record', 'shows')), line)

    line = trade.gate_text([HOD], HOD_TALK, PLAYER)
    check('Hod paid through the gold box: the record says so and that nothing came back',
          '(In this talk so far, Brom handed Hod 10 gold; Hod handed Brom nothing. '
          "The goods are in Brom's hands only once Hod hands them over with Trade give_item.)" in line, line)
    check('...no game or record words an NPC could read out',
          not any(word in line.lower() for word in ('game', 'record', 'shows')), line)

    handed = HOD_TALK + [npc('Here you go.'), user('(Hod handed Brom Cooked Beef; it was handed over.)\nThanks.')]
    line = trade.gate_text([HOD], handed, PLAYER)
    check('after give_item went through: the beef is in the line, no "goods only once handed" sentence',
          'Brom handed Hod 10 gold; Hod handed Brom Cooked Beef.)' in line and 'only once Hod hands them over' not in line, line)

    only_game = HOD_TALK[:4] + [user('(Hod picked up/took 10 Gold)\n(Brom dropped/gave 10 Gold)\nThere.')]
    line = trade.gate_text([HOD], only_game, PLAYER)
    check("the game's own pick-up lines are not a trade result (World's line is the record)",
          'no gold or goods changed hands between Brom and Hod' in line, line)

    lucan = [user("I'd like to buy a Potion of Minor Healing."), npc('Of course.'), user('Tell me about the theft at your shop.')]
    check('a merchant: no line on a later line without trade words (as before)', trade.gate_text([LUCAN], lucan, PLAYER) == '')
    now = trade.gate_text([LUCAN], lucan[:1], PLAYER)
    check('a merchant on a trade line: the gate line as before, no record line',
          now.endswith('does not offer it.)') and 'In this talk so far' not in now, now)
    check('a close friend: no line', trade.gate_text([{'name': 'Alvor', 'close': 1}], GERDUR_TALK, PLAYER) == '')
    check('a talk that never asked for anything: no line',
          trade.gate_text([GERDUR], [user('How is the mill doing?'), npc('Busy.'), user('And Frodnar?')], PLAYER) == '')
    check('the gate line text before the new parts is unchanged', trade.gate_text([GERDUR], GERDUR_TALK, PLAYER).startswith(
        '(Gerdur does not know Brom well enough to give anything away: no gold, food, drink or goods as a gift, only a sale '
        'or paying back what Brom handed over first, so Gerdur does not offer it. In a sale'))


def part_ledger():
    rec = trade.ledger(['(' + PAID_LINE + ')\n' + PAID_LINE], 'Hod', PLAYER)
    check('an event shown twice in one message counts once', rec['paid'] == 10, rec)
    rec = trade.ledger(['(' + PAID_LINE + ')', '(' + PAID_LINE + ')'], 'Hod', PLAYER)
    check('two payments in two messages count twice', rec['paid'] == 20, rec)
    rec = trade.ledger(['(Brom handed Hod 1,200 gold (all Brom had) instead of the 1500 gold asked for; it was handed over.)'],
                       'Hod', PLAYER)
    check('a custom answer and "all he had": the gold that really moved', rec['paid'] == 1200, rec)
    rec = trade.ledger(['(Hod handed Brom 2 Cooked Beef (only 2 were there); it was handed over.)'], 'Hod', PLAYER)
    check('goods handed to the player, the "only" note left out', rec['goods_out'] == ['2 Cooked Beef'], rec)
    rec = trade.ledger(['(Brom bought Potion of Minor Healing from Lucan Valerius for 52 gold; the goods and the gold were '
                        'handed over.)'], 'Lucan Valerius', PLAYER)
    check("a merchant's sale: gold paid and goods out", rec['paid'] == 52 and rec['goods_out'] == ['Potion of Minor Healing'], rec)
    rec = trade.ledger([REFUSED_GERDUR, 'Here you go, ten gold.'], 'Gerdur', PLAYER)
    check('a refused trade and spoken payment move nothing', rec == {'paid': 0, 'back': 0, 'goods_in': [], 'goods_out': []}, rec)
    rec = trade.ledger(['(Brom handed Hodric 10 gold; it was handed over.)'], 'Hod', PLAYER)
    check('another NPC whose name starts the same is not this one', rec['paid'] == 0, rec)
    check('no player name: nothing', trade.ledger([PAID_LINE], 'Hod', '')['paid'] == 0)
    # World's refusal now also names the least price: the memory still finds the goods in it (no debt kept for them)
    new_refusal = ("(Nothing happened: Hod does not know Brom well and hands over gold or goods only as payment: Brom has "
                   "handed over 5 gold's worth in this talk, and Cooked Beef is worth 16 gold; Hod hands it over for 8 gold or more.)")
    check("World's longer refusal still names the goods for the memory", memory.refused_goods([new_refusal]) == ['Cooked Beef'],
          memory.refused_goods([new_refusal]))


def part_debug_log():
    import living_world as hub
    from living_world import lw_state
    seen = []
    class Grab(logging.Handler):
        def emit(self, record):
            seen.append(record.getMessage())
    log = logging.getLogger('Mantella')
    grab, level = Grab(), log.level
    log.addHandler(grab)
    log.setLevel(1)
    real = lw_state.debug_log
    try:
        lw_state.debug_log = lambda: True
        hub._logged_gate('(In this talk so far, x.)')
        check('debug log on: the trade gate line is logged', any('trade gate in this request: (In this talk so far' in l for l in seen), seen)
        seen.clear()
        lw_state.debug_log = lambda: False
        check('debug log off: the line is given back, nothing logged', hub._logged_gate('(x)') == '(x)' and not seen, seen)
    finally:
        lw_state.debug_log = real
        log.removeHandler(grab)
        log.setLevel(level)


# --- the summary and the memory keep the game's record over the words ------------------------------------------------
class Char:
    def __init__(self, name, ref_id, bio='A person.'):
        self.name, self.ref_id, self.bio = name, ref_id, bio

class Line:
    def __init__(self, text):
        self.text = text
    def get_formatted_content(self):
        return self.text
    def __str__(self):
        return self.text

class Thread(list):
    def get_talk_only(self, include_system_generated_messages=False):
        return list(self)
    def transform_to_dict_representation(self, messages):
        return '\n'.join(str(m) for m in messages)

class Params:
    def __init__(self, lines, chars):
        self.messages, self.characters = Thread(Line(l) for l in lines), chars

class People:
    def get_player_name(self):
        return PLAYER

class Summaries:
    def __init__(self, threads, reply):
        self.threads, self.reply, self.calls = threads, reply, []
    def get_threads_for_summarization(self, messages, npcs):
        return self.threads
    def group_shared_threads(self, threads):
        return [list(threads)]
    def summarize_conversation(self, text, prompt):
        self.calls.append((text, prompt))
        return self.reply


def lines(talk, name):
    return [(m['content'] if m['role'] == 'user' else f"{name}: {m['content']}") for m in talk]


def summarize(tmp, char, talk, reply):
    store = memory.MemoryStore(str(tmp / ('conversations-' + char.name)), 'Brom1')
    summaries = Summaries({char.name: Params(talk, [char])}, json.dumps(reply))
    ctx = {'messages': None, 'npcs_to_summarize': [char], 'npcs_in_conversation': People(), 'is_reload': False,
           'end_timestamp': 1.7, 'is_radiant': False, 'summaries': summaries, 'is_minor': lambda c: False,
           'unrecognised': lambda c: False}
    memory.summarize(ctx, store)
    return summaries, store.load(char.name, char.ref_id)


def part_summary(tmp):
    gerdur = Char('Gerdur', '013489')
    talk = lines(GERDUR_TALK, 'Gerdur') + ["Gerdur: Ten gold for a wedge of goat cheese is fair, so here you go.",
                                          REFUSED_GERDUR, 'Fine, here are ten gold for the cheese.']
    false_sale = {'memory': 'A traveler asked for food; they paid ten gold and I handed the cheese over.',
                  'feelings': {'Gerdur': 'friendly'}, 'promises': [], 'importance': 0.3}
    summaries, mem = summarize(tmp, gerdur, talk, false_sale)
    sent = summaries.calls[0][0] if summaries.calls else ''
    check("the summary reads the game's record: nothing changed hands",
          'no gold or goods changed hands between Brom and Gerdur' in sent and memory.RECORD_ASK.split('{')[0] in sent, sent[-400:])
    text = mem['recent'][-1]['text'] if mem['recent'] else ''
    check("a memory that says she was paid and handed the cheese over carries the game's record after it",
          text.endswith('(What really happened in that talk: no gold or goods changed hands between Brom and Gerdur.)'), text)
    check('...in plain words of the talk, nothing an NPC could read out as a game record',
          not any(word in text.lower() for word in ('game', 'record')), text)
    check('...the words of the memory are kept as the model wrote them', text.startswith(false_sale['memory']), text)

    hod = Char('Hod', '01348A')
    talk = lines(HOD_TALK, 'Hod')
    true_memory = {'memory': 'I took ten gold for cooked beef but never handed the beef over.', 'promises': [], 'importance': 0.3}
    summaries, mem = summarize(tmp, hod, talk, true_memory)
    sent = summaries.calls[0][0] if summaries.calls else ''
    check("Hod's summary reads the record: 10 gold to Hod, nothing back", 'Brom handed Hod 10 gold; Hod handed Brom nothing' in sent,
          sent[-400:])
    text = mem['recent'][-1]['text'] if mem['recent'] else ''
    check('a memory saying goods were handed over (or not) gets the record: the beef never came',
          text.endswith('(What really happened in that talk: Brom handed Hod 10 gold; Hod handed Brom nothing.)'), text)

    paid_back = {'memory': 'Brom paid me ten gold and I gave him the cooked beef.', 'promises': [], 'importance': 0.3}
    done = talk + ['(Hod handed Brom Cooked Beef; it was handed over.)']
    summaries, mem = summarize(tmp, Char('Hod', '01348B'), done, paid_back)
    text = mem['recent'][-1]['text'] if mem['recent'] else ''
    check('a memory that matches the record is kept as written', text == paid_back['memory'], text)

    chat = ['How is the mill doing?', 'Sigrid: Busy, the logs keep coming.', 'And Dorthe?', 'Sigrid: Running about, as always.',
            'I gave her a wooden sword once.', 'Sigrid: She still has it.']
    plain = {'memory': 'We talked about the mill; Brom said he gave Dorthe a wooden sword once.', 'promises': [], 'importance': 0.2}
    summaries, mem = summarize(tmp, Char('Sigrid', '013485'), chat, plain)
    sent = summaries.calls[0][0] if summaries.calls else ''
    text = mem['recent'][-1]['text'] if mem['recent'] else ''
    check('a talk with no trade: no record in the summary text and none on the memory',
          'What really happened' not in sent and memory.RECORD_ASK.split('{')[0] not in sent and text == plain['memory'], (sent, text))


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    for part in (part_gate, part_ledger, part_debug_log, lambda: part_summary(tmp)):
        try:
            part()
        except Exception as e:
            import traceback
            traceback.print_exc()
            check(f'{getattr(part, "__name__", "part")} ran without error', False, e)

print('RESULT:' + ('ALL PASS' if not FAILS else f'{len(FAILS)} FAILED: {FAILS}'))
sys.exit(1 if FAILS else 0)
