"""Prompt probe (developer tool, not shipped): builds the whole prompt the Hub sends for a few sample talks from fixture
data in a temporary folder, the way Mantella - Direct AI Connect calls the hooks (memory_text, then system_parts, then
extra_user_text), and prints each part in the order sent with a rough token count (about 4 characters per token).

Talks: one NPC; two NPCs; a commanded NPC with someone who knows her well; the first NPC again after she was made to
forget a logged event. Nothing outside the temporary folder is written; the Knowledge module's places and profiles
are read when its repo sits next to this one.

usage: py -3.11 tools/prompt_probe.py [one|two|commanded|wiped|all]   (default: all)"""
import json
import os
import shutil
import sys
import tempfile

HUB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HUB, 'server'))
KNOWLEDGE = os.path.join(os.path.dirname(HUB), 'Mantella-Living-World-Knowledge', 'data')
if os.path.isdir(KNOWLEDGE):
    os.environ.setdefault('LW_KNOWLEDGE_DATA', KNOWLEDGE)

import living_world as LW  # noqa: E402
from living_world import (bio_evolve, characters, command, embed, lw_state, memory, news, npc_block, prompt_rules,  # noqa: E402
                          settings, worldlog)

RULES = os.path.join(HUB, 'SKSE', 'Plugins', 'MantellaSoftware', 'data', 'prompt_rules')
PLAYER = 'Inga'
TODAY = 40
# (name, base id, Mantella's ref id, npc file extras, bio)
NPCS = {
    'Lydia': ('0A2C94', '0A2C8E', {'race': 'Nord', 'sex': 'female', 'home': 'Breezehome', 'hold': 'Whiterun',
                                   'home_town': 'Whiterun', 'town': 'Whiterun', 'follower': 1, 'close': 1},
              'Lydia is a Nord housecarl sworn to the Thane of Whiterun. She is loyal, dry and plain-spoken.'),
    'Hulda': ('013BA3', '013BA4', {'race': 'Nord', 'sex': 'female', 'home': 'The Bannered Mare', 'hold': 'Whiterun',
                                   'home_town': 'Whiterun', 'town': 'Whiterun'},
              'Hulda runs the Bannered Mare in Whiterun. She is warm, shrewd and hears every rumour first.'),
    'Ysolda': ('013BAB', '013BAC', {'race': 'Nord', 'sex': 'female', 'home': "Ysolda's House", 'hold': 'Whiterun',
                                    'home_town': 'Whiterun', 'town': 'Whiterun'},
               'Ysolda is a young Whiterun merchant who dreams of running the Bannered Mare one day.'),
}
TALKS = {'one': ['Lydia'], 'two': ['Lydia', 'Hulda'], 'commanded': ['Ysolda', 'Hulda'], 'wiped': ['Lydia']}


class Char:
    def __init__(self, name):
        self.name, self.ref_id, self.bio = name, NPCS[name][1], NPCS[name][3]


class Game:
    def __init__(self, path):
        self.conversation_folder_path = path


class Summaries:
    def __init__(self, game):
        self._Summaries__game, self._Summaries__language_name = game, 'English'

    def summarize_conversation(self, text, prompt):
        return ''  # no model in the probe


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def set_speakers(channel, names):
    write(os.path.join(channel, 'conversation.json'),
          {'string': {'player': PLAYER}, 'int': {'day': TODAY, 'player_illusion': 40},
           'stringList': {'speakers': [NPCS[n][0] for n in names]}})


def fixture(tmp):
    channel = os.path.join(tmp, 'channel')
    lw_state.DATA_DIR = channel
    settings.PATH = os.path.join(tmp, 'settings.json')
    characters.PATH = os.path.join(tmp, 'characters.json')
    for name, (base, ref, extra, _) in NPCS.items():
        strings = {k: v for k, v in extra.items() if isinstance(v, str)}
        ints = {k: v for k, v in extra.items() if isinstance(v, int)}
        write(os.path.join(channel, 'npc', base + '.json'),
              {'string': dict(strings, name=name, ref_id='00' + ref), 'int': ints})
    write(os.path.join(channel, 'ties.json'), {'013BAB': {'name': 'Ysolda', 'home': "Ysolda's House",
                                                          'ties': [{'kind': 'household', 'base': '013BA3', 'name': 'Hulda'}]}})
    write(os.path.join(channel, 'marriages.json'), {'marriages': [
        {'base': '013BAB', 'name': 'Ysolda', 'status': 'married', 'day': 30.5, 'commanded': 1, 'player': PLAYER}]})
    write(os.path.join(channel, 'crimes.json'), {'player': PLAYER, 'crimes': [
        {'id': 'murder-0001A6B0-36500', 'crime': 'murder', 'day': 36.5, 'place': 'Plains District', 'town': 'Whiterun',
         'hold': 'Whiterun', 'victim': {'base': '013BB5', 'ref_id': '0001A6B0', 'name': 'Nazeem', 'thalmor': 0},
         'witnesses': [{'base': '013BA3', 'ref_id': '00013BA4', 'name': 'Hulda'},
                       {'base': '013BB1', 'ref_id': '0001A6B2', 'minor': 1}], 'by_player': True, 'player': PLAYER}],
        'deaths': []})
    store = memory.MemoryStore(os.path.join(tmp, 'conversations'), 'Inga1')
    mems = {
        'Lydia': [(31, 9, 'Inga and I cleared Bleak Falls Barrow; she found the dragonstone.'),
                  (35, 20, 'Inga bought me a new shield at Warmaiden\'s and would not take no for an answer.'),
                  (39, 14, 'We came back to Breezehome after a week on the road; Inga slept for a day.')],
        'Hulda': [(33, 21, 'Inga paid for a round for the whole inn and sang badly.')],
        'Ysolda': [(30, 12, 'Inga asked me to marry her and I said yes at once.'),
                   (38, 10, 'Inga brought me mammoth tusks to sell.')],
    }
    for name, rows in mems.items():
        store.save(name, NPCS[name][1], dict(memory.empty(), recent=[
            {'day': d, 'hour': h, 'text': t, 'witnesses': [name], 'importance': 0.5} for d, h, t in rows]))
    bio_evolve.edit(store, 'Lydia', NPCS['Lydia'][1], text='Lydia follows Inga as her housecarl and has come to trust '
                    'her judgement on the road, though she still worries Inga takes too many risks.')
    bio_evolve.edit(store, 'Ysolda', NPCS['Ysolda'][1], text='Ysolda is newly married to Inga and happier than she '
                    'has ever been; she wants to save for a stall of her own.')
    command.save(store, {'commands': [{'id': 'cmd1', 'key': 'k1', 'text': 'You love Inga and you want to stay with her.',
                                       'given': 29.0, 'npcs': [{'name': 'Ysolda', 'ref_id': NPCS['Ysolda'][1]}],
                                       'forget': '', 'aware': False, 'status': 'active', 'hidden': [], 'until': -1.0,
                                       'hours': 0.0, 'announced': True, 'read_by': 'words'}],
                         'seen': ['k1'], 'ended': []})
    # Ysolda was met before (her home town is known for the news of her wedding)
    worldlog.note_people(store, [dict(worldlog.person('Ysolda', '013BAB', NPCS['Ysolda'][1]), town='Whiterun', hold='Whiterun')])
    return store, channel


