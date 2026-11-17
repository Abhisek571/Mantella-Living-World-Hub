"""Mantella Living World: the Integration Hub's side inside Mantella, loaded by Mantella - Direct AI Connect."""
import logging
import os
import re
import time
from collections import Counter

from . import action_filter, asked_before, basic_bio, battle, embed, layout, lw_state, memory, nearby, preview, prompt_rules, server_status, settings, stage_timing, ui_overrides, ui_tab, update_check, world_note
from . import bio_evolve, bio_optimise, events as custom_events
from . import command
from . import console
from . import characters
from . import memory_ui
from . import intimacy
from . import trade
from . import facts_history, npc_block, release
from . import news, reputation, strangeness, timeline
from . import action_args
from . import silent_requests
from . import menu_dialogue

_logged_rules = {'text': None}
_last_store: dict = {'store': None, 'people': [], 'game': None}
_asked = asked_before.Tracker()


def _speaker_names() -> list[str]:
    return [s.get('name', '?') for s in lw_state.load_conversation()]


def _gates() -> dict:
    """The action files' gates plus the settings' own (stock Mantella actions carry none)."""
    return action_filter.with_settings(action_filter.load_gates(), settings.load()['action_gates'])


def _installed() -> set[str]:
    """The Living World modules installed in this profile (from their action files and rule files), for the fact owner
    check."""
    return set(ui_tab.installed_modules())


def child_line(speakers: list[dict]) -> str:
    """With a child in a group talk: one line so nothing adult is said in front of them. A speaker whose age the game has
    not confirmed yet (action_filter.adult) gets the same caution, without being called a child."""
    children = [s.get('name', '?') for s in speakers if action_filter._int(s.get('minor'), 0) > 0]
    if len(speakers) < 2:
        return ''
    if not children:
        if all(action_filter.adult(s) for s in speakers):
            return ''
        return "(Not everyone's age here is known yet: nothing sexual or romantic is said, done or hinted at.)"
    return (f"(A child, {', '.join(children)}, is in this conversation: nothing sexual or romantic is said, done or "
            f"hinted at.)")


def _npc_state(character, speakers: list[dict] | None = None) -> dict:
    """A Mantella character's state from the game side: the conversation's speaker with their reference id or name
    first, else the npc file of their base id."""
    ref = _ref(getattr(character, 'ref_id', None))
    for s in speakers or []:
        if (ref is not None and _ref(s.get('ref_id')) == ref) or s.get('name') == getattr(character, 'name', None):
            return s
    return lw_state.load_npc(str(getattr(character, 'base_id', '') or ''))


def _is_minor(character, speakers: list[dict] | None = None) -> bool:
    """A Mantella character is a child by the game side's file (_npc_state), or not yet confirmed as an adult there (no
    file, a broken one, no minor key): treated as a child until the game has written it."""
    return not action_filter.adult(_npc_state(character, speakers))


def _share_adult(name: str, ref_id) -> bool:
    """A ShareConversation recipient (absent from the talk) the game confirmed as an adult: their npc file, found by
    reference id (and name), says minor 0. No file found means not known as an adult (fail closed)."""
    ref = _ref(ref_id)
    if ref is None:
        return False
    try:
        files = os.listdir(os.path.join(lw_state.DATA_DIR, 'npc'))
    except OSError:
        return False
    for file in files:
        if not file.lower().endswith('.json'):
            continue
        npc = lw_state.load_npc(file[:-5])
        if npc and _ref(npc.get('ref_id')) == ref and lw_state._same_name(npc.get('name'), name):
            return action_filter.adult(npc)
    return False


def _start_memory_model(values) -> None:
    """Meaning search for old memories: the model shipped with the Hub (data/embed) or downloaded once into Mantella's
    user folder. Only loaded while recall is on."""
    if not values['memory_recall'] or embed.status() != 'off':
        return
    here = os.path.dirname(os.path.abspath(__file__))
    embed.configure([os.path.join(here, 'data', 'embed'), os.path.join(ui_overrides.user_folder(), 'data', 'living_world_models')],
                    values['memory_model_download'])
    embed.start()


def _recall_extra(character) -> str:
    """What was just said nearby and why an ambient talk started: part of what old memories are matched against."""
    try:
        return '\n'.join(t for t in (nearby.seed(lw_state.load_banter()), nearby.said_nearby(lw_state.load_said_nearby(), time.time())) if t)
    except Exception:
        return ''


def _action_speakers() -> list[dict]:
    """The speakers as the action filter sees them: the Intimacy setting and the Characters page flags
    (characters.for_actions), then an NPC with an absolute command in force counts as close and intimate
    (command.unlocked), then Intimacy: never and the child checks, which nothing overrides (characters.final_limits)."""
    speakers = lw_state.load_conversation()
    try:
        speakers = characters.for_actions(speakers, characters.intimacy_mode(settings.load()))
    except Exception as e:
        logging.getLogger('Mantella').warning(f"Living World: the Characters page flags could not be checked for actions ({e})")
    try:
        speakers = command.unlocked(_last_store['store'], speakers, _ref, command.current_time(lw_state.load_today()))
    except Exception as e:
        logging.getLogger('Mantella').warning(f"Living World: absolute commands could not be checked for actions ({e})")
    return characters.final_limits(speakers)


def _known_for(player: str):
    """known_for(speaker) -> how long they have known the player, from their memories ('' when unknown)."""
    store, today = _last_store['store'], lw_state.load_today()
    people = _last_store['people']

    def known_for(speaker):
        if store is None:
            return ''
        ref = next((r for n, r in people if n == speaker.get('name')), None)
        if ref is None:
            return ''
        # only memories still in mind and of the loaded save's timeline (as _knows_player counts them)
        branch = timeline.current(store)
        usable = [e for e in memory._peek(store, speaker['name'], ref).get('recent', [])
                  if not e.get('hidden') and timeline.usable(branch, e)]
        talks = memory._player_talks({'recent': usable})
        days = [e.get('day') for e in usable
                if not e.get('radiant') and not e.get('battle') and isinstance(e.get('day'), int) and e['day'] >= 0]
        return intimacy.known_text(talks, min(days) if days else None, today, player)
    return known_for


