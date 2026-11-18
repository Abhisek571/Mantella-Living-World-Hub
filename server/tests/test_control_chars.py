"""No control characters in the Hub's sources (tab, CR and LF only), and the "divorced" claim that one hid.
A backspace (\\x08) once stood in a regex of facts_history.py where \\b was meant (a heredoc turned "\\b" into the
character), so that pattern could never match. This scans every .py under server/living_world, every .psc and every
shipped text/JSON file of the repo (SKSE, MCM, Source, the root readme files).
Run with a Python 3.11: test_control_chars.py <repo server dir> [<other repo> ...]   (other repos: scanned the same way)"""
import os, re, sys
from pathlib import Path

SERVER = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(SERVER))
REPO = SERVER.parent
CONTROL = re.compile(rb'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
TEXT = ('.py', '.psc', '.json', '.txt', '.ini', '.md', '.yaml', '.yml', '.toml', '.cfg', '.html', '.css', '.js')
SKIP_DIRS = {'__pycache__', '.git', 'build', 'dist', 'node_modules', '.snapshots'}

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)) if not cond else ''))
    if not cond:
        FAILS.append(name)


def files_of(repo: Path):
    """The source and shipped text files of a repo: everything under server/living_world (Hub), Source, SKSE, MCM,
    plus its root text files; .psc anywhere outside build output."""
    roots = [repo / 'server' / 'living_world', repo / 'Source', repo / 'SKSE', repo / 'MCM', repo / 'Scripts']
    seen = set()
    for root in roots:
        if not root.is_dir():
            continue
        for d, dirs, names in os.walk(root):
            dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
            for n in names:
                if n.lower().endswith(TEXT):
                    seen.add(Path(d) / n)
    for d, dirs, names in os.walk(repo):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        seen.update(Path(d) / n for n in names if n.lower().endswith('.psc'))
    seen.update(p for p in repo.iterdir() if p.is_file() and p.suffix.lower() in ('.md', '.txt', '.json'))
    return sorted(seen)


def hits(repo: Path):
    out = []
    for path in files_of(repo):
        data = path.read_bytes()
        for m in CONTROL.finditer(data):
            line = data.count(b'\n', 0, m.start()) + 1
            out.append(f'{path.relative_to(repo)}:{line}: byte 0x{m.group(0)[0]:02x}')
    return out


found = hits(REPO)
check(f'Hub: no control characters other than tab, CR and LF ({len(files_of(REPO))} files)', not found, found[:20])
check('the scan sees facts_history.py and the shipped prompt rules',
      any(p.name == 'facts_history.py' for p in files_of(REPO)) and any(p.suffix == '.txt' and 'prompt_rules' in str(p) for p in files_of(REPO)))
check('the scan finds a backspace when there is one', CONTROL.search(b'divorced\\s+{p}\x08') is not None and not CONTROL.search(b'a\tb\r\n'))

# the pattern the backspace broke: "<her> divorced <the player>" (and the false positives that must stay quiet)
from living_world import facts_history as F
src = (REPO / 'server' / 'living_world' / 'facts_history.py').read_text(encoding='utf-8')
check('facts_history: the divorced pattern ends in a word boundary', r'divorced\s+{p}\b' in src)
ysolda = {'name': 'Ysolda', 'sex': 'female'}
for text in ('Ysolda divorced Inga.', 'She divorced Inga last spring.', 'Ysolda has divorced the player.', 'She divorced the player.'):
    check(f'divorced claim detected ({text})', F._unmarried_claim(text, 'Inga', ysolda))
for text in ('Lydia divorced Inga.', 'Her sister divorced Inga.', 'Inga divorced Lydia.', 'Lydia and Inga divorced.',
             'She is still married to Inga.'):
    check(f'not her: no divorced claim ({text})', not F._unmarried_claim(text, 'Inga', ysolda))
check('a longer name after the player is not cut ("Ingard" is not Inga)',
      not re.search(r"(?<![\w'])(?:ysolda)\s+" + F._AUX + r"divorced\s+(?:Inga|the player)\b", 'Ysolda divorced Ingard', re.I))

for other in sys.argv[2:]:
    path = Path(other).resolve()
    found = hits(path)
    check(f'{path.name}: no control characters other than tab, CR and LF ({len(files_of(path))} files)', not found, found[:20])

print(f'\n{len(FAILS)} failed' if FAILS else '\nall passed')
sys.exit(1 if FAILS else 0)
