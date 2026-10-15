# Edge AI Remote FPGA Lab — research findings

Scope: DE25-Nano (Agilex 5), FPGA AI Suite 2025.3.1/20, OpenVINO 2024.6.0, Mender OSS, Tailscale.
Sources: local code/docs + Mender/Altera docs. Board `board-01` offline during research (tailscale: "offline, last seen 9d ago"), so board-only files (`/usr/share/mender/modules/v3/fpga-reconfig`, `/etc/mender/mender.conf`) are cited via local docs, not read directly.

Paths abbreviated: `LAB=~/mender/lab-backend`, `RT=~/coredla_work/runtime`, `REL=~/coredla_work/de25_coredla_release`, `MP=~/coredla_work/de25_nano_bringup/model_prep`, `SUITE=/opt/altera/fpga_ai_suite_2025.3.1/dla`.

---

## Q1. How the remote lab pushes an RBF today

### Backend flow (host side)
- `POST /session/program` accepts multipart field `bitstream`; rejects unless name ends `.rbf` and size ≤ `MAX_RBF_BYTES` (8 MiB); saves to `uploads/<uuid>.rbf`; hands to queue loop. `LAB/main.py:50-68`, `LAB/config.py:15`.
- Loop calls `mender_client.deploy(rbf, "fpga-lab-<job>-<ts>")`; on release redeploys idle `assets/ghrd.core.rbf`. `LAB/queue_manager.py:115-134`.
- `deploy()` = build artifact → upload → create deployment → poll. `LAB/mender_client.py:121-143`.
- Artifact build is a **Mender Update Module ("module-image") artifact, custom type `fpga-reconfig`**, two payload files:
  ```
  mender-artifact write module-image -T fpga-reconfig -t de25-nano -n <name> -o <out>.mender -f output_design.core.rbf -f my_overlay.dtb
  ```
  `LAB/mender_client.py:62-69`. RBF is staged under the fixed name `output_design.core.rbf` because the board module hardcodes it (`_BOARD_RBF_NAME`, `LAB/mender_client.py:49-61`).
- Upload: `POST /api/management/v1/deployments/artifacts` multipart. `LAB/mender_client.py:79-86`.
- Deployment: `POST /api/management/v1/deployments/deployments` with `{name, artifact_name, devices:[DEVICE_ID]}`; id from `Location` header. `LAB/mender_client.py:89-96`.
- **Completion detection**: poll `GET /deployments/{id}` every 2 s until `status == "finished"`, then read `/statistics`; success iff `failure == 0 and success+already-installed > 0`; 300 s timeout. `LAB/mender_client.py:99-118`.
- Artifact names must be unique per deploy (Mender rejects duplicate names). `LAB/queue_manager.py:118-119`.
- httpx timeout is 120 s read / 10 s connect for every call incl. artifact upload. `LAB/mender_client.py:21`.

### Board side (from docs; module script not readable — board offline)
- Module lives at `/usr/share/mender/modules/v3/fpga-reconfig`, has `RBF_FILE="output_design.core.rbf"` and a `DTB_FILE` that happens to equal `my_overlay.dtb`. `~/mender/MVP Web UI.MD:313-318`.
- Mechanism: "configfs device-tree-overlay + FPGA manager, Agilex 5" — **live reprogram, no reboot**. `~/mender/MVP Web UI.MD:37-39`. Measured 4.9–19.7 s install+verify. `~/mender/MVP Web UI.MD:42`.
- RBF lands in `/lib/firmware/output_design.core.rbf` (rollback verified by md5 of that path). `~/mender/MVP Web UI.MD:327-330`.
- Module implements `ArtifactRollback`; on failure restores prior rbf, re-applies overlay (`status: applied`, `fpga0/state: operating`). `~/mender/MVP Web UI.MD:327-330`.
- Overlay content (`LAB/assets/my_overlay.dtb`, decompiled with `dtc`): fragment targeting `/fpga-region`, `firmware-name = "output_design.core.rbf"`, `ranges` covering only `0x20000000 +0x20000` (128 KiB), one `sysid@10000` child. So the lab overlay does **not** describe CoreDLA CSR (`0x20020000`) or mSGDMA (`0x20021000`).
- Same mechanism was prototyped for CoreDLA but never installed: `~/coredla_work/de25_nano_bringup/boot_setup/coredla-fpga-up.sh:13-30` writes `my_overlay.dtb` into `/sys/kernel/config/device-tree/overlays/fpga-reconfig/path`, waits for `fpga0/state == operating`, then `modprobe uio_pdrv_genirq of_id=generic-uio; altera-msgdma; msgdma_userio`. Ledger marks it "never installed — the boot.scr `fpga load` path is used instead". `~/coredla_work/INVESTIGATION_LEDGER.md:917`.

