"""One canonical cross-process lock for entry decisions and local reconciliation.

Lock order: entry state -> managed reconciliation -> storage -> projection.
Nonblocking contention fails closed; no lock inode rotation or force-unlock.
"""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import stat
import threading

_local=threading.local()


@contextmanager
def lock(root, *, attempts=1):
    """Bounded nonblocking acquisition; contention fails closed.

    Read-only reconciliation callers may pass attempts>1 to serialize behind a
    peer without writing; execution callers keep attempts=1 (no write retries).
    """
    import time
    for attempt in range(attempts - 1, -1, -1):
        try:
            with _lock_once(root):
                yield
            return
        except RuntimeError as error:
            if str(error) != 'entry_state_busy' or attempt == 0:
                raise
            time.sleep(0.05)


@contextmanager
def _lock_once(root):
    root=Path(root).resolve(strict=True)
    key=(threading.get_ident(),str(root))
    held=getattr(_local,'held',{})
    if key in held:
        yield
        return
    path=root/'.entry_state.lock'
    fd=os.open(path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise RuntimeError('entry_state_invalid')
        try: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as error: raise RuntimeError('entry_state_busy') from error
        if os.stat(path,follow_symlinks=False).st_ino != info.st_ino:
            raise RuntimeError('entry_state_invalid')
        held[key]=fd;_local.held=held
        try: yield
        finally: held.pop(key,None)
    finally:
        os.close(fd)
