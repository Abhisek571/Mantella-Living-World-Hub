"""The NPCs page: one page per NPC. Pick a save (your character) and an NPC, then see and change, in the order the
prompt sends them: the prompt preview, Personality (the bio), Background (facts at game start), Now (their situation as
they believe it), the facts history, Memories, Commands and what they know about the world.

The logic lives in the modules this page calls (ui_overrides, characters, bio_evolve, facts_history, memory, arcs,
release, npc_block); this file only shows it. The view and action functions are plain functions (no Gradio) so they can
be tested with a temporary save; build() wires them to the page. Nothing here changes the game: marriage, home,
follower status and faction membership come from the game, and text typed here is only what the NPC believes."""
import html
import logging
import os
import re
import shutil
import time

from . import (action_filter, archive, arcs, bio_evolve, bio_optimise, characters, command, contracts, embed, facts_history, lw_state, memory,
               memory_ui, npc_block, release, ui_help, ui_overrides)
from . import mod_facts

logger = logging.getLogger('Mantella')

# the files this page reads; None = the user's own (ui_overrides / memory_ui defaults, read when used, so tests can
# point them elsewhere)
CSV = None
OVERRIDES = None
PRESETS = None
CHARS = None

MAX_ROWS = 200  # memories shown in the table at once; search finds the rest
SOURCE_LABELS = {'seen': 'seen', 'told': 'told', 'rumour': 'rumour', 'own': 'own thought'}
STATE_LABELS = {'mind': 'in mind', 'older': 'older (comes back when the talk is about it)', 'hidden': 'hidden',
                'aside': 'set aside (made after the loaded save)', 'other': 'other timeline'}
CHOICE_LABELS = {release.CHOICE_TEXT[c].capitalize(): c for c in release.CHOICES}
MODE_LABELS = {'Leaves a gap (they notice something is missing)': 'gap', 'Clean (they notice nothing)': 'clean'}
ADD_FACTS = {'Custom line': 'custom', 'Belief: married to / dating': 'partner', 'Belief: home': 'home',
             'Belief: follower': 'follower', 'Role': 'role', 'Belief: member of': 'member_of'}
CAUSES = {'original': 'at start', 'game': 'the game', 'user': 'you'}
STATUS_LABELS = {'current': 'current', 'on_hold': 'on hold', 'ended': 'ended'}
NO_PICK = 'Pick an NPC first.'
EXACT_NOTE = ("Exact text last sent for this NPC (from the last reply this session where they were the only NPC "
              "in the talk).")
REBUILT_NOTE = ("Rebuilt now from the saved files, in the order sent. The real prompt can differ a little: the scene, "
                "other NPCs in the talk and the older memories a talk brings back.")
NO_REF_NOTE = ("No reference id known for them in this save yet: Now, facts history, memories and commands start after "
               "their first talk through Mantella. Personality and Background work already.")


# --- who ---------------------------------------------------------------------------------------------------------------

_listed: dict = {}  # (conversations dir, world) -> the last npc_list, so a click finds its NPC without reading again


def npc_list(conversations_dir, world, only_remember: bool = False, csv_path=None, overrides_dir=None,
             followers=None) -> list[dict]:
    """[{label, name, ref_id, has, custom, follower}]: NPCs who remember you in this save first, then everyone in
    Mantella's list with a reference id, then your own NPCs and followers that are in neither (no reference id yet).
    Only folder names and Mantella's csv are read; no memory file is opened."""
    csv_path = csv_path or CSV or ui_overrides.DEFAULT_CSV
    overrides_dir = overrides_dir or OVERRIDES or ui_overrides.DEFAULT_OVERRIDES
    followers = ui_overrides.followers_seen() if followers is None else followers
    people = memory_ui.people(conversations_dir, world, csv_path, followers) if world else []
    names = {p['name'].lower() for p in people}
    extra = []
    for row in ui_overrides.find_characters('', csv_path, overrides_dir, limit=None, followers=followers):
        if row['name'].lower() not in names:
            names.add(row['name'].lower())
            extra.append({'name': row['name'], 'ref_id': '', 'has': False, 'custom': row.get('_custom', False),
                          'follower': row.get('_follower', False), 'label': row['name']})
    everyone = people + extra
    _listed[(conversations_dir, world)] = everyone
    return [p for p in everyone if p['has']] if only_remember else everyone


def same_label(choices, label):
    """label as it is in choices, letter case aside (an override file "Lydia" for the game's "lydia"); None if absent."""
    if label in (choices or []):
        return label
    low = str(label or '').strip().lower()
    found = [c for c in choices or [] if str(c).strip().lower() == low]
    return found[0] if len(found) == 1 else None


def find_npc(conversations_dir, world, label) -> dict | None:
    """The NPC a Find NPC label stands for, letter case aside. A name with no reference id yet (picked before their
    first talk, or from an override file whose name differs only in case from the game's) is read again, and the one
    entry of that same name that has a reference id wins; two different NPCs sharing a name are never merged."""
    if not label:
        return None
    for fresh in (False, True):
        listing = _listed.get((conversations_dir, world))
        if fresh or listing is None:
            listing = npc_list(conversations_dir, world)
        chosen = same_label([p['label'] for p in listing], label)
        found = next((p for p in listing if p['label'] == chosen), None) if chosen is not None else None
        if found is None:
            continue
        if not found.get('ref_id'):
            low = found['name'].strip().lower()
            with_ref = [p for p in listing if p.get('ref_id') and p['name'].strip().lower() == low]
            if len(with_ref) == 1:
                return with_ref[0]
            if not fresh:
                continue  # the cached list may be from before their first talk
        return found
    return None


def character_row(p: dict, csv_path=None, overrides_dir=None) -> dict:
    """Their row in Mantella's character list with your override on top (bio, voice, race, base id), as Mantella sees
    it; a bare row for an NPC that is in neither."""
    csv_path = csv_path or CSV or ui_overrides.DEFAULT_CSV
    overrides_dir = overrides_dir or OVERRIDES or ui_overrides.DEFAULT_OVERRIDES
    low = p['name'].lower()
    rows = [r for r in ui_overrides.find_characters(p['name'], csv_path, overrides_dir, limit=None, followers=set())
            if r.get('name', '').lower() == low]
    if len(rows) > 1 and p.get('ref_id'):
        same = [r for r in rows if memory_ui.mantella_ref(r.get('ref_id')) == p['ref_id'].upper()]
        rows = same or rows
    if rows:
        return rows[0]
    return {'name': p['name'], 'race': '', 'base_id': '', 'bio': '', 'voice_model': '', '_custom': True}


def player_name() -> str:
    return lw_state.load_player_name() or 'the player'


class Ctx:
    """One NPC on the page: who, their character row, their save's store (None without a save or a reference id) and
    their live game values (the npc file the game wrote, read when first needed)."""

    def __init__(self, conversations_dir, world, p: dict):
        self.p, self.world_id = p, world
        self.name, self.ref = p['name'], p.get('ref_id') or ''
        self.row = character_row(p)
        self.race = self.row.get('race', '') or ''
        self.store = memory.MemoryStore(conversations_dir, world) if world and self.ref else None
        self._speaker = None
        self.player = player_name()

    @property
    def speaker(self) -> dict:
        if self._speaker is None:
            npc = characters.game_npc(self.name, self.race)
            self._speaker = dict(npc, name=self.name, ref_id=self.ref or npc.get('ref_id') or '')
        return self._speaker

    def entry(self) -> dict:
        return characters.entry_for(self.name, self.race, CHARS) or {}


def context(conversations_dir, world, label) -> Ctx | None:
    p = find_npc(conversations_dir, world, label)
    return Ctx(conversations_dir, world, p) if p else None


def upd(**kwargs) -> dict:
    """A change to a component other than its value (choices, visibility); build() turns it into gr.update."""
    return {'__update__': kwargs}


def _choice(label: str) -> str:
    """The id at the end of a pick label ("... #id")."""
    return str(label or '').rpartition('#')[2].strip()


def _norm(text) -> str:
    return ' '.join(str(text or '').split())


def _rows(table) -> list:
    """A Dataframe value as a list of lists (an older Gradio hands a pandas frame)."""
    if hasattr(table, 'values') and hasattr(table, 'columns'):
        table = table.values.tolist()
    return [list(r) for r in table or [] if isinstance(r, (list, tuple))]


def mismatch_lines(found: list[dict], where: tuple = ()) -> list[str]:
    """facts_history.mismatches rows as plain sentences: "Now says married to Inga; the game says not married"."""
    what = {'now': 'Now says', 'custom': 'A custom line says', 'belief': 'A belief line says', 'event': 'A custom event says'}
    out = []
    for m in found or []:
        if where and m.get('where') not in where:
            continue
        line = f"{what.get(m.get('where'), 'It says')} {m.get('says')}; the game says {m.get('game') or 'otherwise'}"
        if m.get('where') == 'custom':
            line += f" (\"{_norm(m.get('text'))[:80]}\")"
        if line not in out:
            out.append(line)
    return out


def _mismatches(ctx: Ctx, now_text: str = '') -> list[dict]:
    try:
        return facts_history.mismatches(ctx.store, ctx.speaker, ctx.player, now_text, ctx.entry())
    except Exception as e:
        logger.warning(f"Living World: could not compare {ctx.name}'s beliefs with the game ({e})")
        return []


# --- 1. prompt preview ---------------------------------------------------------------------------------------------------

def preview_view(ctx: Ctx) -> dict:
    try:
        bio = ctx.row.get('bio', '') or ''
        found = npc_block.preview(ctx.store, ctx.name, ctx.ref, bio=bio_optimise.used_bio(ctx.name, bio), speaker=ctx.speaker,
                                  player=ctx.player, world=lw_state.load_world())
    except Exception as e:
        return {'pv_note': f"The preview could not be built: {e}", 'pv_text': ''}
    body = '\n\n'.join(f"=== {name} ===\n{text}" for name, text in found['sections'])
    return {'pv_note': EXACT_NOTE if found['exact'] else REBUILT_NOTE, 'pv_text': body or '(nothing is sent for them yet)'}


# --- 2. personality (the bio) ----------------------------------------------------------------------------------------------

def _presets():
    return PRESETS or ui_overrides.MY_NPC_PRESETS


def _overrides():
    return OVERRIDES or ui_overrides.DEFAULT_OVERRIDES


def badge(row: dict, running=None) -> str:
    if ui_overrides.bio_state(row) == 'no bio' and not ui_overrides._own_bio(row, _overrides()):
        return ui_overrides._state_html(('pending', "No bio yet: Mantella only knows their name (Living World gives them "
                                                    "a short basic bio from their race, job and home). Paste their "
                                                    "Nexus page or a few notes below, then Write bio with AI."))
    level, text = ui_overrides.override_state(row, _overrides(), running_bio=running, presets_path=_presets())
    return ui_overrides._state_html((level, text if level != 'none' else "Using Mantella's default bio. Edit it below "
                                                                         "to make your own."))


def version_choices(row: dict, text: str) -> dict:
    default, mine = ui_overrides.default_bio(row, CSV or ui_overrides.DEFAULT_CSV), ui_overrides._own_bio(row, _overrides())
    choices = ui_overrides.versions(row, default, mine, _presets())
    found = ui_overrides.version_of(text, row, default, mine, _presets())
    return upd(choices=choices, value=found if found in choices else None, interactive=bool(choices))


def personality_view(ctx: Ctx, running=None) -> dict:
    row = ctx.row
    text = row.get('bio', '') or ''
    has_default = bool(ui_overrides.default_bio(row, CSV or ui_overrides.DEFAULT_CSV))
    return {'bio': text, 'voice': row.get('voice_model', '') or None, 'version': version_choices(row, text),
            'badge': badge(row, running), 'ai_btn': upd(value='Optimize with AI' if has_default else 'Write bio with AI')}


def save_personality(ctx: Ctx, bio: str, voice: str) -> str:
    """Writes your override file (only the fields that differ from what Mantella has now)."""
    if not _norm(bio):
        return 'The bio is empty; nothing saved.'
    path = ui_overrides.save_override(_overrides(), ctx.row, {'bio': bio, 'voice_model': voice or ''}, CSV or ui_overrides.DEFAULT_CSV)
    if not path:
        return 'Nothing changed.'
    return f"Saved {os.path.basename(path)}. Press Apply now to use it from the next conversation."


