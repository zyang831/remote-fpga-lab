#!/bin/bash
# Phase 3: turn an uploaded IR in ../models/<name>/ (model.xml, model.bin,
# categories.txt, name) into a coredla-model artifact. Called by lab-backend
# after its xml/categories validation; last stdout line is the artifact name.
#   ./build-user-model.sh <name>
# 1. CPU-plugin smoke: the .bin loads against the .xml and answers [1,N] on
#    one image (there is no x86 emulator build, see docs/MODEL_TRAINING_PLAN.md).
# 2. training/compile.sh: dla_compiler + placement/DDR checks.
# 3. build-model.sh: bundle with the DLA bitstream + overlay.
set -eu
cd "$(dirname "$0")/.."
NAME=$1
M=models/$NAME
for f in model.xml model.bin categories.txt name; do [ -f "$M/$f" ] || { echo "missing $M/$f" >&2; exit 1; }; done
N=$(wc -l < "$M/categories.txt")

echo "=== checking the model loads and answers ($N classes)"
~/build-openvino-dev/openvino_env/bin/python - "$M" "$N" <<'EOF'
import sys, numpy as np, openvino as ov
from PIL import Image
m, n = sys.argv[1], int(sys.argv[2])
cm = ov.Core().compile_model(f"{m}/model.xml", "CPU")
img = Image.open("demo-images/fruit/apple_00.jpg").convert("RGB").resize((224, 224))
p = cm(np.asarray(img, dtype=np.float32).transpose(2, 0, 1)[None])[0]
assert p.shape == (1, n), f"output shape {p.shape}, expected (1, {n})"
assert abs(p.sum() - 1) < 1e-3 and np.isfinite(p).all(), "output is not a probability vector"
print("ok: [1,%d], argmax %d" % (n, p.argmax()))
EOF

echo "=== compiling for the FPGA (dla_compiler, about a minute)"
training/compile.sh "$NAME"

echo "=== bundling with the FPGA design"
artifacts/build-model.sh "$NAME" | tail -1 | sed 's#.*/##; s#\.mender$##'
