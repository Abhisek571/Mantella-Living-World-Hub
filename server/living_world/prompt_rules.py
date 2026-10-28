"""Rule lines every Living World mod adds to the prompt: data/prompt_rules/<file>.txt, merged in file-name order.
Each file is one short rule block (at most MAX_CHARS); {player_name} is filled in."""
import logging
import os

MAX_CHARS = 600
logger = logging.getLogger('Mantella')


def _files(rules_dir: str) -> list[str]:
    try:
        return sorted(f for f in os.listdir(rules_dir) if f.endswith('.txt'))
    except OSError:
        return []


def _read(rules_dir: str, name: str) -> str:
    try:
        with open(os.path.join(rules_dir, name), encoding='utf-8') as f:
            text = '\n'.join(line.strip() for line in f if line.strip())
    except OSError:
        return ''
    if len(text) > MAX_CHARS:
        logger.warning(f"Living World: prompt rule file {name} is over {MAX_CHARS} characters; the rest is left out")
        text = text[:MAX_CHARS]
    return text


def load_rules(rules_dir: str = 'data/prompt_rules', player_name: str = '', disabled: list[str] | None = None) -> str:
    blocks = [_read(rules_dir, name) for name in _files(rules_dir) if name not in (disabled or [])]
    return '\n'.join(b for b in blocks if b).replace('{player_name}', player_name or 'the player')


def rule_token_counts(rules_dir: str = 'data/prompt_rules') -> dict[str, int]:
    """Rough tokens per rule file (4 characters a token), for the tab."""
    return {name: max(1, len(_read(rules_dir, name)) // 4) for name in _files(rules_dir)}
