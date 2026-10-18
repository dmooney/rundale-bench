import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from rundale_bench.publication import file_failure_issue
class PublicationTests(unittest.TestCase):
 def test_dnf_issue_deduplicates_without_reposting(self):
  run={'version':'3.0','run_id':'run1','model':'model','reasoning':'high','failure_cause':'model','errors':[{'kind':'npc_contract'}],'reason':'Repeated invalid output'}
  with tempfile.TemporaryDirectory() as t,patch('rundale_bench.publication.gh',return_value=json.dumps([{'number':2,'url':'https://github.com/dmooney/rundale-bench/issues/2'}])) as mocked:
   result=file_failure_issue(Path(t),run)
   self.assertEqual(result['status'],'existing');self.assertEqual(mocked.call_count,1)
   self.assertTrue((Path(t)/'output/run1/issue.json').exists())
 def test_failed_issue_filing_is_never_claimed_complete(self):
  run={'version':'3.0','run_id':'run1','model':'model','reasoning':None,'failure_cause':'unknown','reason':'Uncertain billing'}
  with tempfile.TemporaryDirectory() as t,patch('rundale_bench.publication.gh',side_effect=OSError('network')):
   self.assertEqual(file_failure_issue(Path(t),run)['status'],'filing_unconfirmed')
