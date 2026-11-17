"""Qualify Linux TCP_INFO through real sockets, including isolated loss when netem exists."""
from pathlib import Path
import hashlib,importlib.util,json,os,socket,subprocess,sys,threading,time
root=Path(sys.argv[1]);spec=importlib.util.spec_from_file_location('observer',Path(__file__).with_name('tcp-observer.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
fields=m.layout(root);diag=m.Diag(fields);amount=4*1024**2;payload=b'x'*1024
def receive(sock):
 local='%s:%s'%sock.getsockname();peer='%s:%s'%sock.getpeername();samples=[];received=[];failure=[]
 def reader():
  h=hashlib.sha256();n=0
  try:
   while data:=sock.recv(65536):h.update(data);n+=len(data)
   received.append((n,h.hexdigest()))
  except Exception as error:failure.append(type(error).__name__)
 thread=threading.Thread(target=reader);thread.start()
 while thread.is_alive():
  rows,interrupted=diag.snapshot(os.getpid());assert not interrupted
  samples.extend({'mono_ns':time.monotonic_ns(),**r} for r in rows if r['local']==local and r['peer']==peer);time.sleep(.03)
 thread.join();sock.close();assert not failure and received==[(amount,hashlib.sha256(payload*(amount//len(payload))).hexdigest())]
 assert samples and any(r['tcp'].get('rtt',0)>0 for r in samples)
 assert max(r['tcp'].get('bytes_received',0) for r in samples)>=amount,'Kernel byte counter/tuple mapping mismatch'
 return samples

listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen();port=listener.getsockname()[1]
def serve():
 c,_=listener.accept();c.sendall(payload*64);time.sleep(.4);c.sendall(payload*(amount//len(payload)-64));time.sleep(.15);c.close();listener.close()
threading.Thread(target=serve,daemon=True).start();clean=receive(socket.create_connection(('127.0.0.1',port),timeout=15))
report={'basic_passed':True,'known_bytes_and_sha256_verified':True,'netlink_exact_socket_tuple_verified':True,'clean_rtt_us_max':max(r['tcp']['rtt'] for r in clean),'clean_bytes_received_max':max(r['tcp']['bytes_received'] for r in clean),'clean_samples':clean,'loss_test':{}}
label='ctcp'+str(os.getpid());host='cth'+str(os.getpid());peer='ctp'+str(os.getpid());server=None;netem=False
def cmd(*args):
 r=subprocess.run(list(args),capture_output=True,text=True)
 if r.returncode:raise RuntimeError(' '.join(args[:3])+': '+r.stderr[:300])
try:
 assert os.geteuid()==0
 cmd('ip','netns','add',label)
 cmd('ip','link','add',host,'type','veth','peer','name',peer)
 cmd('ip','link','set',peer,'netns',label)
 cmd('ip','addr','add','198.18.0.1/30','dev',host);cmd('ip','link','set',host,'up')
 cmd('ip','netns','exec',label,'ip','addr','add','198.18.0.2/30','dev',peer);cmd('ip','netns','exec',label,'ip','link','set',peer,'up')
 cmd('ip','netns','exec',label,'tc','qdisc','add','dev',peer,'root','netem','delay','10ms','loss','2%');netem=True
 sender_report=root/'results/tcp-loss-sender.json'
 code="""import json,socket,sys,time
from pathlib import Path
fields=json.loads(Path(sys.argv[1]).read_text())['fields']
s=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind(('198.18.0.2',49091));s.listen();c,_=s.accept();c.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
for _ in range(4096):c.sendall(b'x'*1024);time.sleep(.0005)
time.sleep(.3);raw=c.getsockopt(socket.IPPROTO_TCP,socket.TCP_INFO,1024);out={k:int.from_bytes(raw[o:o+n],sys.byteorder) for k,(o,n) in fields.items() if o+n<=len(raw)}
Path(sys.argv[2]).write_text(json.dumps(out));time.sleep(.15);c.close();s.close()
"""
 with open(root/'tcp-loss-server.private.log','w') as log:server=subprocess.Popen(['ip','netns','exec',label,'python3','-c',code,str(root/'results/tcp-layout.json'),str(sender_report)],stdout=log,stderr=subprocess.STDOUT)
 sock=None
 for _ in range(100):
  try:sock=socket.create_connection(('198.18.0.2',49091),timeout=2);sock.settimeout(60);break
  except OSError:time.sleep(.05)
 assert sock is not None,'Isolated loss server not ready'
 lossy=receive(sock);server.wait(timeout=5);assert server.returncode==0
 sender=json.loads(sender_report.read_text());ooo=max(r['tcp'].get('rcv_ooopack',0) for r in lossy)
 assert sender['total_retrans']>0 and ooo>0,'Injected receive-path loss was not detected'
 report['loss_test']={'supported':True,'passed':True,'injection':'Only isolated namespace veth egress:10ms delay,2% loss; real VM eth0/R2 path untouched.','server_total_retrans':sender['total_retrans'],'client_rcv_ooopack_max':ooo,'client_total_retrans_max':max(r['tcp']['total_retrans'] for r in lossy),'client_rtt_us_max':max(r['tcp']['rtt'] for r in lossy),'samples':lossy}
except RuntimeError as error:
 if netem:raise
 report['loss_test']={'supported':False,'reason':str(error),'passed':False}
finally:
 if server and server.poll() is None:server.terminate();server.wait(timeout=5)
 subprocess.run(['ip','link','delete',host],capture_output=True)
 subprocess.run(['ip','netns','delete',label],capture_output=True)
out=root/'results/tcp-qualification.json';out.write_text(json.dumps(report,indent=2));os.chmod(out,0o644)
print(json.dumps({'tcp_info_qualification_passed':True,'loss_test':{k:v for k,v in report['loss_test'].items() if k!='samples'}}))
