"""Candidate output shapes: constrain syntax without supplying correct answers."""
from __future__ import annotations

import json


def object_schema(properties: dict) -> dict:
    return {'type': 'object', 'additionalProperties': False,
            'properties': properties, 'required': list(properties)}


def candidate_schema(case: dict) -> dict:
    if case['eval'] in ('dialogue', 'multiturn'):
        return object_schema({
            'dialogue': {'type': 'string'},
            'action': {'type': 'string'},
            'mood': {'type': 'string'},
            'language_hints': {'type': 'array', 'items': object_schema({
                key: {'type': 'string'} for key in ('word', 'pronunciation', 'meaning')})},
            'assigned_task': {'type': ['string', 'null']},
        })
    answer = case['answer']
    if answer['type'] == 'choice':
        return object_schema({'answer': {'type': 'string', 'enum': ['A', 'B']}})
    if answer['type'] == 'exact_json':
        return object_schema({key: ({'type': 'string', 'enum': ['A', 'B']}
                                   if key == 'irish_meaning_choice' else {'type': 'string'})
                              for key in answer['expected']})
    raise ValueError('Unsupported candidate output contract')


def validate_output(text: str, schema: dict) -> None:
    """Validate the small frozen schema vocabulary, without repairing the response."""
    def unique_object(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError('Structured output contains duplicate object keys')
            obj[key] = value
        return obj

    try:
        obj = json.loads(text, object_pairs_hook=unique_object)
    except (ValueError, TypeError) as exc:
        raise ValueError('Expected native structured JSON output') from exc

    def check(value, spec):
        types = spec['type'] if isinstance(spec['type'], list) else [spec['type']]
        matches = {'object': isinstance(value, dict), 'array': isinstance(value, list),
                   'string': isinstance(value, str), 'null': value is None}
        if not any(matches.get(kind, False) for kind in types):
            raise ValueError('Structured output has an invalid field type')
        if 'enum' in spec and value not in spec['enum']:
            raise ValueError('Structured output contains an invalid choice')
        if isinstance(value, dict):
            if set(value) != set(spec['properties']):
                raise ValueError('Structured output must contain exactly the required fields')
            for key, item in value.items():
                check(item, spec['properties'][key])
        elif isinstance(value, list):
            for item in value:
                check(item, spec['items'])

    check(obj, schema)
