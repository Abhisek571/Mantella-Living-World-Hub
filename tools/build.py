"""Builds every Mantella Living World mod in one go: compiles all Papyrus scripts, builds every plugin from its Spriggit
YAML, assembles each mod (plugin, scripts, sources, data files, license, readme), checks the contents, and packs one
.7z per mod into dist/ for Nexus.

usage: py -3 build.py [--version 1.0.0] [--only hub,ostim,...] [--no-pack]
"""
import argparse, os, re, shutil, subprocess, sys

CODING = r'D:\coding'
HUB_DIR = os.path.join(CODING, 'Mantella-Living-World-Hub')
NGVO = r'D:\Modlists\NGVO'
MODS = os.path.join(NGVO, 'mods')
GAME = r'D:\Games\Steam\steamapps\common\Skyrim Special Edition'
COMPILER = os.path.join(GAME, 'Papyrus Compiler', 'PapyrusCompiler.exe')
VANILLA = os.path.join(GAME, 'Data', 'Source', 'Scripts')
FLAGS = os.path.join(VANILLA, 'TESV_Papyrus_Flags.flg')
SEVEN_ZIP = r'C:\Program Files\7-Zip\7z.exe'
OUT = os.path.join(HUB_DIR, 'build', 'release')
DIST = os.path.join(HUB_DIR, 'dist')

# Sources of the mods these scripts call (compile only; nothing of theirs is shipped).
DEPS = {
    'skse': 'Skyrim Script Extender (SKSE64)/Scripts/Source',
    'papyrusutil': 'PapyrusUtil SE - Modders Scripting Utility Functions/Scripts/Source',
    'skymessage': '[NoDelete] Papyrus MessageBox - SKSE NG/Scripts/Source',
    'ostim': '[NoDelete] OStim Standalone/Scripts/Source',
    'osl': '[NoDelete] OSL Aroused/Scripts/Source',
    'maras': '[NoDelete] M.A.R.A.S - Marry Anyone Rule All Skyrim/Scripts/Source',
    'mantella': '[NoDelete] Mantella - Bring NPCs to Life with AI/Scripts/Source',
    'jcontainers': 'JContainers SE/scripts/source',
    'po3': "powerofthree's Papyrus Extender/Source/scripts",
    'skyui': 'MCM Recorder/Scripts/Source',
    'relationsfinder': 'Relations Finder/scripts/source',
}

PROJECTS = {
    'hub': dict(dir='Mantella-Living-World-Hub', name='Mantella Living World - Integration Hub',
                deps=['skse', 'papyrusutil', 'skymessage'], data=['MCM', 'SKSE'], prebuilt=[], extensions=['living_world']),
    'ostim': dict(dir='Mantella-Living-World-OStim-Expansion', name='Mantella Living World - OStim Expansion',
                  imports=[os.path.join(HUB_DIR, 'Source', 'Scripts'), os.path.join(HUB_DIR, 'build', 'stubs')],
                  deps=['skse', 'papyrusutil', 'skymessage', 'ostim', 'osl'], data=['SKSE'], prebuilt=[],
                  tools=['tools/flowgen.py', 'tools/Build Flows.cmd']),
    'arousal': dict(dir='Mantella-Living-World-Arousal', name='Mantella Living World - Arousal',
                    deps=['skse', 'papyrusutil', 'osl', 'maras', 'mantella', 'jcontainers', 'po3', 'skyui'],
                    data=['SKSE'], prebuilt=[]),
    'relationships': dict(dir='Mantella-Living-World-Relationships', name='Mantella Living World - Relationships',
                          deps=['skse', 'papyrusutil', 'skymessage', 'maras', 'mantella', 'jcontainers', 'po3', 'skyui',
                                'relationsfinder'],
                          data=['SKSE'], prebuilt=[]),  # Lover's Ledger ships no sources: build/stubs has the five functions MRB_Ledger calls
    'world': dict(dir='Mantella-Living-World-World', name='Mantella Living World - World',
                  deps=['skse', 'papyrusutil', 'mantella'], data=['SKSE'], prebuilt=[],  # Hub and Mantella conversation come from build/stubs
                  dlls=['plugin/build/release/MLWW_Listener.dll']),  # built by plugin/build.ps1
    'knowledge': dict(dir='Mantella-Living-World-Knowledge', name='Mantella Living World - Knowledge',
                      deps=['skse', 'papyrusutil', 'mantella'], data=['SKSE'], prebuilt=[],
                      extensions=['lw_knowledge'], extension_data={'lw_knowledge': 'data'}),
    'missives': dict(dir='Mantella-Living-World-Missives', name='Mantella Living World - Missives',
                     deps=['skse', 'papyrusutil'], data=['SKSE'], prebuilt=[]),  # no Missives master: quests found by editor id
    'followers': dict(dir='Mantella-Living-World-Followers', name='Mantella Living World - Followers',
                      imports=[os.path.join(HUB_DIR, 'Source', 'Scripts'), os.path.join(HUB_DIR, 'build', 'stubs')],
                      deps=['skse', 'papyrusutil', 'skymessage'], data=['SKSE'], prebuilt=[]),  # NFF and Mantella come from build/stubs
}
# Never in a release: test harness and logs; extra names and words come from a local, untracked list
# (tools/release-check.txt: "name:<regex>" or "text:<regex>" per line).
_CHECK = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'release-check.txt')
_LINES = [l.strip() for l in open(_CHECK, encoding='utf-8')] if os.path.isfile(_CHECK) else []
FORBIDDEN_NAME = re.compile('|'.join([r'(^|[\\/])(test|tests)([\\/]|$)', 'MAE_Test', r'\.log$'] + [l[5:] for l in _LINES if l.startswith('name:')]), re.I)
FORBIDDEN_TEXT = re.compile('|'.join(l[5:] for l in _LINES if l.startswith('text:')).encode() or rb'(?!)', re.I)


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        raise SystemExit(f'FAILED: {cmd}\n{r.stdout[-3000:]}\n{r.stderr[-3000:]}')
    return r.stdout


