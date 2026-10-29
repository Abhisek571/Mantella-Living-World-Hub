"""The "Living World" tab in Mantella's settings UI: what each module does, what it costs per reply, the last prompt,
each NPC's memory and the Living World settings."""
import html
import json
import os
import re
import time

from . import data_io, lw_state, memory, memory_ui, preview, prompt_rules, settings, ui_help, ui_overrides

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


def module_status(name: str, installed: bool, values: dict, data_dir: str = lw_state.DATA_DIR,
                  extensions_dir: str = 'extensions') -> tuple[str, str]:
    """(level, text) for the Start here table: 'ok' (green), 'todo' (yellow, with the missing step) or 'off' (grey,
    not installed). Only what this tab can see is checked; a module with nothing to check is green once installed."""
    if not installed:
        return 'off', 'Not installed'
    if name == 'Integration Hub' and not os.path.isdir(data_dir):
        return 'todo', 'Needs: load a save with Living World enabled (no game data written yet), then run Setup in the MCM'
    if name == 'World' and not os.path.isfile(os.path.join(data_dir, 'world.json')):
        return 'todo', 'Needs: play a little with World enabled (no world data yet)'
    if name == 'Knowledge':
        if values.get('knowledge_mode') == 'off':
            return 'todo', 'Switched off in the settings below'
        if not os.path.isfile(os.path.join(extensions_dir, 'lw_knowledge', 'data', 'lore.sqlite')):
            return 'todo', 'Needs: its lore database (reinstall Knowledge)'
    return 'ok', 'Working'


COLORS = {'ok': '#22c55e', 'todo': '#eab308', 'off': '#9ca3af'}


def start_here_html(actions_dir: str, extensions_dir: str, values: dict, data_dir: str = lw_state.DATA_DIR) -> str:
    installed = set(installed_modules(actions_dir, extensions_dir))
    cell = 'style="padding:6px 10px;border-bottom:1px solid rgba(128,128,128,.3);vertical-align:top"'
    rows = []
    for name, _, does, todo in MODULES:
        level, text = module_status(name, name in installed, values, data_dir, extensions_dir)
        yes = f'<b style="color:{COLORS["ok"] if name in installed else COLORS["off"]}">{"Yes" if name in installed else "No"}</b>'
        rows.append(f'<tr><td {cell}><b>{html.escape(name)}</b></td><td {cell}>{yes}</td>'
                    f'<td {cell}><b style="color:{COLORS[level]}">{html.escape(text)}</b></td>'
                    f'<td {cell}>{html.escape(does)}</td><td {cell}>{html.escape(todo)}</td></tr>')
    head = ''.join(f'<th {cell} align="left">{h}</th>' for h in ('Module', 'Installed', 'Status', 'What it does', 'What to set'))
    return (ui_help.heading('Start here', 'Green: installed and nothing missing that this tab can check. Yellow: '
                            'installed, but a step is still needed. Grey: not installed. The tab checks files on disk '
                            'only; it cannot see in-game state such as whether Setup was run.')
            + f'<table style="width:100%;border-collapse:collapse"><tr>{head}</tr>{"".join(rows)}</table>'
            + '<p style="opacity:.8">Use the same model for conversations and summaries: the summary request then reads '
              'the cached conversation.</p>')


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


