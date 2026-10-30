# ============================================================================
# Imports
# ============================================================================
import os
import sys
import warnings
warnings.filterwarnings('ignore')

import numpy as np
import matplotlib
matplotlib.use('Agg')  # Plots are only saved to file, never shown
import matplotlib.pyplot as plt
import cv2
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from importrhsutilities import load_file


# ============================================================================
# Parameters
# ============================================================================

# Prompt user for digital input channel
while True:
    try:
        DIN_CHANNEL = int(input("Enter digital input channel to analyze (1-16, default 1): ") or "1")
        if 1 <= DIN_CHANNEL <= 16:
            break
        else:
            print("Please enter a number between 1 and 16.")
    except ValueError:
        print("Invalid input. Please enter a number between 1 and 16.")

DIN_NAME = f"DIGITAL-IN-{DIN_CHANNEL:02d}"
print(f"Using digital input: {DIN_NAME}")


# ============================================================================
# File Selection
# ============================================================================

default_dir = os.path.expanduser("~/Documents")

# Select Intan .rhs file
print("Please select the Intan .rhs file...")
ps_command = f"""
Add-Type -AssemblyName System.Windows.Forms
$openFileDialog = New-Object System.Windows.Forms.OpenFileDialog
$openFileDialog.InitialDirectory = '{default_dir}'
$openFileDialog.Filter = 'Intan RHS files (*.rhs)|*.rhs|All files (*.*)|*.*'
$openFileDialog.Title = 'Select Intan .rhs file'
$result = $openFileDialog.ShowDialog()
if ($result -eq 'OK') {{
    Write-Output $openFileDialog.FileName
}}
"""

result = subprocess.run(
    ["powershell", "-Command", ps_command],
    capture_output=True,
    text=True
)

rhs_file = result.stdout.strip()

if not rhs_file or not os.path.exists(rhs_file):
    print("No file selected. Exiting.")
    exit()

print(f"Selected file: {rhs_file}")
main_path = os.path.dirname(rhs_file)

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
# Load Intan Data
# ============================================================================

data, data_present = load_file(rhs_file)

if not data_present:
    raise ValueError("The .rhs file contains no data (header-only file).")
if 'board_dig_in_data' not in data:
    raise ValueError("No digital input channels were saved in this .rhs file.")

din_channels = data['board_dig_in_channels']
din_idx = next((i for i, ch in enumerate(din_channels)
                if ch['native_channel_name'] == DIN_NAME), None)
if din_idx is None:
    available = ", ".join(ch['native_channel_name'] for ch in din_channels)
    raise ValueError(f"{DIN_NAME} not found in recording. Available: {available}")

states = data['board_dig_in_data'][din_idx, :].astype(int)
timestamps = data['t']


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

# Only keep samples around state changes for plotting (full-rate data is huge)
change_idx = np.where(state_changes != 0)[0]
plot_idx = np.unique(np.concatenate(([0, len(states) - 1], change_idx, change_idx + 1)))
plot_t = timestamps[plot_idx]
plot_states = states[plot_idx]

# Plot TTL signal with zoom windows
fig, axes = plt.subplots(3, 1, figsize=(12, 10))

# Full signal plot
axes[0].step(plot_t, plot_states, where="post")
axes[0].set_xlabel('Time (s)')
if video_frames is not None:
    axes[0].set_title('{}: {} frames | Video frames: {} | Duration: {:.1f}s at {:.1f} Hz'.format(
        DIN_NAME, n_frames, video_frames, duration, frame_rate))
else:
    axes[0].set_title('{}: {} frames | Duration: {:.1f}s at {:.1f} Hz'.format(
        DIN_NAME, n_frames, duration, frame_rate))
axes[0].grid(True, alpha=0.3)

# Zoom on start (±500ms window)
zoom_window = 0.5  # 500ms
start_mask = (plot_t >= start_time - zoom_window) & (plot_t <= start_time + zoom_window)
axes[1].step(plot_t[start_mask], plot_states[start_mask], where="post")
axes[1].set_xlabel('Time (s)')
axes[1].set_title(f'Recording Start ({start_time:.1f}s)')
axes[1].set_xlim(start_time - zoom_window, start_time + zoom_window)
axes[1].grid(True, alpha=0.3)
axes[1].axvline(start_time, color='r', linestyle='--', alpha=0.5, label='First frame')
axes[1].legend()

# Zoom on end (±500ms window)
end_mask = (plot_t >= end_time - zoom_window) & (plot_t <= end_time + zoom_window)
axes[2].step(plot_t[end_mask], plot_states[end_mask], where="post")
axes[2].set_xlabel('Time (s)')
axes[2].set_title(f'Recording End ({end_time:.1f}s)')
axes[2].set_xlim(end_time - zoom_window, end_time + zoom_window)
axes[2].grid(True, alpha=0.3)
axes[2].axvline(end_time, color='r', linestyle='--', alpha=0.5, label='Last frame')
axes[2].legend()

plt.tight_layout()
plot_path = os.path.join(main_path, f'ttl_signal_din_{DIN_CHANNEL:02d}.png')
plt.savefig(plot_path, dpi=150, bbox_inches='tight')
plt.close()

print(f"Detected number of frames from TTL ({DIN_NAME}): {n_frames}")


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
