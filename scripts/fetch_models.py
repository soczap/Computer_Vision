"""Download the model weights VIGIL needs into models/ (not kept in git).

Face models are NOT downloaded: VIGIL reads the FRS backend's own ONNX files (SCRFD det_10g,
AdaFace IR101) read-only; point VIGIL_FACE_DET_MODEL / VIGIL_FACE_REC_MODEL at them.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "models"
ROOT.mkdir(exist_ok=True)

from huggingface_hub import snapshot_download  # noqa: E402
from ultralytics import YOLO  # noqa: E402
import os  # noqa: E402

os.chdir(ROOT)
for w in ("yolo11s-pose.pt", "yolo11s.pt"):
    YOLO(w)  # ultralytics downloads into the current directory
# VideoMAE fine-tuned on RWF-2000 (CCTV fights). Legacy q_bias/v_bias layout: remapped at load time.
snapshot_download("lmazzon70/videomae-base-finetuned-kinetics-finetuned-rwf2000mp4-epochs8-batch8-kb",
                  local_dir=str(ROOT / "violence" / "videomae_rwf2000"),
                  allow_patterns=["*.json", "pytorch_model.bin"])
import open_clip  # noqa: E402
open_clip.create_model_and_transforms("ViT-B-32", pretrained="laion2b_s34b_b79k")  # cached by open_clip
print("models ready in", ROOT)
