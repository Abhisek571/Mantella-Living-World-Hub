"""Offers each NPC only the actions that fit them. An action JSON may carry "lw_gate":
    close     a friend or closer (vanilla rank 1+, a teammate, Arousal's standing, Relationships engaged or married)
    intimate  a lover: vanilla rank 4, Relationships dating or closer, an Arousal open group, or the player's own
              Allow-intimacy choice on the Living World hotkey
    follower  in the party (a teammate or hired)
    unrated   positions not rated yet (OStim Expansion)
    guard     a guard of this hold
    adult     anyone who is not a child, and never while a child is in the talk (e.g. OStim Expansion's couple dance)
    field=N   the NPC's file has that int field at N (e.g. "maras=1" by Relationships, "nff=1" by Followers)
    a+b       every one of the gates (e.g. "intimate+unrated")
No gate = always offered. In a group the actions are the union of what each speaker may use, and one line tells the
model who may use which. With a child among the speakers no close, intimate or adult action is offered to anyone. Actions
from other mods (stock Mantella's Inventory, Attack) get a gate from the Hub settings (action_gates). The filter fails closed: with no speaker list from the game (file missing or half-written) or
a gate it does not know, gated actions are left out and only ungated ones are offered."""
import json
import logging
import re
import os

def _int(value, default=-1) -> int:
    """A field as a number, whatever a hand edit or another writer left there ("1", a list)."""
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


GATE_OPEN = {
    'close': lambda npc: _int(npc.get('close'), 0) > 0,
    'intimate': lambda npc: _int(npc.get('intimate'), 0) > 0,
    'follower': lambda npc: _int(npc.get('follower'), 0) > 0,
    'unrated': lambda npc: _int(npc.get('rated'), 0) == 0,
    'guard': lambda npc: _int(npc.get('guard'), 0) > 0,
    'adult': lambda npc: _int(npc.get('minor'), 0) == 0,
}

ADULT_GATES = {'close', 'intimate', 'adult'}

_cache: dict = {'dir': None, 'stamp': None, 'gates': {}}


def with_settings(gates: dict[str, str], extra) -> dict[str, str]:
    """The action files' gates with the settings' action_gates on top (settings win); a non-text entry is ignored."""
    merged = dict(gates)
    if isinstance(extra, dict):
        merged.update({k: v for k, v in extra.items() if isinstance(k, str) and isinstance(v, str) and k and v})
    return merged


def load_gates(actions_dir: str = 'data/actions') -> dict[str, str]:
    """Tool name -> gate, from the action JSON files; re-read when a file there changes."""
    try:
        files = sorted(f for f in os.listdir(actions_dir) if f.endswith('.json'))
        stamp = tuple((f, os.path.getmtime(os.path.join(actions_dir, f))) for f in files)
    except OSError:
        return {}
    if _cache['dir'] == actions_dir and _cache['stamp'] == stamp:
        return _cache['gates']
    gates = {}
    for f in files:
        try:
            with open(os.path.join(actions_dir, f), encoding='utf-8') as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        for action in data if isinstance(data, list) else [data]:  # Mantella also loads files holding a list
            if isinstance(action, dict) and action.get('lw_gate') and action.get('name'):
                gates[action['name']] = action['lw_gate']
    _cache.update(dir=actions_dir, stamp=stamp, gates=gates)
    return gates


def _name(tool: dict) -> str:
    return (tool.get('function') or tool).get('name', '')


_warned_gates: set = set()


def may_use(npc: dict, gate: str | None) -> bool:
    if not gate:
        return True
    if '+' in gate:
        return all(part and may_use(npc, part) for part in gate.split('+'))  # "close+" is a typo: closed
    field = re.fullmatch(r'(\w+)=(-?\d+)', gate)
    if field:  # "maras=1": the NPC's file field has that value
        return _int(npc.get(field.group(1))) == int(field.group(2))
    test = GATE_OPEN.get(gate)
    if test is None:  # a typo in an action file must not open the action to everyone
        if gate not in _warned_gates:
            _warned_gates.add(gate)
            logging.getLogger('Mantella').warning(f"Living World: unknown action gate '{gate}'; that action is not offered")
        return False
    return bool(test(npc))


def filter_actions(actions: list[dict], speakers: list[dict], gates: dict[str, str]) -> list[dict]:
    """The actions at least one speaker may use, sorted by name so the list stays the same reply to reply. With no
    speakers known only ungated actions are kept. A child among the speakers takes every close, intimate or adult action out
    (all of them are adult ones)."""
    if any(_int(s.get('minor'), 0) > 0 for s in speakers or []):
        actions = [a for a in actions if not ADULT_GATES & set((gates.get(_name(a)) or '').split('+'))]
    if speakers:
        keep = [a for a in actions if any(may_use(s, gates.get(_name(a))) for s in speakers)]
    else:
        keep = [a for a in actions if not gates.get(_name(a))]
    return sorted(keep, key=_name)


def speaker_note(actions: list[dict], speakers: list[dict], gates: dict[str, str]) -> str:
    """One line for group talks: which gated actions only some speakers may use."""
    if len(speakers) < 2:
        return ''
    allowed: dict[str, list[str]] = {}
    for action in actions:
        name = _name(action)
        users = [s.get('name', '?') for s in speakers if may_use(s, gates.get(name))]
        if len(users) < len(speakers):
            allowed.setdefault(', '.join(users), []).append(name)
    if not allowed:
        return ''
    return '(' + ' '.join(f"Only {who} may use: {', '.join(sorted(names))}." for who, names in sorted(allowed.items())) + ')'


def shorten(actions: list[dict], gates: dict[str, str] | None = None) -> list[dict]:
    """Copies with each action's description cut to its first sentence (the model only needs to know what the action
    does; the rest repeats when-to-use advice). Gated actions keep their whole description: theirs holds the consent
    and safety conditions. Parameters are kept as they are."""
    out = []
    for action in actions:
        function = action.get('function')
        text = (function or {}).get('description')
        if not isinstance(text, str) or (gates or {}).get(_name(action)):
            out.append(action)
            continue
        first = re.split(r'(?<=[.!?])\s+', text.strip(), maxsplit=1)[0]
        out.append(dict(action, function=dict(function, description=first)))
    return out
