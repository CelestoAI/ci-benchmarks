import hashlib,json,os,sys,time
from pathlib import Path
root=Path('/tmp/qcow2-preallocation-'+os.environ['GITHUB_RUN_ID']+'-'+os.environ['GITHUB_RUN_ATTEMPT']);root.mkdir(exist_ok=True)
evidence=Path(os.environ['RUNNER_TEMP'])/'qcow2-preallocation-evidence';evidence.mkdir(exist_ok=True)
mode=sys.argv[1]
if mode=='wait':
 ready={'run_id':os.environ['GITHUB_RUN_ID'],'attempt':os.environ['GITHUB_RUN_ATTEMPT'],'runner':os.environ['RUNNER_NAME'],'arm':os.environ['EXPERIMENT_ARM'],'case':os.environ['EXPERIMENT_CASE'],'ready_wall_ns':time.time_ns()};(root/'ready.json').write_text(json.dumps(ready));(evidence/'identity.json').write_text(json.dumps(ready))
 deadline=time.monotonic()+900
 while not (root/'release.json').exists():
  if time.monotonic()>deadline:raise TimeoutError('Host preparation gate timed out')
  time.sleep(.5)
 release=json.loads((root/'release.json').read_text());assert release['run_id']==ready['run_id'] and release['arm']==ready['arm'];(evidence/'disk-preparation.json').write_text(json.dumps(release,indent=2))
 with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('selected='+str(release['action']=='run').lower()+'\n')
 print(json.dumps({'gate_action':release['action'],'arm':ready['arm'],'case':ready['case'],'host_id':release.get('host_id'),'reason':release.get('reason')}))
elif mode in {'hash','verify'}:
 begin=time.monotonic();p=Path(os.environ['GITHUB_WORKSPACE'])/'cache-file';h=hashlib.sha256()
 assert p.stat().st_size==4294967296
 with p.open('rb') as f:
  while b:=f.read(8*1024**2):h.update(b)
 digest=h.hexdigest()
 if mode=='hash':(evidence/'payload.sha256').write_text(digest)
 else:assert digest==(evidence/'payload.sha256').read_text()
 (evidence/(mode+'.json')).write_text(json.dumps({'sha256':digest,'size':p.stat().st_size,'seconds':time.monotonic()-begin,'verified':mode=='verify'}));print(json.dumps({'mode':mode,'sha256':digest,'seconds':time.monotonic()-begin}))
