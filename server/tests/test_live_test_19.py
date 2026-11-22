"""Offline tests for live session 19 (2026-11-18), from the lines that session logged: a stranger who is no merchant
agreed a sale, took the player's "Here you go" as the payment and called give_item, which World's gate refused; the
summary then kept the sale nobody finished as the player's debt ("Still owe me thirteen gold for that goat cheese").
Run with a Python 3.11: test_live_test_19.py <repo server dir>"""
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


class Lines(logging.Handler):
    def __init__(self):
        super().__init__(1)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


LOG = Lines()
logging.getLogger('Mantella').addHandler(LOG)
logging.getLogger('Mantella').setLevel(1)


class Char:
    def __init__(self, name, ref_id, bio='A person.'):
        self.name, self.ref_id, self.bio = name, ref_id, bio

class UserMessage:
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
        self.messages, self.characters = Thread(UserMessage(l) for l in lines), chars

class People:
    def get_player_name(self):
        return 'Brom'

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


# World's own refusal line from the session (MLWW_Trade GiveItem, a stranger's goods)
REFUSED = ("(Nothing happened: Gerdur does not know Brom well and hands over gold or goods only as payment for what Brom "
           "gives first, and Brom has given nothing yet in this talk, and Goat Cheese Wedge is worth 13 gold.)")
TALK = ['Could you spare me something to eat, Gerdur? I am famished.',
        "Gerdur: I'm not one for handouts, but I'll sell you a wedge of goat cheese. Say ten gold and it's yours.",
        'Fair enough, ten gold for the cheese then. Here you go.',
        "Gerdur: I'll trust that you've handed over the ten gold, so here's your cheese.",
        REFUSED,
        'Gerdur: Hold on, no coin has crossed my palm yet. Hand over the coin first and then the cheese is yours.',
        'Thanks, Gerdur.',
        "Gerdur: I still haven't seen a coin from you, so no cheese yet."]
DEBT = 'Brom must pay thirteen gold for the wedge of goat cheese before Gerdur hands it over'
CHORE = 'Brom will chop wood for Gerdur tomorrow'


# --- the gate line: someone who is no merchant sells payment first ---------------------------------------------------
def part_gate():
    ask = [{'role': 'user', 'content': 'Fair enough, ten gold for the cheese then. Here you go.'}]
    gerdur = {'name': 'Gerdur', 'close': 0, 'follower': 0}
    line = trade.gate_text([gerdur], ask, 'Brom')
    check('a stranger who is no merchant: the sale goes payment first (ask_gold), the spoken payment is none',
          'asks for the gold first with Trade ask_gold' in line and "only once Brom's gold is in Gerdur's hand" in line
          and 'Brom saying it was paid puts no gold there' in line, line)
    check('...in plain words of the talk, nothing an NPC could read out as a game record',
          not any(word in line.lower() for word in ('game', 'record', 'shows')), line)
    check('...the gate line itself is unchanged before it', line.startswith(
        '(Gerdur does not know Brom well enough to give anything away: no gold, food, drink or goods as a gift, only a sale '
        'or paying back what Brom handed over first, so Gerdur does not offer it. In a sale') and line.endswith('.)'), line)
    lucan = {'name': 'Lucan Valerius', 'close': 0, 'follower': 0, 'merchant': 1}
    sold = trade.gate_text([lucan], ask, 'Brom')
    check('a merchant: no payment-first line (offer_trade moves the gold and the goods together)',
          sold.endswith('does not offer it.)') and 'ask_gold' not in sold, sold)
    check('a close friend: still no line', trade.gate_text([{'name': 'Alvor', 'close': 1}], ask, 'Brom') == '')
    talk = [{'role': 'user', 'content': 'How is the mill doing?'}]
    check('a line about no trade: still no line', trade.gate_text([gerdur], talk, 'Brom') == '')


