"""Intimacy, the NPC decides: one line per NPC in the talk for the newest message, with what they have to go on
instead of a verdict. The scene action (OStim Expansion) carries a decision (accept or decline) and a reason; the game
side handles a decline as a real result (HUD line, event line, memory).

    offered the scene, Default     the facts that exist (how they stand with the player, partner, how long they have
                                   known the player, an absolute command, Arousal's open nature) and that they decide
                                   for themselves and may refuse
    offered the scene, willing     told they are willing (Intimacy: always willing, or Always willing on the hotkey)
    not offered (Lovers only)      a game fact: they are not lovers, so nothing intimate can start now
    not offered (Intimacy: never)  a game fact: nothing intimate starts with them
Nothing with a child in the talk (the child rules cover it), nothing while the game has not confirmed every speaker as
an adult (action_filter.adult: no npc file yet, a broken one, no minor key), and nothing when the scene action is not
gated (OStim Expansion missing)."""
from . import action_filter, characters

SCENE_ACTION = 'SexWithPlayer'  # OStim Expansion's scene with the player
RANKS = {4: 'lover', 3: 'ally', 2: 'confidant', 1: 'friend', 0: 'acquaintance', -1: 'rival', -2: 'foe', -3: 'enemy',
         -4: 'archnemesis'}


def _int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def known_text(talks: int, first_day: int | None, today: int | None, player: str) -> str:
    """How long they have known the player, from their memories: talks remembered and the first one's day."""
    if talks <= 0:
        return f"no talks with {player} remembered before this one"
    text = f"{talks} talk{'s' if talks != 1 else ''} with {player} remembered"
    if first_day is not None and first_day >= 0 and today is not None and today >= first_day:
        days = today - first_day
        text += ', the first today' if days == 0 else f", the first {days} day{'s' if days != 1 else ''} ago"
    return text


def facts(npc: dict, player: str, known: str = '', entry: dict | None = None) -> list[str]:
    """What exists about this NPC and the player: game standing, partner (the Characters page's pinned one first),
    travelling together, Arousal's open nature, how long they have known each other, an absolute command."""
    out = []
    rank = _int(npc.get('rank'))
    if rank in RANKS:
        out.append(f"how they stand with {player} in the game: {RANKS[rank]}")
    pinned = ((entry or {}).get('pinned') or {}).get('partner')
    partner = pinned if isinstance(pinned, str) and pinned.strip() else characters.live_partner(npc, player)
    if partner:
        out.append(f"partner: {partner}")
    if _int(npc.get('follower'), 0) > 0:
        out.append(f"travels with {player}")
    if _int(npc.get('close'), 0) == 2:  # the Arousal module's open group (forward by nature)
        out.append('open about desire by nature')
    if known:
        out.append(known)
    if _int(npc.get('commanded'), 0) > 0:
        out.append(f"an absolute command from {player} is in force on them (see the command)")
    return out


def line(speakers: list[dict], gates: dict, player: str, mode: str, known_for=None, data=None) -> str:
    """The newest-message line for every adult NPC here. known_for(npc) -> known_text or ''."""
    gate = gates.get(SCENE_ACTION)
    if not gate or not speakers or any(not action_filter.adult(s) for s in speakers):
        return ''
    data = data if data is not None else characters.load()
    lines = []
    for s in speakers:
        name = s.get('name')
        if not name:
            continue
        choice = characters.intimacy_choice(s, data=data)
        if not action_filter.may_use(s, gate):
            if choice == 'never':
                lines.append(f"(Nothing intimate starts between {name} and {player}: {name} will not, whatever is said.)")
            else:
                lines.append(f"({name} and {player} are not lovers, so nothing intimate can start between them now.)")
            continue
        if choice == 'willing' and _int(s.get('commanded'), 0) <= 0:
            lines.append(f"({name} is willing to be intimate with {player}. If {player} asks for it, use the scene "
                         f"action with decision accept.)")
            continue
        entry = characters.entry_for(str(name), s.get('race', ''), data=data)
        known = ''
        if known_for is not None:
            try:
                known = known_for(s) or ''
            except Exception:
                known = ''
        what = facts(s, player, known, entry)
        lines.append(f"(Whether to be intimate with {player} is {name}'s own choice: {name} decides as the person they "
                     f"are and may refuse. " + (f"What {name} has to go on: {'; '.join(what)}. " if what else '') +
                     f"If {player} asks for it, use the scene action with decision accept or decline and a short "
                     f"reason.)")
    return ' '.join(lines)
