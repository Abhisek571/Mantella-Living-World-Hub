"""What the NPCs here carry, for trading by talk (World's GiveGold, GiveItem, OfferTrade and the rest). World writes it
into each NPC's file when they join a talk and after every trade: carry_gold, carry_items (the most valuable things they
could hand over), and for a merchant merchant=1, stock (the five most valuable wares with the barter menu's price) and
wares (every ware in the chest as "kind|count|price|name", newer World). One short line per NPC
goes with the newest message, and only when the player's latest line is about buying, selling, gold or giving: other
turns pay no tokens for it.

World writes the numbers only when the NPC joins and after its own trades, so gold the NPC picked up or was given in
some other way mid-talk (seen live: 200 gold from the console, then "my purse reads empty") would leave a stale number.
Once a hand-over involving the NPC shows up in the talk after their file was written, their line drops the numbers and
lets the newest event decide; the game refuses a hand-over they cannot afford with a told-back line."""
import os
import re
import time

TRADE_WORDS = re.compile(
    r"\b(buy|buying|bought|sell|selling|sold|sale|wares|gold|coins?|septims?|money|pay|paid|paying|payment|price|prices|"
    r"cost|costs|cheap|expensive|discount|haggle|bargain|barter|trade|trading|deal|purchase|give|giving|gave|gift|lend|"
    r"loan|borrow|owe|owes|owed|debt|hire|hired|fee|reward|how much|spare)\b", re.I)


def player_line(messages) -> str:
    """The text of the newest user message (the player's line, with any event lines Mantella put before it)."""
    for message in reversed(messages or []):
        if not isinstance(message, dict) or message.get('role') != 'user':
            continue
        content = message.get('content')
        if isinstance(content, str):
            return content
        if isinstance(content, list):  # content blocks
            return ' '.join(b.get('text', '') for b in content if isinstance(b, dict) and isinstance(b.get('text'), str))
        return ''
    return ''


def wants_trade(text: str) -> bool:
    return bool(text) and TRADE_WORDS.search(text) is not None


def _int(value) -> int | None:
    try:
        return int(value) if not isinstance(value, bool) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ''


HANDOVER = re.compile(r"\b(picked up|took|dropped|gave|given|handed|received|bought|sold|stole|paid)\b", re.I)
CLOCK_SLACK = 1.0  # seconds: file times and time.time() can differ a little; when unsure the numbers go
WORLD_TRADE = 'it was handed over'  # the end of World's own trade result line (MLWW_Trade Done)
_seen: dict = {}  # npc name (lower case) -> [hand-over event lines seen in the talk, time.time() when that grew]


def _event_lines(messages) -> list[str]:
    """The in-game event lines of the talk's user messages (each in parentheses on its own line). A message that carries
    World's own trade result ("...; it was handed over") is left out: World rewrote the numbers for that trade."""
    out = []
    for message in messages or []:
        if not isinstance(message, dict) or message.get('role') != 'user':
            continue
        content = message.get('content')
        if isinstance(content, list):
            content = '\n'.join(b.get('text', '') for b in content if isinstance(b, dict) and isinstance(b.get('text'), str))
        if isinstance(content, str):
            lines = [l.strip() for l in content.splitlines() if l.strip().startswith('(')]
            if not any(WORLD_TRADE in l for l in lines):
                out += lines
    return out


def handovers(name: str, messages) -> int:
    """How many event lines of the talk hand something to or from this NPC (or have them pick it up)."""
    if not name:
        return 0
    who = re.compile(rf"(?<![\w']){re.escape(name)}(?![\w'])", re.I)
    return sum(1 for line in _event_lines(messages) if who.search(line) and HANDOVER.search(line))


def changed_since(name: str, messages, written, now=None) -> bool:
    """True when a hand-over involving this NPC was first seen after their file was written (written: its mtime)."""
    key = name.lower()
    count = handovers(name, messages)
    seen = _seen.get(key)
    if seen is None or count < seen[0]:  # a new talk
        seen = _seen[key] = [count, 0.0 if count == 0 else time.time() if now is None else now]
    if count > seen[0]:
        seen[0], seen[1] = count, time.time() if now is None else now
    return bool(count) and seen[1] > 0 and (written is None or seen[1] >= written - CLOCK_SLACK)


