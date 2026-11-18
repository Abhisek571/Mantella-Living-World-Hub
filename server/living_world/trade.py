"""What the NPCs here carry, for trading by talk (World's GiveGold, GiveItem, OfferTrade and the rest). World writes it
into each NPC's file when they join a talk and after every trade: carry_gold, carry_items (the most valuable things they
could hand over), and for a merchant merchant=1, stock (the five most valuable wares with the barter menu's price) and
wares (every ware in the chest as "kind|count|price|name", newer World; wares_complete=1 when the chest was read to its
end). One short line per NPC
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
# live test 16: World's talk-start recap of the day's trades ("(Player bought 52 gold worth of goods from Lucan Valerius
# today.)", MLWW_Personal) tells an earlier trade, written into the file before this talk: no hand-over of this talk
DAY_RECAP = re.compile(r"\bgold (?:worth of goods from .+|for goods) today\b", re.I)  # "... paid Player 30 gold for goods today"


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
            lines = [l.strip() for l in content.splitlines() if l.strip().startswith('(') and not DAY_RECAP.search(l)]
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
        # live test 11: "what the newest events say Lydia picked up ... is Lydia's now" came back spoken as reasoning about
        # her ("She just picked up 100 gold, so she can cover thirty"): a plain fact, no events to reason from
        # live test 16: this line returned at once and a merchant lost his wares with it (Lucan, after a sale earlier
        # that day, was asked for an Iron Sword with no wares line and opened Barter); the shop's wares go on below
        line = f"({name}'s purse and pack hold what {name} had plus what {name} picked up or was handed in this talk"
    else:
        items = _text(npc.get('carry_items'))
        have = f"{max(gold, 0)} gold" + (f" and {items}" if items else '')
        # live test 12: an ale picked up dropped her gold count too, and Lydia with 100 gold said she might not have twenty;
        # a hand-over of goods only keeps the gold, with the goods added
        line = f"({name} carries {have}" + (f", plus what {name} picked up or was handed in this talk" if changed else '')
    wares = npc.get('wares')
    stock = wares_text(wares) or _text(npc.get('stock'))
    if _int(npc.get('merchant')) == 1 and stock:
        # live test 8: "I'd like to buy the Candlelight spell tome" always went to stock Barter (the barter menu); a
        # named ware for a price talked out is World's Trade offer_trade, so verbal haggling works. Live test 9: the
        # list named only the dearest wares and Lucan denied having the Oakflesh tome his chest held, so it says it
        # is not complete (the sale itself checks the real chest and says when a ware is truly not there)
        # live test 15: with 5 of 58 wares named, "I'd like to buy a Potion of Minor Healing" (an unnamed ware) went to
        # Barter; every ware is now named with its price when the chest fits (trade turns only), so the list is the
        # whole stock and a ware not in it is not in the shop. Only when World read the chest to its end
        # (wares_complete): a chest past World's scan limit gave a list that only looked whole.
        if whole_stock(wares) and _int(npc.get('wares_complete')) == 1 and not stock_changed(name, messages):  # restocked: the list may be stale
            line += f"; the wares for sale: {stock} ({ALL_STOCK.format(name=name)})"
        else:
            line += f"; a few of the wares for sale: {stock} (shop prices; {NOT_ALL.format(name=name)})"
        asked = asked_text(wares, player_line(messages)) if messages is not None else ''
        if asked:
            line += f"; {ASKED.format(name=name, wares=asked)}"
        if stock_changed(name, messages):
            line += f"; {STOCK_CHANGED.format(name=name)}"
    return line + '.)'


# Live test 10: the barter menu restocks the merchant's chest when it opens (Goat Hide gone, 57 -> 59 wares), but World
# writes the wares when the NPC joins and after a trade, so Lucan's list still named a Goat Hide he no longer had. After
# his barter menu opened or a sale with him in this talk, his line says the stock changed and to check before promising.
STOCK_CHANGED = ("{name}'s stock has changed during this talk (the barter menu restocks it), so the list may be out of "
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
# live test 14: with "you give only what you carry" Lucan read his pack as his whole stock and refused a potion his chest
# held ("not among what I'm carrying"), and with no price for an unnamed ware he never called the sale: the wares are
# the shop's, and a sale with no agreed price goes at the shop price (OfferTrade takes no price as the shop price)
NOT_ALL = ("a sample: {name} sells any shop ware asked for, listed or not, with Trade offer_trade (no price agreed: shop "
           "price); the game refuses a missing one")
# live test 15: the whole stock named (World wrote it; the chest is the shop's): any ware of it is sold with offer_trade,
# and one not in it is not in the shop (stock Barter still opens the menu for browsing)
ALL_STOCK = ("shop prices each; {name}'s whole shop stock: {name} sells any of it asked for with Trade offer_trade (no "
             "price agreed: shop price); a ware not listed is not in the shop")
MAX_NAMED = 100  # wares named in the line (live test 15: 5 was too few); a bigger chest names this many across kinds and prices
MAX_KINDS = 3   # kinds counted by name in "and 14 more: ..."; the rest are "N other"
MAX_WARES = 200


def whole_stock(raw) -> bool:
    """True when World's wares list is usable and every ware of it fits in the line (so the line is the whole stock)."""
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list) or len(raw) > MAX_WARES:
        return False
    usable = sum(1 for r in raw if _ware(r))
    return 0 < usable <= MAX_NAMED
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
    """The wares list: every ware when the chest fits MAX_NAMED, else MAX_NAMED taken a kind at a time (the dearest of
    each kind, then the cheapest, then one between, then the rest), so cheap stock is named as well as soul gems and rings; then how many more
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
    def spread(l):  # the dearest, the cheapest, one between, then the rest dearest first
        seq = []
        for w in [l[0], l[-1], l[len(l) // 2]] + l:
            if w not in seq:
                seq.append(w)
        return seq
    seqs = {k: spread(kinds[k]) for k in order}
    named = []
    for i in range(max(len(s) for s in seqs.values())):  # a kind at a time, so every kind is named before a second of any
        for k in order:
            if len(named) < MAX_NAMED and i < len(seqs[k]):
                named.append(seqs[k][i])
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


# live test 15: "I'd like to buy a Potion of Minor Healing, please." went to stock Barter ("Let me see what I have on
# the shelf"): the potion was in Lucan's chest (2 at 52 gold) but not in the 5-ware sample, so neither its being there
# nor its price was known. A ware the player's own line names is told with its count and shop price.
ASKED = "the ware asked for is in {name}'s shop: {wares}"
MAX_ASKED = 3


def _words(text: str) -> str:
    return ' '.join(re.findall(r"[a-z0-9']+", text.lower().replace('’', "'")))


def _named_in(name: str, said: str) -> bool:
    """True when the player's line (already _words) names this ware, a plural ending allowed on each word. A spell tome
    ("Spell Tome (Novice): Flames") also counts when only its spell is named with "tome" or "book" in the line."""
    words = _words(name).split()
    if not words:
        return False
    pattern = r"(?<![a-z0-9'])" + r"\s+".join(re.escape(w) + r"(?:e?s)?" for w in words) + r"(?![a-z0-9'])"
    if re.search(pattern, said):
        return True
    if ':' in name and re.search(r"\b(?:tome|tomes|book|books)\b", said):
        return _named_in(name.split(':', 1)[1], said) if len(name.split(':', 1)[1].strip()) >= 4 else False
    return False


def asked_text(raw, said: str) -> str:
    """'Potion of Minor Healing, 2 at 52 gold each' for each ware of World's list the player's line names (at most
    MAX_ASKED, a longer name winning over a shorter one inside it); '' when it names none."""
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list) or not said:
        return ''
    said = _words(said)
    found: dict = {}
    for ware in (w for w in (_ware(r) for r in raw[:MAX_WARES]) if w):
        if _named_in(ware[3], said):
            found.setdefault(ware[3], []).append(ware)
    names = sorted(found, key=lambda n: -len(n))
    keep = [n for n in names if not any(n != o and re.search(rf"(?<![a-z0-9']){re.escape(_words(n))}(?![a-z0-9'])", _words(o))
                                        for o in names)]
    keep.sort(key=lambda n: said.find(_words(n).split()[0]))
    parts = []
    for n in keep[:MAX_ASKED]:
        offers = sorted(found[n], key=lambda w: w[2])
        parts.append(n + ', ' + ' and '.join(f"{c} at {p} gold" + (' each' if c > 1 else '') for _, c, p, _ in offers))
    return '; '.join(parts)


NEED_WORDS = re.compile(r"\b(food|eat|eating|hungry|starving|bread|meal|cheese|meat|stew|drink|ale|mead|wine|water|thirsty|"
                        r"cold|freezing|warm|blanket|cloak|potion|spare|share|lend|give)\b", re.I)
FOOD_WORDS = re.compile(r"\b(food|eat|eating|hungry|starving|bread|meal|cheese|meat|stew|drink|ale|mead|wine|thirsty)\b", re.I)


def gate_text(speakers: list[dict], messages, player: str, survival: bool = False) -> str:
    """World's trade gate, told before the NPC answers (live test 18: Gerdur offered goat cheese and wine aloud, then the
    gate turned the hand-over down, since she does not know the player well). On a line asking for something: one line
    per NPC who gives nothing for free (not close, not in the party), and with Survival, food for a party member goes
    through Survival's ShareFood action (the action the game expects for food eaten now), not Trade."""
    said = re.sub(r"\([^()]*\)", ' ', player_line(messages))  # the player's words, not the event lines before them
    if not (wants_trade(said) or NEED_WORDS.search(said)):
        return ''
    player = player or 'the player'
    lines = []
    for s in speakers or []:
        name = _text(s.get('name')) if isinstance(s, dict) else ''
        if not name:
            continue
        follower = (_int(s.get('follower')) or 0) > 0
        if not follower and (_int(s.get('close')) or 0) <= 0:
            lines.append(f"({name} does not know {player} well enough to give anything away: no gold, food, drink or goods "
                         f"as a gift, only a sale or paying back what {player} handed over first, so {name} does not offer it.)")
        elif survival and follower and FOOD_WORDS.search(said):
            lines.append(f"(Food {name} hands {player} to eat now goes through the ShareFood action, not Trade.)")
    return ' '.join(lines)


def carry_text(speakers: list[dict], messages) -> str:
    """One line per NPC here when the player's latest line is about trade, else ''."""
    if not wants_trade(player_line(messages)):
        return ''
    lines = [carry_line(s, messages) for s in speakers or [] if isinstance(s, dict)]
    return ' '.join(line for line in lines if line)
