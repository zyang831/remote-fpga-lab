# Mender OTA (Open Source, docker-compose) + Tailscale on Ubuntu — Complete Single-Board Eval/Dev Setup Guide

## TL;DR

- **This is fully achievable today** with a Mender Server v4.1.x docker-compose evaluation stack (Traefik-based) on one Ubuntu 24.04/26.04 host, a `mender-client4` board, and Tailscale providing the private network plus a real Let's Encrypt TLS certificate for the server's MagicDNS name — no port forwarding required.
- The biggest version-specific gotchas: (1) the Mender server repo was consolidated into `github.com/mendersoftware/mender-server` and v4 uses **Traefik**, not the old nginx `mender-api-gateway` (so the old `ALLOWED_HOSTS` env var and `docker.mender.io` cert volume mounts no longer apply); (2) the v4 compose stack has **no single "custom domain + cert" env var** — you set `MENDER_HOSTNAME` and drop your cert into `compose/certs/`; (3) the client package is `mender-client4` with systemd services `mender-authd`/`mender-updated` (not `mender-client`).
- Tailscale does **not** provide WAN uplink failover; you get that on the board with NetworkManager route metrics (Ethernet < WiFi < hotspot), while Tailscale silently re-establishes the tunnel (direct → DERP relay) over whichever uplink wins.
- **[2026-07 update] board-01 now has a real second uplink.** A USB WiFi dongle (AIC8800D80 chipset) is bring-up'd and working on board-01 — see §4.1 below. It requires an out-of-tree driver and a mode-switch quirk on every power cycle, both handled by an installed udev rule, so from Mender's/Tailscale's point of view it behaves like an ordinary NetworkManager-managed WiFi connection once up.

## Key Findings

**Current versions (verified July 2026):**

- **Ubuntu LTS:** 26.04 LTS "Resolute Raccoon" — per Canonical's official announcement (lists.ubuntu.com, 2026-04-23) it was released April 23, 2026 and "will continue to receive security updates and critical bug fixes for five years" (i.e., to April 2031). Direct 24.04→26.04 upgrades are only enabled at the 26.04.1 point release (scheduled August 6, 2026). 24.04 LTS "Noble Numbat" remains fully supported and is the safer, more battle-tested choice for an eval box. [assumption] This guide targets Ubuntu Server 24.04 LTS as the primary, with 26.04 notes where they differ.
- **Mender Server (Open Source):** latest is **v4.1.2** (released 2026-07-09). The official docs pin `v4.1.0` in their clone command (verbatim on docs.mender.io: `git clone -b v4.1.0 https://github.com/mendersoftware/mender-server.git mender-server` … `export MENDER_IMAGE_TAG=v4.1.0`); v4.1.2 is two patch releases newer and drop-in compatible.
- **Mender Client:** the `mender-client4` Debian meta-package ships the 4.x/5.x client generation; latest confirmed released is **5.0.3** (components `mender-auth`, `mender-update` — corroborated on Mender Hub, where a user reports "mender-client4 which had the mender-update component, mender-update --version 5.0.3"). The package name is `mender-client4` even though it installs client 5.x — the "4" denotes the post-4.0 split architecture.
- **[2025-11] APT repo relocation gotcha:** the device APT repo moved from `downloads.mender.io/repos/debian` to `downloads.mender.io/repos/device-components`. The old path returns HTTP 403. Use the new path.

**Architecture decision (why Tailscale cert on the host):** Run `tailscale cert` on the *host* for the host's own MagicDNS name (e.g. `mender-host.tailXXXX.ts.net`), mount that cert into Traefik, set `MENDER_HOSTNAME` to the same name, and point the board's `ServerURL` at `https://mender-host.tailXXXX.ts.net`. Because the cert is a genuine Let's Encrypt cert issued through Tailscale, the board validates it against the system CA bundle with **no** custom `ServerCertificate` needed on the client — this is much cleaner than the old self-signed `keys-generated/cert.crt` provisioning flow.

---

## Details

Assumptions and conventions used throughout:

- [assumption] Host MagicDNS name: `mender-host.tailXXXX.ts.net`; board name: `board-01`. Substitute your real tailnet name (find it on the DNS page of the admin console).
- **Tailscale plan:** the free **Personal plan is sufficient.** Note that under Tailscale's "pricing v4" update (official blog, April 8, 2026) the Personal plan now "supports up to six users—the same limit Personal Plus had" and removed the device cap entirely ("no limit on the number of user-owned devices"). (The older "3 users / 100 devices" figure is pre-April-2026.) You need a Tailscale account with an identity-provider login.
- Commands assume `sudo`/root where noted. Both machines are amd64 or arm64.
- **board-01 network interfaces (confirmed 2026-07):** `eth0` (onboard, always present) + `wlx<mac>` (USB WiFi dongle, AIC8800D80 chipset — up only after driver + mode-switch, see §4.1) + `tailscale0` (once Tailscale is up). No `wlan0` — the dongle's interface keeps its `wlx`-prefixed MAC-derived name because the driver's udev rename rule only targets a different USB ID (CUDY WU900), not this dongle's `a69c:8d80`.

---

## PART 1 — HOST / SERVER SETUP (Ubuntu machine)

### 1.1 Prerequisites: Docker Engine + Compose plugin, resources

**Minimum resources for the Mender demo stack** (verbatim from docs.mender.io "Evaluation with Docker Compose"): "Architectures: x86_64, arm64 · 16 GiB RAM · 2 vCPUs · 50 GiB storage available for the containers. MongoDB 5.0+ requires a CPU with AVX support… a CPU type `x86-64-v3` is recommended." Software: Docker Engine ≥ v1.20 (i.e., current) and **Docker Compose ≥ v2.23.1** (the mender-server README/docs state: "Mender Server requires Docker Compose version v2.23.1 or newer").

> Gotcha: The 16 GiB figure is the documented minimum for the full eval stack (Mongo, NATS, MinIO, all microservices, GUI, Traefik). A board eval will run comfortably; do not try this on a 4 GiB VM — Mongo/NATS will OOM. (By contrast, a production Kubernetes install needs only "at least 4 GB of RAM, 4 vCPUs and 10 GB for the persistent volumes" per worker node — the compose eval stack is intentionally heavier because it packs everything onto one host.)