def apply_overrides(game) -> str:
    if ui_overrides.apply_now(game, _overrides()):
        return 'Applied: the running Mantella uses your overrides from the next conversation.'
    return 'Mantella will read it at its next start (or press again after your first conversation this session).'


def optimize(ctx: Ctx, ask, bio: str) -> tuple[str, str]:
    """(proposal or '', message). One request to your model; nothing is saved."""
    if ask is None:
        return '', 'This needs a newer Mantella - Direct AI Connect.'
    default = ui_overrides.default_bio(ctx.row, CSV or ui_overrides.DEFAULT_CSV)
    if not _norm(bio) and not default:
        return '', 'Paste their Nexus page or write a few notes in the bio box first.'
    out = ui_overrides.optimize_bio(ask, ctx.name, default, bio)
    if out.startswith(('Could not', 'The model gave')):
        return '', out
    text, assumed = ui_overrides.bio_and_assumed(out)
    notes = []
    if not default and len((bio or '').split()) < ui_overrides.MIN_NOTES_WORDS:
        notes.append('That was very little to go on, so most of this bio is guessed.')
    if assumed:
        notes.append(f'Not in what you gave, so assumed: {assumed}. Change anything that is wrong before you save.')
    return text, ' '.join(['Proposal ready below. Use this bio, then Save bio.'] + notes)


def save_preset(ctx: Ctx, name: str, bio: str) -> str:
    problem = ui_overrides.save_npc_preset(_presets(), ctx.row, name, bio, ctx.entry() or None)
    return problem or f"Saved as {ctx.name}'s preset '{(name or '').strip()}' (bio and Background). It stays on this PC only."


def delete_preset(ctx: Ctx, choice: str) -> str:
    if not choice or choice in (ui_overrides.DEFAULT_VERSION, ui_overrides.CURRENT_VERSION):
        return 'Pick one of your saved presets in Version first.'
    if not ui_overrides.delete_npc_preset(_presets(), ctx.row, choice):
        return f"'{choice}' is not one of your presets."
    return f"Preset '{choice}' deleted. The bio box and any saved override are unchanged."


def reset_personality(ctx: Ctx, config=None) -> str:
    moved = ui_overrides.reset_override(_overrides(), ctx.row)
    if not moved:
        return f"{ctx.name} has no override file of their own to reset."
    ui_overrides.request_reload(config)
    return (f"{ctx.name} is back to Mantella's default bio and voice from the next conversation ({', '.join(moved)} "
            f"moved to character_overrides_removed).")


def short_bio_view(ctx: Ctx) -> dict:
    """The short bio beside the original (bio_optimise): which one is sent, and the per-NPC choice."""
    found = bio_optimise.page_view(ctx.name, (ctx.row.get('bio') or '').strip())
    return {'sb_status': found['status'], 'sb_original': found['original'],
            'sb_short': found['short'] or '(none yet)',
            'sb_toggle': upd(value='Use the short bio again' if found['opted_out'] else 'Use original for this NPC')}


def toggle_original(ctx: Ctx) -> str:
    """Use original for this NPC (sticks), or back to the short bio."""
    now = not bio_optimise.uses_original(ctx.name)
    bio_optimise.set_use_original(ctx.name, now)
    return (f"{ctx.name}'s original bio is sent from the next talk." if now else
            f"{ctx.name}'s short bio is sent again from the next talk (when one is current).")


def optimise_again(ctx: Ctx, ask=None) -> str:
    """Writes their short bio now (one or two requests), checked like the automatic one; the bio itself is not changed."""
    original = (ctx.row.get('bio') or '').strip()
    if len(original) < bio_optimise.MIN_CHARS:
        return f"{ctx.name}'s bio is short enough already ({len(original)} characters); it is sent as it is."
    ask = ask or bio_optimise.pick_ask(original, ctx.name)
    if ask is None:
        return 'No model is reachable yet: talk to someone once, or open this page from a newer Mantella.'
    lines = bio_optimise.stable_background(ctx.speaker, ctx.entry())
    detail = bio_optimise.optimise_detail(original, lines, ctx.name, ask)
    if detail.get('error'):
        return f"Not done: {detail['why']}."
    bio_optimise.remember(ctx.name, original, detail, source='button', replace_manual=True)  # this NPC's own button: replaces a hand-made one
    if detail['status'] == 'done':
        return f"Short bio written: {len(original):,} -> {len(detail['text']):,} characters. Used from the next talk."
    return f"The original is kept: {detail['why']}."


def new_npc(name: str, race: str, bio: str, voice: str = '') -> str:
    """Your own NPC that is not in Mantella's list (a follower or an NPC from another mod): '' when saved, else why not."""
    problem = ui_overrides.new_npc_problem(name, CSV or ui_overrides.DEFAULT_CSV)
    if problem:
        return problem
    if not _norm(bio):
        return 'Write their bio first (or paste their Nexus page and use Write bio with AI after saving a short one).'
    row = {'name': name.strip(), 'race': (race or '').strip(), 'base_id': '', 'bio': '', 'voice_model': ''}
    path = ui_overrides.save_override(_overrides(), row, {'bio': bio, 'voice_model': voice or ''}, CSV or ui_overrides.DEFAULT_CSV)
    return '' if path else 'Nothing was saved.'


# --- 3. background ---------------------------------------------------------------------------------------------------------

GAME_LABELS = dict(characters.LIVE)


def background_view(ctx: Ctx) -> dict:
    entry, npc = ctx.entry(), ctx.speaker
    locked, pinned = entry.get('locked') or {}, entry.get('pinned') or {}
    live = characters.live_values(npc, ctx.player)
    race = locked.get('race') or str(npc.get('race') or ctx.race or '').strip()
    world = lw_state.load_world()
    game = [f"- {GAME_LABELS[k]}: {live.get(k) or '(none)'}" for k in characters.GAME_OWNED]
    known = bool(npc.get('base_id') or len(npc) > 2)
    game_md = ('**From the game (read-only):**\n' + '\n'.join(game)) if known else \
        "**From the game:** nothing read yet; the game writes their values at their first talk through Mantella."
    other = mod_facts.npc_sources(npc, ctx.player)  # what other mods record, read from the game (never edited here)
    if other and known:
        game_md += '\n\n**From other mods (read-only):**\n' + '\n'.join(f"- {text} ({mod})" for mod, text in other)
    try:  # fact files for this NPC (a scan just made), before the game has read them at their next talk
        from . import mod_facts_scan, ui_overrides as _uo
        files = mod_facts_scan.preview(str(npc.get('base_id') or ''), (_uo.mod_facts_where() or {}).get('out', ''))
    except Exception:
        files = []
    if files:
        game_md += ('\n\n**Fact files for this NPC (read-only; the game picks the line from its values when they next join '
                    'a talk):**\n' + '\n'.join(f"- {mod} ({folder}): {len(lines)} possible line(s), e.g. {lines[0][:120]}"
                                               for mod, folder, lines in files if lines))
    members = characters.live_members(npc)
    from_game = characters.religion_for(members, None)
    out = {'b_race': race.capitalize() if race.isupper() else race,
           'b_sex': locked.get('sex') or str(npc.get('sex') or '').strip(),
           'b_game': game_md,
           'b_role': pinned['role'] if 'role' in pinned else live.get('role', ''),
           'b_role_pin': 'role' in pinned,
           'b_religion': entry.get('religion', ''),
           'b_religion_note': f"The game says they {from_game}; that wins over what you type." if from_game else '',
           'b_values': entry.get('values', ''),
           'b_stances': characters.stance_rows(entry, npc, world) or [['', '', False]],
           'b_custom': entry.get('custom', ''),
           'b_mismatch': ui_help.red_lines(mismatch_lines(_mismatches(ctx), ('custom', 'belief')))}
    for k in characters.FLAG_KEYS:
        out['flag_' + k] = bool((entry.get('flags') or {}).get(k))
    return out


def save_background(ctx: Ctx, race, sex, role, role_pin, religion, values, stances, custom, flags) -> str:
    """Saves race and sex (locked), role, religion, values, feelings toward groups, custom lines and flags. Beliefs typed
    over a game-owned fact are kept (they are added and ended in Facts history)."""
    npc, world = ctx.speaker, lw_state.load_world()
    existing = characters.entry_for(ctx.name, ctx.race, CHARS)
    entry = dict(existing or {})
    entry['locked'] = {k: v for k, v in (('race', _norm(race)), ('sex', _norm(sex))) if v}
    pinned = dict(entry.get('pinned') or {})
    live_role = characters.live_values(npc, ctx.player).get('role', '')
    if _norm(role) and (role_pin or _norm(role) != _norm(live_role)):
        pinned['role'] = _norm(role)
    else:
        pinned.pop('role', None)
    entry['pinned'] = pinned
    members = characters.members_for(entry, npc)
    entry['stances'] = characters.pinned_stances(_rows(stances), characters.auto_stances(members, npc, world))
    entry['custom'] = custom or ''
    entry['religion'], entry['values'] = _norm(religion), _norm(values)
    entry['flags'] = {k: True for k, on in zip(characters.FLAG_KEYS, flags or []) if on}
    if existing is None:  # opening an NPC and saving changes nothing must not make an entry of the game's race and sex
        same = {k: v for k, v in entry['locked'].items() if v.lower() != str(npc.get(k) or '').strip().lower()}
        if characters.is_empty(dict(entry, locked=same)):
            return 'Nothing to save: everything matches the game.'
    if not characters.save_entry(ctx.name, ctx.race, entry, CHARS):
        return 'Nothing changed.'
    return f"Saved {ctx.name}'s Background. Used from the next reply."


def reset_background(ctx: Ctx) -> str:
    """Back to the game's values: race, sex, role, religion, values, feelings and custom lines go; flags stay."""
    existing = characters.entry_for(ctx.name, ctx.race, CHARS)
    if not existing:
        return f"{ctx.name} has no Background of your own to reset."
    flags = dict(existing.get('flags') or {})
    if not characters.save_entry(ctx.name, ctx.race, {'flags': flags}, CHARS) and flags:
        return 'Nothing changed.'
    return f"{ctx.name}'s Background is back to the game's values (flags kept). Used from the next reply."


# --- 4. now ----------------------------------------------------------------------------------------------------------------

def now_status(state: dict) -> str:
    if not state['text']:
        line = 'Locked, with no paragraph.' if state['locked'] else 'No paragraph yet: it is written after a few more talks.'
    else:
        by = 'written from their memories' if state['auto'] else 'your own text'
        day = f", last on day {state['day']}" if state['day'] >= 0 else ''
        line = f"{'Locked. ' if state['locked'] else ''}{by.capitalize()}{day}."
    if state['due'] and not state['locked']:
        line += ' Rewritten after the next talk: ' + '; '.join(state['due'][-3:]) + '.'
    return line


def now_view(ctx: Ctx) -> dict:
    if ctx.store is None:
        return {'n_status': '', 'n_mismatch': '', 'n_text': '', 'n_lock': False, 'n_others': '', 'n_gaps': ''}
    state = bio_evolve.load(ctx.store, ctx.name, ctx.ref)
    gaps = '\n'.join(f"- {g['text']}" for g in state['gaps'])
    return {'n_status': now_status(state),
            'n_mismatch': ui_help.red_lines(mismatch_lines(_mismatches(ctx, state['text']), ('now',))),
            'n_text': state['text'], 'n_lock': state['locked'], 'n_others': state['others'],
            'n_gaps': ('**Gap lines (always sent after the paragraph):**\n' + gaps) if gaps else 'No gap lines.'}


def save_now(ctx: Ctx, text: str, locked: bool, others: str) -> str:
    if ctx.store is None:
        return NO_REF_NOTE
    bio_evolve.edit(ctx.store, ctx.name, ctx.ref, text=text or '', locked=bool(locked), others=others or '')
    return f"Saved {ctx.name}'s Now paragraph{' (locked)' if locked else ''}. Used from the next conversation with them."


