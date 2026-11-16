"""Fresh-object 4 GiB cache roundtrips on one runner; public receipts contain no capabilities."""
import hashlib,io,json,os,shutil,subprocess,sys,tarfile,time,urllib.request
from pathlib import Path
ROOT=Path('/tmp/large-download-smoke-'+os.environ['GITHUB_RUN_ID']+'-'+os.environ['GITHUB_RUN_ATTEMPT'])
RESULTS=ROOT/'results'

def digest(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for chunk in iter(lambda:f.read(8*1024**2),b''):h.update(chunk)
 return h.hexdigest()

def write(name,v):
 RESULTS.mkdir(parents=True,exist_ok=True);(RESULTS/name).write_text(json.dumps(v,indent=2))

def sudo(*args):subprocess.run(['sudo','-n',*map(str,args)],check=True,stdout=subprocess.DEVNULL)

def setup():
 ROOT.mkdir(mode=0o700);RESULTS.mkdir()
 source=ROOT/'source';source.mkdir()
 guest=source/'dataplane/guest'
 url=os.environ.pop('MATRIX_SOURCE_URL')
 with urllib.request.urlopen(url,timeout=90) as r:data=r.read()
 assert hashlib.sha256(data).hexdigest()==os.environ['MATRIX_SOURCE_SHA256'],'source checksum'
 with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as tar:tar.extractall(source,filter='data')
 del data,url
 # RUNNER_TEMP is <runner>/_work/_temp; Node lives under the same runner's externals.
 runner=Path(os.environ['RUNNER_TEMP']).parent.parent
 helper=runner/'externals/celesto-ci-cache-download'
 assert helper.is_file(),'published helper missing'
 shutil.copy2(helper,ROOT/'original-helper')
 (ROOT/'helper-path').write_text(str(helper))
 write('machine.json',{'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'cpus':os.cpu_count(),'memory':[s for s in Path('/proc/meminfo').read_text().splitlines() if s.startswith('MemTotal:')],'original_helper_sha256':digest(helper),'kernel':os.uname().release,'runner_name':os.environ.get('RUNNER_NAME'),'source_archive_sha256':os.environ['MATRIX_SOURCE_SHA256']})
 # Install tools inside this ephemeral, owned job VM only.
 sudo('apt-get','update','-qq');sudo('apt-get','install','-y','-qq','--no-install-recommends','musl-tools','build-essential')
 os.environ['PATH']=str(Path.home()/'.cargo/bin')+':'+os.environ['PATH']
 with open(ROOT/'build.log','w') as log:
  if not shutil.which('rustup'):
   with urllib.request.urlopen('https://sh.rustup.rs',timeout=90) as response:(ROOT/'rustup-init.sh').write_bytes(response.read())
   subprocess.run(['sh',str(ROOT/'rustup-init.sh'),'-y','--profile','minimal','--no-modify-path'],check=True,stdout=log,stderr=subprocess.STDOUT)
  subprocess.run(['rustup','target','add','x86_64-unknown-linux-musl'],check=True,stdout=log,stderr=subprocess.STDOUT)
  test_env={**os.environ,'RUST_LOG':'info'}
  with open(ROOT/'linux-tests.log','w') as test_log:
   subprocess.run(['cargo','test','--locked','--manifest-path',str(guest/'Cargo.toml')],check=True,env=test_env,stdout=test_log,stderr=subprocess.STDOUT)
  subprocess.run(['cargo','build','--locked','--release','--target','x86_64-unknown-linux-musl','--manifest-path',str(guest/'Cargo.toml'),'--bin','celesto-ci-cache-proxy'],check=True,stdout=log,stderr=subprocess.STDOUT)
 binary=guest/'target/x86_64-unknown-linux-musl/release/celesto-ci-cache-proxy'
 write('build.json',{'binary_sha256':digest(binary),'rustc':subprocess.check_output(['rustc','--version'],text=True).strip(),'lock_sha256':digest(guest/'Cargo.lock'),'writer_batch_bytes':262144,'geometry_overrides':False,'candidate_commit':os.environ['MATRIX_CANDIDATE_SHA'],'native_source_sha256':digest(guest/'src/cache_download.rs'),'linux_test_summary':[line for line in (ROOT/'linux-tests.log').read_text().splitlines() if line.startswith('test result:')],'private_source_excluded':True})
 sudo('install','-m','0755',binary,helper)
 print('Built the branch helper with --locked; Linux guest tests passed; real cache proxy and upload action retained.')

def generate(index):
 expected=json.loads((RESULTS/'machine.json').read_text())
 assert expected['boot_id']==Path('/proc/sys/kernel/random/boot_id').read_text().strip()
 assert not any(key.startswith('CELESTO_EXPERIMENT_') for key in os.environ),'unexpected experimental override'
 Path('cache-file').unlink(missing_ok=True)
 before=time.monotonic()
 with open('cache-file','wb') as out,open('/dev/urandom','rb') as source:
  for _ in range(512):out.write(source.read(8*1024**2))
 elapsed=time.monotonic()-before
 write(f'payload-{index}.json',{'index':index,'range_cap_mib':16,'concurrency':64,'bytes':Path('cache-file').stat().st_size,'sha256':digest('cache-file'),'generation_seconds':elapsed,'boot_id':expected['boot_id']})
 print(f'Fresh 4 GiB payload {index}; branch defaults, no geometry overrides.')

def verify(index):
 expected=json.loads((RESULTS/f'payload-{index}.json').read_text());before=time.monotonic()
 actual=digest('cache-file');assert actual==expected['sha256'] and Path('cache-file').stat().st_size==expected['bytes'],'restored bytes mismatch'
 build=json.loads((RESULTS/'build.json').read_text());helper=Path((ROOT/'helper-path').read_text())
 assert digest(helper)==build['binary_sha256'],'branch helper changed during cache roundtrip'
 write(f'verified-{index}.json',{**expected,'restored_sha256':actual,'verified':True,'hash_seconds':time.monotonic()-before,'helper_sha256':build['binary_sha256'],'candidate_commit':build['candidate_commit']})
 Path('cache-file').unlink();print(f'Payload {index}: full 4 GiB SHA-256 verified.')

def cleanup():
 if (ROOT/'helper-path').exists() and (ROOT/'original-helper').exists():
  helper=Path((ROOT/'helper-path').read_text());sudo('install','-m','0755',ROOT/'original-helper',helper)
  assert digest(helper)==digest(ROOT/'original-helper')
  write('cleanup.json',{'original_helper_restored':True,'sha256':digest(helper)})
 Path('cache-file').unlink(missing_ok=True)

if __name__=='__main__':
 try:
  mode=sys.argv[1]
  if mode=='setup':setup()
  elif mode=='generate':generate(int(sys.argv[2]))
  elif mode=='verify':verify(int(sys.argv[2]))
  elif mode=='cleanup':cleanup()
  else:raise ValueError('unsupported operation')
 except Exception as error:
  # Build logs and source remain in the owned VM; exceptions may contain capability URLs.
  print('Experiment stopped: '+type(error).__name__+'; inspect owned private logs.',file=sys.stderr)
  sys.exit(1)
