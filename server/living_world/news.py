"""News rings: how what is in the world log (worldlog.py) reaches people, lazily, when they next talk. No background
work and no model call: at talk start catch_up() works out which events should have reached this NPC by now and adds
each once as a memory (memory.add_memory with key 'world:<event id>', so it never comes twice).

Ring 1  present at it, or named in it at once                         seen
Ring 2  their circle (ties.json:    about 1 day after the tie       told by that person
        family, household, boss /   knew it (0.75 to 1.25 days)
        workers; else same home)
Ring 3  same town as the event       2 to 3 days                     rumour, shortened public text
Ring 4  same hold, big events only  6 to 8 days                     rumour from elsewhere in the hold, shorter

Delays differ per NPC and event (worldlog.jitter: a hash, never random per call). An NPC whose town is unknown only
gets rings 1 and 2. Rings 2 to 4 need someone who still knows: when everyone who knew has had it wiped, it stops.
Only the public text ever goes out; an event with no public text never spreads. At most MAX_PER_TALK news items per
NPC per talk, the most important first; the rest come at later talks.

Wipes (apply_wipe): a scope (this NPC, those present, their circle, the town, everyone who knows) loses the memory
(hidden through memory.hide_matching, so it can be given back) and the event stops spreading inside it.
Re-entry rule: an event comes back into a wiped scope only when someone outside it who knows it is in a talk with the
NPC (it arrives as told by them), or the Hub user tells them. Never by itself: no ring delivers inside a wiped scope.

Children never receive marriage or intimate news. An intimate event reaches only those present. A wipe or a release
(worldlog.NEVER_NEWS_KINDS) is never delivered to anyone: the player's magic was quiet, so nobody knows it happened.

The game's day in conversation.json is a whole number and can still be the last talk's day when a talk's first request
comes in: an event logged earlier on that day is never taken for one from the future (talk_start's horizon)."""
import logging
import re

from . import worldlog as W

logger = logging.getLogger('Mantella')

MAX_PER_TALK = 3
MAX_SCAN = 600  # newest events looked at per NPC
RING2_DAYS, RING2_SPREAD = 0.75, 0.5
RING3_DAYS, RING3_SPREAD = 2.0, 1.0
RING4_DAYS, RING4_SPREAD = 6.0, 2.0
MAX_AGE = {1: 365, 2: 120, 3: 20, 4: 90}  # days after which an event is too old to be passed on (ring 3 big: 90)
BIG_RING3_AGE = 90
SCOPES = ('npc', 'present', 'circle', 'town', 'everyone')
NEWS_KEY = 'world:'

_seen: dict = {}  # (root, npc key, log version, game hour) -> already worked out this talk
FRESH_DAYS = 0.25  # something seen this recently (6 game hours) is still on the witness's mind at the greeting
_fresh: dict = {}  # NPC name -> the line for their next request's newest message (fresh_text)
_index: dict = {}  # (root, version) -> prepared events


def _memory():
    try:
        from . import memory
        return memory
    except Exception:
        return None


def _mantella_day() -> int:
    memory = _memory()
    return getattr(memory, 'MANTELLA_DAY', 1) if memory else 1


# --- prepared view of the log ------------------------------------------------------------------------------------------

def _key_idents(key: str, entry: dict) -> set:
    """A known entry's idents (key, ref, base and name); people are compared with worldlog.ident_match."""
    return W.known_idents(key, entry)


def _ids(p: dict) -> set:
    """What one person is compared by (worldlog.ident_match decides: reference id, base id, a name only without ids)."""
    return W.weak_idents(p)


def _by_ident(items) -> dict:
    """ident -> [(idents, item)] for quick candidates; ident_match still decides (a shared ident is not enough)."""
    out = {}
    for idents, item in items:
        for i in idents:
            out.setdefault(i, []).append((idents, item))
    return out


def _matches(index: dict, ids) -> list:
    """The items of a _by_ident index that are this person (worldlog.ident_match), each once, in index order."""
    out, seen = [], set()
    for i in ids:
        for idents, item in index.get(i, ()):
            if id(item) not in seen and W.ident_match(ids, idents):
                seen.add(id(item))
                out.append(item)
    return out


def _tie_ids(ties: list) -> list:
    """The ties with each one's idents worked out once ('_ids'), not again for every event."""
    return [dict(t, _ids=_ids(W.person(t.get('name'), t.get('base')))) for t in ties or [] if isinstance(t, dict)]


def close_to_dead(e: dict, me: dict, ties: list) -> bool:
    """A death or murder is "close" (the death_close flag) only when the dead was one of this person's own circle (family,
    household, workers, from ties) or a fellow follower of the player; a stranger dying nearby is not (live test 15: a
    hostile mercenary killed near Faendal). Never raises."""
    try:
        if not (e.get('kind') == 'death' or (e.get('kind') in ('crime', 'killing') and e.get('crime') == 'murder')):
            return False
        dead = [p for p in e.get('involved') or [] if isinstance(p, dict) and p.get('key') != W.PLAYER]
        for p in dead:
            ids = _ids(p)
            if any(W.ident_match(ids, t['_ids'] if '_ids' in t else _ids(W.person(t.get('name'), t.get('base')))) for t in ties or []):
                return True
        return _is_follower((me or {}).get('base')) and any(_is_follower(p.get('base')) for p in dead)
    except Exception:
        return False


def _is_follower(base) -> bool:
    if not base:
        return False
    try:
        from . import lw_state
        flag = (lw_state.load_npc(base) or {}).get('follower')
        return isinstance(flag, int) and not isinstance(flag, bool) and flag > 0
    except Exception:
        return False


def _present(prep, ids) -> bool:
    return bool(_matches(prep['present'], ids))


def _in_wipe(w: dict, ids) -> bool:
    """Whether this person is in a wipe's scope list: per person (people) in new wipes; older wipes kept one flat list
    of ids, compared by id."""
    people = w.get('people')
    if isinstance(people, list):
        return any(isinstance(m, list) and W.ident_match(ids, set(m)) for m in people)
    strong = {i for i in ids if not str(i).startswith('n:')} or set(ids)
    return bool(strong & set(w.get('members') or []))


