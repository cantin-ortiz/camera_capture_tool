# render_worker.py

import multiprocessing
import queue
import time
import os
from processing_utils import render_chunk

def render_worker(image_folder, framerate, render_queue, stop_event, debug_mode=False):
    """
    Worker function (process) that continuously pulls chunk jobs from the queue and renders them.
    This function now uses the logical chunk index for naming and sorts the output paths.
    """
    # List to track successfully rendered chunk file paths along with their index:
    # Format: [(chunk_index, path_to_file), ...]
    chunk_paths_with_index = [] 
    
    # Define the final chunk list file path to be written on exit
    chunk_list_file = os.path.join(image_folder, "final_chunk_paths.txt") 
    
    while not stop_event.is_set():
        try:
            # PULL MODIFIED JOB TUPLE: (chunk_index, start_frame, n_frames)
            chunk_index, start_frame, n_frames = render_queue.get(timeout=1) 
            
            # --- EXECUTE THE RENDER JOB ---
            # Use chunk_index + 1 for display chunk number (starting from 1)
            if debug_mode:
                print(f"\n[WORKER INFO] Rendering Chunk {chunk_index + 1} (Frames {start_frame} to {start_frame + n_frames - 1}) from Process...")
            
            # Execute the heavy FFmpeg job. chunk_index is passed as chunk_num.
            chunk_file = render_chunk(
                image_folder=image_folder, 
                chunk_num=chunk_index, # Logical index (0, 1, 2, ...)
                start_frame=start_frame,
                n_frames=n_frames, 
                framerate=framerate
            )
            
            if chunk_file:
                # Store the index along with the path
                chunk_paths_with_index.append((chunk_index, chunk_file))
            
        except queue.Empty:
            continue
        except Exception as e:
            print(f"[WORKER ERROR] Fatal error during chunk rendering: {e}")
            # Log the error and continue to the next job
    
    # --- PROCESS EXIT & SORTING ---
    if debug_mode:
        print("[WORKER INFO] Render process received stop signal. Preparing final path list...")
    
    # 1. SORT the list by the chunk index (the first element of the tuple)
    chunk_paths_with_index.sort(key=lambda x: x[0])
    
    # 2. Extract only the paths, now in correct order
    sorted_chunk_paths = [path for index, path in chunk_paths_with_index]
    
    # 3. Write the sorted list of successful chunk paths to disk before exiting
    if sorted_chunk_paths:
        try:
            with open(chunk_list_file, "w") as f:
                for path in sorted_chunk_paths:
                    # WRITE IN FFmpeg CONCATENATION LIST FORMAT: file 'path'
                    f.write(f"file '{path}'\n") 
            if debug_mode:
                print(f"[WORKER INFO] Wrote {len(sorted_chunk_paths)} correctly ordered chunk paths to {chunk_list_file}")
        except Exception as e:
            print(f"[WORKER ERROR] Failed to write chunk paths on exit: {e}")

    # Clean up the queue if any jobs were pending after stop signal
    while not render_queue.empty():
        try:
            render_queue.get_nowait()
        except queue.Empty:
            break
            
    if debug_mode:
        print("[WORKER INFO] Rendering process exiting.")
    return