import cv2
import numpy as np
import socket
import struct
import time
import os
from datetime import datetime
import sys
import select
import tty
import termios

PORT = 5000
CAM_W = 2560
CAM_H = 400
SAVE_DIR = "captures_raw"

correction_enabled = True  
if not os.path.exists(SAVE_DIR):
    os.makedirs(SAVE_DIR)

print("[*] HEADLESS MODE ACTIVE (No Display)")
print("[*] Controls: 'c' = Toggle Correction | 's' = Save PNG | 'v' = Start/Stop Video | 'q' = Quit")

def make_server():
    """Create and return a bound, listening server socket."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('0.0.0.0', PORT))
    server.listen(1)
    server.settimeout(1.0) 
    return server

def recvall(sock, n):
    data = bytearray()
    while len(data) < n:
        packet = sock.recv(n - len(data))
        if not packet:
            return None
        data.extend(packet)
    return data

img_counter = 0
quit_flag = False
video_recording = False
video_writer = None

# --- Terminal Setup for Headless Keystrokes ---
# Save the terminal's original state so we can restore it when the script exits
old_settings = termios.tcgetattr(sys.stdin)

try:
    # Set the terminal to read single characters without requiring the user to press 'Enter'
    tty.setcbreak(sys.stdin.fileno())

    while not quit_flag:
        server = make_server()
        print(f"\n[*] Waiting for Jetson Nano on port {PORT}...")

        conn = None
        while conn is None and not quit_flag:
            try:
                conn, addr = server.accept()
            except socket.timeout:
                # Check for 'q' while waiting for connection
                if select.select([sys.stdin], [], [], 0)[0]:
                    key = sys.stdin.read(1).lower()
                    if key == 'q':
                        quit_flag = True
                continue

        if quit_flag:
            break

        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        print(f"[+] Connected to Jetson at: {addr}")

        bytes_received = 0
        frames_received = 0
        timer = time.time()

        try:
            while True:
                raw_header = recvall(conn, 12)
                if raw_header is None:
                    print("\n[!] Connection lost. Waiting for reconnect...")
                    break

                timestamp, frame_size = struct.unpack('>dI', raw_header)

                raw_frame = recvall(conn, frame_size)
                if raw_frame is None:
                    print("\n[!] Connection lost mid-frame. Waiting for reconnect...")
                    break

                bytes_received += frame_size + 12
                frames_received += 1
                latency_ms = (time.time() - timestamp) * 1000

                frame = np.frombuffer(raw_frame, dtype=np.uint8).reshape(CAM_H, CAM_W, 3)

                if correction_enabled:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    scale = 0.125
                    small_gray = cv2.resize(gray, (0, 0), fx=scale, fy=scale)
                    blur = cv2.GaussianBlur(small_gray, (31, 31), 0)
                    illumination = cv2.resize(blur, (CAM_W, CAM_H))
                    illumination = np.clip(illumination, 1, 255).astype(np.float32)
                    illumination = np.expand_dims(illumination, axis=-1)
                    frame_float = frame.astype(np.float32)

                    target_brightness = 120.0
                    balanced_float = (frame_float / illumination) * target_brightness

                    frame = np.clip(balanced_float, 0, 255).astype(np.uint8)

                # --- Headless Keyboard Listener ---
                # Check if there is terminal input waiting
                if select.select([sys.stdin], [], [], 0)[0]:
                    key = sys.stdin.read(1).lower()
                    
                    if key == 'c':
                        correction_enabled = not correction_enabled
                        state = "ON" if correction_enabled else "OFF"
                        print(f"\n[!] Illumination Correction: {state}")

                    elif key == 's':
                        timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]
                        state_tag = "_corrected" if correction_enabled else "_raw"
                        filename = os.path.join(SAVE_DIR, f"cap_{img_counter}_{timestamp_str}{state_tag}.png")
                        cv2.imwrite(filename, frame, [cv2.IMWRITE_PNG_COMPRESSION, 0])
                        print(f"\n[!] SAVED UNCOMPRESSED: {filename}")
                        img_counter += 1

                    elif key == 'v':
                        if not video_recording:
                            # Start video recording
                            timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]
                            state_tag = "_corrected" if correction_enabled else "_raw"
                            video_filename = os.path.join(SAVE_DIR, f"video_cap_{timestamp_str}{state_tag}.mp4")
                            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                            video_writer = cv2.VideoWriter(video_filename, fourcc, 30.0, (CAM_W, CAM_H))
                            video_recording = True
                            print(f"\n[!] VIDEO RECORDING STARTED: {video_filename}")
                        else:
                            # Stop video recording
                            if video_writer:
                                video_writer.release()
                                video_writer = None
                            video_recording = False
                            print(f"\n[!] VIDEO RECORDING STOPPED")

                    elif key == 'q':
                        quit_flag = True
                        break

                if video_recording and video_writer:
                    video_writer.write(frame)

                now = time.time()
                if now - timer >= 1.0:
                    mb_per_sec = bytes_received / (1024 * 1024)
                    capture_time = datetime.fromtimestamp(timestamp)
                    # \033[K clears the terminal line so prints don't overlap messily
                    sys.stdout.write(f"\r\033[KFPS: {frames_received:3d} | "
                                     f"{mb_per_sec:6.1f} MB/s | "
                                     f"Latency: {latency_ms:5.1f}ms | "
                                     f"TS: {capture_time.strftime('%H:%M:%S.%f')[:-3]}")
                    sys.stdout.flush()
                    bytes_received = 0
                    frames_received = 0
                    timer = now

        except (ConnectionResetError, BrokenPipeError, OSError) as e:
            print(f"\n[!] Socket error: {e}. Waiting for reconnect...")
            if video_writer:
                video_writer.release()
                video_writer = None
            video_recording = False

        finally:
            if video_writer:
                video_writer.release()
                video_writer = None
            video_recording = False
            if conn:
                conn.close()
            if server:
                server.close()

except KeyboardInterrupt:
    print("\n[!] Stopped by User (Ctrl+C).")

finally:
    # Restoring terminal settings is critical so your SSH terminal doesn't act weird afterward
    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
    if video_writer:
        video_writer.release()