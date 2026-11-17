"""The Absolute commands section of the Events page: the commands in force per save character and what each one made
its NPCs forget, and the three command settings. Releasing a command is done per NPC on the NPCs page (Commands)."""
import html

from . import command, memory, memory_ui, settings, ui_help, ui_overrides


def _when(record: dict) -> str:
    given = command._float(record.get('given'))
    day = f"day {int(given) + memory.MANTELLA_DAY}" if given >= 0 else 'an unknown day'
    if command._float(record.get('until')) > 0:
        return f"given on {day}, ends after {record['hours']:g} game hours"
    return f"given on {day}, until removed"


def commands_html(records: list[dict]) -> str:
    if not records:
        return '<div style="opacity:.6">No absolute commands in this save.</div>'
    items = []
    for r in records:
        who = html.escape(', '.join(n['name'] for n in r['npcs']))
        extra = []
        if r.get('forget'):
            extra.append(f"forgets: {html.escape(r['forget'])}")
        if r.get('aware'):
            extra.append('knows it was done to them')
        if r.get('status') == 'checking':
            extra.append('still being read')
        hid = ''.join(f'<li style="opacity:.55"><s>{html.escape(h["name"])}: {html.escape(str(h.get("text") or ""))}</s></li>'
                      for h in r['hidden'])
        items.append(f'<li><b>{who}</b>: "{html.escape(r["text"])}"<br><small>{html.escape(_when(r))}'
                     f'{"; " + "; ".join(extra) if extra else ""}</small>'
                     + (f'<ul style="margin:2px 0 6px;padding-left:18px">{hid}</ul>' if hid else '') + '</li>')
    return '<ul style="margin:0;padding-left:18px">' + ''.join(items) + '</ul>'


SETTING_HELP = {
    'command_hours': ('Commands last (game hours)', "How long an absolute command lasts when it does not say itself "
                      "(\"for two hours\"). 0 = until you release it (the NPC's page, or the hotkey's menu in game). "
                      "Memories it hid come back when it ends."),
    'command_model_check': ('Read commands with the model', "One short request to your summary model per command: what "
                            "it makes them forget, how long it lasts, whether they know. Off: read from its words only."),
    'command_forget_limit': ('Memories one command can hide', "Per NPC: the memories that fit what they must forget best."),
}


def build(gr, conversations_dir=memory_ui.DEFAULT_CONVERSATIONS, settings_path: str = settings.PATH) -> None:
    worlds = memory_ui.saves(conversations_dir)
    store_for = lambda w: memory.MemoryStore(conversations_dir, w) if w else None
    records = lambda w: command.load(store_for(w))['commands'] if w else []
    now = lambda: settings.load(settings_path)
    with gr.Accordion('Absolute commands', open=False):
        gr.HTML(ui_help.about('Orders given with the Absolute Command hotkey (G), per save. Release them on the NPCs page.', "Orders you gave with the Absolute Command hotkey (Living World's MCM, "
                              "G by default) during a conversation. Each NPC in that talk must accept it and act on it, "
                              "above every rule, their personality and their memories. A command that makes them forget "
                              "something hides those memories; nothing is deleted. To release one, open the NPC on the "
                              "NPCs page (Commands)."))
        with gr.Row():
            world = gr.Dropdown(choices=worlds, value=worlds[0] if worlds else None, label='Save (your character)',
                                interactive=True, scale=3)
            refresh = gr.Button('Refresh', size='sm', scale=0, min_width=120)
        listing = gr.HTML(ui_help.safe(lambda: commands_html(records(worlds[0] if worlds else None))))
        said = gr.Markdown('')
        with gr.Row():
            hours = gr.Number(value=lambda: now()['command_hours'], label=SETTING_HELP['command_hours'][0],
                              info=SETTING_HELP['command_hours'][1], precision=0, minimum=0)
            limit = gr.Number(value=lambda: now()['command_forget_limit'], label=SETTING_HELP['command_forget_limit'][0],
                              info=SETTING_HELP['command_forget_limit'][1], precision=0, minimum=1)
        check = gr.Checkbox(value=lambda: now()['command_model_check'], label=SETTING_HELP['command_model_check'][0],
                            info=SETTING_HELP['command_model_check'][1])
        save_btn = gr.Button('Save command settings', scale=0, min_width=160)

    def save(h, l, c):
        values = dict(now(), command_hours=max(0, int(h or 0)), command_forget_limit=max(1, int(l or 1)), command_model_check=bool(c))
        settings.save(settings_path, values)
        return ui_overrides._notify(gr, 'Saved. The next command uses these settings.')

    world.change(lambda w: commands_html(records(w)), inputs=[world], outputs=[listing])
    refresh.click(lambda w: commands_html(records(w)), inputs=[world], outputs=[listing])
    save_btn.click(save, inputs=[hours, limit, check], outputs=[said])