def _prepare(store) -> list[dict]:
    """The log's events with who was there, towns and holds worked out; events of a save line the player went back
    from (worldlog.usable) are left out: they did not happen in the loaded save."""
    log = W.read_log(store)
    branch = W.branch_of(store)
    line = (branch.seq, branch.id, branch.parent, len(branch.gone), getattr(branch, 'days', None)) if branch is not None else None
    cache_key = (getattr(store, 'root', ''), log.get('version'), len(log['events']), line)
    hit = _index.get(cache_key)
    if hit is not None:
        return hit
    people = W.read_people(store)
    out = []
    for e in log['events'][-MAX_SCAN * 2:]:
        if not isinstance(e, dict) or not e.get('id') or not W.usable(e, branch):
            continue
        towns, holds = set(), set()
        if e.get('place', {}).get('town'):
            towns.add(W.norm(e['place']['town']))
        if e.get('place', {}).get('hold'):
            holds.add(e['place']['hold'])
        for p in e.get('involved') or []:  # news of a person travels to their own town too
            entry = W.lookup(people, p) or {}
            if entry.get('town'):
                towns.add(W.norm(entry['town']))
            if entry.get('hold'):
                holds.add(entry['hold'])
        for t in list(towns):
            h = W.hold_of_place(t)
            if h:
                holds.add(h)
        there = [p for p in (e.get('present') or []) + (e.get('involved') or [])  # those it happened to were there too
                 if isinstance(p, dict) and p.get('key') != W.PLAYER]
        known = _by_ident((_key_idents(key, k), key) for key, k in (e.get('known') or {}).items() if isinstance(k, dict))
        out.append({'e': e, 'towns': towns, 'holds': holds, 'present': _by_ident((_ids(p), p) for p in there), 'people': there,
                    'known': known})
    _index.clear()
    _index[cache_key] = out
    return out


def _wipes(e) -> list[dict]:
    return [w for w in e.get('wipes') or [] if isinstance(w, dict)]


def _entry_for(prep, ids) -> tuple[str, dict] | tuple[None, None]:
    """This person's known entry of the event (worldlog.ident_match), else (None, None)."""
    for key in _matches(prep['known'], ids):
        k = (prep['e'].get('known') or {}).get(key)
        if isinstance(k, dict):
            return key, k
    return None, None


def _blocked_entry(k: dict | None) -> bool:
    return bool(k) and W._int(k.get('wiped'), -1) > W._int(k.get('reentry'), -1)


def inside_wipe(e: dict, ids: set, town: str, reentry: int = -1) -> dict | None:
    """The newest wipe of this event whose scope holds this person (listed, or the wiped town is theirs), made after
    the last time it came back to them; else None."""
    found = None
    for w in _wipes(e):
        if W._int(w.get('seq'), 0) <= reentry:
            continue
        if _in_wipe(w, ids) or (w.get('town') and town and W.norm(w['town']) == W.norm(town)):
            if found is None or W._int(w.get('seq')) > W._int(found.get('seq')):
                found = w
    return found


def knowers(prep) -> dict:
    """Everyone who knows the event now and is not wiped (those present, and those it reached), as a _by_ident index of
    (since, name). Find one person in it with _knows."""
    e = prep['e']
    out = []
    for p in prep['people']:
        ids = _ids(p)
        key, k = _entry_for(prep, ids)
        if _blocked_entry(k):
            continue
        if any(_in_wipe(w, ids) and W._int(w.get('seq')) > W._int((k or {}).get('reentry'), -1) for w in _wipes(e)):
            continue
        out.append((ids, (W._float(e.get('day')), p.get('name') or '')))
    for key, k in (e.get('known') or {}).items():
        if not isinstance(k, dict) or _blocked_entry(k):
            continue
        out.append((_key_idents(key, k), (W._float(k.get('since'), W._float(e.get('day'))), k.get('name') or '')))
    return _by_ident(out)


def _knows(who, ids) -> tuple[float, str] | None:
    """(since, name) of the earliest knower in who (knowers) who is this person, else None."""
    hits = _matches(who, ids)
    return min(hits, key=lambda h: h[0]) if hits else None


def _short(text: str, limit: int) -> str:
    text = ' '.join(str(text or '').split())
    first = re.split(r'(?<=[.!?])\s', text, maxsplit=1)[0]
    if len(first) <= limit:
        return first
    cut = first[:limit].rsplit(' ', 1)[0]
    return cut.rstrip(',;:') + '...'


def news_text(e: dict, ring: int, town: str = '', named: bool = False) -> str:
    """What the NPC is given: the public text (ring 1 and 2), shortened and vaguer for rings 3 and 4. town: the
    listener's own town (ring 3 is always theirs). named: a witness who knows the player personally saw who it was
    under the hood (an event with named_text)."""
    if named and ring == 1 and e.get('named_text'):
        return e['named_text']
    public = e.get('public_text') or ''
    if not public:
        return ''
    place = e.get('place') or {}
    if ring <= 2:
        return public
    if ring == 3:
        where = f"people in {town or place.get('town')}" if (town or place.get('town')) else 'people around town'
        return f"{where} are saying: {_short(public, 160)}"
    origin = place.get('town') or place.get('location')
    return f"word has come from {origin}: {_short(public, 110)}" if origin else f"word has come from elsewhere in the hold: {_short(public, 110)}"


def _evaluate(prep, me: dict, ids: set, ties: list, now: float, with_people=(), horizon: float | None = None) -> dict | None:
    """How (and when) this event reaches me by now: {ring, due, by, source}, or None. ring 0 = came back into a wiped
    scope from someone in this talk. horizon: the latest game time an event may have and still count as past (now
    when not given)."""
    e = prep['e']
    if e.get('retracted') or not e.get('public_text') or e.get('kind') in W.NEVER_NEWS_KINDS:
        return None
    day = W._float(e.get('day'))
    if day > max(now, horizon if horizon is not None else now) + 0.001:
        return None
    if (me.get('minor') or me.get('unconfirmed')) and e.get('kind') in W.NO_CHILD_KINDS:
        return None
    key, k = _entry_for(prep, ids)
    if k is not None and not _blocked_entry(k):
        return None  # knows it already
    private = e.get('kind') in W.PRIVATE_KINDS  # what happens between two people is never passed on as news
    wipe = inside_wipe(e, ids, me.get('town', ''), W._int((k or {}).get('reentry'), -1))
    if wipe is not None or _blocked_entry(k):
        for other in with_people or ():
            o_ids = _ids(other)
            if not o_ids or W.ident_match(o_ids, ids):
                continue
            o_key, o_k = _entry_for(prep, o_ids)
            who = knowers(prep)
            if not _knows(who, o_ids) or inside_wipe(e, o_ids, other.get('town', ''), W._int((o_k or {}).get('reentry'), -1)):
                continue
            return {'ring': 0, 'due': now, 'by': other.get('name', ''), 'source': 'told'}
        return None
    age = now - day
    if _present(prep, ids) and not (k and _blocked_entry(k)):
        if age <= MAX_AGE[1]:
            return {'ring': 1, 'due': day, 'by': '', 'source': 'seen'}
    if private:
        return None
    who = knowers(prep)
    best = None
    if age <= MAX_AGE[2]:
        for t in ties:
            hit = _knows(who, t['_ids'] if '_ids' in t else _ids(W.person(t.get('name'), t.get('base'))))
            if hit is None:
                continue
            due = hit[0] + RING2_DAYS + RING2_SPREAD * W.jitter(me.get('key'), e['id'], 2)
            if due <= now and (best is None or due < best['due']):
                best = {'ring': 2, 'due': due, 'by': t.get('name') or hit[1], 'source': 'told'}
    if best:
        return best
    if not who:
        return None
    town = W.norm(me.get('town'))
    big = e.get('size') == 'big'
    if town and town in prep['towns'] and age <= (BIG_RING3_AGE if big else MAX_AGE[3]):
        due = day + RING3_DAYS + RING3_SPREAD * W.jitter(me.get('key'), e['id'], 3)
        if due <= now:
            return {'ring': 3, 'due': due, 'by': '', 'source': 'rumour'}
    if big and me.get('hold') and me['hold'] in prep['holds'] and age <= MAX_AGE[4]:
        due = day + RING4_DAYS + RING4_SPREAD * W.jitter(me.get('key'), e['id'], 4)
        if due <= now:
            return {'ring': 4, 'due': due, 'by': '', 'source': 'rumour'}
    return None


