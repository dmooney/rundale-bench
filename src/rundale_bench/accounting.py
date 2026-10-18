"""Durable pre-call reservations; uncertain invoices are never free."""
from __future__ import annotations
import hashlib
import json
import math
import sqlite3
from pathlib import Path

class BudgetError(RuntimeError):
    pass

class UncertainBilling(BudgetError):
    pass

def validate_prices(profile: dict) -> None:
    for key in ('input_per_million_usd', 'output_per_million_usd'):
        value = profile.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise BudgetError(f'Unknown or invalid pricing: {key}')

    value=profile.get('cached_input_per_million_usd')
    if value is not None and (isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0):
        raise BudgetError('Invalid cached input pricing')

def actual_cost(profile: dict, usage: dict) -> float:
    validate_prices(profile)
    for key in ('input_tokens', 'output_tokens'):
        if type(usage.get(key)) is not int or usage[key] < 0:
            raise UncertainBilling(f'Missing or invalid billed {key}')
    cached = usage.get('cached_input_tokens', 0)
    if type(cached) is not int or cached < 0 or cached > usage['input_tokens']:
        raise UncertainBilling('Invalid cached input usage')
    cached_rate = profile.get('cached_input_per_million_usd')
    if cached_rate is None:
        cached_rate = profile['input_per_million_usd']
    # Provider output_tokens includes reasoning: do not add reasoning_tokens again.
    return ((usage['input_tokens'] - cached) * profile['input_per_million_usd']
            + cached * cached_rate + usage['output_tokens'] * profile['output_per_million_usd']) / 1_000_000

def upper_cost(profile: dict, messages: list, max_output_tokens: int, extra: dict | None = None) -> float:
    validate_prices(profile)
    if type(max_output_tokens) is not int or max_output_tokens <= 0:
        raise BudgetError('A positive output/reasoning token limit is required')
    # UTF-8 bytes bound ordinary text tokenization; allowance covers native wrappers,
    # schema, and rubric expansion. Never use a discounted cache assumption here.
    input_bound = len(json.dumps({'messages': messages, 'extra': extra}, ensure_ascii=False).encode()) + 16384
    return (input_bound * profile['input_per_million_usd'] + max_output_tokens * profile['output_per_million_usd']) / 1_000_000

class Ledger:
    def __init__(self, path: Path, cap: float):
        if not math.isfinite(cap) or cap <= 0:
            raise BudgetError('Cap must be a finite positive dollar amount')
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute('CREATE TABLE IF NOT EXISTS meta (id INTEGER PRIMARY KEY, cap REAL NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS calls (id TEXT PRIMARY KEY, digest TEXT NOT NULL, state TEXT NOT NULL, reserved REAL NOT NULL, actual REAL, response TEXT)')
        row = self.db.execute('SELECT cap FROM meta WHERE id=1').fetchone()
        if row is None:
            self.db.execute('INSERT INTO meta VALUES (1, ?)', (cap,))
        elif row['cap'] != cap:
            self.db.close()
            raise BudgetError('Resume must use the original spending cap')
        self.cap = cap
        self.db.commit()

    @property
    def exposure(self) -> float:
        return self.db.execute("SELECT COALESCE(SUM(CASE WHEN state='committed' THEN actual WHEN state IN ('reserved','uncertain') THEN reserved ELSE 0 END),0) FROM calls").fetchone()[0]

    @property
    def spent(self) -> float:
        return self.db.execute("SELECT COALESCE(SUM(actual),0) FROM calls WHERE state='committed'").fetchone()[0]

    def cached(self, request_id: str, request: dict) -> dict | None:
        row = self.db.execute('SELECT * FROM calls WHERE id=?', (request_id,)).fetchone()
        if row is None:
            return None
        digest = self.request_digest(request)
        if row['digest'] != digest:
            raise BudgetError('Resume request differs from the paid request')
        if row['state'] == 'committed':
            return json.loads(row['response'])
        if row['state'] in ('reserved', 'uncertain'):
            raise UncertainBilling('Previous request may have been billed; reconcile it before continuing')
        return None

    @staticmethod
    def request_digest(request: dict) -> str:
        return hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def cached_request(self, request: dict) -> tuple[str, dict] | None:
        """Find a committed receipt by request content, independent of its call ID."""
        digest = self.request_digest(request)
        rows = self.db.execute('SELECT id,state,response FROM calls WHERE digest=? ORDER BY id', (digest,)).fetchall()
        if any(row['state'] in ('reserved', 'uncertain') for row in rows):
            raise UncertainBilling('A matching request may have been billed; reconcile it before continuing')
        for row in rows:
            if row['state'] == 'committed':
                return row['id'], json.loads(row['response'])
        return None

    def committed_calls(self) -> list[tuple[str, dict]]:
        rows = self.db.execute("SELECT id,response FROM calls WHERE state='committed' ORDER BY id").fetchall()
        return [(row['id'], json.loads(row['response'])) for row in rows]

    def reserve(self, request_id: str, request: dict, amount: float, future_judging: float = 0) -> None:
        if not all(math.isfinite(v) and v >= 0 for v in (amount, future_judging)):
            raise BudgetError('Invalid cost reservation')
        digest = self.request_digest(request)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            if self.db.execute("SELECT 1 FROM calls WHERE state IN ('reserved','uncertain')").fetchone():
                raise UncertainBilling('An earlier request has unresolved billing')
            if self.exposure + amount + future_judging > self.cap + 1e-12:
                raise BudgetError('Budget cannot cover this request and its required judging')
            old = self.db.execute('SELECT * FROM calls WHERE id=?', (request_id,)).fetchone()
            if old and old['state'] != 'cancelled':
                raise BudgetError('Request already exists; use cached result')
            self.db.execute('INSERT OR REPLACE INTO calls VALUES (?,?,?,?,NULL,NULL)', (request_id, digest, 'reserved', amount))
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def commit(self, request_id: str, response: dict, cost: float) -> None:
        row = self.db.execute('SELECT * FROM calls WHERE id=?', (request_id,)).fetchone()
        if row is None or row['state'] != 'reserved':
            raise BudgetError('Only a reserved call can be committed')
        if not math.isfinite(cost) or cost < 0:
            raise UncertainBilling('Invalid actual cost')
        self.db.execute('UPDATE calls SET state=?,actual=?,response=? WHERE id=?', ('committed', cost, json.dumps(response, ensure_ascii=False), request_id))
        self.db.commit()
        if cost > row['reserved'] + 1e-12 or self.exposure > self.cap + 1e-12:
            raise BudgetError('Provider usage exceeded its conservative reservation; further calls stopped')

    def fail(self, request_id: str, uncertain: bool = True) -> None:
        self.db.execute("UPDATE calls SET state=? WHERE id=? AND state='reserved'", ('uncertain' if uncertain else 'cancelled', request_id))
        self.db.commit()

    def close(self):
        self.db.close()
