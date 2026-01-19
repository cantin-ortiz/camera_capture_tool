# main_recorder.py

import argparse
import sys
import threading
import time
import os
import signal
import PySpin
import cv2  
import numpy as np 
# NEW IMPORT: For process-based concurrency
import multiprocessing 

# Add parent directory to path to import config
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from config import CHUNK_DURATION_S, BUFFER_MULTIPLIER, DEFAULT_FRAMERATE, DEFAULT_LINE, DEFAULT_SAVE_PATH
from src.buffer_control import CircularBuffer 
# Import all camera/acquisition functions from the camera module
from src.camera_control import set_line_source, acquire_images, stop_recording, fs_error_detected, run_live_preview, quit_program_event
# Import all file/processing utilities from the processing module
from src.processing_utils import get_save_path, create_video_from_images, cleanup_frames
# Import worker components
from src.render_worker import render_worker
from src.saving_worker import saving_worker, stop_saving_worker

# Expand the default save path from config
DEFAULT_SAVE_PATH = os.path.expanduser(DEFAULT_SAVE_PATH)

# Define the common window name
WINDOW_NAME = 'Live Camera Feed'

# --- GLOBAL MULTIPROCESSING COMPONENTS ---\
manager = None
render_queue = None
stop_worker = None
# --- END GLOBAL MULTIPROCESSING COMPONENTS ---\
# --- NEW GLOBAL EVENT for START ---
start_recording_event = threading.Event()

# ____________________________________________________________________________
#
# SIGNAL HANDLER FOR CTRL+C
# ____________________________________________________________________________
def signal_handler(sig, frame):
    """
    Handle Ctrl+C (SIGINT) gracefully by stopping recording instead of crashing.
    """
    print("\n\n[INFO] Ctrl+C detected. Stopping recording gracefully...")
    if not start_recording_event.is_set():
        # During preview phase - exit immediately
        quit_program_event.set()
        sys.exit(0)
    else:
        # During recording - stop recording gracefully
        stop_recording.set()
        quit_program_event.set()

# ____________________________________________________________________________
#
# UNIFIED CONSOLE LISTENER BLOCK (Handles Start and Stop)
# ____________________________________________________________________________
def console_listener_unified():
    """
    Handles console input for both the START (pre-acquisition) and STOP (during acquisition) phases.
    This runs in a single background thread.
    """
    
    # --- STAGE 1: WAIT FOR START ---
    print("\n[INFO] Press ENTER in the console to START recording, or 'q' + ENTER to quit.")
    try:
        user_input = input()
        
        if user_input.lower().strip() == 'q':
            print("\n[INFO] Console 'q' received during wait. Exiting program.")
            quit_program_event.set()
            return
        else:
            # Signal the main thread to proceed with acquisition setup
            start_recording_event.set()
            print("\n[INFO] Console 'ENTER' received. Starting acquisition...")
            
    except EOFError:
        # Handles case where standard input is closed prematurely
        quit_program_event.set()
        return
    except KeyboardInterrupt:
        # Ctrl+C during input - let signal handler handle it
        quit_program_event.set()
        return
    except Exception as e:
        print(f"[FATAL] Console input error during START wait: {e}")
        quit_program_event.set()
        return

    # --- STAGE 2: WAIT FOR STOP (Blocks here until acquisition is finished or user stops) ---
    print("[INFO] Acquisition is running. Press ENTER in the console to STOP recording, or 'q' + ENTER to quit.")
    
    # This loop ensures the thread can check the quit_program_event if it was set externally 
    while not quit_program_event.is_set() and not stop_recording.is_set():
        try:
            if quit_program_event.is_set() or stop_recording.is_set():
                break
                
            # Block until ENTER is pressed for STOP or 'q' for QUIT
            user_input = input()
            
            if user_input.lower().strip() == 'q':
                print("\n[INFO] Console 'q' received during acquisition. Exiting program.")
                quit_program_event.set()
            else:
                # Assume any other input (like just ENTER) means STOP RECORDING
                stop_recording.set()
                print("\n[INFO] Console 'ENTER' received. Signaling stop...")
                
        except EOFError:
            # Standard input closed, exit gracefully
            quit_program_event.set()
        except KeyboardInterrupt:
            # Ctrl+C during input - let signal handler handle it
            pass
        except Exception as e:
            print(f"[FATAL] Console input error during STOP wait: {e}")
            quit_program_event.set()
        break # Exit loop after handling input or error


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
    help=f'Folder to save videos and frames (default: {DEFAULT_SAVE_PATH})'
)
parser.add_argument('--framerate', type=int, default=DEFAULT_FRAMERATE, help=f'Recording framerate in Hz (should match camera setting) (default: {DEFAULT_FRAMERATE})')
parser.add_argument('--line', type=int, default=DEFAULT_LINE, choices=[1, 2], help=f'Line (GPIO pin) to use for strobe output (1 or 2) (default: {DEFAULT_LINE})')
parser.add_argument('--output', type=str, default='video', choices=['video', 'images', 'both'], help='Output format: video, raw images, or both (default: video)')
parser.add_argument('--keep-frames', action='store_true', help='Keep raw image frames after video generation (default: delete)')
parser.add_argument('--sequential', action='store_true', help='Use sequential rendering (no concurrent worker) (default: concurrent)')
parser.add_argument('--nolive', action='store_true', help='Disable live video preview (default: live)')
parser.add_argument('--debug', action='store_true', help='Enable debug mode with verbose worker output (default: quiet)')

