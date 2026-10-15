# Files used in the paper but NOT in this repository

They are derivatives of Altera FPGA AI Suite / Quartus IP, Terasic material or are too large. The Altera FPGA AI Suite licence allows distributing FPGA images and runtime derivatives only embedded in licensed products under an end-user licence (see Altera licence s.3 and s.4); a public repository is not that. Rebuild each file with your own licensed tools using the guides; compare your build with the sha256 below (bit-identical output is not guaranteed across tool runs, so a different hash is not an error; verify function with the checks in REPLICATION.md).

| file (as named in the experiments) | size B | sha256 | what it is |
|---|---|---|---|
| 1-bitstream/led-bouncing.core.rbf | 1687552 | 96e2d06e2890fffb2e649649cadc7d5560552225283959cde0dc5066a97bca4f | student demo design (D2/D3 bitstream series) |
| 1-bitstream/led-johnson.core.rbf | 1679360 | fe5d6d9e698238c27f7643c4bcaa6798a2612f64c5349160032070d421e52e65 | student demo design |
| 1-bitstream/ghrd.core.rbf | 1576960 | 0415d069a907a36ce70c21b33f111004e9fe627aa35d2c77fb0bc8f76d1447d0 | Terasic GHRD-derived design |
| 1-bitstream/edge-ai-dla.core.rbf | 3747840 | f1e4ab4d29fd4a41ccad5dcaceeedd149cebed397127b5be3cb8341c9fa46cde | CoreDLA design AGX5_Small_k16c16_sb20480 + camera (the board's idle/boot design) |
| CoreDLA_NoSoftmax/output_design.core.rbf | 3284992 | 929cf663a8dc1b9b31001f4cae8d3f0f733d015cba0edf19803d24ee2aa9ed16 | CoreDLA variant (see folder name) |
| CoreDLA_Softmax/output_design.core.rbf | 3403776 | 97384bc0baff8ce90326cab1184f49b99bf4002b871829d90a2be29f30fdf282 | CoreDLA variant (see folder name) |
| board/dla_sb12883.core.rbf | 3764224 | ce45df7113aed70d0b4d0d4bcdb4feacc809ad34369294d553c40242fa71ddeb | CoreDLA stream-buffer 12883 variant |
| fruit-v1/graph.bin | 67231231 | fa07ff382b2b91661a86aa81e93135e8f6b964711ab66de14d93c423c61b4c26 | compiled DLA graph (dla_compiler output) for the model of the same name |
| flag/graph.bin | 67280448 | eb29566bd212e467ee45c9e84a77eb2a92901bfb9fb93b5eeda2a69ddad5747d | compiled DLA graph (dla_compiler output) for the model of the same name |
| fruit-v1/AGX5_Small_k16c16_sb20480.arch | 2046 | eaee702fbd4e8168bfb42a16248d88aba5f5eedbf6f38f818713b1deecf330ea | DLA architecture file (AI Suite example arch, k16 c16, stream buffer 20480) |
| runtime/libcoreDlaRuntimePlugin.so | 16782976 | 69fc303ad4c858ea4983d3994a8c18b100a9a27bffbd4df95ece27a0ae11174c | CoreDLA runtime plugin (HPS build) |
| runtime/libcoreDLAHeteroPlugin.so | 14106160 | b7f4d59a0035f84e34dede49618a676f341ea3a16d88920a64e29c4823b4e1f5 | CoreDLA hetero plugin |
| runtime/libhps_platform_mmd.so | 745648 | 329a215bf7dbf04b48959d7b3e2e78647efdb4e40867ecb6004971efca24ecb7 | HPS MMD (patched, see RUNBOOK) |
| CoreDLA_GHRD/sdcard.img | 5767168000 | 17ac98f9d7aeeb1adcf76fec123f7f8d37f43970a5671f4c8085c4e93d75e026 | base SD image (Yocto-free Ubuntu 22.04 rootfs + kernel 6.12.11), see SDCARD_IMAGE_GUIDE |

Other things you must obtain yourself (not redistributable here): Quartus Prime Pro 25.3.1 and Altera FPGA AI Suite 2025.3.1 (vendor downloads, licence required); Terasic DE25-Nano resource package and GHRD (Terasic site); Linux socfpga, U-Boot and ATF sources (public upstream, versions in the guides); Mender server source (github.com/mendersoftware/mender-server) and the Mender client 5.1.0; the Fruits dataset used for the fruit model (see training/README.md).
