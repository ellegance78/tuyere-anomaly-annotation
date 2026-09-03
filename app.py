"""
Video Annotation Tool - Flask Backend
======================================
Serves video files from Videolar/ and moves them to
Normal/, Anormal/, or Belirsiz/ based on user classification (binary
for now; sub-categorization into Anormal/<subcategory>/ happens in a
later pass). Belirsiz/ holds clips the annotator wasn't sure about,
to be reviewed again later.
"""

import os
import shutil
import mimetypes
from pathlib import Path
from flask import Flask, jsonify, send_file, request, render_template, abort

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent.resolve()

VIDEO_SOURCE_DIR = BASE_DIR / "Videolar"
NORMAL_DIR       = BASE_DIR / "Normal"
ANORMAL_DIR      = BASE_DIR / "Anormal"
SKIPPED_DIR      = BASE_DIR / "Belirsiz"

# Anomaly sub-categorization is not done at labeling time yet — anomalies are
# labeled as a single "anomaly" class and moved straight into ANORMAL_DIR.
# These sub-folders are kept on disk for a later categorization pass.
ANOMALY_CATEGORIES = [
    "Slag_Hanging",
    "Raceway_Collapse",
    "Tuyere_Blockage",
    "Coal_Injection_Failure",
    "Coal_Pipe_Break",
    "Lance_Misalignment",
    "Large_Coke_Falling",
    "Flame_Weakening",
    "Wind_Off",
    "Burn_through",
]

VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v"}

# ---------------------------------------------------------------------------
# Ensure output directories exist
# ---------------------------------------------------------------------------
NORMAL_DIR.mkdir(parents=True, exist_ok=True)
ANORMAL_DIR.mkdir(parents=True, exist_ok=True)
SKIPPED_DIR.mkdir(parents=True, exist_ok=True)
for category in ANOMALY_CATEGORIES:
    (ANORMAL_DIR / category).mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------
app = Flask(__name__, template_folder="templates")


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------
def scan_video_files() -> list[Path]:
    """
    Recursively scan VIDEO_SOURCE_DIR for video files.
    Returns a sorted list of absolute Path objects.
    """
    videos: list[Path] = []
    for root, _dirs, files in os.walk(VIDEO_SOURCE_DIR):
        for filename in sorted(files):
            if Path(filename).suffix.lower() in VIDEO_EXTENSIONS:
                videos.append(Path(root) / filename)
    return sorted(videos)


def path_to_api_id(path: Path) -> str:
    """
    Convert an absolute video path to a URL-safe relative id
    (relative to VIDEO_SOURCE_DIR, with '/' as separator).
    """
    return path.relative_to(VIDEO_SOURCE_DIR).as_posix()


def api_id_to_path(video_id: str) -> Path:
    """
    Resolve a URL-safe video id back to an absolute Path.
    Guards against path traversal attacks.
    """
    resolved = (VIDEO_SOURCE_DIR / video_id).resolve()
    if not str(resolved).startswith(str(VIDEO_SOURCE_DIR.resolve())):
        abort(400, description="Invalid video path.")
    return resolved


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    """Serve the main annotation UI."""
    return render_template("index.html")


@app.route("/api/videos")
def list_videos():
    """
    Return the full list of remaining video IDs and statistics.
    Response JSON:
      {
        "videos": ["Tuyer-1/clip001.mp4", ...],
        "total":  <int>,
        "categories": ["Slag_Hanging", ...]
      }
    """
    videos = scan_video_files()
    return jsonify(
        videos=[path_to_api_id(p) for p in videos],
        total=len(videos),
        categories=ANOMALY_CATEGORIES,
    )


@app.route("/api/video/<path:video_id>")
def serve_video(video_id: str):
    """Stream the requested video file to the browser."""
    video_path = api_id_to_path(video_id)
    if not video_path.is_file():
        abort(404, description="Video file not found.")

    mime, _ = mimetypes.guess_type(str(video_path))
    mime = mime or "video/mp4"
    return send_file(video_path, mimetype=mime, conditional=True)


