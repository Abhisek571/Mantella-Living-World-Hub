"""Developer tool (not shipped): the size of the action list Mantella sends to the model, per tool and in total, for a
few typical NPCs. Builds each tool the way Mantella's FunctionManager.generate_context_aware_tools does (name,
description, parameters with "required"; enum_source and resolve_to_id dropped), filters and shortens them with the
Hub's own action_filter (Hub settings on: action_filter, short_actions), and counts size units as the Hub does:
(characters + 3) // 4 of the tool's JSON. Mantella's " Available: <names>" lists are left out (Direct AI Connect moves
them out of the tools).

Stock Mantella actions are read from the installed mod (read only) or the Mantella checkout; the Living World ones
from the repositories next to this one. Disabled stock actions come from Mantella's config.ini when it is found.

usage: py -3 tools/action_sizes.py [--detail] [--json out.json]
"""
import argparse
import configparser
import copy
import glob
import json
import os
import sys

HUB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODING = os.path.dirname(HUB)
sys.path.insert(0, os.path.join(HUB, 'server'))
from living_world import action_filter  # noqa: E402

LW_REPOS = ['World', 'OStim-Expansion', 'Arousal', 'Followers', 'Survival', 'Missives', 'Relationships', 'Knowledge',
            'Quests', 'Hub']
STOCK_DIRS = [os.path.join(os.environ.get('MLW_MO2', ''), 'mods', r'[NoDelete] Mantella - Bring NPCs to Life with AI\SKSE\Plugins\MantellaSoftware\data\actions'),
              os.path.join(CODING, 'Mantella', 'data', 'actions')]
CONFIG = os.path.join(os.path.expanduser('~'), 'Documents', 'My Games', 'Mantella', 'config.ini')
SETTINGS_GATES = {'Inventory': 'follower', 'Attack': 'follower'}  # the Hub's default action_gates
SERVER_ONLY = {'Console'}  # the Hub takes it out of every request but its own turn

CASES = {
    'adult stranger': dict(scene=0, minor=0, intimate=1, affection=1, guard=0, merchant=0),
    'adult merchant': dict(scene=0, minor=0, intimate=1, affection=1, guard=0, merchant=1),
    'guard': dict(scene=0, minor=0, intimate=1, affection=1, guard=1, merchant=0),
    'follower (NFF)': dict(scene=0, minor=0, close=1, follower=1, nff=1, intimate=1, affection=1, guard=0, merchant=0, surv_warm=1),
    'lover (married)': dict(scene=0, minor=0, close=1, intimate=1, affection=1, guard=0, merchant=0, maras_on=1, maras_tracked=1),
    'lover in a scene': dict(minor=0, close=1, intimate=1, affection=1, guard=0, merchant=0, maras_on=1, maras_tracked=1,
                             scene=1, rated=0),
}


def load_dir(path):
    out = []
    for f in sorted(glob.glob(os.path.join(glob.escape(path), '*.json'))):
        try:
            data = json.load(open(f, encoding='utf-8'))
        except (OSError, ValueError):
            continue
        out.extend(a for a in (data if isinstance(data, list) else [data]) if isinstance(a, dict) and a.get('name'))
    return out


def disabled():
    if not os.path.isfile(CONFIG):
        return set()
    text = open(CONFIG, encoding='utf-8', errors='replace').read()
    for line in text.splitlines():
        if line.strip().startswith('disabled_actions') and '=' in line:
            return {n.strip().lower() for n in line.split('=', 1)[1].split(',') if n.strip()}
    return set()


def actions():
    stock_dir = next((d for d in STOCK_DIRS if os.path.isdir(d)), None)
    stock = load_dir(stock_dir) if stock_dir else []
    lw = []
    for repo in LW_REPOS:
        lw += load_dir(os.path.join(CODING, 'Mantella-Living-World-' + repo, 'SKSE', 'Plugins', 'MantellaSoftware', 'data', 'actions'))
    off = disabled()
    stock = [a for a in stock if a['name'].lower() not in off]
    return stock, lw


def tool(action):
    t = {'type': 'function', 'function': {'name': action['name'], 'description': action['description']}}
    params = {'type': 'object', 'properties': {}}
    if 'parameters' in action:
        params['properties'] = copy.deepcopy(action['parameters'])
        if 'required' in action:
            params['required'] = action['required']
        for p in params['properties'].values():
            if isinstance(p, dict):
                p.pop('enum_source', None)
                p.pop('resolve_to_id', None)
    t['function']['parameters'] = params
    return t


def units(t):
    return (len(json.dumps(t)) + 3) // 4


def offered(all_actions, speaker, one_on_one=True):
    key = 'one-on-one' if one_on_one else 'multi-npc'
    usable = [a for a in all_actions if a.get(key, a.get(key.replace('-', '_'), False)) and a['name'] not in SERVER_ONLY]
    gates = action_filter.with_settings({a['name']: a['lw_gate'] for a in all_actions if a.get('lw_gate')}, SETTINGS_GATES)
    tools = action_filter.filter_actions([tool(a) for a in usable], [dict(speaker, name='NPC')], gates)
    return action_filter.shorten(tools, gates)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--detail', action='store_true')
    ap.add_argument('--json')
    args = ap.parse_args()
    stock, lw = actions()
    stock_names = {a['name'] for a in stock}
    report = {}
    print(f"{'case':20} {'tools':>5} {'units':>6} {'stock':>6} {'LW':>6}")
    for case, speaker in CASES.items():
        tools = offered(stock + lw, speaker)
        rows = [(t['function']['name'], units(t)) for t in tools]
        total = sum(u for _, u in rows)
        s = sum(u for n, u in rows if n in stock_names)
        report[case] = {'tools': len(rows), 'units': total, 'rows': rows}
        print(f"{case:20} {len(rows):>5} {total:>6} {s:>6} {total - s:>6}")
        if args.detail:
            for n, u in sorted(rows, key=lambda r: -r[1]):
                print(f"    {n:24} {u:>5}{'  (stock)' if n in stock_names else ''}")
    if args.json:
        json.dump(report, open(args.json, 'w', encoding='utf-8'), indent=1)


if __name__ == '__main__':
    main()