def _intimacy(ctx) -> str:
    """Intimacy, the NPC decides (intimacy.line): facts and their own choice for each NPC here, instead of a verdict."""
    if not settings.load()['action_filter'] or 'OStim Expansion' not in _installed():
        return ''
    player = lw_state.load_player_name() or 'the player'
    gates = _gates()
    speakers = _action_speakers()
    locked = _action_lock['names'] if _action_lock['key'] == _action_key() else None
    if locked is not None and intimacy.SCENE_ACTION not in locked and             action_filter.filter_actions([{'function': {'name': intimacy.SCENE_ACTION}}], speakers, gates):
        # allowed now but locked out until the next talk (_locked_actions): no line inviting a choice it cannot make
        gates = {k: v for k, v in gates.items() if k != intimacy.SCENE_ACTION}
    return intimacy.line(speakers, gates, player, characters.intimacy_mode(settings.load()), _known_for(player))


def _server_actions(tools, ctx):
    """Actions the server builds itself for this reply (Direct AI Connect's server_actions hook): the Console action on
    a wish's turn, from one helper call with the summary model."""
    summaries = _last_store.get('summaries')
    ask = (lambda prompt, text: summaries.summarize_conversation(text, prompt)) if summaries is not None else None
    return console.server_actions(tools, ctx, _last_store['store'], ask)


GREETING_WAIT = 1.0  # seconds a talk's first request waits for the game to write a new NPC's minor flag, at most


def _await_npc_files(ctx) -> None:
    """At a talk's first request (no NPC reply yet) a newly met NPC's file can still be on its way: the game writes a
    small part at once (minor, carry_gold, nff, name, ref id) and the rest 9 to 11 seconds later, after the greeting
    has come back (diag 2026-11-15). Only the minor flag is waited for (at most GREETING_WAIT): without it nothing adult
    can be offered at all. Every other missing value reads as its safe, likely one (action_filter: no scene, not close,
    not intimate, not a follower), so a first-ever meeting may cost one cache rewrite when the rest arrives; an NPC
    whose file is already on disk (any later talk, in any session) is not waited for at all. Direct AI Connect's keyword
    question (which "Name:" keywords may fire) carries no messages and is never the first request: it never waits."""
    if (ctx or {}).get('keyword_actions') or             any(isinstance(m, dict) and m.get('role') == 'assistant' for m in (ctx or {}).get('messages') or []):
        return
    known = lambda s: isinstance(s.get('minor'), int) and not isinstance(s.get('minor'), bool)
    start = time.time()
    while not all(known(s) for s in lw_state.load_conversation()) and time.time() < start + GREETING_WAIT:
        time.sleep(0.05)


def _filter_tools(tools, ctx):
    tools, console_tools = console.split(tools, ctx, _last_store['store'])  # the Console action: only on its one turn
    try:  # a command given or released just now changes the actions on this same request, with the prompt (one cache miss)
        _commands(newest=False)
    except Exception as e:
        logging.getLogger('Mantella').warning(f"Living World: absolute commands could not be read before the actions ({e})")
    try:
        _await_npc_files(ctx)
    except Exception:
        pass
    try:
        values = settings.load()
        gates = _gates()
        if values['action_filter']:
            tools = action_filter.filter_actions(tools, _action_speakers(), gates)
        if values['short_actions']:
            tools = action_filter.shorten(tools, gates)
        tools = _locked_actions(tools)
        # the reply right after a custom event: nothing is handed over again for what already happened
        tools = custom_events.filter_tools(tools, (ctx or {}).get('messages'))
        if not (ctx or {}).get('keyword_actions'):  # Direct AI Connect also asks which "Name:" keywords may fire
            preview.record_tools(len(tools), _speaker_names())
            _offered['names'] = {_tool_name(t) for t in tools}
        return tools + console_tools
    except Exception as e:  # an error here would hand Mantella back every action, gated ones included: fail closed
        logging.getLogger('Mantella').warning(f"Living World: the action filter failed ({e}); only ungated actions are offered")
        try:
            return action_filter.filter_actions(tools, [], action_filter.with_settings(action_filter.load_gates(), settings.DEFAULTS['action_gates']))
        except Exception:
            return []


_action_lock: dict = {'key': None, 'names': None}  # the actions offered at this talk's first request
_offered: dict = {'names': None}  # the actions of the newest request (Direct AI Connect filters them before the extra text)


def _action_key() -> tuple:
    """What the action list is locked for: this talk (npc_block's generation), the NPCs in it, the absolute commands in
    force and the player's own choices (the action filter and Intimacy settings, the Characters page): a command given
    or released, or a setting changed, during the talk changes the actions at once, as before (one cache miss)."""
    store = _last_store['store']
    npc_block.touch(store)  # a long quiet spell or another save starts a new talk here too, not only in the prompt
    values = settings.load()
    speakers = tuple(sorted(str(s.get('base_id') or s.get('name') or '') for s in lw_state.load_conversation()))
    commands = tuple(sorted(c['id'] for c in command.load(store)['commands'] if c.get('status') in command.IN_FORCE))         if store is not None else ()
    return (npc_block._talk['gen'], getattr(store, 'root', None), speakers, commands, values['action_filter'],
            characters.intimacy_mode(values), _file_stamp(characters.PATH))


def _tool_name(tool) -> str:
    return str(((tool or {}).get('function') or {}).get('name') or (tool or {}).get('name') or '')


def _locked_actions(tools: list) -> list:
    """The action list stays as it was at the talk's greeting, so the greeting and every reply send the same actions
    (one cached prefix; live tests: a new NPC's file arriving after the greeting added actions at the first reply and
    rewrote the whole cache). An action allowed only later (a just-met NPC's file arriving late) waits for the next
    talk. An action the filter takes away (a child joins, consent withdrawn, Intimacy set to never, a release) goes at
    once: what is offered is always the locked list AND what the filter allows now."""
    key = _action_key()
    if _action_lock['key'] != key or _action_lock['names'] is None:
        _action_lock.update(key=key, names={_tool_name(t) for t in tools})
        return tools
    return [t for t in tools if _tool_name(t) in _action_lock['names']]


def _speaker_note(ctx):
    if not settings.load()['action_filter']:
        return ''
    gates = _gates()
    speakers = _action_speakers()
    if not gates or len(speakers) < 2:
        return ''
    locked = _action_lock['names'] if _action_lock['key'] == _action_key() else None
    offered = [{'function': {'name': name}} for name in gates if locked is None or name in locked]
    return action_filter.speaker_note(action_filter.filter_actions(offered, speakers, gates), speakers, gates)


