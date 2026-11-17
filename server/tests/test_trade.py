"""Offline tests for the trade line (server/living_world/trade.py) and the trade pieces around it: the merchant gate of
World's one Trade action, the debt wording in the summary prompt, and the line's place among the newest-message lines.
Run with a Python 3.11: test_trade.py <repo server dir>"""
import json
import os
import sys
from pathlib import Path

SERVER = Path(sys.argv[1]).resolve()  # "." too: the World check looks next to the Hub repo
sys.path.insert(0, str(SERVER))
from living_world import action_filter, events, memory, trade

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)) if not cond else ''))
    if not cond:
        FAILS.append(name)


lydia = {'name': 'Lydia', 'carry_gold': 230, 'carry_items': 'Steel Sword, 2 Potion of Healing', 'merchant': 0, 'stock': ''}
belethor = {'name': 'Belethor', 'carry_gold': 85, 'carry_items': '', 'merchant': 1, 'stock': 'Steel Battleaxe 160 gold, Iron Sword 50 gold'}
nothing = {'name': 'Hod'}  # World not installed or the file not written yet
user = lambda text: [{'role': 'system', 'content': 'x'}, {'role': 'assistant', 'content': 'Hello.'}, {'role': 'user', 'content': text}]

# test_trigger_words
for text in ('How much for that sword?', 'I can pay you 50 gold.', 'Want to buy some pelts?', 'Can you lend me some coin?',
             'I owe you, friend.', 'Here, a gift for you.', 'Let us trade.', 'I will sell these.'):
    check(f'trade talk: {text!r}', trade.wants_trade(text))
for text in ('Good morning.', 'Where is the Jarl?', 'Tell me about the war.', 'I am golden-haired.', 'Golden fields.'):
    check(f'no trade talk: {text!r}', not trade.wants_trade(text))

# test_newest_user_message_only
msgs = [{'role': 'user', 'content': 'How much gold do you have?'}, {'role': 'assistant', 'content': 'Enough.'}, {'role': 'user', 'content': 'Nice weather.'}]
check('only the newest player line counts', trade.carry_text([lydia], msgs) == '', trade.carry_text([lydia], msgs))
check('content blocks are read', trade.player_line([{'role': 'user', 'content': [{'type': 'text', 'text': 'I will pay.'}]}]) == 'I will pay.')
check('no user message: nothing', trade.carry_text([lydia], [{'role': 'system', 'content': 'gold'}]) == '')

# test_lines
line = trade.carry_text([lydia], user('Could you spare some gold?'))
check('follower line: gold and items', line == '(Lydia carries 230 gold and Steel Sword, 2 Potion of Healing.)', line)
line = trade.carry_text([belethor], user('What are you selling?'))
check('merchant line: a sample of wares with prices; a ware not named is never refused for that, it is sold with Trade offer_trade',
      line == '(Belethor carries 85 gold; a few of the wares for sale: Steel Battleaxe 160 gold, Iron Sword 50 gold (shop prices; a '
              'sample: any ware asked for, listed or not, Belethor sells with Trade offer_trade; the game refuses a missing one).)', line)
check('no World data: no line', trade.carry_text([nothing], user('Buy something?')) == '')
check('group: one line each, missing skipped', trade.carry_text([lydia, nothing, belethor], user('Pay me.')).count('carries') == 2)
check('not trade talk: nothing', trade.carry_text([lydia, belethor], user('Hello there.')) == '')
check('broken values do not break it', trade.carry_line({'name': 'X', 'carry_gold': 'many', 'carry_items': 5}) == '' and
      trade.carry_line({'name': 'X', 'carry_gold': -3, 'carry_items': None}) == '(X carries 0 gold.)')
check('a merchant flag without stock adds nothing', trade.carry_line({'name': 'X', 'carry_gold': 1, 'merchant': 1, 'stock': ''}) == '(X carries 1 gold.)')
check('line stays short (under 60 tokens for a merchant)', memory.tokens(trade.carry_line(belethor)) < 60, memory.tokens(trade.carry_line(belethor)))

# live test 9: the stock line named only Lucan's dearest wares (soul gems, rings, necklaces) and he denied having the
# Oakflesh tome his chest held. World now writes every ware with its kind; the line names a few of each kind across
# prices, counts the rest by kind, and says it is not a full list (the sale itself checks the real chest).
LUCAN_STOCK = ('Grand Soul Gem 1520 gold, 2 Greater Soul Gem 1064 gold, Necklace of Minor Stamina 760 gold, Necklace of '
               'Minor Blocking 760 gold, Common Soul Gem 456 gold')  # his real npc file, live test 9
