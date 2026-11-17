"""Each NPC's part of the prompt after their bio: Background (the facts history's current, visible lines) and Now (their
current situation as they believe it, bio_evolve.py). The order sent is Personality (bio) -> Background -> Now ->
Memories -> Commands; one shared rule line (prompt_rules) says the later part is the current truth.

The NPC's part must not change during a talk (it sits before the cache point after the NPC's fixed text), so it is built
once per talk and kept: the facts history is brought up to date then (a game-owned fact that changed since the last talk
marks the Now paragraph due, written after the talk), and anything written meanwhile (a Now paragraph, a forget's gap,
a page edit) is sent from the next talk on."""
import logging
import re
import threading
import time

from . import bio_evolve, characters, contracts, facts_history
from . import mod_facts

logger = logging.getLogger('Mantella')

TALK_IDLE_SECONDS = bio_evolve.TALK_IDLE_SECONDS
_lock = threading.Lock()
_talk = {'gen': 0, 'last': 0.0, 'root': None}
_frozen: dict = {}  # (talk gen, store root, npc key) -> the NPC's text for this talk


def touch(store=None, now: float | None = None) -> None:
    """A request of a talk is being built: a long quiet spell (Mantella closed) or another save starts a new talk."""
    now = time.time() if now is None else now
    root = getattr(store, 'root', None)
    with _lock:
        if (_talk['last'] and now - _talk['last'] > TALK_IDLE_SECONDS) or (root and _talk['root'] and root != _talk['root']):
            _new_talk()
        _talk['last'] = now
        if root:
            _talk['root'] = root


def talk_over() -> None:
    """The talk ended (its summary was saved): the next one builds every NPC's part anew."""
    with _lock:
        _new_talk()


def _new_talk() -> None:
    _talk['gen'] += 1
    _frozen.clear()


def _changes_text(changes: list[dict]) -> str:
    out = []
    for c in changes:
        label = facts_history.LABELS.get(c['fact'], c['fact'])
        if c['old'] and c['new']:
            out.append(f"{label} changed in the game: now \"{c['new']}\" (was \"{c['old']}\")")
        elif c['new']:
            out.append(f"{label} in the game: now \"{c['new']}\"")
        else:
            out.append(f"{label} in the game: \"{c['old']}\" no longer holds")
    return '; '.join(out)


def fact_memories(store, name: str, ref_id: str, changes: list[dict], player: str) -> list[str]:
    """A short dated memory for a change the game made between talks: a partner change with the player (flag 'bond')
    and the follower status (flag 'follower': only the first joining and the latest change stay flagged). Never raises."""
    from . import memory
    made = []
    try:
        for c in changes:
            old, new = str(c.get('old') or ''), str(c.get('new') or '')
            if c.get('fact') == 'partner':
                text, flag = (f"Became {new}." if new else f"Is no longer {old}."), 'bond'
            elif c.get('fact') == 'follower' and new.startswith('yes') and not old.startswith('yes'):
                text, flag = f"Started travelling with {player} as a companion.", 'follower'
            elif c.get('fact') == 'follower' and old.startswith('yes') and not new.startswith('yes'):
                text, flag = f"Stopped travelling with {player}.", 'follower'
            else:
                continue
            key = f"{flag}:{old}>{new}:{memory.lw_state.load_today()}"
            if memory.add_memory(store, name, ref_id, text, kind='relationship', key=key, flags={flag: True}):
                made.append(text)
        if any('companion' in t or 'Stopped travelling' in t for t in made):
            with store.lock(name, ref_id):
                mem = store.load(name, ref_id)
                memory.thin_flag(mem, 'follower', keep_first=True, keep_last=1)
                store.save(name, ref_id, mem)
    except Exception as e:
        logger.warning(f"Living World: {name}'s change could not be remembered ({e})")
    return made


def _people_ref(speaker: dict, people) -> tuple[str, str]:
    """The (name, ref id) Mantella files this speaker under (its Now file), matched by reference, else by name."""
    ref = facts_history.short_ref(speaker.get('ref_id'))
    name = str(speaker.get('name') or '')
    for n, r in people or []:
        if ref and facts_history.short_ref(r) == ref:
            return str(n), str(r)
    for n, r in people or []:
        if str(n) == name:
            return str(n), str(r)
    from .memory_ui import mantella_ref
    return name, mantella_ref(str(speaker.get('ref_id') or ''))


