"""Serial real-proxy cache roundtrips; every trial has independent random bytes and key."""
import hashlib,io,json,math,os,random,re,shutil,socket,subprocess,sys,tarfile,time,urllib.request
from pathlib import Path
from urllib.parse import urlsplit
MIB=1048576
SIZES=[20,24,32,64,96,400,1024,2048,3072,4096]
RANGES=[1,4,8,16,32,64]
PIN='55cc8345863c7cc4c66a329aec7e433d2d1c52a9'
ROOT=Path('/tmp/cache-tcp-r2-'+os.environ['GITHUB_RUN_ID']+'-'+os.environ['GITHUB_RUN_ATTEMPT'])
RESULTS=ROOT/'results'
trials=[]
progress_url=None
backup_url=None

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

def backup_receipts():
 import io
 secret=ROOT/'receipts-put.private'
 if not secret.exists():return
 buffer=io.BytesIO()
 with tarfile.open(fileobj=buffer,mode='w:gz',compresslevel=1) as archive:
  for path in RESULTS.rglob('*'):
   if path.is_file():archive.add(path,arcname=str(path.relative_to(RESULTS)),recursive=False)
 for attempt in range(3):
  try:
   request=urllib.request.Request(secret.read_text(),data=buffer.getvalue(),method='PUT')
   with urllib.request.urlopen(request,timeout=60) as response:response.read()
   print(json.dumps({'direct_receipt_backup_bytes':buffer.tell()}),flush=True);return
  except Exception:
   if attempt==2:print('Direct receipt backup delayed; retained for cleanup retry.',flush=True)
   else:time.sleep(1)


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
 sudo('apt-get','update','-qq');sudo('apt-get','install','-y','-qq','--no-install-recommends','musl-tools','build-essential','iproute2')
 subprocess.run(['sudo','-n','python3',str(Path(os.environ['GITHUB_WORKSPACE'])/'.harness/scripts/qualify-tcp.py'),str(ROOT)],check=True)
 os.environ['PATH']=str(Path.home()/'.cargo/bin')+':'+os.environ['PATH']
 with open(ROOT/'build.log','w') as log:
  if not shutil.which('rustup'):
   with urllib.request.urlopen('https://sh.rustup.rs',timeout=90) as response:(ROOT/'rustup-init.sh').write_bytes(response.read())
   subprocess.run(['sh',str(ROOT/'rustup-init.sh'),'-y','--profile','minimal','--no-modify-path'],check=True,stdout=log,stderr=subprocess.STDOUT)
  subprocess.run(['rustup','target','add','x86_64-unknown-linux-musl'],check=True,stdout=log,stderr=subprocess.STDOUT)
  with open(ROOT/'linux-tests.private.log','w') as tests:
   subprocess.run(['cargo','test','--locked','--manifest-path',str(source/'guest/Cargo.toml'),'--test','ci_cache_proxy','download::'],check=True,env={**os.environ,'RUST_LOG':'info'},stdout=tests,stderr=subprocess.STDOUT)
  write('linux-tests.json',{'passed':True,'command':'cargo test --locked --test ci_cache_proxy download::','summary':[line for line in (ROOT/'linux-tests.private.log').read_text().splitlines() if line.startswith('test result:')]})
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
 write('build.json',{'binary_sha256':digest(binary),'rustc':subprocess.check_output(['rustc','--version'],text=True).strip(),'lock_sha256':digest(source/'guest/Cargo.lock'),'writer_batch_bytes':262144,'action_pin':PIN,'preparations':preparations,'range_overrides':False,'concurrency_override':'32 or64; adaptive range formula unchanged','geometry_receipt':True,'released_commit':'e81b6a77ec58853556c40eda528c9b4715852bba','instrumented_module_sha256':digest(source/'guest/src/cache_download.rs'),'full_locked_guest_crate':True})
 sudo('install','-m','0755',binary,helper)
 subprocess.run(['python3',str(Path(os.environ['GITHUB_WORKSPACE'])/'.harness/scripts/qualify-proxy-r2-timing.py'),str(ROOT)],check=True)
 print('Full locked guest built; focused Linux contracts and controlled per-hop timing qualification passed.')

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
 index=len(trials)+1;key=f'tcp-r2-paired-{os.environ["GITHUB_RUN_ID"]}-{os.environ["GITHUB_RUN_ATTEMPT"]}-{index}'
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
  control=ROOT/'tcp-control.json';temporary=ROOT/'tcp-control.tmp';temporary.write_text(json.dumps({'active':True,'trial':index}));temporary.replace(control)
  deadline=time.monotonic()+5
  while not (RESULTS/f'tcp-window-{index}.json').exists() and time.monotonic()<deadline:time.sleep(.02)
  assert (RESULTS/f'tcp-window-{index}.json').exists(),'TCP collector did not acknowledge the restore window'
  row['restore_s'],row['restore_resources']=run_action('restore',env,restore_log,f'system-{index}.json');row['after_restore']=snapshot()
  temporary.write_text(json.dumps({'active':False,'trial':index}));temporary.replace(control);deadline=time.monotonic()+5
  while not (RESULTS/f'tcp-window-end-{index}.json').exists() and time.monotonic()<deadline:time.sleep(.02)
  assert (RESULTS/f'tcp-window-end-{index}.json').exists(),'TCP collector did not close the restore window'
  tcp_window=json.loads((RESULTS/f'tcp-window-end-{index}.json').read_text());shutil.copy2(tcp_window['output'],RESULTS/f'tcp-{index}.jsonl.gz')
  save=save_log.read_text();restore=restore_log.read_text()
  assert receipt.exists() and 'Celesto cache native download:' in restore and 'native unavailable' not in restore,'native path not used'
  native=json.loads(receipt.read_text())
  proxy_dir=Path(json.loads((RESULTS/'proxy-setup.json').read_text())['trace_dir']);proxy_ranges=[];joined=[]
  for request in native['requests']:
   trace_path=proxy_dir/('range-'+request['id']+'.json');deadline=time.monotonic()+3
   while not trace_path.exists() and time.monotonic()<deadline:time.sleep(.01)
   assert trace_path.is_file(),'Proxy timing missing: live instrumented proxy not reached'
   trace=json.loads(trace_path.read_text());assert trace['id']==request['id'] and (trace['range_start'],trace['range_end'])==(request['start'],request['end'])
   if 'body' not in trace:
    trace['body_observed']=False
    trace['body']={'bytes':0,'first_poll_mono_ns':0,'first_byte_mono_ns':0,'last_byte_mono_ns':0,'pending_wait_ns':0,'max_pending_wait_ns':0,'consumer_gap_ns':0,'max_consumer_gap_ns':0,'eof_observed':False,'upstream_error':False,'milestones':[]}
   else:trace['body_observed']=True

   if request['error'] is None:assert trace['body']['bytes']==request['end']-request['start']+1,'Proxy body trace incomplete'
   proxy_ranges.append(trace)
   joined.append({'id':request['id'],'native_s':request['seconds'],'proxy_s':trace['total_ns']/1e9,'dispatch_to_handler_s':(trace['begin_mono_ns']-request['begin_mono_ns'])/1e9,'r2_headers_s':sum(x['headers_wait_ns'] for x in trace['upstream_requests'])/1e9,'link_lock_s':trace.get('link_lock_wait_ns',0)/1e9,'refresh_s':trace.get('refresh_ns',0)/1e9,'r2_body_pending_s':trace['body']['pending_wait_ns']/1e9,'max_r2_body_pending_s':trace['body']['max_pending_wait_ns']/1e9,'consumer_gap_s':trace['body']['consumer_gap_ns']/1e9,'max_consumer_gap_s':trace['body']['max_consumer_gap_ns']/1e9,'client_write_s':request['write_ns']/1e9,'max_client_write_s':request['max_write_ns']/1e9})
  write(f'proxy-{index}.json',{'ranges':proxy_ranges,'joined':joined})
  row['proxy_summary']={'range_receipts':len(proxy_ranges),'r2_attempts':sum(len(t['upstream_requests']) for t in proxy_ranges),'refresh_count':sum(t.get('refresh_count',0) for t in proxy_ranges),'max_r2_headers_s':max(j['r2_headers_s'] for j in joined),'max_r2_body_pending_s':max(j['max_r2_body_pending_s'] for j in joined),'max_consumer_gap_s':max(j['max_consumer_gap_s'] for j in joined),'max_link_lock_s':max(j['link_lock_s'] for j in joined)}
  row['slow_ranges']=sorted(joined,key=lambda x:x['native_s'],reverse=True)[:5]
  import gzip,statistics
  peers={t['upstream_requests'][-1].get('peer') for t in proxy_ranges if t['upstream_requests']};samples=[json.loads(line) for line in gzip.open(RESULTS/f'tcp-{index}.jsonl.gz','rt')];connections={};rtts=[];receiver=[]
  for sample in samples:
   for tcp in sample.get('sockets',[]):
    if tcp['peer'] in peers and 'tcp' in tcp:
     key=tuple(tcp['cookie']);connections.setdefault(key,[]).append(tcp);rtts.append(tcp['tcp'].get('rtt',0))
  assert connections and rtts,'No TCP_INFO for actual R2 sockets'
  delta=lambda field:sum(max(x['tcp'].get(field,0) for x in group)-min(x['tcp'].get(field,0) for x in group) for group in connections.values())
  row['tcp_summary']={'samples':len(samples),'r2_connections':len(connections),'rtt_median_us':statistics.median(rtts),'rtt_max_us':max(rtts),'local_send_retrans_delta':delta('total_retrans'),'receiver_ooo_delta':delta('rcv_ooopack'),'local_rto_delta':delta('total_rto'),'query_max_ms':max(x.get('query_ns',0) for x in samples)/1e6}
  assert native['bytes']>=4096*MIB and native['range_bytes']==16*MIB and native['concurrency']==concurrency,'geometry mismatch'
  assert native['peak_active']==concurrency,'requested concurrency not reached'
  rates=re.findall(r'Sent [0-9]+ of [0-9]+ \(100\.0%\), ([0-9.]+) MBs/sec',save)
  row.update(archive_bytes=native['bytes'],native_s=native['seconds'],download_mib_s=native['bytes']/MIB/native['seconds'],range_bytes=native['range_bytes'],peak_active=native['peak_active'],recovery_used=native['recovery_used'],download_function_s=timing(restore,'download_total'),upload_function_s=timing(save,'upload_total'),upload_mib_s=float(rates[-1]) if rates else None,archive_create_s=timing(save,'archive_create'),archive_extract_s=timing(restore,'archive_extract'),cache_total_s=row['save_s']+row['restore_s'],native_fallback=False,diagnostics={k:v for k,v in native.items() if k!='requests'})
  assert row['download_function_s'] is not None and row['upload_function_s'] is not None,'timing receipt missing'
  row['upload_effective_mib_s']=native['bytes']/MIB/row['upload_function_s']
  before=time.monotonic();actual=digest(output);assert output.stat().st_size==4096*MIB and actual==row['source_sha256'],'payload integrity mismatch'
  row.update(restored_sha256=actual,hash_s=time.monotonic()-before,success=True)
 except Exception as error:
  row.update(error_type=type(error).__name__,reason=str(error) if isinstance(error,(AssertionError,RuntimeError,KeyError)) else 'owned_trial_operation_failed')
 finally:
  if (ROOT/'tcp-control.json').exists():
   temporary=ROOT/'tcp-control.tmp';temporary.write_text(json.dumps({'active':False,'trial':index}));temporary.replace(ROOT/'tcp-control.json')
  output.unlink(missing_ok=True);row['completed_unix']=time.time();trials.append(row);write('trials.json',trials)
 backup_receipts()
 checkpoint('running',last_trial={k:row.get(k) for k in ['index','pair','position','concurrency','success','download_mib_s','upload_mib_s','cache_total_s','recovery_used','reason']})
 assert row['success'],'Trial failed; preserve failure and stop without replacement.'

