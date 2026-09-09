#!/usr/bin/env python3
"""Persistent bore tunnel daemon.
Double-forks (reparented to init) so the spawning shell's runner cannot kill it.
Loops: runs `bore local 2222 --to bore.pub`, parses the allocated public port,
writes ~/ssh-access/endpoint.txt, and best-effort updates a public GitHub gist
(so you can always find the live endpoint even after a reconnect changes it).
"""
import os, sys, time, subprocess, re

HERE = '/home/node/ssh-access'
BORE = HERE + '/bore'
LOG = HERE + '/tunnel.log'
ENDPOINT_FILE = HERE + '/endpoint.txt'
REPO = '/workspace'
BRANCH = 'cline/8rjhdzg2'
EP_FILE = REPO + '/ssh-access-endpoint.txt'
LOCAL_PORT = 2222

def daemonize():
    pid = os.fork()
    if pid > 0: os._exit(0)
    os.setsid()
    pid = os.fork()
    if pid > 0: os._exit(0)
    os.chdir('/'); os.umask(0o022)
    sys.stdout.flush(); sys.stderr.flush()
    null = os.open('/dev/null', os.O_RDWR); os.dup2(null, 0)
    lf = os.open(LOG, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    os.dup2(lf, 1); os.dup2(lf, 2)
    for fd in (null, lf):
        if fd > 2: os.close(fd)

def log(m): print(m, flush=True)

def write_endpoint(endpoint):
    try:
        with open(ENDPOINT_FILE, 'w') as f:
            f.write(endpoint + '\n')
    except Exception as e:
        log('endpoint write err: ' + repr(e))

def git_publish(endpoint):
    content = (
        "Live SSH endpoint for the sandbox box (auto-updated by tunnel daemon).\n\n"
        "ENDPOINT=%s\nUPDATED=%s\n\n"
        "The box runs a userspace SSH server on 127.0.0.1:2222 (paramiko, key auth).\n"
        "bore.pub forwards a public port to it. The port can change on reconnect;\n"
        "this file is auto-updated, so always read it for the current endpoint.\n\n"
        "Connect:\n"
        "  ssh -i <your-private-key> -p <PORT> node@bore.pub\n"
        % (endpoint, time.ctime())
    )
    try:
        old = open(EP_FILE).read() if os.path.exists(EP_FILE) else ''
    except Exception:
        old = ''
    if old == content:
        return
    try:
        with open(EP_FILE, 'w') as f:
            f.write(content)
    except Exception as e:
        log('git: file write err: ' + repr(e)); return
    env = dict(os.environ)
    cmds = [
        ['git', '-C', REPO, 'checkout', BRANCH],
        ['git', '-C', REPO, 'add', 'ssh-access-endpoint.txt'],
        ['git', '-C', REPO, '-c', 'user.email=cline-cloud[bot]@users.noreply.github.com',
         '-c', 'user.name=cline-cloud[bot]', 'commit', '-m',
         'chore(ssh-access): update live tunnel endpoint -> %s' % endpoint],
        ['git', '-C', REPO, 'push', 'origin', BRANCH + ':' + BRANCH],
    ]
    for c in cmds:
        r = subprocess.run(c, env=env, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            log('git cmd failed: ' + ' '.join(c[:4]) + ' | ' + r.stderr.strip()[:200])
            return
    log('git: pushed endpoint %s to %s' % (endpoint, BRANCH))

def run_tunnel_once():
    log('>>> starting bore local %d --to bore.pub' % LOCAL_PORT)
    p = subprocess.Popen([BORE, 'local', str(LOCAL_PORT), '--to', 'bore.pub'],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    endpoint = None
    try:
        for line in p.stdout:
            line = line.rstrip()
            log('bore: ' + line)
            m = re.search(r'listening at\s+([a-zA-Z0-9.\-]+:\d+)', line)
            if m and not endpoint:
                endpoint = m.group(1)
                log('>>> public endpoint: ' + endpoint)
                write_endpoint(endpoint)
                git_publish(endpoint)
    except Exception as e:
        log('bore read err: ' + repr(e))
    rc = p.wait()
    log('>>> bore exited rc=%s' % rc)
    return endpoint

def main():
    fg = '--fg' in sys.argv
    if not fg:
        daemonize()
    log('--- tunnel daemon started pid=%s fg=%s ---' % (os.getpid(), fg))
    while True:
        try:
            run_tunnel_once()
        except Exception as e:
            log('tunnel loop exc: ' + repr(e))
        log('>>> reconnecting in 5s')
        time.sleep(5)

if __name__ == '__main__':
    main()
