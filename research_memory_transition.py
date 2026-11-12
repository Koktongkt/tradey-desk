"""One approved forward-only retirement of formal event admission; no network."""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import entry_state
import sqlite_ledger as storage

POLICY_STREAM='private/opportunity_policy.jsonl'
MODE='exact_document_research_dedup'
_FIELDS={'manifest_version','policy_version','mode','root','source_revision','rule_version',
         'predecessor','streams','config_sha256','broker_baseline_sha256','history_mode'}
_DIGEST=re.compile(r'[0-9a-f]{64}')


class TransitionError(RuntimeError):pass


def _canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',', ':'),ensure_ascii=True,allow_nan=False).encode()


def manifest_digest(manifest: dict) -> str:
    return hashlib.sha256(_canonical(manifest)).hexdigest()


def _prefix(rows):
    return hashlib.sha256(''.join(storage._canonical(r) for r in rows).encode()).hexdigest()


def _snapshot(root):
    root=Path(root).absolute()
    if root.resolve()!=root or storage._storage_root(root/'order_ledger.jsonl')!=root:
        raise TransitionError('research_transition_root_invalid')
    return storage.read_stream_snapshot_readonly(root,storage.DEFAULT_STREAMS)


def _legacy(snapshot):
    from opportunity_cutover import BASELINE_STREAMS
    return storage.LedgerSnapshot(snapshot.root,{k:snapshot.rows[k] for k in BASELINE_STREAMS},
        tuple(w for w in snapshot.watermark if w[0] in BASELINE_STREAMS))


def _predecessor(snapshot):
    from opportunity_state import _state_parts, _baseline_exclusions
    policy=snapshot.rows[POLICY_STREAM]
    activations=[r for r in policy if r.get('record_type')=='activation']
    if len(activations)>1:raise TransitionError('research_predecessor_chain_invalid')
    version=activations[0].get('policy_version') if activations else 0
    if type(version) is not int or version not in (0,1,2):
        raise TransitionError('research_predecessor_unsupported')
    if activations:
        from opportunity_activation import _KNOWN_RECORD_TYPES
        row=activations[0]
        if (not isinstance(row.get('manifest_sha256'),str)
            or _DIGEST.fullmatch(row['manifest_sha256']) is None):
            raise TransitionError('research_predecessor_invalid')
    _state_parts(_legacy(snapshot));_baseline_exclusions(snapshot.root)
    return dict(policy_version=version,activation_sha256=manifest_digest(activations[0]) if activations else None)


def _shape(root,m):
    if (not isinstance(m,dict) or set(m)!=_FIELDS or type(m['manifest_version']) is not int
        or m['manifest_version']!=3 or type(m['policy_version']) is not int or m['policy_version']!=3
        or m['mode']!=MODE or m['root']!=str(root) or m['history_mode']!='preserve_exact_dossier_and_operational_history'
        or not isinstance(m['source_revision'],str) or re.fullmatch(r'[0-9a-f]{40}',m['source_revision']) is None
        or not isinstance(m['rule_version'],str) or not m['rule_version'].strip() or len(m['rule_version'])>256
        or not isinstance(m['predecessor'],dict)
        or set(m['predecessor'])!={'policy_version','activation_sha256'}
        or not isinstance(m['streams'],dict) or set(m['streams'])!=set(storage.DEFAULT_STREAMS)):
        raise TransitionError('research_transition_manifest_invalid')
    for k in ('config_sha256','broker_baseline_sha256'):
        if not isinstance(m[k],str) or _DIGEST.fullmatch(m[k]) is None:
            raise TransitionError('research_transition_manifest_invalid')
    for bound in m['streams'].values():
        if (not isinstance(bound,dict) or set(bound)!={'sequence','prefix_sha256'}
            or type(bound['sequence']) is not int or bound['sequence']<0
            or not isinstance(bound['prefix_sha256'],str) or _DIGEST.fullmatch(bound['prefix_sha256']) is None):
            raise TransitionError('research_transition_manifest_invalid')


def _active(snapshot):
    rows=snapshot.rows[POLICY_STREAM]
    indices=[i for i,r in enumerate(rows) if r.get('record_type')=='activation' and r.get('policy_version')==3]
    if not indices:return None
    if len(indices)!=1 or indices[0]!=len(rows)-1:raise TransitionError('research_transition_chain_invalid')
    index=indices[0];row=rows[index]
    if set(row)!={'record_type','schema_version','policy_version','timestamp','manifest_sha256','research_transition'}:
        raise TransitionError('research_transition_record_invalid')
    if type(row['schema_version']) is not int or row['schema_version']!=1 or type(row['policy_version']) is not int:
        raise TransitionError('research_transition_record_invalid')
    from research_memory import _timestamp
    _timestamp(row['timestamp'])
    m=row['research_transition'];_shape(snapshot.root,m)
    if row['manifest_sha256']!=manifest_digest(m) or m['streams'][POLICY_STREAM]['sequence']!=index:
        raise TransitionError('research_transition_digest_mismatch')
    prefix={}
    for name,bound in m['streams'].items():
        original=snapshot.rows[name][:bound['sequence']]
        if len(original)!=bound['sequence'] or _prefix(original)!=bound['prefix_sha256']:
            raise TransitionError('research_transition_prefix_mismatch')
        prefix[name]=original
    old=storage.LedgerSnapshot(snapshot.root,prefix,())
    if _predecessor(old)!=m['predecessor']:raise TransitionError('research_transition_predecessor_mismatch')
    return row


