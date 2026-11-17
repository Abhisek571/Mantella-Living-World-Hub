"""Offline tests for action argument types (server/living_world/action_args.py) and the script getter check
(tools/check_action_getters.py). A wrong-type SKSE_HTTP getter crashed the game in live test 5 (Trade, count 0).
Run with a Python 3.11: test_action_args.py <repo server dir>"""
import os, sys, types
from pathlib import Path

SERVER = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SERVER.parent / 'tools'))
from living_world import action_args
import check_action_getters as getters

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)) if not cond else ''))
    if not cond:
        FAILS.append(name)

TRADE = {'kind': {'type': 'string', 'enum': ['give_gold']}, 'amount': {'type': 'integer'}, 'item': {'type': 'string'},
         'count': {'type': 'integer'}, 'price': {'type': 'integer'}}
ORDER = {'source': {'type': 'array', 'items': {'type': 'string'}}, 'order': {'type': 'string'}}
N = action_args.normalise

# integers: numbers stay numbers, text numbers become numbers, nothing else gets through as another type
check('the live-test call stays as sent (int zeros are ints)',
      N({'kind': 'give_gold', 'amount': 50, 'count': 0, 'price': 0}, TRADE) == {'kind': 'give_gold', 'amount': 50, 'count': 0, 'price': 0})
check('integer sent as text becomes an int', N({'amount': '50'}, TRADE) == {'amount': 50})
check('integer sent as "1,200" or " 30 gold"', N({'amount': '1,200', 'price': ' 30 gold'}, TRADE) == {'amount': 1200, 'price': 30})
check('integer sent as a float becomes an int', N({'count': 2.0}, TRADE) == {'count': 2} and type(N({'count': 2.0}, TRADE)['count']) is int)
check('integer as words is left out (game default)', N({'amount': 'fifty'}, TRADE) == {})
check('integer as true/false or null is left out', N({'count': True, 'price': None}, TRADE) == {})
check('negative integer kept (the script refuses it)', N({'amount': -5}, TRADE) == {'amount': -5})
check('absurdly large integer held to the int range', N({'amount': 10 ** 30}, TRADE) == {'amount': 2 ** 31 - 1})
check('nan/inf float is left out', N({'amount': float('nan'), 'count': float('inf')}, TRADE) == {})
# strings: never a number, list or object (getString on those crashes)
check('string sent as a number becomes text', N({'item': 5}, TRADE) == {'item': '5'} and N({'kind': 2.5}, TRADE) == {'kind': '2.5'})
check('string sent as a list is joined', N({'item': ['missionary', 'cowgirl']}, TRADE) == {'item': 'missionary, cowgirl'})
check('string sent as an object is left out', N({'item': {'a': 1}}, TRADE) == {})
check('string sent as true becomes "true"', N({'item': True}, TRADE) == {'item': 'true'})
# arrays of strings: always a list of strings (getStringArray on a plain string crashes)
check('array sent as one name becomes a list', N({'source': 'Lydia'}, ORDER) == {'source': ['Lydia']})
check('array items turned to text, nulls dropped', N({'source': ['Lydia', 3, None]}, ORDER) == {'source': ['Lydia', '3']})
check('undeclared or untyped arguments are kept', N({'x': [1, 2]}, {'x': {}}) == {'x': [1, 2]} and N({'y': 1}, {}) == {'y': 1})
check('not a dict: returned as it is', N(['a'], TRADE) == ['a'])
check('booleans', N({'b': 'yes', 'c': 0, 'd': 'maybe'}, {'b': {'type': 'boolean'}, 'c': {'type': 'boolean'}, 'd': {'type': 'boolean'}}) == {'b': True, 'c': False})

# install(): wraps Mantella's own argument check once
check('install without Mantella code: False, no error', action_args.install() is False)
calls = []
class FunctionManager:
    @staticmethod
    def _validate_arguments_against_schema(llm_arguments, defined_params, action_identifier):
        calls.append(action_identifier)
        return {k: v for k, v in llm_arguments.items() if k in defined_params}
pkg = types.ModuleType('src'); sub = types.ModuleType('src.actions'); fm = types.ModuleType('src.actions.function_manager')
fm.FunctionManager = FunctionManager
sys.modules.update({'src': pkg, 'src.actions': sub, 'src.actions.function_manager': fm})
check('install with Mantella code: True', action_args.install() is True)
check('installing twice wraps once', action_args.install() is True and getattr(FunctionManager.__dict__['_validate_arguments_against_schema'].__func__, '_lw_typed', False))
out = FunctionManager._validate_arguments_against_schema({'kind': 'give_gold', 'count': '0', 'bogus': 1}, TRADE, 'mantella_mlww_trade')
check('wrapped check keeps Mantella filtering and types the rest', out == {'kind': 'give_gold', 'count': 0} and calls == ['mantella_mlww_trade'], (out, calls))
for name in ('src.actions.function_manager', 'src.actions', 'src'):
    del sys.modules[name]

# the script check catches the crash pattern and its reverse
OLD_AMOUNT = '''int Function Amount(int aiArguments, string asKey)
	int n = SKSE_HTTP.getInt(aiArguments, asKey, 0)
	If n <= 0
		n = SKSE_HTTP.getString(aiArguments, asKey, "0") as int
	EndIf
	Return n
EndFunction
'''
REVERSE = '''Event OnX(Form akSpeaker, Form akConversation, int aiArguments)
	string s = SKSE_HTTP.getString(aiArguments, "count", "")
	If s == ""
		int n = SKSE_HTTP.getInt(aiArguments, "count", 0)
	EndIf
EndEvent
'''
WRONG_DECLARED = '''Event OnY(Form akSpeaker, Form akConversation, int aiArguments)
	string s = SKSE_HTTP.getString(aiArguments, "count", "")
EndEvent
'''
check('old Trade Amount (getInt then getString on one key) is caught', getters.problems_in(OLD_AMOUNT, {}) != [], getters.problems_in(OLD_AMOUNT, {}))
check('the reverse fallback (getString then getInt) is caught', getters.problems_in(REVERSE, {}) != [])
check('a declared integer read with getString is caught', getters.problems_in(WRONG_DECLARED, {'count': {'integer'}}) != [])
check('one getter of the declared type passes', getters.problems_in(WRONG_DECLARED, {'count': {'string'}}) == [])
check('comments are not code', getters.problems_in('Function F()\n\t; SKSE_HTTP.getInt(aiArguments, "a") SKSE_HTTP.getString(aiArguments, "a")\nEndFunction\n', {}) == [])
coding = SERVER.parent.parent
repos = [p for p in sorted(coding.glob('Mantella-Living-World-*')) if (p / 'Source' / 'Scripts').is_dir()]
for repo in repos:
    found = getters.check_repo(str(repo))
    check(f'action getters in {repo.name}: one getter of the declared type per key', not found, found)

print(f'\n{len(FAILS)} failed' if FAILS else '\nall passed')
sys.exit(1 if FAILS else 0)
