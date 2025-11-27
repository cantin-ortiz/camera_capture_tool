# render_worker.py

import threading
import queue
import time
import os
# Import the actual rendering function
from processing_utils import render_chunk

# Global stop event for the worker
stop_worker = threading.Event()
# Global Queue to hold rendering instructions (jobs)
render_queue = queue.Queue()

def render_worker(image_folder, framerate):
    """
    Worker function that continuously pulls chunk jobs from the queue and renders them.
    """
    chunk_num = 1
    # List to track successfully rendered chunk file paths
    chunk_paths = [] 

    while not stop_worker.is_set():
        try:
            # Wait for a job tuple (start_frame, n_frames) with a 1-second timeout
            start_frame, n_frames = render_queue.get(timeout=1) 
            
            # --- EXECUTE THE RENDER JOB ---
            print(f"\n[WORKER INFO] Rendering Chunk {chunk_num} ({n_frames} frames) from thread...")
            
            # Execute the heavy FFmpeg job in this separate thread
            chunk_file = render_chunk(
                image_folder=image_folder, 
                chunk_num=chunk_num, 
                start_frame=start_frame,
                n_frames=n_frames, 
                framerate=framerate
            )
            
            if chunk_file:
                chunk_paths.append(chunk_file)
            
            render_queue.task_done()
            chunk_num += 1

        except queue.Empty:
            # If queue is empty, loop and check stop signal
            continue
        except Exception as e:
            print(f"[WORKER ERROR] Fatal error during chunk rendering: {e}")
            render_queue.task_done()
            # Log the error and continue

    # --- CLEANUP: Save final chunk list for main thread retrieval ---
    # This happens only after stop_worker.set() is called and the worker exits the loop
    chunk_list_file = os.path.join(image_folder, "final_chunk_paths.txt")
    try:
        with open(chunk_list_file, 'w') as f:
            for path in chunk_paths:
                f.write(path + '\n')
    except Exception as e:
        print(f"[WORKER WARNING] Could not save final chunk list file: {e}")
        
    print("[WORKER INFO] Render worker exiting.")
    return chunk_paths