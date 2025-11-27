# buffer_control.py

import threading
import numpy as np
# Import the CircularBuffer class for type hints, but we don't use a global instance here.

class CircularBuffer:
    """
    A thread-safe circular buffer for storing NumPy image arrays.
    """
    def __init__(self, size):
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
            
            # Use np.copy() to ensure the data is not referenced by the camera/SpinView later
            self.buffer[self.write_index] = (self.total_frames_written, np.copy(np_image))
            frame_index = self.total_frames_written
            
            self.write_index = (self.write_index + 1) % self.size
            self.total_frames_written += 1
            
            # Notify the consumer (Saving Worker) that new data is available
            self.condition.notify_all()
            return frame_index

    def get(self):
        """
        Retrieves a frame from the buffer. Waits if the buffer is empty.
        Returns (frame_index, numpy_array) or (None, None) if stopping and empty.
        """
        # LOCAL IMPORT for clean exit check: This avoids circular dependency with saving_worker.py
        from saving_worker import stop_saving_worker 
        
        with self.condition:
            # Wait while the buffer is empty
            while self.buffer[self.read_index] is None:
                
                # Check for clean exit: if stop is set AND buffer is empty, break out
                if stop_saving_worker.is_set() and self.read_index == self.write_index:
                    return None, None 
                
                self.condition.wait(timeout=0.5) # Wait for producer to add data
                
                # Check again after waking up
                if self.buffer[self.read_index] is None and stop_saving_worker.is_set():
                    return None, None 

            # Retrieve data and clear slot
            frame_index, np_image = self.buffer[self.read_index]
            self.buffer[self.read_index] = None
            
            self.read_index = (self.read_index + 1) % self.size
            
            # Notify the producer (Acquisition Thread) that space has been cleared
            self.condition.notify_all()
            return frame_index, np_image