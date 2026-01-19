# buffer_control.py

import threading
import numpy as np
# Import the CircularBuffer class for type hints, but we don't use a global instance here.

class CircularBuffer:
    """
    A thread-safe circular buffer for storing NumPy image arrays.
    """
    def __init__(self, size, stop_event=None):
        self.size = size
        # List of lists to store (frame_index, numpy_array) tuples
        self.buffer = [None] * size 
        # Index where the next frame will be written (producer)
        self.write_index = 0
        # Index where the next frame will be read (consumer)
        self.read_index = 0
        # Condition variable for thread synchronization
        self.condition = threading.Condition()
        # Total number of frames successfully written (for indexing)
        self.total_frames_written = 0
        # Stop event for clean shutdown
        self.stop_event = stop_event

    def put(self, np_image):
        """
        Adds a frame to the buffer. Waits if the buffer is full.
        Returns the unique index of the frame written.
        """
        with self.condition:
            # Wait while the buffer is full (read_index is right behind write_index)
            while self.write_index == self.read_index and self.buffer[self.write_index] is not None:
                print(f"\n[BUFFER WARNING] Buffer full! Acquisition thread must wait for Saving Worker to catch up.")
                self.condition.wait()
            
            # Store the frame directly (no copy needed - acquisition thread already copied)
            self.buffer[self.write_index] = (self.total_frames_written, np_image)
            frame_index = self.total_frames_written
            
            self.write_index = (self.write_index + 1) % self.size
            self.total_frames_written += 1
            
            # Notify the consumer (Saving Worker) that new data is available
            self.condition.notify()
            return frame_index

    def get(self):
        """
        Retrieves a frame from the buffer. Waits if the buffer is empty.
        Returns (frame_index, numpy_array) or (None, None) if stopping and empty.
        """
        with self.condition:
            # Wait while the buffer is empty
            while self.buffer[self.read_index] is None:
                
                # Check for clean exit: if stop is set AND buffer is empty, break out
                if self.stop_event and self.stop_event.is_set() and self.read_index == self.write_index:
                    print(f"\n[BUFFER] Returning None - stop set and buffer empty")
                    return None, None 
                
                self.condition.wait(timeout=0.5) # Wait for producer to add data
                
                # Check again after waking up
                if self.buffer[self.read_index] is None and self.stop_event and self.stop_event.is_set():
                    print(f"\n[BUFFER] Returning None after wakeup - buffer empty and stop set")
                    return None, None 

            # Retrieve data and clear slot
            frame_index, np_image = self.buffer[self.read_index]
            self.buffer[self.read_index] = None
            
            self.read_index = (self.read_index + 1) % self.size
            
            # Notify the producer (Acquisition Thread) that space has been cleared
            self.condition.notify()
            return frame_index, np_image