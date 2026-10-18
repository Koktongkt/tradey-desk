"""Child-local focused CLI extraction registration and private receipts."""
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
    from research_extraction import extract_tool

    entry = registry.get_entry('web_extract')
    if entry is None or not entry.is_async:
        raise RuntimeError('focused extraction registration unavailable')
    original = entry.handler
    dispatch = extract_tool
    if recorder is not None:
        recorder.guarded = True  # Only this controlled project path can attest uncached dispatch.
        dispatch = recorder.wrap(dispatch)

    async def handler(args, **kwargs):
        return await dispatch(args.get('urls', []), 'markdown', char_limit=args.get('char_limit'))

    entry.handler = handler
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
        if recorder is not None:
            recorder.guarded = False


if __name__ == '__main__':
    sys.exit(main())
