#!/usr/bin/env python3
"""List/inspect a remote ZIP via HTTP range requests (no full download)."""
import sys, struct, subprocess

def get(url, start, end):
    out = subprocess.run(["curl","-sL","--fail","-r",f"{start}-{end}",url],
                         capture_output=True)
    if out.returncode: raise SystemExit(f"curl failed {out.returncode}: {out.stderr[:200]}")
    return out.stdout

def size(url):
    out = subprocess.run(["curl","-sIL",url], capture_output=True, text=True).stdout
    n=None
    for line in out.splitlines():
        if line.lower().startswith("content-length:"):
            n=int(line.split(":")[1].strip())
    return n

def tail(url, n=131072):
    sz=size(url)
    start=max(0,sz-n)
    return get(url,start,sz-1), sz

def find_eocd(buf):
    i=len(buf)-22
    while i>=0:
        if buf[i:i+4]==b'PK\x05\x06':
            return i
        i-=1
    return -1

def main(url):
    buf,sz = tail(url)
    i=find_eocd(buf)
    if i<0: raise SystemExit("no EOCD found (zip64? or not a zip)")
    cd_size, cd_off = struct.unpack('<II', buf[i+12:i+20])
    if cd_off==0xFFFFFFFF or cd_size==0xFFFFFFFF:
        # zip64
        zi=buf.rfind(b'PK\x06\x06')
        cd_size,cd_off = struct.unpack('<QQ', buf[zi+40:zi+56])
    cd = get(url, cd_off, cd_off+cd_size-1)
    p=0; entries=[]
    while p < len(cd)-4 and cd[p:p+4]==b'PK\x01\x02':
        (ver,verneed,flags,method,mtime,mdate,crc,csize,usize,
         nlen,elen,clen,disk,iattr,eattr,off)=struct.unpack('<HHHHHHIIIHHHHHII', cd[p+4:p+46])
        name=cd[p+46:p+46+nlen].decode('utf-8','replace')
        entries.append((name,csize,usize,method,off))
        p += 46+nlen+elen+clen
    print(f"# {url}\n# total size: {sz/1e6:.1f} MB   entries: {len(entries)}")
    tot=0
    for name,csize,usize,method,off in sorted(entries):
        tot+=csize
        print(f"{usize:>12} {csize:>12}  {name}")
    print(f"# sum compressed: {tot/1e6:.1f} MB")

if __name__=="__main__":
    main(sys.argv[1])
