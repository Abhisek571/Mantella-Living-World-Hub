"""Test helper for the menu dialogue flow: the end of a Mantella talk (memory.summarize) with stand-ins for Mantella's
classes. A test's own summary object answers the menu part: its reply becomes that NPC's "menu" memory in the talk's
one summary request."""
import json

import os

from living_world import lw_state, memory, menu_dialogue


class Thread:
    def __init__(self, lines):
        self.lines = list(lines)

    def get_talk_only(self):
        return list(self.lines)

    def transform_to_dict_representation(self, messages):
        return '\n'.join(messages)

    def __len__(self):
        return len(self.lines)


class Params:
    def __init__(self, lines, chars):
        self.messages, self.characters = Thread(lines), chars


class People:
    def __init__(self, player):
        self.player = player

    def get_player_name(self):
        return self.player


class EndOfTalk:
    """Mantella's Summaries for one talk: one shared thread; the summary call goes to inner, whose reply (when the
    request asks for "menu") is that NPC's menu memory, and the talk's own memory is TALK_MEMORY."""
    TALK_MEMORY = 'We talked a little.'

    def __init__(self, inner, threads):
        self.inner, self.threads, self.calls = inner, threads, []
        self._Summaries__language_name = 'English'

    def get_threads_for_summarization(self, messages, npcs):
        return self.threads

    def group_shared_threads(self, threads):
        return [list(threads)]

    def summarize_conversation(self, text, prompt):
        self.calls.append((text, prompt))
        reply = self.inner.summarize_conversation(text, prompt)
        if not reply or '"menu"' not in prompt:
            return reply
        names = [n for n in self.threads if n in menu_dialogue._talk_pending]
        try:
            data = json.loads(reply)
        except ValueError:
            data = {'memory': reply}
        return json.dumps({'memory': self.TALK_MEMORY, 'feelings': data.get('feelings') or {},
                           'menu': {n: data for n in names}})


def end_talk(store, characters, inner, player='Player', talk=('Player: Hello.', 'Gerdur: Hm.'), **extra):
    """Runs the end of a talk with these NPCs (one shared thread of talk lines); returns the EndOfTalk object."""
    threads = {c.name: Params(talk, list(characters)) for c in characters}
    summaries = EndOfTalk(inner, threads)
    ctx = {'messages': None, 'npcs_to_summarize': list(characters), 'npcs_in_conversation': People(player),
           'world_id': 'w', 'is_reload': False, 'end_timestamp': 20.5, 'is_radiant': False, 'summaries': summaries}
    ctx.update(extra)
    real = lw_state.DATA_DIR
    if real == lw_state.default_data_dir():  # never the real channel folder: World's acknowledgement goes next to the store
        lw_state.DATA_DIR = os.path.join(store.root, 'channel')
    try:
        memory.summarize(ctx, store)
    finally:
        lw_state.DATA_DIR = real
    return summaries
