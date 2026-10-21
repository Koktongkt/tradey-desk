"""Fixed, sanitized bridge failure vocabulary; legacy errors stay generic."""
import json

REASONS = frozenset({'entry_calendar_invalid', 'entry_calendar_unavailable',
                     'response_validation', 'authentication'})


class BrokerSnapshotError(RuntimeError):
    def __init__(self, reason):
        self.reason = reason if reason in REASONS else None
        super().__init__('broker_mcp_failure' + (':' + self.reason if self.reason else ''))


def error_envelope(error):
    # Never infer authentication from exception names or provider prose.
    import httpx
    from pydantic import ValidationError
    reason = None
    if isinstance(error, httpx.HTTPStatusError) and error.response.status_code == 401:
        reason = 'authentication'
    elif isinstance(error, ValidationError):
        reason = 'response_validation'
    elif isinstance(error, RuntimeError) and str(error) in {'entry_calendar_invalid', 'entry_calendar_unavailable'}:
        reason = str(error)
    result = {'error': 'RuntimeError'}
    if reason is not None:
        result['reason'] = reason
    return result


def transported_reason(stderr):
    # The child emits its final envelope after any library warnings. Additional
    # keys, unknown reasons, arbitrary log lines and old class-only errors fail closed.
    try:
        value = json.loads(stderr.strip().splitlines()[-1])
        if (isinstance(value, dict) and set(value) == {'error', 'reason'}
                and value['error'] == 'RuntimeError' and value['reason'] in REASONS):
            return value['reason']
    except (ValueError, TypeError, IndexError):
        pass
    return None


def snapshot_failure(error):
    reason = error.reason if isinstance(error, BrokerSnapshotError) else None
    if reason in {'entry_calendar_invalid', 'entry_calendar_unavailable'}:
        return 'BLOCKER ' + reason, 2
    if reason == 'response_validation':
        return 'SYSTEM_FAILURE broker_response_validation', 4
    if reason == 'authentication':
        return 'AUTH_FAILURE broker_mcp_unavailable', 3
    return 'SYSTEM_FAILURE broker_mcp_failure', 4
