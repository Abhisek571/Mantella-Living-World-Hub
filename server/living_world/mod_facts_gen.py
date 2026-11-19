"""The mod facts scanner: drafts one fact file per plugin from the installed plugins themselves, with no
invented wording. It reads each plugin file on its own (records only; nothing is changed) and finds the dialogue
conditions that tie a mod's state to an NPC: an INFO (or its quest's dialogue conditions) that is said only by one
NPC (GetIsID) and tests a global (GetGlobalValue), a quest's stage (GetStage) or a faction (GetInFaction,
GetFactionRank). A state tested by at least MIN_INFOS dialogue lines of that NPC becomes a fact; each tested value
gets one line built from the mod's own text:
    <mod>: <editor id> <value> (of <lowest>-<highest>). Said at this value: "<that NPC's own line at that value>"
A quoted line with an explicit word is not quoted: for a mod whose scripts start sex scenes (OStim or SexLab) it says
"has been intimate with {player} (<editor id> <value> of <lowest>-<highest>)" above the lowest value, otherwise just
the value. A line with no quoted text of the mod's own is dropped (live test 14: an editor id and a number told the
model nothing), except that intimate line. The explicit-word rule applies to every plugin. Config-like globals
(installed, toggle, timer, cooldown, SMP, voice, combat, speaking, debug, MCM, ...), follower-framework factions and
framework plugins (DENY: OStim, SexLab, follower frameworks, ...) are skipped. A quote ends at a sentence end, at most
QUOTE_CHARS characters, and is never cut inside a word.

Used by tools/modfacts_generate.py (writes the generated/ folder) and tools/modfacts_check.py."""
import json
import os
import re
import struct
import zlib

from . import lw_state, mod_facts

MIN_INFOS = 3        # dialogue lines of that NPC that must test a state before it becomes a fact
MAX_INFOS = 3000     # a plugin with more dialogue lines (Serana Dialogue Add-On: 7,495) is too big to draft well: skipped
MAX_VALUES = 12      # a state with more tested values is a list (a name picker), not a story state: skipped
LABEL_CHARS = 48     # the mod's name in a fact line, cut at a " - " part
QUOTE_CHARS = 120    # the NPC's own line ends at a sentence end within this many characters (never inside a word)
BASE_GAME = {'skyrim.esm', 'update.esm', 'dawnguard.esm', 'hearthfires.esm', 'dragonborn.esm'}
F_GETSTAGE, F_GETSTAGEDONE, F_GETISID, F_GETINFACTION, F_GETFACTIONRANK, F_GETGLOBALVALUE = 58, 59, 72, 71, 73, 74
OWNED_MIN_INFOS = 2  # a global only one NPC's lines test (or named after the plugin) needs this many (Dibella's priestesses)
OPS = ('==', '!=', '>', '>=', '<', '<=')
CONFIG = re.compile(r'installed|toggle|timer|cooldown|setting|config|enable|disable|debug|test|init|mcm|version|count(?:er)?$|'
                    r'smp|voice|combat|speak|hotkey|option|chance|delay|interval', re.I)
FOLLOWER_FACTION = re.compile(r'follow|nwsff|^nff|^eff|^aft|hireling|dismiss|spar', re.I)  # a follower framework's state
# framework plugins: their dialogue serves every NPC (or a scene system), so a "fact" from them is a framework state
DENY = ('ostim*', 'sexlab*', '*solutions*', 'nwsfollowerframework*', "nether's*", 'amazingfollowertweaks*', 'effcore*',
        'eff.esp', 'mantella*', 'skyui*', 'fnis*', 'nemesis*', 'pandora*', 'dynamicanimationreplacer*', 'skyrimnet*')