def mantella_prompt(names, memory_text):
    bios = '\n\n'.join(NPCS[n][3] for n in names)
    return ('# Rules\nYou are a character in Skyrim. Stay in character.\n\n'
            f'# Overview\nThis is a conversation between {PLAYER} and {", ".join(names)}.\n\n'
            f'# Background\n{bios}\n\n'
            f'# History\n{memory_text}\n\n'
            '# Current Scene\nIt is 2 in the afternoon in Whiterun, Plains District. The weather is clear.\n'
            f'Respond as {" and ".join(names)}.')


def tokens(text):
    return (len(text) + 3) // 4


def run_talk(store, channel, case):
    names = TALKS[case]
    set_speakers(channel, names)
    npc_block.talk_over()  # a new talk
    news._talks.clear()
    chars = [Char(n) for n in names]
    summaries = Summaries(Game(store_folder))
    memory_text = LW._memory_text('Below is a summary of past events:', {'characters': chars, 'world_id': 'Inga1',
                                                                         'summaries': summaries})
    mantella = mantella_prompt(names, memory_text)
    parts = LW._system_parts({'mantella': mantella}, {})
    messages = [{'role': 'system', 'content': mantella}, {'role': 'user', 'content': f'{PLAYER}: Good day.'}]
    newest = LW._extra_text({'messages': messages})
    again = LW._system_parts({'mantella': mantella}, {})  # the second request of the same talk
    order = [k for k in parts.get('__order__', []) if isinstance(parts.get(k), str)]
    order += [k for k in parts if not k.startswith('__') and k not in order and isinstance(parts[k], str)]
    total = 0
    print(f"\n######## talk: {case} ({', '.join(names)}) ########")
    for key in order:
        text = parts[key]
        total += tokens(text)
        print(f"\n=== {key} (~{tokens(text)} tokens) ===\n{text}")
    print(f"\n=== newest message lines (~{tokens(newest)} tokens) ===\n{newest or '(none)'}")
    print(f"\n--- system prompt ~{total} tokens; newest-message lines ~{tokens(newest)}; cache points after "
          f"{parts.get('__breakpoints_after__')}")
    same = all(again.get(k) == parts.get(k) for k in order if k != 'command')
    print(f"--- second request of the same talk gives the same cached parts: {same}")
    return parts, newest


store_folder = None


def main():
    global store_folder
    want = sys.argv[1] if len(sys.argv) > 1 else 'all'
    embed.use(None)
    real_rules = prompt_rules.load_rules
    prompt_rules.load_rules = lambda rules_dir=RULES, player_name='', disabled=None: real_rules(RULES, player_name, disabled)
    LW._installed = lambda: {'Integration Hub', 'World', 'Relationships'}
    tmp = tempfile.mkdtemp(prefix='lw-probe-')
    try:
        store, channel = fixture(tmp)
        store_folder = os.path.join(tmp, 'conversations')
        cases = list(TALKS) if want == 'all' else [want]
        for case in cases:
            if case == 'wiped':
                murder = next((e for e in worldlog.events(store) if e['kind'] == 'killing'), None)
                if murder:
                    report = news.forget_event(store, {'name': 'Lydia', 'ref_id': NPCS['Lydia'][1], 'base_id': '0A2C94'},
                                               murder['id'], by='probe')
                    print(f"\n(Lydia was made to forget: {murder['public_text']} -> wipes {report['wipes']}, "
                          f"{report['hidden']} memory hidden)")
            run_talk(store, channel, case)
        print('\n######## world log (the Hub\'s record) ########')
        for e in worldlog.events(store):
            print(f"- {e['id']}: {e['kind']}, {e['size']}, day {e['day']:.1f}; public: {e['public_text'] or '(private)'}; "
                  f"knows: {', '.join(k.get('name') or '(child)' for k in e['known'].values())}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    main()
