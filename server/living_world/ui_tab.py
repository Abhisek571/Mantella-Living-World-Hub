"""The "Living World" tab in Mantella's settings UI: what each module does, what it costs per reply, the last prompt,
each NPC's memory and the Living World settings."""
import html
import json
import math
import os
import re
import time

from . import data_io, lw_state, memory, memory_ui, preview, prompt_rules, settings, ui_help, ui_overrides, update_check

# (name, pattern of the action files it installs, or None if detected another way, what it does, what to set).
# Knowledge is found by its extension folder, Missives by its prompt rule (neither ships an action file).
MODULES = [
    ('Integration Hub', None, 'The core every other module uses: temperament, shared quiet times, pacing and these tabs.',
     'The Hub page of the MCM. With Arousal: press the Living World hotkey with nobody targeted once to run the setup.'),
    ('Followers', r'mantella_mlw_(?!w_|m_|k_)', 'Follower orders through Nether\'s Follower Framework, outfits, and noticing clothes you gave them.',
     'Nothing to set; follower actions only appear for party members.'),
    ('OStim Expansion', r'mantella_mae_', 'Scenes that unfold over time, favourite positions, bystanders who comment.',
     'Scene length and bystander chance in the MCM.'),
    ('Arousal', r'mantella_osla_', 'Arousal as a private mood for strangers; closeness unlocks bolder lines.',
     'Open groups (courtesans, succubus races) in its settings file. Needs Advanced Actions on in Mantella.'),
    ('Relationships', r'mantella_maras', "Marriage, affection and proposals (M.A.R.A.S), family ties (Relations Finder) and shared history (Lover's Ledger).",
     'Nothing to set; a marriage change asks you Yes or No first.'),
    ('World', r'mantella_mlww_', 'Fame, bounty, deeds and who knows whom; party banter; settling crime by talking.',
     'World page in the MCM; "What NPCs know about you" in the Settings tab.'),
    ('Knowledge', 'lw_knowledge', 'Limits what each NPC knows to what they plausibly would.',
     "Knowledge mode in the Settings tab: off, profiles only, or profiles and lore."),
    ('Missives', '40_missives.txt', 'Job posters and couriers who know about their own Missives jobs.',
     'Nothing to set.'),
]
# the module row of the map on Main Status
MAP_ROW = ['Followers', 'World', 'Knowledge', 'Missives', 'Relationships', 'Arousal', 'OStim Expansion']

TABLE_HEADERS = ['Time', 'Model', 'Cached', 'Cache write', 'New', 'Output', 'Cost $']


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


def model_name(config) -> tuple[str | None, str | None]:
    """(service, model) from Mantella's settings, or (None, None) when they are not reachable."""
    try:
        value = lambda key: config.definitions.get_config_value_definition(key).value
        return str(value('llm_api')), str(value('model'))
    except Exception:
        return None, None


def model_status(service: str | None, model: str | None, replies: int | None) -> tuple[str, str]:
    """The AI model box: green once a reply came back this session. Only the Native, cached service reports its replies to
    this tab, so other services show the model without a check."""
    if not model:
        return 'idle', 'Model not known yet'
    if service and 'Native' in service and replies is not None:
        return ('ok', f'{model}, replying') if replies else ('idle', f'{model}, no reply yet')
    return 'idle', f'{model}, not checked (only the Native, cached service reports replies)'


def advanced_actions(config) -> bool | None:
    """Mantella's Advanced Actions setting (tool calling), or None when the settings are not reachable."""
    try:
        return bool(config.definitions.get_config_value_definition('advanced_actions_enabled').value)
    except Exception:
        return None


def setup_done(data_dir: str | None = None) -> bool | None:
    """Whether the Hub setup (temperament) was run, as the game last wrote it; None before the game wrote it."""
    data_dir = data_dir or lw_state.DATA_DIR
    try:
        with open(os.path.join(data_dir, 'conversation.json'), 'rb') as f:
            value = (json.loads(lw_state.decode(f.read())).get('int') or {}).get('setup_done')
    except (OSError, ValueError, AttributeError):
        return None
    return bool(value) if isinstance(value, int) else None


