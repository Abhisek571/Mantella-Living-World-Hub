"""Offline tests for short bios (server/living_world/bio_optimise.py and its hooks in living_world/__init__.py): the
check without a second call, one retry then the original, never longer, short bios untouched, the cache keyed by text
and format, the per-NPC opt-out, the setting, overrides as sources, the explicit write with its backup, the talk freeze
and the size report. Run with a Python 3.11: test_bio_optimise.py <repo server dir>"""
import json, os, sys, tempfile
from pathlib import Path

SERVER = Path(sys.argv[1])
sys.path.insert(0, str(SERVER))
import living_world
from living_world import bio_optimise as O, memory, npc_block, preview, settings

memory.SUMMARY_RETRY_SECONDS = 0

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)) if not cond else ''))
    if not cond:
        FAILS.append(name)


ORIGINAL = """Alvor is a blacksmith who lives in Riverwood.
Physical Appearance: Adult man with strong physique. Dirty blond hair, with thick beard.
Personality Keywords: hard-working, even-tempered, brave, honorable
Riverwood Information: A village along the White River. Alvor and Sigrid's house and attached smithy are near the riverbank.
Tavern Patron: In the evening, Alvor sometimes drinks at the local Sleeping Giant Inn.
Alvor's Known Family Members:
- Sigrid: His beautiful wife.
- Dorthe: Their daughter. She often tries to convince Alvor to let her start working the forge.
- Hadvar: His nephew. Imperial legionnaire. Alvor and Sigrid are happy to host him if he visits.
Regarding the local jarl: "Jarl Balgruuf? He rules Whiterun Hold. A good man; perhaps a bit over-cautious, but these are dangerous times. I don't think he likes either Ulfric or Elisif much."
Toward travelers: "Whatever you need. By Ysmir, if it's simple and strong, I can forge it."
He charges 25 gold to sharpen a blade."""
BACKGROUND = ['- Race: Nord', '- Sex: male', '- Family: Dorthe (child)', '- Home: Riverwood', '- Role: blacksmith', '- Partner: married to Player']
GOOD = """Personality: hard-working, even-tempered, brave and honourable.
Looks: strong build, dirty blond hair, thick beard.
Voice: plain village speech: "By Ysmir".
History: smithy beside the house on the White River in Riverwood; drinks some evenings at the Sleeping Giant Inn. Wife Sigrid; daughter Dorthe wants to work the forge; nephew Hadvar, an Imperial legionnaire, is always welcome. Charges 25 gold to sharpen a blade.
Knows: Jarl Balgruuf rules Whiterun Hold, a good man but over-cautious, who likes neither Ulfric nor Elisif.
Sample lines: "Whatever you need. By Ysmir, if it's simple and strong, I can forge it.\""""
NO_HADVAR = GOOD.replace('; nephew Hadvar, an Imperial legionnaire, is always welcome', '')


class Ask:
    """A stand-in helper call: replies in turn, records (prompt, text)."""
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []
    def __call__(self, prompt, text):
        self.calls.append((prompt, text))
        reply = self.replies[min(len(self.calls), len(self.replies)) - 1]
        if isinstance(reply, Exception):
            raise reply
        return reply


# --- the check ------------------------------------------------------------------------------------------------------------

keep = O.must_keep(ORIGINAL, '\n'.join(O.stable_lines(BACKGROUND)), 'Alvor')
check('must keep: the named people, places and the number', all(x in keep for x in ('Riverwood', 'Sigrid', 'Hadvar', 'Balgruuf', 'Ulfric', 'Elisif', 'Sleeping', 'Ysmir', '25')), keep)
check('must keep: not the own name or field labels', not any(x in keep for x in ('Alvor', 'Physical', 'Appearance', 'Personality', 'Regarding', "I'd")), keep)
check('must keep: family the Background states too (family is never covered, live test 9)', 'Dorthe' in keep, keep)
check('a good result passes the check', O.problems(ORIGINAL, GOOD, '\n'.join(BACKGROUND), 'Alvor') == ([], []))
check('simple inflection counts: Imperials for Imperial, Nords for Nord', O._same_word('imperials', 'imperial') and O._same_word('cyrodilic', 'cyrodiil')
      and not O._same_word('hod', 'hold'))
bad, lost = O.problems(ORIGINAL, NO_HADVAR, '\n'.join(BACKGROUND), 'Alvor')
check('a result that drops a named person fails, naming them', lost == ['Hadvar'] and 'leaves out Hadvar' in '; '.join(bad), (bad, lost))
NO_DORTHE = GOOD.replace('daughter Dorthe wants to work the forge; ', '')
check('a family name stays even when a Background line states it (live test 9: ties data is not guaranteed)',
      'Dorthe' in O.missing(ORIGINAL, NO_DORTHE, '\n'.join(O.stable_lines(BACKGROUND)), 'Alvor'))
check('...and without that Background line too', 'Dorthe' in O.missing(ORIGINAL, NO_DORTHE, '', 'Alvor'))

# per save: only lines every save states alike count as covered (home, partner, role can differ between saves)
check('stable lines: race and sex only (family and spouse are never covered)',
      O.stable_lines(BACKGROUND + ['- Spouse: Sigrid', '- Follower: yes']) == ['- Race: Nord', '- Sex: male'])
NO_HOME = GOOD.replace(' in Riverwood', '')
check('a home the Background states is never covered: it must stay in the shared bio', 'Riverwood' in O.missing(ORIGINAL, NO_HOME, '\n'.join(O.stable_lines(BACKGROUND)), 'Alvor'))
ask = Ask(NO_HOME, NO_HOME)
d = O.optimise_detail(ORIGINAL, BACKGROUND, 'Alvor', ask)
check('optimise: a result that drops the home is refused even when this save states it', d['status'] == 'kept' and 'Riverwood' in d['why'], d['why'])
check('optimise: the helper is shown only the stable lines (no home, partner, role or family)', '- Home:' not in ask.calls[0][1]
      and '- Partner:' not in ask.calls[0][1] and '- Family:' not in ask.calls[0][1] and '- Race: Nord' in ask.calls[0][1])
ties = {'013BA0': {'name': 'Alvor', 'ties': [{'kind': 'spouse', 'base': '013BA1', 'name': 'Sigrid'},
                                              {'kind': 'child', 'base': '013BA2', 'name': 'Dorthe'},
                                              {'kind': 'works_for', 'base': '013BA9', 'name': 'Hod'}]}}
stable = O.stable_background({'name': 'Alvor', 'race': 'NORD', 'sex': 'male', 'base_id': '013BA0', 'home': "Player's house",
                              'follower': 1, 'spouse': 1}, {}, ties)
check('stable background: race, sex, family and the own spouse from ties.json; no home, follower or player marriage',
      stable == ['- Race: Nord', '- Sex: male', '- Family: Dorthe (child)', '- Spouse: Sigrid'], stable)

# fewer false names: ordinary words inside a name are not checked alone; the name's own word is, and "the Eight" is a name
FALSE = ("She keeps the tradition of the Five Hundred Companions. She knows Close Wounds and fears the Dark Brotherhood. "
         "\"May the blessings of the Eight be with you,\" she says to Master Wizard Tolfdir by the White River.")
kept = O.must_keep(FALSE, '', 'Aela')
check('stop-list: Five, Close, Dark, Master and White are not checked alone', not any(x in kept for x in ('Five', 'Close', 'Dark', 'Master', 'White')), kept)
check('stop-list: the real names are still checked (Companions, Wounds, Brotherhood, Wizard, Tolfdir, River, the Eight)',
      all(x in kept for x in ('Companions', 'Wounds', 'Brotherhood', 'Wizard', 'Tolfdir', 'River', 'Eight')), kept)
