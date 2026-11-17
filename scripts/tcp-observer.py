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
 def __init__(self,fields):
  self.fields=fields;self.sequence=0;self.socket=socket.socket(socket.AF_NETLINK,socket.SOCK_DGRAM,4);self.socket.bind((0,0));self.socket.settimeout(2)
 def snapshot(self,pid):
  owned=inodes(pid);self.sequence+=1
  request=struct.pack('=BBBBI',socket.AF_INET,socket.IPPROTO_TCP,1|2|8|64,0,0xffffffff)+b'\0'*40+struct.pack('=II',0xffffffff,0xffffffff)
  self.socket.sendto(struct.pack('=IHHII',16+len(request),20,1|0x300,self.sequence,0)+request,(0,0))
  rows=[];interrupted=False
  while True:
   data=self.socket.recv(1024*1024);pos=0
   while pos+16<=len(data):
    length,kind,flags,seq,_=struct.unpack_from('=IHHII',data,pos);assert length>=16;payload=data[pos+16:pos+length];pos+=(length+3)&~3
    if seq!=self.sequence:continue
    interrupted|=bool(flags&16)
    if kind==3:return rows,interrupted
    if kind==2:
     error=struct.unpack_from('=i',payload)[0]
     if error:raise OSError(-error,os.strerror(-error))
     continue
    if kind!=20 or len(payload)<72:continue
    inode=struct.unpack_from('=I',payload,68)[0]
    if inode not in owned:continue
    sport,dport=struct.unpack_from('!HH',payload,4)
    if not dport:continue
    row={'inode':inode,'cookie':list(struct.unpack_from('=II',payload,44)),'local':socket.inet_ntop(socket.AF_INET,payload[8:12])+':'+str(sport),'peer':socket.inet_ntop(socket.AF_INET,payload[24:28])+':'+str(dport),'state':payload[1],'timer':payload[2],'timer_retrans':payload[3],'expires_ms':struct.unpack_from('=I',payload,52)[0],'recv_q':struct.unpack_from('=I',payload,56)[0],'send_q':struct.unpack_from('=I',payload,60)[0]}
    offset=72
    while offset+4<=len(payload):
     size,attribute=struct.unpack_from('=HH',payload,offset);assert size>=4;value=payload[offset+4:offset+size];offset+=(size+3)&~3
     if attribute==2:
      row['info_len']=len(value);row['tcp']={name:int.from_bytes(value[o:o+n],sys.byteorder) for name,(o,n) in self.fields.items() if o+n<=len(value)}
     elif attribute==4:row['congestion']=value.rstrip(b'\0').decode('ascii','replace')
     elif attribute==7:row['skmem']=list(struct.unpack('='+str(len(value)//4)+'I',value))
    rows.append(row)

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
 fields=json.loads((root/'results/tcp-layout.json').read_text())['fields'];diag=Diag(fields);stop=False
 def halt(*_):
  nonlocal stop;stop=True
 signal.signal(signal.SIGTERM,halt);signal.signal(signal.SIGINT,halt)
 control=root/'tcp-control.json';trace_dir=Path(json.loads((root/'results/proxy-setup.json').read_text())['trace_dir'])
 output=trace_dir/'tcp-samples.jsonl.gz';samples=0;errors=0;max_lag=0;first=time.monotonic_ns();start_cpu=resource.getrusage(resource.RUSAGE_SELF);windows=set()
 ready=root/'results/tcp-collector-ready.json';ready.write_text(json.dumps({'pid':os.getpid(),'proxy_pid':pid,'sample_interval_ms':100,'output_dir':str(trace_dir),'method':'INET_DIAG_INFO for proxy-owned socket inodes, exact tuple/cookie; no packet payload.'}));os.chmod(ready,0o644)
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
