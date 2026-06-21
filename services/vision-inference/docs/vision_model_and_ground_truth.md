# Vision model, dataset & ground truth (presentation Q&A)

What to say when asked *"what is your vision model, what data, and what's your ground truth?"*

> Placeholders marked `‹FILL›` are the only numbers to complete before presenting — do **not**
> quote a metric we haven't measured. Everything else is the defensible methodology.

## The model
- **YOLO26 segmentation** (Ultralytics YOLO, segmentation head), **fine-tuned by us** for the
  single class **`pothole`**. Output = instance **masks + boxes + confidence** per frame.
- Runs on **every frame** in the cascade (ms/frame), locally on our private GPU server (Triton
  in the real-time path; Ultralytics directly in the offline `pipeline/`).
- On disk the weights file is `models/pablo_v1/pablo_v1.pt` (legacy internal name) — it **is**
  the YOLO26-seg model.
- A public **RDD2022 YOLOv12** model is kept only as an **external baseline** for comparison;
  it is not our model and not in the production cascade.

## Training data — **manually captured + manually annotated**
- **Images we collected ourselves**: street-level photos/frames of real roads (our own
  capture, not scraped), covering varied conditions (lighting, wet/dry, asphalt/concrete).
- **Manual annotation**: each pothole hand-labeled as a **polygon segmentation mask** (and
  therefore a box), by us. This human labeling **is the training ground truth**.
- Split into **train / val** (and a separate held-out **test** set below).
- `‹FILL›`: # images, # pothole instances, train/val sizes, annotation tool (e.g. Roboflow /
  CVAT / Label Studio), # annotators.

## Test data — separate manually captured set
- A **held-out set of images we captured manually**, kept apart from training (ideally
  **different streets / sessions** to avoid leakage), with the **same manual mask annotation**.
- Used only to measure the model — never seen during training.
- `‹FILL›`: # test images, # instances, where/when captured.

## So, what is our ground truth?
**Human-annotated pothole segmentation masks on our own manually-captured images.** Concretely:

| Question | Our ground truth |
|---|---|
| Detector (per image) | the **hand-drawn polygon masks/boxes** we labeled — train/val/test |
| Is the model good? | masks/boxes vs ground-truth masks on the **held-out test set**, scored by **mask mAP@50 / mAP@50-95, IoU, precision & recall** at a fixed confidence `‹FILL›` |
| System (cascade) end-to-end | detector proposes → **VLM (Qwen2.5-VL) validates** each candidate (2nd opinion); a confirmed event = detector mask **and** VLM agreement on the best frame |
| Georeference | each confirmed pothole tied to the capture **GPS** (interpolated per frame) → GeoJSON with timestamps; ground truth for location = the capture device's GPS track |

### One-paragraph answer (say this)
> "Our model is a **YOLO26 segmentation** network we **fine-tuned on images we captured and
> annotated by hand** — the **ground truth is our own polygon mask labels** of potholes. We
> evaluate on a **separate, manually-captured held-out set** with the same hand annotations,
> reporting **mask mAP / IoU / precision-recall**. We deliberately run it **alongside the VLM
> for redundancy**: in the live system the YOLO detection is **cross-validated by the VLM**, so a
> reported pothole has agreement from **two independent models** — our fine-tuned detector and
> the language-vision model — and is georeferenced from the capture GPS."

## Honest caveats (good to volunteer)
- Hand-labeled set is **small** (hackathon scale) → we mitigate over-fit with the floor gate
  (Segformer drops off-road false positives) and the **VLM cross-check** rather than relying on
  the detector alone.
- The **VLM is zero-shot** (not trained on our labels); it is a validator/describer, so it does
  **not** define the detector's ground truth — only the human masks do.
- Public RDD2022 is a **baseline**, not ground truth; metrics on it aren't directly comparable
  (different label definitions / dataset).
