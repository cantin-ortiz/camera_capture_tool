# ============================================================================
# Imports
# ============================================================================
import os
import warnings
warnings.filterwarnings('ignore')

import numpy as np
from axona import RawFile
from datetime import datetime
import matplotlib.pyplot as plt
import cv2
import subprocess


# ============================================================================
# Parameters
# ============================================================================

# Sampling frequency (Hz) - adjust if needed
fs = 48e3  # 48 kHz

# Axona channel remapping
_axona_channel_remap = (32, 33, 34, 35, 36, 37, 38, 39,
                            0,   1,  2,  3,  4,  5,  6,  7,
                            40, 41, 42, 43, 44, 45, 46, 47,
                            8,   9, 10, 11, 12, 13, 14, 15,
                            48, 49, 50, 51, 52, 53, 54, 55,
                            16, 17, 18, 19, 20, 21, 22, 23,
                            56, 57, 58, 59, 60, 61, 62, 63,
                            24, 25, 26, 27, 28, 29, 30, 31)
_axona_inverse_channel_remap = np.arange(64)[_axona_channel_remap, ]
_128ch_pk_slice = (slice(None, 64), slice(64, None))
_traces_pk_slice = (slice(None), _axona_channel_remap)
_valid_channels = np.ones(64, dtype=bool)

load_traces = False

# ============================================================================
# File Selection
# ============================================================================

default_dir = os.path.expanduser("~/Documents")

# Select Axona .bin file
print("Please select the Axona .bin file...")
ps_command = f"""
Add-Type -AssemblyName System.Windows.Forms
$openFileDialog = New-Object System.Windows.Forms.OpenFileDialog
$openFileDialog.InitialDirectory = '{default_dir}'
$openFileDialog.Filter = 'Axona Binary files (*.bin)|*.bin|All files (*.*)|*.*'
$openFileDialog.Title = 'Select Axona .bin file'
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

raw_path = result.stdout.strip()

if not raw_path or not os.path.exists(raw_path):
    print("No file selected. Exiting.")
    exit()

print(f"Selected file: {raw_path}")
main_path = os.path.dirname(raw_path)

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
# Load Axona Data
# ============================================================================

with RawFile(raw_path) as raw_data:
    num_pkgs = len(raw_data)
    packet_ids = np.zeros(num_pkgs, dtype='a4')
    packet_num = np.zeros(num_pkgs, dtype=np.uint32)
    digital_in = np.zeros((num_pkgs, 16), dtype=np.uint8)
    sync_in = np.zeros((num_pkgs, 16), dtype=np.uint8)
    frame_counter = np.zeros(num_pkgs, dtype=np.uint32)
    position = np.zeros((num_pkgs, 8), dtype=np.uint16)
    digital_out = np.zeros((num_pkgs, 16), dtype=np.uint8)
    stimulator_status = np.zeros((num_pkgs, 16), dtype=np.uint8)
    keys_pressed = np.zeros((num_pkgs, 2), dtype='a1')
    
    if load_traces:
        traces_shape = (num_pkgs*3, _valid_channels.sum())
        traces = np.zeros(traces_shape, dtype=np.int16)
    
    pkg_idx = 0
    for packet in raw_data:
        # Read packet
        (pkg_id, pkg_num, dig_in, snc_in, frm_ctr, pos_tracking, data,
            dig_out, stim_status, keys) = RawFile.read_packet(packet)
        packet_ids[pkg_idx] = pkg_id
        packet_num[pkg_idx] = pkg_num
        digital_in[pkg_idx, :] = dig_in
        sync_in[pkg_idx, :] = snc_in
        frame_counter[pkg_idx] = frm_ctr
        position[pkg_idx, :] = pos_tracking
        digital_out[pkg_idx, :] = dig_out
        stimulator_status[pkg_idx, :] = stim_status
        keys_pressed[pkg_idx, :] = keys
        
        if load_traces:
            data_idx = (
                            slice(pkg_idx*3, (pkg_idx+1)*3),
                            slice(None)
                        )
            # Write data in output file
            pk_data = data[_traces_pk_slice]
            traces[data_idx] = \
                pk_data[:, _valid_channels]
                
        # Advance the packet index
        pkg_idx += 1


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

sample_to_time = fs/3

ttl_signal = digital_in[:,8]
acquisition_start = np.where(np.diff(ttl_signal) == 1)[0]
start_time = acquisition_start[0]/sample_to_time
end_time = acquisition_start[-1]/sample_to_time
n_frames = len(acquisition_start)

duration = end_time-start_time
x = np.linspace(0,digital_in.shape[0]/sample_to_time,num=len(ttl_signal))

# Get video frame count first if available
video_frames = None
if video_file:
    video_frames = get_frame_count(video_file)

# Plot full TTL signal
plt.figure(figsize=(12, 4))
plt.plot(x,ttl_signal)
plt.xlabel('Time (s)')
if video_frames is not None:
    plt.title('TTL frames: {:d} | Video frames: {:d} | Duration: {:.1f}s at {:.1f} Hz'.format(
        n_frames, video_frames, duration, n_frames/duration))
else:
    plt.title('TTL frames: {:d} | Duration: {:.1f}s at {:.1f} Hz'.format(
        n_frames, duration, n_frames/duration))
plot_path_1 = os.path.join(main_path, 'ttl_signal_full.png')
plt.savefig(plot_path_1, dpi=150, bbox_inches='tight')
plt.close()

print(f"Detected number of frames from TTL: {n_frames}")


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

print(f"\nSaved TTL signal plot to:\n{plot_path_1}")