def gold_moved(name: str, messages) -> bool:
    """True when an event line of the talk hands gold to or from this NPC (or has them pick it up)."""
    who = re.compile(rf"(?<![\w']){re.escape(name)}(?![\w'])", re.I)
    return any(who.search(l) and HANDOVER.search(l) and re.search(r"\b(?:gold|septims?|coins?)\b", l, re.I)
               for l in _event_lines(messages))


def _written(npc: dict):
    from . import lw_state
    base = _text(npc.get('base_id'))
    return lw_state._file_time(os.path.join('npc', base.upper() + '.json')) if base else None


def carry_line(npc: dict, messages=None) -> str:
    """'(Lydia carries 230 gold and Steel Sword, 2 Potion of Healing.)'; '' when World wrote nothing for them. When a
    hand-over involving them came after World wrote the numbers, a line without numbers instead."""
    name = _text(npc.get('name'))
    gold = _int(npc.get('carry_gold'))
    if not name or gold is None:
        return ''
    changed = messages is not None and changed_since(name, messages, _written(npc))
    if changed and gold_moved(name, messages):
        # live test 11: "what the newest events say nyri picked up ... is nyri's now" came back spoken as reasoning about
        # her ("She just picked up 100 gold, so she can cover thirty"): a plain fact, no events to reason from
        return f"({name}'s purse and pack hold what {name} had plus what {name} picked up or was handed in this talk.)"
    items = _text(npc.get('carry_items'))
    have = f"{max(gold, 0)} gold" + (f" and {items}" if items else '')
    # live test 12: an ale picked up dropped her gold count too, and Nyri with 100 gold said she might not have twenty;
    # a hand-over of goods only keeps the gold, with the goods added
    line = f"({name} carries {have}" + (f", plus what {name} picked up or was handed in this talk" if changed else '')
    stock = wares_text(npc.get('wares')) or _text(npc.get('stock'))
    if _int(npc.get('merchant')) == 1 and stock:
        # live test 8: "I'd like to buy the Candlelight spell tome" always went to stock Barter (the barter menu); a
        # named ware for a price talked out is World's Trade offer_trade, so verbal haggling works. Live test 9: the
        # list named only the dearest wares and Lucan denied having the Oakflesh tome his chest held, so it says it
        # is not complete (the sale itself checks the real chest and says when a ware is truly not there)
        line += f"; a few of the wares for sale: {stock} (shop prices; {NOT_ALL.format(name=name)})"
        if stock_changed(name, messages):
            line += f"; {STOCK_CHANGED.format(name=name)}"
    return line + '.)'


# Live test 10: the barter menu restocks the merchant's chest when it opens (Goat Hide gone, 57 -> 59 wares), but World
# writes the wares when the NPC joins and after a trade, so Lucan's list still named a Goat Hide he no longer had. After
# his barter menu opened or a sale with him in this talk, his line says the stock changed and to check before promising.
STOCK_CHANGED = ("{name}'s stock has changed during this talk (the barter menu restocks it), so the sample may be out of "
                 "date: {name} still tries a sale asked for with Trade offer_trade and lets the result decide")
_STOCK_EVENT = ("{name}'s barter menu opened", " traded with {name} in the barter menu", " from {name} for ")


def stock_changed(name: str, messages) -> bool:
    """True when the talk's event lines show this merchant's barter menu opened (Mantella's Barter action) or a sale with
    them (World's own sale result or a barter menu trade)."""
    if not name or not messages:
        return False
    marks = [m.format(name=name).lower() for m in _STOCK_EVENT]
    for message in messages:
        if not isinstance(message, dict) or message.get('role') != 'user':
            continue
        content = message.get('content')
        if isinstance(content, list):
            content = '\n'.join(b.get('text', '') for b in content if isinstance(b, dict) and isinstance(b.get('text'), str))
        if not isinstance(content, str):
            continue
        for line in content.splitlines():
            text = line.strip().lower()
            if text.startswith('(') and any(mark in text for mark in marks):
                return True
    return False