LUCAN_WARES = ['soul gem|1|1520|Grand Soul Gem', 'soul gem|2|1064|Greater Soul Gem', 'jewelry|1|760|Necklace of Minor Stamina',
               'jewelry|1|760|Necklace of Minor Blocking', 'soul gem|1|456|Common Soul Gem', 'jewelry|1|821|Nordic Ring',
               'spell tome|1|146|Spell Tome: Oakflesh', 'spell tome|1|152|Spell Tome: Frostbite', 'spell tome|1|152|Spell Tome: Healing',
               'soul gem|3|198|Lesser Soul Gem', 'soul gem|4|33|Petty Soul Gem', 'potion|2|119|Potion of Minor Healing',
               'potion|1|66|Potion of Minor Magicka', 'potion|1|99|Potion of Minor Stamina', 'weapon|1|83|Iron Sword',
               'weapon|1|33|Iron Dagger', 'armor|1|165|Leather Armor', 'armor|1|83|Hide Boots', 'misc|5|7|Lockpick',
               'misc|2|7|Torch', 'food|3|7|Bread', 'ingredient|2|7|Wheat']  # his chest as the test saw it, rebuilt (the file held only the top five)
lucan_old = {'name': 'Lucan Valerius', 'carry_gold': 35, 'carry_items': 'Silver Garnet Ring, Alto Wine, Iron Dagger, Bread',
             'merchant': 1, 'stock': LUCAN_STOCK}
lucan = dict(lucan_old, wares=LUCAN_WARES)
old_line = trade.carry_line(lucan_old)
check('older World (stock only): the line still says it is a sample, so a ware not named is not denied',
      LUCAN_STOCK in old_line and 'a sample: any ware asked for, listed or not' in old_line, old_line)
new_line = trade.carry_line(lucan)
check('wares: a spell tome is named beside the soul gems and jewelry, and the rest are counted by kind',
      'Spell Tome:' in new_line and 'Grand Soul Gem 1520 gold' in new_line and 'Nordic Ring 821 gold' in new_line
      and 'and 17 more: 4 soul gems, 2 pieces of jewelry, 2 spell tomes, 9 other' in new_line, new_line)
check('wares: the dearest of each kind first, then the cheapest (cheap stock is visible, not only soul gems)',
      trade.wares_text(['potion|1|300|Potion of Ultimate Healing', 'potion|1|20|Potion of Minor Healing',
                        'potion|1|90|Potion of Healing', 'spell tome|1|146|Spell Tome: Oakflesh'])
      == 'Potion of Ultimate Healing 300 gold, Potion of Healing 90 gold, Potion of Minor Healing 20 gold, Spell Tome: Oakflesh 146 gold')
check('wares: a small chest is named in full, no "more" part', trade.wares_text(['weapon|1|50|Iron Sword', 'misc|3|7|Torch'])
      == 'Iron Sword 50 gold, 3 Torch 7 gold')
check('wares: broken entries are skipped, an unknown kind counts as other', trade.wares_text(
      ['x', 'potion|0|5|Empty', 'potion|a|5|Bad', 'weird|1|5|Strange Thing', None, 5]) == 'Strange Thing 5 gold')
check('wares: none usable -> the stock string is used', trade.carry_line(dict(lucan_old, wares=['garbage'])) == old_line)
from living_world import preview  # the same counter the Status page uses
base_line = old_line  # the same sample note on both: what the wares list itself costs over the stock list
check(f'token cost stays near the old line (old {preview.tokens(base_line)}, new {preview.tokens(new_line)}, at most 30 more)',
      preview.tokens(new_line) - preview.tokens(base_line) <= 30, (preview.tokens(base_line), preview.tokens(new_line)))

# test_one_trade_action: World's one Trade action (the kind inside) is offered to every adult who may talk; selling from
# wares (offer_trade) is refused by the game for anyone who is no merchant, so it needs no gate
world_actions = SERVER.parent.parent / 'Mantella-Living-World-World' / 'SKSE' / 'Plugins' / 'MantellaSoftware' / 'data' / 'actions'
if world_actions.is_dir():
    gates = action_filter.load_gates(str(world_actions))
    files = {json.load(open(world_actions / f, encoding='utf-8'))['name']: json.load(open(world_actions / f, encoding='utf-8')) for f in os.listdir(world_actions)}
    check('one Trade action, none of the six separate ones', 'Trade' in files and not {'GiveGold', 'AskGold', 'GiveItem', 'AskItem', 'OfferTrade', 'TakeGift'} & set(files), sorted(files))
    check('Trade has no gate', not gates.get('Trade'), gates)
    kinds = files['Trade']['parameters']['kind']['enum']
    check('Trade carries all six kinds', kinds == ['give_gold', 'ask_gold', 'give_item', 'ask_item', 'offer_trade', 'take_gift'], kinds)
    tools = [{'function': {'name': 'Trade'}}]
    names = lambda speakers: [t['function']['name'] for t in action_filter.filter_actions(tools, speakers, gates)]
    check('merchant and non-merchant both get Trade', names([{'merchant': 1}]) == ['Trade'] and names([{'merchant': 0}]) == ['Trade'] and names([{}]) == ['Trade'])
    first = action_filter.shorten([{'function': {'name': 'Trade', 'description': files['Trade']['description']}}], gates)[0]['function']['description']
    check('shortened Trade keeps the stranger rule', 'stranger' in first, first)
    # live test 8: "I'd like to buy X" always picked stock Barter (it only opens the barter menu); the one sentence the
    # model sees tells them apart: a named item for a talked price is offer_trade
    check('shortened Trade tells offer_trade (named item, talked price) from Barter (shop menu)',
          'offer_trade' in first and 'Barter' in first and 'price' in first, first)
    check('Trade stays about the same size (description under 230 characters)', len(files['Trade']['description']) < 230, len(files['Trade']['description']))
    check('the trade kinds are the ones the Hub blocks after a custom event', set(kinds) <= set(events.ITEM_ACTIONS) | set(events.GOLD_ACTIONS)
          and {'give_gold', 'ask_gold'} <= set(events.GOLD_ACTIONS), kinds)