def _carry_text(messages) -> str:
    """The trade line (trade.carry_text), plus one debug log line saying whether this request carried a merchant's wares
    and World's Trade action (live test 14: neither is in Mantella's own log, so a failed sale by talk could not be
    told apart from a missing line or action)."""
    text = trade.carry_text(lw_state.load_conversation(), messages) if 'World' in _installed() else ''
    logging.getLogger('Mantella').debug(trade_request_note(messages, text))
    return text


def trade_request_note(messages, carry: str) -> str:
    offered = _offered['names']
    action = 'not known' if offered is None else 'yes' if 'Trade' in offered else 'no'
    talk = 'yes' if trade.wants_trade(trade.player_line(messages)) else 'no'
    return (f"Living World: trade check for this request: trade talk {talk}, wares line "
            f"{'yes' if 'wares for sale' in carry else 'no'}, Trade action {action}")


def _extra_text(ctx):
    """Lines for the newest message: who may do what (groups), why an ambient talk started, what was just said nearby,
    topics the player asked this NPC about in an earlier talk, and the scene (time, place, weather; taken out of the
    system prompt so the cached part stays the same all talk)."""
    bio_evolve.talk_going_on()
    store = _last_store['store']
    messages = ctx.get('messages') or []
    custom_events.fix_request(messages, store)  # custom events edited or taken back during this talk
    system = messages[0].get('content') if messages and messages[0].get('role') == 'system' else ''
    producers = [  # each on its own: one failing must not take the scene (or the others) out of the reply
        lambda: (lambda scene: f"(The scene now. {scene})" if scene else '')(layout.scene_text(system) if isinstance(system, str) else ''),
        lambda: child_line(lw_state.load_conversation()),
        lambda: _speaker_note(ctx),
        lambda: _intimacy(ctx),
        lambda: nearby.seed(lw_state.load_banter()),
        lambda: nearby.said_nearby(lw_state.load_said_nearby(), time.time()),
        lambda: _asked.notes(messages, _last_store['people'], store, lw_state.load_player_name() or 'The player', lw_state.load_today(),
                             talk=npc_block._talk['gen']),  # a trim mid-talk is the same talk
        lambda: battle.prompt_text(lw_state.load_conversation(), lw_state.load_battles(), lw_state.load_today(), _ref,
                                   knows=lambda s: _recognises_now(s.get('name'), memory_ui.mantella_ref(str(s.get('ref_id') or '')))) if 'World' in _installed() else '',
        lambda: _carry_text(messages),  # what they carry, on trade talk
        lambda: bio_evolve.others_text(store, _last_store['people'], messages),  # how others see an NPC (a custom event)
        lambda: _strangeness(store),  # people who know an enchanted NPC well notice it
        lambda: _commands(newest=True),
        lambda: console.newest_text(messages),  # the Console wish, on the turn its action is offered
        lambda: _recognition(messages) if 'World' in _installed() else '',  # hood or not, already for the greeting
        lambda: news.fresh_text([n for n, _ in _last_store['people']]),  # a killing they saw a short while ago
        lambda: npc_block.marriage_text(messages, lw_state.load_conversation()),  # Relationships' note, on marriage talk only
        lambda: silent_requests.note(lw_state.load_player_name()),  # a rating asked for: a note for the actions, not an event
    ]
    lines = []
    for produce in producers:
        try:
            lines.append(produce())
        except Exception as e:
            logging.getLogger('Mantella').warning(f"Living World: a newest-message line failed ({e}); the others are kept")
    return '\n'.join(line for line in lines if line)


def _knows_player(name: str, ref, speaker: dict | None = None) -> bool:
    """Knows the player personally, hood or not (npc_block.knows_player): their file, an absolute command in force on
    them, or several remembered talks with the player."""
    store = _last_store['store']
    speaker = speaker if speaker is not None else next((s for s in lw_state.load_conversation() if s.get('name') == name), {})
    commanded, talks = False, 0
    if store is not None and name:
        try:
            character = type('NPC', (), {'name': name, 'ref_id': ref})()
            commanded = bool(command.active_for(store, character, _ref, command.current_time(lw_state.load_today())))
            # only talks the loaded save has (an older save loaded: the later ones never happened), none forgotten
            branch = timeline.current(store)
            remembered = memory._peek(store, name, ref)
            usable = [e for e in remembered.get('recent', []) if not e.get('hidden') and timeline.usable(branch, e)]
            talks = memory._player_talks({'recent': usable})
            if any('intimacy' in (e.get('flags') or []) for e in usable) or menu_dialogue.intimate(memory.file_name(name)):
                commanded = True  # someone who has been intimate with the player knows him under a hood (live test 14)
        except Exception:
            pass
    return npc_block.knows_player(speaker, commanded, talks)


_unrecognised: dict = {}  # name -> ref of NPCs this talk was told do not recognise the player under the hood


def _recognition(messages) -> str:
    """On the greeting (no NPC reply yet): who recognises the player under a hood (npc_block.recognition_text). Later
    requests have World's own event in the talk, corrected in _dialogue_events; and an NPC told at the greeting that they
    do not recognise the player who knows them now (an absolute command given during the talk) is told so, once."""
    player = lw_state.load_player_name() or 'the player'
    if any(isinstance(m, dict) and m.get('role') == 'assistant' for m in messages or []):
        lines = []
        for name, ref in list(_unrecognised.items()):
            if _knows_player(name, ref):
                _unrecognised.pop(name, None)
                # knowing who it is now is no shared past: "Good to see you again" to someone never met was invented
                line = (f"({name} now knows who {player} is, hood or not. That is no earlier acquaintance: {name} has met "
                        f"{player} before only if {name}'s memories say so.")
                store = _last_store['store']
                if store is not None and memory.connection_line(memory._peek(store, name, ref), name, player):
                    line += f" The hooded stranger in {name}'s memories was {player}."
                lines.append(line + ')')
        return '\n'.join(lines)
    _unrecognised.clear()
    _hooded_talk.clear()

    def knows(name, ref, speaker=None):
        known = _knows_player(name, ref, speaker)
        if not known:
            _unrecognised[name] = ref
        return known
    text = npc_block.recognition_text(_last_store['people'], lw_state.load_conversation(), player, knows)
    _hooded_talk.update(n for n in _unrecognised if f"({n} does not recognise " in text)
    return text


