"""Step 3 of the guide: fine-tune ImageNet ResNet-18 on data/<name>-split/{train,val}/<label>/
(made by prepare.py).

  python train.py fruit [--epochs 30] [--no-flip] [--no-sim] [--sim-p 0.3] [--arch resnet50|mobilenet_v2] [--teacher RUN]

--arch: another backbone (resnet50 = the pre-2026-09-28 models, ~2.5x slower on the board);
  writes runs/<name>-<arch>/ instead.
--teacher: distil from runs/<RUN>/model.pt (e.g. `flag-resnet50`): the loss mixes the
  labels with the teacher's softened outputs on the same augmented batch, which carries
  the big net's robustness over to a small one.
Catalog recipes (2026-09-28): fruit with the defaults; flag `--no-flip --teacher flag-resnet50
  --sim-p 0.5` (teacher = `train.py flag --arch resnet50 --no-flip`).

--no-flip: for classes a mirror image changes (flags, text, logos).
--no-sim:  skip the camera/screen simulation (augment.CameraScreen).

Schedule: 2 epochs training only the new last layer (the pretrained backbone stays
frozen), then all layers at a low learning rate ("linear probe, then fine-tune").
The last epoch is kept: runs/<name>/model.pt (state_dict + classes + arch), metrics.json,
confusion.txt. Val uses the deploy transform (centre square, 224x224) and is printed
per epoch to watch progress, not to pick a checkpoint.

At the end the model is checked on ../demo-images/<name>/<label>_<nn>.jpg if present
(held-out photos, never trained on; none_<nn>.jpg are negatives): top-1 as they are,
top-1 through the camera/screen simulation, and none recall, each PASS at >= 80 %.
The numbers are a sanity check, not a gate.
"""
import argparse
import json
import random
import time
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image
from torchvision import datasets, transforms

from augment import CameraScreen, RotateNoCorners
from common import ARCHS, MEAN, ROOT, STD, backbone, categories, center_square, run_name

ap = argparse.ArgumentParser()
ap.add_argument("name")
ap.add_argument("--epochs", type=int, default=30)
ap.add_argument("--batch", type=int, default=32)
ap.add_argument("--no-flip", action="store_true", help="chiral classes (flags)")
ap.add_argument("--no-sim", action="store_true", help="no camera/screen simulation")
ap.add_argument("--arch", choices=ARCHS, default=ARCHS[0])
ap.add_argument("--teacher", help="runs/<dir> of a trained model to distil from (its soft outputs on each batch)")
ap.add_argument("--sim-p", type=float, default=0.3, help="probability of each camera/screen effect")
args = ap.parse_args()

HERE = Path(__file__).parent
classes = categories(args.name)
norm = transforms.Normalize(MEAN.flatten().tolist(), STD.flatten().tolist())
train_tf = transforms.Compose([
    transforms.RandomResizedCrop(224, scale=(0.5, 1.0)),
    RotateNoCorners(45),
    *([] if args.no_flip else [transforms.RandomHorizontalFlip()]),
    transforms.ColorJitter(0.3, 0.3, 0.3, 0.05),
    *([] if args.no_sim else [CameraScreen(p=args.sim_p)]),
    transforms.ToTensor(), norm,
])
deploy_tf = transforms.Compose([transforms.Lambda(center_square), transforms.Resize((224, 224))])
val_tf = transforms.Compose([deploy_tf, transforms.ToTensor(), norm])
data = HERE / "data" / f"{args.name}-split"
train_ds = datasets.ImageFolder(data / "train", train_tf)
val_ds = datasets.ImageFolder(data / "val", val_tf)
assert train_ds.classes == classes, f"folder classes {train_ds.classes} != categories.txt {classes}"
assert val_ds.classes == classes
train_dl = torch.utils.data.DataLoader(train_ds, args.batch, shuffle=True, num_workers=8)
val_dl = torch.utils.data.DataLoader(val_ds, 64, num_workers=8)

dev = "cuda"
model = backbone(args.arch, len(classes)).to(dev)
head = model.fc if hasattr(model, "fc") else model.classifier
head_ids = {id(p) for p in head.parameters()}
body = [p for p in model.parameters() if id(p) not in head_ids]
opt = torch.optim.AdamW([{"params": body, "lr": 1e-4}, {"params": head.parameters(), "lr": 1e-3}],
                        weight_decay=1e-4)
sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, args.epochs * len(train_dl))
loss_fn = nn.CrossEntropyLoss(label_smoothing=0.1)
scaler = torch.amp.GradScaler()
FREEZE_EPOCHS = 2
teacher = None
if args.teacher:
    tck = torch.load(HERE / "runs" / args.teacher / "model.pt", map_location="cpu", weights_only=True)
    assert tck["classes"] == classes, "teacher classes != categories.txt"
    teacher = backbone(tck.get("arch", "resnet50"), len(classes))  # pre-arch checkpoints are ResNet-50
    teacher.load_state_dict(tck["state_dict"])
    teacher.to(dev).eval()
KD_T, KD_W = 4.0, 0.7  # distillation temperature and weight (the rest is the label loss)


def evaluate():
    model.eval()
    hit1 = hit5 = n = 0
    conf = torch.zeros(len(classes), len(classes), dtype=torch.int64)
    with torch.no_grad(), torch.autocast(dev):
        for x, y in val_dl:
            out = model(x.to(dev)).float().cpu()
            top5 = out.topk(min(5, len(classes)), 1).indices
            hit1 += (top5[:, 0] == y).sum().item()
            hit5 += (top5 == y[:, None]).any(1).sum().item()
            n += len(y)
            for t, p in zip(y, top5[:, 0]):
                conf[t, p] += 1
    return hit1 / n, hit5 / n, conf


def checks() -> dict:
    """Held-out demo images: clean, through the camera/screen simulation, and none recall."""
    demo = sorted((ROOT / "demo-images" / args.name).glob("*.jpg"))
    if not demo:
        print(f"no demo-images/{args.name}/ -> skipping the held-out checks")
        return {}
    random.seed(0)
    sim = CameraScreen(p=0.5)
    hits = {"held-out photos": [], "held-out photos, camera/screen sim": [], "none recall (held-out negatives)": []}
    model.eval()
    with torch.no_grad():
        for f in demo:
            truth = f.name.rsplit("_", 1)[0]
            if truth not in classes:
                print(f"skip {f.name}: {truth!r} is not a class")
                continue
            img = deploy_tf(Image.open(f).convert("RGB"))
            for key, im in (("clean", img), ("sim", sim(img))):
                pred = classes[int(model(norm(transforms.functional.to_tensor(im))[None].to(dev)).argmax())]
                if truth == "none":
                    hits["none recall (held-out negatives)"].append(pred == "none")
                else:
                    hits["held-out photos" if key == "clean" else "held-out photos, camera/screen sim"].append(pred == truth)
    out = {}
    for k, v in hits.items():
        if v:
            out[k] = sum(v) / len(v)
            print(f"  {k:36s} {sum(v):3d}/{len(v):3d} = {out[k]:.2f}  {'PASS' if out[k] >= 0.8 else 'LOW'}")
    return out


out_dir = HERE / "runs" / run_name(args.name, args.arch)
out_dir.mkdir(parents=True, exist_ok=True)
history = []
for epoch in range(args.epochs):
    for p in body:
        p.requires_grad_(epoch >= FREEZE_EPOCHS)
    model.train()
    t0, tot, cnt = time.time(), 0.0, 0
    for x, y in train_dl:
        x, y = x.to(dev), y.to(dev)
        with torch.autocast(dev):
            logits = model(x)
            loss = loss_fn(logits, y)
            if teacher is not None:
                with torch.no_grad():
                    soft = F.softmax(teacher(x).float() / KD_T, 1)
                kd = F.kl_div(F.log_softmax(logits.float() / KD_T, 1), soft, reduction="batchmean") * KD_T ** 2
                loss = (1 - KD_W) * loss + KD_W * kd
        opt.zero_grad(set_to_none=True)
        scaler.scale(loss).backward()
        scaler.step(opt)
        scaler.update()
        sched.step()
        tot += loss.item() * len(y)
        cnt += len(y)
    top1, top5, conf = evaluate()
    history.append({"epoch": epoch + 1, "loss": tot / cnt, "val_top1": top1, "val_top5": top5})
    print(f"epoch {epoch + 1:2d}  loss {tot / cnt:.3f}  val top-1 {top1:.3f}  top-5 {top5:.3f}  {time.time() - t0:.0f}s")

torch.save({"state_dict": model.state_dict(), "classes": classes, "arch": args.arch}, out_dir / "model.pt")
(out_dir / "confusion.txt").write_text(
    "val, rows = truth, cols = predicted\n" + "\n".join(f"{c:16s} " + " ".join(f"{v:3d}" for v in row)
                                                     for c, row in zip(classes, conf.tolist())) + "\n")
print(f"final val top-1 {top1:.3f} -> {out_dir / 'model.pt'}")
print("held-out checks (sanity, not a gate):")
(out_dir / "metrics.json").write_text(json.dumps({"epochs": history, "checks": checks()}, indent=1))
