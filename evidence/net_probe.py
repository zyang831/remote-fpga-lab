"""RTT and TCP throughput to the board, both directions, no installs on the board (python3 there).
python3 net_probe.py LABEL BOARD_ADDR [seconds]  -> appends to data/D1-net/probe.csv
Throughput: PC listens, board connects and sends (board->PC); then board listens, PC connects and sends (PC->board)."""
import sys, os, re, time, socket, subprocess, csv, threading
import harness as h
label, addr = sys.argv[1], sys.argv[2]; T = float(sys.argv[3]) if len(sys.argv) > 3 else 10
def ping(a, n=20):
    o = subprocess.run(["ping", "-c", str(n), "-i", "0.2", a], capture_output=True, text=True).stdout
    m = re.search(r"min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)", o); l = re.search(r"(\d+)% packet loss", o)
    return (m.groups() if m else ("", "", "", "")) + (l.group(1) if l else "",)
SEND = "import socket,sys,time;s=socket.create_connection((sys.argv[1],int(sys.argv[2])));b=b'x'*65536;t=time.time()\nwhile time.time()-t<float(sys.argv[3]): s.sendall(b)\ns.close()"
RECV = "import socket,sys,time;l=socket.socket();l.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);l.bind(('0.0.0.0',int(sys.argv[1])));l.listen(1);c,_=l.accept();n=0;t=time.time()\nwhile True:\n d=c.recv(1<<20)\n if not d: break\n n+=len(d)\nprint(n,time.time()-t)"
def board_to_pc():
    srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); srv.bind(("0.0.0.0", 5201)); srv.listen(1); srv.settimeout(30)
    me = subprocess.run("ip route get " + addr + " | sed -n 's/.* src \\([0-9.]*\\).*/\\1/p'", shell=True, capture_output=True, text=True).stdout.strip()
    p = subprocess.Popen(["ssh", h.BOARD, f"python3 -c \"{SEND}\" {me} 5201 {T}"]); c, _ = srv.accept(); n = 0; t = time.time()
    while True:
        d = c.recv(1 << 20)
        if not d: break
        n += len(d)
    dt = time.time() - t; p.wait(); return n * 8 / dt / 1e6
def pc_to_board():
    p = subprocess.Popen(["ssh", h.BOARD, f"python3 -c \"{RECV}\" 5202"], stdout=subprocess.PIPE, text=True); time.sleep(3)
    s = socket.create_connection((addr, 5202)); b = b"x" * 65536; t = time.time()
    while time.time() - t < T: s.sendall(b)
    s.close(); out = p.communicate()[0].split(); return int(out[0]) * 8 / float(out[1]) / 1e6
r = ping(addr); up, dn = pc_to_board(), board_to_pc()
os.makedirs(f"{h.DATA}/D1-net", exist_ok=True); path = f"{h.DATA}/D1-net/probe.csv"; new = not os.path.exists(path)
with open(path, "a", newline="") as f:
    w = csv.writer(f)
    if new: w.writerow(["time", "label", "addr", "rtt_min_ms", "rtt_avg_ms", "rtt_max_ms", "rtt_mdev_ms", "loss_pct", "pc_to_board_mbit", "board_to_pc_mbit", "seconds_each"])
    w.writerow([time.strftime("%F %T"), label, addr, *r, f"{up:.1f}", f"{dn:.1f}", T])
print(label, addr, "rtt avg/max ms", r[1], r[2], "loss%", r[4], "PC->board", f"{up:.1f}", "board->PC", f"{dn:.1f}", "Mbit/s")
