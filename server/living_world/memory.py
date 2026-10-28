"""Each NPC's memory from their own point of view, replacing Mantella's summary files when the Hub is installed.

Memory = {recent: [Entry], long_term: {section: text}, feeling: str}; Entry = {day, hour, text, witnesses} or a
reference {day, hour, shared: id, witnesses} to a group talk stored once in shared/<id>.json. Dates come from the
game clock, never from the model. Talks under MIN_SUMMARY_MESSAGES lines get one line without a model call. The
summary itself goes through Mantella's own summary call, so it uses the player's chosen summary model.

Files: <conversations folder>/<world id>/living_world/<name> - <ref id>.json (+ shared/, legacy_backup/)."""
import glob
import hashlib
import json
import logging
import os
import re
import shutil
import time

logger = logging.getLogger('Mantella')

MIN_SUMMARY_MESSAGES = 5
MAX_RECENT = 30
FOLD_COUNT = 10
EARLIER_CHARS = 2400
DEFAULT_BUDGET = 1500
MAX_ENTRY_CHARS = 1200  # one memory entry; a model reply that isn't clean JSON is cut to this

SUMMARY_PROMPT = (
    "You keep the memories of {names} in {game}. Below is a conversation they just had with {player}.\n"
    "Write what they will remember, from their own point of view, in {language}: 2 to 4 sentences, facts and promises "
    "first, no dates or day numbers. Keep only what was actually said or done in this conversation; never add "
    "details nobody said (where something came from, names, reasons), and keep doubts as doubts. "
    "Then how each of them now feels about {player}, in a few words.\n"
    "Answer only with JSON: {{\"memory\": \"...\", \"feelings\": {{\"<name>\": \"...\"}}}}\n\n"
    "Who they are:\n{bios}")

# Talks among NPCs only (radiant): no player, so no feelings about them.
RADIANT_PROMPT = (
    "You keep the memories of {names} in {game}. Below is a conversation they just had among themselves.\n"
    "Write what they will remember, from their own point of view, in {language}: 2 to 4 sentences, facts and promises "
    "first, no dates or day numbers. Keep only what was actually said or done in this conversation; never add "
    "details nobody said, and keep doubts as doubts.\n"
    "Answer only with JSON: {{\"memory\": \"...\"}}\n\n"
    "Who they are:\n{bios}")


def empty() -> dict:
    return {'recent': [], 'long_term': {}, 'feeling': '', 'asked': {}}