### How the CoreDLA release board is programmed (different path)
- U-Boot: `fatload mmc 0:1 0x90000000 golden_top.core.rbf` → `fpga load 0 …` → `bridge enable`, before `booti`; `mem=768M` in bootargs. `~/coredla_work/RUNBOOK.md:441-470`, `REL/README.md:101-103`.
- Consequence: `/sys/class/fpga_manager/fpga0/state` reads `unknown` (bypassed fpga_manager). `REL/README.md:142-143`.
- Kernel modules that touch the fabric (`altera-msgdma`) panic if probed while fabric absent: "msgdma_irq_handler → synchronous external abort → kernel panic". `~/coredla_work/de25_nano_bringup/SDCARD_IMAGE_CHANGES.md:124-130`. After any reconfig they must be reloaded in order (`03_board_setup.sh` pattern). `REL/README.md:116-125`.
- DLA DDR carveout `0xB000_0000-0xBFFF_FFFF` (256 MiB) exists only because of `mem=768M` bootarg — not creatable from a runtime overlay. `REL/source/socfpga_agilex5.dtsi.patch:36-55`, `REL/README.md:186-189`.
- DT nodes CoreDLA needs (`msgdma@20021000` with SPI 20, `msgdma_coredla0` userio node, `coredla0@20020000` generic-uio) are today in the **base** dtsi patch. `REL/source/socfpga_agilex5.dtsi.patch:25-67`.
- Ledger: one physical board, reachable as `coredla` / `board-01` over Tailscale. `~/coredla_work/INVESTIGATION_LEDGER.md:1074`.

### Mender update-module facts (official docs)
- `-f` is repeatable; payload files land in `$2/files/` of the module's ArtifactInstall call; module entry point under `/usr/share/mender/modules/v3`; `-T` must equal the module filename. States: `ArtifactInstall`, `NeedsArtifactReboot` (`No`/`Automatic`), `SupportsRollback`, `ArtifactRollback`, `ArtifactCommit`. https://docs.mender.io/artifact-creation/create-a-custom-update-module
- Reference `dir-overlay` module: expects `update.tar` + `dest_dir`, unpacks to dest, keeps backup+manifest for rollback, `NeedsArtifactReboot → No`. https://raw.githubusercontent.com/mendersoftware/mender-update-modules/master/dir-overlay/module/dir-overlay

### Conclusion Q1
- Minimal path: **keep `module-image`, extend to a new module type (e.g. `coredla-bundle`) that takes N files via repeated `-f`** — identical packaging/upload/poll code; only `build_artifact()` gains extra `-f` args and `-T`. The existing `fpga-reconfig` script should not be reused as-is: it hardcodes two filenames and the lab overlay lacks the CoreDLA nodes.
- Board-side `coredla-bundle` module must, in `ArtifactInstall`: `rmmod msgdma_userio altera_msgdma` → copy rbf to `/lib/firmware` → apply overlay carrying `firmware-name` + CoreDLA child nodes (msgdma/uio) with `ranges` widened past `0x20000` → wait `operating` → modprobe chain → unpack app payload → restart inference service. Rollback = previous rbf/overlay + previous app dir (dir-overlay pattern).
- Hard constraint: the kernel must already boot with `mem=768M` (or a `reserved-memory` node in the base DTB). Live reconfig cannot add the DDR carveout. `REL/README.md:186-189`.
- Size: bundle ≈ 3.2 MiB rbf (`REL/prebuilt/golden_top.core.rbf`) + 147 MiB graph + app.tar 675.7 MiB (`REL/app-payload/app.tar`). `poll_until_finished` 300 s (`LAB/mender_client.py:99`) and 8 MiB rbf cap (`LAB/config.py:15`) both need raising / a separate size cap for bundles. App libs (sdklibs+OpenVINO ≈ 500 MiB) should ship once, not per deploy: split "runtime" artifact (rare) from "model" artifact (rbf+dtb+arch+bin+categories).

