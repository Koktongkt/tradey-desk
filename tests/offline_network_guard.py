"""Sticky per-interpreter external-network tripwire; not an OS/child sandbox."""
import atexit
import ipaddress
import os
import sys

_installed=False
_blocked=0

def install():
    global _installed
    if _installed:return
    _installed=True
    def local(host):
        if host is None or host in ('localhost','localhost.localdomain'):return True
        if isinstance(host,bytes):host=host.decode('ascii',errors='replace')
        try:return ipaddress.ip_address(host).is_loopback
        except (ValueError,TypeError):return False
    def guard(event,args):
        global _blocked
        target=None
        if event in ('socket.getaddrinfo','socket.gethostbyname','socket.gethostbyaddr'):target=args[0]
        elif event in ('socket.connect','socket.sendto'):
            address=args[-1]
            if isinstance(address,str) and address.startswith('/'):return
            target=address[0] if isinstance(address,tuple) else address
        else:return
        if not local(target):
            _blocked+=1
            raise RuntimeError('offline_external_network_forbidden')
    def report():
        print('OFFLINE_NETWORK_BOUNDARY unexpected_external_attempts='+str(_blocked),flush=True)
        if _blocked:os._exit(86)
    sys.addaudithook(guard);atexit.register(report)
