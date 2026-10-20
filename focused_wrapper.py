"""Child-local focused CLI extraction registration and private receipts."""
from copy import deepcopy
import logging
import os
import sys

from focused_capture import FD_ENV, NONCE_ENV, Recorder


def main():
    # Consume before CLI startup; never propagate the channel to descendants.
    fd_text = os.environ.pop(FD_ENV, '')
    nonce = os.environ.pop(NONCE_ENV, '')
    recorder = None
    try:
        if len(nonce) == 64 and all(c in '0123456789abcdef' for c in nonce):
            fd = int(fd_text)
            os.set_inheritable(fd, False)
            recorder = Recorder(fd, nonce)
    except (ValueError, OSError):
        pass
    from hermes_cli.main import main as cli_main
    from tools import web_tools  # Register the actual CLI tool before replacing its stored handler.
    from tools.registry import registry
    from research_extraction import (extract_tool, MIN_EXTRACT_CHARS,
                                     MAX_EXTRACT_CHARS, DEFAULT_EXTRACT_CHARS,
                                     MAX_EXTRACT_URLS)

    entry = registry.get_entry('web_extract')
    if entry is None or not entry.is_async:
        raise RuntimeError('focused extraction registration unavailable')
    original = entry.handler
    original_schema = entry.schema
    schema = deepcopy(original_schema)
    schema['description'] = (
        'Extract web pages as bounded Markdown text. At most '
        f'{MAX_EXTRACT_URLS} URLs per call; per-page character budget '
        f'{MIN_EXTRACT_CHARS}–{MAX_EXTRACT_CHARS}, default {DEFAULT_EXTRACT_CHARS}. '
        'Long pages return bounded head/tail text; full text is not stored. '
        'Publication and URL safety validation still apply.'
    )
    properties = schema['parameters']['properties']
    properties['urls']['maxItems'] = MAX_EXTRACT_URLS
    properties['char_limit'] = {
        'type': 'integer', 'minimum': MIN_EXTRACT_CHARS,
        'maximum': MAX_EXTRACT_CHARS, 'default': DEFAULT_EXTRACT_CHARS,
        'description': f'Per-page character budget; default {DEFAULT_EXTRACT_CHARS}. '
                       'Larger integer requests are capped; full text is not stored.',
    }
    dispatch = extract_tool
    if recorder is not None:
        recorder.guarded = True  # Only this controlled project path can attest uncached dispatch.
        dispatch = recorder.wrap(dispatch)

    async def handler(args, **kwargs):
        limit = args.get('char_limit')
        if limit is None:
            limit = DEFAULT_EXTRACT_CHARS
        elif type(limit) is int and limit > MAX_EXTRACT_CHARS:
            # Compatibility is limited to a smaller output request, never URL,
            # provenance, policy or provider-error repair. Do not log raw args.
            limit = MAX_EXTRACT_CHARS
            logging.getLogger('focused_wrapper').warning(
                'focused_extract_limit_capped effective_char_limit=%d', limit)
        return await dispatch(args.get('urls', []), 'markdown', char_limit=limit)

    entry.handler = handler
    entry.schema = schema
    sys.argv[0] = 'hermes'
    try:
        try:
            result = cli_main()
        except SystemExit as exit:
            if exit.code is None or exit.code == 0:
                if recorder is not None:
                    recorder.complete()
            raise
        if result is None or result == 0:
            if recorder is not None:
                recorder.complete()
        return result
    finally:
        entry.handler = original
        entry.schema = original_schema
        if recorder is not None:
            recorder.guarded = False


if __name__ == '__main__':
    sys.exit(main())
