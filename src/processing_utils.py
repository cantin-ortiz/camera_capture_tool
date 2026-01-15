# processing_utils.py

import os
import subprocess
import shutil
import glob # Required for sequential mode
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
    """
    filename_num = chunk_num + 1 
    chunk_file = os.path.join(image_folder, f"chunk_{filename_num:03d}.ts")
    
    # Input pattern: specifies starting frame and number of digits
    input_pattern = os.path.join(image_folder, "frame_%07d.jpg")
    
    cmd = [
        'ffmpeg',
        '-y', 
        
        # --- INPUT OPTIONS (MUST come before -i) ---\
        '-framerate', str(framerate),
        '-start_number', str(start_frame),  # Start index
        
        # --- INPUT FILE ---\
        '-i', input_pattern,
        
        # --- OUTPUT CONSTRAINTS (MUST come after -i, before encoding options) ---\
        '-vframes', str(n_frames),          # Number of frames to process
        
        # --- OUTPUT ENCODING PARAMETERS ---\
        '-c:v', 'libx264',
        '-preset', 'ultrafast',
        '-tune', 'zerolatency',
        '-crf', '23', # Constant Rate Factor: lower is higher quality/larger file
        '-pix_fmt', 'yuv420p',
        
        # Output container settings for concatenation:\
        '-f', 'mpegts',
        chunk_file
    ]
    
    try:
        # Run FFmpeg. We now capture output for debugging and raise exception on error.
        result = subprocess.run(cmd, check=True, capture_output=True, text=True) 
        return chunk_file
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] FFmpeg chunk rendering failed for chunk {chunk_num}. Exit code {e.returncode}.")
        # --- DEBUG OUTPUT ---\
        print("\n--- FFmpeg Stderr Output START ---")
        print(e.stderr)
        print("--- FFmpeg Stderr Output END ---\n")
        # --------------------\
        return None
    except FileNotFoundError:
        print(f"[ERROR] FFmpeg command not found. Cannot render chunk {chunk_num}.")
        return None

def create_video_from_images(image_folder, output_file, framerate, generate_video, chunk_paths_ff):
    """
    If chunk_paths_ff is provided, concatenates temporary chunk files (concurrent mode).
    If chunk_paths_ff is empty, renders the video sequentially from all frames (sequential mode).
    """
    if not generate_video:
        print("[INFO] Video generation skipped.")
        return False
        
    if not chunk_paths_ff:
        # --- SEQUENTIAL RENDERING MODE ---
        print("[INFO] No chunk paths provided. Rendering video sequentially from all frames...")
        
        # Input pattern: specifies starting frame and number of digits
        input_pattern = os.path.join(image_folder, "frame_%07d.jpg")
        
        cmd = [
            'ffmpeg',
            '-y', 
            '-framerate', str(framerate), # Input framerate
            '-i', input_pattern,          # Input image sequence
            
            # Encoding parameters 
            '-c:v', 'libx264',
            '-preset', 'ultrafast',
            '-crf', '23', 
            '-pix_fmt', 'yuv420p',
            
            output_file
        ]
        
        success = False
        try:
            # Run FFmpeg and capture output for debugging
            result = subprocess.run(cmd, check=True, capture_output=True, text=True) 
            print("[INFO] Sequential video rendering complete.")
            success = True
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Sequential FFmpeg rendering failed. Exit code {e.returncode}.")
            print("\n--- Sequential FFmpeg Stderr Output START ---")
            print(e.stderr)
            print("--- Sequential FFmpeg Stderr Output END ---\n")
        except FileNotFoundError:
            print("[ERROR] FFmpeg command not found.")
        
        return success
        
    # --- CHUNK CONCATENATION MODE ---
    print("[INFO] Concatenating temporary video chunks...")

    # 1. Create a temporary list file for FFmpeg to read
    list_file_path = os.path.join(image_folder, "concat_list.txt")
    
    # Write the sorted chunk paths (which are already in FFmpeg format) to the temporary list file
    # Renamed variable to chunk_paths_ff
    with open(list_file_path, "w") as f:
        # chunk_paths_ff now contains lines like: file 'path/to/chunk_001.ts'
        for line in chunk_paths_ff:
            # Robustly write the line, stripping whitespace and ensuring a single newline
            f.write(line.strip() + "\n") 

    # 2. Concatenate all chunks (Transport Stream format)
    cmd = [
        'ffmpeg',
        '-y', 
        '-f', 'concat', 
        '-safe', '0',   # Allows absolute paths in the list file
        '-i', list_file_path,
        '-c', 'copy',   # Copies the stream without re-encoding (very fast)
        '-map', '0:v:0', # Map only the first video stream (added for robustness)
        output_file
    ]
    
    success = False
    try:
        # We capture output for debugging the final concatenation step.
        result = subprocess.run(cmd, check=True, capture_output=True, text=True) 
        print("[INFO] Final video concatenation complete.")
        success = True
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Final FFmpeg concatenation failed. Exit code {e.returncode}.")
        # --- DEBUG OUTPUT ---
        print("\n--- Final FFmpeg Stderr Output START ---")
        print(e.stderr)
        print("--- Final FFmpeg Stderr Output END ---\n")
        # --------------------
    except FileNotFoundError:
        print("[ERROR] FFmpeg command not found.")
        
    # 3. Clean up the temporary list file 
    if os.path.exists(list_file_path):
        os.remove(list_file_path)
    
    return success

def cleanup_frames(save_path, delete_frames, video_success):
    """
    Delete all image frames and the folder containing them if DELETE_FRAMES is True 
    and the video was successfully generated.
    """

    if delete_frames and video_success:
        if os.path.exists(save_path) and os.path.isdir(save_path):
            try:
                # Use shutil.rmtree for directory deletion
                shutil.rmtree(save_path)
                print(f"[INFO] Deleted frame folder and contents: {save_path}")
            except OSError as e:
                print(f"[WARNING] Error deleting directory {save_path}: {e}")
        else:
            print(f"[WARNING] Frame folder not found for deletion: {save_path}")
    else:
        # Inform the user why frames were kept
        if not delete_frames:
            print("[INFO] Frames were kept because --keep-frames argument was used.")
        elif not video_success:
            print("[INFO] Frames were kept because video generation failed.")