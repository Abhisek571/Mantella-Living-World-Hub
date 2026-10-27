"""Table data for the Nexus pages (written as native [table]s by nexus_pages.py) and the gallery images:
every table as a PNG (<project>/nexus/images/<name>.png, headless Chrome) and the OStim flow chart (Graphviz, flow.png).

usage: py -3 nexus_images.py
"""
import html, os, subprocess, tempfile

CHROME = r'C:\Program Files\Google\Chrome\Application\chrome.exe'
CODING = r'D:\coding'
PROJECTS = {
    'hub': 'Mantella-Living-World-Hub',
    'ostim': 'Mantella-Adult-Expansion-OStim',
    'arousal': 'Mantella-OSL-Aroused-Bridge',
    'relationships': 'Mantella-Relationship-Bridge',
    'followers': 'Mantella-Living-World-Followers',
}
# Dark surface that sits well on Nexus; neutral ink, the pages' green accent for the header rule.
BG, INK, MUTED, RULE, ACCENT = '#1d1e21', '#e8e6e3', '#a9a6a1', '#34363b', '#93c47d'
WIDTH = 900

TABLES = {
    'hub': {
        'modules': ('Modules', ['Module', 'Adds', 'Needs'], [
            ['OStim Expansion', 'Scene flows, scene talk, bystanders, favourite positions', 'OStim Standalone'],
            ['Arousal', 'Arousal, appetite, satisfied and overwhelmed', 'OSL Aroused'],
            ['Relationships', 'Marriage, shared history', 'MARAS or Lover\'s Ledger'],
            ['Followers', 'Join, leave, wait, follow, passive, wear this', 'Nether\'s Follower Framework'],
        ]),
        'features': ('What the hub does', ['Feature', 'Effect'], [
            ['Quiet outfits', 'No equip / unequip spam in conversations during scenes and after loading screens'],
            ['Temperament', 'Reserved, bold or forward per NPC; set with a hotkey'],
            ['Module status', 'MCM page with a check for each installed module and supported mod'],
            ['Troubleshooting', 'Writes a report for bug reports; optional debug log'],
            ['Settings', 'One MCM page for the hub and its shared settings'],
        ]),
    },
    'ostim': {
        'talk': ('What Mantella hears during a scene', ['Moment', 'Example line'], [
            ['Scene starts or moves on', 'Vega and the player have started: a blowjob.'],
            ['Excitement 30 / 50 / 75', 'Vega is really into it now; she reacts out loud.'],
            ['Pace change', 'The pace picks up; it is now steady.'],
            ['Climax', 'Vega just climaxed.  (+ a remark from someone watching)'],
            ['Scene ends', 'One summary: where, how long, what you did, climaxes.'],
        ]),
        'features': ('Features', ['Feature', 'What it does'], [
            ['Scene flows', 'Builds each scene live from your own animation packs'],
            ['Finish scenes', 'Played when the man is close; borrowed from another pack if needed'],
            ['Not satisfied?', 'A new round starts in the same pack after her climax'],
            ['Your control', 'Pick a scene yourself and the flow steps back'],
            ['Favourite positions', 'Rated from her personality, learned from your scenes'],
            ['Position requests', 'Ask her in conversation; she switches if it fits'],
            ['Group scenes', 'Scene talk names everyone; flows stay two-person'],
        ]),
    },
    'arousal': {
        'temperament': ('Temperament', ['Temperament', 'Aroused', 'At her peak'], [
            ['Reserved', 'Keeps it to herself', 'Hints at most'],
            ['Bold', 'Lets it show, drops hints', 'Asks you directly, accepts no'],
            ['Forward', 'Says it openly', 'Begs (never starts a scene without you)'],
        ]),
        'appetite': ('Appetite', ['State', 'What happens'], [
            ['Rated', 'Mantella rates her appetite once, from her bio'],
            ['Counting', 'Climaxes this session are counted against it'],
            ['Satisfied', 'Arousal drops; she is content'],
            ['Overwhelmed', 'Far past it; she asks to rest'],
        ]),
    },
    'relationships': {
        'parts': ('What Mantella learns', ['Mod', 'Mantella learns'], [
            ['MARAS', 'Married, engaged, candidate or divorced; your spouses when asked'],
            ['Lover\'s Ledger', 'Your history together, her favourite acts, her other lovers'],
            ['After a scene', 'She opens a conversation and speaks first'],
        ]),
    },
    'followers': {
        'actions': ('Actions', ['Action', 'What happens'], [
            ['JoinParty / LeaveParty', 'The NPC joins or leaves your NFF party'],
            ['WaitHere / FollowMe', 'Only that follower waits or follows again'],
            ['EveryoneWait / EveryoneFollow', 'The whole party'],
            ['StayPassive / FightFreely', 'Stays out of fights, or attacks enemies and helps allies'],
            ['WearThis', 'Opens trade; what you hand over becomes their NFF outfit for where you are'],
        ]),
    },
}

