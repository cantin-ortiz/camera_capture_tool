# main_recorder.py

import argparse
import sys
import threading
import time
import os
import PySpin
import cv2  
import numpy as np 
# NEW IMPORT: For process-based concurrency
import multiprocessing 
from config import CHUNK_DURATION_S 
from buffer_control import CircularBuffer 
# Import all camera/acquisition functions from the camera module
# >>> UPDATED IMPORT: Added quit_program_event <<<
from camera_control import set_line_source, acquire_images, stop_recording, fs_error_detected, run_live_preview, quit_program_event 
# Import all file/processing utilities from the processing module
from processing_utils import get_save_path, create_video_from_images, cleanup_frames
# Import worker components
from render_worker import render_worker
from saving_worker import saving_worker, stop_saving_worker

# Define the dynamic default path: ~/Documents/flea3_recordings
DEFAULT_SAVE_PATH = os.path.join(os.path.expanduser('~'), "Documents", "flea3_recordings")

# --- GLOBAL MULTIPROCESSING COMPONENTS ---\
manager = None
render_queue = None
stop_worker = None
# --- END GLOBAL MULTIPROCESSING COMPONENTS ---\

# >>> MODIFIED CONSOLE STOP LISTENER FUNCTION <<<
def console_stop_listener():
    """Waits for console input during acquisition. Sets stop_recording event (ENTER) or quits ('q')."""
    try:
        # Read the console input (blocks until ENTER)
        user_input = input()
        
        if user_input.lower().strip() == 'q':
            print("\n[INFO] Console 'q' received. Exiting program.")
            # Set the quit event to stop acquisition and signal main thread to exit
            quit_program_event.set()
        else:
            # Assume any other input (like just ENTER, or ENTER with other text) means STOP RECORDING
            stop_recording.set()
            print("\n[INFO] Console 'ENTER' received. Stopping acquisition...")
            
    except EOFError:
        pass # Handle process termination


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
parser.add_argument('--framerate', type=int, default=50, help='Recording framerate in Hz (should match camera setting)')
parser.add_argument('--line', type=int, default=2, choices=[1, 2], help='Line (GPIO pin) to use for strobe output (1 or 2, default: 2)')
parser.add_argument('--output', type=str, default='video', choices=['video', 'images', 'both'], help='Output format: video, raw images, or both (default: video)')
parser.add_argument('--keep-frames', action='store_true', help='Keep raw image frames after video generation (default: delete)')
parser.add_argument('--sequential', action='store_true', help='Use sequential rendering (no concurrent worker) (default: concurrent)')
parser.add_argument('--nolive', action='store_true', help='Disable live video preview (default: live)')
parser.add_argument('--no-cleanup', action='store_true', help='Skip the final cleanup and deletion of frames/video files on error (default: cleanup)')

