"""Pure private identity projection; symbols are checks, never join keys.

Position totals and fill_observations are cumulative, NOT executions to replay.
Only exact broker activity IDs are execution events; their time coverage is the
broker adapter's requested interval, not proof of lifetime accounting coverage.
"""
from decimal import Decimal

from .types import BrokerSnapshot, LineageResult, OperationalSnapshot, aware_timestamp, money

IDENTITY_FIELDS = ('candidate_id', 'dossier_hash', 'proposal_hash', 'evidence_id', 'client_order_id')
ZERO = Decimal(0)


def build_lineage(op: OperationalSnapshot, broker: BrokerSnapshot) -> LineageResult:
    """Join explicit immutable identities without operational I/O or mutation."""
    graph, reasons = {}, list(op.reasons)

    def tokens(row):
        return [(key, row[key]) for key in IDENTITY_FIELDS
                if isinstance(row.get(key), str) and row[key]]

    def connect(nodes):
        for node in nodes:
            graph.setdefault(node, set()).update(nodes)

    streams = op.streams
    candidates = streams.get('candidates.jsonl', [])
    reviews = streams.get('private/reviews.jsonl', [])
    ledger = streams.get('order_ledger.jsonl', [])
    intents = streams.get('private/order_intents.jsonl', [])
    # Candidate/model rows establish research identity only. Execution tokens
    # belong to the durable review/ledger/intent envelopes, never the model.
    for row in candidates:
        connect([node for node in tokens(row) if node[0] in ('candidate_id', 'dossier_hash')])
    for row in reviews:
        connect([node for node in tokens(row) if node[0] != 'client_order_id'])
    for row in ledger:
        connect(tokens(row))

    def proposal_evidence(proposal):
        # A candidate may have multiple proposals. Evidence for one is not
        # automatically evidence for every proposal in its graph component.
        return sorted({row['evidence_id'] for row in reviews + ledger
                       if row.get('proposal_hash') == proposal
                       and isinstance(row.get('evidence_id'), str) and row['evidence_id']})

    def component(node):
        found, pending = set(), [node]
        while pending:
            current = pending.pop()
            if current not in found:
                found.add(current)
                pending.extend(graph.get(current, set()) - found)
        return found

    # Freeze proposal provenance before intent edges can merge components.
    # An intent corroborates a recorded proposal; it cannot create its owner.
    proposal_links = {value: component((field, value)) for field, value in graph if field == 'proposal_hash'}
    for row in intents:
        proposal = (row.get('plan') or {}).get('proposal_hash') or row.get('proposal_hash')
        if proposal in proposal_links:
            connect([('proposal_hash', proposal), ('client_order_id', row.get('client_order_id'))])

    def candidate_key(row):
        for key in ('candidate_id', 'dossier_hash'):
            if isinstance(row.get(key), str) and row[key]:
                return key, row[key]
        return None

    candidate_rows = {candidate_key(row): row for row in candidates if candidate_key(row)}

    def resolve(ref):
        links = component(('client_order_id', ref))
        matches = {candidate_key(row) for row in candidates
                   if {node for node in tokens(row) if node[0] in ('candidate_id', 'dossier_hash')} & links}
        ids = {v for k, v in links if k == 'candidate_id'}
        dossiers = {v for k, v in links if k == 'dossier_hash'}
        if len(matches) != 1 or len(ids) > 1 or len(dossiers) > 1:
            return None
        return next(iter(matches))

    if not op.complete:
        reasons.append('operational_snapshot_incomplete')
    source_complete = op.complete and broker.complete and all(
        broker.coverage.get(key) == 'complete' for key in ('orders', 'references', 'activities'))
    if not broker.complete or not all(broker.coverage.get(key) == 'complete' for key in ('orders', 'references', 'activities')):
        reasons.append('broker_snapshot_incomplete')
    refs = {value for key, value in graph if key == 'client_order_id'}
    ambiguous_refs = set()
    for ref in refs:
        links = component(('client_order_id', ref))
        if any(len({v for k, v in links if k == field}) > 1 for field in ('candidate_id', 'dossier_hash')):
            ambiguous_refs.add(ref)
    for intent in intents:
        ref = intent.get('client_order_id')
        links = component(('client_order_id', ref))
        plan = intent.get('plan') or {}
        proposal_conflict = ('proposal_hash' in intent and 'proposal_hash' in plan
                             and intent['proposal_hash'] != plan['proposal_hash'])
        parent_conflict = (plan.get('action') == 'BUY' and 'parent_client_order_id' in intent
                           and intent['parent_client_order_id'] != ref)
        if proposal_conflict or parent_conflict or any(
                node not in links for node in tokens(intent) if node[0] in ('candidate_id', 'dossier_hash')):
            ambiguous_refs.add(ref)
    if ambiguous_refs:
        reasons.append('lineage_contradictory')

    # BrokerSnapshot is an identity-validated forest. Parent/leg and registered
    # replacement relationships bind only these exact orders, not symbol lots.
    by_ref, by_id, descendants = {}, {}, {}
    def index_order(order):
        by_ref[order['client_order_id']] = order
        by_id[order['id']] = order
        children = []
        for leg in order.get('legs', []):
            index_order(leg)
            children.append(leg)
            children.extend(descendants[leg['client_order_id']])
        descendants[order['client_order_id']] = children
    for order in broker.orders:
        index_order(order)

    registry = streams.get('private/protection_orders.jsonl', [])
    exits_by_parent = {}
    for intent in intents:
        ref = intent.get('client_order_id')
        exits = list(descendants.get(ref, []))
        for registration in registry:
            if registration.get('parent_client_order_id') == ref:
                replacement = by_ref.get(registration.get('protection_client_order_id'))
                if replacement is None:
                    reasons.append('referenced_protection_missing')
                else:
                    exits.append(replacement)
                    exits.extend(descendants[replacement['client_order_id']])
        exits_by_parent[ref] = {order['id']: order for order in exits}
    exit_parents = {}
    for ref, exits in exits_by_parent.items():
        for identity in exits:
            exit_parents.setdefault(identity, set()).add(ref)
    for parents in exit_parents.values():
        if len(parents) > 1:
            ambiguous_refs.update(parents)
            reasons.append('lineage_contradictory')

    positions, filled, seen_refs, order_owners = [], set(), set(), {}
    for intent in intents:
        ref = intent.get('client_order_id')
        if ref in seen_refs:
            continue
        seen_refs.add(ref)
        key = resolve(ref)
        plan = intent.get('plan') or {}
        if any((other.get('plan') or {}) != plan for other in intents if other.get('client_order_id') == ref):
            ambiguous_refs.add(ref)
            reasons.append('intent_plan_conflict')
        proposal = plan.get('proposal_hash') or intent.get('proposal_hash')
        if key is None or ref in ambiguous_refs or key not in proposal_links.get(proposal, set()):
            reasons.append('intent_lineage_unknown')
            continue
        if plan.get('action') != 'BUY':
            continue
        order = by_ref.get(ref)
        if order is None:
            reasons.append('referenced_order_missing')
            continue
        candidate = candidate_rows[key]
        if order['side'] != 'buy' or order['symbol'] != plan.get('symbol') or candidate.get('symbol') != order['symbol']:
            reasons.append('order_lineage_mismatch')
            continue
        exits = list(exits_by_parent[ref].values())
        if any(leg['side'] != 'sell' or leg['symbol'] != order['symbol'] for leg in exits):
            reasons.append('order_lineage_mismatch')
            continue
        quantity = money(order['filled_qty'])
        if quantity <= 0:
            continue
        exit_quantity = sum((money(leg['filled_qty']) for leg in exits), ZERO)
        exit_notional = sum((money(leg['filled_qty']) * money(leg.get('filled_avg_price', 0)) for leg in exits), ZERO)
        remaining = quantity - exit_quantity
        ownership = 'verified' if source_complete else 'unknown'
        if remaining < 0:
            remaining, ownership = None, 'discrepancy'
            reasons.append('managed_exit_exceeds_entry')
        links = component(('client_order_id', ref))
        filled.add(key)
        owned_orders = [order] + exits
        for owned in owned_orders:
            order_owners[owned['id']] = ref
        observations = [dict(broker_order_id=o['id'], client_order_id=o['client_order_id'], side=o['side'],
                             cumulative_quantity=money(o['filled_qty']),
                             cumulative_notional=money(o['filled_qty']) * money(o.get('filled_avg_price', 0)),
                             captured_at=broker.captured_at, trusted=source_complete)
                        for o in owned_orders]
        positions.append(dict(position_id=ref, candidate_id=candidate.get('candidate_id'),
            dossier_hash=candidate.get('dossier_hash'), proposal_hash=plan.get('proposal_hash') or intent.get('proposal_hash'),
            evidence_ids=proposal_evidence(plan.get('proposal_hash') or intent.get('proposal_hash')), parent_client_order_id=ref,
            broker_order_id=order['id'], symbol=order['symbol'], entry_quantity=quantity,
            entry_notional=quantity * money(order['filled_avg_price']), exit_quantity=exit_quantity,
            exit_notional=exit_notional, remaining_quantity=remaining, ownership=ownership,
            planned_exit_at=plan.get('planned_exit_at'),
            stop=money(plan['stop']) if plan.get('stop') is not None else None,
            target=money(plan['target']) if plan.get('target') is not None else None,
            setup_type=plan.get('setup_type') or candidate.get('setup_type'), horizon=plan.get('horizon'),
            thesis_baseline={k: candidate[k] for k in ('thesis', 'catalyst', 'assumptions', 'breakers', 'kpis', 'risks') if k in candidate},
            protective_client_order_ids=sorted(o['client_order_id'] for o in exits), fill_observations=observations,
            fills=[], fill_event_coverage='requested_interval_only', delta_status='unknown',
            operational_captured_at=op.captured_at, broker_captured_at=broker.captured_at))

    for position in positions:
        symbol = position['symbol']
        observed = [row for row in broker.positions if row.get('symbol') == symbol]
        observed_quantity = money(observed[0]['qty']) if len(observed) == 1 else ZERO if not observed else None
        position['broker_symbol_quantity'] = observed_quantity
        managed = [p['remaining_quantity'] for p in positions if p['symbol'] == symbol]
        managed_quantity = sum(managed, ZERO) if all(q is not None for q in managed) else None
        if position['ownership'] == 'verified' and observed_quantity != managed_quantity:
            position['ownership'] = 'discrepancy'
            reasons.append('managed_quantity_discrepancy')
        seen_activities = set()
        for activity in broker.activities:
            if activity.get('activity_type') != 'FILL' or order_owners.get(activity.get('order_id')) != position['position_id']:
                continue
            bound_order = by_id[activity['order_id']]
            if activity['symbol'] != bound_order['symbol'] or activity['side'] != bound_order['side']:
                reasons.append('activity_order_mismatch')
                continue
            if activity['id'] in seen_activities:
                continue
            seen_activities.add(activity['id'])
            position['fills'].append(dict(activity_id=activity['id'], broker_order_id=activity['order_id'],
                side=activity['side'], quantity=money(activity['qty']), notional=money(activity['qty']) * money(activity['price']),
                timestamp=activity['transaction_time']))

    observations, duplicates, unattributed = {}, 0, 0
    positions_by_ref = {p['position_id']: p for p in positions}
    for row in streams.get('trade_journal.jsonl', []):
        # Every explicit order token must resolve, and execution tokens must
        # name the SAME order. The parent is contextual, not an exit alias.
        supplied_orders = [index.get(row[field]) for field, index in (
            ('broker_order_id', by_id), ('client_order_id', by_ref), ('exit_client_order_id', by_ref))
            if field in row]
        exact_order = supplied_orders[0] if supplied_orders else by_ref.get(row.get('parent_client_order_id'))
        owner_ref = order_owners.get(exact_order['id']) if exact_order else None
        position = positions_by_ref.get(owner_ref)
        corroborated = position is not None and exact_order is not None and all(
            order is not None and order['id'] == exact_order['id'] for order in supplied_orders)
        if position:
            corroborated = corroborated and all(
                field not in row or row[field] == position[field]
                for field in ('candidate_id', 'dossier_hash', 'proposal_hash', 'parent_client_order_id'))
            corroborated = corroborated and ('evidence_id' not in row or row['evidence_id'] in position['evidence_ids'])
        if not corroborated:
            unattributed += 1
        if row.get('broker_order_id') and row.get('cumulative_filled_quantity') is not None:
            try:
                observation_key = (row['broker_order_id'], money(row['cumulative_filled_quantity']))
                notional = money(row['cumulative_filled_notional']) if row.get('cumulative_filled_notional') is not None else None
            except ValueError:
                reasons.append('fill_observation_invalid')
                continue
            if observation_key in observations:
                duplicates += 1
                if observations[observation_key] != notional:
                    reasons.append('fill_observation_conflict')
            observations[observation_key] = notional
    if unattributed:
        reasons.append('journal_lineage_unknown')

    decisions = []
    for key, row in candidate_rows.items():
        links = component(key)
        events = [event for event in ledger if set(tokens(event)) & links]
        linked_reviews = [event for event in reviews if set(tokens(event)) & links]
        review_decisions = [review.get('decision') for event in linked_reviews for review in event.get('reviews', [])
                            if isinstance(review, dict) and isinstance(review.get('decision'), str)]
        review_status = 'reviewer_rejected' if 'HOLD' in review_decisions else 'approved' if 'APPROVE' in review_decisions else 'researched'
        status = events[-1].get('status', review_status) if events else review_status
        linked_refs = sorted(v for k, v in links if k == 'client_order_id')
        contradictory = any(ref in ambiguous_refs for ref in linked_refs)
        broker_statuses = sorted({by_ref[ref]['status'] for ref in linked_refs if ref in by_ref})
        if key not in filled and any(status in {'new', 'accepted', 'pending_new', 'held'} for status in broker_statuses):
            status = 'submitted_unfilled'
        decisions.append(dict(candidate_id=row.get('candidate_id'), dossier_hash=row.get('dossier_hash'), symbol=row.get('symbol'),
            proposal_hashes=sorted(v for k, v in links if k == 'proposal_hash'), client_order_ids=linked_refs,
            evidence_ids=sorted(v for k, v in links if k == 'evidence_id'), review_decisions=review_decisions,
            broker_statuses=broker_statuses,
            status='unknown' if contradictory else 'closed' if status == 'closed' and key in filled else 'filled' if key in filled else status,
            coverage='unknown' if contradictory or not op.complete else 'complete'))
    for row in candidates:
        if candidate_key(row) is None:
            reasons.append('candidate_identity_unknown')
            decisions.append(dict(candidate_id=None, dossier_hash=None, symbol=row.get('symbol'),
                                  proposal_hashes=[], client_order_ids=[], evidence_ids=[], review_decisions=[],
                                  broker_statuses=[], status='unknown', coverage='unknown'))
    reasons = list(dict.fromkeys(reasons))
    return LineageResult(positions, decisions, dict(status='unknown' if reasons else 'complete',
        ambiguous_order_refs=len(ambiguous_refs), unattributed_journal_rows=unattributed,
        duplicate_fill_observations=duplicates, managed_positions=len(positions),
        fill_event_coverage='requested_interval_only', operational_complete=op.complete, broker_complete=broker.complete), reasons)


def cumulative_fill_delta(current, previous):
    """No prior trusted observation means no proven delta (never replay a BUY)."""
    unknown = dict(status='unknown', quantity=None, notional=None, reason='fill_delta_coverage_unknown')
    if not previous or previous.get('trusted') is not True or current.get('trusted') is False:
        return unknown
    if 'captured_at' in current or 'captured_at' in previous:
        try:
            if aware_timestamp(current['captured_at']) < aware_timestamp(previous['captured_at']):
                return unknown
        except (KeyError, ValueError):
            return unknown
    identity = current.get('broker_order_id')
    if not isinstance(identity, str) or not identity or identity != previous.get('broker_order_id'):
        return unknown
    try:
        quantity, notional = money(current['cumulative_quantity']), money(current['cumulative_notional'])
        old_quantity, old_notional = money(previous['cumulative_quantity']), money(previous['cumulative_notional'])
    except (KeyError, ValueError):
        return unknown
    dq, dn = quantity - old_quantity, notional - old_notional
    if min(quantity, notional, old_quantity, old_notional, dq, dn) < 0 or (dq == 0) != (dn == 0):
        return unknown
    return dict(status='complete', quantity=dq, notional=dn, reason=None)
