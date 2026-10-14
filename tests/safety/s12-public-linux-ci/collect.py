#!/usr/bin/env python3
"""Inactive public-only collector. No harness/initializer import or effects on import."""
from pathlib import Path,PurePosixPath
import hashlib,io,json,os,re,shutil,signal,stat,sys,tarfile,tempfile
sys.dont_write_bytecode=True
RUN_AUTHORIZED=True
REPO='meser-recovery/starter-package'
REPO_ID='1097646215'
BASE_SHA='80e44321653491ffecd1d9407583809f48c877f4'
BRANCH_PREFIX='codex/s12-public-linux-ci-r1/'
WORKFLOW='.github/workflows/safety-baseline.yml'
WORKFLOW_ID=347881817
ARCHIVE_SHA='a9d2251edcb6b96695eb15511f4bf36e55e9365b53de036c1c53637f52214083'
INSPECTOR_SHA='fdcc0e1118f97c760af59459150f5fe11e60db7e68f8f707f9ba81dd1e1540e7'
PREFIX='S12-PUBLIC-LINUX-HARNESS-R1-20261014/'
RUNTIME={
 'scripts/linux-supervisor-regressions.py':'05b0342f8b77817415a06d09b2db334979b62ed56414335278fb75a59adece00',
 'scripts/common.py':'d8943a4dfb4af0a8033a2cb8d8ae9275812ab3e1b1bd4e33c37a92ea1c967373',
 'scripts/owned-supervisor.py':'307bf48b8da626b23606865d6618994ad383de37f938075718cd3928bb54986a',
 'operator-copy/deploy/s10a/s12_recovery.py':'fd50b2990e4df84e30be9553eed1e297e00a652554eb582aa2ada0e371997984',
 'manifest.json':hashlib.sha256(b'{"paths":{}}\n').hexdigest(),
 'planned-inputs/bindings.json':hashlib.sha256(b'{"approved":false}\n').hexdigest(),
}
class Refused(ValueError):pass
def need(x,code):
 if not x:raise Refused(code)
def digest(b):return hashlib.sha256(b).hexdigest()
def unique(rows):
 out={}
 for k,v in rows:need(k not in out,'DUPLICATE_FIELD');out[k]=v
 return out
def validate_context(c):
 need(set(c)=={'repository','repository_id','event','ref','sha','workflow_sha','workflow_ref','run_id','run_attempt','runner_os','runner_arch','runner_environment'},'CONTEXT_SCHEMA_REFUSED')
 need(c['repository']==REPO and c['repository_id']==REPO_ID and c['event']=='workflow_dispatch','CONTEXT_REPO_EVENT_REFUSED')
 need(isinstance(c['ref'],str) and re.fullmatch('refs/heads/'+BRANCH_PREFIX+'[0-9a-f]{40}',c['ref']),'REF_REFUSED')
 need(re.fullmatch('[0-9a-f]{40}',c['sha']) and c['workflow_sha']==c['sha'] and c['workflow_ref']==REPO+'/'+WORKFLOW+'@'+c['ref'],'WORKFLOW_SHA_REFUSED')
 need(re.fullmatch('[1-9][0-9]{0,19}',c['run_id']) and c['run_attempt']=='1','RERUN_REFUSED')
 need((c['runner_os'],c['runner_arch'],c['runner_environment'])==('Linux','X64','github-hosted'),'RUNNER_REFUSED')
 return c['ref'].rsplit('/',1)[1]
def inspect_archive(raw,expected_sha=ARCHIVE_SHA,runtime=RUNTIME):
 need(digest(raw)==expected_sha and len(raw)<=200000,'ARCHIVE_PIN_REFUSED')
 with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as t:
  members=t.getmembers();need(len(members)==9 and len({m.name for m in members})==9,'MEMBERSHIP_REFUSED')
  need(all(m.isfile() and m.name.startswith(PREFIX) and not PurePosixPath(m.name).is_absolute() and '..' not in PurePosixPath(m.name).parts and 0<m.size<=100000 for m in members),'UNSAFE_ARCHIVE_MEMBER')
  data={m.name[len(PREFIX):]:t.extractfile(m).read() for m in members}
 need(set(data)==set(runtime)|{'README.md','SOURCE-LOCKS.json','SHA256SUMS'},'MEMBERSHIP_REFUSED')
 sums={}
 for row in data['SHA256SUMS'].decode('ascii').splitlines():
  h,sep,n=row.partition('  ');need(sep and re.fullmatch('[0-9a-f]{64}',h) and n not in sums and n in data and n!='SHA256SUMS','COVERAGE_REFUSED');sums[n]=h
 need(set(sums)==set(data)-{'SHA256SUMS'},'COVERAGE_REFUSED')
 need(all(digest(data[n])==h for n,h in sums.items()),'PAYLOAD_CHECKSUM_REFUSED')
 need(all(digest(data[n])==h for n,h in runtime.items()),'RUNTIME_PIN_REFUSED')
 locks=json.loads(data['SOURCE-LOCKS.json'],object_pairs_hook=unique)
 need(locks['code_or_guards_changed'] is False and locks['original_code_sha256']=={n:h for n,h in runtime.items() if n.endswith('.py')},'SOURCE_LOCKS_REFUSED')
 need(data['manifest.json']==b'{"paths":{}}\n' and data['planned-inputs/bindings.json']==b'{"approved":false}\n','PUBLIC_PROFILE_REFUSED')
 return {n:data[n] for n in runtime}