def module_status(name: str, installed: bool, values: dict, data_dir: str | None = None,
                  extensions_dir: str = 'extensions', advanced: bool | None = None, others: set | None = None) -> tuple[str, str]:
    """(level, text) for the module map: 'ok' (green), 'todo' (yellow, with the missing step), 'bad' (red, cannot work
    as installed) or 'off' (grey, not installed). Only what this tab can see is checked; a module with nothing to
    check is green once installed. advanced: Mantella's Advanced Actions setting; others: the modules installed."""
    if not installed:
        return 'off', 'Not installed'
    data_dir = data_dir or lw_state.DATA_DIR
    if name == 'Integration Hub':
        if not os.path.isdir(data_dir):
            return 'todo', 'No game data yet: load a save with Living World enabled and talk to someone'
        if 'Arousal' in (others or ()) and setup_done(data_dir) is False:
            return 'todo', 'Setup not run yet: in game, press the Living World hotkey with nobody targeted'
    if name == 'World':
        if not os.path.isfile(os.path.join(data_dir, 'world.json')):
            return 'todo', 'No world data yet: play a little with World enabled'
        if not values.get('world_note', True):
            return 'todo', 'NPCs are not told your fame, bounty and deeds: switched off in the Settings tab'
        if advanced is False:
            return 'todo', 'Advanced Actions is off in Mantella: guards can only take a bounty payment, not a bribe or persuasion'
    if name == 'Arousal' and advanced is False:
        return 'todo', 'Advanced Actions is off in Mantella: appetite is never rated, so the satisfied and overwhelmed stages never start'
    if name == 'Knowledge':
        if values.get('knowledge_mode') == 'off':
            return 'todo', 'Switched off in the Settings tab'
        if not os.path.isfile(os.path.join(extensions_dir, 'lw_knowledge', 'data', 'lore.sqlite')):
            return 'bad', 'Its lore database is missing: reinstall Knowledge'
    return 'ok', 'Working'


COLORS = {'ok': '#22c55e', 'todo': '#eab308', 'bad': '#ef4444', 'off': '#9ca3af', 'idle': '#9ca3af'}
WORDS = {'ok': 'Working', 'todo': 'Needs a step', 'bad': 'Problem', 'off': 'Not installed', 'idle': 'Not checked yet'}


def _short(reason: str, limit: int = 30) -> str:
    """The part of a reason that fits in a map box (before the colon); the full text is in the hover and the list."""
    text = reason.split(':')[0].split('. ')[0].strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '\u2026'


def _svg_box(x: int, y: int, w: int, h: int, name: str, level: str, reason: str) -> str:
    color = COLORS[level]
    dash = ' stroke-dasharray="5 4"' if level == 'off' else ''
    faded = ' opacity="0.55"' if level == 'off' else ''
    sub = WORDS[level] if level == 'off' or reason == 'Working' else reason if len(reason) <= 32 else _short(reason, 32)
    return (f'<g{faded} style="cursor:help"><title>{html.escape(name)}: {html.escape(reason)}</title>'
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{color}" fill-opacity="0.12" stroke="{color}" stroke-width="1.2"{dash}/>'
            f'<rect x="{x}" y="{y}" width="5" height="{h}" rx="2" fill="{color}"/>'
            f'<text x="{x + 14}" y="{y + h / 2 - 8}" dominant-baseline="central" font-size="14" font-weight="600" fill="var(--body-text-color, currentColor)">{html.escape(name)}</text>'
            f'<text x="{x + 14}" y="{y + h / 2 + 10}" dominant-baseline="central" font-size="12" fill="var(--body-text-color-subdued, currentColor)">{html.escape(sub)}</text></g>')