EXPLICIT = re.compile(r"\b(?:fuck\w*|cock\w*|pussy|cunt|tits?|cum\w*|dick\w*|suck\w*|anal|blowjob\w*|horny|naked|nude|"
                      r"sex\w*|knock(?:ed|ing)? (?:me )?up|orgasm\w*|whore\w*|slut\w*|brothel|hard-on|hard,|breed\w*|balls|loads?|swallow\w*|pull out|inside me|take me|moan\w*|bastard|lick\w*|erect\w*|seed|drip\w*|jerk\w*|piss\w*|legs open|filthy|having you|wet|ride|riding|bed you|in bed|thrust\w*|climax\w*|nipples?|breasts?|ass|\w*hole|womb|cheeks|hump\w*|sore|swollen|spread\w*|tiny thing|strokes?|tight|aching|hard|kiss my feet)\b", re.I)
SEX_SCRIPT = re.compile(rb'OThread|OStim|SexLab|StartSex|QuickStart', re.I)


# --- one plugin file, read on its own -------------------------------------------------------------------------------------

def _fields(body: bytes):
    k, out = 0, []
    while k + 6 <= len(body):
        size = struct.unpack_from('<H', body, k + 4)[0]
        out.append((body[k:k + 4], body[k + 6:k + 6 + size]))
        k += 6 + size
    return out


def _z(b: bytes) -> str:
    return b.split(b'\0')[0].decode('utf-8', 'replace')


def _cond(v: bytes) -> dict | None:
    if len(v) < 20:
        return None
    op = v[0] >> 5
    return {'op': OPS[op] if op < 6 else '?', 'or': bool(v[0] & 1), 'value': struct.unpack_from('<f', v, 4)[0],
            'func': struct.unpack_from('<H', v, 8)[0], 'p1': struct.unpack_from('<I', v, 12)[0],
            'p2': struct.unpack_from('<I', v, 16)[0]}


def _record_fields(rflags: int, body: bytes):
    """The subrecords of one record, unpacked first when it is compressed; None when it cannot be unpacked."""
    if rflags & 0x40000:
        try:
            body = zlib.decompress(body[4:])
        except zlib.error:
            return None
    return _fields(body)


def _first(fl, tag: bytes, read, default):
    return next((read(v) for t, v in fl if t == tag), default)


def _glob(fl, edid: str, text, localized: bool) -> dict:
    start = next((struct.unpack_from('<f', v)[0] for t, v in fl if t == b'FLTV' and len(v) >= 4), 0.0)
    return {'edid': edid, 'start': int(start)}


def _fact(fl, edid: str, text, localized: bool) -> dict:
    return {'edid': edid}


def _npc(fl, edid: str, text, localized: bool) -> dict:
    return {'edid': edid, 'name': text(b'FULL')}


def _dial(fl, edid: str, text, localized: bool) -> dict:
    return {'edid': edid, 'text': text(b'FULL'), 'quest': _first(fl, b'QNAM', lambda v: struct.unpack_from('<I', v)[0], 0)}


def _qust(fl, edid: str, text, localized: bool) -> dict:
    """Stages, journal lines per stage and the quest's own dialogue conditions (the ones before any stage)."""
    conds, stages, logs, stage = [], [], {}, None
    for t, v in fl:
        if t == b'INDX':
            stage = struct.unpack_from('<H', v)[0]
            stages.append(stage)
        elif t == b'CNAM' and stage is not None and not localized and stage not in logs:
            logs[stage] = _z(v)
        elif t == b'NEXT':
            stage = -1  # event conditions follow: not dialogue conditions
        elif t == b'CTDA' and stage is None:
            c = _cond(v)
            if c:
                conds.append(c)
    return {'edid': edid, 'name': text(b'FULL'), 'stages': sorted(set(stages)), 'logs': logs, 'conds': conds}


def _info(fl, edid: str, text, localized: bool) -> dict:
    conds = [c for c in (_cond(v) for t, v in fl if t == b'CTDA') if c]
    resp = [_z(v) for t, v in fl if t == b'NAM1'] if not localized else []
    prompt = _first(fl, b'RNAM', _z, '') if not localized else ''
    return {'conds': conds, 'resp': resp, 'prompt': prompt}


