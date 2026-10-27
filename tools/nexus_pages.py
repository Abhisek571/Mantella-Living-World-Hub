"""Writes the Nexus description BBCode for every Mantella Living World mod in the approved page style
(D:\\coding\\nexus-assets\\nexus-page-style.md): no title, centered green headings, one-line tables, closed list items,
images in spoilers. Output: <project>/nexus/description.bbcode. Paste it in the editor's source mode.

usage: py -3 nexus_pages.py
"""
import os
from nexus_images import TABLES, CODING

NEXUS = 'https://www.nexusmods.com/skyrimspecialedition/mods/'
GITHUB = 'https://github.com/Abhisek571/'
IDS = {'hub': 196849, 'ostim': 196850, 'arousal': 196851, 'relationships': 196852, 'followers': int(os.environ.get('MLW_FOLLOWERS_ID', 0)) or None}
DIRS = {'hub': 'Mantella-Living-World-Hub', 'ostim': 'Mantella-Adult-Expansion-OStim', 'arousal': 'Mantella-OSL-Aroused-Bridge',
        'relationships': 'Mantella-Relationship-Bridge', 'followers': 'Mantella-Living-World-Followers'}
REPOS = {'hub': 'Mantella-Living-World-Hub', 'ostim': 'Mantella-Living-World-OStim-Expansion', 'arousal': 'Mantella-Living-World-Arousal',
         'relationships': 'Mantella-Living-World-Relationships', 'followers': 'Mantella-Living-World-Followers'}
NAMES = {'hub': 'Integration Hub', 'ostim': 'OStim Expansion', 'arousal': 'Arousal', 'relationships': 'Relationships', 'followers': 'Followers'}
ACCENT = '#93c47d'
GREY = '#888888'
FLOW_IMG = 'https://staticdelivery.nexusmods.com/mods/1704/images/196850/196850-1793033586-163909772.png'
CHART_IMG = os.environ.get('MLW_CHART_IMG', '')  # the hub breakdown chart once uploaded to the hub's gallery


def link(name, mod_id):
    return f'[url={NEXUS}{mod_id}]{name}[/url]' if mod_id else name


def module(key):
    return link('Mantella Living World - ' + NAMES[key], IDS[key])


def heading(title):
    return f'[center][size=5][font=Trebuchet MS][b][color={ACCENT}]{title.upper()}[/color][/b][/font][/size][/center]'


def table(head, rows):
    # One line: newlines inside [table] show as gaps on Nexus.
    return ('[table][tr]' + ''.join(f'[th]{h}[/th]' for h in head) + '[/tr]'
            + ''.join('[tr]' + ''.join(f'[td]{c}[/td]' for c in r) + '[/tr]' for r in rows) + '[/table]')


def tbl(key, name):
    _, head, rows = TABLES[key][name]
    return table(head, rows)


def bullets(items, ordered=False):
    # Closed items, [/list] right after the last one: otherwise the last bullet gets a stray line break.
    return ('[list=1]' if ordered else '[list]') + '\n' + ''.join(f'[*]{i}[/*]' for i in items) + '[/list]'


def grey(text):
    return f'[color={GREY}]{text}[/color]'


def spoiler(img):
    return f'[spoiler][img]{img}[/img][/spoiler]'


MANTELLA = link('Mantella', 98631)
HUB = module('hub')
SKSE = '[b]SKSE team[/b], [b]exiledviper[/b] and [b]meh321[/b] for SKSE and PapyrusUtil'
MAX_TOKENS = grey("Mantella's default response length (max_tokens 250) can cut replies off once modules add their lines. "
                  "If NPCs go quiet or stop mid-sentence, raise it to 500 in Mantella's LLM settings.")


def page(key, intro, sections, requirements, install, notes, credits_extra):
    """Sections are (heading, body) pairs. A list or table already has space below it, so the next heading follows
    directly; after a spoiler one line break, after text a blank line. Every gap on the page comes out the same."""
    blocks = list(sections) + [('Requirements', bullets(requirements)), ('Installation', bullets(install, True))]
    if notes:
        blocks.append(('Notes', bullets(notes)))
    blocks.append(('Source and license', f'[url={GITHUB}{REPOS[key]}]GitHub[/url], GNU AGPL-3.0 (Mantella is AGPL-3.0). '
                                          'Unofficial, not endorsed by the authors of the mods it works with.'))
    blocks.append(('Credits', bullets(['[b]Art from the Machine[/b] and contributors for ' + MANTELLA] + credits_extra)))
    out = intro
    for title, body in blocks:
        joiner = '' if out.endswith(('[/list]', '[/table]')) else ('\n' if out.endswith('[/spoiler]') else '\n\n')
        out += joiner + heading(title) + body
    return out + '\n'