def map_svg(chain: list[tuple[str, str, str]], hub: tuple[str, str], modules: list[tuple[str, str, str]]) -> str:
    """The module map: the chain (Skyrim, Mantella, Direct AI Connect, AI model) down the left, the Hub in the middle,
    one arm per module on the right. Hover a box for the full reason."""
    height = max(20 + len(modules) * 48, 20 + len(chain) * 78)
    cy = height // 2
    top = cy - (len(chain) * 78 - 30) // 2
    chain_y = [top + i * 78 for i in range(len(chain))]
    line = 'stroke="rgba(128,128,128,.7)" stroke-width="1.5"'
    parts = []
    for i, (name, level, reason) in enumerate(chain):
        parts.append(_svg_box(20, chain_y[i], 210, 48, name, level, reason))
        if i < len(chain) - 1:
            parts.append(f'<line x1="125" y1="{chain_y[i] + 48}" x2="125" y2="{chain_y[i + 1]}" {line}/>')
    hx, r = 335, 50
    connect_y = chain_y[2] + 24 if len(chain) > 2 else cy
    parts.append(f'<path d="M230 {connect_y} Q{hx - r - 25} {cy} {hx - r} {cy}" fill="none" {line}/>')
    count = len(modules)
    for i, (name, level, reason) in enumerate(modules):
        y = 10 + i * 48
        dash = ' stroke-dasharray="4 4"' if level == 'off' else ''
        # each arm leaves the circle's edge at its own angle, spread evenly over the right side, then curves to its box
        angle = math.radians(-60 + 120 * i / (count - 1)) if count > 1 else 0.0
        sx, sy = hx + r * math.cos(angle), cy + r * math.sin(angle)
        parts.append(f'<path d="M{sx:.1f} {sy:.1f} C{sx + 45 * math.cos(angle):.1f} {sy + 45 * math.sin(angle):.1f} '
                     f'405 {y + 20} 455 {y + 20}" fill="none" {line}{dash}/>')
        parts.append(_svg_box(455, y, 215, 40, name, level, reason))
    level, reason = hub
    color = COLORS[level]
    text = 'text-anchor="middle" dominant-baseline="central" font-size="14" font-weight="600" fill="var(--body-text-color, currentColor)"'
    parts.append(f'<g style="cursor:help"><title>Integration Hub: {html.escape(reason)}</title>'
                 f'<circle cx="{hx}" cy="{cy}" r="{r}" fill="{color}" fill-opacity="0.15" stroke="{color}" stroke-width="2"/>'
                 f'<text x="{hx}" y="{cy - 9}" {text}>Integration</text><text x="{hx}" y="{cy + 9}" {text}>Hub</text></g>')
    return (f'<svg viewBox="0 0 680 {height}" width="100%" style="max-width:760px;display:block;margin:4px auto" role="img" '
            f'aria-label="Module map">{"".join(parts)}</svg>')


def statuses(actions_dir: str, extensions_dir: str, values: dict, data_dir: str | None = None,
             advanced: bool | None = None) -> dict[str, tuple[str, str]]:
    installed = set(installed_modules(actions_dir, extensions_dir))
    return {name: module_status(name, name in installed, values, data_dir, extensions_dir, advanced, installed)
            for name, *_ in MODULES}


UPDATE_COLOR = '#60a5fa'  # updates are news, not a problem: their own colour in the list, nothing on the map


def update_lines(updates: dict | None, found: dict[str, tuple[str, str]]) -> list[tuple[str, str]]:
    """(module, text) for each installed module with a newer version on Nexus, in map order."""
    order = ['Integration Hub'] + MAP_ROW
    return [(name, f"Update {u['latest']} is on Nexus (you have {u['installed']})")
            for name, u in sorted((updates or {}).items(), key=lambda kv: order.index(kv[0]) if kv[0] in order else 99)
            if found.get(name, ('off',))[0] != 'off']