**Install Docker from the official apt repo (not snap, not Ubuntu's `docker.io`):**

```bash
# 1. Remove any distro/conflicting packages
for pkg in docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc; do
  sudo apt-get remove -y $pkg 2>/dev/null
done

# 2. Add Docker's official GPG key
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

# 3. Add the repository (uses your Ubuntu codename automatically: noble=24.04, resolute=26.04)
sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
sudo apt-get update

# 4. Install Engine + CLI + containerd + Buildx + Compose plugin
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# 5. Verify
sudo docker run hello-world
docker compose version   # must report v2.23.1 or newer

# 6. (Optional) run docker without sudo
sudo usermod -aG docker $USER && newgrp docker
```

> Package-name gotcha: Docker's repo uses `docker-compose-plugin` (invoked as `docker compose`). Ubuntu's repo uses `docker-compose-v2`. Do not mix the two families. On Ubuntu 26.04, cgroup v1 is removed and `/tmp` is tmpfs by default — neither affects Mender but is worth knowing for container debugging.

### 1.2 Install Tailscale on the host, enable MagicDNS + HTTPS certs

```bash
# Install (official script; auto-detects apt and adds Tailscale's repo)
curl -fsSL https://tailscale.com/install.sh | sh

# Bring up with a stable hostname; --ssh optional for admin convenience
sudo tailscale up --hostname=mender-host
```

Authenticate at the printed URL. Then, in the **Tailscale admin console** (https://login.tailscale.com/admin):

1. **DNS page** → ensure **MagicDNS** is enabled (default-on for tailnets created after 2022-10-20).
2. **DNS page → HTTPS Certificates → Enable HTTPS.** Acknowledge the notice that machine names + tailnet DNS name are published to the public Certificate Transparency ledger.
3. Note your tailnet name (shown on the DNS page), e.g. `tailXXXX.ts.net`. Your host's FQDN is `mender-host.tailXXXX.ts.net`.

Provision the certificate **on the host**:

```bash
# Run from a working directory you control, e.g. ~/mender-tls
mkdir -p ~/mender-tls && cd ~/mender-tls
sudo tailscale cert mender-host.tailXXXX.ts.net
# Produces: mender-host.tailXXXX.ts.net.crt  and  mender-host.tailXXXX.ts.net.key
```

> Gotcha: `tailscale cert` only works after HTTPS is enabled in the console AND MagicDNS is on. The cert is a real Let's Encrypt cert (90-day expiry) — see §1.4/Recommendations for renewal.

### 1.3 Obtain the Mender Open Source server (current repo/method)

The server is now consolidated in **`github.com/mendersoftware/mender-server`** (the old `mendersoftware/integration` layout and the nginx `mender-api-gateway` are legacy). The v4 stack uses **Traefik v3** as the API gateway.

```bash
cd ~
# Clone a pinned tag. Docs pin v4.1.0; v4.1.2 is the current latest patch.
git clone -b v4.1.2 https://github.com/mendersoftware/mender-server.git mender-server
cd mender-server
export MENDER_IMAGE_TAG=v4.1.2
```

> Gotcha: This docker-compose composition is **evaluation-only** per Mender. The README states verbatim: "We strongly advise using the helm chart for production setups. This docker composition is only meant for evaluation purposes." That is fine and expected for a single-board dev/eval deployment. The default demo brings up self-signed certs for `docker.mender.io`; we replace that below.

### 1.4 Serve Mender over the Tailscale domain (custom domain + real TLS)

This is the part with the most version drift. **In the v4.x compose stack there is no single "custom domain + cert" environment variable.** There are two independent levers:

- **`MENDER_HOSTNAME`** — the public hostname baked into every Traefik router rule. The compose file templates each rule as `Host(\`${MENDER_HOSTNAME:-docker.mender.io}\`) || Host(\`localhost\`) ...`.
- **Traefik's TLS file provider** — the cert Traefik serves is defined in `compose/config/traefik/tls.yaml`, and cert files live in `compose/certs/` (bind-mounted read-only to `/etc/traefik/certs` in the Traefik container). The demo cert/key are `compose/certs/mender.crt` and `compose/certs/mender.key`.

The Traefik service in v4.x is defined (abridged, verbatim keys) as:

```yaml
  traefik:
    image: traefik:v3.6.13
    command:
      - --entrypoints.websecure.address=:443
      - --entrypoints.websecure.http.tls=true
      - --entrypoints.websecure.asDefault=true
      - --providers.file.directory=/etc/traefik/config
      - --providers.docker=true
      - --providers.docker.exposedByDefault=false
    volumes:
      - ./compose/config/traefik:/etc/traefik/config:ro
      - ./compose/certs:/etc/traefik/certs:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
    ports:
      - 443:443
      - 80:80
```

**Simplest working approach — overwrite the demo cert files (Option A):**

```bash
cd ~/mender-server
# Copy the Tailscale-issued cert/key onto the filenames tls.yaml already references
sudo cp ~/mender-tls/mender-host.tailXXXX.ts.net.crt compose/certs/mender.crt
sudo cp ~/mender-tls/mender-host.tailXXXX.ts.net.key compose/certs/mender.key
```

Because `compose/config/traefik/tls.yaml` already points the default store at `/etc/traefik/certs/mender.crt` + `mender.key`, no further TLS edit is needed. The `tls.yaml` uses standard Traefik v3 dynamic-config syntax:

```yaml
tls:
  stores:
    default:
      defaultCertificate:
        certFile: /etc/traefik/certs/mender.crt
        keyFile: /etc/traefik/certs/mender.key
  certificates:
    - certFile: /etc/traefik/certs/mender.crt
      keyFile: /etc/traefik/certs/mender.key
```

**Explicit approach (Option B):** keep your files under their own names in `compose/certs/` and edit `compose/config/traefik/tls.yaml` to reference `/etc/traefik/certs/mender-host.tailXXXX.ts.net.crt` and `.key`. Traefik's file provider watches `/etc/traefik/config` and reloads on change.

**Set the hostname and the hard-coded fallbacks via an override** so you never edit the tracked compose file. Create `docker-compose.override.yml`:

```yaml
# ~/mender-server/docker-compose.override.yml
services:
  mender-deployments:
    environment:
      DEPLOYMENTS_PRESIGN_URL_HOSTNAME: "mender-host.tailXXXX.ts.net"
      DEPLOYMENTS_AWS_EXTERNAL_URI: "https://mender-host.tailXXXX.ts.net"
  workflows-worker:
    environment:
      WOKRFLOWS_MENDER_URL: "https://mender-host.tailXXXX.ts.net"   # NB: "WOKRFLOWS" typo is in the upstream file — keep it
```

Then export the hostname before starting:

```bash
export MENDER_HOSTNAME=mender-host.tailXXXX.ts.net
```

> Gotchas: (1) The `WOKRFLOWS_MENDER_URL` misspelling is literally in the upstream compose — copy it exactly or the override won't match. (2) `DEPLOYMENTS_PRESIGN_URL_HOSTNAME`/`DEPLOYMENTS_AWS_EXTERNAL_URI` default to `docker.mender.io`/`s3.docker.mender.io`; if you skip them, artifact downloads (presigned MinIO URLs) will hand the device an unreachable hostname and deployments will fail at the download step even though auth/inventory work. (3) Since everything is single-host and reached over the tailnet, you do not need a separate `s3.` name — routing all of it through the one MagicDNS host is fine for eval.

### 1.5 Bring it up, verify, create the admin user

```bash
cd ~/mender-server
export MENDER_IMAGE_TAG=v4.1.2
export MENDER_HOSTNAME=mender-host.tailXXXX.ts.net

docker compose up -d

# Watch health
docker compose ps
docker compose logs -f traefik        # Ctrl-C when you see it serving :443
```

Create the initial admin user (v4.1.x form, from the docs — one-off container via `run`):

```bash
MENDER_USERNAME=admin@example.com
MENDER_PASSWORD='PleaseReplaceWithASecurePassword'
docker compose run --name create-user useradm create-user \
  --username "$MENDER_USERNAME" --password "$MENDER_PASSWORD"
```

(Equivalent alternative if `useradm` is already running: `docker compose exec useradm useradm create-user --username ... --password ...` — note `useradm` appears twice: service name then binary.)

From a Tailscale-connected browser, open **`https://mender-host.tailXXXX.ts.net`** and log in. Because the cert is a real Let's Encrypt cert for that exact name, there should be **no** browser warning (unlike the demo self-signed default).

Verify containers are healthy:

```bash
docker compose ps          # every service Up / healthy
# The gateway is Traefik; there is no nginx mender-api-gateway in v4.
```

### 1.6 Firewall / UFW on the host

Key facts:

- The board reaches the server **over the tailnet only** — you do **not** need to expose 443 to the public internet. This is the main security win of the Tailscale approach.
- **Docker bypasses UFW** by writing its own iptables rules (published container ports are reachable regardless of UFW `deny`). Do not rely on UFW alone to "close" 443.

Recommended posture for an eval host:

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow in on tailscale0                 # trust the tailnet interface
sudo ufw allow 22/tcp                            # SSH (or restrict to tailscale0 too)
sudo ufw enable
```

Tailscale itself needs only **outbound 443** to the coordination/DERP servers and, for direct connections, **outbound UDP 41641** (open it inbound too if you want to favor direct over relayed). To actually prevent public reach of Docker-published ports, either bind Mender's Traefik to the tailscale interface or add a `DOCKER-USER` iptables rule; for eval, keeping the host off any public IP (or behind a NAT with no forward) plus `ufw` is typically sufficient. [assumption] Your eval host is not on a public IP with inbound 443 forwarded.

---

## PART 2 — CLIENT / BOARD SETUP (Ubuntu board)

### 2.1 Install Tailscale, pre-auth key, boot persistence

Generate a **reusable pre-auth key** in the admin console: **Settings → Keys → Generate auth key** (https://login.tailscale.com/admin/settings/keys). Choose **Reusable** (and optionally Ephemeral=off so the node persists). Copy the `tskey-auth-…` value.

On the board:

```bash
curl -fsSL https://tailscale.com/install.sh | sh

# Enable the daemon at boot and bring the node up non-interactively
sudo systemctl enable --now tailscaled
sudo tailscale up --authkey=tskey-auth-XXXXXXXXXXXX --hostname=board-01
```

`tailscaled` is enabled as a systemd service by the installer; `systemctl enable --now tailscaled` guarantees boot persistence. Credentials are stored locally so the node reconnects automatically on reboot.

Verify:

```bash
tailscale status         # should list board-01 and mender-host with 100.x addresses
tailscale ip -4
```

> **Gotcha (de25-nano / boards with trimmed kernels): `tailscaled` crash-loops with `503 Service Unavailable: no backend`.**
> `tailscale up` fails immediately after `enable --now` with `failed to connect to local tailscaled ... 503 Service Unavailable: no backend`, and `systemctl status tailscaled` shows a high restart counter. Root cause: `journalctl -u tailscaled -n 50` shows `router: ... could not setup netfilter: could not get iptables version: exit status 1`, and `sudo iptables --version` shows `Failed to initialize nft: Protocol not supported` — the board's kernel has no `nf_tables` support, so the iptables-nft backend tailscaled defaults to can't init, and the daemon dies before its backend comes up.
>
> Fix: switch the host to the legacy iptables backend, which doesn't touch nftables:
>
> ```bash
> sudo update-alternatives --set iptables /usr/sbin/iptables-legacy
> sudo update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy
> sudo iptables --version   # should print "(legacy)", no nft error
> sudo systemctl restart tailscaled
> sudo tailscale up --authkey=tskey-auth-XXXXXXXXXXXX --hostname=board-01
> ```
>
> If `update-alternatives --list iptables` has no `iptables-legacy` entry (package not installed) or the kernel lacks `ip_tables.ko` too, skip netfilter setup entirely instead: add `FLAGS="--netfilter-mode=off"` to `/etc/default/tailscaled`, then restart. This forgoes MASQUERADE/subnet-router features tailscaled would otherwise manage, which a plain client-only board (this guide's setup) doesn't need.

### 2.2 Install the Mender client (current method)

Set up the **new** device-components APT repo and install `mender-client4`:

```bash
# Dependencies
sudo apt-get update
sudo apt-get install -y --no-install-recommends apt-transport-https ca-certificates curl gnupg jq

# Mender GPG key (verify fingerprint E6C8 5734 5575 F921 8396 5662 2407 2B80 A1B2 9B00)
curl -fsSL https://downloads.mender.io/repos/debian/gpg | sudo tee /etc/apt/trusted.gpg.d/mender.asc >/dev/null
gpg --show-keys --with-fingerprint /etc/apt/trusted.gpg.d/mender.asc

# Remove any stale old-repo lines
sudo sed -i.bak -e "\,https://downloads.mender.io/repos/device-components,d" /etc/apt/sources.list 2>/dev/null || true

# Add the device-components repo for your Ubuntu release (match your board's actual codename,
# check with `lsb_release -c` — do not assume 24.04 just because that's the guide's target):
# Ubuntu 22.04 (jammy):
echo "deb [arch=$(dpkg --print-architecture)] https://downloads.mender.io/repos/device-components ubuntu/jammy/stable main" \
  | sudo tee /etc/apt/sources.list.d/mender.list
# Ubuntu 24.04 (noble): replace 'jammy' with 'noble'
# Ubuntu 26.04 (resolute): replace 'jammy' with 'resolute'

sudo apt-get update
sudo apt-get install -y mender-client4
```

Alternatively the convenience script: `curl -fLsS https://get.mender.io -o get-mender.sh` then (after inspecting it) `sudo bash get-mender.sh mender-client4`.

> Gotchas: (1) Old guides use `mender-client` (the pre-4.0 Go client) — that's a different, legacy package. Use **`mender-client4`**. (2) The `/repos/debian` device path is dead (403); you must use `/repos/device-components`. (3) The GPG key URL is still under `/repos/debian/gpg` even though the package repo moved — that's correct. (4) **Codename mismatch breaks dependency resolution, not the apt-get update step.** `apt-get update` succeeds fine against the wrong codename's repo (it's a valid repo, just for a different release) — the failure only shows up at `apt-get install` as unmet deps like `libc6 (>= 2.38) but 2.35-... is to be installed`. On a jammy (22.04) board, pointing at `ubuntu/noble/stable` pulls packages built against glibc 2.38+/libstdc++ 13+, which jammy's 2.35/12.3 base can't satisfy — confirmed on a de25-nano board (jammy) in 2026-07: switching the repo line to `ubuntu/jammy/stable` fixed it immediately, no OS upgrade needed. Always verify with `lsb_release -c` on the actual board before picking the repo suffix.

### 2.3 Configure `/etc/mender/mender.conf`

Use `mender-setup` (the standalone tool in 4.x/5.x; on clients < 4.0 it was `mender setup`). For a self-hosted **open-source** server with a CA-valid cert, you point at the server URL and need **no** tenant token and **no** custom server cert:

```bash
DEVICE_TYPE="board-01-eval"
SERVER_URL="https://mender-host.tailXXXX.ts.net"

sudo mender-setup \
  --device-type "$DEVICE_TYPE" \
  --server-url "$SERVER_URL" \
  --server-cert=""
```

Then hand-tune `/etc/mender/mender.conf` for WAN-failover resilience. A complete open-source config:

```json
{
  "ServerURL": "https://mender-host.tailXXXX.ts.net",
  "UpdatePollIntervalSeconds": 1800,
  "InventoryPollIntervalSeconds": 28800,
  "RetryPollIntervalSeconds": 300,
  "RetryPollCount": 10
}
```

Executable command:
```bash
sudo jq '. + {
  "UpdatePollIntervalSeconds": 1800,
  "InventoryPollIntervalSeconds": 28800,
  "RetryPollIntervalSeconds": 300,
  "RetryPollCount": 10
}' /etc/mender/mender.conf | sudo tee /etc/mender/mender.conf.tmp >/dev/null && sudo mv /etc/mender/mender.conf.tmp /etc/mender/mender.conf

```

Field notes (from Mender docs):

- **`TenantToken` is NOT needed** for open-source/self-hosted — it's a hosted-Mender/multi-tenant concept. Omit it.
- **`UpdatePollIntervalSeconds`: 1800** (30 min) — documented production default. Demo mode uses far more aggressive values; don't ship those.
- **`InventoryPollIntervalSeconds`: 28800** (8 h) — documented default.
- **`RetryPollIntervalSeconds`: 300** — max backoff between retries when contacting the server. Minimum enforced value is 60 s (anything lower is ignored and treated as 60). Backoff starts at 60 s, doubles every 3 failures up to this ceiling.
- **`RetryPollCount`: 10** — max attempts per server contact before giving up that cycle. If 0/unset, the client computes `3 * ceil(log2(RetryPollIntervalSeconds) + 1)`. Setting it explicitly (e.g. 10) gives predictable, resilient behavior across a WAN failover window. Introduced in client 3.3+.

> Resilience rationale: With a 5-minute retry ceiling and 10 retries, a transient uplink switch (Ethernet→WiFi→hotspot) will not fail an in-flight authorization/poll — the client keeps retrying across the ~minutes-long window it takes routes to re-converge and Tailscale to re-establish. Because the ServerURL is a stable MagicDNS name, the IP the client dials is constant regardless of which uplink is active. This window is now a real path on board-01, not hypothetical — see §4.1: on power cycle the WiFi uplink is briefly absent until the dongle's udev-triggered mode switch completes, which is exactly the kind of transient gap this retry config is meant to survive.

### 2.4 Restart / enable the correct systemd services

In client 4.0+ the monolithic `mender`/`mender-client` was split into two daemons: **`mender-authd`** (auth/server comms) and **`mender-updated`** (update engine). The `mender-client` service no longer exists on `mender-client4`.

```bash
sudo systemctl enable mender-authd mender-updated
sudo systemctl restart mender-authd mender-updated

# Verify
systemctl is-active mender-authd     # active
systemctl is-active mender-updated   # active
systemctl is-enabled mender-authd    # enabled
```

> Gotcha: Any older script that does `systemctl restart mender-client` or `journalctl -u mender-client` will silently do nothing useful on a 4.x/5.x device. Use `mender-authd`/`mender-updated`. Logs: `journalctl -u mender-updated -f` and `journalctl -u mender-authd -f`.

### 2.5 Device authentication / acceptance workflow

On first start the client generates an RSA/EC keypair, POSTs an auth request, and the server records it as **pending** (HTTP 401 to the device until accepted). To accept:

**Via UI:** Open `https://mender-host.tailXXXX.ts.net` → **Devices → Pending** → select the device → inspect its identity → **Accept**. It moves to the accepted group and begins reporting inventory within an inventory-poll cycle.

**Via API / mender-cli (optional automation):** authenticate to the management API and PUT the auth set status to `accepted`. mender-cli (`mender-cli login`, then the devices endpoints) or a raw `curl` against `/api/management/v2/devauth/devices/{id}/auth/{aid}/status` with body `{"status":"accepted"}` both work. For a single eval board the UI is fastest; the API path matters if you preauthorize at manufacture time.

> Note: For fully hands-off onboarding you can **preauthorize** — submit the device's identity + public key before it boots so it flips straight to accepted. That's optional for a single board.

### 2.6 Stable device identity (fix: device re-pends on every reboot)

> **Gotcha (de25-nano, confirmed 2026-07): board re-appears as a new pending device after every reboot.** Root cause: the stock `/usr/share/mender/identity/mender-device-identity` script keys device identity off the `eth0` MAC address, and this board's MAC is locally-administered (randomized) each boot — confirmed via `sh /usr/share/mender/identity/mender-device-identity` returning a different `mac=` value pre/post reboot (e.g. `fa:1a:...`, first-octet low bit set = locally-administered). Since Mender's device ID is derived from identity data, a changed MAC means a brand-new device record every reboot.

Fix: repoint the identity script at an immutable, boot-stable ID instead of the MAC. `/etc/machine-id` works if it survives reboot on your image (verify first — some stateless/overlay rootfs images regenerate it every boot, in which case use a hardware-burned ID like the eMMC CID instead: `cat /sys/block/mmcblk0/device/cid`).

```bash
# 1. verify /etc/machine-id is stable — run, reboot, run again, diff
cat /etc/machine-id

# 2. back up and patch the identity script
sudo cp /usr/share/mender/identity/mender-device-identity /usr/share/mender/identity/mender-device-identity.bak

sudo tee /usr/share/mender/identity/mender-device-identity > /dev/null << 'EOF'
#!/bin/sh
set -ue
echo "mac=$(cat /etc/machine-id)"
EOF
sudo chmod +x /usr/share/mender/identity/mender-device-identity

# 3. verify output, then re-trigger auth
sh /usr/share/mender/identity/mender-device-identity
sudo systemctl restart mender-authd
journalctl -u mender-authd -f
```

> Note: identity is read by **`mender-authd`**, not `mender-updated` — restarting the wrong daemon (or a nonexistent `mender-client.service`) does nothing. `systemctl list-units --type=service | grep -i mender` shows the real unit names on 4.x/5.x (`mender-authd`, `mender-updated`).
>
> Why this fix also protects the WiFi path (§4.1): the `wlx<mac>`-named dongle interface's MAC is a real, stable hardware MAC (unlike `eth0`'s randomized one on this board), so it was never the source of the re-pending bug — but it's worth confirming your identity script isn't accidentally keyed off whichever interface happens to be up first if you ever add a third uplink. Keying off `/etc/machine-id` (interface-independent) sidesteps that class of bug entirely.

