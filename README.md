# Remote FPGA lab: OTA-updated CoreDLA classifier on a DE25-Nano

Code for the paper's remote lab: FastAPI lab backend (`backend/`), Mender update modules and board services (`board/`), the dla-server source (`dla-server/`), build/deploy helpers (`artifacts/`), design notes (`docs/`), and training code (`training/`, notebook in `backend/static/`). MIT licensed (see `LICENSE`).

## Not included
Bitstreams (`*.rbf`), compiled graphs, runtime libraries, the Quartus project and the Terasic board package. The CoreDLA bitstream and runtime are derivatives of the Altera FPGA AI Suite, whose licence allows distribution only embedded in licensed products under an end-user licence at least as restrictive as its Exhibit A. To rebuild you need Quartus Prime Pro 25.3.1, the Altera FPGA AI Suite 2025.3.1 and the Terasic DE25-Nano package under your own licences. The hashes of the bitstreams used in the paper are listed in the paper's data notes.

## Versions measured
Snapshot of the working trees at paper revision 2 (see `SNAPSHOT.md` for base commits).
