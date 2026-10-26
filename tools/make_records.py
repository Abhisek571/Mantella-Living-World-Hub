"""Writes the Integration Hub's plugin as Spriggit YAML (globals, quests) and its MCM Helper menu. Run from the
project root."""
import json, os

E = 'Mantella Living World - Integration Hub.esp'
G = [('000800', 'MLW_QuietLoads', 'GlobalShort', 1), ('000801', 'MLW_QuietSeconds', 'GlobalFloat', 10),
     ('000802', 'MLW_TemperDefault', 'GlobalShort', 0), ('000803', 'MLW_TemperSource', 'GlobalShort', 0),
     ('000804', 'MLW_NeverForceStart', 'GlobalShort', 1), ('000805', 'MLW_Hotkey', 'GlobalShort', 199),
     ('000806', 'MLW_SetupReminder', 'GlobalShort', 1), ('000807', 'MLW_SetupDone', 'GlobalShort', 0),
     ('000808', 'MLW_QuietScenes', 'GlobalShort', 1), ('000809', 'MLW_DebugLog', 'GlobalShort', 0)]
gid = {n: f for f, n, _, _ in G}
PROPS = {
    'MLW_Hub': ['MLW_DebugLog', 'MLW_QuietLoads', 'MLW_QuietSeconds'],
    'MLW_Setup': ['MLW_Hotkey', 'MLW_SetupDone', 'MLW_SetupReminder', 'MLW_TemperDefault', 'MLW_TemperSource'],
}
Q = {'000820': ('MLW_QuestHub', 'MLW_Hub', 'Mantella Living World - Hub'),
     '000821': ('MLW_QuestSetup', 'MLW_Setup', 'Mantella Living World - Setup')}


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, 'w', encoding='utf-8', newline='\n').write(text)


def prop(name, form):
    return f'    - MutagenObjectType: ScriptObjectProperty\n      Name: {name}\n      Object: {form}\n'


for fid, name, typ, val in G:
    write(f'esp/Globals/{name} - {fid}_{E}.yaml', f'MutagenObjectType: {typ}\nFormKey: {fid}:{E}\nEditorID: {name}\nData: {val}\n')
for fid, (eid, script, title) in Q.items():
    body = ''.join(prop(g, f'{gid[g]}:{E}') for g in sorted(PROPS[script])) + prop('PlayerRef', '000014:Skyrim.esm')
    write(f'esp/Quests/{eid} - {fid}_{E}.yaml',
          f"FormKey: {fid}:{E}\nEditorID: {eid}\nVirtualMachineAdapter:\n  Scripts:\n  - Name: {script}\n    Properties:\n{body}  FileName: ''\n"
          f"Name:\n  TargetLanguage: English\n  Value: {title}\nFlags:\n- StartGameEnabled\nNextAliasID: 0\n")
# MCM Helper menu: its own base script, and SkyUI's load-game alias on the player (same shape as TrueHUD's MCM quest).
write(f'esp/Quests/MLW_QuestMCM - 000822_{E}.yaml',
      f"FormKey: 000822:{E}\nEditorID: MLW_QuestMCM\nVirtualMachineAdapter:\n  Scripts:\n  - Name: MLW_MCM\n    Properties:\n"
      f"    - MutagenObjectType: ScriptStringProperty\n      Name: ModName\n      Data: Mantella Living World\n  FileName: ''\n"
      f"  Aliases:\n  - Property:\n      Name: ''\n      Object: 000822:{E}\n      Alias: 0\n    Scripts:\n    - Name: SKI_PlayerLoadGameAlias\n"
      f"Name:\n  TargetLanguage: English\n  Value: Mantella Living World - MCM\nFlags:\n- StartGameEnabled\n- RunOnce\nNextAliasID: 1\n"
      f"Aliases:\n- Name: PlayerAlias\n  Flags: []\n  ForcedReference: 000014:Skyrim.esm\n  VoiceTypes: Null\n")
