"""Mantella Living World: the Integration Hub's side inside Mantella, loaded by Mantella - Direct AI Connect."""
import logging
import time

from . import action_filter, asked_before, layout, lw_state, memory, nearby, preview, prompt_rules, settings, ui_overrides, ui_tab

_logged_rules = {'text': None}
_last_store: dict = {'store': None, 'people': [], 'game': None}
_asked = asked_before.Tracker()


def _speaker_names() -> list[str]:
    return [s.get('name', '?') for s in lw_state.load_conversation()]


def _filter_tools(tools, ctx):
    values = settings.load()
    gates = action_filter.load_gates()
    if values['action_filter']:
        tools = action_filter.filter_actions(tools, lw_state.load_conversation(), gates)
    if values['short_actions']:
        tools = action_filter.shorten(tools, gates)
    if not (ctx or {}).get('keyword_actions'):  # Direct AI Connect also asks which "Name:" keywords may fire
        preview.record_tools(len(tools), _speaker_names())
    return tools


def _speaker_note(ctx):
    if not settings.load()['action_filter']:
        return ''
    gates = action_filter.load_gates()
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
        lambda: _speaker_note(ctx),
        lambda: nearby.seed(lw_state.load_banter()),
        lambda: nearby.said_nearby(lw_state.load_said_nearby(), time.time()),
        lambda: _asked.notes(messages, _last_store['people'], store, lw_state.load_player_name() or 'The player'),
    ]
    lines = []
    for produce in producers:
        try:
            lines.append(produce())
        except Exception as e:
            logging.getLogger('Mantella').warning(f"Living World: a newest-message line failed ({e}); the others are kept")
    return '\n'.join(line for line in lines if line)


def _system_parts(parts, ctx):
    values = settings.load()
    rules = prompt_rules.load_rules(player_name=lw_state.load_player_name(), disabled=settings.disabled_rules(values))
    if rules != _logged_rules['text']:
        _logged_rules['text'] = rules
        logging.getLogger('Mantella').log(23, f"Living World: {len(rules.splitlines())} rule line(s) in the system prompt (~{len(rules) // 4} tokens)")
    keep = values['bio_examples']
    ordered = layout.order_system(parts, rules, keep_examples=None if keep < 0 else keep)
    jobs = lw_state.jobs_text(lw_state.load_conversation())
    if jobs:
        ordered['jobs'] = jobs
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
    ctx = dict(ctx, language=getattr(ctx['summaries'], '_Summaries__language_name', 'English'))
    return memory.summarize(ctx, store)


def _memory_text(text, ctx):
    store = _store(ctx)
    if not store:
        return text
    _last_store['people'] = [(c.name, c.ref_id) for c in ctx.get('characters') or []]
    values = settings.load()
    close = {s.get('name') for s in lw_state.load_conversation() if s.get('close') or s.get('follower')}
    budget_for = lambda c: values['memory_budget'] if c.name in close else values['memory_budget_stranger']
    return memory.memory_text(text, ctx, store, values['memory_budget'], budget_for)


def register(api):
    api.on('system_parts', _system_parts)
    api.on('filter_tools', _filter_tools)
    api.on('extra_user_text', _extra_text)
    api.on('summarize', _summarize)
    api.on('memory_text', _memory_text)
    api.on('conversation_limit', lambda tokens: settings.load()['trim_after_tokens'] or tokens)
    game_fn = lambda: _last_store['game']
    try:
        # four tabs of our own: Main Status, Player and NPC Data, Memory, Prompt Rules and Settings
        api.on('ui_page', lambda gr, config: ui_tab.build_pages(gr, api, config, game_fn))
    except ValueError:  # an older Mantella exe without tabs of their own: everything inside its one Living World tab
        api.on('ui_tab', lambda gr: ui_tab.build(gr, api, game_fn=game_fn))
