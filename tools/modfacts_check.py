"""Dry check of mod fact files: every referenced global, quest or faction exists in the installed plugin (single-file
reads of the winning plugin), and what each NPC's facts read at sample values (each line's own range).

usage: py -3 modfacts_check.py --mo2 <Mod Organizer 2 instance> [--profile Default] --folder <modfacts folder> [...]
A folder holds user/, shipped/ and generated/ (or pass one of those directly). NPC references into the base game
masters are not looked up (reading Skyrim.esm whole is slow); a plugin's own NPCs are."""
import argparse, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'server'))
from living_world import mod_facts as M, mod_facts_gen as G  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mo2', required=True)
    ap.add_argument('--profile', default='Default')
    ap.add_argument('--folder', action='append', required=True)
    a = ap.parse_args()
    plugins, mods = G.mo2_plugins(a.mo2, a.profile)
    enabled = {p.lower() for p in plugins} | G.BASE_GAME
    files = {}
    for folder in a.folder:
        found = M.load_folder(folder)
        if not found and os.path.basename(folder.rstrip('\\/')) in M.FOLDERS:  # one of the three folders itself
            found = M.load_folder(os.path.dirname(folder.rstrip('\\/')))
        for k, v in found.items():
            files.setdefault(k, v)
    parsed_cache, problems = {}, 0

    def parsed(plugin):
        if plugin.lower() not in parsed_cache:
            _, path = G.winner(a.mo2, mods, plugin)
            parsed_cache[plugin.lower()] = G.read_plugin(path) if path else None
        return parsed_cache[plugin.lower()]

    for key, data in sorted(files.items()):
        state = 'enabled' if key in enabled else 'NOT installed: ignored in game'
        print(f"== {data['plugin']} ({data['folder']}/{data['file']}, {data['mod']}): {state}")
        if key not in enabled:
            continue
        for npc in data['npcs']:
            ref = M.form_ref(npc['npc'])
            label = npc['name'] or npc['npc']
            if ref and ref[0].lower() not in G.BASE_GAME:
                p = parsed(ref[0])
                own = p and any((fid & 0xFFFFFF) == ref[1] for fid in p['npc'])
                if not own:
                    problems += 1
                    print(f"   PROBLEM npc {npc['npc']} not found in {ref[0]}")
            print(f"   NPC {label} ({npc['npc']})")
            for fact in npc['facts']:
                form = M.form_ref(fact['form'])
                if form:
                    p = parsed(form[0])
                    table = {'global': 'glob', 'stage': 'qust', 'quest': 'qust', 'faction': 'fact'}[fact['kind']]
                    hit = p and next((r['edid'] for fid, r in p[table].items() if (fid & 0xFFFFFF) == form[1]), None)
                    if not hit:
                        problems += 1
                        print(f"   PROBLEM {fact['kind']} {fact['form']} not found in {form[0]}")
                        continue
                    print(f"     {fact['kind']} {hit} ({fact['form']})")
                for line in fact['lines']:
                    print(f"       at {line['min']}: {M.line_for(fact, line['min']).replace('{player}', 'Player')}")
    print(f"\n{len(files)} file(s), {problems} problem(s)")
    sys.exit(1 if problems else 0)


if __name__ == '__main__':
    main()
