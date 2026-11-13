"""Measure provider-native official actions across sizes, preserving runner tuning."""
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ACTION='55cc8345863c7cc4c66a329aec7e433d2d1c52a9'
SIZES=[64,128,400,1024,4096]
PROVIDER=os.environ['PROFILE_PROVIDER']
SAMPLE=int(os.environ['PROFILE_SAMPLE'])
ROOT=Path(os.environ.get('PROFILE_ROOT',f"/dev/shm/cache-size-sweep-{os.environ['GITHUB_RUN_ID']}-{os.environ['GITHUB_RUN_ATTEMPT']}-{SAMPLE}"))
mode=sys.argv[1]

def write(path,data):path.write_text(json.dumps(data,indent=2)+'\n')
def command(*args):
    p=subprocess.run(args,capture_output=True,text=True,timeout=30)
    return p.stdout.strip() if p.returncode==0 else None
def export(**values):
    with open(os.environ['GITHUB_ENV'],'a') as f:
        for k,v in values.items():f.write(f'{k}={v}\n')
def current():return Path(os.environ['PROFILE_OUT'])
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        while block:=f.read(4*1024**2):h.update(block)
    return h.hexdigest()

def summarize_case():
    out=current();case=json.loads((out/'case.json').read_text())
    result={**case,'valid':False}
    try:
        events=[json.loads(line) for line in (out/'events.jsonl').read_text().splitlines()]
        required={'save_total','detect_compression','resolve_paths','create_temp_dir','archive','reserve','upload','finalize','cleanup','process'}
        ends=[e for e in events if e['event']=='end'];starts=[e for e in events if e['event']=='start']
        assert len(ends)==len(required) and {e['phase'] for e in ends}==required,'Missing/duplicate phase endings'
        assert len(starts)==len(required) and {e['phase'] for e in starts}==required,'Missing/duplicate phase starts'
        assert all(e.get('status','success')=='success' for e in ends),'Failed save phase'
        phases={e['phase']:e for e in ends};obs={e['phase']:e for e in events if e['event']=='observed'}
        assert phases['process']['exit_code']==0,'Action process failed'
        assert obs['cache_result']['saved'],'Action skipped save'
        config=obs['upload_config'];size=obs['archive_bytes']['bytes']
        expected_concurrency=64 if PROVIDER=='celesto' else 8
        assert config['concurrency']==expected_concurrency and config['chunk_bytes']==64*1024**2,'Unexpected native upload config'
        if PROVIDER=='celesto':
            assert config['batch'] and config['size_metadata'],'Celesto batch preparation bypassed'
            assert config['script'].startswith('.celesto-upload-'),'Official runner preparation bypassed'
        verified=json.loads((out/'verification.json').read_text())
        assert verified['sha256_match'] and verified['size_match'],'Restored bytes mismatch'
        assert case['mib']*1024**2 < size < case['mib']*1024**2+1024**2,'Unexpected archive size/compression'
        seconds={k:e['duration_ms']/1000 for k,e in phases.items()}
        host=json.loads((ROOT/'host.json').read_text())
        result.update(valid=True,seconds=seconds,upload_mib_s=size/1024**2/seconds['upload'],archive_bytes=size,upload_config=config,payload_sha256=verified['expected_sha256'],restored_sha256=verified['restored_sha256'],restore_verified=True,phase_starts={e['phase']:e for e in starts},phase_ends=phases,host=host)
    except Exception as error:
        result['error_type']=type(error).__name__;result['error']=str(error)
    write(out/'result.json',result)
    return result

