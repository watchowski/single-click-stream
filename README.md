# 🔴 Single Click Stream

**One click to go live on YouTube with your screen and system audio — plus a local control panel to manage every stream.**

Single Click Stream is a lightweight Windows desktop tool I built to remove all the friction from screen sharing on YouTube. No OBS scenes, no stream keys to copy, no YouTube Studio tabs: click one desktop icon and a few seconds later you are live, with the share link already in your clipboard.

> Personal portfolio project · Python · YouTube Live Streaming API · FFmpeg · WASAPI

---

## ✨ Features

| | |
|---|---|
| 🖱️ **Single-click go-live** | One shortcut creates the broadcast, starts the capture and copies the link. |
| 🖥️ **Screen + system audio** | Captures the desktop (DXGI Desktop Duplication) and whatever your speakers play (WASAPI loopback) — no virtual audio drivers needed. |
| 🔗 **Instant share link** | `https://youtu.be/<id>` is copied to the clipboard and shown in the panel. |
| ✏️ **Live editing** | Rename the stream and switch **Public / Unlisted / Private** while you are live. |
| 🗂️ **Stream manager** | List, rename, change privacy, open or delete all your past and current broadcasts from one page. |
| 🔁 **Self-healing** | Watchdog restarts the encoder after network drops and forces the broadcast live if YouTube's auto-start does not trigger. |
| 🔒 **Local-only & safe** | Control panel binds to `127.0.0.1`, rejects foreign Host headers and requires a custom header on every action (blocks CSRF / DNS-rebinding). OAuth tokens never leave your machine. |

## 🧱 How it works

```
 Desktop shortcut ──► streamer.py (single instance, local HTTP server :8765)
                         │
        ┌────────────────┼──────────────────────────┐
        ▼                ▼                          ▼
 YouTube Data API   LoopbackAudio (WASAPI)     Control panel (panel.html)
  liveStreams.insert    │ PCM, silence-padded       status / edit / delete
  liveBroadcasts.insert ▼ by wall clock
  liveBroadcasts.bind  FFmpeg  ◄── ddagrab (GPU screen capture, gdigrab fallback)
        │               │  H.264 + AAC
        └──── RTMP ◄────┘
```

1. **Create** – a `liveStream` (RTMP ingest) and a `liveBroadcast` with `enableAutoStart`/`enableAutoStop` are created and bound.
2. **Capture** – FFmpeg grabs the screen with `ddagrab`; system audio is read from the default speakers' WASAPI loopback device and piped into FFmpeg.
3. **Go live** – YouTube auto-starts when the ingest becomes active; a monitor thread polls the lifecycle and handles failures.
4. **Manage** – the browser panel talks to the local server to update title/privacy, stop, or delete (falls back to the `videos` endpoint for completed broadcasts).

### Interesting problems solved

- **Silent loopback gaps** – Windows delivers *no* audio packets while nothing is playing, which stalls FFmpeg and desyncs the stream. The audio writer paces output by wall clock, pads silence when the device is idle and drops excess when the device clock drifts ahead.
- **High-DPI screens** – `gdigrab` captures only part of a scaled display; using `ddagrab` (Desktop Duplication API) captures the true resolution with GPU efficiency, with automatic fallback.
- **Multichannel devices** – 7.1 sound cards are captured natively and downmixed to stereo for YouTube.

## 🚀 Getting started

**Requirements:** Windows 10/11, Python 3.10+, FFmpeg 6.1+ (`winget install Gyan.FFmpeg`), a YouTube channel with live streaming enabled.

```powershell
git clone https://github.com/watchowski/single-click-stream.git
cd single-click-stream
pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File create_shortcuts.ps1
```

Then create your own Google OAuth *Desktop* client and save it as `client_secret.json` in the project folder — full step-by-step guide in **[SETUP.md](SETUP.md)**.

Test the capture pipeline without YouTube:

```powershell
python streamer.py --test-capture test.mp4
```

## ⚙️ Configuration

`settings.json` is created on first run:

| Key | Default | Description |
|---|---|---|
| `default_title` | `Live screen share {date}` | Title for one-click streams (`{date}` is replaced) |
| `default_privacy` | `unlisted` | `public`, `unlisted` or `private` |
| `monitor` | `0` | Display index to capture |
| `framerate` / `max_height` | `30` / `1080` | Output video format |
| `video_bitrate_kbps` | `4500` | Video bitrate |
| `encoder` | `libx264` | e.g. `h264_nvenc` for NVIDIA GPUs |
| `capture_audio` | `true` | Send system audio or silence |

## 🔐 Security notes

- `client_secret.json`, `token.json`, `settings.json` and `logs/` are git-ignored — bring your own Google credentials.
- The RTMP stream key is never written to the logs.
- Required scope: `https://www.googleapis.com/auth/youtube` (manage your own broadcasts).

## 📁 Project structure

```
streamer.py            app: YouTube API client, capture pipeline, local web server
panel.html             control panel UI (vanilla HTML/CSS/JS, no build step)
create_shortcuts.ps1   creates the desktop shortcuts
SETUP.md               Google Cloud + YouTube setup guide
docs/                  public home page & privacy policy (GitHub Pages, used by the OAuth consent screen)
```

## 🛠️ Tech stack

Python (stdlib `http.server`, threading) · Google API Python Client · OAuth 2.0 · FFmpeg (ddagrab, libx264, AAC, FLV/RTMP) · PyAudioWPatch (WASAPI loopback) · Vanilla JS

## 📄 License

[MIT](LICENSE)
