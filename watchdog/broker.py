"""Deterministic paper-only broker observation boundary; never dispatches writes."""
from copy import deepcopy
import asyncio
from typing import Any
from broker_mcp_bridge import text_result, alpaca_mcp_config
from fastmcp import Client
from jsonschema import Draft202012Validator, SchemaError, ValidationError
from dataclasses import asdict
from decimal import Decimal
import json
import sys
from datetime import datetime, timezone
from broker_normalization import tool_arguments
from watchdog.types import BrokerSnapshot, aware_timestamp, money, snapshot_time_reasons
from zoneinfo import ZoneInfo

# No aliases are needed for these verified schemas. Unsupported logical fields
# must fail rather than being silently dropped by transport normalization.
PARAMETERS = {
    'get_account_info': (set(), set()),
    'get_all_positions': (set(), set()),
    'get_orders': ({'status', 'nested', 'limit', 'direction'}, {'before_order_id'}),
    'get_order_by_client_id': ({'client_order_id'}, set()),
    'get_calendar': ({'start', 'end', 'date_type'}, set()),
    'get_account_activities': ({'after', 'until', 'direction', 'page_size'}, {'page_token'}),
}


def validate_request(name, values, schema, validator):
    if not isinstance(values, dict) or not isinstance(schema, dict):
        raise ValueError('broker_read_arguments_invalid')
    required, optional = PARAMETERS[name]
    if not required <= values.keys() or values.keys() - required - optional:
        raise ValueError('broker_read_arguments_invalid')
    if name == 'get_orders' and (values['status'] != 'open' or values['nested'] is not True
                                or values['direction'] != 'desc' or values['limit'] != 500):
        raise ValueError('broker_read_arguments_invalid')
    if name == 'get_calendar' and values['date_type'] != 'TRADING':
        raise ValueError('broker_read_arguments_invalid')
    if name == 'get_account_activities' and (values['direction'] != 'asc' or values['page_size'] != 100):
        raise ValueError('broker_read_arguments_invalid')
    for key in ('start', 'end', 'after', 'until'):
        if key in values:
            aware_timestamp(values[key])
    for left, right in (('start', 'end'), ('after', 'until')):
        if left in values and aware_timestamp(values[left]) >= aware_timestamp(values[right]):
            raise ValueError('broker_read_interval_invalid')
    props = schema.get('properties', {})
    if schema.get('type') != 'object' or not isinstance(props, dict):
        raise ValueError('broker_read_schema_invalid')
    if not set(schema.get('required', [])) <= values.keys():
        raise ValueError('broker_read_schema_required')
    for key, value in values.items():
        field = props.get(key, {})
        expected = field.get('type')
        valid = ((expected == 'string' and isinstance(value, str) and 0 < len(value) <= 128)
                 or (expected == 'integer' and type(value) is int)
                 or (expected == 'boolean' and type(value) is bool))
        if not valid or ('enum' in field and value not in field['enum']):
            raise ValueError('broker_read_schema_invalid')
        if type(value) is int and (value < field.get('minimum', value) or value > field.get('maximum', value)):
            raise ValueError('broker_read_schema_invalid')
    try:
        args = tool_arguments(props, values)
    except RuntimeError:
        raise ValueError('broker_read_schema_invalid') from None
    if args != values:
        raise ValueError('broker_read_parameters_lost')
    try:
        validator.validate(args)
    except ValidationError:
        raise ValueError('broker_read_schema_invalid') from None
    return args

# Exact tool names verified against the configured MCP list_tools catalog.
READ_TOOLS = frozenset({'get_account_info', 'get_all_positions', 'get_orders',
                        'get_order_by_client_id', 'get_calendar', 'get_account_activities'})


def schema_has_reference(value):
    if isinstance(value, dict):
        return ('$ref' in value or '$dynamicRef' in value
                or any(schema_has_reference(item) for item in value.values()))
    if isinstance(value, list):
        return any(schema_has_reference(item) for item in value)
    return False


class ReadOnlyAlpaca:
    def __init__(self, client, tool_schemas):
        self._client = client
        self._schemas = deepcopy(tool_schemas)
        self._validators = {}

    async def call(self, name: str, values: dict) -> object:
        if name not in READ_TOOLS or name not in self._schemas:
            raise ValueError('broker_read_tool_forbidden')
        if name not in self._validators:
            if schema_has_reference(self._schemas[name]):
                # No verified read schema needs references; never fetch schemas.
                raise ValueError('broker_read_schema_reference_forbidden')
            try:
                Draft202012Validator.check_schema(self._schemas[name])
                self._validators[name] = Draft202012Validator(self._schemas[name])
            except SchemaError:
                raise ValueError('broker_read_schema_invalid') from None
        args = validate_request(name, deepcopy(values), self._schemas[name], self._validators[name])
        return await self._client.call_tool(name, args)


