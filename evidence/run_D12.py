"""D12 server load with simulated devices: python3 run_D12.py N1,N2,... [switches]. Simulated devices authenticate, get accepted, then poll
/deployments/next every 5 s like the real client. One REAL board does the model switches; server CPU/RAM sampled with docker stats.
Simulated devices are decommissioned on exit. Results -> data/D12-load/."""
import sys, os, time, json, base64, asyncio, statistics as st, csv, subprocess, requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import harness as h
for l in open(os.path.expanduser("~/mender/lab-backend/lab-backend.env")):
    if "=" in l and not l.startswith("#"): k, v = l.strip().split("=", 1); os.environ.setdefault(k, v)
sys.path.insert(0, os.path.expanduser("~/mender/lab-backend")); import mender_client as mc, config, httpx
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes, serialization
U = config.MENDER_URL; levels = [int(x) for x in sys.argv[1].split(",")]; nsw = int(sys.argv[2]) if len(sys.argv) > 2 else 4
class Dev:
    def __init__(s, i):
        s.i = i; s.key = rsa.generate_private_key(65537, 2048); s.jwt = None; s.id = None; s.lat = []; s.err = 0
        s.pub = s.key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        s.idd = json.dumps({"mac": f"02:d1:2c:00:{i >> 8:02x}:{i & 255:02x}"})
    def req(s):
        body = json.dumps({"id_data": s.idd, "pubkey": s.pub, "tenant_token": ""}).encode()
        sig = base64.b64encode(s.key.sign(body, padding.PKCS1v15(), hashes.SHA256())).decode()
        return body, {"Content-Type": "application/json", "X-MEN-Signature": sig}
async def auth(c, d):
    body, hd = d.req(); r = await c.post(f"{U}/api/devices/v1/authentication/auth_requests", content=body, headers=hd)
    if r.status_code == 200: d.jwt = r.text.strip()
    return r.status_code
async def poll(c, d, stop):
    await asyncio.sleep((d.i % 50) / 10)  # spread phases over 5 s
    while not stop.is_set():
        t = time.monotonic()
        try:
            r = await c.get(f"{U}/api/devices/v1/deployments/device/deployments/next", params={"artifact_name": "sim", "device_type": "sim-board"}, headers={"Authorization": f"Bearer {d.jwt}"})
            if r.status_code in (200, 204): d.lat.append(time.monotonic() - t)
            else: d.err += 1
        except Exception: d.err += 1
        await asyncio.sleep(5)
async def sampler(rows, stop, tag):
    while not stop.is_set():
        p = await asyncio.create_subprocess_exec("docker", "stats", "--no-stream", "--format", "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}", stdout=asyncio.subprocess.PIPE)
        out = (await p.communicate())[0].decode(); cpu = mem = 0.0
        for l in out.splitlines():
            n, c, m = l.split("|"); cpu += float(c.strip("%")); v = m.split("/")[0].strip(); mem += float(v[:-3]) * (1024 if v.endswith("GiB") else 1) if v.endswith(("MiB", "GiB")) else float(v[:-3]) / 1024
        rows.append((tag, time.time(), cpu, mem, open("/proc/loadavg").read().split()[0]))
        await asyncio.sleep(1)
def switch(j, tgt):
    t = time.monotonic(); r = requests.post(f"{h.BACKEND}/session/model", params={"job_id": j}, json={"name": tgt})
    res = h.wait(j, "model_state", limit=300) if r.ok else f"fail:http{r.status_code}"
    return res, time.monotonic() - t
async def main():
    os.makedirs(f"{h.DATA}/D12-load", exist_ok=True); allsim = []; samples = []
    async with httpx.AsyncClient(timeout=30, limits=httpx.Limits(max_connections=400)) as c:
        try:
            tok = await mc.login(); mh = {"Authorization": f"Bearer {tok}"}
            j = h.join(); live = requests.get(f"{h.BACKEND}/session/model").json()["name"]; other = "flag" if live != "flag" else "fruit"; names = [other, live]
            with h.Series("D12-load", f"real-board+sim-devices; live-before={live}") as s, open(f"{h.DATA}/D12-load/samples.csv", "a", newline="") as sf:
                s.cleanup(lambda: h.finish(j)); sw = csv.writer(sf); k = 0
                for N in levels:
                    # create + accept simulated devices up to N
                    new = [Dev(len(allsim) + x) for x in range(max(0, N - len(allsim)))]; t0 = time.monotonic()
                    for d in new: await auth(c, d)
                    allsim += new
                    r = await c.get(f"{U}/api/management/v2/devauth/devices", params={"status": "pending", "per_page": 500}, headers=mh)
                    pend = {x["identity_data"]["mac"]: x for x in r.json()}
                    for d in new:
                        x = pend.get(json.loads(d.idd)["mac"])
                        if x: d.id = x["id"]; await c.put(f"{U}/api/management/v2/devauth/devices/{x['id']}/auth/{x['auth_sets'][0]['id']}/status", json={"status": "accepted"}, headers=mh)
                    for d in new: await auth(c, d)
                    ok = sum(1 for d in allsim[:N] if d.jwt); print(f"N={N}: {ok} simulated devices authenticated (setup {time.monotonic()-t0:.0f}s)", flush=True)
                    stop = asyncio.Event(); rows = []; act = allsim[:N]
                    tasks = [asyncio.create_task(poll(c, d, stop)) for d in act if d.jwt] + [asyncio.create_task(sampler(rows, stop, f"N{N}"))]
                    await asyncio.sleep(12)  # settle
                    for _ in range(nsw):
                        res, dt = await asyncio.get_running_loop().run_in_executor(None, switch, j, names[k % 2]); k += 1
                        s.record(f"sim{N}:{names[(k-1) % 2]}", "ok" if res == "ok" else f"fail:{res}", dt); print(f"  N={N} switch -> {names[(k-1)%2]}: {res} {dt:.1f}s", flush=True)
                        await asyncio.sleep(3)
                    stop.set(); await asyncio.gather(*tasks)
                    for r_ in rows: sw.writerow(r_)
                    lat = [x for d in act for x in d.lat]; err = sum(d.err for d in act)
                    cp = [r_[2] for r_ in rows]; mm = [r_[3] for r_ in rows]
                    print(f"  N={N}: polls {len(lat)} errors {err}; poll latency median {1e3*st.median(lat) if lat else 0:.0f} ms p95 {1e3*sorted(lat)[int(.95*len(lat))-1] if lat else 0:.0f} ms; server containers CPU sum median {st.median(cp):.1f}% max {max(cp):.1f}%; mem median {st.median(mm):.0f} MiB; samples {len(rows)}", flush=True)
        finally:
            gone = 0
            for d in allsim:
                if d.id:
                    r = await c.delete(f"{U}/api/management/v2/devauth/devices/{d.id}", headers=mh); gone += r.status_code in (200, 204)
            print(f"decommissioned {gone}/{len(allsim)} simulated devices", flush=True)
asyncio.run(main())
