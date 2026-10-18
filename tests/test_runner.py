import hashlib, json, tempfile, unittest
import contextlib, io
from pathlib import Path
from unittest.mock import patch

from rundale_bench.runner import run, dry_run, validate_suite
from rundale_bench.accounting import Ledger, upper_cost


def fixture(root):
    (root/'config').mkdir(); (root/'suites'/'3.0').mkdir(parents=True)
    (root/'results').mkdir()
    profile={'id':'fake-high','provider':'openai','model':'fake','reasoning':'high','supported_reasoning':['high'],
             'input_per_million_usd':1.0,'output_per_million_usd':1.0,'cached_input_per_million_usd':0.0,'api_key_env':'FAKE_KEY'}
    (root/'config'/'providers.json').write_text(json.dumps({'profiles':[profile]}))
    cases=[
        {'id':'d','eval':'dialogue','messages':[{'role':'user','content':'say hi'}],'max_output_tokens':20},
        {'id':'m','eval':'multiturn','system':'role','initial_context':'Captured exchange from the pinned scene.','turns':['one','two','three','four','five','six'],'max_output_tokens':20},
        *[{'id':group+str(i),'eval':'gaeilge','subcategory':group,'messages':[{'role':'user','content':'choose'}],'max_output_tokens':20,'answer':{'type':'choice','expected':'A'}} for group in ('grammar','meaning','code_switch') for i in range(8)],
    ]
    cp=root/'suites'/'3.0'/'cases.jsonl'; cp.write_text(''.join(json.dumps(x)+'\n' for x in cases))
    rubric={'dialogue':{'voice':{'anchors':{str(i):str(i) for i in range(1,6)}}},'multiturn':{'memory':{'anchors':{str(i):str(i) for i in range(1,6)}}}}
    rp=root/'suites'/'3.0'/'rubrics.json'; rp.write_text(json.dumps(rubric))
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    manifest={'version':'3.0','status':'ready','cases_sha256':digest(cp),'rubrics_sha256':digest(rp),'counts':{'dialogue':1,'multiturn':1,'gaeilge':24},'repeat_ids':[],
              'judge_policy':{'dialogue':'fake-high','multiturn':'fake-high'},'judge_profiles':{'fake-high':profile},'engine':{'capture_sha256':'abc','commit':'deadbeef'}}
    mp=root/'suites'/'3.0'/'manifest.json'; mp.write_text(json.dumps(manifest))
    sh=digest(mp)
    q={'status':'qualified','suite_hash':sh,'judges':{k:{'profile_id':'fake-high','qualified':True} for k in ('dialogue','multiturn')}}
    (root/'qualification'/'3.0').mkdir(parents=True); (root/'qualification'/'3.0'/'status.json').write_text(json.dumps(q))
    return cases,profile


def rehash(root):
    base=root/'suites'/'3.0'; cp=base/'cases.jsonl'; rp=base/'rubrics.json'; mp=base/'manifest.json'
    manifest=json.loads(mp.read_text())
    manifest['cases_sha256']=hashlib.sha256(cp.read_bytes()).hexdigest()
    manifest['rubrics_sha256']=hashlib.sha256(rp.read_bytes()).hexdigest()
    mp.write_text(json.dumps(manifest))
    q=root/'qualification'/'3.0'/'status.json'; receipt=json.loads(q.read_text())
    receipt['suite_hash']=hashlib.sha256(mp.read_bytes()).hexdigest(); q.write_text(json.dumps(receipt))


class FakeClient:
    def __init__(self, fail_at=None, fail_kind='malformed', failures=None): self.calls=0; self.fail_at=fail_at; self.fail_kind=fail_kind; self.failures=failures or {}
    def generate(self, profile, messages, max_output_tokens, response_schema=None):
        from rundale_bench.providers import ProviderResponse, ProviderError
        self.calls += 1
        kind=self.failures.get(self.calls,self.fail_kind if self.calls==self.fail_at else None)
        if kind: raise ProviderError('bad output',kind=kind,billing_uncertain=False)
        text='A' if messages[-1]['content']=='choose' else f'reply {self.calls}'
        return ProviderResponse(text,{'input_tokens':5,'cached_input_tokens':0,'output_tokens':3,'reasoning_tokens':0},'fake',1,None,{'safe':True})


