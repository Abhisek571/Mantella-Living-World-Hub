"""Offline check of how Papyrus scripts read action arguments (SKSE_HTTP.get*), no game needed.

SKSE_HTTP stores each argument in the type it arrived in and its getters do no type check: getString or
getStringArray on a number crashes the game (std::length_error "string too long"), getInt on text returns garbage.
So every key must be read with exactly one getter, the one that matches the type its action file declares:
  - no key is read with two getters of different types in one function or event (the old "getInt, then getString
    when it was 0" fallback that crashed Trade);
  - an argument an action file declares is read only with the getter of its declared type
    (integer -> getInt, number -> getFloat, string -> getString, boolean -> getBool, array of strings -> getStringArray).
usage: py -3 tools/check_action_getters.py <repo> [<repo> ...]   (default: every Mantella-Living-World-* next to the Hub)
Exit code 1 when any check fails.
"""
import glob
import json
import os
import re
import sys

GETTER_TYPE = {'getInt': 'integer', 'getFloat': 'number', 'getString': 'string', 'getBool': 'boolean',
               'getStringArray': 'array:string', 'getIntArray': 'array:integer', 'getFloatArray': 'array:number',
               'getBoolArray': 'array:boolean', 'getNestedDictionary': 'object', 'getNestedDictionariesArray': 'array:object'}
CALL = re.compile(r'SKSE_HTTP\.(get\w+)\(\s*(\w+)\s*,\s*("([^"]*)"|\w+)')
BLOCK_START = re.compile(r'^\s*(?:\w+(?:\[\])?\s+)?(Function|Event)\s+(\w+)', re.I)
BLOCK_END = re.compile(r'^\s*End(Function|Event)\b', re.I)


def declared_types(repo):
    """{parameter name (lower case, as SKSE_HTTP stores keys): {declared types}} over the repo's action files."""
    types = {}
    for path in glob.glob(os.path.join(repo, 'SKSE', 'Plugins', 'MantellaSoftware', 'data', 'actions', '*.json')):
        try:
            data = json.load(open(path, encoding='utf-8'))
        except Exception:
            continue
        for name, spec in (data.get('parameters') or {}).items():
            kind = spec.get('type', '')
            if kind == 'array':
                kind = 'array:' + ((spec.get('items') or {}).get('type') or 'string')
            types.setdefault(name.lower(), set()).add(kind)
    return types


def blocks(text):
    """(block name, [code lines]) per Function/Event; comments stripped."""
    out, name, lines = [], None, []
    for raw in text.splitlines():
        line = raw.split(';', 1)[0]
        if name is None:
            m = BLOCK_START.match(line)
            if m:
                name, lines = m.group(2), [line]
                if re.search(r'\bnative\b', line, re.I):
                    name = None
            continue
        lines.append(line)
        if BLOCK_END.match(line):
            out.append((name, lines))
            name = None
    return out


def problems_in(text, declared, label=''):
    """Every getter misuse in one script's text, as readable lines."""
    found = []
    for name, lines in blocks(text):
        seen = {}
        for line in lines:
            for getter, handle, key_expr, literal in CALL.findall(line):
                kind = GETTER_TYPE.get(getter)
                if kind is None:
                    continue
                key = literal.lower() if key_expr.startswith('"') else '$' + key_expr
                seen.setdefault((handle, key), set()).add(getter)
                if key_expr.startswith('"') and handle == 'aiArguments' and key in declared and kind not in declared[key]:
                    found.append(f'{label}{name}: "{literal}" is declared {"/".join(sorted(declared[key]))} but read with {getter}')
        for (handle, key), getters in seen.items():
            if len({GETTER_TYPE[g] for g in getters}) > 1:
                shown = key[1:] if key.startswith('$') else f'"{key}"'
                found.append(f'{label}{name}: {shown} is read with {" and ".join(sorted(getters))} (one getter per key)')
    return found


def check_repo(repo):
    declared = declared_types(repo)
    found = []
    for path in sorted(glob.glob(os.path.join(repo, 'Source', 'Scripts', '*.psc'))):
        found += problems_in(open(path, encoding='utf-8', errors='replace').read(), declared, os.path.basename(path) + ' ')
    return found


def main(argv):
    repos = argv or sorted(glob.glob(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '..',
                                                  'Mantella-Living-World-*')))
    bad = 0
    for repo in repos:
        if not os.path.isdir(os.path.join(repo, 'Source', 'Scripts')):
            continue
        found = check_repo(repo)
        print(('FAIL ' if found else 'PASS ') + f'action getters: {os.path.basename(os.path.normpath(repo))}')
        for line in found:
            print('   ' + line)
        bad += len(found)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
