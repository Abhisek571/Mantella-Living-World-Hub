"""Action arguments in the type each action declares, before Mantella sends them to the game.

The game reads an action's arguments with one typed getter per key (SKSE_HTTP.getInt, getString, getStringArray).
SKSE_HTTP does no type check: reading a key with the getter of another type returns garbage, and getString or
getStringArray on a number crashes the game. A model may still send "count": "2", "item": 5 or "source": "Lydia".
So every argument of an action call is turned into the type its action file declares, or left out when it cannot be
(the game then uses its default). Arguments that already have the declared type are kept as they are.
"""
import math
import re

INT_MIN, INT_MAX = -2 ** 31, 2 ** 31 - 1
_DROP = object()
_NUMBER = re.compile(r'^[+-]?\d+(\.\d+)?')


def _to_int(value):
    if isinstance(value, bool):
        return _DROP
    if isinstance(value, int):
        number = value
    elif isinstance(value, float):
        if not math.isfinite(value):
            return _DROP
        number = int(round(value))
    elif isinstance(value, str):
        match = _NUMBER.match(value.strip().replace(',', ''))
        if not match:
            return _DROP
        number = int(round(float(match.group(0))))
    else:
        return _DROP
    return max(INT_MIN, min(INT_MAX, number))


def _to_float(value):
    if isinstance(value, bool):
        return _DROP
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        match = _NUMBER.match(value.strip().replace(',', ''))
        if not match:
            return _DROP
        number = float(match.group(0))
    else:
        return _DROP
    return number if math.isfinite(number) else _DROP


def _to_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        word = value.strip().lower()
        if word in ('true', 'yes', '1'):
            return True
        if word in ('false', 'no', '0'):
            return False
    return _DROP


def _to_str(value):
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value)
    if isinstance(value, list):
        parts = [_to_str(v) for v in value if not isinstance(v, (list, dict)) and v is not None]
        return ', '.join(p for p in parts if p is not _DROP)
    return _DROP


_SCALAR = {'integer': _to_int, 'number': _to_float, 'boolean': _to_bool, 'string': _to_str}


def coerce(value, spec):
    """The value in the type spec declares; _DROP when it cannot be turned into it. An undeclared type is kept."""
    if value is None:
        return _DROP
    kind = (spec or {}).get('type') if isinstance(spec, dict) else None
    if kind in _SCALAR:
        return _SCALAR[kind](value)
    if kind == 'array':
        items = spec.get('items') if isinstance(spec.get('items'), dict) else {}
        item_spec = items if items.get('type') in _SCALAR else {'type': 'string'}
        values = value if isinstance(value, list) else [value]
        out = [coerce(v, item_spec) for v in values]
        return [v for v in out if v is not _DROP]
    return value


def normalise(arguments, defined_params, action_identifier=''):
    """arguments with every declared parameter in its declared type; values that cannot be turned are left out."""
    if not isinstance(arguments, dict):
        return arguments
    params = defined_params if isinstance(defined_params, dict) else {}
    out = {}
    for name, value in arguments.items():
        typed = coerce(value, params.get(name))
        if typed is not _DROP:
            out[name] = typed
    return out


def install():
    """Wraps Mantella's argument check so every action call leaves it typed. False when Mantella's action code is not
    there (tests, another exe); installing twice changes nothing."""
    try:
        from src.actions.function_manager import FunctionManager
    except Exception:
        return False
    current = FunctionManager.__dict__.get('_validate_arguments_against_schema')
    fn = current.__func__ if isinstance(current, staticmethod) else current
    if fn is None:
        return False
    if getattr(fn, '_lw_typed', False):
        return True

    def typed(llm_arguments, defined_params, action_identifier):
        return normalise(fn(llm_arguments, defined_params, action_identifier), defined_params, action_identifier)

    typed._lw_typed = True
    FunctionManager._validate_arguments_against_schema = staticmethod(typed)
    return True
