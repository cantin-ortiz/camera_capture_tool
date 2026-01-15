# FLIR Camera Recording Tool

A camera recording tool for synchronized FLIR camera capture with real-time preview, concurrent video encoding, and GPIO strobe control.

## Quick Start

### Prerequisites

- Python 3.x
- FLIR camera with Spinnaker SDK installed

### Installation

1. Clone or download this repository
2. Ensure your Python virtual environment is set up with required packages:
   - PySpin (FLIR Spinnaker SDK)
   - OpenCV (cv2)
   - NumPy
   - FFmpeg (system installation)

### Running the Recorder

**Simple method** (double-click):
```
start_recording.bat
```

**With arguments**:
```batch
start_recording.bat --duration 30 --framerate 50
```

**Direct Python**:
```bash
python src/main_recorder.py [OPTIONS]
```

## Usage

### Basic Workflow

1. **Start the program**: Double-click `start_recording.bat` or run from command line
2. **Preview phase**: Camera preview appears (if not disabled with `--nolive`)
3. **Start recording**: Press ENTER in the console when ready
4. **Stop recording**: Press ENTER again, or wait for duration to elapse
5. **Processing**: Video is rendered and frames are cleaned up automatically

### Command-Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `--duration SECONDS` | Recording duration (infinite if not specified) | None |
| `--framerate HZ` | Camera framerate in Hz, must match what you set in SpinView | 50 | 
| `--save_path PATH` | Folder for saving recordings | `~/Documents/flea3_recordings` |
| `--line {1,2}` | GPIO line for strobe output | 2 |
| `--output {video,images,both}` | Output format | video |
| `--keep-frames` | Keep raw frames after video generation | False |
| `--sequential` | Disable concurrent rendering | False |
| `--nolive` | Disable live preview | False |
| `--debug` | Enable verbose debug output | False |

### Examples

**10-second test recording at 40 Hz**:
Remember to edit the framerate in SpinView! If it does not match, the code will crash at the end.
```bash
start_recording.bat --duration 10 --framerate 40
```

**Keep frames for post-processing**:
```bash
start_recording.bat --keep-frames
```

**Low-speed capture without preview**:
```bash
start_recording.bat --framerate 10 --nolive
```

**Debug mode with frame preservation**:
```bash
start_recording.bat --debug --keep-frames --sequential
```

## Configuration

Edit `config.py` to customize default settings:

```python
# Virtual environment path (relative to project root)
VENV_PATH = "../env_camera"

# Chunk duration for video encoding (seconds)
CHUNK_DURATION_S = 10

# Buffer size multiplier (increase if disk is slow)
BUFFER_MULTIPLIER = 2.0

# JPEG quality (0-100, higher = better quality)
JPEG_QUALITY = 85
```

### Recommended Settings

- **Standard recording**: Default settings work well
- **Slow disk**: Increase `BUFFER_MULTIPLIER` to 3.0 or 4.0
- **High quality**: Set `JPEG_QUALITY` to 95
- **Fast recording**: Set `JPEG_QUALITY` to 75, use `--nolive`

## Project Structure

```
camera_capture_tool/
├── README.md                  # This file
├── config.py                  # User-editable configuration
├── start_recording.bat        # Windows launcher
├── src/                       # Source code
│   ├── main_recorder.py       # Main orchestration
│   ├── camera_control.py      # Camera acquisition & GPIO
│   ├── buffer_control.py      # Thread-safe circular buffer
│   ├── saving_worker.py       # Disk I/O worker
│   ├── render_worker.py       # Concurrent video encoding
│   └── processing_utils.py    # FFmpeg utilities
└── __pycache__/              # Python cache
```

## Troubleshooting

### Camera not detected
- Check camera connection (USB)
- Verify Spinnaker SDK is installed
- Test with SpinView application

### Buffer overruns
- Increase `BUFFER_MULTIPLIER` in `config.py`
- Use faster storage (SSD)
- Disable live preview with `--nolive`
- Reduce `JPEG_QUALITY` for faster saving

### Video rendering fails
- Check FFmpeg is installed and in PATH
- Verify disk has sufficient space
- Check console for error messages with `--debug`

### Console stays open after recording
- Press any key to close the window
- This is normal behavior to review messages

## Advanced Features

### Concurrent Rendering
By default, video chunks are rendered in parallel while recording continues. This provides:
- Real-time video encoding
- No waiting after recording stops
- Better CPU utilization

Disable with `--sequential` if you encounter stability issues.

### GPIO Strobe Control
- Strobe enabled during recording
- Line source configurable (default: Line 2)
- ExposureActive signal for hardware sync
- Timing logged to CSV file

## Output Files

### Video File
- Location: Parent of save_path folder
- Format: MP4 (H.264 codec)
- Naming: `VIDEO_YYYYMMDD-HHMMSS.mp4`

### Frame Files (if `--keep-frames`)
- Location: `save_path/VIDEO_YYYYMMDD-HHMMSS/`
- Format: JPEG images
- Naming: `frame_NNNNNN.jpg`

### Timing Data
- File: `VIDEO_YYYYMMDD-HHMMSS.csv`
- Contains: Frame timestamps and GPIO timing
