"""Requests for a silent rating action, taken out of the in-game events and given as one note for the actions instead.

Arousal asks for an NPC's appetite rating, and OStim Expansion for their favourite positions, with an event line:
"Lydia's sexual appetite has not been rated yet. Give the rating only as the number in the RateAppetite action: ...".
As an event in parentheses it reads as something that happened in the scene, which Mantella's own rules say to react
to, and it comes in the same newest message as the player's words, so the model answers both (live test 10: asked to
lend 30 gold, the reply spoken was "I'll rate her appetite silently and hand over the gold."; live test 5: "I'm rating
her appetite quietly as a succubus, very high."; "never say this" wording in the line and the action did not stop it).

The Hub takes such lines out of the events (dialogue_events hook) and adds one note after the player's words for that
one reply (extra_user_text hook): not part of the scene, not to be answered; the rating goes only in the action; the
spoken reply answers the player and never mentions a rating, an action or what the speaker is about to do. The note is
never kept in the talk's history. Without the Hub (or with a Direct AI Connect too old for the events hook) the line
stays an event, as before; a line naming no action is left alone."""
import logging
import re
import threading

_LINE = re.compile(r"^\(?\s*(?P<who>[^()\n]+?)'s (?P<what>[^.()\n]+?) (?P<verb>has|have) not been rated yet\.(?P<rest>.*)$",
                   re.I | re.S)
_ACTION = re.compile(r"\bin the ([A-Z][A-Za-z]+) action\b")
_lock = threading.Lock()
_pending: list[tuple[str, str, str, str]] = []  # (who, what, has/have, action) waiting for the next reply


def take(events) -> list:
    """The events without the rating requests (kept for the next reply's note); anything else unchanged."""
    if not isinstance(events, list):
        return events
    keep, found = [], []
    for event in events:
        m = _LINE.match(event.strip()) if isinstance(event, str) else None
        action = _ACTION.search(m.group('rest')) if m else None
        if not action:
            keep.append(event)
            continue
        found.append((m.group('who').strip(), m.group('what').strip(), m.group('verb').lower(), action.group(1)))
    for who, what, _, action in found:  # Mantella's "Received in-game events" line is written before this hook runs
        logging.getLogger('Mantella').info(f"Living World: rating request for {who} sent as an action note ({action})")
    if found:
        with _lock:
            for item in found:
                if item not in _pending:
                    _pending.append(item)
    return keep


def note(player: str = '') -> str:
    """The note for this reply ('' when nothing waits); each request goes with one reply only."""
    with _lock:
        items = list(_pending)
        _pending.clear()
    if not items:
        return ''
    asks = ' '.join(f"{who}'s {what} {verb} not been rated yet: give it only in the {action} action." for who, what, verb, action in items)
    return (f"Action note, not part of the scene and not something to answer: {asks} The spoken reply answers "
            f"{player or 'the player'}'s words as the character would; it never mentions a rating, an action, this note "
            f"or what the speaker is about to do.")


def clear() -> None:
    """A talk ended: a request no reply took is not carried into the next talk (the game asks again)."""
    with _lock:
        _pending.clear()
