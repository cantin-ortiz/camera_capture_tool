# config.py

# --- GLOBAL SETTINGS ---

# Duration (in seconds) that defines the size of each video chunk.
# E.g., at 50Hz, 10s = 500 frames per chunk.
CHUNK_DURATION_S = 10

# Buffer size multiplier for the circular buffer.
# Buffer size = BUFFER_MULTIPLIER × framerate × CHUNK_DURATION_S
# E.g., at 50Hz with multiplier 2.0: buffer holds 1000 frames
# Increase if disk is slow (e.g., 3.0 or 4.0), decrease if RAM is limited (e.g., 1.5)
BUFFER_MULTIPLIER = 2.0