def npc_text(store, speaker: dict, people, player: str, world=None, chars=None, data=None, ties=None,
             bio_changes: bool = True, knows=None) -> str:
    """One NPC's Background and Now, as sent. knows(speaker) False: the NPC does not know who the hooded player is, so
    the mod fact lines say "the hooded stranger" (live test 14)."""
    name = str(speaker.get('name') or '').strip()
    if not name:
        return ''
    entry = characters.entry_for(name, speaker.get('race', ''), data=chars)
    mname, mref = _people_ref(speaker, people)
    state = bio_evolve.load(store, mname, mref) if store is not None else bio_evolve.empty()
    lines = facts_history.background_lines(store, speaker, player, entry, world, values=state['values'], data=data, ties=ties)
    stranger = knows is not None and not _safe_knows(knows, speaker)
    lines += mod_facts.npc_lines(speaker, HOODED_WORD if stranger else player)  # what other mods record (MLW_ModFacts)
    parts = []
    if lines:
        parts.append(f"Background facts about {name}:\n" + '\n'.join(lines))
    if bio_changes and store is not None:
        now = bio_evolve.now_text(store, mname, mref, state)
        if now:
            parts.append(now)
    return '\n'.join(parts)


HOODED_WORD = 'the hooded stranger'  # the player, to an NPC who does not know who is under the hood


def _safe_knows(knows, speaker) -> bool:
    try:
        return bool(knows(speaker))
    except Exception:
        return True


def text(store, speakers: list[dict], people, player: str, world=None, today=None, commands=None,
         bio_changes: bool = True, knows=None) -> str:
    """The Background and Now of every NPC in the talk, built once per talk (the first request brings the facts history
    up to date and marks Now paragraphs due where a game-owned fact changed)."""
    touch(store)
    speakers = [s for s in speakers or [] if str(s.get('name') or '').strip() and not facts_history.action_minor(s)]
    root = getattr(store, 'root', None)
    keys = [(_talk['gen'], root, bool(bio_changes), facts_history.npc_key(s.get('name'), s.get('ref_id'))) for s in speakers]
    missing = [s for s, k in zip(speakers, keys) if k not in _frozen]
    if missing:
        if store is not None:
            changed = facts_history.sync_talk(store, missing, player, today, commands)
            for s in missing:
                found = changed.get(facts_history.npc_key(s.get('name'), s.get('ref_id')))
                if found:
                    mname, mref = _people_ref(s, people)
                    bio_evolve.mark_due(store, mname, mref, _changes_text(found))
                    fact_memories(store, mname, mref, found, player)
        chars = characters.load()
        data = facts_history.load(store)
        ties = contracts.load_ties()
        for s, k in zip(speakers, keys):
            if k not in _frozen:
                try:
                    _frozen[k] = npc_text(store, s, people, player, world, chars, data, ties, bio_changes, knows)
                except Exception as e:
                    logger.warning(f"Living World: {s.get('name')}'s background could not be built ({e}); left out")
                    _frozen[k] = ''
    return '\n\n'.join(_frozen[k] for k in keys if _frozen.get(k))


def parts_of(text_: str, name: str) -> tuple[str, str]:
    """(Background, Now) of one NPC in the NPCs' part as sent (text()), for the token report; ('', '') when absent."""
    text_ = text_ or ''
    background = re.search(r'^Background facts about ' + re.escape(name) + r':\n(?:- .*(?:\n|$))*', text_, re.M)
    now = re.search(r'^Now, as ' + re.escape(name) + r' sees it: .*$', text_, re.M)
    return (background.group(0).strip() if background else ''), (now.group(0).strip() if now else '')


def frozen(store, key, build) -> str:
    """Any other text for the cached part of the prompt, built once per talk like the NPCs' part (build() -> str) and
    kept until the talk ends: the reputation line, which would otherwise change as game time passes during a talk.
    A failing build gives '' for this talk."""
    touch(store)
    k = (_talk['gen'], getattr(store, 'root', None), 'extra', key)
    if k not in _frozen:
        try:
            _frozen[k] = build() or ''
        except Exception as e:
            logger.warning(f"Living World: part of the prompt could not be built ({e}); left out")
            _frozen[k] = ''
    return _frozen[k]


