"""Asked-before notes: each NPC remembers which names (places, people, things) the player asked them about, counted
once per conversation. When the player brings one up again in a later conversation, one line tells the model so:
"(CHAD asked Camilla Valerius about Bleak Falls Barrow before; ... add something new ...)". Kept in the NPC's memory file under "asked"."""
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
             'reply', 'respond', 'say', 'speak', 'start', 'stay', 'use'}
MAX_COUNT = 99


def topics(text: str, exclude: set[str]) -> list[str]:
    """Names in the player's line, in order, without the people in the conversation."""
    text = re.sub(r'\([^)]*\)', ' ', text or '')
    skip = {w.lower() for name in exclude for w in [name, *name.split()] if w}
    out = []
    for m in _NAME.finditer(text):
        words = m.group(0).split()
        while words and words[0].lower() in _STARTERS:
            words.pop(0)
        while words and words[0].lower() in ('of', 'the'):
            words.pop(0)
        name = ' '.join(words)
        if not name or name.lower() in skip or name.lower() in _STARTERS:
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


class Tracker:
    """Knows which topics this conversation already counted. A conversation starts over when the message list gets
    shorter or the people change."""

    def __init__(self):
        self.people: tuple = ()
        self.length = 0
        self.seen: set[str] = set()

    def notes(self, messages: list[dict], people: list[tuple[str, str]], store, player: str) -> str:
        if store is None or not people:
            return ''
        key = tuple(people)
        if key != self.people or len(messages or []) < self.length:
            self.people, self.seen = key, set()
        self.length = len(messages or [])
        names = {name for name, _ in people} | {player}
        lines = []
        for topic in topics(_player_line(messages), names):
            if topic in self.seen:
                continue
            self.seen.add(topic)
            for name, ref_id in people:
                memory = store.load(name, ref_id)
                asked = memory.setdefault('asked', {})
                if asked.get(topic, 0) >= 1:
                    lines.append(f"({player} asked {name} about {topic} before; {name} already told them. Answer briefly, "
                                 f"in other words, and add something new if {name} knows more.)")
                asked[topic] = min(MAX_COUNT, asked.get(topic, 0) + 1)
                store.save(name, ref_id, memory)
        return '\n'.join(lines)
