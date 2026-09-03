"""
split_videos.py  —  Tuyere 24h Recording Splitter
===================================================
Splits long recordings (e.g. 24-hour .mp4 files) into 5-second clips
and saves each tuyere's clips into the corresponding Videolar/Tuyer-X/ folder.

USAGE
-----
1. Drop your raw recordings into the  raw/  folder.
2. Name each file so the tuyere number is identifiable, e.g.:
       Tuyer-1.mp4  |  tuyer_1.mp4  |  camera1.mp4  |  1.mp4
3. Run:
       python3 split_videos.py

   Optional flags:
       --raw-dir   <path>    Source folder  (default: ./raw)
       --out-dir   <path>    Videolar root  (default: ./Videolar)
       --segment   <secs>    Clip length    (default: 5)
       --prefix    <str>     Output filename prefix  (default: clip)
       --dry-run             Preview only, do not run FFmpeg

SUPPORTED FILENAME PATTERNS  (case-insensitive, number 1-14)
-------------------------------------------------------------
    Tuyer-3.mp4  |  tuyer_3.mp4  |  tuyer3.mp4
    camera_3.mp4 |  cam3.mp4     |  3.mp4
    tuyere-03.mp4  (leading zero OK)
"""

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

# ── Constants ──────────────────────────────────────────────────────────────
SEGMENT_SECONDS  = 5
RAW_DIR_DEFAULT  = "raw"
OUT_DIR_DEFAULT  = "Videolar"
CLIP_PREFIX      = "clip"
VIDEO_BITRATE    = "1500k"  # target bitrate for re-encoded output (browser-playable H.264)
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v", ".ts", ".mts"}

# Regex: captures the first 1-2 digit number found in the filename stem
_NUM_RE = re.compile(r"(?<![0-9])(\d{1,2})(?![0-9])")

_hw_encoder_cache: Optional[bool] = None


def has_videotoolbox_encoder() -> bool:
    """Check once whether ffmpeg supports macOS hardware H.264 encoding."""
    global _hw_encoder_cache
    if _hw_encoder_cache is None:
        try:
            result = subprocess.run(
                ["ffmpeg", "-hide_banner", "-encoders"],
                capture_output=True, text=True, timeout=10,
            )
            _hw_encoder_cache = "h264_videotoolbox" in result.stdout
        except Exception:
            _hw_encoder_cache = False
    return _hw_encoder_cache


# ── Helpers ────────────────────────────────────────────────────────────────

def extract_tuyere_number(path: Path) -> Optional[int]:
    """
    Try to extract a tuyere number (1-14) from a filename stem.
    Returns None if nothing found or number is out of range.
    """
    stem = path.stem.lower()

    # Prefer explicit keyword match first: tuyer-3, tuyer_3, tuyer3, tuyere-3,
    # "tuyer 03" (space-separated, e.g. NVR exports like
    # "YF4 TUYER_TUYER 01_20260728...mp4"). Take the LAST match so a prefix
    # like "YF4" (unrelated digit) or a repeated "TUYER_TUYER" label doesn't
    # get picked up instead of the real channel number.
    keyword_matches = list(re.finditer(r"tuyer[e]?[\s_-]*(\d{1,2})", stem))
    if keyword_matches:
        n = int(keyword_matches[-1].group(1))
        return n if 1 <= n <= 14 else None

    # Fallback: first standalone number in stem
    nums = _NUM_RE.findall(stem)
    if nums:
        n = int(nums[0])
        return n if 1 <= n <= 14 else None

    return None


def get_video_duration(video_path: Path) -> float:
    """
    Use ffprobe to get the duration of the video in seconds.
    Returns -1.0 if the duration cannot be determined.
    """
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return float(result.stdout.strip())
    except Exception:
        return -1.0


def format_duration(seconds: float) -> str:
    """Return a human-readable duration string."""
    if seconds < 0:
        return "unknown"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}h {m:02d}m {s:02d}s"


def estimate_clip_count(duration: float, segment: int) -> int:
    import math
    return math.ceil(duration / segment) if duration > 0 else -1


def bar(pct: float, width: int = 30) -> str:
    filled = int(width * pct)
    return "█" * filled + "░" * (width - filled)


# ── Core splitting logic ───────────────────────────────────────────────────