def compile_scripts(key, p, out_scripts):
    src = os.path.join(CODING, p['dir'], 'Source', 'Scripts')
    imports = [src, os.path.join(CODING, p['dir'], 'build', 'stubs')] + p.get('imports', []) \
        + [os.path.join(MODS, DEPS[d]) for d in p['deps']] + [VANILLA]
    imports = [d for d in imports if os.path.isdir(d) or 'build' not in d]  # a project may have no stubs
    for d in imports:
        if not os.path.isdir(d):
            raise SystemExit(f'{key}: import folder missing: {d}')
    names = sorted(f[:-4] for f in os.listdir(src) if f.endswith('.psc') and f[:-4] not in p['prebuilt'])
    for n in names:
        run([COMPILER, os.path.join(src, n + '.psc'), f'-f={FLAGS}', '-i=' + ';'.join(imports), f'-o={out_scripts}', '-op'])
    for n in p['prebuilt']:
        shutil.copy2(os.path.join(CODING, p['dir'], 'Scripts', n + '.pex'), out_scripts)
    return names + p['prebuilt']


def build_plugin(p, out_dir):
    plugin = p['name'] + '.esp'
    run(['bash', os.path.join(NGVO, 'tools', 'spriggit-cli.sh'), 'deserialize',
         '--InputPath', os.path.join(CODING, p['dir'], 'esp').replace('\\', '/'),
         '--OutputPath', os.path.join(out_dir, plugin).replace('\\', '/')], cwd=NGVO)
    if not os.path.isfile(os.path.join(out_dir, plugin)):
        raise SystemExit(f'plugin not built: {plugin}')


def check(stage):
    bad = []
    for d, _, files in os.walk(stage):
        for f in files:
            rel = os.path.relpath(os.path.join(d, f), stage)
            if FORBIDDEN_NAME.search(rel):
                bad.append(f'name: {rel}')
            elif not f.endswith(('.esp', '.pex', '.7z', '.png', '.jpg')):
                if FORBIDDEN_TEXT.search(open(os.path.join(d, f), 'rb').read()):
                    bad.append(f'text: {rel}')
    if bad:
        raise SystemExit('release check failed:\n  ' + '\n  '.join(bad))


def build(key, version, pack):
    p = PROJECTS[key]
    root = os.path.join(CODING, p['dir'])
    stage = os.path.join(OUT, p['name'])
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(os.path.join(stage, 'Scripts', 'Source'))
    names = compile_scripts(key, p, os.path.join(stage, 'Scripts'))
    for n in names:
        src = os.path.join(root, 'Source', 'Scripts', n + '.psc')
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(stage, 'Scripts', 'Source'))
    build_plugin(p, stage)
    for d in p['data']:
        shutil.copytree(os.path.join(root, d), os.path.join(stage, d), dirs_exist_ok=True)
    for dll in p.get('dlls', []):
        if not os.path.isfile(os.path.join(root, dll)):
            raise SystemExit(f'{key}: SKSE plugin not built: {dll}')
        os.makedirs(os.path.join(stage, 'SKSE', 'Plugins'), exist_ok=True)
        shutil.copy2(os.path.join(root, dll), os.path.join(stage, 'SKSE', 'Plugins'))
    # Python extensions for Mantella - Direct AI Connect: server/<name>/ -> MantellaSoftware/extensions/<name>/ (tests stay out)
    for name in p.get('extensions', []):
        shutil.copytree(os.path.join(root, 'server', name),
                        os.path.join(stage, 'SKSE', 'Plugins', 'MantellaSoftware', 'extensions', name),
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'), dirs_exist_ok=True)
    # an extension's data folder (repo-relative) shipped inside it: extensions/<name>/data/
    for name, folder in p.get('extension_data', {}).items():
        shutil.copytree(os.path.join(root, folder), os.path.join(stage, 'SKSE', 'Plugins', 'MantellaSoftware', 'extensions', name, 'data'),
                        ignore=shutil.ignore_patterns('ratings', 'prompt_rules'), dirs_exist_ok=True)
    for t in p.get('tools', []):
        dst = os.path.join(stage, 'tools', p['name'], os.path.basename(t))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(root, t), dst)
    docs = os.path.join(stage, 'Docs', p['name'])
    os.makedirs(docs)
    shutil.copy2(os.path.join(root, 'LICENSE'), os.path.join(docs, 'LICENSE.txt'))
    if os.path.isfile(os.path.join(root, 'nexus', 'readme.txt')):
        shutil.copy2(os.path.join(root, 'nexus', 'readme.txt'), os.path.join(docs, 'Readme.txt'))
    check(stage)
    archive = None
    if pack:
        os.makedirs(DIST, exist_ok=True)
        archive = os.path.join(DIST, f"{p['name']} {version}.7z")
        if os.path.exists(archive):
            os.remove(archive)
        run([SEVEN_ZIP, 'a', '-t7z', '-mx=9', archive, '.\\*'], cwd=stage)
    files = sum(len(f) for _, _, f in os.walk(stage))
    print(f"{p['name']}: {len(names)} scripts, {files} files" + (f' -> {archive}' if archive else ''))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--version', default='1.0.0')
    ap.add_argument('--only', default=','.join(PROJECTS))
    ap.add_argument('--no-pack', action='store_true')
    a = ap.parse_args()
    for key in a.only.split(','):
        build(key.strip(), a.version, not a.no_pack)


if __name__ == '__main__':
    main()