check('stop-list: ordinary words are not called invented either', O.added(FALSE, FALSE + ' Five Close Dark.', '', 'Aela') == [])
check('an invented name fails', 'Thane' in ' '.join(O.problems(ORIGINAL, GOOD.replace('beard.', 'beard, sworn to the Thane Erikur.'), '\n'.join(BACKGROUND), 'Alvor')[0]))
check('a cut-off result fails', 'cut off' in ' '.join(O.problems(ORIGINAL, GOOD[:-30], '\n'.join(BACKGROUND), 'Alvor')[0]))
check('prose without the labelled parts fails', 'labelled' in ' '.join(O.problems(ORIGINAL, GOOD.replace('Personality:', 'He is').replace('Looks:', '').replace('Voice:', '').replace('History:', '').replace('Knows:', '').replace('Sample lines:', ''), '\n'.join(BACKGROUND), 'Alvor')[0]))
# placeholders: kept where they stand in a sentence the result kept; one only in a dropped sentence is no reason to reject
WITH_NAME = ORIGINAL + ' He greets {player_name} warmly at the forge.'
check('placeholders in braces must stay in a kept sentence', '{player_name}' in O.missing(WITH_NAME, GOOD + ' Greets the player warmly at the forge.', '', 'Alvor'))
check('a placeholder only in a dropped sentence is not required', '{player_name}' not in O.missing(WITH_NAME, GOOD, '', 'Alvor'))
check('a placeholder in a rule is carried with the rule', '{player_name}' in O.must_keep(ORIGINAL + ' Never call {player_name} a friend unless earned.', '', 'Alvor'))

# --- optimise -------------------------------------------------------------------------------------------------------------

ask = Ask(GOOD)
d = O.optimise_detail(ORIGINAL, BACKGROUND, 'Alvor', ask)
check('a shorter, complete result is accepted on the first call', d['status'] == 'done' and d['text'] == GOOD and len(ask.calls) == 1, d)
check('the helper gets the Background facts and the sheet; the prompt asks for the shape, no second person', 'Background facts already sent'
      in ask.calls[0][1] and ORIGINAL in ask.calls[0][1] and 'Personality:' in ask.calls[0][0] and 'Sample lines' in ask.calls[0][0]
      and 'third person' in ask.calls[0][0], ask.calls[0][0][:200])
check('optimise() returns the text', O.optimise(ORIGINAL, BACKGROUND, 'Alvor', Ask(GOOD)) == GOOD)

ask = Ask(NO_HADVAR, NO_HADVAR)
d = O.optimise_detail(ORIGINAL, BACKGROUND, 'Alvor', ask)
check('dropping a name: retried once with the missing items listed, then the original is kept with why', d['status'] == 'kept'
      and d['text'] == ORIGINAL.strip() and len(ask.calls) == 2 and 'leaves out Hadvar' in ask.calls[1][0] and 'Hadvar' in d['why'], d)
ask = Ask(NO_HADVAR, GOOD)
check('dropping a name, fixed on the retry: accepted', O.optimise_detail(ORIGINAL, BACKGROUND, 'Alvor', ask)['status'] == 'done' and len(ask.calls) == 2)
longer = GOOD + '\nKnows: ' + ORIGINAL.replace('\n', ' ')
ask = Ask(longer, longer)
d = O.optimise_detail(ORIGINAL, BACKGROUND, 'Alvor', ask)
check('never longer: a result as long as the original is refused and the original kept', d['status'] == 'kept' and d['text'] == ORIGINAL.strip()
      and 'not clearly shorter' in d['why'], d['why'])
