# D4 upload rejection matrix (2026-10-15; D4-matrix/matrix.csv, script ../run_D4.py)

Each case n=3 (fresh session each). 'deployment' = a new Mender deployment appeared. Board state after = live model | dla-server | fpga manager, checked until healthy. Backend commit 1cd01b9 (+3 modified files).

| kind | case | n | HTTP | message (first 90 chars) | deployment created | answer s | final state | board after |
|---|---|---|---|---|---|---|---|---|
| bit | empty file | 3 | 400 | not an Agilex 5 .core.rbf (unexpected header) | 0 | 0.0 | - | healthy |
| bit | random bytes 2 MiB | 3 | 400 | not an Agilex 5 .core.rbf (unexpected header) | 0 | 0.0 | - | healthy |
| bit | valid header, 64 KiB cut | 3 | 400 | too small to be a complete Agilex 5 .core.rbf | 0 | 0.0 | - | healthy |
| bit | valid file cut to 75% | 3 | 200 | {"programming": true} | 1 | 0.0 | fail:failed | healthy |
| bit | wrong header, right size | 3 | 400 | not an Agilex 5 .core.rbf (unexpected header) | 0 | 0.0 | - | healthy |
| bit | valid header + 9 MiB | 3 | 413 | bitstream exceeds 8388608 bytes | 0 | 0.0 | - | healthy |
| bit | wrong extension | 3 | 400 | filename must end in .rbf | 0 | 0.0 | - | healthy |
| model | ResNet-50 (wrong topology) | 3 | 400 | model.xml has 292 layers, the reference ResNet-18 has 120 | 0 | 0.1 | - | healthy |
| model | extra layer | 3 | 400 | model.xml has 121 layers, the reference ResNet-18 has 120 | 0 | 0.1 | - | healthy |
| model | final layer (SoftMax) missing | 3 | 400 | model.xml has 119 layers, the reference ResNet-18 has 120 | 0 | 0.1 | - | healthy |
| model | SoftMax replaced by Sigmoid | 3 | 400 | layer id=118 (Sigmoid) differs from the reference ResNet-18 (SoftMax); only the final FC s | 0 | 0.1 | - | healthy |
| model | preprocessing (Divide) missing | 3 | 400 | model.xml has 119 layers, the reference ResNet-18 has 120 | 0 | 0.1 | - | healthy |
| model | categories: one extra line | 3 | 400 | model.xml output is [1,15] but categories.txt has 16 lines | 0 | 0.1 | - | healthy |
| model | categories: empty | 3 | 400 | categories.txt needs one non-empty label per line, at least two lines | 0 | 0.1 | - | healthy |
| model | categories: one line | 3 | 400 | categories.txt needs one non-empty label per line, at least two lines | 0 | 0.0 | - | healthy |
| model | categories: blank line inside | 3 | 400 | categories.txt needs one non-empty label per line, at least two lines | 0 | 0.0 | - | healthy |
| model | name: uppercase/space | 3 | 400 | name must be 1-32 chars of a-z, 0-9, - (starting with a letter or digit) | 0 | 0.0 | - | healthy |
| model | name: starts with dash | 3 | 400 | name must be 1-32 chars of a-z, 0-9, - (starting with a letter or digit) | 0 | 0.0 | - | healthy |
| model | name: 33 chars | 3 | 400 | name must be 1-32 chars of a-z, 0-9, - (starting with a letter or digit) | 0 | 0.0 | - | healthy |
| model | name: built-in 'fruit' | 3 | 400 | fruit is a built-in model; pick another name | 0 | 0.1 | - | healthy |
| model | model.xml truncated (half) | 3 | 400 | model.xml is not well-formed XML (unclosed token: line 1268, column 3) | 0 | 0.1 | - | healthy |
| model | model.bin truncated (half) | 3 | 400 | model.bin is 22358834 bytes; a 15-class ResNet-18 IR should be 44717668 | 0 | 0.0 | - | healthy |
| model | model.xml not OpenVINO (random bytes) | 3 | 400 | model.xml is not well-formed XML (not well-formed (invalid token): line 1, column 0) | 0 | 0.0 | - | healthy |
| model | model.bin not weights (random, right size) | 3 | 200 | {"building": true, "classes": 15} | 0 | 0.1 | fail:failed | healthy |
| model | ACCEPT? duplicate categories | 3 | 200 | {"building": true, "classes": 15} | 1 | 0.1 | build:ok | healthy |
| model | ACCEPT: valid, random weights | 3 | 200 | {"building": true, "classes": 15} | 0 | 0.1 | fail:failed | healthy |
| model | ACCEPT: valid weights, labels reversed (wrong answers) | 3 | 200 | {"building": true, "classes": 15} | 1 | 0.1 | build:ok | healthy |

Findings:
- Bitstream: 6 of 7 cases refused at upload (HTTP 400/413), no Mender deployment, about 0 s, board untouched. A valid file cut to 75% passes every check (200), creates a deployment, fails on the board (fail:failed) and Mender rolls back; board healthy afterwards in 3/3. The check cannot see truncation above 1 MiB; the board is the second line of defence.
- Model: topology, layer count, SoftMax/preprocessing removal, class-count vs categories mismatch, empty/one-line/blank-line categories, bad names, truncated xml/bin, non-XML are all refused at upload with a message naming the problem (HTTP 400), no deployment, in under 0.2 s.
- Gaps: duplicate category labels are accepted, built and deployed (3/3). A valid IR with wrong labels (reversed order) is accepted and deployed (3/3): the platform cannot judge training quality. A model.bin of random bytes with the right size is accepted at upload (200) and caught only by the build-time load check (build failed, no deployment); the same for random float weights.
- 'ACCEPT: valid, random weights' overwrote the integer shape constants as well, so it measures the build-time check, not 'badly trained'. The corrected badly-trained case is 'labels reversed'.
- Cleanup: test models deleted via API (catalog back to fruit/flag/imagenet), leftover rej-* directories and 39 test .rbf uploads of 2026-10-15 removed, board on fruit.
Feeds: new Table 'Upload checks' replacing Table IV rows 'Garbage or 64-KiB'; R4 acceptance wording: from 'described, not tested' to this matrix.
