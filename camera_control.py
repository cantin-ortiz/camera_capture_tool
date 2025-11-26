# camera_control.py

import PySpin
import os
import cv2
import threading
import time
import sys

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


def acquire_images(cam, save_path, DURATION, FRAMERATE, LINE, LIVE_VIDEO):
    """
    Continuously acquires images from the camera and saves them to disk.
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
    print("[INFO] Started acquisition. Press ENTER to stop recording.")

    if DURATION is not None:
        print(f"[INFO] Otherwise, capture will stop automatically after {DURATION} s")
    i = 0
    t_first_frame = 0
    t_last_frame = 0

    while not stop_recording.is_set():
        try:
            # GetNextImage with 1 second timeout
            image_result = cam.GetNextImage(1000) 
            if i == 0:
                t_first_frame = time.perf_counter()       
            
            if image_result.IsIncomplete():
                print(f"[WARNING] Incomplete image {i}")
                image_result.Release()
                continue

            np_image = image_result.GetNDArray()
            
            # ---------------------------
            # LIVE VIDEO PREVIEW
            # Display frame only once every 5 iterations (50 FPS / 5 = 10 FPS display)
            if LIVE_VIDEO and (i % 5 == 0):
                cv2.imshow('Live Camera Feed', np_image)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    stop_recording.set()
            # ---------------------------

            # Save frame to disk
            filename = os.path.join(save_path, f"frame_{i:07d}.jpg")
            # Note: OpenCV's imwrite can take parameters for JPEG quality if needed
            cv2.imwrite(filename, np_image) 
            print(f"[INFO] Saved {filename}", end='\r')

            image_result.Release()
            t_last_frame = time.perf_counter()
            i += 1

            # Automatically stop after the set duration
            if DURATION is not None and (t_last_frame - t_first_frame) > DURATION:
                stop_recording.set()

        except PySpin.SpinnakerException as ex:
            print(f"\n[ERROR] Image acquisition error: {ex}")
            stop_recording.set()
            break
        except cv2.error as e:
            # Handle OpenCV GUI issues
            print(f"\n[ERROR] OpenCV error in acquisition: {e}")
            stop_recording.set()
            break

    # End acquisition and reset strobe signal
    try:
        cam.EndAcquisition()
        # Set strobe signal back to constant state (Strobe OFF)
        source_name = f"UserOutput{LINE}" if LINE in (1, 2) else "UserOutput1"
        set_line_source(cam, f"Line{LINE}", source_name)
        print("[INFO] Strobe disabled.")
        t_set_line_constant = time.perf_counter()    
    except PySpin.SpinnakerException:
        print("[WARNING] Could not end acquisition cleanly")

    print("\n[INFO] Acquisition complete")

    # Save and check timing data
    _process_timing(save_path, i, t_first_frame, t_last_frame, t_set_line_exposure, t_set_line_constant, FRAMERATE)

    return    


def _process_timing(save_path, nframes, t_first_frame, t_last_frame, t_set_line_exposure, t_set_line_constant, FRAMERATE):
    """
    Internal helper to calculate and save timing data.
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