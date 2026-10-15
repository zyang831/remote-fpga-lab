"""Phase 3: validate a user-uploaded OpenVINO IR against the reference ResNet-18.

Topology is fixed (plan: only the final FC dims may vary), so the uploaded
model.xml must equal the reference layer for layer, port for port, edge for
edge, with exactly one allowed difference: wherever the reference has the
reference class count, the upload has its own. Names, bin offsets/sizes and
tensor names are export noise and ignored. The real safety gate is dla_compiler
on the host; this check just fails fast with a message the user can act on.
"""

import re
import xml.etree.ElementTree as ET

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
_SKIP_ATTRS = {"offset", "size", "names", "name"}


def read_categories(data: bytes) -> list[str]:
    try:
        text = data.decode("utf-8-sig")  # Notepad may prepend a BOM
    except UnicodeDecodeError:
        raise ValueError("categories.txt is not UTF-8") from None
    cats = text.rstrip().splitlines()  # CRLF and trailing blank lines from a Windows editor are fine
    if len(cats) < 2 or any(not c.strip() for c in cats):
        raise ValueError("categories.txt needs one non-empty label per line, at least two lines")
    return cats


def _canon(xml_bytes: bytes) -> tuple[list, list]:
    """(layers, edges): every value that could legally carry the class count as a str."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        raise ValueError(f"model.xml is not well-formed XML ({e})") from None
    if root.tag != "net":
        raise ValueError("model.xml is not an OpenVINO IR (<net> root missing)")
    layers = []
    for layer in root.iter("layer"):
        ports = []
        for side in ("input", "output"):
            for port in layer.iter(side):
                for p in port.iter("port"):
                    ports.append((side, p.get("id"), [d.text.strip() for d in p.iter("dim")]))
        data = layer.find("data")
        attrs = [] if data is None else sorted(
            (k, [t.strip() for t in v.split(",")]) for k, v in data.attrib.items() if k not in _SKIP_ATTRS
        )
        layers.append((layer.get("id"), layer.get("type"), layer.get("version"), attrs, ports))
    # (from-layer, to-layer) only: torch/openvino versions differ in operand order
    # (which port a residual Add or a constant lands on) but not in which layers
    # connect. Sorted multiset, so a fan-out into two ports of one layer still counts twice.
    edges = sorted((e.attrib["from-layer"], e.attrib["to-layer"]) for e in root.iter("edge"))
    return layers, edges


def _same(a, b, n_ref: str, n_user: str) -> bool:
    """Structural equality where n_ref on the reference side may match n_user on the user side."""
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_same(x, y, n_ref, n_user) for x, y in zip(a, b))
    return a == b or (a == n_ref and b == n_user)


def check_ir(xml_bytes: bytes, reference_xml: bytes, n_ref: int, n_user: int) -> None:
    """Raises ValueError naming the first layer that differs from the reference."""
    layers, edges = _canon(xml_bytes)
    ref_layers, ref_edges = _canon(reference_xml)
    if len(layers) != len(ref_layers):
        raise ValueError(f"model.xml has {len(layers)} layers, the reference ResNet-18 has {len(ref_layers)}")
    for lay, ref in zip(layers, ref_layers):
        if not _same(ref, lay, str(n_ref), str(n_user)):
            raise ValueError(
                f"layer id={lay[0]} ({lay[1]}) differs from the reference ResNet-18 ({ref[1]}); "
                f"only the final FC size may change, and it must be {n_user} (lines in categories.txt)"
            )
    if edges != ref_edges:
        raise ValueError("model.xml edges differ from the reference ResNet-18")
    # Every N-shaped dim on the reference side must have become n_user, not stayed n_ref.
    if n_ref != n_user and _same(layers, ref_layers, "", "") is True:
        raise ValueError(f"model.xml output is [1,{n_ref}] but categories.txt has {n_user} lines")


if __name__ == "__main__":
    # Self-check against the real exports: python model_upload.py
    from pathlib import Path

    root = Path.home() / "edge-ai-demo" / "models"
    fruit = (root / "fruit-v1" / "model.xml").read_bytes()  # the reference: notebook kit, ResNet-18, 15 classes
    assert read_categories((root / "fruit-v1" / "categories.txt").read_bytes()) == read_categories(
        b"\n".join(l.encode() for l in (root / "fruit-v1" / "categories.txt").read_text().split("\n"))
    )
    check_ir(fruit, fruit, 15, 15)
    for bad, n, msg in (
        (fruit, 16, "has 16 lines"),
        (fruit.replace(b"</layers>", b'<layer id="999" type="Relu" version="opset1"/></layers>', 1), 15, "layers"),
        (fruit.replace(b'type="SoftMax"', b'type="Sigmoid"', 1), 15, "differs"),
        (fruit.replace(b'<dim>224</dim>', b'<dim>256</dim>', 1), 15, "differs"),
        (fruit.replace(b'to-layer="2" to-port="0"', b'to-layer="4" to-port="0"', 1), 15, "edges"),
        (b"<html/>", 15, "not an OpenVINO IR"),
        (b"<net", 15, "not well-formed"),
    ):
        try:
            check_ir(bad, fruit, 15, n)
            raise AssertionError(f"accepted a bad IR ({msg})")
        except ValueError as e:
            assert msg in str(e), (msg, e)
    assert read_categories(b"\xef\xbb\xbfapple\r\nbanana\r\n\r\n") == ["apple", "banana"]
    for bad in (b"", b"one\n", b"a\n\nb\n", "é".encode("latin-1")):
        try:
            read_categories(bad)
            raise AssertionError(f"accepted {bad!r}")
        except ValueError:
            pass
    assert NAME_RE.match("my-model-1") and not NAME_RE.match("My Model") and not NAME_RE.match("-x")
    print("ok: model_upload self-check")
