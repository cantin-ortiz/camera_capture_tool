# camera_control.py

import PySpin
import os
import cv2
import threading
import time
import sys
import queue
# Import the buffer class for type hinting
from buffer_control import CircularBuffer 
# Import the chunk duration from the central config
from config import CHUNK_DURATION_S 

# Global events for thread communication
stop_recording = threading.Event()
fs_error_detected = threading.Event()


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


def acquire_images(buffer: CircularBuffer, cam, save_path, DURATION, FRAMERATE, LINE, LIVE_VIDEO):
    """
    Continuously acquires images and writes them to the in-memory CircularBuffer.
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
    print("[INFO] Started acquisition. Press ENTER or 'q' to stop recording.")

    if DURATION is not None:
        print(f"[INFO] Capture will stop automatically after {DURATION} s")
    
    # CHUNK_DURATION_S is imported, this calculation is correct
    FRAMES_PER_CHUNK = FRAMERATE * CHUNK_DURATION_S 
    
    i = 0 # Total frames acquired
    t_first_frame = 0
    t_last_frame = 0
    
    current_frame_index = 0

    # --- Window status tracking ---
    window_active = LIVE_VIDEO
    WINDOW_NAME = 'Live Camera Feed'
    if window_active:
        # Explicitly create the window if we intend to show video
        cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_AUTOSIZE)
    # ------------------------------

    while not stop_recording.is_set():
        try:
            # 1. READ CAMERA (Time-critical operation)
            image_result = cam.GetNextImage(1000) 
            if i == 0:
                t_first_frame = time.perf_counter()       
            
            if image_result.IsIncomplete():
                print(f"\n[WARNING] Incomplete image {i}")
                image_result.Release()
                continue

            np_image = image_result.GetNDArray()
            
            # LIVE VIDEO PREVIEW (MODIFIED LOGIC)
            if window_active:
                
                # CRITICAL: 1. Check window status first, before attempting to draw
                window_status = cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE)

                if window_status < 1:
                    # Window was closed by user. Disable future display attempts.
                    window_active = False 
                    cv2.destroyAllWindows() # Clean up all windows/handles reliably
                    print("\n[INFO] Live window closed manually. Continuing acquisition without feedback.")
                    # Jump to buffer writing for the current frame, skipping drawing
                    # This prevents cv2.imshow from being called in subsequent loops
                else:
                    # 2. Only draw and check keypress if the window is still active
                    cv2.imshow(WINDOW_NAME, np_image)
                    
                    # 3. Check for 'q' key press (and process OS events)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        print("\n[INFO] 'q' pressed. Stopping recording...")
                        stop_recording.set()
                
                # Check for clean exit
                if stop_recording.is_set():
                    image_result.Release()
                    break

            # 2. WRITE TO BUFFER (FAST, RAM operation) - This is outside the display check, so it's always fast.
            current_frame_index = buffer.put(np_image) 
            
            image_result.Release()
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
            # Catch OpenCV errors that might occur if the window was closed but the state is bad
            print(f"\n[ERROR] OpenCV error in acquisition: {e}")
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
    finally:
        # Final cleanup for the OpenCV window
        cv2.destroyAllWindows()


    print("\n[INFO] Acquisition complete")

    # Save and Check timing data (i is the total frames ACQUIRED)
    _process_timing(save_path, i, t_first_frame, t_last_frame, t_set_line_exposure, t_set_line_constant, FRAMERATE)

    return    


def _process_timing(save_path, nframes, t_first_frame, t_last_frame, t_set_line_exposure, t_set_line_constant, FRAMERATE):
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

    # Saving time edges
    try:
        csv_name = os.path.basename(save_path) + ".csv"
        output_file = os.path.join(os.path.dirname(save_path), csv_name)     
        with open(output_file, "w") as f:
            f.write("Variable,Value (s)\n")
            f.write(f"t_first_frame,{t_first_frame}\n")
            f.write(f"t_set_line_exposure,{t_set_line_exposure}\n")
            f.write(f"t_set_line_constant,{t_set_line_constant}\n")
            f.write(f"t_last_frame,{t_last_frame}\n")
        print(f"[INFO] Timing saved to {output_file}")
    except Exception as e:
        print(f"[WARNING] Could not export time offsets: {e}")