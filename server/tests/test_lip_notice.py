"""Offline tests for the lip sync notice on the Status page (ui_tab.lip_status, lip_line and the Hide setting).
Lip sync stays optional: the Hub only looks for Mantella's files, by Mantella's own rule, and never creates any.
Run with a Python 3.11: test_lip_notice.py <repo server dir>"""
import json, os, sys, tempfile
from pathlib import Path
from types import SimpleNamespace

SERVER = Path(sys.argv[1])
sys.path.insert(0, str(SERVER))
from living_world import settings, ui_tab

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)) if not cond else ''))
    if not cond:
        FAILS.append(name)


def folders(tmp, lipgen=False, wrapper=False, cdf=False):
    """A game folder with Tools\\LipGen and a mod folder with Sound\\Voice\\Processing, holding the files asked for."""
    lip = Path(tmp) / 'Game/Tools/LipGen'
    facefx = Path(tmp) / 'Game/Data/Sound/Voice/Processing'
    (lip / 'LipGenerator').mkdir(parents=True)
    facefx.mkdir(parents=True)
    for wanted, path in ((lipgen, lip / 'LipGenerator/LipGenerator.exe'), (wrapper, facefx / 'FaceFXWrapper.exe'),
                         (cdf, facefx / 'FonixData.cdf')):
        if wanted:
            path.write_bytes(b'x')
    return str(lip), str(facefx)


def config(lip, facefx, generation='enabled'):
    return SimpleNamespace(lipgen_path=lip, facefx_path=facefx, lip_generation=generation)


def listing(tmp):
    return sorted(str(p.relative_to(tmp)) for p in Path(tmp).rglob('*'))


# nothing present: FaceFXWrapper.exe is named first (Mantella checks it first), with the real folder
with tempfile.TemporaryDirectory() as tmp:
    lip, facefx = folders(tmp)
    before = listing(tmp)
    status = ui_tab.lip_status(config(lip, facefx))
    check('nothing present: missing FaceFXWrapper.exe', status == ('missing', 'FaceFXWrapper.exe', os.path.normpath(facefx)), status)
    check('nothing present: no file created', listing(tmp) == before)
    name, text = ui_tab.lip_line(status)
    check('wrapper missing: line text', name == 'Lip sync is off' and text ==
          f'FaceFXWrapper.exe is missing from {os.path.normpath(facefx)}. It ships with Mantella: reinstall Mantella.', (name, text))

# LipGenerator present (Creation Kit): fine whatever the FaceFX folder holds
with tempfile.TemporaryDirectory() as tmp:
    lip, facefx = folders(tmp, lipgen=True)
    check('LipGenerator present: ok', ui_tab.lip_status(config(lip, facefx)) == ('ok', None, None))
    check('LipGenerator present: no line', ui_tab.lip_line(ui_tab.lip_status(config(lip, facefx))) is None)

# FaceFXWrapper present, FonixData.cdf missing: names the cdf, Nexus mod 40971 and the Creation Kit folder
with tempfile.TemporaryDirectory() as tmp:
    lip, facefx = folders(tmp, wrapper=True)
    status = ui_tab.lip_status(config(lip, facefx))
    check('cdf missing: missing FonixData.cdf', status == ('missing', 'FonixData.cdf', os.path.normpath(facefx)), status)
    name, text = ui_tab.lip_line(status)
    expected = ("FonixData.cdf is missing. Install Nexus mod 40971 with your mod manager "
                "(https://www.nexusmods.com/skyrimspecialedition/mods/40971), or copy FonixData.cdf from the Creation Kit's "
                f"Tools\\LipGen\\LipGenerator folder into {os.path.normpath(facefx)}.")
    check('cdf missing: line text', name == 'Lip sync is off' and text == expected, text)
    page = ui_tab.start_here_html(str(Path(tmp) / 'actions'), str(Path(tmp) / 'ext'), {'knowledge_mode': 'full'},
                                  str(Path(tmp) / 'nodata'), lip=(name, text))
    check('cdf missing: listed under What needs attention, yellow', 'What needs attention' in page and
          f'<b style="color:{ui_tab.COLORS["todo"]}">Lip sync is off</b>: FonixData.cdf is missing.' in page, page[-900:])
    check('cdf missing: Nexus address is a link', f'<a href="{ui_tab.LIP_NEXUS}" target="_blank">{ui_tab.LIP_NEXUS}</a>' in page, page[-900:])
    check('cdf missing: never red', f'<b style="color:{ui_tab.COLORS["bad"]}">Lip sync' not in page)

# both present: ok
with tempfile.TemporaryDirectory() as tmp:
    lip, facefx = folders(tmp, wrapper=True, cdf=True)
    check('wrapper and cdf present: ok', ui_tab.lip_status(config(lip, facefx)) == ('ok', None, None))