def utc_now():
    return datetime.now(timezone.utc)


def project(row, source, text_fields=(), numeric_fields=(), time_fields=()):
    if not isinstance(row, dict) or 'error' in row:
        raise ValueError('broker_row_invalid')
    result = {}
    for key in text_fields:
        if row.get(key) is not None:
            if not isinstance(row[key], str) or not row[key] or len(row[key]) > 128:
                raise ValueError('broker_field_invalid')
            result[key] = row[key]
    result.update({key: money(row[key]) for key in numeric_fields if row.get(key) is not None})
    result.update({key: aware_timestamp(row[key]).isoformat() for key in time_fields if row.get(key) is not None})
    result['provenance'] = {key: f'{source}.{key}' for key in result}
    return result


def require(row, fields):
    if not set(fields) <= row.keys():
        raise ValueError('broker_required_field_missing')


def normalize_account(row):
    result = project(row, 'get_account_info', numeric_fields=
                     ('cash', 'equity', 'long_market_value', 'short_market_value', 'last_equity'))
    require(result, ('cash', 'equity'))
    return result


def normalize_position(row):
    result = project(row, 'get_all_positions', ('symbol', 'side'),
                     ('qty', 'avg_entry_price', 'current_price', 'market_value', 'cost_basis', 'unrealized_pl'))
    require(result, ('symbol', 'side', 'qty', 'avg_entry_price', 'current_price', 'market_value', 'cost_basis'))
    if result['side'] not in {'long', 'short'} or result['qty'] == 0:
        raise ValueError('broker_position_domain_invalid')
    if any(result[key] <= 0 for key in ('avg_entry_price', 'current_price')):
        raise ValueError('broker_position_domain_invalid')
    if result['side'] == 'long' and any(result[key] <= 0 for key in ('qty', 'market_value', 'cost_basis')):
        raise ValueError('broker_position_domain_invalid')
    if result['side'] == 'short' and any(result[key] >= 0 for key in ('qty', 'market_value', 'cost_basis')):
        raise ValueError('broker_position_domain_invalid')
    return result


def normalize_session(row):
    result = project(row, 'get_calendar', ('date', 'open', 'close'))
    require(result, ('date', 'open', 'close'))
    zone = ZoneInfo('America/New_York')
    for key in ('open', 'close'):
        value = datetime.fromisoformat(result['date'] + 'T' + result[key])
        if value.tzinfo is not None:
            raise ValueError('broker_calendar_invalid')
        result[key + '_at'] = value.replace(tzinfo=zone).isoformat()
        result['provenance'][key + '_at'] = f'get_calendar.{key}+date:America/New_York'
    if aware_timestamp(result['open_at']) >= aware_timestamp(result['close_at']):
        raise ValueError('broker_calendar_invalid')
    return result


def response_payload(raw, collection=None, *, now):
    # MCP errors and malformed text are never normalized to an empty success.
    if getattr(raw, 'is_error', False):
        raise ValueError('broker_transport_error')
    if not isinstance(raw, (dict, list)):
        structured = getattr(raw, 'structured_content', None)
        raw = structured if isinstance(structured, (dict, list)) else text_result(raw)
    totals = []
    for _ in range(8):
        if not isinstance(raw, dict):
            break
        if ('error' in raw or 'text' in raw or raw.get('complete') is False
                or raw.get('isError') or raw.get('is_error')
                or raw.get('has_more') not in (None, False) or raw.get('next_page_token')
                or raw.get('next_token')):
            raise ValueError('broker_transport_error')
        if 'captured_at' in raw:
            if snapshot_time_reasons(raw['captured_at'], now=now, max_age_seconds=60):
                raise ValueError('broker_source_timestamp_invalid')
        if collection:
            totals.extend(raw[key] for key in ('total', 'count', 'total_count') if key in raw)
        keys = list(dict.fromkeys(key for key in ('data', 'result', collection) if key and key in raw))
        if len(keys) > 1:
            raise ValueError('broker_envelope_ambiguous')
        if not keys:
            break
        raw = raw[keys[0]]
    if collection is not None:
        if not isinstance(raw, list) or any(not isinstance(row, dict) for row in raw):
            raise ValueError('broker_collection_invalid')
        if any(type(total) is not int or total != len(raw) for total in totals):
            raise ValueError('broker_declared_count_mismatch')
    elif not isinstance(raw, dict):
        raise ValueError('broker_mapping_invalid')
    return raw


