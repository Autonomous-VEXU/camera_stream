import cv2
import numpy as np
import socket
import struct
import time
import os
from datetime import datetime

PORT = 5000
CAM_W = 2560
CAM_H = 400
SAVE_DIR = "captures_raw"

#Byte 0-7:   timestamp (float64, big-endian double) = [0x41, 0xD8, 0x4D, 0x63, 0x2A, 0x1F, 0x5C, 0x29]
#Byte 8-11:  frame size (uint32, big-endian) = [0x00, 0x2E, 0xE0, 0x00]
#Byte 12+:   raw BGR pixel data = [ B, G, R, B, G, R, B, G, R, ...]

if not os.path.exists(SAVE_DIR):
    os.makedirs(SAVE_DIR)

print(f"[*] Controls: 's' = Save Uncompressed PNG | 'q' = Quit")


def make_server():
    """Create and return a bound, listening server socket."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('0.0.0.0', PORT))
    server.listen(1)
    server.settimeout(1.0)  # Allow KeyboardInterrupt to be caught while waiting
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

try:
    while not quit_flag:
        server = make_server()
        print(f"[*] Waiting for Jetson Nano on port {PORT}...")

        conn = None
        while conn is None and not quit_flag:
            try:
                conn, addr = server.accept()
            except socket.timeout:
                # Check for 'q' keypress while waiting for connection
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
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

                cv2.imshow('Jetson Raw Stream', frame)

                key = cv2.waitKey(1) & 0xFF

                if key == ord('s'):
                    timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]
                    filename = os.path.join(SAVE_DIR, f"raw_cap_{img_counter}_{timestamp_str}.png")
                    cv2.imwrite(filename, frame, [cv2.IMWRITE_PNG_COMPRESSION, 0])
                    print(f"\n[!] SAVED UNCOMPRESSED: {filename}")
                    img_counter += 1

                elif key == ord('q'):
                    quit_flag = True
                    break

                now = time.time()
                if now - timer >= 1.0:
                    mb_per_sec = bytes_received / (1024 * 1024)
                    capture_time = datetime.fromtimestamp(timestamp)
                    print(f"FPS: {frames_received:3d} | "
                          f"{mb_per_sec:6.1f} MB/s | "
                          f"Latency: {latency_ms:5.1f}ms | "
                          f"TS: {capture_time.strftime('%H:%M:%S.%f')[:-3]}", end='\r')
                    bytes_received = 0
                    frames_received = 0
                    timer = now

        except (ConnectionResetError, BrokenPipeError, OSError) as e:
            print(f"\n[!] Socket error: {e}. Waiting for reconnect...")

        finally:
            conn.close()
            server.close()

except KeyboardInterrupt:
    print("\n[!] Stopped.")

finally:
    cv2.destroyAllWindows()