"""Swap only this ephemeral job VM's one cache proxy; retain exact startup config privately."""
from pathlib import Path
import hashlib,json,os,signal,socket,subprocess,sys,time
root=Path(sys.argv[2]);state_path=root/'proxy-state.private.json'
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def args_for(pid):return (Path('/proc')/str(pid)/'cmdline').read_bytes().rstrip(b'\0').split(b'\0')
def alive(pid):
 try:os.kill(pid,0);return True
 except ProcessLookupError:return False
def stop(pid,expected):
 if not alive(pid):return
 actual=args_for(pid)
 assert actual and os.fsdecode(actual[0])==expected,'Proxy PID ownership changed'
 os.kill(pid,signal.SIGTERM)
 deadline=time.monotonic()+10
 while alive(pid) and time.monotonic()<deadline:
  if (Path('/proc')/str(pid)/'stat').read_text().split(') ')[1].startswith('Z'):break
  time.sleep(.05)
 else:
  assert not alive(pid),'Owned proxy failed to stop'
def wait_ready(process,argv):
 address=argv[argv.index('--listen')+1];host,port=address.rsplit(':',1)
 for _ in range(100):
  assert process.poll() is None,'Owned proxy exited before readiness'
  try:
   with socket.create_connection((host,int(port)),timeout=.1):return
  except OSError:time.sleep(.1)
 raise RuntimeError('Owned proxy readiness deadline')
def launch(argv,env,log):
 with open(log,'ab') as output:
  process=subprocess.Popen(argv,env=env,stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
 try:wait_ready(process,argv)
 except Exception:
  process.terminate();process.wait(timeout=10);raise
 return process.pid
def save(value):
 fd=os.open(state_path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
 with os.fdopen(fd,'w') as f:json.dump(value,f)

assert os.geteuid()==0
mode=sys.argv[1]
if mode=='start':
 assert not state_path.exists(),'Proxy swap already recorded'
 candidates=[]
 for proc in Path('/proc').glob('[0-9]*'):
  try:
   args=[os.fsdecode(v) for v in args_for(int(proc.name))]
   if args and Path(args[0]).name=='celesto-ci-cache-proxy' and '--api-url' in args and '--listen' in args and args[args.index('--listen')+1].endswith(':8448'):candidates.append((int(proc.name),args))
  except (OSError,ValueError):continue
 assert len(candidates)==1,'Expected exactly one owned VM cache server'
 pid,argv=candidates[0]
 assert (Path('/proc')/str(pid)/'status').read_text().split('Uid:')[1].split()[0]=='0'
 environment=dict(os.fsdecode(v).split('=',1) for v in (Path('/proc')/str(pid)/'environ').read_bytes().split(b'\0') if b'=' in v)
 trace_dir=Path('/dev/shm')/(root.name+'-proxy');trace_dir.mkdir(mode=0o755)
 original_exe=os.readlink(Path('/proc')/str(pid)/'exe');binary=root/'source/guest/target/x86_64-unknown-linux-musl/release/celesto-ci-cache-proxy'
 record={'original_argv':argv,'original_env':environment,'original_exe':original_exe,'original_sha256':digest(original_exe),'original_pid':pid,'instrumented_binary':str(binary),'trace_dir':str(trace_dir),'status':'recorded'};save(record)
 try:
  stop(pid,argv[0]);record['status']='original_stopped';save(record)
  new_argv=[str(binary),*argv[1:]];new_env={**environment,'CELESTO_EXPERIMENT_PROXY_TIMING_DIR':str(trace_dir)}
  record['instrumented_pid']=launch(new_argv,new_env,root/'proxy-debug.private.log');record['status']='instrumented';save(record)
 except Exception:
  if record['status']=='original_stopped':record['restored_pid']=launch(argv,environment,root/'proxy-restored.private.log');record['status']='restored_after_setup_error';save(record)
  raise
 public={'original_proxy_sha256':record['original_sha256'],'instrumented_binary_sha256':digest(binary),'same_original_arguments_and_environment':True,'instrumented_pid':record['instrumented_pid'],'trace_dir':str(trace_dir),'proxy_restarted_once_before_measurement':True}
 (root/'results/proxy-setup.json').write_text(json.dumps(public,indent=2));print('Owned VM proxy is instrumented and ready; original startup configuration retained privately.')
 observer=str(Path(__file__).with_name('tcp-observer.py'))
 with open(root/'tcp-observer.private.log','ab') as log:
  child=subprocess.Popen(['python3',observer,'collect',str(root),str(record['instrumented_pid'])],stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
 record['tcp_observer_pid']=child.pid;record['tcp_observer_script']=observer;save(record)
 for _ in range(100):
  assert child.poll() is None,'TCP observer exited'
  if (root/'results/tcp-collector-ready.json').exists():break
  time.sleep(.05)
 else:raise RuntimeError('TCP observer readiness deadline')
elif mode=='restore':
 if not state_path.exists():sys.exit(0)
 record=json.loads(state_path.read_text())
 if record.get('tcp_observer_pid') and alive(record['tcp_observer_pid']):
  arguments=[os.fsdecode(x) for x in args_for(record['tcp_observer_pid'])];assert record['tcp_observer_script'] in arguments and 'collect' in arguments
  os.kill(record['tcp_observer_pid'],signal.SIGTERM)
  for _ in range(100):
   if (root/'results/tcp-collector-summary.json').exists():break
   time.sleep(.05)
  assert (root/'results/tcp-collector-summary.json').exists(),'TCP observer did not finish'
 if record['status']=='instrumented':
  stop(record['instrumented_pid'],record['instrumented_binary']);record['restored_pid']=launch(record['original_argv'],record['original_env'],root/'proxy-restored.private.log');record['status']='restored';save(record)
 assert record['status'].startswith('restored')
 assert digest(record['original_exe'])==record['original_sha256']
 (root/'results/proxy-cleanup.json').write_text(json.dumps({'original_proxy_restarted':True,'original_arguments_and_environment_restored':True,'original_proxy_sha256':record['original_sha256']},indent=2));print('Original owned VM cache proxy restored and ready.')
else:raise ValueError('Unsupported proxy operation')
