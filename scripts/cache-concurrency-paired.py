"""Serial real-proxy cache roundtrips; every trial has independent random bytes and key."""
import hashlib,io,json,math,os,random,re,shutil,socket,subprocess,sys,tarfile,time,urllib.request
from pathlib import Path
from urllib.parse import urlsplit
MIB=1048576
SIZES=[20,24,32,64,96,400,1024,2048,3072,4096]
RANGES=[1,4,8,16,32,64]
PIN='55cc8345863c7cc4c66a329aec7e433d2d1c52a9'
ROOT=Path('/tmp/cache-concurrency-paired-'+os.environ['GITHUB_RUN_ID']+'-'+os.environ['GITHUB_RUN_ATTEMPT'])
RESULTS=ROOT/'results'
trials=[]
progress_url=None

def digest(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for chunk in iter(lambda:f.read(8*MIB),b''):h.update(chunk)
 return h.hexdigest()

def write(name,value):
 RESULTS.mkdir(parents=True,exist_ok=True);p=RESULTS/name;q=p.with_suffix('.tmp');q.write_text(json.dumps(value,indent=2));q.replace(p)

def sudo(*args):subprocess.run(['sudo','-n',*map(str,args)],check=True,stdout=subprocess.DEVNULL)

def checkpoint(stage,**extra):
 value={'stage':stage,'trials':trials,'completed':len(trials),'successful':sum(r.get('success',False) for r in trials),'updated_unix':time.time(),**extra}
 write('progress.json',value)
 if progress_url:
  for attempt in range(3):
   try:
    request=urllib.request.Request(progress_url,data=json.dumps(value).encode(),method='PUT')
    with urllib.request.urlopen(request,timeout=30) as response:response.read()
    break
   except Exception:
    if attempt==2:print(json.dumps({'stage':'progress_publish_delayed'}),flush=True)
    else:time.sleep(1)
 print(json.dumps({k:v for k,v in value.items() if k!='trials'}),flush=True)

def setup():
 ROOT.mkdir(mode=0o700);RESULTS.mkdir();source=ROOT/'source';source.mkdir()
 write('telemetry-availability.json',{name:Path('/proc/'+name).is_file() for name in ['stat','diskstats','meminfo','vmstat','pressure/io','pressure/cpu','pressure/memory']})
 url=os.environ.pop('MATRIX_SOURCE_URL')
 with urllib.request.urlopen(url,timeout=90) as response:data=response.read()
 assert hashlib.sha256(data).hexdigest()==os.environ['MATRIX_SOURCE_SHA256'],'source checksum'
 with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as tar:tar.extractall(source,filter='data')
 del data,url
 runner=Path(os.environ['RUNNER_TEMP']).parent.parent;helper=runner/'externals/celesto-ci-cache-download';assert helper.is_file()
 shutil.copy2(helper,ROOT/'original-helper');(ROOT/'helper-path').write_text(str(helper))
 write('machine.json',{'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'cpus':os.cpu_count(),'memory':[s for s in Path('/proc/meminfo').read_text().splitlines() if s.startswith('MemTotal:')],'original_helper_sha256':digest(helper),'kernel':os.uname().release,'runner_name':os.environ.get('RUNNER_NAME'),'source_archive_sha256':os.environ['MATRIX_SOURCE_SHA256']})
 sudo('apt-get','update','-qq');sudo('apt-get','install','-y','-qq','--no-install-recommends','musl-tools','build-essential')
 os.environ['PATH']=str(Path.home()/'.cargo/bin')+':'+os.environ['PATH']
 with open(ROOT/'build.log','w') as log:
  if not shutil.which('rustup'):
   with urllib.request.urlopen('https://sh.rustup.rs',timeout=90) as response:(ROOT/'rustup-init.sh').write_bytes(response.read())
   subprocess.run(['sh',str(ROOT/'rustup-init.sh'),'-y','--profile','minimal','--no-modify-path'],check=True,stdout=log,stderr=subprocess.STDOUT)
  subprocess.run(['rustup','target','add','x86_64-unknown-linux-musl'],check=True,stdout=log,stderr=subprocess.STDOUT)
  subprocess.run(['cargo','build','--locked','--release','--target','x86_64-unknown-linux-musl','--manifest-path',str(source/'guest/Cargo.toml'),'--bin','celesto-ci-cache-proxy'],check=True,stdout=log,stderr=subprocess.STDOUT)
  subprocess.run(['sudo','-n','docker','run','--rm','-v',str(source/'prep')+':/src','-w','/src','mcr.microsoft.com/dotnet/sdk:8.0','dotnet','build','Prepare.csproj','-o','/src/build','-v','quiet'],check=True,stdout=log,stderr=subprocess.STDOUT)
 binary=source/'guest/target/x86_64-unknown-linux-musl/release/celesto-ci-cache-proxy'
 # Prepare the pinned official bundles with exactly main's C# preparation code.
 preparations=[]
 for action in ['save','restore']:
  folder=ROOT/'actions/dist'/(action+'-only');folder.mkdir(parents=True);original=folder/'index.js';prepared=folder/'matrix-prepared.js'
  with urllib.request.urlopen(f'https://raw.githubusercontent.com/actions/cache/{PIN}/dist/{action}-only/index.js',timeout=90) as response:original.write_bytes(response.read())
  command=['sudo','-n','docker','run','--rm','--network','none','-v',str(source/'prep')+':/prep','-v',str(folder)+':/action','mcr.microsoft.com/dotnet/sdk:8.0','dotnet','/prep/build/Prepare.dll','/action/index.js','/action/matrix-prepared.js']
  r=subprocess.run(command,capture_output=True,text=True);assert r.returncode==0,'action preparation failed'
  proof=json.loads(r.stdout.strip().splitlines()[-1]);assert proof['prepared'],'official action not recognized';preparations.append({'action':action,**proof})
 write('build.json',{'binary_sha256':digest(binary),'rustc':subprocess.check_output(['rustc','--version'],text=True).strip(),'lock_sha256':digest(source/'guest/Cargo.lock'),'writer_batch_bytes':262144,'action_pin':PIN,'preparations':preparations,'range_overrides':'explicit bytes; no cap-induced duplicate geometries','geometry_receipt':True,'released_commit':'e81b6a77ec58853556c40eda528c9b4715852bba','instrumented_module_sha256':digest(source/'guest/src/cache_download.rs'),'full_locked_guest_crate':True})
 sudo('install','-m','0755',binary,helper)
 print('Built the full released guest crate with a 32/64 knob and diagnostics; real proxy and exact action preparation retained.')

def snapshot():
 result={};missing=[]
 for name in ['stat','diskstats','meminfo','vmstat','pressure/io','pressure/cpu','pressure/memory']:
  try:result[name]=Path('/proc/'+name).read_text()
  except FileNotFoundError:result[name]=None;missing.append(name)
 result['unavailable']=missing
 return result

def run_action(action,env,log_path,sample_path=None):
 import threading,resource
 samples=[];stop=threading.Event()
 def sample():
  while not stop.is_set():
   samples.append({'monotonic':time.monotonic(),**snapshot()});stop.wait(0.2)
 thread=threading.Thread(target=sample) if sample_path else None
 if thread:thread.start()
 before=time.monotonic();usage=resource.getrusage(resource.RUSAGE_CHILDREN)
 try:
  with open(log_path,'w') as log:
   result=subprocess.run([os.environ['MATRIX_NODE'],str(ROOT/'actions/dist'/(action+'-only')/'matrix-prepared.js')],env=env,stdout=log,stderr=subprocess.STDOUT,timeout=240)
 finally:
  elapsed=time.monotonic()-before;after=resource.getrusage(resource.RUSAGE_CHILDREN);stop.set()
  if thread:
   thread.join();samples.append({'monotonic':time.monotonic(),**snapshot()});write(sample_path,samples)
 assert result.returncode==0,action+'_action_failed'
 return elapsed,{'user_s':after.ru_utime-usage.ru_utime,'system_s':after.ru_stime-usage.ru_stime,'major_faults':after.ru_majflt-usage.ru_majflt,'block_inputs':after.ru_inblock-usage.ru_inblock,'block_outputs':after.ru_oublock-usage.ru_oublock}

def timing(log,phase):
 for raw in reversed(re.findall(r'Celesto cache timing (\{[^\n]+\})',log)):
  event=json.loads(raw)
  if event['phase']==phase:return event['duration_ms']/1000
 return None

def trial(concurrency,pair,position):
 index=len(trials)+1;key=f'paired-concurrency-{os.environ["GITHUB_RUN_ID"]}-{os.environ["GITHUB_RUN_ATTEMPT"]}-{index}'
 row={'index':index,'pair':pair,'position':position,'concurrency':concurrency,'key':key,'success':False,'started_unix':time.time()}
 output=Path(os.environ['GITHUB_WORKSPACE'])/'cache-file';receipt=RESULTS/f'native-{index}.json';save_log=RESULTS/f'{index}-save.log';restore_log=RESULTS/f'{index}-restore.log'
 try:
  machine=json.loads((RESULTS/'machine.json').read_text());assert machine['boot_id']==Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'boot changed'
  output.unlink(missing_ok=True)
  # Settle the preceding trial's writes before generating a new source file.
  # This is outside all measured phases; no flush is added between save/restore.
  before=time.monotonic();os.sync();row['between_trial_sync_s']=time.monotonic()-before
  row['before_generation']=snapshot();h=hashlib.sha256();before=time.monotonic()
  with open('/dev/urandom','rb') as source,open(output,'wb') as target:
   for _ in range(512):
    data=source.read(8*MIB);assert len(data)==8*MIB;target.write(data);h.update(data)
  row.update(source_sha256=h.hexdigest(),generation_s=time.monotonic()-before,boot_id=machine['boot_id'])
  env={**os.environ,'ACTIONS_CACHE_SERVICE_V2':'true','INPUT_PATH':'cache-file','INPUT_KEY':key,'INPUT_RESTORE-KEYS':'','INPUT_FAIL-ON-CACHE-MISS':'true','INPUT_LOOKUP-ONLY':'false','INPUT_ENABLECROSSOSARCHIVE':'false'}
  for name in list(env):
   if name.startswith('CELESTO_EXPERIMENT_') or name in ['CACHE_UPLOAD_CHUNK_SIZE','CACHE_UPLOAD_CONCURRENCY']:env.pop(name)
  row['save_s'],row['save_resources']=run_action('save',env,save_log);output.unlink()
  row['before_restore']=snapshot();env.update(CELESTO_EXPERIMENT_CONCURRENCY=str(concurrency),CELESTO_EXPERIMENT_RECEIPT_PATH=str(receipt))
  row['restore_s'],row['restore_resources']=run_action('restore',env,restore_log,f'system-{index}.json');row['after_restore']=snapshot()
  save=save_log.read_text();restore=restore_log.read_text()
  assert receipt.exists() and 'Celesto cache native download:' in restore and 'native unavailable' not in restore,'native path not used'
  native=json.loads(receipt.read_text());assert native['bytes']>=4096*MIB and native['range_bytes']==16*MIB and native['concurrency']==concurrency,'geometry mismatch'
  assert native['peak_active']==concurrency,'requested concurrency not reached'
  rates=re.findall(r'Sent [0-9]+ of [0-9]+ \(100\.0%\), ([0-9.]+) MBs/sec',save)
  row.update(archive_bytes=native['bytes'],native_s=native['seconds'],download_mib_s=native['bytes']/MIB/native['seconds'],range_bytes=native['range_bytes'],peak_active=native['peak_active'],recovery_used=native['recovery_used'],download_function_s=timing(restore,'download_total'),upload_function_s=timing(save,'upload_total'),upload_mib_s=float(rates[-1]) if rates else None,archive_create_s=timing(save,'archive_create'),archive_extract_s=timing(restore,'archive_extract'),cache_total_s=row['save_s']+row['restore_s'],native_fallback=False,diagnostics={k:v for k,v in native.items() if k!='requests'})
  assert row['download_function_s'] is not None and row['upload_function_s'] is not None,'timing receipt missing'
  row['upload_effective_mib_s']=native['bytes']/MIB/row['upload_function_s']
  before=time.monotonic();actual=digest(output);assert output.stat().st_size==4096*MIB and actual==row['source_sha256'],'payload integrity mismatch'
  row.update(restored_sha256=actual,hash_s=time.monotonic()-before,success=True)
 except Exception as error:
  row.update(error_type=type(error).__name__,reason=str(error) if isinstance(error,(AssertionError,RuntimeError)) else 'owned_trial_operation_failed')
 finally:
  output.unlink(missing_ok=True);row['completed_unix']=time.time();trials.append(row);write('trials.json',trials)
 checkpoint('running',last_trial={k:row.get(k) for k in ['index','pair','position','concurrency','success','download_mib_s','upload_mib_s','cache_total_s','recovery_used','reason']})
 assert row['success'],'Trial failed; preserve failure and stop without replacement.'

def run():
 global progress_url
 progress_url=os.environ.pop('MATRIX_PROGRESS_PUT_URL')
 assert os.environ.get('ACTIONS_RUNTIME_TOKEN') and os.environ.get('ACTIONS_RESULTS_URL'),'real Node action runtime missing'
 proxy=urlsplit(os.environ['ACTIONS_RESULTS_URL']);mapped={a[4][0] for a in socket.getaddrinfo('celesto-cache.blob.core.windows.net',8448,type=socket.SOCK_STREAM)}
 assert proxy.scheme=='http' and proxy.port==8448 and proxy.hostname in mapped|{'127.0.0.1','localhost','celesto-cache.blob.core.windows.net'},'real cache proxy unavailable'
 write('runtime.json',{'real_cache_host_mapping_verified':True,'proxy_port':proxy.port,'runtime_token_present':True,'node':os.environ['MATRIX_NODE']})
 os.chdir(os.environ['GITHUB_WORKSPACE'])
 write('method.json',{'released_commit':'e81b6a77ec58853556c40eda528c9b4715852bba','pairs':10,'trials':20,'payload_mib':4096,'concurrency':[32,64],'range_mib':16,'writer_batch_bytes':262144,'order':'32,64 on odd pairs; 64,32 on even pairs. Fixed before measurement.','first_download_only':True,'unique_random_payload_and_cache_key_per_trial':True,'same_vm_same_helper_binary':True,'action_pin':PIN,'proxy':'actual released CI proxy, real backend metadata, real R2','upload':'same pinned official save bundle, exact released C# preparation, default adaptive upload','between_trial_sync':True,'sync_between_upload_and_restore':False,'hash_verification':'full SHA-256 source vs restored payload for every trial','limits':['Only concurrency changes; one instrumented released helper is used for both values. Diagnostic timing overhead is shared.','New cache object on every restore; no repeat reads. The VM and proxy process remain alive across trials, so this does not reproduce a fresh VM for each configuration.','sync runs before generating each new payload, outside measured phases, to reduce dirty writeback carryover.','Header/body wait sums overlap across requests and include runtime scheduling; they are not pure wire latency. Write sums can also overlap across runtime threads.','Shared physical host load and R2 internal state remain unobservable/uncontrolled.']})
 for pair in range(1,11):
  for position,concurrency in enumerate([32,64] if pair%2 else [64,32],1):trial(concurrency,pair,position)
 assert len(trials)==20 and len({r['source_sha256'] for r in trials})==20 and len({r['key'] for r in trials})==20
 checkpoint('complete')

def cleanup():
 if (ROOT/'helper-path').exists() and (ROOT/'original-helper').exists():
  helper=Path((ROOT/'helper-path').read_text());sudo('install','-m','0755',ROOT/'original-helper',helper);assert digest(helper)==digest(ROOT/'original-helper');write('cleanup.json',{'original_helper_restored':True,'sha256':digest(helper)})
 (Path(os.environ['GITHUB_WORKSPACE'])/'cache-file').unlink(missing_ok=True)

if __name__=='__main__':
 try:
  {'setup':setup,'run':run,'cleanup':cleanup}[sys.argv[1]]()
 except Exception as error:
  print('Experiment stopped: '+type(error).__name__+'; inspect owned evidence.',file=sys.stderr);sys.exit(1)
