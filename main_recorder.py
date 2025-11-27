# main_recorder.py

import argparse
import sys
import threading
import time
import os
import PySpin
import cv2  # Needed here for the final cv2.destroyAllWindows() cleanup
import numpy as np # Needed for array manipulation

# Import all camera/acquisition functions from the camera module
from camera_control import set_line_source, acquire_images, stop_recording, fs_error_detected
# Import all file/processing utilities from the processing module
from processing_utils import get_save_path, create_video_from_images, cleanup_frames
# Import worker components for concurrent rendering
from render_worker import render_worker, stop_worker, render_queue
# Import the new buffer class (not instance)
from buffer_control import CircularBuffer 
# Import the new saving worker, and its stop event
from saving_worker import saving_worker, stop_saving_worker


# Define the dynamic default path: ~/Documents/flea3_recordings
DEFAULT_SAVE_PATH = os.path.join(os.path.expanduser('~'), "Documents", "flea3_recordings")
# --- NEW BUFFER SETTING ---
BUFFER_DURATION_S = 10 # 10 seconds of frames in RAM buffer
# --- END NEW BUFFER SETTING ---

# ____________________________________________________________________________
#
# ARGUMENT PARSING
# ____________________________________________________________________________

parser = argparse.ArgumentParser(description="Record from FLIR camera.")
parser.add_argument('--duration', type=float, default=None, help='Recording duration in seconds (default: None, infinite)')
parser.add_argument(
    '--save_path', 
    type=str, 
    default=DEFAULT_SAVE_PATH, 
    help='Folder to save videos and frames (default: ~/Documents/flea3_recordings)'
)
parser.add_argument('--framerate', type=int, default=50, help='Recording framerate in Hz (should match SpinView)')
parser.add_argument('--line', type=int, default=1, help='Which line should send the synchronization signal.')
parser.add_argument('--novid', dest='rendervid', action='store_false', help='Skip video conversion')
parser.set_defaults(rendervid=True)
parser.add_argument('--keep-frames', dest='clear', action='store_false', help='Keep frames after video conversion')
parser.set_defaults(clear=True)
parser.add_argument('--nolive', dest='livevideo', action='store_false', help='Do not display live video')
parser.set_defaults(livevideo=True)
args = parser.parse_args()

# Set variables
DURATION = args.duration
SAVE_PATH = args.save_path
FRAMERATE = args.framerate
GENERATE_VIDEO = args.rendervid
DELETE_FRAMES = args.clear
LIVE_VIDEO = args.livevideo
LINE = args.line


# ____________________________________________________________________________
# HELPERS
# ____________________________________________________________________________

def wait_for_enter():
    """Waits for user input and sets the global stop_recording event."""
    input(">>> Press ENTER to stop recording...\n")
    stop_recording.set()

# ____________________________________________________________________________
# MAIN EXECUTION
# ____________________________________________________________________________

def main():
    system = PySpin.System.GetInstance()
    cam_list = system.GetCameras()
    
    if cam_list.GetSize() == 0:
        print("[ERROR] No cameras detected.")
        cam_list.Clear()
        system.ReleaseInstance()
        return

    cam = cam_list.GetByIndex(0)
    cam.Init()

    # Pre-configure strobe to a constant state (UserOutput1/2)
    source_name = f"UserOutput{LINE}" if LINE in (1, 2) else "UserOutput1"
    set_line_source(cam, f"Line{LINE}", source_name)

    # --- NEW: INITIALIZE CIRCULAR BUFFER ---
    BUFFER_SIZE = FRAMERATE * BUFFER_DURATION_S
    # Create the buffer instance locally
    buffer = CircularBuffer(size=BUFFER_SIZE)
    print(f"[INFO] Initialized Circular Buffer with size: {BUFFER_SIZE} frames ({BUFFER_DURATION_S}s).")
    # ----------------------------------------
    
    # --- Start Recording Block ---
    try:
        input(">>> Press Enter to start recording (strobe ON)...")

        save_path = get_save_path(SAVE_PATH)
        if not os.path.exists(save_path):
            os.makedirs(save_path)

        # 1. Start the Render Worker Thread (FFmpeg)
        render_thread = threading.Thread(
            target=render_worker, 
            args=(save_path, FRAMERATE)
        )
        render_thread.start()

        # 2. Start the NEW Saving Worker Thread (Disk I/O)
        saving_thread = threading.Thread(
            target=saving_worker,
            # PASS THE BUFFER INSTANCE
            args=(buffer, save_path, FRAMERATE, render_queue) 
        )
        saving_thread.start()
        
        # 3. Start the Acquisition Thread (Camera read & Buffer write)
        acquisition_thread = threading.Thread(
            target=acquire_images, 
            # PASS THE BUFFER INSTANCE
            args=(buffer, cam, save_path, DURATION, FRAMERATE, LINE, LIVE_VIDEO)
        )
        acquisition_thread.start()

        # 4. Start thread to listen for Enter press
        input_thread = threading.Thread(target=wait_for_enter)
        input_thread.daemon = True 
        input_thread.start()

        # Main loop checks if recording should stop
        while not stop_recording.is_set():
            time.sleep(0.1)

        acquisition_thread.join()  # Wait for ACQUISITION to finish

        # --- Graceful Shutdown of Workers ---
        print("[INFO] Acquisition done. Waiting for Saving Worker to flush buffer...")
        
        # Signal Saving Worker to stop consuming buffer and exit
        stop_saving_worker.set() 
        saving_thread.join() # Wait for SAVING to flush buffer and finish I/O
        
        # Signal Render Worker to stop and wait for remaining queue items to be processed
        print("[INFO] Waiting for render queue to empty...")
        render_queue.join() # Blocks until all items in the render queue have been processed and marked done
        stop_worker.set() 
        render_thread.join() # Wait for RENDERING to completely finish

    except Exception as e:
        print(f"[FATAL] {e}")

    # --- Cleanup and Video Rendering Block ---
    finally:
        try:
            cam.DeInit()
            del cam
            cam_list.Clear()
            system.ReleaseInstance()
            if LIVE_VIDEO:
                cv2.destroyAllWindows()
        except Exception as cleanup_error:
            print(f"[CLEANUP ERROR] {cleanup_error}")
    
    # Check for fatal frame rate error before rendering
    if fs_error_detected.is_set():
        print("[INFO] Video rendering skipped due to frame rate discrepancy.")
        sys.exit()

    # --- RETRIEVE CHUNK PATHS --- (Read from file written by render_worker)
    chunk_list_file = os.path.join(save_path, "final_chunk_paths.txt")
    chunk_paths = []
    if os.path.exists(chunk_list_file):
        try:
            with open(chunk_list_file, 'r') as f:
                chunk_paths = [line.strip() for line in f if line.strip()] 
            os.remove(chunk_list_file) 
        except Exception as e:
            print(f"[WARNING] Could not read or delete chunk list file: {e}")

    # Run ffmpeg to generate video (pass the list of chunks)
    video_name = os.path.basename(save_path) + ".mp4"
    output_path = os.path.join(os.path.dirname(save_path), video_name)
    
    # PASS CHUNK PATHS TO THE RENDERER
    create_video_from_images(save_path, output_path, FRAMERATE, GENERATE_VIDEO, chunk_paths)

    # Delete frames and chunks if required
    cleanup_frames(save_path, GENERATE_VIDEO, DELETE_FRAMES)


if __name__ == "__main__":
    main()