_hooded_talk: set = set()  # names told at this talk's greeting that they do not recognise the hooded player


def _hooded_in_thread(thread) -> set:
    """The names World's event in this talk says do not recognise the player under a hood (lines not turned into
    "knows ... well" for someone who knows them)."""
    names = set()
    try:
        for i in range(len(thread)):
            for event in getattr(thread[i], '_UserMessage__ingame_events', None) or []:
                found = npc_block.UNRECOGNISED.match(str(event).strip()) if isinstance(event, str) else None
                if found:
                    names.add(found.group(1).strip())
    except Exception:
        pass
    return names


def _unrecognised_for(messages):
    """unrecognised(character) -> True when the game said this NPC did not recognise the hooded player in the talk
    being saved and they do not know the player now (an absolute command or a tie makes them know who it was)."""
    named = set(_hooded_talk) | _hooded_in_thread(messages)

    def unrecognised(character):
        try:
            return character.name in named and not _knows_player(character.name, character.ref_id)
        except Exception:
            return False
    return unrecognised


def _recognises_now(name, ref) -> bool:
    """This NPC knows who the player is now: they know the player personally, or no hood hides the player's face."""
    if _knows_player(name, ref):
        return True
    try:
        return not (npc_block.face_hidden() and npc_block.hood_hides(lw_state.load_world()))
    except Exception:
        return False


def _command_for(store):
    """command_for(character) -> the id of an absolute command in force for them, else '' (memory.summarize tags the
    talk with it; bio_evolve writes no note for them meanwhile)."""
    def command_for(character):
        try:  # a release during this talk: the talk was still under that command (release.after_talk)
            return command.active_for(store, character, _ref, command.current_time(lw_state.load_today())) \
                or release.released_in_talk(character)
        except Exception:
            return ''
    return command_for


POLL_SECONDS = 1.0  # unchanged game files are polled again after this long (commands that wear off, stuck checks)
_polled: dict = {}


def _file_stamp(path):
    try:
        st = os.stat(path)
        return st.st_mtime_ns, st.st_size
    except OSError:
        return None


def _commands(newest: bool) -> str:
    """Absolute commands (command.py) for the NPCs in this talk, after reading new ones from the game's hotkey: the full
    part for the system prompt, or newest=True the line for the newest message."""
    store = _last_store['store']
    if store is None:
        return ''
    values = settings.load()
    summaries = _last_store.get('summaries')
    ask = (lambda prompt, text: summaries.summarize_conversation(text, prompt)) if summaries is not None else None
    speakers = lw_state.load_conversation() or [{'name': n, 'ref_id': r} for n, r in _last_store['people']]
    player = lw_state.load_player_name()
    now = time.monotonic()
    # one request asks up to four times (the keyword question, the actions, the newest message, the system prompt): the
    # game's files are polled again only when one of them changed, the talk or a setting changed, or POLL_SECONDS passed
    key = (getattr(store, 'root', None), tuple(sorted(str(s.get('base_id') or s.get('name') or '') for s in speakers)),
           tuple(_file_stamp(os.path.join(lw_state.DATA_DIR, f)) for f in (command.GAME_FILE, release.GAME_FILE, command.GAME_SETTINGS)),
           _file_stamp(command.store_path(store)), values.get('command_hours'), player)
    if _polled.get('key') != key or now - _polled.get('at', -POLL_SECONDS) >= POLL_SECONDS:
        _polled.update(key=key, at=now)
        command.write_game_settings(values)
        command.poll(store, _last_store['people'], values, ask, _ref, lw_state.load_today(), player, speakers)
        release.poll_game(store, player, lw_state.load_today(), speakers, ask, in_talk=speakers)  # the in-game hotkey menu
    if newest:  # a release acts at once: one line for each NPC here just released
        return '\n'.join(t for t in (release.newest_text(speakers), command.newest_text(store, speakers, player or 'the player', _ref)) if t)
    return command.system_text(store, speakers, player or 'the player', _ref)


def _knowledge_on(values) -> bool:
    """Knowledge is installed and on: it tells who has heard of the Dragonborn."""
    here = os.path.dirname(os.path.abspath(__file__))
    return values['knowledge_mode'] != 'off' and os.path.isdir(os.path.join(os.path.dirname(here), 'lw_knowledge'))