---

## Q2. image_streaming_app ↔ streaming_inference_app transport

### Transport
- **Not a socket/pipe/file.** `image_streaming_app` writes raw image bytes with `fwrite` to the char device **`/dev/msgdma_stream0`** (an mSGDMA *streaming* driver, ingress DMA into the DLA). `RT/streaming/image_streaming_app/image_streaming_app.cpp:177-234`.
- Handshake: POSIX named semaphore `/CoreDLA_ready_for_streaming` — inference app `sem_post`s after model import; streaming app `sem_timedwait`s before sending. `RT/streaming/streaming_inference_app/streaming_inference_app.cpp:179-184`, `RT/streaming/image_streaming_app/image_streaming_app.cpp:277-307`.
- Cancel: second named semaphore whose name comes from plugin property `cancel_semaphore_name`. `streaming_inference_app.cpp:134-135,171-176`.
- Image format: 224×224 BMP (or `.raw`/`.lt`), validated as exactly `224*224*3` bytes (4 ch with external LT); optional FP16 layout transform + mean shift (`-blue_shift=-103.94` etc.), rate `-rate=Hz`, `-image=` single file or `-images_folder=`. `image_streaming_app.cpp:33-88`, `RT/streaming/image_streaming_app/raw_image.cpp:55-60`.
- Results: top-1 to stdout per frame (`"N - <class>, score = X"`), top-5 of first 1000 frames to `results.txt` in cwd; class names from `categories.txt` in cwd (expects 1001 lines). `streaming_inference_app.cpp:290-370,376-400`.
- `streaming_inference_app` imports the graph **once** (`import_model`), keeps N async requests re-arming themselves forever — persistent, but it has **no per-image API**: it consumes whatever the hardware stream delivers. `streaming_inference_app.cpp:107-168,258-262,368-370`.
- Score printed as `score * 100` — assumes softmax probabilities in output. `streaming_inference_app.cpp:338-354`.

### Hardware prerequisites the current GHRD does not meet
- Plugin: streaming path is entered only if `input_configuration.enable_input_streaming || cfg_.enableStreaming`; then `InitializeScheduler()` must succeed or: `"Scheduler module initialization failed. Check that you have an S2M bitstream."` `SUITE/dla_plugin/src/dla_compiled_model.cpp:286-310`.
- `InitializeScheduler` needs a `StreamControllerComms` that `IsPresent()` — the HPS MMD looks for a UIO device named `stream_controller*`. `RT/coredla_device/src/coredla_device.cpp:589-600`, `RT/coredla_device/mmd/hps_platform/host/mmd_device.cpp:34,89-96`.
- Streaming needs `input_stream_interface.enable` in the .arch. `SUITE/inc/arch_params.h:507-509`. `AGX5_Nano_k32c16.arch` has no `input_stream_interface` block. `MP/AGX5_Nano_k32c16.arch` (whole file). Ledger: interface widths "streaming in/out `0`". `INVESTIGATION_LEDGER.md:1032`.
- DE25 DT has `msgdma_coredla0` (M2M userio) and `coredla0` UIO only — no `stream_controller`, no `/dev/msgdma_stream0`. `REL/source/socfpga_agilex5.dtsi.patch:25-67`.
- Altera: S2M design = "Streaming input data is copied to FPGA on-device memory"; M2M = `dla_benchmark` on HPS. https://altera-fpga.github.io/rel-25.3.1/ed-ai-suite/agilex5/soc/fpga_ai_suite_soc_design_example/
- Script comment: streaming model must be compiled `--ffolding-option=0`. `REL app.tar:app/run_inference_stream.sh:13`.
- The two binaries were shipped in app.tar untested ("not used in the qualified run"). `INVESTIGATION_LEDGER.md:909`.