ask = Ask(GOOD)
d = O.optimise_detail('Lydia is a housecarl of Whiterun, loyal and dry-witted.', [], 'Lydia', ask)
check('a short bio is left alone, no call', d['status'] == 'short' and not ask.calls and d['text'].startswith('Lydia is'))
d = O.optimise_detail(ORIGINAL, BACKGROUND, 'Alvor', Ask(RuntimeError('rate limited')))
check('a failed call keeps the original and is marked as an error (not cached)', d['status'] == 'kept' and d.get('error'))
O.helper.update(summaries=None, config=None)
check('no model reachable: optimise() gives the original, no call', O.pick_ask(ORIGINAL) is None and O.optimise(ORIGINAL, BACKGROUND, 'Alvor') == ORIGINAL.strip())
check('code fences and bold labels are cleaned', O.clean_reply('```\n**Voice**: soft.\n```') == 'Voice: soft.')

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    path = str(tmp / 'bios.json')
    on, off = dict(settings.DEFAULTS), dict(settings.DEFAULTS, bio_optimise=False)
    check('the setting is on by default', settings.DEFAULTS['bio_optimise'] is True and settings.load(str(tmp / 'none.json'))['bio_optimise'] is True)

    # --- the cache ------------------------------------------------------------------------------------------------------
    check('nothing cached: the original is used', O.used_bio('Alvor', ORIGINAL, on, path) == ORIGINAL)
    O.remember('Alvor', ORIGINAL, {'status': 'done', 'text': GOOD}, path)
    check('a current short bio is used in place of the original', O.used_bio('Alvor', ORIGINAL, on, path) == GOOD)
    check('the cache is keyed by the text: a changed original is not current', O.entry('Alvor', ORIGINAL + ' He hates trolls.', path) is None
          and O.used_bio('Alvor', ORIGINAL + ' He hates trolls.', on, path) == ORIGINAL + ' He hates trolls.')
    check('spacing alone does not change the key', O.bio_hash(ORIGINAL) == O.bio_hash(ORIGINAL.replace('\n', '\r\n') + '  '))
    real_version = O.FORMAT_VERSION
    O.FORMAT_VERSION = real_version + 1
    check('a new format version is not current (written again)', O.entry('Alvor', ORIGINAL, path) is None and O.used_bio('Alvor', ORIGINAL, on, path) == ORIGINAL)
    O.FORMAT_VERSION = real_version
    check('setting off: the original is used', O.used_bio('Alvor', ORIGINAL, off, path) == ORIGINAL)
    O.set_use_original('Alvor', True, path)
    check('opt-out sticks: the original is used, the short bio is kept', O.used_bio('Alvor', ORIGINAL, on, path) == ORIGINAL
          and O.uses_original('alvor', path) and O.entry('Alvor', ORIGINAL, path)['text'] == GOOD)
    O.set_use_original('Alvor', False, path)
    check('opt-out switched back: the short bio again', O.used_bio('Alvor', ORIGINAL, on, path) == GOOD)
    O.remember('Hod', ORIGINAL.replace('Alvor', 'Hod'), {'status': 'kept', 'text': ORIGINAL, 'why': 'failed twice'}, path)
    check('a kept result is cached but sends the original', O.used_bio('Hod', ORIGINAL.replace('Alvor', 'Hod'), on, path) == ORIGINAL.replace('Alvor', 'Hod')
          and O.entry('Hod', ORIGINAL.replace('Alvor', 'Hod'), path)['why'] == 'failed twice')
    check('an error is never cached', O.remember('Gerdur', ORIGINAL, {'status': 'kept', 'text': ORIGINAL, 'error': True}, path) is None)
    check('the cache file lives in the user folder, never in the shipped extension', os.path.dirname(O.PATH) != os.path.dirname(O.__file__)
          and O.PATH.startswith(living_world.ui_overrides.user_folder()) and O.PATH.endswith('living_world_bios.json'), O.PATH)
    page = O.page_view('Alvor', ORIGINAL, on, path)
    check('the page shows original and short version side by side', page['original'] == ORIGINAL and page['short'] == GOOD and 'Short bio in use' in page['status'], page['status'])
    check('the page says when it is switched off', 'switched off' in O.page_view('Alvor', ORIGINAL, off, path)['status'])

    # --- the prompt ---------------------------------------------------------------------------------------------------
    prompt = f"# Background\n{ORIGINAL}\n\n# Rules\nBe brief."
    out = O.apply(prompt, [('Alvor', ORIGINAL), ('Lydia', 'Short.')], lambda n, o: O.used_bio(n, o, on, path))
    check('apply: the short bio replaces the original in the prompt, the rest stays', GOOD in out and ORIGINAL not in out and out.endswith('Be brief.'))
    check('apply: setting off leaves the prompt as it was', O.apply(prompt, [('Alvor', ORIGINAL)], lambda n, o: O.used_bio(n, o, off, path)) == prompt)

    # the hook: the bio is chosen once per talk and kept; a newer one is used from the next talk
    real_path, real_load = O.PATH, settings.load
    O.PATH = path
    settings.load = lambda p=settings.PATH: dict(on)
    living_world._last_store.update(store=None, people=[('Alvor', '0A0B0C')], bios=[('Alvor', ORIGINAL)], npc_text='')
    npc_block.talk_over()
    parts = living_world._system_parts({'mantella': prompt}, {})
    sent = '\n'.join(v for k, v in parts.items() if isinstance(v, str))
    check('the system prompt hook sends the short bio', GOOD in sent and 'Dirty blond hair, with thick beard' not in sent)
    newer = GOOD.replace('thick beard', 'thick red beard')
    O.remember('Alvor', ORIGINAL, {'status': 'done', 'text': newer}, path)
    sent = '\n'.join(v for k, v in living_world._system_parts({'mantella': prompt}, {}).items() if isinstance(v, str))
    check('mid-talk: the bio sent does not change (cache stays valid)', GOOD in sent and 'thick red beard' not in sent)
    rows = dict((r[0], r) for r in preview.sections_for('Alvor'))
    check('size report: bio sent and the original, per section', rows['bio sent'][1] == preview.tokens(GOOD)
          and rows['bio sent'][2] == f"original {preview.tokens(ORIGINAL):,}" and 'Background' in rows and 'system prompt' in rows, rows)
    check('size report on the Status page', 'Alvor: bio sent' in preview.sections_text())
    npc_block.talk_over()
    sent = '\n'.join(v for k, v in living_world._system_parts({'mantella': prompt}, {}).items() if isinstance(v, str))
    check('next talk: the newer short bio is used', 'thick red beard' in sent)
    settings.load = lambda p=settings.PATH: dict(off)
    npc_block.talk_over()
    sent = '\n'.join(v for k, v in living_world._system_parts({'mantella': prompt}, {}).items() if isinstance(v, str))
    check('setting off: the hook sends the original', 'Dirty blond hair, with thick beard' in sent)

    # --- after a talk ---------------------------------------------------------------------------------------------------
    class NPC:
        def __init__(self, name, bio):
            self.name, self.bio, self.ref_id = name, bio, '0A0B0C'
    class Summaries:
        def __init__(self, reply, room=None):
            self.reply, self.calls = reply, []
            self._Summaries__client = type('C', (), {'_request_params': {'max_tokens': room} if room else {}})()
        def summarize_conversation(self, text, prompt):
            self.calls.append((text, prompt))
            return self.reply
    O.PATH = str(tmp / 'after.json')
    people = [NPC(f"Guard{i}", ORIGINAL.replace('Alvor', f"Guard{i}")) for i in range(5)]
    good_for = lambda n: GOOD.replace('Alvor', n)
    s = Summaries(None)
    check('setting off: nothing queued', O.after_talk(people, s, off, background=False) == [] and not s.calls)
    s.reply = good_for('Guard0')
    done = O.after_talk(people, s, on, lambda npc: BACKGROUND, background=False)
    check('after a talk: at most MAX_PER_TALK NPCs, one call each', len(done) == O.MAX_PER_TALK and len(s.calls) == O.MAX_PER_TALK, (len(done), len(s.calls)))
    check('after a talk: the result is cached for the next talk', O.entry('Guard0', people[0].bio) is not None)
    s.calls.clear()
    O.set_use_original('Guard3', True)
    O.after_talk(people, s, on, lambda npc: BACKGROUND, background=False)
    check('already done and opted-out NPCs are not asked again', [t for t, _ in s.calls] and all('Guard3' not in t for t, _ in s.calls)
          and all('Guard0' not in t.split('Character sheet of ')[1][:8] for t, _ in s.calls), [t.split('Character sheet of ')[1][:8] for t, _ in s.calls])
    tight = Summaries(GOOD, room=50)
    check('too long for the summary reply limit: not asked (never cut off)', O.after_talk([NPC('Lucan', ORIGINAL.replace('Alvor', 'Lucan'))], tight, on, background=False) == []
          and not tight.calls)
    check('reply room is read from the summary client', O.reply_room(tight) == 50 and O.reply_room(Summaries(GOOD)) is None)

    # with Mantella's config: a client of its own with room for the answer, so long bios are done after the talk too
    made = []
    real_asker = living_world.ui_overrides.model_asker
    roomy_calls = []
    def fake_asker(config, summary=False, max_tokens=1500):
        made.append((config, summary, max_tokens))
        return lambda prompt, text: roomy_calls.append(text) or GOOD.replace('Alvor', 'Faendal')
    living_world.ui_overrides.model_asker = fake_asker
    O._roomy.update(config=None, ask=None)
    tight = Summaries(GOOD, room=50)
    tight._Summaries__config = object()  # Mantella's config, as its Summaries object holds it
    lucan = NPC('Faendal', ORIGINAL.replace('Alvor', 'Faendal'))
    done = O.after_talk([lucan], tight, on, lambda npc: BACKGROUND, background=False)
    check('long bio, 250-token summary limit: done after the talk on a roomy client, not skipped', done and done[0]['status'] == 'done'
          and roomy_calls and not tight.calls, (done, len(roomy_calls), len(tight.calls)))
    check('the roomy client: the summary model when set, with room for REPLY_TOKENS', made == [(tight._Summaries__config, True, O.REPLY_TOKENS)]
          and O.REPLY_TOKENS >= 2000, made)
    check('the roomy client is made once and reused', O.roomy_ask(tight) is O.roomy_ask(tight) and len(made) == 1)
    cut = Summaries(None)
    cut._Summaries__config = tight._Summaries__config
    living_world.ui_overrides.model_asker = lambda config, summary=False, max_tokens=1500: (lambda p, t: GOOD.replace('Alvor', 'Hulda')[:-40])
    O._roomy.update(config=None, ask=None)
    hulda = NPC('Hulda', ORIGINAL.replace('Alvor', 'Hulda'))
    done = O.after_talk([hulda], cut, on, lambda npc: BACKGROUND, background=False)
    check('a cut-off answer is never stored as the short bio', done and done[0]['status'] == 'kept' and 'cut off' in done[0]['why']
          and O.used_bio('Hulda', hulda.bio, on) == hulda.bio, done)
    living_world.ui_overrides.model_asker = real_asker
    O._roomy.update(config=None, ask=None)
    O.PATH = real_path

    # --- the NPC page: side by side, Use original, Optimise again ---------------------------------------------------
    from living_world import npc_page_ui as P
    O.PATH = str(tmp / 'page.json')
    settings.load = lambda p=settings.PATH: dict(on)
    GOOD_RW = GOOD.replace('on the White River', 'on the White River in Riverwood')  # no saved home here: it must stay
    ctx = type('Ctx', (), {'name': 'Alvor', 'row': {'bio': ORIGINAL}, 'store': None, 'player': 'Player',
                           'speaker': {'name': 'Alvor', 'race': 'Nord'}, 'entry': lambda self: {}})()
    view = P.short_bio_view(ctx)
    check('NPC page: no short bio yet, the original shown', view['sb_original'] == ORIGINAL and view['sb_short'] == '(none yet)' and 'No short bio yet' in view['sb_status'])
    said = P.optimise_again(ctx, Ask(GOOD_RW))
    view = P.short_bio_view(ctx)
    check('NPC page: Optimise again writes it, shown beside the original', 'Short bio written' in said and view['sb_short'] == GOOD_RW, said)
    said = P.optimise_again(ctx, Ask(NO_HADVAR, NO_HADVAR))
    check('NPC page: Optimise again that fails the check keeps the original and says why', 'original is kept' in said and 'Hadvar' in said
          and P.short_bio_view(ctx)['sb_short'] == '(none yet)', said)
    P.optimise_again(ctx, Ask(GOOD_RW))
    P.toggle_original(ctx)
    view = P.short_bio_view(ctx)
    check('NPC page: Use original for this NPC sticks, the button offers the way back', O.uses_original('Alvor')
          and view['sb_toggle']['__update__']['value'] == 'Use the short bio again' and O.used_bio('Alvor', ORIGINAL, on) == ORIGINAL)
    P.toggle_original(ctx)
    check('NPC page: back to the short bio', O.used_bio('Alvor', ORIGINAL, on) == GOOD_RW)
    short_ctx = type('Ctx', (), {'name': 'Lydia', 'row': {'bio': 'Lydia is a housecarl.'}})()
    check('NPC page: a short bio is not sent for optimising', 'short enough' in P.optimise_again(short_ctx, Ask(GOOD)))
    O.PATH = real_path

    # --- overrides ------------------------------------------------------------------------------------------------------
    folder = tmp / 'character_overrides'
    folder.mkdir()
    (folder / 'Alvor.json').write_text(json.dumps({'name': 'Alvor', 'race': 'Nord', 'bio': ORIGINAL}, indent=2), encoding='utf-8')
    (folder / 'Lydia.json').write_text(json.dumps({'name': 'Lydia', 'bio': 'Lydia is a housecarl.'}), encoding='utf-8')
    (folder / 'Hod.json').write_text(json.dumps({'name': 'Hod', 'bio': ORIGINAL.replace('Alvor', 'Hod')}), encoding='utf-8')
    before = {f.name: f.read_bytes() for f in folder.iterdir()}
    opath = str(tmp / 'override_bios.json')
    asks = {'Alvor': Ask(GOOD), 'Hod': Ask(NO_HADVAR.replace('Alvor', 'Hod'), NO_HADVAR.replace('Alvor', 'Hod'))}
    seen = []
    r = O.optimise_overrides(str(folder), lambda bio, name: asks[name], lambda row: BACKGROUND, lambda i, n, name: seen.append((i, n, name)), path=opath)
    check('Optimise all: every override with a bio, the short one left alone', r['total'] == 3 and r['shortened'] == 1 and r['short'] == 1
          and r['kept'] and r['kept'][0][0] == 'Hod' and 'Hadvar' in r['kept'][0][1], r)
    check('Optimise all: progress for each NPC', [x[2] for x in seen[:-1]] == ['Alvor', 'Hod', 'Lydia'] and seen[-1][:2] == (3, 3), seen)
    check('Optimise all: the override text is the source (cached under its hash)', O.entry('Alvor', ORIGINAL, opath)['text'] == GOOD
          and O.entry('Alvor', ORIGINAL, opath)['source'] == 'button')
    check('Optimise all: the override files are not touched', {f.name: f.read_bytes() for f in folder.iterdir()} == before)
    text = O.summary_text(r)
    check('Optimise all: a summary with counts, saving and why kept', '1 shortened now' in text and 'kept Hod' in text and 'characters' in text, text)
    again = O.optimise_overrides(str(folder), lambda bio, name: Ask(GOOD), lambda row: BACKGROUND, path=opath)
    check('Optimise all again: current ones are not asked again', again['current'] == 2 and again['shortened'] == 0, again)
    check('the automatic path never writes override files', {f.name: f.read_bytes() for f in folder.iterdir()} == before)

    backups = tmp / 'backups'
    w = O.write_into_overrides(str(folder), opath, str(backups))
    saved = list(backups.iterdir())
    check('Write into overrides: a dated backup of every file first, byte for byte', len(saved) == 1
          and {f.name: f.read_bytes() for f in saved[0].iterdir()} == before, w)
    alvor = json.loads((folder / 'Alvor.json').read_text(encoding='ascii'))
    check('Write into overrides: the short bio is in the file (ASCII), other fields kept', alvor['bio'] == GOOD and alvor['race'] == 'Nord' and w['bios'] == 1)
    check('Write into overrides: a kept NPC and a short bio are untouched', (folder / 'Hod.json').read_bytes() == before['Hod.json']
          and (folder / 'Lydia.json').read_bytes() == before['Lydia.json'])
    check('Write into overrides: the written text is not shortened again', not O.due('Alvor', GOOD, on, opath)
          and O.used_bio('Alvor', GOOD, on, opath) == GOOD)
    check('Write into overrides: the default backup folder sits next to the overrides folder, not in it',
          O.BACKUPS not in str(folder) and not O.BACKUPS.startswith('character_overrides' + os.sep))
    O.set_use_original('Hod', True, opath)
    waits = iter([True, False])
    real_sleep = O.time.sleep
    O.time.sleep = lambda s: None
    forced = O.optimise_overrides(str(folder), lambda b, n: Ask(GOOD.replace('Alvor', n)), lambda row: BACKGROUND, force=True, path=str(tmp / 'w.json'),
                                  wait=lambda: next(waits, False))
    O.time.sleep = real_sleep
    check('Optimise all waits while a talk goes on, then asks', forced['shortened'] + len(forced['kept']) >= 1, forced)
    check('opt-out NPCs are skipped by Optimise all', O.optimise_overrides(str(folder), lambda b, n: Ask(GOOD), path=opath)['opted_out'] == 1)
    empty = tmp / 'none'
    empty.mkdir()
    check('Write into overrides with no files: nothing, no backup', O.write_into_overrides(str(empty), opath, str(tmp / 'b2'))['files'] == 0
          and not (tmp / 'b2').exists())
    settings.load = real_load

