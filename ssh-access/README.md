# SSH access to the sandbox box

This directory holds the (secret-free) scripts that set up SSH access to a sandbox
box that has **no inbound reachability** (behind NAT) and **no root**.

## How it works (architecture)

1. **`server.py`** — a userspace SSH server (paramiko) running on `127.0.0.1:2222`,
   no root required. Authenticates with the ed25519 key whose pubkey is
   `client_ed25519.pub`, and (as a fallback) a random password written to
   `~/ssh-access/password.txt`. Spawns a real PTY shell (`/bin/bash -l`) for the
   `node` user.
2. **`daemon.py`** — double-fork launcher that execs `python3 server.py`,
   reparenting it to init so the sandbox runner cannot reap it.
3. **`tunnel.py --fg`** — a reconnect loop that runs `bore local 2222 --to bore.pub`
   to expose the local SSH server on a public `bore.pub:<PORT>` endpoint, and
   publishes the live endpoint to `ssh-access-endpoint.txt` on this branch
   (`cline/8rjhdzg2`) via `git commit && git push`.
4. **`tunnel_daemon.py`** — double-fork launcher that execs `python3 tunnel.py --fg`.

## Connect (from your machine)

Save the private key (provided separately) to e.g. `~/.ssh/box_ed25519` and
`chmod 600`. Then find the live port and connect:

```bash
# always-current endpoint (auto-updated if the tunnel reconnects and the port changes):
curl -s https://raw.githubusercontent.com/idreesmuhammadqazi-create/glmocr-box/cline/8rjhdzg2/ssh-access-endpoint.txt

# connect (replace <PORT> with the port from ENDPOINT=... above, e.g. 23119):
ssh -i ~/.ssh/box_ed25519 -p <PORT> node@bore.pub
```

e.g. `ssh -i ~/.ssh/box_ed25519 -p 23119 node@bore.pub`

## Notes / caveats

- The box is **ephemeral** ("may be torn down at any time"). The daemons persist
  only while the box is up; they are not restarted on reboot (no init/systemd).
- bore.pub's free tier allocates a **random public port** that can change if the
  tunnel drops. `tunnel.py` reconnects and re-publishes the new port, so always
  read the raw-URL file above for the current endpoint.
- Secrets (`client_ed25519` private key, `host_ed25519`, `password.txt`,
  `endpoint.txt`, the `bore` binary) live in `~/ssh-access/` on the box and are
  intentionally **not** committed here.
- To reproduce the runtime setup on the box (from a shell on the box):
  ```bash
  cd ~/ssh-access
  python3 daemon.py            # start the paramiko SSH server (detached)
  python3 tunnel_daemon.py    # start the bore tunnel + endpoint publisher (detached)
  ```