def safe_report(raw):
 need(len(raw)<=16384,'REPORT_TOO_LARGE');r=json.loads(raw,object_pairs_hook=unique)
 keys={'status','live_linux_cases','results','root_or_privileged_setup','production_Docker_mount_credentials_or_enabled_stages','forced_kills','public_fixtures_removed'}
 need(type(r) is dict and set(r)==keys,'HARNESS_REPORT_REFUSED')
 expected=['normal command; kernel ECHILD proof','leader-exit-orphan; separate-session child accounted for; no false cleanup','setsid-timeout; separate-session child accounted for; no false cleanup','ignored-SIGTERM; separate-session child accounted for; no false cleanup','nested common.run supervisors; whole owned tree reaped','SIGTERM to caller forwarded; owned descendants confirmed stopped','unrelated sibling never signalled']
 need(r['status']=='PASS' and type(r['live_linux_cases']) is int and r['live_linux_cases']==7 and r['results']==expected,'HARNESS_NOT_PASS')
 need(r['root_or_privileged_setup'] is r['production_Docker_mount_credentials_or_enabled_stages'] is r['forced_kills'] is False and r['public_fixtures_removed'] is True,'HARNESS_CLEANUP_UNCONFIRMED')
 return r

_SUPPORT_ATTESTATION=object()
class VerifiedSetupRefusal(Exception):
 def __init__(self,exit_code,origin,primitive,proof,pins,seal):
  need(seal is _SUPPORT_ATTESTATION,'UNVERIFIED_SUPPORT_REFUSAL')
  self.exit_code=exit_code;self.origin=origin;self.primitive=primitive
  self.proof_identity=proof;self.proof_snapshot=dict(proof);self.pins=dict(pins);self.seal=seal

def required_api_support(os_api=os,signal_api=signal):
 return callable(getattr(os_api,'pidfd_open',None)) and callable(getattr(signal_api,'pidfd_send_signal',None))

def verified_completion_proof(state):
 p=state.get('proof')
 keys={'version','supervisor_pid','child_started','dispatch_attempted','supervision_ready','tree_empty_confirmed','command_returncode','stop_reason','signalled_children','adopted_children_reaped','error_code'}
 return (type(p) is dict and set(p)==keys and type(p['version']) is int and p['version']==1
   and type(p['supervisor_pid']) is int and p['supervisor_pid']>0
   and all(type(p[k]) is bool for k in ('child_started','dispatch_attempted','supervision_ready','tree_empty_confirmed'))
   and p['tree_empty_confirmed'] is True and state.get('unconfirmed_group') is None
   and state.get('retained_paths')==[] and (p['command_returncode'] is None or type(p['command_returncode']) is int)
   and (p['error_code'] is None or type(p['error_code']) is str) and (p['stop_reason'] is None or type(p['stop_reason']) is str)
   and all(type(p[k]) is int and p[k]>=0 for k in ('signalled_children','adopted_children_reaped')))

def support_origin(proof):
 if proof['stop_reason'] is not None:return None
 if (proof['child_started'] and proof['dispatch_attempted'] and proof['supervision_ready']
     and type(proof['command_returncode']) is int and proof['command_returncode'] in (77,78)
     and proof['error_code'] is None and proof['signalled_children']==proof['adopted_children_reaped']==0):return 'IMMUTABLE_HARNESS_PRETEST'
 if (proof['child_started'] is proof['dispatch_attempted'] is proof['supervision_ready'] is False
     and proof['command_returncode'] is None and proof['error_code']=='SUPERVISION_UNAVAILABLE_BEFORE_DISPATCH'
     and proof['signalled_children']==proof['adopted_children_reaped']==0):return 'IMMUTABLE_SUPERVISOR_SETUP'
 return None