def _system_parts(parts, ctx):
    bio_evolve.talk_going_on()
    values = settings.load()
    rules = prompt_rules.load_rules(player_name=lw_state.load_player_name(), disabled=settings.disabled_rules(values))
    if rules != _logged_rules['text']:
        _logged_rules['text'] = rules
        logging.getLogger('Mantella').log(23, f"Living World: {len(rules.splitlines())} rule line(s) in the system prompt (~{len(rules) // 4} tokens)")
    keep = values['bio_examples']
    speakers = lw_state.load_conversation()
    if isinstance(parts.get('mantella'), str):  # each long bio's short version (bio_optimise), the same all talk
        try:
            parts = dict(parts, mantella=bio_optimise.apply(parts['mantella'], _last_store.get('bios'),
                                                            lambda name, original: _used_bio(name, original, values)))
        except Exception as e:
            logging.getLogger('Mantella').warning(f"Living World: the short bios could not be used ({e}); the originals are sent")
    bios = _last_store.get('bios') or []
    if keep >= 0 and bios and isinstance(parts.get('mantella'), str):
        parts = dict(parts, mantella=_trim_stock_examples(parts['mantella'], bios, keep))
    if values['basic_bios'] and isinstance(parts.get('mantella'), str):
        parts = dict(parts, mantella=basic_bio.replace(parts['mantella'], speakers))
    # without the bios known (no memory hook yet) every examples block is cut, as before
    ordered = layout.order_system(parts, rules, keep_examples=None if keep < 0 or bios else keep)
    # the jobs and the world note sit in the cached part: built once per talk (npc_block.frozen), so a world.json rewrite
    # mid-talk (a bounty, fame, a quest event) no longer rewrites the cache; a new NPC's late file part (hold, guard,
    # groups: 9 to 11 s after the greeting) is still used, once
    store = _last_store['store']
    people = tuple(sorted(str(s.get('base_id') or s.get('name') or '') for s in speakers))
    jobs = npc_block.frozen(store, ('jobs', people), lambda: lw_state.jobs_text(speakers, _installed()))
    if jobs:
        ordered['jobs'] = jobs
    if values['world_note']:
        filed = tuple(sorted((str(s.get('base_id') or s.get('name') or ''), bool(s.get('hold') or s.get('guard') or s.get('groups')))
                             for s in speakers))
        note = npc_block.frozen(store, ('world', filed, _knowledge_on(values)), lambda: world_note.text(
            speakers, lw_state.load_world(), lw_state.load_player_name(), skip_dragonborn=_knowledge_on(values)))
        if note:
            ordered['world'] = note
    try:  # what the hold believes about the player (reputation.py): built once per talk, so the cached part holds
        fame = _reputation(speakers)
        if fame:
            ordered['world'] = (ordered.get('world', '') + '\n' + fame).strip()  # a part not in __order__ goes after it
    except Exception as e:
        logging.getLogger('Mantella').warning(f"Living World: reputation failed ({e}); left out")
    try:  # Personality (the bio), then each NPC's Background facts and Now paragraph; built once per talk
        characters.remember_locked(speakers)
        ordered = npc_block.add_to_parts(ordered, _npc_block(speakers, values))
    except Exception as e:
        logging.getLogger('Mantella').warning(f"Living World: the NPCs' background and Now could not be added ({e}); left out")
    try:
        commands = _commands(newest=False)
        if commands:  # last before the reply instruction, after memories: it overrides everything above it
            ordered['command'] = commands
            order = [k for k in ordered.get('__order__', []) if k != 'command']
            at = order.index('respond') if 'respond' in order else len(order)
            ordered['__order__'] = order[:at] + ['command'] + order[at:]
    except Exception as e:
        logging.getLogger('Mantella').warning(f"Living World: absolute commands could not be added ({e}); left out")
    try:
        _record_sizes(ordered, values)
    except Exception as e:
        logging.getLogger('Mantella').warning(f"Living World: the prompt's sizes could not be recorded ({e})")
    preview.record_system(ordered, _speaker_names())
    return ordered


def _trim_stock_examples(text: str, bios, keep: int) -> str:
    """The example lines of each stock bio still sent as it is cut to keep (the Example lines setting); a short bio
    (bio_optimise) and a bio set by hand on the NPC page (kept as it is, or written by hand) are never cut."""
    for name, original in bios:
        try:
            if not original.strip() or original not in text or bio_optimise.uses_original(name) \
                    or bio_optimise.is_manual(bio_optimise.entry(name, original)):
                continue
            text = text.replace(original, layout.trim_examples(original, keep), 1)
        except Exception as e:
            logging.getLogger('Mantella').warning(f"Living World: {name}'s example lines could not be cut ({e}); sent whole")
    return text


def _used_bio(name: str, original: str, values: dict) -> str:
    """The bio sent for this NPC this talk: the short version when current, else the original; chosen at the talk's
    first request and kept (npc_block.frozen), so one written meanwhile is used from the next talk."""
    key = ('bio', name, bio_optimise.bio_hash(original), bool(values.get('bio_optimise', True)))
    return npc_block.frozen(_last_store['store'], key, lambda: bio_optimise.used_bio(name, original, values)) or original


def _record_sizes(ordered: dict, values: dict) -> None:
    """The size of each section of this request, per NPC (preview.sections_for): the bio sent and the original, their
    Background and Now, then world, memories, commands and rules as sent, and how many actions were offered."""
    tok = preview.tokens
    bios = dict(_last_store.get('bios') or [])
    block = _last_store.get('npc_text') or ''
    shared = [(label, ordered.get(key)) for label, key in (('world', 'world'), ('memories', 'history'),
                                                           ('commands', 'command'), ('rules', 'prompt_rules'))]
    total = sum(tok(v) for k, v in ordered.items() if not k.startswith('__') and isinstance(v, str))
    tools = preview.latest().get('tools')
    rows = {}
    for name in [n for n, _ in _last_store['people']] or list(bios):
        original = bios.get(name, '')
        used = _used_bio(name, original, values) if len(original.strip()) >= bio_optimise.MIN_CHARS else original
        background, now = npc_block.parts_of(block, name)
        row = [('bio sent', tok(used), f"original {tok(original):,}" if used != original else 'the original'),
               ('Background', tok(background), ''), ('Now', tok(now), '')]
        row += [(label, tok(text), '') for label, text in shared if isinstance(text, str) and text]
        row.append(('system prompt', total, 'all parts'))
        row.append(('actions offered', None, f"{tools}, size not counted here" if tools else 'not known yet'))
        rows[name] = row
    preview.record_sections([n for n, _ in _last_store['people']], rows)


def _characters():
    return [type('NPC', (), {'name': n, 'ref_id': r})() for n, r in _last_store['people']]


def _reputation(speakers) -> str:
    """What the hold believes about the player, for the NPCs in this talk: the same text all talk (npc_block.frozen)."""
    store = _last_store['store']
    if store is None or not _last_store['people']:
        return ''
    # who the game has confirmed as an adult is part of the key: an NPC whose file arrives after the greeting gets their
    # line on the next request (built once more), not left out for the whole talk
    confirmed = tuple(sorted((str(s.get('base_id') or s.get('name') or ''), action_filter.adult(s)) for s in speakers or []))
    key = ('reputation', tuple(sorted(str(r) for _, r in _last_store['people'])), confirmed)
    return npc_block.frozen(store, key, lambda: reputation.text(store, _characters(), lw_state.load_player_name(),
                                                               lw_state.load_today(), speakers))


def _strangeness(store) -> str:
    """Strangeness lines for the newest message (they follow the commands in force, which can change mid-talk)."""
    if store is None:
        return ''
    return strangeness.text(store, lw_state.load_conversation(), lw_state.load_player_name(),
                            _characters() or None, command.current_time(lw_state.load_today()),
                            knows=lambda o: _recognises_now(o.get('name'), o.get('ref')))