write('esp/RecordData.yaml', f'ModKey: {E}\nGameRelease: SkyrimSE\nModHeader:\n  Flags:\n  - Small\n  Author: itsPigeon2000\n'
      '  Description: Mantella Living World - Integration Hub. Shared services for the Living World modules.\n'
      '  MasterReferences:\n  - Master: Skyrim.esm\n    FileSize: 0\n  - Master: Update.esm\n    FileSize: 0\n')
write('esp/spriggit-meta.json', json.dumps({'PackageName': 'Spriggit.Yaml.Skyrim', 'Version': '0.40.0', 'Release': 'SkyrimSE', 'ModKey': E}, indent=2))


def g(name):
    return {'sourceType': 'GlobalValue', 'sourceForm': f'{E}|{gid[name].lstrip("0")}'}


def toggle(text, name, help_):
    return {'text': text, 'type': 'toggle', 'help': help_, 'valueOptions': g(name)}


MCM = {
    'modName': E[:-4], 'displayName': 'Mantella Living World', 'minMcmVersion': 9, 'cursorFillMode': 'topToBottom',
    'pages': [{
        'pageDisplayName': 'Hub',
        'content': [
            {'text': 'Quiet outfits', 'type': 'header'},
            toggle('During scenes', 'MLW_QuietScenes', "Modules hide Mantella's equip and unequip lines while a scene undresses and redresses everyone."),
            toggle('After loading screens', 'MLW_QuietLoads', "Hide Mantella's equip and unequip lines right after a loading screen, when outfits are put back on."),
            {'text': 'Quiet for (seconds)', 'type': 'slider', 'help': 'How long the quiet lasts after a loading screen or a scene.',
             'valueOptions': dict(g('MLW_QuietSeconds'), min=0, max=30, step=1, formatString='{0} s')},
            {'text': 'Temperament', 'type': 'header'},
            {'text': 'Default temperament', 'type': 'enum', 'help': 'For NPCs without their own setting. Set one NPC: aim at her and press the hotkey.',
             'valueOptions': dict(g('MLW_TemperDefault'), options=['Auto', 'Reserved', 'Bold', 'Forward'])},
            {'text': 'Auto judges lust from', 'type': 'enum', 'help': "Mantella's appetite rating (OSL values until rated), or OSL Aroused values only.",
             'valueOptions': dict(g('MLW_TemperSource'), options=['Appetite rating', 'OSL values only'])},
            toggle('Never force-start a scene', 'MLW_NeverForceStart', "NPCs at peak arousal beg but never start a scene without the player's yes."),
            {'text': 'Hotkey', 'type': 'keymap', 'help': 'Aim at an NPC: set her temperament. Aim at nobody: run setup.', 'valueOptions': g('MLW_Hotkey')},
            toggle('Setup reminder', 'MLW_SetupReminder', 'Remind at game launch while setup has not been run.'),
        ],
    }, {
        'pageDisplayName': 'Troubleshooting',
        'content': [
            {'text': 'Bug reports', 'type': 'header'},
            {'text': 'Write report', 'type': 'text', 'help': r"Writes SKSE\Plugins\MantellaLivingWorld\report.txt (with MO2: the overwrite folder): versions, installed modules and mods, settings, quiet state, the Mantella conversation and the last debug lines. Attach it with Mantella's logging.log.",
             'valueOptions': {'value': 'Click'}, 'action': {'type': 'CallFunction', 'function': 'WriteReport'}},
            toggle('Debug log', 'MLW_DebugLog', r'Modules write what they do to SKSE\Plugins\MantellaLivingWorld\debug.log. Turn on while reproducing a problem, then write a report.'),
        ],
    }],
}
write(f'MCM/Config/{E[:-4]}/config.json', json.dumps(MCM, indent=2))
print('hub records written:', len(G), 'globals, 3 quests, MCM page')