### classification_sample_async (C++)
- CLI: `-m <IR .xml>` `-i <images>` `-d HETERO:FPGA,CPU` `-plugins <plugins.xml>` `-arch_file <.arch>`. `RT/classification_sample_async/classification_sample_async.h:44-57`, `README.md`.
- **JIT only**: `core.read_model(FLAGS_m)` then `core.compile_model(model, FLAGS_d)` — compiles the IR on the device every invocation; no `import_model`/`-cm`. `RT/classification_sample_async/main.cpp:108,193`.
- Runs 10 async iterations of one batch, prints top-10 via `ClassificationResult`; labels from `<model>.labels` beside the xml. `main.cpp:210-272`, `main.cpp:33`.
- **Not buildable for this board**: `hps_platform` CMake preset sets `DISABLE_JIT=TRUE` (`RT/CMakePresets.json:87-95`), and `BUILD_DEMO` fatals under `DISABLE_JIT` (`RT/CMakeLists.txt:452-460`); the demo is only added with `-build_demo` (`RT/CMakeLists.txt:461`). HPS builds add only `dla_benchmark` + the two streaming apps (`RT/CMakeLists.txt:449,465-468`). Python demos are JIT too (`RT/python_demos/OpenVINO_classification_sample_async/*.py:134`) and no Python OpenVINO is in app.tar.

### dla_benchmark (what actually works on the board)
- Imports precompiled graph via `-cm`: reads device string, then `core.import_model(stream, "HETERO:FPGA,CPU", cfg)`. `RT/dla_benchmark/main.cpp:960-990`.
- Measured `Import model took 76642 ms`; latency 475 ms/frame; 2.10 FPS system. `INVESTIGATION_LEDGER.md:446-466`, `REL/README.md:151-166`.
- `-dump_output` writes `result.txt` / `result_{batch}.bin`; `-groundtruth_loc` does top-1/top-5 accuracy; no human-readable "top-5 labels" printer. `RT/dla_benchmark/dla_benchmark.hpp:288,303`, `main.cpp:1448-1560`.

### Conclusion Q2
- Neither shipped app fits "HTTP upload → top-5": `streaming_inference_app` needs an S2M bitstream/arch the DE25 GHRD doesn't have; `classification_sample_async` can't be built for HPS; `dla_benchmark` pays ~76 s import per process.
- Best fit: a small **persistent C++ server** built in the HPS runtime tree, reusing `dla_benchmark`'s `-cm` import code (`main.cpp:960-990`) and `streaming_inference_app`'s top-5 + `categories.txt` code (`streaming_inference_app.cpp:290-400`), reading images from a directory/FIFO/local socket that the lab backend (or a tiny on-board HTTP shim) feeds. Image preprocessing = resize to 224×224 u8 NCHW as `dla_benchmark`/`inputs_filling.cpp` does; mean subtraction is already folded into the graph (`Subtract_*` preprocessing layers in the IR, see `strings resnet50_k32c16.bin | head`).

---

## Q3. Softmax in graph