def _npc_block(speakers, values) -> str:
    store = _last_store['store']
    commands = command.load(store)['commands'] if store is not None else []
    speakers = speakers or [{'name': n, 'ref_id': r} for n, r in _last_store['people']]
    _last_store['npc_text'] = ''
    _last_store['npc_text'] = npc_block.text(store, speakers, _last_store['people'], lw_state.load_player_name() or 'the player',
                          lw_state.load_world() if 'World' in _installed() else None, lw_state.load_today(), commands,
                          values['bio_changes'], knows=lambda s: _recognises_now(s.get('name'), _ref(s.get('ref_id'))))
    return _last_store['npc_text']


def _now_context(store, speakers):
    """now_context(npc) -> what the Now writer is given besides the bio and memories: the NPC's Background facts, the
    commands in force on them and the labels for memories made under a command."""
    player = lw_state.load_player_name() or 'the player'

    def context(npc):
        speaker = next((s for s in speakers if _ref(s.get('ref_id')) is not None and _ref(s.get('ref_id')) == _ref(getattr(npc, 'ref_id', None))),
                       None) or next((s for s in speakers if s.get('name') == npc.name), {'name': npc.name, 'ref_id': npc.ref_id})
        entry = characters.entry_for(npc.name, speaker.get('race', ''))
        state = bio_evolve.load(store, npc.name, npc.ref_id)
        facts = facts_history.background_lines(store, speaker, player, entry, None, values=state['values'])
        commands = '\n'.join(command._line(r, names, player) for r, names in command.in_force(store, [speaker], _ref))
        remembered = memory._peek(store, npc.name, npc.ref_id)
        # never learned who the player is: only talks with a hooded stranger, no tie, no command
        hooded = (any(e.get('unrecognised') for e in remembered.get('recent', [])) and not memory._player_talks(remembered)
                  and not _knows_player(npc.name, npc.ref_id))
        return {'facts': '\n'.join(facts), 'commands': commands, 'player': player, 'hooded': hooded,
                'values_given': bool((entry or {}).get('values')), 'labels': command.memory_labels(store, player),
                'events': custom_events.established_text(store, npc.name)}  # custom events: true, never contradicted
    return context


def _stable_background(npc, speakers) -> list[str]:
    """The Background lines a short bio may leave out (bio_optimise.stable_background): the same in every save."""
    speaker = next((s for s in speakers if _ref(s.get('ref_id')) is not None and _ref(s.get('ref_id')) == _ref(getattr(npc, 'ref_id', None))),
                   None) or next((s for s in speakers if s.get('name') == npc.name), {'name': npc.name})
    return bio_optimise.stable_background(speaker, characters.entry_for(npc.name, speaker.get('race', '')))


def _custom_event_reasons(store, characters_, speakers) -> None:
    """The custom events of the talk that just ended: each NPC there gets their Now paragraph due, and an event that
    claims a game-owned fact (a marriage, a home) is noted as a mismatch for the page; the game value stands."""
    talk = custom_events._talk['id']
    if store is None or talk is None:
        return
    player = lw_state.load_player_name() or 'the player'
    rows = [r for r in custom_events.load(store) if r.get('talk') == talk and r.get('status') == 'active']
    for npc in characters_ or []:
        mine = [r for r in rows if any(n.get('name') == npc.name for n in r.get('npcs') or [])]
        if not mine:
            continue
        for row in mine:
            bio_evolve.mark_due(store, npc.name, npc.ref_id, f"a custom event happened (true; it happened): {row['text'][:200]}")
            speaker = next((s for s in speakers if _ref(s.get('ref_id')) == _ref(npc.ref_id)), None)
            if speaker:
                found = facts_history.event_claims(row['text'], speaker, player)
                facts_history.record_mismatches(store, npc.name, npc.ref_id, f"custom event {row['id']}", row['text'], found,
                                                lw_state.load_today())


def _store(ctx):
    """Memories sit next to Mantella's own summaries: <conversations folder>/<world id>/living_world/."""
    game = getattr(ctx.get('summaries'), '_Summaries__game', None)
    if game is not None:
        _last_store['game'] = game
    folder = getattr(game, 'conversation_folder_path', None)
    if not (folder and ctx.get('world_id')):
        return None
    _last_store['store'] = memory.MemoryStore(folder, ctx['world_id'])
    return _last_store['store']


def _summarize(ctx):
    try:
        lw_state.note_live_player(ctx['npcs_in_conversation'].get_player_name())
    except Exception:
        pass
    store = _store(ctx)
    if store is None:
        return False  # Mantella saves its own summaries
    speakers = lw_state.load_conversation()
    _remember_battles(store, ctx.get('npcs_to_summarize'), at_end=True)
    values = settings.load()
    command.note_time(ctx.get('end_timestamp'))
    ctx = dict(ctx, language=getattr(ctx['summaries'], '_Summaries__language_name', 'English'),
               is_minor=lambda character: _is_minor(character, speakers), share_adult=_share_adult,
               chatter_filter=values['chatter_filter'],
               diary_for=lambda character: values['follower_diary'] and bool(_npc_state(character, speakers).get('follower')),
               purse_for=lambda character: _npc_state(character, speakers).get('carry_gold'),
               command_for=_command_for(store), unrecognised=_unrecognised_for(ctx.get('messages')))
    custom_events.fix_thread(ctx.get('messages'), store)
    try:
        _save_talk_memories(ctx, store, speakers, values)
    finally:  # whatever failed while saving, the next talk starts clean (in the same order as before)
        if not ctx.get('is_reload') and not ctx.get('departed'):
            bio_evolve.talk_over()  # the talk is over: notes waiting on it may be written now
            news.talk_over()  # the next talk, even with the same people a minute later, gets its news
            timeline.note_time(None)
            npc_block.talk_over()  # the next talk builds each NPC's background and Now anew
            console.talk_ended()  # a Console wish never carries into another talk
            silent_requests.clear()  # a rating request no reply took: the game asks again in the next talk
            menu_dialogue.talk_over()
    try:
        bio_evolve.after_summary(dict(ctx, now_context=_now_context(store, speakers)), store, values)
    except Exception as e:
        logging.getLogger('Mantella').warning(f"Living World: how NPCs have changed could not be updated ({e})")
    try:  # a short bio for NPCs of this talk who have none yet, on the same background worker
        bio_optimise.helper['summaries'] = ctx.get('summaries')
        if not ctx.get('is_reload'):
            bio_optimise.after_talk(ctx.get('npcs_to_summarize'), ctx.get('summaries'), values,
                                    lambda npc: _stable_background(npc, speakers))
    except Exception as e:
        logging.getLogger('Mantella').warning(f"Living World: short bios could not be queued ({e})")
    # always handled here: Mantella's own summary would be a second model call into files Living World never reads
    return True