def runtime_matches(work,pins):
 return all(digest((work/n).read_bytes())==h for n,h in pins.items())

def invoke_verified_harness(primitive,work,env,runtime=RUNTIME):
 """Typed refusal bridge for this ONE immutable command. Never resets old guards/state."""
 need(runtime_matches(work,runtime),'IMMUTABLE_RUNTIME_CHANGED')
 state=primitive.PROCESS_STATE
 need(state.get('proof') is None and state.get('unconfirmed_group') is None and state.get('retained_paths')==[],'STALE_SUPERVISOR_STATE')
 try:
  result=primitive.run([sys.executable,'-B',str(work/'scripts/linux-supervisor-regressions.py')],timeout=120,stop_grace=15,env=env)
 except Exception as error:
  state=primitive.PROCESS_STATE
  if not verified_completion_proof(state):raise Refused('SUPERVISOR_PROOF_UNCONFIRMED') from None
  need(runtime_matches(work,runtime),'IMMUTABLE_RUNTIME_CHANGED')
  proof=state['proof'];origin=support_origin(proof)
  exact_error=(type(error) is ValueError and ((origin=='IMMUTABLE_HARNESS_PRETEST' and str(error)=='SUBPROCESS_FAILED') or (origin=='IMMUTABLE_SUPERVISOR_SETUP' and str(error)=='SUPERVISION_UNAVAILABLE_BEFORE_DISPATCH')))
  if exact_error:
   code=proof['command_returncode'] if origin=='IMMUTABLE_HARNESS_PRETEST' else 78
   raise VerifiedSetupRefusal(code,origin,primitive,proof,runtime,_SUPPORT_ATTESTATION) from None
  if type(error) is ValueError and str(error)=='CHILD_OPERATION_INTERRUPTED_OR_TIMED_OUT':raise Refused('HARNESS_INTERRUPTED_OR_TIMED_OUT') from None
  raise Refused('HARNESS_COMMAND_FAILED') from None
 need(verified_completion_proof(primitive.PROCESS_STATE) and primitive.PROCESS_STATE['proof']['command_returncode']==0 and primitive.PROCESS_STATE['proof']['error_code'] is None and primitive.PROCESS_STATE['proof']['stop_reason'] is None and all(primitive.PROCESS_STATE['proof'][k] is True for k in ('child_started','dispatch_attempted','supervision_ready')),'SUPERVISOR_PROOF_UNCONFIRMED')
 need(runtime_matches(work,runtime),'IMMUTABLE_RUNTIME_CHANGED');return result

def support_refusal_current(refusal,primitive,pins):
 state=primitive.PROCESS_STATE
 return (type(refusal) is VerifiedSetupRefusal and refusal.seal is _SUPPORT_ATTESTATION
   and refusal.primitive is primitive and refusal.pins==pins and verified_completion_proof(state)
   and state['proof'] is refusal.proof_identity and state['proof']==refusal.proof_snapshot
   and support_origin(state['proof'])==refusal.origin)

