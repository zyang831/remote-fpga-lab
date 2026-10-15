"""Split the real Commons photos (data/flag-real, from get_flag_photos.py) by title:
drop files whose title names another of our countries or a year (mislabeled /
historical), then per country the first 3 -> demo-images/flag/<label>_<nn>.jpg
(held-out test set + SOURCES.md) and the rest -> data/flag/<label>/real_*.jpg. Run after
make_flags.py (which leaves demo-images/flag/none_*.jpg alone here). Selection never looks
at model output.
"""
import re
import shutil
from pathlib import Path

from make_flags import COUNTRIES

HERE = Path(__file__).parent
src = HERE / "data" / "flag-real"
demo = HERE.parent / "demo-images" / "flag"
train = HERE / "data" / "flag"
N_DEMO = 3
demo.mkdir(parents=True, exist_ok=True)
for old in demo.iterdir():
    if not old.name.startswith("none_"):
        old.unlink()
for old in train.rglob("real_*.jpg"):
    old.unlink()
labels = sorted(COUNTRIES.values())
n_demo, n_train, out = {}, {}, ["# Sources (Wikimedia Commons)", ""]
for line in (src / "SOURCES.md").read_text().splitlines():
    m = re.match(r"- `([^/]+)/(\d+\.jpg)` — File:(.*?) — ", line)
    if not m:
        continue
    label, fname, title = m.groups()
    t = title.lower()
    if any(l != label and l in t for l in labels) or re.search(r"\b(1[6-9]\d\d|20[0-1]\d)\b", t):
        continue
    if n_demo.get(label, 0) < N_DEMO:
        n = n_demo[label] = n_demo.get(label, 0) + 1
        shutil.copyfile(src / label / fname, demo / f"{label}_{n - 1:02d}.jpg")
        out.append(line.replace(f"`{label}/{fname}`", f"`{label}_{n - 1:02d}.jpg`"))
    else:
        n = n_train[label] = n_train.get(label, 0) + 1
        (train / label).mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src / label / fname, train / label / f"real_{n - 1:02d}.jpg")
(demo / "SOURCES.md").write_text("\n".join(out) + "\n")
print(f"demo {sum(n_demo.values())} images / {len(n_demo)} countries; "
      f"train real {sum(n_train.values())} images / {len(n_train)} countries")
print("countries with < 3 real train photos:", {l: n_train.get(l, 0) for l in labels if n_train.get(l, 0) < 3})