@app.route("/api/classify", methods=["POST"])
def classify_video():
    """
    Move the current video to the target directory and return the next video.

    Expected JSON body:
      {
        "video_id":   "Tuyer-3/clip042.mp4",
        "label":      "normal" | "anomaly" | "skip"
      }

    Response JSON (success):
      {
        "status":     "ok",
        "moved_to":   "/abs/path/Normal/Tuyer-3/clip042.mp4",
        "next_video": "Tuyer-3/clip043.mp4" | null,
        "remaining":  <int>
      }
    """
    data = request.get_json(force=True, silent=True) or {}

    video_id = data.get("video_id", "").strip()
    label    = data.get("label", "").strip().lower()

    if not video_id:
        return jsonify(error="Missing 'video_id'."), 400
    if label not in ("normal", "anomaly", "skip"):
        return jsonify(error="'label' must be 'normal', 'anomaly', or 'skip'."), 400

    video_path = api_id_to_path(video_id)
    if not video_path.is_file():
        return jsonify(error="Video file not found on disk."), 404

    # Determine destination directory. Each label has its own root, and
    # within it clips are kept in a per-camera subfolder (the video's
    # original Tuyer-X folder) so Normal/Anormal/Belirsiz stay separated
    # by camera. Anomalies are not sub-categorized by anomaly type at
    # labeling time — they land in Anormal/<camera>/ and get categorized
    # into Anormal/<category>/ in a later pass. "skip" is for clips the
    # annotator isn't sure about — parked in Belirsiz/<camera>/ for review.
    label_root = {
        "normal":  NORMAL_DIR,
        "anomaly": ANORMAL_DIR,
        "skip":    SKIPPED_DIR,
    }[label]
    camera_folder = video_id.split("/")[0]
    dest_dir = label_root / camera_folder

    dest_dir.mkdir(parents=True, exist_ok=True)

    # Handle filename collisions by appending a counter
    dest_file = dest_dir / video_path.name
    counter = 1
    while dest_file.exists():
        stem   = video_path.stem
        suffix = video_path.suffix
        dest_file = dest_dir / f"{stem}_{counter}{suffix}"
        counter += 1

    shutil.move(str(video_path), str(dest_file))

    # Find next video after the move
    remaining_videos = scan_video_files()
    next_video_id    = path_to_api_id(remaining_videos[0]) if remaining_videos else None

    return jsonify(
        status="ok",
        moved_to=str(dest_file),
        next_video=next_video_id,
        remaining=len(remaining_videos),
    )


def _count_videos(dir_path: Path) -> int:
    """Recursively count video files under dir_path (e.g. across per-camera subfolders)."""
    if not dir_path.exists():
        return 0
    return sum(
        1 for f in dir_path.rglob("*")
        if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
    )


@app.route("/api/stats")
def stats():
    """
    Return annotation progress statistics.
    Normal/ and Belirsiz/ hold per-camera subfolders (Tuyer-1/, Tuyer-2/, ...).
    Anormal/ holds per-camera subfolders for not-yet-categorized clips, plus
    the ANOMALY_CATEGORIES subfolders for clips already categorized in a
    later pass.
    """
    normal_count  = _count_videos(NORMAL_DIR)
    skipped_count = _count_videos(SKIPPED_DIR)

    anormal_counts: dict[str, int] = {
        cat: _count_videos(ANORMAL_DIR / cat) for cat in ANOMALY_CATEGORIES
    }
    anormal_categorized   = sum(anormal_counts.values())
    anormal_total         = _count_videos(ANORMAL_DIR)
    anormal_uncategorized = anormal_total - anormal_categorized

    remaining = len(scan_video_files())

    return jsonify(
        remaining=remaining,
        normal=normal_count,
        skipped=skipped_count,
        anormal_total=anormal_total,
        anormal_uncategorized=anormal_uncategorized,
        anormal_by_category=anormal_counts,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("  Video Annotation Tool")
    print(f"  Source  : {VIDEO_SOURCE_DIR}")
    print(f"  Normal  : {NORMAL_DIR}")
    print(f"  Anormal : {ANORMAL_DIR}")
    print(f"  Belirsiz: {SKIPPED_DIR}")
    print("  Open    : http://127.0.0.1:5050")
    print("=" * 60)
    # Port 5000 is claimed by macOS's AirPlay Receiver (ControlCenter) as
    # soon as it's free, so this server can silently lose the port every
    # time it restarts. 5050 avoids that recurring conflict.
    app.run(debug=True, host="127.0.0.1", port=5050)
