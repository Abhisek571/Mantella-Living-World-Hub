"""Short bios: each NPC's bio (Mantella's character list, or the user's own override file) rewritten once into one short,
consistent shape that carries only what the Background facts and the Now paragraph do not: who they are as a person,
how they speak, their history, and what they know (secrets, quest hooks, opinions about named people, lore).

    Personality: ...
    Looks: ...
    Voice: ...
    History: ...
    Knows: ...
    Sample lines: "..." / "..."
    Rules: ...

Rules: every instruction in the original about how to play the character (imperatives, "never assumed" lines, "should",
"must not", lines under a heading such as Instructions, Rules, Roleplay, Continuity or Starting point) is copied by this
code, word for word, into a final "Rules:" part. The helper never sees them, so it cannot squeeze or misfile them, and
they do not count against the length.

The original is never changed. The short version is written by one helper call (the summary model, the same call the
Now paragraph uses) after a talk, on the Now paragraph's background worker, and kept per NPC in the user's Mantella
folder (data/Skyrim/living_world_bios.json, never part of the mod), keyed by a hash of the original text and FORMAT_VERSION:
a changed original or a new format writes it again. At prompt time the short version is used in place of the original
when it is current, else the original, unchanged; never waited for, and the same all talk (it takes effect from the
next talk).

Every result is checked without a second model call: the names and numbers of the original that the Background facts
do not cover must still be there (case-insensitive, simple inflection allowed; race and sex words, list numbering,
the original's own heading words and bare titles beside a kept name may go), nothing new may be named, every quoted line
must be in the original word for word, enough sample lines kept, no judgement word the original does not use, every
rule line present verbatim, and it must be shorter, in the labelled shape and not cut off. A failed check is asked again once with what was wrong; failing again,
the original is kept for that NPC and the reason recorded. Short bios are left alone.

The user's override files are sources like any other bio; only the explicit "Write the short bios into my override
files" action rewrites them, after copying them to a dated backup folder next to them."""
import hashlib
import json
import logging
import os
import re
import shutil
import threading
import time

from . import lw_state, preview
from .ui_overrides import user_folder

logger = logging.getLogger('Mantella')

FORMAT_VERSION = 6  # 2: rules carried verbatim, quoted lines checked, more sample lines; 3: lines on how they treat
#                      the player are rules, nickname lines kept word for word, author notes on sample lines kept;
#                      4: instruction lines found that are not word for word a known heading (Serana, Adrianne,
#                      Valerica), tolerant quote matching ("milk drinkers"), the lost-reason check (live test 8: still
#                      at 3, so nothing was redone and these never ran on the stored entries); 5: family and spouse
#                      stated in the bio are never left out ("the mother of Serana": live test 9, Valerica), the
#                      sentence a rule refers back to goes with it ("what she feels": Serana), fewer false refusals of
#                      quoted words and place names (Aela, Sylgja); 6: a carried sentence that starts by pointing
#                      back ("To such a person") takes the sentence it points at with it (live test 10: Adrianne), a
#                      line on how they react in a situation is kept whole (Elisif's surprise at the Embassy). Between
#                      bumps, CHECKER below re-checks stored entries when the check code changes.
PATH = os.path.join(user_folder(), 'data', 'Skyrim', 'living_world_bios.json')
BACKUPS = 'character_overrides_before_short_bios'  # next to the overrides folder (Mantella never loads it)
MIN_CHARS = 600      # shorter bios are left alone: nothing to gain
AIM = 0.5            # the length asked for, as a share of the original...
MAX_SHARE = 0.9      # ...and the most accepted, of its own text: part labels, the rules and the lines it must copy word
#                      for word (nickname lines, the author note, quoted lines it kept) left out on both sides, the
#                      result must be at least 10% shorter (anything longer saves too little and the original is kept)
MIN_AIM = 350
MAX_PER_TALK = 3     # NPCs of one talk queued for a short bio
MAX_ENTRIES = 3000
PARTS = ('Personality', 'Looks', 'Voice', 'History', 'Knows', 'Sample lines', 'Rules')

PROMPT = (
    "You rewrite the character sheet of {name}, a person in Skyrim, into a short sheet with a fixed shape. The background "
    "facts given below are always sent beside it, so leave out only what those facts already say (their race and sex) "
    "unless the sheet adds detail beyond the bare fact; keep everything else, home and work included. Keep every family "
    "tie and spouse the sheet states, with the name and how it stands (\"the mother of Serana\", \"the estranged wife of "
    "Lord Harkon\", \"his widow, if he has since been killed\").\n"
    "Write these parts, each on its own line starting with its label; leave out a part with nothing to say:\n"
    "Personality: temperament, what they value and how it shows, habits and mannerisms.\n"
    "Looks: a few words.\n"
    "Voice: how they speak: tone, favourite words, oaths, accent.\n"
    "History: their past and present life: events, work, skills, relationships to named people.\n"
    "Knows: secrets, quest involvement, opinions about named people and places, lore they hold.\n"
    "Sample lines: {lines}, copied word for word from the sheet, in quotes, separated by \" / \". Pick the lines that "
    "show their voice most: catchphrases, oaths, greetings, put-downs, the lines only this person would say.\n"
    "How to write: third person, present tense, short sentences or phrases. Use only what the sheet says and never add "
    "anything: no new adjectives, judgements, moods or conditions (do not call someone haunted, deadly or tragic unless "
    "the sheet does; \"deadly\" never becomes \"deadly when crossed\"). Never merge two facts into one claim, and keep "
    "every cause and link as the sheet states it (\"Y inspired X\" is not \"made X\"; a suitor test and the quest given "
    "as its example stay together; \"a sword, fond of rapiers\" is not \"fights with a rapier\"). Keep what a thing does "
    "or gives, not only its name. Keep every qualifier, condition and stated reason with the fact it belongs to "
    "(\"merely\", \"if they own one\", \"after grief drove him\", \"because it killed nearly a whole village\" stay). "
    "Copy word for word every sentence that gives a nickname, insult or slang term in quotes, and never restate who or "
    "what a term refers to: a term the sheet only uses inside a spoken line stays inside that line. "
    "A word goes under Voice as a phrase they use only when the sheet shows them using it "
    "that way. Quoted words are always copied exactly from the sheet: never paraphrase a quoted line and never write a "
    "line they did not say. Keep every name, number and concrete detail the background facts do not cover; other "
    "example dialogue becomes the facts, opinions and voice it shows; a line given for a situation (\"If approached at "
    "X:\") keeps how they react there (surprised to see you, suspicious) with the facts it holds. Drop repetition, scene-setting, dialogue of other "
    "people as dialogue, and notes about how to use the sheet. Do not write a Rules part: the sheet's instructions for "
    "playing the character were taken out of it and are added after your parts word for word. Keep words in braces such "
    "as {{player_name}} exactly as written. At most {chars} characters, sample lines included. Answer with the parts "
    "only.\n"
    "Example of the shape (another person):\n"
    "Personality: friendly, nosy, a keen bargain hunter; sharp-tongued with anyone who annoys her.\n"
    "Voice: brisk market talk, proud of Nord grit and her head for business.\n"
    "History: orphaned; learning the merchant's trade at the market stalls; dreams of buying the Bannered Mare from Hulda.\n"
    "Knows: pays 150 gold a bottle for Sleeping Tree sap since her supplier Ulag stopped coming.\n"
    "Sample lines: \"They say there's nothing a Nord woman can't do if she puts her mind to it.\"")
RETRY = "\n\nYour last answer was not usable: {problems}. Write it again, fixing that."

# capitalised words that are not names: pronouns, function words, interjections and the field labels bios use
COMMON = set("""
a an the and or but nor so yet for of in on at to by from with without into onto upon over under about above below
after before during since until while when whenever where wherever why how what which who whom whose that this these
those there here then than as if unless because although though even just only also too very much many more most
some any all each every both either neither no not none nothing never always often sometimes usually rarely perhaps
maybe still already again ever once twice now soon later today tonight tomorrow yesterday i me my mine myself you your
yours yourself yourselves he him his himself she her hers herself it its itself we us our ours ourselves they them their
theirs themselves one ones someone somebody something anyone anybody anything everyone everybody everything nobody
is are was were be been being am do does did done have has had having can could will would shall should may might must
let lets let's yes yeah aye nay ah oh ooh hmm hm huh eh ha haha hehe heh hey well okay ok alright please thanks thank
sorry dear sir madam lady lord friend stranger traveler traveller woman man girl boy child love fine good great right
wrong sure true indeed really course however therefore otherwise besides instead meanwhile moreover furthermore
regarding concerning toward towards against among between through throughout within beyond near like unlike per via
example examples dialogue dialogues conversation conversations speech pattern patterns quote quotes line lines note
notes physical appearance race gender sex age species name names personality keywords traits trait background history
info information typical location locations home occupation job role status marital initial known family members
member relationships relationship likes dislikes quirks skills abilities voice style tone behavior behaviour attitude
goals fears secrets beliefs opinions views outlook demeanor demeanour mannerisms habits life notable facts fact
description summary misc other current present past future young old adult elderly middle aged teen teenage
use inspiration avoid parroting reference fitting when if asked player
first second third last next new old another other same such own
""".split())
PART_WORDS = {w.lower() for p in PARTS for w in p.split()}
# ordinary words often capitalised inside a name ("Five Hundred Companions", "Close Wounds", "Dark Brotherhood", "Master
# Wizard"): not checked on their own, since the name's other word is; after "the" they are a name ("the Eight", "the Pale")
ORDINARY = set("""
one two three four five six seven eight nine ten eleven twelve twenty thirty forty fifty hundred hundreds thousand
thousands million first second third fourth fifth sixth seventh eighth ninth tenth half north south east west
northern southern eastern western black white red blue green gray grey gold golden silver dark light bright great
grand high low little big small long short elder lesser greater upper lower inner outer close open master mistress
hunting potential development combat style trainer specialist tip tips warning important note
""".split())

_WORD = re.compile(r"[A-Za-zÀ-ɏ][A-Za-zÀ-ɏ'’\-]*")
_NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")
_BRACES = re.compile(r"\{[A-Za-z_][\w ]*\}")
_LIST_LABEL = re.compile(r"^\s*[-*•]\s*([A-Z][\w'’\-]*)")
_LINE_LABEL = re.compile(r"^\s*(?:[-*•]\s*)?([^:\n]{1,60}):")
_LIST_NUMBER = re.compile(r"(?m)^\s*\(?\d{1,2}[.)](?=\s)")  # "1. " list numbering, not a number to keep
_BRACKET_HEAD = re.compile(r"\[([^\]:\n]{1,40}):")