def _int(value, default=-1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def clean(data) -> dict:
    """A memory dict with the expected shapes, whatever the file held (hand edits, old versions)."""
    memory = empty()
    if not isinstance(data, dict):
        return memory
    for entry in data.get('recent') if isinstance(data.get('recent'), list) else []:
        if not isinstance(entry, dict) or not isinstance(entry.get('text', entry.get('shared')), str):
            continue
        kept = dict(entry, day=_int(entry.get('day')), hour=_int(entry.get('hour')))
        if isinstance(kept.get('text'), str):
            kept['text'] = kept['text'][:MAX_ENTRY_CHARS]
        memory['recent'].append(kept)
    if isinstance(data.get('long_term'), dict):
        memory['long_term'] = {str(k): v for k, v in data['long_term'].items() if isinstance(v, str)}
    if isinstance(data.get('feeling'), str):
        memory['feeling'] = data['feeling']
    if isinstance(data.get('asked'), dict):
        memory['asked'] = data['asked']
    return memory


def file_name(name: str) -> str:
    """Like Mantella: a trailing number is dropped ("Whiterun Guard 2" is the same person as "Whiterun Guard")."""
    return re.sub(r'\s+\d+$', '', name.strip())


def tokens(text: str) -> int:
    return (len(text) + 3) // 4


def day_hour(game_days: float | None) -> tuple[int, int]:
    if game_days is None:
        return -1, -1
    days = int(game_days)
    return days, int(round((game_days - days) * 24)) % 24


def time_group(hour: int) -> str:
    if hour < 0:
        return ''
    if hour < 5:
        return 'at night'
    if hour < 12:
        return 'in the morning'
    if hour < 18:
        return 'in the afternoon'
    if hour < 22:
        return 'in the evening'
    return 'at night'


def header(day: int, hour: int) -> str:
    if day < 0:
        return ''
    twelve = hour - 12 if hour > 12 else (12 if hour == 0 else hour)
    return f"[Day {day}, {twelve} {time_group(hour)}]"


class MemoryStore:
    def __init__(self, conversations_dir: str, world_id: str):
        self.root = os.path.join(conversations_dir, world_id, 'living_world')
        self.legacy_root = os.path.join(conversations_dir, world_id)

    def _path(self, name: str, ref_id: str):
        from pathlib import Path
        return Path(self.root) / f"{file_name(name)} - {ref_id}.json"

    def load(self, name: str, ref_id: str) -> dict:
        path = self._path(name, ref_id)
        if path.exists():
            try:
                memory = clean(json.loads(path.read_text(encoding='utf-8-sig')))
                for entry in memory['recent']:
                    if 'shared' in entry:
                        entry['text'] = self.shared_text(entry['shared'])
                return memory
            except (OSError, ValueError):
                # kept aside, so the next save can't overwrite the only copy
                aside = path.with_name(f"{path.name}.unreadable-{time.strftime('%Y%m%d-%H%M%S')}")
                try:
                    shutil.copy2(path, aside)
                except OSError:
                    pass
                logger.warning(f"Living World: memory file for {name} could not be read; copied to {aside.name}, starting empty")
                return empty()
        return self.convert_legacy(name, ref_id)

    def save(self, name: str, ref_id: str, memory: dict) -> None:
        path = self._path(name, ref_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.tmp')
        stored = dict(memory, recent=[{k: v for k, v in e.items() if not ('shared' in e and k == 'text')} for e in memory['recent']])
        tmp.write_text(json.dumps(stored, ensure_ascii=False, indent=1), encoding='utf-8')
        tmp.replace(path)

    def save_shared(self, entry: dict) -> str:
        key = hashlib.sha1(json.dumps(entry, sort_keys=True).encode('utf-8')).hexdigest()[:16]
        folder = os.path.join(self.root, 'shared')
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, key + '.json'), 'w', encoding='utf-8') as f:
            json.dump(entry, f, ensure_ascii=False)
        return key

    def shared_text(self, key: str) -> str:
        try:
            with open(os.path.join(self.root, 'shared', key + '.json'), encoding='utf-8') as f:
                return json.load(f).get('text', '')
        except (OSError, ValueError):
            return ''

    def convert_legacy(self, name: str, ref_id: str) -> dict:
        """Mantella's own summary files become the 'earlier' section; they are copied to legacy_backup first and
        never changed."""
        base = file_name(name)
        files = []
        for folder in (f"{base} - {ref_id}", base):  # Mantella's folders: "<name> - <ref id>", older ones "<name>"
            files = glob.glob(os.path.join(glob.escape(self.legacy_root), glob.escape(folder), f"{glob.escape(base)}_summary_*.txt"))
            if files:
                break
        files.sort(key=lambda f: _int(''.join(re.findall(r'_summary_(\d+)', f)[-1:]), 0))  # _2 before _10
        if not files:
            return empty()
        backup = os.path.join(self.root, 'legacy_backup')
        os.makedirs(backup, exist_ok=True)
        texts = []
        for f in files:
            shutil.copy2(f, os.path.join(backup, os.path.basename(f) + '.bak'))
            try:
                with open(f, encoding='utf-8') as fh:
                    texts.append(fh.read().strip())
            except OSError:
                continue
        memory = empty()
        memory['long_term']['earlier'] = '\n'.join(t for t in texts if t)[-EARLIER_CHARS:]
        self.save(name, ref_id, memory)
        logger.info(f"Living World: converted {len(files)} Mantella summary file(s) for {name}")
        return memory


def entry_text(entry: dict, store: MemoryStore | None = None) -> str:
    if not entry.get('text') and 'shared' in entry and store is not None:
        return store.shared_text(entry['shared'])
    return entry.get('text', '')


def render(memory: dict, budget_tokens: int = DEFAULT_BUDGET, store: MemoryStore | None = None) -> str:
    """Newest entries first in, so cutting for the budget drops the oldest; printed oldest to newest."""
    tail = []
    if memory.get('feeling'):
        tail.append(f"How you feel now: {memory['feeling']}")
    head = [text for section, text in memory.get('long_term', {}).items() if text]
    used = tokens('\n'.join(tail))
    lines = []
    for entry in reversed(memory.get('recent', [])):
        text = entry_text(entry, store)
        if not text:
            continue
        line = f"{header(entry.get('day', -1), entry.get('hour', -1))} {text}".strip()
        if used + tokens(line) + 1 > budget_tokens:
            continue  # an entry too long for what is left; older, shorter ones may still fit
        lines.append(line)
        used += tokens(line) + 1
    kept_head = []
    for text in head:
        if used + tokens(text) + 1 > budget_tokens:
            text = text[-max(0, (budget_tokens - used - 1) * 4):] if budget_tokens - used > 20 else ''
        if text:
            kept_head.append(text)
            used += tokens(text) + 1
    return '\n'.join(kept_head + list(reversed(lines)) + tail)