# live test 11: "not a full list, offer to check" still made Lucan refuse an Iron Helmet and an Iron Sword his chest held
# ("isn't among the wares I can name"); the game checks the real chest when offer_trade runs and says when a ware is not
# there, so the line says the list is a sample and to let the sale decide
NOT_ALL = "a sample: any ware asked for, listed or not, {name} sells with Trade offer_trade; the game refuses a missing one"
MAX_NAMED = 5   # wares named in the line, a few of each kind across price ranges; the rest are counted by kind
MAX_KINDS = 3   # kinds counted by name in "and 14 more: ..."; the rest are "N other"
MAX_WARES = 200
# kind (as World writes it) -> (one, many)
KINDS = {'spell tome': ('spell tome', 'spell tomes'), 'book': ('book', 'books'), 'potion': ('potion', 'potions'),
         'poison': ('poison', 'poisons'), 'food': ('food', 'foods'), 'weapon': ('weapon', 'weapons'),
         'ammo': ('kind of arrows', 'kinds of arrows'), 'armor': ('piece of armor', 'pieces of armor'),
         'clothing': ('piece of clothing', 'pieces of clothing'), 'jewelry': ('piece of jewelry', 'pieces of jewelry'),
         'soul gem': ('soul gem', 'soul gems'), 'ingredient': ('ingredient', 'ingredients'), 'scroll': ('scroll', 'scrolls'),
         'key': ('key', 'keys'), 'misc': ('other ware', 'other wares')}


def _ware(raw):
    """("kind", count, price, "name") from World's "kind|count|price|name", None when it is not one."""
    if not isinstance(raw, str):
        return None
    parts = raw.split('|', 3)
    if len(parts) != 4:
        return None
    kind, name = parts[0].strip().lower(), parts[3].strip()
    count, price = _int(parts[1].strip()), _int(parts[2].strip())
    if not name or count is None or price is None or count < 1:
        return None
    return (kind if kind in KINDS else 'misc', count, max(price, 0), name)


def wares_text(raw) -> str:
    """A short, representative wares list: up to MAX_NAMED wares, taken a kind at a time (the dearest of each kind,
    then the cheapest, then one between), so cheap stock is named as well as soul gems and rings; then how many more
    by kind ("and 14 more: 6 spell tomes, 5 potions, 3 weapons"). '' without a usable list (older World: stock is used)."""
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return ''
    wares = [w for w in (_ware(r) for r in raw[:MAX_WARES]) if w]
    if not wares:
        return ''
    kinds: dict = {}
    for w in sorted(wares, key=lambda w: (-w[2], w[3].lower())):
        kinds.setdefault(w[0], []).append(w)
    order = sorted(kinds, key=lambda k: (-len(kinds[k]), -kinds[k][0][2]))
    named, rounds = [], ((lambda l: 0), (lambda l: len(l) - 1), (lambda l: len(l) // 2))
    for pick in rounds:
        for k in order:
            if len(named) < MAX_NAMED and kinds[k] and kinds[k][pick(kinds[k])] not in named:
                named.append(kinds[k][pick(kinds[k])])
    named.sort(key=lambda w: (order.index(w[0]), -w[2], w[3].lower()))
    text = ', '.join((f"{c} {n}" if c > 1 else n) + f" {p} gold" for _, c, p, n in named)
    rest = {k: sum(1 for w in kinds[k] if w not in named) for k in order}
    more = sum(rest.values())
    if more:
        counted = [(k, n) for k, n in sorted(rest.items(), key=lambda kv: -kv[1]) if n]
        by_kind = [f"{n} {KINDS[k][0] if n == 1 else KINDS[k][1]}" for k, n in counted[:MAX_KINDS]]
        other = sum(n for _, n in counted[MAX_KINDS:])
        text += f", and {more} more: {', '.join(by_kind + ([f'{other} other'] if other else []))}"
    return text


def carry_text(speakers: list[dict], messages) -> str:
    """One line per NPC here when the player's latest line is about trade, else ''."""
    if not wants_trade(player_line(messages)):
        return ''
    lines = [carry_line(s, messages) for s in speakers or [] if isinstance(s, dict)]
    return ' '.join(line for line in lines if line)
