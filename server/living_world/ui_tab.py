"""The "Living World" tab in Mantella's settings UI: what each module does, what it costs per reply, the last prompt,
each NPC's memory and the Living World settings."""
import json
import os
import re
import time

from . import memory, preview, prompt_rules, settings, ui_overrides

# (name, pattern of the action files it installs, or None if detected another way, what it does, what to set).
# Knowledge is found by its extension folder, Missives by its prompt rule (neither ships an action file).
MODULES = [
    ('Integration Hub', None, 'The core every other module uses: setup, temperament, shared quiet times and this tab.',
     'Run the setup once from the MCM (Mantella Living World > Setup).'),
    ('Followers', r'mantella_mlw_(?!w_|m_|k_)', 'Follower orders through Nether\'s Follower Framework, outfits, and noticing clothes you gave them.',
     'Nothing to set; follower actions only appear for party members.'),
    ('OStim Expansion', r'mantella_mae_', 'Scenes that unfold over time, favourite positions, bystanders who comment.',
     'Scene length and bystander chance in the MCM.'),
    ('Arousal', r'mantella_osla_', 'Arousal as a private mood for strangers; closeness unlocks bolder lines.',
     'Open groups (courtesans, succubus races) in its settings file.'),
    ('Relationships', r'mantella_maras', "Marriage, affection and proposals (M.A.R.A.S), family ties (Relations Finder) and shared history (Lover's Ledger).",
     'Nothing to set; a marriage change asks you Yes or No first.'),
    ('World', r'mantella_mlww_', 'Fame, bounty, war side and who knows whom; settling crime by talking.',
     'World page in the MCM.'),
    ('Knowledge', 'lw_knowledge', 'Limits what each NPC knows to what they plausibly would.',
     "Knowledge mode in this tab's settings: off, profiles only, or profiles and lore."),
    ('Missives', '40_missives.txt', 'Job posters and couriers who know about their own Missives jobs.',
     'Nothing to set.'),
]

TABLE_HEADERS = ['Time', 'Model', 'Cache read', 'Cache written', 'New', 'Output', 'Cost ($)']


def installed_modules(actions_dir: str = 'data/actions', extensions_dir: str = 'extensions') -> list[str]:
    """Living World modules present, from the action files they install (Knowledge: its extension folder)."""
    try:
        files = os.listdir(actions_dir)
    except OSError:
        files = []
    found = []
    for name, pattern, _, _ in MODULES:
        if pattern is None:
            found.append(name)  # this tab ships with the Hub
        elif name == 'Knowledge':
            if os.path.isdir(os.path.join(extensions_dir, pattern)):
                found.append(name)
        elif name == 'Missives':
            if os.path.isfile(os.path.join(os.path.dirname(actions_dir), 'prompt_rules', pattern)):
                found.append(name)
        elif any(re.match(pattern, f) for f in files):
            found.append(name)
    return found


def reply_cost(entry: dict) -> float | None:
    """Dollar cost of one reply, as priced by the AI connector (None when it has no price for the model)."""
    return entry.get('cost')


def usage_table(log: list[dict]) -> list[list]:
    rows = []
    for entry in log:
        rows.append([time.strftime('%H:%M:%S', time.localtime(entry.get('time', 0))), entry.get('model', ''),
                     entry.get('cache_read', 0), entry.get('cache_write', 0), entry.get('uncached', 0),
                     entry.get('output', 0), reply_cost(entry)])
    return rows


def usage_totals(log: list[dict]) -> dict:
    totals = {key: sum(entry.get(key, 0) for entry in log) for key in ('cache_read', 'cache_write', 'uncached', 'output')}
    totals['cost'] = sum(cost for cost in (reply_cost(entry) for entry in log) if cost is not None)
    span_hours = (log[-1].get('time', 0) - log[0].get('time', 0)) / 3600 if len(log) > 1 else 0
    totals['per_hour'] = totals['cost'] / span_hours if span_hours >= 0.25 else None
    totals['replies'] = len(log)
    return totals