# race and sex words may be dropped: the Background facts cover race and sex (and a bio's "(High Elf)" is not a name)
RACE_SEX = set("""
nord nords imperial imperials breton bretons redguard redguards altmer bosmer dunmer orsimer orc orcs orcish khajiit
argonian argonians elf elves elven elvish high-elf wood-elf dark-elf human humans mer male female
""".split())
# a bare title may go when the named person on the same line is kept ("High Queen" beside Elisif)
TITLES = set("""
queen king jarl thane steward housecarl emperor empress prince princess duke duchess count countess baron baroness
harbinger arch-mage archmage general captain commander legate lord lady sir dame priest priestess goddess god
""".split())
# judgement and mood words a short bio may use only when the original does ("haunted" added to a woodcutter)
JUDGEMENT = set("""
haunted tormented tragic deadly dangerous ruthless cruel sinister menacing fearsome brutal bloodthirsty vengeful wicked
evil heroic legendary notorious infamous feared troubled broken lonely
""".split())

# --- rules: instructions for playing the character, carried word for word ---------------------------------------------
_RULE_HEAD = r"(?:instructions?|rules?|role-?play(?:ing)?|continuity|starting point|relationship (?:development|stages?)|ooc)"
_RULE_LINE = re.compile(rf"^\s*(?:[-*•]\s*)?(?:[\w'’]+\s+){{0,3}}{_RULE_HEAD}\b[^:\n]{{0,30}}:", re.I)
_RULE_BRACKET = re.compile(rf"\[\s*(?:[\w'’]+\s+){{0,3}}{_RULE_HEAD}\b[^:\]\n]{{0,30}}:\s*([^\]\n]*)\]?", re.I)
_LIST_ITEM = re.compile(r"^\s*(?:\(?\d{1,2}[.)]|[-*•])\s")
_IMPERATIVE = re.compile(r"^\W*(?:do not|don't|don’t|never|always|avoid|distinguish|express|preserve|allow|treat|"
                         r"remember|make sure|portray|respond)\b", re.I)
_RULE_WORDS = re.compile(r"\bnever assumed\b|\brather than assumption\b|\bshould\b|\bmust (?:not|never|always)\b|"
                         r"\byou must\b|[;:]\s*(?:do not|don't|don’t|never|always)\s+[a-z]", re.I)
# a sentence on how they treat the player is a rule too ("Owes the player nothing on first meeting", "treats the player
# as a travelling companion"): the player (or {player_name}, the Dragonborn, you) with a word of obligation or attitude
_PLAYER = re.compile(r"\b(?:the player|the dragonborn)\b|\{player_name\}", re.I)
_YOU = re.compile(r"\b(?:you|your)\b", re.I)  # second person counts outside a dialogue line ("Farkas: ...") only
_SPEAKER = re.compile(r"^\s*[A-Z][\w'’ .-]{0,40}:\s")
_ATTITUDE = re.compile(r"\b(?:owes?|owed|trusts?|distrusts?|treats?|judges?|respects?|obeys?|worships?|wary|loyal|"
                       r"refuses?|expects?|demands?|resents?|forgives?|admits?|admitting|acts? on)\b", re.I)
# sentences that bound what they know or how they behave toward the player (live test 7: Serana's "this is her
# interpretation ... not confirmed knowledge", "Her initial knowledge does not include", "supersede this initial
# uncertainty", "does not constantly bring up his aura"; Adrianne's "will not pretend someone is legendary", "Until she
# has reason to believe the player is the Dragonborn ..., they are just another customer")
_RULE_CUES = re.compile(r"\binterpretation\b|\bnot confirmed\b|\b(?:initial|her|his|their) knowledge\b|\bsupersedes?\b|"
                        r"\boverrides?\b|\bdoes not (?:constantly|automatically)\b|\bnot simply from\b|\bwill not pretend\b|"
                        r"\bjust another (?:customer|stranger|traveller|traveler)\b|"
                        r"\buntil (?:she|he|they) (?:is|are|has|have|knows?)\b|\bretains? (?:her|his|their)\b[^.]*\bboundaries\b",
                        re.I)
# a rule sentence that points back at the sentence before it ("beyond that", "this initial uncertainty", "does not
# admit it"): that sentence is carried with it, or the rule points at nothing
_BACKREF = re.compile(r"\bbeyond (?:that|this)\b|\bthis (?:\w+ )?(?:uncertainty|mystery|interpretation|knowledge|desire|"
                      r"feeling|belief|doubt|secret)\b|\b(?:admit|act on|hides?|shows?|reveals?|mentions?) it\b|\buntil then\b|"
                      r"\bwhat (?:she|he|they) (?:feels?|felt|senses?|sensed)\b",  # Serana: "her interpretation of what she feels"
                      re.I)
# a sentence that starts by pointing back ("To such a person she drops her shop manner"): carried as a rule, the sentence
# before it goes too, word for word, or "such a person" points at nothing (live test 10: Adrianne lost "stirs her like
# nothing else")
_LEAD_BACKREF = re.compile(r"^\W*(?:to such (?:a|an) \w+|such (?:a|an)\b|that kind of\b|in that case\b|then\b)", re.I)
_QUOTED = re.compile(r'"([^"\n]+)"|“([^”\n]+)”')
_NOTE = re.compile(r"\[[^\]\n]*\b(?:inspiration|parrot\w*|reference)\b[^\]\n]*\]", re.I)  # "[use as inspiration but avoid parroting]"
_TERM = re.compile(r'"([^"\n]{1,40})"|“([^”\n]{1,40})”|' r"(?<![\w’'])'([^'\n]{1,40})'(?![\w’])")
_NAMING = re.compile(r"\b(?:call|calls|called|calling|nicknamed?|known as|named|dubbed|insults?|slang|term|refers? to|"
                     r"means)\b", re.I)


def _mask_quotes(line: str) -> str:
    """The line with everything inside double quotes (and the quotes) blanked, same length: what the person says is
    never an instruction, and a full stop inside a quote does not end a sentence. An unclosed quote runs to the end."""
    out, inside = [], False
    for i, ch in enumerate(line):
        if ch == '"' or ch in '“”':
            closing = inside if ch == '"' else ch == '”'
            inside = not inside if ch == '"' else ch == '“'
            out.append('.' if closing and i and line[i - 1] in '.!?' else ' ')  # a quoted sentence ends there
        else:
            out.append(' ' if inside else ch)
    return ''.join(out)


def _sentence_spans(masked: str, line: str):
    spans, start = [], 0
    for m in re.finditer(r"[.!?]+(?=\s|$)", masked):
        if len(line[start:m.end()].strip()) <= 3:  # "1." or "U." is not a sentence of its own
            continue
        spans.append((start, m.end()))
        start = m.end()
    if masked[start:].strip():
        spans.append((start, len(masked)))
    return spans


def _is_rule(bare: str, player) -> bool:
    """A sentence (quotes blanked) that directs how to play the character."""
    return bool(_IMPERATIVE.match(bare) or _RULE_WORDS.search(bare) or _RULE_CUES.search(bare)
                or ((_PLAYER.search(bare) or (player and player.search(bare))) and _ATTITUDE.search(bare)))


def rule_items(original: str) -> list[str]:
    """The instructions in a bio for how to play the character, word for word, in order: whole lines under a rule
    heading (Instructions, Rules, Roleplay, Continuity, Starting point, Relationship development) with the numbered
    lines after them, the inside of a [Roleplay Instructions: ...] bracket, and sentences outside quotes that direct
    (an imperative, "should", "must not", "; do not ...", "never assumed")."""
    items, block = [], False
    for line in (original or '').splitlines():
        text = line.strip()
        if not text:
            continue  # a blank line keeps a heading's numbered list going
        if _RULE_LINE.match(text):
            items.append(text)
            block = True
            continue
        if block and _LIST_ITEM.match(text):
            items.append(text)
            continue
        block = False
        masked = _mask_quotes(line)
        player = _YOU if not _SPEAKER.match(line) else None
        for m in _RULE_BRACKET.finditer(line):
            inner = m.group(1).strip()
            if inner:
                items.append(inner)
            masked = masked[:m.start()] + ' ' * (m.end() - m.start()) + masked[m.end():]
        spans = _sentence_spans(masked, line)
        ruled = [bool(line[a:b].strip()) and _is_rule(masked[a:b], player) for a, b in spans]
        for k, (start, end) in enumerate(spans):
            sentence, bare = line[start:end].strip(), masked[start:end]
            if ruled[k]:
                carry = []
                if k and _BACKREF.search(bare):  # the sentence it points back at goes with it, word for word
                    j = k - 1
                    while j and ruled[j]:  # past the rule sentences before it, to the fact they all hang on
                        j -= 1
                    carry.append(j)
                first = carry[0] if carry else k
                while first and _LEAD_BACKREF.match(masked[spans[first][0]:spans[first][1]]):  # "To such a person ..."
                    first -= 1
                    carry.insert(0, first)
                for j in reversed(carry):
                    before = line[spans[j][0]:spans[j][1]].strip()
                    if before and before not in items:
                        run = [line[a:b].strip() for a, b in spans[j + 1:k]]
                        at = next((items.index(r) for r in run if r in items), len(items))
                        items.insert(at, before)
                items.append(sentence)
    return list(dict.fromkeys(items))


def without_rules(original: str, rules=None) -> str:
    """The bio with its rule items taken out: what the helper rewrites."""
    text = str(original or '')
    for item in (rule_items(text) if rules is None else rules):
        text = text.replace(item, '', 1)
    text = re.sub(r"\[[^\]\n]{0,40}:\s*\]", '', text)  # an emptied [Roleplay Instructions: ] bracket
    text = '\n'.join(line.rstrip() for line in text.splitlines())
    return re.sub(r"\n{3,}", '\n\n', text).strip()


def _flat(text: str) -> str:
    text = str(text or '').lower().replace('’', "'").replace('‘', "'").replace('“', '"').replace('”', '"').replace('…', '...')
    return ' '.join(text.split())


def quoted(text: str) -> list[str]:
    return [(a or b).strip() for a, b in _QUOTED.findall(text or '') if (a or b).strip()]


def _terms(text: str) -> list[str]:
    """Short quoted words (one to three), in double, curly or single quotes."""
    out = []
    for m in _TERM.finditer(text or ''):
        term = next(g for g in m.groups() if g is not None).strip()
        if term and len(term.split()) <= 3:
            out.append(term)
    return out


NAMING_REACH = 40  # characters before a quoted term in which the naming word must stand


