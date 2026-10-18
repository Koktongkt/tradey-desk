"""Focused-only public CLI entrypoint; tool results are never transformed."""
import os
import sys

from focused_capture import FD_ENV, NONCE_ENV, Recorder


def main():
    # Consume the channel before CLI/model startup; never expose it in argv,
    # prompts, returned tool text, stdout, logs or descendant environments.
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
    # Public CLI import precedes tool registration/readiness checks.
    from hermes_cli.main import main as cli_main
    from tools import web_tools
    from extraction_worker import final_location_cache_guard
    original = web_tools.web_extract_tool
    if recorder is not None:
        web_tools.web_extract_tool = recorder.wrap(original)
    sys.argv[0] = 'hermes'
    try:
        # One process-lifetime guard, never overlapping per-await contexts.
        with final_location_cache_guard():
            if recorder is not None:
                recorder.guarded = True
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
        web_tools.web_extract_tool = original
        if recorder is not None:
            recorder.guarded = False


if __name__ == '__main__':
    sys.exit(main())