# --- model_asker: its own client with room and no stop; the summary model when one is set -------------------------------
import types
made_clients = []
class FakeClient:
    def __init__(self, config):
        self._request_params = {'max_tokens': 250, 'stop': ['#']}
        made_clients.append((type(self).__name__, self))
    def request_call(self, thread):
        return 'reply'
class LLMClient(FakeClient): pass
class SummaryLLMClient(FakeClient): pass
class Thread:
    def __init__(self, config, system): self.system = system
    def add_message(self, m): pass
fakes = {'src': types.ModuleType('src'), 'src.llm': types.ModuleType('src.llm'),
         'src.llm.llm_client': types.SimpleNamespace(LLMClient=LLMClient),
         'src.llm.summary_client': types.SimpleNamespace(SummaryLLMClient=SummaryLLMClient),
         'src.llm.message_thread': types.SimpleNamespace(message_thread=Thread),
         'src.llm.messages': types.SimpleNamespace(UserMessage=lambda config, text: text)}
saved_modules = {k: sys.modules.get(k) for k in fakes}
sys.modules.update(fakes)
from living_world import ui_overrides as U
U.model_asker(types.SimpleNamespace(summary_llm_enabled=True), summary=True, max_tokens=3000)('sys', 'text')
U.model_asker(types.SimpleNamespace(summary_llm_enabled=False), summary=True, max_tokens=3000)('sys', 'text')
U.model_asker(types.SimpleNamespace(summary_llm_enabled=True))('sys', 'text')
check('model_asker: the custom summary model when set, else the conversation model; the button keeps the conversation model',
      [n for n, _ in made_clients] == ['SummaryLLMClient', 'LLMClient', 'LLMClient'], made_clients)
check('model_asker: room for the reply and no stop sequence (no cut-off at 250 tokens or at #)',
      made_clients[0][1]._request_params == {'max_tokens': 3000} and made_clients[2][1]._request_params == {'max_tokens': 1500})
for k, v in saved_modules.items():
    if v is None:
        sys.modules.pop(k, None)
    else:
        sys.modules[k] = v

# --- release safety: the build never packs the cache, the overrides or the Characters file -------------------------------
build_py = (SERVER.resolve().parent / 'tools' / 'build.py').read_text(encoding='utf-8')
check('build: the release check refuses the cache, override folders and the Characters file', all(x in build_py for x in
      ("r'living_world_bios'", "r'character_overrides'", "living_world_characters")), '')
check('build: the extension copy ignores a stray cache file', '"living_world_bios*.json"' in build_py)
# --- live test 5: the owner's override bios (bios-before-after.md) ---------------------------------------------------------
# Short excerpts of the real originals and results are inline; the whole file is checked too when it is there.
RULE = ("Anything between her and the player beyond a first meeting develops only through their conversations and shared "
        "history; it is never assumed.")
BREVAL = ("Breval is a Breton woman who was once a happy housewife, until her husband died suddenly one night of an "
          "unexplained exhaustion. After years of mourning she devoted her life to Mara, hoping the goddess would one day "
          "bless her with love and a family again. She serves at the Temple of Mara in Riften.\n\nShe is warm, gentle and "
          "popular, widely admired in Riften, and still carries a quiet grief beneath her kindness. She is not much of a "
          "fighter, relying on alteration, wards and restoration to keep herself safe, and when she gets into trouble her "
          "many local admirers are quick to come to her aid. " + RULE)
