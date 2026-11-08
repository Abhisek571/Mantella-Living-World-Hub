"""Asked-before notes: each NPC remembers which names (places, people, things) the player asked them about, counted
once per conversation. When the player brings one up again in a later conversation, one line tells the model so:
"(Player brought up Bleak Falls Barrow with Camilla Valerius before; add something new ...)". Kept in the NPC's memory
file under "asked" (count per topic, newest last, at most MAX_TOPICS) and "asked_day" (the game day it last came up)."""
import re

# Capitalized words, joined by "of" / "the" (Jarl of Whiterun, Bleak Falls Barrow).
_NAME = re.compile(r"[A-Z][\w'-]+(?:\s+(?:of\s+|the\s+)?[A-Z][\w'-]+)*")
# Words that are capitalized only because they start a sentence.
_STARTERS = {'a', 'about', 'again', 'also', 'and', 'any', 'are', 'but', 'can', 'could', 'did', 'do', 'does', 'have',
             'hello', 'hey', 'hi', 'how', 'i', 'is', 'let', 'my', 'no', 'now', 'ok', 'okay', 'please', 'so', 'tell',
             'that', 'the', 'then', 'there', 'this', 'we', 'well', 'what', 'when', 'where', 'who', 'why', 'will',
             'would', 'yes', 'you', 'your',
             # instruction words in Mantella's own opening and event lines
             'answer', 'begin', 'continue', 'describe', 'ensure', 'greet', 'keep', 'make', 'note', 'remember',
             'reply', 'respond', 'say', 'speak', 'start', 'stay', 'use',
             # greetings, thanks and fillers that open a line
             'goodbye', 'farewell', 'bye', 'thanks', 'thank', 'sorry', 'greetings', 'honestly', 'maybe', 'perhaps',
             'interesting', 'indeed', 'aye', 'oh', 'ah', 'gods', 'divines', 'sure', 'listen', 'right', 'fine', 'good',
             'great', 'nice', 'come', 'look', 'wait', 'stop', 'go', 'later', 'anyway', 'actually', 'alright'}
MAX_COUNT = 99
MAX_TOPICS = 100  # topics kept per NPC; the oldest go first
_OPENERS = '.!?:;"*-“\''


def _sentence_start(text: str, at: int) -> bool:
    before = text[:at].rstrip()
    return not before or before[-1] in _OPENERS


def _mid_sentence(text: str, word: str) -> bool:
    return any(not _sentence_start(text, m.start()) for m in re.finditer(r'\b' + re.escape(word) + r'\b', text))


def topics(text: str, exclude: set[str]) -> list[str]:
    """Names in the player's line, in order, without the people in the conversation."""
    text = re.sub(r'\([^)]*\)', ' ', text or '')
    skip = {w.lower() for name in exclude for w in [name, *name.split()] if w}
    out = []
    for m in _NAME.finditer(text):
        words = m.group(0).split()
        popped = False
        while words and words[0].lower() in _STARTERS:
            words.pop(0)
            popped = True
        while words and words[0].lower() in ('of', 'the'):
            words.pop(0)
            popped = True
        name = ' '.join(words)
        if not name or name.lower() in skip or name.lower() in _STARTERS or "'" in name:
            continue
        # one capitalized word opening a sentence ("Honestly", "Gods") is a name only if it is also capitalized
        # somewhere in the middle of a sentence
        if len(words) == 1 and not popped and _sentence_start(text, m.start()) and not _mid_sentence(text, name):
            continue
        if name not in out:
            out.append(name)
    return out


def _player_line(messages: list[dict]) -> str:
    for message in reversed(messages or []):
        if message.get('role') != 'user':
            continue
        content = message.get('content')
        if isinstance(content, list):
            content = ' '.join(p.get('text', '') for p in content if isinstance(p, dict) and p.get('type') == 'text')
        return content or ''
    return ''


def _count(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _answering(messages: list[dict], people: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """In a group: the NPC whose reply came just before the player's line, when it starts with their name
    ("Lydia: ..."); everyone when that is not known."""
    if len(people) < 2:
        return people
    seen_user = False
    for message in reversed(messages or []):
        if message.get('role') == 'user':
            seen_user = True
        elif seen_user and message.get('role') == 'assistant':
            content = message.get('content')
            speaker = content.split(':', 1)[0].strip() if isinstance(content, str) and ':' in content[:60] else ''
            return [p for p in people if p[0] == speaker] or people
    return people


class Tracker:
    """Knows which topics this conversation already counted. A conversation starts over when the message list gets
    shorter or the people change."""

    def __init__(self):
        self.people: tuple = ()
        self.length = 0
        self.seen: set[str] = set()

    def notes(self, messages: list[dict], people: list[tuple[str, str]], store, player: str, today: int | None = None) -> str:
        """today: the game day; a topic stamped with a later day (an earlier save was loaded) counts as new."""
        if store is None or not people:
            return ''
        key = tuple(people)
        if key != self.people or len(messages or []) < self.length:
            self.people, self.seen = key, set()
        self.length = len(messages or [])
        names = {name for name, _ in people} | {player}
        new = [t for t in topics(_player_line(messages), names) if t not in self.seen]
        if not new:
            return ''
        self.seen.update(new)
        lines = []
        for name, ref_id in _answering(messages, people):
            memory = store.load(name, ref_id)
            asked = memory.setdefault('asked', {})
            days = memory.setdefault('asked_day', {})
            for topic in new:
                count = _count(asked.get(topic))
                if today is not None and _count(days.get(topic), -1) > today:
                    count = 0  # stamped on a day this save has not reached
                if count >= 1:
                    lines.append(f"({player} brought up {topic} with {name} before; add something new if {name} knows more, or say so.)")
                asked.pop(topic, None)  # re-added last, so the newest stay when the list is trimmed
                asked[topic] = min(MAX_COUNT, count + 1)
                if today is not None:
                    days[topic] = today
            for old in list(asked)[:max(0, len(asked) - MAX_TOPICS)]:
                asked.pop(old, None)
                days.pop(old, None)
            store.save(name, ref_id, memory)  # once per NPC per reply
        return '\n'.join(lines)
