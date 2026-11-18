"""Offline tests for mod facts: the fact file format, value-to-line mapping, the folders' priority, the caps, where the
lines land in the prompt and when they change, the game side's reader (source checks), the shipped files, and the
scanner on the real plugins when they are on this PC.
Run with a Python 3.11: test_mod_facts.py <repo server dir>"""
import json, os, re, sys, tempfile
from pathlib import Path

SERVER = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(SERVER))
from living_world import mod_facts as M, mod_facts_gen as G, npc_block

REPO = SERVER.parent
SHIPPED = REPO / 'SKSE' / 'Plugins' / 'StorageUtilData' / 'MantellaLivingWorld' / 'modfacts'
MO2 = os.environ.get('MLW_MO2', '')
FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)[:700]) if not cond else ''))
    if not cond:
        FAILS.append(name)


GERDUR = {'format': 1, 'plugin': 'shadowman_gerdur.esp', 'mod': 'Gerdur Handling Wood', 'npcs': [
    {'npc': 'Skyrim.esm|0x01347C', 'name': 'Gerdur', 'facts': [
        {'kind': 'global', 'form': 'shadowman_gerdur.esp|0x000897',
         'lines': [{'min': 1, 'max': 1, 'text': 'once'}, {'min': 2, 'max': 4, 'text': 'several times'}, {'min': 5, 'max': 99, 'text': 'affair'}]},
        {'kind': 'relationship', 'lines': [{'min': 3, 'max': 4, 'text': 'lover by rank'}]},
        {'kind': 'bogus', 'form': 'x|1', 'lines': [{'min': 0, 'max': 1, 'text': 'never'}]}]}]}


def part_format():
    data = M.clean_file(GERDUR)
    facts = data['npcs'][0]['facts']
    check('a file is read with its usable facts only (an unknown kind is dropped)', [f['kind'] for f in facts] == ['global', 'relationship'])
    check('values map to the first line whose range holds them; none for the start value',
          [M.line_for(facts[0], v) for v in (0, 1, 3, 5, 120)] == ['', 'once', 'several times', 'affair', ''])
    check('a form reference is plugin|hex in any letter case', M.form_ref('Shadowman_Gerdur.ESP|0x000897') == ('Shadowman_Gerdur.ESP', 0x897)
          and M.form_ref('Skyrim.esm|1347c') == ('Skyrim.esm', 0x1347C) and M.form_ref('nope') is None)
    check('a file with no plugin or no usable fact is nothing', M.clean_file({'npcs': []}) is None and M.clean_file({'plugin': 'a.esp', 'npcs': []}) is None)
    long = dict(GERDUR, npcs=[dict(GERDUR['npcs'][0], facts=[dict(GERDUR['npcs'][0]['facts'][0], lines=[{'min': 1, 'max': 1, 'text': 'x' * 400}])])])
    check(f'a line is cut to {M.MAX_CHARS} characters', len(M.clean_file(long)['npcs'][0]['facts'][0]['lines'][0]['text']) == M.MAX_CHARS)


def part_folders(tmp):
    root = tmp / 'modfacts'
    for folder, text in (('generated', 'generated line'), ('shipped', 'shipped line'), ('user', 'user line')):
        (root / folder).mkdir(parents=True)
        data = json.loads(json.dumps(GERDUR))
        data['npcs'][0]['facts'][0]['lines'][0]['text'] = text
        (root / folder / 'gerdur.json').write_text(json.dumps(data), encoding='utf-8')
    other = dict(GERDUR, plugin='other.esp')
    (root / 'generated' / 'other.json').write_text(json.dumps(other), encoding='utf-8')
    files = M.load_folder(str(root))
    check('for the same plugin the user file wins over shipped and generated', files['shadowman_gerdur.esp']['folder'] == 'user'
          and files['shadowman_gerdur.esp']['npcs'][0]['facts'][0]['lines'][0]['text'] == 'user line')
    (root / 'user' / 'gerdur.json').unlink()
    check('...shipped over generated', M.load_folder(str(root))['shadowman_gerdur.esp']['folder'] == 'shipped')
    value = lambda kind, form: {'global': 1, 'relationship': 4}.get(kind)
    got = M.facts_for(files, ['Skyrim.esm', 'shadowman_gerdur.esp'], ('Skyrim.esm', 0x1347C), 'Gerdur', value)
    check('the game-side rule: an installed plugin, the NPC by reference, each fact by its value', got == [('Gerdur Handling Wood', 'user line'), ('Gerdur Handling Wood', 'lover by rank')], got)
    check('a plugin that is not installed gives nothing', M.facts_for(files, ['Skyrim.esm'], ('Skyrim.esm', 0x1347C), 'Gerdur', value) == [])
    check('another NPC gets nothing', M.facts_for(files, ['Skyrim.esm', 'shadowman_gerdur.esp'], ('Skyrim.esm', 0x13476), 'Sigrid', value) == [])
    many = dict(GERDUR, npcs=[dict(GERDUR['npcs'][0], facts=[{'kind': 'relationship', 'lines': [{'min': -4, 'max': 4, 'text': f'fact {i}'}]} for i in range(9)])])
    capped = M.facts_for({'x': M.clean_file(many)}, ['shadowman_gerdur.esp', 'Skyrim.esm'], ('Skyrim.esm', 0x1347C), 'Gerdur', value)
    check(f'at most {M.MAX_LINES} lines per NPC', len(capped) == M.MAX_LINES, len(capped))