def start_here_html(actions_dir: str, extensions_dir: str, values: dict, data_dir: str | None = None,
                    advanced: bool | None = None, updates: dict | None = None,
                    model: tuple[str, str] | None = None) -> str:
    """The module map (the game, Mantella, the Hub and each module, coloured by status; hover a box for the reason),
    then what needs attention in plain words."""
    data_dir = data_dir or lw_state.DATA_DIR
    found = statuses(actions_dir, extensions_dir, values, data_dir, advanced)
    game = ('ok', 'Game data found') if os.path.isdir(data_dir) else \
        ('todo', 'No game data yet: load a save with Living World enabled')
    connect = ('ok', 'Running: this page is part of it') if advanced is not False else \
        ('todo', "Advanced Actions is off. Turn it on in Mantella's Actions tab: Arousal's appetite rating and "
                 "World's bribes and persuasion need it")
    mantella = ('ok', 'Running: this page is part of it')
    chain = [('Skyrim', *game), ('Mantella', *mantella), ('Direct AI Connect', *connect),
             ('AI model', *(model or ('idle', 'Model not known yet')))]
    picture = map_svg(chain, found['Integration Hub'], [(name, *found[name]) for name in MAP_ROW])
    legend = ''.join(f'<span style="display:inline-flex;align-items:center;gap:4px;margin-right:12px">'
                     f'<span style="width:10px;height:10px;border-radius:2px;background:{COLORS[k]}"></span>{WORDS[k]}</span>'
                     for k in ('ok', 'todo', 'bad', 'off', 'idle'))
    todo = [(n, lv, why) for n, (lv, why) in [('Skyrim', game), ('Mantella - Direct AI Connect', connect)] + list(found.items())
            if lv in ('todo', 'bad')]
    if advanced is False:  # said once, on Direct AI Connect; the modules keep it as their hover reason
        todo = [t for t in todo if t[0] == 'Mantella - Direct AI Connect' or not t[2].startswith('Advanced Actions')]
    todo.sort(key=lambda t: t[1] != 'bad')
    news = update_lines(updates, found)
    if todo or news:
        items = ''.join(f'<li style="margin:3px 0"><b style="color:{COLORS[lv]}">{html.escape(n)}</b>: {html.escape(why)}</li>'
                        for n, lv, why in todo)
        items += ''.join(f'<li style="margin:3px 0"><b style="color:{UPDATE_COLOR}">{html.escape(n)}</b>: '
                         f'<span style="color:{UPDATE_COLOR}">{html.escape(text)}</span></li>' for n, text in news)
        attention = f'<h3 style="margin:14px 0 4px">What needs attention</h3><ul style="margin:0;padding-left:20px">{items}</ul>'
    else:
        attention = f'<p style="margin:14px 0 0"><b style="color:{COLORS["ok"]}">Everything installed is working.</b></p>'
    return (ui_help.heading('Module map', 'Green: installed and nothing missing that this tab can check. Yellow: installed, '
                            'but a step is still needed. Red: installed but cannot work as it is. Grey: not installed. '
                            'The tab checks files and settings only; it cannot see everything in game.',
                            'Hover a box to see why it has its colour.')
            + picture
            + f'<div style="font-size:.85em;margin-top:8px;opacity:.85">{legend}</div>' + attention)


def details_html() -> str:
    cell = 'style="padding:6px 10px;border-bottom:1px solid rgba(128,128,128,.3);vertical-align:top"'
    rows = ''.join(f'<tr><td {cell}><b>{html.escape(n)}</b></td><td {cell}>{html.escape(d)}</td><td {cell}>{html.escape(t)}</td></tr>'
                   for n, _, d, t in MODULES)
    head = ''.join(f'<th {cell} align="left">{h}</th>' for h in ('Module', 'What it does', 'What to set'))
    return f'<table style="width:100%;border-collapse:collapse"><tr>{head}</tr>{rows}</table>'


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
    return [[name, count, 'No' if name in off else 'Yes'] for name, count in prompt_rules.rule_token_counts(rules_dir).items()]


UPDATE_CHECK_WHY = ("Living World is new, so this check is only here until the modules have been in use long enough to "
                    "be sure there are no bugs left in the Living World system; after that it will be off by default (0 days). It asks "
                    "Nexus's public API for the installed modules' versions, sending only their Nexus IDs (no account or key).")