def run():
 global progress_url
 progress_url=os.environ.pop('MATRIX_PROGRESS_PUT_URL')
 secret=ROOT/'receipts-put.private';secret.write_text(os.environ.pop('MATRIX_RECEIPTS_PUT_URL'));secret.chmod(0o600)
 assert os.environ.get('ACTIONS_RUNTIME_TOKEN') and os.environ.get('ACTIONS_RESULTS_URL'),'real Node action runtime missing'
 proxy=urlsplit(os.environ['ACTIONS_RESULTS_URL']);mapped={a[4][0] for a in socket.getaddrinfo('celesto-cache.blob.core.windows.net',8448,type=socket.SOCK_STREAM)}
 assert proxy.scheme=='http' and proxy.port==8448 and proxy.hostname in mapped|{'127.0.0.1','localhost','celesto-cache.blob.core.windows.net'},'real cache proxy unavailable'
 write('runtime.json',{'real_cache_host_mapping_verified':True,'proxy_port':proxy.port,'runtime_token_present':True,'node':os.environ['MATRIX_NODE']})
 os.chdir(os.environ['GITHUB_WORKSPACE'])
 subprocess.run(['sudo','-n','python3',str(Path(os.environ['GITHUB_WORKSPACE'])/'.harness/scripts/manage-cache-proxy-timing.py'),'start',str(ROOT)],check=True)
 write('method.json',{'released_commit':'e81b6a77ec58853556c40eda528c9b4715852bba','pairs':10,'trials':20,'payload_mib':4096,'concurrency':[32,64],'range_mib':16,'writer_batch_bytes':262144,'order':'32,64 on odd pairs; 64,32 on even pairs. Fixed before measurement.','first_download_only':True,'unique_random_payload_and_cache_key_per_trial':True,'same_vm_same_helper_binary':True,'same_instrumented_proxy_for_all_trials':True,'proxy_restarted_once_before_measurement':True,'timing_receipts_in_tmpfs':True,'correlation':'helper/proxy IDs, CLOCK_MONOTONIC and per-range R2 local/remote socket tuples; kernel inode/cookie identity','tcp_sample_interval_ms':100,'tcp_payload_captured':False,'action_pin':PIN,'proxy':'instrumented released CI proxy, original startup arguments/environment, real backend metadata and R2','upload':'same pinned official save bundle, exact released C# preparation, default adaptive upload','between_trial_sync':True,'sync_between_upload_and_restore':False,'hash_verification':'full SHA-256 source vs restored payload for every trial','limits':['Only concurrency changes; one instrumented released helper is used for both values. Diagnostic timing overhead is shared.','New cache object on every restore; no repeat reads. The VM and proxy process remain alive across trials, so this does not reproduce a fresh VM for each configuration.','sync runs before generating each new payload, outside measured phases, to reduce dirty writeback carryover.','Header/body wait sums overlap across requests and include runtime scheduling; they are not pure wire latency. Write sums can also overlap across runtime threads.','Shared physical host load and R2 internal state remain unobservable/uncontrolled.','Upstream Pending time includes readiness scheduling; consumer gaps include downstream backpressure and scheduling.100ms proxy heartbeat helps identify broad runtime stalls.','Header wait includes client pooling, DNS/connect/TLS and R2 first-response latency; it does not isolate those lower-level components.','TCP_INFO retransmission/cwnd/RTT statistics describe the local sender; they do not directly expose the R2 sender congestion window or total incoming retransmissions. Receiver out-of-order and global receive/DSACK/drop counters are recorded separately.','Sampling is100ms, so very brief connection events can be missed. Socket cookies and exact four-tuples disambiguate keepalive reuse; range attribution near sampling boundaries can include neighboring requests.']})
 for pair in range(1,11):
  for position,concurrency in enumerate([32,64] if pair%2 else [64,32],1):trial(concurrency,pair,position)
 assert len(trials)==20 and len({r['source_sha256'] for r in trials})==20 and len({r['key'] for r in trials})==20
 checkpoint('complete')