def record_video(
    DURATION, 
    SAVE_PATH, 
    FRAMERATE, 
    LINE, 
    GENERATE_VIDEO, 
    DELETE_FRAMES,
    CONCURRENT_RENDER,
    LIVE_VIDEO,
    SKIP_CLEANUP):
    
    # ____________________________________________________________________________
    #
    # INITIAL SETUP & CAMERA ACQUISITION
    # ____________________________________________________________________________
    
    # Initial success state for cleanup logic
    video_success = False 
    
    # PySpin setup
    system = PySpin.System.GetInstance()
    cam_list = system.GetCameras()
    num_cameras = cam_list.GetSize()
    
    if num_cameras == 0:
        print("[ERROR] No cameras detected.")
        system.ReleaseInstance()
        sys.exit()

    cam = cam_list.GetByIndex(0)
    
    # Camera Initialization
    try:
        cam.Init()
        
        # --- Configure Camera Settings ---
        # Frame rate setting is controlled externally (e.g., SpinView).
        # We only ensure it's enabled if required by the camera model.
        # This line is kept as a minimal requirement for some PySpin cams, but the value is NOT set.
        try:
             cam.AcquisitionFrameRateEnable.SetValue(True)
        except PySpin.SpinnakerException:
             # This node may not be writable/available on all cameras, so we pass
             pass 

        # REMOVED: FrameRate setting: cam.AcquisitionFrameRate.SetValue(FRAMERATE)
        # REMOVED: Exposure Mode setting
        # REMOVED: Exposure Auto setting
        # REMOVED: Exposure Time setting
        # The camera's current exposure and framerate settings will be used.

    except PySpin.SpinnakerException as ex:
        print(f"[ERROR] Camera initialization failed: {ex}")
        system.ReleaseInstance()
        sys.exit()
    except Exception as e:
        print(f"[FATAL] Unhandled error during setup: {e}")
        system.ReleaseInstance()
        sys.exit()
    
    # --- Create Save Path ---
    try:
        save_path = get_save_path(SAVE_PATH)
        os.makedirs(save_path, exist_ok=True)
        print(f"[INFO] Saving frames to: {save_path}")
    except Exception as e:
        print(f"[ERROR] Could not create save directory: {e}")
        # Proceed to cleanup camera without saving
        sys.exit()

    # --- Setup Worker Communication ---
    # Global objects are initialized in __main__
    global manager, render_queue, stop_worker
    
    # Create the thread-safe circular buffer (size: 2 * framerate * chunk_duration_s, e.g. 2*50*10 = 1000 frames)
    # The size is dynamically calculated from the config file and command line framerate
    BUFFER_SIZE = 2 * FRAMERATE * CHUNK_DURATION_S
    image_buffer = CircularBuffer(BUFFER_SIZE)
    print(f"[INFO] Circular buffer created with size {BUFFER_SIZE} frames.")

    # ____________________________________________________________________________
    #
    # LIVE PREVIEW PHASE
    # ____________________________________________________________________________
    try:
        # Run the preview loop. This blocks until the user presses ENTER or 'q' in the console.
        run_live_preview(cam, LIVE_VIDEO)
        
    except SystemExit:
        # User pressed 'q' in the console or closed the window manually. Clean exit.
        print("[INFO] Exiting program as requested during preview.")
        sys.exit()
    except Exception as e:
        print(f"[FATAL] Unhandled error during preview phase: {e}")
        sys.exit()

    # ____________________________________________________________________________
    #
    # RECORDING PHASE (Execution proceeds here immediately after preview returns)
    # ____________________________________________________________________________

    # --- Start Saving Worker (Consumer Thread) ---
    saving_thread = threading.Thread(
        target=saving_worker, 
        args=(image_buffer, save_path, FRAMERATE, render_queue, CONCURRENT_RENDER)
    )
    saving_thread.start()
    
    # --- Start Rendering Worker (Concurrent Process) ---
    render_process = None
    if CONCURRENT_RENDER:
        render_process = multiprocessing.Process(
            target=render_worker, 
            args=(save_path, FRAMERATE, render_queue, stop_worker)
        )
        render_process.start()
        print(f"[INFO] Concurrent rendering worker started (PID: {render_process.pid})")
    else:
        print("[INFO] Sequential rendering selected (no concurrent worker).")

    # --- Start Acquisition Thread (Producer) ---
    acquisition_thread = threading.Thread(
        target=acquire_images, 
        args=(image_buffer, cam, save_path, DURATION, FRAMERATE, LINE, LIVE_VIDEO)
    )
    acquisition_thread.start()
    print("[INFO] Acquisition thread started.")

    # --- START CONSOLE STOP LISTENER ---
    # This thread waits for ENTER (to stop) or 'q' (to quit) in the console.
    print("[INFO] Press ENTER in the console to stop the recording, or 'q' + ENTER to quit.")
    stop_listener_thread = threading.Thread(target=console_stop_listener, daemon=True)
    stop_listener_thread.start()
    
    # ____________________________________________________________________________
    #
    # MAIN THREAD WAITS FOR ACQUISITION TO FINISH
    # ____________________________________________________________________________
    
    try:
        # Wait for the acquisition thread to finish (either by duration or console ENTER/q)
        acquisition_thread.join()
        
        # >>> NEW CHECK: Exit immediately if the quit signal was set during acquisition <<<
        if quit_program_event.is_set():
            # Stop recording has been signaled by 'q' in the console. Jump to cleanup.
            raise SystemExit()
        
        # --- STOP WORKERS ---
        print("\n[INFO] Acquisition complete. Signaling workers to stop...")
        
        # 1. Stop Saving Worker
        stop_saving_worker.set()
        saving_thread.join(timeout=10)
        
        # 2. Stop Rendering Worker (if concurrent)
        if CONCURRENT_RENDER:
            stop_worker.set()
            if render_process.is_alive():
                render_process.join(timeout=30) # Give time for final jobs
            
            # If the process is still running after join, terminate it forcefully
            if render_process.is_alive():
                print("[WARNING] Render worker failed to terminate gracefully. Terminating forcefully.")
                render_process.terminate()

        # ____________________________________________________________________________
        #
        # VIDEO RENDERING & CLEANUP
        # ____________________________________________________________________________

        if not GENERATE_VIDEO:
            print("[INFO] Video generation skipped as requested.")
            video_success = True # Consider frame saving a success
        
        # Check for fatal frame rate error before rendering
        if fs_error_detected.is_set():
            print("[INFO] Video rendering skipped due to frame rate discrepancy.")

        # --- RETRIEVE CHUNK PATHS ---
        chunk_list_file = os.path.join(save_path, "final_chunk_paths.txt")
        chunk_paths = []
        if os.path.exists(chunk_list_file):
            try:
                with open(chunk_list_file, 'r') as f:
                    # Read paths, strip whitespace, and filter empty lines
                    # The format is 'file 'path'\n'
                    chunk_paths = [line.strip().lstrip("file '").rstrip("'") for line in f if line.strip()] 
            except Exception as e:
                print(f"[WARNING] Could not read chunk list file: {e}")

        # Run ffmpeg to generate video (pass the list of chunks or empty list for sequential mode)
        video_name = os.path.basename(save_path) + ".mp4"
        output_path = os.path.join(os.path.dirname(save_path), video_name)
        
        # create_video_from_images handles both chunk-based (if paths provided) and sequential modes
        if GENERATE_VIDEO and not fs_error_detected.is_set():
            video_success = create_video_from_images(save_path, output_path, FRAMERATE, GENERATE_VIDEO, chunk_paths)
        else:
            # Set video_success flag appropriately if rendering was skipped
            video_success = True # Frames were successfully saved, even if video wasn't made
        
    except SystemExit:
        # Exit was requested, ensuring video_success is False to prevent unwanted frame deletion
        video_success = False 
    except Exception as e:
        print(f"[FATAL] Unhandled error in main process: {e}")
        video_success = False

    # --- Camera Cleanup Block ---\
    finally:
        if not SKIP_CLEANUP:
            try:
                cam.DeInit()
                del cam
                cam_list.Clear()
                system.ReleaseInstance()
            except Exception as cleanup_error:
                print(f"[CLEANUP ERROR] Camera hardware cleanup failed: {cleanup_error}")
    
        # Delete frames and chunks if required
        cleanup_frames(save_path, DELETE_FRAMES, video_success)


if __name__ == "__main__":
    # Initialize the multiprocessing objects ONLY when the script is run directly
    multiprocessing.freeze_support() # Recommended for Windows/executable distribution
    
    manager = multiprocessing.Manager()
    render_queue = manager.Queue()
    stop_worker = manager.Event()
    
    # --- ARGUMENT PARSING ---
    args = parser.parse_args()
    
    # --- CONFIGURE RUNTIME PARAMETERS ---
    DURATION = args.duration
    SAVE_PATH = args.save_path
    FRAMERATE = args.framerate
    LINE = args.line
    GENERATE_VIDEO = (args.output == 'video' or args.output == 'both')
    DELETE_FRAMES = not args.keep_frames
    CONCURRENT_RENDER = not args.sequential
    LIVE_VIDEO = not args.nolive
    SKIP_CLEANUP = args.no_cleanup
    
    # --- START RECORDING ---
    record_video(
        DURATION, 
        SAVE_PATH, 
        FRAMERATE, 
        LINE, 
        GENERATE_VIDEO, 
        DELETE_FRAMES, 
        CONCURRENT_RENDER, 
        LIVE_VIDEO,
        SKIP_CLEANUP)