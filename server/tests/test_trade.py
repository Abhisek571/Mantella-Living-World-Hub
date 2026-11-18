"""Offline tests for the trade line (server/living_world/trade.py) and the trade pieces around it: the merchant gate of
World's one Trade action, the debt wording in the summary prompt, and the line's place among the newest-message lines.
Run with a Python 3.11: test_trade.py <repo server dir>"""
import json
import os
import re
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
              'sample: Belethor sells any shop ware asked for, listed or not, with Trade offer_trade (no price agreed: shop '
              'price); the game refuses a missing one).)', line)
check('no World data: no line', trade.carry_text([nothing], user('Buy something?')) == '')
check('group: one line each, missing skipped', trade.carry_text([lydia, nothing, belethor], user('Pay me.')).count('carries') == 2)
check('not trade talk: nothing', trade.carry_text([lydia, belethor], user('Hello there.')) == '')
check('broken values do not break it', trade.carry_line({'name': 'X', 'carry_gold': 'many', 'carry_items': 5}) == '' and
      trade.carry_line({'name': 'X', 'carry_gold': -3, 'carry_items': None}) == '(X carries 0 gold.)')
check('a merchant flag without stock adds nothing', trade.carry_line({'name': 'X', 'carry_gold': 1, 'merchant': 1, 'stock': ''}) == '(X carries 1 gold.)')
# live test 14: the sale note grew by about 9 tokens (the shop's wares, no agreed price needed); trade turns only
check('line stays short (under 70 tokens for a merchant)', memory.tokens(trade.carry_line(belethor)) < 70, memory.tokens(trade.carry_line(belethor)))

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
lucan = dict(lucan_old, wares=LUCAN_WARES, wares_complete=1)
old_line = trade.carry_line(lucan_old)
check('older World (stock only): the line still says it is a sample, so a ware not named is not denied',
      LUCAN_STOCK in old_line and 'sells any shop ware asked for, listed or not' in old_line, old_line)
new_line = trade.carry_line(lucan)
# live test 15: a chest that fits is named in full (every ware, its price), and the line says it is the whole stock
check('wares: a chest that fits is named in full, with no "more" part, and called the whole shop stock',
      all(w.split('|')[3] in new_line for w in LUCAN_WARES) and ' more:' not in new_line
      and "Lucan Valerius's whole shop stock" in new_line and 'a ware not listed is not in the shop' in new_line
      and 'listed or not' not in new_line, new_line)
# B04: World stops reading a chest after MAX_SCAN entries; a list it did not read to the end (wares_complete 0) or an
# older World that writes no flag never claims to be the whole stock, so a ware past the limit is not denied
for flag, label in ((0, 'chest not read to its end'), (None, 'older World without the flag')):
    cut = trade.carry_line(dict(lucan, wares_complete=flag) if flag is not None else {k: v for k, v in lucan.items() if k != 'wares_complete'})
    check(f'wares: {label}: every ware still named, but a sample, listed or not',
          all(w.split('|')[3] in cut for w in LUCAN_WARES) and 'listed or not' in cut and 'whole shop stock' not in cut, cut[-300:])
big =[f'misc|1|{i + 1}|Thing {i:03d}' for i in range(trade.MAX_NAMED)] + ['potion|1|50|Potion of Minor Healing', 'potion|1|9|Weak Potion']
big_line = trade.carry_line({'name': 'Belethor', 'carry_gold': 5, 'merchant': 1, 'wares': big})
check('wares: a chest bigger than the line names every kind, counts the rest, and stays "a sample, listed or not"',
      'Potion of Minor Healing 50 gold' in big_line and 'Weak Potion 9 gold' in big_line and 'and 2 more: 2 other wares' in big_line
      and 'listed or not' in big_line and 'whole shop stock' not in big_line, big_line[-400:])
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
# live test 15: quality over tokens (owner, 2026-11-17): the whole stock costs about 8 tokens a ware, on trade turns only
check(f'token cost of the whole 22-ware stock stays bounded (old {preview.tokens(base_line)}, new {preview.tokens(new_line)}, at most 260)',
      preview.tokens(new_line) <= 260, (preview.tokens(base_line), preview.tokens(new_line)))

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
    check('Trade stays about the same size (description under 260 characters; live test 15 added the shop-price sale)', len(files['Trade']['description']) < 260, len(files['Trade']['description']))
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

