"""Living World settings, edited in the tab and kept next to the extension: extensions/living_world/settings.json.
Missing or broken values fall back to the defaults."""
import json
import os

DEFAULTS = {
    'action_filter': True,     # offer each NPC only the actions that fit them
    'intimacy_check': 'npc_decides',  # 'npc_decides' (every adult is offered the scene and decides) or 'lovers_only'
    'memory_budget': 1500,     # tokens of memory per conversation (close NPCs and followers)
    'memory_budget_stranger': 400,  # tokens of memory for everyone else
    'lore_budget': 150,        # tokens of lore per reply (Knowledge add-on)
    'story_control': True,     # the custom-event limits line (00_hub.txt)
    'bio_examples': 3,         # example dialogue lines kept from each stock bio (-1 = all; short and hand-set bios are never cut)
    'short_actions': True,     # first sentence of each action's description only
    'knowledge_mode': 'full',  # Knowledge: 'full' (profiles and lore), 'profiles' (no lore lines) or 'off'
    'dragonborn_secret': False, # Knowledge: nobody connects the Dragonborn news to the player
    'world_note': True,
    'basic_bios': True,        # NPCs with no bio get a short one from their race, job and home (not Mantella's one line)        # World: what NPCs know of the player's fame, bounty and deeds
    'bio_optimise': True,      # each long bio is rewritten once into a short sheet (bio_optimise.py); off: originals are sent
    'trim_after_tokens': 8000, # save the memory and trim a talk once it is this long (0 = Mantella's own limit)
    'memory_recall': True,     # older memories that fit the talk come back (by meaning with the search model, else by words)
    'memory_model_download': True,  # fetch the 23 MB memory search model once if it is not shipped (checksum checked)
    'chatter_filter': True,    # stock barks and lines heard over and over never become memories
    'follower_diary': False,   # followers write one short diary memory per game day (one extra summary call a day)
    'custom_events_silent': False,  # custom events are silent unless they start with "react:" (else narrated unless "silent:")
    'bio_changes': True,       # a short "how they have changed" note after each NPC's bio, written from their memories
    'bio_changes_talks': 5,    # talks between two updates of that note (sooner after important memories)
    'command_hours': 0,        # absolute commands last this many game hours unless the command says (0 = until removed)
    'command_model_check': True,  # one short summary request per absolute command: what to forget, how long, who knows
    'command_forget_limit': 8, # memories one absolute command can hide per NPC
    'console_actions': True,   # the Console button's action is offered on the turn after a wish (the MCM's Console switch, off by default, is the main one)
    'disabled_rules': [],      # rule files switched off
    'mod_facts_generated': False,  # use the scanned (generated) mod fact files too; shipped and user files always apply
    'mod_facts_mo2': '',       # Mod Organizer 2 instance folder for Scan my dialogue mods ('' = found by itself or unset)
    'mod_facts_data': '',      # without Mod Organizer: the game's Data folder to scan
    'mod_facts_plugins': '',   # without Mod Organizer: plugins.txt ('' = %LOCALAPPDATA%\Skyrim Special Edition\plugins.txt)
    'stage_timing': False,     # speed testing: the game side and this side write stage times (timing_game.csv, timing_backend.csv)
    'prepare_npc_data': False, # speed testing: the game side prepares an NPC's file when the player aims at them
    'update_check_days': 3,    # ask Nexus every this many days whether installed modules have a newer version (0 = never)
    'hide_lip_notice': False,  # Status page: leave out the line saying Mantella's lip sync files are missing
    # gates for actions whose files carry none (stock Mantella): Inventory hands over any NPC's items, Attack works on anyone
    'action_gates': {'Inventory': 'follower', 'Attack': 'follower'},
}
INTIMACY_MODES = ('lovers_only', 'npc_decides')  # by index: the number in intimacy_settings.json and the MCM's global
OLD_INTIMACY = {'strict': 'lovers_only', 'relaxed': 'npc_decides', 'any_adult': 'npc_decides'}
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
    # the three older values: Strict became Lovers only, Relaxed and Any adult became NPC decides
    out['intimacy_check'] = OLD_INTIMACY.get(out['intimacy_check'], out['intimacy_check'])
    if out['intimacy_check'] not in INTIMACY_MODES:
        out['intimacy_check'] = DEFAULTS['intimacy_check']
    out['action_gates'] = {k: v for k, v in out['action_gates'].items() if isinstance(k, str) and isinstance(v, str) and k and v}
    return out


def save(path: str, values: dict) -> None:
    from . import lw_state
    clean = {key: values.get(key, default) for key, default in DEFAULTS.items()}
    tmp = lw_state.temp_path(path)  # this thread's own temp file, replaced with a retry while a reply reads the file
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(clean, f, indent=2)
    lw_state.replace_file(tmp, path)


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
