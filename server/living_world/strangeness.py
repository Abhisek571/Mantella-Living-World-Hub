"""Visible strangeness: people who know an NPC well notice when that NPC is under an Absolute Command of an
enchantment kind (made to love, obey, believe, forget...). One fact line, never a verdict, never a block on what the
player does.

Who notices: a tie of the subject (ties.json: family, spouse, household, boss / workers), or someone with at least
KNOW_WELL memories of the subject. Not the subject, not a child, not someone under a command themselves.
Mages (magic training: MLW_WorldFacts' magic flag, a mage class, the College, Knowledge's mage professions) compare
their Illusion skill with the player's (MLW_WorldFacts writes "illusion" into the npc file and "player_illusion" into
conversation.json):
    clearly weaker (more than WEAKER below)   nothing magical is sensed
    about equal                              something magical is off
    much stronger (STRONGER or more above)   it is Illusion magic, and the player cast it
Without the skills (game side not updated) only the plain line is given. The magic part needs the subject in the
talk (sensed, not heard about); the plain line also covers a tie who is absent from the talk but has been around
them while the command held (at least AROUND_DAYS)."""
import logging
import re

from . import worldlog as W

logger = logging.getLogger('Mantella')

KNOW_WELL = 4
WEAKER = 10
STRONGER = 20
AROUND_DAYS = 1.0
MAX_LINES = 2
ENCHANT = re.compile(
    r"\b(?:love|adore|desire|want|crave|obey|serve|worship|devot\w*|loyal\w*|believe|think|forget|forgotten|remember|"
    r"marry|wife|husband|feel|fall for|attract\w*|trust|submit|yours|mine|belong|charm\w*|calm|fear|hate|like me|"
    r"agree|consent|willing|always|never|you are|you're|act as|behave|become)\b", re.I)


def is_enchantment(record: dict) -> bool:
    """A command that changes how the NPC thinks or feels (rather than a plain task). A kind written on the record by
    command.py wins ('enchantment' / 'obey' / 'task')."""
    if not isinstance(record, dict):
        return False
    kind = str(record.get('kind') or '').lower()
    if kind:
        return kind in ('enchantment', 'charm', 'belief', 'forget', 'feeling')
    return bool(record.get('forget')) or bool(ENCHANT.search(str(record.get('text') or '')))


def _commands(store, commands=None) -> list[dict]:
    if commands is not None:
        return [c for c in commands if isinstance(c, dict)]
    try:
        from . import command
        return command.load(store)['commands']
    except Exception:
        return []


def active_enchantment(store, subject: dict, now=None, commands=None) -> dict | None:
    """The active enchantment-kind command on this person (identify() result), else None. Never for a child."""
    if not subject or subject.get('minor'):
        return None
    for record in _commands(store, commands):
        if record.get('status') not in ('checking', 'active'):
            continue
        until = W._float(record.get('until'))
        if now is not None and 0 < until <= W._float(now):
            continue
        if not is_enchantment(record):
            continue
        for n in record.get('npcs') or []:
            if isinstance(n, dict) and W.same(W.person(n.get('name'), n.get('base_id'), n.get('ref_id')), subject):
                return record
    return None


def _ties_with(observer: dict, subject: dict, ties=None, people=None) -> bool:
    for t in W.ties_for(observer, W.load_ties() if ties is None else ties, people or {}):
        if (t.get('base') and t['base'] == subject.get('base')) or (not t.get('base') and W.norm(t.get('name')) == W.norm(subject.get('name'))):
            return True
    return False


def shared_memories(store, observer: dict, subject: dict) -> int:
    """How many of the observer's memories have the subject in them (by first name or as a witness)."""
    try:
        from . import memory
        data = memory._peek(store, observer['name'], observer['ref'])
    except Exception:
        return 0
    first = (subject.get('name') or '').split(' ')[0]
    if len(first) < 3:
        return 0
    pattern = re.compile(r'\b' + re.escape(first) + r'\b', re.I)
    count = 0
    for e in data.get('recent') or []:
        if e.get('hidden'):
            continue
        if subject.get('name') in (e.get('witnesses') or []) or pattern.search(str(e.get('text') or '')):
            count += 1
    return count


def knows_well(store, observer: dict, subject: dict, ties=None, people=None) -> bool:
    if _ties_with(observer, subject, ties, people):
        return True
    return bool(observer.get('name') and observer.get('ref')) and shared_memories(store, observer, subject) >= KNOW_WELL


def _self_word(subject: dict) -> str:
    return {'female': 'herself', 'male': 'himself'}.get(str(subject.get('sex') or '').strip().lower(), 'themselves')


