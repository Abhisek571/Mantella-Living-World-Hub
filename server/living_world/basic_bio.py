"""A short bio for NPCs Mantella knows nothing about. For an NPC with no bio in its list and no override, Mantella
writes one line ("You are a male Nord Whiterun Guard."); this swaps that line for a few grounded sentences from what
the game wrote to the NPC's file: race, sex, job, where they are, their hold and groups. Bios from Mantella's list
or the user's overrides never match the one-line pattern, so they are left alone."""
import re

HOLDS = {'Reach': 'the Reach', 'Pale': 'the Pale', 'Rift': 'the Rift'}
# class names that are a job; most classes are a fighting style, and mods rename them (a guard's can read "dremora")
JOB_CLASSES = {'blacksmith', 'merchant', 'farmer', 'miner', 'hunter', 'bard', 'priest', 'priestess', 'alchemist',
               'apothecary', 'lumberjack', 'beggar', 'innkeeper', 'fletcher', 'tailor', 'pawnbroker', 'monk'}


def stock_line(name: str) -> re.Pattern:
    """Mantella's line for an NPC it has no bio for (skyrim.py load_unnamed_npc); the race may be blank."""
    return re.compile(r'You are an? (male|female) +(?:[^\n.]*? +)?' + re.escape(name) + r'\.')


def _article(word: str) -> str:
    return ('an ' if word[:1].lower() in 'aeiou' else 'a ') + word


def _role(npc: dict) -> str:
    work = (npc.get('work') or '').strip()
    if work:
        return work
    if npc.get('guard'):
        return 'guard'
    cls = (npc.get('class') or '').strip().lower()
    return cls if cls in JOB_CLASSES else ''


def text(npc: dict) -> str:
    """The basic bio, in the second person like Mantella's own line; '' without enough to say."""
    name = (npc.get('name') or '').strip()
    if not name:
        return ''
    race = (npc.get('race') or '').strip()
    sex = npc.get('sex') if npc.get('sex') in ('male', 'female') else ''
    role = _role(npc)
    hold = (npc.get('hold') or '').strip()
    place = (npc.get('location') or '').strip()
    who = ' '.join(w for w in (sex, race, role) if w)
    lines = [f"You are {name}, {_article(who)}." if who else f"You are {name}."]
    hold_text = HOLDS.get(hold, hold)
    if hold and place and place.lower() not in hold.lower() and hold.lower() not in place.lower():
        lines.append(f"You are at {place}, in {hold_text}.")
    elif hold:
        lines.append(f"You live in {hold_text}.")
    elif place:
        lines.append(f"You are at {place}.")
    groups = [g for g in npc.get('groups') or [] if isinstance(g, str) and g]
    if groups:
        lines.append(f"You belong to the {' and the '.join(groups)}." if len(groups) < 3 else f"You belong to: {', '.join(groups)}.")
    plain = role or 'person'
    local = f" of {HOLDS.get(hold, hold)}" if hold else ''
    lines.append(f"Nothing more is written about you: be an ordinary {plain}{local}, with a modest life, local worries and "
                 "opinions that fit who you are. Invent only small, lore-friendly details and stay consistent with them.")
    return ' '.join(lines)


def replace(mantella_text: str, speakers: list[dict]) -> str:
    """Mantella's prompt with each speaker's one-line stock bio swapped for the basic bio."""
    out = mantella_text
    for npc in speakers:
        name = (npc.get('name') or '').strip()
        if not name:
            continue
        bio = text(npc)
        if bio:
            out = stock_line(name).sub(lambda m: bio, out, count=1)
    return out
