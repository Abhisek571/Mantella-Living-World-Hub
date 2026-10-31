"""Writes the Integration Hub's plugin as Spriggit YAML (globals, quests) and its MCM Helper menu. Run from the
project root."""
import json, os

E = 'Mantella Living World - Integration Hub.esp'
G = [('000800', 'MLW_QuietLoads', 'GlobalShort', 1), ('000801', 'MLW_QuietSeconds', 'GlobalFloat', 10),
     ('000802', 'MLW_TemperDefault', 'GlobalShort', 0), ('000803', 'MLW_TemperSource', 'GlobalShort', 0),
     ('000804', 'MLW_NeverForceStart', 'GlobalShort', 1), ('000805', 'MLW_Hotkey', 'GlobalShort', 199),
     ('000806', 'MLW_SetupReminder', 'GlobalShort', 1), ('000807', 'MLW_SetupDone', 'GlobalShort', 0),
     ('000808', 'MLW_QuietScenes', 'GlobalShort', 1), ('000809', 'MLW_DebugLog', 'GlobalShort', 0),
     ('00080A', 'MLW_PaceHourly', 'GlobalShort', 6), ('00080B', 'MLW_SetupPowerOn', 'GlobalShort', 1)]
gid = {n: f for f, n, _, _ in G}
PROPS = {
    'MLW_Hub': ['MLW_DebugLog', 'MLW_QuietLoads', 'MLW_QuietSeconds'],
    'MLW_Channel': [],
    'MLW_Setup': ['MLW_Hotkey', 'MLW_SetupDone', 'MLW_SetupReminder', 'MLW_TemperDefault', 'MLW_TemperSource'],
}
Q = {'000820': ('MLW_QuestHub', 'MLW_Hub', 'Mantella Living World - Hub'),
     '000821': ('MLW_QuestSetup', 'MLW_Setup', 'Mantella Living World - Setup'),
     '000823': ('MLW_QuestChannel', 'MLW_Channel', 'Mantella Living World - Channel')}


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
# Living World Setup power: a free Lesser Power that does what the hotkey does (MLW_SetupPower calls MLW_Setup.Trigger).
# Silent and invisible: a self-delivered script effect with no shaders, art or sounds. MLW_Setup adds it to the player.
POWER_TEXT = 'Aim at an NPC to set her temperament, or at nobody to run the setup.'
write(f'esp/MagicEffects/MLW_SetupPowerEffect - 000830_{E}.yaml',
      f"FormKey: 000830:{E}\nEditorID: MLW_SetupPowerEffect\nVirtualMachineAdapter:\n  Scripts:\n  - Name: MLW_SetupPower\n"
      f"Name:\n  TargetLanguage: English\n  Value: Living World Setup\n"
      f"Flags:\n- NoHitEvent\n- NoDuration\n- NoMagnitude\n- NoArea\n- Painless\n- NoHitEffect\n"
      f"Archetype:\n  MutagenObjectType: MagicEffectArchetype\n  Type: Script\n"
      f"CastType: FireAndForget\nCastingSoundLevel: Silent\nSounds: []\n"
      f"Description:\n  TargetLanguage: English\n  Value: {POWER_TEXT}\n")
write(f'esp/Spells/MLW_SetupPower - 000831_{E}.yaml',
      f"FormKey: 000831:{E}\nEditorID: MLW_SetupPower\nName:\n  TargetLanguage: English\n  Value: Living World Setup\n"
      f"EquipmentType: 025BEE:Skyrim.esm\n"  # Voice, like vanilla powers
      f"Description:\n  TargetLanguage: English\n  Value: {POWER_TEXT}\n"
      f"Type: LesserPower\nCastType: FireAndForget\nEffects:\n- BaseEffect: 000830:{E}\n  Data: {{}}\n")
write('esp/RecordData.yaml', f'ModKey: {E}\nGameRelease: SkyrimSE\nModHeader:\n  Flags:\n  - Small\n  Author: itsPigeon2000\n'
      '  Description: Mantella Living World - Integration Hub. Shared services for the Living World modules.\n'
      '  MasterReferences:\n  - Master: Skyrim.esm\n    FileSize: 0\n  - Master: Update.esm\n    FileSize: 0\n')
write('esp/spriggit-meta.json', json.dumps({'PackageName': 'Spriggit.Yaml.Skyrim', 'Version': '0.40.0', 'Release': 'SkyrimSE', 'ModKey': E}, indent=2))


def g(name):
    return {'sourceType': 'GlobalValue', 'sourceForm': f'{E}|{gid[name].lstrip("0")}'}


def toggle(text, name, help_):
    return {'text': text, 'type': 'toggle', 'help': help_, 'valueOptions': g(name)}


def status(text, prop, help_):
    return {'text': text, 'type': 'toggle', 'help': help_, 'groupCondition': 1,
            'valueOptions': {'sourceType': 'PropertyValueBool', 'propertyName': prop}}


# Module status page: (label, MLW_MCM property, help). MLW_MCM.CheckModules fills the properties.
MODULES = [
    ('Integration Hub', 'HasHub', 'The shared base. Every module needs it.'),
    ('OStim Expansion', 'HasOStimExpansion', 'Scene flows, scene talk and bystanders. Needs OStim Standalone.'),
    ('Arousal', 'HasArousal', 'Arousal, appetite, satisfied and overwhelmed. Needs OSL Aroused.'),
    ('Relationships', 'HasRelationships', "Marriage and shared history. Needs M.A.R.A.S or Lover's Ledger."),
    ('Followers', 'HasFollowers', "Join, leave, wait, follow, passive, wear this. Needs Nether's Follower Framework."),
    ('World', 'HasWorld', 'Fame, crime, quest outcomes, who knows whom, banter, NPCs who come to talk.'),
]
WORLD = 'Mantella Living World - World.esp'


