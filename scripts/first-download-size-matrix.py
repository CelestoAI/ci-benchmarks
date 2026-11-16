"""Serial real-proxy cache roundtrips; every trial has independent random bytes and key."""
import hashlib,io,json,math,os,random,re,shutil,socket,subprocess,sys,tarfile,time,urllib.request
from pathlib import Path
from urllib.parse import urlsplit
MIB=1048576
SIZES=[20,24,32,64,96,400,1024,2048,3072,4096]
RANGES=[1,4,8,16,32,64]
PIN='55cc8345863c7cc4c66a329aec7e433d2d1c52a9'
ROOT=Path('/tmp/first-download-size-matrix-'+os.environ['GITHUB_RUN_ID']+'-'+os.environ['GITHUB_RUN_ATTEMPT'])
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
  subprocess.run(['cargo','build','--release','--target','x86_64-unknown-linux-musl','--manifest-path',str(source/'guest/Cargo.toml'),'--bin','celesto-ci-cache-proxy'],check=True,stdout=log,stderr=subprocess.STDOUT)
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
 write('build.json',{'binary_sha256':digest(binary),'rustc':subprocess.check_output(['rustc','--version'],text=True).strip(),'lock_sha256':digest(source/'guest/Cargo.lock'),'writer_batch_bytes':262144,'action_pin':PIN,'preparations':preparations,'range_overrides':'explicit bytes; no cap-induced duplicate geometries','geometry_receipt':True})
 sudo('install','-m','0755',binary,helper)
 print('Built released native downloader with geometry overrides and exact action preparation; real proxy retained.')

def shape(r,c):return {'range_mib':r,'concurrency':c,'mode':'fixed'}
MAIN={'mode':'main'}
def profile_id(p):return 'main' if p['mode']=='main' else f'r{p["range_mib"]}-c{p["concurrency"]}'

def candidates(mib):
 seen={};size=mib*MIB+1
 for r in RANGES:
  for c in ([1,4,8,16,32,64] if mib<=96 else [8,16,32,64]):
   n=math.ceil(size/(r*MIB));key=(min(size,r*MIB),min(c,n))
   seen.setdefault(key,shape(r,c))
 return list(seen.values())

def main_geometry(size):
 c,cap=(64,32*MIB) if 128*MIB<size<=2*1024**3 else (32,16*MIB)
 target=(size+c-1)//c;power=1<<(target-1).bit_length()
 return min(max(power,MIB),cap),c

def run_action(action,env,log_path):
 before=time.monotonic()
 with open(log_path,'w') as log:
  result=subprocess.run([os.environ['MATRIX_NODE'],str(ROOT/'actions/dist'/(action+'-only')/'matrix-prepared.js')],env=env,stdout=log,stderr=subprocess.STDOUT,timeout=240)
 if result.returncode:raise RuntimeError(action+'_action_failed')
 return time.monotonic()-before

def timing(log,phase):
 for raw in reversed(re.findall(r'Celesto cache timing (\{[^\n]+\})',log)):
  event=json.loads(raw)
  if event['phase']==phase:return event['duration_ms']/1000
 return None