def clear_gaps(ctx: Ctx) -> str:
    if ctx.store is None:
        return NO_REF_NOTE
    count = bio_evolve.clear_gaps(ctx.store, ctx.name, ctx.ref)
    return f"{count} gap line(s) cleared." if count else 'There were no gap lines.'


def rewrite_soon(ctx: Ctx) -> str:
    if ctx.store is None:
        return NO_REF_NOTE
    state = bio_evolve.load(ctx.store, ctx.name, ctx.ref)
    if state['locked']:
        return 'The paragraph is locked; untick Lock and save first, or it is never rewritten.'
    bio_evolve.mark_due(ctx.store, ctx.name, ctx.ref, 'you asked for it on the NPC page')
    return f"{ctx.name}'s Now paragraph is rewritten after the next talk with them."


def reset_now(ctx: Ctx) -> str:
    if ctx.store is None:
        return NO_REF_NOTE
    bio_evolve.reset(ctx.store, ctx.name, ctx.ref)
    return f"{ctx.name}'s Now paragraph is cleared; it grows again from what happens next."


# --- 5. facts history ------------------------------------------------------------------------------------------------------

def _cause(cause: str, commands: dict) -> str:
    cause = str(cause or '')
    if cause.startswith('command:'):
        text = commands.get(cause[8:], '')
        return f"absolute command{': ' + text[:40] if text else ''}"
    if cause.startswith('event:'):
        return 'custom event'
    return CAUSES.get(cause, cause or '?')


def _link_text(link: dict, ctx: Ctx) -> str:
    me = {'key': facts_history.npc_key(ctx.name, ctx.ref), 'base': contracts.base_key(ctx.speaker.get('base_id')),
          'name': ctx.name}
    other = link['b'] if facts_history._is(link['a'], me) else link['a']
    who = ctx.player if other == facts_history.PLAYER else (other.get('name') if isinstance(other, dict) else '?')
    return f"{link['kind']} {'to' if link['kind'] in ('married', 'engaged') else 'with'} {who}"


def facts_view(ctx: Ctx) -> dict:
    if ctx.store is None:
        return {'f_table': [], 'f_pick': upd(choices=[], value=None), 'f_mismatch': '', 'f_note': ''}
    found = facts_history.history(ctx.store, ctx.name, ctx.ref)
    try:
        commands = {c['id']: c['text'] for c in command.load(ctx.store)['commands']}
    except Exception:
        commands = {}
    rows, choices = [], []
    for line in found['lines']:
        label = facts_history.LABELS.get(line['fact'], 'Custom' if line['fact'] == 'custom' else line['fact'])
        owner = 'game' if line.get('owner') == 'game' else 'you'
        rows.append([label, line.get('value', ''), line.get('since', -1), _cause(line.get('cause'), commands),
                     STATUS_LABELS.get(line.get('status'), line.get('status')), 'yes' if line.get('visible', True) else 'no', owner])
        choices.append(f"{label}: {_norm(line.get('value'))[:60]} [{STATUS_LABELS.get(line.get('status'), '')}, {owner}] #{line['id']}")
    for link in found['links']:
        text = _link_text(link, ctx)
        rows.append(['Partner', text, link.get('since', -1), _cause(link.get('cause'), commands),
                     STATUS_LABELS.get(link.get('status'), link.get('status')), 'yes' if link.get('visible', True) else 'no', 'game'])
        choices.append(f"Partner: {text[:60]} [{STATUS_LABELS.get(link.get('status'), '')}, game] #{link['id']}")
    note = '' if found['lines'] or found['links'] else ("Nothing written down in this save yet: the history starts at "
                                                         "their next talk, or when you add a line below.")
    return {'f_table': rows, 'f_pick': upd(choices=choices, value=None), 'f_note': note,
            'f_mismatch': ui_help.red_lines(mismatch_lines(_mismatches(ctx), ('belief', 'event', 'custom')))}


def _find_line(store, line_id: str):
    data = facts_history.load(store)
    for record in data['npcs'].values():
        for line in record['lines']:
            if line['id'] == line_id:
                return line, False
    for link in data['links']:
        if link['id'] == line_id:
            return link, True
    return None, False


def fact_visible(ctx: Ctx, label: str) -> bool:
    line, _ = _find_line(ctx.store, _choice(label)) if ctx.store is not None and label else (None, False)
    return bool(line.get('visible', True)) if line else True


def set_fact_visible(ctx: Ctx, label: str, visible: bool) -> str:
    if ctx.store is None:
        return NO_REF_NOTE
    if not label:
        return 'Pick a line first.'
    line, is_link = _find_line(ctx.store, _choice(label))
    if line is None:
        return 'That line is gone; pick it again.'
    if not is_link and line.get('owner') == 'game':
        return ("The game's own lines are set again at every talk, so they cannot be hidden here. To change what they "
                "believe, add a belief line (it takes the game line's place in what they are told).")
    if facts_history.set_visible(ctx.store, line['id'], bool(visible)):
        return 'They know this line now.' if visible else 'They no longer know this line (shown here only, never sent).'
    return 'No change: the line already was like that, or is gone.'


def _ensure_history(ctx: Ctx, today) -> None:
    """Writes the NPC's facts down in this save the way their first talk would (only when nothing is written yet, so
    no change the next talk should notice is used up here)."""
    record = facts_history.load(ctx.store)['npcs'].get(facts_history.npc_key(ctx.name, ctx.ref))
    if not (record or {}).get('migrated'):
        facts_history.sync_talk(ctx.store, [ctx.speaker], ctx.player, today, data_path=CHARS)


def add_fact(ctx: Ctx, fact_label: str, value: str, visible: bool = True, today=None) -> str:
    """A line of your own, from today: a custom line, a role, or a belief over a game-owned fact (what they believe; the
    game is not changed). It is also written to their Background, so the next talk keeps it."""
    if ctx.store is None:
        return NO_REF_NOTE
    fact, value = ADD_FACTS.get(fact_label, fact_label), _norm(value)
    if fact not in ADD_FACTS.values():
        return 'Pick what kind of line it is.'
    if not value:
        return 'Write the line first.'
    today = lw_state.load_today() if today is None else today
    _ensure_history(ctx, today)
    entry = dict(characters.entry_for(ctx.name, ctx.race, CHARS) or {})
    if fact == 'custom':
        lines = characters.custom_lines(entry.get('custom', ''))
        if value in lines:
            return 'They already have that line.'
        entry['custom'] = '\n'.join(lines + [value])
    else:
        old = (entry.get('pinned') or {}).get(fact)
        for line in facts_history.history(ctx.store, ctx.name, ctx.ref)['lines']:
            if line['fact'] == fact and line.get('owner') == 'user' and line['status'] == 'current' and line['value'] == old:
                _end_line(ctx.store, line['id'], today, 'replaced on the NPC page')
        entry['pinned'] = dict(entry.get('pinned') or {}, **{fact: value})
    characters.save_entry(ctx.name, ctx.race, entry, CHARS)
    facts_history.add_line(ctx.store, ctx.name, ctx.ref, fact, value, 'user', today, bool(visible), 'user',
                           ctx.speaker.get('base_id', ''))
    extra = '' if fact in ('custom', 'role') else ' This is what they believe; the game is not changed.'
    return f"Added from today{'' if visible else ' (hidden from them)'}.{extra}"


def _end_line(store, line_id: str, today, why: str) -> dict | None:
    """Ends one of your own current lines; returns it (None when it is not yours or not current)."""
    with facts_history._lock:
        data = facts_history.load(store)
        for record in data['npcs'].values():
            for line in record['lines']:
                if line['id'] == line_id and line.get('owner') == 'user' and line['status'] == 'current':
                    line.update(status='ended', ended=facts_history._day(today), why=why)
                    facts_history.save(store, data)
                    return dict(line)
    return None


def end_fact(ctx: Ctx, label: str, today=None) -> str:
    if ctx.store is None:
        return NO_REF_NOTE
    if not label:
        return 'Pick a line first.'
    line, is_link = _find_line(ctx.store, _choice(label))
    if line is None:
        return 'That line is gone; pick it again.'
    if is_link or line.get('owner') == 'game':
        return ('That line belongs to the game and cannot be ended here. Change it in the game, or with an Absolute '
                'Command (G).')
    if line['status'] != 'current':
        return 'That line has already ended or is on hold.'
    today = lw_state.load_today() if today is None else today
    ended = _end_line(ctx.store, line['id'], today, 'ended on the NPC page')
    if ended is None:
        return 'That line could not be ended.'
    entry = dict(characters.entry_for(ctx.name, ctx.race, CHARS) or {})  # or the next talk would start it again
    if ended['fact'] == 'custom':
        entry['custom'] = '\n'.join(l for l in characters.custom_lines(entry.get('custom', '')) if l != ended['value'])
    elif (entry.get('pinned') or {}).get(ended['fact']) == ended['value']:
        entry['pinned'] = {k: v for k, v in entry['pinned'].items() if k != ended['fact']}
    characters.save_entry(ctx.name, ctx.race, entry, CHARS)
    return f"Ended: {ended['value'][:80]}"


# --- 6. memories -----------------------------------------------------------------------------------------------------------

def _known(entry: dict) -> str:
    source = archive.source_of(entry)
    if source == 'told':
        by = _norm(entry.get('told_by'))[:40]
        return f"told by {by}" if by else 'told'
    return SOURCE_LABELS.get(source, source)


def all_memories(store, name: str, ref_id: str) -> list[dict]:
    """Every memory of this NPC, oldest first: {id, day, hour, text, known, spell, state, importance, arc, hidden,
    recent}. Archived rows (folded, or hidden) and the memory file's newest ones, each once."""
    mem = store.load(name, ref_id)
    recent = {archive.entry_id(e): e for e in mem['recent']}
    try:
        db = store.archive_for(name, ref_id)
        rows = db.rows(hidden=None) if db.exists() else []
        arc_names = {a['id']: a['label'] for a in db.arcs()} if db.exists() else {}
    except Exception as e:
        logger.warning(f"Living World: could not read {name}'s older memories ({e})")
        rows, arc_names = [], {}
    other = {r['id']: r['state'] for r in memory.list_other_timeline(store, name, ref_id)}
    out, seen = [], set()
    for r in rows + [dict(e, id=i) for i, e in recent.items()]:
        i = r['id']
        if i in seen:
            continue
        seen.add(i)
        entry = recent.get(i) or r
        hidden = bool(entry.get('hidden') or r.get('hidden'))
        state = 'hidden' if hidden else other.get(i) or ('mind' if i in recent else 'older')
        out.append({'id': i, 'day': memory._int(r.get('day')), 'hour': memory._int(r.get('hour')),
                    'text': memory.entry_text(entry, store) or r.get('text', ''), 'known': _known(entry),
                    'spell': _norm(entry.get('spell')), 'state': state, 'importance': archive.importance_of(entry),
                    'arc': arc_names.get(r.get('arc'), ''), 'hidden': hidden, 'recent': i in recent})
    return sorted(out, key=lambda m: (m['day'], m['hour']))


def memory_label(m: dict) -> str:
    when = memory.header(m['day'], m['hour']) or '[undated]'
    text = _norm(m['text'])
    return f"{when} {text[:80]}{'...' if len(text) > 80 else ''}{' (hidden)' if m['hidden'] else ''} #{m['id']}"