HOW = {0: 'told', 1: 'seen', 2: 'told', 3: 'rumour', 4: 'hearsay'}


def _context_with_store(store, context):
    context = dict(context or {})
    context.setdefault('store', store)
    return context


def catch_up(store, npc, now_day, context=None) -> list[dict]:
    """At talk start, for one NPC in the talk: every logged event that should have reached them by now_day (game days)
    and has not, added as a memory (at most MAX_PER_TALK, most important first). context: {speakers (the game's
    speaker dicts), people ([(Mantella name, ref)]), with (the other people in this talk, identify() results),
    ties, max, horizon (see _evaluate)}. Returns [{id, ring, how, by, memory}]. Never raises."""
    try:
        memory = _memory()
        if store is None or memory is None or now_day is None:
            return []
        now = W._float(now_day, -1.0)
        if now < 0:
            return []
        context = _context_with_store(store, context)
        ties_data = context.get('ties') if isinstance(context.get('ties'), dict) else W.load_ties()
        people = W.read_people(store)
        me = npc if isinstance(npc, dict) and npc.get('key') else W.identify(npc, context, people, ties_data)
        if not me.get('name') or not me.get('ref') or me.get('key') == W.PLAYER:
            return []
        prepared = _prepare(store)
        if not prepared:
            return []
        version = W.read_log(store).get('eversion')
        cache = (getattr(store, 'root', ''), W.known_key(me), version, int(now * 24),
                 tuple(sorted(p.get('key', '') for p in context.get('with') or [])))
        if cache in _seen:
            return []
        ids = _ids(me)
        ties = _tie_ids(W.ties_for(me, ties_data, people))
        found = []
        for prep in reversed(prepared[-MAX_SCAN:]):
            how = _evaluate(prep, me, ids, ties, now, context.get('with') or (), W._float(context.get('horizon'), now))
            if how:
                found.append((prep['e'], how))
        found.sort(key=lambda pair: (pair[0].get('size') != 'big', pair[1]['ring'], -W._float(pair[0].get('importance')),
                                     -W._float(pair[0].get('day'))))
        limit = W._int(context.get('max'), MAX_PER_TALK)
        delivered = []
        knows = context.get('knows')
        for e, how in found[:limit]:
            named = bool(e.get('masked') and callable(knows) and knows(me.get('name'), me.get('ref')))
            text = news_text(e, how['ring'] or 2, me.get('town', ''), named)
            if not text:
                continue
            if how['ring'] == 1 and now - W._float(e.get('day')) <= FRESH_DAYS:
                _fresh[me['name']] = (f"({me['name']} saw this happen a short while ago, and it is still on "
                                      f"{me['name']}'s mind: {text})")
            due = how['due']
            day = int(due) + _mantella_day() if due >= 0 else None
            hour = int((due - int(due)) * 24) if due >= 0 else -1
            importance = W._float(e.get('importance'), 0.4) - (0.1 if how['ring'] >= 3 else 0)
            close_death = how['ring'] in (1, 2) and close_to_dead(e, me, ties)
            mem_id = memory.add_memory(store, me['name'], me['ref'], text, source=how['source'], told_by=how['by'],
                                       day=day, hour=hour, importance=max(0.1, importance), key=NEWS_KEY + e['id'],
                                       kind='knowledge', tags=['news', e.get('kind', '')],
                                       flags={'unrecognised': bool(e.get('masked')) and not named, 'death_close': close_death})
            delivered.append({'id': e['id'], 'ring': how['ring'], 'how': HOW[how['ring']], 'by': how['by'], 'memory': mem_id,
                              'since': due, 'text': text})
        if delivered:
            _mark_known(store, me, delivered)
        version = W.read_log(store).get('eversion')
        _seen[(cache[0], W.known_key(me), version, int(now * 24), cache[4])] = True
        if len(_seen) > 5000:
            _seen.clear()
        return delivered
    except Exception as e:
        logger.warning(f"Living World: world news could not be passed on ({e})")
        return []


def fresh_text(names) -> str:
    """The lines for the newest message: what each NPC here saw happen a short while ago (catch_up), once."""
    return '\n'.join(line for line in (_fresh.pop(n, '') for n in names or []) if line)


def _mark_known(store, me: dict, delivered: list[dict]) -> None:
    def apply(log):
        changed = False
        for d in delivered:
            e = next((x for x in log['events'] if x.get('id') == d['id']), None)
            if e is None:
                continue
            known = e.setdefault('known', {})
            # this individual's own entry only: another NPC sharing their base id (a guard) keeps theirs
            old_key = next((k for k, v in known.items() if isinstance(v, dict) and W.ident_match(_ids(me), _key_idents(k, v))), None)
            old = known.pop(old_key, None) if old_key else None
            entry = {'how': d['how'], 'since': d['since'], 'by': d['by'], 'mem': d['memory'], 'name': me['name'],
                     'ref': me['ref'], 'base': me.get('base', ''), 'town': me.get('town', ''), 'text': d.get('text', '')}
            top = max([W._int(w.get('seq')) for w in _wipes(e)] or [-1])
            if old or d['ring'] == 0 or d.get('reentry'):
                entry['reentry'] = top
            if old and old.get('wiped') is not None:
                entry['wiped'] = old['wiped']
            known[W.known_key(me)] = entry
            changed = True
        return changed
    W.change_log(store, apply, events_changed=False)


TALK_GAP = 600  # seconds: without the game's talk id, the same people asked again within this are the same talk
_talks: dict = {}


