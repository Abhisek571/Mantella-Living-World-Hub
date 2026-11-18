"""Player reputation: what people around an NPC have come to believe about the player, from the world log, built with
rules (no model call). Only events that have reached this NPC count (news.reached_events: known to them or due by
the news rings), never one wiped for them, and only what onlookers could know (an event's public side: a killing
nobody saw does not name the player, a spell nobody revealed is not known). One short line, '' when nothing notable."""
import logging

from . import worldlog as W

logger = logging.getLogger('Mantella')

MAX_ITEMS = 3
SEVERAL_MARRIAGES = 3


def beliefs(events: list[dict], player: str) -> list[str]:
    """The items, most serious first, from the events that reached someone."""
    count = lambda fn: sum(1 for e in events if fn(e))
    involves = lambda e: any(p.get('key') == W.PLAYER for p in e.get('involved') or [])
    killings = count(lambda e: e.get('kind') == 'killing' and e.get('player_named'))
    revealed = count(lambda e: (e.get('kind') == 'release' and e.get('came_to_light')))
    marriages = count(lambda e: e.get('kind') == 'marriage' and involves(e))
    # a marriage made under a command only looks strange to people once a spell on that spouse came to light
    spelled = [p for e in events if e.get('kind') == 'release' and e.get('came_to_light') for p in e.get('involved') or []
               if p.get('key') != W.PLAYER]
    strange = count(lambda e: e.get('kind') in ('marriage', 'engagement') and e.get('strange') and involves(e)
                    and any(W.same(p, s) for p in e.get('involved') or [] if p.get('key') != W.PLAYER for s in spelled))
    divorces = count(lambda e: e.get('kind') == 'divorce' and involves(e))
    dragons = count(lambda e: e.get('kind') == 'fight' and e.get('dragon') and involves(e))
    items = []
    if killings:
        items.append('has killed someone who was no threat' if killings == 1 else 'has killed people who were no threat')
    if revealed:  # only someone the spelled NPC told (the Hub's Tell), never the rings: a release is never news
        items.append("is said to have put someone under a spell" if revealed == 1 else "is said to bend people's minds with magic")
    if strange:
        items.append(f"has married in strange circumstances; some say the spouse was not themselves")
    elif marriages >= SEVERAL_MARRIAGES:
        items.append('has married several times')
    if divorces >= 2:
        items.append('has ended more than one marriage')
    if dragons:
        items.append('has fought a dragon')
    return items[:MAX_ITEMS]


def reputation_line(npc, store, player: str = '', now_day=None, context=None) -> str:
    """One line for this NPC, or ''. npc: a Mantella character, a speaker dict or an identify() result."""
    try:
        from . import news
        if store is None:
            return ''
        if now_day is None:
            from . import lw_state
            now_day = lw_state.load_today()
        player = player or 'the player'
        me = news._resolve(store, npc, context)
        if not me.get('name'):
            return ''
        reached = [e for e in news.reached_events(store, me, now_day, context)  # never their own wipe or spell
                   if not (e.get('kind') in ('wipe', 'release') and any(W.same(p, me) for p in e.get('involved') or []))]
        items = beliefs(reached, player)
        if not items:
            return ''
        where = f"around {W.hold_text(me['hold'])}" if me.get('hold') else 'around here'
        return f"(What people {where} have come to believe about {player}: {player} " + '; '.join(items) + '.)'
    except Exception as e:
        logger.warning(f"Living World: the reputation line failed ({e})")
        return ''


def text(store, characters, player: str = '', now_day=None, speakers=None) -> str:
    """The reputation lines for every NPC in a talk (one when they are all the same)."""
    try:
        from . import lw_state
        if speakers is None:
            speakers = lw_state.load_conversation()
        player = player or lw_state.load_player_name() or 'the player'
        context = {'speakers': speakers, 'store': store,
                   'people': [(getattr(c, 'name', ''), getattr(c, 'ref_id', '')) for c in characters or []]}
        lines = []
        for c in characters or []:
            line = reputation_line(c, store, player, now_day, context)
            if line:
                lines.append((getattr(c, 'name', '') or (c.get('name') if isinstance(c, dict) else ''), line))
        if not lines:
            return ''
        if len(lines) == len(characters) and len({l for _, l in lines}) == 1:
            return lines[0][1]
        return '\n'.join(f"{line[:-2]}; only {name} has heard this.)" if len(characters) > 1 else line for name, line in lines)
    except Exception as e:
        logger.warning(f"Living World: reputation lines failed ({e})")
        return ''