def memories_view(ctx: Ctx, query: str = '') -> dict:
    empty = {'m_mood': '', 'm_count': '', 'm_table': [], 'm_pick': upd(choices=[], value=None), 'm_edit': '',
             'm_feeling': '', 'm_long': [['', '']], 'a_table': [], 'a_pick': upd(choices=[], value=None),
             'a_merge': upd(choices=[], value=[])}
    if ctx.store is None:
        return empty
    mem = ctx.store.load(ctx.name, ctx.ref)
    found = all_memories(ctx.store, ctx.name, ctx.ref)
    q = _norm(query).lower()
    shown = [m for m in found if not q or q in m['text'].lower() or q in m['known'].lower() or q in m['arc'].lower()]
    cut = shown[-MAX_ROWS:]
    rows = [[m['day'], m['hour'], m['text'], m['known'], m['spell'], STATE_LABELS.get(m['state'], m['state']),
             round(m['importance'], 2), m['arc']] for m in reversed(cut)]
    count = f"{len(found)} memories in all" + (f", {len(shown)} match" if q else '')
    if len(shown) > len(cut):
        count += f"; showing the newest {len(cut)}, search to find the rest"
    mood = memory.mood_line((ctx.name, ctx.ref), ctx.store)
    arc_list = arcs.list_arcs(ctx.store, ctx.name, ctx.ref)
    arc_choices = [f"{a['label']} ({len(a['memories'])}) #{a['id']}" for a in arc_list]
    promises = memory.open_promises(mem)
    return {'m_mood': f"**Mood:** {mood}" if mood else '**Mood:** neutral (nothing since their last talk).',
            'm_count': count + '.' + (f" Open promises: {'; '.join(promises)}" if promises else ''),
            'm_table': rows, 'm_pick': upd(choices=[memory_label(m) for m in reversed(cut)], value=None), 'm_edit': '',
            'm_feeling': mem.get('feeling') or '',
            'm_long': [[k, v] for k, v in (mem.get('long_term') or {}).items()] or [['', '']],
            'a_table': [[a['label'], a['summary'], a['day'], len(a['memories'])] for a in arc_list],
            'a_pick': upd(choices=arc_choices, value=None), 'a_merge': upd(choices=arc_choices, value=[])}


def memory_text(ctx: Ctx, label: str) -> str:
    if ctx.store is None or not label:
        return ''
    mid = _choice(label)
    return next((m['text'] for m in all_memories(ctx.store, ctx.name, ctx.ref) if m['id'] == mid), '')


def edit_memory(ctx: Ctx, label: str, text: str) -> str:
    """Puts your text in place of one memory (a recent one in the memory file, an older one in the archive). Its day,
    hour, source and story arc stay; the old text leaves the archive so it never comes back."""
    if ctx.store is None:
        return NO_REF_NOTE
    mid, text = _choice(label), _norm(text)[:memory.MAX_ENTRY_CHARS]
    if not label:
        return 'Pick a memory first.'
    if not text:
        return 'The text is empty; nothing saved. To remove a memory use Hide or Delete.'
    store, name, ref = ctx.store, ctx.name, ctx.ref
    with store.lock(name, ref):
        mem = store.load(name, ref)
        db = store.archive_for(name, ref)
        arc_id = next((r.get('arc') for r in (db.rows(hidden=None) if db.exists() else []) if r['id'] == mid), None)
        entry = next((e for e in mem['recent'] if archive.entry_id(e) == mid), None)
        if entry is not None:
            if entry.get('hidden'):
                return 'That memory is hidden; unhide it first.'
            old = dict(entry)
            entry.pop('shared', None)
            entry['text'] = text
            new_id = archive.entry_id(entry)
            if new_id == mid:
                return 'Nothing changed.'
            store.save(name, ref, mem)
            memory_ui.forget_in_archive(store, name, ref, [old])
        else:
            row = next((r for r in (db.rows(hidden=None) if db.exists() else []) if r['id'] == mid), None)
            if row is None:
                return 'That memory changed meanwhile; pick it again.'
            if row.get('hidden'):
                return 'That memory is hidden; unhide it first.'
            added = {k: row.get(k) for k in memory.REWRITE_KEYS + ('witnesses', 'promises') if row.get(k) not in (None, '', [])}
            added['text'] = text
            new_id = archive.entry_id(added)
            if new_id == mid:
                return 'Nothing changed.'
            db.add([(added, text)], embed.current())
            db.delete([mid])
        if arc_id:
            db.set_arc([new_id], arc_id)
    return f"Saved. {name} remembers it like this from the next conversation."


def hide_memory(ctx: Ctx, label: str) -> str:
    """Hides one memory (nothing is deleted; Unhide brings it back). Written to the true record, with no gap line."""
    if ctx.store is None:
        return NO_REF_NOTE
    if not label:
        return 'Pick a memory first.'
    found = release.forget(ctx.store, ctx.name, ctx.ref, ids=[_choice(label)], mode='clean', by='you')
    return f"Hidden: {_norm(found['hidden'][0]['text'])[:80]}" if found['hidden'] else 'That memory is already hidden or gone.'


def unhide_memory(ctx: Ctx, label: str) -> str:
    if ctx.store is None:
        return NO_REF_NOTE
    if not label:
        return 'Pick a memory first.'
    if memory.unhide(ctx.store, ctx.name, ctx.ref, _choice(label)):
        return f"{ctx.name} remembers it again from the next conversation."
    return 'That memory was not hidden.'


def delete_memory(ctx: Ctx, label: str, ok: bool) -> str:
    """Removes one memory for good (you only; commands never delete). Asks first; the files as they were are copied to
    living_world_memory_removed, and the true record notes it."""
    if ctx.store is None:
        return NO_REF_NOTE
    if not label:
        return 'Pick a memory first.'
    if not ok:
        return 'Nothing deleted.'
    mid = _choice(label)
    removed = release.delete_memory(ctx.store, ctx.name, ctx.ref, mid)  # a memory in mind (the memory file)
    if not removed:
        removed = _delete_other(ctx, mid)  # a hidden one, or one only in the archive
    if not removed:
        return 'That memory changed meanwhile; pick it again.'
    return f"Deleted for good: {_norm(removed.partition(chr(10))[0])[:100]}"


def _delete_other(ctx: Ctx, mid: str) -> str:
    store, name, ref = ctx.store, ctx.name, ctx.ref
    with store.lock(name, ref):
        mem = store.load(name, ref)
        db = store.archive_for(name, ref)
        entry = next((e for e in mem['recent'] if archive.entry_id(e) == mid), None)
        row = next((r for r in (db.rows(hidden=None) if db.exists() else []) if r['id'] == mid), None)
        if entry is None and row is None:
            return ''
        folder = memory_ui._backup_folder(memory_ui.DEFAULT_BACKUPS)
        for f in (store._path(name, ref), store.archive_path(name, ref)):
            if f.exists():
                shutil.copy2(str(f), os.path.join(folder, f.name))
        text = memory.entry_text(entry, store) if entry is not None else row.get('text', '')
        day = memory._int((entry or row).get('day'))
        if entry is not None:
            mem['recent'].remove(entry)
            store.save(name, ref, mem)
        if db.exists():
            db.delete([mid])
    release.write_record(store, 'delete', name, ref, _norm(text)[:200], 'you', [day])
    return text or '(a memory)'


ROW_LINE = re.compile(r'^\s*(-?\d+)\s*\|\s*(-?\d+)\s*\|\s*(.+)$')


def add_memory(ctx: Ctx, text: str, source_label: str, told_by: str = '') -> str:
    """Adds one memory per line. A line "day | hour | text" (from Turn notes into memories) keeps its day and hour
    (-1: unknown); a plain line is dated today."""
    if ctx.store is None:
        return NO_REF_NOTE
    source = next((k for k, v in SOURCE_LABELS.items() if v == source_label), 'seen')
    lines = [l for l in str(text or '').splitlines() if _norm(l)]
    if not lines:
        return 'Write the memory first.'
    added = 0
    for line in lines:
        found = ROW_LINE.match(line)
        day, hour, body = (int(found.group(1)), int(found.group(2)), found.group(3)) if found else (None, -1, line)
        if memory.add_memory(ctx.store, ctx.name, ctx.ref, body, source=source, told_by=told_by or '', day=day, hour=hour,
                             kind='experience'):
            added += 1
    if not added:
        return 'Not added (they already have it, or the file is busy).'
    return f"{added} memory(s) added. {ctx.name} remembers from the next conversation."


def notes_to_lines(ctx: Ctx, ask, notes: str) -> tuple[str, str]:
    """(lines for the Add a memory box, message): your model turns plain-word notes into "day | hour | text" lines from
    the NPC's point of view. Nothing is saved until Add memory."""
    if ask is None:
        return '', 'This needs a newer Mantella - Direct AI Connect.'
    rows, _, problem = memory_ui.notes_to_rows(ask, ctx.name, ctx.player, notes)
    if problem:
        return '', problem
    return '\n'.join(f"{d} | {h} | {t}" for d, h, t in rows), f"{len(rows)} memory line(s) below. Check them, then Add memory."


def save_feeling(ctx: Ctx, feeling: str) -> str:
    if ctx.store is None:
        return NO_REF_NOTE
    with ctx.store.lock(ctx.name, ctx.ref):
        mem = ctx.store.load(ctx.name, ctx.ref)
        mem['feeling'] = _norm(feeling)[:memory.MAX_FEELING_CHARS]
        ctx.store.save(ctx.name, ctx.ref, mem)
    return f"Saved how {ctx.name} feels about you. Used from the next conversation."


def save_long_term(ctx: Ctx, rows) -> str:
    if ctx.store is None:
        return NO_REF_NOTE
    notes, joined = memory_ui.long_term_from_rows(_rows(rows))
    with ctx.store.lock(ctx.name, ctx.ref):
        mem = ctx.store.load(ctx.name, ctx.ref)
        mem['long_term'] = notes
        ctx.store.save(ctx.name, ctx.ref, mem)
    return 'Saved the long-term notes.' + (f" Rows with the same topic were joined: {', '.join(joined)}." if joined else '')


def forget_everything(ctx: Ctx, ok: bool) -> str:
    if ctx.store is None:
        return NO_REF_NOTE
    if not ok:
        return 'Nothing deleted.'
    if not memory_ui.reset_memory(ctx.store, ctx.name, ctx.ref, memory_ui.DEFAULT_BACKUPS):
        return f"{ctx.name} has no memories of you to delete."
    return (f"{ctx.name} no longer remembers you in this save. The files were moved to living_world_memory_removed in "
            f"case you want them back.")


def arc_fields(ctx: Ctx, label: str) -> tuple[str, str]:
    if ctx.store is None or not label:
        return '', ''
    found = next((a for a in arcs.list_arcs(ctx.store, ctx.name, ctx.ref) if a['id'] == _choice(label)), None)
    return (found['label'], found['summary']) if found else ('', '')


def rename_arc(ctx: Ctx, label: str, name: str, summary: str) -> str:
    if ctx.store is None or not label:
        return 'Pick a story first.'
    ok = arcs.rename_arc(ctx.store, ctx.name, ctx.ref, _choice(label), label=name or None, summary=summary)
    return 'Story saved (kept as you wrote it from now on).' if ok else 'That story is gone; pick it again.'


def merge_arcs(ctx: Ctx, label: str, others) -> str:
    ids = [_choice(o) for o in others or [] if _choice(o) != _choice(label)]
    if ctx.store is None or not label:
        return 'Pick the story to keep first.'
    if not ids:
        return 'Tick the stories to merge into it.'
    ok = arcs.merge_arcs(ctx.store, ctx.name, ctx.ref, _choice(label), ids)
    return f"{len(ids)} story(s) merged." if ok else 'Nothing merged.'


def move_to_arc(ctx: Ctx, memory_label_: str, label: str) -> str:
    if ctx.store is None or not memory_label_ or not label:
        return 'Pick a memory and a story first.'
    ok = arcs.add_to_arc(ctx.store, ctx.name, ctx.ref, _choice(memory_label_), _choice(label))
    return 'Memory moved into the story.' if ok else 'Not moved (that memory or story is gone).'


def take_from_arc(ctx: Ctx, memory_label_: str) -> str:
    if ctx.store is None or not memory_label_:
        return 'Pick a memory first.'
    ok = arcs.remove_from_arc(ctx.store, ctx.name, ctx.ref, _choice(memory_label_))
    return 'Memory taken out of its story.' if ok else 'That memory is in no story.'


def new_arc(ctx: Ctx, name: str, memory_label_: str = '') -> str:
    if ctx.store is None:
        return NO_REF_NOTE
    if not _norm(name):
        return 'Give the story a name first.'
    ids = [_choice(memory_label_)] if memory_label_ else []
    made = arcs.new_arc(ctx.store, ctx.name, ctx.ref, name, '', ids)
    return f"Story '{_norm(name)}' made{' with the picked memory' if ids else ''}." if made else 'No story made (they have no memories yet).'


def delete_arc(ctx: Ctx, label: str) -> str:
    if ctx.store is None or not label:
        return 'Pick a story first.'
    return 'Story removed; its memories stay.' if arcs.delete_arc(ctx.store, ctx.name, ctx.ref, _choice(label)) else 'That story is gone.'


