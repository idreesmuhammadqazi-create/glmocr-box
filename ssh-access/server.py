#!/usr/bin/env python3
"""Userspace SSH server (no root required) using paramiko.
Gives a real interactive PTY shell as the current user.
Listens on 127.0.0.1:2222 and authenticates via an ed25519 pubkey (or password).
"""
import os, sys, socket, select, threading, struct, fcntl, termios, signal, pty, base64, time, traceback, secrets
import paramiko

HERE = os.path.dirname(os.path.abspath(__file__))
HOSTKEY_FILE = os.path.join(HERE, 'host_ed25519')
CLIENT_PUB = os.path.join(HERE, 'client_ed25519.pub')
LISTEN_HOST = '127.0.0.1'
LISTEN_PORT = 2222
SHELL = '/bin/bash'
PASSWORD = secrets.token_urlsafe(18)

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def load_client_pub_b64():
    with open(CLIENT_PUB) as f:
        parts = f.read().split()
    return parts[0], parts[1]  # ('ssh-ed25519', '<base64>')

class Server(paramiko.ServerInterface):
    def __init__(self, pub_name, pub_b64, password):
        self.pub_name = pub_name
        self.pub_b64 = pub_b64
        self.password = password
        self.event = threading.Event()
        self.pty = None
        self.winch = None
        self.shell_requested = False
        self.exec_command = None

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED if kind == 'session' else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def get_allowed_auths(self, username):
        return 'publickey,password'

    def check_auth_password(self, username, password):
        return paramiko.AUTH_SUCCESSFUL if password == self.password else paramiko.AUTH_FAILED

    def check_auth_publickey(self, username, key):
        try:
            if key.get_name() == self.pub_name and key.get_base64() == self.pub_b64:
                log(f"auth OK (pubkey) user={username}")
                return paramiko.AUTH_SUCCESSFUL
        except Exception:
            pass
        log(f"auth FAILED (pubkey) user={username}")
        return paramiko.AUTH_FAILED

    def check_channel_pty_request(self, channel, term, w, h, pw, ph, modes):
        self.pty = (term or 'xterm-256color', w or 80, h or 24)
        return True

    def check_channel_shell_request(self, channel):
        self.shell_requested = True
        self.event.set()
        return True

    def check_channel_exec_request(self, channel, command):
        self.shell_requested = True
        self.exec_command = command.decode() if isinstance(command, bytes) else command
        self.event.set()
        return True

    def check_channel_window_change_request(self, channel, w, h, pw, ph):
        self.winch = (w or 80, h or 24)
        return True

def handle_client(client, addr, host_key, pub_name, pub_b64, password):
    try:
        t = paramiko.Transport(client)
        t.set_hexdump(False)
        t.add_server_key(host_key)
        server = Server(pub_name, pub_b64, password)
        try:
            t.start_server(server=server)
        except paramiko.SSHException as e:
            log(f"SSH negotiate failed from {addr}: {e}")
            return
        chan = t.accept(30)
        if chan is None:
            log(f"No channel from {addr}")
            return
        server.event.wait(30)
        if not server.shell_requested:
            log(f"No shell from {addr}; closing")
            chan.close()
            return
        term, w, h = server.pty or ('xterm-256color', 80, 24)
        master, slave = pty.openpty()
        fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack('HHHH', h, w, 0, 0))
        is_exec = bool(server.exec_command)
        argv = ['/bin/bash', '-l'] if not is_exec else ['/bin/bash', '-lc', server.exec_command]
        pid = os.fork()
        if pid == 0:
            try:
                os.setsid()
                fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
                os.close(master)
                os.dup2(slave, 0); os.dup2(slave, 1); os.dup2(slave, 2)
                if slave > 2:
                    os.close(slave)
                os.environ['TERM'] = term
                os.environ['HOME'] = os.path.expanduser('~')
                os.environ['USER'] = os.environ.get('USER', 'node')
                os.environ['LANG'] = os.environ.get('LANG', 'C.UTF-8')
                try:
                    os.chdir(os.environ['HOME'])
                except Exception:
                    pass
                os.execvp(SHELL, argv)
            except Exception:
                traceback.print_exc()
                os._exit(127)
        os.close(slave)
        log(f"shell pid={pid} for {addr} term={term} {w}x{h}")
        client_eof = False
        fds = [master, chan]
        while True:
            r, _, _ = select.select(fds, [], [], 1)
            if master in r:
                try:
                    data = os.read(master, 65536)
                except OSError:
                    # pty master raises EIO when slave side (shell) exited -> treat as shell done
                    data = b''
                if data:
                    try:
                        chan.sendall(data)
                    except Exception:
                        break
                else:
                    # shell exited; flush + signal EOF to client
                    try:
                        chan.shutdown_write()
                    except Exception:
                        pass
                    try:
                        chan.send_exit_status(0)
                    except Exception:
                        pass
                    break
            if (not client_eof) and chan in r:
                try:
                    data = chan.recv(65536)
                except Exception:
                    data = b''
                if not data:
                    # client sent EOF on its input (no more stdin) -- keep relaying shell output
                    client_eof = True
                    fds = [master]
                else:
                    try:
                        os.write(master, data)
                    except OSError:
                        break
            if server.winch:
                w2, h2 = server.winch
                server.winch = None
                try:
                    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack('HHHH', h2, w2, 0, 0))
                except Exception:
                    pass
        try:
            os.kill(pid, signal.SIGHUP)
        except Exception:
            pass
        try:
            os.close(master)
        except Exception:
            pass
        try:
            chan.close()
        except Exception:
            pass
        log(f"session ended for {addr}")
    except Exception:
        log("handler error: " + traceback.format_exc())
    finally:
        try:
            client.close()
        except Exception:
            pass

def main():
    host_key = paramiko.Ed25519Key(filename=HOSTKEY_FILE)
    pub_name, pub_b64 = load_client_pub_b64()
    with open(os.path.join(HERE, 'password.txt'), 'w') as f:
        f.write(PASSWORD + '\n')
    os.chmod(os.path.join(HERE, 'password.txt'), 0o600)
    log(f"listening on {LISTEN_HOST}:{LISTEN_PORT}; auth=pubkey+password")
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((LISTEN_HOST, LISTEN_PORT))
    s.listen(50)
    while True:
        try:
            client, addr = s.accept()
        except KeyboardInterrupt:
            break
        log(f"connection from {addr}")
        threading.Thread(target=handle_client, args=(client, addr, host_key, pub_name, pub_b64, PASSWORD), daemon=True).start()

if __name__ == '__main__':
    main()