def _new_talk(store, characters) -> bool:
    """True once per talk: by the game's talk id (MLW_Timeline) when there is one, else by the same people within
    TALK_GAP seconds. News is only added at the start of a talk, so the NPC's prompt stays the same all talk."""
    import time
    refs = tuple(sorted(W.ref_key(getattr(c, 'ref_id', None) or (c.get('ref_id') if isinstance(c, dict) else '')) for c in characters))
    talk = ''
    try:
        from . import contracts, lw_state
        data = contracts.game_flat(lw_state._read('conversation.json'))  # keys without case (Papyrus strings)
        if data.get('talk_open') == 1 and isinstance(data.get('talk_id'), str):
            talk = data['talk_id'].strip()
    except Exception:
        talk = ''
    key = (getattr(store, 'root', ''), refs)
    last = _talks.get(key)
    now = time.time()
    if talk:  # the greeting goes out before the game writes the talk id: that request and this one are one talk
        new = not last or (last[0] != talk and not (last[0] == '' and now - last[1] <= TALK_GAP))
    else:
        new = not last or bool(last[0]) or now - last[1] > TALK_GAP
    _talks[key] = (talk, now)
    if len(_talks) > 500:
        _talks.clear()
    return new


def talk_over() -> None:
    """A talk ended (its memory was saved): the next start of a talk, even with the same people a minute later, is a new
    talk. The game's talk id is not there yet when a talk's first request goes out, so it cannot tell them apart."""
    _talks.clear()


def _clock(today, game_days=None) -> tuple[float, float]:
    """(now, horizon) in game days from the game's whole day: now is Mantella's own clock while it fits that day
    (command.current_time), else the day itself; horizon is the end of that day, so an event logged earlier today is
    never taken for one from the future. game_days: Mantella's time of this request (GameDaysPassed + 1), when the
    server gave it: the game's day file can still hold the last talk's day at a talk's first request, so this wins."""
    fresh = W._float(game_days, -1.0)
    if fresh >= 1.0:
        now = fresh - 1.0
        return now, now
    now = W._float(today, 0.0)
    try:
        from . import command
        clock = command.current_time(int(now))
        if clock is not None:
            now = float(clock)
    except Exception:
        pass
    return now, max(now, int(W._float(today, 0.0)) + 0.999)


def talk_start(store, characters, today=None, context=None, force: bool = False) -> int:
    """The one call at talk start (safe to call on every request: it acts once per talk, see _new_talk): reads other
    parts' files into the log (worldlog.ingest), remembers who is here, and catches every NPC in the talk up on the
    news. today: the game day (lw_state.load_today) when not given. Returns how many news memories were added. Never
    raises."""
    try:
        if store is None or not characters:
            return 0
        from . import lw_state
        context = dict(context or {})
        speakers = context.get('speakers')
        if speakers is None:
            speakers = lw_state.load_conversation()
        player = context.get('player') or lw_state.load_player_name() or ''
        if not force and not _new_talk(store, characters):
            W.ingest(store, player, speakers)  # what happens during the talk is logged now (cheap: once per file change)
            return 0
        today = today if today is not None else lw_state.load_today()
        if today is None and context.get('game_days') is None:
            return 0
        now, horizon = _clock(today, context.get('game_days'))
        context.setdefault('horizon', horizon)
        people_pairs = [(getattr(c, 'name', None) or (c.get('name') if isinstance(c, dict) else ''),
                         getattr(c, 'ref_id', None) or (c.get('ref_id') if isinstance(c, dict) else ''))
                        for c in characters]
        context.update(speakers=speakers, people=people_pairs, player=player, store=store)
        context.setdefault('ties', W.load_ties())
        W.ingest(store, player, speakers)
        here = [W.identify(c, context, None, context['ties']) for c in characters]
        W.note_people(store, here, now)
        count = 0
        for me in here:
            others = [o for o in here if o is not me]
            count += len(catch_up(store, me, now, dict(context, **{'with': others})))
        return count
    except Exception as e:
        logger.warning(f"Living World: world news at talk start failed ({e})")
        return 0


# --- "Knows about" (the NPC page) --------------------------------------------------------------------------------------

def _resolve(store, npc, context=None) -> dict:
    if isinstance(npc, dict) and npc.get('key'):
        return npc
    return W.identify(npc, _context_with_store(store, context), None, W.load_ties())


def known_events(store, npc, now_day=None, context=None) -> list[dict]:
    """The events this NPC knows and how: [{id, kind, day, text, how (seen / told / rumour / hearsay / own), by, since,
    wiped (True when it was taken from them)}], newest first. Includes events they were present at."""
    me = _resolve(store, npc, context)
    ids = _ids(me)
    out = []
    for prep in reversed(_prepare(store)):
        e = prep['e']
        if e.get('retracted'):
            continue
        key, k = _entry_for(prep, ids)
        present = _present(prep, ids)
        if k is None and not present:
            continue
        wiped = _blocked_entry(k) or bool(inside_wipe(e, ids, me.get('town', ''), W._int((k or {}).get('reentry'), -1))
                                            and (present or k is not None) and _member(e, ids, k))
        out.append({'id': e['id'], 'kind': e.get('kind'), 'day': e.get('day'), 'text': e.get('public_text') or e.get('true_text'),
                    'true_text': e.get('true_text'), 'how': (k or {}).get('how', 'seen'), 'by': (k or {}).get('by', ''),
                    'since': (k or {}).get('since', e.get('day')), 'wiped': wiped})
    return out


def _member(e, ids, k) -> bool:
    reentry = W._int((k or {}).get('reentry'), -1)
    return any(_in_wipe(w, ids) and W._int(w.get('seq')) > reentry for w in _wipes(e))


def who_knows(store, event_id: str) -> list[dict]:
    """[{name, ref, how, by, since, wiped}] for one event: those present and those it reached."""
    e = W.find(store, event_id)
    if e is None:
        return []
    out, seen = [], []
    for key, k in (e.get('known') or {}).items():
        if not isinstance(k, dict):
            continue
        out.append({'key': key, 'name': k.get('name', ''), 'ref': k.get('ref', ''), 'how': k.get('how', 'seen'),
                    'by': k.get('by', ''), 'since': k.get('since'), 'wiped': _blocked_entry(k)})
        seen.append(_key_idents(key, k))
    for p in (e.get('present') or []) + (e.get('involved') or []):
        if p.get('key') == W.PLAYER or any(W.ident_match(_ids(p), s) for s in seen):
            continue
        wiped = any(_in_wipe(w, _ids(p)) for w in _wipes(e))
        out.append({'key': p['key'], 'name': p.get('name', ''), 'ref': p.get('ref', ''), 'how': 'seen', 'by': '',
                    'since': e.get('day'), 'wiped': wiped})
    return out