def _save_talk_memories(ctx, store, speakers, values) -> None:
    """_summarize's saving part: the memories, then what the talk changed for commands, releases and custom events; each
    step logs its own failure and the others still run."""
    try:
        memory.summarize(ctx, store)
    except Exception as e:
        logging.getLogger('Mantella').warning(f"Living World: this talk's memories could not be saved ({e})")
    summaries = ctx.get('summaries')
    ask = (lambda prompt, text: summaries.summarize_conversation(text, prompt)) if summaries is not None else None
    for step, run in (
            ('what the talk said about a forgotten thing', lambda: command.after_summary(
                store, ctx.get('npcs_to_summarize'), _ref, values, ask, memory.day_hour(ctx.get('end_timestamp')))),
            ('releases during the talk', lambda: release.after_talk(store, ctx.get('npcs_to_summarize'), final=not ctx.get('is_reload'))),
            ('custom events for the Now paragraph', lambda: _custom_event_reasons(store, ctx.get('npcs_to_summarize'), speakers)),
            ('custom events of the talk', lambda: custom_events.after_summary(ctx, store))):
        try:
            run()
        except Exception as e:
            logging.getLogger('Mantella').warning(f"Living World: {step} could not be handled ({e})")


def _remember_battles(store, characters, at_end: bool) -> None:
    """World's memorable fights into the memory of each NPC who was there (battle.remember); never stops the caller."""
    try:
        if 'World' in _installed():
            battle.remember(store, characters, lw_state.load_battles(), _ref, at_end,
                            knows=lambda c: _recognises_now(c.name, c.ref_id))
    except Exception as e:
        logging.getLogger('Mantella').warning(f"Living World: fight memories failed ({e}); left out")


def _dialogue_events(events, ctx):
    bio_evolve.talk_going_on()
    lw_state.note_live_player(ctx.get('player'))  # Mantella's own name for the player in this talk: the freshest
    events = silent_requests.take(events)  # a silent rating asked for is no scene event (silent_requests): a note instead
    events = npc_block.collapse_outfit_events(events)  # a follower's outfit swap: one line, not thirty
    command.note_time(ctx.get('game_days'))  # the game clock, for absolute commands that last some hours
    timeline.note_time(ctx.get('game_days'))
    store = _store(ctx)
    summaries = ctx.get('summaries')
    ask = (lambda prompt, text: summaries.summarize_conversation(text, prompt)) if summaries is not None else None
    if {'World', 'OStim Expansion'} & _installed():  # menu dialogue (World) and kept scenes (OStim Expansion) from before the talk
        try:
            events = _menu_memories(events, ctx, store)
        except Exception as e:
            logging.getLogger('Mantella').warning(f"Living World: earlier dialogue or scenes could not be remembered ({e})")
    if 'World' in _installed():  # someone who knows the player personally still knows them under a hood
        ref_of = dict(_last_store['people'])
        events = npc_block.fix_recognition_events(events, lambda name: _knows_player(name, ref_of.get(name)),
                                                  lw_state.load_player_name() or 'the player')
    events = custom_events.process(events, ctx, store, settings.load()['custom_events_silent'], ask)
    if not store:
        return events
    ctx = dict(ctx, language=getattr(ctx['summaries'], '_Summaries__language_name', 'English'),
               chatter_filter=settings.load()['chatter_filter'])
    return memory.compact_dialogue(events, ctx, store)


def _menu_memories(events, ctx, store):
    """At a talk's first message: Mantella's own copy of the menu dialogue this talk already shows (prepare) gives way to
    a short note. On any message: OStim Expansion's kept scenes (taken from these events) that followed that dialogue
    are paired with it for the end-of-talk summary, any other becomes its own memory at once; menu lines Mantella put
    into the talk are marked used."""
    player = lw_state.load_player_name() or ctx.get('player') or 'the player'
    raw = events  # with the scene times, which remember_scene_events dates the scenes by
    events, scenes = menu_dialogue.scene_records(events)
    # a kept scene sent again although already in her memory (OStim Expansion re-sends until it reads the
    # acknowledgement) is not shown to the model again (live test 17); it is still acknowledged below
    stored = menu_dialogue.stored_scene_indexes(raw, ctx.get('characters'), store)
    if stored:
        events = [e for i, e in enumerate(events) if i not in stored]
    knows = lambda c: _recognises_now(c.name, c.ref_id)  # knows him personally, or no hood hides his face
    strangers = {c.name for c in ctx.get('characters') or [] if not knows(c)}
    if ctx.get('is_first') and store is not None:
        # her menu lines are in her memory block already (prepare): Mantella's own copy of them becomes a short note,
        # kept aside for the player's words World missed; the end-of-talk summary makes them into her memory
        events = menu_dialogue.replace_events(events, ctx.get('player') or player, strangers)
    else:
        events = menu_dialogue.mask_strangers(events, ctx.get('player') or player, strangers)
    if scenes and store is not None:
        # OStim Expansion's kept scenes come with the first or second message (live test 15: after the player's first
        # line): one that followed this talk's menu lines goes into that memory at the end of the talk, else each is
        # its own memory at once
        paired = menu_dialogue.pair_late_scenes(raw, ctx.get('characters'), store, player)
        menu_dialogue.remember_scene_events(raw, ctx.get('characters'), store, lw_state.load_today(), ctx.get('summaries'),
                                            paired=paired, knows=knows, player=player)
    menu_dialogue.mark_delivered(events, ctx.get('characters'), store, ctx.get('player') or player)
    if scenes and store is not None:  # OStim Expansion keeps a scene until it is acknowledged here (live test 16)
        menu_dialogue.acknowledge_scenes(raw, ctx.get('characters'), store)
    return events


def _menu_before_prompt(store, ctx, speakers) -> None:
    """The game's own dialogue World heard since each NPC's last talk goes into her memory block as it was said, dated,
    before the prompt is built, so the greeting already knows it (menu_dialogue.prepare; no model call: live test 17
    showed the prompt is built before the first message's events). The talk's end-of-talk summary makes it into her
    lasting memory, with any kept scene that followed (_menu_memories). Once per NPC per talk; never raises."""
    try:
        player = lw_state.load_player_name() or 'the player'
        for character in ctx.get('characters') or []:
            menu_dialogue.prepare(store, character, player, speakers=speakers,
                                  knows=lambda c=character: _recognises_now(c.name, c.ref_id))
    except Exception as e:
        logging.getLogger('Mantella').warning(f"Living World: earlier dialogue could not be read before the prompt ({e})")


