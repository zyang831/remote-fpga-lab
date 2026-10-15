# Sources (fetched 2026-09-28)

Third-party figures, unmodified. Cite them on any slide or poster that shows them.

## Mender documentation: CC BY 4.0 (github.com/mendersoftware/mender-docs)

Credit line: "Figure: Mender documentation (Northern.tech), CC BY 4.0, docs.mender.io"

- `mender-updater-components.png`: build system → Mender Server → devices (client polls "check for update").
  https://docs.mender.io/overview/introduction
- `mender-deployment-lifecycle.png`: CREATED → PENDING → INPROGRESS (pending, downloading, installing,
  rebooting) → FINISHED (success, failure, …). https://docs.mender.io/overview/deployment
- `mender-update-module-states.png`: Update Module state machine (Download, ArtifactInstall,
  ArtifactCommit, ArtifactRollback, …). https://docs.mender.io/artifact-creation/create-a-custom-update-module
- `mender-artifact-format.png`: layout of a `.mender` artifact. https://docs.mender.io/overview/artifact

## Altera FPGA Developer Site: no licence stated, © Altera

Credit line: "Figure: Altera, FPGA AI Suite SoC Design Example (rel-25.3.1), altera-fpga.github.io".
No licence is given, so reuse depends on fair dealing for academic presentation. Check with your
supervisor before printing on the poster.

Page: https://altera-fpga.github.io/rel-25.3.1/ed-ai-suite/agilex5/soc/fpga_ai_suite_soc_design_example/

- `aisuite-software-stack.png`: "Software Stacks for FPGA AI Suite Inference" (compilation stack:
  OpenVINO → IR → FPGA AI Suite Compiler + `.arch` → CompiledNetwork.bin; runtime stack: OpenVINO
  Hetero plugin → FPGA AI Suite runtime plugin → driver). Section 3.3, Figure 1.
- `aisuite-soc-m2m-block.png`: "Block Diagram of M2M Variant" (ARM SoC, mSGDMA, AI Suite IP, EMIF). Figure 4.
- `aisuite-soc-inference-sequence.png`: "SoC Design Example Inference Sequence Overview" (host CPU
  runtime → DLA job queue / DMA / PE array ↔ DDR buffers). Figure 3.