def add_to_parts(ordered: dict, text_: str) -> dict:
    """After the bios: at the end of Mantella's background part (Personality, then Background, then Now)."""
    return bio_evolve.add_to_parts(ordered, text_)


def preview(store, name: str, ref_id: str, bio: str = '', speaker: dict | None = None, player: str = '',
            world=None) -> dict:
    """The prompt for one NPC, for the page: the exact text last sent when they were the only NPC in a talk
    (exact True), else built now in the order sent: Personality, Background and Now, Memories, Commands.
    {exact, sections: [(name, text)], text}."""
    from . import command, memory, preview as recorded
    last = recorded.last_for(name)
    if last:
        return {'exact': True, 'sections': last, 'text': '\n\n'.join(t for _, t in last)}
    player = player or 'the player'
    speaker = dict(speaker or {}, name=name, ref_id=(speaker or {}).get('ref_id') or ref_id)
    chars = characters.load()
    sections = [('Personality', (bio or '').strip())]
    sections.append(('Background and Now', npc_text(store, speaker, [(name, ref_id)], player, world, chars)))
    try:
        character = type('NPC', (), {'name': name, 'ref_id': ref_id, 'bio': bio})()
        mem = memory.memory_text('', {'characters': [character], 'player': player, 'recall': False}, store) if store is not None else ''
    except Exception as e:
        mem = f"(memories could not be read: {e})"
    sections.append(('Memories', mem))
    ref = lambda v: facts_history.short_ref(v) or None
    sections.append(('Commands', command.system_text(store, [speaker], player, ref) if store is not None else ''))
    sections = [(k, v) for k, v in sections if v]
    return {'exact': False, 'sections': sections, 'text': '\n\n'.join(v for _, v in sections)}


# --- recognition at the greeting (World's hood rule, known before the talk starts) ---------------------------------------

RECOGNITION_FILE = 'recognition.json'  # World (MLWW_Recognition) keeps int face_hidden there, written when gear changes
FAME_KNOWN = 3  # fame in the current hold at which a face under a hood is still known (as MLWW_Recognition)
UNCANNY = 4  # observation at which someone sees through a hood
KNOWN_TALKS = 3  # remembered talks with the player that make a face under a hood still known
UNRECOGNISED = re.compile(r'^\s*\(?\s*(.+?) does not recognise (.+?): a hood hides their face\.?\s*\)?\s*$')


def face_hidden() -> bool:
    """A hood or helmet covers the player's face now (World's recognition.json; False without World or the file)."""
    from . import lw_state
    value = contracts.game_flat(lw_state._read(RECOGNITION_FILE)).get('face_hidden')
    return isinstance(value, int) and not isinstance(value, bool) and value == 1


def hood_hides(world: dict | None) -> bool:
    """In a hold where the player is not famous and not Thane: a hood hides who they are. Outside any hold, or with no
    current world file, it hides nothing (as MLWW_Recognition)."""
    if not isinstance(world, dict) or not world:
        return False
    hold = world.get('hold')
    if not isinstance(hold, str) or not hold.strip():
        return False
    fame = next((v for k, v in (world.get('fame') or {}).items() if contracts.low(k) == contracts.low(hold)), 0) \
        if isinstance(world.get('fame'), dict) else 0
    thane = [contracts.low(t) for t in world.get('thane') or []] if isinstance(world.get('thane'), list) else []
    return not ((isinstance(fame, (int, float)) and fame >= FAME_KNOWN) or contracts.low(hold) in thane)


def knows_player(speaker: dict | None, commanded: bool = False, talks: int = 0) -> bool:
    """Knows the player personally, hood or not: a follower, housecarl or spouse, a friend or closer (rank 1+, close),
    someone under the player's absolute command, or someone with several remembered talks with the player."""
    s = speaker or {}
    num = lambda key: s.get(key) if isinstance(s.get(key), int) and not isinstance(s.get(key), bool) else 0
    return bool(commanded or talks >= KNOWN_TALKS or num('follower') > 0 or num('housecarl') > 0 or num('spouse') > 0
                or num('rank') >= 1 or num('close') > 0)


