"""What the NPCs in the conversation know about the player's standing, from World's world.json: fame, bounty and the
quest outcomes that reached them (by hold, by group, or by name). One short block in the system prompt, the same
for the whole talk, so it stays in the cached part. Nothing without World."""

FAMOUS, KNOWN, HEARD = 7, 4, 1
WANTED = 1000          # a bounty everyone in the hold has heard of
MAX_EVENTS = 6
# Knowledge decides who has heard of the Dragonborn (and keeps it secret when asked to)
DRAGONBORN_EVENTS = ('mq104_dragonborn', 'mq105_greybeards')


def hold_text(hold: str) -> str:
    return 'the ' + hold if hold in ('Reach', 'Pale', 'Rift') else hold


def _number(table, hold) -> int:
    value = table.get(hold) if isinstance(table, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _reaches(event: dict, hold: str, groups: list, name: str) -> bool:
    holds = event.get('holds') or []
    return ('all' in holds or (hold and hold in holds)
            or any(g in groups for g in event.get('factions') or [])
            or (name and name in (event.get('named') or [])))


def known_items(speaker: dict, world: dict, player: str, skip_dragonborn: bool = False) -> list[str]:
    """What one NPC knows, as short sentences. The NPC's own hold (from the Hub's file channel), else where the talk is."""
    hold = speaker.get('hold') or world.get('hold') or ''
    groups = speaker.get('groups') if isinstance(speaker.get('groups'), list) else []
    items = []
    if hold:
        fame = _number(world.get('fame'), hold)
        if fame >= FAMOUS:
            items.append(f"{player} is famous all over {hold_text(hold)}.")
        elif fame >= KNOWN:
            items.append(f"{player} is well known in {hold_text(hold)}.")
        elif fame >= HEARD:
            items.append(f"{player}'s name has come up around {hold_text(hold)}.")
        bounty = _number(world.get('bounty'), hold)
        violent = _number(world.get('bounty_violent'), hold)
        if bounty and speaker.get('guard'):
            kind = ' for violent crimes' if violent else ''
            items.append(f"{player} has a bounty of {bounty} gold in {hold_text(hold)}{kind}.")
        elif bounty >= WANTED:
            items.append(f"{player} is wanted for crimes in {hold_text(hold)}.")
    events = world.get('events') if isinstance(world.get('events'), list) else []
    told = 0
    for event in events:
        if told >= MAX_EVENTS:
            break
        if not isinstance(event, dict) or not isinstance(event.get('text'), str):
            continue
        if skip_dragonborn and event.get('id') in DRAGONBORN_EVENTS:
            continue
        if _reaches(event, hold, groups, speaker.get('name', '')):
            items.append(event['text'].strip())
            told += 1
    return items


def text(speakers: list[dict], world: dict, player: str, skip_dragonborn: bool = False) -> str:
    """One block for everyone; when the speakers know different things, a block per speaker."""
    if not world or not speakers:
        return ''
    player = player or world.get('player') or 'The player'
    known = [(s.get('name', '?'), known_items(s, world, player, skip_dragonborn)) for s in speakers]
    known = [(name, items) for name, items in known if items]
    if not known:
        return ''
    if len(known) == len(speakers) and all(items == known[0][1] for _, items in known):
        title = f"What {known[0][0]} knows about {player}" if len(known) == 1 else f"What everyone here knows about {player}"
        return title + ':\n' + '\n'.join('- ' + i for i in known[0][1])
    return '\n\n'.join(f"What {name} knows about {player}:\n" + '\n'.join('- ' + i for i in items) for name, items in known)