# live test 5: jenassa had 0 gold at talk start, got 200 from the console, and said "my purse reads empty": the number World
# wrote at join is stale once a hand-over involving her shows up in the talk after her file was written
import tempfile, time as _time
from living_world import lw_state
with tempfile.TemporaryDirectory() as tmp:
    lw_state.DATA_DIR = tmp
    os.makedirs(os.path.join(tmp, 'npc'))
    path = os.path.join(tmp, 'npc', '00080E.json')
    open(path, 'w').write('{}')
    os.utime(path, (_time.time() - 300, _time.time() - 300))
    jenassa = {'name': 'jenassa', 'base_id': '00080E', 'carry_gold': 0, 'carry_items': 'Glass Dagger'}
    talk = [{'role': 'system', 'content': 'x'}, {'role': 'user', 'content': '(Player picked up / took Torch)\n(jenassa picked up/took Torch from Player)\nHere is a torch.'},
            {'role': 'assistant', 'content': 'Thanks.'}, {'role': 'user', 'content': 'Lend me 50 gold?'}]
    trade._seen.clear()
    first = trade.carry_text([jenassa], talk)
    # live test 12: only goods moved (a torch), so her gold count stays, with what she picked up added
    check('a hand-over of goods seen first now (file older): the gold stays, the goods are added', '0 gold' in first and 'plus what jenassa picked up or was handed in this talk' in first, first)
    trade._seen.clear()
    open(path, 'w').write('{}')  # World rewrote her file after that
    plain = [{'role': 'user', 'content': 'Lend me 50 gold?'}]
    check('no hand-over in the talk: the numbers are shown', trade.carry_text([jenassa], plain) == '(jenassa carries 0 gold and Glass Dagger.)')
    later = plain + [{'role': 'assistant', 'content': 'My purse is empty.'},
                     {'role': 'user', 'content': '(jenassa picked up/took 200 Gold)\nCheck your purse again, Jenassa. Lend me 50 gold.'}]
    line = trade.carry_text([jenassa], later)
    check('200 gold picked up mid-talk: no stale "0 gold" in her line', '0 gold' not in line and "jenassa's purse and pack hold what jenassa had plus" in line, line)
    check('the line names no number at all', not any(ch.isdigit() for ch in line), line)
    trade._seen.clear()
    own = plain + [{'role': 'user', 'content': '(Player dropped/gave 50 Gold)\n(jenassa picked up/took 50 Gold)\n((Player handed jenassa 50 gold; it was handed over.))\nThere.'}]
    check("World's own trade (it rewrites the numbers) does not make them stale", trade.carry_text([jenassa], own + [{'role': 'user', 'content': 'How much gold now?'}]).startswith('(jenassa carries'))
    check('another NPC\'s hand-over does not touch her line', trade.handovers('jenassa', [{'role': 'user', 'content': '(Lydia picked up/took 9 Gold)\nx'}]) == 0)
    check('a name inside another word does not count', trade.handovers('Ria', [{'role': 'user', 'content': '(Brian picked up/took Gold)'}]) == 0)
lw_state.DATA_DIR = lw_state.default_data_dir()
rules = (SERVER / '..' / 'SKSE' / 'Plugins' / 'MantellaSoftware' / 'data' / 'prompt_rules' / '01_talk.txt').read_text(encoding='utf-8')
check('one shared rule: events, notes in brackets and game data are never mentioned as such',
      'never mention' in rules.lower() and 'events' in rules and 'brackets' in rules and len(rules) <= 600, rules)