def tell_event(store, npc, event_id: str, told_by: str = '', now_day=None, context=None) -> str:
    """The Hub user tells an NPC about an event now (also inside a wiped scope): one memory, told by told_by (or plainly
    told). Returns the memory id ('' when nothing was added)."""
    memory = _memory()
    e = W.find(store, event_id)
    me = _resolve(store, npc, context)
    if memory is None or e is None or e.get('retracted') or not me.get('name') or not me.get('ref'):
        return ''
    if (me.get('minor') or me.get('unconfirmed')) and e.get('kind') in W.NO_CHILD_KINDS:
        return ''
    text = e.get('public_text') or ''
    if not text:
        return ''
    if now_day is None:
        try:
            from . import lw_state
            now_day = lw_state.load_today()
        except Exception:
            now_day = None
    day = int(now_day) + _mantella_day() if now_day is not None else None
    # a key of its own: an earlier delivery (since wiped) keeps its key, so this one must not collide with it
    seq = max([W._int(w.get('seq')) for w in _wipes(e)] or [0])
    mem_id = memory.add_memory(store, me['name'], me['ref'], text, source='told', told_by=told_by, day=day,
                               importance=W._float(e.get('importance'), 0.4), key=f"{NEWS_KEY}{e['id']}#{seq}",
                               kind='knowledge', tags=['news', e.get('kind', '')], flags={'unrecognised': bool(e.get('masked'))})
    _mark_known(store, me, [{'id': e['id'], 'ring': 0, 'how': 'told', 'by': told_by, 'memory': mem_id,
                             'since': W._float(now_day, W._float(e.get('day'))), 'text': text, 'reentry': True}])
    return mem_id


def forget_event(store, npc, event_id: str, by: str = 'Hub', context=None) -> dict:
    """Makes one NPC forget an event (hidden, can be given back with undo_wipe) and stops it reaching them again."""
    return apply_wipe(store, 'npc', npc, event_id=event_id, by=by, context=context)


# --- command scopes ----------------------------------------------------------------------------------------------------

RELATIONS = {'brother': ('sibling',), 'sister': ('sibling',), 'sibling': ('sibling',), 'siblings': ('sibling',),
             'husband': ('spouse',), 'wife': ('spouse',), 'spouse': ('spouse',),
             'son': ('child',), 'daughter': ('child',), 'children': ('child',), 'kids': ('child',), 'child': ('child',),
             'mother': ('parent',), 'father': ('parent',), 'parents': ('parent',), 'mum': ('parent',), 'dad': ('parent',),
             'boss': ('works_for',), 'employer': ('works_for',), 'master': ('works_for',),
             'workers': ('employs',), 'employees': ('employs',), 'servants': ('employs',),
             'household': ('household', 'spouse', 'child', 'parent', 'sibling'),
             'family': ('spouse', 'child', 'parent', 'sibling', 'cousin', 'household'),
             'cousin': ('cousin',), 'cousins': ('cousin',), 'lover': ('courting',), 'suitor': ('courting',)}

_PRESENT = re.compile(r"\b(?:every(?:one|body)|all(?: of them| those| who| people)?|anyone|those)\s+(?:who (?:was|were) "
                      r"(?:there|present|here)|who (?:saw|witnessed|heard) (?:it|this|that)|present|here|in (?:this|the) room|that "
                      r"(?:was|were) there|nearby|around)\b|\b(?:the )?witnesses\b", re.I)
_TOWN = re.compile(r"\b(?i:every(?:one|body)|all(?: the people)?|anyone|the whole|people)\s+(?i:(?:living )?in|of|from)\s+"
                   r"((?:the )?(?:[A-Z][\w'-]+)(?:\s+[A-Z][\w'-]+)?)")
NOT_TOWNS = {'skyrim', 'tamriel', 'the world', 'world', 'the room', 'room', 'here', 'there', 'town'}
_THIS_TOWN = re.compile(r"\b(?:the whole (?:town|village|city)|every(?:one|body) in (?:town|the village|the city|this town|"
                        r"this village|this city)|the (?:town|village|city) (?:too|as well))\b", re.I)
_EVERYONE = re.compile(r"\b(?:every(?:one|body)|anyone|all|whoever)\s+(?:who|that)\s+(?:knows?|heard|has heard|learned|"
                       r"found out)\b|\bthe whole world\b|\bno one (?:else )?(?:will )?remember", re.I)
_BARE_EVERYONE = re.compile(r"\b(?:every(?:one|body)|all of skyrim)\b", re.I)
_CIRCLE = re.compile(r"\b(?:her|his|their|your)\s+(?:own\s+)?(" + '|'.join(sorted(RELATIONS, key=len, reverse=True))
                     + r")\b|\b(?:her|his|their|your) (?:circle|people|loved ones|kin|friends and family)\b", re.I)


def parse_scope(text: str, known_towns=()) -> dict:
    """The scope an Absolute Command's words give, without a model: {scope: present / town / circle / everyone /
    unknown, town, relation, kinds}. 'unknown' when the words name none (the caller keeps today's behaviour: only the
    NPCs in the talk)."""
    text = str(text or '')
    out = {'scope': 'unknown', 'town': '', 'relation': '', 'kinds': []}
    if _PRESENT.search(text):
        out['scope'] = 'present'
        return out
    match = _TOWN.search(text)
    if match:
        name = re.sub(r'^the\s+', '', match.group(1).strip(), flags=re.I)
        words = name.split()
        towns = {W.norm(t): t for t in known_towns or ()}
        town = (towns.get(W.norm(name)) or W.town_of_place(name) or (towns.get(W.norm(words[0])) if words else '')
                or (W.town_of_place(words[0]) if words else '') or name)
        if words and W.norm(town) not in NOT_TOWNS:
            out.update(scope='town', town=town)
            return out
    if _THIS_TOWN.search(text):
        out['scope'] = 'town'
        return out
    if _EVERYONE.search(text):
        out['scope'] = 'everyone'
        return out
    match = _CIRCLE.search(text)
    if match:
        word = (match.group(1) or 'family').lower()
        out.update(scope='circle', relation=word, kinds=list(RELATIONS.get(word, RELATIONS['family'])))
        return out
    if _BARE_EVERYONE.search(text):
        out['scope'] = 'everyone'
    return out


_DAYS = re.compile(r"\bbetween day\s*(\d+)\s*(?:and|to|-)\s*(?:day\s*)?(\d+)\b|\bfrom day\s*(\d+)\s*(?:to|until)\s*(?:day\s*)?(\d+)\b", re.I)
_LAST = re.compile(r"\b(?:the )?(?:last|past)\s+(\d+|one|two|three|four|five|six|seven|ten)\s+days?\b", re.I)
_SINCE_YESTERDAY = re.compile(r"\b(?:since yesterday|yesterday)\b", re.I)
_TODAY = re.compile(r"\btoday\b", re.I)
_NUM = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'ten': 10}