def world_g(fid):
    return {'sourceType': 'GlobalValue', 'sourceForm': f'{WORLD}|{fid}'}
MODS = [
    ('Mantella', 'HasMantella', "Required by everything. Turn on Advanced Actions in the Actions tab of Mantella's settings."),
    ('OStim Standalone', 'HasOStim', 'Used by OStim Expansion.'),
    ('OSL Aroused', 'HasOSL', 'Used by Arousal.'),
    ('M.A.R.A.S', 'HasMARAS', 'Used by Relationships and Arousal.'),
    ("Lover's Ledger", 'HasLedger', 'Used by Relationships.'),
    ('Relations Finder', 'HasRelationsFinder', "Used by Relationships for each NPC's family and ties."),
    ("Nether's Follower Framework", 'HasNFF', 'Used by Followers.'),
]


MCM = {
    'modName': E[:-4], 'displayName': 'Mantella Living World', 'minMcmVersion': 9, 'cursorFillMode': 'topToBottom',
    'pages': [{
        'pageDisplayName': 'Hub',
        'content': [
            {'text': 'Quiet outfits', 'type': 'header'},
            toggle('During scenes', 'MLW_QuietScenes', "OStim Expansion and Followers ask the hub to hide Mantella's equip and unequip lines while a scene undresses and redresses everyone. Does nothing without one of them."),
            toggle('After loading screens', 'MLW_QuietLoads', "Hide Mantella's equip and unequip lines right after a loading screen, when outfits are put back on."),
            {'text': 'Quiet for (seconds)', 'type': 'slider', 'help': 'How long the quiet lasts after a loading screen or a scene.',
             'valueOptions': dict(g('MLW_QuietSeconds'), min=0, max=30, step=1, formatString='{0} s')},
            {'text': 'Temperament', 'type': 'header'},
            {'text': 'Default temperament', 'type': 'enum', 'help': 'For NPCs without their own setting. Only has an effect with the Arousal module. Set one NPC: aim at her and press the hotkey.',
             'valueOptions': dict(g('MLW_TemperDefault'), options=['Auto', 'Reserved', 'Bold', 'Forward'])},
            {'text': 'Auto judges lust from', 'type': 'enum', 'help': "Mantella's appetite rating (OSL values until rated), or OSL Aroused values only. Only has an effect with the Arousal module; the appetite rating needs Mantella's Advanced Actions on.",
             'valueOptions': dict(g('MLW_TemperSource'), options=['Appetite rating', 'OSL values only'])},
            toggle('Never force-start a scene', 'MLW_NeverForceStart', "NPCs at peak arousal beg but never start a scene without the player's yes. Only has an effect with the Arousal module."),
            {'text': 'Hotkey', 'type': 'keymap', 'help': 'Aim at an NPC: set her temperament. Aim at nobody: run the setup (default temperament, only matters with the Arousal module). Temperament needs the Arousal module.', 'valueOptions': g('MLW_Hotkey')},
            toggle('Setup power in magic menu', 'MLW_SetupPowerOn', 'The Living World Setup power does what the hotkey does: cast it aiming at an NPC or at nobody. For controllers or a hotkey clash.'),
            toggle('Setup reminder', 'MLW_SetupReminder', 'Remind after loading while the setup has not been run. The setup only matters with the Arousal module.'),
        ],
    }, {
        'pageDisplayName': 'Module status',
        'content': [
            # Read-only: the checks are filled in when the menu opens; group 1 is never on, so they cannot be clicked.
            {'type': 'hiddenToggle', 'groupControl': 1, 'valueOptions': {'sourceType': 'PropertyValueBool', 'propertyName': 'Never'}},
            {'text': 'Mantella Living World', 'type': 'header'},
        ] + [status(t, p, h) for t, p, h in MODULES] + [
            {'text': 'Works with', 'type': 'header'},
        ] + [status(t, p, h) for t, p, h in MODS],
    }, {
        'pageDisplayName': 'World',
        'content': [
            {'text': 'Needs Mantella Living World - World', 'type': 'text', 'help': 'These settings do nothing without Mantella Living World - World.esp. Banter is between party members only.'},
            {'text': 'Banter', 'type': 'header'},
            {'text': 'Party banter', 'type': 'toggle', 'valueOptions': world_g('810'),
             'help': 'A party member may react to a line said nearby, to walking into an inn or to the end of a fight.'},
            {'text': 'Chance to react', 'type': 'slider', 'help': 'How often a party member reacts when banter could start.',
             'valueOptions': dict(world_g('811'), min=0, max=100, step=5, formatString='{0}%')},
            {'text': 'NPCs who come to talk', 'type': 'header'},
            {'text': 'Come over to talk', 'type': 'toggle', 'valueOptions': world_g('812'),
             'help': 'An NPC with something to tell you (a promise, a job, news) walks up and starts a talk.'},
            {'text': 'Pacing', 'type': 'header'},
            {'text': 'Ambient lines per hour', 'type': 'slider', 'help': 'Most banter and walk-up talks per real hour, all together.',
             'valueOptions': dict(g('MLW_PaceHourly'), min=1, max=20, step=1, formatString='{0}')},
            {'text': 'Reset pacing', 'type': 'text', 'help': 'Forget the cooldowns and the count for this hour.',
             'valueOptions': {'value': 'Click'}, 'action': {'type': 'CallFunction', 'function': 'ResetPace'}},
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
print('hub records written:', len(G), 'globals, 4 quests, 1 magic effect, 1 spell, MCM page')