def cleanup():
 failure=None
 try:
  subprocess.run(['sudo','-n','python3',str(Path(os.environ['GITHUB_WORKSPACE'])/'.harness/scripts/manage-cache-proxy-timing.py'),'restore',str(ROOT)],check=True)
 except Exception as error:failure=type(error).__name__
 try:
  if (RESULTS/'proxy-setup.json').exists():
   trace_dir=Path(json.loads((RESULTS/'proxy-setup.json').read_text())['trace_dir'])
   for path in trace_dir.glob('tcp-*.jsonl.gz'):
    if not (RESULTS/path.name).exists():shutil.copy2(path,RESULTS/path.name)
   if (trace_dir/'runtime-lag.jsonl').exists():shutil.copy2(trace_dir/'runtime-lag.jsonl',RESULTS/'proxy-runtime-lag.jsonl')
   known=set()
   for file in RESULTS.glob('proxy-[0-9]*.json'):
    known.update(t['id'] for t in json.loads(file.read_text())['ranges'])
   orphan=RESULTS/'unjoined-ranges'
   for file in trace_dir.glob('range-*.json'):
    if file.stem.removeprefix('range-') not in known:orphan.mkdir(exist_ok=True);shutil.copy2(file,orphan/file.name)
   write('proxy-coverage.json',{'joined_range_receipts':len(known),'total_range_receipts':len(list(trace_dir.glob('range-*.json'))),'unjoined':len(list(orphan.glob('*.json'))) if orphan.exists() else 0})
 finally:
  if (ROOT/'helper-path').exists() and (ROOT/'original-helper').exists():
   helper=Path((ROOT/'helper-path').read_text());sudo('install','-m','0755',ROOT/'original-helper',helper);assert digest(helper)==digest(ROOT/'original-helper');write('cleanup.json',{'original_helper_restored':True,'sha256':digest(helper),'proxy_cleanup_error':failure})
  (Path(os.environ['GITHUB_WORKSPACE'])/'cache-file').unlink(missing_ok=True)
  backup_receipts()
 if failure:raise RuntimeError('Proxy cleanup failed; direct receipts backed up independently')

if __name__=='__main__':
 try:
  {'setup':setup,'run':run,'cleanup':cleanup}[sys.argv[1]]()
 except Exception as error:
  print('Experiment stopped: '+type(error).__name__+'; inspect owned evidence.',file=sys.stderr);sys.exit(1)
