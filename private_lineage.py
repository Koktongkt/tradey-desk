"""Forward-only private persistence metadata. Never merge into executable plans."""
from decimal import Decimal, InvalidOperation

LINEAGE_FIELDS = ('candidate_id', 'dossier_hash', 'proposal_hash', 'parent_client_order_id')


def private_lineage(source):
    """Copy supplied exact identities only, without mutation or invented IDs."""
    return {key: source[key] for key in LINEAGE_FIELDS
            if isinstance(source.get(key), str) and source[key]}


def confirmed_fill_metadata(order, lineage=None):
    """Add broker execution identity and cumulative observations, not new trades."""
    result = private_lineage(lineage or {})
    for key, source in (('broker_order_id', 'id'), ('client_order_id', 'client_order_id')):
        if isinstance(order.get(source), str) and order[source]:
            result[key] = order[source]
    try:
        quantity = Decimal(str(order['filled_qty']))
        price = Decimal(str(order['filled_avg_price']))
        if quantity.is_finite() and price.is_finite() and quantity > 0 and price > 0:
            result.update(cumulative_filled_quantity=str(quantity), cumulative_filled_notional=str(quantity * price))
    except (KeyError, InvalidOperation, ValueError):
        pass  # Metadata cannot introduce an execution-policy gate.
    return result
