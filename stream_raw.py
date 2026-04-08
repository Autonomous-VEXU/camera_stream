import cv2
import numpy as np
import socket
import struct
import time
import threading
from utils import ArducamUtils

HOST = '192.168.1.100'
PORT = 5000
TARGET_FPS = 30

# Camera capture thread
latest_frame = None
frame_lock = threading.Lock()
capture_running = True


def capture_thread():
    global latest_frame, capture_running

    cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
    arducam_utils = ArducamUtils(0)

    if arducam_utils.convert2rgb == 0:
        cap.set(cv2.CAP_PROP_CONVERT_RGB, arducam_utils.convert2rgb)

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 5120)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 800)

    while capture_running:
        ret, frame = cap.read()
        if not ret:
            continue

        timestamp = time.time()

        if arducam_utils.convert2rgb == 0:
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            frame = frame.reshape(h, w)

        frame = arducam_utils.convert(frame)

        frame = cv2.convertScaleAbs(frame, alpha=1.3, beta=30)

        frame[:, :, 0] = np.clip(frame[:, :, 0] * 1.2, 0, 255)
        frame[:, :, 1] = np.clip(frame[:, :, 1] * 0.95, 0, 255)
        frame[:, :, 2] = np.clip(frame[:, :, 2] * 0.90, 0, 255)
        frame = frame.astype(np.uint8)

        frame = cv2.resize(frame, (2560, 400))

        with frame_lock:
            latest_frame = (frame, timestamp)

    cap.release()


def connect_socket():
    """Create and return a connected socket, retrying until successful."""
    while True:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.connect((HOST, PORT))
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            print(f"\nConnected to {HOST}:{PORT}")
            return sock
        except (ConnectionRefusedError, OSError) as e:
            print(f"Receiver not ready, retrying in 2s... ({e})", end='\r')
            sock.close()
            time.sleep(2)


# Start capture thread
t = threading.Thread(target=capture_thread, daemon=True)
t.start()

print("Waiting for first frame...")
while True:
    with frame_lock:
        if latest_frame is not None:
            break
    time.sleep(0.01)

print(f"Trying to connect to {HOST}:{PORT}...")
sock = connect_socket()

# Send loop at fixed 30fps
frame_time = 1.0 / TARGET_FPS
fps_counter = 0
fps_timer = time.time()

try:
    while True:
        loop_start = time.time()

        with frame_lock:
            if latest_frame is None:
                continue
            frame, timestamp = latest_frame

        try:
            data = frame.tobytes()
            frame_size = len(data)
            header = struct.pack('>dI', timestamp, frame_size)
            sock.sendall(header + data)
        except (BrokenPipeError, ConnectionResetError, OSError) as e:
            print(f"\nConnection lost: {e}. Reconnecting...")
            sock.close()
            sock = connect_socket()
            continue

        fps_counter += 1
        if time.time() - fps_timer >= 1.0:
            print(f"Sending FPS: {fps_counter}", end='\r')
            fps_counter = 0
            fps_timer = time.time()

        elapsed = time.time() - loop_start
        sleep_time = frame_time - elapsed
        if sleep_time > 0:
            time.sleep(sleep_time)

except KeyboardInterrupt:
    print("\nStopping...")
finally:
    capture_running = False
    sock.close()