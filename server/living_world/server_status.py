"""What the bug report needs from the server side: installed module versions and the last Living World warnings. Written
as PapyrusUtil JSON next to the other channel files, so the game's Troubleshooting report can include it. No memories,
no conversation text."""
import json
import logging
import os

from . import lw_state, update_check

FILE = 'server_report.json'
MAX_LINES = 10
MAX_CHARS = 200
# Mantella logs a hook of ours that raised as "Extension '<our folder>' failed in <hook>: ..."
OURS = ('Living World', f"Extension '{(__package__ or 'living_world').rsplit('.', 1)[-1]}'")


def write(lines: list[str], versions_dir: str = update_check.VERSIONS_DIR) -> None:
    versions = [f"{module} {info['version']}" for module, info in sorted(update_check.installed(versions_dir).items())]
    lw_state.write_json(FILE, {'stringList': {'versions': versions, 'errors': lines[-MAX_LINES:]}})


class RecentWarnings(logging.Handler):
    def __init__(self, versions_dir: str = update_check.VERSIONS_DIR):
        super().__init__(logging.WARNING)
        self.lines: list[str] = []
        self.versions_dir = versions_dir

    def emit(self, record):
        try:
            message = record.getMessage()
            if not any(mark in message for mark in OURS):
                return
            self.lines = (self.lines + [message[:MAX_CHARS]])[-MAX_LINES:]
            write(self.lines, self.versions_dir)
        except Exception:
            pass  # the report must never break the conversation


def start() -> None:
    try:
        write([])
        log = logging.getLogger('Mantella')
        for old in [h for h in log.handlers if type(h).__name__ == RecentWarnings.__name__]:
            log.removeHandler(old)  # registered again: one handler, not one per registration
        log.addHandler(RecentWarnings())
    except Exception as e:
        logging.getLogger('Mantella').debug(f"server report not written: {e}")
