"""Mod facts: what other mods record about an NPC and the player (a quest stage, a global, a faction rank, the
relationship rank), turned into short background lines. The facts are read from the game, never set from the Hub.

Fact files are JSON, one per plugin, in StorageUtilData/MantellaLivingWorld/modfacts/:
  user/       the player's own files, never touched by an update or a rescan
  shipped/    files that come with the Integration Hub
  generated/  files the scanner (tools/modfacts_generate.py) writes from the installed plugins
For the same plugin a user file wins over a shipped one, and a shipped one over a generated one. A file whose plugin
is not installed is ignored. The format (format 1):
  {"format": 1, "plugin": "shadowman_gerdur.esp", "mod": "Gerdur Handling Wood",
   "npcs": [{"npc": "Skyrim.esm|0x01347C", "name": "Gerdur",
             "facts": [{"kind": "global", "form": "shadowman_gerdur.esp|0x000897",
                        "lines": [{"min": 1, "max": 1, "text": "..."}]}]}]}
kind: global (its value), stage (the quest's current stage), quest (0 not started, 1 running, 2 completed),
faction (the NPC's rank in it, -1 when not a member), relationship (the NPC's relationship rank to the player, -4 to 4,
no form). The first line whose min..max holds the value is the fact; none means no fact. {player} stands for the
player's name.

The Hub's game side (MLW_ModFacts.psc) does the lookups when an NPC joins a talk and writes the lines into the NPC's
file (modfact_1 .. modfact_6, "<mod>|<text>"); this module puts them into that NPC's Background (cached all talk) and
holds the same rules for the tools and the tests."""
import json
import os
import re

FORMAT = 1
MAX_LINES = 6     # fact lines per NPC
MAX_CHARS = 160   # characters per fact line
KINDS = ('global', 'stage', 'quest', 'faction', 'relationship')
FOLDERS = ('user', 'shipped', 'generated')  # first wins for the same plugin
FORM_REF = re.compile(r'^\s*([^|]+\.(?:esp|esm|esl))\s*\|\s*(?:0x)?([0-9a-fA-F]{1,8})\s*$', re.I)


def form_ref(text) -> tuple[str, int] | None:
    """'plugin.esp|0x000897' -> ('plugin.esp', 0x897); None when malformed."""
    found = FORM_REF.match(str(text or ''))
    return (found.group(1).strip(), int(found.group(2), 16)) if found else None


def _int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def clean_file(data) -> dict | None:
    """A fact file with only usable parts, or None when it names no plugin or has no usable fact."""
    if not isinstance(data, dict) or not isinstance(data.get('plugin'), str) or not data['plugin'].strip():
        return None
    npcs = []
    for npc in data.get('npcs') if isinstance(data.get('npcs'), list) else []:
        if not isinstance(npc, dict) or not (form_ref(npc.get('npc')) or str(npc.get('name') or '').strip()):
            continue
        facts = []
        for fact in npc.get('facts') if isinstance(npc.get('facts'), list) else []:
            if not isinstance(fact, dict) or fact.get('kind') not in KINDS:
                continue
            if fact['kind'] != 'relationship' and not form_ref(fact.get('form')):
                continue
            lines = [dict(min=_int(l.get('min')), max=_int(l.get('max')), text=str(l.get('text')).strip()[:MAX_CHARS])
                     for l in fact.get('lines') if isinstance(l, dict)] if isinstance(fact.get('lines'), list) else []
            lines = [l for l in lines if l['min'] is not None and l['max'] is not None and l['min'] <= l['max'] and l['text']]
            if lines:
                facts.append({'kind': fact['kind'], 'form': fact.get('form', ''), 'lines': lines})
        if facts:
            npcs.append({'npc': npc.get('npc', ''), 'name': str(npc.get('name') or '').strip(), 'facts': facts})
    if not npcs:
        return None
    return {'format': FORMAT, 'plugin': data['plugin'].strip(), 'mod': str(data.get('mod') or data['plugin']).strip(), 'npcs': npcs}


def line_for(fact: dict, value: int) -> str:
    """The fact's line for this value: the first whose range holds it; '' for none."""
    for line in fact.get('lines') or []:
        if line['min'] <= value <= line['max']:
            return line['text']
    return ''


def load_folder(root: str) -> dict[str, dict]:
    """{plugin (lower case): file} from root/user, root/shipped and root/generated, the first folder winning."""
    out = {}
    for folder in FOLDERS:
        path = os.path.join(root, folder)
        try:
            names = sorted(n for n in os.listdir(path) if n.lower().endswith('.json'))
        except OSError:
            continue
        for name in names:
            try:
                with open(os.path.join(path, name), encoding='utf-8-sig') as f:
                    data = clean_file(json.load(f))
            except (OSError, ValueError):
                continue
            if data and data['plugin'].lower() not in out:
                out[data['plugin'].lower()] = dict(data, folder=folder, file=name)
    return out


def facts_for(files: dict, installed, npc_ref: tuple[str, int] | None, name: str, value_of) -> list[tuple[str, str]]:
    """(mod, line) for one NPC, as the game side builds them: files of installed plugins only, the NPC matched by its
    reference or (when the file gives none) by name, each fact's form from an installed plugin, value_of(kind, form)
    -> int or None. At most MAX_LINES."""
    have = {p.lower() for p in installed}
    out = []
    for data in files.values():
        if data['plugin'].lower() not in have:
            continue
        for npc in data['npcs']:
            ref = form_ref(npc['npc'])
            if not ((ref and npc_ref and ref[0].lower() == npc_ref[0].lower() and ref[1] == npc_ref[1])
                    or (not ref and npc['name'] and npc['name'].lower() == (name or '').lower())):
                continue
            for fact in npc['facts']:
                form = form_ref(fact['form'])
                if fact['kind'] != 'relationship' and (not form or form[0].lower() not in have):
                    continue
                value = value_of(fact['kind'], form)
                text = line_for(fact, value) if isinstance(value, int) else ''
                if text and len(out) < MAX_LINES:
                    out.append((data['mod'], text))
    return out


def npc_lines(speaker: dict, player: str) -> list[str]:
    """The Background lines from the NPC's file (modfact_1 .. modfact_6, "<mod>|<text>"), {player} filled in."""
    out = []
    for i in range(1, MAX_LINES + 1):
        raw = (speaker or {}).get(f'modfact_{i}')
        if not isinstance(raw, str) or not raw.strip():
            continue
        text = raw.split('|', 1)[1] if '|' in raw else raw
        text = ' '.join(text.replace('{player}', player or 'the player').split())[:MAX_CHARS]
        if text:
            out.append(f"- {text}")
    return out


def npc_sources(speaker: dict, player: str) -> list[tuple[str, str]]:
    """(mod, line) from the NPC's file, for the NPC page (read-only, with the mod named)."""
    out = []
    for i in range(1, MAX_LINES + 1):
        raw = (speaker or {}).get(f'modfact_{i}')
        if isinstance(raw, str) and '|' in raw:
            mod, text = raw.split('|', 1)
            if text.strip():
                out.append((mod.strip(), text.replace('{player}', player or 'the player').strip()[:MAX_CHARS]))
    return out
