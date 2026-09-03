import os
import subprocess
import shutil

def setup_test_environment():
    """
    Creates the required directory structure for the blast furnace pipeline
    and populates it with generated dummy video clips for testing.
    """
    base_dir = "Project_Root"
    input_dir = os.path.join(base_dir, "Videolar")
    output_normal = os.path.join(base_dir, "Normal")
    output_abnormal = os.path.join(base_dir, "Tuyer-Anormal")

    anomalies = [
        "Slag_Hanging", "Raceway_Collapse", "Tuyere_Blockage",
        "Coal_Injection_Failure", "Coal_Pipe_Break", "Lance_Misalignment",
        "Large_Coke_Falling", "Flame_Weakening", "Wind_Off", "Burn_through"
    ]

    print("1. Creating directory structure...")
    # Create input folders (Tuyer-1 to Tuyer-14)
    for i in range(1, 15):
        os.makedirs(os.path.join(input_dir, f"Tuyer-{i}"), exist_ok=True)
        
    # Create output folders
    os.makedirs(output_normal, exist_ok=True)
    for anomaly in anomalies:
        os.makedirs(os.path.join(output_abnormal, anomaly), exist_ok=True)

    print("2. Generating a dummy 5-second video via FFmpeg...")
    dummy_video = "dummy_source.mp4"
    # Generates a standard test pattern video with a running timer
    ffmpeg_cmd = [
        "ffmpeg", "-y", "-f", "lavfi", 
        "-i", "testsrc=duration=5:size=640x480:rate=30",
        "-c:v", "libx264", dummy_video
    ]
    subprocess.run(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    print("3. Populating input directories with test clips...")
    # Place 3 dummy clips into each of the 14 Tuyer folders
    for i in range(1, 15):
        tuyer_folder = os.path.join(input_dir, f"Tuyer-{i}")
        for j in range(1, 4):
            dest = os.path.join(tuyer_folder, f"test_clip_tuyer{i}_{j}.mp4")
            shutil.copy(dummy_video, dest)

    # Clean up the initial dummy file
    os.remove(dummy_video)
    print(f"Success! Test environment is fully populated inside '{base_dir}'.")

if __name__ == "__main__":
    setup_test_environment()
