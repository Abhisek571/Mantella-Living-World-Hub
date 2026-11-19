"""Offline tests for the code-quality pass of 2026-11-20: the shared step logger of the Hub's hooks (_logged), the NPC
page's short bio status, URL opening with retries (net.open_url, used by the update check and the model download),
release_command's error paths and its "keeps believing" choice, and the mod facts scanner on a small plugin built here.
Run with a Python 3.11: test_code_quality.py <repo server dir>"""
import io, json, logging, os, struct, sys, tempfile, urllib.error, zlib
from pathlib import Path

SERVER = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(SERVER))
import living_world as LW
from living_world import bio_optimise, command, embed, lw_state, memory, mod_facts_gen as G, net, release, update_check
memory.SUMMARY_RETRY_SECONDS = 0
embed.use(None)

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)[:500]) if not cond else ''))
    if not cond:
        FAILS.append(name)


class Logs(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


logs = Logs()
logging.getLogger('Mantella').addHandler(logs)


# --- _logged: one failing step is logged in the same words and goes no further -------------------------------------------
def part_logged():
    logs.lines.clear()
    ran = []
    with LW._logged('step one failed'):
        ran.append('one')
    check('a step that works runs and logs nothing', ran == ['one'] and logs.lines == [], logs.lines)
    with LW._logged('reputation failed', '; left out'):
        raise ValueError('bad file')
    ran.append('after')
    check('a failing step is logged with its error and the ending', logs.lines == ['Living World: reputation failed (bad file); left out'], logs.lines)
    check('the code after a failing step still runs', ran == ['one', 'after'])
    value = 'kept'
    with LW._logged('x'):
        value = 1 / 0
    check('a value set in a failing step keeps its old value', value == 'kept')
    try:
        with LW._logged('x'):
            raise KeyboardInterrupt
        check('an interrupt is not swallowed', False)
    except KeyboardInterrupt:
        check('an interrupt is not swallowed', True)


# --- the NPC page's short bio status ---------------------------------------------------------------------------------------
def part_page_status():
    long_bio = 'x' * (bio_optimise.MIN_CHARS + 10)
    on = {'bio_optimise': True}
    status = bio_optimise._page_status
    check('status: no bio', status('', on, False, None) == 'No bio yet.')
    check('status: switched off', status(long_bio, {'bio_optimise': False}, False, None).startswith('Short bios are switched off'))
    check('status: off wins over the opt-out', status(long_bio, {'bio_optimise': False}, True, None).startswith('Short bios are switched off'))
    check('status: opted out', status(long_bio, on, True, None).startswith('Set to use the original'))
    check('status: short enough', status('short', on, False, None) == 'Short enough (5 characters): the original is sent.')
    check('status: none yet', status(long_bio, on, False, None).startswith('No short bio yet'))
    manual = {'source': bio_optimise.MANUAL, 'status': 'done', 'text': 'y' * 40, 'before': 1500}
    check('status: hand edit in use', status(long_bio, on, False, manual)
          == 'Short bio edited by hand, in use: 1,500 -> 40 characters. Optimise leaves it alone until the original changes.')
    check('status: kept by hand', status(long_bio, on, False, dict(manual, status='kept')).startswith('The original is kept (decided by hand)'))
    done = {'status': 'done', 'text': 'y' * 40}
    check('status: short bio in use', status(long_bio, on, False, done).startswith(f"Short bio in use: {len(long_bio):,} -> 40 characters"))
    check('status: failed check, its reason', status(long_bio, on, False, {'status': 'failed', 'why': 'too long'})
          == 'The original is kept: too long.')
    check('status: failed check, no reason', status(long_bio, on, False, {'status': 'failed'})
          == 'The original is kept: the short version did not pass the check.')
    with tempfile.TemporaryDirectory() as tmp:
        view = bio_optimise.page_view('Lydia', '  short  ', on, os.path.join(tmp, 'bios.json'))
        check('page view: the original is shown as given, the status from the stripped text',
              view == {'status': 'Short enough (5 characters): the original is sent.', 'original': '  short  ', 'short': '',
                       'opted_out': False}, view)


# --- net.open_url: a timeout always, more tries only on 429 and 5xx ---------------------------------------------------------
def http_error(code):
    return urllib.error.HTTPError('https://example.invalid', code, 'error', {}, io.BytesIO(b''))


def part_open_url():
    def opener_of(answers, calls):
        def opener(target, timeout):
            calls.append((target, timeout))
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        return opener

    calls, waits = [], []
    got = net.open_url('u', 7, opener=opener_of([io.BytesIO(b'ok')], calls), sleep=waits.append)
    check('first try works: one call with the timeout, no wait', got.read() == b'ok' and calls == [('u', 7)] and waits == [], calls)
    calls, waits = [], []
    got = net.open_url('u', 7, opener=opener_of([http_error(503), http_error(429), io.BytesIO(b'ok')], calls), sleep=waits.append)
    check('503 then 429 then success: three calls, growing waits', got.read() == b'ok' and len(calls) == 3 and waits == [1.0, 2.0], waits)
    calls, waits = [], []
    try:
        net.open_url('u', 7, opener=opener_of([http_error(500)] * 3, calls), sleep=waits.append)
        check('three server errors: the last one is raised', False)
    except urllib.error.HTTPError as e:
        check('three server errors: the last one is raised', e.code == 500 and len(calls) == 3 and waits == [1.0, 2.0])
    for error in (http_error(404), OSError('no network'), TimeoutError('slow')):
        calls, waits = [], []
        try:
            net.open_url('u', 7, opener=opener_of([error], calls), sleep=waits.append)
            raised = None
        except Exception as e:
            raised = e
        check(f'{type(error).__name__} is not tried again', raised is error and len(calls) == 1 and waits == [])
    check('retryable: only 429 and 5xx', [net.retryable(http_error(c)) for c in (400, 404, 429, 500, 503, 599)]
          == [False, False, True, True, True, True] and not net.retryable(OSError()))

    body = json.dumps({'data': {'legacyModsByDomain': {'nodes': [{'modId': 5, 'version': '1.2', 'status': 'published'}]}}}).encode()
    calls, waits = [], []
    latest = update_check.fetch_latest([5], opener=opener_of([http_error(502), io.BytesIO(body)], calls), sleep=waits.append)
    check('the update check asks again after a server error', latest == {'5': '1.2'} and len(calls) == 2 and waits == [1.0], latest)
    check('the update check sends its timeout', calls[0][1] == update_check.TIMEOUT)

    real = dict(embed.FILES)
    try:
        import hashlib
        embed.FILES = {'tokenizer.json': (hashlib.sha256(b'{}').hexdigest(), 'https://example.invalid/tokenizer.json')}
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            answers = [http_error(503), io.BytesIO(b'{}')]
            real_sleep = net.time.sleep
            net.time.sleep = lambda s: None  # embed.download uses the default wait: no real waiting in the test
            try:
                ok = embed.download(tmp, opener_of(answers, calls))
            finally:
                net.time.sleep = real_sleep
            check('the model download tries again after a server error', ok and len(calls) == 2
                  and os.path.isfile(os.path.join(tmp, 'tokenizer.json')))
    finally:
        embed.FILES = real


# --- release_command: error paths and "keeps believing" ---------------------------------------------------------------------
def part_release():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        real_dir = lw_state.DATA_DIR
        lw_state.DATA_DIR = str(tmp / 'channel')
        os.makedirs(lw_state.DATA_DIR)
        try:
            store = memory.MemoryStore(str(tmp / 'conversations'), 'P1')
            out = release.release_command(store, 'c1', 'nonsense', player='Inga', today=10, in_talk=[])
            check('release: an unknown choice is refused', out == {'ok': False, 'message': 'Unknown choice: nonsense'}, out)
            out = release.release_command(store, 'c1', 'believe', player='Inga', today=10, in_talk=[])
            check('release: a command no longer in force', out == {'ok': False, 'message': 'That command is no longer in force.'}, out)
            lydia, hod = {'name': 'Lydia', 'ref_id': '000A2C94'}, {'name': 'Hod', 'ref_id': '00013B9B'}
            command.save(store, {'commands': [{'id': 'c1', 'text': 'Follow me', 'given': 8.0, 'npcs': [lydia, hod], 'hidden': []}],
                                 'seen': []})
            out = release.release_command(store, 'c1', 'believe', npc={'name': 'Ysolda', 'ref_id': '0001A69F'}, player='Inga',
                                          today=10, in_talk=[])
            check('release: an NPC the command does not bind', out == {'ok': False, 'message': 'That command does not bind them.'}, out)
            out = release.release_command(store, 'c1', ' Believe ', npc=lydia, player='Inga', today=10, in_talk=[])
            check('release believe for one NPC: ok, nothing changes', out['ok'] and out['message'] == 'Released (keeps believing). Lydia: nothing changes'
                  and out['npcs'] == [lydia] and out['requests'] == [], out)
            data = command.load(store)
            check('release for one NPC: the others stay bound', [n['name'] for n in data['commands'][0]['npcs']] == ['Hod'], data)
            check('release for one NPC: kept as ended with its choice', data['ended'][-1]['choice'] == 'believe'
                  and data['ended'][-1]['npcs'] == [lydia], data['ended'])
            row = release.record_rows(store, 'Lydia', '000A2C94')[0]
            check('release believe: the true record line', row['kind'] == 'release' and row['choice'] == 'believe' and row['mode'] == ''
                  and row['days'] == [8 + memory.MANTELLA_DAY, 10 + memory.MANTELLA_DAY] and row['end_marriage_request'] == '', row)
            check('release believe: nothing waits for the next request', release._key(lydia) not in release._pending['tell'])
            out = release.release_command(store, 'c1', 'believe', player='Inga', today=11, in_talk=[])
            check('release of the last NPC ends the command', out['ok'] and command.load(store)['commands'] == []
                  and out['message'] == 'Released (keeps believing). Hod: nothing changes', out)
        finally:
            lw_state.DATA_DIR = real_dir


# --- the mod facts scanner on a small plugin built here ---------------------------------------------------------------------
def field(tag, data):
    return tag + struct.pack('<H', len(data)) + data


def record(tag, form_id, body, flags=0):
    if flags & 0x40000:
        body = struct.pack('<I', len(body)) + zlib.compress(body)
    return tag + struct.pack('<III', len(body), flags, form_id) + b'\0' * 8 + body


def group(label, kind, content):
    return b'GRUP' + struct.pack('<IIi', 24 + len(content), label, kind) + b'\0' * 8 + content


def cond(func, p1, value=1.0, op=0):
    return field(b'CTDA', bytes([op << 5, 0, 0, 0]) + struct.pack('<fHHII', value, func, 0, p1, 0) + b'\0' * 12)


def z(text):
    return text.encode('utf-8') + b'\0'


NPC, GLOB, DIAL = 0x000801, 0x000802, 0x000803


def plugin_bytes():
    head = record(b'TES4', 0, field(b'HEDR', struct.pack('<fII', 1.7, 0, 0)))
    infos = b''
    lines = {1: ['I trust you a little more now, friend.', 'You have been kind to me lately.'],
             2: ['I would follow you to Sovngarde and back again.']}
    form = 0x000900
    for value, said in lines.items():
        for text in said:
            infos += record(b'INFO', form, cond(G.F_GETISID, NPC) + cond(G.F_GETGLOBALVALUE, GLOB, float(value)) + field(b'NAM1', z(text)))
            form += 1
    infos += record(b'INFO', form, cond(G.F_GETGLOBALVALUE, GLOB, 1.0) + field(b'NAM1', z('Said by anyone at all here.')))
    body = (group(0, 0, record(b'GLOB', GLOB, field(b'EDID', z('HildeTrust')) + field(b'FLTV', struct.pack('<f', 0.0))))
            + group(0, 0, record(b'NPC_', NPC, field(b'EDID', z('HildeNPC')) + field(b'FULL', z('Hilde')), flags=0x40000))
            + group(0, 0, record(b'DIAL', DIAL, field(b'EDID', z('HildeTopic')) + field(b'FULL', z('Talk')))
                    + group(DIAL, 7, infos)))
    return head + body


def part_mod_facts():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, 'HildeMod.esp')
        with open(path, 'wb') as f:
            f.write(plugin_bytes())
        parsed = G.read_plugin(path)
        check('plugin: no masters, not localized', parsed['masters'] == [] and not parsed['localized'], parsed['masters'])
        check('plugin: the global with its start value', parsed['glob'] == {GLOB: {'edid': 'HildeTrust', 'start': 0}}, parsed['glob'])
        check('plugin: a compressed NPC record is read', parsed['npc'] == {NPC: {'edid': 'HildeNPC', 'name': 'Hilde'}}, parsed['npc'])
        check('plugin: the topic', parsed['dial'] == {DIAL: {'edid': 'HildeTopic', 'text': 'Talk', 'quest': 0}}, parsed['dial'])
        check('plugin: every line with its topic and conditions', len(parsed['info']) == 4
              and all(i['topic'] == DIAL for i in parsed['info']) and parsed['info'][0]['resp'] == ['I trust you a little more now, friend.']
              and [c['func'] for c in parsed['info'][0]['conds']] == [G.F_GETISID, G.F_GETGLOBALVALUE]
              and list(parsed['info'][0]) == ['id', 'topic', 'conds', 'resp', 'prompt'], parsed['info'][:1])
        made = G.draft('HildeMod.esp', parsed, 'Hilde Mod', False)
        fact = made['npcs'][0]['facts'][0] if made else {}
        check('draft: one NPC with her name', made and made['npcs'][0]['name'] == 'Hilde' and made['npcs'][0]['npc'] == G.ref_of('HildeMod.esp', parsed, NPC), made)
        check('draft: the global, counted over her lines only', fact.get('editor_id') == 'HildeTrust' and fact.get('kind') == 'global'
              and fact.get('infos') == 3, fact)
        texts = [l['text'] for l in fact.get('lines', [])]
        check('draft: one line per value, quoting her own words', [(l['min'], l['max']) for l in fact.get('lines', [])] == [(1, 1), (2, 2)]
              and texts[0] == 'Hilde Mod: HildeTrust 1 (of 1-2). Said at this value: "I trust you a little more now, friend."', texts)
        check('draft: a global only her lines test needs only OWNED_MIN_INFOS lines', G.draft('HildeMod.esp', parsed, 'Hilde Mod', False, min_infos=4) is not None)
        check('draft: fewer lines than that, no file', G.draft('HildeMod.esp', dict(parsed, info=parsed['info'][:1]), 'Hilde Mod', False) is None)
        explicit = dict(parsed, info=[dict(i, resp=['Take me to bed, you are so naked.']) for i in parsed['info']])
        plain = G.draft('HildeMod.esp', explicit, 'Hilde Mod', False)
        check('draft: explicit lines only and no scene scripts: no file', plain is None, plain)
        sexual = G.draft('HildeMod.esp', explicit, 'Hilde Mod', True)
        lines = sexual['npcs'][0]['facts'][0]['lines'] if sexual else []
        check('draft: a scene mod says intimate above the lowest value, never quotes', [l['text'] for l in lines]
              == ['Hilde Mod: has been intimate with {player} (HildeTrust 2 (of 1-2))'], lines)
        check('draft: a localized plugin gives no file', G.draft('HildeMod.esp', dict(parsed, localized=True), 'Hilde Mod', False) is None)
        with open(os.path.join(tmp, 'bad.esp'), 'wb') as f:
            f.write(b'NOPE' + b'\0' * 30)
        try:
            G.read_plugin(os.path.join(tmp, 'bad.esp'))
            check('not a plugin: refused', False)
        except ValueError:
            check('not a plugin: refused', True)


part_logged()
part_page_status()
part_open_url()
part_release()
part_mod_facts()
print(f"\n{'ALL PASS' if not FAILS else str(len(FAILS)) + ' FAILED'}")
sys.exit(1 if FAILS else 0)