# live test 14: Lucan (merchant, in his shop, the wares read) said "I've got an iron dagger" (his own pack) and twice
# refused a Potion of Minor Healing his chest held ("not among what I'm carrying"), never calling offer_trade. The texts
# the model saw: World's rule "you give only what you carry", Trade's "offer_trade: a merchant sells a named item at
# the agreed price" (no "from their wares"; no price known for a ware not named) and the line's pack before its wares.
# The sale rule must survive the shortening, tell the shop's wares from the pack, and need no agreed price.
LUCAN_14 = {'name': 'Lucan Valerius', 'carry_gold': 34, 'carry_items': 'Silver Garnet Ring, Iron Dagger, Green Apple, Lockpick',
            'merchant': 1, 'wares_complete': 1, 'stock': 'Gold and Diamond Circlet 1824 gold, Grand Soul Gem 1520 gold',
            'wares': ['spell tome|1|152|Spell Tome (Novice): Flames', 'Armor|2|380|Iron Armor', 'clothing|1|16|Blue Mage Robes',
                      'Misc|1|304|Garnet', 'JEWELRY|1|1824|Gold and Diamond Circlet', 'soul gem|1|1520|Grand Soul Gem',
                      'Potion|1|52|Potion of Minor Healing', 'Potion|4|61|Potion of Minor Magicka']}  # from his live npc file
buy = user("No need to open the shop. I'll buy one Potion of Minor Healing from you, here is the gold.")
line14 = trade.carry_text([LUCAN_14], buy)
# live test 15: his 8 wares now fit the line in full, so the potion is named and the line is his whole stock
check('live test 14: the potion is sold from the shop with offer_trade (named in the whole stock)',
      'Potion of Minor Healing 52 gold' in line14 and 'sells any of it asked for with Trade offer_trade' in line14, line14)
check('live test 14: no agreed price is no reason to refuse (the shop price is used)', 'no price agreed: shop price' in line14, line14)
check('live test 14: the whole stock listed: a ware not in it is not in the shop', 'a ware not listed is not in the shop' in line14, line14)
check('live test 14: merchant line stays bounded (under 220 tokens with 8 wares)', memory.tokens(line14) < 220, memory.tokens(line14))
if world_actions.is_dir():
    trade_json = files['Trade']
    shortened = action_filter.shorten([{'function': {'name': 'Trade', 'description': trade_json['description'],
                                                     'parameters': {'properties': trade_json['parameters']}}}], gates)[0]['function']
    kind_text = shortened['parameters']['properties']['kind']['description']
    price_text = shortened['parameters']['properties']['price']['description']
    # live test 15: "listed or not" went with the 5-ware sample; the wares line now says itself whether it is the whole stock
    check('live test 14: shortened Trade still says offer_trade sells a ware asked for from the shop',
          'offer_trade: a merchant sells' in kind_text and 'shop' in kind_text and 'listed or not' not in kind_text, kind_text)
    check('live test 14: offer_trade needs no agreed price (left out: the shop price)', 'leave out for the shop price' in price_text, price_text)
    check('live test 14: price stays optional (only kind required)', trade_json['required'] == ['kind'], trade_json['required'])
    world_rules = (world_actions.parent / 'prompt_rules' / '20_world.txt').read_text(encoding='utf-8')
    rule = next((l for l in world_rules.splitlines() if 'what you carry' in l), '')
    check('live test 14: "you give only what you carry" no longer covers a merchant\'s wares', 'merchant also sells' in rule, rule)

