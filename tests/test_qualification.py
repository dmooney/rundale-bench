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
   manifest_path=root/'suites/3.0/manifest.json';manifest=json.loads(manifest_path.read_text());manifest.update(validation_mode='owner',status='draft',judge_policy={'dialogue':None,'multiturn':None});manifest_path.write_text(json.dumps(manifest))
   pack,rubrics,split=load_review(root);english=[i for i in pack['items'] if i['category']!='gaeilge']
   refs=[{'id':i['id'],'axes':{a:3 for a in rubrics[i['category']]}} for i in english]
   ratings=root/'ratings.json';ratings.write_text(json.dumps({'pack_sha256':digest(root/'review/pack.json'),'rubric_sha256':digest(root/'review/rubric.json'),'track':'owner','items':refs}))
   from rundale_bench.providers import load_profiles
   profiles=load_profiles(root/'config/providers.json')
   from rundale_bench.bias import build_checks
   checks=build_checks({i['id']:i for i in english},split)
   protocol_hash=hashlib.sha256(json.dumps(checks,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
   judgments={pid:{i['id']:{'axes':row['axes'],'usage':{'input_tokens':100,'output_tokens':10,'cached_input_tokens':0}} for i,row in zip(english,refs)} for pid in PROFILES}
   for pid in PROFILES:
    for c in checks:
     import copy
     judgments[pid][c['id']]=copy.deepcopy(judgments[pid][c['source_id']])
     if not c['expected_invariant']:judgments[pid][c['id']]['axes']['craft']=1
   out=root/'output/qualification';out.mkdir(parents=True)
   collection={'pack_sha256':digest(root/'review/pack.json'),'rubric_sha256':digest(root/'review/rubric.json'),'split_sha256':digest(root/'review/split.json'),'profiles':{p:profiles[p] for p in PROFILES},'checks':[{k:v for k,v in c.items() if k!='item'} for c in checks],'bias_protocol_sha256':protocol_hash,'cost_usd':.01}
   (out/'collection.json').write_text(json.dumps(collection));(out/'judgments.json').write_text(json.dumps(judgments))
   receipt=evaluate(root,ratings)
   self.assertEqual(receipt['status'],'qualified')
   for pid in PROFILES:self.assertEqual(receipt['metrics']['dialogue'][pid]['repeat_agreement']['fraction'],1)
   manifest=json.loads((root/'suites/3.0/manifest.json').read_text())
   self.assertEqual(receipt['suite_hash'],digest(root/'suites/3.0/manifest.json'))
   self.assertEqual(qualification_blockers(root,manifest,receipt['suite_hash']),[])
   self.assertEqual(evaluate(root,ratings),receipt)
   (root/'config/providers.json').write_text('{}')
   self.assertTrue(any('provider' in s.lower() for s in qualification_blockers(root,manifest,receipt['suite_hash'])))
 def test_collection_uses_six_frozen_controls_and_reuses_paid_receipts(self):
  import shutil
  from unittest.mock import patch
  from rundale_bench.qualification import collect,PROFILES
  from rundale_bench.accounting import upper_cost as real_upper_cost
  source=Path(__file__).resolve().parents[1]
  with tempfile.TemporaryDirectory() as t:
   root=Path(t)
   for directory in ('review','config'):shutil.copytree(source/directory,root/directory)
   def fake_judge(client,profile,item,rubric,*,grade_order=None):
    if item['id']=='check-3':self.assertEqual(grade_order,[5,4,3,2,1])
    return {'axes':{axis:3 for axis in rubric},'usage':{'input_tokens':100,'output_tokens':10,'cached_input_tokens':0},'raw':{'fixture':True}}
   with patch('rundale_bench.qualification.judge_response',side_effect=fake_judge) as judged, patch('rundale_bench.qualification.upper_cost',wraps=real_upper_cost) as reservations:
    first=collect(root,{},client=object())
    again=collect(root,{},client=object())
    self.assertEqual(judged.call_count,44)
   self.assertTrue(all(call.args[2]==4096 for call in reservations.call_args_list))
   self.assertEqual(first['cost_usd'],again['cost_usd'])
   self.assertEqual(len(first['checks']),6)
   self.assertEqual(len(first['bias_protocol_sha256']),64)
   for pid in PROFILES:self.assertEqual(len(first['bias_diagnostics']['profiles'][pid]['controls']),6)
   contract=root/'output/qualification/contract.json'
   frozen=json.loads(contract.read_text());frozen['bias_protocol_sha256']='changed';contract.write_text(json.dumps(frozen))
   with self.assertRaisesRegex(ValueError,'contract changed'):collect(root,{},client=object())
 def test_opus_collection_reserves_profile_output_limit(self):
  import shutil
  from unittest.mock import patch
  from rundale_bench.qualification import collect
  from rundale_bench.accounting import upper_cost as real_upper_cost
  source=Path(__file__).resolve().parents[1]
  with tempfile.TemporaryDirectory() as t:
   root=Path(t)
   for directory in ('review','config'):shutil.copytree(source/directory,root/directory)
   def fake_judge(client,profile,item,rubric,*,grade_order=None):
    return {'axes':{axis:3 for axis in rubric},'usage':{'input_tokens':100,'output_tokens':10,'cached_input_tokens':0},'raw':{'fixture':True}}
   with patch('rundale_bench.qualification.judge_response',side_effect=fake_judge), patch('rundale_bench.qualification.upper_cost',wraps=real_upper_cost) as reservations:
    receipt=collect(root,{},client=object(),version='3.2',profile_ids=('claude-opus-5-5-judge-high',))
   self.assertEqual(receipt['version'],'3.2')
   self.assertEqual(len(reservations.call_args_list),22)
   self.assertTrue(all(call.args[2]==16384 for call in reservations.call_args_list))
   self.assertTrue((root/'output/qualification/3.2/collection.json').exists())
   self.assertFalse((root/'output/qualification/collection.json').exists())
 def test_provisional_evaluation_refuses_before_writes(self):
  import shutil
  from rundale_bench.qualification import evaluate
  source=Path(__file__).resolve().parents[1]
  for provisional_at in ('status','manifest'):
   with self.subTest(provisional_at=provisional_at), tempfile.TemporaryDirectory() as t:
    root=Path(t)
    shutil.copytree(source/'suites',root/'suites')
    status=root/'qualification/3.0/status.json';status.parent.mkdir(parents=True)
    manifest=root/'suites/3.0/manifest.json'
    if provisional_at=='status':status.write_text('{"status":"provisional"}')
    else:
     data=json.loads(manifest.read_text());data['validation_mode']='provisional';manifest.write_text(json.dumps(data))
    paths=(status,manifest) if status.exists() else (manifest,)
    before={p:p.read_bytes() for p in paths}
    with self.assertRaisesRegex(ValueError,'new benchmark version'):
     evaluate(root,root/'missing-ratings.json')
    self.assertEqual({p:p.read_bytes() for p in before},before)
 def test_explicit_legacy_contract_repair_rejudges_only_changed_jev_request(self):
  import shutil,sqlite3,hashlib
  from unittest.mock import patch
  from rundale_bench.qualification import collect
  source=Path(__file__).resolve().parents[1]
  with tempfile.TemporaryDirectory() as t:
   root=Path(t)
   for directory in ('review','config'):shutil.copytree(source/directory,root/directory)
   def fake_judge(client,profile,item,rubric,*,grade_order=None):
    return {'axes':{axis:3 for axis in rubric},'usage':{'input_tokens':100,'output_tokens':10,'cached_input_tokens':0},'raw':{'fixture':True}}
   with patch('rundale_bench.qualification.judge_response',side_effect=fake_judge) as judged:
    first=collect(root,{},client=object())
    self.assertEqual(judged.call_count,44)
    contract=root/'output/qualification/contract.json';frozen=json.loads(contract.read_text());frozen.pop('adapter_protocols');contract.write_text(json.dumps(frozen))
    pack,rubrics,_=load_review(root);from rundale_bench.providers import load_profiles
    profiles=load_profiles(root/'config/providers.json');check=next(c for c in __import__('rundale_bench.bias',fromlist=['build_checks']).build_checks({i['id']:i for i in pack['items'] if i['category']!='gaeilge'},json.loads((root/'review/split.json').read_text())) if c['id']=='check-3')
    old_request={'profile':profiles['jev-1.13.0'],'item':check['item'],'rubric':rubrics[check['item']['category']],'grade_order':check['grade_order']}
    old_digest=hashlib.sha256(json.dumps(old_request,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    db=sqlite3.connect(root/'output/qualification/ledger.sqlite')
    existing_ids=[row[0] for row in db.execute('select id from calls').fetchall()]
    for index,call_id in enumerate(existing_ids):db.execute('update calls set id=? where id=?',(f'tmp:{index}',call_id))
    for index,call_id in enumerate(existing_ids):
     profile_id,rid=call_id.split(':',2)[:2]
     db.execute('update calls set id=? where id=?',(f'{profile_id}:{rid}',f'tmp:{index}'))
    db.execute('update calls set digest=? where id=?',(old_digest,'jev-1.13.0:check-3'));db.commit();db.close()
    with self.assertRaisesRegex(ValueError,'contract changed'):collect(root,{},client=object())
    repaired=collect(root,{},client=object(),repair_grade_order=True)
    self.assertEqual(judged.call_count,45)
    self.assertGreater(repaired['cost_usd'],first['cost_usd'])
    self.assertEqual(len(repaired['superseded_evidence']),1)
    archives=list((root/'output/qualification/contracts').glob('*.json'));self.assertEqual(len(archives),1)
    db=sqlite3.connect(root/'output/qualification/ledger.sqlite')
    self.assertEqual(db.execute('select cap from meta').fetchone()[0],10)
    self.assertEqual(db.execute('select count(*) from calls').fetchone()[0],45)
    db.close()
    collect(root,{},client=object(),repair_grade_order=True)
    self.assertEqual(judged.call_count,45)
 def test_amended_control_reuses_all_matching_calls_and_only_rejudges_changed_items(self):
  import shutil,sqlite3
  from unittest.mock import patch
  from rundale_bench.qualification import collect
  from rundale_bench.bias import build_checks as real_build_checks
  source=Path(__file__).resolve().parents[1]
  with tempfile.TemporaryDirectory() as t:
   root=Path(t)
   for directory in ('review','config'):shutil.copytree(source/directory,root/directory)
   def fake_judge(client,profile,item,rubric,*,grade_order=None):
    return {'axes':{axis:3 for axis in rubric},'usage':{'input_tokens':100,'output_tokens':10,'cached_input_tokens':0},'raw':{'fixture':True}}
   with patch('rundale_bench.qualification.judge_response',side_effect=fake_judge) as judged:
    initial=collect(root,{},client=object())
    def changed_checks(by_id,split):
     checks=real_build_checks(by_id,split)
     for check in checks:
      if check['id']=='check-5':check['item']['user'] += '\nRevised injection wording.'
     return checks
    with patch('rundale_bench.qualification.build_checks',side_effect=changed_checks):
     with self.assertRaisesRegex(ValueError,'contract changed'):collect(root,{},client=object())
     amended=collect(root,{},client=object(),repair_grade_order=True)
     self.assertEqual(judged.call_count,46)
     self.assertGreater(amended['cost_usd'],initial['cost_usd'])
     archives=list((root/'output/qualification/contracts').glob('*.json'));self.assertEqual(len(archives),1)
     archived=json.loads(archives[0].read_text());self.assertIn('contract',archived);self.assertIn('controls',archived)
     rerun=collect(root,{},client=object(),repair_grade_order=True)
     self.assertEqual(judged.call_count,46)
     self.assertEqual(rerun['cost_usd'],amended['cost_usd'])
    db=sqlite3.connect(root/'output/qualification/ledger.sqlite')
    self.assertEqual(db.execute('select cap from meta').fetchone()[0],10)
    self.assertEqual(db.execute('select count(*) from calls').fetchone()[0],46)
    self.assertAlmostEqual(amended['cost_usd'],db.execute("select coalesce(sum(actual),0) from calls where state='committed'").fetchone()[0])
    db.close()
