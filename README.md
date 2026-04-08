# camera_stream

Raw video streaming for the **Arducam 1200° wide-angle camera** (5120×800) running on a **Jetson Nano B01**, streamed over a direct Ethernet cable to a receiver.

---

## Overview

The system has two scripts:

| Script | Runs on | Role |
|---|---|---|
| `stream_raw.py` | Sender | Captures, processes, and sends frames |
| `receive_raw.py` | Receiver | Receives, displays, and optionally saves frames |

Frames are sent as raw BGR pixel data over a TCP socket — no video encoding. 

---

## Hardware Setup

- Arducam wide-angle camera CamArray HAT connected to the Jetson Nano via CSI
- Sender and Receiver connected **directly** via an Ethernet cable (no router/switch needed)
---

## Network Configuration

The streamer connects **outbound** to a fixed IP. Set a static IP on the receiver to match.

**Receiver PC static IP (required):**

| Field | Value |
|---|---|
| IP Address | `192.168.1.100` |
| Subnet Mask | `255.255.255.0` |

**Windows:** Settings → Network & Internet → Ethernet → Edit IP assignment → Manual

**Linux:**
```bash
sudo ip addr add 192.168.1.100/24 dev eth0
sudo ip link set eth0 up
```

The Sender does not need a specific IP — only the receiver does.

---

## Installation

### Sender

```bash
pip3 install opencv-python numpy
```

The `ArducamUtils` dependency comes from Arducam's SDK. Follow their setup guide for your specific camera module and ensure `utils.py` is in the same directory as `streamer.py`.

### Receiver

```bash
pip install opencv-python numpy
```

---

## Usage

Can be launched in any order. Both sides will wait and automatically reconnect if the connection drops.

### 1. Start the receiver

```bash
python3 receive_raw.py
```

The receiver will listen on port `5000` and wait for the Sender to connect.

### 2. Start the streamer

```bash
python3 stream_raw.py
```

The streamer will wait for a frame from the camera, then connect to the receiver and begin sending.

### Receiver controls (while stream window is open)

| Key | Action |
|---|---|
| `s` | Save current frame as uncompressed PNG to `captures_raw/` |
| `q` | Quit |

---

## Wire Protocol

Each frame is sent as a binary packet:

```
Bytes 0–7   : Capture timestamp  (float64, big-endian)
Bytes 8–11  : Frame data size    (uint32, big-endian)
Bytes 12+   : Raw BGR pixel data (uint8, row-major)
```

Frame resolution after downscale: **2560 × 400 px**, 3 channels = **3,072,000 bytes per frame**.

---

## Configuration

All tuneable constants are at the top of each script.

**`streamer.py`**

| Constant | Default | Description |
|---|---|---|
| `HOST` | `192.168.1.100` | Receiver PC IP address |
| `PORT` | `5000` | TCP port |
| `TARGET_FPS` | `30` | Sending rate cap |

**`receiver.py`**

| Constant | Default | Description |
|---|---|---|
| `PORT` | `5000` | TCP port to listen on |
| `CAM_W` | `2560` | Expected frame width |
| `CAM_H` | `400` | Expected frame height |
| `SAVE_DIR` | `captures_raw` | Directory for saved PNGs |

---

## Reconnection Behaviour

Both sides handle disconnects without needing a restart:

- **Streamer:** If the connection is refused or drops mid-stream, it closes the socket and retries every 2 seconds until the receiver is available again.
- **Receiver:** If the Sender disconnects, it closes the connection and immediately starts listening for a new one. The display window stays open while waiting.

The camera capture thread on the Jetson runs independently and is never interrupted by network events.

---

## Image Processing (streamer-side)

Before sending, each frame is processed on the Jetson Nano:

1. Captured at native **5120 × 800**
2. Converted from raw sensor format to BGR via `ArducamUtils`
3. Brightness/contrast boost — `alpha=1.3`, `beta=30`
4. Per-channel colour correction:
   - Blue ×1.2
   - Green ×0.95
   - Red ×0.90
5. Downscaled to **2560 × 400** via `cv2.resize`

---

## Troubleshooting

**Streamer says "Receiver not ready, retrying..." indefinitely**
- Check the static IP is set correctly on the Receiver (`192.168.1.100`)
- Make sure `receiver.py` is running before or shortly after `streamer.py`
- Check no firewall is blocking port `5000` on the PC

**Receiver shows no window / black frame**
- Confirm `CAM_W` and `CAM_H` in `receiver.py` match the resolution being sent by the streamer (default: 2560×400)
- mismatch will cause `reshape()` to throw an error

**High latency**
- Use `ethtool` to confirm the link is running at 1 Gbps: `ethtool eth0 | grep Speed`

**Camera not found on Jetson**
- Verify the camera is detected: `ls /dev/video*`
- Check Arducam driver is installed and `utils.py` is present
- Check Cable connection (Usually the issue)
