"""The Custom events section of the Events page and its settings on the Settings page (each NPC's Now paragraph is on
the NPCs page). The logic is in events.py; this only shows it."""
from . import events, memory, memory_ui, settings, ui_help, ui_overrides

ALL = 'Everyone'
MODES = {'Narrated (NPCs react)': events.NARRATED, 'Silent (known, no reply)': events.SILENT}
EVENTS_HELP = ("Custom events are what you type with Mantella's Add Custom Game Event hotkey (N by default). Start one "
               "with silent: and everyone present knows it happened and remembers it, but nobody answers it; react: "
               "makes one narrated when the setting makes them silent. Type undo as a custom event to take back your "
               "last one in this talk.\n\nEdit or Take back: in a talk that is still going on, it applies from the "
               "next reply and goes into the memory. If a memory was already written from it, that memory is hidden "
               "(Unhide in Memories on the NPCs page brings it back) and your model rewrites it without the event, or with your edit: "
               "one short request per NPC. Nothing is deleted.")


def _label(row: dict) -> str:
    return events.label(row)


def _id(label) -> str:
    return str(label or '').rpartition('[')[2].rstrip(']')


def _mode_label(mode: str) -> str:
    return next((k for k, v in MODES.items() if v == mode), next(iter(MODES)))


def build(gr, conversations_dir=memory_ui.DEFAULT_CONVERSATIONS, config=None) -> None:
    worlds = memory_ui.saves(conversations_dir)
    ask = ui_overrides.model_asker(config) if config is not None else None
    model = (lambda system, text: ask(system, text)) if ask is not None else None
    store_for = lambda w: memory.MemoryStore(conversations_dir, w) if w else None

    with gr.Accordion('Custom events', open=False):
        gr.HTML(ui_help.about('Events you added in the game, newest first. Pick one to edit or take it back.', EVENTS_HELP))
        with gr.Row():
            ev_world = gr.Dropdown(choices=worlds, value=worlds[0] if worlds else None, label='Save (your character)', scale=1)
            ev_npc = gr.Dropdown(choices=[ALL], value=ALL, label='NPC', scale=2, filterable=True)
            ev_refresh = gr.Button('Refresh', size='sm', scale=0, min_width=120)
        first = events.listing(store_for(worlds[0])) if worlds else []
        ev_table = gr.Dataframe(value=events.table(first), headers=['When', 'Who was there', 'Mode', 'Status', 'Event'], type='array',
                                interactive=False, wrap=True, column_widths=['18%', '18%', '10%', '12%', '42%'])
        ev_pick = gr.Dropdown(choices=[_label(r) for r in first], value=None, label='Pick an event to edit or take back', interactive=True)
        ev_text = gr.Textbox(label='Event', lines=2)
        ev_mode = gr.Radio(choices=list(MODES), value=next(iter(MODES)), label='Mode')
        with gr.Row():
            ev_save = gr.Button('Save edit', variant='primary', scale=0, min_width=140)
            ev_restore = gr.Button('Restore', scale=0, min_width=140)
            ev_remove = gr.Button('Take back', scale=0, min_width=140, elem_classes=['lw-danger'])
        ev_said = gr.Markdown('')

    def ev_list(w, npc):
        store = store_for(w)
        rows = events.listing(store, None if npc in (None, '', ALL) else npc)
        names = [ALL] + events.npc_names(store)
        return (gr.update(choices=names, value=npc if npc in names else ALL), events.table(rows),
                gr.update(choices=[_label(r) for r in rows], value=None), '', gr.update(value=next(iter(MODES))))

    def ev_show(w, label):
        row = events.find(store_for(w), _id(label)) if w and label else None
        if row is None:
            return '', gr.update(value=next(iter(MODES)))
        return row['text'], gr.update(value=_mode_label(row.get('mode', events.NARRATED)))

    def ev_change(w, npc, label, text, mode, remove=False):
        if not w or not label:
            return (*ev_list(w, npc)[:3], gr.update(), gr.update(), 'Pick an event first.')
        note = events.change(store_for(w), _id(label), text=None if remove else text, mode=MODES.get(mode), remove=remove, ask=model)
        return (*ev_list(w, npc)[:3], gr.update(), gr.update(), ui_overrides._notify(gr, note))

    def ev_back(w, npc, label):
        if not w or not label:
            return (*ev_list(w, npc)[:3], gr.update(), gr.update(), 'Pick an event first.')
        note = events.restore(store_for(w), _id(label))
        return (*ev_list(w, npc)[:3], gr.update(), gr.update(), ui_overrides._notify(gr, note))

    lists = [ev_npc, ev_table, ev_pick, ev_text, ev_mode]
    for trigger in (ev_world.change, ev_npc.change, ev_refresh.click):
        trigger(ev_list, inputs=[ev_world, ev_npc], outputs=lists)
    ev_pick.change(ev_show, inputs=[ev_world, ev_pick], outputs=[ev_text, ev_mode])
    ev_save.click(ev_change, inputs=[ev_world, ev_npc, ev_pick, ev_text, ev_mode], outputs=lists + [ev_said])
    ev_remove.click(lambda w, n, l, t, m: ev_change(w, n, l, t, m, remove=True), inputs=[ev_world, ev_npc, ev_pick, ev_text, ev_mode],
                    outputs=lists + [ev_said])
    ev_restore.click(ev_back, inputs=[ev_world, ev_npc, ev_pick], outputs=lists + [ev_said])


SETTING_HELP = {
    'custom_events_silent': ('Custom events are silent', "On: NPCs know about each custom event but nobody answers it, "
                             "unless it starts with react:. Off: they react, unless it starts with silent:."),
    'bio_changes': ('Now paragraphs', "A short paragraph after each NPC's bio and Background: their situation as they "
                    "believe it, written after talks. One summary request each time. Bios and overrides are never changed."),
    'bio_changes_talks': ('Talks between updates', "How often the Now paragraph is written again; sooner after important "
                          "memories or when something changed."),
}


def build_settings(gr, settings_path: str = settings.PATH) -> None:
    """Its own small section with its own Save button, so it never writes the other settings."""
    now = lambda: settings.load(settings_path)
    with gr.Accordion('Custom events and Now paragraphs', open=False):
        silent = gr.Checkbox(value=lambda: now()['custom_events_silent'], label=SETTING_HELP['custom_events_silent'][0],
                             info=SETTING_HELP['custom_events_silent'][1])
        changes = gr.Checkbox(value=lambda: now()['bio_changes'], label=SETTING_HELP['bio_changes'][0],
                              info=SETTING_HELP['bio_changes'][1])
        every = gr.Number(value=lambda: now()['bio_changes_talks'], label=SETTING_HELP['bio_changes_talks'][0],
                          info=SETTING_HELP['bio_changes_talks'][1], precision=0, minimum=1)
        said = gr.Markdown('')

        def save(s, c, e):
            new = dict(now(), custom_events_silent=bool(s), bio_changes=bool(c),
                       bio_changes_talks=max(1, int(e or settings.DEFAULTS['bio_changes_talks'])))
            settings.save(settings_path, new)
            return ui_overrides._notify(gr, 'Saved. Applies from the next custom event and the next talk.')
        gr.Button('Save these', scale=0, min_width=140).click(save, inputs=[silent, changes, every], outputs=[said])
