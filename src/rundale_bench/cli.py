"""Command line interface for Benchmark 3.0."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

from .providers import load_profiles
from .runner import PACKAGE, dry_run, run, validate_suite
from .storage import rebuild_index, safe_id
from .runner import _load_env
from .scoring import paired_difference


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='rundale-bench')
    sub = p.add_subparsers(dest='command', required=True)
    r = sub.add_parser('run', help='run the fixed 3.0 suite')
    r.add_argument('model')
    r.add_argument('--reasoning')
    r.add_argument('--budget', type=float, default=5.0)
    r.add_argument('--env-file', type=Path)
    r.add_argument('--resume')
    r.add_argument('--dry-run', action='store_true')
    s = sub.add_parser('status', help='show candidate profiles and qualification readiness')
    s.add_argument('--model')
    pub = sub.add_parser('publish', help='rebuild the public results index')
    pub.add_argument('--results', type=Path, default=PACKAGE/'results')
    v = sub.add_parser('validate-suite', help='check suite hashes and case structure')
    q = sub.add_parser('qualify', help='collect or evaluate pinned English judge qualification evidence')
    qs = q.add_subparsers(dest='qualify_command', required=True)
    qc = qs.add_parser('collect', help='run qualification trials using the fixed $10 cap')
    qc.add_argument('--env-file',type=Path)
    qc.add_argument('--amend-controls', '--repair-grade-order', dest='repair_grade_order', action='store_true', help='explicitly amend calibration controls under the same durable $10 ledger; reuse all unchanged paid requests')
    qe = qs.add_parser('evaluate', help='evaluate collected judgments against owner reference ratings')
    qe.add_argument('--ratings',type=Path,required=True)
    qs.add_parser('screen', help='offline automated screening for explicitly provisional scores; no human ratings or paid calls')
    c = sub.add_parser('compare',help='paired case-level comparison of two published runs')
    c.add_argument('left_run_id')
    c.add_argument('right_run_id')
    return p


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == 'run':
            result = run(args.model, reasoning=args.reasoning, budget=args.budget,
                         resume=args.resume, dry=args.dry_run, env_file=args.env_file)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            if args.dry_run:
                return 0 if result.get('valid') and not result.get('problems') and not result.get('blockers') else 1
            return 0 if result.get('status') == 'complete' else 1
        if args.command == 'status':
            report = validate_suite()
            profiles=load_profiles(PACKAGE/'config/providers.json')
            report['profiles'] = list(profiles.values())
            if args.model:
                from .runner import _resolve_candidate
                try: report['selected_profile'] = _resolve_candidate(args.model,None,profiles)
                except ValueError as exc: report['profile_error'] = str(exc)
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 0 if report['valid'] else 1
        if args.command == 'publish':
            report = rebuild_index(args.results)
            print(json.dumps({'published':str(args.results/'index.json'),'versions':len(report['versions'])},indent=2))
            return 0
        if args.command == 'validate-suite':
            report = validate_suite()
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 0 if report['valid'] else 1
        if args.command == 'qualify':
            from .qualification import collect, evaluate
            if args.qualify_command == 'collect':
                receipt=collect(PACKAGE,{**__import__('os').environ,**_load_env(args.env_file)},repair_grade_order=args.repair_grade_order)
            elif args.qualify_command == 'screen':
                from .provisional import screen
                receipt=screen(PACKAGE)
            else:
                receipt=evaluate(PACKAGE,args.ratings)
            print(json.dumps(receipt,indent=2,ensure_ascii=False))
            return 0 if receipt.get('status') in ('collected','qualified','provisional') else 1
        if args.command == 'compare':
            left_id,right_id=safe_id(args.left_run_id),safe_id(args.right_run_id)
            left_path=PACKAGE/'results'/'3.0'/'runs'/(left_id+'.json')
            right_path=PACKAGE/'results'/'3.0'/'runs'/(right_id+'.json')
            left,right=json.loads(left_path.read_text()),json.loads(right_path.read_text())
            def scores(run):
                return {r['case_id']:r['score'] for r in run.get('case_results',[]) if r.get('trial',0)==0 and r.get('score') is not None}
            report={'left_run_id':left_id,'right_run_id':right_id,'left_model':left.get('model'),'right_model':right.get('model'),
                    'comparison':paired_difference(scores(left),scores(right))}
            print(json.dumps(report,indent=2,ensure_ascii=False))
            return 0 if report['comparison']['n'] else 1
    except Exception as exc:
        print(f'rundale-bench: command failed ({type(exc).__name__}); inspect local run or qualification evidence for details.', file=sys.stderr)
        return 2
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
