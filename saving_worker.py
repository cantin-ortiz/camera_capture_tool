# saving_worker.py

import threading
import time
import os
import cv2
import numpy as np

# Import only what is needed from other modules
from render_worker import render_queue
from buffer_control import CircularBuffer # For type reference, not instance

# Global stop event for the saving worker
stop_saving_worker = threading.Event()

# --- GLOBAL SETTING (Must match camera_control) ---
CHUNK_DURATION_S = 60 
# --- END GLOBAL SETTING ---

def saving_worker(buffer: CircularBuffer, save_path, framerate, render_queue):
    """
    Worker function that continuously pulls raw frames from the CircularBuffer,
    saves them to disk, and posts rendering jobs to the render queue.
    """
    FRAMES_PER_CHUNK = framerate * CHUNK_DURATION_S
    i = 0 # Total frames saved by this worker (used to find the total count and chunk index)

    while not stop_saving_worker.is_set():
        # Get frame from the circular buffer (blocking call), using the passed instance
        frame_index, np_image = buffer.get()
        
        # Check for clean exit
        if frame_index is None:
            # If the acquisition stopped and the buffer is empty, we exit
            if stop_saving_worker.is_set():
                break 
            time.sleep(0.01) # Wait briefly and check again
            continue 
            
        # --- DISK I/O (The Bottleneck is now ISOLATED here) ---
        # Using JPEG as it was the fastest previously
        filename = os.path.join(save_path, f"frame_{frame_index:07d}.jpg")
        cv2.imwrite(filename, np_image) 
        
        # Update total frames saved for chunking calculation
        i = frame_index + 1 
        
        # Log buffer lag to monitor system health
        buffer_lag = buffer.total_frames_written - i
        print(f"[SAVE WORKER] Saved frame {frame_index:07d} (Lag: {buffer_lag} frames).", end='\r')

        # --- CHUNK RENDERING TRIGGER ---
        if (i > 0) and (i % FRAMES_PER_CHUNK == 0):
            start_frame_index = i - FRAMES_PER_CHUNK
            
            # POST THE JOB to the render worker queue
            render_queue.put((start_frame_index, FRAMES_PER_CHUNK))
            print(f"\n[SAVE WORKER] Posted Chunk Job (Frames {start_frame_index} to {i-1}).")
        # -------------------------------

    # --- POST-STOP: Handle the final partial chunk after the buffer is empty ---
    if i > 0:
        remaining_frames = i % FRAMES_PER_CHUNK
        
        if remaining_frames > 0:
            start_frame_index = i - remaining_frames
            
            print(f"\n[SAVE WORKER] Posting final partial chunk job ({remaining_frames} frames)...")
            render_queue.put((start_frame_index, remaining_frames))
        
    print("[SAVE WORKER] Saving worker exiting.")
    return