def parse_days(text: str, today: int | None) -> tuple[int, int] | None:
    """A day range from the words ("between day 12 and 40", "the last 3 days", "yesterday", "today"), game days."""
    text = str(text or '')
    m = _DAYS.search(text)
    if m:
        a, b = [int(x) for x in m.groups() if x is not None][:2]
        return (min(a, b), max(a, b))
    if today is None:
        return None
    m = _LAST.search(text)
    if m:
        n = _NUM.get(m.group(1).lower()) or int(m.group(1)) if not m.group(1).isdigit() else int(m.group(1))
        return (today - n, today)
    if _SINCE_YESTERDAY.search(text):
        return (today - 1, today)
    if _TODAY.search(text):
        return (today, today)
    return None


def _person_file(people, p, prep_known=None) -> dict:
    """A person with a memory file (Mantella name and ref) when one is known."""
    entry = W.lookup(people, p) or {}
    out = dict(p)
    out['name'] = (prep_known or {}).get('name') or entry.get('mname') or p.get('name') or entry.get('name', '')
    out['ref'] = p.get('ref') or (prep_known or {}).get('ref') or entry.get('ref', '')
    out['base'] = p.get('base') or entry.get('base', '')
    out['town'] = entry.get('town', '') or (prep_known or {}).get('town', '')
    out['key'] = out['base'] or out.get('key')
    return out


def scope_members(store, e: dict, scope: str, me: dict | None, kinds=(), town: str = '') -> list[dict]:
    """The people a scope covers for one event (see SCOPES), each with name / ref where known."""
    people = W.read_people(store)
    out = []

    def add(p, k=None):
        if not isinstance(p, dict) or p.get('key') == W.PLAYER:
            return
        full = _person_file(people, p, k)
        if (full.get('key') or full.get('name')) and not any(W.same(full, o) for o in out):
            out.append(full)
    if me and scope in ('npc', 'circle', 'present'):
        add(me)
    if scope == 'present' and e:
        for p in (e.get('present') or []) + (e.get('involved') or []):
            add(p)
    elif scope == 'circle' and me:
        for t in W.ties_for(me, W.load_ties(), people):
            if kinds and t['kind'] not in kinds:
                continue
            add(W.person(t.get('name'), t.get('base')))
    elif scope == 'town':
        town = town or (me or {}).get('town') or ((e or {}).get('place') or {}).get('town') or ''
        if town:
            for key, entry in people.items():
                if isinstance(entry, dict) and W.norm(entry.get('town')) == W.norm(town):
                    add(W.person(entry.get('mname') or entry.get('name'), entry.get('base'), entry.get('ref')))
            for key, k in ((e or {}).get('known') or {}).items():
                if isinstance(k, dict) and W.norm(k.get('town')) == W.norm(town):
                    add(W.person(k.get('name'), k.get('base') or (key if re.fullmatch(r'[0-9A-F]{6}', key) else ''), k.get('ref')), k)
            for p in ((e or {}).get('present') or []) + ((e or {}).get('involved') or []):
                entry = W.lookup(people, p) or {}
                if W.norm(entry.get('town') or ((e or {}).get('place') or {}).get('town')) == W.norm(town):
                    add(p)
    elif scope == 'everyone' and e:
        for p in (e.get('present') or []) + (e.get('involved') or []):
            add(p)
        for key, k in (e.get('known') or {}).items():
            if isinstance(k, dict):
                add(W.person(k.get('name'), k.get('base') or (key if re.fullmatch(r'[0-9A-F]{6}', key) else ''), k.get('ref')), k)
        if me:
            add(me)
    return out


def _hide_event_for(store, memory, e: dict, member: dict, by: str, note: str) -> list[dict]:
    """Hides this person's memory of the event: the news memory by its id, and, when they remember it from the talk
    itself, the closest memory to its text (sure matches only)."""
    if not member.get('name') or not member.get('ref'):
        return []
    known = e.get('known') or {}
    k = next((v for key, v in known.items() if isinstance(v, dict) and W.ident_match(_ids(member), _key_idents(key, v))), None)
    hidden = []
    if k and k.get('mem'):
        found = memory.hide_matching(store, member['name'], member['ref'], k.get('text') or e.get('public_text') or '',
                                     limit=1, by=by, note=note, only={k['mem']})
        hidden += found
    elif e.get('public_text') or e.get('true_text'):
        found = memory.hide_matching(store, member['name'], member['ref'], e.get('public_text') or e.get('true_text'),
                                     limit=1, by=by, note=note)
        hidden += found
    return [{'name': member['name'], 'ref': member['ref'], 'id': h['id']} for h in hidden if h.get('id')]


def _wipe_events(store, memory, event_ids, scope, me, kinds, town, by, note, day) -> tuple[list, list]:
    """One wipe per event: hides the memories, records the scope. Returns (wipes, members)."""
    wipes, everyone = [], []
    for event_id in event_ids:
        e = W.find(store, event_id)
        if e is None:
            continue
        members = scope_members(store, e, scope, me, kinds, town)
        hidden = []
        for m in members:
            hidden += _hide_event_for(store, memory, e, m, by, note)
        _now_back(store, hidden, W._float(e.get('day')))
        wipe_town = (town or (me or {}).get('town') or (e.get('place') or {}).get('town') or '') if scope == 'town' else ''
        member_ids = sorted(set().union(*[W.idents(m) for m in members])) if members else []
        member_people = [sorted(_ids(m)) for m in members]  # per person: guards sharing a base id stay apart

        def apply(log, e_id=event_id):
            target = next((x for x in log['events'] if x.get('id') == e_id), None)
            if target is None:
                return False
            log['seq'] = W._int(log.get('seq')) + 1
            wipe = {'id': f"w{log['seq']}", 'seq': log['seq'], 'scope': scope, 'members': member_ids, 'people': member_people,
                    'town': wipe_town,
                    'day': day, 'by': by, 'note': note, 'hidden': hidden}
            target.setdefault('wipes', []).append(wipe)
            known = target.setdefault('known', {})
            for m in members:
                key = next((k for k, v in known.items() if isinstance(v, dict) and W.ident_match(_ids(m), _key_idents(k, v))), None)
                if key is None:
                    if not any(W.same(m, p) for p in (target.get('present') or []) + (target.get('involved') or [])):
                        continue
                    key = W.known_key(m) or W.person(m.get('name'), m.get('base'), m.get('ref'))['key']
                    known[key] = {'how': 'seen', 'since': target.get('day'), 'by': '', 'mem': '', 'name': m.get('name', ''),
                                  'ref': m.get('ref', ''), 'base': m.get('base', ''), 'town': m.get('town', '')}
                known[key]['wiped'] = log['seq']
            wipes.append(dict(wipe, event=e_id))
            return True
        W.change_log(store, apply)
        everyone += [m for m in members if not any(W.same(m, o) for o in everyone)]
    return wipes, everyone