def _tier(observer: dict, player_illusion) -> str:
    """'' (no magic training or no data), 'weaker', 'equal' or 'stronger'."""
    if not observer.get('magic') or not isinstance(observer.get('illusion'), int) or not isinstance(player_illusion, int):
        return ''
    diff = observer['illusion'] - player_illusion
    if diff < -WEAKER:
        return 'weaker'
    if diff >= STRONGER:
        return 'stronger'
    return 'equal'


def strangeness_line(observer, subject, player: str, store=None, player_illusion=None, commands=None, now=None,
                     present: bool = True, ties=None, people=None, context=None, knows=None) -> str:
    """One fact line for observer about subject when the subject is under an enchantment and the observer knows them
    well; '' otherwise. observer / subject: identify() results (or anything identify() takes, with context).
    knows(observer) False: the observer does not know who the hooded player is, so the caster is not named."""
    try:
        context = dict(context or {}, store=store)
        observer = observer if isinstance(observer, dict) and observer.get('key') else W.identify(observer, context)
        subject = subject if isinstance(subject, dict) and subject.get('key') else W.identify(subject, context)
        if not observer.get('name') or not subject.get('name') or W.same(observer, subject):
            return ''
        if observer.get('minor') or subject.get('minor') or observer.get('unconfirmed') or subject.get('unconfirmed'):
            return ''  # a child, or someone the game has not confirmed as an adult yet
        record = active_enchantment(store, subject, now, commands)
        if record is None or active_enchantment(store, observer, now, commands) is not None:
            return ''
        if not present and now is not None and W._float(now) - W._float(record.get('given'), W._float(now)) < AROUND_DAYS:
            return ''
        if not knows_well(store, observer, subject, ties, people):
            return ''
        if not present and not _ties_with(observer, subject, ties, people):
            return ''
        player = player or 'the player'
        line = f"({observer['name']} knows {subject['name']} well, and {subject['name']} has not been acting like {_self_word(subject)} lately"
        tier = _tier(observer, player_illusion) if present else ''
        if tier == 'equal':
            line += f"; {observer['name']} senses that something magical is off about {subject['name']}"
        elif tier == 'stronger':
            caster = player if knows is None or knows(observer) else 'the hooded stranger'
            line += f"; {observer['name']} can tell it is Illusion magic, and that {caster} cast it"
        return line + '.)'
    except Exception as e:
        logger.warning(f"Living World: the strangeness line failed ({e})")
        return ''


def text(store, speakers=None, player: str = '', characters=None, now=None, commands=None, knows=None) -> str:
    """Lines for the newest message: for each NPC in the talk, about each other NPC here under an enchantment, and
    about absent ties of theirs who are (at most MAX_LINES). '' when there is nothing. Never raises."""
    try:
        from . import lw_state
        if speakers is None:
            speakers = lw_state.load_conversation()
        player = player or lw_state.load_player_name() or 'the player'
        if now is None:
            now = lw_state.load_today()
        player_illusion = _player_illusion()
        records = _commands(store, commands)
        if not any(r.get('status') in ('checking', 'active') and is_enchantment(r) for r in records):
            return ''
        context = {'speakers': speakers, 'people': [(getattr(c, 'name', ''), getattr(c, 'ref_id', '')) for c in characters or []],
                   'store': store}
        ties = W.load_ties()
        people = W.read_people(store)
        here = [W.identify(s, context, people, ties) for s in (characters or speakers or [])]
        lines = []
        for observer in here:
            for subject in here:
                line = strangeness_line(observer, subject, player, store, player_illusion, records, now, True, ties, people,
                                        knows=knows)
                if line and line not in lines:
                    lines.append(line)
            for record in records:  # absent ties under a command
                for n in record.get('npcs') or []:
                    subject = W.identify({'name': n.get('name'), 'ref_id': n.get('ref_id'), 'base_id': n.get('base_id')},
                                         {'store': store}, people, ties)
                    if any(W.same(subject, h) for h in here):
                        continue
                    line = strangeness_line(observer, subject, player, store, player_illusion, records, now, False, ties, people)
                    if line and line not in lines:
                        lines.append(line)
        return '\n'.join(lines[:MAX_LINES])
    except Exception as e:
        logger.warning(f"Living World: strangeness lines failed ({e})")
        return ''


def _player_illusion():
    try:
        from . import contracts, lw_state
        value = contracts.game_flat(lw_state._read('conversation.json')).get('player_illusion')  # keys without case
        return value if isinstance(value, int) and not isinstance(value, bool) else None
    except Exception:
        return None