SETTING_HELP = {
    'action_filter': ('Fitting actions only', "Each NPC is offered only the actions that make sense for them (a guard is "
                      "not offered to follow you home). Fewer actions also means a shorter, cheaper prompt."),
    'story_control': ('Story-control limits', "Custom events from the N hotkey cannot rewrite the story: no instant "
                      "deaths, marriages or quest changes from one line of text."),
    'memory_budget': ('Memory for close NPCs', "How much each follower or close NPC remembers of you per conversation, "
                      "in tokens (about 3/4 of a word each). Newest memories are kept first; older ones are folded "
                      "into a short summary."),
    'memory_budget_stranger': ('Memory for everyone else', "The same for NPCs who are not close to you. Lower keeps "
                               "strangers cheap; they still remember the main things."),
    'lore_budget': ('Lore per reply (Knowledge)', "How much Skyrim lore Knowledge may add to one reply, in tokens. "
                    "Only lore the NPC would plausibly know is added."),
    'knowledge_mode': ('Knowledge mode', "full: each NPC's knowledge profile plus matching lore. profiles: only what "
                       "each NPC knows about, no lore text. off: Knowledge adds nothing."),
    'dragonborn_secret': ('Keep Dragonborn secret', "NPCs still hear that a Dragonborn exists, but nobody connects it "
                          "to you unless you tell them."),
    'trim_after_tokens': ('Save and trim long talks', "Once a talk passes this many tokens (8000 is about 6000 words), "
                          "its memory is saved, only the most recent quarter is kept, and the talk goes on. The NPC "
                          "may pause a moment. Keeps long talks fast and cheap. 0 = Mantella's own limit (90% of the "
                          "model's context); at least 4000."),
    'bio_examples': ('Example lines per bio', "How many example dialogue lines to keep from each bio. Fewer = cheaper "
                     "prompts; -1 keeps them all."),
    'disabled_rules': ('Rule files switched off', "Pick the prompt rule files to leave out (see the table above). Use "
                       "this to switch off one module's rules without uninstalling it."),
}


def build_status(gr, api, actions_dir: str = 'data/actions', extensions_dir: str = 'extensions', settings_path: str = settings.PATH) -> None:
    """Living World Main Status: module status, what each reply cost, the last prompt."""
    values = settings.load(settings_path)
    gr.HTML(start_here_html(actions_dir, extensions_dir, values))

    with gr.Accordion('Tokens and cache', open=False):
        gr.HTML(ui_help.heading('Tokens and cache', "Each reply's size and cost. Cache read: the part reused from the last "
                                "reply (the long bio and rules), billed at about a tenth. Cache written: stored for reuse "
                                "(the first reply costs a bit more). New: fresh text. Output: what the NPC said.",
                                'What each reply cost this session. Press Refresh after talking.'))
        summary = gr.Markdown(totals_text(api.usage_log()))
        table = gr.Dataframe(headers=TABLE_HEADERS, value=usage_table(api.usage_log()), interactive=False)
        gr.Button('Refresh').click(lambda: (totals_text(api.usage_log()), usage_table(api.usage_log())), outputs=[summary, table])

    with gr.Accordion('Prompt preview', open=False):
        gr.HTML(ui_help.heading('Prompt preview', "The parts of the last request and their size in tokens: the bio, "
                                "memory, rules, lore and so on. Use it to see why a reply was expensive or what an NPC "
                                "was told.", 'What the model received on the last reply, part by part. Fills in after a reply.'))
        shown = gr.Markdown(preview_text(preview.latest()))
        gr.Button('Refresh preview').click(lambda: preview_text(preview.latest()), outputs=[shown])


