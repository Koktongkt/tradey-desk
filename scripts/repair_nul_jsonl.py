#!/usr/bin/env python3
"""Offline, loss-conservative JSONL salvage. Does not synthesize missing records.

Call recover on archived bytes first. Writers must be quiescent before applying
an approved result; this module deliberately contains no production entry point.
"""
import json


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def _constant(value):
    raise ValueError('non-finite JSON number')


def recover(data: bytes):
    recovered = []
    changes = []
    for number, line in enumerate(data.splitlines(keepends=True), 1):
        clean = line.lstrip(b'\x00')
        removed = len(line) - len(clean)
        if removed and not clean.strip():
            raise ValueError(f'line {number}: missing record after NUL prefix')
        if clean.strip():
            record = json.loads(clean, object_pairs_hook=_object, parse_constant=_constant)
            if not isinstance(record, dict):
                raise ValueError(f'line {number}: JSON object required')
        if removed:
            changes.append({'line': number, 'nul_bytes_removed': removed})
        recovered.append(clean)
    return b''.join(recovered), changes
