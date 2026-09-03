"""
extract_frames.py — Pull 1 frame/second from each 5s clip in Normal/Tuyer-X/
==============================================================================
For every camera (Tuyer-1..14), reads the classified "Normal" 5-second clips
and extracts one JPEG per second (5 photos per clip) into a destination
folder, mirroring the same per-camera subfolder layout.

Resumable: a clip is skipped if its first output frame already exists, so
an interrupted run can just be re-launched.

USAGE
-----
    python3 extract_frames.py \
        --src  <proje-dizini> \
        --dst  <proje-dizini>
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

CAMERAS = range(1, 15)
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v"}


def extract_clip(video_path: Path, dst_dir: Path) -> int:
    """Extract 1 fps frames from video_path into dst_dir. Returns frame count written."""
    stem = video_path.stem
    out_pattern = dst_dir / f"{stem}_f%d.jpg"
    marker = dst_dir / f"{stem}_f1.jpg"
    if marker.exists():
        return -1  # already done, skipped

    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-vf", "fps=1", "-q:v", "2",
        "-y", "-loglevel", "error",
        str(out_pattern),
    ]
    subprocess.run(cmd, check=True)
    return len(list(dst_dir.glob(f"{stem}_f*.jpg")))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", default="<proje-dizini>")
    parser.add_argument("--dst", default="<proje-dizini>")
    args = parser.parse_args()

    src_root = Path(args.src)
    dst_root = Path(args.dst)

    total_clips = 0
    total_frames = 0
    total_skipped = 0
    t_start = time.time()

    for cam in CAMERAS:
        src_dir = src_root / f"Tuyer-{cam}"
        dst_dir = dst_root / f"Tuyer-{cam}"
        dst_dir.mkdir(parents=True, exist_ok=True)

        if not src_dir.exists():
            print(f"[Tuyer-{cam}] kaynak klasör yok, atlanıyor: {src_dir}")
            continue

        clips = sorted(
            f for f in src_dir.iterdir()
            if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
        )
        print(f"[Tuyer-{cam}] {len(clips)} klip bulundu")

        cam_frames = 0
        cam_skipped = 0
        for i, clip in enumerate(clips, start=1):
            try:
                n = extract_clip(clip, dst_dir)
            except subprocess.CalledProcessError as e:
                print(f"  HATA: {clip.name}: {e}")
                continue
            if n == -1:
                cam_skipped += 1
            else:
                cam_frames += n
            if i % 200 == 0:
                print(f"[Tuyer-{cam}] {i}/{len(clips)} işlendi...")

        total_clips += len(clips)
        total_frames += cam_frames
        total_skipped += cam_skipped
        print(f"[Tuyer-{cam}] tamam — {cam_frames} yeni kare, {cam_skipped} zaten vardı (atlandı)")

    elapsed = time.time() - t_start
    print(f"\n{'='*60}")
    print(f"  Toplam klip     : {total_clips}")
    print(f"  Yeni üretilen kare : {total_frames}")
    print(f"  Atlanan (zaten vardı) : {total_skipped}")
    print(f"  Süre            : {elapsed:.1f}s")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
