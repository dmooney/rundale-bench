import tempfile
import unittest
from pathlib import Path
from rundale_bench.accounting import Ledger,BudgetError,UncertainBilling,actual_cost

class AccountingTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'ledger.sqlite';self.l=Ledger(self.path,5)
 def tearDown(self):self.l.close();self.tmp.cleanup()
 def test_reserve_includes_judging(self):
  with self.assertRaises(BudgetError):self.l.reserve('x',{},4,2)
  self.assertEqual(self.l.exposure,0)
 def test_resume_reuses_committed_and_rejects_changed_request(self):
  self.l.reserve('x',{'question':'a'},2);self.l.commit('x',{'text':'yes'},1)
  self.assertEqual(self.l.cached('x',{'question':'a'}),{'text':'yes'})
  with self.assertRaises(BudgetError):self.l.cached('x',{'question':'b'})
 def test_crash_or_timeout_blocks_billing(self):
  self.l.reserve('x',{},2)
  with self.assertRaises(UncertainBilling):self.l.cached('x',{})
  self.l.fail('x',True)
  with self.assertRaises(UncertainBilling):self.l.reserve('y',{},1)
 def test_cached_and_reasoning_not_double_charged(self):
  p={'input_per_million_usd':2,'output_per_million_usd':10,'cached_input_per_million_usd':.1}
  self.assertAlmostEqual(actual_cost(p,{'input_tokens':1000,'cached_input_tokens':500,'output_tokens':100,'reasoning_tokens':80}),.00205)
 def test_missing_usage_and_unknown_price_not_free(self):
  with self.assertRaises(UncertainBilling):actual_cost({'input_per_million_usd':2,'output_per_million_usd':10},{})
  with self.assertRaises(BudgetError):actual_cost({'input_per_million_usd':None,'output_per_million_usd':0},{'input_tokens':1,'output_tokens':0})
 def test_resume_cannot_expand_cap(self):
  with self.assertRaises(BudgetError):Ledger(self.path,10)
