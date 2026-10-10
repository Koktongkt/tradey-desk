"""Ephemeral exact-snapshot qualification; never model-authored execution authority."""
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import managed_reconciliation as m

_STATE = ('order_ledger.jsonl', 'trade_journal.jsonl', 'private/order_intents.jsonl',
          'private/protection_orders.jsonl', 'private/broker_baseline.json')
_SEAL = object()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def state_digest(root):
    return digest([(name, (Path(root)/name).read_bytes().hex() if (Path(root)/name).exists() else None)
                   for name in _STATE])


def enabled(cfg):
    return cfg.get('pending_entry_policy') == 'exact_owned_zero_fill_v1' and type(cfg.get('max_pending_entry_parents')) is int and cfg['max_pending_entry_parents'] == 2


@dataclass(frozen=True)
class Proof:
    snapshot_hash: str
    root: Path
    state_hash: str
    pending: tuple
    seal: object

    @property
    def reserved(self):
        return sum((Decimal(row[2]) for row in self.pending), Decimal(0))


def qualify(root, snapshot, broker):
    """Exact shared lineage checks against *this* snapshot, with no accounting repair."""
    # Provenance: Alpaca developer-relations staff note (2023, forum.alpaca.markets t/12745/2)
    # and official orders docs: buying_power is reduced by open long buys; cash is not
    # (updated at fill). Mapping: cash=gross (subtract verified outstanding buys once);
    # buying_power=available_net (already reflects open orders; never subtract again).
    # 2023 staff note, not a formal current account spec: provenance recorded, limit documented.
    for key in ("cash", "buying_power"):
        value = snapshot.get(key)
        m.require(not isinstance(value, bool) and isinstance(value, (int, float, str)), "funding_state_invalid")
        m.number(value, zero=True)
    def read(op, payload):
        m.require(op == 'reconciliation_snapshot')
        refs = payload['client_order_ids']
        orders = broker('reconcile_many', {'client_order_ids': refs}).get('orders') if refs else []
        return {**snapshot, 'orders': orders}
    _, summary = m.reconcile_detailed(root, read, verify_only=True)
    return Proof(digest(snapshot), Path(root), state_digest(root),
                 tuple((r['client_order_id'], r['symbol'], r['remaining_notional'], r['planned_risk']) for r in summary['pending']), _SEAL)


def valid(proof, snapshot):
    return (isinstance(proof, Proof) and proof.seal is _SEAL
            and proof.snapshot_hash == digest(snapshot) and proof.state_hash == state_digest(proof.root))


def cash_headroom(proof, snapshot):
    amount = m.number(snapshot["cash"], zero=True)
    # Reflected broker holds are subtracted once from gross cash, never again from net BP.
    return max(Decimal(0), amount - (proof.reserved if snapshot.get("cash_semantics") == "gross" else Decimal(0)))


def constraints(proof, snapshot, cfg, symbol):
    if not enabled(cfg) or not valid(proof, snapshot):
        return ['pending_qualification_required']
    errors = []
    if snapshot.get("cash_semantics") not in {"gross", "available_net"} or snapshot.get("buying_power_semantics") != "available_net":
        errors.append("funding_semantics_unverified")
    if any(Decimal(row[2]) > Decimal(str(cfg["max_position_usd"])) for row in proof.pending):
        errors.append("pending_position_size_exceeded")
    if any(Decimal(row[3]) > Decimal(str(cfg["max_planned_risk_per_trade_usd"])) for row in proof.pending):
        errors.append("pending_planned_risk_exceeded")
    if len(proof.pending) >= cfg['max_pending_entry_parents']:
        errors.append('pending_entry_limit')
    if any(row[1] == symbol for row in proof.pending):
        errors.append('same_symbol_pending_entry')
    return errors
