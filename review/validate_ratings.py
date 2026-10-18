"""Validate an exported human review without creating judge reference labels."""
import argparse,hashlib,json
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('ratings',type=Path);args=parser.parse_args()
p=Path(__file__).parent
pack_bytes=(p/'pack.json').read_bytes();pack=json.loads(pack_bytes);rubric=json.loads((p/'rubric.json').read_text());r=json.loads(args.ratings.read_text())
assert r['schema_version']=='human-review-v2','Unexpected review schema'
assert r['pack_sha256']==hashlib.sha256(pack_bytes).hexdigest(),'Ratings are for a different pack revision'
assert r.get('rubric_sha256')==hashlib.sha256((p/'rubric.json').read_bytes()).hexdigest(),'Ratings are for a different rubric revision'
assert isinstance(r['reviewer'],str) and r['reviewer'].strip(),'Reviewer identifier required'
assert r['track'] in ['owner','irish'],'Unknown review track'
if r['track']=='irish':assert r['fluent_irish_attested'] is True,'Fluent Irish attestation required'
expected={i['id']:i for i in pack['items'] if (i['category']=='gaeilge')==(r['track']=='irish')}
assert len(r['items'])==len(expected) and {i['id'] for i in r['items']}==set(expected),'Missing, extra, or duplicated case IDs'
complete=0;skipped=0
for rating in r['items']:
 dims=rubric['categories'][expected[rating['id']]['category']];axes=rating['axes'];assert set(axes)<=set(dims),'Unexpected dimension'
 assert isinstance(rating['notes'],str),'Notes must be text'
 for value in axes.values():assert value is None or (type(value)==int and 1<=value<=5),'Score outside 1–5/null'
 if set(axes)==set(dims) and (all(v is not None for v in axes.values()) or rating['notes'].strip()):complete+=1
 skipped+=sum(v is None for v in axes.values())
assert r['completed']==complete and r['total']==len(expected),'Reported completion does not match ratings'
print(json.dumps({'valid_export':True,'complete_cases':complete,'total_cases':len(expected),'skipped_dimensions':skipped,'status':'complete review; skipped axes remain unlabelled' if complete==len(expected) else 'partial review; not ready for judge qualification'}))