def fold_old(memory: dict, store: MemoryStore | None = None) -> dict:
    """Keeps at most MAX_RECENT entries: the oldest FOLD_COUNT move into the 'earlier' section."""
    while len(memory['recent']) > MAX_RECENT:
        old, memory['recent'] = memory['recent'][:FOLD_COUNT], memory['recent'][FOLD_COUNT:]
        moved = '\n'.join(f"{header(e.get('day', -1), e.get('hour', -1))} {entry_text(e, store)}".strip() for e in old)
        earlier = (memory['long_term'].get('earlier', '') + '\n' + moved).strip()
        memory['long_term']['earlier'] = earlier[-EARLIER_CHARS:]
    return memory


def parse_summary(reply: str, names: list[str]) -> tuple[str, dict[str, str]]:
    text = (reply or '').strip()
    if text.startswith('```'):
        text = text.strip('`').split('\n', 1)[-1].rsplit('```', 1)[0].strip()
    start, end = text.find('{'), text.rfind('}')
    for candidate in (text, text[start:end + 1] if 0 <= start < end else ''):
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, dict) and isinstance(data.get('memory'), str):
            feelings = data.get('feelings') if isinstance(data.get('feelings'), dict) else {}
            return data['memory'].strip()[:MAX_ENTRY_CHARS], {k: str(v).strip() for k, v in feelings.items() if k in names}
    return text[:MAX_ENTRY_CHARS], {}


def one_line(talk: list[str], player: str) -> str:
    # Mantella messages are objects; an NPC's words are in its sentences (get_formatted_content), not in .text
    said = [str(line.get_formatted_content() if hasattr(line, 'get_formatted_content') else getattr(line, 'text', line)).strip()
            for line in talk]
    said = [s for s in said if s]
    return f"Spoke briefly with {player}: " + ' '.join(said)[:240]


def summarize(ctx: dict, store: MemoryStore) -> bool:
    """The 'summarize' hook: saves this conversation into each witness's memory. Always handles the save."""
    summaries = ctx['summaries']
    threads = summaries.get_threads_for_summarization(ctx['messages'], ctx['npcs_in_conversation'])
    wanted = {c.name: c for c in ctx['npcs_to_summarize']}
    threads = {name: p for name, p in threads.items() if name in wanted}
    player = ctx['npcs_in_conversation'].get_player_name() or 'the player'
    day, hour = day_hour(ctx.get('end_timestamp'))
    for group in summaries.group_shared_threads(threads):
        params = threads[group[0]]
        talk = params.messages.get_talk_only()
        if len(talk) < 2 and not ctx.get('is_radiant'):
            continue
        feelings = {}
        if len(params.messages) < MIN_SUMMARY_MESSAGES and not ctx.get('is_radiant'):
            text = one_line(talk, player)
        else:
            bios = '\n'.join(f"{c.name}: {getattr(c, 'bio', '')}" for c in params.characters)
            template = RADIANT_PROMPT if ctx.get('is_radiant') else SUMMARY_PROMPT
            prompt = template.format(names=', '.join(group), game='Skyrim', player=player,
                                     language=ctx.get('language', 'English'), bios=bios)
            text, feelings = parse_summary(summaries.summarize_conversation(params.messages.transform_to_dict_representation(talk), prompt), group)
        if not text:
            continue
        entry = {'day': day, 'hour': hour, 'text': text, 'witnesses': list(group)}
        if len(group) > 1:
            entry = {'day': day, 'hour': hour, 'shared': store.save_shared(entry), 'witnesses': list(group)}
        for name in group:
            npc = wanted[name]
            memory = store.load(name, npc.ref_id)
            memory['recent'].append(dict(entry))
            if feelings.get(name):
                memory['feeling'] = feelings[name]
            store.save(name, npc.ref_id, fold_old(memory, store))
    return True


def memory_text(text: str, ctx: dict, store: MemoryStore, budget_tokens: int = DEFAULT_BUDGET, budget_for=None) -> str:
    """The 'memory_text' hook: our memories in the prompt; Mantella's text for anyone we have nothing for.
    budget_for(character) -> tokens, when each NPC has their own limit (strangers remember less of the player)."""
    characters = ctx.get('characters') or []
    blocks = []
    for character in characters:
        memory = store.load(character.name, character.ref_id)
        budget = budget_for(character) if budget_for else budget_tokens
        body = render(memory, min(budget, budget_tokens) // max(1, len(characters)), store)
        if not body:
            continue
        if len(characters) > 1:
            body = (f"[This is the beginning of {character.name}'s memory. Only {character.name} knows what is in this block; "
                    f"the others here learn it only if {character.name} says it aloud.]\n{body}\n[This is the end of {character.name}'s memory]")
        blocks.append(body)
    if not blocks:
        return text
    return "Below is a summary of past events:\n" + '\n\n'.join(blocks)