def apply_wipe(store, scope: str, npc=None, event_id: str = '', day_from=None, day_to=None, kinds=(), town: str = '',
               by: str = 'Absolute Command', note: str = '', player: str = '', context=None, now_day=None) -> dict:
    """Takes an event (event_id), or everything about the player between game days day_from and day_to, from a scope:
    'npc' (this NPC), 'present' (those at the event), 'circle' (the NPC and their ring 2; kinds narrows it, e.g.
    ('sibling',) for "her brother"), 'town' (town, else the NPC's, else the event's), 'everyone' (everyone who knows).
    Works on absent NPCs through their memory files. Memories are hidden (memory.hide_matching), never deleted, and
    undo_wipe gives them back. The event stops spreading inside the scope (see the re-entry rule above).
    Returns {events, wipes, targets, hidden}. Never raises."""
    report = {'events': [], 'wipes': [], 'targets': [], 'hidden': 0}
    try:
        memory = _memory()
        if store is None or memory is None or scope not in SCOPES:
            return report
        me = _resolve(store, npc, context) if npc is not None else None
        if scope in ('npc', 'circle') and not me:
            return report
        if now_day is None:
            try:
                from . import lw_state
                now_day = lw_state.load_today()
            except Exception:
                now_day = None
        if event_id:
            ids = [event_id]
        elif day_from is not None and day_to is not None:
            a, b = W._float(day_from), W._float(day_to) + 1
            ids = [e['id'] for e in W.events(store) if not e.get('retracted') and a <= W._float(e.get('day')) < b
                   and any(p.get('key') == W.PLAYER for p in (e.get('involved') or []) + (e.get('present') or []))]
        else:
            return report
        wipes, members = _wipe_events(store, memory, ids, scope, me, kinds, town, by, note, now_day)
        report['events'] = [w['event'] for w in wipes]
        report['wipes'] = [w['id'] for w in wipes]
        report['hidden'] = sum(len(w['hidden']) for w in wipes)
        if not event_id and day_from is not None:
            # everything about the player in those days: their own memories too, not only logged events
            if not members:
                members = scope_members(store, None, scope if scope in ('npc', 'circle', 'town') else 'npc', me, kinds, town)
                if scope == 'present':
                    members += [W.identify(o, _context_with_store(store, context)) for o in (context or {}).get('with') or []]
            hidden = _hide_days(store, memory, members, W._int(day_from), W._int(day_to), by, note, player)
            if hidden:
                def apply(log):
                    log['seq'] = W._int(log.get('seq')) + 1
                    log.setdefault('day_wipes', []).append({'id': f"w{log['seq']}", 'seq': log['seq'], 'scope': scope,
                                                            'from': W._int(day_from), 'to': W._int(day_to), 'by': by,
                                                            'note': note, 'hidden': hidden})
                    report['wipes'].append(f"w{log['seq']}")
                    return True
                W.change_log(store, apply)
                report['hidden'] += len(hidden)
        report['targets'] = [m.get('name') for m in members if m.get('name')]
        return report
    except Exception as e:
        logger.warning(f"Living World: a memory wipe could not be applied ({e})")
        return report


def _hide_days(store, memory, members, day_from, day_to, by, note, player) -> list[dict]:
    """Hides each member's memories of talks with the player (not NPC-only talks) dated between those game days."""
    out = []
    first, last = day_from + _mantella_day(), day_to + _mantella_day()
    for m in members[:200]:
        if not m.get('name') or not m.get('ref'):
            continue
        try:
            with store.lock(m['name'], m['ref']):
                data = store.load(m['name'], m['ref'])
                store.sync_archive(m['name'], m['ref'], data)
                db = store.archive_for(m['name'], m['ref'])
                rows = [r for r in (db.rows() if db.exists() else [])
                        if first <= W._int(r.get('day'), -9) <= last and not r.get('radiant') and not r.get('hidden')]
        except Exception:
            continue
        for r in rows:
            found = memory.hide_matching(store, m['name'], m['ref'], r.get('text') or player or 'x', limit=1, by=by,
                                         note=note, only={r['id']})
            out += [{'name': m['name'], 'ref': m['ref'], 'id': h['id']} for h in found if h.get('id')]
    _now_back(store, out, day_from)
    return out


def _now_back(store, hidden: list[dict], game_day: float) -> None:
    """A wiped memory may already be in that NPC's Now paragraph (written from their memories): it goes back to a text
    from before that day and is written again from what they still remember (bio_evolve.roll_back), as a command's own
    forget does. Never raises."""
    if not hidden or game_day is None or W._float(game_day) < 0:
        return
    try:
        from . import bio_evolve
    except Exception:
        return
    day = int(W._float(game_day)) + _mantella_day()
    for name, ref in {(h['name'], h['ref']) for h in hidden if h.get('name') and h.get('ref')}:
        try:
            if bio_evolve.roll_back(store, name, ref, day):
                bio_evolve.mark_due(store, name, ref, 'some memories were taken away')
        except Exception as e:
            logger.warning(f"Living World: could not put back {name}'s Now paragraph after a wipe ({e})")


def undo_wipe(store, wipe_id: str) -> int:
    """Gives back what one wipe hid and lets the event reach that scope again. Returns memories given back."""
    memory = _memory()
    if memory is None:
        return 0
    found = {'hidden': [], 'seq': None}

    def apply(log):
        for e in log['events']:
            for w in list(e.get('wipes') or []):
                if w.get('id') == wipe_id:
                    found.update(hidden=list(w.get('hidden') or []), seq=w.get('seq'))
                    e['wipes'].remove(w)
                    for k in (e.get('known') or {}).values():
                        if isinstance(k, dict) and k.get('wiped') == w.get('seq'):
                            k.pop('wiped', None)
                    return True
        for w in list(log.get('day_wipes') or []):
            if w.get('id') == wipe_id:
                found.update(hidden=list(w.get('hidden') or []), seq=w.get('seq'))
                log['day_wipes'].remove(w)
                return True
        return False
    if not W.change_log(store, apply):
        return 0
    return sum(1 for h in found['hidden'] if memory.unhide(store, h['name'], h['ref'], h['id']))


def blocked_for(store, npc, event: dict, context=None) -> bool:
    """True when this event was wiped for this NPC (listed or inside a wiped town) and has not come back to them.
    Reputation, strangeness and anything else built on the log must skip such events."""
    me = _resolve(store, npc, context)
    ids = _ids(me)
    known = event.get('known') or {}
    k = next((v for key, v in known.items() if isinstance(v, dict) and W.ident_match(ids, _key_idents(key, v))), None)
    return _blocked_entry(k) or inside_wipe(event, ids, me.get('town', ''), W._int((k or {}).get('reentry'), -1)) is not None