# --- 7. commands -----------------------------------------------------------------------------------------------------------

def _binds(record: dict, ctx: Ctx) -> bool:
    ref = facts_history.short_ref(ctx.ref)
    return any((ref and facts_history.short_ref(n.get('ref_id')) == ref) or
               (not ref and str(n.get('name', '')).lower() == ctx.name.lower()) for n in record.get('npcs') or [])


def _when(record: dict) -> str:
    given = command._float(record.get('given'))
    day = f"day {int(given) + memory.MANTELLA_DAY}" if given >= 0 else 'an unknown day'
    until = command._float(record.get('until'))
    return f"given on {day}" + (', for a few game hours' if until > 0 else ', until released')


def commands_view(ctx: Ctx) -> dict:
    if ctx.store is None:
        return {'c_list': '', 'c_pick': upd(choices=[], value=None), 'c_marriage': upd(visible=False, value=False),
                'c_record': []}
    found = [r for r in release.releasable(ctx.store, [ctx.speaker]) if _binds(r, ctx)]
    items = []
    for r in found:
        others = [n['name'] for n in r['npcs'] if n['name'] != ctx.name]
        married = any(m['name'] == ctx.name for m in r['marriages'])
        items.append(f'<li>"{html.escape(r["text"])}"<br><small>{html.escape(_when(r))}'
                     f'{"; also binds " + html.escape(", ".join(others)) if others else ""}'
                     f'{"; a marriage was made while it was in force" if married else ""}</small></li>')
    listing = ('<ul style="margin:0;padding-left:18px">' + ''.join(items) + '</ul>') if items else \
        '<div style="opacity:.6">No absolute command is in force on them.</div>'
    choices = [f"{r['text'][:70]}{'...' if len(r['text']) > 70 else ''} #{r['id']}" for r in found]
    can_end = contracts.present() and any(m['name'] == ctx.name for r in found for m in r['marriages'])
    rows = []
    for r in release.record_rows(ctx.store, ctx.name, ctx.ref):
        days = r.get('days') or []
        span = (f"day {days[0]}" if days[0] == days[-1] else f"days {days[0]} to {days[-1]}") if days else ''
        how = release.CHOICE_TEXT.get(r.get('choice'), '') or ('leaves a gap' if r.get('mode') == 'gap' else
                                                               'clean' if r.get('mode') == 'clean' else '')
        rows.append([time.strftime('%Y-%m-%d %H:%M', time.localtime(r.get('at') or 0)), r.get('kind', ''), r.get('what', ''),
                     span, r.get('by', ''), how])
    return {'c_list': listing, 'c_pick': upd(choices=choices, value=None), 'c_marriage': upd(visible=can_end, value=False),
            'c_record': rows}


def release_one(ctx: Ctx, label: str, choice_label: str, mode_label: str, end_marriage: bool, everyone: bool, ok: bool,
                ask=None) -> str:
    if ctx.store is None:
        return NO_REF_NOTE
    if not label:
        return 'Pick a command first.'
    if not ok:
        return 'Nothing released.'
    choice = CHOICE_LABELS.get(choice_label)
    if choice is None:
        return 'Pick what happens when it is released.'
    npc = None if everyone else {'name': ctx.name, 'ref_id': ctx.ref}
    result = release.release_command(ctx.store, _choice(label), choice, npc=npc, end_marriage=bool(end_marriage),
                                     mode=MODE_LABELS.get(mode_label, 'clean'), player=ctx.player, speakers=[ctx.speaker],
                                     ask=ask)
    message = result['message']
    if result.get('ok') and result.get('ended'):
        message += f" {result['ended']} fact line(s) it made ended, {result['returned']} came back."
    if result.get('requests'):
        message += ' The Relationships module will ask in the game whether to end the marriage.'
    return message


def forget_now(ctx: Ctx, what: str, mode_label: str, ok: bool) -> str:
    """Hides the memories closest to what (nothing deleted), with a gap line or clean, and writes the true record."""
    if ctx.store is None:
        return NO_REF_NOTE
    if not _norm(what):
        return 'Write what they should forget first.'
    if not ok:
        return 'Nothing forgotten.'
    found = release.forget(ctx.store, ctx.name, ctx.ref, what=_norm(what), mode=MODE_LABELS.get(mode_label, 'clean'), by='you')
    if not found['hidden']:
        return f"No memory of {ctx.name}'s matches that closely enough; nothing was hidden."
    return f"{len(found['hidden'])} memory(s) hidden. Unhide in Memories brings any of them back."


# --- 8. knows about (world events from the world log, news.py) ---------------------------------------------------------

HOW_LABELS = {'seen': 'saw it', 'told': 'told', 'rumour': 'rumour', 'hearsay': 'hearsay from the hold', 'own': 'their own'}
KIND_LABELS = {'marriage': 'wedding', 'engagement': 'engagement', 'divorce': 'divorce', 'breakup': 'broken engagement',
               'death': 'death', 'killing': 'killing', 'crime': 'crime', 'wipe': 'lost memory', 'release': 'spell lifted',
               'custom': 'event', 'fight': 'fight', 'intimate': 'event'}


def _npc(ctx: Ctx) -> dict:
    """This NPC as the world log matches people: Mantella's name and reference id, the game's base id."""
    return {'name': ctx.name, 'ref_id': ctx.ref, 'base_id': ctx.speaker.get('base_id') or ctx.row.get('base_id') or '',
            'minor': 0 if action_filter.adult(ctx.speaker) else 1}  # not confirmed an adult by the game: a child


def _day(day) -> str:
    try:
        value = float(day)
    except (TypeError, ValueError):
        return ''
    return str(int(value) + memory.MANTELLA_DAY) if value >= 0 else ''


def _event_label(e: dict) -> str:
    text = _norm(e.get('text') or e.get('public_text') or e.get('true_text'))
    return f"day {_day(e.get('day')) or '?'}: {text[:80]}{'...' if len(text) > 80 else ''} #{e['id']}"


def knows_text(store, name: str, ref_id: str) -> str:
    """A one-line count for the section (the table holds the rest)."""
    if store is None or not ref_id:
        return 'Nothing recorded yet.'
    try:
        from . import news
        found = news.known_events(store, {'name': name, 'ref_id': ref_id})
    except Exception:
        return 'Nothing recorded yet.'
    taken = sum(1 for e in found if e['wiped'])
    if not found:
        return 'They know of no event in the world log yet.'
    return f"They know of {len(found)} event(s)" + (f", {taken} of them taken from them." if taken else '.')


def knows_view(ctx: Ctx) -> dict:
    """The events this NPC knows (how, since when, told by whom, taken or not), the ones they could be told, and the
    count line."""
    empty = {'k_text': 'Nothing recorded yet.', 'k_table': [], 'k_pick': upd(choices=[], value=None),
             'k_tell_pick': upd(choices=[], value=None), 'k_who': ''}
    if ctx.store is None:
        return empty
    from . import news, worldlog
    found = news.known_events(ctx.store, _npc(ctx))
    rows = [[_day(e.get('day')), KIND_LABELS.get(e.get('kind'), e.get('kind') or ''), e.get('text') or '',
             HOW_LABELS.get(e.get('how'), e.get('how') or ''), e.get('by') or '', _day(e.get('since')),
             'taken from them' if e['wiped'] else ''] for e in found]
    known = {e['id'] for e in found if not e['wiped']}
    tellable = [e for e in reversed(worldlog.events(ctx.store)) if not e.get('retracted') and e.get('public_text')
                and e['id'] not in known]
    return {'k_text': knows_text(ctx.store, ctx.name, ctx.ref), 'k_table': rows,
            'k_pick': upd(choices=[_event_label(e) for e in found], value=None),
            'k_tell_pick': upd(choices=[_event_label(dict(e, text=e.get('public_text'))) for e in tellable[:200]], value=None),
            'k_who': ''}


def who_knows(ctx: Ctx, label: str) -> str:
    """Everyone the world log has as knowing the picked event, and how."""
    if ctx.store is None or not label:
        return ''
    from . import news, worldlog
    event = worldlog.find(ctx.store, _choice(label))
    if event is None:
        return 'That event is no longer in the world log.'
    people = news.who_knows(ctx.store, event['id'])
    lines = [f"- {p['name'] or 'a child (not named)'}: {HOW_LABELS.get(p['how'], p['how'])}"
             + (f" by {p['by']}" if p.get('by') else '') + (f", since day {_day(p.get('since'))}" if _day(p.get('since')) else '')
             + (' (taken from them)' if p.get('wiped') else '') for p in people]
    head = f"**What really happened** (the Hub's record, never sent): {html.escape(event.get('true_text') or '')}"
    return head + '\n\n' + ('\n'.join(lines) if lines else 'Nobody knows it yet.')


def forget_known(ctx: Ctx, label: str, ok: bool) -> str:
    """Makes this NPC forget the picked event (hidden, nothing deleted) and stops it reaching them again."""
    if ctx.store is None:
        return NO_REF_NOTE
    if not label:
        return 'Pick an event they know first.'
    if not ok:
        return 'Nothing forgotten.'
    from . import news
    report = news.forget_event(ctx.store, _npc(ctx), _choice(label), by='you')
    if not report['wipes']:
        return 'That event is no longer in the world log.'
    return (f"{ctx.name} no longer knows it ({report['hidden']} memory(s) hidden). It reaches them again only if someone "
            "who knows it tells them in a talk, or you tell them here.")


def tell_known(ctx: Ctx, label: str, told_by: str) -> str:
    """Tells this NPC about an event from the log now (one memory, told by someone or plainly told)."""
    if ctx.store is None:
        return NO_REF_NOTE
    if not label:
        return 'Pick an event to tell them first.'
    from . import news, worldlog
    event = worldlog.find(ctx.store, _choice(label))
    if event is None:
        return 'That event is no longer in the world log.'
    if news.tell_event(ctx.store, _npc(ctx), event['id'], told_by=_norm(told_by)):
        return f"{ctx.name} has been told" + (f" by {_norm(told_by)}." if _norm(told_by) else '.')
    if not action_filter.adult(ctx.speaker) and event.get('kind') in worldlog.NO_CHILD_KINDS:
        return ('A child is never told about that.' if action_filter._int(ctx.speaker.get('minor'), 0) > 0 else
                "The game has not said yet whether they are an adult; talk to them once in the game first.")
    return 'Nothing added: they know it already, or it has nothing others could be told.'


def knows_section(gr) -> dict:
    """The Knows about section's components, by load_view key."""
    out = {}
    with gr.Accordion('Knows about', open=False):
        gr.HTML(ui_help.about(SECTION_ABOUT['knows'], 'World events this NPC has heard of, and how: saw it, told by someone, a '
                              'rumour in their town, or hearsay from elsewhere in the hold. News reaches people when they '
                              'next talk. Forget hides their memory of it (nothing is deleted) and stops it reaching them '
                              'again; Tell gives them one memory of it now.'))
        gr.HTML(ui_help.warning())
        out['k_text'] = gr.Markdown('Nothing recorded yet.')
        out['k_table'] = gr.Dataframe(headers=['Day', 'What', 'Event', 'How', 'Told by', 'Since day', 'Taken'],
                                      type='array', interactive=False, wrap=True, height=240,
                                      column_widths=['6%', '11%', '38%', '11%', '12%', '10%', '12%'])
        out['k_pick'] = gr.Dropdown(choices=[], value=None, label='Event they know', interactive=True, filterable=True)
        out['k_who'] = gr.Markdown('')
        with gr.Row():
            out['k_who_btn'] = gr.Button('Who else knows', scale=0, min_width=150)
            out['k_forget_btn'] = gr.Button('Make them forget it', size='sm', variant='stop', elem_classes=['lw-danger'],
                                            scale=0, min_width=180)
        with gr.Row():
            out['k_tell_pick'] = gr.Dropdown(choices=[], value=None, label='Tell them (an event from the world log)',
                                             interactive=True, filterable=True, scale=3)
            out['k_told_by'] = gr.Textbox(label='Told by (optional)', scale=1)
        out['k_tell_btn'] = gr.Button('Tell them', scale=0, min_width=130)
        out['k_said'] = gr.Markdown('')
    return out