def part_prompt():
    speaker = {'name': 'Gerdur', 'ref_id': '0001347C', 'base_id': '01347C', 'race': 'Nord', 'sex': 'female',
               'modfact_1': "Gerdur Handling Wood|Gerdur gave in once to {player}; she keeps it from Hod.", 'modfact_2': '',
               'modfact_7': 'X|never read'}
    text = npc_block.npc_text(None, speaker, [('Gerdur', '01347C')], 'Brom', bio_changes=False)
    check('the facts land in the Background part, the player named, the mod name left out',
          '- Gerdur gave in once to Brom; she keeps it from Hod.' in text and text.index('Background facts about Gerdur') < text.index('gave in once')
          and 'Handling Wood' not in text and 'never read' not in text, text)
    check('the same values give the very same text (no cache rewrite between talks)',
          npc_block.npc_text(None, dict(speaker), [('Gerdur', '01347C')], 'Brom', bio_changes=False) == text)
    changed = dict(speaker, modfact_1='Gerdur Handling Wood|Gerdur is in an affair with {player}.')
    check('a changed value changes the text (one cache rewrite, only then)',
          npc_block.npc_text(None, changed, [('Gerdur', '01347C')], 'Brom', bio_changes=False) != text)
    check('the NPC page shows them read-only with the mod named', M.npc_sources(speaker, 'Brom') == [('Gerdur Handling Wood', 'Gerdur gave in once to Brom; she keeps it from Hod.')])
    src = (SERVER / 'living_world' / 'npc_block.py').read_text(encoding='utf-8')
    check('...and npc_text is what the talk freezes (built once per talk in text())', 'lines += mod_facts.npc_lines(speaker, HOODED_WORD if stranger else player)' in src
          and '_frozen[k] = npc_text(' in src)


def part_papyrus():
    psc = (REPO / 'Source' / 'Scripts' / 'MLW_ModFacts.psc').read_text(encoding='utf-8')
    channel = (REPO / 'Source' / 'Scripts' / 'MLW_Channel.psc').read_text(encoding='utf-8')
    ref = re.search(r'Form Function RefForm\(.*?EndFunction', psc, re.S).group(0)
    check('reader: a form is looked up only in an installed plugin', ref.find('Game.IsPluginInstalled(plugin)') < ref.find('Game.GetFormFromFile'))
    write = re.search(r'Function WriteNpc\(.*?EndFunction', psc, re.S).group(0)
    check('reader: user, then shipped, then generated; a file of a plugin not installed is skipped; a plugin is read once',
          write.find('"user/"') < write.find('"shipped/"') < write.find('"generated/"') and 'Game.IsPluginInstalled(plugin)' in write
          and 'done.Find(plugin) < 0' in write)
    check('reader: at most 6 lines, the rest cleared, each cut to 160 characters', 'new string[6]' in write and 'UnsetStringValue(asPath, "modfact_"' in write
          and 'StringUtil.Substring(text, 0, 160)' in psc)
    check('reader: every kind is read without changing anything of the other mod',
          all(k in psc for k in ('.GetValue()', '.GetStage()', '.IsCompleted()', '.GetFactionRank(', '.GetRelationshipRank(')) and 'SetValue' not in psc and 'SetStage' not in psc)
    check('reader: called when an NPC joins a talk, before the file is saved',
          -1 < channel.find('MLW_ModFacts.WriteNpc(akNpc, path)') < channel.find('JsonUtil.Save(path)', channel.find('MLW_ModFacts.WriteNpc')))


def part_shipped():
    files = M.load_folder(str(SHIPPED))
    check('the shipped files: Gerdur and Sigrid, read as valid', sorted(files) == ['shadowman_gerdur.esp', 'shadowman_sigrid.esp'], sorted(files))
    for key, data in files.items():
        lines = [l['text'] for n in data['npcs'] for f in n['facts'] for l in f['lines']]
        check(f'{key}: plain third-person lines within {M.MAX_CHARS} characters, no explicit word, no instruction',
              all(len(t) <= M.MAX_CHARS and not G.EXPLICIT.search(t) and not re.search(r'\b(?:you must|should|never say)\b', t, re.I) for t in lines), lines)