def collect_once(c,raw,fx,expected_sha=ARCHIVE_SHA,runtime=RUNTIME):
 """New lifecycle with explicit injected effects; production constructor remains disabled."""
 tree=validate_context(c)
 r={'schema':'s12-public-linux-proof-v1','status':'FAILED','exit_status':1,'source':{'repository':REPO,'workflow_id':WORKFLOW_ID,'workflow_ref':c['workflow_ref'],'workflow_sha':c['workflow_sha'],'commit_sha':c['sha'],'tree_sha':tree,'run_id':c['run_id'],'run_attempt':1,'archive_sha256':expected_sha,'inspector_sha256':INSPECTOR_SHA,'runtime_files_sha256':dict(runtime)},'kernel_live':'NOT RUN','owned_tree':'NOT_STARTED','fixture_cleanup':'NOT_RUN','runtime_cleanup':'NOT_CREATED','code':'NOT_COMPLETED'}
 work=None;dispatched=False;support_refusal=None;support_verified=False
 try:
  files=inspect_archive(raw,expected_sha,runtime)
  need(fx.checkout_binding(c['sha'],tree,BASE_SHA) is True,'CHECKOUT_BINDING_REFUSED')
  work=fx.stage(files)
  probe=fx.prerequisites()
  if probe!='SUPPORTED':r.update(status='BLOCKED',exit_status=78,code='PREREQUISITES_UNSUPPORTED');return r
  dispatched=True
  output=fx.execute(work)
  need(fx.tree_complete() is True,'OWNED_TREE_UNCONFIRMED')
  need(fx.fixtures_empty(work) is True,'PUBLIC_FIXTURES_REMAIN')
  need(fx.runtime_unchanged(work,runtime) is True,'RUNTIME_CHANGED')
  r['harness']=safe_report(output);r.update(kernel_live='PENDING_COMPLETION',owned_tree='CONFIRMED',fixture_cleanup='PASS',code='PENDING_CLEANUP')
 except VerifiedSetupRefusal as ex:
  support_refusal=ex;r['code']='VERIFIED_SETUP_REFUSAL_PENDING_CLEANUP'
 except Exception as ex:
  r['code']=str(ex) if isinstance(ex,Refused) and re.fullmatch('[A-Z0-9_]+',str(ex)) else 'OPERATION_FAILED'
 finally:
  work=work if work is not None else getattr(fx,'work',None)
  try:complete=not dispatched or fx.tree_complete() is True
  except Exception:complete=False
  if support_refusal is not None:
   if not complete:r['code']='OWNED_TREE_UNCONFIRMED'
   else:
    try:
     need(fx.support_refusal_current(support_refusal,runtime) is True,'STALE_SUPPORT_PROOF')
     need(fx.runtime_unchanged(work,runtime) is True,'RUNTIME_CHANGED')
     need(fx.fixtures_empty(work) is True,'PUBLIC_FIXTURES_REMAIN')
     support_verified=True;r['fixture_cleanup']='CONFIRMED_EMPTY_PRETEST'
    except Exception as ex:r['code']=str(ex) if isinstance(ex,Refused) and re.fullmatch('[A-Z0-9_]+',str(ex)) else 'SUPPORT_REFUSAL_UNCONFIRMED'
  r['owned_tree']='CONFIRMED' if dispatched and complete else ('UNCONFIRMED' if dispatched else 'NOT_STARTED')
  if work is not None:
   if not complete:r['runtime_cleanup']='RETAINED_OWNED_TREE_UNCONFIRMED'
   else:
    try:r['runtime_cleanup']=fx.cleanup(work)
    except Exception:r['runtime_cleanup']='RETAINED_CLEANUP_FAILED'
  if support_verified and complete and r['runtime_cleanup']=='REMOVED':
   r.update(status='BLOCKED',exit_status=78,kernel_live='NOT RUN',code='VERIFIED_SETUP_SUPPORT_REFUSAL')
   r['support_refusal']={'origin':support_refusal.origin,'setup_exit_status':support_refusal.exit_code,'harness_command_exit_status':support_refusal.proof_snapshot['command_returncode'],'verified_fresh_proof':True}
  elif support_verified:r['code']='SUPPORT_REFUSAL_CLEANUP_UNCONFIRMED'
  if r['code']=='PENDING_CLEANUP' and r['runtime_cleanup']=='REMOVED':r.update(status='PASS',exit_status=0,code='COMPLETE',kernel_live='PASS')
  elif r['status']!='BLOCKED':r.update(status='FAILED',exit_status=1,kernel_live='NOT_CONFIRMED' if dispatched else 'NOT RUN')
  if r['status']=='BLOCKED' and r['runtime_cleanup'] not in ('NOT_CREATED','REMOVED'):r.update(status='FAILED',exit_status=1,code='CLEANUP_UNCONFIRMED')
 return r

