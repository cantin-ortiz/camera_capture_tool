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

def render_chunk(image_folder, chunk_num, start_frame, n_frames, framerate):
    """
    Renders a specific sequence of frames into a temporary MPEG Transport Stream (.ts) file.
    .ts format is ideal for fast concatenation later.
    """
    chunk_file = os.path.join(image_folder, f"chunk_{chunk_num:03d}.ts")
    
    # Input pattern: specifies starting frame and number of digits
    input_pattern = os.path.join(image_folder, "frame_%07d.jpg")
    
    cmd = [
        'ffmpeg',
        '-y', 
        '-framerate', str(framerate),
        # Input parameters to specify the frame range:
        '-start_number', str(start_frame),  # Start index
        '-vframes', str(n_frames),          # Number of frames to process
        '-i', input_pattern,
        
        # Encoding parameters:
        '-c:v', 'libx264',
        '-crf', '23',
        '-pix_fmt', 'yuv420p',
        
        # Output container for fast concatenation: MPEG Transport Stream
        '-f', 'mpegts', 
        chunk_file
    ]
    
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return chunk_file
    except subprocess.CalledProcessError as e:
        print(f"\n[ERROR] FFmpeg failed rendering Chunk {chunk_num}. Exit code {e.returncode}. This chunk will be skipped.")
        return None
    except FileNotFoundError:
        print("[ERROR] FFmpeg command not found. Ensure it is in your PATH.")
        raise
        
def create_video_from_images(image_folder, output_file, framerate, generate_video, chunk_paths):
    """
    Concatenates the pre-rendered video chunks into the final video file.
    This step is fast because it uses stream copying (-c copy).
    """
    if not generate_video:
        print("[INFO] Video generation skipped by --novid argument.")
        return
        
    if not chunk_paths:
        print("[WARNING] No video chunks were successfully rendered. Cannot create final video.")
        return
        
    print(f"\n[INFO] Concatenating {len(chunk_paths)} video chunks into: {output_file}")
    
    # 1. Create a concatenation list file
    list_file_path = os.path.join(image_folder, "concat_list.txt")
    with open(list_file_path, "w") as f:
        for chunk in chunk_paths:
            f.write(f"file '{chunk}'\n")

    # 2. Run FFmpeg to concatenate (fast using -c copy)
    cmd = [
        'ffmpeg',
        '-y',
        '-f', 'concat',
        '-safe', '0', # Allows absolute paths in the list file
        '-i', list_file_path,
        '-c', 'copy', 
        output_file
    ]
    
    try:
        # Note: We still suppress output, but this step is quick
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) 
        print("[INFO] Final video concatenation complete.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Final FFmpeg concatenation failed. Exit code {e.returncode}.")
    except FileNotFoundError:
        print("[ERROR] FFmpeg command not found.")
        
    # 3. Clean up the list file 
    os.remove(list_file_path)

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