def part_scanner(tmp):
    gerdur = os.path.join(MO2, 'mods', '[NoDelete] Shadowmans NPCs 68 - Gerdur Handling Wood - Ostim Conversion and Redux', 'shadowman_gerdur.esp')
    if not os.path.isfile(gerdur):
        return print('SKIP the Gerdur plugin is not on this PC')
    made = G.draft('shadowman_gerdur.esp', G.read_plugin(gerdur), 'Shadowmans NPCs 68 - Gerdur Handling Wood', True)
    fact = made['npcs'][0]['facts'][0]
    check("the scanner finds Gerdur's global by its dialogue conditions (her quest's GetIsID), tested by 111 lines",
          made['npcs'][0]['npc'] == 'Skyrim.esm|0x01347C' and fact['form'] == 'shadowman_gerdur.esp|0x000897' and fact['infos'] == 111, fact)
    check('...one line per tested value above the start value (0 is where it starts)', [l['min'] for l in fact['lines']] == [1, 2, 3, 4, 5])
    check('...quoting her own line at a value, or the neutral form where her lines are explicit',
          'Said at this value: "Don\'t talk about it here! Come to my home when Hod\'s not there."' in fact['lines'][1]['text']
          and fact['lines'][0]['text'].endswith('has been intimate with {player} (gerdurfuckedstate 1 (of 0-5))'), [l['text'] for l in fact['lines']])
    check('...no explicit word in any generated line', not any(G.EXPLICIT.search(l['text'].split('Said at this value:')[-1]) for l in fact['lines']))
    check('the mod name is cut at a " - " part', G.mod_label('[NoDelete] Shadowmans NPCs 68 - Gerdur Handling Wood - Ostim Conversion and Redux', 'x.esp')
          == 'Shadowmans NPCs 68 - Gerdur Handling Wood')
    dibella = os.path.join(MO2, 'mods', "[NoDelete] Shadowmans NPCs 29 - Dibella's priestesses - Sexlab and Flower Girls", 'shadowman_dibella.esp')
    if os.path.isfile(dibella):
        got = G.draft('shadowman_dibella.esp', G.read_plugin(dibella), "Dibella's priestesses", True)
        check("Dibella's priestesses: each priestess's own global, tested by 2 of her lines, is kept (a global only her lines test)",
              got and sorted(f['editor_id'] for n in got['npcs'] for f in n['facts']) == ['anwenfucked', 'hamalfucked', 'orlafucked', 'sennafucked'], got)
    grosta = os.path.join(MO2, 'mods', '[NoDelete] Shadowmans NPCs 67 - Lonely Widow Grosta - Sexlab and Flowergirls', 'shadowman_grosta.esp')
    if os.path.isfile(grosta):
        got = G.draft('shadowman_grosta.esp', G.read_plugin(grosta), 'Lonely Widow Grosta', True)
        check("Grosta: a vanilla quest's stage her lines test (GetStage / GetStageDone) becomes a stage fact",
              got and got['npcs'][0]['facts'][0]['kind'] == 'stage' and got['npcs'][0]['facts'][0]['form'] == 'Skyrim.esm|0x0E3EA5', got)
    hulda = os.path.join(MO2, 'mods', '[NoDelete] Shadowmans NPCs 44 - Innkeeper Hulda - Sexlab and Flowergirls', 'shadowman_hulda.esp')
    if os.path.isfile(hulda):
        check('Hulda: lines gated only by who speaks (no global, stage or faction) give nothing',
              G.draft('shadowman_hulda.esp', G.read_plugin(hulda), 'Innkeeper Hulda', True) is None)
    sda = os.path.join(MO2, 'mods', '[NoDelete] Serana Dialogue Add-On', 'SeranaDialogAddon.esp')
    if os.path.isfile(sda):
        check(f'a plugin with more than {G.MAX_INFOS} dialogue lines is not drafted (Serana Dialogue Add-On)',
              G.draft('SeranaDialogAddon.esp', G.read_plugin(sda), 'Serana Dialogue Add-On', False) is None)
    out = G.write({'shadowman_gerdur.esp': made, 'x.esp': 'no state'}, str(tmp / 'generated'))
    check('the scanner writes only drafted plugins, into the folder it is given', [os.path.basename(p) for p in out] == ['shadowman_gerdur.esp.json']
          and M.clean_file(json.load(open(out[0], encoding='utf-8'))) is not None)


with tempfile.TemporaryDirectory() as tmp:
    for part in (part_format, lambda: part_folders(Path(tmp)), part_prompt, part_papyrus, part_shipped, lambda: part_scanner(Path(tmp))):
        try:
            part()
        except Exception as e:
            import traceback
            traceback.print_exc()
            check('a part ran without an error', False, e)

print(f"\n{len(FAILS)} failure(s)" if FAILS else '\nall passed')
sys.exit(1 if FAILS else 0)