def recognition_text(people, speakers, player: str, knows, world=None, hidden=None) -> str:
    """With the player's face hidden in a hold where that hides it: one line per NPC here, for the greeting, as World says
    it after the greeting (does not recognise / sees through), and for those who know the player personally that they
    still do. people: Mantella's (name, ref id) of the talk; knows(name, ref id, speaker) -> bool. '' otherwise."""
    from . import lw_state
    if not (face_hidden() if hidden is None else hidden) or not hood_hides(lw_state.load_world() if world is None else world):
        return ''
    lines = []
    for name, ref in people or []:
        speaker = next((s for s in speakers or [] if facts_history.short_ref(s.get('ref_id')) and
                        facts_history.short_ref(s.get('ref_id')) == facts_history.short_ref(ref)), None) \
            or next((s for s in speakers or [] if s.get('name') == name), {})
        observation = speaker.get('observation') if isinstance(speaker.get('observation'), int) else 2
        if knows(name, ref, speaker):
            lines.append(f"({name} knows {player} well and recognises them, hood or not.)")
        elif observation >= UNCANNY:
            lines.append(f"({name} sees through {player}'s hood and knows who they are.)")
        else:
            lines.append(f"({name} does not recognise {HOODED_WORD}: a hood hides their face.)")
    strangers = [n for n, _ in people or [] if f"({n} does not recognise " in '\n'.join(lines)]
    if strangers:
        lines.append(stranger_line(strangers, player))
    return '\n'.join(lines)


def stranger_line(names, player: str) -> str:
    """Said with "does not recognise": the name in the prompt is not theirs to use (Mantella's own prompt always says
    who the player is)."""
    who = ' and '.join(names)
    # the player's name is never in a line for someone who does not know it (live test 15); Mantella's own prompt says
    # who the player is, so this line says plainly that the name is not theirs to use
    return (f"(To {who}, the player is {HOODED_WORD}: {who} does not know the player's name and never says it, and "
            f"has met them before only as the hooded stranger their memories may mention.)")


def fix_recognition_events(events, knows_name, player: str) -> list:
    """World's "X does not recognise <player>: a hood hides their face." for someone who knows the player personally
    (knows_name(name) -> bool) becomes "X knows <player> well and recognises them, hood or not.": knowing them wins over
    the hood. Other events pass unchanged. Never raises."""
    try:
        out = []
        for event in events or []:
            found = UNRECOGNISED.match(event) if isinstance(event, str) else None
            if found and knows_name(found.group(1).strip()):
                out.append(f"{found.group(1).strip()} knows {player} well and recognises them, hood or not.")
            elif found:  # World's line names the player (an older World does): never to someone who does not know him
                name = found.group(1).strip()
                out += [f"{name} does not recognise {HOODED_WORD}: a hood hides their face.",
                        stranger_line([name], player).strip('()')]
            else:
                out.append(event)
        return out
    except Exception:
        return events


# --- notes only for a marriage talk -----------------------------------------------------------------------------------

MARRIAGE_WORDS = re.compile(r'\b(marr(y|ies|ied|iage|ying)|wed(s|ded|ding)?|propos(e|es|ed|al|ing)|spouse|husband|wife|'
                            r'engage(d|ment)?|amulet of mara)\b', re.I)


def marriage_text(messages, speakers) -> str:
    """Relationships' "marriage_note" for each NPC here (why M.A.R.A.S cannot marry them), only when the player's newest
    message speaks of marrying or proposing; '' otherwise, so the note is not noise in every talk."""
    newest = next((m.get('content') for m in reversed(messages or []) if isinstance(m, dict) and m.get('role') == 'user'), '')
    if isinstance(newest, list):
        newest = ' '.join(p.get('text', '') for p in newest if isinstance(p, dict) and isinstance(p.get('text'), str))
    if not isinstance(newest, str) or not MARRIAGE_WORDS.search(newest):
        return ''
    notes = [s.get('marriage_note').strip() for s in speakers or []
             if isinstance(s.get('marriage_note'), str) and s.get('marriage_note').strip()]
    return '\n'.join(f"({n})" for n in notes)


# --- outfit changes: one line per burst ------------------------------------------------------------------------------