# live test 14 (cut B and the stage table): the talk request reaches Mantella before the game writes the NPC file. A
# merchant greeted before his wares are written must still get World's Trade action (taken into the locked list at the
# greeting: it has no gate) and his wares line on the next trade turn (read from disk on every request, not frozen).
# A debug line says for each request whether both went with it.
import logging as _logging
import living_world as LW
from living_world import characters, npc_block, settings
with tempfile.TemporaryDirectory() as tmp:
    lw_state.DATA_DIR = tmp
    os.makedirs(os.path.join(tmp, 'npc'))
    settings.PATH = os.path.join(tmp, 'settings.json')
    characters.PATH = os.path.join(tmp, 'characters.json')
    saved_installed = LW._installed
    LW._installed = lambda: {'Integration Hub', 'World'}
    LW._last_store['store'] = None
    LW._action_lock.update(key=None, names=None)
    LW._offered['names'] = None
    npc_block.talk_over()
    with open(os.path.join(tmp, 'conversation.json'), 'w', encoding='utf-8') as fh:
        json.dump({'string': {'player': 'Player'}, 'int': {'day': 1}, 'stringList': {'speakers': ['01347A']}}, fh)
    seen_logs = []

    class _Grab(_logging.Handler):
        def emit(self, record):
            seen_logs.append(record.getMessage())
    grab, mlog = _Grab(), _logging.getLogger('Mantella')
    old_level = mlog.level
    mlog.addHandler(grab)
    mlog.setLevel(_logging.DEBUG)
    tool_list = [{'type': 'function', 'function': {'name': 'Trade', 'description': files['Trade']['description'] if world_actions.is_dir() else 'Trade.'}},
                 {'type': 'function', 'function': {'name': 'Barter', 'description': 'Opens the shop menu.'}}]
    greet = [{'role': 'system', 'content': '# Overview\nYou are Lucan Valerius.'}, {'role': 'user', 'content': 'Hello.'}]
    names_now = lambda msgs: [t['function']['name'] for t in LW._filter_tools([dict(t) for t in tool_list], {'messages': msgs})]
    check('greeting before his file is written: Trade offered (no gate; the lock takes it)', 'Trade' in names_now(greet), names_now(greet))
    first_newest = LW._extra_text({'messages': greet})
    check('greeting before his file: no wares line (nothing written yet, not trade talk)', 'wares for sale' not in first_newest, first_newest)
    with open(os.path.join(tmp, 'npc', '01347A.json'), 'w', encoding='utf-8') as fh:  # the game writes him 5 s after the join
        json.dump({'int': {'minor': 0, 'carry_gold': 34, 'merchant': 1, 'wares_complete': 1},
                   'string': {'name': 'Lucan Valerius', 'ref_id': '00013487', 'carry_items': LUCAN_14['carry_items'], 'stock': LUCAN_14['stock']},
                   'stringList': {'wares': LUCAN_14['wares']}}, fh)
    turn = greet + [{'role': 'assistant', 'content': 'Welcome to the Riverwood Trader.'},
                    {'role': 'user', 'content': 'Do you have any iron daggers or a cheap health potion for sale?'}]
    seen_logs.clear()
    check('next request after his file arrived: Trade still offered (the lock kept it)', 'Trade' in names_now(turn), names_now(turn))
    newest = LW._extra_text({'messages': turn})
    check('next request after his file arrived: the wares line goes with it', 'the wares for sale' in newest and 'offer_trade' in newest, newest)
    note = [m for m in seen_logs if m.startswith('Living World: trade check for this request')]
    check('debug log: this request had trade talk, the wares line and the Trade action',
          note == ['Living World: trade check for this request: trade talk yes, wares line yes, Trade action yes'], note)
    seen_logs.clear()
    LW._extra_text({'messages': greet + [{'role': 'assistant', 'content': 'Hm.'}, {'role': 'user', 'content': 'Nice weather.'}]})
    note = [m for m in seen_logs if m.startswith('Living World: trade check')]
    check('debug log: a plain turn says no trade talk and no wares line', note and 'trade talk no, wares line no' in note[0], note)
    check('debug log names no gold, wares or player text', note and not any(ch.isdigit() for ch in note[0]) and 'weather' not in note[0], note)
    mlog.removeHandler(grab)
    mlog.setLevel(old_level)
    LW._installed = saved_installed
    LW._action_lock.update(key=None, names=None)
    LW._offered['names'] = None
lw_state.DATA_DIR = lw_state.default_data_dir()

