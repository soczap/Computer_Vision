"""Benchmark candidate violence classifiers on held-out RWF-2000 val clips.

Measured, not assumed: prints AUC and best-threshold accuracy per model so the
production choice rests on this site's evaluation rather than on model cards.
"""
import glob, sys, time
import cv2, numpy as np, torch
from transformers import AutoModelForVideoClassification, AutoModelForImageClassification, AutoImageProcessor

ROOT = "data/testclips"
clips = [(p, 1) for p in sorted(glob.glob(f"{ROOT}/Fight/*.avi")) if "_processed" not in p] + \
        [(p, 0) for p in sorted(glob.glob(f"{ROOT}/NonFight/*.avi")) if "_processed" not in p]
print("clips", len(clips), "fight", sum(l for _, l in clips))

def read_frames(path, n=16):
    cap = cv2.VideoCapture(path); frames = []
    while True:
        ok, f = cap.read()
        if not ok: break
        frames.append(cv2.cvtColor(f, cv2.COLOR_BGR2RGB))
    idx = np.linspace(0, len(frames) - 1, n).astype(int)
    return [frames[i] for i in idx]

def auc(scores, labels):
    s = np.array(scores); l = np.array(labels)
    pos, neg = s[l == 1], s[l == 0]
    return float(np.mean([(p > n) + 0.5 * (p == n) for p in pos for n in neg]))

def best_acc(scores, labels):
    s = np.array(scores); l = np.array(labels)
    return max(((s >= t) == l).mean() for t in np.unique(s))

dev = "cuda"

def load_videomae(path):
    """Load VideoMAE, remapping the legacy q_bias/v_bias layout.

    Old checkpoints store attention biases as q_bias/v_bias (no key bias);
    transformers 5 expects query/key/value .bias and would otherwise
    silently re-initialise them randomly.
    """
    import os
    from transformers import VideoMAEConfig
    sd_path = os.path.join(path, "pytorch_model.bin")
    if not os.path.exists(sd_path):
        return AutoModelForVideoClassification.from_pretrained(path)
    sd = torch.load(sd_path, map_location="cpu")
    fixed = {}
    for k, v in sd.items():
        if k.endswith("attention.attention.q_bias"):
            base = k[: -len("q_bias")]
            fixed[base + "query.bias"] = v
            fixed[base + "key.bias"] = torch.zeros_like(v)
        elif k.endswith("attention.attention.v_bias"):
            fixed[k[: -len("v_bias")] + "value.bias"] = v
        else:
            fixed[k] = v
    from transformers import VideoMAEForVideoClassification
    m = VideoMAEForVideoClassification(VideoMAEConfig.from_pretrained(path))
    missing, unexpected = m.load_state_dict(fixed, strict=False)
    assert not missing and not unexpected, (missing, unexpected)
    return m
data = [(read_frames(p), l) for p, l in clips]
results = {}
for name, path, idx in [("vmae_lmazzon", "models/cand/vmae_lmazzon", 0), ("vmae_happygook", "models/cand/vmae_happygook", 1)]:
    proc = AutoImageProcessor.from_pretrained(path)
    m = load_videomae(path).to(dev).eval().half()
    sc = []; t = time.time()
    for frames, _ in data:
        x = proc(frames, return_tensors="pt")["pixel_values"].to(dev).half()
        with torch.no_grad():
            sc.append(float(torch.softmax(m(pixel_values=x).logits.float(), -1)[0, idx]))
    results[name] = sc
    print(name, "ms/clip", (time.time() - t) / len(data) * 1000)
from transformers import ViTImageProcessor
proc = ViTImageProcessor.from_pretrained("models/cand/vit_violence")
from transformers import ViTForImageClassification
m = ViTForImageClassification.from_pretrained("models/cand/vit_violence").to(dev).eval()
sc = []
for frames, _ in data:
    x = proc(frames[::2], return_tensors="pt")["pixel_values"].to(dev)
    with torch.no_grad():
        sc.append(float(torch.softmax(m(pixel_values=x).logits, -1)[:, 1].mean()))
results["vit_frame_label1"] = sc
import open_clip
cm, _, cpre = open_clip.create_model_and_transforms("ViT-B-32", pretrained="laion2b_s34b_b79k")
cm = cm.to(dev).eval(); tok = open_clip.get_tokenizer("ViT-B-32")
pos = ["people fighting", "a person punching another person", "a violent brawl", "people kicking someone", "a physical assault"]
neg = ["people walking", "people standing and talking", "people hugging", "people playing sports", "an empty room", "people shaking hands", "a crowd of people"]
with torch.no_grad():
    tf = cm.encode_text(tok([f"a CCTV photo of {p}" for p in pos + neg]).to(dev)); tf /= tf.norm(dim=-1, keepdim=True)
from PIL import Image
sc = []
for frames, _ in data:
    x = torch.stack([cpre(Image.fromarray(f)) for f in frames[::2]]).to(dev)
    with torch.no_grad():
        f = cm.encode_image(x); f /= f.norm(dim=-1, keepdim=True)
        p = (100 * f @ tf.T).softmax(-1)[:, :len(pos)].sum(-1).mean()
    sc.append(float(p))
results["clip_zeroshot"] = sc
labels = [l for _, l in data]
for k, v in results.items():
    print(f"{k:22s} AUC={auc(v, labels):.3f} best_acc={best_acc(v, labels):.3f} acc@0.5={((np.array(v)>=0.5)==np.array(labels)).mean():.3f}")
np.save("data/testclips/scores.npy", results)
