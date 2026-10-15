import os
from pathlib import Path

BASE_DIR = Path(__file__).parent

MENDER_URL = os.environ["MENDER_URL"]
MENDER_USER = os.environ["MENDER_USER"]
MENDER_PASS = os.environ["MENDER_PASS"]

# coredla SD in board-01 (2026-09-17); the old lab SD was 6fcb3fac-90f2-43d2-851c-b7bee2b6fe3d
DEVICE_ID = os.environ.get("DEVICE_ID", "56bc13f6-c33d-4637-8f25-c4eb03605b40")
DEVICE_TYPE = os.environ.get("DEVICE_TYPE", "de25-nano")

SESSION_SECONDS = int(os.environ.get("SESSION_SECONDS", 1200))
ACK_GRACE_SECONDS = int(os.environ.get("ACK_GRACE_SECONDS", 120))
MAX_RBF_BYTES = int(os.environ.get("MAX_RBF_BYTES", 8 * 1024 * 1024))
# Every Agilex 5 core.rbf built here (GHRD, DLA, golden, student uploads) starts with
# these bytes; random data sent to the board wedged its FPGA manager until a power
# cycle (docs/OTA_HARDENING_PLAN.md step 4b). The smallest good one is 1.5 MB, a
# 64 KiB truncation programmed "ok". ponytail: header + size heuristic, not a format
# check; a crafted file still passes, the board-side stuck detector covers that.
RBF_MAGIC = bytes.fromhex("9548296250000000")
MIN_RBF_BYTES = 1024 * 1024

BOARD_STREAM_URL = os.environ.get("BOARD_STREAM_URL", "http://coredla:8080/stream")

DTB_PATH = BASE_DIR / "assets" / "my_overlay.dtb"
GHRD_RBF_PATH = BASE_DIR / "assets" / "ghrd.core.rbf"
UPLOADS_DIR = BASE_DIR / "uploads"
# fpga-reconfig artifact whose payload is only a `restore` file: the board puts its
# idle (last good model) design back. Built once, see docs/OTA_HARDENING_PLAN.md step 4.
RESTORE_ARTIFACT = os.environ.get("RESTORE_ARTIFACT", "fpga-restore-v1")
RELEASE_RETRIES = 10
RELEASE_RETRY_SECONDS = 30

# Phase 1 (edge AI demo): inference goes over ssh to the board's dla-server
# spool, never through Mender. Key auth as terasic, see ~/edge-ai-demo/README.md.
BOARD_SSH = os.environ.get("BOARD_SSH", "terasic@coredla")
BOARD_SPOOL = os.environ.get("BOARD_SPOOL", "/var/lib/dla/spool")
BOARD_MODEL_DIR = os.environ.get("BOARD_MODEL_DIR", "/var/lib/dla/model")
# Phase 2: model catalog. name -> coredla-model artifact already on the Mender
# server (built + uploaded by ~/edge-ai-demo/artifacts/build-model.sh +
# mender-deploy.sh). MODEL_CATALOG="fruit=coredla-model-fruit-7580298c,flag=..."
# The first entry is the default: put back after a session that programmed its
# own .rbf over the DLA design, unless that session switched to another one.
MODEL_CATALOG = dict(
    kv.split("=", 1)
    for kv in os.environ.get(
        "MODEL_CATALOG",
        "fruit=coredla-model-fruit-7580298c,flag=coredla-model-flag-73107bc0,imagenet=coredla-model-imagenet-9e0571d4",
    ).split(",")
)
MODEL_NAME = next(iter(MODEL_CATALOG))
BUILTIN_MODELS = frozenset(MODEL_CATALOG)  # user uploads may not shadow these

# Phase 3: user IR upload. Files land in EDGE_AI_DIR/models/<name>/ and
# artifacts/build-user-model.sh (CPU smoke + dla_compiler + bundle) runs there.
EDGE_AI_DIR = Path(os.environ.get("EDGE_AI_DIR", Path.home() / "edge-ai-demo"))
# Uploads must be the notebook kit's ResNet-18 (fine-tuned from fruit-v1), the same
# backbone as the catalog models (2026-09-28).
REFERENCE_IR_XML = EDGE_AI_DIR / "models" / "fruit-v1" / "model.xml"
MAX_IR_XML_BYTES = int(os.environ.get("MAX_IR_XML_BYTES", 1024 * 1024))
MAX_IR_BIN_BYTES = int(os.environ.get("MAX_IR_BIN_BYTES", 128 * 1024 * 1024))
MAX_CATEGORIES_BYTES = int(os.environ.get("MAX_CATEGORIES_BYTES", 64 * 1024))
BUILD_TIMEOUT_SECONDS = float(os.environ.get("BUILD_TIMEOUT_SECONDS", 900))
