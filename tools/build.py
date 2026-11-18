"""Builds every Mantella Living World mod in one go: compiles all Papyrus scripts, builds every plugin from its Spriggit
YAML, assembles each mod (plugin, scripts, sources, data files, license, readme), checks the contents, and packs one
.7z per mod into dist/ for Nexus.

usage: py -3 build.py [--version 1.0.0] [--only hub,ostim,...] [--no-pack]
"""
import argparse, json, os, re, shutil, subprocess, sys

CODING = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HUB_DIR = os.path.join(CODING, 'Mantella-Living-World-Hub')
# Local folders: the environment (MLW_MO2, MLW_GAME) or the untracked tools/local-paths.json of the Integration Hub
# repository ({"mo2": "<Mod Organizer 2 instance>", "game": "<Skyrim Special Edition folder>"}).
def _local(key, env):
    if os.environ.get(env):
        return os.environ[env]
    f = os.path.join(HUB_DIR, 'tools', 'local-paths.json')
    value = json.load(open(f, encoding='utf-8')).get(key, '') if os.path.isfile(f) else ''
    if not value:
        raise SystemExit(f'Set {env}, or "{key}" in {f}')
    return value


MO2 = _local('mo2', 'MLW_MO2')
MODS = os.path.join(MO2, 'mods')
GAME = _local('game', 'MLW_GAME')
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
    'relationsfinder': 'Relations Finder/scripts/source',
}

PROJECTS = {
    'hub': dict(dir='Mantella-Living-World-Hub', name='Mantella Living World - Integration Hub',
                deps=['skse', 'papyrusutil', 'skymessage', 'po3'], data=['MCM', 'SKSE'], prebuilt=[], extensions=['living_world']),
    'ostim': dict(dir='Mantella-Living-World-OStim-Expansion', name='Mantella Living World - OStim Expansion',
                  imports=[os.path.join(HUB_DIR, 'Source', 'Scripts'), os.path.join(HUB_DIR, 'build', 'stubs')],
                  deps=['skse', 'papyrusutil', 'skymessage', 'po3', 'ostim', 'osl'], data=['SKSE'], prebuilt=[],
                  tools=['tools/flowgen.py', 'tools/Build Flows.cmd']),
    'arousal': dict(dir='Mantella-Living-World-Arousal', name='Mantella Living World - Arousal',
                    deps=['skse', 'papyrusutil', 'osl', 'maras', 'mantella', 'jcontainers', 'po3'],
                    data=['SKSE'], prebuilt=[]),
    'relationships': dict(dir='Mantella-Living-World-Relationships', name='Mantella Living World - Relationships',
                          deps=['skse', 'papyrusutil', 'skymessage', 'maras', 'mantella', 'jcontainers', 'po3',
                                'relationsfinder'],  # no SkyUI: no script here uses it (like the Hub, only what is called)
                          data=['SKSE'], prebuilt=[],  # Lover's Ledger ships no sources: build/stubs has the five functions MRB_Ledger calls
                          after=['tools/compile_maras2x.py']),  # the M.A.R.A.S 2.x calls need their own MARAS.psc
    'world': dict(dir='Mantella-Living-World-World', name='Mantella Living World - World',
                  deps=['skse', 'papyrusutil', 'skymessage', 'po3', 'mantella'], data=['SKSE'], prebuilt=[],  # Hub and Mantella conversation come from build/stubs
                  dlls=['plugin/build/release/MLWW_Listener.dll']),  # built by plugin/build.ps1
    'knowledge': dict(dir='Mantella-Living-World-Knowledge', name='Mantella Living World - Knowledge',
                      deps=['skse', 'papyrusutil', 'mantella'], data=['SKSE'], prebuilt=[],
                      extensions=['lw_knowledge'], extension_data={'lw_knowledge': 'data'}),
    'missives': dict(dir='Mantella-Living-World-Missives', name='Mantella Living World - Missives',
                     deps=['skse', 'papyrusutil'], data=['SKSE'], prebuilt=[]),  # no Missives master: quests found by editor id
    'followers': dict(dir='Mantella-Living-World-Followers', name='Mantella Living World - Followers',
                      imports=[os.path.join(HUB_DIR, 'Source', 'Scripts'), os.path.join(HUB_DIR, 'build', 'stubs')],
                      deps=['skse', 'papyrusutil', 'skymessage', 'po3'], data=['SKSE'], prebuilt=[]),  # NFF and Mantella come from build/stubs
    'survival': dict(dir='Mantella-Living-World-Survival', name='Mantella Living World - Survival',
                     deps=['skse', 'papyrusutil'], data=['SKSE'], prebuilt=[],  # Hub, Mantella and SMI come from build/stubs
                     dlls=['plugin/build/release/MLWS_Listener.dll'],  # built by plugin/build.ps1
                     ),
}
# Module name on the Main Status map and Nexus mod id, written to the version file the Hub's update check reads.
MODULE_INFO = {'hub': ('Integration Hub', 196849), 'ostim': ('OStim Expansion', 196850), 'arousal': ('Arousal', 196851),
               'relationships': ('Relationships', 196852), 'world': ('World', 197309), 'knowledge': ('Knowledge', 197315),
               'missives': ('Missives', 197320), 'followers': ('Followers', 196878), 'survival': ('Survival', 198520)}
