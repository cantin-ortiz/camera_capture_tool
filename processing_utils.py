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
        
        # --- INPUT OPTIONS (BEFORE -i) ---
        '-err_detect', 'aggressive',
        '-probesize', '32M', 
        
        # Framerate and demuxer are crucial input options
        '-framerate', str(framerate),
        '-f', 'image2',
        
        # Input parameters to specify the frame range:
        '-start_number', str(start_frame),  # Start index
        
        '-i', input_pattern,                # Input File
        
        # --- OUTPUT OPTIONS (AFTER -i) ---
        # FIX: -vframes must be here when using image sequence input
        '-vframes', str(n_frames),          # Limit output/encoded frames
        
        # Encoding parameters:
        '-c:v', 'libx264',
        '-crf', '23',
        '-pix_fmt', 'yuv420p',
        
        # Output container for fast concatenation: MPEG Transport Stream
        '-f', 'mpegts', 
        chunk_file
    ]
    
    try:
        # Capture output for debugging on failure
        result = subprocess.run(
            cmd, 
            check=True, 
            capture_output=True, 
            text=True
        )
        # If successful, return chunk file
        return chunk_file
    
    except subprocess.CalledProcessError as e:
        # FFmpeg failed: return None so the chunk is not added to the final list
        print(f"\n[ERROR] FFmpeg failed rendering Chunk {chunk_num}. Exit code {e.returncode}.")
        
        # Print the detailed error message captured from FFmpeg
        print("--- FFmpeg ERROR OUTPUT START ---")
        print(e.stderr)
        print("--- FFmpeg ERROR OUTPUT END ---")
        
        return None
        
    except FileNotFoundError:
        print("[ERROR] FFmpeg command not found. Ensure it is in your system PATH.")
        raise
        
def create_video_from_images(image_folder, output_file, framerate, generate_video, chunk_paths):
    """
    Concatenates the pre-rendered video chunks into the final video file using stream copy.
    Returns True if video was successfully created or skipped, False otherwise.
    """
    if not generate_video:
        print("[INFO] Video generation skipped by --novid argument.")
        return True
        
    if not chunk_paths:
        print("[WARNING] No video chunks were successfully rendered. Cannot create final video.")
        return False
        
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
        '-safe', '0', 
        '-i', list_file_path,
        '-c', 'copy', 
        output_file
    ]
    
    success = False
    try:
        # This call should still suppress output as it's not the source of the crash
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) 
        print("[INFO] Final video concatenation complete.")
        success = True
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Final FFmpeg concatenation failed. Exit code {e.returncode}.")
    except FileNotFoundError:
        print("[ERROR] FFmpeg command not found.")
        
    # 3. Clean up the list file 
    os.remove(list_file_path)
    
    return success

def cleanup_frames(save_path, delete_frames, video_generation_success):
    """
    Delete all image frames and the folder containing them only if 
    DELETE_FRAMES is True AND the video generation was successful.
    """

    if delete_frames and video_generation_success:
        if os.path.exists(save_path) and os.path.isdir(save_path):
            try:
                shutil.rmtree(save_path) 
                print(f"[INFO] Deleted frame folder and contents: {save_path}")
            except OSError as e:
                print(f"[WARNING] Error deleting directory {save_path}: {e}")
        else:
            print(f"[WARNING] Frame folder not found for deletion: {save_path}")
    else:
        reason = ""
        if not delete_frames:
            reason = "DELETE_FRAMES=False"
        elif not video_generation_success:
            reason = "Video generation failed (frames kept)." 
        print(f"[INFO] Frame and chunk deletion skipped ({reason}).")