After this, reboot and confirm in the UI the board keeps its **same** device ID and stays Accepted — no new pending row. Reject/decommission any stale duplicate device records accumulated from prior reboots. This edit lives on the running rootfs only; if the board image is rebuilt/reflashed, bake the same identity-script change into the image (meta-layer/rootfs overlay) so it isn't lost.

---

## PART 3 — END-TO-END VERIFICATION CHECKLIST

Run these in order; each isolates one layer.

**1. Tailscale connectivity (both directions):**

```bash
# On the board:
tailscale status              # mender-host listed, shows 'active; direct ...' or 'relay ...'
tailscale ping mender-host    # 'pong ... via <ip>:<port>' = direct; 'via DERP(xxx)' = relayed
```

Either direct or relay is fine functionally; direct is lower-latency. Run `tailscale ping` a few times — Tailscale keeps attempting NAT traversal, so a connection that starts on DERP may upgrade to direct. If it stays on DERP, both ends are likely behind hard/symmetric NAT — traffic still flows. `tailscale netcheck` diagnoses NAT type.

**2. TLS cert validity from the board (independent of Mender):**

```bash
# Should complete the handshake with no verify error and show your MagicDNS CN/SAN:
echo | openssl s_client -connect mender-host.tailXXXX.ts.net:443 -servername mender-host.tailXXXX.ts.net 2>/dev/null \
  | openssl x509 -noout -subject -issuer -dates
# Issuer should be Let's Encrypt; dates within the 90-day window.
curl -sSf https://mender.example.ts.net/ >/dev/null && echo "TLS+HTTP OK"
```