def start_here_text(actions_dir: str, extensions_dir: str) -> str:
    installed = set(installed_modules(actions_dir, extensions_dir))
    lines = ['## Start here', '', '| Module | Installed | What it does | What to set |', '|---|---|---|---|']
    for name, _, does, settings in MODULES:
        lines.append(f"| {name} | {'Yes' if name in installed else 'No'} | {does} | {settings} |")
    lines += ['', 'Use the same model for conversations and summaries: the summary request then reads the cached conversation.']
    return '\n'.join(lines)


def totals_text(log: list[dict]) -> str:
    if not log:
        return 'No replies yet this session. Talk to someone, then press Refresh.'
    t = usage_totals(log)
    per_hour = f", about ${t['per_hour']:.2f} per hour" if t['per_hour'] is not None else ''
    return (f"{t['replies']} replies: {t['cache_read']:,} tokens read from cache, {t['cache_write']:,} written, "
            f"{t['uncached']:,} new, {t['output']:,} output. Cost ${t['cost']:.4f}{per_hour}.")


def preview_text(p: dict) -> str:
    if not p.get('parts'):
        return 'Nothing sent yet this session.'
    who = ', '.join(p.get('speakers') or []) or 'unknown'
    lines = [f"Last request ({who}): {p['total']:,} tokens of system prompt, {p.get('tools', 0)} actions offered.", '',
             '| Part | Tokens |', '|---|---|']
    lines += [f"| {name} | {count:,} |" for name, count in p['parts']]
    return '\n'.join(lines)


def memory_names(store) -> list[str]:
    try:
        return sorted(f[:-5] for f in os.listdir(store.root) if f.endswith('.json'))
    except (OSError, AttributeError):
        return []


def _split_name(name: str) -> tuple[str, str]:
    npc, _, ref = name.rpartition(' - ')
    return npc, ref


def memory_fields(store, name: str) -> tuple[str, str, str]:
    """(feeling, recent entries as JSON, long-term sections as JSON) for the editor."""
    memory = store.load(*_split_name(name))
    recent = [{k: v for k, v in e.items() if k != 'shared'} for e in memory['recent']]
    return memory['feeling'], json.dumps(recent, ensure_ascii=False, indent=1), json.dumps(memory['long_term'], ensure_ascii=False, indent=1)


def save_memory_fields(store, name: str, feeling: str, recent_json: str, long_term_json: str) -> str:
    try:
        recent, long_term = json.loads(recent_json), json.loads(long_term_json)
        if not isinstance(recent, list) or not isinstance(long_term, dict):
            raise ValueError('recent must be a list and long-term a set of sections')
    except ValueError as e:
        return f"Not saved: {e}"
    npc, ref = _split_name(name)
    # merged into the file as it is now: asked-before data (and anything not in the editor) stays
    current = store.load(npc, ref)
    edited = memory.clean({'recent': recent, 'long_term': long_term, 'feeling': feeling.strip()})
    store.save(npc, ref, dict(current, recent=edited['recent'], long_term=edited['long_term'], feeling=edited['feeling']))
    return f"Saved {npc}'s memory."