# --- the page --------------------------------------------------------------------------------------------------------------

def summary_parts(ctx: Ctx) -> list[str]:
    """Who the picked NPC is and what is in force on them, as short phrases (read only; nothing is written)."""
    npc, entry = ctx.speaker, ctx.entry()
    flags = entry.get('flags') or {}
    out = []
    if npc.get('base_id') or len(npc) > 2:  # the game has written their values (background_view's test)
        live = characters.live_values(npc, ctx.player)
        partner = ((entry.get('pinned') or {}).get('partner') or '').strip()
        if partner:
            out.append(f"believes: {partner}")
        elif live.get('partner'):
            out.append(live['partner'])
        else:  # the game's own NPC-to-NPC spouse (Relationships' ties.json): Alvor is married to Sigrid
            spouses = [t['name'] for t in contracts.ties_of(npc.get('base_id')) if t.get('kind') == 'spouse' and t.get('name')]
            if spouses:
                out.append(f"married to {', '.join(dict.fromkeys(spouses))}")
        if live.get('follower', '').startswith('yes'):
            out.append(f"travels with {ctx.player}")
    else:
        out.append('game values not read yet (talk to them once in the game)')
    if ctx.store is not None:
        try:
            commands = [r for r in release.releasable(ctx.store, [ctx.speaker]) if _binds(r, ctx)]
        except Exception:
            commands = []
        if commands:
            out.append(f"under {len(commands)} absolute command{'s' if len(commands) > 1 else ''}")
    if flags.get('never_intimate'):
        out.append('intimacy: never')
    elif flags.get('bypass_intimacy'):
        out.append('intimacy: always willing')
    else:
        out.append('intimacy: default')
    if flags.get('ignore_commands'):
        out.append('ignores absolute commands')
    return out


def summary_html(ctx: Ctx) -> str:
    """The one line under the NPC picker: name, race and role, then what is active."""
    try:
        npc, entry = ctx.speaker, ctx.entry()
        race = (entry.get('locked') or {}).get('race') or str(npc.get('race') or ctx.race or '').strip()
        role = (entry.get('pinned') or {}).get('role') or characters.live_values(npc, ctx.player).get('role', '')
        who = ', '.join(x for x in (race.capitalize() if race.isupper() else race, role) if x)
        parts = summary_parts(ctx)
    except Exception as e:
        logger.warning(f"Living World: could not sum up {ctx.name} ({e})")
        who, parts = '', []
    return (f'<div class="lw-summary"><b>{html.escape(ctx.name)}</b>'
            + (f'<span>{html.escape(who)}</span>' if who else '')
            + ''.join(f'<span> · {html.escape(p)}</span>' for p in parts) + '</div>')


def load_view(ctx: Ctx | None, running=None) -> dict:
    """Every section of one NPC (all empty, and the editor hidden, without one)."""
    if ctx is None:
        return {'editor': upd(visible=False), 'saved_part': upd(visible=False), 'no_ref': '', 'summary': ''}
    out = {'editor': upd(visible=True), 'saved_part': upd(visible=ctx.store is not None),
           'no_ref': NO_REF_NOTE if ctx.store is None else '', 'summary': summary_html(ctx)}
    for view in (preview_view, lambda c: personality_view(c, running), short_bio_view, background_view, now_view, facts_view,
                 memories_view, commands_view, knows_view):
        try:
            out.update(view(ctx))
        except Exception as e:
            logger.warning(f"Living World: part of {ctx.name}'s page could not be shown ({e})")
    return out


# the one-line description at the top of each section, in the order sent
SECTION_ABOUT = {
    'preview': 'The exact text sent for this NPC, in order.',
    'personality': 'Who they are: their bio and voice. Same in every save.',
    'background': 'Facts at game start: race, role, faith, what they care about. Same in every save.',
    'now': 'Their situation as they believe it, in one paragraph. This save only.',
    'facts': 'Their facts with dates: what changed, when and why. This save only.',
    'memories': 'What they remember, newest first. This save only.',
    'commands': 'Absolute commands in force on them, and what each one hid.',
    'knows': 'World events they have heard of, and how.',
}

INTRO = ('Pick a save and an NPC: everything about them, in the order the model reads it.',
         "Each part below is one part of what this NPC is told, in the order sent: Personality (their bio), Background "
         "(facts at game start), Now (their situation as they believe it), Memories, Commands. Where they differ, the "
         "later part wins. Personality and Background are the same in every save; the rest is per save character. "
         "Marriage, home, follower status and faction membership come from the game: what you type here changes what "
         "they believe, never the game.")