# key: (label, help shown under the field)
SETTING_HELP = {
    'action_filter': ('Offer only fitting actions', "Each NPC is offered only the actions that make sense for them (a "
                      "guard is not offered to follow you home). Fewer actions also means a shorter, cheaper prompt."),
    'story_control': ('Limit what custom events can change', "Custom events from the N hotkey cannot rewrite the story: "
                      "no instant deaths, marriages or quest changes from one line of text."),
    'world_note': ('Tell NPCs what they would know about you', "With World: your fame, bounty and deeds, only where word "
                   "would have reached them (their hold, their guild, people involved). A few lines, cached."),
    'basic_bios': ('Basic bio for NPCs with no bio', "Mantella only knows the name of NPCs that are not in its list. "
                   "This gives them a few lines from their race, job and home instead. Your own overrides always win."),
    'memory_budget': ('Memory for close NPCs (tokens)', "How much each follower or close NPC remembers of you per "
                      "conversation; a token is about 3/4 of a word. Newest memories first, older ones folded into a summary."),
    'memory_budget_stranger': ('Memory for everyone else (tokens)', "The same for NPCs who are not close to you. Lower "
                               "keeps strangers cheap; they still remember the main things."),
    'trim_after_tokens': ('Save and trim talks longer than (tokens)', "Past this size (8000 is about 6000 words) the "
                          "memory is saved and only the newest quarter of the talk is kept; the NPC may pause a moment. "
                          "0 = Mantella's own limit (90% of the model's context)."),
    'knowledge_mode': ('Knowledge', "Profiles and lore: what each NPC knows about, plus matching Skyrim lore. Profiles "
                       "only: no lore text. Off: Knowledge adds nothing."),
    'lore_budget': ('Lore per reply (tokens)', "How much Skyrim lore Knowledge may add to one reply. Only lore the NPC "
                    "would plausibly know is added."),
    'dragonborn_secret': ('Keep Dragonborn secret', "NPCs still hear that a Dragonborn exists, but nobody connects it to "
                          "you unless you tell them."),
    'bio_examples': ('Example lines kept from each bio', "Stock bios end with example lines. Fewer means cheaper prompts; "
                     "All keeps them all."),
    'update_check_days': ('Check for module updates every (days)', "3 days is recommended; once a week (7) is also fine. 0 = never. "
                          "A newer version of an installed module shows on Main Status."),
    'disabled_rules': ('Rule files switched off', "Pick rule files to leave out (sizes in the table above), for example "
                       "to switch off one module's rules without uninstalling it."),
}
KNOWLEDGE_MODES = {'Profiles and lore': 'full', 'Profiles only': 'profiles', 'Off': 'off'}
EXAMPLES = ['All', 'None', '1', '2', '3', '5']


def examples_choice(value: int) -> str:
    return 'All' if value < 0 else 'None' if value == 0 else str(value) if str(value) in EXAMPLES else str(value)


def examples_value(choice) -> int:
    if choice in (None, 'All'):
        return -1
    if choice == 'None':
        return 0
    try:
        return max(0, int(choice))
    except (TypeError, ValueError):
        return -1


def build_status(gr, api, actions_dir: str = 'data/actions', extensions_dir: str = 'extensions', settings_path: str = settings.PATH,
                 config=None) -> None:
    """Living World Main Status: the module map, what each reply cost, the last prompt."""
    def page():
        values = settings.load(settings_path)
        return start_here_html(actions_dir, extensions_dir, values, advanced=advanced_actions(config),
                               updates=update_check.outdated() if values['update_check_days'] > 0 else None,
                               model=model_status(*model_name(config), len(api.usage_log())))
    shown = gr.HTML(page)  # a function: drawn on every page load, so a check that finished after startup shows
    with gr.Row():
        gr.Button('Check again', size='sm', scale=0, min_width=140).click(page, outputs=[shown])
    with gr.Accordion('What each module does', open=False):
        gr.HTML(details_html())

    with gr.Accordion('Tokens and cost', open=False):
        gr.HTML(ui_help.heading('Tokens and cost', "Each reply's size and cost. Cached: the part reused from the last "
                                "reply (the long bio and rules), billed at about a tenth. Cache write: stored for reuse "
                                "(the first reply costs a bit more). New: fresh text. Output: what the NPC said.",
                                'What each reply cost this session. Press Refresh after talking.'))
        summary = gr.Markdown(totals_text(api.usage_log()))
        table = gr.Dataframe(headers=TABLE_HEADERS, value=usage_table(api.usage_log()), interactive=False,
                             visible=bool(api.usage_log()))  # an empty grid looks broken
        gr.Button('Refresh', size='sm').click(
            lambda: (totals_text(api.usage_log()), gr.update(value=usage_table(api.usage_log()), visible=bool(api.usage_log()))),
            outputs=[summary, table])

    with gr.Accordion('Prompt preview', open=False):
        gr.HTML(ui_help.heading('Prompt preview', "The parts of the last request and their size in tokens: the bio, "
                                "memory, rules, lore and so on. Use it to see why a reply was expensive or what an NPC "
                                "was told.", 'What the model received on the last reply, part by part. Fills in after a reply.'))
        shown = gr.Markdown(preview_text(preview.latest()))
        gr.Button('Refresh', size='sm').click(lambda: preview_text(preview.latest()), outputs=[shown])