FLOW = r'''digraph G {
  bgcolor="%(bg)s"; rankdir=LR; pad=0.3; nodesep=0.35; ranksep=0.45;
  node [shape=box, style="rounded,filled", fillcolor="#2a2c30", color="#3c3f45", fontcolor="%(ink)s",
        fontname="Segoe UI", fontsize=13, margin="0.18,0.1"];
  edge [color="%(muted)s", fontcolor="%(muted)s", fontname="Segoe UI", fontsize=11, arrowsize=0.7];
  open  [label="Soft opener\none pack"];
  roll  [label="Next set rolled\nnatural moves, favourites"];
  hold  [label="Holds\n4 sets per round"];
  fin   [label="Finish scene", color="%(accent)s"];
  climax[label="Her climax"];
  again [label="New round\nsame pack"];
  you   [label="You pick a scene\nflow steps back"];
  open -> roll -> hold;
  roll -> roll [label="up to 4"];
  hold -> fin [label="he is close"];
  roll -> climax; climax -> again [label="not satisfied"]; again -> roll;
  roll -> you [style=dashed];
}'''


def table_html(title, head, rows):
    th = ''.join(f'<th>{html.escape(h)}</th>' for h in head)
    tr = ''.join('<tr>' + ''.join(f'<td>{html.escape(c)}</td>' for c in r) + '</tr>' for r in rows)
    return f'''<!doctype html><meta charset="utf-8"><style>
html,body{{margin:0;background:{BG};}}
body{{padding:22px 26px;font:15px/1.45 "Segoe UI",system-ui,sans-serif;color:{INK};width:{WIDTH - 52}px}}
h1{{font-size:17px;font-weight:600;margin:0 0 12px;color:{INK}}}
table{{border-collapse:collapse;width:100%}}
th{{text-align:left;font-weight:600;color:{MUTED};font-size:13px;letter-spacing:.02em;padding:0 14px 8px 0;border-bottom:2px solid {ACCENT}}}
td{{padding:10px 14px 10px 0;border-bottom:1px solid {RULE};vertical-align:top}}
td:first-child{{white-space:nowrap;font-weight:600}}
tr:last-child td{{border-bottom:none}}
</style><h1>{html.escape(title)}</h1><table><tr>{th}</tr>{tr}</table>'''


def shoot(page, out, height):
    with tempfile.NamedTemporaryFile('w', suffix='.html', delete=False, encoding='utf-8') as f:
        f.write(page)
    subprocess.run([CHROME, '--headless=new', '--disable-gpu', '--hide-scrollbars', '--force-device-scale-factor=1.5',
                    f'--window-size={WIDTH},{height}', f'--screenshot={out}', f.name],
                   check=True, capture_output=True)
    os.remove(f.name)


def main():
    # The pages use native [table]s (nexus_pages.py); these images are for the galleries.
    for key, tables in TABLES.items():
        for name, (title, head, rows) in tables.items():
            out = os.path.join(CODING, PROJECTS[key], 'nexus', 'images', name + '.png')
            os.makedirs(os.path.dirname(out), exist_ok=True)
            shoot(table_html(title, head, rows), out, 900)
            # Cut the unused height, then put back even padding.
            subprocess.run(['magick', out, '-trim', '+repage', '-bordercolor', BG, '-border', '36', out], check=True)
            print(out)
    flow_out = os.path.join(CODING, PROJECTS['ostim'], 'nexus', 'images', 'flow.png')
    dot = FLOW % {'bg': BG, 'ink': INK, 'muted': MUTED, 'accent': ACCENT}
    subprocess.run(['dot', '-Tpng', '-Gdpi=144', '-o', flow_out], input=dot.encode(), check=True)
    print(flow_out)


if __name__ == '__main__':
    main()
