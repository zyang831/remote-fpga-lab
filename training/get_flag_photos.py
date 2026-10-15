"""Real flag photos for the held-out test set, from Wikimedia Commons search
(JPEG only, CC0/CC BY/CC BY-SA/public domain only, 640 px thumbnails).

  python get_flag_photos.py            # -> data/flag-real/<label>/<nn>.jpg + SOURCES.md

split_flag_real.py then title-filters them: first 3 per country -> demo-images/flag
(held out), the rest -> data/flag/train/<label>/real_*.jpg (plan §2.2 risk clause).
"""
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from make_flags import COUNTRIES

HERE = Path(__file__).parent
OUT = HERE / "data" / "flag-real"
UA = {"User-Agent": "edge-ai-demo/0.1 (Monash FYP; tzyang0831@gmail.com)"}
OK_LICENSE = re.compile(r"^(CC0|CC BY( |-SA )\d|Public domain)", re.I)
PER_COUNTRY = 25
# Extra title phrases for countries where "flag of X" alone finds too few photos.
ALT = {
    "united states": ["american flag", "US flag", "stars and stripes"],
    "united kingdom": ["union jack", "british flag", "union flag"],
    "malaysia": ["malaysian flag", "jalur gemilang"],
    "saudi arabia": ["saudi flag", "saudi arabian flag"],
    "philippines": ["philippine flag", "philippines flag"],
    "singapore": ["singapore flag", "singaporean flag"],
    "indonesia": ["indonesian flag", "indonesia flag"],
    "portugal": ["portuguese flag"], "australia": ["australian flag"],
    "new zealand": ["new zealand flag"], "south africa": ["south african flag"],
    "switzerland": ["swiss flag"], "south korea": ["korean flag", "taegukgi"],
}


def api(params):
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({"format": "json", **params})
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return json.load(r)


lines = ["# Sources (Wikimedia Commons)", ""]
for code, label in COUNTRIES.items():
    d = OUT / label
    d.mkdir(parents=True, exist_ok=True)
    n, seen, pages = 0, set(), []
    for phrase in [f"flag of {label}"] + ALT.get(label, []):
        res = api({"action": "query", "generator": "search", "gsrnamespace": 6, "gsrlimit": 80,
                   # intitle: keeps it to files named after the flag; the bare phrase search
                   # returns crowds, buildings and emblems (tried: 15 % usable).
                   "gsrsearch": f'intitle:"{phrase}" (waving OR flagpole OR flying OR flag) '
                                f'filetype:bitmap -intitle:map -intitle:coat', "prop": "imageinfo",
                   "iiprop": "url|extmetadata|size|mime", "iiurlwidth": 640})
        for p in sorted(res.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 0)):
            if p["title"] not in seen:
                seen.add(p["title"])
                pages.append(p)
    for p in pages:
        if "imageinfo" not in p:  # some search hits carry no file info
            continue
        ii = p["imageinfo"][0]
        meta = ii.get("extmetadata", {})
        lic = meta.get("LicenseShortName", {}).get("value", "")
        if ii["mime"] != "image/jpeg" or ii["width"] < 640 or not OK_LICENSE.match(lic):
            continue
        dest = d / f"{n:02d}.jpg"
        try:
            with urllib.request.urlopen(urllib.request.Request(ii["thumburl"], headers=UA), timeout=60) as r:
                dest.write_bytes(r.read())
        except Exception as e:  # one bad thumb should not stop the run
            print("skip", p["title"], e)
            continue
        artist = re.sub(r"<[^>]+>", "", meta.get("Artist", {}).get("value", "")).strip()
        lines.append(f"- `{label}/{dest.name}` — {p['title']} — {lic} — {artist} — {ii['descriptionurl']}")
        n += 1
        if n >= PER_COUNTRY:
            break
    print(f"{label:16s} {n}")
    time.sleep(0.5)
(OUT / "SOURCES.md").write_text("\n".join(lines) + "\n")
