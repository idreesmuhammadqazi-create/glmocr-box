#!/usr/bin/env python3
"""Double-fork launcher for the tunnel (mirrors daemon.py, which is proven to
detach and survive the runner). Execs `python3 tunnel.py --fg` so the external
double-fork handles reparenting-to-init, and tunnel.py's --fg skips its own
daemonize.
"""
import os, sys

LOG = '/home/node/ssh-access/tunnel.log'

pid = os.fork()
if pid > 0:
    os._exit(0)
os.setsid()
pid = os.fork()
if pid > 0:
    os._exit(0)
os.chdir('/')
os.umask(0o022)
sys.stdout.flush(); sys.stderr.flush()
null = os.open('/dev/null', os.O_RDWR)
os.dup2(null, 0)
logfd = os.open(LOG, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
os.dup2(logfd, 1)
os.dup2(logfd, 2)
for fd in (null, logfd):
    if fd > 2:
        os.close(fd)
os.execvp('python3', ['python3', '/home/node/ssh-access/tunnel.py', '--fg'])