def _ref(value):
    """A reference id as a number the way Mantella keeps it, whatever its text form ("FE1DD821", "0xfe1dd821",
    4263364641). The game side writes all 8 hex digits; Mantella keeps only the last 6, a light plugin's FE id its last 3
    (memory_ui.mantella_ref), so both sides are cut the same way before they are compared."""
    try:
        number = value if isinstance(value, int) and not isinstance(value, bool) else int(str(value), 16)
    except (TypeError, ValueError):
        return None
    number %= 1 << 32  # a signed 32-bit form id too
    return number & 0xFFF if number >> 24 == 0xFE else number & 0xFFFFFF


def _memory_text(text, ctx):
    bio_evolve.talk_going_on()
    stage_timing.apply(settings.load()['stage_timing'])  # speed testing (off by default)
    store = _store(ctx)
    if not store:
        return text
    _last_store['people'] = [(c.name, c.ref_id) for c in ctx.get('characters') or []]
    _last_store['summaries'] = ctx.get('summaries')  # absolute commands are read with the summary model
    bio_optimise.helper['summaries'] = ctx.get('summaries')
    _last_store['bios'] = [(c.name, str(getattr(c, 'bio', '') or '')) for c in ctx.get('characters') or []]
    # Mantella's time of this request (Direct AI Connect gives it): right after an older save was loaded the game's talk
    # counter is still the newer save's until this talk's counter is written (timeline.Cut)
    timeline.note_time(ctx.get('game_days'))
    _remember_battles(store, ctx.get('characters'), at_end=False)
    values = settings.load()
    speakers = lw_state.load_conversation()
    today = lw_state.load_today()
    try:  # world news (news.py): once per talk, what has reached each NPC by now becomes a memory before they are shown
        news.talk_start(store, ctx.get('characters') or [], today, {'speakers': speakers, 'game_days': ctx.get('game_days'),
                                                                    'knows': _knows_player})  # under a hood: named only to them
    except Exception as e:
        logging.getLogger('Mantella').warning(f"Living World: world news failed ({e})")
    if 'World' in _installed():
        _menu_before_prompt(store, ctx, speakers)
    by_name = {s.get('name'): s for s in speakers}
    # two light-plugin NPCs can cut to the same short ref (FE00A802, FE00B802): such a ref matches nobody, the name decides
    refs = Counter(_ref(s.get('ref_id')) for s in speakers)
    by_ref = {_ref(s.get('ref_id')): s for s in speakers if _ref(s.get('ref_id')) is not None and refs[_ref(s.get('ref_id'))] == 1}
    # Mantella numbers same-named NPCs ("Whiterun Guard 2"), so match on the reference first, the name second
    speaker = lambda c: by_ref.get(_ref(getattr(c, 'ref_id', None))) or by_name.get(c.name, {})
    installed = _installed()
    facts_for = lambda c: lw_state.game_facts(speaker(c), today, installed)
    # the same speaker as for facts: a stranger who shares a follower's name is still a stranger
    budget_for = lambda c: values['memory_budget'] if speaker(c).get('close') or speaker(c).get('follower') else values['memory_budget_stranger']
    def profile_seen(character, profile):
        try:
            lw_state.write_profile(speaker(character).get('base_id', ''), profile)
        except OSError as e:
            logging.getLogger('Mantella').warning(f"Living World: could not write {character.name}'s profile for the game ({e})")
    _start_memory_model(values)
    ctx = dict(ctx, today=today, player=lw_state.load_player_name() or 'the player', facts_for=facts_for,
               recall=values['memory_recall'], recall_query=_recall_extra,
               profile_seen=profile_seen, profile_overrides=settings.load_profile_overrides(),
               is_minor=lambda character: not action_filter.adult(speaker(character)),
               knows_player=lambda character: _recognises_now(character.name, character.ref_id),
               extra_for=lambda character: menu_dialogue.talk_text(memory.file_name(character.name),
                                                                   lw_state.load_player_name() or 'the player'))
    return memory.memory_text(text, ctx, store, values['memory_budget'], budget_for)


def _pages(gr, api, config, game_fn):
    bio_optimise.helper['config'] = config  # the page's short-bio buttons can use the model Optimize with AI uses
    return ui_tab.build_pages(gr, api, config, game_fn)


def register(api):
    action_args.install()  # action arguments reach the game in their declared type (a wrong type crashes it)
    api.on('system_parts', _system_parts)
    api.on('filter_tools', _filter_tools)
    api.on('extra_user_text', _extra_text)
    api.on('summarize', _summarize)
    api.on('memory_text', _memory_text)
    try:
        api.on('dialogue_events', _dialogue_events)
    except ValueError:  # an older Direct AI Connect has no such hook: long dialogue is summarized when the talk ends
        pass
    try:
        api.on('server_actions', _server_actions)
        console.use_server()  # the Console action is built by the server, never chosen by the NPC model
    except ValueError:  # an older Direct AI Connect: the Console action is offered to the model on its turn, as before
        pass
    api.on('conversation_limit', lambda tokens: settings.load()['trim_after_tokens'] or tokens)
    update_check.check_in_background(settings.load()['update_check_days'])
    characters.write_game_flags()  # the game reads the Characters page flags from its channel folder
    _start_memory_model(settings.load())  # in the background, so it is ready by the first talk
    server_status.start()
    menu_dialogue.start_overflow_watch(lambda: _last_store.get('store'), lambda: _last_store.get('summaries'),
                                       knows=lambda c: _recognises_now(c.name, c.ref_id))
    game_fn = lambda: _last_store['game']
    try:
        # four tabs of our own: Main Status, Player and NPC Data, Memory, Prompt Rules and Settings
        api.on('ui_page', lambda gr, config: _pages(gr, api, config, game_fn))
    except ValueError:  # an older Mantella exe without tabs of their own: everything inside its one Living World tab
        api.on('ui_tab', lambda gr: ui_tab.build(gr, api, game_fn=game_fn))
