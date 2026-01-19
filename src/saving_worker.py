# saving_worker.py

import threading
import time
import os
import sys
import cv2
import numpy as np

# Add parent directory to path to import config
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from config import CHUNK_DURATION_S, JPEG_QUALITY

# Global stop event for the saving worker
stop_saving_worker = threading.Event()

# >>> MODIFIED FUNCTION SIGNATURE <<<
def saving_worker(buffer, save_path, framerate, render_queue, concurrent_render, generate_video, debug_mode=False):
    """
    Worker function that continuously pulls raw frames from the CircularBuffer,
    saves them to disk, and conditionally posts rendering jobs based on the flag.
    """
    FRAMES_PER_CHUNK = framerate * CHUNK_DURATION_S
    
    # State variable to track the last chunk whose job was posted. 
    last_chunk_posted_index = -1 
    
    # ADAPTIVE FLOW CONTROL SETTING:
    MAX_ACCEPTABLE_LAG_FRAMES = 50 

    i = 0 # Total frames saved by this worker
    start_time = time.time()  # Track when recording started
    
    while not stop_saving_worker.is_set():
        # Get frame from the circular buffer (blocking call)
        frame_index, np_image = buffer.get()
        
        # Check for clean exit - if None received and stop is set, exit loop
        if frame_index is None:
            if stop_saving_worker.is_set():
                break
            time.sleep(0.01)
            continue 
            
        # --- DISK I/O: SAVE FRAME ---
        filename = os.path.join(save_path, f"frame_{frame_index:07d}.jpg")
        cv2.imwrite(filename, np_image, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        
        # Update total frames saved for chunking calculation
        i = frame_index + 1 
        
        # Calculate lag: Total frames acquired minus total frames saved
        buffer_lag = buffer.total_frames_written - i
        buffer_capacity = buffer.size
        elapsed_time = time.time() - start_time
        
        if debug_mode:
            print(f"[SAVE WORKER] Saved frame {frame_index:07d} (Lag: {buffer_lag} frames, Time: {elapsed_time:.1f}s).", end='\r')
        else:
            print(f"Lag: {buffer_lag}/{buffer_capacity} frames | Time: {elapsed_time:.1f}s", end='\r')

        # --- CHUNK RENDERING TRIGGER (ADAPTIVE FLOW CONTROL) ---
        
        # >>> CONDITIONAL EXECUTION: Only if video generation is enabled <<<
        if generate_video and concurrent_render: 
            # 1. Check if a chunk is fully written to disk and needs posting
            if (i > 0) and (i % FRAMES_PER_CHUNK == 0):
                
                # The chunk index we would post is the one that just finished saving (0, 1, 2, ...)
                chunk_to_post_index = (i // FRAMES_PER_CHUNK) - 1 
                
                if chunk_to_post_index > last_chunk_posted_index:
                    
                    # 2. Check the adaptive flow control condition: Is the Saving Worker caught up?
                    if buffer_lag < MAX_ACCEPTABLE_LAG_FRAMES:
                        # Lag is low, meaning the disk is relatively idle. POST THE JOB.
                        start_frame_index = chunk_to_post_index * FRAMES_PER_CHUNK
                        
                        # POSTING TUPLE: (LOGICAL_INDEX, start_frame, n_frames)
                        render_queue.put((chunk_to_post_index, start_frame_index, FRAMES_PER_CHUNK))
                        if debug_mode:
                            print(f"\n[SAVE WORKER] Posted Flow-Controlled Chunk Job (Frames {start_frame_index} to {start_frame_index + FRAMES_PER_CHUNK - 1}).")
                        
                        last_chunk_posted_index = chunk_to_post_index
                    else:
                        # Lag is high. Prioritize disk saving. DEFER POSTING.
                        if debug_mode:
                            print(f"\n[SAVE WORKER] Deferring Chunk Job {chunk_to_post_index+1}. Lag too high ({buffer_lag} frames).")
    
    print(f"\n[SAVE WORKER] Exited main loop. Total frames saved: {i}")
    
    # --- POST-STOP: Handle all remaining chunks ---
    # >>> CONDITIONAL EXECUTION: Only if video generation is enabled <<<
    if generate_video and concurrent_render:
        # This ensures all deferred chunks are posted immediately upon acquisition stop.
        total_chunks_written = i // FRAMES_PER_CHUNK
        
        # Post all full chunks that were deferred by the flow control logic
        for chunk_index in range(last_chunk_posted_index + 1, total_chunks_written):
            start_frame_index = chunk_index * FRAMES_PER_CHUNK
            if debug_mode:
                print(f"\n[SAVE WORKER] Posting Deferred Full Chunk Job {chunk_index+1} ({FRAMES_PER_CHUNK} frames)...")
            # POSTING TUPLE: (LOGICAL_INDEX, start_frame, n_frames)
            render_queue.put((chunk_index, start_frame_index, FRAMES_PER_CHUNK))

        # Handle the very last partial chunk (the remainder)
        remaining_frames = i % FRAMES_PER_CHUNK
        
        print(f"[SAVE WORKER] Full chunks: {total_chunks_written}, Remaining frames: {remaining_frames}")
        
        if remaining_frames > 0:
            chunk_index = total_chunks_written # Use the next logical index
            start_frame_index = i - remaining_frames
            
            print(f"[SAVE WORKER] Posting final partial chunk {chunk_index+1}: frames {start_frame_index} to {i-1} ({remaining_frames} frames)")
            # POSTING TUPLE: (LOGICAL_INDEX, start_frame, n_frames)
            render_queue.put((chunk_index, start_frame_index, remaining_frames))
        else:
            print(f"[SAVE WORKER] No remaining frames to post.")
        
    print("[SAVE WORKER] Saving worker function returning.")
    return