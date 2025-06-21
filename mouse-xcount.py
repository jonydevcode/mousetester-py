import os
import sys
import termios
import threading
import tty

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


def get_char():
    """
    Reads a single character from stdin without requiring Enter to be pressed.
    """
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return ch


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

    print("\nPress the SPACE bar to start measuring mouse movement in the x-direction.")
    while True:
        char = get_char()
        if char == ' ':
            print("Measurement started. Press the SPACE bar again to stop measuring.")
            break

    # Start tracking mouse events in a background thread.
    tracker.start_tracking()

    while True:
        char = get_char()
        if char == ' ':
            print("Measurement stopped.")
            break

    # Stop the tracking thread.
    tracker.stop_tracking()

    # Retrieve the total x-movement.
    total_x_movement = tracker.get_total_x_movement()
    print(f"\nTotal counts moved by the mouse in the x-direction: {total_x_movement}")
    sys.exit(0)


class MouseTracker:
    """
    A class to track mouse movement from a specific device in a separate
    thread and calculate the total net movement in the x-direction.
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

        # Total net movement in the x-direction.
        self._total_x_movement = 0

    def _event_loop(self):
        """
        The core loop that reads and processes mouse events. This method is
        intended to be run in a separate thread.
        """
        try:
            self._device.grab()
            print("Mouse device grabbed exclusively.")

            for event in self._device.read_loop():
                if not self._is_running:
                    break
                if event.type == ecodes.EV_REL:
                    if event.code == ecodes.REL_X:
                        with self._lock:
                            self._total_x_movement += event.value
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

    def get_total_x_movement(self):
        """
        Returns the total net movement in the x-direction.

        Returns:
            An integer representing the total x-movement in counts.
        """
        with self._lock:
            return self._total_x_movement


if __name__ == "__main__":
    main()