# lip generation disabled in Mantella, or folders not known: not applicable, nothing listed
with tempfile.TemporaryDirectory() as tmp:
    lip, facefx = folders(tmp)
    check('disabled: not applicable', ui_tab.lip_status(config(lip, facefx, 'disabled')) == ('n/a', None, None))
    check('Lazy still checked', ui_tab.lip_status(config(lip, facefx, 'lazy'))[0] == 'missing')
    by_definitions = SimpleNamespace(lipgen_path=lip, facefx_path=facefx, definitions=SimpleNamespace(
        get_config_value_definition=lambda key: SimpleNamespace(value='Disabled' if key == 'lip_generation' else None)))
    check('disabled, read from the settings list: not applicable', ui_tab.lip_status(by_definitions) == ('n/a', None, None))
    check('folders not known: not applicable', ui_tab.lip_status(config('', '')) == ('n/a', None, None))
    check('no config (older exe): not applicable', ui_tab.lip_status(None) == ('n/a', None, None))
    check('not applicable: no line', ui_tab.lip_line(('n/a', None, None)) is None)


class FakeComponent:
    def __init__(self, kind, *args, **kwargs):
        self.kind, self.args, self.kwargs = kind, args, kwargs
    def __enter__(self):
        return self
    def __exit__(self, *exc):
        return False
    def click(self, fn, inputs=None, outputs=None, **kwargs):
        self.kwargs['on_click'] = fn
        self.kwargs['inputs'] = inputs
        return self
    def change(self, fn, **kwargs):
        return self


class FakeGradio:
    def __init__(self):
        self.made = []
    def __getattr__(self, kind):
        def make(*args, **kwargs):
            component = FakeComponent(kind, *args, **kwargs)
            self.made.append(component)
            return component
        return make


class FakeApi:
    def usage_log(self):
        return []


def status_page(tmp, cfg, hide):
    path = Path(tmp) / 'settings.json'
    settings.save(str(path), dict(settings.DEFAULTS, update_check_days=0, hide_lip_notice=hide))
    gr = FakeGradio()
    ui_tab.build_status(gr, FakeApi(), str(Path(tmp) / 'actions'), str(Path(tmp) / 'ext'), str(path), config=cfg)
    page = next(c for c in gr.made if c.kind == 'HTML' and c.args and callable(c.args[0]))
    return page.args[0]()


# the Status page: the line shows by default, and the setting hides it
with tempfile.TemporaryDirectory() as tmp:
    lip, facefx = folders(tmp, wrapper=True)
    check('setting off by default', settings.DEFAULTS['hide_lip_notice'] is False and settings.load(str(Path(tmp) / 'none.json'))['hide_lip_notice'] is False)
    shown = status_page(tmp, config(lip, facefx), hide=False)
    check('status page: notice shown', 'Lip sync is off</b>: FonixData.cdf is missing.' in shown, shown[-900:])
    hidden = status_page(tmp, config(lip, facefx), hide=True)
    check('status page: notice hidden by the setting', 'Lip sync' not in hidden, hidden[-900:])
    check('setting saved and read back', json.loads((Path(tmp) / 'settings.json').read_text(encoding='utf-8'))['hide_lip_notice'] is True
          and settings.load(str(Path(tmp) / 'settings.json'))['hide_lip_notice'] is True)

# the Settings page: the box sits with the update check and Save settings stores it
with tempfile.TemporaryDirectory() as tmp:
    path = str(Path(tmp) / 'settings.json')
    gr = FakeGradio()
    ui_tab.build_settings(gr, None, str(Path(tmp) / 'rules'), path)
    names = [(c.kind, c.kwargs.get('label') or (c.args[0] if c.args and isinstance(c.args[0], str) else '')) for c in gr.made]
    accordion = names.index(('Accordion', 'Updates and notices'))
    box = names.index(('Checkbox', 'Hide the lip sync notice'))
    following = [n for n in names[accordion + 1:] if n[0] == 'Accordion']
    check('settings: box in the Updates and notices section', accordion < box and (not following or box < names.index(following[0])), names[accordion:box + 1])
    save = next(c for c in gr.made if c.kind == 'Button' and c.args and c.args[0] == 'Save settings')
    box_component = next(c for c in gr.made if c.kind == 'Checkbox' and c.kwargs.get('label') == 'Hide the lip sync notice')
    check('settings: Save settings reads the box', box_component in save.kwargs['inputs'])
    inputs = save.kwargs['inputs']
    values = settings.load(path)
    args = []
    for c in inputs:  # every field at its current value, the lip box ticked
        if c is box_component:
            args.append(True)
        else:
            v = c.kwargs.get('value')
            args.append(v() if callable(v) else v)
    save.kwargs['on_click'](*args)
    check('settings: Save settings stores the box', settings.load(path)['hide_lip_notice'] is True)
    check('settings: nothing else changed', {k: v for k, v in settings.load(path).items() if k != 'hide_lip_notice'}
          == {k: v for k, v in values.items() if k != 'hide_lip_notice'})

print('RESULT: ' + ('ALL PASS' if not FAILS else f'{len(FAILS)} FAILED: {FAILS}'))
sys.exit(1 if FAILS else 0)
