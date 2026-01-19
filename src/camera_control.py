# camera_control.py

import PySpin
import os
import cv2
import threading
import time
import sys
import queue
import numpy as np # Explicitly imported for np_image.copy()
# Import the buffer class for type hinting
from src.buffer_control import CircularBuffer 
# Import config values
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from config import CHUNK_DURATION_S, BUFFER_MULTIPLIER, JPEG_QUALITY 

# Windows API for console focus management
import ctypes

# Global events for thread communication
stop_recording = threading.Event()
fs_error_detected = threading.Event()
# Event to signal program exit across all threads
quit_program_event = threading.Event() 

# Define the common window name
WINDOW_NAME = 'Live Camera Feed'


def refocus_console():
    """
    Refocus the console window after OpenCV window creation steals focus.
    Windows-specific implementation using ctypes.
    """
    try:
        # Get the console window handle
        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32
        
        hwnd = kernel32.GetConsoleWindow()
        if hwnd:
            # Bring console window to foreground
            user32.SetForegroundWindow(hwnd)
    except Exception:
        # Silently fail on non-Windows or if API calls fail
        pass


def set_line_source(cam, line_name, source_name):
    """
    Set the output signal source for a specific GPIO line on the camera.
    """
    nodemap = cam.GetNodeMap()
    try:
        cam.EndAcquisition()
    except:
        pass

    line_selector = PySpin.CEnumerationPtr(nodemap.GetNode("LineSelector"))
    line_entry = line_selector.GetEntryByName(line_name)
    line_selector.SetIntValue(line_entry.GetValue())

    line_source = PySpin.CEnumerationPtr(nodemap.GetNode("LineSource"))
    source_entry = line_source.GetEntryByName(source_name)

    if source_entry is None:
        raise RuntimeError(f"[ERROR] LineSource option '{source_name}' not found.")
    if not PySpin.IsWritable(line_source):
        raise RuntimeError(f"[ERROR] Cannot write to LineSource '{source_name}'.")

    line_source.SetIntValue(source_entry.GetValue())
    print(f"[INFO] Set {line_name} LineSource to {source_name}")


def run_live_preview(cam, LIVE_VIDEO, start_recording_event):
    """
    Runs live video preview until the start_recording_event is set in the console 
    or the window is manually closed (which triggers a full program exit in this phase).
    """
    if not LIVE_VIDEO:
        return
        
    # 1. Start Acquisition for Preview
    nodemap = cam.GetNodeMap()
    acquisition_mode = PySpin.CEnumerationPtr(nodemap.GetNode("AcquisitionMode"))
    acquisition_mode.SetIntValue(acquisition_mode.GetEntryByName("Continuous").GetValue())

    cam.BeginAcquisition()
    
    # Ensure the window is created outside the loop
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_AUTOSIZE)
    
    # Refocus the console after window creation
    refocus_console()
    
    preview_active = True
    
    while preview_active:
        try:
            # Check for console input event first
            if start_recording_event.is_set():
                preview_active = False # Break the preview loop
                continue

            # Check for quit event
            if quit_program_event.is_set():
                raise SystemExit()
                
            # READ CAMERA (Time-critical operation)
            # Use a short timeout to prevent blocking indefinitely
            image_result = cam.GetNextImage(100) 
            
            if image_result.IsIncomplete():
                image_result.Release()
                continue
                
            np_image = image_result.GetNDArray()
            image_result.Release()
            
            # LIVE VIDEO PREVIEW
            cv2.imshow(WINDOW_NAME, np_image)
            
            # Only call waitKey(1) to process window events (like manual close)
            cv2.waitKey(1) 
            
            # Check if the window was closed manually by the user
            if cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1:
                print("\n[INFO] Live window closed manually. Exiting program.")
                # Closing the window is now treated as an exit command in the PREVIEW phase.
                quit_program_event.set()
                raise SystemExit() 
            
        except PySpin.SpinnakerException as ex:
            print(f"\n[ERROR] Image acquisition error during preview: {ex}")
            preview_active = False
        except SystemExit:
            raise # Re-raise the exit signal from console_listener or window close
        except Exception as e:
            print(f"\n[FATAL] Unhandled error during preview: {e}")
            preview_active = False

    # 2. Stop Acquisition after Preview
    try:
        # Note: Acquisition is stopped here. It will be restarted in acquire_images.
        cam.EndAcquisition() 
    except PySpin.SpinnakerException:
        print("[WARNING] Could not end preview acquisition cleanly.")
        
    # The window remains open for the main thread's display loop to take over.


# Removed display_worker function.