# --- a refused trade is a non-event for the memory --------------------------------------------------------------------
def part_marks():
    marked = memory.mark_refused('Here you go.\n' + REFUSED + '\nThanks.')
    check('the summary reads the refused line marked as a non-event', REFUSED + memory.REFUSED_NOTE in marked, marked)
    check('...once only', memory.mark_refused(marked) == marked)
    check('a talk with no refused line is left as it is', memory.mark_refused('Hello. (Brom picked up 5 Gold)') == 'Hello. (Brom picked up 5 Gold)')
    check('a refused line in double brackets (as Mantella shows it) is marked too',
          memory.REFUSED_NOTE in memory.mark_refused('(' + REFUSED + ')'))
    check('not a string: given back as it is', memory.mark_refused(None) is None)
    check('the goods of the refused trade are found', memory.refused_goods(TALK) == ['Goat Cheese Wedge'], memory.refused_goods(TALK))
    later = TALK + ['(Gerdur handed Brom Goat Cheese Wedge; it was handed over.)']
    check('goods handed over later in the talk do not count as refused', memory.refused_goods(later) == [], memory.refused_goods(later))
    offer = ['(Nothing happened: Brom has only 20 gold; 2 Iron Sword costs 100)',
             '(Nothing happened: Brom declined to buy Potion of Minor Healing for 52 gold.)',
             '(Nothing happened: Lucan carries nothing called "Elven Bow" that can be handed over.)']
    check('a refused sale and an unknown ware name their goods', memory.refused_goods(offer) == ['Iron Sword', 'Potion of Minor Healing', 'Elven Bow'],
          memory.refused_goods(offer))
    check('no talk: nothing', memory.refused_goods(None) == [])


def part_promises():
    mem = memory.empty()
    reply = json.dumps({'memory': 'x', 'promises': [{'text': DEBT, 'by': 'Brom', 'due_in_days': None},
                                                    {'text': CHORE, 'by': 'Brom', 'due_in_days': 1}]})
    memory.add_promises(mem, reply, 3, refused=['Goat Cheese Wedge'])
    texts = [f['text'] for f in mem['facts']]
    check('paying for goods of a refused trade is no promise', DEBT not in texts, texts)
    check('...another promise of the same talk is kept', CHORE in texts, texts)
    check('...and logged', any('not kept as a promise (a trade the game refused)' in l for l in LOG.lines))
    mem = memory.empty()
    memory.add_promises(mem, reply, 3)
    check('with no refused trade the debt is kept as before', [f['text'] for f in mem['facts']] == [DEBT, CHORE], mem['facts'])
    mem = memory.empty()
    memory.add_promises(mem, json.dumps({'promises': [{'text': 'Brom will bring Gerdur goat cheese from Whiterun', 'by': 'Brom'}]}),
                        3, refused=['Goat Cheese Wedge'])
    check('a promise naming the goods but no payment is kept', len(mem['facts']) == 1, mem['facts'])


def part_summary(tmp):
    store = memory.MemoryStore(str(tmp / 'conversations'), 'Brom1')
    gerdur = Char('Gerdur', '013489')
    reply = json.dumps({'memory': 'Brom asked for food; I offered goat cheese for ten gold, but no coin reached my hand, so he '
                                  'has no cheese yet.', 'feelings': {'Gerdur': 'wary'},
                        'promises': [{'text': DEBT, 'by': 'Brom', 'due_in_days': None}, {'text': CHORE, 'by': 'Brom', 'due_in_days': 1}],
                        'importance': 0.3})
    summaries = Summaries({'Gerdur': Params(TALK, [gerdur])}, reply)
    ctx = {'messages': None, 'npcs_to_summarize': [gerdur], 'npcs_in_conversation': People(), 'is_reload': False,
           'end_timestamp': 1.7, 'is_radiant': False, 'summaries': summaries, 'is_minor': lambda c: False,
           'unrecognised': lambda c: False}
    memory.summarize(ctx, store)
    check('the summary call got the refused line marked as a non-event',
          summaries.calls and REFUSED + memory.REFUSED_NOTE in summaries.calls[0][0], summaries.calls[:1])
    facts = [f['text'] for f in store.load('Gerdur', '013489')['facts']]
    check('her memory keeps no debt for the cheese she never handed over', DEBT not in facts, facts)
    check('...but keeps the real promise of that talk', CHORE in facts, facts)


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    for part in (part_gate, part_marks, part_promises, lambda: part_summary(tmp)):
        try:
            part()
        except Exception as e:
            import traceback
            traceback.print_exc()
            check(f'{getattr(part, "__name__", "part")} ran without error', False, e)

print('RESULT:' + ('ALL PASS' if not FAILS else f'{len(FAILS)} FAILED: {FAILS}'))
sys.exit(1 if FAILS else 0)