# live test 15 (2026-11-17): "I'd like to buy a Potion of Minor Healing, please." to Lucan went to stock Barter ("Let me
# see what I have on the shelf"): the request held the wares line and Trade, but the potion (2 at 52 gold in his chest)
# was not among the 5 of 58 wares named, and Trade's description said offer_trade was "a named item at a price agreed in
# talk" ("once agreed"), with no price said. Now every ware fits the line (his whole stock, shop prices), a ware the
# player's line names is told with its count and price, and Trade's first sentence says a ware asked for by name is
# offer_trade, at the shop price unless another was agreed.
# A generic general-goods chest in the shape World writes (kind|count|price|name, kinds in mixed case as the game
# gives them); the potion is not among the first few wares, and one name (Petty Soul Gem) comes at two prices.
LUCAN_15 = {'name': 'Lucan Valerius', 'carry_gold': 40, 'carry_items': 'Silver Garnet Ring, Silver Necklace, Iron Dagger, Ale',
            'merchant': 1, 'wares_complete': 1, 'wares': ['spell tome|1|152|Spell Tome (Novice): Bound Dagger', 'Misc|1|304|Garnet', 'Armor|1|380|Iron Armor',
                                     'WEAPON|1|183|Iron Warhammer', 'clothing|1|46|Novice Robes of Conjuration & Illusion',
                                     'spell tome|1|152|Spell Tome (Novice): Flames', 'Armor|1|83|Hide Boots', 'Misc|3|23|Leather Strips',
                                     'Potion|2|52|Potion of Minor Healing', 'Potion|2|61|Potion of Minor Magicka',
                                     'Potion|1|99|Potion of Minor Stamina', 'soul gem|8|31|Petty Soul Gem', 'soul gem|1|122|Petty Soul Gem',
                                     'soul gem|1|456|Common Soul Gem', 'Misc|12|7|Lockpick', 'Misc|4|7|Torch', 'food|3|7|Bread',
                                     'Ingredient|2|7|Wheat', 'clothing|1|12|Fur Shoes', 'WEAPON|1|76|Iron Sword', 'WEAPON|1|33|Iron Dagger']}
line15 = trade.carry_text([LUCAN_15], user("I'd like to buy a Potion of Minor Healing, please."))
check('live test 15: every ware of his chest is in the line with its shop price (the potion too)',
      all(w.split('|')[3] in line15 for w in LUCAN_15['wares']) and '2 Potion of Minor Healing 52 gold' in line15 and ' more:' not in line15, line15)
check('live test 15: the line is his whole stock: any of it sold with offer_trade at the shop price, a ware not in it is not there',
      "Lucan Valerius's whole shop stock" in line15 and 'sells any of it asked for with Trade offer_trade (no price agreed: shop price)' in line15
      and 'a ware not listed is not in the shop' in line15 and 'shop prices each' in line15, line15)
check('live test 15: the potion asked for is told as in his shop with count and shop price',
      "the ware asked for is in Lucan Valerius's shop: Potion of Minor Healing, 2 at 52 gold each" in line15, line15)
check('live test 15: the asked-for ware comes after the wares list', line15.find('the wares for sale') < line15.find('the ware asked for'), line15)
check('live test 15: no ware named, no asked-for part (Daedric Greatsword is not stocked; "show me" names none)',
      'the ware asked for' not in trade.carry_text([LUCAN_15], user("I'd like to buy a Daedric Greatsword."))
      and 'the ware asked for' not in trade.carry_text([LUCAN_15], user('Show me what you have for sale.')))
check('live test 15: "Daedric Greatsword" is in no ware of the list (so the whole-stock line rules it out)',
      not any('daedric' in w.lower() for w in LUCAN_15['wares']) and 'whole shop stock' in trade.carry_text([LUCAN_15], user("I'd like to buy a Daedric Greatsword.")))
check('live test 15: after the barter menu restocked him, the list is no longer called whole (it may be stale)',
      'whole shop stock' not in trade.carry_text([LUCAN_15], [{'role': 'user', 'content': "(Lucan Valerius's barter menu opened)\nHi."},
                                                            {'role': 'assistant', 'content': 'Hm.'}, {'role': 'user', 'content': 'Buy a Garnet?'}]))
check('live test 15: plural and case: "two potions of minor healing"',
      'Potion of Minor Healing, 2 at 52 gold each' in trade.asked_text(LUCAN_15['wares'], 'Can I buy two potions of minor healing?'))
petty = trade.asked_text(LUCAN_15['wares'], 'Sell me a petty soul gem.')
check('live test 15: a longer name wins over a shorter one inside it, both prices told', petty.startswith('Petty Soul Gem, 8 at 31 gold each and 1 at 122 gold') and 'Common' not in petty, petty)
flames = trade.asked_text(LUCAN_15['wares'], 'I want the Flames tome.')
check('live test 15: a spell tome asked for by its spell and "tome"', flames.startswith('Spell Tome (Novice): Flames, 1 at 152 gold'), flames)
check('live test 15: a word inside another word is no match ("swordsman" is no Iron Sword; "lockpicking" no Lockpick)',
      trade.asked_text(LUCAN_15['wares'], 'Any iron swordsman gear? I like lockpicking.') == '', trade.asked_text(LUCAN_15['wares'], 'Any iron swordsman gear? I like lockpicking.'))