def pages():
    return {
        'hub': page('hub',
                    'The shared base of Mantella Living World. Install it once, then add only the modules you want. '
                    'Modules never need each other, only the hub.\n\n' + MAX_TOKENS,
                    [('Modules', table(['Module', 'Adds', 'Needs'], [
                        [module('ostim'), 'Scene flows, scene talk, bystanders, favourite positions', 'OStim Standalone'],
                        [module('arousal'), 'Arousal, appetite, satisfied and overwhelmed', 'OSL Aroused'],
                        [module('relationships'), 'Marriage, shared history', "MARAS or Lover's Ledger"],
                        [module('followers'), 'Join, leave, wait, follow, passive, wear this', "Nether's Follower Framework"],
                    ]) + (('\n' + spoiler(CHART_IMG)) if CHART_IMG else '')),
                     ('What the hub does', table(['Feature', 'Effect'], [
                         ['Quiet outfits', 'No equip / unequip spam in conversations during scenes, outfit changes and after loading screens'],
                         ['Temperament', 'Reserved, bold or forward per NPC; set with a hotkey'],
                         ['Module status', 'MCM page with a check for each installed module and supported mod'],
                         ['Troubleshooting', 'Writes a report for bug reports; optional debug log'],
                         ['Settings', 'One MCM page for the hub and its shared settings'],
                     ]))],
                    [MANTELLA + ' 0.14', link('SKSE', 30379), link('PapyrusUtil', 13048), link('MCM Helper', 53000),
                     link('Papyrus MessageBox', 83578)],
                    ['Install with your mod manager and enable the plugin.', 'Add the modules you want, each from its own page.',
                     'Run the setup when the game reminds you, or press the hotkey with nobody targeted.'],
                    ['Bug? MCM, page Troubleshooting: turn on the debug log, reproduce it, then Write report. '
                     r"Attach SKSE\Plugins\MantellaLivingWorld\report.txt and Mantella's logging.log."],
                    [SKSE, '[b]Parapets[/b] for MCM Helper, [b]SkyUI team[/b] for SkyUI', '[b]mrowrpurr[/b] for Papyrus MessageBox']),
        'ostim': page('ostim',
                      'Mantella NPCs who live through OStim scenes with you: scenes that flow on their own, and partners who react, talk and remember.',
                      [('Features', tbl('ostim', 'features')),
                       ('What Mantella hears', tbl('ostim', 'talk') + '\n' + spoiler(FLOW_IMG))],
                      [HUB, MANTELLA + ' 0.14', link('OStim Standalone', 98163) + ' and at least one animation pack',
                       link('Mantella Living World - Arousal', IDS['arousal']) + ' (recommended)'],
                      ['Install the hub, then this module.',
                       "Close the game and run Build Flows (in the mod's tools folder; needs Python and Mod Organizer 2).",
                       'Enable the generated Flows mod.', 'Run Build Flows again whenever you add or remove animation packs.'],
                      ['Settings: OStim\'s MCM, page "Living World".', 'Flows stay two-person; group scenes still get scene talk.'],
                      ['[b]OStim team[/b] for ' + link('OStim Standalone', 98163), SKSE]),
        'arousal': page('arousal',
                        'Tells Mantella how aroused NPCs are, so they act on it in their own way.',
                        [('Temperament', tbl('arousal', 'temperament')), ('Appetite', tbl('arousal', 'appetite'))],
                        [HUB, MANTELLA + ' 0.14', link('OSL Aroused', 65454)],
                        ['Install the hub, then this module.'],
                        ['Climaxes are counted from OStim scenes and from what NPCs report in conversation.',
                         "Temperament is set per NPC with the hub's hotkey, or left on Auto."],
                        ['[b]ozooma10[/b] for ' + link('OSL Aroused', 65454), SKSE]),
        'relationships': page('relationships',
                              'Mantella NPCs who know where they stand with you.',
                              [('What Mantella learns', tbl('relationships', 'parts'))],
                              [HUB, MANTELLA + ' 0.14', link('M.A.R.A.S', 159033) + ' (optional)',
                               link("Lover's Ledger", 158983) + ' (optional)'],
                              ['Install the hub, then this module.'],
                              ['Each part runs only when its mod is installed.'],
                              ["[b]TangyTweaks[/b] for M.A.R.A.S and Lover's Ledger", SKSE]),
        'followers': page('followers',
                          'Mantella actions for ' + link("Nether's Follower Framework", 55653) + ': talk an NPC into your party, '
                          'tell them to wait, follow, stay out of fights, or hand them clothes to wear.',
                          [('Actions', table(['Action', 'What happens'], [
                              ['JoinParty / LeaveParty', 'The NPC joins or leaves your NFF party'],
                              ['WaitHere / FollowMe', 'Only that follower waits or follows again'],
                              ['EveryoneWait / EveryoneFollow', 'The whole party'],
                              ['StayPassive / FightFreely', 'Stays out of fights, or attacks enemies and helps allies'],
                              ['WearThis', 'Opens trade; what you hand over becomes their NFF outfit for where you are'],
                          ]) + '\n' + grey("Every order goes through NFF itself, so NFF's menu always shows the same state."))],
                          [HUB, MANTELLA + ' 0.14', link("Nether's Follower Framework", 55653)],
                          ['Install the hub, then this module.', "In the Mantella UI's action settings, turn off Mantella's own Follow, Unfollow and Wait."],
                          ["Wear this saves the outfit for where you are: adventuring, town or home (NFF's own outfit slots).",
                           'NFF shows a one-time notice the first time an outfit is stored.'],
                          ['[b]Nether[/b] for ' + link("Nether's Follower Framework", 55653), SKSE]),
    }


def main():
    for key, text in pages().items():
        path = os.path.join(CODING, DIRS[key], 'nexus', 'description.bbcode')
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, 'w', encoding='utf-8', newline='\n').write(text)
        print(path)


if __name__ == '__main__':
    main()
