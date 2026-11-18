"""Offline tests for live session 12 (2026-11-16), built from the real files it left: a memory saved as the summary's
raw JSON (the reply was cut off), menu dialogue spoken before Mantella's first talk of the session, and an NPC whose
gold count was dropped because she picked up an ale. The session's files are read from its folder when it is on this
PC (never copied into the repository); a part that needs them is skipped without them.
Run with a Python 3.11: test_live_test_12.py <repo server dir>"""
import json, os, sys, tempfile
from pathlib import Path
from types import SimpleNamespace

SERVER = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(SERVER))
from living_world import archive, memory, menu_dialogue, trade

LIVE12 = os.path.join(os.environ.get('MLW_EVIDENCE', ''), r'lw-live-test-12-2026-11-16')
FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)[:700]) if not cond else ''))
    if not cond:
        FAILS.append(name)


def _summary_reply():
    try:
        with open(os.path.join(LIVE12, 'test-artifacts', 'logging.log'), encoding='utf-8', errors='replace') as f:
            for line in f:
                if '09:48:05,222 LLM: Conversation summary: ' in line:
                    return line.split('Conversation summary: ', 1)[1].strip()
    except OSError:
        return None


# --- 1. the summary saved as raw JSON ------------------------------------------------------------------------------------
def part_summary():
    reply = _summary_reply()
    if not reply:
        return print('SKIP the live session 12 log is not on this PC')
    check('the real reply is cut off before its end (why it could not be read as JSON)', reply.endswith('"physical":'), reply[-40:])
    text, feelings = memory.parse_summary(reply, ['Gerdur'])
    check('...its memory is read from the complete part, never the wrapper', text.startswith('The hooded stranger came back asking for help')
          and '{' not in text and '"memory"' not in text, text[:120])
    check('...with her feeling', feelings.get('Gerdur', '').startswith('wary and ashamed'), feelings)
    data = memory._summary_data(reply)
    check('...and the promises, mood and importance of the complete members', len(data.get('promises') or []) == 2
          and data.get('importance') == 0.7 and data.get('emotion') == 'guilt', sorted(data))
    fenced = '```json\n{"memory": "We traded.", "feelings": {"Lucan": "content"}}\n```'
    check('a fenced reply and a plain text reply still work', memory.parse_summary(fenced, ['Lucan']) == ('We traded.', {'Lucan': 'content'})
          and memory.parse_summary('We traded quietly.', ['Lucan'])[0] == 'We traded quietly.')
    check('a reply cut inside its memory text keeps the text it has, not the wrapper',
          not memory.parse_summary('{"memory": "We traded and then', ['Lucan'])[0].startswith('{'))


def part_stored():
    path = os.path.join(LIVE12, 'test-artifacts', 'conversations-Brom1', 'living_world', 'Gerdur - 013489.json')
    if not os.path.isfile(path):
        return print('SKIP the stored Gerdur memory is not on this PC')
    raw = json.load(open(path, encoding='utf-8'))
    check('the stored memory is the wrapper (cut at 1200 characters)', raw['recent'][0]['text'].startswith('{"memory": '))
    shown = memory.clean(raw)['recent'][0]['text']
    check('read back, it is shown unwrapped', shown.startswith('The hooded stranger came back') and not shown.startswith('{'), shown[:80])
    row = archive.Archive._row(tuple(raw['recent'][0]['text'] if c == 'text' else None for c in archive.COLUMNS))
    check("...and so is the archive's copy", row['text'].startswith('The hooded stranger came back'), row['text'][:80])
    check('ordinary text and other JSON-looking text are left alone', archive.unwrap_text('I met {player}.') == 'I met {player}.'
          and archive.unwrap_text('{"other": 1}') == '{"other": 1}' and archive.unwrap_text(None) is None)