### How variants were produced
- `resnet50.bin` (→ board `resnet50_nosoftmax.bin`): `dla_compiler --march AGX5_Small_NoSoftmax.arch --network-file models_ir/public/resnet-50-tf/FP32/resnet-50-tf.xml --foutput-format dla_compiled_result --o compiled/resnet50.bin --fdisplay-device`. `MP/.run_dla_compile.sh:7-12`.
- `resnet50_nofold.bin`: same + `--ffolding-option 0`. `MP/.run_dla_compile_nofold.sh:6-12`.
- `resnet50_k32c16.bin`: same as first with `--march AGX5_Nano_k32c16.arch` (default folding = 1, no extra flags). `MP/.run_dla_compile_k32c16.sh:7-12`. md5 `e70be16a…` identical to `app.tar:app/resnet-50-tf/resnet50_k32c16.bin` (checked by `md5sum` on both).
- `resnet50_softmax.bin` (2026-07-29): no script survives; ledger: "`dla_compiler` with the Softmax arch" (i.e. `AGX5_Small_Softmax.arch`). `INVESTIGATION_LEDGER.md:702,910`. Consistent evidence: that build's `hetero_subgraphs_Model7.dot` (same timestamp) shows a **single FPGA subgraph, no CPU node**. `MP/hetero_subgraphs_Model7.dot`. The bin's hetero header lists only `device="FPGA"` (grep on the file).
- Softmax is selected purely by the **.arch** (`custom_aux_primitive { layer_type: 'softmax' … }` + xbar port + `module { name: 'softmax' }`), not by a dlac flag or IR edit. `diff SUITE/example_architectures/AGX5_Small_NoSoftmax.arch AGX5_Small_Softmax.arch`; README: "Small supports Resnet only, Small_Softmax supports Resnet and Softmax". `SUITE/example_architectures/README.txt:16`.

### Does the k32c16 graph include softmax?
- **Not on the FPGA.** `AGX5_Nano_k32c16.arch` has no softmax primitive (`MP/AGX5_Nano_k32c16.arch`). dlac message for this arch family: "Softmax custom aux primitive is not enabled in the architecture!" → CPU placement. `MP/TensorFlow_Frontend_IR_dla_messages.txt`, `MP/unsupported_layer_chains.dot`, `MP/TensorFlow_Frontend_IR_FPGA_dla_layer_device.csv` (`softmax_tensor,CPU,Softmax,[1 1001]`). (These dumps are from the 2026-09-04 `sb12883` compile, same arch family.)
- **But softmax is in the compiled file as a CPU submodel**: `resnet50_k32c16.bin` hetero header = `<compiled_submodel device="FPGA"/><compiled_submodel device="CPU"/>`, output mapped from submodel 1 (`head -c 4000 resnet50_k32c16.bin | strings`). The hetero plugin imports the CPU chunk and runs it on the CPU plugin. `SUITE/hetero_plugin/compiled_model.cpp:185-271`. Under `-d HETERO:FPGA,CPU` with `libopenvino_arm_cpu_plugin.so` (`app.tar:app/plugins.xml:5`), the final output **is** softmax probabilities, computed on the ARM CPU.
- The output tensor is `[1,1001]` (1001 classes, background at 0) — matches `categories.txt` 1001-line expectation. `MP/TensorFlow_Frontend_IR_FPGA_dla_layer_device.csv`, `streaming_inference_app.cpp:379-397`.

### Does any runtime app apply softmax on CPU itself?
- No. `streaming_inference_app` sorts raw output and prints `score*100` (`streaming_inference_app.cpp:322-354`); `dla_benchmark` dumps raw tensors (`main.cpp:1448-1560`); no `exp`/softmax in `RT/dla_benchmark/top1_top5.hpp` or `utils.cpp` (grep). Probabilities come only from the graph (FPGA softmax or CPU-submodel softmax).

