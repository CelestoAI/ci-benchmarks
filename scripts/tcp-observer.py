"""Linux INET_DIAG/TCP_INFO sampling. Socket metadata/counters only, never payload."""
from pathlib import Path
import gzip,json,os,re,resource,signal,socket,struct,subprocess,sys,time

FIELDS=['state','ca_state','retransmits','probes','backoff','options','rto','ato','snd_mss','rcv_mss','unacked','sacked','lost','retrans','fackets','last_data_sent','last_ack_sent','last_data_recv','last_ack_recv','pmtu','rcv_ssthresh','rtt','rttvar','snd_ssthresh','snd_cwnd','advmss','reordering','rcv_rtt','rcv_space','total_retrans','pacing_rate','max_pacing_rate','bytes_acked','bytes_received','segs_out','segs_in','notsent_bytes','min_rtt','data_segs_in','data_segs_out','delivery_rate','busy_time','rwnd_limited','sndbuf_limited','delivered','delivered_ce','bytes_sent','bytes_retrans','dsack_dups','reord_seen','rcv_ooopack','snd_wnd','rcv_wnd','rehash','total_rto','total_rto_recoveries','total_rto_time','received_ce']
def layout(root):
 header=Path('/usr/include/linux/tcp.h').read_text();names=[n for n in FIELDS if re.search(r'\btcpi_'+n+r'\b',header)]
 code='#include <stdio.h>\n#include <stddef.h>\n#include <linux/tcp.h>\nint main(void){puts("{");\n'
 for index,n in enumerate(names):code+=f'printf("\\\"{n}\\\":[%zu,%zu]{"," if index<len(names)-1 else ""}\\n",offsetof(struct tcp_info,tcpi_{n}),sizeof(((struct tcp_info*)0)->tcpi_{n}));\n'
 code+='puts("}");return 0;}\n';source=root/'tcp-layout.c';source.write_text(code);binary=root/'tcp-layout'
 subprocess.run(['cc','-O2',str(source),'-o',str(binary)],check=True,capture_output=True)
 fields=json.loads(subprocess.check_output([str(binary)],text=True));(root/'results/tcp-layout.json').write_text(json.dumps({'fields':fields,'running_kernel':os.uname().release,'header_sha256':__import__('hashlib').sha256(header.encode()).hexdigest(),'byteorder':sys.byteorder},indent=2));return fields

def inodes(pid):
 result=set()
 for fd in (Path('/proc')/str(pid)/'fd').iterdir():
  try:
   value=os.readlink(fd)
   if value.startswith('socket:['):result.add(int(value[8:-1]))
  except (OSError,ValueError):pass
 return result

class Diag:
 def __init__(self,fields,unix_path=None):self.fields=fields;self.unix_path=unix_path
 def decode(self,row):
  raw=bytes.fromhex(row.pop('info_hex'));row['info_len']=len(raw);row['tcp']={name:int.from_bytes(raw[o:o+n],sys.byteorder) for name,(o,n) in self.fields.items() if o+n<=len(raw)};return row
 def snapshot(self,pid):
  if pid!=os.getpid():
   assert self.unix_path is not None
   with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as sock:
    sock.settimeout(2);sock.connect(str(self.unix_path));pieces=[]
    while data:=sock.recv(262144):pieces.append(data)
   result=json.loads(b''.join(pieces));return [self.decode(row) for row in result['sockets']],False
  rows=[]
  for fd in (Path('/proc')/str(pid)/'fd').iterdir():
   try:
    link=os.readlink(fd)
    if not link.startswith('socket:['):continue
    copied=os.dup(int(fd.name))
    with socket.socket(fileno=copied) as sock:
     if sock.family!=socket.AF_INET:continue
     local=sock.getsockname();peer=sock.getpeername();raw=sock.getsockopt(socket.IPPROTO_TCP,socket.TCP_INFO,1024)
     cookie=int.from_bytes(sock.getsockopt(socket.SOL_SOCKET,57,8),sys.byteorder)
     import fcntl
     recv_q=struct.unpack('=i',fcntl.ioctl(sock,0x541B,struct.pack('=i',0)))[0];send_q=struct.unpack('=i',fcntl.ioctl(sock,0x5411,struct.pack('=i',0)))[0]
     row={'inode':os.fstat(sock.fileno()).st_ino,'cookie':[cookie&0xffffffff,cookie>>32],'local':'%s:%s'%local,'peer':'%s:%s'%peer,'recv_q':recv_q,'send_q':send_q,'info_hex':raw.hex()}
     rows.append(self.decode(row))
   except (OSError,ValueError):continue
  return rows,False