# --- 2. menu dialogue spoken before Mantella's first talk ---------------------------------------------------------------
# MLWW_Listener.log 09:43:00-09:43:40 (the first exchange, lost) and 09:44:33-09:44:46 (the second, which Mantella kept);
# the topics of the first exchange are not in any log: those here stand in for them
WORLD = {'player': 'Brom', 'npcs': {'013489': {'name': 'Gerdur', 'lines': [
    {'said': "Gerdur, you're the heart of this town. I've got an awkward question.", 'line': "Is this going to make me want to toss you in the river? Just kidding. Spit it out. I've heard it all. Whatever it is, it won't shock me.", 'time': 1794782580.0, 'day': 1.6},
    {'said': 'I need help with a problem.', 'line': "Hah! You'd have better luck finding a polite Thalmor. If you're that desperate, the river's cold enough to solve your problem. Damn it. You have done right by us. Fine. I'll...", 'time': 1794782593.0, 'day': 1.6},
    {'said': 'Thank you.', 'line': "You think I want him knowing? Shut your damn mouth.", 'time': 1794782620.0, 'day': 1.6},
    {'said': 'I need help with my problem again.', 'line': "By Ysmir's beard... Do I look like a brothel? You've got the stones to ask twice. The river's still cold, friend.", 'time': 1794782675.0, 'day': 1.6},
    {'said': "Just once more? I swear I'll never ask again! ...Probably.", 'line': 'Ugh. Fine. But this is the last time.', 'time': 1794782686.0, 'day': 1.6},
    {'said': '', 'line': "Don't talk about it here! Come to my home when Hod's not there.", 'time': 1794782712.0, 'day': 1.6}]}}}
MANTELLA = ['Brom: Hello; Gerdur: Lucan over in the Riverwood Trader says thieves broke into his store. Strange, he says they hardly took anything.',
            "Brom: I need help with my problem again.;\n Gerdur: By Ysmir's beard... Do I look like a brothel? You've got the stones to ask twice. "
            "The river's still cold, friend. Brom: Just once more? I swear I'll never ask again! ...Probably.;\n Gerdur: Ugh. Fine. But this is the "
            "last time. Brom: ...;\n Gerdur:  "]  # logging.log 09:45:12, Mantella's own store


def part_menu(tmp):
    # live session 12's first exchange (lost by Mantella's own store) is shown at her next talk and made into her memory
    # by that talk's end-of-talk summary (test_menu_memory.py covers the details: dates, failures, restart, overflow)
    from menu_talk import end_talk

    class Summaries:
        _Summaries__language_name = 'English'
        def summarize_conversation(self, text, prompt):
            return json.dumps({'memory': 'The hooded stranger asked me an awkward question and I gave in.', 'feelings': {}})
    store = memory.MemoryStore(str(tmp / 'mem'), 'w')
    gerdur = SimpleNamespace(name='Gerdur', ref_id='013489', base_id='013489')
    entry = menu_dialogue.prepare(store, gerdur, 'Brom', data=WORLD, sexual=lambda p: False)
    check('the first exchange World heard (and the rest of that day) is in her memory block at the next talk',
          entry is not None and 'awkward question' in menu_dialogue.talk_text('Gerdur', 'Brom'))
    check("...Mantella's own copy of the second exchange gives way to a note (not shown or summarised twice)",
          menu_dialogue.replace_events(MANTELLA, 'Brom')[1].startswith(memory.COMPACTED))
    end_talk(store, [gerdur], Summaries())
    check('...and the end of that talk makes it her memory', any(e.get('text', '').startswith('The hooded stranger asked me')
                                                                 for e in store.load('Gerdur', '013489')['recent']))
    menu_dialogue.talk_over()


# --- 6. an ale picked up dropped her gold count ---------------------------------------------------------------------------
def part_purse():
    lira = {'name': 'lira', 'carry_gold': 100, 'carry_items': 'Glass Dagger'}
    ale = [{'role': 'user', 'content': '(lira sees the player as a trusted ally. )\n(lira picked up/took Ale)\n(lira equipped Glass Dagger)\n'
                                       'Lira, could you lend me 20 gold?'}]  # logging.log 09:52:52
    trade._seen.clear()
    line = trade.carry_text([lira], ale)
    check('the real turn: an ale picked up keeps her 100 gold in the line, with what she picked up added',
          line == '(lira carries 100 gold and Glass Dagger, plus what lira picked up or was handed in this talk.)', line)
    gold = [{'role': 'user', 'content': '(lira picked up/took 100 Gold)\nNyri, could you lend me 30 gold?'}]
    trade._seen.clear()
    check('gold picked up in the talk still drops the stale count', 'carries' not in trade.carry_text([lira], gold), trade.carry_text([lira], gold))
    trade._seen.clear()


with tempfile.TemporaryDirectory() as tmp:
    for part in (part_summary, part_stored, lambda: part_menu(Path(tmp)), part_purse):
        try:
            part()
        except Exception as e:
            import traceback
            traceback.print_exc()
            check(f'{getattr(part, "__name__", "part")} ran without an error', False, e)

print(f"\n{len(FAILS)} failure(s)" if FAILS else '\nall passed')
sys.exit(1 if FAILS else 0)
