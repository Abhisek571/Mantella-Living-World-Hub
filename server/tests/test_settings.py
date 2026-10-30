"""Offline tests for settings, rule switches, prompt preview and the memory editor.
Run with a Python 3.11: test_settings.py <repo server dir>"""
import json, sys, tempfile
from pathlib import Path

SERVER = Path(sys.argv[1])
sys.path.insert(0, str(SERVER))
from living_world import settings, prompt_rules, preview, memory, ui_tab

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)) if not cond else ''))
    if not cond:
        FAILS.append(name)

with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / 'settings.json'
    # defaults when missing or broken
    s = settings.load(str(path))
    check('defaults when missing', s == settings.DEFAULTS, s)
    check('stranger memory budget defaults to 400', s.get('memory_budget_stranger') == 400, s)
    check('all bio examples kept by default', s.get('bio_examples') == -1, s)
    check('short action descriptions by default', s.get('short_actions') is True, s)
    check('talks saved and trimmed after 8,000 tokens by default', s.get('trim_after_tokens') == 8000, s)
    check('Dragonborn not kept secret by default', s.get('dragonborn_secret') is False, s)
    check('Knowledge in full by default', s.get('knowledge_mode') == 'full', s)
    path.write_text('{"memory_budget": ', encoding='utf-8')
    check('defaults when broken', settings.load(str(path)) == settings.DEFAULTS)
    # test_settings_saved_and_reloaded
    settings.save(str(path), dict(settings.DEFAULTS, memory_budget=900, disabled_rules=['20_world.txt']))
    s = settings.load(str(path))
    check('settings saved and reloaded', s['memory_budget'] == 900 and s['disabled_rules'] == ['20_world.txt'], s)
    path.write_text(json.dumps({'memory_budget': 'lots', 'unknown': 1, 'lore_budget': 200}), encoding='utf-8')
    s = settings.load(str(path))
    check('bad values fall back, unknown keys dropped', s['memory_budget'] == settings.DEFAULTS['memory_budget'] and s['lore_budget'] == 200 and 'unknown' not in s, s)

    # rule switches: a disabled file and the story-control line
    rules = Path(tmp) / 'prompt_rules'; rules.mkdir()
    (rules / '00_hub.txt').write_text('Custom events are facts.', encoding='utf-8')
    (rules / '20_world.txt').write_text('Fame travels slowly.', encoding='utf-8')
    text = prompt_rules.load_rules(str(rules), 'Player', disabled=['20_world.txt'])
    check('switching a rule file off removes it', text == 'Custom events are facts.', text)
    check('story control off drops the hub line', prompt_rules.load_rules(str(rules), 'Player', disabled=settings.disabled_rules(dict(settings.DEFAULTS, story_control=False))) == 'Fame travels slowly.')

    # test_preview_parts_sum_to_total
    preview.record_system({'prompt_rules': 'Speak plainly. ' * 10, 'mantella': 'You are Mjoll. ' * 40, '__breakpoint_after__': 'mantella'}, ['Mjoll'])
    preview.record_tools(12, ['Mjoll'])
    p = preview.latest()
    check('preview names the speakers', p['speakers'] == ['Mjoll'], p)
    check('preview parts sum to total', sum(t for _, t in p['parts']) == p['total'] and p['total'] > 0, p)
    check('preview has the tool count', p['tools'] == 12, p)
    check('preview text lists each part', 'prompt_rules' in ui_tab.preview_text(p) and 'mantella' in ui_tab.preview_text(p))

    # test_memory_edit_round_trip
    store = memory.MemoryStore(str(Path(tmp) / 'conversations'), 'Player1')
    store.save('Mjoll', 'FE1DD821', {'recent': [{'day': 3, 'hour': 13, 'text': 'We fished.', 'witnesses': ['Mjoll']}], 'long_term': {}, 'feeling': 'fond'})
    from living_world import memory_ui
    current = store.load('Mjoll', 'FE1DD821')
    f, r, l = memory_ui.to_tables(current)
    check('memory tables shown', f == 'fond' and r[0][2] == 'We fished.', (f, r))
    r[0][2] = 'We fished at dawn.'
    store.save('Mjoll', 'FE1DD821', memory.clean(memory_ui.from_tables(current, 'trusts Player', r, [['earlier', 'Met at Riverwood.']])))
    again = store.load('Mjoll', 'FE1DD821')
    check('memory edit round trip', again['feeling'] == 'trusts Player' and again['recent'][0]['text'] == 'We fished at dawn.' and again['long_term'] == {'earlier': 'Met at Riverwood.'}, again)

print('RESULT: ' + ('ALL PASS' if not FAILS else f'{len(FAILS)} FAILED: {FAILS}'))
sys.exit(1 if FAILS else 0)
