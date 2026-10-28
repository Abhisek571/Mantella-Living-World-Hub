"""Offline tests for prompt rules and the system layout (server/living_world/prompt_rules.py, layout.py).
Run with a Python 3.11: test_prompt_rules.py <repo server dir>"""
import json, logging, sys, tempfile
from pathlib import Path

SERVER = Path(sys.argv[1])
sys.path.insert(0, str(SERVER))
from living_world import prompt_rules, layout, lw_state

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)) if not cond else ''))
    if not cond:
        FAILS.append(name)

records = []
class Collect(logging.Handler):
    def emit(self, record):
        records.append(record)
logging.getLogger('Mantella').addHandler(Collect())

with tempfile.TemporaryDirectory() as tmp:
    d = Path(tmp) / 'prompt_rules'; d.mkdir()
    (d / '20_world.txt').write_text('Fame travels slowly.\n\n', encoding='utf-8')
    (d / '00_hub.txt').write_text('\nWhat you wear is your own choice.\n', encoding='utf-8')
    (d / 'followers.txt').write_text('Clothes {player_name} gave you are from {player_name}.', encoding='utf-8')
    (d / 'notes.md').write_text('not a rule file', encoding='utf-8')
    # test_sorted_and_stable
    text = prompt_rules.load_rules(str(d), 'CHAD')
    check('sorted by file name', text.splitlines() == ['What you wear is your own choice.', 'Fame travels slowly.', 'Clothes CHAD gave you are from CHAD.'], text)
    check('stable across calls', prompt_rules.load_rules(str(d), 'CHAD') == text)
    check('no player name leaves the placeholder out', 'the player' in prompt_rules.load_rules(str(d), ''))
    # test_overlong_file_truncated_with_warning
    (d / '90_long.txt').write_text('x' * 900, encoding='utf-8')
    records.clear()
    long_text = prompt_rules.load_rules(str(d), 'CHAD')
    check('overlong file cut to 600 chars', max(len(l) for l in long_text.splitlines()) == prompt_rules.MAX_CHARS, len(long_text))
    check('overlong file logged', any('90_long.txt' in r.getMessage() for r in records))
    counts = prompt_rules.rule_token_counts(str(d))
    check('token counts per file', set(counts) == {'00_hub.txt', '20_world.txt', '90_long.txt', 'followers.txt'} and all(v > 0 for v in counts.values()), counts)
    # test_missing_dir_is_empty
    check('missing dir is empty', prompt_rules.load_rules(str(Path(tmp) / 'nope'), 'CHAD') == '')

    # test_stable_first_layout: Mantella's sections split; what never changes in a talk comes first, then memory;
    # the scene (time, weather) leaves the system prompt for the newest message
    stock = ('# Overview\nYou are Vega in Skyrim.\n\n# Background\nVega is a Nord.\n\n# History\nBelow is a summary of past events:\n'
             '[Day 2] We fished.\n\n# Current Scene\nYou are now in Riverwood. The time is 12 in the afternoon.\n\n# Rules\n'
             'Stay in character.\n\n# Response Format\nUse 1-2 short sentences.\n\nRespond as Vega now in English.')
    parts = layout.order_system({'mantella': stock, 'common_knowledge': 'Skyrim has nine holds.', 'identity': 'Identity: Vega.'}, 'Rule one.')
    names = [k for k in parts if not k.startswith('__')]
    check('sections split, nothing lost', set(names) >= {'prompt_rules', 'mantella_rules', 'overview', 'background', 'history', 'respond'} and 'mantella' not in names, names)
    check('order: stable parts, then memory, then respond', parts['__order__'].index('mantella_rules') < parts['__order__'].index('common_knowledge')
          < parts['__order__'].index('background') < parts['__order__'].index('knows') < parts['__order__'].index('history') < parts['__order__'].index('respond'), parts['__order__'])
    check('scene left out of the system prompt', 'Riverwood' not in ''.join(v for k, v in parts.items() if not k.startswith('__')), parts)
    check('rules and format kept together', parts['mantella_rules'].startswith('# Rules') and '# Response Format' in parts['mantella_rules'], parts['mantella_rules'])
    check('respond line last', parts['respond'] == 'Respond as Vega now in English.', parts['respond'])
    check('cache points: end of the stable part, end of the prompt', parts['__breakpoints_after__'] == [['overview', 'background', 'identity', 'knows', 'jobs'], 'respond'], parts['__breakpoints_after__'])
    check('scene text for the newest message', layout.scene_text(stock) == 'You are now in Riverwood. The time is 12 in the afternoon.', layout.scene_text(stock))
    check('no sections: Mantella text kept whole', [k for k in layout.order_system({'mantella': 'You are Vega.'}, '') if not k.startswith('__')] == ['mantella'])

    # bio dialogue examples cut to a few lines (they are most of a long stock bio)
    bio = ('# Background\nCamilla: a merchant in Riverwood.\n\nExample conversations/dialogue [use as inspiration but avoid parroting]:\n'
           + '\n'.join(f'"Line {i}."' for i in range(30)) + '\n\n# Current Scene\nRiverwood.')
    cut = layout.trim_examples(bio, 3)
    check('examples cut to 3 lines', cut.count('"Line ') == 3 and '"Line 2."' in cut and '"Line 3."' not in cut, cut)
    check('facts and later sections kept', 'a merchant in Riverwood' in cut and cut.endswith('# Current Scene\nRiverwood.'), cut)
    check('no examples: text unchanged', layout.trim_examples('# Background\nJust facts.', 3) == '# Background\nJust facts.')
    check('keep 0 removes the block', 'Example conversations' not in layout.trim_examples(bio, 0) and '"Line 0."' not in layout.trim_examples(bio, 0))
    alt = '# Background\nAlvor conversation/dialogue examples [use as inspiration but avoid parroting]:\nAlvor: "One."\nSigrid: "Two."\nAlvor: "Three."\nAlvor: "Four."'
    check('other header spelling handled', layout.trim_examples(alt, 2).count('"') == 4, layout.trim_examples(alt, 2))
    for header in ('Example Camilla conversations/dialogue [use as inspiration/reference but avoid parroting]:', 'Speech Pattern Examples:',
                   'Bandit dialogue examples [use these examples as inspiration, but avoid parroting them]:', 'Example Dialogue:'):
        t = f'# Background\nFacts.\n{header}\n"A."\n"B."\n"C."\n"D."\n\n# Rules\nx'
        check(f'header spelling: {header[:24]}', layout.trim_examples(t, 1).count('"') == 2, layout.trim_examples(t, 1))
    check('spoken-dialogue rule line is not an examples header', layout.trim_examples('# Rules\nOutput ONLY spoken dialogue.\n"A."', 0) == '# Rules\nOutput ONLY spoken dialogue.\n"A."')
    check('order_system trims the bio examples', '"Line 5."' not in layout.order_system({'mantella': bio}, '', keep_examples=3)['background'] and '"Line 5."' in layout.order_system({'mantella': bio}, '', keep_examples=None)['background'])

    # player name from the conversation file
    lw_state.DATA_DIR = tmp
    (Path(tmp) / 'conversation.json').write_text(json.dumps({'string': {'player': 'CHAD'}, 'stringList': {'speakers': []}}), encoding='utf-8')
    check('player name from conversation file', lw_state.load_player_name() == 'CHAD')

print('RESULT: ' + ('ALL PASS' if not FAILS else f'{len(FAILS)} FAILED: {FAILS}'))
sys.exit(1 if FAILS else 0)
