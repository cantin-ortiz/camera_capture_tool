# config.py

# --- GLOBAL SETTINGS ---

# Virtual environment path (relative to project root)
# Change this if you use a different virtual environment name or location
# Set to None to use system Python instead of a virtual environment
VENV_PATH = "../env_camera"
#VENV_PATH = None

# Default recording framerate (Hz)
# This should match the framerate configured in SpinView
DEFAULT_FRAMERATE = 50

# Default GPIO line for strobe output (1 or 2)
DEFAULT_LINE = 2

# Duration (in seconds) that defines the size of each video chunk.
# E.g., at 50Hz, 10s = 500 frames per chunk.
CHUNK_DURATION_S = 10

# Buffer size multiplier for the circular buffer.
# Buffer size = BUFFER_MULTIPLIER × framerate × CHUNK_DURATION_S
# E.g., at 50Hz with multiplier 2.0: buffer holds 1000 frames
# Increase if disk is slow (e.g., 3.0 or 4.0), decrease if RAM is limited (e.g., 1.5)
BUFFER_MULTIPLIER = 2.0

# JPEG compression quality for saved frames (0-100)
# Higher = better quality but slower saving and larger files
# 95 = default OpenCV quality (highest)
# 85 = recommended for performance (30-40% faster, visually identical)
# 75 = good balance for high-speed capture
# Lower values may introduce visible artifacts
JPEG_QUALITY = 85