# main_recorder.py

# ____________________________________________________________________________
#
# ARGUMENT PARSING
# ____________________________________________________________________________
import argparse
import sys
import threading
import time
import os

# Import modules
import PySpin
from camera_control import set_line_source, acquire_images, stop_recording, fs_error_detected
from processing_utils import get_save_path, create_video_from_images, cleanup_frames

# Parse command-line arguments
parser = argparse.ArgumentParser(description="Record from FLIR camera.")
parser.add_argument('--duration', type=float, default=None, help='Recording duration in seconds (default: None, infinite)')
parser.add_argument('--save_path', type=str, default="C:/Users/cantino/Documents/flea3_recording", help='Folder to save videos and frames')
parser.add_argument('--framerate', type=int, default=50, help='Recording framerate in Hz (should match SpinView)')
parser.add_argument('--line', type=int, default=1, help='Which line should send the synchronization signal.')
parser.add_argument('--novid', dest='rendervid', action='store_false', help='Skip video conversion')
parser.set_defaults(rendervid=True)
parser.add_argument('--keep-frames', dest='clear', action='store_false', help='Keep frames after video conversion')
parser.set_defaults(clear=True)
parser.add_argument('--nolive', dest='livevideo', action='store_false', help='Do not display live video')
parser.set_defaults(livevideo=True)
args = parser.parse_args()

# Set variables (passed to functions or used globally)
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

    # --- Start Recording Block ---
    try:
        input(">>> Press Enter to start recording (strobe ON)...")

        # Get and create the unique timestamped path
        save_path = get_save_path(SAVE_PATH)
        if not os.path.exists(save_path):
            os.makedirs(save_path)

        # Start image acquisition in a separate thread
        acquisition_thread = threading.Thread(
            target=acquire_images, 
            args=(cam, save_path, DURATION, FRAMERATE, LINE, LIVE_VIDEO)
        )
        acquisition_thread.start()

        # Start thread to listen for Enter press
        input_thread = threading.Thread(target=wait_for_enter)
        input_thread.daemon = True 
        input_thread.start()

        # Main loop checks if recording should stop
        while not stop_recording.is_set():
            time.sleep(0.1)

        acquisition_thread.join()  # Wait for the acquisition thread to finish

    except Exception as e:
        print(f"[FATAL] {e}")

    # --- Cleanup and Video Rendering Block ---
    finally:
        try:
            cam.DeInit()
            del cam
            cam_list.Clear()
            system.ReleaseInstance()
            # If live video was active, clean up the OpenCV window
            if LIVE_VIDEO:
                import cv2
                cv2.destroyAllWindows()
        except Exception as cleanup_error:
            print(f"[CLEANUP ERROR] {cleanup_error}")
    
    # Check for fatal frame rate error before rendering
    if fs_error_detected.is_set():
        print("[INFO] Video rendering skipped due to frame rate discrepancy.")
        sys.exit()

    # Run ffmpeg to generate video
    video_name = os.path.basename(save_path) + ".mp4"
    output_path = os.path.join(os.path.dirname(save_path), video_name)
    create_video_from_images(save_path, output_path, FRAMERATE, GENERATE_VIDEO)

    # Delete frames if required
    cleanup_frames(save_path, GENERATE_VIDEO, DELETE_FRAMES)


if __name__ == "__main__":
    main()