def split_video(
    input_path:   Path,
    output_dir:   Path,
    tuyere_num:   int,
    segment_secs: int,
    prefix:       str,
    dry_run:      bool,
    fast_copy:    bool = False,
) -> dict:
    """
    Split a single video into segment_secs-length clips using FFmpeg.
    Returns a result dict with keys: clips_written, duration, skipped, error.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Output pattern: clip_T03_0001.mp4
    out_pattern = output_dir / f"{prefix}_T{tuyere_num:02d}_%04d.mp4"

    duration = get_video_duration(input_path)
    expected = estimate_clip_count(duration, segment_secs)

    print(f"\n{'─'*60}")
    print(f"  📹  Input  : {input_path.name}")
    print(f"  📂  Output : {output_dir}")
    print(f"  ⏱️   Duration: {format_duration(duration)}")
    print(f"  🔢  Est. clips: {expected if expected > 0 else '?'}")
    print(f"{'─'*60}")

    if dry_run:
        print("  [DRY-RUN] Would run FFmpeg — skipping.")
        return {"clips_written": 0, "duration": duration, "skipped": True, "error": None}

    # ----- FFmpeg command -----
    # Audio is dropped (-an): the annotation UI plays clips muted, and
    # source audio codecs (e.g. pcm_mulaw from NVR exports) are often not
    # supported inside an .mp4 container anyway.
    if fast_copy:
        # Stream copy — no re-encoding, very fast, but (a) segment cuts can
        # only happen on the source's existing keyframes, so clips won't be
        # exactly segment_secs long unless the source has a frequent GOP,
        # and (b) the source codec is preserved as-is — only use this if
        # the source is already browser-playable H.264. Sources encoded as
        # HEVC/H.265 (common for NVR exports) will NOT play in the
        # annotation UI's <video> element in most browsers if copied as-is.
        cmd = [
            "ffmpeg",
            "-i", str(input_path),
            "-c:v", "copy", "-an",
            "-f", "segment",
            "-segment_time", str(segment_secs),
            "-reset_timestamps", "1",
            "-avoid_negative_ts", "make_zero",
            "-y",
            str(out_pattern),
        ]
    else:
        # Re-encode to H.264 (universally browser-playable) with a forced
        # keyframe at every segment boundary so cuts land exactly on
        # segment_secs regardless of the source's GOP structure or codec
        # (e.g. HEVC NVR exports). Uses macOS hardware encoding when
        # available (much faster); falls back to software libx264.
        if has_videotoolbox_encoder():
            video_codec_args = ["-c:v", "h264_videotoolbox", "-b:v", VIDEO_BITRATE]
        else:
            video_codec_args = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]

        cmd = [
            "ffmpeg",
            "-i", str(input_path),
            *video_codec_args,
            "-force_key_frames", f"expr:gte(t,n_forced*{segment_secs})",
            "-an",
            "-f", "segment",
            "-segment_time", str(segment_secs),
            "-reset_timestamps", "1",
            "-avoid_negative_ts", "make_zero",
            "-y",
            str(out_pattern),
        ]

    print(f"  Running: {' '.join(cmd[:6])} ... {out_pattern.name}")
    t_start = time.time()

    try:
        proc = subprocess.run(
            cmd,
            stderr=subprocess.PIPE,
            text=True,
            timeout=3 * 3600,   # 3-hour hard timeout per file
        )
    except subprocess.TimeoutExpired:
        return {"clips_written": 0, "duration": duration, "skipped": False,
                "error": "FFmpeg timed out after 3 hours"}
    except FileNotFoundError:
        return {"clips_written": 0, "duration": duration, "skipped": False,
                "error": "ffmpeg not found — is it installed?"}

    elapsed = time.time() - t_start

    if proc.returncode != 0:
        # Print last 10 lines of stderr for diagnosis
        stderr_tail = "\n".join(proc.stderr.strip().splitlines()[-10:])
        return {"clips_written": 0, "duration": duration, "skipped": False,
                "error": f"FFmpeg exit {proc.returncode}:\n{stderr_tail}"}

    # Count actually written files
    prefix_glob = f"{prefix}_T{tuyere_num:02d}_*.mp4"
    clips_written = len(list(output_dir.glob(prefix_glob)))

    print(f"  ✅  Done in {elapsed:.1f}s  →  {clips_written} clips written")
    return {"clips_written": clips_written, "duration": duration,
            "skipped": False, "error": None}


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Split tuyere recordings into 5-second clips.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--raw-dir",  default=RAW_DIR_DEFAULT,
                        help=f"Folder containing raw recordings (default: {RAW_DIR_DEFAULT})")
    parser.add_argument("--out-dir",  default=OUT_DIR_DEFAULT,
                        help=f"Videolar root folder (default: {OUT_DIR_DEFAULT})")
    parser.add_argument("--segment",  type=int, default=SEGMENT_SECONDS,
                        help=f"Clip length in seconds (default: {SEGMENT_SECONDS})")
    parser.add_argument("--prefix",   default=CLIP_PREFIX,
                        help=f"Output filename prefix (default: {CLIP_PREFIX})")
    parser.add_argument("--dry-run",  action="store_true",
                        help="Preview what would happen without running FFmpeg")
    parser.add_argument("--fast-copy", action="store_true",
                        help="Use stream-copy (no re-encoding, much faster) instead of "
                             "the default forced-keyframe re-encode to H.264. Only use "
                             "this if your source is already browser-playable H.264 AND "
                             "has a short keyframe interval (~1s) — otherwise clips will "
                             "not be exactly --segment seconds long, and non-H.264 "
                             "sources (e.g. HEVC NVR exports) won't play in the "
                             "annotation UI's browser video player.")
    args = parser.parse_args()

    raw_dir = Path(args.raw_dir)
    out_dir = Path(args.out_dir)

    # ── Validate raw dir
    if not raw_dir.exists():
        print(f"❌  Raw directory not found: {raw_dir.resolve()}")
        print(f"   Create it and drop your recordings inside:")
        print(f"   mkdir -p {raw_dir}")
        sys.exit(1)

    # ── Discover video files
    found_files = sorted(
        f for f in raw_dir.iterdir()
        if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
    )

    if not found_files:
        print(f"❌  No video files found in: {raw_dir.resolve()}")
        print(f"   Supported extensions: {', '.join(sorted(VIDEO_EXTENSIONS))}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  Tuyere 24h Recording Splitter")
    print(f"  Raw dir  : {raw_dir.resolve()}")
    print(f"  Out dir  : {out_dir.resolve()}")
    print(f"  Segment  : {args.segment}s per clip")
    print(f"  Dry run  : {'YES — no files will be written' if args.dry_run else 'No'}")
    print(f"{'='*60}")

    # ── Map each file to a tuyere number
    mapping: list[tuple[Path, int]] = []
    unmatched: list[Path] = []

    for f in found_files:
        n = extract_tuyere_number(f)
        if n is not None:
            mapping.append((f, n))
        else:
            unmatched.append(f)

    print(f"\n📋  Found {len(found_files)} video(s):")
    for f, n in mapping:
        print(f"     {f.name:40s}  →  Tuyer-{n}")
    if unmatched:
        print(f"\n⚠️   Could NOT determine tuyere number for:")
        for f in unmatched:
            print(f"     {f.name}")
        print("   Rename them (e.g. Tuyer-5.mp4) or they will be skipped.")

    if not mapping:
        print("\n❌  Nothing to process. Exiting.")
        sys.exit(1)

    # ── Check for duplicates (two files map to same tuyere)
    seen: dict[int, Path] = {}
    for f, n in mapping:
        if n in seen:
            print(f"\n⚠️   Tuyere {n} has multiple files:")
            print(f"     {seen[n].name}")
            print(f"     {f.name}")
            print("   Only the first one will be processed.")
        else:
            seen[n] = f

    mapping = [(seen[n], n) for n in sorted(seen)]

    # ── Confirm before starting
    if not args.dry_run:
        total_dur = sum(get_video_duration(f) for f, _ in mapping)
        print(f"\n⏱️   Total source duration: {format_duration(total_dur)}")
        try:
            ans = input("\n▶  Start splitting? [Y/n]: ").strip().lower()
            if ans not in ("", "y", "yes"):
                print("Aborted.")
                sys.exit(0)
        except KeyboardInterrupt:
            print("\nAborted.")
            sys.exit(0)

    # ── Process each file
    results: list[dict] = []
    total_clips = 0

    for idx, (video_path, tuyere_num) in enumerate(mapping, start=1):
        print(f"\n[{idx}/{len(mapping)}]  Processing Tuyer-{tuyere_num}…")
        target_dir = out_dir / f"Tuyer-{tuyere_num}"

        result = split_video(
            input_path   = video_path,
            output_dir   = target_dir,
            tuyere_num   = tuyere_num,
            segment_secs = args.segment,
            prefix       = args.prefix,
            dry_run      = args.dry_run,
            fast_copy    = args.fast_copy,
        )
        result["tuyere"] = tuyere_num
        result["file"]   = video_path.name
        results.append(result)

        if not result["error"] and not result["skipped"]:
            total_clips += result["clips_written"]

    # ── Summary report
    print(f"\n{'='*60}")
    print(f"  SUMMARY")
    print(f"{'='*60}")
    errors = 0
    for r in results:
        status = "⏭  skipped" if r["skipped"] else ("❌  ERROR" if r["error"] else "✅  ok")
        clips  = r["clips_written"] if not r["skipped"] else "—"
        print(f"  Tuyer-{r['tuyere']:2d}  {r['file']:35s}  {str(clips):>6} clips   {status}")
        if r["error"]:
            print(f"           └─ {r['error']}")
            errors += 1

    print(f"{'─'*60}")
    print(f"  Total clips written : {total_clips}")
    print(f"  Errors              : {errors}")
    print(f"{'='*60}\n")

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
