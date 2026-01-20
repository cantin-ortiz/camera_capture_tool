# ============================================================================
# Imports
# ============================================================================
import os
import warnings
warnings.filterwarnings('ignore')

import numpy as np
import matplotlib.pyplot as plt
import cv2
import subprocess
import glob


# ============================================================================
# Parameters
# ============================================================================

# Prompt user for TTL channel
while True:
    try:
        TTL_CHANNEL = int(input("Enter TTL channel to analyze (0-7, default 1): ") or "1")
        if 0 <= TTL_CHANNEL <= 7:
            break
        else:
            print("Please enter a number between 0 and 7.")
    except ValueError:
        print("Invalid input. Please enter a number between 0 and 7.")

print(f"Using TTL channel: {TTL_CHANNEL}")


# ============================================================================
# File Selection
# ============================================================================

default_dir = os.path.expanduser("~/Documents")

# Select Open Ephys recording folder
print("Please select the Open Ephys recording folder (e.g., experiment1/recording1)...")
ps_command = f"""
Add-Type -AssemblyName System.Windows.Forms
$folderBrowser = New-Object System.Windows.Forms.FolderBrowserDialog
$folderBrowser.SelectedPath = '{default_dir}'
$folderBrowser.Description = 'Select Open Ephys recording folder'
$result = $folderBrowser.ShowDialog()
if ($result -eq 'OK') {{
    Write-Output $folderBrowser.SelectedPath
}}
"""

result = subprocess.run(
    ["powershell", "-Command", ps_command],
    capture_output=True,
    text=True
)

recording_path = result.stdout.strip()

if not recording_path or not os.path.exists(recording_path):
    print("No folder selected. Exiting.")
    exit()

print(f"Selected recording: {recording_path}")
main_path = os.path.dirname(recording_path)

# Select video file
print("Please select the video file...")
ps_command_video = f"""
Add-Type -AssemblyName System.Windows.Forms
$openFileDialog = New-Object System.Windows.Forms.OpenFileDialog
$openFileDialog.InitialDirectory = '{main_path}'
$openFileDialog.Filter = 'Video files (*.mp4;*.avi;*.mov)|*.mp4;*.avi;*.mov|All files (*.*)|*.*'
$openFileDialog.Title = 'Select Video file'
$result = $openFileDialog.ShowDialog()
if ($result -eq 'OK') {{
    Write-Output $openFileDialog.FileName
}}
"""

result_video = subprocess.run(
    ["powershell", "-Command", ps_command_video],
    capture_output=True,
    text=True
)

video_file = result_video.stdout.strip()

if not video_file or not os.path.exists(video_file):
    print("No video file selected. Will skip frame count analysis.")
    video_file = None
else:
    print(f"Selected video file: {video_file}")
    
print("Processing data...")


# ============================================================================
# Load Open Ephys Data
# ============================================================================

# Find the Acquisition_Board folder dynamically
events_base = f"{recording_path}/events"
acquisition_folders = glob.glob(f"{events_base}/Acquisition_Board*")
if not acquisition_folders:
    raise FileNotFoundError(f"No Acquisition_Board folder found in {events_base}")
acquisition_folder = acquisition_folders[0]  # Use the first match

event_folder = f"{acquisition_folder}/TTL"
words = np.load(f"{event_folder}/full_words.npy")
timestamps = np.load(f"{event_folder}/timestamps.npy")


# ============================================================================
# Analyze TTL Signal
# ============================================================================

# Define helper function
def get_frame_count(video_path):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise IOError("Cannot open video file")
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    return frame_count

# Decode the specified TTL channel
states = ((words >> TTL_CHANNEL) & 1).astype(int)

# Find rising edges (0→1 transitions) - these are the frame triggers
state_changes = np.diff(states)
rising_edges = np.where(state_changes == 1)[0]
rising_timestamps = timestamps[rising_edges + 1]  # +1 because diff shifts indices

n_frames = len(rising_timestamps)

# Calculate timing information
if n_frames > 1:
    start_time = rising_timestamps[0]
    end_time = rising_timestamps[-1]
    duration = end_time - start_time
    frame_rate = (n_frames - 1) / duration if duration > 0 else 0
else:
    start_time = end_time = duration = frame_rate = 0

# Get video frame count first if available
video_frames = None
if video_file:
    video_frames = get_frame_count(video_file)

# Plot TTL signal
plt.figure(figsize=(12, 4))
plt.step(timestamps, states, where="post")
plt.xlabel('Time (s)')
if video_frames is not None:
    plt.title('TTL Channel {}: {} frames | Video frames: {} | Duration: {:.1f}s at {:.1f} Hz'.format(
        TTL_CHANNEL, n_frames, video_frames, duration, frame_rate))
else:
    plt.title('TTL Channel {}: {} frames | Duration: {:.1f}s at {:.1f} Hz'.format(
        TTL_CHANNEL, n_frames, duration, frame_rate))
plot_path = os.path.join(main_path, f'ttl_signal_channel_{TTL_CHANNEL}.png')
plt.savefig(plot_path, dpi=150, bbox_inches='tight')
plt.close()

print(f"Detected number of frames from TTL (channel {TTL_CHANNEL}): {n_frames}")


# ============================================================================
# Display Results and Frame Comparison
# ============================================================================

if video_file:
    print(f"Detected number of frames from video: {video_frames}")
    
    # Calculate frame difference
    frame_diff = abs(n_frames - video_frames)
    print(f"\nFrame difference (TTL vs Video): {frame_diff}")
    
    if frame_diff < 5:
        print("✓ Looks good! Frame counts match well.")
    elif frame_diff <= 10:
        print("⚠ Suspicious: Frame difference is noticeable. Please verify.")
    else:
        print("✗ Warning: Large frame difference detected. Something may be wrong, please check!")
else:
    print("\nNo video file provided for comparison.")

print(f"\nSaved TTL signal plot to:\n{plot_path}")