def record_video(
    DURATION, 
    SAVE_PATH, 
    FRAMERATE, 
    LINE, 
    GENERATE_VIDEO, 
    DELETE_FRAMES,
    CONCURRENT_RENDER,
    LIVE_VIDEO,
    DEBUG_MODE):
    
    # --- Shared State for Display (Accessed by acquisition thread and main thread) ---
    latest_frame_data = [None] # Shared list to hold the latest frame (numpy array)
    latest_frame_lock = threading.Lock() # Lock to protect the shared data
    # NEW FLAG: Controls the live display loop, independent of recording stop
    live_display_active = [LIVE_VIDEO] 
    # ---------------------------------------------------------------------
    
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
        try:
             cam.AcquisitionFrameRateEnable.SetValue(True)
        except PySpin.SpinnakerException:
             pass 

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
    
    # Create the thread-safe circular buffer (size: buffer_multiplier * framerate * chunk_duration_s, e.g. 2*50*10 = 1000 frames)
    # The size is dynamically calculated from the config file and command line framerate
    BUFFER_SIZE = int(BUFFER_MULTIPLIER * FRAMERATE * CHUNK_DURATION_S)
    image_buffer = CircularBuffer(BUFFER_SIZE, stop_event=stop_saving_worker)
    print(f"[INFO] Circular buffer created with size {BUFFER_SIZE} frames (multiplier: {BUFFER_MULTIPLIER:.1f}).")

    # ____________________________________________________________________________
    #
    # LIVE PREVIEW & START WAIT PHASE
    # ____________________________________________________________________________
    try:
        # Start the UNIFIED console listener thread immediately
        console_thread = threading.Thread(target=console_listener_unified, daemon=True)
        console_thread.start()
        
        # 1. Start live preview (Acquisition and display starts immediately if LIVE_VIDEO=True)
        run_live_preview(cam, LIVE_VIDEO, start_recording_event)
        
        # 2. Block the main thread until the user signals START or QUIT.
        while not start_recording_event.is_set() and not quit_program_event.is_set():
             time.sleep(0.1)
        
        # Check if quit was requested
        if quit_program_event.is_set():
            raise SystemExit()
        
    except SystemExit:
        # User pressed 'q' in the console or closed the window manually. Clean exit.
        print("[INFO] Exiting program as requested during start phase.")
        sys.exit()
    except Exception as e:
        print(f"[FATAL] Unhandled error during preview/start phase: {e}")
        sys.exit()

    # ____________________________________________________________________________
    #
    # RECORDING PHASE (Execution proceeds here immediately after start_recording_event is set)
    # ____________________________________________________________________________
    
    # --- Start Saving Worker (Consumer Thread) ---
    saving_thread = threading.Thread(
        target=saving_worker, 
        args=(image_buffer, save_path, FRAMERATE, render_queue, CONCURRENT_RENDER, DEBUG_MODE)
    )
    saving_thread.start()
    
    # --- Start Rendering Worker (Concurrent Process) ---
    render_process = None
    if CONCURRENT_RENDER:
        render_process = multiprocessing.Process(
            target=render_worker, 
            args=(save_path, FRAMERATE, render_queue, stop_worker, DEBUG_MODE)
        )
        render_process.start()
        if DEBUG_MODE:
            print(f"[INFO] Concurrent rendering worker started (PID: {render_process.pid})")
    else:
        if DEBUG_MODE:
            print("[INFO] Sequential rendering selected (no concurrent worker).")

    # --- Start Acquisition Thread (Producer) ---
    # Create metadata dictionary for CSV export
    metadata = {
        'duration': DURATION,
        'framerate': FRAMERATE,
        'line': LINE,
        'generate_video': GENERATE_VIDEO,
        'keep_frames': not DELETE_FRAMES,
        'concurrent_render': CONCURRENT_RENDER,
        'live_video': LIVE_VIDEO,
        'debug_mode': DEBUG_MODE
    }
    
    acquisition_thread = threading.Thread(
        target=acquire_images, 
        # Pass shared variables for the main thread display loop
        args=(image_buffer, cam, save_path, DURATION, FRAMERATE, LINE, LIVE_VIDEO, latest_frame_data, latest_frame_lock, metadata) 
    )
    acquisition_thread.start()
    
    # ____________________________________________________________________________
    #
    # MAIN THREAD GUI LOOP (Handles live display, independent of acquisition)
    # ____________________________________________________________________________
    
    # LIVE_VIDEO is the command line flag. live_display_active is the runtime control.
    if LIVE_VIDEO:
        if DEBUG_MODE:
            print("[INFO] Main thread starting dedicated display loop (15 FPS update).")
        
        # Frame rate control for the display (e.g., ~15 FPS display)
        DISPLAY_PERIOD_S = 1.0 / 15.0 
        
        # Loop continues as long as acquisition is running AND the display is active
        while not stop_recording.is_set() and not quit_program_event.is_set() and live_display_active[0]:
            start_time = time.perf_counter()

            # 1. Acquire the latest frame data
            frame_to_display = None
            with latest_frame_lock:
                if latest_frame_data[0] is not None:
                    frame_to_display = latest_frame_data[0] 

            # 2. Display the frame if available
            if frame_to_display is not None:
                try:
                    cv2.imshow(WINDOW_NAME, frame_to_display)
                    
                    # CRITICAL: cv2.waitKey(1) MUST be called from the main thread
                    cv2.waitKey(1) 
                    
                    # Check if the window was closed manually by the user
                    if cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1:
                        print("\n[INFO] Live window closed manually. Continuing recording without live display.")
                        # --- MODIFIED: ONLY SET THE DISPLAY FLAG TO FALSE ---
                        live_display_active[0] = False
                        break # Exit the display loop, but not the recording loop

                except Exception as e:
                    # Catch OpenCV errors that might occur during display
                    print(f"\n[ERROR] Main thread display error: {e}. Disabling live display.")
                    live_display_active[0] = False
                    break

            # 3. Sleep to control the display rate
            elapsed = time.perf_counter() - start_time
            sleep_time = DISPLAY_PERIOD_S - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
                
        # If the display was active but exited due to recording stop, close the window cleanly
        if LIVE_VIDEO and live_display_active[0] == False: # Only run if it was active and now is off
             try:
                 cv2.destroyWindow(WINDOW_NAME)
                 print("[INFO] Closed live display window.")
             except Exception:
                 pass # Ignore if window already closed/not created

        # If the display loop was running, the main thread must wait for the acquisition to finish.
        if LIVE_VIDEO:
             print("[INFO] Main thread is now waiting for acquisition to finish...")

    # If LIVE_VIDEO was False, the main thread was free and now needs to wait for the acquisition to finish.
    # If LIVE_VIDEO was True, the display loop just finished, and the main thread will continue to wait below.
    
    # ____________________________________________________________________________
    #
    # FINAL JOIN & POST-ACQUISITION PROCESSING (This block is now the centralized wait)
    # ____________________________________________________________________________
    
    try:
        # Wait for the acquisition thread to finish (either by duration, console stop, or error)
        if acquisition_thread.is_alive():
             print("[INFO] Waiting for acquisition thread to close...")
             acquisition_thread.join(timeout=None) # Wait indefinitely or until thread terminates
             
        # Wait for the console listener to finish (it should have been signaled by stop_recording)
        if console_thread.is_alive():
            print("[INFO] Waiting for console listener to close...")
            # A short timeout is okay here, as it should close quickly after stop_recording is set.
            console_thread.join(timeout=2) 
        
        # Check if quit was requested
        if quit_program_event.is_set():
            # Stop recording has been signaled by 'q' in the console. Jump to cleanup.
            raise SystemExit()
        
        # --- STOP WORKERS ---
        print("\n[INFO] Acquisition complete. Signaling workers to stop...")
        
        # 1. Stop Saving Worker
        stop_saving_worker.set()
        # Wake up the buffer's condition variable to unblock the saving worker
        with image_buffer.condition:
            image_buffer.condition.notify_all()
        print("[INFO] Waiting for saving worker to finish...")
        saving_thread.join()  # Wait indefinitely for all frames to be saved
        print("[INFO] Saving worker finished.")
        
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
            video_success = False # Prevent frame deletion when video wasn't rendered

        # --- RETRIEVE CHUNK PATHS ---
        chunk_list_file = os.path.join(save_path, "final_chunk_paths.txt")
        # Renamed variable to reflect it holds FFmpeg-formatted lines
        chunk_paths_ff = [] 
        if os.path.exists(chunk_list_file):
            try:
                with open(chunk_list_file, 'r') as f:
                    # FIX: Read the lines *AS IS* (they are already in 'file 'path'\n' format)
                    # The list now holds the correct FFmpeg formatted lines.
                    chunk_paths_ff = [line for line in f if line.strip()] 
            except Exception as e:
                print(f"[WARNING] Could not read chunk list file: {e}")


        # Run ffmpeg to generate video (pass the list of chunks or empty list for sequential mode)
        video_name = os.path.basename(save_path) + ".mp4"
        output_path = os.path.join(os.path.dirname(save_path), video_name)
        
        # create_video_from_images handles both chunk-based (if paths provided) and sequential modes
        if GENERATE_VIDEO and not fs_error_detected.is_set():
            # PASS THE FFmpeg FORMATTED LINES
            video_success = create_video_from_images(save_path, output_path, FRAMERATE, GENERATE_VIDEO, chunk_paths_ff)
        elif fs_error_detected.is_set():
            # Framerate error: frames saved but video not rendered
            video_success = False
        else:
            # Video generation was disabled by user, but frames were successfully saved
            video_success = True
        
    except SystemExit:
        # Exit was requested, ensuring video_success is False to prevent unwanted frame deletion
        video_success = False 
    except Exception as e:
        print(f"[FATAL] Unhandled error in main process: {e}")
        video_success = False

    # --- Camera Cleanup Block ---\
    finally:
        # --- Centralized OpenCV Window Cleanup ---
        # The window was destroyed in the main loop, but use destroyAllWindows for safety
        try:
            if LIVE_VIDEO:
                cv2.destroyAllWindows()
                print("[INFO] Final OpenCV window cleanup.")
        except Exception:
             pass
        
        try:
            cam.DeInit()
            del cam
            cam_list.Clear()
            system.ReleaseInstance()
        except Exception as cleanup_error:
            print(f"[CLEANUP ERROR] Camera hardware cleanup failed: {cleanup_error}")
    
        # Delete frames and chunks if required
        cleanup_frames(save_path, DELETE_FRAMES, video_success)
        
        # If quit was requested, force exit to terminate daemon threads
        if quit_program_event.is_set():
            print("[INFO] Program terminated.")
            os._exit(0)


if __name__ == "__main__":
    # Initialize the multiprocessing objects ONLY when the script is run directly
    multiprocessing.freeze_support() # Recommended for Windows/executable distribution
    
    # Install signal handler for graceful Ctrl+C handling
    signal.signal(signal.SIGINT, signal_handler)
    
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
    DEBUG_MODE = args.debug
    
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
        DEBUG_MODE)