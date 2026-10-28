"""Order of the system prompt sent to the model: the Living World rules first, then Mantella's own text (character,
memories, scene). The cache point goes after everything that stays the same for the whole conversation.

Stock bios end with a long block of example lines ("Example conversations/dialogue ..."), often most of the bio;
a few lines give the voice, the rest only costs tokens on every reply."""
import re

# "Example Camilla conversations/dialogue [...]", "Example Dialogue", "Speech Pattern Examples:", "Bandit dialogue
# examples [...]", anything with "avoid parroting"
EXAMPLES_HEADER = re.compile(r'^.*(?:\bexamples?\b.*\b(?:dialogue|conversations?|speech)\b|\b(?:dialogue|conversations?|speech)\b.*\bexamples?\b'
                             r'|avoid parroting).*$', re.I | re.M)
SECTION = re.compile(r'\n(?=# )')


def trim_examples(text: str, keep: int) -> str:
    """Keeps the header and the first `keep` example lines of each examples block (keep 0 drops the block)."""
    out, pos = [], 0
    for match in EXAMPLES_HEADER.finditer(text):
        if match.start() < pos:
            continue
        end_match = SECTION.search(text, match.end())
        end = end_match.start() if end_match else len(text)
        lines = [l for l in text[match.end():end].splitlines() if l.strip()]
        kept = lines[:keep]
        out.append(text[pos:match.start()])
        if kept:
            out.append(match.group(0) + '\n' + '\n'.join(kept) + ('\n' if end_match else ''))
        pos = end
    out.append(text[pos:])
    return ''.join(out)


# Stable first: what is the same for every NPC (rules, common knowledge), then this NPC's fixed text (looks, bio,
# identity, what they know), then what changes between talks (memory). The scene (time, weather, location) changes
# inside a talk, so it goes into the newest message instead (scene_text); the system prompt then stays cached.
ORDER = ['prompt_rules', 'mantella_rules', 'common_knowledge', 'overview', 'background', 'identity', 'knows', 'jobs', 'history', 'respond']
STABLE_END = ['overview', 'background', 'identity', 'knows', 'jobs']
HEADERS = {'overview': 'overview', 'background': 'background', 'history': 'history', 'current scene': 'scene',
           'rules': 'mantella_rules', 'response format': 'mantella_rules'}


def sections(text: str) -> dict[str, str]:
    """Mantella's prompt cut at its '# ' headers: {part: text}; Rules and Response Format stay together, the final
    'Respond as ...' line becomes 'respond'. Unknown headers keep their own part ('section_<name>')."""
    out: dict[str, str] = {}
    for chunk in re.split(r'\n(?=# )', text.strip()):
        head = chunk.split('\n', 1)[0]
        name = HEADERS.get(head[2:].strip().lower()) if head.startswith('# ') else 'preamble'
        if name is None:
            name = 'section_' + re.sub(r'\W+', '_', head[2:].strip().lower())
        out[name] = (out[name] + '\n\n' + chunk) if name in out else chunk
    if out:
        last = next(reversed(out))
        lines = out[last].rstrip().split('\n')
        if lines and lines[-1].startswith('Respond '):
            out['respond'] = lines[-1].strip()
            out[last] = '\n'.join(lines[:-1]).rstrip()
    return {k: v for k, v in out.items() if v.strip()}


def scene_text(text: str) -> str:
    """The body of Mantella's '# Current Scene' section, for the newest message."""
    scene = sections(text).get('scene', '')
    return scene.split('\n', 1)[1].strip() if '\n' in scene else ''


def order_system(parts: dict[str, str], rules: str, keep_examples: int | None = None) -> dict[str, str]:
    """keep_examples: bio example lines kept per examples block (None keeps them all)."""
    mantella = parts.get('mantella', '')
    split = sections(mantella)
    ordered = {k: v for k, v in parts.items() if k != 'mantella' and not k.startswith('__')}
    if rules:
        ordered['prompt_rules'] = rules
    if 'background' not in split and 'overview' not in split:  # not Mantella's usual layout: keep it whole
        ordered['mantella'] = trim_examples(mantella, keep_examples) if keep_examples is not None else mantella
        ordered['__order__'] = ['prompt_rules', 'mantella']
        ordered['__breakpoints_after__'] = ['mantella']
        return ordered
    split.pop('scene', None)
    if keep_examples is not None and 'background' in split:
        split['background'] = trim_examples(split['background'], keep_examples)
    ordered.update(split)
    extra = [k for k in split if k not in ORDER]  # preamble, unknown sections: with the character's fixed text
    i = ORDER.index('history')
    ordered['__order__'] = ORDER[:i] + extra + ORDER[i:]
    ordered['__breakpoints_after__'] = [STABLE_END + extra, 'respond']
    return ordered