# record type -> (where read_plugin keeps it, how it is read); INFO rows go into a list with their id and topic
_RECORDS = {b'GLOB': ('glob', _glob), b'QUST': ('qust', _qust), b'FACT': ('fact', _fact), b'NPC_': ('npc', _npc),
            b'DIAL': ('dial', _dial), b'INFO': ('info', _info)}


def read_plugin(path: str) -> dict:
    """Records of one plugin: masters, GLOB, QUST (editor id, stages, dialogue conditions), FACT, NPC_ names, DIAL and
    every INFO (topic, conditions, player prompt, response lines). Localized plugins give no text."""
    data = open(path, 'rb').read()
    if data[:4] != b'TES4':
        raise ValueError('not a plugin')
    hsize, flags = struct.unpack_from('<II', data, 4)
    head = _fields(data[24:24 + hsize])
    out = {'masters': [_z(v) for t, v in head if t == b'MAST'], 'localized': bool(flags & 0x80), 'light': bool(flags & 0x200),
           'glob': {}, 'qust': {}, 'fact': {}, 'npc': {}, 'dial': {}, 'info': []}
    localized = out['localized']

    def add(typ: bytes, fid: int, fl, topic) -> None:
        bucket, read = _RECORDS[typ]
        edid = _first(fl, b'EDID', _z, '')
        text = (lambda tag: _first(fl, tag, _z, '')) if not localized else (lambda tag: '')
        row = read(fl, edid, text, localized)
        if typ == b'INFO':
            out['info'].append({'id': fid, 'topic': topic, **row})
        else:
            out[bucket][fid] = row

    def walk(start, end, topic):
        j = start
        while j + 24 <= end:
            typ = data[j:j + 4]
            size = struct.unpack_from('<I', data, j + 4)[0]
            if typ == b'GRUP':
                label, gtype = struct.unpack_from('<Ii', data, j + 8)
                walk(j + 24, j + size, label if gtype == 7 else topic)
                j += size
                continue
            rflags, fid = struct.unpack_from('<II', data, j + 8)
            body = data[j + 24:j + 24 + size]
            j += 24 + size
            if typ not in _RECORDS:
                continue
            fl = _record_fields(rflags, body)
            if fl is not None:
                add(typ, fid, fl, topic)

    walk(24 + hsize, len(data), None)
    return out


def ref_of(plugin_name: str, parsed: dict, form_id: int) -> str:
    """'plugin|0xID' for a form id as the plugin stores it (its high byte numbers the masters, then the plugin)."""
    index, local = form_id >> 24, form_id & 0xFFFFFF
    owner = parsed['masters'][index] if index < len(parsed['masters']) else plugin_name
    if owner.lower().endswith('.esl') or (owner == plugin_name and parsed.get('light')):
        local &= 0xFFF
    return f"{owner}|0x{local:06X}"


# --- the draft --------------------------------------------------------------------------------------------------------------

