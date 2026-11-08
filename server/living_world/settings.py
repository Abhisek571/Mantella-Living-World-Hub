"""Living World settings, edited in the tab and kept next to the extension: extensions/living_world/settings.json.
Missing or broken values fall back to the defaults."""
import json
import os

DEFAULTS = {
    'action_filter': True,     # offer each NPC only the actions that fit them
    'memory_budget': 1500,     # tokens of memory per conversation (close NPCs and followers)
    'memory_budget_stranger': 400,  # tokens of memory for everyone else
    'lore_budget': 150,        # tokens of lore per reply (Knowledge add-on)
    'story_control': True,     # the custom-event limits line (00_hub.txt)
    'bio_examples': -1,        # example dialogue lines kept from each stock bio (-1 = all)
    'short_actions': True,     # first sentence of each action's description only
    'knowledge_mode': 'full',  # Knowledge: 'full' (profiles and lore), 'profiles' (no lore lines) or 'off'
    'dragonborn_secret': False, # Knowledge: nobody connects the Dragonborn news to the player
    'world_note': True,
    'basic_bios': True,        # NPCs with no bio get a short one from their race, job and home (not Mantella's one line)        # World: what NPCs know of the player's fame, bounty and deeds
    'trim_after_tokens': 8000, # save the memory and trim a talk once it is this long (0 = Mantella's own limit)
    'disabled_rules': [],      # rule files switched off
    'update_check_days': 3,    # ask Nexus every this many days whether installed modules have a newer version (0 = never)
    # gates for actions whose files carry none (stock Mantella): Inventory hands over any NPC's items, Attack works on anyone
    'action_gates': {'Inventory': 'follower', 'Attack': 'follower'},
}
STORY_CONTROL_FILE = '00_hub.txt'
PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'settings.json')
OVERRIDES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'profile_overrides.json')


def load(path: str = PATH) -> dict:
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError, RecursionError):
        data = {}
    out = dict(DEFAULTS)
    for key, default in DEFAULTS.items():
        value = data.get(key) if isinstance(data, dict) else None
        if type(value) is type(default):  # also keeps true/false out of number settings
            out[key] = value
    out['disabled_rules'] = [r for r in out['disabled_rules'] if isinstance(r, str)]
    out['action_gates'] = {k: v for k, v in out['action_gates'].items() if isinstance(k, str) and isinstance(v, str) and k and v}
    return out


def save(path: str, values: dict) -> None:
    clean = {key: values.get(key, default) for key, default in DEFAULTS.items()}
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(clean, f, indent=2)
    os.replace(tmp, path)


def load_profile_overrides(path: str = OVERRIDES_PATH) -> dict:
    """The player's own "what wins them over" ratings: {"NPC name": {"talk": 1, "deeds": 2, "care": 2, "gifts": 2, "physical": 3}}."""
    try:
        with open(path, encoding='utf-8-sig') as f:
            data = json.load(f)
    except (OSError, ValueError, RecursionError):
        return {}
    return data if isinstance(data, dict) else {}


def disabled_rules(values: dict) -> list[str]:
    """Rule files to leave out: the ones switched off, plus the story-control line when that is off."""
    off = list(values.get('disabled_rules', []))
    if not values.get('story_control', True) and STORY_CONTROL_FILE not in off:
        off.append(STORY_CONTROL_FILE)
    return off
