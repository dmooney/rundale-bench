import json,tempfile,unittest,hashlib
from pathlib import Path
from rundale_bench.qualification import owner_references,metrics,load_review
class QualificationTests(unittest.TestCase):
 def test_small_sample_metrics_are_not_population_claims(self):
  refs={'x':{'grounding':1,'craft':4}}
  judgments={'x':{'axes':{'grounding':5,'craft':4}}}
  m=metrics(['x'],refs,judgments)
  self.assertFalse(m['passed']);self.assertEqual(len(m['severe_misses']),1)
  self.assertIn('small',m['evidence_strength'])
 def test_unknown_reference_axes_do_not_qualify(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);(root/'review').mkdir()
   pack={'items':[{'id':'x','category':'dialogue'}]};rub={'categories':{'dialogue':{'grounding':{}}}};split={'selection':[],'validation':['x']}
   for n,v in [('pack.json',pack),('rubric.json',rub),('split.json',split)]: (root/'review'/n).write_text(json.dumps(v))
   export={'pack_sha256':hashlib.sha256((root/'review/pack.json').read_bytes()).hexdigest(),'rubric_sha256':hashlib.sha256((root/'review/rubric.json').read_bytes()).hexdigest(),'track':'owner','items':[{'id':'x','axes':{'grounding':None}}]}
   path=root/'ratings.json';path.write_text(json.dumps(export))
   with self.assertRaisesRegex(ValueError,'unlabelled'):owner_references(root,path)
 def test_review_and_suite_have_identical_english_anchors(self):
  root=Path(__file__).resolve().parents[1]
  actual=json.loads((root/'review/rubric.json').read_text())['categories'];suite=json.loads((root/'suites/3.0/rubrics.json').read_text())
  self.assertEqual({k:actual[k] for k in ('dialogue','multiturn')},suite)
 def test_selection_and_final_validation_disjoint_and_balanced(self):
  root=Path(__file__).resolve().parents[1];pack,_,split=load_review(root);by={i['id']:i for i in pack['items']}
  self.assertFalse(set(split['selection'])&set(split['validation']))
  self.assertEqual(set(split['selection'])|set(split['validation']),{i for i,x in by.items() if x['category']!='gaeilge'})
  for group in ('selection','validation'):
   for cat in ('dialogue','multiturn'):self.assertEqual(sum(by[i]['category']==cat for i in split[group]),4)
 def test_success_pins_manifest_and_is_idempotent(self):
  # Synthetic fixtures exercise the gate; these are never production reference labels.
  import shutil
  from rundale_bench.qualification import evaluate, digest, PROFILES
  from rundale_bench.runner import qualification_blockers
  source=Path(__file__).resolve().parents[1]
  with tempfile.TemporaryDirectory() as t:
   root=Path(t)
   for directory in ('review','suites','config'):shutil.copytree(source/directory,root/directory)
   pack,rubrics,split=load_review(root);english=[i for i in pack['items'] if i['category']!='gaeilge']
   refs=[{'id':i['id'],'axes':{a:3 for a in rubrics[i['category']]}} for i in english]
   ratings=root/'ratings.json';ratings.write_text(json.dumps({'pack_sha256':digest(root/'review/pack.json'),'rubric_sha256':digest(root/'review/rubric.json'),'track':'owner','items':refs}))
   from rundale_bench.providers import load_profiles
   profiles=load_profiles(root/'config/providers.json')
   checks=[{'id':'check-'+i['id'],'source_id':i['id'],'kind':'exact'} for i in english if i['id'] in split['selection']]
   judgments={pid:{i['id']:{'axes':row['axes'],'usage':{'input_tokens':100,'output_tokens':10,'cached_input_tokens':0}} for i,row in zip(english,refs)} for pid in PROFILES}
   for pid in PROFILES:
    for c in checks:judgments[pid][c['id']]=judgments[pid][c['source_id']]
   out=root/'output/qualification';out.mkdir(parents=True)
   collection={'pack_sha256':digest(root/'review/pack.json'),'rubric_sha256':digest(root/'review/rubric.json'),'split_sha256':digest(root/'review/split.json'),'profiles':{p:profiles[p] for p in PROFILES},'checks':checks,'cost_usd':.01}
   (out/'collection.json').write_text(json.dumps(collection));(out/'judgments.json').write_text(json.dumps(judgments))
   receipt=evaluate(root,ratings)
   self.assertEqual(receipt['status'],'qualified')
   manifest=json.loads((root/'suites/3.0/manifest.json').read_text())
   self.assertEqual(receipt['suite_hash'],digest(root/'suites/3.0/manifest.json'))
   self.assertEqual(qualification_blockers(root,manifest,receipt['suite_hash']),[])
   self.assertEqual(evaluate(root,ratings),receipt)
   (root/'config/providers.json').write_text('{}')
   self.assertTrue(any('provider' in s.lower() for s in qualification_blockers(root,manifest,receipt['suite_hash'])))
