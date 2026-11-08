"""Mantella Living World: the Integration Hub's side inside Mantella, loaded by Mantella - Direct AI Connect."""
import logging
import os
import time
from collections import Counter

from . import action_filter, asked_before, basic_bio, layout, lw_state, memory, nearby, preview, prompt_rules, server_status, settings, ui_overrides, ui_tab, update_check, world_note

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
    check; Survival is not on the Status page, so it is found by its own action files here."""
    found = set(ui_tab.installed_modules())
    try:
        if any(f.startswith('mantella_mlws_') for f in os.listdir('data/actions')):
            found.add('Survival')
    except OSError:
        pass
    return found


def child_line(speakers: list[dict]) -> str:
    """With a child in a group talk: one line so nothing adult is said in front of them."""
    children = [s.get('name', '?') for s in speakers if action_filter._int(s.get('minor'), 0) > 0]
    if not children or len(speakers) < 2:
        return ''
    return (f"(A child, {', '.join(children)}, is in this conversation: nothing sexual or romantic is said, done or "
            f"hinted at.)")


def _is_minor(character, speakers: list[dict] | None = None) -> bool:
    """A Mantella character is a child by the game side's file: the conversation's speaker with their reference id or
    name first, else the npc file of their base id."""
    ref = _ref(getattr(character, 'ref_id', None))
    for s in speakers or []:
        if (ref is not None and _ref(s.get('ref_id')) == ref) or s.get('name') == getattr(character, 'name', None):
            return action_filter._int(s.get('minor'), 0) > 0
    base = str(getattr(character, 'base_id', '') or '')
    return action_filter._int(lw_state.load_npc(base).get('minor'), 0) > 0


def _filter_tools(tools, ctx):
    try:
        values = settings.load()
        gates = _gates()
        if values['action_filter']:
            tools = action_filter.filter_actions(tools, lw_state.load_conversation(), gates)
        if values['short_actions']:
            tools = action_filter.shorten(tools, gates)
        if not (ctx or {}).get('keyword_actions'):  # Direct AI Connect also asks which "Name:" keywords may fire
            preview.record_tools(len(tools), _speaker_names())
        return tools
    except Exception as e:  # an error here would hand Mantella back every action, gated ones included: fail closed
        logging.getLogger('Mantella').warning(f"Living World: the action filter failed ({e}); only ungated actions are offered")
        try:
            return action_filter.filter_actions(tools, [], action_filter.with_settings(action_filter.load_gates(), settings.DEFAULTS['action_gates']))
        except Exception:
            return []


def _speaker_note(ctx):
    if not settings.load()['action_filter']:
        return ''
    gates = _gates()
    speakers = lw_state.load_conversation()
    if not gates or len(speakers) < 2:
        return ''
    offered = [{'function': {'name': name}} for name in gates]
    return action_filter.speaker_note(action_filter.filter_actions(offered, speakers, gates), speakers, gates)


def _extra_text(ctx):
    """Lines for the newest message: who may do what (groups), why an ambient talk started, what was just said nearby,
    topics the player asked this NPC about in an earlier talk, and the scene (time, place, weather; taken out of the
    system prompt so the cached part stays the same all talk)."""
    store = _last_store['store']
    messages = ctx.get('messages') or []
    system = messages[0].get('content') if messages and messages[0].get('role') == 'system' else ''
    producers = [  # each on its own: one failing must not take the scene (or the others) out of the reply
        lambda: (lambda scene: f"Current scene: {scene}" if scene else '')(layout.scene_text(system) if isinstance(system, str) else ''),
        lambda: child_line(lw_state.load_conversation()),
        lambda: _speaker_note(ctx),
        lambda: nearby.seed(lw_state.load_banter()),
        lambda: nearby.said_nearby(lw_state.load_said_nearby(), time.time()),
        lambda: _asked.notes(messages, _last_store['people'], store, lw_state.load_player_name() or 'The player', lw_state.load_today()),
    ]
    lines = []
    for produce in producers:
        try:
            lines.append(produce())
        except Exception as e:
            logging.getLogger('Mantella').warning(f"Living World: a newest-message line failed ({e}); the others are kept")
    return '\n'.join(line for line in lines if line)


def _knowledge_on(values) -> bool:
    """Knowledge is installed and on: it tells who has heard of the Dragonborn."""
    here = os.path.dirname(os.path.abspath(__file__))
    return values['knowledge_mode'] != 'off' and os.path.isdir(os.path.join(os.path.dirname(here), 'lw_knowledge'))


def _system_parts(parts, ctx):
    values = settings.load()
    rules = prompt_rules.load_rules(player_name=lw_state.load_player_name(), disabled=settings.disabled_rules(values))
    if rules != _logged_rules['text']:
        _logged_rules['text'] = rules
        logging.getLogger('Mantella').log(23, f"Living World: {len(rules.splitlines())} rule line(s) in the system prompt (~{len(rules) // 4} tokens)")
    keep = values['bio_examples']
    speakers = lw_state.load_conversation()
    if values['basic_bios'] and isinstance(parts.get('mantella'), str):
        parts = dict(parts, mantella=basic_bio.replace(parts['mantella'], speakers))
    ordered = layout.order_system(parts, rules, keep_examples=None if keep < 0 else keep)
    jobs = lw_state.jobs_text(speakers, _installed())
    if jobs:
        ordered['jobs'] = jobs
    if values['world_note']:
        try:
            note = world_note.text(speakers, lw_state.load_world(), lw_state.load_player_name(), skip_dragonborn=_knowledge_on(values))
        except Exception as e:
            note = ''
            logging.getLogger('Mantella').warning(f"Living World: the world note failed ({e}); left out")
        if note:
            ordered['world'] = note
    preview.record_system(ordered, _speaker_names())
    return ordered


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
    store = _store(ctx)
    if store is None:
        return False  # Mantella saves its own summaries
    speakers = lw_state.load_conversation()
    ctx = dict(ctx, language=getattr(ctx['summaries'], '_Summaries__language_name', 'English'),
               is_minor=lambda character: _is_minor(character, speakers))
    return memory.summarize(ctx, store)


def _dialogue_events(events, ctx):
    store = _store(ctx)
    if not store:
        return events
    ctx = dict(ctx, language=getattr(ctx['summaries'], '_Summaries__language_name', 'English'))
    return memory.compact_dialogue(events, ctx, store)


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
    store = _store(ctx)
    if not store:
        return text
    _last_store['people'] = [(c.name, c.ref_id) for c in ctx.get('characters') or []]
    values = settings.load()
    speakers = lw_state.load_conversation()
    today = lw_state.load_today()
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
    ctx = dict(ctx, today=today, player=lw_state.load_player_name() or 'the player', facts_for=facts_for,
               profile_seen=profile_seen, profile_overrides=settings.load_profile_overrides(),
               is_minor=lambda character: action_filter._int(speaker(character).get('minor'), 0) > 0)
    return memory.memory_text(text, ctx, store, values['memory_budget'], budget_for)


def register(api):
    api.on('system_parts', _system_parts)
    api.on('filter_tools', _filter_tools)
    api.on('extra_user_text', _extra_text)
    api.on('summarize', _summarize)
    api.on('memory_text', _memory_text)
    try:
        api.on('dialogue_events', _dialogue_events)
    except ValueError:  # an older Direct AI Connect has no such hook: long dialogue is summarized when the talk ends
        pass
    api.on('conversation_limit', lambda tokens: settings.load()['trim_after_tokens'] or tokens)
    update_check.check_in_background(settings.load()['update_check_days'])
    server_status.start()
    game_fn = lambda: _last_store['game']
    try:
        # four tabs of our own: Main Status, Player and NPC Data, Memory, Prompt Rules and Settings
        api.on('ui_page', lambda gr, config: ui_tab.build_pages(gr, api, config, game_fn))
    except ValueError:  # an older Mantella exe without tabs of their own: everything inside its one Living World tab
        api.on('ui_tab', lambda gr: ui_tab.build(gr, api, game_fn=game_fn))