BREVAL_AFTER = ("Personality: warm, gentle, popular and widely admired; carries quiet grief beneath her kindness. Hopes Mara "
                "will bless her with love and a family again. Not a fighter.\nHistory: once a happy housewife; her husband "
                "died suddenly one night of unexplained exhaustion. After years of mourning she devoted herself to Mara. "
                "Serves at the Temple of Mara in Riften. Uses alteration, wards and restoration for safety; local admirers "
                "rush to her aid when she's in trouble.\nKnows: nothing beyond a first meeting with {player_name} unless "
                "conversation and shared history build it.")
check('rules: the "never assumed" line is found word for word', O.rule_items(BREVAL) == [RULE], O.rule_items(BREVAL))
check('rules: the helper never sees them (the sheet it gets has no rule line)', RULE not in O.without_rules(BREVAL))
bad, _ = O.problems(BREVAL, BREVAL_AFTER, '', 'Breval')
check('rules: the real misfiled result ("Knows: nothing beyond a first meeting") fails for the missing rule',
      any('rule lines word for word' in b for b in bad), bad)
fixed = O.with_rules(BREVAL_AFTER.replace("\nKnows: nothing beyond a first meeting with {player_name} unless conversation and shared history build it.", ''), O.rule_items(BREVAL))
check('rules: carried verbatim into a final Rules part, the result passes', fixed.endswith('Rules: ' + RULE) and O.problems(BREVAL, fixed, '', 'Breval')[0] == [],
      O.problems(BREVAL, fixed, '', 'Breval'))
check('rules: a Rules part the helper writes anyway is replaced by the verbatim one',
      O.with_rules(BREVAL_AFTER + '\nRules: be nice.', [RULE]).count('Rules:') == 1 and 'be nice' not in O.with_rules(BREVAL_AFTER + '\nRules: be nice.', [RULE]))
check('rules: they do not count against the length', len(O.without_rules(BREVAL)) == len(BREVAL) - len(RULE) - 1)
BREVAL_LONG = BREVAL.replace('in Riften.', 'in Riften, where she tends the sick and keeps the shrine clean.', 1)
ask = Ask(BREVAL_AFTER.replace("\nKnows: nothing beyond a first meeting with {player_name} unless conversation and shared history build it.", ''))
d = O.optimise_detail(BREVAL_LONG, [], 'Breval', ask)
check('optimise: the rule is added by the code, word for word; the helper got the sheet without it',
      d['status'] == 'done' and d['text'].endswith('Rules: ' + RULE) and RULE not in ask.calls[0][1], d)
VALERICA = ("Valerica is an ancient vampire.\nRoleplay direction: Explicit out-of-character scene direction from the player may "
            "establish a subtle emotional beat. Do not turn a passing feeling into a permanent personality trait.\n"
            "Her development should move toward greater willingness to experience the world.")
SERANA = ("Relationship development: trust grows gradually through their conversations and shared experiences.\n\n"
          "1. Highly guarded: She is cagey about her past.\n\n2. Cautiously warming: Consistent respect makes her less defensive.\n\n"
          "Continuity: Preserve established closeness across conversations. Express progression through dialogue and "
          "behaviour; never announce a stage number or treat the relationship as a score.\n\nStarting point: when Serana first "
          "meets the player they share no history. Talking alone never performs a wedding or any other ritual, and never "
          "completes a quest; do not invent rites or quest outcomes.\n\nSerana is witty.")
SYLGJA = ("The mine was recently infested by deadly frostbite spiders. [Roleplay Instructions: There is a significant possibility "
          "that this spider infestation has already been rectified. Consequently, you should avoid making definitive statements "
          "about the mine's infestation status.]\nShe hums while she works.")
check('rules: lines under a Roleplay heading, and "should" sentences', O.rule_items(VALERICA) == [
    "Roleplay direction: Explicit out-of-character scene direction from the player may establish a subtle emotional beat. Do not turn a passing feeling into a permanent personality trait.",
    "Her development should move toward greater willingness to experience the world."], O.rule_items(VALERICA))
serana = O.rule_items(SERANA)
check('rules: a heading with its numbered stages, continuity and starting point (whole lines)', len(serana) == 5
      and serana[1].startswith('1. Highly guarded') and serana[4].startswith('Starting point:') and 'Serana is witty.' not in serana, serana)
check('rules: the inside of a [Roleplay Instructions: ...] bracket', O.rule_items(SYLGJA) == [
    "There is a significant possibility that this spider infestation has already been rectified. Consequently, you should avoid making definitive statements about the mine's infestation status."],
    O.rule_items(SYLGJA))
check('rules: an emptied bracket head is not left behind', '[Roleplay Instructions' not in O.without_rules(SYLGJA))
check('rules: a line spoken in quotes is never a rule', O.rule_items('She says: "You must always keep the faith. Never give up." She smiles.') == [])
check('rules: a quoted sentence before the rule stays out of it', O.rule_items(
    'She is fierce. "Honor is found in deeds alone." Any closeness with the player develops only through their shared history; it is never assumed.')
    == ['Any closeness with the player develops only through their shared history; it is never assumed.'])
check('rules: ordinary facts with never/always stay facts', O.rule_items(
    'War cost him good friends and left wounds that never healed. He trades in rare artifacts, always for a price.') == [])

# false rejections of the real run
check('race words may go (Faralda "leaves out Elf")', 'Elf' not in O.must_keep('Race: Altmer (High Elf)\nUnlike most Altmer, she has red hair. She studies with a fellow female Altmer named Nirya.', '', 'Faralda'))
check('race words may go (Lyn Lauet "leaves out Breton")', O.must_keep('Lynelle is a young Breton woman who lives with her brother Remy and blames Ashe.', '', 'Lyn Lauet') == ['Remy', 'Ashe'])
check('list numbering is not a number to keep (Serana "leaves out 1, 2, 3, 4, 5")', not any(n in O.must_keep(SERANA + '\n\n3. x.\n\n4. y.\n\n5. z.', '', 'Serana') for n in '12345'))
check('real numbers still kept (ages, prices, dates)', all(any(k.strip(',') == n for k in O.missing('She is 25. Born in 4E 171, she charges 150 gold.', 'Knows: x.', '', 'X')) for n in ('25', '171', '150')))
check('a heading word of the original may go (Sylgja "leaves out Instructions")', 'Instructions' not in O.must_keep(SYLGJA + ' She met Verner in Riften.', '', 'Sylgja'))
GERDUR = ('About Elisif: "I suppose she\'s \'Jarl\' Elisif now. She married High King Torygg. The Empire supports her claim to be High Queen."\n'
          'About the jarl: "Jarl Balgruuf rules well."')
check('a bare title may go when the named person on its line is kept (Gerdur "leaves out Queen")',
      'Queen' not in O.missing(GERDUR, 'Knows: Elisif married Torygg and the Empire backs her; Jarl Balgruuf rules Whiterun.', '', 'Gerdur'))
check('...but not when that person is dropped too', 'Queen' in O.missing(GERDUR, 'Knows: Jarl Balgruuf rules well; Torygg died.', '', 'Gerdur')
      or 'Elisif' in O.missing(GERDUR, 'Knows: Jarl Balgruuf rules well; Torygg died.', '', 'Gerdur'))
check('real names still protected', 'Nirya' in O.missing('She studies with a fellow female Altmer named Nirya.', 'Knows: studies.', '', 'Faralda'))

# voice: quoted lines word for word, enough of them
ELISIF = ('"Ulfric is a fool and a coward who naively believes he can bring about peace through warfare! It\'s rather sad really."\n'
          '"Please direct questions to my steward."\n"Pray for Solitude, and my husband."\n"Keep the faith. General Tullius will win this war."\n'
          '"I may not be the Queen Skyrim asked for, but I must become the Queen she needs."')