# Never in a release: test harness and logs; extra names and words come from a local, untracked list
# (tools/release-check.txt: "name:<regex>" or "text:<regex>" per line).
_CHECK = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'release-check.txt')
_LINES = [l.strip() for l in open(_CHECK, encoding='utf-8')] if os.path.isfile(_CHECK) else []
FORBIDDEN_NAME = re.compile('|'.join([r'(^|[\\/])(test|tests)([\\/]|$)', 'MAE_Test', r'_Test\.(psc|pex)$', r'\.log$', r'\.tmp$', r'update_check\.json$',
                                     r'living_world_bios', r'character_overrides', r'living_world_characters\.json$'] + [l[5:] for l in _LINES if l.startswith('name:')]), re.I)
FORBIDDEN_TEXT = re.compile('|'.join(l[5:] for l in _LINES if l.startswith('text:')).encode() or rb'(?!)', re.I)


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        raise SystemExit(f'FAILED: {cmd}\n{r.stdout[-3000:]}\n{r.stderr[-3000:]}')
    return r.stdout


PEX_MAGIC = b'\xfa\x57\xc0\xde'  # Skyrim .pex, big-endian


def neutral_pex_header(path):
    """The compiler writes the Windows user name and computer name into every .pex header (after the source file
    name); a release ships 'builder' and 'BUILD' instead. Nothing after the header moves: it is read in order."""
    data = open(path, 'rb').read()
    if data[:4] != PEX_MAGIC:
        raise SystemExit(f'not a Skyrim .pex: {path}')
    pos = 4 + 1 + 1 + 2 + 8  # magic, major, minor, game id, compile time
    out = bytearray(data[:pos])
    n = int.from_bytes(data[pos:pos + 2], 'big')
    out += data[pos:pos + 2 + n]  # source file name, kept
    pos += 2 + n
    for value in (b'builder', b'BUILD'):  # user name, computer name
        pos += 2 + int.from_bytes(data[pos:pos + 2], 'big')
        out += len(value).to_bytes(2, 'big') + value
    out += data[pos:]
    with open(path, 'wb') as f:
        f.write(out)


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


def git_bash():
    """Git Bash, found explicitly: a bare 'bash' on Windows is often WSL's bash.exe in System32, which cannot run the
    Spriggit wrapper. The usual install places first, then Git's own folder next to git.exe, then 'bash' on PATH."""
    places = [os.environ.get('MLW_BASH', '')]
    for root in (os.environ.get('ProgramFiles', r'C:\Program Files'), os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'),
                 os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs')):
        places += [os.path.join(root, 'Git', 'bin', 'bash.exe'), os.path.join(root, 'Git', 'usr', 'bin', 'bash.exe')]
    git = shutil.which('git')
    if git:  # ...\Git\cmd\git.exe or ...\Git (bin)\git.exe
        home = os.path.dirname(os.path.dirname(git))
        places += [os.path.join(home, 'bin', 'bash.exe'), os.path.join(home, 'usr', 'bin', 'bash.exe')]
    for place in places:
        if place and os.path.isfile(place):
            return place
    return shutil.which('bash') or 'bash'


def build_plugin(p, out_dir):
    plugin = p['name'] + '.esp'
    run([git_bash(), os.path.join(MO2, 'tools', 'spriggit-cli.sh'), 'deserialize',
         '--InputPath', os.path.join(CODING, p['dir'], 'esp').replace('\\', '/'),
         '--OutputPath', os.path.join(out_dir, plugin).replace('\\', '/')], cwd=MO2)
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
    for script in p.get('after', []):  # a project's own extra compile step, into this stage
        run([sys.executable, os.path.join(root, script), os.path.join(stage, 'Scripts')])
    for f in os.listdir(os.path.join(stage, 'Scripts')):
        if f.lower().endswith('.pex'):
            neutral_pex_header(os.path.join(stage, 'Scripts', f))
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
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.tmp", "update_check.json", "settings.json", "profile_overrides.json", "living_world_bios*.json",
                                                              "*.onnx", "embed", "*.download"), dirs_exist_ok=True)
    # an extension's data folder (repo-relative) shipped inside it: extensions/<name>/data/
    for name, folder in p.get('extension_data', {}).items():
        shutil.copytree(os.path.join(root, folder), os.path.join(stage, 'SKSE', 'Plugins', 'MantellaSoftware', 'extensions', name, 'data'),
                        ignore=shutil.ignore_patterns('ratings', 'prompt_rules', '*.onnx', 'embed', '*.download'), dirs_exist_ok=True)
    for t in p.get('tools', []):
        dst = os.path.join(stage, 'tools', p['name'], os.path.basename(t))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(root, t), dst)
    module, nexus_id = MODULE_INFO[key]
    versions = os.path.join(stage, 'SKSE', 'Plugins', 'MantellaSoftware', 'data', 'living_world', 'versions')
    os.makedirs(versions, exist_ok=True)
    with open(os.path.join(versions, key + '.json'), 'w', encoding='utf-8') as f:
        json.dump({'module': module, 'version': version, 'nexus_id': nexus_id}, f, indent=2)
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
    ap.add_argument('--only', default=','.join(k for k, p in PROJECTS.items() if not p.get('unreleased')))
    ap.add_argument('--no-pack', action='store_true')
    a = ap.parse_args()
    for key in a.only.split(','):
        build(key.strip(), a.version, not a.no_pack)


if __name__ == '__main__':
    main()
