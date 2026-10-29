"""Offers each NPC only the actions that fit them. An action JSON may carry "lw_gate":
    close     a friend or closer (MLW_IsClose from Arousal/Relationships), or an open group
    follower  in the party or a potential follower
    unrated   positions not rated yet (OStim Expansion)
    guard     a guard of this hold
    field=N   the NPC's file has that int field at N (e.g. "maras=1", written by Relationships)
    a+b       every one of the gates (e.g. "close+unrated")
No gate = always offered. In a group the actions are the union of what each speaker may use, and one line tells the
model who may use which. The filter fails closed: with no speaker list from the game (file missing or half-written) or
a gate it does not know, gated actions are left out and only ungated ones are offered."""
import json
import logging
import re
import os

GATE_OPEN = {
    'close': lambda npc: npc.get('close', 0) > 0,
    'follower': lambda npc: npc.get('follower', 0) > 0,
    'unrated': lambda npc: npc.get('rated', 0) == 0,
    'guard': lambda npc: npc.get('guard', 0) > 0,
}

_cache: dict = {'dir': None, 'stamp': None, 'gates': {}}


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
        return npc.get(field.group(1)) == int(field.group(2))
    test = GATE_OPEN.get(gate)
    if test is None:  # a typo in an action file must not open the action to everyone
        if gate not in _warned_gates:
            _warned_gates.add(gate)
            logging.getLogger('Mantella').warning(f"Living World: unknown action gate '{gate}'; that action is not offered")
        return False
    return bool(test(npc))


def filter_actions(actions: list[dict], speakers: list[dict], gates: dict[str, str]) -> list[dict]:
    """The actions at least one speaker may use, sorted by name so the list stays the same reply to reply. With no
    speakers known only ungated actions are kept."""
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