def positive(value, default: int) -> int:
    """A whole number above 0 from a settings field, else the default."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def rules_table(rules_dir: str, values: dict) -> list[list]:
    off = settings.disabled_rules(values)
    return [[name, count, 'off' if name in off else 'on'] for name, count in prompt_rules.rule_token_counts(rules_dir).items()]


def build(gr, api, actions_dir: str = 'data/actions', extensions_dir: str = 'extensions', store_fn=lambda: None,
          rules_dir: str = 'data/prompt_rules', settings_path: str = settings.PATH, game_fn=lambda: None) -> None:
    """Builds the sections inside the Living World tab."""
    gr.Markdown(start_here_text(actions_dir, extensions_dir))
    gr.Markdown('## Tokens and cache')
    summary = gr.Markdown(totals_text(api.usage_log()))
    table = gr.Dataframe(headers=TABLE_HEADERS, value=usage_table(api.usage_log()), interactive=False)
    refresh = gr.Button('Refresh')
    refresh.click(lambda: (totals_text(api.usage_log()), usage_table(api.usage_log())), outputs=[summary, table])

    gr.Markdown('## Prompt preview')
    shown = gr.Markdown(preview_text(preview.latest()))
    gr.Button('Refresh preview').click(lambda: preview_text(preview.latest()), outputs=[shown])

    gr.Markdown('## Memory')
    who = gr.Dropdown(choices=memory_names(store_fn()), label='NPC', interactive=True)
    feeling = gr.Textbox(label='How they feel about the player')
    recent = gr.Textbox(label='Recent memories (JSON)', lines=8)
    long_term = gr.Textbox(label='Long-term sections (JSON)', lines=4)
    status = gr.Markdown('')
    who.change(lambda name: memory_fields(store_fn(), name) if name and store_fn() else ('', '[]', '{}'), inputs=[who], outputs=[feeling, recent, long_term])
    gr.Button('Save memory').click(lambda name, f, r, l: save_memory_fields(store_fn(), name, f, r, l) if name and store_fn() else 'Pick an NPC first.',
                                   inputs=[who, feeling, recent, long_term], outputs=[status])
    gr.Button('Refresh list').click(lambda: gr.update(choices=memory_names(store_fn())), outputs=[who])

    ui_overrides.build(gr, game_fn)

    gr.Markdown('## Prompt rules and settings')
    values = settings.load(settings_path)
    rules = gr.Dataframe(headers=['Rule file', 'Tokens', 'In use'], value=rules_table(rules_dir, values), interactive=False)
    use_filter = gr.Checkbox(value=values['action_filter'], label='Offer each NPC only the actions that fit them')
    story = gr.Checkbox(value=values['story_control'], label='Story-control limits for custom events')
    memory_budget = gr.Number(value=values['memory_budget'], label='Memory tokens per conversation (close NPCs and followers)', precision=0)
    stranger_budget = gr.Number(value=values['memory_budget_stranger'], label='Memory tokens for everyone else', precision=0)
    lore_budget = gr.Number(value=values['lore_budget'], label='Lore tokens per reply (Knowledge)', precision=0)
    kmode = gr.Dropdown(choices=['full', 'profiles', 'off'], value=values['knowledge_mode'], label='Knowledge: full (profiles and lore), profiles only, or off')
    secret = gr.Checkbox(value=values['dragonborn_secret'], label='Keep my Dragonborn identity secret (Knowledge)')
    trim = gr.Number(value=values['trim_after_tokens'], label='Save and trim a talk after this many tokens (0 = off, at least 4000)', precision=0)
    examples = gr.Number(value=values['bio_examples'], label='Example dialogue lines kept per bio (-1 = all)', precision=0)
    off = gr.Textbox(value=', '.join(values['disabled_rules']), label='Rule files switched off (comma separated)')
    saved = gr.Markdown('')

    def save(f, s, m, l, o, e, sm, tr, ds, km):
        new = dict(values, action_filter=bool(f), story_control=bool(s), memory_budget=positive(m, settings.DEFAULTS['memory_budget']),
                   memory_budget_stranger=positive(sm, settings.DEFAULTS['memory_budget_stranger']),
                   trim_after_tokens=max(0, int(tr or 0)), dragonborn_secret=bool(ds),
                   knowledge_mode=km if km in ('full', 'profiles', 'off') else 'full',
                   lore_budget=positive(l, settings.DEFAULTS['lore_budget']), bio_examples=max(-1, int(e if e is not None else -1)), disabled_rules=[x.strip() for x in (o or '').split(',') if x.strip()])
        settings.save(settings_path, new)
        values.update(new)
        return 'Saved. The next reply uses these settings.', rules_table(rules_dir, new)
    gr.Button('Save settings').click(save, inputs=[use_filter, story, memory_budget, lore_budget, off, examples, stranger_budget, trim, secret, kmode], outputs=[saved, rules])