def trial(mib,profile,stage,block,role=None):
 index=len(trials)+1;key=f'first-size-{os.environ["GITHUB_RUN_ID"]}-{os.environ["GITHUB_RUN_ATTEMPT"]}-{index}';row={'index':index,'payload_mib':mib,'stage':stage,'block':block,'role':role or profile_id(profile),'profile':profile,'key':key,'success':False,'started_unix':time.time()}
 output=Path(os.environ['GITHUB_WORKSPACE'])/'cache-file';receipt=ROOT/f'native-{index}.json';save_log=ROOT/f'{index}-save.log';restore_log=ROOT/f'{index}-restore.log'
 try:
  machine=json.loads((RESULTS/'machine.json').read_text());assert machine['boot_id']==Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'boot changed'
  output.unlink(missing_ok=True);h=hashlib.sha256();before=time.monotonic()
  with open('/dev/urandom','rb') as source,open(output,'wb') as target:
   remaining=mib*MIB
   while remaining:
    data=source.read(min(8*MIB,remaining));assert data;target.write(data);h.update(data);remaining-=len(data)
  row.update(source_sha256=h.hexdigest(),generation_seconds=time.monotonic()-before,boot_id=machine['boot_id'])
  env={**os.environ,'ACTIONS_CACHE_SERVICE_V2':'true','INPUT_PATH':'cache-file','INPUT_KEY':key,'INPUT_RESTORE-KEYS':'','INPUT_FAIL-ON-CACHE-MISS':'true','INPUT_LOOKUP-ONLY':'false','INPUT_ENABLECROSSOSARCHIVE':'false'}
  for name in ['CELESTO_EXPERIMENT_RANGE_MIB','CELESTO_EXPERIMENT_CONCURRENCY','CELESTO_EXPERIMENT_RECEIPT_PATH','CACHE_UPLOAD_CHUNK_SIZE','CACHE_UPLOAD_CONCURRENCY']:env.pop(name,None)
  row['save_s']=run_action('save',env,save_log);output.unlink();env['CELESTO_EXPERIMENT_RECEIPT_PATH']=str(receipt)
  if profile['mode']=='fixed':env.update(CELESTO_EXPERIMENT_RANGE_MIB=str(profile['range_mib']),CELESTO_EXPERIMENT_CONCURRENCY=str(profile['concurrency']))
  row['restore_s']=run_action('restore',env,restore_log);save=save_log.read_text();restore=restore_log.read_text()
  assert receipt.exists() and 'Celesto cache native download:' in restore and 'native unavailable' not in restore,'native path not used'
  native=json.loads(receipt.read_text());assert native['bytes']>=mib*MIB,'archive too small'
  expected=main_geometry(native['bytes']) if profile['mode']=='main' else (profile['range_mib']*MIB,profile['concurrency'])
  assert (native['range_bytes'],native['concurrency'])==expected,'geometry override missing'
  rates=re.findall(r'Sent [0-9]+ of [0-9]+ \(100\.0%\), ([0-9.]+) MBs/sec',save)
  row.update(archive_bytes=native['bytes'],native_seconds=native['seconds'],download_mib_s=native['bytes']/MIB/native['seconds'],range_bytes=native['range_bytes'],configured_concurrency=native['concurrency'],maximum_active_requests=min(native['concurrency'],math.ceil(native['bytes']/native['range_bytes'])),recovery_used=native['recovery_used'],download_function_s=timing(restore,'download_total'),upload_function_s=timing(save,'upload_total'),upload_reported_mib_s=float(rates[-1]) if rates else None,archive_create_s=timing(save,'archive_create'),archive_extract_s=timing(restore,'archive_extract'),cache_total_s=row['save_s']+row['restore_s'],native_fallback=False)
  assert row['download_function_s'] is not None and row['upload_function_s'] is not None,'timing receipt missing'
  row['upload_effective_mib_s']=native['bytes']/MIB/row['upload_function_s']
  before=time.monotonic();actual=digest(output);assert output.stat().st_size==mib*MIB and actual==row['source_sha256'],'payload integrity mismatch'
  row.update(restored_sha256=actual,hash_seconds=time.monotonic()-before,success=True)
 except Exception as error:
  row['error_type']=type(error).__name__;row['reason']=str(error) if isinstance(error,RuntimeError) else 'owned_trial_operation_failed'
 finally:
  output.unlink(missing_ok=True);receipt.unlink(missing_ok=True)
  row['completed_unix']=time.time();trials.append(row);write('trials.json',trials)
 checkpoint(stage,last_trial={k:row.get(k) for k in ['index','payload_mib','role','block','success','download_mib_s','upload_effective_mib_s','cache_total_s','reason']})
 if sum(not r['success'] for r in trials)>=5:raise RuntimeError('too_many_failed_trials')
 return row

def select_screen(mib):
 rows=[r for r in trials if r['stage']=='screen' and r['payload_mib']==mib and r['success']];base=next(r for r in rows if r['role']=='main')
 def identity(row):return (min(row['archive_bytes'],row['range_bytes']),row['maximum_active_requests'])
 distinct={identity(base)};picked=[]
 for r in sorted(rows,key=lambda r:r['download_function_s']):
  if r['profile']['mode']=='main' or identity(r) in distinct:continue
  distinct.add(identity(r));picked.append(r['profile'])
  if len(picked)==2:break
 assert len(picked)==2
 return [MAIN,*picked]

def select_policy(mib,profiles):
 import statistics
 rows=[r for r in trials if r['stage']=='confirmation' and r['payload_mib']==mib and r['success']];by={profile_id(p):[r for r in rows if r['role']==profile_id(p)] for p in profiles};base=by['main'];assert len(base)==3
 median=lambda rs:statistics.median(r['download_function_s'] for r in rs)
 winner=MAIN;best=median(base)
 for p in profiles[1:]:
  rs=by[profile_id(p)]
  if len(rs)!=3:continue
  wins=sum(next(r for r in rs if r['block']==b)['download_function_s']<next(r for r in base if r['block']==b)['download_function_s'] for b in [1,2,3])
  value=median(rs)
  if value<best and value<=median(base)*0.95 and wins>=2:winner=p;best=value
 return {'payload_mib':mib,'profile':winner,'confirmation_median_s':best,'baseline_confirmation_median_s':median(base),'reason':'candidate needs >=5% lower median and >=2/3 paired wins; otherwise retain main'}