ITEM_EVENT = re.compile(r"\(?([^()\n]{1,80}?) (equipped|unequipped|dropped/gave|picked up/took) ([^\n]{1,160}?)\)?")
MAX_ITEM_EVENT = 300  # longer lines are no item event (and a regex on a huge line must stay cheap)


def _item_event(event):
    text = event.strip() if isinstance(event, str) else ''
    return ITEM_EVENT.fullmatch(text) if 0 < len(text) <= MAX_ITEM_EVENT else None
OUTFIT_BURST = 4  # item lines (equip, unequip, drop) of one person in one batch from which it is an outfit change
MAX_WORN_NAMED = 3
# a weapon is drawn, not worn: a newly drawn one keeps its own line beside the outfit change
WEAPON = re.compile(r"\b(?:dagger|sword|greatsword|claymore|katana|blade|rapier|scimitar|knife|axe|battleaxe|waraxe|"
                    r"mace|warhammer|hammer|bow|crossbow|staff|wand|spear|halberd|pike|shield|whip)s?\b", re.I)


def collapse_outfit_events(events) -> list:
    """Mantella's item events for one person in one batch ("nyri equipped ...", "nyri unequipped ...", "nyri dropped/gave
    ..."): from OUTFIT_BURST such lines on (equip, unequip and drop lines all count; the name in any case), they are one
    outfit change (live tests 6 and 7: about thirty lines for one follower's outfit swaps by Nether's Follower
    Framework) and become one short line, where the first of them was: "nyri changed outfit, now wearing A, B and C."
    It names only what was newly put on (an item taken off and put back on did not change); a newly drawn weapon keeps
    its own line ("nyri equipped Glass Dagger"). What they picked up stays, unless it was only part of the swap. A
    single meaningful equip stays as it is. Other events pass unchanged. Never raises."""
    try:
        found = [(i, _item_event(e)) for i, e in enumerate(events or [])]
        key = lambda m: m.group(1).strip().casefold()
        counts: dict = {}
        for i, m in found:
            if m and m.group(2) != 'picked up/took':
                counts[key(m)] = counts.get(key(m), 0) + 1
        bursts = {who for who, n in counts.items() if n >= OUTFIT_BURST}
        if not bursts:
            return events
        worn: dict = {who: {} for who in bursts}   # item -> worn at the end of the batch
        before: dict = {who: {} for who in bursts}  # item -> worn before the batch (its first equip line took it off)
        touched: dict = {who: set() for who in bursts}
        shown: dict = {}
        for i, m in found:
            if m and key(m) in bursts and m.group(2) != 'picked up/took':
                who, item = key(m), m.group(3).strip()
                shown.setdefault(who, m.group(1).strip())
                touched[who].add(item.lower())
                if m.group(2) in ('equipped', 'unequipped'):
                    before[who].setdefault(item, m.group(2) == 'unequipped')
                if m.group(2) == 'equipped':
                    worn[who][item] = True
                else:
                    worn[who].pop(item, None)
        out, done, folded = [], set(), {}
        for i, m in found:
            who = key(m) if m else ''
            if who not in bursts:
                out.append(events[i])
                continue
            if m.group(2) == 'picked up/took' and m.group(3).strip().lower() not in touched[who]:
                out.append(events[i])
                continue
            folded[who] = folded.get(who, 0) + 1
            if who in done:
                continue
            done.add(who)
            new = [item for item in worn[who] if not before[who].get(item)]
            names = [item for item in new if not WEAPON.search(item)]
            if names:
                listed = names[:MAX_WORN_NAMED]
                more = f" and {len(names) - len(listed)} more" if len(names) > len(listed) else ''
                text = ', '.join(listed) if more else listed[0] if len(listed) == 1 else                     ', '.join(listed[:-1]) + ' and ' + listed[-1]
                out.append(f"{shown[who]} changed outfit, now wearing {text}{more}.")
            else:
                out.append(f"{shown[who]} changed outfit.")
            out += [f"{shown[who]} equipped {item}" for item in new if WEAPON.search(item)]
        for who, n in folded.items():
            logger.log(23, f"Living World: {n} outfit lines of {shown.get(who, who)} sent as one")
        return out
    except Exception:
        return events
