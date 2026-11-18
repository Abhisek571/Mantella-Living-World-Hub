"""Battle accounts, from World's battles.json: each fight near the player as World's SKSE plugin recorded it (who fought
on which side, who died, health lost and dealt, close calls, rescues, magic, kills). While World keeps a fight in the
prompt (the hours set on the MCM's World page), each NPC in the conversation who was in it gets a short account from
their own side in the newest message, and a bystander gets one line that they saw it. A fight worth remembering becomes
one memory entry for each NPC who was there: when a talk with them ends, or at the start of their first talk after the
account has left the prompt. No model call; only what the game recorded, in words, never numbers."""
from . import archive, memory, timeline

MAX_FIGHTS = 2   # accounts per NPC, newest first (one each in a group talk)
MAX_NAMES = 6    # people listed by name per side, and items per list (kills, close calls, magic)
MAX_ACCOUNT_CHARS = 1000  # one account at most (a big battle would otherwise fill the newest message every turn)
MAX_GROUP_CHARS = 2400  # all accounts of a group talk together, at most (each NPC gets their share, never under 450)
MAX_SEEN = 200  # fight ids kept per NPC once remembered, so a fight folded out of recent is never added again
LOW = 0.15       # below this much health is a close call (World's plugin uses the same)
HARM_ORDER = ('fire', 'frost', 'shock', 'poison', 'slow', 'paralysis', 'drain')
HELP_ORDER = ('healing', 'ward', 'armor')
# How much a fight matters to one NPC (memory importance 0-1, see archive.retention): by what was fought, then raised
# by what happened to them and around them. Only memorable fights become memories at all.
TIER_FEW = 0.45     # one or two ordinary foes (a wolf, a pair of bandits)
TIER_PACK = 0.55    # three to five
TIER_HORDE = 0.65   # six or more
TIER_NAMED = 0.75   # a named or unique foe
TIER_DRAGON = 0.9   # a dragon
DEATH_FLOOR = 0.85  # someone on their side died: never less than this
SELF_CLOSE = 0.15   # they went down or nearly died
PLAYER_CLOSE = 0.1  # the player went down or nearly died
SAVED_BY_PLAYER = 0.15  # the player got them out of it
SAVED_PLAYER = 0.1  # they got the player out of it
LONG_FIGHT = 0.05   # it went on for two minutes or more
BYSTANDER_LESS = 0.2  # only watching: this much less, never under BYSTANDER_MIN
BYSTANDER_MIN = 0.3


def _num(value, default=0.0) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def _flag(value) -> bool:
    return _num(value) > 0