else:
    print('SKIP World is not checked out next to the Hub')

# test_debt_wording
check('summary prompt asks debts as "<who> owes <whom> <amount> gold for <what>"', 'owes <whom> <amount> gold for <what>' in memory.SUMMARY_PROMPT)
check('summary prompt still formats', 'owes' in memory.SUMMARY_PROMPT.format(names='A', game='Skyrim', player='P', language='English', promises='[]', bios=''))

# test_hooked_in: the line is one of the newest-message lines, only with World installed
init = (SERVER / 'living_world' / '__init__.py').read_text(encoding='utf-8')
check('carry line is a newest-message producer gated on World', "trade.carry_text(lw_state.load_conversation(), messages) if 'World' in _installed()" in init)

# live test 5: nyri had 0 gold at talk start, got 200 from the console, and said "my purse reads empty": the number World
# wrote at join is stale once a hand-over involving her shows up in the talk after her file was written
import tempfile, time as _time
from living_world import lw_state
with tempfile.TemporaryDirectory() as tmp:
    lw_state.DATA_DIR = tmp
    os.makedirs(os.path.join(tmp, 'npc'))
    path = os.path.join(tmp, 'npc', '00080E.json')
    open(path, 'w').write('{}')
    os.utime(path, (_time.time() - 300, _time.time() - 300))
    nyri = {'name': 'nyri', 'base_id': '00080E', 'carry_gold': 0, 'carry_items': 'Glass Dagger'}
    talk = [{'role': 'system', 'content': 'x'}, {'role': 'user', 'content': '(CHAD picked up / took Torch)\n(nyri picked up/took Torch from CHAD)\nHere is a torch.'},
            {'role': 'assistant', 'content': 'Thanks.'}, {'role': 'user', 'content': 'Lend me 50 gold?'}]
    trade._seen.clear()
    first = trade.carry_text([nyri], talk)
    # live test 12: only goods moved (a torch), so her gold count stays, with what she picked up added
    check('a hand-over of goods seen first now (file older): the gold stays, the goods are added', '0 gold' in first and 'plus what nyri picked up or was handed in this talk' in first, first)
    trade._seen.clear()
    open(path, 'w').write('{}')  # World rewrote her file after that
    plain = [{'role': 'user', 'content': 'Lend me 50 gold?'}]
    check('no hand-over in the talk: the numbers are shown', trade.carry_text([nyri], plain) == '(nyri carries 0 gold and Glass Dagger.)')
    later = plain + [{'role': 'assistant', 'content': 'My purse is empty.'},
                     {'role': 'user', 'content': '(nyri picked up/took 200 Gold)\nCheck your purse again, Nyri. Lend me 50 gold.'}]
    line = trade.carry_text([nyri], later)
    check('200 gold picked up mid-talk: no stale "0 gold" in her line', '0 gold' not in line and "nyri's purse and pack hold what nyri had plus" in line, line)
    check('the line names no number at all', not any(ch.isdigit() for ch in line), line)
    trade._seen.clear()
    own = plain + [{'role': 'user', 'content': '(CHAD dropped/gave 50 Gold)\n(nyri picked up/took 50 Gold)\n((CHAD handed nyri 50 gold; it was handed over.))\nThere.'}]
    check("World's own trade (it rewrites the numbers) does not make them stale", trade.carry_text([nyri], own + [{'role': 'user', 'content': 'How much gold now?'}]).startswith('(nyri carries'))
    check('another NPC\'s hand-over does not touch her line', trade.handovers('nyri', [{'role': 'user', 'content': '(Lydia picked up/took 9 Gold)\nx'}]) == 0)
    check('a name inside another word does not count', trade.handovers('Ria', [{'role': 'user', 'content': '(Brian picked up/took Gold)'}]) == 0)
lw_state.DATA_DIR = lw_state.default_data_dir()
rules = (SERVER / '..' / 'SKSE' / 'Plugins' / 'MantellaSoftware' / 'data' / 'prompt_rules' / '01_talk.txt').read_text(encoding='utf-8')
check('one shared rule: events, notes in brackets and game data are never mentioned as such',
      'never mention' in rules.lower() and 'events' in rules and 'brackets' in rules and len(rules) <= 600, rules)

print('RESULT: ' + ('ALL PASS' if not FAILS else f'{len(FAILS)} FAILED: {FAILS}'))
sys.exit(1 if FAILS else 0)