class LinuxEffect:
 def __init__(self,workspace,runner_temp):
  need(RUN_AUTHORIZED is True,'CI_DISABLED')
  self.workspace=Path(workspace);self.runner_temp=Path(runner_temp);self.c=None;self.work=None
 def checkout_binding(self,commit,tree,parent):
  import subprocess
  def git(*args):return subprocess.check_output(['git',*args],cwd=self.workspace,text=True).strip()
  return git('rev-parse','HEAD')==commit and git('rev-parse','HEAD^{tree}')==tree and git('show','-s','--format=%P','HEAD')==parent
 def stage(self,files):
  need(self.runner_temp.is_absolute() and self.runner_temp.resolve()==self.runner_temp and self.runner_temp.is_dir(),'RUNNER_TEMP_REFUSED')
  p=Path(tempfile.mkdtemp(prefix='s12-public-linux-ci-',dir=self.runner_temp));self.work=p;s=p.lstat();self.identity=s.st_dev,s.st_ino;os.chmod(p,0o700)
  for n,b in files.items():
   f=p/n;f.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
   fd=os.open(f,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
   with os.fdopen(fd,'wb') as out:os.fchmod(out.fileno(),0o600);out.write(b)
  (p/'fixtures').mkdir(mode=0o700);return p
 def prerequisites(self):
  if not required_api_support():return 'BLOCKED'
  # Read-only probe only; no initializer import, setters or fallback.
  import ctypes
  if sys.platform!='linux' or os.geteuid()==0 or not hasattr(os,'pidfd_open'):return 'BLOCKED'
  pid=os.getpid()
  try:
   Path('/proc/self/stat').read_text();Path('/proc/self/task/'+str(pid)+'/children').read_text()
   value=ctypes.c_int();libc=ctypes.CDLL(None,use_errno=True)
   if libc.prctl(37,ctypes.byref(value),0,0,0)!=0:return 'BLOCKED'
   fd=os.pidfd_open(pid,0);os.close(fd)
  except Exception:return 'BLOCKED'
  return 'SUPPORTED'
 def execute(self,work):
  need(RUN_AUTHORIZED is True,'CI_DISABLED')
  import importlib.util
  sys.path.insert(0,str(work/'scripts'))
  spec=importlib.util.spec_from_file_location('s12_public_command_primitive',work/'scripts/common.py');self.c=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.c)
  env={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','TMPDIR':str(work/'fixtures')}
  return invoke_verified_harness(self.c,work,env)
 def support_refusal_current(self,refusal,pins):return support_refusal_current(refusal,self.c,pins)
 def tree_complete(self):return self.c is not None and self.c.PROCESS_STATE['unconfirmed_group'] is None and (self.c.PROCESS_STATE['proof'] or {}).get('tree_empty_confirmed') is True
 def fixtures_empty(self,work):return not any((work/'fixtures').iterdir())
 def runtime_unchanged(self,work,pins):return all(digest((work/n).read_bytes())==h for n,h in pins.items())
 def cleanup(self,work):
  s=work.lstat();need(stat.S_ISDIR(s.st_mode) and (s.st_dev,s.st_ino)==self.identity,'WORK_IDENTITY_CHANGED')
  shutil.rmtree(work);need(not work.exists(),'WORK_REMAINS');return 'REMOVED'

def write_evidence(directory,report):
 directory=Path(directory);directory.mkdir(mode=0o700,exist_ok=True)
 b=(json.dumps(report,sort_keys=True,indent=2)+'\n').encode()
 for n,data in [('report.json',b),('SHA256SUMS',(digest(b)+'  report.json\n').encode())]:
  fd=os.open(directory/n,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'wb') as f:os.fchmod(f.fileno(),0o600);f.write(data);f.flush();os.fsync(f.fileno())
def main():
 if not RUN_AUTHORIZED:print('REFUSED: CI draft disabled',file=sys.stderr);return 64
 keys={'repository':'GITHUB_REPOSITORY','repository_id':'GITHUB_REPOSITORY_ID','event':'GITHUB_EVENT_NAME','ref':'GITHUB_REF','sha':'GITHUB_SHA','workflow_sha':'GITHUB_WORKFLOW_SHA','workflow_ref':'GITHUB_WORKFLOW_REF','run_id':'GITHUB_RUN_ID','run_attempt':'GITHUB_RUN_ATTEMPT','runner_os':'RUNNER_OS','runner_arch':'RUNNER_ARCH','runner_environment':'S12_RUNNER_ENVIRONMENT'}
 c={k:os.environ.get(v,'') for k,v in keys.items()}
 try:
  validate_context(c);workspace=Path(os.environ['GITHUB_WORKSPACE']);t=workspace/'tests/safety/s12-public-linux-ci'
  need(digest((t/'inspect.py').read_bytes())==INSPECTOR_SHA,'INSPECTOR_PIN_REFUSED')
  r=collect_once(c,(t/'public-harness.tar.gz').read_bytes(),LinuxEffect(workspace,os.environ['RUNNER_TEMP']))
  r['source']['collector_sha256']=digest(Path(__file__).read_bytes());r['source']['workflow_file_sha256']=digest((workspace/WORKFLOW).read_bytes())
 except Exception:r={'schema':'s12-public-linux-proof-v1','status':'BLOCKED','exit_status':78,'code':'ENTRY_PREREQUISITE_REFUSED','kernel_live':'NOT RUN'}
 try:write_evidence('ci-public-evidence',r)
 except Exception:print('COLLECTOR_EVIDENCE_FAILED',file=sys.stderr);return 1
 return r['exit_status']
if __name__=='__main__':raise SystemExit(main())
