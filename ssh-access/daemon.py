#!/usr/bin/env python3
"""Double-fork daemon launcher: starts server.py as a true daemon
(reparented to init, own session, no controlling tty) so the spawning
shell's runner cannot reap/kill it when the launch command returns.
"""
import os, sys

SERVER = '/home/node/ssh-access/server.py'
LOG = '/home/node/ssh-access/server.log'

# First fork
pid = os.fork()
if pid > 0:
    os._exit(0)

# Become session leader (no controlling tty)
os.setsid()

# Second fork (so we can never reacquire a tty; reparented to init)
pid = os.fork()
if pid > 0:
    os._exit(0)

# Daemon child
os.chdir('/')
os.umask(0o022)

# Redirect std fds: stdin from /dev/null, stdout/stderr to the log (append)
sys.stdout.flush()
sys.stderr.flush()
null = os.open('/dev/null', os.O_RDWR)
os.dup2(null, 0)
logfd = os.open(LOG, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
os.dup2(logfd, 1)
os.dup2(logfd, 2)
for fd in (null, logfd):
    if fd > 2:
        os.close(fd)

# Write a marker so we know the daemon took over
print('--- daemon started %s ---' % os.getpid(), flush=True)

os.execvp('python3', ['python3', SERVER])