def term_lines(original: str) -> list[str]:
    """Sentences of the bio that give a nickname, insult or slang term in quotes ("some call her \"Sanguine's girl\""):
    carried word for word, so who a term is for can never be turned around."""
    out = []
    for line in (original or '').splitlines():
        spans = _sentence_spans(_mask_quotes(line), line)
        for m in _TERM.finditer(line):
            term = next(g for g in m.groups() if g is not None).strip()
            # the naming word stands just before the term ("calls women 'lass'", "the nickname \"Warmaiden\""), not
            # anywhere in a long sentence ("was named Thane ... the shout of \"Dovahkiin!\"")
            if not term or len(term.split()) > 3 or not _NAMING.search(line[max(0, m.start() - NAMING_REACH):m.start()]):
                continue
            span = next(((a, b) for a, b in spans if a <= m.start() < b), None)
            if span:
                out.append(line[span[0]:span[1]].strip())
    return list(dict.fromkeys(out))


def terms_missing(original: str, result: str) -> list[str]:
    have = _flat(result)
    return [t for t in term_lines(original) if _flat(t) not in have]


def explained_terms(original: str, result: str) -> list[str]:
    """Quoted terms the result attaches to someone outside its sample lines while the bio only uses them inside a spoken
    line (live test 6: "calls those who sit out the war 'snowberries'", where the bio's line says the snowberries are
    the ones out earning glory). Fine when that spoken line is kept word for word among the sample lines."""
    defined = {_flat(t) for line in term_lines(original) for t in _terms(line)}
    samples = _flat(' '.join(l for l in (result or '').splitlines() if re.match(r"\s*Sample lines\s*:", l, re.I)))
    spoken = [_flat(q) for q in quoted(original) if len(q.split()) > 3]
    spoken += [_flat(l.split(':', 1)[1]) for l in (original or '').splitlines() if re.match(r"\s*[A-Z][\w' ]{0,40}:\s*\S", l)]
    # a term counts when the sheet itself puts it in quotes (Faralda's 'advisor', Aela's "into the pack") or the result
    # names someone or something with it ("calls Kodlak \"the old man\""); a plain word from a spoken line that the
    # result only lists ("speaks of \"the hunt\", \"glory\"": live test 9) says who it is for no more than the line does
    marked = [_flat(t).strip(' .,!?') for t in _terms(original)]
    out = []
    for line in _body(result).splitlines():
        if re.match(r"\s*Sample lines\s*:", line, re.I):
            continue
        last, naming = 0, False
        for m in _TERM.finditer(line):
            term = next(g for g in m.groups() if g is not None).strip()
            clause, last = line[last:m.start()], m.end()
            # a list of terms after one naming word ("Calls the unproven "milk drinker", "snowberries"": live test 11,
            # Aela): the word names each of them
            naming = bool(_NAMING.search(re.split(r"[.!?;]\s", clause)[-1][-NAMING_REACH:])) or (
                naming and not re.sub(r"\b(?:and|or)\b|[\s,/'\"“”]", '', clause))
            if not term or len(term.split()) > 3:
                continue
            t = _flat(term).strip(' .,!?')
            if not t or t in defined or _filler(t):
                continue
            said = [s for s in spoken if re.search(rf"(?<!\w){re.escape(t)}(?!\w)", s)]
            if not said or any(s.strip(' "') in samples for s in said):
                continue
            if naming or any(re.search(rf"(?<!\w){re.escape(t)}(?!\w)", q) for q in marked):
                out.append(term)
    return list(dict.fromkeys(out))


# a phrase of only these words is how someone talks ("I suppose", "by the gods"), not a name, title or thing the result
# could attach to the wrong person: the "term only in a spoken line" check is for nouns, names and titles
_FILLER_WORDS = set("""
i i'm i'd i'll me my mine we us our you your he him his she her they them their it it's its one suppose supposed guess
think know mean see say said well oh ah aye nay hmm huh indeed course of the a an by gods divines please thanks thank
really perhaps maybe just so yes no not now then here there sure right
""".split())


def _filler(term: str) -> bool:
    words = [w for w in re.findall(r"[a-z']+", _flat(term)) if w.strip("'")]
    return bool(words) and all(w in _FILLER_WORDS for w in words)


def author_note(original: str) -> str:
    """The bio's note on its sample lines ("[use as inspiration but avoid parroting]"), '' when it has none."""
    found = _NOTE.search(original or '')
    return found.group(0) if found else ''


def with_note(result: str, note: str) -> str:
    """The note kept with the Sample lines part it belongs to."""
    if not note or _flat(note) in _flat(result):
        return result
    return re.sub(r"(?im)^(\s*Sample lines\s*:)\s*", lambda m: f"{m.group(1)} {note} ", result, count=1)