def build_settings(gr, config=None, rules_dir: str = 'data/prompt_rules', settings_path: str = settings.PATH) -> None:
    """Living World Prompt Rules and Settings, then Export / Import."""
    values = settings.load(settings_path)
    gr.HTML(ui_help.heading('Living World Prompt Rules and Settings', "Rule files are short instructions each module "
                            "adds to the prompt; the table shows their size. Settings apply from the next reply.",
                            'Hover the ? next to a setting to see what it does.'))
    def field(key, make):
        gr.HTML(ui_help.label(*SETTING_HELP[key]))
        return make()
    rule_files = sorted(set(prompt_rules.rule_token_counts(rules_dir)) | set(values['disabled_rules']))
    with gr.Accordion('Actions and story', open=True):
        use_filter = field('action_filter', lambda: gr.Checkbox(value=values['action_filter'], label='On'))
        story = field('story_control', lambda: gr.Checkbox(value=values['story_control'], label='On'))
    with gr.Accordion('Memory', open=False):
        memory_budget = field('memory_budget', lambda: gr.Number(value=values['memory_budget'], show_label=False, precision=0))
        stranger_budget = field('memory_budget_stranger', lambda: gr.Number(value=values['memory_budget_stranger'], show_label=False, precision=0))
        trim = field('trim_after_tokens', lambda: gr.Number(value=values['trim_after_tokens'], show_label=False, precision=0))
    with gr.Accordion('Knowledge', open=False):
        kmode = field('knowledge_mode', lambda: gr.Dropdown(choices=['full', 'profiles', 'off'], value=values['knowledge_mode'], show_label=False))
        lore_budget = field('lore_budget', lambda: gr.Number(value=values['lore_budget'], show_label=False, precision=0))
        secret = field('dragonborn_secret', lambda: gr.Checkbox(value=values['dragonborn_secret'], label='On'))
    with gr.Accordion('Prompt rules', open=False):
        rules = gr.Dataframe(headers=['Rule file', 'Tokens', 'In use'], value=rules_table(rules_dir, values), interactive=False)
        examples = field('bio_examples', lambda: gr.Number(value=values['bio_examples'], show_label=False, precision=0))
        off = field('disabled_rules', lambda: gr.Dropdown(choices=rule_files, value=list(values['disabled_rules']), multiselect=True, show_label=False))
    saved = gr.Markdown('')

    def save(f, s, m, l, o, e, sm, tr, ds, km):
        new = dict(values, action_filter=bool(f), story_control=bool(s), memory_budget=positive(m, settings.DEFAULTS['memory_budget']),
                   memory_budget_stranger=positive(sm, settings.DEFAULTS['memory_budget_stranger']),
                   trim_after_tokens=max(0, int(tr or 0)), dragonborn_secret=bool(ds),
                   knowledge_mode=km if km in ('full', 'profiles', 'off') else 'full',
                   lore_budget=positive(l, settings.DEFAULTS['lore_budget']), bio_examples=max(-1, int(e if e is not None else -1)), disabled_rules=[x.strip() for x in (o if isinstance(o, list) else str(o or '').split(',')) if str(x).strip()])
        settings.save(settings_path, new)
        values.update(new)
        return 'Saved. The next reply uses these settings.', rules_table(rules_dir, new)
    gr.Button('Save settings', variant='primary').click(save, inputs=[use_filter, story, memory_budget, lore_budget, off, examples, stranger_budget, trim, secret, kmode], outputs=[saved, rules])
    build_transfer(gr, config, settings_path)


