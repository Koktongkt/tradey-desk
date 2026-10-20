"""Child-local installed search-handler admission and mandatory private receipts."""
import os
import sys

from focused_capture import FD_ENV, NONCE_ENV
from focused_search import SearchProtocolError, SearchRecorder


def main():
    # Consume before importing CLI/model startup. Descendants inherit neither
    # the environment capability nor the descriptor, even with close_fds=False.
    fd_text = os.environ.pop(FD_ENV, '')
    nonce = os.environ.pop(NONCE_ENV, '')
    try:
        fd = int(fd_text)
        os.set_inheritable(fd, False)
        if len(nonce) != 64 or any(c not in '0123456789abcdef' for c in nonce):
            raise ValueError
    except (ValueError, OSError) as error:
        raise SearchProtocolError('search channel unavailable') from error
    recorder = SearchRecorder(fd, nonce)
    from hermes_cli.main import main as cli_main
    from tools import web_tools  # noqa: F401 - register actual installed handler
    from tools.registry import registry
    from toolsets import TOOLSETS, resolve_toolset

    if (TOOLSETS.get('search', {}).get('tools') != ['web_search']
            or TOOLSETS['search'].get('includes') or resolve_toolset('search') != ['web_search']):
        raise SearchProtocolError('search-only toolset unavailable')
    entry = registry.get_entry('web_search')
    if entry is None:
        raise SearchProtocolError('search registration unavailable')
    original = entry.handler
    entry.handler = recorder.wrap(original)
    sys.argv[0] = 'hermes'
    try:
        try:
            result = cli_main()
        except SystemExit as exit:
            if exit.code is None or exit.code == 0:
                recorder.complete()
            raise
        if result is None or result == 0:
            recorder.complete()
        return result
    finally:
        entry.handler = original


if __name__ == '__main__':
    sys.exit(main())