def _quote(text: str, limit: int = QUOTE_CHARS) -> str:
    """The line itself when it fits, else up to its last sentence end within limit, else its last whole word + '...';
    '' when not even a word fits."""
    text = ' '.join(str(text or '').split()).strip('"')
    if len(text) <= limit:
        return text
    ends = [m.end() for m in re.finditer(r'[.!?]+(?=\s|$)', text[:limit + 1]) if m.end() <= limit]
    if ends and ends[-1] >= min(30, limit // 2):
        return text[:ends[-1]]
    cut = text[:max(limit - 3, 0) + 1]
    if ' ' not in cut.strip():
        return ''
    return cut.rsplit(' ', 1)[0].rstrip(' ,;:-') + '...'


def _quoted(prefix: str, said: str) -> str:
    """prefix + the quoted line, the quote shortened (whole words) so the line fits MAX_CHARS; '' when it cannot."""
    quote = _quote(said, min(QUOTE_CHARS, mod_facts.MAX_CHARS - len(prefix) - 2))
    return f'{prefix}"{quote}"' if len(quote) >= 12 else ''


def denied(plugin: str) -> bool:
    import fnmatch
    return any(fnmatch.fnmatch(plugin.lower(), d) for d in DENY)


def _range_text(values) -> str:
    return f"{min(values)}-{max(values)}"


def _is_said_by(c: dict) -> bool:
    return c['func'] == F_GETISID and c['op'] == '==' and c['value'] == 1.0


def _speakers(info: dict, parsed: dict, quest_npcs: dict) -> list:
    """The NPCs who say this line (its own GetIsID conditions, else its quest's), each once; [] for nobody in particular."""
    npcs = [c['p1'] for c in info['conds'] if _is_said_by(c)]
    if not npcs:
        npcs = quest_npcs.get(parsed['dial'].get(info['topic'], {}).get('quest', 0), [])
    return list(dict.fromkeys(npcs))  # several speakers (GetIsID ... OR): each of them says it


def _quest_name(plugin_name: str, parsed: dict, form: int) -> str:
    return parsed['qust'].get(form, {}).get('edid') or ref_of(plugin_name, parsed, form)


def _condition_state(c: dict, parsed: dict, plugin_name: str):
    """(kind, form, editor id, value, op) for a dialogue condition that tests a mod state, None for any other."""
    func, form = c['func'], c['p1']
    if func == F_GETGLOBALVALUE and form in parsed['glob'] and not CONFIG.search(parsed['glob'][form]['edid']):
        kind, name = 'global', parsed['glob'][form]['edid']
    elif func == F_GETSTAGE and c['op'] in ('==', '>='):  # any quest's stage, a master's too (Grosta: a vanilla quest)
        kind, name = 'stage', _quest_name(plugin_name, parsed, form)
    elif func == F_GETSTAGEDONE and c['op'] == '==' and c['value'] >= 1.0:  # stage N done: read as "N or more"
        return 'stage', form, _quest_name(plugin_name, parsed, form), int(c['p2']), '>='
    elif func in (F_GETINFACTION, F_GETFACTIONRANK) and form in parsed['fact'] and \
            not FOLLOWER_FACTION.search(parsed['fact'][form]['edid']):
        kind, name = 'faction', parsed['fact'][form]['edid']
    else:
        return None
    if c['op'] not in ('==', '>='):
        return None
    value = int(c['value'])
    if func == F_GETINFACTION:  # in the faction (1) is rank 0 or more, not in it (0) is -1
        value = 0 if value >= 1 else -1
    return kind, form, name, value, c['op']


def _tested_states(plugin_name: str, parsed: dict) -> dict:
    """{(npc, kind, form, editor id): {(value, op): [(the line's only state, info)]}} over every INFO said by an NPC."""
    quest_npcs = {qid: [c['p1'] for c in q['conds'] if _is_said_by(c)] for qid, q in parsed['qust'].items()}
    found = {}
    for info in parsed['info']:
        npcs = _speakers(info, parsed, quest_npcs)
        if not npcs:
            continue  # said by nobody in particular (a voice type, a faction of guards): no one NPC's state
        states = [s for s in (_condition_state(c, parsed, plugin_name) for c in info['conds']) if s is not None]
        for npc in npcs:
            for kind, form, name, value, op in states:
                key = (npc, kind, form, name)
                found.setdefault(key, {}).setdefault((value, op), []).append((len(states) == 1, info))
    return found


def _value_text(parsed: dict, mod_name: str, sexual: bool, kind: str, form: int, name: str, value: int, op: str,
                numbers: list, infos: list) -> str:
    """The fact line for one tested value ('' when there is nothing of the mod's own to tell)."""
    said = next((r for _, info in infos for r in info['resp'] if r.strip()), '')
    label = f"{name} {value}{' or more' if op == '>=' else ''} (of {_range_text(numbers)})"
    spoken = [r for _, info in infos for r in info['resp'] if r.strip()]
    explicit = sum(1 for r in spoken if EXPLICIT.search(r))
    if said and EXPLICIT.search(said):
        said = next((r for r in spoken if not EXPLICIT.search(r)), '')
    text = _quoted(f"{mod_name}: {label}. Said at this value: ", said) if said else ''
    if spoken and explicit * 3 >= len(spoken):
        # a third or more of this value's lines explicit (any plugin: the word list misses some): no quote at all
        text = ''
    if not text and sexual and value > min(numbers):
        text = f"{mod_name}: has been intimate with {{player}} ({label})"[:mod_facts.MAX_CHARS]
    journal = parsed['qust'].get(form, {}).get('logs', {}).get(value, '') if kind == 'stage' else ''
    if journal and not EXPLICIT.search(journal):  # a quest stage's own journal text, where the quest has one
        text = _quoted(f"{mod_name}: {name} stage {value}. Journal: ", journal) or text
    return text


def _state_lines(parsed: dict, mod_name: str, sexual: bool, kind: str, form: int, name: str, values: dict) -> list:
    """The fact's lines, one per tested value with something to tell, lowest value first."""
    numbers = sorted({v for v, _ in values})
    start = parsed['glob'][form]['start'] if kind == 'global' else (0 if kind == 'stage' else -1)
    lines = []
    for (value, op), infos in sorted(values.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        if value == start and op == '==':
            continue  # the value it starts at: nothing has happened yet
        # a line the player chose a topic for first, then the one with the fewest other conditions
        infos = sorted(infos, key=lambda x: (not x[1]['prompt'], sum(1 for c in x[1]['conds'] if c['func'] != F_GETISID),
                                             -len(' '.join(x[1]['resp']))))  # then the longest (most to go on)
        text = _value_text(parsed, mod_name, sexual, kind, form, name, value, op, numbers, infos)
        if text:  # no quoted text of the mod's own (and not the intimate line): nothing to tell the model
            lines.append({'min': value, 'max': 9999 if op == '>=' else value, 'text': text, 'infos': len(infos)})
    return lines


def draft(plugin_name: str, parsed: dict, mod_name: str, sexual: bool, min_infos: int = MIN_INFOS) -> dict | None:
    """The fact file for one plugin, or None when no state is tied to an NPC by enough dialogue lines."""
    if parsed['localized'] or len(parsed['info']) > MAX_INFOS:
        return None
    found = _tested_states(plugin_name, parsed)
    testers = {}  # (kind, form) -> the NPCs whose lines test it
    for npc, kind, form, name in found:
        testers.setdefault((kind, form), set()).add(npc)
    stem = re.sub(r'^shadowman_|\.es[mpl]$', '', plugin_name.lower())
    npcs = {}
    for (npc, kind, form, name), values in found.items():
        total = sum(len(v) for v in values.values())
        owned = kind == 'global' and (testers[(kind, form)] == {npc} or (len(stem) >= 4 and stem in name.lower()))
        if total < (min(min_infos, OWNED_MIN_INFOS) if owned else min_infos):
            continue
        if len({v for v, _ in values}) > MAX_VALUES:
            continue
        lines = _state_lines(parsed, mod_name, sexual, kind, form, name, values)
        if not lines:
            continue
        npcs.setdefault(npc, []).append({'kind': kind, 'form': ref_of(plugin_name, parsed, form), 'editor_id': name,
                                         'infos': total, 'lines': lines})
    if not npcs:
        return None
    out = []
    for npc, facts in npcs.items():
        facts = sorted(facts, key=lambda f: -f['infos'])[:mod_facts.MAX_LINES]
        name = parsed['npc'].get(npc, {}).get('name', '') if (npc >> 24) == len(parsed['masters']) else ''
        out.append({'npc': ref_of(plugin_name, parsed, npc), 'name': name, 'facts': facts})
    return {'format': mod_facts.FORMAT, 'plugin': plugin_name, 'mod': mod_name, 'source': 'generated',
            'min_infos': min_infos, 'npcs': out}


# --- a Mod Organizer 2 instance --------------------------------------------------------------------------------------------

def mo2_plugins(instance: str, profile: str = 'Default', profiles_dir: str | None = None) -> tuple[list[str], list[str]]:
    """(enabled plugins in load order, enabled mod folders highest priority first)."""
    prof = os.path.join(profiles_dir or os.path.join(instance, 'profiles'), profile)
    plugins = [l.strip()[1:] for l in open(os.path.join(prof, 'plugins.txt'), encoding='utf-8-sig') if l.startswith('*')]
    mods = [l.rstrip('\r\n')[1:] for l in open(os.path.join(prof, 'modlist.txt'), encoding='utf-8-sig') if l.startswith('+')]
    return plugins, mods


def winner(instance: str, mods: list[str], relative: str, game_data: str | None = None) -> tuple[str, str] | tuple[None, None]:
    """(mod folder, path) of the file that wins in the virtual Data folder; ('', path) when only the game has it."""
    for mod in mods:
        path = os.path.join(instance, 'mods', mod, relative)
        if os.path.isfile(path):
            return mod, path
    if game_data and os.path.isfile(os.path.join(game_data, relative)):
        return '', os.path.join(game_data, relative)
    return None, None


def mod_label(folder: str, plugin: str) -> str:
    """A short name for the mod: its folder without "[NoDelete]", its " - " parts kept while within LABEL_CHARS (so
    "Shadowmans NPCs 68 - Gerdur Handling Wood - Ostim Conversion and Redux" is "Shadowmans NPCs 68 - Gerdur Handling
    Wood"), else the plugin name."""
    name = re.sub(r'^\[NoDelete\]\s*', '', folder or '').strip()
    if not name:
        return os.path.splitext(plugin)[0]
    parts, kept = name.split(' - '), ''
    for part in parts:
        joined = f"{kept} - {part}" if kept else part
        if kept and len(joined) > LABEL_CHARS:
            break
        kept = joined
    return kept[:LABEL_CHARS * 2]


def sexual_mod(folder_path: str) -> bool:
    """Whether the mod's own scripts start sex scenes (OStim or SexLab calls in its scripts)."""
    scripts = os.path.join(folder_path, 'Scripts')
    for root, _, files in os.walk(scripts):
        for name in files:
            if name.lower().endswith(('.psc', '.pex')):
                try:
                    with open(os.path.join(root, name), 'rb') as f:
                        if SEX_SCRIPT.search(f.read()):
                            return True
                except OSError:
                    continue
    return False


def has_dialogue(path: str) -> bool:
    """Whether a plugin has a top-level dialogue group (most plugins have none: they are skipped without parsing)."""
    try:
        with open(path, 'rb') as f:
            data = f.read()
    except OSError:
        return False
    at = data.find(b'DIAL')
    while at >= 0:
        if at >= 8 and data[at - 8:at - 4] == b'GRUP':
            return True
        at = data.find(b'DIAL', at + 1)
    return False


def sources_mo2(instance: str, profile: str = 'Default', game_data: str | None = None, mods_dir: str | None = None,
                profiles_dir: str | None = None) -> list[tuple]:
    """(plugin, path, mod folder path or None, mod name) for each enabled plugin of an MO2 profile, where it wins."""
    plugins, mods = mo2_plugins(instance, profile, profiles_dir)
    base = mods_dir or os.path.join(instance, 'mods')
    out = []
    for plugin in plugins:
        if plugin.lower() in BASE_GAME:
            continue
        folder, path = None, None
        for mod in mods:
            if os.path.isfile(os.path.join(base, mod, plugin)):
                folder, path = mod, os.path.join(base, mod, plugin)
                break
        if not path and game_data and os.path.isfile(os.path.join(game_data, plugin)):
            path = os.path.join(game_data, plugin)
        out.append((plugin, path, os.path.join(base, folder) if folder else None, mod_label(folder or '', plugin)))
    return out


def sources_data(data_dir: str, plugins_txt: str) -> list[tuple]:
    """The same for a game without Mod Organizer: the enabled plugins of plugins.txt ("*name"), from the Data folder."""
    out = []
    try:
        lines = open(plugins_txt, encoding='utf-8-sig').read().splitlines()
    except OSError:
        return out
    for line in lines:
        name = line.strip()
        if not name.startswith('*'):
            continue
        name = name[1:].strip()
        if name.lower() in BASE_GAME:
            continue
        path = os.path.join(data_dir, name)
        out.append((name, path if os.path.isfile(path) else None, None, os.path.splitext(name)[0]))
    return out


def generate_from(sources: list[tuple], only=None, min_infos: int = MIN_INFOS, step=None) -> dict:
    """{plugin: draft or reason} for the given sources (only: plugin -> bool; step(done, total, plugin): progress)."""
    todo = [s for s in sources if not only or only(s[0])]
    out, sexual = {}, {}
    for done, (plugin, path, folder, label) in enumerate(todo):
        if step:
            step(done, len(todo), plugin)
        if not path:
            out[plugin] = 'not found'
            continue
        if not has_dialogue(path):
            out[plugin] = 'no dialogue'
            continue
        if denied(plugin):
            out[plugin] = 'a framework (its dialogue is not one NPC\'s story)'
            continue
        try:
            parsed = read_plugin(path)
        except (OSError, ValueError, struct.error) as e:
            out[plugin] = f'unreadable ({e})'
            continue
        if folder and folder not in sexual:
            sexual[folder] = sexual_mod(folder)
        made = draft(plugin, parsed, label, bool(folder) and sexual[folder], min_infos)
        out[plugin] = made or ('localized: no text' if parsed['localized'] else
                               f"too big to draft ({len(parsed['info'])} dialogue lines): write its file by hand" if len(parsed['info']) > MAX_INFOS else
                               'no state tied to an NPC by enough dialogue lines')
    if step:
        step(len(todo), len(todo), '')
    return out


def generate(instance: str, profile: str = 'Default', only=None, min_infos: int = MIN_INFOS, game_data: str | None = None) -> dict:
    """{plugin: draft or reason} for every enabled plugin of an MO2 profile (only: a function plugin -> bool)."""
    return generate_from(sources_mo2(instance, profile, game_data), only, min_infos)


def write(drafts: dict, folder: str) -> list[str]:
    """Writes each draft as <plugin>.json into folder (the generated/ folder), after removing the files an earlier scan
    wrote there (only files marked "source": "generated"); returns the files written. Nothing else is touched. Each file
    is replaced in one step (the game reads them at every join, and keeps a half-written one for the session), and a
    file this scan writes again is never removed first."""
    os.makedirs(folder, exist_ok=True)
    keep = {(plugin + '.json').lower() for plugin, made in drafts.items() if isinstance(made, dict)}
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        if name.lower().endswith('.json') and name.lower() not in keep:
            try:
                with open(path, encoding='utf-8') as f:
                    old = json.load(f)
            except (OSError, ValueError):
                continue
            if isinstance(old, dict) and old.get('source') == 'generated':
                os.remove(path)
    written = []
    for plugin, made in drafts.items():
        if isinstance(made, dict):
            path = os.path.join(folder, plugin + '.json')
            temp = lw_state.temp_path(path)
            with open(temp, 'w', encoding='utf-8') as f:
                json.dump(made, f, ensure_ascii=False, indent=1)
            lw_state.replace_file(temp, path)
            written.append(path)
    return written
