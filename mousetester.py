# main.py

import os
import sys
import threading
import time

import matplotlib.pyplot as plt
from evdev import InputDevice, ecodes


def find_all_mice():
    """
    Scans /dev/input/ for all devices with mouse-like capabilities.

    Returns:
        A list of tuples, where each tuple contains the device path and name.
        Example: [('/dev/input/event4', 'Logitech G Pro'), ...]
    """
    mice = []
    try:
        device_paths = [os.path.join('/dev/input', fn) for fn in os.listdir('/dev/input') if fn.startswith('event')]
    except FileNotFoundError:
        print("The /dev/input directory was not found.", file=sys.stderr)
        return []

    for path in device_paths:
        try:
            device = InputDevice(path)
            capabilities = device.capabilities(verbose=False)
            # A device is considered a mouse if it has relative X and Y axes.
            if ecodes.EV_REL in capabilities and \
               ecodes.REL_X in capabilities.get(ecodes.EV_REL, []) and \
               ecodes.REL_Y in capabilities.get(ecodes.EV_REL, []):
                mice.append((path, device.name))
        except (IOError, OSError):
            # This can happen if we don't have permissions or the device is busy.
            continue
    return mice


def select_mouse_device(devices):
    """
    Prompts the user to select a mouse from a list of available devices.

    Args:
        devices: A list of (path, name) tuples for detected mice.

    Returns:
        The path of the selected device as a string, or None if selection fails.
    """
    print("Available mouse devices:")
    for i, (path, name) in enumerate(devices):
        print(f"  {i + 1}: {name} ({path})")

    while True:
        try:
            choice_str = input("Please select a mouse by number: ")
            choice_num = int(choice_str)
            if 1 <= choice_num <= len(devices):
                return devices[choice_num - 1][0]
            else:
                print(f"Invalid number. Please enter a number between 1 and {len(devices)}.")
        except ValueError:
            print("That is not a valid number. Please try again.")


def main():
    """
    Main function to run the mouse tracking application.
    """
    # Reading from /dev/input requires root privileges on most systems.
    if os.geteuid() != 0:
        print("This script requires root privileges to access raw mouse events.")
        print("Please run with 'sudo python3 main.py'")
        sys.exit(1)

    # Find and select the mouse device.
    available_mice = find_all_mice()
    if not available_mice:
        print("No mouse devices could be found. Exiting.")
        sys.exit(1)

    selected_device_path = select_mouse_device(available_mice)

    try:
        tracker = MouseTracker(device_path=selected_device_path)
    except Exception as e:
        print(f"Failed to initialise tracker: {e}")
        sys.exit(1)

    # Begin a 3-second countdown on the console.
    print("\nPrepare to track mouse movement. Starting in...")
    for i in range(3, 0, -1):
        print(f"{i}...")
        time.sleep(1)
    print("Start tracking!")

    # Start tracking mouse events in a background thread.
    tracker.start_tracking()

    # Allow tracking for a duration of 5 seconds.
    tracking_duration = 3
    time.sleep(tracking_duration)

    # Stop the tracking thread.
    tracker.stop_tracking()

    # Retrieve the collected data and generate a plot.
    path = tracker.get_path()
    plot_mouse_path(path)


class MouseTracker:
    """
    A class to track mouse movement from a specific device in a separate
    thread and store the path coordinates with high-precision timestamps.
    """

    def __init__(self, device_path):
        """
        Initialises the mouse tracker with a specific device path.

        Args:
            device_path (str): The path to the input device, e.g., '/dev/input/event4'.
        """
        self._device = InputDevice(device_path)
        print(f"Using mouse: {self._device.name} at {self._device.path}")

        self._tracking_thread = None
        self._is_running = False
        self._lock = threading.Lock()

        # Path data is stored as a list of tuples: (timestamp, x, y)
        self.path_data = []
        self._current_x = 0
        self._current_y = 0

    def _event_loop(self):
        """
        The core loop that reads and processes mouse events. This method is
        intended to be run in a separate thread.
        """
        try:
            self._device.grab()
            print("Mouse device grabbed exclusively. Tracking has begun.")

            start_time = time.monotonic()
            with self._lock:
                self.path_data.append((start_time, self._current_x, self._current_y))

            for event in self._device.read_loop():
                if not self._is_running:
                    break
                if event.type == ecodes.EV_REL:
                    if event.code == ecodes.REL_X:
                        self._current_x += event.value
                    elif event.code == ecodes.REL_Y:
                        self._current_y += -event.value

                    event_time = event.timestamp()
                    with self._lock:
                        self.path_data.append((event_time, self._current_x, self._current_y))
        except Exception as e:
            print(f"An error occurred in the event loop: {e}", file=sys.stderr)
        finally:
            self._device.ungrab()
            print("Mouse device released.")

    def start_tracking(self):
        """Starts the mouse tracking thread."""
        if self._tracking_thread is not None:
            print("Tracking is already in progress.")
            return

        self._is_running = True
        self._tracking_thread = threading.Thread(target=self._event_loop, daemon=True)
        self._tracking_thread.start()

    def stop_tracking(self):
        """Stops the mouse tracking thread gracefully."""
        if self._tracking_thread and self._is_running:
            self._is_running = False
            self._tracking_thread.join(timeout=1.0)
            self._tracking_thread = None
            print("Tracking stopped.")

    def get_path(self):
        """
        Returns a thread-safe copy of the recorded path data.

        Returns:
            A list of (timestamp, x, y) tuples.
        """
        with self._lock:
            return list(self.path_data)


def plot_mouse_path(path_data):
    """
    Generates and displays a scatter plot of raw mouse movement over time.
    Horizontal and vertical movements are plotted as separate series.

    Args:
        path_data: A list of (timestamp, x, y) tuples representing the
                   cumulative mouse path.
    """
    if not path_data or len(path_data) < 2:
        print("Not enough data points were recorded to generate a plot.")
        return

    timestamps, x_coords, y_coords = zip(*path_data)
    start_time = timestamps[0]
    relative_times_ms = [(t - start_time) * 1000 for t in timestamps]

    delta_x = [x_coords[i] - x_coords[i-1] for i in range(1, len(x_coords))]
    delta_y = [y_coords[i] - y_coords[i-1] for i in range(1, len(y_coords))]
    plot_times = relative_times_ms[1:]

    if not plot_times:
        print("No movement was detected to plot.")
        return

    plt.figure(figsize=(12, 6), tight_layout=True)
    plt.scatter(plot_times, delta_x, s=2, color='blue', label='Horizontal Movement (X)')
    plt.scatter(plot_times, delta_y, s=2, color='red', label='Vertical Movement (Y)')

    plt.title('Raw Mouse Movement Over Time')
    plt.xlabel('Time (milliseconds)')
    plt.ylabel('Raw Movement Delta (counts)')
    plt.legend()
    plt.grid(True, which='both', linestyle='--', linewidth=0.5)
    plt.axhline(0, color='black', linewidth=0.75)

    print("Displaying plot. Close the plot window to exit the program.")
    plt.show()


if __name__ == "__main__":
    main()