def acquire_images(buffer: CircularBuffer, cam, save_path, DURATION, FRAMERATE, LINE, LIVE_VIDEO, latest_frame_data, latest_frame_lock, metadata=None):
    """
    Continuously acquires images and writes them to the in-memory CircularBuffer and 
    the latest_frame_data for the main thread display loop.
    The display logic (cv2.imshow) is REMOVED from this time-critical function.
    """
    global stop_recording
    nodemap = cam.GetNodeMap()
    acquisition_mode = PySpin.CEnumerationPtr(nodemap.GetNode("AcquisitionMode"))
    acquisition_mode.SetIntValue(acquisition_mode.GetEntryByName("Continuous").GetValue())

    # Set strobe signal to ExposureActive (Strobe ON)
    if LINE in (1, 2):
        set_line_source(cam, f"Line{LINE}", "ExposureActive")
    
    t_set_line_exposure = time.perf_counter()
    cam.BeginAcquisition()
    # Console listener in main_recorder.py handles the stop
    
    if DURATION is not None:
        print(f"[INFO] Capture will stop automatically after {DURATION} s")
    
    # CHUNK_DURATION_S is imported, this calculation is correct
    FRAMES_PER_CHUNK = FRAMERATE * CHUNK_DURATION_S 
    
    i = 0 # Total frames acquired
    t_first_frame = 0
    t_last_frame = 0
    
    current_frame_index = 0

    while not stop_recording.is_set() and not quit_program_event.is_set():
        try:
            # 1. READ CAMERA (Time-critical operation)
            image_result = cam.GetNextImage(1000) 
            if i == 0:
                t_first_frame = time.perf_counter()       
            
            if image_result.IsIncomplete():
                print(f"\n[WARNING] Incomplete image {i}")
                image_result.Release()
                continue

            # Create a stable copy of the image data before camera buffer is reused
            # This single copy serves both the saving worker and display
            np_image = image_result.GetNDArray().copy()
            image_result.Release()
            
            # --- UPDATE SHARED FRAME DATA FOR MAIN THREAD DISPLAY ---
            if LIVE_VIDEO:
                # Share the same copy with the display thread
                with latest_frame_lock:
                    latest_frame_data[0] = np_image
            
            # 2. WRITE TO BUFFER (FAST, RAM operation - no additional copy needed)
            current_frame_index = buffer.put(np_image)
            t_last_frame = time.perf_counter()
            i += 1
            
            # Automatic stop after duration check
            if DURATION is not None and (t_last_frame - t_first_frame) > DURATION:
                stop_recording.set()

        except PySpin.SpinnakerException as ex:
            print(f"\n[ERROR] Image acquisition error: {ex}")
            stop_recording.set()
            break
        except cv2.error as e:
            print(f"\n[ERROR] OpenCV error in acquisition: {e}")
            stop_recording.set()
            break
        except SystemExit:
            # Exit was requested from a worker
            stop_recording.set()
            break
        except Exception as e:
            # Catch any other unexpected errors
            print(f"\n[FATAL] Unhandled error in acquisition: {e}")
            stop_recording.set()
            break

    # End acquisition and reset strobe signal
    try:
        cam.EndAcquisition()
        source_name = f"UserOutput{LINE}" if LINE in (1, 2) else "UserOutput1"
        set_line_source(cam, f"Line{LINE}", source_name)
        print("[INFO] Strobe disabled.")
        t_set_line_constant = time.perf_counter()    
    except PySpin.SpinnakerException:
        print("[WARNING] Could not end acquisition cleanly")


    print("\n[INFO] Acquisition complete")

    # Save and Check timing data (i is the total frames ACQUIRED)
    _process_timing(save_path, i, t_first_frame, t_last_frame, t_set_line_exposure, t_set_line_constant, FRAMERATE, metadata)

    return    


def _process_timing(save_path, nframes, t_first_frame, t_last_frame, t_set_line_exposure, t_set_line_constant, FRAMERATE, metadata=None):
    """
    Internal helper to calculate and save timing data (Original simple CSV format).
    """
    global fs_error_detected
    
    # Calculate acquisition metrics
    duration = t_last_frame - t_first_frame
    estimated_fs = nframes / duration if duration > 0 else 0

    print(f"Time between strobe ON and first frame: {(t_first_frame - t_set_line_exposure) * 1e3:.1f} ms")
    print(f"Time between last frame and strobe OFF: {(t_set_line_constant - t_last_frame) * 1e3:.1f} ms")
    print(f"[INFO] {nframes} frames recorded over {duration:.1f} seconds, estimated fs: {estimated_fs:.1f} Hz.")

    # Frame rate stability check
    if abs(estimated_fs - FRAMERATE) > 1 and nframes > 10:
        fs_error_detected.set()
        print(f"[ERROR] Estimated frame rate ({estimated_fs:.1f} Hz) differs from expected ({FRAMERATE} Hz) by more than 1 Hz. Video won't be rendered but frames remained saved.")

    # Saving time edges and configuration metadata
    try:
        csv_name = os.path.basename(save_path) + ".csv"
        output_file = os.path.join(os.path.dirname(save_path), csv_name)     
        with open(output_file, "w") as f:
            f.write("Variable,Value\n")
            # Timing data
            f.write(f"t_first_frame,{t_first_frame}\n")
            f.write(f"t_set_line_exposure,{t_set_line_exposure}\n")
            f.write(f"t_set_line_constant,{t_set_line_constant}\n")
            f.write(f"t_last_frame,{t_last_frame}\n")
            # Configuration and runtime parameters
            if metadata:
                f.write(f"duration_s,{metadata.get('duration', 'None')}\n")
                f.write(f"framerate_hz,{metadata.get('framerate')}\n")
                f.write(f"gpio_line,{metadata.get('line')}\n")
                f.write(f"generate_video,{metadata.get('generate_video')}\n")
                f.write(f"keep_frames,{metadata.get('keep_frames')}\n")
                f.write(f"concurrent_render,{metadata.get('concurrent_render')}\n")
                f.write(f"live_video,{metadata.get('live_video')}\n")
                f.write(f"debug_mode,{metadata.get('debug_mode')}\n")
                f.write(f"chunk_duration_s,{CHUNK_DURATION_S}\n")
                f.write(f"buffer_multiplier,{BUFFER_MULTIPLIER}\n")
                f.write(f"jpeg_quality,{JPEG_QUALITY}\n")
        print(f"[INFO] Timing saved to {output_file}")
    except Exception as e:
        print(f"[WARNING] Could not export time offsets: {e}")