check('sample lines needed: at least four when the original has four or more', O.sample_need(ELISIF) == 4 and O.sample_need('"One two three." "Four five six."') == 0)
check('sample lines needed: a third of many', O.sample_need(' '.join(f'"line number {i} here."' for i in range(30))) == 10)
LONG_ELISIF = ELISIF + '\nElisif rules Solitude from the Blue Palace. ' + 'She mourns her husband Torygg and trusts General Tullius. ' * 6
ask = Ask('Voice: x.')
O.optimise_detail(LONG_ELISIF, [], 'Elisif', ask)
check('the prompt asks for that many', 'at least 4 short lines' in ask.calls[0][0], ask.calls[0][0][:400])
three = 'Voice: formal.\nSample lines: "Please direct questions to my steward." / "Pray for Solitude, and my husband." / "Keep the faith. General Tullius will win this war."'
check('three sample lines from a sheet with five fail (Elisif kept 3)', any('sample lines' in b for b in O.problems(LONG_ELISIF, three, '', 'Elisif')[0]))
check('a misquote fails ("fool and coward" for "a fool and a coward")', O.invented_quotes(ELISIF, 'Voice: scorn for Ulfric ("fool and coward").') == ['fool and coward'])
check('an invented sample line fails (Aryo "Live. Experience.")', O.invented_quotes("He told her to 'live' and 'experience'.", 'Sample lines: "Live. Experience."') == ['Live. Experience.'])
check('a quoted line copied exactly passes, also one sentence of it', O.invented_quotes(ELISIF, 'Sample lines: "Pray for Solitude, and my husband." / "Keep the faith."') == [])
check('quoted single words from the sheet pass ("lass")', O.invented_quotes("He calls women 'lass'.", 'Voice: calls women "lass".') == [])
check('the Rules part is not checked as quotes', O.invented_quotes('x', 'Voice: y.\nRules: She says "z".') == [])
# small inventions
ROLEN = ("Rolen Briand is a former Dark Brotherhood assassin who now lives as a woodcutter near the Karth River. He speaks with a "
         "rough, plain manner, calls women 'lass', and believes vengeance only breeds more emptiness.")
check('an added judgement fails (Rolen "haunted")', O.judged(ROLEN, 'Personality: gruff, haunted, plain-dealing.') == ['haunted'])
check('a judgement word the sheet uses passes (Delariel "deadly")', O.judged('She is seductive, mysterious and deadly.', 'Personality: deadly.') == [])
for rule_text in ('no new adjectives, judgements', '"deadly" never becomes "deadly when crossed"', '"Y inspired X" is not "made X"',
                  'a suitor test and the quest given as its example stay together', '"a sword, fond of rapiers" is not "fights with a rapier"',
                  'Keep what a thing does or gives', 'never paraphrase a quoted line', 'never write a line they did not say',
                  'only when the sheet shows them using it that way', 'Do not write a Rules part'):
    check(f'prompt rule: {rule_text}', rule_text in O.PROMPT, rule_text)
check('format version bumped: every stored short bio is redone', O.FORMAT_VERSION >= 2)

FIXTURE = os.environ.get('LW_BIOS_FIXTURE', os.path.join(os.environ.get('MLW_EVIDENCE', ''), r'lw-live-test-5-2026-11-15\bios-before-after.md'))
if os.path.isfile(FIXTURE):
    import re as _re
    pairs = {}
    for sec in _re.split(r'\n## ', open(FIXTURE, encoding='utf-8').read())[1:]:
        head, _, body = sec.partition('\n')
        m = _re.match(r'(.*?) \((\d+) -> (\d+) chars, status (\w+)\)', head)
        before = body.split('**Before**', 1)[1].split('**After**', 1)[0].strip()
        after = body.split('**After**', 1)[1].split('\n---', 1)[0].strip() if '**After**' in body else ''
        pairs[m.group(1)] = (before, after, m.group(4))
    never = [n for n, (b, _, _) in pairs.items() if 'never assumed' in b]
    check(f'real file: every "never assumed" line is a rule ({len(never)} bios)',
          all(any('never assumed' in r for r in O.rule_items(pairs[n][0])) for n in never))
    for n, word in (('Faralda', 'Elf'), ('Lyn Lauet', 'Breton'), ('Sylgja', 'Instructions')):
        check(f'real file: {n} no longer needs "{word}"', word not in O.must_keep(pairs[n][0], '', n))
    check('real file: Serana no longer needs the list numbers', not any(x in O.must_keep(pairs['Serana'][0], '', 'Serana') for x in '12345'))
    flagged = lambda n, text: ' '.join(O.problems(pairs[n][0], pairs[n][1], '', n)[0])
    check('real file: Aela kept too few sample lines', 'sample lines' in flagged('Aela the Huntress', ''))
    check('real file: Elisif kept too few lines and misquoted one', 'sample lines' in flagged('Jarl Elisif the Fair', '') and 'fool and coward' in flagged('Jarl Elisif the Fair', ''))
    check('real file: Senna kept too few sample lines', 'sample lines' in flagged('Senna', ''))
    check('real file: Rolen got "haunted"', 'haunted' in flagged('Rolen Briand', ''))
    check('real file: Aryo got an invented line', 'Live. Experience.' in flagged('Aryo Avellan', ''))
    check('real file: Valerica\'s rules were squeezed', 'rule lines' in flagged('Valerica', ''))
    # bios with a rule or a nickname line (format 3 carries those word for word; the format 2 results reworded them) aside
    clean = [n for n, (b, a, s) in pairs.items() if s == 'done' and not O.rule_items(b) and not O.term_lines(b) and not flagged(n, '')]
    check(f'real file: results with no rule, no nickname line and no problem still pass ({len(clean)})', len(clean) >= 15, clean)
    reworded = [n for n, (b, a, s) in pairs.items() if s == 'done' and O.term_lines(b) and O.terms_missing(b, a)]
    check(f'real file: nickname lines the format 2 results reworded are asked again ({len(reworded)})',
          {'Rolen Briand', 'Thorfinn'} <= set(reworded), reworded)
else:
    print(f'SKIP real file checks: {FIXTURE} not found')

# live test 8: the rule detection, tolerant quote matching and lost-reason check changed but FORMAT_VERSION stayed 3:
# "51 already had a current short bio", nothing was redone. Format 4 redoes every stored entry; the original is sent
# until the new one exists; the opt-out list and the "written into your override file" marks survive; and stored
# entries are checked again (no model call) when the check code changes without a bump.
check('format 4 or later: the live test 8 rule changes redo every stored short bio', O.FORMAT_VERSION >= 4, O.FORMAT_VERSION)
check('the check code has a fingerprint', len(O.CHECKER) == 16, O.CHECKER)
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    path = str(tmp / 'bios.json')
    on = dict(settings.DEFAULTS)
    rows = {O.bio_hash(ORIGINAL, 3): {'name': 'Alvor', 'status': 'done', 'text': GOOD, 'why': '', 'format': 3, 'source': 'button'},
            O.bio_hash(ORIGINAL.replace('Alvor', 'Hod'), 3): {'name': 'Hod', 'status': 'kept', 'text': '', 'why': 'x', 'format': 3},
            O.bio_hash(GOOD, 3): {'name': 'Gerdur', 'status': 'kept', 'text': '', 'format': 3, 'source': O.WRITTEN,
                                  'why': 'already the short bio (written into your override file)'}}
    Path(path).write_text(json.dumps({'version': 1, 'bios': rows, 'use_original': ['lydia']}), encoding='utf-8')
    check('a format 3 short bio is not used: the original is sent, never no bio', O.entry('Alvor', ORIGINAL, path) is None
          and O.used_bio('Alvor', ORIGINAL, on, path) == ORIGINAL)
    check('a format 3 entry is due again (written after the next talk or by the button)', O.due('Alvor', ORIGINAL, on, path))
    check('the opt-out list survives the bump', O.uses_original('Lydia', path) and O.used_bio('Lydia', ORIGINAL, on, path) == ORIGINAL)
    check('an override file already holding its short bio stays marked under the new format (not shortened again)',
          (O.entry('Gerdur', GOOD, path) or {}).get('source') == O.WRITTEN)
    O.remember('Alvor', ORIGINAL, {'status': 'done', 'text': GOOD, 'covered': '\n'.join(O.stable_lines(BACKGROUND))}, path)
    saved = json.loads(Path(path).read_text(encoding='utf-8'))
    check('after a new write: the old format entry is gone, the opt-out and the written mark kept',
          O.bio_hash(ORIGINAL, 3) not in saved['bios'] and O.bio_hash(GOOD, 3) in saved['bios'] and saved['use_original'] == ['lydia'], saved)
    new = saved['bios'][O.bio_hash(ORIGINAL)]
    check('a new entry records the check code and the Background lines it was checked against',
          new['checker'] == O.CHECKER and new['format'] == O.FORMAT_VERSION and '- Race: Nord' in new.get('covered', ''), new)
    check('the short bio is used once written again', O.used_bio('Alvor', ORIGINAL, on, path) == GOOD)

    # the check code changes, the format does not: entries are checked again when read, without a model call
    bad_text = GOOD.replace('Sample lines: "Whatever you need. By Ysmir, if it\'s simple and strong, I can forge it."',
                            'Sample lines: "Whatever you want, friend, I can make it."')
    hod = ORIGINAL.replace('Alvor', 'Hod')
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    data['bios'][O.bio_hash(ORIGINAL)]['checker'] = 'older0check0code'
    data['bios'][O.bio_hash(hod)] = {'name': 'Hod', 'status': 'done', 'text': bad_text.replace('Alvor', 'Hod'), 'why': '',
                                     'format': O.FORMAT_VERSION, 'checker': 'older0check0code', 'source': 'button'}
    aela = ORIGINAL.replace('Alvor', 'Aela')
    data['bios'][O.bio_hash(aela)] = {'name': 'Aela', 'status': 'kept', 'text': '', 'format': O.FORMAT_VERSION, 'checker': 'older0check0code',
                                      'why': O.FAILED_CHECK + ' (it quotes words the sheet does not have word for word: "milk drinkers")'}
    Path(path).write_text(json.dumps(data), encoding='utf-8')
    O._checked.clear()
    check('older check code, still passing: the stored short bio stays in use', O.used_bio('Alvor', ORIGINAL, on, path) == GOOD)
    check('older check code, now failing (an invented quote): the original is sent and it is due again',
          O.entry('Hod', hod, path) is None and O.used_bio('Hod', hod, on, path) == hod and O.due('Hod', hod, on, path))
    check('older check code: a "failed the check" result is asked again (the check may pass it now, as Aela\'s quote)',
          O.entry('Aela', aela, path) is None and O.due('Aela', aela, on, path))
    data['bios'][O.bio_hash(aela)]['checker'] = O.CHECKER
    Path(path).write_text(json.dumps(data), encoding='utf-8')
    check('same check code: a "failed the check" result stands (no new model call)', O.entry('Aela', aela, path) is not None)
    check('the check code fingerprint ignores everything outside the checks (prompt, cache)',
          "def load(" not in open(O.__file__, encoding='utf-8').read().split('\nCOMMON = set(')[1].split('\ndef target_chars(')[0])