If `curl` fails with a cert error, MagicDNS/HTTPS isn't fully propagated or you copied the wrong cert into `compose/certs/`.

**3. Mender client authenticating + polling over the Tailscale name:**

```bash
# On the board:
journalctl -u mender-authd -f
#  -> expect 'authorized' / successful auth once you Accept in the UI
journalctl -u mender-updated -f
#  -> expect periodic 'update check' / inventory submission with no x509 or DNS errors
```

In the UI the device shows **accepted** and its **inventory** tab populates (hostname, device_type, network). That confirms the full path: board → tailnet → MagicDNS → Traefik(TLS) → useradm/deviceauth/inventory.

**3b. Identity stability across reboot:** reboot the board, then repeat the identity check — confirm the device stays the same accepted record instead of re-appearing pending (see §2.6 if it doesn't).

**3c. WiFi uplink smoke test (§4.1) — do not skip, and verify the DATA PATH not just the link:** with Ethernet unplugged (or `nmcli con down "Wired connection 1"`), confirm the dongle is in WiFi mode (`ip -br link show | grep wlx` shows the interface; `nmcli -t -f DEVICE,STATE dev` shows it `connected`), then repeat checks 1–3 above over WiFi only. **Critical:** do not trust `connected`+valid-IP alone — check the receive path with `ping -I wlx<mac> <gateway-ip>` and `ip neigh show <gateway-ip> dev wlx<mac>` (expect 0% loss and `REACHABLE`). On board-01 an earlier run of this test failed and went offline ~6 min (§4.2); that was the driver RX buffer-pool leak, since fixed (§4.4). A dead RX path shows `FAILED`/`Destination Host Unreachable` and looks exactly like AP L2 isolation — if you see that on the patched driver, check `sudo dmesg | grep rxbuff` and §4.4 before blaming the AP.

**4. Deployment smoke test (optional but recommended):** upload/deploy a trivial application (e.g. a `deb` or docker-compose update-module artifact) to confirm the **download** step works — this is what catches a missing `DEPLOYMENTS_PRESIGN_URL_HOSTNAME` override (auth/inventory can be green while downloads 404 on `docker.mender.io`).

---

## PART 4 — WAN FAILOVER RESILIENCE (board side)

Tailscale rides on top of whatever default route exists; it does **not** choose or fail over your physical uplink. Give the board deterministic uplink preference with **route metrics** (lower metric = higher priority): Ethernet best, WiFi next, cellular/hotspot last.

> **Board gotcha (de25-nano, confirmed 2026-07):** this guide originally assumed **netplan**, but the de25-nano's Ubuntu image has no `/etc/netplan/` and no `netplan` binary at all — `sudo netplan try` fails with `netplan: command not found`. Networking on this board is managed by **NetworkManager** (`systemctl is-active NetworkManager` → `active`; `systemd-networkd` → `inactive`). Use `nmcli`, not netplan, on this board.

### 4.1 WiFi uplink now live: AIC8800D80 USB dongle (board-01, confirmed 2026-07)

Earlier revisions of this guide noted board-01 had no `wlan0`/WiFi interface until a dongle was attached. That dongle is now bring-up'd and working — this section replaces that placeholder.

**Hardware/driver summary:**

- Dongle chipset: **AIC8800D80** (USB VID `a69c`, PID `5723` in its default fake-CD-ROM boot mode, SCSI model string `AIC flash`). No mainline Linux driver exists — this required an out-of-tree build.
- **Mode switch (required every power cycle):** the dongle enumerates as USB mass storage on plug-in and must be kicked into WiFi mode with `sudo usb_modeswitch -v a69c -p 5723 -KQ`, which flips it to `a69c:8d80` ("AIC Wlan"). A generic `sg_raw` vendor-CDB trigger does **not** work on this PID variant (that trick is specific to a different bootloader PID, `1111:1111`) — confirmed by direct testing, not just docs.
- **Driver source:** built from `github.com/Xanderful/aic8800d80` (a fork of `goecho/aic8800_linux_drvier`, patched for kernel 6.15+ compatibility). Cross-compiled on the workstation against the board's exact kernel source tree (kept at `/home/<user>/coredla_work/de25_nano_bringup/linux`, matching the board's running `uname -r` commit) using `aarch64-linux-gnu-gcc-13` — no need to ship a full kernel tree onto the board itself.
- **Two local patches beyond upstream are required** (both must be applied on every rebuild):
  - **(a) Build patch — `rwnx_radar.c`:** guards an extra `link_id` parameter to `cfg80211_cac_event()` behind a `LINUX_VERSION_CODE >= 6.15.0` check, but this board's 6.12.11 kernel tree already carries the newer function signature (the vendor SoC tree backported that wireless-core change ahead of its version tag). The guard misfires and the build fails with "too few arguments" unless forced on (`#if 1`, both occurrences). Re-check this if the board's kernel is ever rebuilt/updated — it's about actual header content, not the reported kernel version string.
  - **(b) Functional patch — RX buffer-pool leak (`aicwf_txrxif.c`, REQUIRED for a working data path):** without this the WiFi associates and gets DHCP but the data path goes dead ~72s later — this was the real cause of every "connects then goes silent" symptom (full root-cause in §4.4). In `aicwf_process_rxframes()`, the `aicwf_usb_rx_aggr` + `CONFIG_PREALLOC_RX_SKB` branch bails on a routine `if (pkt_len > 1600)` with `return -EBADE`, which aborts the whole rxq drain while the URB-completion path keeps allocating fresh pool buffers — exhausting the fixed 1000-buffer prealloc pool in ~72s (`rxbuff list is empty` / `failed to alloc rxbuff` flood in dmesg, `rx_packets` frozen). **Fix:** change that `return -EBADE;` to `break;` (drop the rest of the corrupt aggregated buffer; the existing end-of-loop `aicwf_prealloc_rxbuff_free()` returns the buffer to the pool and the outer loop keeps draining). Keep `CONFIG_PREALLOC_RX_SKB=y` — do **not** try to fix this by disabling prealloc (see §4.4 for why that's a dead end).
- **Persistence across reboot/replug:** the dongle resets to mass-storage mode on every power loss, so the mode switch above must be re-triggered automatically. Installed `/etc/udev/rules.d/aic.rules` (from the driver repo's `tools/aic.rules`), matching `KERNEL=="sd*", idVendor=="a69c", idProduct=="5723"` and running `eject /dev/%k` — `eject` re-triggers the same SCSI-level mode switch. Requires the `eject` package (not installed by default on this image). No `modules-load.d` entry needed: once the `.ko` is `depmod`'d, the WiFi PID's modalias auto-loads the driver normally.
- **Interface name:** comes up as `wlx<mac>` (e.g. `wlx6c1ff78b5bf8`) — **not** `wlan0`. The driver repo's udev rename rule only targets the CUDY WU900's `368b:8d81` ID, not this dongle's `a69c:8d80`, so it keeps the kernel-default MAC-derived name. Use the actual `wlx...` name (check with `ip -br link show`) in every `nmcli`/route command below — don't assume `wlan0`.

> **Practical implication for failover:** because the mode switch happens via udev on device (re-)enumeration, there's a short window after power-on or dongle replug where the interface doesn't exist yet — WiFi is not "instant-on" the way Ethernet is. This is exactly the kind of transient the retry/backoff config in §2.3 (`RetryPollIntervalSeconds`/`RetryPollCount`) is meant to ride out; it isn't a new failure mode, just confirmation the existing config choice matters in practice on this hardware.

**Set the metric on the existing wired connection:**

```bash
# 1. Find the NetworkManager connection profile bound to eth0
nmcli -t -f NAME,DEVICE con show
#  -> e.g. "Wired connection 1:eth0"

# 2. Set its route metric explicitly (100 = preferred/primary uplink)
sudo nmcli con mod "Wired connection 1" ipv4.route-metric 100
sudo nmcli con up "Wired connection 1"

# 3. Verify
ip route   # default route via eth0 should show "metric 100"
```

**WiFi uplink (dongle from §4.1) — set up the connection profile and give it a higher (lower-priority) metric:**

```bash
# 0. Confirm the dongle is in WiFi mode and named as expected (see §4.1)
ip -br link show                          # look for wlx<mac>, not wlan0
nmcli -t -f DEVICE,STATE dev              # wlx<mac> should show as 'disconnected' or 'connected', not 'unavailable'

# 1. Create/connect the WiFi profile (first time only — replace SSID/password)
sudo nmcli dev wifi connect "YOUR_SSID" password "YOUR_PASSWORD" ifname wlx<mac>

# 2. Find the resulting connection profile name
nmcli -t -f NAME,DEVICE con show

# 3. Set its metric higher than Ethernet's (200 = fallback uplink)
sudo nmcli con mod "YOUR_SSID" ipv4.route-metric 200
sudo nmcli con up "YOUR_SSID"

# 4. A third uplink (e.g. USB cellular hotspot), if added later, would get ipv4.route-metric 300
```

```bash
# Verify both routes coexist with the expected priority
ip route
#  default via <gw> dev eth0 metric 100
#  default via <gw> dev wlx<mac> metric 200
```

When the primary drops **and the fallback uplink actually has a working path to the internet**, the kernel falls back to the next-lowest metric automatically; Tailscale re-establishes over the new path (briefly via DERP, then upgrading to direct if possible), and because the Mender `ServerURL` is a stable MagicDNS name, the client's retry loop (§2.3) transparently rides through the switch. That qualifier is not hypothetical — see §4.2, a real failure of exactly this assumption caught on board-01.

> Notes/caveats: (1) `nmcli con mod ... ipv4.route-metric` works for both DHCP and static NetworkManager profiles — no separate syntax needed for static IPs (unlike the netplan case). (2) Pure metric-based failover switches on *link* loss, not on "internet is up but this uplink is black-holing." For true dead-gateway detection you'd add `keepalived` or a health-check script that adjusts metrics — **this is not optional out-of-scope polish, it's the actual gap that bit board-01, see §4.2.** (3) Metrics give preference, not load-balancing. (4) If a future board/image in this family *does* ship netplan (e.g. a stock Ubuntu Server 24.04 install rather than the vendor de25-nano image), the original netplan approach applies instead — check `dpkg -l | grep -iE 'networkd|network-manager|netplan'` and `systemctl is-active systemd-networkd NetworkManager` first to pick the right tool before assuming either. (5) **The dongle's driver/mode-switch setup (§4.1) is a per-board, per-image concern** — if board-01's rootfs is rebuilt or reflashed, the udev rule, the built `.ko`, and its `depmod` registration all need to be re-baked in (or the driver rebuilt against the new kernel tree), or the dongle silently reverts to appearing as a USB mass-storage device with no WiFi interface at all.

### 4.2 CRITICAL — metrics configured correctly but WiFi failover confirmed broken on board-01 (tested 2026-07-23)

> **⚠️ SUPERSEDED 2026-07-24 — the root cause diagnosed in this section was WRONG. See §4.4 for the real cause and the fix.** The gateway-`FAILED`/`Destination Host Unreachable` symptom recorded below is real, but it was **not** AP client-isolation/VLAN. It was the driver's RX buffer-pool leak: the data path (RX) goes dead ~72s after association, so the board sends ARP requests but never *receives* the replies — which looks identical to "the AP isn't bridging us." Once the RX leak is fixed (§4.1 patch (b) / §4.4), the same `pinkdolphin1` network reaches gateway `192.168.68.1` fine over WiFi (`ping -I wlx<mac> <gw>` 0% loss, `ip neigh` → `REACHABLE`). The AP was never the problem. The forensic record below is kept intact because the *test method* (pull Ethernet, check `ip neigh` on the WiFi dev) is still the correct way to validate, and because it shows how a dead-RX data path masquerades as an L2 isolation problem.

**Do not consider §4.1's config sufficient. It was applied exactly as documented and then live-tested by pulling Ethernet, and the board went dark for ~6 minutes.** This is the actual test, not a hypothetical — recording it in full because it invalidates the "transparently rides through the switch" claim above for this specific network.

**What was done:** `ipv4.route-metric` set to 100 (eth0, "Wired connection 1") and 200 (`wlx6c1ff78b5bf8`, connection `pinkdolphin1`), confirmed via `nmcli -g ipv4.route-metric con show` and `ip route` showing both default routes with the correct priority — exactly matching §4.1's commands. Then `sudo nmcli con down "Wired connection 1"` was run to simulate a physical Ethernet loss.

**What happened:** the board dropped off Tailscale entirely (`tailscale status` → `offline`) for ~6 minutes. `journalctl -u tailscaled` during the outage showed continuous DERP/bootstrap-DNS failures (`network is unreachable`, `no route to host`) on *every* region tried, over both IPv4 and IPv6 — i.e. genuinely no working path out, not just a slow reconnect. The board only came back when `eth0` itself reactivated on its own (NetworkManager's autoconnect retried the DHCP transaction and got a fresh lease ~5m53s later — confirmed via `dhcp6 (eth0): state changed new lease` in the NetworkManager journal). WiFi never carried the traffic, despite `wlx6c1ff78b5bf8` showing `connected` with a valid DHCP-assigned IP (`192.168.68.55/22`) and an installed default route the entire time.

**Root cause, confirmed by direct testing:**

```bash
ip neigh show 192.168.68.1
# 192.168.68.1 dev wlx6c1ff78b5bf8  FAILED
# 192.168.68.1 dev eth0 lladdr <MAC> REACHABLE
```

ARP resolution for the gateway **fails over the WiFi interface** and **succeeds over Ethernet**, even though both interfaces are configured on the same `192.168.68.0/22` subnet with the same gateway address. `curl --interface wlx6c1ff78b5bf8` and `ping -I wlx6c1ff78b5bf8` to `1.1.1.1` both confirmed `Destination Host Unreachable` while connected. In other words: the `pinkdolphin1` WiFi network hands out an IP in the same subnet as the wired LAN, but does **not** actually bridge to the same gateway at layer 2 — most likely AP client isolation, or the WiFi and wired ports are on separate switch/VLAN segments behind the router despite sharing one DHCP pool. This is a property of the router/AP, not of the board, the driver, or the `nmcli` config — §4.1's driver bring-up and the metric configuration are both correct and were not the problem.

**Why metrics alone couldn't have caught this:** route metrics only express *preference*; the kernel installs the WiFi default route and considers it valid because DHCP succeeded on that interface. Nothing in a plain `ip route` failover checks whether the next hop is actually reachable — that's exactly the "link is up but black-holing" gap flagged as caveat (2) above, and it is not theoretical here.

**Required fix before this network can be trusted for failover (not yet implemented — flagging for next session):** either (a) get the WiFi AP's client-isolation/VLAN setting fixed so `pinkdolphin1` clients can actually reach `192.168.68.1`, or (b) add a dead-gateway health check that demotes the WiFi route (or removes it) when ARP/ping to the gateway fails, e.g. a small systemd timer running `ip neigh show <gw> dev wlx<mac> | grep -q REACHABLE || nmcli con mod pinkdolphin1 ipv4.route-metric 900`. Until one of these is done, **do not rely on this board's WiFi as a real failover path** — it will silently hold a dead default route exactly like it did in this test.

**State left after this test:** both interfaces are back to normal (`eth0` and `wlx6c1ff78b5bf8` both `connected`, metrics 100/200 as configured, `ip route` showing both default routes). No further changes made — the board is in the same state §4.1's steps produce, which is precisely why the follow-up fix above is still needed.

### 4.3 FINAL VERDICT (2026-07-23, extended follow-up) — WiFi is not usable for failover on board-01 as of this session, for two independent, stacked reasons

> **⚠️ SUPERSEDED 2026-07-24 — both "stacked reasons" below are now resolved or reclassified; see §4.4.** Short version: (1) the AP-side gateway-unreachable blocker was a **misdiagnosis** — it was the same RX buffer-pool leak, not Deco isolation (proven: a laptop on `pinkdolphin1` reaches its gateway fine, and the board itself does too once patched). (2) The driver's `rxbuff` exhaustion — the one concrete, reproducible failure that actually killed the data path — is now **root-caused and fixed** (§4.1 patch (b) / §4.4), validated with a 110s ping + a 4000-packet flood at 0% loss and the pool never exhausting. The *only* driver issue still genuinely open is the intermittent `-110 err_lmac_reqs` init wedge on reconnect (§4.4), which affects re-association robustness, not steady-state throughput. The `attempt 1/2` writeups below are kept because they correctly rule out ARP-offload and document the scan-instability that blocked the control test — both still true, just no longer the whole story.

A full follow-up session chased §4.2's finding further, including a real code fix attempt and a control test. Neither closed the gap — recording both in full so the next session doesn't repeat them.

**Attempt 1 — ruled out driver ARP-offload as the cause.** `journalctl`/dmesg showed a `MM_SET_ARPOFFLOAD_REQ` firmware command timing out ~4s after a successful association, which looked like a plausible cause for the permanently-`INCOMPLETE`/`FAILED` gateway ARP. Traced it to `drivers/aic8800/aic8800_fdrv/Makefile:63` (`CONFIG_ARP_OFFLOAD = y`, hardcoded), rebuilt the driver with `make CONFIG_ARP_OFFLOAD=n` (command-line override wins over the in-Makefile default — confirmed via `nm` on the resulting `.ko` showing zero `arpoffload` symbols), cross-compiled against the board's kernel tree, deployed it (original backed up on-board at `.../aic8800/aic8800_fdrv.ko.bak-arpoffload`), reloaded, re-associated to `pinkdolphin1` — **`ping -I wlx<mac> 192.168.68.1` still gave `Destination Host Unreachable`, identical to before.** ARP offload was a red herring; the gateway-unreachable problem is unaffected by it. The no-ARP-offload build is still installed (harmless, arguably removes one instability source) but did not fix anything.

**Attempt 2 — control test with a personal hotspot to isolate Deco vs. board.** Plan: join the dongle to a phone hotspot instead of `pinkdolphin1` and check if the *same* gateway-unreachable pattern reproduces (would indict the board/driver) or not (would confirm it's Deco-specific). **Never completed** — the driver's own instability blocked the test itself: a `dev wifi rescan` mid-session hit the same `rxbuff` exhaustion bug from §4.1 (`failed to alloc rxbuff`, `rxbuff list is empty`), after which every scan just aborted (`rwnx_cfg80211_scan is scanning, abort`) and the hotspot SSID (confirmed broadcasting, visible to a laptop at the same time) never appeared in scan results on the board.

**Root-cause picture, revised:** there are **two separate, independent problems**, not one:

1. **AP-side (Deco/`pinkdolphin1`): gateway `192.168.68.1` unreachable from WiFi clients** (§4.2). Not fixed. No visible AP-isolation toggle found in the Deco app for this network (it's the main/only network, not a guest SSID) — newer Deco/HomeShield firmware may auto-isolate unrecognized-vendor devices without an explicit user-facing toggle. Unconfirmed; the hotspot control test that would have isolated this cause never completed (see above). **Do not assume this is fixed without re-testing** — it was never actually proven to be Deco's fault in isolation, only strongly suspected.
2. **Board/driver-side: the out-of-tree AIC8800D80 driver does not reliably survive repeated scan/connect/reload cycles**, independent of #1 and independent of any code change made this session. Confirmed failure modes, all reproduced multiple times across this session on **both** the stock driver and the no-ARP-offload rebuild:
   - `cmd queue crashed` (firmware command queue fault, e.g. triggered by an `nmcli con up` scan request)
   - `failed to alloc rxbuff` / `rxbuff list is empty` (RX buffer pool exhaustion, seen both on cold boot and mid-session after a rescan)
   - `MM_SET_STACK_START_REQ` timeout / `aicwf_usb_probe` `errno -110` on `rmmod`/`modprobe` reload (probe fails outright — this exact signature occurred on the *very first* reload attempt this session, before any source changes, so it predates and is unrelated to both the old DFS/`cfg80211_cac_event` kernel-signature patch and the new ARP-offload removal)
   - Scans intermittently missing an SSID that was visible seconds/minutes earlier from the same physical location, with no interface-level error reported

   **Only physical unplug/replug of the USB dongle reliably recovered from these** (full USB re-enumeration + fresh firmware load); `rmmod`/`modprobe` reload alone succeeded roughly half the time and left the interface in a broken state (`errno -110`, no `wlx*` interface at all) the rest.

**Practical conclusion:** even if AP isolation on the Deco side gets fixed, this dongle/driver combination cannot currently be trusted to hold a stable WiFi connection unattended (no physical access to power-cycle it on failure) — which defeats the entire purpose of it as a failover uplink. **Do not mark this workstream done based on a Deco config fix alone.** Before relying on this for real failover, either: get sustained multi-hour stability testing on the current driver build first, find/build a less flaky driver revision, or use different WiFi hardware.

**Manual bring-up recipe (for now, while WiFi is not yet automatic/reliable):**

```bash
# 1. check interface exists
ip -br link show | grep wlx

# 2a. if missing, or nmcli shows disconnected/failed repeatedly: reload driver (works ~50% of the time)
sudo rmmod aic8800_fdrv
sleep 2
sudo modprobe aic8800_fdrv
sleep 5
ip -br link show | grep wlx

# 2b. if 2a doesn't produce an interface, or dmesg shows "is scanning, abort" repeating:
#     physically unplug/replug the dongle instead — most reliable reset found so far,
#     though even this is not 100% (needed 2-3 attempts in this session on occasion).

# 3. explicit rescan before connecting — con up without one often races the first scan and fails
#    with "The Wi-Fi network could not be found" even when the AP is in range
sudo nmcli dev wifi rescan ifname wlx6c1ff78b5bf8
sleep 5
nmcli -f SSID,SIGNAL dev wifi list ifname wlx6c1ff78b5bf8 | grep pinkdolphin1   # confirm visible first

# 4. bring up the connection
sudo nmcli con up pinkdolphin1

# 5. verify (note: even a successful connect here does NOT mean working internet — see §4.2)
nmcli -t -f DEVICE,STATE,CONNECTION dev
ip -4 addr show wlx6c1ff78b5bf8
```

### 4.4 RESOLVED (2026-07-24) — root cause of the WiFi "connects then goes silent" was an RX buffer-pool leak; fixed and validated

This closes out §4.2 and §4.3. The single behaviour behind all of it — associate + DHCP succeed, then the data path goes dead within ~72s while the link still shows "connected" — was **not** AP isolation and **not** power-save. It was a bug in the out-of-tree driver's RX path.

**Root cause.** The driver is built with `CONFIG_PREALLOC_RX_SKB=y` (forced by `export CONFIG_PREALLOC_RX_SKB = y` in `drivers/aic8800/Makefile:9`, which overrides the `?= n` default in the sub-Makefiles). That gives a fixed preallocated RX pool of **1000 buffers × ~20 KB** (`aic_load_fw/aicwf_rx_prealloc.c`). In `aicwf_process_rxframes()` (`aic8800_fdrv/aicwf_txrxif.c`, the `aicwf_usb_rx_aggr` + `#ifdef CONFIG_PREALLOC_RX_SKB` branch), a routine `if (pkt_len > 1600) { …; return -EBADE; }` **aborts the entire rxq drain** on a condition that occurs constantly under real traffic (it fired 358× in a 110-second test). Meanwhile the USB RX-completion path keeps allocating a fresh pool buffer for every resubmitted URB. Buffers therefore drain from the pool faster than the early-returning drain loop frees them; the pool hits zero in ~72s and RX is then permanently dead — dmesg floods `aicwf_prealloc_rxbuff_alloc … rxbuff list is empty` / `failed to alloc rxbuff` / `sub rx fail`, `rx_packets` freezes, TX and the association stay up. Because only *receive* dies, gateway ARP shows `FAILED` and every ping is `Destination Host Unreachable` — which is exactly why §4.2 mistook it for AP-side L2 isolation.

**The fix** (see §4.1 patch (b)): change that `return -EBADE;` to `break;`. Breaking the inner subframe loop lets the existing end-of-loop `aicwf_prealloc_rxbuff_free()` return the buffer to the pool and lets the outer loop continue draining the rest of rxq. Net effect: corrupt/oversized aggregated subframes are dropped (TCP retransmits) instead of taking down the whole receive path. The `pkt_len > 1600` line is now logged as `drop rest of buffer`.

```c
/* aic8800_fdrv/aicwf_txrxif.c, in aicwf_process_rxframes(), USB rx_aggr + PREALLOC branch */
                if (pkt_len > 1600) {
                    AICWFDBG(LOGERROR, "%s pkt_len > 1600, drop rest of buffer\r\n", __func__);
                    break;          /* was: aicwf_prealloc_rxbuff_free(...); atomic_dec(...); return -EBADE; */
                }
```

**Dead end — do NOT "fix" this by setting `CONFIG_PREALLOC_RX_SKB=n`.** The upstream default is `n` (dynamic `__dev_alloc_skb` per RX), but building that way makes firmware *init* fail on this dongle: `err_lmac_reqs` → `aicwf_rwnx_usb_platform_init err -110` → `probe … failed with error -110`, no `wlx` interface ever appears (reproduced deterministically). The vendor's non-prealloc `#else` RX path is bit-rotted for the 8800D80. Keep the pool; fix the drain. (Also ruled out this session: `ps_on=0` firmware power-save — no effect on the leak.)

**Validation (2026-07-24, after a physical dongle power-cycle so init was clean).** With the patched `.ko` loaded, eth0 present but WiFi tested in isolation via `ping -I`:

```bash
# survives well past the old ~72s death point:
ping -I wlx6c1ff78b5bf8 -c 110 -i 1 192.168.68.1
#   -> 110 packets transmitted, 110 received, 0% packet loss
ip neigh show 192.168.68.1 dev wlx6c1ff78b5bf8      # -> REACHABLE  (was FAILED)

# heavy RX stress (this volume killed the old build in seconds):
sudo ping -f -s 1472 -c 4000 -I wlx6c1ff78b5bf8 192.168.68.1
#   -> 4000 packets transmitted, 4000 received, 0% packet loss

# pool health throughout both tests:
sudo dmesg | grep -c "rxbuff list is empty\|running out"   # -> 0  (was a continuous flood)
```

**Deployment state on board-01.** Patched `aic8800_fdrv.ko` + `aic_load_fw.ko` installed under `/lib/modules/$(uname -r)/kernel/drivers/net/wireless/aic8800/`; the stock (pre-fix) modules are backed up alongside as `*.ko.bak-prealloc-<timestamp>`. The driver source was re-cloned to a scratchpad from `github.com/Xanderful/aic8800d80` — **the patched source is not yet saved to a permanent tree**; if this needs to be rebuilt (kernel bump, reflash), re-apply patches (a) and (b) from a fresh clone.

**Still open — the `-110 err_lmac_reqs` init wedge (separate bug, affects reconnect robustness only).** The dongle firmware occasionally wedges at init and then fails every probe with `-110`. This state survives a warm `sudo reboot` **and** software USB re-enumeration (`echo 0/1 > /sys/bus/usb/devices/1-1/authorized`, driver `unbind`/`bind`) — only a physical VBUS cut (unplug/replug, or a full board power-off) clears it. There is no `uhubctl` on the board and the port has no software VBUS control. Practical impact: steady-state WiFi throughput is now solid, but automatic *re-association after a firmware wedge* is not yet reliable without physical access. Closing this (a powered USB hub with per-port switching + `uhubctl`, or a driver-level firmware-reload path that works without VBUS cycling) is the remaining task before board-01's WiFi can be trusted as a fully unattended failover uplink.

**Manual bring-up recipe (updated 2026-07-24 — supersedes §4.3's):**

```bash
# 1. interface should exist on its own after boot (udev mode-switch + auto-load)
ip -br link show | grep wlx

# 2. if NO wlx interface and dmesg shows "err_lmac_reqs" / "errno -110":
#    firmware is wedged — a warm reboot or sysfs rebind will NOT help.
#    Physically unplug/replug the dongle (or full board power-cycle). Only that cuts VBUS.

# 3. explicit rescan before connecting (con up without one races the first scan)
sudo nmcli dev wifi rescan ifname wlx6c1ff78b5bf8
sleep 5
nmcli -f SSID,SIGNAL dev wifi list ifname wlx6c1ff78b5bf8 | grep pinkdolphin1

# 4. bring up
sudo nmcli con up pinkdolphin1

# 5. verify the DATA PATH, not just the link (this is the check that matters):
ping -I wlx6c1ff78b5bf8 -c 5 192.168.68.1        # expect 0% loss
ip neigh show 192.168.68.1 dev wlx6c1ff78b5bf8   # expect REACHABLE, not FAILED
sudo dmesg | grep -c "rxbuff list is empty"      # expect 0
```

---

## Recommendations

**Do this, in order:**

1. **Start on Ubuntu 24.04 LTS** for both host and board unless you have a specific 26.04 need. 24.04 has broader third-party validation; 26.04's Rust-coreutils/sudo-rs and cgroup-v1 removal add avoidable variables to an eval. (Also note in-place 24.04→26.04 upgrades only open at the 26.04.1 point release on 2026-08-06.)
2. **Bring up Tailscale + HTTPS certs first**, confirm `tailscale cert` succeeds, *then* deploy Mender. TLS is the most common failure point; isolate it early.
3. **Pin Mender to a specific tag** (`v4.1.2`) rather than tracking a branch, so your eval is reproducible. Fall back to the docs' `v4.1.0` only if you hit an undocumented regression.
4. **Use the cert-overwrite approach (Option A)** for TLS — fewer moving parts than editing `tls.yaml`. Automate the 90-day renewal now (don't defer it): a `systemd timer` that runs `tailscale cert`, copies into `compose/certs/`, and `docker compose restart traefik`.
5. **Verify layer-by-layer** using Part 3 before deploying any artifact. If auth works but deployments fail, the culprit is almost always the `DEPLOYMENTS_PRESIGN_URL_HOSTNAME`/`DEPLOYMENTS_AWS_EXTERNAL_URI` overrides.
6. **Now that WiFi is live (§4.1) and the RX-path bug is fixed (§4.4), test failover end-to-end.** Pull Ethernet on board-01 and run §3's checklist over WiFi only — confirm Tailscale and Mender both ride through the switch. **History:** the first failover test (2026-07-23, §4.2) failed and was misread as an AP L2-isolation problem; it was actually the driver RX buffer-pool leak (§4.4), now patched. With the fix, `ping -I wlx<mac> <gw>` holds 0% loss and `ip neigh` is `REACHABLE`. Always verify the **data path** (`ping -I <wifi-iface> <that-subnet's-gateway>` with `ip neigh` → `REACHABLE`), not just link/DHCP state — a dead RX path presents identically to a working link.
7. **One driver issue remains before board-01's WiFi is fully unattended-ready: the `-110 err_lmac_reqs` init wedge on reconnect (§4.4).** Steady-state throughput is now solid (validated with a 4000-packet flood at 0% loss, pool never exhausting), so this is no longer a "don't trust the driver at all" situation — but the firmware occasionally wedges at init and only a physical VBUS cycle clears it (warm reboot and sysfs rebind don't). Close that (powered hub + `uhubctl`, or a working firmware-reload path) before relying on WiFi to *self-recover* from a wedge without physical access.

**Thresholds that change the plan:**

- **Moving beyond eval / to any production intent:** abandon docker-compose and move to the **Kubernetes/Helm** chart — Mender's README explicitly states the compose stack "is only meant for evaluation purposes," and the Helm chart *does* have first-class `MENDER_SERVER_URL`/ingress+cert-manager TLS. Production K8s needs only ~4 GB RAM / 4 vCPU / 10 GB PV per worker node. That's the point to switch.
- **Host RAM < 16 GiB:** don't proceed; the compose stack's documented minimum is 16 GiB. Resize the VM first.
- **Board on hard-NAT cellular that never goes direct:** if DERP latency hurts deployment throughput, stand up a **Tailscale subnet router / peer relay** on a well-connected node.
- **Dongle needs re-setup** (kernel rebuilt, board reflashed, new/different dongle model): redo the mode-switch + rebuild the `.ko` against the current kernel tree (§4.1), and re-check the `cfg80211_cac_event` signature before assuming the same patch applies unchanged.

## Caveats

- **Eval-only stack.** The docker-compose composition is documented by Mender as evaluation-only and is not optimized/hardened for production. This guide honors that scope.
- **Version drift is real.** Mender restructured repos (integration → mender-server) and split the client (mender → mender-authd/mender-updated), and the APT repo moved (debian → device-components) in late 2025. Commands here reflect July 2026 state; re-check `docs.mender.io` before a fresh build.
- **`tls.yaml` exact contents unverified byte-for-byte.** The cert mount point (`/etc/traefik/certs`) and demo filenames (`mender.crt`/`mender.key`) are confirmed; if upstream renames them in a later patch, open `compose/config/traefik/tls.yaml` and match the `certFile`/`keyFile` paths. This is the one place to double-check against your exact checkout. Likewise the `traefik:v3.6.13` tag is from current `main`; the frozen v4.1.x tag may pin a slightly earlier v3.x — the config approach is identical.
- **The `WOKRFLOWS_MENDER_URL` typo** is in the upstream compose as of the versions inspected; if a future release fixes the spelling, update your override accordingly.
- **Ubuntu 26.04 is very new** (April 2026). Package availability for `mender-client4` on `ubuntu/resolute` is confirmed in Mender's repo layout, but broader ecosystem maturity on 26.04 is still settling — another reason to prefer 24.04 for eval.
- **Public CT ledger exposure:** enabling Tailscale HTTPS publishes your host's FQDN (`mender-host.tailXXXX.ts.net`) to the public Certificate Transparency log. Access is still gated by the tailnet; only the name is public. Use a randomized tailnet name if that matters.
- **Client version naming is genuinely confusing:** the package is `mender-client4` but installs client **5.0.3**; the "4" refers to the post-4.0 split architecture generation, not the version number.
- **WiFi dongle driver is out-of-tree and board/kernel-specific (§4.1).** It is not a mainline or DKMS-managed driver — a kernel rebuild or board reflash silently drops WiFi back to a non-functional mass-storage device unless the driver, udev rule, and mode-switch setup are re-applied. Treat it as part of the board image, not a one-time setup step.
- **WiFi on board-01 — data path FIXED 2026-07-24 (§4.4), one reconnect-robustness item still open.** The two blockers recorded on 2026-07-23 (§4.2/§4.3) are resolved/reclassified: (1) the "AP gateway-unreachable" blocker was a misdiagnosis of the driver RX buffer-pool leak — not Deco isolation; (2) that RX leak is root-caused and patched (`return -EBADE` → `break` in `aicwf_process_rxframes`), validated at 0% loss over a 110s ping and a 4000-packet flood with the pool never exhausting. **Remaining open:** the intermittent `-110 err_lmac_reqs` firmware init wedge on reconnect, which only a physical VBUS cycle clears (warm reboot / sysfs rebind don't) — so unattended *self-recovery* from a wedge isn't guaranteed yet, though steady-state throughput is solid. The driver remains out-of-tree and board/kernel-specific (previous caveat still applies).