def build_transfer(gr, config=None, settings_path: str = settings.PATH) -> None:
    """Export / Import: one zip, a folder per part; the user ticks what goes in and what comes back. Events that touch a
    File stay out of the API listing (show_api=False): Gradio 4.28 cannot describe a File there, so /info fails and every
    button on the page stops working."""
    paths = data_io.Paths(user=ui_overrides.user_folder(), hub_settings=settings_path)
    names = data_io.PART_NAMES
    pick_label = {v: k for k, v in names.items()}
    gr.HTML(ui_help.heading('Export and import', "Export packs the parts you tick into one zip, a folder per part "
                            "(overrides, player, memory per save, settings). Import reads a zip, shows what is inside, "
                            "and copies only what you tick. Every file it would replace is backed up first. API keys "
                            "are never exported.", 'Move or back up your overrides, memories and settings.'))
    with gr.Accordion('Export', open=False):
        worlds = memory_ui.saves(paths.conversations)
        out_parts = gr.CheckboxGroup(choices=[names[p] for p in data_io.PARTS], value=[names[p] for p in data_io.PARTS[:4]], label='Include')
        out_saves = gr.CheckboxGroup(choices=worlds, value=worlds, label='Saves (for memory)')
        out_file = gr.File(label='Your export', interactive=False)
        out_said = gr.Markdown('')

        def export(parts, saves):
            chosen = {pick_label[p] for p in parts or []}
            if not chosen:
                return None, 'Tick at least one part.'
            folder = os.path.join(paths.user, 'living_world_exports')
            os.makedirs(folder, exist_ok=True)
            path = data_io.export_zip(os.path.join(folder, time.strftime('LivingWorld-export-%Y%m%d-%H%M%S.zip')), paths, chosen, saves or [],
                                      player_description=ui_overrides.player_description(config) if 'player' in chosen else None)
            return path, ui_overrides._notify(gr, f"Exported to {path}. Download it below, or find it there.")
        gr.Button('Export').click(export, inputs=[out_parts, out_saves], outputs=[out_file, out_said], show_api=False)

    with gr.Accordion('Import', open=False):
        in_file = gr.File(label='Living World export (.zip)', file_types=['.zip'], type='filepath')
        in_parts = gr.CheckboxGroup(choices=[], label='Import these', visible=False)
        in_saves = gr.CheckboxGroup(choices=[], label='Saves (for memory)', visible=False)
        in_said = gr.Markdown('')
        sure = gr.Checkbox(visible=False)

        def inspect(path):
            if not path:
                return gr.update(visible=False), gr.update(visible=False), ''
            found = data_io.inspect_zip(path)
            if 'error' in found:
                return gr.update(visible=False), gr.update(visible=False), found['error']
            labels = [names[p] for p in found['parts']]
            return (gr.update(choices=labels, value=labels, visible=True),
                    gr.update(choices=found['saves'], value=found['saves'], visible=bool(found['saves'])),
                    f"Found: {', '.join(labels) or 'nothing Living World can use'}. Untick what you don't want, then Import.")

        def do_import(ok, path, parts, saves, *_):
            if not ok:
                return 'Not imported.'
            if not path:
                return 'Choose a zip first.'
            chosen = {pick_label[p] for p in parts or []}
            report = data_io.import_zip(path, paths, chosen, saves or [], os.path.join(paths.user, 'living_world_import_backups'))
            extra = ''
            if report['player_description'] and 'player' in chosen:
                ui_overrides.save_player_description(config, report['player_description'])
                extra = ' Player description set.'
            if 'overrides' in chosen:
                ui_overrides.request_reload(config)
            backup = f" {report['replaced']} replaced file(s) backed up to {report['backup']}." if report['replaced'] else ''
            return ui_overrides._notify(gr, f"Imported {report['files']} file(s).{extra}{backup} Used from the next conversation.")

        in_file.change(inspect, inputs=[in_file], outputs=[in_parts, in_saves, in_said], show_api=False)
        gr.Button('Import', variant='primary').click(do_import, inputs=[sure, in_file, in_parts, in_saves], outputs=[in_said], show_api=False,
                                                     js=ui_overrides._confirm_js('Import the ticked parts? Files they replace are backed up first.'))


def build_pages(gr, api, config, game_fn) -> None:
    """The four Living World tabs (Mantella exes with tabs of their own)."""
    with gr.Tab('Living World Main Status'):
        build_status(gr, api)
    ui_overrides.build_page(gr, config, game_fn)
    with gr.Tab('Living World Memory'):
        memory_ui.build(gr, config=config)
    with gr.Tab('Living World Prompt Rules and Settings'):
        build_settings(gr, config)


def build(gr, api, actions_dir: str = 'data/actions', extensions_dir: str = 'extensions', rules_dir: str = 'data/prompt_rules',
          settings_path: str = settings.PATH, game_fn=lambda: None) -> None:
    """Everything inside the one Living World tab, for an older Mantella exe without tabs of its own."""
    build_status(gr, api, actions_dir, extensions_dir, settings_path)
    memory_ui.build(gr)
    ui_overrides.build(gr, game_fn)
    build_settings(gr, None, rules_dir, settings_path)