def build(gr, config=None, game_fn=lambda: None, conversations_dir=None) -> None:
    conv = conversations_dir or memory_ui.DEFAULT_CONVERSATIONS
    ask = ui_overrides.model_asker(config) if config is not None else None
    running = lambda: ui_overrides.running_bio_fn(game_fn())
    worlds = memory_ui.saves(conv)
    first = worlds[0] if worlds else None
    c = {}  # component by key, for load_view's keys
    gr.HTML(ui_help.intro(*INTRO))
    with gr.Row():
        world = gr.Dropdown(choices=worlds, value=first, label='Save (your character)', interactive=True, scale=1)
        pick = gr.Dropdown(choices=[p['label'] for p in npc_list(conv, first)], value=None,
                           label='NPC (type to search)', filterable=True, interactive=True, scale=3)
        only = gr.Checkbox(label='Only who remembers you', value=False, scale=0, min_width=240)
        refresh = gr.Button('Refresh list', size='sm', scale=0, min_width=120)
    c['summary'] = gr.HTML('')
    said = gr.Markdown('')
    with gr.Accordion('Add an NPC who is not in the list', open=False):
        gr.HTML(ui_help.label('New NPC', "Only for a new follower or an NPC from a mod that is not in Mantella's list: "
                              "type the name exactly as it shows in game. Anyone already in the list: pick them above "
                              "instead, or the two would clash. Saves your own override file."))
        with gr.Row():
            new_name = gr.Textbox(label='Name', scale=2)
            new_race = gr.Dropdown(choices=ui_overrides.known_races(CSV or ui_overrides.DEFAULT_CSV), value=None, label='Race',
                                   allow_custom_value=True, filterable=True, scale=1)
        new_bio = gr.Textbox(label='Bio (or rough notes; improve it later with Write bio with AI)', lines=4)
        new_btn = gr.Button('Save new NPC', scale=0, min_width=160)
    sure = gr.Checkbox(visible=False)  # the browser's "are you sure?" answer (ui_overrides._confirm_js)
    editor = gr.Column(visible=False)
    c['editor'] = editor
    with editor:
        # 1. prompt preview
        with gr.Accordion('Prompt preview', open=False):
            gr.HTML(ui_help.about(SECTION_ABOUT['preview'], "Everything this NPC is told, in the order sent: the parts "
                                  "below, one after another. Refresh builds it again after a change."))
            c['pv_note'] = gr.Markdown('')
            c['pv_text'] = gr.Textbox(show_label=False, lines=14, max_lines=40, interactive=False, autoscroll=False)
            pv_refresh = gr.Button('Refresh', size='sm', scale=0, min_width=120)
        # 2. personality
        with gr.Accordion('Personality', open=True):
            gr.HTML(ui_help.about(SECTION_ABOUT['personality'], "Who they are: their bio. Your version replaces Mantella's "
                                  "default completely; Mantella's list and the game are never changed. Save bio writes "
                                  "your override file; Apply now loads it into the running Mantella. Version: Default is "
                                  "Mantella's own bio; under it your saved presets."))
            c['badge'] = gr.HTML('')
            with gr.Row():
                c['version'] = gr.Dropdown(choices=[], value=None, label='Version (Default or one of your presets)',
                                           interactive=True, scale=2)
                c['voice'] = gr.Dropdown(choices=ui_overrides.known_voices(CSV or ui_overrides.DEFAULT_CSV), value=None,
                                         label='Voice model', filterable=True, allow_custom_value=True, scale=2)
            c['bio'] = gr.Textbox(show_label=False, lines=10, placeholder='Their bio.', autoscroll=False)
            with gr.Row():
                save_bio_btn = gr.Button('Save bio', variant='primary', scale=0, min_width=140)
                apply_btn = gr.Button('Apply now', scale=0, min_width=140)
                c['ai_btn'] = gr.Button('Optimize with AI', scale=0, min_width=160)
            p_said = gr.Markdown('')
            proposal = gr.Textbox(label='AI proposal (not saved until you press Use this bio and Save bio)', lines=8,
                                  visible=False, interactive=True)
            use_btn = gr.Button('Use this bio', visible=False, scale=0, min_width=140)
            with gr.Row():
                preset_name = gr.Textbox(show_label=False, placeholder='Name this version, e.g. Warm and teasing', scale=3)
                preset_btn = gr.Button('Save as preset', scale=0, min_width=150)
                preset_del = gr.Button('Delete preset', size='sm', variant='stop', elem_classes=['lw-danger'], scale=0, min_width=140)
            with gr.Accordion('Short bio (sent instead of the bio)', open=False):
                gr.HTML(ui_help.label('Short bio', "A long bio is rewritten once into a short sheet without what "
                                      "Background already says, and that is sent instead. It is checked so no name or "
                                      "number is lost; if the check fails the original is sent. Your bio and override "
                                      "file are never changed by this. Use original keeps the original for this NPC."))
                c['sb_status'] = gr.Markdown('')
                with gr.Row():
                    c['sb_original'] = gr.Textbox(label='Original', lines=10, max_lines=30, interactive=False, autoscroll=False)
                    c['sb_short'] = gr.Textbox(label='Short version', lines=10, max_lines=30, interactive=False, autoscroll=False)
                with gr.Row():
                    c['sb_toggle'] = gr.Button('Use original for this NPC', scale=0, min_width=200)
                    sb_again = gr.Button('Optimise again', scale=0, min_width=160)
            with gr.Accordion('Example bio (Hadvar), for reference only', open=False):
                gr.Textbox(value=ui_overrides.EXAMPLE_OVERRIDE, show_label=False, lines=8, interactive=False)
            with gr.Row():
                reset_bio_btn = gr.Button("Reset to Mantella's default", size='sm', variant='stop', elem_classes=['lw-danger'],
                                          scale=0, min_width=200)
        # 3. background
        with gr.Accordion('Background', open=False):
            gr.HTML(ui_help.about(SECTION_ABOUT['background'], "Facts at game start, sent after the bio. Race and sex are "
                                  "read from the game once, then only change when you edit them. Feelings toward groups "
                                  "are filled in where the game makes them clear; change one or add a row to keep it. "
                                  "Custom lines: one per line. Flags are obeyed in Mantella and in the game; a child is "
                                  "never close or intimate, whatever is ticked."))
            c['b_mismatch'] = gr.HTML('')
            c['b_game'] = gr.Markdown('')
            with gr.Row():
                c['b_race'] = gr.Textbox(label='Race', placeholder='From the game', scale=1)
                c['b_sex'] = gr.Dropdown(choices=['', 'male', 'female'], value='', label='Sex', allow_custom_value=True, scale=1)
                c['b_role'] = gr.Textbox(label='Role', placeholder='From the game', scale=2)
                c['b_role_pin'] = gr.Checkbox(label='Keep my role', value=False, scale=0, min_width=140)
            with gr.Row():
                c['b_religion'] = gr.Textbox(label='Religion', placeholder='e.g. follows Mara', scale=1)
                c['b_values'] = gr.Textbox(label='Cares about and will not do', scale=2,
                                           placeholder='Empty: a short one is written from their bio')
            c['b_religion_note'] = gr.Markdown('')
            c['b_stances'] = gr.Dataframe(headers=['Group', 'Feeling', 'Keep'], datatype=['str', 'str', 'bool'],
                                          col_count=(3, 'fixed'), type='array', interactive=True,
                                          label='Feelings toward groups (loves, likes, neutral, dislikes, hates)')
            c['b_custom'] = gr.Textbox(label='Custom lines (one per line)', lines=3, placeholder='Favourite food: sweetrolls')
            gr.HTML(ui_help.label('Flags', 'Obeyed in Mantella and in the game. A child is never close or intimate, '
                                  'whatever is ticked.'))
            flags = []
            for k, text, tip in characters.FLAGS:
                c['flag_' + k] = gr.Checkbox(label=text, info=tip, value=False)
                flags.append(c['flag_' + k])
            with gr.Row():
                save_bg_btn = gr.Button('Save background', variant='primary', scale=0, min_width=160)
                reset_bg_btn = gr.Button('Reset to the game', size='sm', variant='stop', elem_classes=['lw-danger'], scale=0, min_width=160)
            b_said = gr.Markdown('')
        c['no_ref'] = gr.Markdown('')
        saved_part = gr.Column(visible=False)
        c['saved_part'] = saved_part
        with saved_part:
            # 4. now
            with gr.Accordion('Now', open=True):
                gr.HTML(ui_help.about(SECTION_ABOUT['now'], "One paragraph after the Background: their situation as they "
                                      "believe it, in this save. Rewritten after a talk that changed something, a custom event, a game "
                                      "fact that changed, or an Absolute Command given or lifted; never during a talk. "
                                      "Lock keeps your text. The note for others is what OTHER NPCs are told about them "
                                      "(an illusion, a disguise). Gap lines come from a forget that leaves a gap."))
                gr.HTML(ui_help.warning())
                c['n_status'] = gr.Markdown('')
                c['n_mismatch'] = gr.HTML('')
                c['n_text'] = gr.Textbox(label='Now paragraph', lines=3, max_lines=8)
                c['n_lock'] = gr.Checkbox(label='Lock (never rewritten by itself)', value=False)
                c['n_others'] = gr.Textbox(label='Note for others (what other NPCs are told about them)', lines=1)
                c['n_gaps'] = gr.Markdown('')
                with gr.Row():
                    save_now_btn = gr.Button('Save', variant='primary', scale=0, min_width=120)
                    due_btn = gr.Button('Rewrite after next talk', scale=0, min_width=200)
                    gaps_btn = gr.Button('Clear gap lines', scale=0, min_width=160)
                    reset_now_btn = gr.Button('Reset', size='sm', variant='stop', elem_classes=['lw-danger'], scale=0, min_width=120)
                n_said = gr.Markdown('')
            # 5. facts history
            with gr.Accordion('Facts history', open=False):
                gr.HTML(ui_help.about(SECTION_ABOUT['facts'], "Their facts with dates, in this save. Lines from the game "
                                      "are read-only. Your own lines can be added and ended; a line can be hidden from them "
                                      "(shown here only, never sent). Since: game day. On hold: replaced for now; it "
                                      "comes back when what replaced it ends."))
                gr.HTML(ui_help.warning())
                c['f_mismatch'] = gr.HTML('')
                c['f_note'] = gr.Markdown('')
                c['f_table'] = gr.Dataframe(headers=['Fact', 'Value', 'Since', 'Cause', 'Status', 'They know', 'From'],
                                            type='array', interactive=False, wrap=True, height=320,
                                            column_widths=['12%', '26%', '7%', '25%', '10%', '10%', '10%'])
                with gr.Row():
                    c['f_pick'] = gr.Dropdown(choices=[], value=None, label='Line', interactive=True, scale=3)
                    f_visible = gr.Checkbox(label='They know it', value=True, scale=0, min_width=140)
                with gr.Row():
                    f_vis_btn = gr.Button('Save "They know it"', scale=0, min_width=180)
                    f_end_btn = gr.Button('End this line', size='sm', variant='stop', elem_classes=['lw-danger'], scale=0, min_width=150)
                with gr.Row():
                    f_kind = gr.Dropdown(choices=list(ADD_FACTS), value='Custom line', label='New line', scale=1)
                    f_value = gr.Textbox(label='Text', scale=3)
                    f_new_visible = gr.Checkbox(label='They know it', value=True, scale=0, min_width=140)
                f_add_btn = gr.Button('Add line', scale=0, min_width=140)
                f_said = gr.Markdown('')
            # 6. memories
            with gr.Accordion('Memories', open=False):
                gr.HTML(ui_help.about(SECTION_ABOUT['memories'], "What they remember, newest first. How known: seen, told by someone, "
                                      "rumour or their own thought. In mind: sent every talk; older ones come back when a "
                                      "talk is about them. Hidden: kept, never sent; Unhide brings it back. Set aside: made "
                                      "after the save you loaded (back when you load the newer save). Delete removes one "
                                      "for good (a backup is kept)."))
                gr.HTML(ui_help.warning())
                c['m_mood'] = gr.Markdown('')
                c['m_count'] = gr.Markdown('')
                with gr.Row():
                    m_search = gr.Textbox(show_label=False, placeholder='Search their memories', scale=3)
                    m_search_btn = gr.Button('Search', size='sm', scale=0, min_width=120)
                c['m_table'] = gr.Dataframe(headers=['Day', 'Hour', 'Memory', 'How known', 'Spell', 'State', 'Importance', 'Story'],
                                            type='array', interactive=False, wrap=True,
                                            column_widths=['5%', '5%', '40%', '10%', '10%', '11%', '9%', '10%'])
                c['m_pick'] = gr.Dropdown(choices=[], value=None, label='Memory', interactive=True, filterable=True)
                c['m_edit'] = gr.Textbox(label='Text of the picked memory', lines=3)
                with gr.Row():
                    m_save_btn = gr.Button('Save edit', variant='primary', scale=0, min_width=130)
                    m_hide_btn = gr.Button('Hide', scale=0, min_width=100)
                    m_unhide_btn = gr.Button('Unhide', scale=0, min_width=100)
                    m_delete_btn = gr.Button('Delete', size='sm', variant='stop', elem_classes=['lw-danger'], scale=0, min_width=100)
                with gr.Row():
                    m_new = gr.Textbox(label='Add a memory (one per line)', lines=2, scale=3,
                                       placeholder='What happened, from their point of view; or rough notes for the AI button')
                    m_source = gr.Dropdown(choices=list(SOURCE_LABELS.values()), value='seen', label='How known', scale=1)
                    m_told = gr.Textbox(label='Told by', scale=1)
                with gr.Row():
                    m_add_btn = gr.Button('Add memory', scale=0, min_width=140)
                    m_ai_btn = gr.Button('Turn notes into memories (AI)', scale=0, min_width=230)
                with gr.Accordion('How they feel and long-term notes', open=False):
                    c['m_feeling'] = gr.Textbox(label='How they feel about you (one line)')
                    m_feeling_btn = gr.Button('Save feeling', scale=0, min_width=140)
                    c['m_long'] = gr.Dataframe(headers=['Topic', 'What they remember'], datatype=['str', 'str'], type='array',
                                               row_count=(1, 'dynamic'), col_count=(2, 'fixed'), interactive=True, wrap=True)
                    m_long_btn = gr.Button('Save notes', scale=0, min_width=140)
                with gr.Accordion('Stories (linked memories kept together)', open=False):
                    c['a_table'] = gr.Dataframe(headers=['Story', 'Summary', 'Day', 'Memories'], type='array',
                                                interactive=False, wrap=True, height=260,
                                                column_widths=['22%', '56%', '8%', '14%'])
                    c['a_pick'] = gr.Dropdown(choices=[], value=None, label='Story', interactive=True)
                    with gr.Row():
                        a_name = gr.Textbox(label='Name', scale=1)
                        a_summary = gr.Textbox(label='Summary', scale=3)
                    with gr.Row():
                        a_rename_btn = gr.Button('Save name and summary', scale=0, min_width=200)
                        a_in_btn = gr.Button('Move picked memory in', scale=0, min_width=190)
                        a_out_btn = gr.Button('Take picked memory out', scale=0, min_width=190)
                    c['a_merge'] = gr.Dropdown(choices=[], value=[], multiselect=True, label='Merge these into the picked story')
                    with gr.Row():
                        a_merge_btn = gr.Button('Merge', scale=0, min_width=120)
                        a_new_btn = gr.Button('New story (with the picked memory)', scale=0, min_width=240)
                        a_del_btn = gr.Button('Remove story', size='sm', variant='stop', elem_classes=['lw-danger'], scale=0, min_width=140)
                with gr.Row():
                    m_forget_all = gr.Button("Delete all of this NPC's memories", size='sm', variant='stop',
                                             elem_classes=['lw-danger'], scale=0, min_width=240)
                m_said = gr.Markdown('')
            # 7. commands
            with gr.Accordion('Commands', open=False):
                gr.HTML(ui_help.about(SECTION_ABOUT['commands'], "Absolute commands in force on them (given with the "
                                      "Absolute Command hotkey, G by default). Release ends one: remembers and knows it was a spell, "
                                      "forgets the whole period, or keeps believing. Forget hides memories (nothing is "
                                      "deleted). The record below is the truth the NPC is never told: what was hidden or "
                                      "deleted, which days, by whom."))
                c['c_list'] = gr.HTML('')
                c['c_pick'] = gr.Dropdown(choices=[], value=None, label='Command', interactive=True)
                c_choice = gr.Radio(choices=list(CHOICE_LABELS), value=next(iter(CHOICE_LABELS)), label='When released, they...')
                c_mode = gr.Radio(choices=list(MODE_LABELS), value='Clean (they notice nothing)', label='If they forget')  # a gap only when asked
                with gr.Row():
                    c['c_marriage'] = gr.Checkbox(label='Also end the marriage made under it (asked in the game)',
                                                  value=False, visible=False)
                    c_everyone = gr.Checkbox(label='Release it for everyone it binds', value=False)
                c_release_btn = gr.Button('Release', variant='primary', scale=0, min_width=130)
                with gr.Row():
                    c_what = gr.Textbox(label='Forget (what they should forget)', placeholder='e.g. the night at the Bannered Mare', scale=3)
                    c_forget_btn = gr.Button('Forget', size='sm', variant='stop', elem_classes=['lw-danger'], scale=0, min_width=120)
                c['c_record'] = gr.Dataframe(headers=['When (real time)', 'What', 'About', 'Game days', 'By', 'How'],
                                             type='array', interactive=False, wrap=True, height=200,
                                             label='True record (what really happened; never told to them)')
                c_said = gr.Markdown('')
            # 8. knows about
            k = knows_section(gr)
            for key in ('k_text', 'k_table', 'k_pick', 'k_tell_pick', 'k_who'):
                c[key] = k[key]

    def to_gr(value):
        return gr.update(**value['__update__']) if isinstance(value, dict) and '__update__' in value else value

    def outs(keys, view: dict, extra=()):
        return [*extra, *(to_gr(view[k]) if k in view else gr.update() for k in keys)]

    def guard(fn, count):
        """Runs a handler; on any error the status says so and nothing else on the page changes (no typed text lost)."""
        def run(*args):
            try:
                return fn(*args)
            except Exception as e:
                logger.warning(f"Living World: NPC page action failed ({e})")
                return (f"That did not work, nothing was changed: {e}",) + tuple(gr.update() for _ in range(count - 1))
        return run

    def notify(text):
        return ui_overrides._notify(gr, text)

    ALL = [k for k in c]
    SECTION = {
        'preview': ['pv_note', 'pv_text'],
        'personality': ['bio', 'voice', 'version', 'badge', 'ai_btn'],
        'short': ['sb_status', 'sb_original', 'sb_short', 'sb_toggle'],
        'background': ['b_race', 'b_sex', 'b_game', 'b_role', 'b_role_pin', 'b_religion', 'b_religion_note', 'b_values',
                       'b_stances', 'b_custom', 'b_mismatch'] + ['flag_' + k for k in characters.FLAG_KEYS],
        'now': ['n_status', 'n_mismatch', 'n_text', 'n_lock', 'n_others', 'n_gaps'],
        'facts': ['f_table', 'f_pick', 'f_mismatch', 'f_note'],
        'memories': ['m_mood', 'm_count', 'm_table', 'm_pick', 'm_edit', 'm_feeling', 'm_long', 'a_table', 'a_pick', 'a_merge'],
        'commands': ['c_list', 'c_pick', 'c_marriage', 'c_record'],
        'knows': ['k_text', 'k_table', 'k_pick', 'k_tell_pick', 'k_who'],
    }
    VIEW = {'preview': preview_view, 'personality': lambda x: personality_view(x, running()), 'short': short_bio_view,
            'background': background_view,
            'now': now_view, 'facts': facts_view, 'memories': memories_view, 'commands': commands_view,
            'knows': knows_view}

    def comps(keys):
        return [c[k] for k in keys]

    def show(w, label):
        return outs(ALL, load_view(context(conv, w, label), running()))

    def relist(w, o, keep=None):
        choices = [p['label'] for p in npc_list(conv, w, bool(o))]
        return gr.update(choices=choices, value=same_label(choices, keep))

    # one action: (status, refreshed sections and the summary line); act(fn, sections, inputs) -> the click handler
    def act(fn, sections, extra_outputs=0):
        keys = [k for s in sections for k in SECTION[s]] + ['summary']

        def run(w, label, *args):
            ctx = context(conv, w, label)
            if ctx is None:
                return (NO_PICK,) + tuple(gr.update() for _ in range(extra_outputs + len(keys)))
            result = fn(ctx, *args)
            message, extra = (result[0], tuple(result[1:])) if isinstance(result, tuple) else (result, ())
            view = {'summary': summary_html(ctx)}  # a Release or Save changes what is in force: the line follows
            for s in sections:
                view.update(VIEW[s](ctx))
            return (notify(message), *extra, *outs(keys, view))
        return guard(run, 1 + extra_outputs + len(keys)), keys

    def wire(button, fn, sections, inputs, status, js=None, extra=()):
        handler, keys = act(fn, sections, len(extra))
        kwargs = {'js': js} if js else {}
        button.click(handler, inputs=[world, pick] + inputs, outputs=[status, *extra] + comps(keys), **kwargs)

    def wire_sure(button, fn, sections, inputs, status, question):
        """A button that asks first: the hidden checkbox gets the browser's answer (it must be the first input)."""
        handler, keys = act(lambda ctx, ok, *a: fn(ctx, *a, ok), sections)
        button.click(lambda ok, w, label, *a: handler(w, label, ok, *a), inputs=[sure, world, pick] + inputs,
                     outputs=[status] + comps(keys), js=ui_overrides._confirm_js(question))

    # picking
    pick.change(lambda l: 'Loading...' if l else '', inputs=[pick], outputs=[said]).then(
        guard(lambda w, l: ['', *show(w, l)], 1 + len(ALL)), inputs=[world, pick], outputs=[said] + comps(ALL))
    world.change(lambda w, o: (relist(w, o), ''), inputs=[world, only], outputs=[pick, said])
    only.change(lambda w, o: relist(w, o), inputs=[world, only], outputs=[pick])
    refresh.click(lambda w, o, l: (relist(w, o, l), 'List read again.'), inputs=[world, only, pick], outputs=[pick, said])

    def add_new(w, o, n, r, b):
        problem = new_npc(n, r, b)
        if problem:
            return problem, gr.update(), gr.update(), gr.update()
        return notify(f"Saved {n.strip()}. Press Apply now in Personality to use it this session."), \
            relist(w, o, n.strip()), '', ''
    new_btn.click(guard(add_new, 4), inputs=[world, only, new_name, new_race, new_bio], outputs=[said, pick, new_name, new_bio])

    # sections
    pv_refresh.click(act(lambda ctx: 'Preview built again.', ['preview'])[0], inputs=[world, pick],
                     outputs=[said] + comps(SECTION['preview']))
    wire(save_bio_btn, save_personality, ['personality', 'short', 'preview'], [c['bio'], c['voice']], p_said)
    wire(c['sb_toggle'], toggle_original, ['short', 'preview'], [], p_said)
    wire(sb_again, optimise_again, ['short', 'preview'], [], p_said)
    apply_btn.click(guard(lambda: notify(apply_overrides(game_fn())), 1), outputs=[p_said])

    def ai(ctx, b):
        text, message = optimize(ctx, ask, b)
        return message, gr.update(value=text, visible=bool(text)), gr.update(visible=bool(text))
    wire(c['ai_btn'], ai, [], [c['bio']], p_said, extra=(proposal, use_btn))
    use_btn.click(lambda p: (p, gr.update(visible=False), gr.update(visible=False), 'Copied into the bio. Press Save bio to keep it.'),
                  inputs=[proposal], outputs=[c['bio'], proposal, use_btn, p_said])
    wire(preset_btn, lambda ctx, n, b: save_preset(ctx, n, b), ['personality'], [preset_name, c['bio']], p_said)
    wire_sure(preset_del, lambda ctx, v, ok: delete_preset(ctx, v) if ok else 'Not deleted.', ['personality'],
              [c['version']], p_said, 'Delete this preset? A saved override using the same text stays as it is.')
    wire_sure(reset_bio_btn, lambda ctx, ok: reset_personality(ctx, config) if ok else 'Not reset.', ['personality', 'preview'],
              [], p_said, "Reset this NPC to Mantella's default bio and voice?")

    def version_pick(w, label, choice, current):
        ctx = context(conv, w, label)
        keys = SECTION['background']
        if ctx is None or not choice:
            return (gr.update(), '', *(gr.update() for _ in keys))
        default = ui_overrides.default_bio(ctx.row, CSV or ui_overrides.DEFAULT_CSV)
        text = ui_overrides.version_text(choice, ctx.row, default, ui_overrides._own_bio(ctx.row, _overrides()), _presets())
        profile = ui_overrides.npc_preset_profile(_presets(), ctx.row, choice)
        same = text is None or _norm(text) == _norm(current)
        bg = {}
        if profile:  # a preset saved with its Background fills those fields too (saved with Save background)
            ctx.entry = lambda: profile
            bg = background_view(ctx)
        if same and not profile:
            return (gr.update(), '', *(gr.update() for _ in keys))
        note = f"'{choice}' is in the bio box" + (' and Background' if profile else '') + '. Nothing is saved until you press Save.'
        return (gr.update() if same else text, note, *outs(keys, bg))
    c['version'].change(guard(version_pick, 2 + len(SECTION['background'])), inputs=[world, pick, c['version'], c['bio']],
                        outputs=[c['bio'], p_said] + comps(SECTION['background']))

    wire(save_bg_btn, lambda ctx, *v: save_background(ctx, *v[:8], list(v[8:])), ['background', 'preview'],
         [c['b_race'], c['b_sex'], c['b_role'], c['b_role_pin'], c['b_religion'], c['b_values'], c['b_stances'], c['b_custom']] + flags,
         b_said)
    wire_sure(reset_bg_btn, lambda ctx, ok: reset_background(ctx) if ok else 'Not reset.', ['background', 'preview'], [], b_said,
              "Reset this NPC's Background to the game's values? Race, sex, role, religion, values, feelings and custom lines go; flags stay.")

    wire(save_now_btn, save_now, ['now', 'preview'], [c['n_text'], c['n_lock'], c['n_others']], n_said)
    wire(due_btn, rewrite_soon, ['now'], [], n_said)
    wire(gaps_btn, clear_gaps, ['now', 'preview'], [], n_said)
    wire_sure(reset_now_btn, lambda ctx, ok: reset_now(ctx) if ok else 'Not reset.', ['now', 'preview'], [], n_said,
              'Clear the Now paragraph? It grows again from what happens next.')

    c['f_pick'].change(guard(lambda w, l, line: fact_visible(context(conv, w, l), line) if context(conv, w, l) else True, 1),
                       inputs=[world, pick, c['f_pick']], outputs=[f_visible])
    wire(f_vis_btn, set_fact_visible, ['facts', 'preview'], [c['f_pick'], f_visible], f_said)
    wire_sure(f_end_btn, lambda ctx, line, ok: end_fact(ctx, line) if ok else 'Nothing ended.', ['facts', 'background', 'preview'],
              [c['f_pick']], f_said, 'End this line? It stays in the history as ended.')
    wire(f_add_btn, add_fact, ['facts', 'background', 'preview'], [f_kind, f_value, f_new_visible], f_said)

    c['m_pick'].change(guard(lambda w, l, m: memory_text(context(conv, w, l), m) if context(conv, w, l) else '', 1),
                       inputs=[world, pick, c['m_pick']], outputs=[c['m_edit']])
    search = lambda ctx, q: ('Search done.' if _norm(q) else 'Showing every memory.')
    for trigger in (m_search_btn.click, m_search.submit):
        trigger(act(lambda ctx, q: (search(ctx, q), *outs(SECTION['memories'], memories_view(ctx, q))), [],
                    len(SECTION['memories']))[0], inputs=[world, pick, m_search], outputs=[m_said] + comps(SECTION['memories']))
    wire(m_save_btn, edit_memory, ['memories', 'preview'], [c['m_pick'], c['m_edit']], m_said)
    wire(m_hide_btn, hide_memory, ['memories', 'commands', 'preview'], [c['m_pick']], m_said)
    wire(m_unhide_btn, unhide_memory, ['memories', 'preview'], [c['m_pick']], m_said)
    wire_sure(m_delete_btn, delete_memory, ['memories', 'commands', 'preview'], [c['m_pick']], m_said,
              'Delete this memory for good? Hide keeps it and can be undone; Delete cannot (a backup file is kept).')
    wire(m_add_btn, add_memory, ['memories', 'preview'], [m_new, m_source, m_told], m_said)

    def ai_notes(ctx, notes):
        text, message = notes_to_lines(ctx, ask, notes)
        return message, gr.update(value=text) if text else gr.update()
    wire(m_ai_btn, ai_notes, [], [m_new], m_said, extra=(m_new,))
    wire(m_feeling_btn, save_feeling, ['memories', 'preview'], [c['m_feeling']], m_said)
    wire(m_long_btn, save_long_term, ['memories', 'preview'], [c['m_long']], m_said)
    wire_sure(m_forget_all, forget_everything, ['memories', 'now', 'preview'], [], m_said,
              "Delete ALL of this NPC's memories of you in this save? Memories, feeling and notes go (moved to "
              "living_world_memory_removed).")
    c['a_pick'].change(guard(lambda w, l, a: arc_fields(context(conv, w, l), a) if context(conv, w, l) else ('', ''), 2),
                       inputs=[world, pick, c['a_pick']], outputs=[a_name, a_summary])
    wire(a_rename_btn, rename_arc, ['memories'], [c['a_pick'], a_name, a_summary], m_said)
    wire(a_merge_btn, merge_arcs, ['memories'], [c['a_pick'], c['a_merge']], m_said)
    wire(a_in_btn, lambda ctx, m, a: move_to_arc(ctx, m, a), ['memories'], [c['m_pick'], c['a_pick']], m_said)
    wire(a_out_btn, take_from_arc, ['memories'], [c['m_pick']], m_said)
    wire(a_new_btn, lambda ctx, n, m: new_arc(ctx, n, m), ['memories'], [a_name, c['m_pick']], m_said)
    wire_sure(a_del_btn, lambda ctx, a, ok: delete_arc(ctx, a) if ok else 'Nothing removed.', ['memories'], [c['a_pick']],
              m_said, 'Remove this story? Its memories stay.')

    wire_sure(c_release_btn, lambda ctx, cmd, ch, mo, em, ev, ok: release_one(ctx, cmd, ch, mo, em, ev, ok, ask),
              ['commands', 'now', 'facts', 'memories', 'preview'],
              [c['c_pick'], c_choice, c_mode, c['c_marriage'], c_everyone], c_said, 'Release this command?')
    wire_sure(c_forget_btn, lambda ctx, what, mo, ok: forget_now(ctx, what, mo, ok), ['commands', 'now', 'memories', 'preview'],
              [c_what, c_mode], c_said, 'Hide the memories that match? Nothing is deleted; Unhide brings them back.')

    k['k_who_btn'].click(guard(lambda w, l, e: who_knows(context(conv, w, l), e) if context(conv, w, l) else NO_PICK, 1),
                         inputs=[world, pick, c['k_pick']], outputs=[c['k_who']])
    wire_sure(k['k_forget_btn'], lambda ctx, e, ok: forget_known(ctx, e, ok), ['knows', 'memories', 'preview'],
              [c['k_pick']], k['k_said'], 'Make them forget this event? Their memory of it is hidden (nothing is deleted).')
    wire(k['k_tell_btn'], tell_known, ['knows', 'memories', 'preview'], [c['k_tell_pick'], k['k_told_by']], k['k_said'])