def sample_need(original: str) -> int:
    """How many of the character's own lines the short bio must keep: none required under four, else at least a third
    of them and never fewer than four."""
    count = len([q for q in quoted(original) if len(q.split()) >= 3])
    return 0 if count < 4 else min(count, max(4, -(-count // 3)))


def _body(result: str) -> str:
    """The parts the helper wrote: the result without its Rules lines."""
    return '\n'.join(l for l in (result or '').splitlines() if not re.match(r"\s*Rules\s*:", l, re.I)).strip()


_QUOTE_WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)*")


def _quote_words(text: str) -> str:
    """The words of a text for comparing quotes: lower case, punctuation and quote style dropped, a plural taken as its
    singular ("milk drinkers" is the original's "milk drinker"), as one space-separated string with a space each side."""
    out = []
    for w in _QUOTE_WORD.findall(_flat(text)):
        w = w[:-2] if w.endswith("'s") else w
        if len(w) > 3 and w.endswith('s') and not w.endswith(('ss', 'us', 'is')):
            w = w[:-1]
        out.append(w)
    return ' ' + ' '.join(out) + ' '


def invented_quotes(original: str, result: str) -> list[str]:
    """Quoted words in the result that the original does not have word for word (a paraphrased or invented line).
    Plural or singular, punctuation, quote style and capitals do not count; every word must be there, in order."""
    source = _quote_words(original)
    out = []
    for q in quoted(_body(result)):
        for part in re.split(r"\.\.\.|…", q):
            core = _quote_words(part)
            if core.strip() and core not in source:
                out.append(q)
                break
    return out


def sample_count(result: str) -> int:
    return sum(len(quoted(l)) for l in (result or '').splitlines() if re.match(r"\s*Sample lines\s*:", l, re.I))


def judged(original: str, result: str) -> list[str]:
    known = _word_set(original)
    words = dict.fromkeys(_norm_word(m.group(0)) for m in _WORD.finditer(_body(result)))
    return [w for w in words if w in JUDGEMENT and not _has(known, w)]


_REASON = re.compile(r"\b(?:because|since|after|so that|due to|as a result of|which is why)\b(?! (?:then|that|which|this|all)\b)",
                     re.I)  # "since then", "after that": time, no reason
REASON_FACT_SHARE = 0.6    # this share of a fact's own words in one sentence of the result: the fact was kept
REASON_WORDS_SHARE = 0.5   # this share of the reason's own words on the same line of the result: the reason was kept
REASON_ANYWHERE = 0.7      # ...or this share of them anywhere in the result (said in another part)
_SINCE_CAUSE = re.compile(r"\s+(?:she|he|they|it|i|we|you)\b", re.I)  # "Since he lost it, ...": a cause; "Since her ascension": time


def _own_words(text: str) -> list[str]:
    return [w for w in _word_set(text) if len(w) >= 4 and w not in COMMON and w not in ORDINARY]


def _reasons(rest: str, name: str = '') -> list[tuple[str, list[str], list[str]]]:
    """(sentence, its fact's own words, its reason's own words) for each sentence of the bio (outside quotes) that ties
    a fact to a reason: "alert to coercion because of her slaver past", "After Rebecca died ..., grief drove him"."""
    out = []
    for line in (rest or '').splitlines():
        masked = _mask_quotes(line)
        for start, end in _sentence_spans(masked, line):
            bare = masked[start:end]
            m = _REASON.search(bare)
            if not m:
                continue
            if not bare[:m.start()].strip(' ,;:-—–'):  # the reason first: "After X, Y" / "Because X, Y"
                comma = bare.find(',', m.end())
                if comma < 0 or (m.group(0).lower() == 'since' and not _SINCE_CAUSE.match(bare[m.end():])):
                    continue  # "Since her ascension, ...": time, no reason
                reason, fact = bare[m.end():comma], bare[comma + 1:]
            else:
                fact, reason = bare[:m.start()], bare[m.end():]
            own = _word_set(name)  # their own name says nothing about why
            fact_words = [w for w in _own_words(fact) if w not in own]
            reason_words = [w for w in _own_words(reason) if w not in own]
            if len(fact_words) >= 2 and reason_words:
                out.append((line[start:end].strip(), fact_words, reason_words))
    return out


def lost_reasons(original: str, result: str, name: str = '') -> list[str]:
    """Sentences of the bio whose fact the result keeps without the reason the bio gives for it in the same sentence
    (live test 7: kept "alert to coercion", dropped "because of a slaver past"). The reason counts as kept when the
    result's sentence with the fact says why (because, since, after, ...) or its line carries most of the reason's words."""
    lines = [l for l in _body(result).splitlines() if l.strip() and not re.match(r"\s*Sample lines\s*:", l, re.I)]
    sentences = []
    for line in lines:
        masked = _mask_quotes(line)
        sentences += [(line[a:b], _word_set(line[a:b]), _word_set(line)) for a, b in _sentence_spans(masked, line)]
    everywhere = _word_set(' '.join(lines))
    out = []
    for sentence, fact_words, reason_words in _reasons(without_rules(original), name):
        holders = [(text, words, line_words) for text, words, line_words in sentences
                   if sum(1 for w in fact_words if _has(words, w)) >= REASON_FACT_SHARE * len(fact_words)]
        if not holders:
            continue  # the fact itself was left out: no reason to keep
        share = lambda words: sum(1 for w in reason_words if _has(words, w)) / len(reason_words)
        if not (any(_REASON.search(text) or share(line_words) >= REASON_WORDS_SHARE for text, words, line_words in holders)
                or share(everywhere) >= REASON_ANYWHERE):
            out.append(sentence)
    return out


# family and spouse ties the bio states are never left out (live test 9: Valerica lost "the mother of Serana, and the
# estranged wife of Lord Harkon (his widow, if he has since been killed)"; Background states a tie only when the game's
# ties data lists it, never an estranged or dead spouse or a mod-added character's family)
_RELATION = re.compile(r"\b(mother|father|daughter|son|sister|brother|wife|husband|widow|widower|lover|betrothed|married)"
                       r"\s+(?:of|to)\s+", re.I)
RELATION_WORDS = {'mother', 'father', 'daughter', 'son', 'sister', 'brother', 'wife', 'husband', 'widow', 'widower',
                  'lover', 'betrothed', 'married', 'estranged'}
_TIE_GLUE = {'and', 'the', 'her', 'his', 'their', 'its', 'late', 'own'}


# the same tie seen from the other side, or said another way, keeps it when it stands right beside the name ("her
# parents Verner Rock-Chucker and Annekke" for "the daughter of Verner Rock-Chucker and Annekke", "Serana, her daughter"
# for "the mother of Serana"); "her daughter's life" four clauses away from "Serana" does not
SAME_TIE_REACH = 3  # words between that word and the first name
_SAME_TIE = {
    'mother': {'mother', 'father', 'parent', 'daughter', 'son', 'child'},
    'father': {'mother', 'father', 'parent', 'daughter', 'son', 'child'},
    'daughter': {'daughter', 'son', 'child', 'parent', 'mother', 'father'},
    'son': {'daughter', 'son', 'child', 'parent', 'mother', 'father'},
    'sister': {'sister', 'brother', 'sibling', 'twin'},
    'brother': {'sister', 'brother', 'sibling', 'twin'},
    'wife': {'wife', 'husband', 'spouse', 'married'},
    'husband': {'wife', 'husband', 'spouse', 'married'},
    'married': {'wife', 'husband', 'spouse', 'married'},
    'widow': {'widow', 'widower', 'widowed'},
    'widower': {'widow', 'widower', 'widowed'},
}


def _tied_names(after: str) -> tuple[list[str], int]:
    """The names right after "mother of" and where they end: capitalised words, past titles, "and", "her father" and
    the like, up to the first other lowercase word or punctuation ("Lord Harkon and Valerica" -> Harkon, Valerica)."""
    names, end = [], 0
    for m in re.finditer(r"[^\s,.;:()!?\[\]]+|[,.;:()!?\[\]]", after[:160]):
        word = m.group(0)
        low = _norm_word(word)
        if not low or not word[0].isalpha():
            break
        if word[0].isupper():
            if low not in TITLES and low not in COMMON and low not in ORDINARY:
                names.append(word)
        elif low not in _TIE_GLUE and low not in RELATION_WORDS and low not in TITLES:
            break
        end = m.end()
    return names, end


def relations(original: str) -> list[tuple[str, str, list[str], list[str]]]:
    """(the tie as the bio says it, relation word, its names, relation words that must stay with it) for each "mother of
    X", "estranged wife of Lord Y", "married to Z" outside quotes and rules: what the result must keep. The other
    relation words of that sentence ("his widow, if he has since been killed") go with its last tie."""
    out = []
    for line in without_rules(original).splitlines():
        masked = _mask_quotes(line)
        for start, end in _sentence_spans(masked, line):
            bare = masked[start:end]
            ties, spans = [], []
            for m in _RELATION.finditer(bare):
                names, stop = _tied_names(bare[m.end():])
                if names:
                    ties.append((bare[m.start():m.end() + stop].strip(), m.group(1).lower(), names,
                                 'estranged' in bare[max(0, m.start() - 12):m.start()].lower()))
                    spans.append((m.start(), m.end() + stop))
            if not ties:
                continue
            rest = ''.join(' ' if any(a <= i < b for a, b in spans) else ch for i, ch in enumerate(bare))
            others = [w for w in dict.fromkeys(_norm_word(x) for x in _WORD.findall(rest)) if w in RELATION_WORDS]
            for k, (said, rel, names, estranged) in enumerate(ties):
                tied = ['estranged'] if estranged else []
                more = [w for w in others if w not in tied] if k == len(ties) - 1 else []
                out.append((('estranged ' if estranged else '') + said, rel, names, tied + more))
    return out


def relations_missing(original: str, result: str) -> list[str]:
    """Ties of the bio the result does not keep: some sentence of the result must hold the relation (or the same tie
    from the other side) with all its names, and "estranged" when the bio says so there; the other relation words of
    the bio's sentence ("his widow") must be in the result somewhere."""
    sentences = []
    for line in (result or '').splitlines():
        for a, b in _sentence_spans(_mask_quotes(line), line):
            sentences.append((_word_set(line[a:b]), [_norm_word(w) for w in _WORD.findall(line[a:b])]))
    everywhere = _word_set(result)

    def beside(tokens, words, name):
        at = [i for i, t in enumerate(tokens) if _same_word(t, _norm_word(name)) or t == _norm_word(name)]
        near = [i for i, t in enumerate(tokens) if any(t == w or _same_word(t, w) for w in words)]
        return any(abs(i - j) <= SAME_TIE_REACH + 1 for i in at for j in near)

    out = []
    for said, rel, names, others in relations(original):
        same = _SAME_TIE.get(rel, {rel}) - {rel}
        kept = any(all(_has(words, n) for n in names) and ('estranged' not in others or _has(words, 'estranged'))
                   and (_has(words, rel) or beside(tokens, same, names[0])) for words, tokens in sentences)
        lost = [w for w in others if w != 'estranged' and not _has(everywhere, w)]
        if not kept or lost:
            out.append(said + (f" (and: {', '.join(lost)})" if lost else ''))
    return list(dict.fromkeys(out))


# a line on how they react in a situation ("If approached at the Thalmor Embassy: "I admit, I'm surprised to see you
# here ..."") keeps the situation and the reaction together: the situation's names (or most of its words) and a reaction
# word of the line in one sentence of the result (live tests 8 to 10: Elisif's surprise at the Embassy dropped every run)
_SITUATION = re.compile(r"^\W*(?:if (?:asked|approached|greeted|met|visited|spoken to|the player|you|\{player_name\})\b|"
                        r"when (?:at|in|approached|asked|greeted|meeting|seeing|the player|you)\b|at the (?-i:[A-Z])|"
                        r"upon (?:seeing|meeting|being)\b|on (?:seeing|meeting)\b)", re.I)
REACTIONS = ('surprised', 'shocked', 'startled', 'astonished', 'amazed', 'suspicious', 'wary', 'distrustful', 'angry',
             'furious', 'annoyed', 'irritated', 'delighted', 'glad', 'nervous', 'frightened', 'embarrassed', 'flustered',
             'amused', 'curious', 'grateful', 'relieved', 'hostile', 'impressed', 'disappointed', 'offended', 'jealous',
             'shy', 'excited', 'uneasy', 'worried')  # not "afraid": "I'm afraid the Temple isn't taking students" (Senna)
_SITUATION_WORDS = {'asked', 'approached', 'greeted', 'visited', 'spoken', 'player', 'seeing', 'meeting', 'being', 'when'}
# the reaction is their own: "I'm surprised" in their line, "she is surprised" outside it; never another's ("don't put on
# that angry look", "he's worried", "they're too afraid" in a line are no reaction of theirs)
_DEGREE = r"(?:(?:so|very|a bit|a little|quite|rather|really|truly|more than a little) )?"
_OWN_REACTION = re.compile(rf"\bI(?:'m|’m| am| was| feel| felt) {_DEGREE}([a-z]+)\b", re.I)
_TOLD_REACTION = re.compile(rf"\b(?:she|he|they)(?:'s|’s| is| are| was| were| seems?| looks?| feels?| becomes?| grows?| gets?) "
                            rf"{_DEGREE}([a-z]+)\b", re.I)


def _reaction_in(words, reaction: str) -> bool:
    """A reaction word in a set of words, with its inflections only ("surprise", "surprising" for "surprised"; "host" is
    no "hostile")."""
    stem = reaction[:-2]
    return reaction in words or (len(stem) >= 5 and any(w.startswith(stem) and abs(len(w) - len(reaction)) <= 3 for w in words))


def situations(original: str) -> list[tuple[str, list[str], int, list[str]]]:
    """(situation, the words that must come with it, how many of them, its reaction words) for each sentence of the bio
    (rules left out: they are carried word for word) that starts with a situation and says how they react there."""
    out = []
    for line in without_rules(original).splitlines():
        masked = _mask_quotes(line)
        for start, end in _sentence_spans(masked, line):
            bare = masked[start:end]
            if not _SITUATION.match(bare):
                continue
            cut = next((i for i in (bare.find(':'), bare.find(',')) if i > 0), -1)
            if cut < 0:
                continue
            situation, rest = line[start:start + cut].strip(), line[start + cut + 1:end]
            said = ' '.join(quoted(rest))
            told = _mask_quotes(rest)
            found = {w.lower() for w in _OWN_REACTION.findall(said) + _TOLD_REACTION.findall(told)}
            reaction = [r for r in REACTIONS if _reaction_in(found, r)]
            if not reaction:
                continue
            names = list(dict.fromkeys(w for w, mid, _ in _caps(situation)[0] if mid))  # names, not the opener
            if names:
                out.append((situation, names, len(names), reaction))
                continue
            own = [w for w in _own_words(situation) if w not in _SITUATION_WORDS]
            if own:
                out.append((situation, own, -(-len(own) // 2), reaction))
    return out


def situations_missing(original: str, result: str) -> list[str]:
    sentences = [_word_set(t) for t in re.split(r"(?<=[.!?;])\s+|\n", result or '') if t.strip()]
    out = []
    for situation, words, need, reaction in situations(original):
        if not any(sum(1 for w in words if _has(have, w)) >= need and any(_reaction_in(have, r) for r in reaction) for have in sentences):
            out.append(f"{situation} ({' or '.join(reaction[:2])})")
    return out


def placeholders_added(original: str, result: str) -> list[str]:
    """{placeholders} the result has and the original does not (live test 11: Lydia and Lily got {player_name} where the
    bio said "the player", once with broken grammar)."""
    have = set(_BRACES.findall(original or ''))
    return [p for p in dict.fromkeys(_BRACES.findall(result or '')) if p not in have]


# a fact the bio gives only as rumour ("rumours tell of a tall red woman living in the old Alchemist's Shack") stays a
# rumour: a sentence of the result with two or more words found only in such a sentence of the bio carries a hedge too
# (live test 11: Zeljka's "Looks: tall, red")
_HEDGE = re.compile(r"\b(?:rumou?r(?:s|ed)?|said to|some say|supposedly|allegedly|reportedly|it is said|legend has it)\b", re.I)


def hedges_lost(original: str, result: str) -> list[str]:
    hedged, plain = [], []
    for line in without_rules(original).splitlines():
        masked = _mask_quotes(line)
        for a, b in _sentence_spans(masked, line):  # by clause: "...secluded places; rumours tell of a tall red woman"
            for clause in re.split(r";\s*|,\s+(?:and|but|though|while)\s+", line[a:b]):
                (hedged if _HEDGE.search(clause) else plain).append(clause)
    if not hedged:
        return []
    elsewhere = _word_set(' '.join(plain))
    out = []
    for sentence in hedged:
        only = {w for w in _word_set(sentence) if w not in COMMON and len(w) >= 3 and not _HEDGE.fullmatch(w)
                and not _has(elsewhere, w)}
        for text in re.split(r"(?<=[.!?;])\s+|\n", _body(result)):
            if not _HEDGE.search(text) and sum(1 for w in only if w in _word_set(text)) >= 2:
                out.append(sentence.strip())
                break
    return out


def rules_missing(original: str, result: str) -> list[str]:
    have = ' '.join((result or '').split())
    return [r for r in rule_items(original) if ' '.join(r.split()) not in have]


def with_rules(parts: str, rules) -> str:
    """The helper's parts (any Rules part it wrote anyway dropped) and the original's rules, word for word."""
    body = _body(parts)
    return body + ('\nRules: ' + ' '.join(rules) if rules else '')

_lock = threading.RLock()
_cache = {'path': None, 'stamp': None, 'data': None}
_tried: set = set()       # (hash) asked this session without a usable answer: not asked again until a restart
helper = {'summaries': None, 'config': None}  # set by the hooks: Mantella's summary object, its config


# --- what must be kept --------------------------------------------------------------------------------------------------

def _norm_word(word: str) -> str:
    w = word.lower().replace('’', "'")
    for tail in ("'s", "'"):
        if w.endswith(tail):
            w = w[:-len(tail)]
    return w.strip("-'")


def _same_word(a: str, b: str) -> bool:
    """The same word, allowing simple inflection: Nord / Nords, Imperial / Imperials, Cyrodiil / Cyrodilic."""
    if a == b:
        return True
    short = min(len(a), len(b))
    if short < 4:
        return False
    shared = 0
    for x, y in zip(a, b):
        if x != y:
            break
        shared += 1
    return shared >= 4 and shared >= max(len(a), len(b)) - 3


def _word_set(text: str) -> set[str]:
    out = set()
    for m in _WORD.finditer(text or ''):
        w = _norm_word(m.group(0))
        if w:
            out.add(w)
            out.update(p for p in w.split('-') if p)
    return out


def _has(words: set[str], word: str) -> bool:
    w = _norm_word(word)
    return w in words or any(_same_word(w, x) for x in words)


def _caps(text: str):
    """(word, mid) for each capitalised word: mid when it sits inside a sentence (after a word or a comma), which makes it
    a name rather than a sentence opener. Words of a short label at the start of a line ("Physical Appearance:") count as
    openers; the name of a list item ("- Hadvar: his nephew") counts as a name."""
    out, listed = [], set()
    for line in (text or '').splitlines():
        found = _LIST_LABEL.match(line)
        if found and len(line) > found.end() and line[found.end():].lstrip()[:1] in (':', '('):
            listed.add(_norm_word(found.group(1)))
        label = _LINE_LABEL.match(line)
        label_end = label.end(1) if label and len(label.group(1).replace('(', ' ').split()) <= 4 else -1
        for m in _WORD.finditer(line):
            word = m.group(0)
            if not word[0].isupper() or (word.isupper() and len(word) > 1):
                continue
            before = line[:m.start()].rstrip()
            mid = bool(before) and (before[-1].isalnum() or before[-1] in ',&') and m.start() >= label_end
            after = line[m.end():].lstrip()
            alone = not (after[:1].isupper() or re.match(r"(of|the)\s+[A-Z]", after))  # "the Eight", not "the Dark Brotherhood"
            out.append((word, mid, alone and (before.lower().endswith(' the') or before.lower() == 'the')))
    return out, listed


def must_keep(original: str, covered: str = '', name: str = '') -> list[str]:
    """The names and numbers of the original that the result must still carry: capitalised words used as names (inside
    a sentence, more than once, or naming a list item), numbers and {placeholders}, less the ones the Background facts
    (covered) already state, the NPC's own name, race and sex words, list numbering, and words used only in the
    original's own headings ("Instructions:", "[Roleplay Instructions:").
    A bare title (Queen, Jarl) is listed but may go when a name on its line is kept (see missing)."""
    caps, listed = _caps(original)
    headings = _heading_only(original)
    lower = {_norm_word(m.group(0)) for m in _WORD.finditer(original or '') if m.group(0)[0].islower()}
    count: dict = {}
    mid: set = set()
    titled: set = set()  # after "the" inside a sentence: a name even when the word is ordinary
    shown: dict = {}
    for word, inside, after_the in caps:
        w = _norm_word(word)
        if not w:
            continue
        count[w] = count.get(w, 0) + 1
        shown.setdefault(w, re.sub(r"['’]s?$", '', word))
        if inside:
            mid.add(w)
        if after_the:
            titled.add(w)
    covered_words = _word_set(covered)
    own = _word_set(name)
    keep = []
    for w in shown:
        named = w in mid or w in listed or (count[w] >= 2 and w not in lower)
        if "'" in w and w.split("'")[0] in COMMON:  # I'll, You're
            continue
        if w in ORDINARY and w not in titled:
            continue
        if not named or w in COMMON or len(w) < 2 or w in own or _has(covered_words, w):
            continue
        if w in RACE_SEX or (w in headings and w not in listed):
            continue
        keep.append(shown[w])
    numbers = [n for n in dict.fromkeys(_NUMBER.findall(_LIST_NUMBER.sub(' ', original or ''))) if n not in (covered or '')]
    # a placeholder must stay where it stands in a kept sentence (the prompt says so); one that stood only in a dropped
    # sentence is no reason to reject the result, unless that sentence was a rule (rules are carried word for word)
    braces = list(dict.fromkeys(_BRACES.findall(' '.join(rule_items(original or '')))))
    return keep + numbers + braces


def _heading_only(original: str) -> set[str]:
    """Words the original uses only in its own headings: a line label of up to six words that is not a list item's
    name, or the head of a bracket ("[Roleplay Instructions: ...")."""
    total, in_heads = {}, {}
    for m in _WORD.finditer(original or ''):
        w = _norm_word(m.group(0))
        total[w] = total.get(w, 0) + 1
    for line in (original or '').splitlines():
        heads = [m.group(1) for m in _BRACKET_HEAD.finditer(line)]
        label = _LINE_LABEL.match(line)
        listed = _LIST_LABEL.match(line)
        if label and len(label.group(1).split()) <= 6 and not (listed and len(label.group(1).split()) == 1):
            heads.append(label.group(1))
        for head in heads:
            for m in _WORD.finditer(head):
                w = _norm_word(m.group(0))
                in_heads[w] = in_heads.get(w, 0) + 1
    return {w for w, n in in_heads.items() if n >= total.get(w, 0)}


def _title_beside_kept(original: str, title: str, words: set, keep: list) -> bool:
    """A title may go when a name the result keeps stands on the same line of the original."""
    names = [k for k in keep if k[:1].isalpha() and _norm_word(k) not in TITLES]
    t = _norm_word(title)
    for line in (original or '').splitlines():
        here = _word_set(line)
        if t in here and any(_has(here, n) and _has(words, n) for n in names):
            return True
    return False


def missing(original: str, result: str, covered: str = '', name: str = '') -> list[str]:
    """What must_keep lists that the result lacks."""
    words = _word_set(result)
    flat = (result or '').replace(',', '')
    keep = must_keep(original, covered, name)
    out = []
    for item in keep:
        if item.startswith('{'):
            ok = item in (result or '')
        elif item[0].isdigit():
            ok = item.replace(',', '') in flat
        else:
            ok = (_has(words, item) or (_norm_word(item) in TITLES and _title_beside_kept(original, item, words, keep))
                  or _place_word_beside_kept(original, item, words))
        if not ok:
            out.append(item)
    for item in dict.fromkeys(_BRACES.findall(original or '')):  # a placeholder in a sentence the result kept stays
        if item not in keep and item not in (result or '') and _kept_sentence_with(original, item, words):
            out.append(item)
    return out


# a place word that is only ever the second part of a name whose own word the result keeps ("River" of "Darkwater
# River" when "Darkwater" is kept, live test 9: Sylgja); never alone, after an ordinary word ("White River") or a title
PLACE_WORDS = set("""
river rivers lake creek falls crossing ford bridge pass road mine mines cave caves hill hills mountain mountains peak
forest woods wood marsh valley bay coast shore isle island
""".split())


def _place_word_beside_kept(original: str, item: str, words: set) -> bool:
    w = _norm_word(item)
    if w not in PLACE_WORDS:
        return False
    found = False
    for m in re.finditer(rf"(?<![\w'’-]){re.escape(item)}(?![\w'’-])", original or ''):
        before = re.search(r"([A-Za-zÀ-ɏ][\w'’-]*)\s+$", original[:m.start()])
        prev = _norm_word(before.group(1)) if before else ''
        if (not before or not before.group(1)[0].isupper() or prev in ORDINARY or prev in COMMON or prev in TITLES
                or not _has(words, prev)):
            return False
        found = True
    return found


def _kept_sentence_with(original: str, item: str, words: set) -> bool:
    """A sentence of the original holding item whose own words the result mostly carries (it was kept, maybe reworded)."""
    for line in (original or '').splitlines():
        for start, end in _sentence_spans(_mask_quotes(line), line):
            sentence = line[start:end]
            if item not in sentence:
                continue
            own = [w for w in _word_set(sentence.replace(item, ' ')) if len(w) >= 4 and w not in COMMON]
            if own and sum(1 for w in own if _has(words, w)) >= 0.6 * len(own):
                return True
    return False


def added(original: str, result: str, covered: str = '', name: str = '') -> list[str]:
    """Names in the result that neither the original, the Background facts nor the NPC's name contain (invented)."""
    known = _word_set(original) | _word_set(covered) | _word_set(name)
    caps, _ = _caps(result)
    out = []
    for word, inside, _ in caps:
        w = _norm_word(word)
        if inside and w and w not in COMMON and w not in ORDINARY and w not in PART_WORDS and not _has(known, w) and word not in out:
            out.append(word)
    return out


def _labelled(text: str) -> bool:
    return any(re.match(rf"\s*{re.escape(p)}\s*:", line, re.I) for line in text.splitlines() for p in PARTS)


def clean_reply(reply) -> str:
    text = str(reply or '').strip()
    text = re.sub(r'^```[a-z]*\n|\n?```$', '', text).strip()
    text = re.sub(r"^(here is|here's)[^\n]*:\s*\n", '', text, flags=re.I)
    lines = []
    for line in text.splitlines():
        line = re.sub(r'^\s*[*_]+([A-Za-z ]+?)[*_]+\s*:', r'\1:', line).strip()  # **Voice**: -> Voice:
        line = re.sub(r'^\s*[*_]+([A-Za-z ]+?):[*_]+', r'\1:', line).strip()    # **Voice:** -> Voice:
        if line:
            lines.append(line)
    return '\n'.join(lines)


_PART_LABEL = re.compile(rf"(?im)^\s*(?:{'|'.join(re.escape(p) for p in PARTS)})\s*:\s*")


def own_sizes(original: str, result: str) -> tuple[int, int]:
    """(the result's own text, the original's) in characters, for the length rule: the rules, the part labels and what
    the result had to copy word for word and did (nickname lines, the author note, quoted lines of the original) left
    out on both sides, so a sheet whose length is mostly lines it must keep is judged by what it could shorten."""
    rest, body = without_rules(original), _body(result)
    flat_body, flat_rest = _flat(body), _flat(rest)
    kept = [p for p in dict.fromkeys(term_lines(rest) + [author_note(original)])
            if p and _flat(p) in flat_body and _flat(p) in flat_rest]
    kept += [q for q in dict.fromkeys(quoted(rest)) if len(q.split()) >= 3 and _flat(q) in flat_body
             and not any(_flat(q) in _flat(k) for k in kept)]
    size = len(_PART_LABEL.sub('', body)) - sum(len(p) for p in kept)
    base = len(rest) - sum(len(p) for p in kept)
    return max(size, 0), max(base, 1)


def problems(original: str, result: str, covered: str = '', name: str = '') -> tuple[list[str], list[str]]:
    """(what is wrong with this result, the names and numbers it lost); ([], []) when it can be used."""
    bad = []
    if not result:
        return ['it was empty'], []
    body, rest = _body(result), without_rules(original)  # the rules are carried word for word: not counted
    size, base = own_sizes(original, result)
    if size > base * MAX_SHARE:
        bad.append(f"it is not clearly shorter ({size} characters of its own text for {base} in the original, labels, "
                   f"rules and lines copied word for word left out; at most {int(base * MAX_SHARE)}, aim for "
                   f"{target_chars(rest)} in all)")
    if not _labelled(result):
        bad.append('it does not use the labelled parts')
    if body.rstrip()[-1:] not in '.!?"”\')…':
        bad.append('it was cut off')
    lost = missing(original, result, covered, name)
    if lost:
        bad.append('it leaves out ' + ', '.join(lost[:40]))
    new = added(original, result, covered, name)
    if new:
        bad.append('it names things the sheet does not: ' + ', '.join(new[:20]))
    fake = invented_quotes(original, result)
    if fake:
        bad.append('it quotes words the sheet does not have word for word: ' + ' / '.join(f'"{q}"' for q in fake[:5]))
    need, have = sample_need(rest), sample_count(result)
    if have < need:
        bad.append(f"it keeps {have} sample lines; keep at least {need} of their own lines, word for word")
    judgement = judged(original, result)
    if judgement:
        bad.append('it adds judgements the sheet does not make: ' + ', '.join(judgement))
    ties = relations_missing(original, result)
    if ties:
        bad.append('it drops these family or spouse ties the sheet states (keep each with its name): ' + '; '.join(ties[:8]))
    rules = rules_missing(original, result)
    if rules:
        bad.append('it does not carry these rule lines word for word: ' + ' | '.join(r[:80] for r in rules[:5]))
    braces = placeholders_added(original, result)
    if braces:
        bad.append('it adds placeholders the sheet does not have: ' + ', '.join(braces) + ' (write it as the sheet does)')
    hedges = hedges_lost(original, result)
    if hedges:
        bad.append('it states as fact what the sheet gives only as a rumour (keep it a rumour): ' + ' | '.join(h[:100] for h in hedges[:3]))
    reacts = situations_missing(original, result)
    if reacts:
        bad.append('it drops how they react in these situations (keep each situation and the reaction together in one '
                   'sentence): ' + ' | '.join(r[:100] for r in reacts[:5]))
    terms = terms_missing(rest, result)
    if terms:
        bad.append('it does not copy these nickname lines word for word: ' + ' | '.join(t[:80] for t in terms[:5]))
    reasons = lost_reasons(original, result, name)
    if reasons:
        bad.append('it keeps these facts but drops the reason the sheet gives for each (keep the reason with the fact): '
                   + ' | '.join(r[:120] for r in reasons[:5]))
    explained = explained_terms(original, result)
    if explained:
        bad.append("it says who a term is for that the sheet only uses inside a spoken line (keep that line word for word "
                   "as a sample line instead): " + ', '.join(f'"{t}"' for t in explained[:5]))
    return bad, lost


def target_chars(original: str) -> int:
    return max(MIN_AIM, int(len(original) * AIM))


def bio_hash(original: str, version: int | None = None) -> str:
    """The cache key: the original text (spacing ignored) and the format version (the current one unless given)."""
    text = ' '.join(str(original or '').split())
    return hashlib.sha256(f"{FORMAT_VERSION if version is None else version}\n{text}".encode('utf-8', 'replace')).hexdigest()[:24]


def _checker_print() -> str:
    """A fingerprint of the check code (from the word lists to problems()): when it changes, stored short bios are
    checked again when they are next read (entry), so a rule change without a FORMAT_VERSION bump is not missed."""
    try:
        with open(__file__, encoding='utf-8') as f:
            src = f.read()  # text mode reads CRLF as LF: the same print whatever line ends git gave the file
        start, end = src.index('\nCOMMON = set('), src.index('\ndef target_chars(')
        return hashlib.sha256(src[start:end].encode('utf-8', 'replace')).hexdigest()[:16]
    except (OSError, ValueError):
        return ''


CHECKER = _checker_print()


def optimise_detail(bio: str, background_lines, name: str, ask) -> dict:
    """{text, status, why, tries}: status 'done' (text is the short bio), 'kept' (the original stays; why says why) or
    'short' (nothing to gain). ask(prompt, text) -> reply: the helper model call. At most two calls; never raises."""
    original = str(bio or '').strip()
    covered = '\n'.join(stable_lines(background_lines))
    if len(original) < MIN_CHARS:
        return {'text': original, 'status': 'short', 'why': f"under {MIN_CHARS} characters: nothing to gain", 'tries': 0}
    rules = rule_items(original)
    rest = without_rules(original, rules)
    if len(rest) < MIN_CHARS:
        return {'text': original, 'status': 'short', 'why': f"under {MIN_CHARS} characters besides its rules: nothing to gain", 'tries': 0}
    need = sample_need(rest)
    lines = f"at least {need} short lines of their own speech" if need else "up to 3 short lines of their own speech"
    prompt = PROMPT.format(name=name, chars=target_chars(rest), lines=lines)
    text = (f"Background facts already sent about {name}:\n{covered.strip() or '(none)'}\n\n"
            f"Character sheet of {name}:\n{rest}")
    why = ''
    for attempt in (1, 2):
        try:
            reply = clean_reply(ask(prompt if attempt == 1 else prompt + RETRY.format(problems='; '.join(why_list)), text))
        except Exception as e:
            return {'text': original, 'status': 'kept', 'why': f"the helper model could not be asked ({e})", 'tries': attempt, 'error': True}
        if not reply:
            return {'text': original, 'status': 'kept', 'why': 'the helper model gave no answer', 'tries': attempt, 'error': True}
        reply = with_rules(with_note(reply, author_note(original)), rules)
        why_list, _ = problems(original, reply, covered, name)
        if not why_list:
            return {'text': reply, 'status': 'done', 'why': '', 'tries': attempt, 'covered': covered}
        why = '; '.join(why_list)
    return {'text': original, 'status': 'kept', 'why': f"{FAILED_CHECK} ({why})", 'tries': 2, 'candidate': reply}


FAILED_CHECK = 'the short version failed the check twice'
WRITTEN = 'written'  # source of the entry marking an override file that already holds its short bio
MANUAL = 'manual'    # source of an entry decided by hand (a short bio written by hand, or the original kept on purpose):
#                      never checked again, redone or replaced by the optimiser while the original text stays the same
KEEP_SOURCES = (WRITTEN, MANUAL)  # entries that stand under any format


STABLE = ('- Race:', '- Sex:')  # Background lines a short bio may leave out: the same in every save, always sent


def stable_lines(lines) -> list[str]:
    """The Background lines a short bio may leave out: race and sex only. Family and spouse are never covered: the
    Background states them only when the game's ties data lists them (never an estranged or dead spouse, nor a mod-added
    character's family; live test 9: Valerica lost "the mother of Serana"), and a spouse line can differ between saves.
    Home, partner, follower, role, groups, religion, values and anything a save or the player changed are never treated
    as covered either: the bio is shared by every save."""
    if isinstance(lines, str):
        lines = lines.splitlines()
    return [l.strip() for l in lines or [] if isinstance(l, str) and l.strip().startswith(STABLE)]


def stable_background(speaker: dict, entry: dict | None = None, ties: dict | None = None) -> list[str]:
    """Those lines for one NPC, built without any save: race and sex (the Characters page, else the game's npc file),
    the game's family ties and the NPC's own spouse from ties.json (base-game data, shared by all saves)."""
    from . import characters, contracts, facts_history
    speaker, entry = speaker or {}, entry or {}
    out = []
    for k, label in characters.LOCKED:
        value = (entry.get('locked') or {}).get(k) or str(speaker.get(k) or '').strip()
        if value:
            out.append(f"- {label}: {value.capitalize() if k == 'race' and value.isupper() else value}")
    family = facts_history.family_line(speaker, ties)
    if family:
        out.append(family)
    base = contracts.base_key(speaker.get('base_id'))
    spouses = [t['name'] for t in contracts.ties_of(base, ties) if t.get('kind') == 'spouse' and t.get('name')] if base else []
    if spouses:
        out.append(f"- Spouse: {', '.join(dict.fromkeys(spouses))}")
    return out


def optimise(bio: str, background_lines, name: str, ask=None) -> str:
    """The short bio, or the original when it is short, the helper is not reachable or the result failed the check."""
    ask = ask or pick_ask(bio)
    if ask is None:
        return str(bio or '').strip()
    return optimise_detail(bio, background_lines, name, ask)['text']


# --- which model call ----------------------------------------------------------------------------------------------------

def reply_room(summaries) -> int | None:
    """The summary call's reply limit in tokens (max_tokens), None when unknown or unlimited."""
    client = getattr(summaries, '_Summaries__client', None)
    params = getattr(client, '_request_params', None)
    value = params.get('max_tokens') if isinstance(params, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def fits(summaries, bio: str) -> bool:
    """The short version of this bio fits in the summary call's reply limit (with room to spare)."""
    room = reply_room(summaries)
    return room is None or preview.tokens('x' * target_chars(bio)) * 1.3 <= room


def summary_ask(summaries, name: str = 'a bio'):
    """ask(prompt, text) through Mantella's summary call, as the Now paragraph is written."""
    from . import memory
    return lambda prompt, text: memory._ask_summary(summaries, text, prompt, f"the short bio of {name}")


REPLY_TOKENS = 3000  # reply room of the short-bio call: the longest stock bio's short version is about 1,300 tokens
_roomy: dict = {'config': None, 'ask': None}


def roomy_ask(summaries=None):
    """ask(prompt, text) on a client of its own with room for REPLY_TOKENS and no stop sequence: the custom summary
    model when one is set, else the conversation model (as the "Optimize with AI" button does), so a long bio's short
    version is never cut off by Mantella's 250-token reply limit. Run on the background worker after a talk or from a
    button, never during a reply. None without Mantella's config."""
    config = helper.get('config') or getattr(summaries if summaries is not None else helper.get('summaries'),
                                             '_Summaries__config', None)
    if config is None:
        return None
    if _roomy['config'] is not config:
        from . import ui_overrides
        _roomy.update(config=config, ask=ui_overrides.model_asker(config, summary=True, max_tokens=REPLY_TOKENS))
    return _roomy['ask']


def pick_ask(bio: str, name: str = 'a bio'):
    """The call for a short bio: roomy_ask when Mantella's config is known, else the summary call when the result fits
    its reply limit; None when neither is reachable (or it would not fit: a cut-off answer is useless)."""
    ask = roomy_ask()
    if ask is not None:
        return ask
    summaries = helper.get('summaries')
    return summary_ask(summaries, name) if summaries is not None and fits(summaries, bio) else None


# --- the cache --------------------------------------------------------------------------------------------------------------

def _empty() -> dict:
    return {'version': 1, 'bios': {}, 'use_original': []}


def load(path=None) -> dict:
    """{version, bios: {hash: entry}, use_original: [lowercase names]}; re-read when it changed. Never raises."""
    path = path or PATH
    with _lock:
        try:
            stamp = os.path.getmtime(path)
        except OSError:
            return _empty()
        if _cache['path'] == path and _cache['stamp'] == stamp:
            return _cache['data']
        try:
            with open(path, encoding='utf-8-sig') as f:
                data = json.load(f)
        except (OSError, ValueError, RecursionError):
            data = {}
        out = _empty()
        if isinstance(data, dict):
            if isinstance(data.get('bios'), dict):
                # an entry of an older format is never used (the original is sent until a current one exists) and
                # is dropped here, so the next write leaves it out of the file (live test 7: format-1 short bios of
                # Breval and Nia still marked done). Kept from any format: the mark that an override file already
                # holds its short bio (written into it), which no format change makes long again.
                out['bios'] = {k: v for k, v in data['bios'].items() if isinstance(k, str) and isinstance(v, dict)
                               and isinstance(v.get('text'), str) and v.get('status') in ('done', 'kept')
                               and (memory_int(v.get('format')) == FORMAT_VERSION or v.get('source') in KEEP_SOURCES)}
            if isinstance(data.get('use_original'), list):
                out['use_original'] = sorted({str(n).strip().lower() for n in data['use_original'] if isinstance(n, str) and n.strip()})
        _cache.update(path=path, stamp=stamp, data=out)
        return out


def _write(path, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if len(data['bios']) > MAX_ENTRIES:  # oldest first out
        keep = sorted(data['bios'].items(), key=lambda kv: kv[1].get('at', 0))[-MAX_ENTRIES:]
        data['bios'] = dict(keep)
    tmp = lw_state.temp_path(path)
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    lw_state.replace_file(tmp, path)
    _cache.update(path=None, stamp=None, data=None)


_checked: dict = {}  # (hash, CHECKER) -> the stored entry still stands under the current check (this session)


def entry(name: str, original: str, path=None) -> dict | None:
    """The cached result for this exact original under the current format, else None (the original is sent and a new
    short bio is written after the next talk or by the button). An override text written as its short bio counts under
    any format. An entry stored by other check code (CHECKER) is checked again, once per session and without a model
    call: a short bio that now fails, or a check failure that the changed check may now pass, is due again."""
    bios = load(path)['bios']
    key = bio_hash(original)
    found = bios.get(key)
    if found is None:
        for version in range(1, FORMAT_VERSION):
            old = bios.get(bio_hash(original, version))
            if old is not None and old.get('source') in KEEP_SOURCES:
                return old
        return None
    if memory_int(found.get('format')) != FORMAT_VERSION:
        return found if found.get('source') in KEEP_SOURCES else None
    if found.get('source') in KEEP_SOURCES or not CHECKER or found.get('checker') == CHECKER:
        return found
    memo = (key, CHECKER)
    if memo not in _checked:
        _checked[memo] = still_passes(name, str(original or '').strip(), found)
    return found if _checked[memo] else None


def still_passes(name: str, original: str, found: dict) -> bool:
    """A stored entry under the current check code: a short bio passes problems() (against the Background lines it was
    checked with); "short enough besides its rules" is measured again; a check failure is asked again."""
    why = str(found.get('why') or '')
    if found.get('status') == 'done':
        bad, _ = problems(original, found.get('text', ''), found.get('covered', ''), name)
        if bad:
            logger.log(23, f"Living World: {name}'s short bio fails the changed check ({'; '.join(bad)[:300]}); the "
                           f"original is sent until a new one is written")
        return not bad
    if why.startswith(FAILED_CHECK):
        return False
    if 'besides its rules' in why:
        return len(without_rules(original)) < MIN_CHARS
    return True


def remember(name: str, original: str, detail: dict, path=None, source: str = 'auto',
             replace_manual: bool = False) -> dict | None:
    """Keeps a 'done' or 'kept' result (not a call that failed to reach the model). 'short' (nothing to gain) is kept
    as 'kept': that decision replaces any older entry for the NPC, so an older short version is never shown again.
    An entry decided by hand (MANUAL) for the same original is left alone (None) unless replace_manual (the NPC page's
    own Optimise again button)."""
    if detail.get('status') not in ('done', 'kept', 'short') or detail.get('error'):
        return None
    detail = dict(detail, status='kept') if detail['status'] == 'short' else detail
    path = path or PATH
    row = {'name': str(name or ''), 'status': detail['status'], 'text': detail['text'] if detail['status'] == 'done' else '',
           'why': detail.get('why', ''), 'format': FORMAT_VERSION, 'before': len(str(original or '').strip()),
           'after': len(detail['text']) if detail['status'] == 'done' else len(str(original or '').strip()),
           'at': time.time(), 'source': source, 'checker': CHECKER}
    if detail['status'] == 'done' and detail.get('covered'):
        row['covered'] = str(detail['covered'])[:4000]  # the Background lines it was checked against, to check it again
    if detail['status'] == 'kept' and detail.get('candidate'):
        row['tried'] = str(detail['candidate'])[:6000]  # the last rejected short version, to see what the check refused
    with _lock:
        data = load(path)
        data = {'version': 1, 'bios': dict(data['bios']), 'use_original': list(data['use_original'])}
        low = row['name'].strip().lower()  # entries of an older format for this NPC are never read again
        data['bios'] = {k: v for k, v in data['bios'].items()
                        if not (str(v.get('name') or '').strip().lower() == low and low and v.get('source') not in KEEP_SOURCES
                                and memory_int(v.get('format')) < FORMAT_VERSION)}
        if source != MANUAL and not replace_manual and _manual_in(data['bios'], original) is not None:
            return None  # decided by hand for this exact original: kept until the original changes
        if replace_manual:
            for version in range(1, FORMAT_VERSION + 1):
                if (data['bios'].get(bio_hash(original, version)) or {}).get('source') == MANUAL:
                    del data['bios'][bio_hash(original, version)]
        data['bios'][bio_hash(original)] = row
        _write(path, data)
    return row


def _manual_in(bios: dict, original: str) -> dict | None:
    for version in range(FORMAT_VERSION, 0, -1):
        found = bios.get(bio_hash(original, version))
        if found is not None and found.get('source') == MANUAL:
            return found
    return None


def is_manual(found: dict | None) -> bool:
    return bool(found) and found.get('source') == MANUAL


def set_manual(name: str, original: str, text: str | None, path=None) -> dict | None:
    """A decision by hand for this exact original: text is the short bio to send, or None/'' to send the original. It
    is never checked again, redone (not even by a forced Optimise) or replaced, until the original text changes (the
    entry is keyed by its hash). The original itself is never touched."""
    original = str(original or '').strip()
    text = str(text or '').strip()
    if not original:
        return None
    detail = ({'status': 'done', 'text': text, 'why': 'edited by hand'} if text else
              {'status': 'kept', 'text': original, 'why': 'kept by hand: the original is sent'})
    return remember(name, original, detail, path, source=MANUAL, replace_manual=True)  # an older hand entry goes


def memory_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return 0


def uses_original(name: str, path=None) -> bool:
    return str(name or '').strip().lower() in load(path)['use_original']


def set_use_original(name: str, flag: bool, path=None) -> None:
    """The per-NPC opt-out: their original bio is always sent (kept until switched back)."""
    path = path or PATH
    low = str(name or '').strip().lower()
    with _lock:
        data = load(path)
        names = set(data['use_original'])
        if flag:
            names.add(low)
        else:
            names.discard(low)
        if names != set(data['use_original']):
            _write(path, {'version': 1, 'bios': dict(data['bios']), 'use_original': sorted(names)})


def used_bio(name: str, original: str, values: dict | None = None, path=None) -> str:
    """The bio to send: the current short version, else the original unchanged (feature off, opted out, none yet,
    kept)."""
    from . import settings
    values = values if values is not None else settings.load()
    if not values.get('bio_optimise', True) or not str(original or '').strip() or uses_original(name, path):
        return original
    found = entry(name, original, path)
    return found['text'] if found and found.get('status') == 'done' and found.get('text') else original


def apply(mantella_text: str, bios, used) -> str:
    """Mantella's prompt with each original bio swapped for the one to send (used(name, original) -> text)."""
    out = mantella_text
    for name, original in bios or []:
        original = str(original or '')
        if len(original.strip()) < MIN_CHARS:
            continue
        text = used(name, original)
        if text and text != original and original in out:
            out = out.replace(original, text, 1)
    return out


# --- after a talk -----------------------------------------------------------------------------------------------------------

def due(name: str, original: str, values: dict, path=None) -> bool:
    """This NPC needs a short bio: the feature is on, not opted out, long enough, none for this text and format yet and
    not tried without an answer this session."""
    original = str(original or '').strip()
    return bool(values.get('bio_optimise', True) and len(original) >= MIN_CHARS and not uses_original(name, path)
                and entry(name, original, path) is None and bio_hash(original) not in _tried)


def run_one(name: str, original: str, background_lines, ask, path=None) -> dict:
    """One NPC: asked, checked, kept. A call that never reached the model is not asked again this session."""
    detail = optimise_detail(original, background_lines, name, ask)
    if detail.get('error'):
        _tried.add(bio_hash(original))
        logger.warning(f"Living World: no short bio for {name} this session ({detail['why']})")
    else:
        remember(name, original, detail, path)
        if detail['status'] == 'done':
            logger.log(23, f"Living World: short bio for {name}: {len(original.strip())} -> {len(detail['text'])} characters")
        elif detail['status'] == 'kept':
            logger.log(23, f"Living World: {name} keeps their original bio ({detail['why']})")
    return detail


def after_talk(npcs, summaries, values: dict, background_for=None, path=None, background: bool = True) -> list:
    """The talk's NPCs without a current short bio are queued (at most MAX_PER_TALK) on the Now paragraph's background
    worker, which waits while a talk goes on: one helper call each (two when the first fails the check).
    background_for(npc) -> their Background lines. Returns the queued NPCs' names (or, background False, the results)."""
    from . import bio_evolve
    if summaries is None or not values.get('bio_optimise', True):
        return []
    jobs = []
    for npc in npcs or []:
        name, original = getattr(npc, 'name', ''), str(getattr(npc, 'bio', '') or '').strip()
        if not name or not due(name, original, values, path):
            continue
        if roomy_ask(summaries) is None and not fits(summaries, original):  # only Mantella's own summary call
            _tried.add(bio_hash(original))
            logger.log(23, f"Living World: {name}'s bio is too long for the summary model's reply limit; it keeps "
                           f"its original")
            continue
        jobs.append((npc, name, original))
        if len(jobs) >= MAX_PER_TALK:
            break
    results = []
    for npc, name, original in jobs:
        def job(npc=npc, name=name, original=original):
            lines = []
            if background_for is not None:
                try:
                    lines = background_for(npc) or []
                except Exception as e:
                    logger.warning(f"Living World: {name}'s Background could not be read for the short bio ({e})")
            if entry(name, original, path) is None:  # done meanwhile (a button)
                return run_one(name, original, lines, roomy_ask(summaries) or summary_ask(summaries, name), path)
            return None
        if background:
            bio_evolve._start_worker()
            bio_evolve._enqueue(('short bio', bio_hash(original)), job)
            results.append(name)
        else:
            results.append(job())
    return results


# --- the user's override files --------------------------------------------------------------------------------------------

def override_bios(overrides_dir) -> list[dict]:
    """[{name, race, bio, file}] of every override with a bio (files Mantella reads: .json; READ only)."""
    out = []
    try:
        names = sorted(os.listdir(overrides_dir))
    except OSError:
        return out
    for file in names:
        if not file.endswith('.json'):
            continue
        try:
            with open(os.path.join(overrides_dir, file), encoding='utf-8-sig') as f:
                data = json.load(f)
        except (OSError, ValueError, RecursionError):
            continue
        for row in data if isinstance(data, list) else [data]:
            if isinstance(row, dict) and isinstance(row.get('name'), str) and isinstance(row.get('bio'), str) and row['bio'].strip():
                out.append({'name': row['name'], 'race': str(row.get('race') or ''), 'bio': row['bio'], 'file': file})
    return out


def user_background(row: dict) -> list[str]:
    """The stable Background lines of an NPC outside a talk (the buttons): the game's npc file and the Characters page
    entry, no save."""
    from . import characters
    name, race = str(row.get('name') or ''), str(row.get('race') or '')
    return stable_background(dict(characters.game_npc(name, race), name=name), characters.entry_for(name, race))


def optimise_overrides(overrides_dir, ask_for, background_for=None, progress=None, force: bool = False, path=None,
                       wait=None) -> dict:
    """Every override bio: short bios written where none is current (force: again). ask_for(bio, name) -> ask (None:
    no model reachable). background_for(row) -> Background lines. progress(done, total, name). The files are only
    read. wait() -> True while a talk goes on: each request waits for it (a reply is never held up). Returns {total, shortened, before, after, kept: [(name, why)], short, current, opted_out, failed}."""
    rows = override_bios(overrides_dir)
    result = {'total': len(rows), 'shortened': 0, 'before': 0, 'after': 0, 'kept': [], 'short': 0, 'current': 0,
              'opted_out': 0, 'failed': []}
    for i, row in enumerate(rows):
        name, original = row['name'], row['bio'].strip()
        if progress is not None:
            try:
                progress(i, len(rows), name)
            except Exception:
                pass
        if uses_original(name, path):
            result['opted_out'] += 1
            continue
        if len(original) < MIN_CHARS:
            result['short'] += 1
            continue
        found = entry(name, original, path)
        if found is not None and (not force or is_manual(found)):
            result['current'] += 1
            if found['status'] == 'done':
                result['before'] += found.get('before') or len(original)
                result['after'] += len(found['text'])
            continue
        while wait is not None and wait():
            time.sleep(2.0)
        ask = ask_for(original, name)
        if ask is None:
            result['failed'].append((name, 'no model reachable yet'))
            continue
        lines = []
        if background_for is not None:
            try:
                lines = background_for(row) or []
            except Exception:
                lines = []
        detail = optimise_detail(original, lines, name, ask)
        if detail.get('error'):
            result['failed'].append((name, detail['why']))
            continue
        remember(name, original, detail, path, source='button')
        if detail['status'] == 'done':
            result['shortened'] += 1
            result['before'] += len(original)
            result['after'] += len(detail['text'])
        else:
            result['kept'].append((name, detail['why']))
    if progress is not None:
        try:
            progress(len(rows), len(rows), '')
        except Exception:
            pass
    return result


def summary_text(r: dict) -> str:
    """The result of optimise_overrides, in a few lines."""
    if not r.get('total'):
        return 'You have no override bios.'
    saved = r['before'] - r['after']
    share = f" ({round(100 * saved / r['before'])}% shorter)" if r['before'] else ''
    lines = [f"{r['total']} override bio(s): {r['shortened']} shortened now, {r['current']} already had a current short "
             f"bio, {r['short']} short enough as they are, {r['opted_out']} set to use the original, {len(r['kept'])} "
             f"kept as they were, {len(r['failed'])} not done.",
             f"Short bios in use for your overrides: {r['before']:,} -> {r['after']:,} characters, about "
             f"{preview.tokens('x' * saved) if saved > 0 else 0:,} tokens less per talk with each of them{share}."]
    for name, why in r['kept']:
        lines.append(f"- kept {name}: {why}")
    for name, why in r['failed']:
        lines.append(f"- not done {name}: {why}")
    return '\n'.join(lines)


def write_into_overrides(overrides_dir, path=None, backup_root=None) -> dict:
    """The explicit action: copies every override file to a dated backup folder next to the overrides folder, then puts
    each current short bio into its override file (not for NPCs set to use the original). The written text is then the
    source, recorded as already short so it is not shortened again. {backup, files, bios}."""
    path = path or PATH
    files = [f for f in sorted(os.listdir(overrides_dir)) if f.endswith('.json')] if os.path.isdir(overrides_dir) else []
    if not files:
        return {'backup': '', 'files': 0, 'bios': 0}
    root = backup_root or os.path.join(os.path.dirname(os.path.abspath(overrides_dir)), BACKUPS)
    folder = os.path.join(root, time.strftime('%Y%m%d-%H%M%S'))
    n = 2
    while os.path.exists(folder):
        folder, n = os.path.join(root, time.strftime('%Y%m%d-%H%M%S') + f"-{n}"), n + 1
    os.makedirs(folder)
    for f in files:
        shutil.copy2(os.path.join(overrides_dir, f), os.path.join(folder, f))
    changed_files = changed_bios = 0
    for f in files:
        full = os.path.join(overrides_dir, f)
        try:
            with open(full, encoding='utf-8-sig') as fh:
                data = json.load(fh)
        except (OSError, ValueError, RecursionError):
            continue
        rows = data if isinstance(data, list) else [data]
        changed = False
        for row in rows:
            if not (isinstance(row, dict) and isinstance(row.get('name'), str) and isinstance(row.get('bio'), str)):
                continue
            if uses_original(row['name'], path):
                continue
            found = entry(row['name'], row['bio'].strip(), path)
            if found and found['status'] == 'done' and found['text'] and found['text'] != row['bio']:
                row['bio'] = found['text']
                remember(row['name'], found['text'], {'status': 'kept', 'text': found['text'],
                                                      'why': 'already the short bio (written into your override file)'},
                         path, source=WRITTEN)
                changed = True
                changed_bios += 1
        if changed:
            tmp = full + '.tmp'
            # ASCII only, as save_override writes them: Mantella reads override files with the system codepage
            with open(tmp, 'w', encoding='ascii') as fh:
                json.dump(data, fh, ensure_ascii=True, indent=2)
            os.replace(tmp, full)
            changed_files += 1
    return {'backup': folder, 'files': changed_files, 'bios': changed_bios}


# --- the NPC page -----------------------------------------------------------------------------------------------------------

def _page_status(original: str, values: dict, opted: bool, found: dict | None) -> str:
    """The Personality section's one status line: why the original or the short bio is sent. original is stripped."""
    if not original:
        return 'No bio yet.'
    if not values.get('bio_optimise', True):
        return 'Short bios are switched off in Settings: the original is sent.'
    if opted:
        return 'Set to use the original for this NPC: the original is sent.'
    if len(original) < MIN_CHARS:
        return f"Short enough ({len(original)} characters): the original is sent."
    if found is None:
        return 'No short bio yet: the original is sent. One is written after their next talk, or press Optimise again.'
    done = found['status'] == 'done'
    if is_manual(found):
        if done:
            return (f"Short bio edited by hand, in use: {found.get('before') or len(original):,} -> "
                    f"{len(found['text']):,} characters. Optimise leaves it alone until the original changes.")
        return 'The original is kept (decided by hand): Optimise leaves it alone until the original changes.'
    if done:
        return (f"Short bio in use: {found.get('before') or len(original):,} -> {len(found['text']):,} characters "
                f"(about {preview.tokens(original) - preview.tokens(found['text']):,} tokens less). Takes effect "
                f"from the next talk.")
    return f"The original is kept: {found.get('why') or 'the short version did not pass the check'}."


def page_view(name: str, original: str, values: dict | None = None, path=None) -> dict:
    """{status, original, short, opted_out} for the Personality section."""
    from . import settings
    values = values if values is not None else settings.load()
    original = str(original or '')
    opted = uses_original(name, path)
    found = entry(name, original.strip(), path) if original.strip() else None
    status = _page_status(original.strip(), values, opted, found)
    return {'status': status, 'original': original, 'short': found['text'] if found and found['status'] == 'done' else '',
            'opted_out': opted}
