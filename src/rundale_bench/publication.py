"""GitHub publication stays reviewable; only the independent gatekeeper merges."""
from __future__ import annotations
import json
import subprocess
import tempfile
from pathlib import Path
from .storage import issue_payload, atomic_json

REPOSITORY = 'dmooney/rundale-bench'

def gh(arguments:list[str], root:Path) -> str:
    return subprocess.run(['gh',*arguments],cwd=root,text=True,check=True,capture_output=True).stdout

def file_failure_issue(root:Path, run:dict, execute:bool=True) -> dict:
    issue=issue_payload(run)
    receipt=root/'output'/run['run_id']/'issue.json'
    if not execute:
        atomic_json(receipt,{**issue,'status':'prepared'});return {**issue,'status':'prepared'}
    try:
        found=json.loads(gh(['issue','list','--repo',REPOSITORY,'--state','all','--search',f'"benchmark-dnf:{issue["fingerprint"]}" in:body','--json','number,url'],root))
        if found:
            result={**issue,'status':'existing','url':found[0]['url']}
        else:
            with tempfile.NamedTemporaryFile('w',suffix='.md',delete=False) as body:
                body.write(issue['body']);name=body.name
            try:
                url=gh(['issue','create','--repo',REPOSITORY,'--title',issue['title'],'--body-file',name],root).strip()
            finally:
                Path(name).unlink(missing_ok=True)
            result={**issue,'status':'filed','url':url}
    except (subprocess.SubprocessError,OSError,json.JSONDecodeError):
        result={**issue,'status':'filing_unconfirmed','reason':'GitHub issue creation could not be confirmed; prepared evidence remains local.'}
    atomic_json(receipt,result)
    return result

def publish_results_pr(root:Path) -> str:
    # A public run can contain arbitrary NPC text. Pass PR prose as a file, never
    # interpolate it into shell code. Run IDs and branch names remain machine-owned.
    changed=subprocess.run(['git','status','--porcelain','--','results'],cwd=root,text=True,check=True,capture_output=True).stdout
    if not changed.strip():raise ValueError('No new public results to publish')
    status=subprocess.run(['git','status','--porcelain'],cwd=root,text=True,check=True,capture_output=True).stdout
    if any(line[3:].split('/')[0]!='results' for line in status.splitlines()):
        raise ValueError('Publish from a clean checkout with only results changes')
    # Enforce the same offline gates used by CI before creating a reviewable PR.
    import sys
    subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-q'],cwd=root,check=True)
    subprocess.run([sys.executable,'-m','rundale_bench.cli','validate-suite'],cwd=root,check=True,capture_output=True)
    from datetime import datetime,timezone
    branch='results/'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
    for command in [['git','switch','-c',branch],['git','add','--','results'],['git','commit','-m','chore: publish benchmark run evidence'],['git','push','-u','origin',branch]]:
        subprocess.run(command,cwd=root,text=True,check=True,capture_output=True)
    body='Publish immutable benchmark evidence and update the cause-aware latest-result index. Raw requests, responses, judgments, costs, coverage, and any DNF reason are retained.\n\nValidation: the suite validation and offline Python tests passed before this PR was created. Independent gatekeeper review is required before merge and site deployment.\n'
    with tempfile.NamedTemporaryFile('w',suffix='.md',delete=False) as handle:
        handle.write(body);name=handle.name
    try:
        return gh(['pr','create','--repo',REPOSITORY,'--base','main','--head',branch,'--title','chore: publish benchmark run evidence','--body-file',name],root).strip()
    finally:Path(name).unlink(missing_ok=True)
