import tempfile, unittest
from pathlib import Path
from rundale_bench.scoring import rubric_score,objective_score,aggregate,wilson,paired_difference
from rundale_bench.storage import publish_run
class ScoreTests(unittest.TestCase):
 def test_complete_coverage_and_subcategory_weights(self):
  cases=[{'id':'d','eval':'dialogue'},{'id':'m','eval':'multiturn'}]+[{'id':x,'eval':'gaeilge','subcategory':x} for x in ['grammar','meaning','code_switch']]
  rows=[{'case_id':c['id'],'score':100,'trial':0} for c in cases]
  self.assertEqual(aggregate(rows,cases)['overall'],100)
  self.assertIsNone(aggregate(rows[:-1],cases)['overall'])
  self.assertEqual(aggregate(rows+[{'case_id':'d','score':0,'trial':1}],cases)['overall'],100)
 def test_axes_and_exact_keys(self):
  self.assertEqual(rubric_score({'a':3},{'a':{}}),50)
  with self.assertRaises(ValueError):rubric_score({'a':True},{'a':{}})
  with self.assertRaises(ValueError):objective_score('AB',{'type':'choice','expected':'A'})
  with self.assertRaises(ValueError):objective_score('[]',{'type':'exact_json','expected':{'fact':'x'}})
  self.assertEqual(objective_score('B',{'type':'choice','expected':'A'}),0)
  self.assertEqual(objective_score('{"answer":"A"}',{'type':'choice','expected':'A'}),100)
 def test_uncertainty_units(self):
  self.assertIsNone(wilson(0,0));self.assertLess(wilson(0,8)[1],1)
  self.assertEqual(paired_difference({'conversation1':80},{'conversation1':60})['n'],1)
class StorageTests(unittest.TestCase):
 def test_latest_cause_and_immutable_evidence(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);run={'version':'3.0','run_id':'a','model':'native-model','reasoning':'high','status':'complete','overall':70,'scores':{},'completed_at':'2026-10-01','cost_usd':1}
   publish_run(root,run)
   for rid,cause,date in [('b','budget','2026-10-02'),('c','unknown','2026-10-03')]:
    publish_run(root,{**run,'run_id':rid,'failure_cause':cause,'status':'dnf','overall':None,'completed_at':date})
   import json
   row=json.loads((root/'index.json').read_text())['versions'][0]['rows'][0]
   self.assertEqual(row['run_id'],'a');self.assertEqual(row['latest_attempt_id'],'c')
   publish_run(root,{**run,'run_id':'d','failure_cause':'model','status':'dnf','overall':None,'completed_at':'2026-10-04'})
   row=json.loads((root/'index.json').read_text())['versions'][0]['rows'][0];self.assertEqual(row['run_id'],'d');self.assertIsNone(row['overall'])
   with self.assertRaises(ValueError):publish_run(root,{**run,'overall':99})
