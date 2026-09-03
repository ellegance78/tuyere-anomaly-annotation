🇬🇧 **English** · [🇹🇷 Türkçe](README.tr.md)

# Tuyere Anomaly Annotation Toolkit

Tooling that turned **20,169 short clips** of blast furnace tuyeres into a
labelled dataset, ready for anomaly-detection training.

Built during a summer internship in the process automation department of an
integrated iron and steel plant.

> **Note on data.** The furnace footage is confidential and is **not** part of
> this repository. What is published is the tooling.

---

## The problem

A tuyere is the nozzle that injects hot blast and pulverised coal into a blast
furnace. Slag hanging in front of it, a blockage, or an interrupted coal feed
all hit production directly. Every tuyere has a camera — but nobody can watch
fourteen of them continuously.

Training a model to flag abnormal states needs a labelled dataset first, and
the raw material was hours-long continuous recordings.

## Pipeline

![Pipeline](docs/pipeline.png)

### 1 · `split_videos.py` — clip splitting

Splits long recordings into fixed-length clips with FFmpeg.

- extracts the tuyere number from the filename and files clips accordingly
- uses **stream copy** rather than re-encoding, which cut runtime dramatically
- detects a hardware encoder and uses it where re-encoding is unavoidable
- progress bar, estimated clip count, formatted durations

### 2 · `app.py` — web annotation tool

Opening twenty thousand clips by hand in a video player was not realistic, so
the classification step became a small Flask app:

- autoplays the next clip, three buttons beneath: **Normal / Abnormal / Uncertain**
- one click moves the file into the matching folder and loads the next clip
- keyboard shortcuts (← normal, → abnormal, ↓ uncertain) — no mouse needed
- progress bar and running counters

### 3 · `extract_frames.py` — frame extraction

Pulls frames from classified clips at a chosen rate for downstream training.

## Result

![Classification result](docs/classification-result.png)

Two findings worth flagging:

- Abnormal clips are **not evenly spread** across the fourteen tuyeres — they
  concentrate on a few, which is worth cross-checking against maintenance records.
- The set is heavily imbalanced (~2.7% abnormal). Any model trained on it will
  need class weighting, or an anomaly-detection framing rather than plain
  classification.

## Anomaly classes

Defined with the responsible engineer: slag hanging, raceway collapse, tuyere
blockage, coal injection failure, coal pipe break, lance misalignment, large
coke falling, flame weakening, wind-off, burn-through.

## Running it

```bash
python -m venv venv && venv/bin/pip install -r requirements.txt

python split_videos.py --src raw/ --segment 5      # long recordings → clips
python app.py                                       # annotation UI → :5050
python extract_frames.py --src Normal/ --dst frames/
```

Clips are read from `Videolar/` and moved into `Normal/`, `Anormal/` or
`Belirsiz/`. Source comments are in Turkish; documentation is in English.
