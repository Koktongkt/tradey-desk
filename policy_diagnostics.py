"""Bounded, sanitized private policy diagnostics; never identity authority."""
from __future__ import annotations
import datetime as dt
import hashlib
import re
from opportunity_identity import EventResolution

POLICY_REASONS=frozenset({'unchanged_opportunity','opportunity_identity_unknown','opportunity_identity_conflict',
    'position_already_held','same_symbol_pending_entry','unknown_history_unreconciled','policy_not_activated',
    'event_binding_missing','historical_binding_missing','dossier_binding_missing'})
RESOLVER_REASONS=frozenset({'not_run','invalid_symbol','invalid_pages','invalid_publication_observation',
    'identity_capture_invalid','identity_capture_duplicate','issuer_conflict','primary_support_conflict',
    'returned_locator_mismatch','alias_collision','conflicting_known_bindings','current_report_cover',
    'explicit_binding','sec_periodic_filing','sec_results_exhibit','unresolved_primary_evidence',
    'unsupported_or_missing_primary_support','multiple_report_subjects','known_binding_disagrees',
    'sec_original_acquisition','acquisition_evidence_missing','acquisition_original_required',
    'acquisition_continuity_unknown','acquisition_date_conflict','acquisition_evidence_invalid',
    'acquisition_incomplete_structure','acquisition_agreement_ambiguous',
    'acquisition_parties_ambiguous','acquisition_execution_missing'})
SOURCE_REASONS=frozenset({'source_fetch_timeout','source_fetch_failed','source_http_forbidden','source_rate_limited',
    'source_upstream_error','source_connection_failed','source_deadline_exhausted','source_url_mismatch',
    'bundle_rescue_unavailable','identity_source_deadline','identity_source_forbidden','identity_source_http_error',
    'identity_source_transport_failed','identity_transport_unavailable','identity_http_status',
    'identity_redirect_mismatch','identity_encoding_unsupported','identity_content_length_invalid',
    'identity_source_capacity','identity_body_incomplete','identity_capture_media','identity_capture_locator',
    'identity_source_invalid','identity_handoff_deadline'})
TRANSPORT_REASONS=frozenset({'identity_source_forbidden','identity_source_http_error','identity_source_transport_failed',
                            'identity_http_status','identity_source_deadline','identity_handoff_deadline'})


def policy_diagnostic(reason, *, timestamp, run_id=None, symbol=None, resolution=None,
                      source_reasons=(), capture_count=0, stage='pre_synthesis'):
    if type(capture_count) is not int or not 0<=capture_count<=32:raise ValueError('invalid_capture_count')
    if not isinstance(source_reasons,(tuple,list)) or len(source_reasons)>64:raise ValueError('invalid_source_reasons')
    if not isinstance(timestamp,str) or len(timestamp)>64 or dt.datetime.fromisoformat(timestamp).utcoffset() is None:
        raise ValueError('invalid_diagnostic_timestamp')
    if not isinstance(run_id,str) or not re.fullmatch(r'[0-9a-f]{32}',run_id):run_id=None
    if not isinstance(symbol,str) or not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,9}',symbol):symbol=None
    if not isinstance(resolution,EventResolution):resolution=None
    status=resolution.status if resolution is not None else 'not_run'
    if status not in {'unknown','verified','conflict','not_run'}:status='not_run'
    subreason=resolution.reason if resolution is not None else 'not_run'
    if subreason not in RESOLVER_REASONS:subreason='unclassified'
    sources=sorted({r for r in source_reasons if isinstance(r,str) and r in SOURCE_REASONS})
    return {'schema_version':2,'timestamp':timestamp,
        'reason':reason if reason in POLICY_REASONS else 'policy_reason_unknown',
        'run_id':run_id,'candidate_token':hashlib.sha256((run_id+':'+symbol).encode()).hexdigest()[:16] if run_id and symbol else None,
        'stage':stage if stage in {'discovery_admission','rescue_admission','pre_synthesis','post_synthesis'} else 'unknown',
        'resolver_status':status,'resolver_reason':subreason,
        'capture_count':capture_count,'capture_kind':'sec_identity_source' if capture_count else 'none',
        'capture_status':'complete' if capture_count else 'unavailable' if resolution is not None else 'not_requested',
        'source_failure_reasons':sources,'source_failure_reason_count':len(sources)}
