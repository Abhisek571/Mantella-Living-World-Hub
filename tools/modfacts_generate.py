"""Drafts mod fact files from the installed plugins (the mod's own text only) into a generated/ folder.

usage: py -3 modfacts_generate.py --mo2 <Mod Organizer 2 instance> [--profile Default] [--out <folder>]
                                 [--only "shadowman_*.esp,SeranaDialogAddon.esp"] [--min-infos 3]
--out defaults to the instance's overwrite\\SKSE\\Plugins\\StorageUtilData\\MantellaLivingWorld\\modfacts\\generated.
Only the generated folder is written; the user/ and shipped/ folders are never touched (their files win in game)."""
import argparse, fnmatch, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'server'))
from living_world import mod_facts_gen as G  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mo2', required=True)
    ap.add_argument('--profile', default='Default')
    ap.add_argument('--out', default='')
    ap.add_argument('--only', default='')
    ap.add_argument('--min-infos', type=int, default=G.MIN_INFOS)
    ap.add_argument('--game-data', default='', help='the game Data folder, for plugins no mod provides')
    a = ap.parse_args()
    out = a.out or os.path.join(a.mo2, 'overwrite', 'SKSE', 'Plugins', 'StorageUtilData', 'MantellaLivingWorld', 'modfacts', 'generated')
    patterns = [p.strip().lower() for p in a.only.split(',') if p.strip()]
    only = (lambda name: any(fnmatch.fnmatch(name.lower(), p) for p in patterns)) if patterns else None
    drafts = G.generate(a.mo2, a.profile, only, a.min_infos, a.game_data or None)
    written = G.write(drafts, out)
    npcs = sum(len(d['npcs']) for d in drafts.values() if isinstance(d, dict))
    for plugin, made in drafts.items():
        if isinstance(made, dict):
            facts = sum(len(n['facts']) for n in made['npcs'])
            print(f"{plugin}: {len(made['npcs'])} NPC(s), {facts} fact(s)")
        else:
            print(f"{plugin}: nothing ({made})")
    print(f"\n{len(written)} file(s) written to {out}; {npcs} NPC(s) get facts")


if __name__ == '__main__':
    main()
