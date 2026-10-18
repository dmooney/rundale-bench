"""Scoring and uncertainty for a fixed application-specific composite."""
from __future__ import annotations
import json
import math
import random
import statistics

EVALS = ('dialogue', 'multiturn', 'gaeilge')
GA_GROUPS = ('grammar', 'meaning', 'code_switch')

def rubric_score(axes: dict, expected_axes: dict) -> float:
    if set(axes) != set(expected_axes) or any(type(v) is not int or not 1 <= v <= 5 for v in axes.values()):
        raise ValueError('Judgment must contain every expected axis with an integer 1–5')
    return 25 * (statistics.mean(axes.values()) - 1)

def objective_score(text: str, answer: dict) -> float:
    # Keys are not substrings; prose or ambiguous answer letters are not accepted.
    if answer['type'] == 'choice':
        value = text.strip()
        try:
            obj = json.loads(value)
            value = obj.get('answer') if isinstance(obj, dict) else obj
        except json.JSONDecodeError:
            pass
        return 100.0 if value == answer['expected'] else 0.0
    if answer['type'] == 'exact_json':
        obj = json.loads(text)
        return 100.0 if obj == answer['expected'] else 0.0
    raise ValueError('Unknown reference answer type')

def aggregate(case_results: list[dict], cases: list[dict]) -> dict:
    primary = {r['case_id']: r for r in case_results if r.get('trial', 0) == 0}
    scores = {}
    coverage = {}
    for category in EVALS:
        required = [c for c in cases if c['eval'] == category]
        available = [primary[c['id']] for c in required if c['id'] in primary and primary[c['id']].get('score') is not None]
        coverage[category] = {'completed': len(available), 'required': len(required)}
        if not required or len(available) != len(required):
            scores[category] = None
        elif category == 'gaeilge':
            groups = []
            for group in GA_GROUPS:
                values = [primary[c['id']]['score'] for c in required if c['subcategory'] == group]
                groups.append(statistics.mean(values) if values else None)
            scores[category] = statistics.mean(groups) if None not in groups else None
        else:
            scores[category] = statistics.mean(r['score'] for r in available)
    overall = statistics.mean(scores.values()) if all(v is not None for v in scores.values()) else None
    return {'scores': scores, 'overall': overall, 'coverage': coverage}

def wilson(successes: int, count: int) -> list[float] | None:
    if count == 0:
        return None
    if not 0 <= successes <= count:
        raise ValueError('Invalid accuracy counts')
    z = 1.959963984540054
    p = successes / count
    denominator = 1 + z*z/count
    center = (p + z*z/(2*count))/denominator
    radius = z * math.sqrt(p*(1-p)/count + z*z/(4*count*count))/denominator
    return [max(0, center-radius), min(1, center+radius)]

def paired_difference(left: dict[str, float], right: dict[str, float], draws: int = 2000) -> dict:
    ids = sorted(set(left) & set(right))
    if not ids:
        return {'n': 0, 'mean_difference': None, 'interval_95': None}
    values = [left[i]-right[i] for i in ids]
    rng = random.Random(300)
    samples = sorted(statistics.mean(rng.choices(values, k=len(values))) for _ in range(draws))
    return {'n': len(ids), 'mean_difference': statistics.mean(values), 'interval_95': [samples[int(.025*draws)], samples[min(draws-1, int(.975*draws))]], 'small_sample': len(ids) < 30, 'unit': 'case (whole conversation for multiturn)'}

def variability(results: list[dict]) -> dict:
    primary = {r['case_id']: r for r in results if r.get('trial',0)==0}
    changes = [abs(r['score']-primary[r['case_id']]['score']) for r in results if r.get('trial',0)>0 and r.get('score') is not None and primary.get(r['case_id'],{}).get('score') is not None]
    return {'repeated_cases': len(changes), 'mean_absolute_score_change': statistics.mean(changes) if changes else None}
