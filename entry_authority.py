"""Code-owned exact candidate/dual-review authority without event allowances."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import sqlite_ledger as storage
import entry_state
from research_mode import context as current_context, ModeContext

_SECRET=secrets.token_bytes(32)
_STREAMS=('private/opportunity_policy.jsonl','candidates.jsonl','private/reviews.jsonl',
          'order_ledger.jsonl','private/order_intents.jsonl')
_FORBIDDEN={'dossier_hash','research_transition_id','event_id','allowance_id','opportunity_identity',
            'opportunity_baseline_id','reopening_claim','current_attempt'}


class AuthorityError(RuntimeError):pass


class _BoundCandidate(dict):pass


def _canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',', ':'),allow_nan=False).encode()


def _hash(value):return hashlib.sha256(_canonical(value)).hexdigest()


def _signature(value):return hmac.new(_SECRET,_canonical(value),hashlib.sha256).hexdigest()


def _mode(root):
    try:
        mode=current_context(root)
        if mode.policy_version!=3:raise AuthorityError('research_mode_not_active')
        return mode
    except AuthorityError:raise
    except Exception as error:raise AuthorityError('research_mode_unavailable') from error


def bind_candidate(root:Path,candidate:dict,*,context:ModeContext)->dict:
    root=Path(root).resolve()
    mode=_mode(root)
    if context!=mode or not isinstance(candidate,dict) or _FORBIDDEN.intersection(candidate):
        raise AuthorityError('candidate_binding_invalid')
    bound=_BoundCandidate(candidate)
    bound['research_transition_id']=mode.transition_id
    bound._signature=_signature(dict(root=str(root),candidate=dict(bound)))
    return bound


def validate_intake(root:Path,candidate:dict)->None:
    root=Path(root).resolve();mode=_mode(root)
    if not isinstance(candidate,_BoundCandidate) or candidate.get('research_transition_id')!=mode.transition_id:
        raise AuthorityError('candidate_intake_untrusted')
    body={k:v for k,v in candidate.items() if k!='dossier_hash'}
    expected=_signature(dict(root=str(root),candidate=body))
    if not hmac.compare_digest(getattr(candidate,'_signature',''),expected):
        raise AuthorityError('candidate_binding_changed')
    if candidate.get('dossier_hash')!=_hash(body):raise AuthorityError('candidate_hash_invalid')


def _candidate(snapshot,candidate,mode):
    if not isinstance(candidate,dict) or candidate.get('research_transition_id')!=mode.transition_id:
        raise AuthorityError('candidate_transition_mismatch')
    body={k:v for k,v in candidate.items() if k!='dossier_hash'}
    if candidate.get('dossier_hash')!=_hash(body):raise AuthorityError('candidate_hash_invalid')
    matches=[r for r in snapshot.rows['candidates.jsonl'] if r.get('dossier_hash')==candidate['dossier_hash']]
    if not matches or any(r!=dict(candidate) for r in matches):raise AuthorityError('candidate_not_durable')


def validate_candidate(root:Path,candidate:dict)->None:
    try:
        mode=_mode(root);snapshot=storage.read_stream_snapshot_readonly(root,_STREAMS)
        _candidate(snapshot,candidate,mode)
    except AuthorityError:raise
    except Exception as error:raise AuthorityError('candidate_state_unavailable') from error


def _proposal(proposal):
    if not isinstance(proposal,dict):raise AuthorityError('proposal_invalid')
    body={k:v for k,v in proposal.items() if k not in {'proposal_hash','confidence'}}
    if proposal.get('proposal_hash')!=_hash(body):raise AuthorityError('proposal_hash_invalid')
    return {**body,'proposal_hash':proposal['proposal_hash']}


def _approval(root,snapshot,candidate,proposal,evidence_id,mode):
    import autotrader
    from candidate_retry import pre_submission_retryable
    from opportunity_state import _legacy_completed_outputs, _spends, _completed_dissent
    if not isinstance(evidence_id,str) or not evidence_id:raise AuthorityError('evidence_id_invalid')
    matching=[r for r in snapshot.rows['private/reviews.jsonl'] if r.get('dossier_hash')==candidate['dossier_hash']]
    approvals=[r for r in matching if r.get('evidence_id')==evidence_id]
    if len(approvals)!=1 or approvals[0]!=matching[-1]:raise AuthorityError('current_attempt_unauthorized')
    row=approvals[0]
    if (row.get('proposal_hash')!=proposal['proposal_hash']
        or row.get('research_transition_id')!=mode.transition_id):raise AuthorityError('current_attempt_unauthorized')
    cfg=json.loads((Path(root)/'autonomy_config.json').read_text())
    if cfg.get('broker_mode')!='paper':raise AuthorityError('paper_mode_required')
    if not autotrader.aggregate_proposal_reviews(proposal,row.get('reviews',[]),cfg)['approved']:
        raise AuthorityError('dual_approval_unverified')
    previous=matching[:-1];orders=list(snapshot.rows['order_ledger.jsonl'])
    if any(_completed_dissent(r) for r in previous):raise AuthorityError('dossier_previously_completed')
    if any(_spends(r) for r in previous) and not pre_submission_retryable(
            candidate['dossier_hash'],previous,Path(root)/'order_ledger.jsonl',ledger_rows=orders):
        raise AuthorityError('dossier_previously_completed')
    ids={r.get('evidence_id') for r in matching if isinstance(r.get('evidence_id'),str)}
    intents=snapshot.rows['private/order_intents.jsonl']
    if any(r.get('evidence_id') in ids or r.get('dossier_hash')==candidate['dossier_hash'] for r in intents):
        # Intent persistence begins the uncertain-submission obligation even
        # when its acknowledgement/next ledger row was lost. This proof is
        # strictly pre-intent; reconciliation, not a new proof, owns recovery.
        raise AuthorityError('dossier_submission_obligation')
    linked=[r for r in orders if r.get('evidence_id') in ids or r.get('dossier_hash')==candidate['dossier_hash']]
    if any(r.get('status') not in {'proposed','rejected'} for r in linked):
        raise AuthorityError('dossier_submission_obligation')
    # Cache/diagnostic writes and this attempt's proposed row do not mutate
    # review authority. Fresh order obligations are checked above independently.
    return _hash({s:list(snapshot.rows[s]) for s in _STREAMS if s!='order_ledger.jsonl'})


@dataclass(frozen=True)
class AttemptProof:
    root:str
    dossier_hash:str
    proposal_json:str
    evidence_id:str
    transition_id:str
    state_digest:str
    signature:str


def authorize_attempt(root:Path,*,candidate:dict,proposal:dict,evidence_id:str,review_ref:dict)->AttemptProof:
    root=Path(root).resolve()
    try:
        with entry_state.lock(root):
            mode=_mode(root);snapshot=storage.read_stream_snapshot_readonly(root,_STREAMS)
            _candidate(snapshot,candidate,mode);proposal=_proposal(proposal)
            if (not isinstance(review_ref,dict) or review_ref.get('evidence_id')!=evidence_id
                or review_ref.get('dossier_hash')!=candidate['dossier_hash']
                or review_ref.get('proposal_hash')!=proposal['proposal_hash']):
                raise AuthorityError('review_reference_invalid')
            digest=_approval(root,snapshot,candidate,proposal,evidence_id,mode)
            fields=dict(root=str(root),dossier_hash=candidate['dossier_hash'],
                        proposal_json=_canonical(proposal).decode(),evidence_id=evidence_id,
                        transition_id=mode.transition_id,state_digest=digest)
            return AttemptProof(**fields,signature=_signature(fields))
    except AuthorityError:raise
    except Exception as error:raise AuthorityError('current_attempt_unauthorized') from error


def validate_attempt(root:Path,*,candidate:dict,proposal:dict,evidence_id:str,proof:AttemptProof)->None:
    if not isinstance(proof,AttemptProof):raise AuthorityError('attempt_proof_invalid')
    fields={k:v for k,v in vars(proof).items() if k!='signature'}
    if (proof.root!=str(Path(root).resolve()) or not hmac.compare_digest(proof.signature,_signature(fields))
        or proof.dossier_hash!=candidate.get('dossier_hash') or proof.evidence_id!=evidence_id
        or proof.proposal_json!=_canonical(_proposal(proposal)).decode()):
        raise AuthorityError('attempt_proof_mismatch')
    fresh=authorize_attempt(root,candidate=candidate,proposal=proposal,evidence_id=evidence_id,
        review_ref=dict(dossier_hash=proof.dossier_hash,evidence_id=evidence_id,proposal_hash=proposal['proposal_hash']))
    if fresh!=proof:raise AuthorityError('attempt_state_changed')
