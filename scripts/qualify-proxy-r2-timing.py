"""Real proxy CLI + HTTP boundaries with independently injected delays, before live R2 trials."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit,parse_qs
import hashlib,http.client,json,os,socket,subprocess,sys,threading,time
root=Path(sys.argv[1]);binary=Path(os.environ['TIMING_PROBE_BINARY']) if os.environ.get('TIMING_PROBE_BINARY') else root/'source/guest/target/x86_64-unknown-linux-musl/release/celesto-ci-cache-proxy'
traces=(Path('/dev/shm') if Path('/dev/shm').is_dir() else root)/(root.name+'-qualification');traces.mkdir(mode=0o700)
size=16*1024**2;chunk=b'x'*65536;scenario='headers';refreshes=0
class Handler(BaseHTTPRequestHandler):
 protocol_version='HTTP/1.1'
 def log_message(self,*args):pass
 def do_POST(self):
  global refreshes
  self.rfile.read(int(self.headers.get('Content-Length','0')))
  link=f'http://127.0.0.1:{self.server.server_port}/archive?mode={scenario}&sig=fake-signed-url-secret'
  if self.path.endswith('/celesto/download-url'):
   refreshes+=1;time.sleep(.4);answer={'url':link,'expiresIn':60}
  else:answer={'ok':True,'matched_key':'timing','signed_download_url':link,'celestoDownload':{'entryId':'timing-probe','sizeBytes':str(size),'expiresIn':1 if scenario=='refresh' else 60,'ticket':'fake-ticket-secret'}}
  raw=json.dumps(answer).encode();self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(raw)
 def do_GET(self):
  mode=parse_qs(urlsplit(self.path).query)['mode'][0]
  if mode=='headers':time.sleep(.4)
  self.send_response(206);self.send_header('Content-Length',str(size));self.send_header('Content-Range',f'bytes 0-{size-1}/{size}');self.send_header('ETag','"probe"');self.send_header('cf-ray','qualification-ray');self.end_headers()
  for index in range(size//len(chunk)):
   self.wfile.write(chunk);self.wfile.flush()
   if mode=='body' and index==0:time.sleep(.4)
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
threading.Thread(target=server.serve_forever,daemon=True).start()
with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
env={**os.environ,'CELESTO_EXPERIMENT_PROXY_TIMING_DIR':str(traces)}
log=open(root/'qualification.private.log','w')
proxy=subprocess.Popen([str(binary),'--listen',f'127.0.0.1:{port}','--api-url',f'http://127.0.0.1:{server.server_port}/cache','--host-provider','qualification','--entitlement-file',str(root/'absent-proof'),'--results-url-file',str(root/'absent-results-url')],env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
def connection():return http.client.HTTPConnection('127.0.0.1',port,timeout=10)
def lookup():
 c=connection();c.request('POST','/twirp/github.actions.results.api.v1.CacheService/GetCacheEntryDownloadURL',body=json.dumps({'key':'timing','version':'v1'}),headers={'Authorization':'Bearer fake-credential-secret','Content-Type':'application/json'});r=c.getresponse();assert r.status==200;answer=json.loads(r.read());c.close();url=urlsplit(answer['signed_download_url']);assert url.port==port and '/download/' in url.path;return url.path
def download(path,identifier,pause=False):
 c=connection();c.request('GET',path,headers={'Range':f'bytes=0-{size-1}','x-celesto-cache-native-download':'1','x-celesto-experiment-range-id':identifier});r=c.getresponse();assert r.status==206
 h=hashlib.sha256();n=0
 if pause:time.sleep(.4)
 while data:=r.read(65536):h.update(data);n+=len(data)
 c.close();assert n==size and h.hexdigest()==hashlib.sha256(chunk*(size//len(chunk))).hexdigest()
 for _ in range(150):
  p=traces/f'range-{identifier}.json'
  if p.exists():
   try:return json.loads(p.read_text())
   except json.JSONDecodeError:pass
  time.sleep(.02)
 raise AssertionError('Timing receipt missing')
receipts=[]
try:
 for _ in range(100):
  assert proxy.poll() is None
  try:
   with socket.create_connection(('127.0.0.1',port),timeout=.1):break
  except OSError:time.sleep(.05)
 else:raise AssertionError('Qualification proxy not ready')
 for case in ['headers','body','consumer']:
  scenario=case;path=lookup();r=download(path,'probe-'+case,pause=case=='consumer');receipts.append(r)
  if case=='headers':assert r['upstream_requests'][0]['headers_wait_ns']>=300_000_000,'Injected header delay not measured'
  if case=='body':assert r['body']['max_pending_wait_ns']>=300_000_000,'Injected R2 body delay not measured'
  if case=='consumer':assert r['body']['max_consumer_gap_ns']>=250_000_000,'Downstream pause not measured separately'
 scenario='refresh';path=lookup();time.sleep(.6)
 with ThreadPoolExecutor(max_workers=2) as pool:
  pair=list(pool.map(lambda name:download(path,name),['probe-refresh-a','probe-refresh-b']))
 receipts+=pair
 assert refreshes==1 and sorted(r.get('refresh_count',0) for r in pair)==[0,1]
 assert max(r['link_lock_wait_ns'] for r in pair)>=300_000_000,'Shared refresh lock delay not measured'
 assert all(r['body']['bytes']==size for r in receipts)
 raw=json.dumps(receipts)
 assert all(secret not in raw for secret in ['fake-signed-url-secret','fake-ticket-secret','fake-credential-secret'])
 report={'passed':True,'cases':['delayed_headers','delayed_body','paused_consumer','shared_link_refresh'],'all_payload_bytes_and_sha256_verified':True,'no_capabilities_in_receipts':True,'receipts':receipts}
 (root/'results/timing-qualification.json').write_text(json.dumps(report,indent=2))
 print('Proxy timing qualification passed: header/body/downstream/refresh-lock delays separated through real HTTP; bytes and SHA-256 unchanged.')
finally:
 proxy.terminate();proxy.wait(timeout=10);log.close();server.shutdown();server.server_close()
