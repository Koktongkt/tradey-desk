"""Dependency-free JSON mechanics; callers retain their acceptance/error policy."""
import json


def first_object(text, *, missing):
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch == "{":
            try:
                obj, _ = decoder.raw_decode(text[i:])
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                pass
    raise ValueError(missing)


def loads_strict(payload, *, duplicate, nonfinite, depth):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(duplicate)
            result[key] = value
        return result
    def invalid_constant(value):
        raise ValueError(nonfinite)
    try:
        return json.loads(payload, object_pairs_hook=unique, parse_constant=invalid_constant)
    except RecursionError:
        raise ValueError(depth) from None