def normalize_order(row, source):
    result = project(row, source,
        ('id', 'client_order_id', 'symbol', 'side', 'type', 'status', 'time_in_force', 'order_class'),
        ('qty', 'filled_qty', 'filled_avg_price', 'limit_price', 'stop_price'),
        ('filled_at', 'submitted_at', 'created_at', 'updated_at', 'expired_at', 'canceled_at'))
    require(result, ('id', 'client_order_id', 'symbol', 'side', 'type', 'status', 'time_in_force',
                     'qty', 'filled_qty'))
    if result['side'] not in {'buy', 'sell'} or result['qty'] <= 0 or not 0 <= result['filled_qty'] <= result['qty']:
        raise ValueError('broker_order_domain_invalid')
    if any(result[key] <= 0 for key in ('filled_avg_price', 'limit_price', 'stop_price') if key in result):
        raise ValueError('broker_order_price_invalid')
    if result['filled_qty'] > 0:
        require(result, ('filled_avg_price', 'filled_at'))
    legs = row.get('legs')
    if legs is not None and (not isinstance(legs, list) or any(not isinstance(leg, dict) for leg in legs)):
        raise ValueError('broker_order_legs_invalid')
    result['legs'] = [normalize_order(leg, source) for leg in legs or []]
    return result


# Concrete activity types from the verified catalog, not aggregate query filters.
ACTIVITY_TYPES = frozenset('FILL ACATC ACATS CFEE CGD CSD CSW DIV DIVCGL DIVCGS DIVFEE DIVFT DIVNRA DIVROC DIVTW DIVTXEX FEE INT INTNRA INTTW JNL JNLC JNLS MA NC OPASN OPCA OPCSH OPEXC OPEXP OPTRD PTC PTR REO REORG SPIN SPLIT FOPT OCT'.split())


def normalize_activity(row):
    result = project(row, 'get_account_activities',
                     ('id', 'activity_type', 'symbol', 'order_id', 'side', 'date', 'type'),
                     ('net_amount', 'qty', 'price', 'cum_qty', 'leaves_qty', 'per_share_amount'),
                     ('transaction_time', 'created_at'))
    require(result, ('id', 'activity_type'))
    kind = result['activity_type']
    if kind not in ACTIVITY_TYPES:
        raise ValueError('broker_activity_type_unknown')
    if kind == 'FILL':
        require(result, ('order_id', 'symbol', 'side', 'qty', 'price', 'transaction_time'))
        if result['side'] not in {'buy', 'sell'} or result['qty'] <= 0 or result['price'] <= 0:
            raise ValueError('broker_activity_fill_invalid')
    else:
        require(result, ('date',))
        if datetime.fromisoformat(result['date']).isoformat()[:10] != result['date']:
            raise ValueError('broker_activity_date_invalid')
        # Security-only corporate actions need not have a cash component.
        if kind not in {'ACATS', 'JNLS', 'MA', 'NC', 'REO', 'REORG', 'SPIN', 'SPLIT', 'FOPT'}:
            require(result, ('net_amount',))
    if any(result[key] < 0 for key in ('cum_qty', 'leaves_qty') if key in result):
        raise ValueError('broker_activity_quantity_invalid')
    return result


def order_tree(rows):
    for row in rows:
        yield row
        yield from order_tree(row['legs'])


def observed_fields(value):
    if isinstance(value, dict):
        return {key: observed_fields(item) for key, item in value.items() if key != 'provenance'}
    if isinstance(value, list):
        return [observed_fields(item) for item in value]
    return value


def validate_collection_input(refs, start, end):
    if (not isinstance(refs, list) or len(refs) > 500
            or any(not isinstance(ref, str) or not ref or len(ref) > 128 for ref in refs)):
        raise ValueError('broker_references_invalid')
    if aware_timestamp(start) >= aware_timestamp(end):
        raise ValueError('broker_interval_invalid')