REAL8 = os.environ.get('LW_BIOS_TEST8', os.path.join(os.environ.get('MLW_EVIDENCE', ''), r'lw-live-test-8-2026-11-15\test-artifacts\living_world_bios.after.json'))
if os.path.isfile(REAL8):
    real = json.load(open(REAL8, encoding='utf-8'))
    O._cache.update(path=None, stamp=None, data=None)
    stored = O.load(REAL8)['bios']
    check(f'real file (live test 8): none of its {len(real["bios"])} format 3 entries is current under format 4', not stored, len(stored))
else:
    print(f'SKIP live test 8 file: {REAL8} not found')

# live test 9: family and spouse ties are never left out; the fact a rule refers back to goes with it; fewer false refusals
check('format 5 or later: the live test 9 check changes redo every stored short bio', O.FORMAT_VERSION >= 5, O.FORMAT_VERSION)
VAL = ("Valerica is an ancient pure-blooded vampire, a Daughter of Coldharbour, the mother of Serana, and the estranged wife "
       "of Lord Harkon (his widow, if he has since been killed). She is an exceptionally skilled alchemist.")
check('ties found: mother of Serana, estranged wife of Lord Harkon with the widow line, Daughter of Coldharbour',
      [(r, n) for _, r, n, _ in O.relations(VAL)] == [('daughter', ['Coldharbour']), ('mother', ['Serana']), ('wife', ['Harkon'])]
      and O.relations(VAL)[-1][3] == ['estranged', 'widow'], O.relations(VAL))
check('a result naming Harkon and Serana elsewhere but not the ties fails (Valerica)',
      O.relations_missing(VAL, 'History: a Daughter of Coldharbour. Opposed Harkon. Protects Serana.')
      == ['mother of Serana', 'estranged wife of Lord Harkon (and: widow)'], O.relations_missing(VAL, 'History: a Daughter of Coldharbour. Opposed Harkon. Protects Serana.'))
check('the ties kept as the bio says them pass', O.relations_missing(VAL, 'History: a Daughter of Coldharbour, the mother of '
      'Serana, and the estranged wife of Lord Harkon (his widow, if he has since been killed).') == [])
check('"estranged" must stay with the wife tie', O.relations_missing(VAL, 'History: a Daughter of Coldharbour; mother of Serana; '
      'wife of Harkon, his widow if he is killed.') == ['estranged wife of Lord Harkon'])
check('the same tie from the other side, right beside the name, keeps it ("her parents Verner and Annekke")',
      O.relations_missing('Sylgja is the daughter of her father Verner Rock-Chucker and her mother Annekke Crag-Jumper.',
                          'History: her parents Verner Rock-Chucker and Annekke Crag-Jumper live in Darkwater Crossing.') == [])
check('...but not four clauses away ("leaving Serana behind ... her daughter\'s life")', O.relations_missing(
      'She is the mother of Serana.', 'Knows: guilt over leaving Serana behind and over allowing fear to dictate so much of her '
      "daughter's life.") == ['mother of Serana'])
check('"married to" is a tie; "son of a farmer" (no name) is not', [r for _, r, _, _ in O.relations(
      'Hod is married to Gerdur. Frodnar is the son of a farmer.')] == ['married'])
check('a tie inside a spoken line or a rule is not checked', O.relations('"I am the wife of Ulfric," she says.') == [])
check('the problems name a lost tie', any('family or spouse ties' in b for b in O.problems(
      VAL + ' ' + 'x ' * 0, 'History: a Daughter of Coldharbour. Opposed Harkon. Protects Serana.', '', 'Valerica')[0]))
SER = ("From the moment they meet, Serana senses an extraordinary, seemingly divine presence radiating from the player, far "
       "beyond anything she has felt from priests, temples, or sacred relics. She suspects he is much more than he admits "
       "and may describe him as divine, but this is her interpretation of what she feels, not confirmed knowledge of his "
       "true nature. Her initial knowledge does not include his origins. Her knowledge develops through their "
       "conversations and supersede this initial uncertainty.")
ser_rules = O.rule_items(SER)
check('Serana: the sentence "what she feels" refers back to goes into Rules word for word, before it',
      ser_rules[0].startswith('From the moment they meet, Serana senses') and ser_rules[1].startswith('She suspects'), ser_rules)
check('...and a later rule pointing back past other rules finds the same sentence (not carried twice)',
      sum(1 for r in ser_rules if r.startswith('From the moment')) == 1 and len(ser_rules) == 4, ser_rules)
ADR = ("To such a person she drops her shop manner entirely: openly curious and bold. She will not pretend someone is "
       "legendary when they are not. Until she has reason to believe the player is the Dragonborn, they are just another "
       "customer. Whatever grows between them beyond that is her choice; it is never assumed.")
check('a chain of rules ending in "beyond that" carries the fact the chain hangs on, in its place',
      O.rule_items(ADR)[0].startswith('To such a person'), O.rule_items(ADR))
AELA_SHEET = ('Aela is a Companion. She may bring a worthy Companion "into the pack".\n'
              'If asked about a cure: "You\'re sounding like the old man. I\'ll take the glories of the hunt right here."\n'
              'On the war: "Snowberries are out there earning glory while we stay out of it."\n'
              '"You were born into the pack, brother. I almost envy you."')
found = O.explained_terms(AELA_SHEET, 'Voice: blunt. Speaks of "the hunt", "glory", "the pack", and calls Kodlak "the old man".')
check('Aela: plain words a result only lists ("the hunt", "glory") are no term', not ({'the hunt', 'glory'} & set(found)), found)
check('Aela: "the pack" (quoted by the sheet) and "the old man" (named onto Kodlak) are still caught',
      {'the pack', 'the old man'} <= set(found), found)
check('a place word whose name\'s own word is kept is not lost ("River" of "Darkwater River", Darkwater kept)',
      'River' not in O.missing('Her parents live in Darkwater Crossing, beside the Darkwater River to the northwest.',
                               'History: her parents live in Darkwater Crossing.'))