### Exact reproduction for k32c16
```bash
source /opt/intel/openvino_2024/setupvars.sh
source /opt/altera/fpga_ai_suite_2025.3.1/dla/bin/init_env.sh
cd ~/coredla_work/de25_nano_bringup/model_prep
dla_compiler --march AGX5_Nano_k32c16.arch \
  --network-file models_ir/public/resnet-50-tf/FP32/resnet-50-tf.xml \
  --foutput-format dla_compiled_result --o compiled/resnet50_k32c16.bin --fdisplay-device
```
`MP/.run_dla_compile_k32c16.sh`. Defaults in force: `--ffolding-option 1`, `--fplugin HETERO:FPGA,CPU`, `--fmin-subgraph-layers 2`, batch 1 (`dlac --help`). IR from `omz_downloader`/`omz_converter --mo` with `openvino-dev==2024.6.0`. `~/coredla_work/de25_nano_bringup/STEP4_INFERENCE_GUIDE.md:55-64`.
- To put softmax **on the FPGA** for k32c16 you must add the `custom_aux_primitive` softmax block + xbar/config_network entries to the arch (pattern in `AGX5_Small_Softmax.arch`), regenerate the IP with `dla_create_ip`, and re-run Quartus — not a dlac-only change. Runtime checks arch name against the fabric (`Runtime arch check passed`). `REL/README.md:151`.

---

## Q4. graph.bin load time and RAM

### Measured
- `Import model took 76642.1017 ms` for the 154 MB `resnet50_nosoftmax.bin` (qualified run 2026-08-17). `INVESTIGATION_LEDGER.md:466`; README: "≈ 76 s (normal … not a hang)". `REL/README.md:152`.
- Steady-state: latency 468-475 ms, 2.10-2.13 FPS system, IP 4.33 FPS. `REL/README.md:155-166`.
- `dla_benchmark` peaks ≈ 475 MB RSS; with `mem=768M` only 683 MB usable → OOM without the 2 GB swapfile. `REL/README.md:90-91`, `INVESTIGATION_LEDGER.md:755-757,1000`. Board is 1 GiB (not 2) at `0x8000_0000-0xBFFF_FFFF`. `INVESTIGATION_LEDGER.md:1047`.
- No first-inference-after-import timing recorded separately; `latency` above is per-frame steady state.

### What the 154 MB file is (why RSS is high)
- Compiled file = hetero header + FPGA submodel [dlac version, **full original FP32 IR xml + 102 MB weights blob** (`max const offset+size = 102130168` from the embedded `<net>`), compiled config/filter blobs] + CPU submodel (softmax). Export serialises `original_model_` in full. `SUITE/dla_plugin/src/dla_compiled_model.cpp:683-692`. Import copies xml+weights into an `ov::Tensor` and calls `read_model`. `SUITE/dla_plugin/src/dlia_plugin.cpp:121-135`.
- Callers double-buffer: `dla_benchmark` reads whole file into `std::string rest_of_data` then copies into `std::istringstream` (`RT/dla_benchmark/main.cpp:972-976`); `streaming_inference_app` does the same (`streaming_inference_app.cpp:123-127`). ⇒ ~2×154 MB transient + 102 MB weights tensor + compiled result ≈ the 475 MB peak. A custom server can free the file buffers after `import_model`.

### FPGA DDR carveout
- MMD: `dla_mmd_get_ddr_size_per_instance()` returns `1ULL << 28` (256 MiB) under `HPS_DE25_NANO` (generic AGX5 = 512 MiB). `RT/coredla_device/mmd/hps_platform/host/acl_hps.cpp:419-427`.
- DT: `mem_start 0xB0000000`, `mem_end 0xBFFFFFFF`; `WINDOW_BASE = 0xB0000000` in the span extender; carved out by `mem=768M`. `REL/source/socfpga_agilex5.dtsi.patch:36-55`, `REL/README.md:181-189`. Four places must agree. `REL/README.md:186-189`.
- Allocator initialised with that size per instance; graph job allocates config+filter buffer and writes it via `WriteToDDR`. `RT/coredla_device/src/coredla_device.cpp:167-169`, `RT/coredla_device/src/coredla_graph_job.cpp:216-241`.
- Actual footprint in the window for the k32c16-family compile: `configFilterBuffer 51,815,424 B` (config 467,968 + filter 51,347,456) + `inputOutputBuffer 425,472` + `interBuffer 3,813,376` ≈ **56 MB of 256 MB**. `MP/ddr_buffer_info_TensorFlow_Frontend_IR_0.txt`. The 256 MB window is a hard cap on *compiled* (FP12 filter + config + intermediates) size, not on the 154 MB file.
- Not CMA/reserved-memory: the region is simply above the kernel's `mem=` limit; `msgdma_userio` adds `mem_start` to file offsets. `REL/source/socfpga_agilex5.dtsi.patch:36-41`.