class RunnerTests(unittest.TestCase):
    def test_full_run_and_resume_reuses_paid_calls(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); fixture(root); client=FakeClient()
            def judge(_client, _profile, item, _rubric):
                axis='voice' if item['eval']=='dialogue' else 'memory'
                return {'axes':{axis:4},'usage':{'input_tokens':2,'cached_input_tokens':0,'output_tokens':1,'reasoning_tokens':0},'raw':{'ok':True}}
            with patch('rundale_bench.runner.judge_response',side_effect=judge):
                result=run('fake',root=root,output=root/'output',budget=5,client=client,run_id='x')
            self.assertEqual(result['status'],'complete'); self.assertAlmostEqual(result['overall'],250/3)
            before=client.calls
            again=run('fake',root=root,output=root/'output',budget=5,client=client,resume='x')
            self.assertEqual(again['status'],'complete'); self.assertEqual(client.calls,before)
            self.assertEqual(result['coverage']['multiturn'],{'completed':1,'required':1})
            self.assertIsNone(result['uncertainty']['gaeilge']['accuracy']['interval_95'])
            self.assertIsNotNone(result['uncertainty']['gaeilge']['subcategories']['grammar']['interval_95'])
            final_turn=next(x['request']['messages'] for x in result['requests'] if x['id']=='m:0:candidate:5')
            self.assertIn('Captured initial scene context',final_turn[1]['content'])
            self.assertEqual(sum(m['role']=='user' for m in final_turn),6)
            self.assertEqual(sum(m['role']=='assistant' for m in final_turn),5)

    def test_budget_failure_is_persisted_before_request(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); fixture(root); client=FakeClient()
            result=run('fake',root=root,output=root/'output',budget=.000001,client=client,run_id='budget')
            self.assertEqual(result['status'],'dnf'); self.assertEqual(result['failure_cause'],'budget')
            self.assertEqual(client.calls,0)
            self.assertTrue((root/'output'/'budget'/'run.json').exists())

    def test_dry_run_needs_no_credentials(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); fixture(root)
            report=dry_run('fake',root=root,budget=5)
            self.assertTrue(report['valid']); self.assertFalse(any('credential' in x.lower() for x in report['blockers']))
            nan_report=dry_run('fake',root=root,budget=float('nan'))
            self.assertTrue(any('Budget' in x for x in nan_report['blockers']))

    def test_cli_dry_run_returns_nonzero_for_readiness_blockers(self):
        from rundale_bench import cli
        with patch('rundale_bench.cli.run',return_value={'valid':True,'problems':[],'blockers':['qualification pending']}):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(['run','fake','--dry-run']),1)

    def test_qualification_and_compare_cli_dispatch(self):
        from rundale_bench import cli
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); cli.PACKAGE=root
            for rid,score in [('left',70),('right',50)]:
                path=root/'results'/'3.0'/'runs'/(rid+'.json'); path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text(json.dumps({'run_id':rid,'model':rid,'case_results':[{'case_id':'c1','trial':0,'score':score}]}))
            with patch('rundale_bench.qualification.collect',return_value={'status':'collected'}):
                with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(cli.main(['qualify','collect']),0)
            with patch('rundale_bench.qualification.evaluate',return_value={'status':'qualified'}):
                with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(cli.main(['qualify','evaluate','--ratings','ratings.json']),0)
            capture=io.StringIO()
            with contextlib.redirect_stdout(capture): self.assertEqual(cli.main(['compare','left','right']),0)
            self.assertIn('mean_difference',capture.getvalue())

    def test_qualification_mismatch_blocks_paid_call(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); fixture(root); q=root/'qualification'/'3.0'/'status.json'; q.write_text('{"status":"pending"}')
            client=FakeClient()
            with self.assertRaisesRegex(ValueError,'Paid launch blocked'):
                run('fake',root=root,client=client)
            self.assertEqual(client.calls,0)

    def test_new_candidate_profile_does_not_require_freezing_registry(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); fixture(root)
            registry=json.loads((root/'config'/'providers.json').read_text())
            registry['profiles'].append({**registry['profiles'][0],'id':'new-model-profile','model':'new-model'})
            (root/'config'/'providers.json').write_text(json.dumps(registry))
            client=FakeClient()
            def judge(_client,_profile,item,_rubric):
                axis='voice' if item['eval']=='dialogue' else 'memory'
                return {'axes':{axis:4},'usage':{'input_tokens':2,'cached_input_tokens':0,'output_tokens':1,'reasoning_tokens':0},'raw':{'ok':True}}
            with patch('rundale_bench.runner.judge_response',side_effect=judge):
                result=run('new-model',root=root,output=root/'output',budget=5,client=client,run_id='new-model')
            self.assertEqual(result['status'],'complete')
            self.assertEqual(result['candidate_profile']['id'],'new-model-profile')
            self.assertEqual(result['judge_profiles']['fake-high']['id'],'fake-high')

    def test_changed_pinned_judge_profile_blocks_before_candidate_call(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); fixture(root)
            registry=json.loads((root/'config'/'providers.json').read_text())
            registry['profiles'][0]['output_per_million_usd']=2.0
            (root/'config'/'providers.json').write_text(json.dumps(registry))
            client=FakeClient()
            with self.assertRaisesRegex(ValueError,'profile differs from its manifest snapshot'):
                run('fake',root=root,client=client)
            self.assertEqual(client.calls,0)

    def test_paid_budget_is_validated_before_any_call(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); fixture(root); client=FakeClient()
            for cap in (0,-1,5.01,float('inf')):
                with self.assertRaises(ValueError): run('fake',root=root,client=client,budget=cap)
            self.assertEqual(client.calls,0)

    def test_provider_rate_error_is_infrastructure_not_model_zero(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); fixture(root); client=FakeClient(fail_at=1,fail_kind='provider')
            result=run('fake',root=root,output=root/'output',budget=5,client=client,run_id='rate')
            self.assertEqual(result['status'],'dnf'); self.assertEqual(result['failure_cause'],'infrastructure')
            self.assertEqual(client.calls,1)

    def test_single_refusal_is_one_model_failure_and_skips_npc_contract_parse(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); cases,_=fixture(root)
            cases[0]['messages'].insert(0,{'role':'system','content':'You MUST respond with a JSON object.'})
            cp=root/'suites'/'3.0'/'cases.jsonl'; cp.write_text(''.join(json.dumps(c)+'\n' for c in cases)); rehash(root)
            def judge(_client,_profile,item,_rubric):
                axis='voice' if item['eval']=='dialogue' else 'memory'
                return {'axes':{axis:4},'usage':{'input_tokens':2,'cached_input_tokens':0,'output_tokens':1,'reasoning_tokens':0},'raw':{'ok':True}}
            with patch('rundale_bench.runner.judge_response',side_effect=judge):
                result=run('fake',root=root,output=root/'output',budget=5,client=FakeClient(fail_at=1,fail_kind='provider_refusal'),run_id='one-refusal')
            self.assertEqual(result['status'],'complete'); self.assertEqual(result['failure_events'],1)
            self.assertEqual([e['kind'] for e in result['errors']],['provider_refusal'])

    def test_refusal_then_refusal_is_second_combined_failure(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); cases,_=fixture(root)
            cases[0]['messages'].insert(0,{'role':'system','content':'You MUST respond with a JSON object.'})
            cp=root/'suites'/'3.0'/'cases.jsonl'; cp.write_text(''.join(json.dumps(c)+'\n' for c in cases)); rehash(root)
            result=run('fake',root=root,output=root/'output',budget=5,
                       client=FakeClient(failures={1:'provider_refusal',2:'provider_refusal'}),run_id='two-refusals')
            self.assertEqual(result['status'],'dnf'); self.assertEqual(result['failure_events'],2)
            self.assertEqual(sum(e['kind']=='npc_contract' for e in result['errors']),0)

    def test_budget_stop_keeps_completed_eval_score_and_coverage(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); fixture(root)
            def judge(_client,_profile,item,_rubric):
                axis='voice' if item['eval']=='dialogue' else 'memory'
                return {'axes':{axis:4},'usage':{'input_tokens':2,'cached_input_tokens':0,'output_tokens':1,'reasoning_tokens':0},'raw':{'ok':True}}
            with patch('rundale_bench.runner.judge_response',side_effect=judge):
                result=run('fake',root=root,output=root/'output',budget=.05,client=FakeClient(),run_id='partial-budget')
            self.assertEqual(result['status'],'dnf'); self.assertEqual(result['failure_cause'],'budget')
            self.assertEqual(result['scores']['dialogue'],75)
            self.assertEqual(result['coverage']['dialogue'],{'completed':1,'required':1})
            self.assertIsNone(result['overall'])
            self.assertEqual(result['budget_usd'],.05)
            self.assertEqual(result['budget_status'],'cap_reached')
            self.assertGreater(result['spending_exposure_usd'],0)
            self.assertIn('pinned profile rates',result['actual_cost_basis'])

    def test_two_malformed_npc_contract_outputs_stop_run(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); cases,_=fixture(root)
            cases[0]['messages'].insert(0,{'role':'system','content':'You MUST respond with a JSON object.'})
            cases[1]['system']='You MUST respond with a JSON object.'
            cp=root/'suites'/'3.0'/'cases.jsonl'; cp.write_text(''.join(json.dumps(c)+'\n' for c in cases)); rehash(root)
            result=run('fake',root=root,output=root/'output',budget=5,client=FakeClient(),run_id='malformed')
            self.assertEqual(result['status'],'dnf'); self.assertEqual(result['failure_cause'],'model')
            self.assertEqual(result['failure_events'],2)
            self.assertEqual(sum(e['kind']=='npc_contract' for e in result['errors']),2)

    def test_committed_call_before_checkpoint_is_recovered_on_resume(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); cases,profile=fixture(root); output=root/'output'; work=output/'crash'
            req={'profile':profile['id'],'messages':cases[0]['messages'],'max_output_tokens':cases[0]['max_output_tokens']}
            record={'text':'A reply','usage':{'input_tokens':5,'cached_input_tokens':0,'output_tokens':3,'reasoning_tokens':0},'model':'fake','elapsed_ms':1,'ttft_ms':None,'raw':{'saved':True}}
            ledger=Ledger(work/'ledger.sqlite',5)
            ledger.reserve('d:0:candidate:0',req,upper_cost(profile,req['messages'],req['max_output_tokens']))
            from rundale_bench.accounting import actual_cost
            ledger.commit('d:0:candidate:0',record,actual_cost(profile,record['usage'])); ledger.close()
            result=run('fake',root=root,output=output,budget=5,client=FakeClient(),resume='crash')
            recovered=next(x for x in result['requests'] if x['id']=='d:0:candidate:0')
            self.assertEqual(recovered['response']['raw'],{'saved':True})


if __name__ == '__main__': unittest.main()

class PerformanceTests(unittest.TestCase):
    def test_timings_use_actual_generation_records_and_keep_unavailable_ttft_null(self):
        from rundale_bench.runner import _performance_summary
        records=[{'elapsed_ms':x,'ttft_ms':None} for x in (100,200,300,400)]
        out=_performance_summary([{'case_id':'m1','trial':0,'eval':'multiturn','score':75,'response_records':records}],[{'id':'m1','eval':'multiturn'}])
        self.assertEqual(out['multiturn']['latency_ms']['p50'],200)
        self.assertEqual(out['multiturn']['latency_ms']['p95'],400)
        self.assertEqual(out['multiturn']['ttft_ms']['n'],0)
        self.assertIsNone(out['multiturn']['ttft_ms']['p95'])