def reached_events(store, npc, now_day, context=None) -> list[dict]:
    """Every event that has reached this NPC by now (known to them, or due by the rings even if not delivered yet
    because of the per-talk cap), never one wiped for them. For reputation."""
    try:
        me = _resolve(store, npc, context)
        ids = _ids(me)
        ties = _tie_ids(W.ties_for(me, W.load_ties(), W.read_people(store)))
        now = W._float(now_day, -1.0)
        out = []
        for prep in _prepare(store):
            e = prep['e']
            if e.get('retracted') or blocked_for(store, me, e):
                continue
            if (me.get('minor') or me.get('unconfirmed')) and e.get('kind') in W.NO_CHILD_KINDS:
                continue  # as with the news itself: never for a child or someone not yet confirmed an adult
            key, k = _entry_for(prep, ids)
            if k is not None or _present(prep, ids):
                out.append(e)
            elif now >= 0 and _evaluate(prep, me, ids, ties, now) is not None:
                out.append(e)
        return out
    except Exception as e:
        logger.warning(f"Living World: could not work out what has reached an NPC ({e})")
        return []


# --- one call for a new Absolute Command ---------------------------------------------------------------------------------

_WORD = re.compile(r"[a-z']{3,}")
# the same thing in other words, so "forget the wedding" finds "Sigrid has married Vega"
_SAME = {'wedding': 'married', 'marriage': 'married', 'marry': 'married', 'marries': 'married', 'wed': 'married',
         'murder': 'murdered', 'murders': 'murdered', 'killing': 'killed', 'kill': 'killed', 'kills': 'killed',
         'death': 'died', 'dead': 'died', 'dies': 'died', 'divorce': 'divorced', 'fighting': 'fight', 'fought': 'fight',
         'battle': 'fight', 'engagement': 'engaged'}


def _words(text: str) -> set:
    return {_SAME.get(w, w) for w in _WORD.findall(str(text or '').lower())}


def strip_scope(text: str) -> str:
    """The forget words without the part that names who else forgets ("and everyone in Riverwood too"), so only what
    is forgotten is matched against the log."""
    text = str(text or '')
    for pattern in (_PRESENT, _TOWN, _THIS_TOWN, _EVERYONE, _CIRCLE, _BARE_EVERYONE):
        text = pattern.sub(' ', text)
    for _ in range(3):  # "..., and too" -> "..."
        text = re.sub(r"[,;]?\s*\b(?:and|as well|too|also)\b\s*(?=[,.;]|$)", ' ', text.strip(), flags=re.I).strip()
    return ' '.join(text.split()).strip(' ,;.')


_STOP = {'the', 'and', 'that', 'what', 'with', 'about', 'from', 'this', 'they', 'them', 'their', 'happened', 'everything',
         'anything', 'all', 'you', 'your', 'saw', 'forget', 'remember', 'was', 'were', 'has', 'have', 'had', 'his', 'her',
         'forgets', 'forgot', 'too', 'also'}


def find_events(store, words: str, npc=None, limit: int = 3, context=None) -> list[dict]:
    """Logged events whose text shares the most words with words (a command's "forget" part): the best fits only (at
    least half the words), newest first; with npc,
    only events this NPC knows or was at. No model."""
    want = {w for w in _words(strip_scope(words)) if w not in _STOP}
    if not want:
        return []
    allowed = None
    if npc is not None:
        allowed = {x['id'] for x in known_events(store, npc, context=context)}
    scored = []
    for e in W.events(store):
        if e.get('retracted') or (allowed is not None and e['id'] not in allowed):
            continue
        have = _words(str(e.get('true_text')) + ' ' + str(e.get('public_text')))
        score = len(want & have) / len(want)
        if score >= 0.5:
            scored.append((score, W._float(e.get('day')), e))
    scored.sort(key=lambda t: (-t[0], -t[1]))
    best = scored[0][0] if scored else 0
    return [e for score, _, e in scored if score >= best][:limit]  # only the best fits: a partial match is never wiped


def apply_command_scope(store, record: dict, player: str = '', speakers=None, now_day=None, fallback: str = '') -> dict | None:
    """For a new Absolute Command (command.py record: text, forget, npcs): when its words give a scope beyond the NPCs
    in the talk ("and everyone in Riverwood", "everyone who was there", "her brother"), wipes the matching logged
    events (or, with a day range in the words, everything about the player in those days) from that scope, for each NPC
    it was given to. None when the words give no scope or nothing matches: the caller keeps today's behaviour (the
    command's own forget on the NPCs in the talk). fallback ('npc'): the scope used when the words name none, so the
    NPCs who forgot stop passing the event on and it no longer counts for what they believe about the player. Never
    raises."""
    try:
        if store is None or not isinstance(record, dict) or not record.get('text'):
            return None
        towns = [p.get('town') for p in W.read_people(store).values() if isinstance(p, dict) and p.get('town')]
        scope = parse_scope(record['text'], towns)
        if scope['scope'] == 'unknown' and fallback in SCOPES:
            scope['scope'] = fallback
        if scope['scope'] == 'unknown':
            return None
        days = parse_days(record['text'], int(now_day) if now_day is not None else None)
        context = {'speakers': speakers or [], 'store': store}
        total = {'scope': scope['scope'], 'events': [], 'wipes': [], 'targets': [], 'hidden': 0}
        npcs = [n for n in record.get('npcs') or [] if isinstance(n, dict) and n.get('name')]
        for n in npcs:
            me = W.identify({'name': n['name'], 'ref_id': n.get('ref_id'), 'base_id': n.get('base_id')}, context)
            if days is not None:
                parts = [apply_wipe(store, scope['scope'], me, day_from=days[0], day_to=days[1], kinds=scope['kinds'],
                                    town=scope['town'], by='Absolute Command', note=record['text'][:120], player=player,
                                    context=context, now_day=now_day)]
            else:
                found = find_events(store, record.get('forget') or '', me, 3, context)
                parts = [apply_wipe(store, scope['scope'], me, event_id=e['id'], kinds=scope['kinds'], town=scope['town'],
                                    by='Absolute Command', note=record['text'][:120], player=player, context=context,
                                    now_day=now_day) for e in found]
            for rep in parts:
                total['events'] += [x for x in rep['events'] if x not in total['events']]
                total['wipes'] += rep['wipes']
                total['targets'] += [t for t in rep['targets'] if t not in total['targets']]
                total['hidden'] += rep['hidden']
        return total if total['wipes'] else None
    except Exception as e:
        logger.warning(f"Living World: the scope of an absolute command could not be applied ({e})")
        return None