def prepare_manifest(root: Path, *, source_revision: str, rule_version: str) -> dict:
    snapshot=_snapshot(root)
    if _active(snapshot) is not None:raise TransitionError('research_transition_reset_forbidden')
    predecessor=_predecessor(snapshot)
    config=(snapshot.root/'autonomy_config.json').read_bytes()
    if json.loads(config).get('broker_mode')!='paper':raise TransitionError('paper_mode_required')
    if not storage.database_path(snapshot.root/'order_ledger.jsonl').exists() and any(snapshot.rows.values()):
        raise TransitionError('research_transition_storage_migration_required')
    m=dict(manifest_version=3,policy_version=3,mode=MODE,root=str(snapshot.root),
           source_revision=source_revision,rule_version=rule_version,predecessor=predecessor,
           streams={n:dict(sequence=len(r),prefix_sha256=_prefix(r)) for n,r in sorted(snapshot.rows.items())},
           config_sha256=hashlib.sha256(config).hexdigest(),
           broker_baseline_sha256=hashlib.sha256((snapshot.root/'private/broker_baseline.json').read_bytes()).hexdigest(),
           history_mode='preserve_exact_dossier_and_operational_history')
    _shape(snapshot.root,m)
    return m


def validate_manifest(root: Path, manifest: dict) -> None:
    snapshot=_snapshot(root);_shape(snapshot.root,manifest)
    current=_active(snapshot)
    if current is not None:
        if current['research_transition']!=manifest:raise TransitionError('research_transition_reset_forbidden')
        return
    expected=prepare_manifest(root,source_revision=manifest['source_revision'],rule_version=manifest['rule_version'])
    if expected!=manifest:raise TransitionError('research_transition_manifest_stale')


def apply(root: Path, manifest: dict, *, approved_manifest_sha256: str) -> dict:
    if (not isinstance(approved_manifest_sha256,str) or _DIGEST.fullmatch(approved_manifest_sha256) is None
            or manifest_digest(manifest)!=approved_manifest_sha256):raise TransitionError('approval_digest_mismatch')
    root=Path(root).absolute()
    with entry_state.lock(root):
        snapshot=_snapshot(root);_shape(root,manifest)
        current=_active(snapshot)
        if current is not None:
            if current['research_transition']!=manifest:raise TransitionError('research_transition_reset_forbidden')
            return dict(policy_version=3,transition_id='rt3:'+approved_manifest_sha256,appended_activation=False)
        validate_manifest(root,manifest)
        row=dict(record_type='activation',schema_version=1,policy_version=3,
                 timestamp=dt.datetime.now(dt.timezone.utc).isoformat(),
                 manifest_sha256=approved_manifest_sha256,research_transition=manifest)
        storage.append_jsonl(root/POLICY_STREAM,row,expected_watermark=snapshot.watermark)
    observed=_active(_snapshot(root))
    if observed!=row:raise TransitionError('research_transition_readback_failed')
    return dict(policy_version=3,transition_id='rt3:'+approved_manifest_sha256,appended_activation=True)


def status(root: Path) -> dict:
    snapshot=_snapshot(root);row=_active(snapshot)
    if row is None:return dict(policy_version=_predecessor(snapshot)['policy_version'],mode='event_policy',transition_id=None)
    return dict(policy_version=3,mode=MODE,transition_id='rt3:'+row['manifest_sha256'],manifest_sha256=row['manifest_sha256'])


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['prepare','validate','apply','status'])
    p.add_argument('--root',type=Path,required=True);p.add_argument('--source-revision');p.add_argument('--rule-version')
    p.add_argument('--manifest',type=Path);p.add_argument('--approved-manifest-sha256');p.add_argument('--apply',action='store_true')
    a=p.parse_args()
    try:
        if a.command=='prepare':out=prepare_manifest(a.root,source_revision=a.source_revision,rule_version=a.rule_version)
        elif a.command=='status':out=status(a.root)
        else:
            if a.manifest is None:raise TransitionError('manifest_required')
            m=json.loads(a.manifest.read_text())
            if a.command=='validate':validate_manifest(a.root,m);out=dict(valid=True,manifest_sha256=manifest_digest(m))
            else:
                if not a.apply:raise TransitionError('explicit_apply_required')
                out=apply(a.root,m,approved_manifest_sha256=a.approved_manifest_sha256)
        print(json.dumps(out,sort_keys=True));return 0
    except (TransitionError,OSError,ValueError,storage.LedgerError):
        print(json.dumps(dict(status='blocked',reason='research_transition_invalid')));return 2


if __name__=='__main__':raise SystemExit(main())
