# D2 model switch, fruit <-> flag (generated from runs.csv, 2026-10-15)
n=40 (+1 flagged warm-up 29.6 s excluded), failures 0, exact one-sided 95% failure bound 7.2%.
All: median 27.2 s, mean 27.7, SD 3.9, min 23.2, max 37.8. Switch to flag (n=20): median 26.5, mean 27.1, SD 3.1, range 23.4-35.5. Switch to fruit (n=20): median 27.2, mean 28.3, SD 4.6, range 23.2-37.8.
End criterion: model_state ok AND GET /session/model name == target. Client wall clock, 0.25 s poll, direct cable (Mender via Tailscale direct path).
Feeds: Table IV (model switch row), VI-A. Every run under the 60 s bar (R3).
Caveat: board dla-server crash loop was present before the series (see notes); redeployed fruit fixed it, 0 crashes logged during all runs (journal follower, scratchpad jf.out). Cause not isolated. Series ended on flag; fruit restored (29.2 s).