def run():
 global progress_url
 progress_url=os.environ.pop('MATRIX_PROGRESS_PUT_URL')
 assert os.environ.get('ACTIONS_RUNTIME_TOKEN') and os.environ.get('ACTIONS_RESULTS_URL'),'real Node action runtime missing'
 proxy=urlsplit(os.environ['ACTIONS_RESULTS_URL'])
 mapped={answer[4][0] for answer in socket.getaddrinfo('celesto-cache.blob.core.windows.net',8448,type=socket.SOCK_STREAM)}
 assert proxy.scheme=='http' and proxy.port==8448 and proxy.hostname in mapped|{'127.0.0.1','localhost','celesto-cache.blob.core.windows.net'},'real cache proxy unavailable'
 write('runtime.json',{'real_cache_host_mapping_verified':True,'proxy_port':proxy.port,'runtime_token_present':bool(os.environ.get('ACTIONS_RUNTIME_TOKEN')),'node':os.environ['MATRIX_NODE']})
 os.chdir(os.environ['GITHUB_WORKSPACE'])
 write('method.json',{'sizes_mib':SIZES,'range_mib':RANGES,'small_concurrency':[1,4,8,16,32,64],'large_concurrency':[8,16,32,64],'screen_rounds':1,'confirmation_rounds':3,'holdout_rounds':3,'first_download_only':True,'unique_random_payload_per_trial':True,'unique_key_per_trial':True,'one_vm':True,'sequential':True,'action_pin':PIN,'proxy':'actual published CI proxy, real backend metadata, actual R2','upload':'main preparation, fixed default64 concurrency and adaptive upload chunks','selection_metric':'outer download function seconds; native helper throughput also recorded','screen_dedup':'collapse configurations with the same request bounds and maximum active requests; baseline retained separately','timing':'download function includes helper startup, HEAD, network and archive writes; cache total includes compression/extraction; generation and hashes excluded','limits':['Size recommendations are sampled, not proof of an optimum at every intervening byte size.','One runner on a shared host; shuffled ordering limits but does not remove environmental variation.','No intentional repeat download; R2 internal state is not observable.']})
 qualification=trial(20,MAIN,'qualification',0);assert qualification['success'],'pipeline qualification failed'
 sizes=SIZES.copy();random.Random(161601).shuffle(sizes)
 for mib in sizes:
  order=[MAIN,*candidates(mib)];random.Random(161602+mib).shuffle(order)
  for p in order:trial(mib,p,'screen',1)
 shortlist={mib:select_screen(mib) for mib in SIZES};write('shortlist.json',shortlist);checkpoint('screen_complete',shortlist=shortlist)
 for block in [1,2,3]:
  order=[(mib,p) for mib in SIZES for p in shortlist[mib]];random.Random(161610+block).shuffle(order)
  for mib,p in order:trial(mib,p,'confirmation',block)
 policy=[select_policy(mib,shortlist[mib]) for mib in SIZES];write('policy.json',policy);checkpoint('confirmation_complete',policy=policy)
 # Independent trials: policy frozen before these fresh payloads are generated.
 for block in [1,2,3]:
  order=[(entry['payload_mib'],p,role) for entry in policy for p,role in [(MAIN,'main'),(entry['profile'],'adaptive')]];random.Random(161620+block).shuffle(order)
  for mib,p,role in order:trial(mib,p,'holdout',block,role)
 assert len({r['source_sha256'] for r in trials if 'source_sha256' in r})==len([r for r in trials if 'source_sha256' in r]),'payload reused'
 checkpoint('complete',policy=policy)
 assert all(r['success'] for r in trials),'one or more trials failed; retained in results'

def cleanup():
 if (ROOT/'helper-path').exists() and (ROOT/'original-helper').exists():
  helper=Path((ROOT/'helper-path').read_text());sudo('install','-m','0755',ROOT/'original-helper',helper);assert digest(helper)==digest(ROOT/'original-helper');write('cleanup.json',{'original_helper_restored':True,'sha256':digest(helper)})
 (Path(os.environ['GITHUB_WORKSPACE'])/'cache-file').unlink(missing_ok=True)

if __name__=='__main__':
 try:
  if sys.argv[1]=='setup':setup()
  elif sys.argv[1]=='run':run()
  elif sys.argv[1]=='cleanup':cleanup()
  else:raise ValueError('unsupported mode')
 except Exception as error:
  write('failure.json',{'error_type':type(error).__name__,'reason':str(error) if isinstance(error,(AssertionError,RuntimeError)) else 'owned_matrix_operation_failed'})
  if progress_url:checkpoint('failed',error_type=type(error).__name__)
  print('Size matrix stopped: '+type(error).__name__+'; sanitized receipt retained.',file=sys.stderr);sys.exit(1)