async def collect_broker(reader: ReadOnlyAlpaca, refs: list[str], start: str, end: str) -> BrokerSnapshot:
    validate_collection_input(refs, start, end)
    captured = utc_now()
    coverage: dict = {key: 'complete' for key in ('account', 'positions', 'orders', 'references', 'calendar',
                'activities', 'account_cashflows', 'distribution', 'fees', 'corporate_actions')}
    coverage.update(interval={'start': start, 'end': end}, reasons=[])

    def unknown(key):
        coverage[key] = 'unknown'
        reason = key + '_coverage_unknown'
        if reason not in coverage['reasons']:
            coverage['reasons'].append(reason)

    deadline = asyncio.get_running_loop().time() + 60

    async def request(name, args, collection=None):
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TimeoutError('broker_read_deadline')
        raw = await asyncio.wait_for(reader.call(name, args), timeout=min(15, remaining))
        return response_payload(raw, collection, now=captured)

    async def read(key, name, args, normalize, collection=None) -> Any:
        try:
            payload = await request(name, args, collection)
            return [normalize(row) for row in payload] if collection else normalize(payload)
        except Exception:
            # Never put exception text/transport payloads in snapshots or reports.
            unknown(key)
            return [] if collection else {}

    async def pages(key, name, args, normalize, page_size, cursor):
        rows, seen = [], set()
        try:
            for _ in range(20):
                payload = await request(name, args, key)
                if len(payload) > page_size:
                    raise ValueError('broker_page_oversize')
                batch = [normalize(row) for row in payload]
                ids = [row['id'] for row in batch]
                if len(set(ids)) != len(ids) or seen.intersection(ids):
                    raise ValueError('broker_pagination_repeated')
                rows.extend(batch)
                seen.update(ids)
                if len(batch) < page_size:
                    return rows
                args = {**args, cursor: ids[-1]}
            raise ValueError('broker_pagination_limit')
        except Exception:
            unknown(key)
            return rows

    account = await read('account', 'get_account_info', {}, normalize_account)
    positions = await read('positions', 'get_all_positions', {}, normalize_position, 'positions')
    orders = await pages('orders', 'get_orders',
                         {'status': 'open', 'nested': True, 'limit': 500, 'direction': 'desc'},
                         lambda row: normalize_order(row, 'get_orders'), 500, 'before_order_id')
    for ref in dict.fromkeys(refs):
        row = await read('references', 'get_order_by_client_id', {'client_order_id': ref},
                         lambda row: normalize_order(row, 'get_order_by_client_id'))
        if row.get('client_order_id') != ref:
            unknown('references')
            continue
        existing = next((item for item in order_tree(orders) if item['id'] == row['id']), None)
        if existing is None:
            orders.append(row)
        elif observed_fields(existing) != observed_fields(row):
            unknown('references')
    sessions = await read('calendar', 'get_calendar', {'start': start, 'end': end, 'date_type': 'TRADING'},
                          normalize_session, 'calendar')
    activities = await pages('activities', 'get_account_activities',
                              {'after': start, 'until': end, 'direction': 'asc', 'page_size': 100},
                              normalize_activity, 100, 'page_token')
    coverage['activity_time_basis'] = 'broker_creation_time_exclusive_bounds'
    coverage['accounting_scope'] = 'requested_interval_only_not_lifetime_total_return'
    if any(row['activity_type'] in {'ACATS', 'JNLS', 'MA', 'NC', 'REO', 'REORG', 'SPIN', 'SPLIT', 'FOPT'}
           for row in activities):
        # Activity existence alone does not establish split ratios/lot adjustments.
        unknown('corporate_actions')
    if coverage['activities'] != 'complete':
        for key in ('account_cashflows', 'distribution', 'fees', 'corporate_actions'):
            unknown(key)
        coverage['reasons'].append('account_cashflows_unknown')
    if snapshot_time_reasons(captured.isoformat(), now=utc_now(), max_age_seconds=60):
        coverage['reasons'].append('broker_snapshot_stale')
    return BrokerSnapshot(account, positions, orders, activities, sessions, captured.isoformat(),
                          not coverage['reasons'], coverage)


async def collect_configured(payload: dict) -> BrokerSnapshot:
    """Credential-bearing worker only; call in a deterministic subprocess.

    No arbitrary operation passthrough and no model-authored order/action fields.
    CLI/model callers must not instantiate this inside a thesis model process.
    """
    if not isinstance(payload, dict) or set(payload) != {'refs', 'start', 'end'}:
        raise ValueError('broker_payload_invalid')
    validate_collection_input(payload['refs'], payload['start'], payload['end'])
    # Existing loader rejects non-paper configuration before starting the server.
    config = alpaca_mcp_config()
    async with Client(config) as client:
        listing = await asyncio.wait_for(client.list_tools(), timeout=30)
        schemas = {tool.name: tool.inputSchema for tool in listing}
        return await collect_broker(ReadOnlyAlpaca(client, schemas), **payload)


def main() -> int:
    """Invoke as `python -m watchdog.broker`; emit no raw transport/errors."""
    try:
        payload = json.loads(sys.stdin.read(65537))
        snapshot = asyncio.run(collect_configured(payload))
        def decimal_json(value):
            if isinstance(value, Decimal):
                return str(value)
            raise TypeError('invalid_snapshot_value')
        encoded = json.dumps(asdict(snapshot), default=decimal_json, allow_nan=False, separators=(',', ':'))
        print(encoded)
        return 0
    except Exception:
        print(json.dumps({'error': 'broker_read_failed'}), file=sys.stderr)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