def global_counters():
 result={}
 for file in ['snmp','netstat']:
  lines=(Path('/proc/net')/file).read_text().splitlines()
  for a,b in zip(lines[::2],lines[1::2]):
   keys,values=a.split(),b.split()
   if keys[0] in ['Tcp:','TcpExt:','IpExt:']:result[keys[0][:-1]]={k:int(v) for k,v in zip(keys[1:],values[1:])}
 soft=[list(map(lambda x:int(x,16),line.split())) for line in Path('/proc/net/softnet_stat').read_text().splitlines()]
 result['softnet']={'processed':sum(x[0] for x in soft),'dropped':sum(x[1] for x in soft),'time_squeeze':sum(x[2] for x in soft)}
 result['interfaces']={}
 for interface in Path('/sys/class/net').iterdir():
  if interface.name=='lo':continue
  result['interfaces'][interface.name]={name:int((interface/'statistics'/name).read_text()) for name in ['rx_packets','rx_bytes','rx_errors','rx_dropped','rx_missed_errors','tx_errors','tx_dropped'] if (interface/'statistics'/name).exists()}
 return result

def collect(root,pid):
 fields=json.loads((root/'results/tcp-layout.json').read_text())['fields'];diag=Diag(fields,root/'tcp-info.sock');stop=False
 def halt(*_):
  nonlocal stop;stop=True
 signal.signal(signal.SIGTERM,halt);signal.signal(signal.SIGINT,halt)
 control=root/'tcp-control.json';trace_dir=Path(json.loads((root/'results/proxy-setup.json').read_text())['trace_dir'])
 output=trace_dir/'tcp-samples.jsonl.gz';samples=0;errors=0;max_lag=0;first=time.monotonic_ns();start_cpu=resource.getrusage(resource.RUSAGE_SELF);windows=set()
 ready=root/'results/tcp-collector-ready.json';ready.write_text(json.dumps({'pid':os.getpid(),'proxy_pid':pid,'sample_interval_ms':100,'output_dir':str(trace_dir),'method':'TCP_INFO read inside the proxy, private Unix IPC, exact tuple/cookie; no packet payload.'}));os.chmod(ready,0o644)
 stream=None;current_trial=None;window_count=0;path=None
 def close_window():
  nonlocal stream,current_trial,window_count
  if stream is not None:
   stream.close();os.chmod(path,0o644)
   end_ack=root/'results'/f'tcp-window-end-{current_trial}.json';temporary=end_ack.with_suffix('.tmp');temporary.write_text(json.dumps({'trial':current_trial,'samples':window_count,'output':str(path),'ended_mono_ns':time.monotonic_ns()}));os.chmod(temporary,0o644);temporary.replace(end_ack)
   stream=None;current_trial=None;window_count=0
 while not stop:
  begun=time.monotonic_ns()
  try:
   state=json.loads(control.read_text()) if control.exists() else {}
   trial=state.get('trial') if state.get('active') else None
   if trial!=current_trial:
    close_window()
    if trial is not None:
     current_trial=trial;path=trace_dir/f'tcp-{trial}.jsonl.gz';stream=gzip.open(path,'wt',compresslevel=1)
   if trial is not None:
    rows,interrupted=diag.snapshot(pid);rows=[r for r in rows if r['peer'].endswith(':443')];stamp=time.monotonic_ns();counters=global_counters()
    stream.write(json.dumps({'mono_ns':stamp,'trial':trial,'query_ns':stamp-begun,'dump_interrupted':interrupted,'sockets':rows,'global':counters},separators=(',',':'))+'\n');samples+=1;window_count+=1
    if trial not in windows:
     stream.flush();ack=root/'results'/f'tcp-window-{trial}.json';ack.write_text(json.dumps({'trial':trial,'initial_mono_ns':stamp,'sockets':len(rows),'collector_pid':os.getpid()}));os.chmod(ack,0o644);windows.add(trial)
  except Exception as error:
   errors+=1
   if stream is not None:stream.write(json.dumps({'mono_ns':time.monotonic_ns(),'error_type':type(error).__name__})+'\n');stream.flush()
  spent=(time.monotonic_ns()-begun)/1e9;max_lag=max(max_lag,max(0,spent-.1));time.sleep(max(0,.1-spent))
 close_window()
 end=resource.getrusage(resource.RUSAGE_SELF);report={'samples':samples,'errors':errors,'windows':sorted(windows),'wall_s':(time.monotonic_ns()-first)/1e9,'cpu_user_s':end.ru_utime-start_cpu.ru_utime,'cpu_system_s':end.ru_stime-start_cpu.ru_stime,'max_interval_overrun_s':max_lag,'payload_captured':False};out=root/'results/tcp-collector-summary.json';out.write_text(json.dumps(report,indent=2));os.chmod(out,0o644)

if __name__=='__main__':
 root=Path(sys.argv[2])
 if sys.argv[1]=='layout':layout(root)
 elif sys.argv[1]=='collect':collect(root,int(sys.argv[3]))
 else:raise ValueError('Unsupported operation')
