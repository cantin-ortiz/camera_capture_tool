# processing_utils.py

import os
import subprocess
import shutil
from datetime import datetime

def get_save_path(base_dir):
    """
    Generate a timestamped folder path for saving video frames.
    """   
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    folder_name = f"VIDEO_{timestamp}"
    full_path = os.path.join(base_dir, folder_name)
    return full_path

def create_video_from_images(image_folder, output_file, framerate, generate_video):
    """
    Convert a sequence of JPEG images into a video using FFmpeg.
    """
    if generate_video:
        print(f"[INFO] Creating video: {output_file}")
        cmd = [
            'ffmpeg',
            '-y', # Overwrite output files without asking
            '-framerate', str(framerate),
            '-i', os.path.join(image_folder, "frame_%07d.jpg"),
            '-c:v', 'libx264',
            '-pix_fmt', 'yuv420p',
            '-crf', '23', # Constant Rate Factor for good quality/size balance
            output_file
        ]
        try:
            # Subprocess.run with check=True raises CalledProcessError on non-zero exit code
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("[INFO] FFmpeg rendering complete.")
        except FileNotFoundError:
            print("[ERROR] FFmpeg command not found. Ensure FFmpeg is installed and in your system PATH.")
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] FFmpeg execution failed. Exit code {e.returncode}.")
    else:
        print("[INFO] Video generation skipped by --novid argument.")

def cleanup_frames(save_path, generate_video, delete_frames):
    """
    Delete all image frames and the folder containing them if DELETE_FRAMES is True.
    """

    if delete_frames and generate_video:
        if os.path.exists(save_path) and os.path.isdir(save_path):
            try:
                shutil.rmtree(save_path)
                print(f"[INFO] Deleted frame folder and contents: {save_path}")
            except OSError as e:
                print(f"[WARNING] Error deleting directory {save_path}: {e}")
        else:
            print(f"[WARNING] Frame folder not found for deletion: {save_path}")
    else:
        # Note: Added reason for skipping deletion
        reason = "DELETE_FRAMES=False" if not delete_frames else "GENERATE_VIDEO=False"
        print(f"[INFO] Frame deletion skipped ({reason}).")