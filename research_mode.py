"""Read-only coherent deployment mode; event admission is retired only in v3."""
from dataclasses import dataclass
from pathlib import Path
from research_memory_transition import _snapshot, _active, _predecessor, MODE


@dataclass(frozen=True)
class ModeContext:
    policy_version:int
    mode:str
    transition_id:str|None
    manifest_sha256:str|None


def context(root:Path)->ModeContext:
    snapshot=_snapshot(root)
    row=_active(snapshot)
    if row is None:
        old=_predecessor(snapshot)
        return ModeContext(old['policy_version'],'event_policy',None,None)
    digest=row['manifest_sha256']
    return ModeContext(3,MODE,'rt3:'+digest,digest)
