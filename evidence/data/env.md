# Environment (auto-captured 2026-10-15 13:56:57)

- lab PC CPU: Intel(R) Core(TM) i9-14900K
- lab PC RAM: 62Gi
- lab PC OS / kernel: Ubuntu 24.04.4 LTS / 6.17.0-1032-oem
- backend commit: 1cd01b9 Reject non-RBF uploads, abort timed-out deploys, restore via the board's idle design
- Mender server images (id, created): mendersoftware/deployments:main 5aa69c2bd501 2 months ago; mendersoftware/deviceauth:main 7a63f4f69cb0 6 months ago; mendersoftware/useradm:main f66ee2d95c38 6 months ago
- OpenVINO (lab PC): openvino_2024 openvino_2024.6.0
- Quartus: Version 25.3.1 Build 100 12/19/2025 SC Pro Edition
- board kernel / OS: 6.12.11-gd7d192a9ddd9-dirty / Ubuntu 22.04.3 LTS
- board artifact_name: artifact_name=coredla-initial
- board Mender client: 5.1.0

## Probed 2026-10-15 (was manual)

- FPGA AI Suite: 2025.3.1 build 20 (`/opt/altera/fpga_ai_suite_2025.3.1`); board runtime `build_version.txt` = 2025.3.1/20, same as `coredla_work/build_version.txt`
- Mender server: deployments service v4.1.2-dirty (`mender-server` checkout b4d4770b "local specific updates"); images tagged :main
- OpenVINO: lab PC `openvino_2024.6.0`; board runtime libs 2024.6.0 (`~/app/libopenvino.so.2024.6.0`)
- Board SD image: built from `quartus_projects/CoreDLA_GHRD/sdcard.img` (5500 MiB, sha256 prefix 17ac98f9d7aeeb1a); live card is 59.5 GB (mmcblk0p1 UUID 0F4F-24C6, p2 UUID 1bc0d711-25d1-453b-991a-3d1f7a53e006), rootfs changed since flashing, so the sha identifies the base image only
- Network path (this session): board eth0 10.42.0.127/24 <-> PC eno1 10.42.0.1/24, direct cable. Mender/Tailscale traffic: `tailscale status` shows "direct 10.42.0.127:41641", so the WireGuard overlay runs over the same cable; Mender server URL is the tailscale name `mender-host`. Board polls every 5 s (`UpdatePollIntervalSeconds`), module timeout 600 s.
- Board: Agilex 5 DE25-Nano, kernel 6.12.11 (dirty), Ubuntu 22.04.3, Mender client 5.1.0

## Still manual

- [ ] Wi-Fi/routed paths: record when tickets 07/14 run

- clock offset board-PC 2026-10-15 13:57:01: +0.009 s (best RTT 0.026 s, error <= 0.013 s)