def build_settings(gr, config=None, rules_dir: str = 'data/prompt_rules', settings_path: str = settings.PATH) -> None:
    """Living World Prompt Rules and Settings, then Export / Import."""
    values = settings.load(settings_path)
    gr.HTML(ui_help.heading('Living World Prompt Rules and Settings', "Rule files are short instructions each module "
                            "adds to the prompt; the table shows their size. Settings apply from the next reply.",
                            'Change what you like, then Save settings at the bottom. Applies from the next reply.'))
    # values are functions: Gradio calls them on every page load, so a reloaded page (or a second window) shows what is
    # saved now, not what was saved when Mantella started, and Save settings never writes old values back
    now = lambda: settings.load(settings_path)
    current = lambda key: (lambda: now()[key])
    check = lambda key: gr.Checkbox(value=current(key), label=SETTING_HELP[key][0], info=SETTING_HELP[key][1])
    number = lambda key: gr.Number(value=current(key), label=SETTING_HELP[key][0], info=SETTING_HELP[key][1], precision=0, minimum=0)
    rule_files = sorted(set(prompt_rules.rule_token_counts(rules_dir)) | set(values['disabled_rules']))
    with gr.Accordion('What NPCs are told', open=True):
        use_filter = check('action_filter')
        story = check('story_control')
        world = check('world_note')
        basic = check('basic_bios')
        gr.HTML(ui_help.label(SETTING_HELP['update_check_days'][0], UPDATE_CHECK_WHY))
        updates = gr.Number(value=current('update_check_days'), show_label=False, info=SETTING_HELP['update_check_days'][1],
                            precision=0, minimum=0)
    with gr.Accordion('Memory', open=False):
        with gr.Row():
            memory_budget = number('memory_budget')
            stranger_budget = number('memory_budget_stranger')
        trim = number('trim_after_tokens')
    with gr.Accordion('Knowledge', open=False):
        mode_label = lambda: next((k for k, v in KNOWLEDGE_MODES.items() if v == now()['knowledge_mode']), 'Profiles and lore')
        kmode = gr.Radio(choices=list(KNOWLEDGE_MODES), value=mode_label, label=SETTING_HELP['knowledge_mode'][0], info=SETTING_HELP['knowledge_mode'][1])
        lore_budget = number('lore_budget')
        secret = check('dragonborn_secret')
    with gr.Accordion('Prompt rules', open=False):
        rules = gr.Dataframe(headers=['Rule file', 'Tokens', 'In use'], value=lambda: rules_table(rules_dir, now()), interactive=False)
        examples = gr.Dropdown(choices=EXAMPLES, value=lambda: examples_choice(now()['bio_examples']), allow_custom_value=True,
                               label=SETTING_HELP['bio_examples'][0], info=SETTING_HELP['bio_examples'][1])
        off = gr.Dropdown(choices=rule_files, value=lambda: list(now()['disabled_rules']), multiselect=True,
                          label=SETTING_HELP['disabled_rules'][0], info=SETTING_HELP['disabled_rules'][1])
    saved = gr.Markdown('')

    def save(f, s, wn, bb, m, l, o, e, sm, tr, ds, km, uc):
        new = dict(now(), action_filter=bool(f), story_control=bool(s), world_note=bool(wn), basic_bios=bool(bb),
                   update_check_days=max(0, int(uc or 0)),
                   memory_budget=positive(m, settings.DEFAULTS['memory_budget']),
                   memory_budget_stranger=positive(sm, settings.DEFAULTS['memory_budget_stranger']),
                   trim_after_tokens=max(0, int(tr or 0)), dragonborn_secret=bool(ds),
                   knowledge_mode=KNOWLEDGE_MODES.get(km, km if km in ('full', 'profiles', 'off') else 'full'),
                   lore_budget=positive(l, settings.DEFAULTS['lore_budget']), bio_examples=examples_value(e),
                   disabled_rules=[x.strip() for x in (o if isinstance(o, list) else str(o or '').split(',')) if str(x).strip()])
        settings.save(settings_path, new)
        return ui_overrides._notify(gr, 'Saved. The next reply uses these settings.'), rules_table(rules_dir, new)
    gr.Button('Save settings', variant='primary').click(
        save, inputs=[use_filter, story, world, basic, memory_budget, lore_budget, off, examples, stranger_budget, trim, secret, kmode, updates],
        outputs=[saved, rules])
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
        build_status(gr, api, config=config)
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
