"""Writes the Nexus description BBCode for every Mantella Living World mod, with native [table]s (Nexus renders
them). Only charts are images (nexus_images.py). Output: <project>/nexus/description.bbcode

usage: py -3 nexus_pages.py
"""
import os
from nexus_images import TABLES, PROJECTS, CODING

NEXUS = 'https://www.nexusmods.com/skyrimspecialedition/mods/'
IDS = {'hub': 196849, 'ostim': 196850, 'arousal': 196851, 'relationships': 196852}
FLOW_IMG = 'https://staticdelivery.nexusmods.com/mods/1704/images/196850/196850-1793005727-1382186894.png'


def link(name, mod_id):
    return f'[url={NEXUS}{mod_id}]{name}[/url]'


def table(head, rows):
    out = ['[table]', '[tr]' + ''.join(f'[th]{h}[/th]' for h in head) + '[/tr]']
    out += ['[tr]' + ''.join(f'[td]{c}[/td]' for c in r) + '[/tr]' for r in rows]
    return '\n'.join(out + ['[/table]'])


def section(title, body):
    return f'[size=3]{title}[/size]\n{body}'


def tbl(key, name):
    title, head, rows = TABLES[key][name]
    return section(title, table(head, rows))


def bullets(items, ordered=False):
    return ('[list=1]' if ordered else '[list]') + '\n' + '\n'.join(f'[*]{i}' for i in items) + '\n[/list]'


HUB = link('Mantella Living World - Integration Hub', IDS['hub'])
MANTELLA = link('Mantella', 98631)


def requirements(rows):
    return section('Requirements', table(['Mod', 'Needed'], rows))


PAGES = {
    'hub': [
        '[size=4]Mantella Living World - Integration Hub[/size]',
        'The shared base of Mantella Living World. Install it once, then add only the modules you want.',
        section('All modules', '[spoiler]\n' + table(['Module', 'Link'], [
            ['Integration Hub (required)', link('Nexus page', IDS['hub'])],
            ['OStim Expansion', link('Nexus page', IDS['ostim'])],
            ['Arousal', link('Nexus page', IDS['arousal'])],
            ['Relationships', link('Nexus page', IDS['relationships'])],
        ]) + '\n[/spoiler]'),
        tbl('hub', 'modules'),
        tbl('hub', 'features'),
        requirements([[MANTELLA, 'Yes'], ['SKSE, PapyrusUtil, MCM Helper', 'Yes']]),
        section('Installation', bullets(['Install with your mod manager.', 'Tick the modules you want in the installer.',
                                         'Load the plugins anywhere after Mantella.'], ordered=True)),
        section('Notes', bullets(['Modules need only the hub, never each other.', 'Uninstalling a module just removes its feature.'])),
    ],
    'ostim': [
        '[size=4]Mantella Living World - OStim Expansion[/size]',
        'Mantella NPCs who live through OStim scenes with you: scenes that flow on their own, and partners who react, talk and remember.',
        tbl('ostim', 'features'),
        section('How a scene flows', f'[img]{FLOW_IMG}[/img]'),
        tbl('ostim', 'talk'),
        requirements([[HUB, 'Yes'], [MANTELLA, 'Yes'], [link('OStim Standalone', 98163) + ' and an animation pack', 'Yes'],
                      [link('Mantella Living World - Arousal', IDS['arousal']), 'Recommended']]),
        section('Installation', bullets(['Install the hub, then this module.',
                                         'Close the game and run Build Flows.exe (reads your animation packs).',
                                         'Enable the generated Flows mod in your mod manager.',
                                         'Run Build Flows again whenever you add or remove animation packs.'], ordered=True)),
        section('Settings', bullets(["OStim's MCM, page \"Adult Expansion\": flows, finish point, talk chance, bystanders, never force a scene."])),
    ],
    'arousal': [
        '[size=4]Mantella Living World - Arousal[/size]',
        'Tells Mantella how aroused NPCs are, so they act on it in their own way.',
        tbl('arousal', 'temperament'),
        tbl('arousal', 'appetite'),
        requirements([[HUB, 'Yes'], [MANTELLA, 'Yes'], [link('OSL Aroused', 65454), 'Yes']]),
        section('Notes', bullets(['Climaxes are counted from OStim scenes and from what NPCs report in conversation.',
                                  'Temperament is set per NPC in the hub (hotkey) or left on Auto.'])),
    ],
    'relationships': [
        '[size=4]Mantella Living World - Relationships[/size]',
        'Mantella NPCs who know where they stand with you.',
        tbl('relationships', 'parts'),
        requirements([[HUB, 'Yes'], [MANTELLA, 'Yes'], [link('M.A.R.A.S', 159033), 'Optional'],
                      [link('Romantasy', 186060), 'Optional'], [link("Lover's Ledger", 158983), 'Optional']]),
        section('Notes', bullets(['Each part runs only when its mod is installed.'])),
    ],
}


def main():
    for key, parts in PAGES.items():
        path = os.path.join(CODING, PROJECTS[key], 'nexus', 'description.bbcode')
        open(path, 'w', encoding='utf-8', newline='\n').write('\n\n'.join(parts) + '\n')
        print(path)


if __name__ == '__main__':
    main()
