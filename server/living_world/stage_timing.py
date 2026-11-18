"""Stage timers for measuring talk start (off by default; Settings page, "Speed testing"). Two switches, both in the
channel file perf.json that the game side reads too:
    timing   the game side writes timing_game.csv (talk key, each module's work when an NPC joins, the start request
             sent), this side writes timing_backend.csv (below), both next to perf.json
    prepare  the Hub's game side prepares an NPC's file when the player aims at them, so a talk start only refreshes
             what changes from moment to moment (MLW_Channel)
timing_backend.csv: wall_time,talk,stage,detail. The stages come from Mantella's own log lines (start request received,
prompt built, first model token, first sentence complete, line handed to the game, prompt and output tokens) and from
two timers around its voice step (voice audio received, lip file done). "talk" is the game side's talk number
(timing_talk.json), so the two files join on it; the token rows carry the same number and time.
Nothing here runs unless the switch is on, and nothing ever raises into a talk."""
import logging
import os
import re
import threading
import time

from . import lw_state

PERF = 'perf.json'
TALK_FILE = 'timing_talk.json'
BACKEND_FILE = 'timing_backend.csv'
GAME_FILE = 'timing_game.csv'

# Mantella's own log lines, in the order a talk reaches them
STAGES = (
    ('start_received', re.compile(r'^Matched (.+?) in CSV')),
    ('prompt_built', re.compile(r'^Prompt sent to LLM \((\d+) tokens\)')),
    ('first_token', re.compile(r'^LLM took ([\d.]+) seconds to respond')),
    ('first_sentence', re.compile(r'^Synthesizing voiceline: (.{0,40})')),
    ('handed_to_game', re.compile(r'^(.+?) should speak$')),
    ('tokens_in', re.compile(r'prompt tokens cached \(read\) (\d+), written to cache (\d+), uncached (\d+)')),
    ('tokens_out', re.compile(r'^Full raw response \((\d+) tokens\)')),
    ('summary_prompt', re.compile(r'^Summary prompt sent to LLM')),
)

_state = {'on': False, 'handler': None, 'patched': False}
_lock = threading.Lock()


def settings_file(on_timing: bool, on_prepare: bool) -> bool:
    """Writes perf.json, which the game side reads at each NPC join and talk end. Never raises."""
    try:
        lw_state.write_json(PERF, {'int': {'timing': 1 if on_timing else 0, 'prepare': 1 if on_prepare else 0}})
        return True
    except OSError:
        return False


def talk_id() -> str:
    value = lw_state._flatten(lw_state._read(TALK_FILE)).get('talk')
    return str(value) if isinstance(value, int) and not isinstance(value, bool) else ''


def mark(stage: str, detail: str = '') -> None:
    """One row in timing_backend.csv while the switch is on. Never raises."""
    if not _state['on']:
        return
    try:
        now = time.time()
        stamp = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now)) + f'.{int(now * 1000) % 1000:03d}'
        detail = str(detail).replace(',', ' ').replace('\n', ' ')[:80]
        with _lock:
            os.makedirs(lw_state.DATA_DIR, exist_ok=True)
            with open(os.path.join(lw_state.DATA_DIR, BACKEND_FILE), 'a', encoding='utf-8') as f:
                f.write(f"{stamp},{talk_id()},{stage},{detail}\n")
    except Exception:
        pass


def stage_of(message: str) -> tuple[str, str] | None:
    """(stage, detail) for one of Mantella's log lines that marks a stage, else None."""
    for stage, pattern in STAGES:
        found = pattern.search(message)
        if found:
            return stage, ' '.join(g for g in found.groups() if g)
    return None


class _Handler(logging.Handler):
    def emit(self, record):
        try:
            message = record.getMessage()
            if len(message) > 400:
                message = message[:400]
            found = stage_of(message)
            if found:
                mark(*found)
        except Exception:
            pass


_inside = threading.local()


def _classes(base) -> list:
    """base and every subclass of it loaded now."""
    out, todo = [], [base]
    while todo:
        cls = todo.pop()
        if cls not in out:
            out.append(cls)
            todo.extend(cls.__subclasses__())
    return out


def _timed(cls, name: str, stage: str) -> None:
    """Wraps cls's own name (not an inherited one) once, so the stage is marked after it returns. Only the outermost
    call marks: an override that calls the base method is one stage, not two."""
    original = cls.__dict__.get(name)
    if original is None or not callable(original) or getattr(original, '_lw_timed', False):
        return

    def wrapper(self, *args, **kwargs):
        outer = not getattr(_inside, stage, False)
        setattr(_inside, stage, True)
        try:
            result = original(self, *args, **kwargs)
        finally:
            if outer:
                setattr(_inside, stage, False)
        if outer:
            mark(stage)
        return result
    wrapper._lw_timed = True
    setattr(cls, name, wrapper)


def _patch_voice() -> None:
    """Timers around the voice step: audio received (tts_synthesize) and lip file done (_generate_voiceline_files).
    Each TTS service overrides tts_synthesize (Direct AI Connect's XTTS does), so the method is wrapped on every class
    that defines it, not only on the base; run again at each switch-on, for a service class loaded later."""
    try:
        from src.tts import ttsable
    except Exception:
        return
    for cls in _classes(ttsable.TTSable):
        _timed(cls, 'tts_synthesize', 'voice_audio')
        _timed(cls, '_generate_voiceline_files', 'lip_done')
    _state['patched'] = True


def apply(on: bool) -> None:
    """Turns the backend timers on or off (from the setting, at each talk start). Never raises."""
    try:
        on = bool(on)
        if on == _state['on']:
            return
        _state['on'] = on
        root = logging.getLogger('Mantella')  # Mantella's own logger (utils.get_logger)
        if on:
            _state['handler'] = _state['handler'] or _Handler(level=logging.DEBUG)
            if _state['handler'] not in root.handlers:
                root.addHandler(_state['handler'])
            _patch_voice()
        elif _state['handler'] in root.handlers:
            root.removeHandler(_state['handler'])
    except Exception:
        pass
