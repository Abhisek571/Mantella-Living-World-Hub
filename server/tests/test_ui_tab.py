"""Offline tests for the Living World tab (server/living_world/ui_tab.py), with a stand-in for Gradio.
Run with a Python 3.11: test_ui_tab.py <repo server dir>"""
import importlib.util, sys, tempfile
from pathlib import Path

SERVER = Path(sys.argv[1])
sys.path.insert(0, str(SERVER))
from living_world import ui_tab

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)) if not cond else ''))
    if not cond:
        FAILS.append(name)


class FakeComponent:
    def __init__(self, kind, *args, **kwargs):
        self.kind, self.args, self.kwargs = kind, args, kwargs
    def __enter__(self):
        return self
    def __exit__(self, *exc):
        return False
    def click(self, fn, inputs=None, outputs=None):
        self.kwargs['on_click'] = fn
    def change(self, fn, inputs=None, outputs=None):
        self.kwargs['on_change'] = fn
    def submit(self, fn, inputs=None, outputs=None):
        self.kwargs['on_submit'] = fn


class FakeGradio:
    def __init__(self):
        self.made = []
    def __getattr__(self, kind):
        def make(*args, **kwargs):
            component = FakeComponent(kind, *args, **kwargs)
            self.made.append(component)
            return component
        return make


class FakeApi:
    def __init__(self, log):
        self._log = log
    def usage_log(self):
        return list(self._log)


# test_tab_builds_without_game: empty usage log, no game files
with tempfile.TemporaryDirectory() as tmp:
    gr = FakeGradio()
    ui_tab.build(gr, FakeApi([]), actions_dir=str(Path(tmp) / 'data' / 'actions'), extensions_dir=str(Path(tmp) / 'extensions'))
    kinds = [c.kind for c in gr.made]
    text = ' '.join(str(c.args[0]) for c in gr.made if c.kind == 'Markdown' and c.args)
    check('tab builds without game', 'Markdown' in kinds and 'Dataframe' in kinds and 'Button' in kinds, kinds)
    check('start here section', 'Start here' in text and 'Integration Hub' in text, text[:200])
    check('tokens section', 'Tokens and cache' in text)
    check('later sections built', all(s in text for s in ('Prompt preview', 'Memory', 'Characters', 'Prompt rules and settings')), text[-300:])

# installed modules come from the action files each module ships
with tempfile.TemporaryDirectory() as tmp:
    actions = Path(tmp) / 'data' / 'actions'; actions.mkdir(parents=True)
    for f in ('mantella_mae_rate_positions.json', 'mantella_osla_rate.json', 'mantella_mlw_wear.json', 'mantella_npc_follow.json'):
        (actions / f).write_text('{}', encoding='utf-8')
    found = ui_tab.installed_modules(str(actions), str(Path(tmp) / 'extensions'))
    check('detects modules by action prefix', found == ['Integration Hub', 'Followers', 'OStim Expansion', 'Arousal'], found)
    check('mlw prefix does not count World', 'World' not in found)
    # Missives ships no action file, only its prompt rule
    rules = Path(tmp) / 'data' / 'prompt_rules'; rules.mkdir()
    (rules / '40_missives.txt').write_text('x', encoding='utf-8')
    check('Missives found by its prompt rule', 'Missives' in ui_tab.installed_modules(str(actions), str(Path(tmp) / 'extensions')))
check('Knowledge set in this tab, not the MCM', 'MCM' not in dict((m[0], m[3]) for m in ui_tab.MODULES)['Knowledge'])

# test_cost_sums: the tab adds up the cost the AI connector put on each reply
rows = [
    {'time': 1000.0, 'model': 'm', 'cache_read': 0, 'cache_write': 4629, 'uncached': 718, 'output': 35, 'cost': 0.013445},
    {'time': 1030.0, 'model': 'm', 'cache_read': 4629, 'cache_write': 151, 'uncached': 790, 'output': 41, 'cost': 0.0028404},
    {'time': 1060.0, 'model': 'm', 'cache_read': 4780, 'cache_write': 84, 'uncached': 790, 'output': 43, 'cost': 0.002698},
]
table = ui_tab.usage_table(rows)
check('one table row per reply', len(table) == 3, table)
check('cost column from the entry', [row[-1] for row in table] == [0.013445, 0.0028404, 0.002698], table)
totals = ui_tab.usage_totals(rows)
check('session total', abs(totals['cost'] - (0.013445 + 0.0028404 + 0.002698)) < 1e-12, totals)
check('tokens totalled', totals['cache_read'] == 9409 and totals['output'] == 119, totals)
check('unpriced reply shows no cost and adds nothing', ui_tab.usage_table([{'time': 1.0, 'uncached': 5}])[0][-1] is None
      and ui_tab.usage_totals([{'time': 1.0, 'uncached': 5}])['cost'] == 0)
check('per hour only after 15 minutes', totals['per_hour'] is None and ui_tab.usage_totals([dict(rows[0], time=0.0), dict(rows[1], time=1800.0)])['per_hour'] is not None)

# test_memory_editor_keeps_other_fields: saving from the tab keeps asked-before data and cleans bad entries
import json
from living_world import memory as M
with tempfile.TemporaryDirectory() as tmp:
    store = M.MemoryStore(tmp, 'W')
    store.save('Lydia', 'A2C94', dict(M.empty(), asked={'whiterun': 2}, feeling='loyal'))
    out = ui_tab.save_memory_fields(store, 'Lydia - A2C94', 'devoted', json.dumps([{'day': '4', 'hour': 9, 'text': 'We fought.'}]), '{}')
    kept = store.load('Lydia', 'A2C94')
    check('asked-before kept', kept['asked'] == {'whiterun': 2}, kept)
    check('edited fields saved and cleaned', kept['feeling'] == 'devoted' and kept['recent'] == [{'day': 4, 'hour': 9, 'text': 'We fought.'}], kept)
check('negative budgets fall back to defaults', ui_tab.positive(-5, 1500) == 1500 and ui_tab.positive('x', 150) == 150 and ui_tab.positive(400, 150) == 400)

print('RESULT: ' + ('ALL PASS' if not FAILS else f'{len(FAILS)} FAILED: {FAILS}'))
sys.exit(1 if FAILS else 0)