if mode=='prepare':
    ROOT.mkdir(parents=True)
    export(PROFILE_ROOT=ROOT)
    bundle=Path(os.environ['RUNNER_WORKSPACE']).parent/'_actions/actions/cache'/ACTION/'dist/save-only/index.js'
    assert bundle.is_file(),f'Official save action not downloaded: {bundle}'
    subprocess.run([sys.executable,str(Path(__file__).with_name('prepare-cache-size-sweep.py')),str(bundle),str(bundle),str(ROOT/'patch.json')],check=True)
    subprocess.run(['node','--check',str(bundle)],check=True)
    host_provider='unknown'
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():continue
        try:args=(p/'cmdline').read_bytes().decode().split('\0')
        except (OSError,UnicodeError):continue
        if args and 'celesto-ci-cache-proxy' in args[0] and '--host-provider' in args:
            value=args[args.index('--host-provider')+1]
            if value in ['aws','ovh']:host_provider=value
    write(ROOT/'host.json',{'provider':PROVIDER,'host_provider':host_provider,'sample':SAMPLE,'runner':os.environ['RUNNER_NAME'],'kernel':os.uname().release,'cpu':command('lscpu'),'memory':command('free','-b'),'payload_filesystem':command('findmnt','-J','-T',os.environ['GITHUB_WORKSPACE']),'archive_filesystem':command('findmnt','-J','-T',os.environ['RUNNER_TEMP']),'metadata_filesystem':command('findmnt','-J','-T',str(ROOT)),'tar':command('tar','--version'),'zstd':command('zstd','--version'),'run_url':f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}"})
elif mode=='case':
    position=int(sys.argv[2]);order=SIZES if SAMPLE==1 else list(reversed(SIZES)) if SAMPLE==2 else SIZES[2:]+SIZES[:2]
    mib=order[position-1];out=ROOT/f'{mib}mib';out.mkdir()
    Path('cache-file').unlink(missing_ok=True)
    export(PROFILE_OUT=out,PROFILE_MIB=mib,CACHE_PROFILE_EVENTS=out/'events.jsonl',CACHE_PROFILE_ARCHIVE_RESOURCES=out/'archive-resources.txt',PROFILE_CACHE_KEY=f"size-sweep-{PROVIDER}-{os.environ['GITHUB_RUN_ID']}-{os.environ['GITHUB_RUN_ATTEMPT']}-{SAMPLE}-{mib}")
    write(out/'case.json',{'provider':PROVIDER,'sample':SAMPLE,'position':position,'mib':mib,'payload_bytes':mib*1024**2,'action_commit':ACTION,'generation_method':'deterministic AES-256-CTR stream per sample; no pre-save hash/sync'})
elif mode=='generate':
    out=current();mib=int(os.environ['PROFILE_MIB']);key=hashlib.sha256(f'ci-cache-size-sweep-v1-sample-{SAMPLE}'.encode()).hexdigest()
    start=time.monotonic();started=datetime.now(UTC).isoformat()
    with open('cache-file','wb') as f:
        head=subprocess.Popen(['head','-c',str(mib*1024**2),'/dev/zero'],stdout=subprocess.PIPE)
        cipher=subprocess.Popen(['openssl','enc','-aes-256-ctr','-K',key,'-iv','0'*32],stdin=head.stdout,stdout=f,stderr=subprocess.PIPE)
        head.stdout.close();_,stderr=cipher.communicate();a=head.wait()
        assert a==0 and cipher.returncode==0,'Payload generator failed'
    assert Path('cache-file').stat().st_size==mib*1024**2
    write(out/'generation.json',{'seconds':time.monotonic()-start,'started_utc':started,'ended_utc':datetime.now(UTC).isoformat(),'size_bytes':mib*1024**2,'pre_save_hash':False,'pre_save_sync':False})
elif mode=='hash-remove':
    path=Path('cache-file');out=current()
    write(out/'input.json',{'sha256':digest(path),'size_bytes':path.stat().st_size})
    path.unlink()
elif mode=='verify':
    out=current();expected=json.loads((out/'input.json').read_text());path=Path('cache-file')
    actual=digest(path) if path.is_file() else None
    size=path.stat().st_size if path.is_file() else None
    write(out/'verification.json',{'expected_sha256':expected['sha256'],'restored_sha256':actual,'sha256_match':actual==expected['sha256'],'restored_size_bytes':size,'size_match':size==int(os.environ['PROFILE_MIB'])*1024**2==expected['size_bytes']})
    path.unlink(missing_ok=True)
elif mode=='summarize-case':
    result=summarize_case()
    print(json.dumps({k:result.get(k) for k in ['provider','sample','mib','valid','seconds','upload_mib_s','upload_config','error']}))
elif mode=='summarize-job':
    results=[]
    for mib in SIZES:
        path=ROOT/f'{mib}mib/result.json'
        results.append(json.loads(path.read_text()) if path.is_file() else {'mib':mib,'valid':False,'error':'Missing case result'})
    write(ROOT/'job-results.json',results)
    lines=[f'## {PROVIDER}:sample{SAMPLE}','', '| MiB | Valid | Upload s | Upload MiB/s | Save body s | Action process s |','| --- | --- | ---: | ---: | ---: | ---: |']
    for r in results:
        s=r.get('seconds',{});lines.append(f"| {r['mib']} | {r['valid']} | {s.get('upload',0):.3f} | {r.get('upload_mib_s',0):.1f} | {s.get('save_total',0):.3f} | {s.get('process',0):.3f} |")
    text='\n'.join(lines)+'\n';(ROOT/'summary.md').write_text(text)
    with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f:f.write(text)
    print(text)
    assert len(results)==5 and all(r['valid'] for r in results),'Some file sizes failed validation; see artifacts'
else:raise ValueError(mode)