check('live test 15: at most 3 wares are told', trade.asked_text(LUCAN_15['wares'], 'Garnet, lockpick, iron sword and iron armor, please.').count(' at ') == 3)
check('live test 15: older World (stock only, no wares list): nothing asked-for, nothing breaks',
      'the ware asked for' not in trade.carry_line(dict(LUCAN_15, wares=None, stock='Garnet 304 gold'), user('Buy a Garnet?')))
check(f'live test 15: the whole-stock line stays bounded (under 650 tokens; it is {memory.tokens(line15)})', memory.tokens(line15) < 650, memory.tokens(line15))
# live test 16 (2026-11-17): after buying the potion, a fresh talk with Lucan began with World's day recap "(Player bought
# 52 gold worth of goods from Lucan Valerius today.)"; it read as a gold hand-over of this talk, so his line became the
# no-numbers purse line, which returned before the wares: "I'd like to buy an Iron Sword." went out with no wares line
# (debug: "wares line no") and the model opened Barter.
recap16 = [{'role': 'user', 'content': "(The time is 1 in the afternoon.)\n(Player bought 52 gold worth of goods from Lucan Valerius today.)\n"
                                       "(Lucan Valerius's ties: sibling Camilla Valerius.)\nI'd like to buy an Iron Sword."}]
trade._seen.clear()
line16 = trade.carry_text([LUCAN_15], recap16)
check("live test 16: World's day recap of a sale is no hand-over of this talk (numbers kept)",
      trade.handovers('Lucan Valerius', recap16) == 0 and line16.startswith('(Lucan Valerius carries 40 gold'), line16[:160])
check('live test 16: "... paid Player 30 gold for goods today" is no hand-over either',
      trade.handovers('Lucan Valerius', [{'role': 'user', 'content': '(Lucan Valerius paid Player 30 gold for goods today.)\nHi.'}]) == 0)
check('live test 16: after the day recap the wares line still goes with the request', 'the wares for sale' in line16 and 'Iron Sword 76 gold' in line16
      and "the ware asked for is in Lucan Valerius's shop: Iron Sword, 1 at 76 gold" in line16, line16[-300:])
trade._seen.clear()
moved = [{'role': 'user', 'content': '(Player dropped/gave 52 Gold)\n(Lucan Valerius picked up/took 52 Gold)\nHere.'},
         {'role': 'assistant', 'content': 'Thanks.'}, {'role': 'user', 'content': 'Now sell me an Iron Sword.'}]
line16b = trade.carry_line(dict(LUCAN_15, base_id=''), moved)
check('live test 16: gold really handed to a merchant this talk: purse numbers go, his wares stay',
      "Lucan Valerius's purse and pack hold what" in line16b and '40 gold and' not in line16b and 'Iron Sword 76 gold' in line16b
      and 'offer_trade' in line16b and line16b.endswith('.)'), line16b[:200])
trade._seen.clear()
if world_actions.is_dir():
    first15 =re.split(r'(?<=[.!?])\s+', files['Trade']['description'].strip(), maxsplit=1)[0]
    short15 = action_filter.shorten([{'function': {'name': 'Trade', 'description': files['Trade']['description']}}], gates)[0]['function']['description']
    check('live test 15: Trade (as shortened) says a ware asked for by name is offer_trade, shop price when none agreed',
          short15 == first15 and 'asks to buy by name' in short15 and 'shop price' in short15 and 'offer_trade' in short15, short15)
    check('live test 15: Trade no longer asks for a price agreed first', 'once agreed' not in short15 and 'price agreed in talk' not in short15, short15)
    check('live test 15: Trade still tells Barter (the shop menu) apart and keeps the stranger rule',
          'Barter only opens the shop menu' in short15 and 'stranger pays only' in short15, short15)

print('RESULT:' + ('ALL PASS' if not FAILS else f'{len(FAILS)} FAILED: {FAILS}'))
sys.exit(1 if FAILS else 0)