check('...but alone, or after an ordinary word ("the White River"), it still must stay',
      'River' in O.missing('She lives by the White River in Riverwood.', 'History: lives in Riverwood.')
      and 'River' in O.missing('She lives by the River near Riverwood. The River is cold.', 'History: lives in Riverwood.'))

REAL9 = os.environ.get('LW_BIOS_TEST9', os.path.join(os.environ.get('MLW_EVIDENCE', ''), r'lw-live-test-9-2026-11-15'))
if os.path.isfile(os.path.join(REAL9, 'test-artifacts', 'living_world_bios.after.json')):
    after9 = json.load(open(os.path.join(REAL9, 'test-artifacts', 'living_world_bios.after.json'), encoding='utf-8-sig'))['bios']
    by_name = {v['name']: v for v in after9.values()}
    def judged9(name):
        row = by_name[name]
        orig = json.load(open(os.path.join(REAL9, 'character_overrides-before', name + '.json'), encoding='utf-8-sig'))['bio'].strip()
        return O.problems(orig, row['text'] if row['status'] == 'done' else row['tried'], row.get('covered', ''), name)[0]
    val = judged9('Valerica')
    check('real file (live test 9): Valerica\'s short bio now fails on the lost mother and estranged-wife ties',
          any('mother of Serana' in b and 'estranged wife of Lord Harkon' in b for b in val), val)
    ser = judged9('Serana')
    check('real file: Serana\'s short bio now fails (the sentence her rules refer back to was reworded under Knows)',
          any('From the moment they meet' in b for b in ser), ser)
    check('real file: Elisif\'s short bio now fails only for the Embassy line (live test 10: the situation check sees it)',
          [b.startswith('it drops how they react in these situations') for b in judged9('Jarl Elisif the Fair')] == [True]
          and 'If approached at the Thalmor Embassy (surprised)' in judged9('Jarl Elisif the Fair')[0], judged9('Jarl Elisif the Fair'))
    aela = ' '.join(judged9('Aela the Huntress'))
    check('real file: Aela\'s candidate is refused only for "the pack" and "the old man" now, not "the hunt" or "glory"',
          '"the pack"' in aela and '"the old man"' in aela and '"the hunt"' not in aela and '"glory"' not in aela, aela)
    check('real file: Faralda\'s "advisor" is still caught', '"advisor"' in ' '.join(judged9('Faralda')))
    check('real file: Sylgja\'s candidate passes now ("River" of "Darkwater River" was the only refusal)',
          judged9('Sylgja') == [], judged9('Sylgja'))
    O._cache.update(path=None, stamp=None, data=None)
    check('real file: none of its format 4 entries is current under format 5',
          not O.load(os.path.join(REAL9, 'test-artifacts', 'living_world_bios.after.json'))['bios'])
else:
    print(f'SKIP live test 9 files: {REAL9} not found')

# review 2026-11-16: a short bio corrected by hand (or the original kept on purpose) stands until the original changes:
# no re-check, no redo by Optimise all (not even forced), no automatic write over it; the NPC page says so.
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    path = str(tmp / 'bios.json')
    on = dict(settings.DEFAULTS)
    HAND = NO_HADVAR  # would fail the check (Hadvar left out): a hand entry is never checked
    row = O.set_manual('Alvor', ORIGINAL, HAND, path)
    check('hand entry: stored as manual, done, with sizes', row and row['source'] == O.MANUAL and row['status'] == 'done'
          and row['after'] == len(HAND) and row['before'] == len(ORIGINAL.strip()), row)
    check('hand entry: its text is sent', O.used_bio('Alvor', ORIGINAL, on, path) == HAND)
    check('hand entry: not due after a talk', not O.due('Alvor', ORIGINAL, on, path))
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    data['bios'][O.bio_hash(ORIGINAL)]['checker'] = 'older0check0code'
    Path(path).write_text(json.dumps(data), encoding='utf-8')
    O._checked.clear()
    check('hand entry: other check code does not re-check it (still sent although the check would refuse it)',
          O.used_bio('Alvor', ORIGINAL, on, path) == HAND and O.problems(ORIGINAL, HAND)[0])
    check('hand entry: an automatic result for the same original does not replace it',
          O.remember('Alvor', ORIGINAL, {'status': 'done', 'text': GOOD}, path, source='button') is None
          and O.used_bio('Alvor', ORIGINAL, on, path) == HAND)
    folder = tmp / 'character_overrides'
    folder.mkdir()
    (folder / 'Alvor.json').write_text(json.dumps({'name': 'Alvor', 'bio': ORIGINAL}), encoding='utf-8')
    asked = []
    def ask_for(bio, name):
        asked.append(name)
        return Ask(GOOD)
    r = O.optimise_overrides(str(folder), ask_for, lambda row: BACKGROUND, force=True, path=path)
    check('hand entry: a forced Optimise all leaves it alone and counts it as current',
          not asked and r['current'] == 1 and r['after'] == len(HAND) and O.used_bio('Alvor', ORIGINAL, on, path) == HAND, (asked, r))
    page = O.page_view('Alvor', ORIGINAL, on, path)
    check('hand entry: the NPC page shows it as edited by hand', 'edited by hand' in page['status'] and page['short'] == HAND, page)
    # a format bump: the entry is keyed by the old format's hash and still stands
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    rowd = data['bios'].pop(O.bio_hash(ORIGINAL))
    rowd['format'] = O.FORMAT_VERSION - 1
    data['bios'][O.bio_hash(ORIGINAL, O.FORMAT_VERSION - 1)] = rowd
    Path(path).write_text(json.dumps(data), encoding='utf-8')
    check('hand entry: survives a format bump', O.used_bio('Alvor', ORIGINAL, on, path) == HAND and not O.due('Alvor', ORIGINAL, on, path))
    check('hand entry: an automatic write still refuses to replace it after a bump',
          O.remember('Alvor', ORIGINAL, {'status': 'done', 'text': GOOD}, path) is None)
    changed = ORIGINAL + ' He also mends pots.'
    check('hand entry: a changed original is no longer covered (the original is sent and it is due)',
          O.entry('Alvor', changed, path) is None and O.used_bio('Alvor', changed, on, path) == changed and O.due('Alvor', changed, on, path))
    O.remember('Alvor', changed, {'status': 'done', 'text': GOOD}, path)
    check('hand entry: the changed original gets its automatic short bio', O.used_bio('Alvor', changed, on, path) == GOOD)
    # the NPC page's own Optimise again replaces it
    O.remember('Alvor', ORIGINAL, {'status': 'done', 'text': GOOD}, path, source='button', replace_manual=True)
    saved = json.loads(Path(path).read_text(encoding='utf-8'))['bios']
    check('hand entry: the NPC page button replaces it (no hand entry left for that original)',
          O.used_bio('Alvor', ORIGINAL, on, path) == GOOD and not any(v.get('source') == O.MANUAL for v in saved.values()), saved)
    # the original kept on purpose
    O.set_manual('Hod', ORIGINAL.replace('Alvor', 'Hod'), None, path)
    hod = ORIGINAL.replace('Alvor', 'Hod')
    found = O.entry('Hod', hod, path)
    check('kept by hand: the original is sent, not due, page says decided by hand',
          found and found['status'] == 'kept' and O.used_bio('Hod', hod, on, path) == hod and not O.due('Hod', hod, on, path)
          and 'decided by hand' in O.page_view('Hod', hod, on, path)['status'], found)
    O.set_manual('Hod', hod, HAND.replace('Alvor', 'Hod'), path)
    check('hand entry: a second hand decision replaces the first', O.used_bio('Hod', hod, on, path) == HAND.replace('Alvor', 'Hod'))
    check('hand entry: an empty original is refused', O.set_manual('Nobody', '  ', 'x', path) is None)

for word in ('claude', 'anthropic', 'openai', 'chatgpt'):
    check(f'no {word} in the shipped module', word not in (SERVER / 'living_world' / 'bio_optimise.py').read_text(encoding='utf-8').lower())

print(f"\n{len(FAILS)} failure(s)" if FAILS else '\nall passed')
sys.exit(1 if FAILS else 0)