### Conclusion Q4
- Persistent process is mandatory (76 s import per process). After import, resident ≈ ov::Model (~102 MB weights) + compiled result (~52 MB) + OpenVINO/OpenCV libs (`app/*.so` ≈ 150 MB mapped, mostly shareable) — fits in 683 MB usable with 2 GB swap already provisioned. Peak during import (~475 MB) is the constraint; free the stream buffers after import and don't run two importers concurrently. Runtime memory of the DLA window (56/256 MB) is not a concern.
- Hetero/CPU submodel means softmax runs on the ARM CPU each frame — negligible (1001 elements).

---

## Weights-only recompile?
- `dlac --help` (2025.3.1, run locally) lists no weights-only / parameter-only option. Relevant flags: `--foutput-format {open_vino_hetero, dla_compiled_result}`, `--ffolding-option 0-3`, `--ffold-preprocessing`, `--fplugin`, `--fmin-subgraph-layers`, `--batch-size`, `--march`, `--gen-arch`, `--enable-early-access`. Full compile is the only documented path.
- Related but different: `dla_aot_splitter` splits a compiled model into input/config/filter blobs for running without OpenVINO (not a recompile). `RT/dla_aot_splitter/README.md:1-5`. Plugin property `PARAMETER_ROM_EXPORT_DIR` exports parameter-ROM blobs for DDR-free archs. `SUITE/dla_plugin/inc/dla_plugin_config.hpp:275-278`.
- Intel docs page for export formats redirects to a 404 (`https://www.intel.com/content/www/us/en/docs/programmable/768972/2024-2/compiler-graph-export-formats.html` → 301 to 404 redirector); the 2025.3 Compiler Reference Manual is download-only on altera.com (https://www.altera.com/downloads/add-development-tools/fpga-ai-suite-version-2025-3-ar). Local `dlac --help` is the primary source used.
- Practical note: filter blob is only ~51 MB (`ddr_buffer_info…txt`); a full k32c16 recompile on the host took minutes (script timestamps `MP/compiled/`), so cost is acceptable.

---

## Decisions needed from user
1. **Boot contract for the demo board**: keep `mem=768M` + CoreDLA DT nodes in the base DTB permanently (kernel sees 683 MB always) vs. move CoreDLA nodes into the Mender overlay and only fix `mem=768M` in the boot script. Live reconfig cannot create the carveout either way.
2. **Artifact split**: one `coredla-bundle` artifact per deploy (~830 MB incl. app.tar) vs. separate rare "runtime" artifact (sdklibs/OpenVINO, ~675 MB) + per-deploy "model" artifact (rbf+dtb+arch+bin+categories, ~150 MB). Second is recommended; needs two module types.
3. **Inference server**: write new C++ persistent server on the `-cm` import path (recommended) vs. drive `dla_benchmark` per request (76 s each) vs. build an S2M bitstream to use the stock streaming apps (new Platform Designer work + Nios stream controller).
4. **Softmax location**: accept CPU-submodel softmax in the current k32c16 graph (works today, probabilities out) vs. add softmax primitive to `AGX5_Nano_k32c16.arch` and rebuild IP+bitstream.
5. **Reconfig path on the CoreDLA board**: confirm `board-01`'s current SD card boots with `mem=768M` and whether `altera-msgdma` autoload is present (would panic on the idle GHRD bitstream). Board offline — could not verify.
6. **Timeouts/caps** in `LAB/config.py`/`mender_client.py`: raise `MAX_RBF_BYTES`-style cap for bundles and `poll_until_finished` beyond 300 s (150-830 MB download over Tailscale relay `sin`).