def _refs(value) -> list[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def fighters(fight: dict) -> list[dict]:
    people = fight.get('fighters') if isinstance(fight, dict) else None
    out = [f for f in people if isinstance(f, dict) and isinstance(f.get('ref_id'), str) and isinstance(f.get('name'), str)] \
        if isinstance(people, list) else []
    for f in out:  # the role is compared as a word (player, party, summon, bystander), whatever its case
        if isinstance(f.get('role'), str) and f['role'] != f['role'].strip().lower():
            f['role'] = f['role'].strip().lower()
    _passive_player(out)
    return out


def _passive_player(people: list[dict]) -> None:
    """A player World records as landing no real blow ("struck": 0, newer World) who cast no harm on anyone on the other
    side and has no summon that fought is not told as having fought or killed: his damage and kills are dropped and a
    kill put down to him has no killer (live test 10: "dealt 23" and the wolf's killer in three fights he never joined,
    from a cloak or aura on him). An older World writes no "struck": its record is told as it is."""
    side_of = {f['ref_id']: int(_num(f.get('side'))) for f in people}
    for p in people:
        if p.get('role') != 'player' or 'struck' not in p or _flag(p.get('struck')):
            continue
        me = p['ref_id']
        cast = any(me in _refs(refs) for f in people if side_of[f['ref_id']] != side_of[me] and f.get('role') != 'party'
                   for refs in (f.get('harm').values() if isinstance(f.get('harm'), dict) else []))
        summon = any(f.get('role') == 'summon' and f.get('owner') == me and (_flag(f.get('struck')) or _num(f.get('dealt')) > 0)
                     for f in people)
        if cast or summon:
            continue
        p['dealt'], p['kills'] = 0, []
        for f in people:
            if f.get('killer') == me:
                f['killer'] = ''


def find(fight: dict, key, ref) -> dict | None:
    """The fighter in this fight whose reference is key (already cut by ref, the Hub's reference comparison)."""
    if key is None:
        return None
    return next((f for f in fighters(fight) if ref(f['ref_id']) == key), None)


def _counted(f: dict) -> bool:
    """Named in the account: summons count for their owner, bystanders only get the witness line."""
    return f.get('role') not in ('summon', 'bystander')


HOODED_NAME = 'the hooded stranger'  # the player in the account of an NPC who does not know who is under the hood


def hooded(fight: dict) -> dict:
    """The fight as an NPC who does not know who the hooded player is tells it: the player fighter is "the hooded
    stranger", never the name."""
    return dict(fight, fighters=[dict(f, name=HOODED_NAME) if f.get('role') == 'player' else f for f in fighters(fight)])


def _label(f: dict, me: dict | None) -> str:
    return 'you' if f is me else f['name']


def hurt(f: dict) -> str:
    if _flag(f.get('dead')):
        return 'killed'
    if _flag(f.get('down')):
        return 'went down'
    low = _num(f.get('lowest'), 1.0)
    if low < LOW:
        return 'nearly killed'
    if low < 0.3:
        return 'badly hurt'
    if low < 0.6:
        return 'hurt'
    if low < 0.9:
        return 'lightly hurt'
    return 'unhurt'


def dealt(fight: dict) -> dict[str, float]:
    """Health each fighter took from the other side, a summon's added to its owner's."""
    out = {}
    for f in fighters(fight):
        owner = f.get('owner') if f.get('role') == 'summon' else ''
        key = owner if isinstance(owner, str) and owner else f['ref_id']
        out[key] = out.get(key, 0.0) + max(0.0, _num(f.get('dealt')))
    return out


def share(part: float, total: float) -> str:
    if total <= 0:
        return ''
    if part >= total * 0.5:
        return 'most of the fighting'
    if part >= total * 0.25:
        return 'a good share of the fighting'
    if part >= total * 0.08:
        return 'some of the fighting'
    if part > 0:
        return 'a little of the fighting'
    return 'none of the fighting'


def length(seconds, active: bool) -> str:
    s = _num(seconds)
    if s < 15:
        text = 'a few seconds'
    elif s < 60:
        text = 'under a minute'
    elif s < 105:
        text = 'about a minute'
    else:
        text = f'about {round(s / 60)} minutes'
    return text + (' so far' if active else '')


def when(fight: dict, today: int | None) -> str:
    if _flag(fight.get('active')):
        return 'going on now'
    end = _num(fight.get('end'), -1.0)
    if end < 0:
        return ''
    day, hour = memory.day_hour(end)
    part = memory.time_group(hour)
    if today is None:
        return part
    ago = today - day
    if ago <= 0:
        return f'earlier today, {part}'
    if ago == 1:
        return f'yesterday {part}'
    return f'{ago} days ago'


def _place(fight: dict) -> str:
    place = fight.get('place')
    return f' at {place.strip()}' if isinstance(place, str) and place.strip() else ''


def _join(items: list[str]) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return ''.join(items)
    return ', '.join(items[:-1]) + ' and ' + items[-1]


def _grouped(names: list[str]) -> str:
    """"Bandit Chief, Bandit ×2": same names counted, in the order first met; past MAX_NAMES names, "N more"."""
    counts = {}
    for name in names:
        counts[name] = counts.get(name, 0) + 1
    shown = list(counts.items())
    text = ', '.join(name if n == 1 else f'{name} ×{n}' for name, n in shown[:MAX_NAMES])
    rest = sum(n for _, n in shown[MAX_NAMES:])
    return text + (f', {rest} more' if rest else '')


def _capped(parts: list[str], more: str) -> str:
    """At most MAX_NAMES of parts, then how many more."""
    if len(parts) <= MAX_NAMES:
        return '; '.join(parts)
    return '; '.join(parts[:MAX_NAMES]) + f'; {len(parts) - MAX_NAMES} more {more}'


def _clip(text: str, limit: int = MAX_ACCOUNT_CHARS) -> str:
    """At most limit characters, cut after the last whole line (else word) that fits."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = cut.rfind('\n')
    if end < limit // 2:
        end = cut.rfind(' ')
    return cut[:end].rstrip(' ;,') + ' ...'



def _people(people: list[dict], me: dict | None, detail) -> str:
    """One side: each person with detail(f), same-named strangers grouped ("Bandit ×3 (2 killed, 1 survived)")."""
    groups = {}
    for f in people:
        key = id(f) if f is me or _flag(f.get('unique')) or f.get('role') in ('player', 'party') else f['name']
        groups.setdefault(key, []).append(f)
    parts = []
    for group in list(groups.values())[:MAX_NAMES]:
        if len(group) == 1:
            more = detail(group[0])
            parts.append(_label(group[0], me) + (f' ({more})' if more else ''))
            continue
        dead = sum(1 for f in group if _flag(f.get('dead')))
        fate = ', '.join(t for t in (f'{dead} killed' if dead else '', f'{len(group) - dead} survived' if len(group) > dead else '') if t)
        parts.append(f"{group[0]['name']} ×{len(group)} ({fate})")
    rest = sum(len(g) for g in list(groups.values())[MAX_NAMES:])
    if rest:
        parts.append(f'{rest} more')
    return ', '.join(parts)


def _by_ref(fight: dict) -> dict[str, dict]:
    return {f['ref_id']: f for f in fighters(fight)}


def _kills(fight: dict, me: dict | None) -> str:
    """Kills by the final blow, the player's first and set apart."""
    people = _by_ref(fight)
    killers = [f for f in fighters(fight) if _counted(f) and _refs(f.get('kills'))]
    killers.sort(key=lambda f: f.get('role') != 'player')
    parts = []
    for f in killers:
        victims = _grouped([_label(people[r], me) for r in _refs(f.get('kills')) if r in people])
        if victims:
            parts.append(f'{_label(f, me)} killed {victims}')
    if not parts:
        return ''
    if killers[0].get('role') == 'player' and len(parts) > 1:
        return f'{parts[0]}; others: ' + _capped(parts[1:], 'with kills')
    return _capped(parts, 'with kills')


def _close_calls(fight: dict, side: int, me: dict | None) -> str:
    """Who on this side went down or nearly died, whose blows did it, and who got them out of it."""
    people = _by_ref(fight)
    calls = []
    for f in sorted(fighters(fight), key=lambda f: f is not me):  # their own close call first
        if not _counted(f) or int(_num(f.get('side'))) != side or _flag(f.get('dead')):
            continue
        down = _flag(f.get('down'))
        if not down and _num(f.get('lowest'), 1.0) >= LOW:
            continue
        who = _label(f, me)
        text = f"{who} {'went down' if down else 'nearly died'}"
        attacker = people.get(f.get('danger_by'))
        if attacker:
            text += f" from {_label(attacker, me)}'s blows"
        saves = []
        for rescue in f.get('rescued_by') if isinstance(f.get('rescued_by'), list) else []:
            rescuer = people.get(rescue.get('ref')) if isinstance(rescue, dict) else None
            if not rescuer:
                continue
            how = f"by killing {_label(attacker, me)}" if rescue.get('how') == 'kill' and attacker else 'with a heal' if rescue.get('how') == 'heal' else ''
            saves.append(f"{_label(rescuer, me)} saved {'you' if f is me else 'them'} {how}".strip())
        if saves:
            text += '; ' + _capped(saves, 'helped')
        calls.append(text)
    return _capped(calls, 'close calls')


def area_casters(fight: dict) -> set:
    """Casters whose harmful magic also landed on their own side: an aura, cloak, ability or enchantment that touches
    everyone near them, not a spell aimed at a foe (live test 7: drain and slow put down to the player on the wolf and on
    Lydia, his own follower, in every fight, while he cast nothing). World's plugin records any harmful effect by its
    caster, whatever cast it, so such harm is not told as theirs."""
    side_of = {f['ref_id']: int(_num(f.get('side'))) for f in fighters(fight)}
    players = {f['ref_id'] for f in fighters(fight) if f.get('role') == 'player'}
    out = set()
    for f in fighters(fight):
        table = f.get('harm') if isinstance(f.get('harm'), dict) else {}
        for refs in table.values():
            for r in _refs(refs):
                if r != f['ref_id'] and r in side_of and (side_of[r] == side_of[f['ref_id']] or (r in players and _party(f, players))):
                    out.add(r)
    return out


def _party(f: dict, players: set) -> bool:
    """A member of the player's party (a follower, or the player's own summon), whatever side the record gives them: the player's
    magic on them is never an attack (live test 9: drain and slow from the player on Lydia, still recorded after the
    plugin's cast check; a record whose sides are off must not turn it into one)."""
    return f.get('role') == 'party' or (f.get('role') == 'summon' and f.get('owner') in players)


def _magic(fight: dict, me: dict, kinds: str, order: tuple) -> str:
    """"fire and slow from Bandit Mage": what was put on me, by caster. Harm from a caster whose magic also hit their
    own side (area_casters) is left out: it was no spell cast at anyone."""
    people = _by_ref(fight)
    table = me.get(kinds) if isinstance(me.get(kinds), dict) else {}
    skip = area_casters(fight) if kinds == 'harm' else set()
    players = {r for r, f in people.items() if f.get('role') == 'player'}
    if kinds == 'harm' and _party(me, players):  # the player's magic on their own party is never told to them as an attack
        skip |= players
    by = {}
    for kind in order:
        for r in _refs(table.get(kind)):
            if r in people and r not in skip:
                by.setdefault(r, []).append(kind)
    return _capped([f"{_join(k)} from {_label(people[r], me)}" for r, k in by.items()], 'casters')


def _sides(fight: dict, side: int) -> tuple[list[dict], list[dict]]:
    counted = [f for f in fighters(fight) if _counted(f)]
    return ([f for f in counted if int(_num(f.get('side'))) == side], [f for f in counted if int(_num(f.get('side'))) != side])


def account(fight: dict, me: dict, today: int | None, limit: int = MAX_ACCOUNT_CHARS) -> str:
    """What one fighter is told: the fight from their own side, at most limit characters (who was only there goes
    last, so it is what a long account loses first)."""
    side = int(_num(me.get('side')))
    ours, theirs = _sides(fight, side)
    if not theirs:
        return ''
    done = dealt(fight)
    total = sum(done.get(f['ref_id'], 0.0) for f in ours)
    ours.sort(key=lambda f: (f.get('role') != 'player', f is not me))
    own = lambda f: '; '.join(t for t in (hurt(f), share(done.get(f['ref_id'], 0.0), total)) if t)

    def theirs_detail(f):
        killer = _by_ref(fight).get(f.get('killer'))
        return f'killed by {_label(killer, me)}' if killer and _flag(f.get('dead')) else 'killed' if _flag(f.get('dead')) else f'survived, {hurt(f)}'

    head = ', '.join(t for t in (when(fight, today), length(fight.get('seconds'), _flag(fight.get('active')))) if t)
    lines = [f"{me['name']}'s own account of a fight{_place(fight)} ({head}); this is what really happened:",
             f'- Your side: {_people(ours, me, own)}.',
             f'- Against you: {_people(theirs, me, theirs_detail)}.']
    for title, text in (('Kills', _kills(fight, me)), ('Close calls', _close_calls(fight, side, me)),
                        ('Magic put on you', _magic(fight, me, 'harm', HARM_ORDER)), ('Help you got', _magic(fight, me, 'help', HELP_ORDER))):
        if text:
            lines.append(f'- {title}: {text}.')
    bystanders = [f['name'] for f in fighters(fight) if f.get('role') == 'bystander']
    if bystanders:
        lines.append(f'- Also there, not fighting: {_grouped(bystanders)}.')
    return _clip('\n'.join(lines), limit)


def _sides_text(fight: dict, me: dict | None) -> str:
    """"Dragonborn and Lydia against Bandit Chief, Bandit ×3", the player's side first."""
    ours, theirs = _sides(fight, 0)
    ours.sort(key=lambda f: f.get('role') != 'player')
    return f"{_join([_label(f, me) for f in ours[:MAX_NAMES]])} against {_grouped([_label(f, me) for f in theirs][:MAX_NAMES * 2])}"


def _dead_text(fight: dict, me: dict | None) -> str:
    dead = [_label(f, me) for f in fighters(fight) if _counted(f) and _flag(f.get('dead'))]
    return f'Dead: {_grouped(dead)}.' if dead else 'Nobody died.'


def witness_line(fight: dict, me: dict, today: int | None) -> str:
    """What a bystander who saw it is told: one line."""
    head = when(fight, today)
    return f"{me['name']} saw a fight{_place(fight)}{f' ({head})' if head else ''}: {_sides_text(fight, None)}. {_dead_text(fight, None)}"


def prompt_text(speakers: list[dict], fights: list[dict], today: int | None, ref, knows=None) -> str:
    """The accounts for everyone in the conversation who was in a fight World still keeps in the prompt. In a group talk
    each block says it is that NPC's alone (one model writes every line). knows(speaker) False: they do not know who the
    hooded player is, so their account never names him (no knows: named, as before)."""
    live = [f for f in fights or [] if isinstance(f, dict) and _flag(f.get('in_prompt'))]
    if not live:
        return ''
    blocks = []
    limit = MAX_ACCOUNT_CHARS if len(speakers or []) <= 1 else max(450, min(MAX_ACCOUNT_CHARS, MAX_GROUP_CHARS // len(speakers)))
    for s in speakers or []:
        key = ref(s.get('ref_id'))
        texts, name = [], s.get('name')
        known = knows is None or bool(knows(s))
        for fight in live:
            fight = fight if known else hooded(fight)
            me = find(fight, key, ref)
            if me is None:
                continue
            text = _clip(witness_line(fight, me, today), limit) if me.get('role') == 'bystander' else account(fight, me, today, limit)
            if text:
                texts.append(text)
                name = name or me['name']
            if len(texts) >= (MAX_FIGHTS if len(speakers) == 1 else 1):
                break
        if not texts:
            continue
        block = '\n'.join(texts)
        if len(speakers) > 1:
            block = f"(Only {name} knows this; the others here learn it only if {name} says it.)\n" + block
        blocks.append(block)
    return '\n\n'.join(blocks)


def memorable(fight: dict) -> bool:
    """Worth remembering: someone on the player's side died, went down or nearly died, a rescue, a named enemy or a
    dragon, or a long fight against three or more."""
    if not isinstance(fight, dict) or _flag(fight.get('active')):
        return False
    ours, theirs = _sides(fight, 0)
    if not theirs:
        return False
    if any(_flag(f.get('dead')) or _flag(f.get('down')) or _num(f.get('lowest'), 1.0) < LOW for f in ours):
        return True
    if any(f.get('rescued_by') for f in ours):
        return True
    if any(_flag(f.get('unique')) or _flag(f.get('dragon')) for f in theirs):
        return True
    return len(theirs) >= 3 and _num(fight.get('seconds')) >= 20


def _close(f: dict) -> bool:
    return _flag(f.get('down')) or _num(f.get('lowest'), 1.0) < LOW


def _rescuers(f: dict) -> set:
    return {r.get('ref') for r in f.get('rescued_by') if isinstance(r, dict)} if isinstance(f.get('rescued_by'), list) else set()


def importance(fight: dict, me: dict) -> float:
    """How much this fight matters to me (a fighter of it), from what World recorded: what was fought (a dragon over a
    named foe over a horde over a wolf), whether anyone on my side died, whether I or the player nearly died, and who
    saved whom. A bystander remembers it less."""
    side = int(_num(me.get('side')))
    ours, theirs = _sides(fight, side)
    if me.get('role') == 'bystander':  # no side of their own: what the player's side fought
        ours, theirs = _sides(fight, 0)
    if any(_flag(f.get('dragon')) for f in theirs):
        value = TIER_DRAGON
    elif any(_flag(f.get('unique')) for f in theirs):
        value = TIER_NAMED
    elif len(theirs) >= 6:
        value = TIER_HORDE
    elif len(theirs) >= 3:
        value = TIER_PACK
    else:
        value = TIER_FEW
    if _num(fight.get('seconds')) >= 120:
        value += LONG_FIGHT
    player = next((f for f in fighters(fight) if f.get('role') == 'player'), None)
    if me.get('role') == 'bystander':
        if any(_flag(f.get('dead')) for f in ours):
            value = max(value, DEATH_FLOOR)
        return round(max(BYSTANDER_MIN, min(1.0, value) - BYSTANDER_LESS), 2)
    if any(_flag(f.get('dead')) for f in ours if f is not me):
        value = max(value, DEATH_FLOOR)
    if _close(me):
        value += SELF_CLOSE
    if player is not None and player is not me:
        if _close(player) and int(_num(player.get('side'))) == side:
            value += PLAYER_CLOSE
        if player['ref_id'] in _rescuers(me):
            value += SAVED_BY_PLAYER
        if me['ref_id'] in _rescuers(player):
            value += SAVED_PLAYER
    return round(min(1.0, value), 2)


def fight_flags(fight: dict, me: dict) -> list[str]:
    """The fixed flags of a fight memory (archive.FLAG_FLOORS): the player fought against me (harmed), the player saved
    me or I saved the player (rescue), I fought on the player's side (fought_beside). A bystander gets none."""
    player = next((f for f in fighters(fight) if f.get('role') == 'player'), None)
    if player is None or player is me or me.get('role') == 'bystander':
        return []
    out = []
    if int(_num(me.get('side'))) != int(_num(player.get('side'))):
        out.append('harmed')
    elif player['ref_id'] in _rescuers(me) or me['ref_id'] in _rescuers(player):
        out.append('rescue')
    elif _flag(me.get('struck')) or _num(me.get('dealt')) > 0:
        out.append('fought_beside')
    return out


def memory_line(fight: dict, me: dict) -> str:
    """The memory entry: short, from their own side, no date (the memory adds it)."""
    if me.get('role') == 'bystander':
        return f"Saw a fight{_place(fight)}: {_sides_text(fight, None)}. {_dead_text(fight, None)}"
    side = int(_num(me.get('side')))
    ours, theirs = _sides(fight, side)
    ours.sort(key=lambda f: (f is not me, f.get('role') != 'player'))
    parts = [f"Fight{_place(fight)}, {length(fight.get('seconds'), False)}: "
             f"{_join([_label(f, me) for f in ours[:MAX_NAMES]])} against {_grouped([f['name'] for f in theirs][:MAX_NAMES * 2])}.",
             _dead_text(fight, me)]
    done = dealt(fight)
    mine = share(done.get(me['ref_id'], 0.0), sum(done.get(f['ref_id'], 0.0) for f in ours))
    parts.append(f"You: {hurt(me)}{'; ' + mine if mine else ''}.")
    for text in (_close_calls(fight, side, me), _kills(fight, me)):
        if text:
            parts.append(text[0].upper() + text[1:] + '.')
    return _clip(' '.join(parts), memory.MAX_ENTRY_CHARS)


def _insert(recent: list, entry: dict) -> None:
    """In time order: a fight from before the last talk goes before it."""
    at = len(recent)
    while at > 0 and (recent[at - 1].get('day', -1), recent[at - 1].get('hour', -1)) > (entry['day'], entry['hour']):
        at -= 1
    recent.insert(at, entry)


def remember(store, characters, fights: list[dict], ref, at_end: bool, knows=None) -> int:
    """One memory entry per memorable fight for each of these Mantella characters who was in it (or saw it), once.
    at_end: a talk is ending, so fights still in the prompt count too; otherwise only fights whose account has left the
    prompt (it would say the same thing twice). knows(character) False: they do not know who the hooded player is, so
    the memory says "the hooded stranger" and is marked unrecognised (no knows: named, as before). Returns the entries
    added."""
    ended = [f for f in fights or [] if memorable(f) and (at_end or not _flag(f.get('in_prompt')))]
    added = 0
    for character in characters or []:
        name, ref_id = getattr(character, 'name', None), getattr(character, 'ref_id', None)
        key = ref(ref_id)
        known = knows is None or bool(knows(character))
        mine = [(fight, me) for fight in (ended if known else [hooded(f) for f in ended]) if (me := find(fight, key, ref)) is not None]
        if not name or not mine:
            continue
        with store.lock(name, ref_id):
            added += _remember_one(store, name, ref_id, mine, known)
    return added


def _remember_one(store, name: str, ref_id: str, mine: list, recognised: bool = True) -> int:
    """remember() for one NPC, with their memory file's lock held. A fight is known by its id in recent, in the
    battles list (kept after it folded out of recent) or, for files from before that list, by its entry in the
    archive."""
    try:
        mem = store.load(name, ref_id)
    except OSError:
        return 0  # locked: tried again at their next talk
    seen = list(dict.fromkeys([str(b) for b in mem.get('battles') or []] + [str(e['battle']) for e in mem['recent'] if e.get('battle')]))
    known = set(seen)
    try:
        stored = store.archive_for(name, ref_id).ids() if store.archive_for(name, ref_id).exists() else {}
    except Exception:
        stored = {}
    new = 0
    branch = timeline.current(store)  # the save's talk counter: a fight remembered now belongs to this talk
    stamp = branch.stamp() if branch is not None else {}
    for fight, me in sorted(mine, key=lambda pair: _num(pair[0].get('end'))):
        key_id = str(fight.get('id'))
        if key_id in known:
            continue
        day, hour = memory.day_hour(_num(fight.get('end')))
        entry = {'day': day + memory.MANTELLA_DAY, 'hour': hour, 'text': memory_line(fight, me)[:memory.MAX_ENTRY_CHARS],
                 'witnesses': [name], 'battle': key_id, 'type': 'experience', 'importance': importance(fight, me), **stamp}
        for flag in fight_flags(fight, me):
            archive.add_flag(entry, flag)
        if not recognised:
            entry['unrecognised'] = True  # never counts toward knowing the player
        known.add(key_id)
        seen.append(key_id)
        if archive.entry_id(entry) in stored:
            continue  # remembered before and folded away already
        _insert(mem['recent'], entry)
        new += 1
    if new or seen != [str(b) for b in mem.get('battles') or []]:
        mem['battles'] = seen[-MAX_SEEN:]
        # no folding here: that needs the summary model to shorten old memories, and the next talk's save does it
        store.save(name, ref_id, mem)
    return new
