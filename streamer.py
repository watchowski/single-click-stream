"""
Single Click Stream - share your screen (with sound) live on YouTube.

  pythonw streamer.py            start a new live stream and open the control panel
  pythonw streamer.py --panel    open the control panel only
  python  streamer.py --test-capture test.mp4   record 8 s of screen+sound to a file (no YouTube)
"""
import datetime
import glob
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PORT = 8765
HOST = "127.0.0.1"
PANEL_URL = f"http://{HOST}:{PORT}/"
CLIENT_SECRET = os.path.join(APP_DIR, "client_secret.json")
TOKEN_FILE = os.path.join(APP_DIR, "token.json")
SETTINGS_FILE = os.path.join(APP_DIR, "settings.json")
LOG_DIR = os.path.join(APP_DIR, "logs")
SCOPES = ["https://www.googleapis.com/auth/youtube"]
NO_WINDOW = 0x08000000 if os.name == "nt" else 0
PRIVACY_VALUES = ("public", "unlisted", "private")

DEFAULT_SETTINGS = {
    "default_title": "Live screen share {date}",
    "default_privacy": "unlisted",
    "framerate": 30,
    "max_height": 1080,
    "video_bitrate_kbps": 4500,
    "audio_bitrate_kbps": 160,
    "encoder": "libx264",
    "capture": "ddagrab",
    "monitor": 0,
    "capture_audio": True,
    "copy_link_on_start": True,
    "open_panel_on_start": True,
}

os.makedirs(LOG_DIR, exist_ok=True)
_log_lock = threading.Lock()


def log(*parts):
    line = f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} " + " ".join(str(p) for p in parts)
    with _log_lock:
        with open(os.path.join(LOG_DIR, "app.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    if sys.stdout:
        try:
            print(line, flush=True)
        except Exception:
            pass


def load_settings():
    s = dict(DEFAULT_SETTINGS)
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                s.update(json.load(f))
        except Exception as e:
            log("settings.json is not valid JSON, using defaults:", e)
    else:
        save_settings(s)
    return s


def save_settings(s):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)


def find_ffmpeg():
    p = shutil.which("ffmpeg")
    if p:
        return p
    pattern = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Packages",
                           "Gyan.FFmpeg*", "*", "bin", "ffmpeg.exe")
    hits = sorted(glob.glob(pattern))
    if hits:
        return hits[-1]
    local = os.path.join(APP_DIR, "ffmpeg.exe")
    if os.path.exists(local):
        return local
    raise RuntimeError("ffmpeg was not found. Install it: winget install Gyan.FFmpeg")


def copy_to_clipboard(text):
    try:
        subprocess.run(["clip"], input=text.encode("utf-16-le"), creationflags=NO_WINDOW, check=False)
    except Exception as e:
        log("clipboard failed:", e)


# --------------------------------------------------------------------------- audio
class LoopbackAudio:
    """Captures what the speakers play (WASAPI loopback) and feeds a steady PCM stream.
    Windows sends no data while nothing plays, so silence is filled in by wall clock."""

    LATENCY = 0.15  # seconds of buffer kept behind real time

    def __init__(self):
        import pyaudiowpatch as pyaudio
        self.pa_mod = pyaudio
        self.pa = pyaudio.PyAudio()
        wasapi = self.pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        out = self.pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
        dev = out if out.get("isLoopbackDevice") else None
        if dev is None:
            for lb in self.pa.get_loopback_device_info_generator():
                if out["name"] in lb["name"]:
                    dev = lb
                    break
        if dev is None:
            raise RuntimeError("No loopback device for the default speakers was found.")
        self.dev = dev
        self.rate = int(dev["defaultSampleRate"])
        self.channels = int(dev["maxInputChannels"]) or 2
        self.bpf = self.channels * 2
        self.buf = bytearray()
        self.lock = threading.Lock()
        self.last_data = 0.0
        self.stop_flag = threading.Event()
        self.stream = None
        self.thread = None
        log(f"audio device: {dev['name']} rate={self.rate} ch={self.channels}")

    def _callback(self, data, frames, info, status):
        with self.lock:
            self.buf.extend(data)
            self.last_data = time.monotonic()
        return (None, self.pa_mod.paContinue)

    def start(self, sink):
        self.stream = self.pa.open(format=self.pa_mod.paInt16, channels=self.channels, rate=self.rate,
                                   input=True, input_device_index=self.dev["index"],
                                   frames_per_buffer=1024, stream_callback=self._callback)
        self.thread = threading.Thread(target=self._writer, args=(sink,), daemon=True)
        self.thread.start()

    def _writer(self, sink):
        start = time.monotonic()
        written = 0
        max_buf = int(self.rate * 0.5)
        try:
            while not self.stop_flag.is_set():
                time.sleep(0.01)
                now = time.monotonic()
                target = int((now - start - self.LATENCY) * self.rate)
                need = target - written
                if need <= 0:
                    continue
                with self.lock:
                    avail = len(self.buf) // self.bpf
                    if avail > need + max_buf:  # device clock ran ahead: drop the oldest audio
                        drop = avail - need
                        del self.buf[: drop * self.bpf]
                        avail -= drop
                    take = min(avail, need)
                    chunk = bytes(self.buf[: take * self.bpf])
                    del self.buf[: take * self.bpf]
                    idle = (now - self.last_data) > 0.1
                if take < need and idle:
                    chunk += b"\x00" * ((need - take) * self.bpf)
                    take = need
                if chunk:
                    sink.write(chunk)
                    sink.flush()
                    written += take
        except (BrokenPipeError, OSError, ValueError):
            pass

    def stop(self):
        self.stop_flag.set()
        try:
            if self.stream:
                self.stream.stop_stream()
                self.stream.close()
        except Exception:
            pass
        try:
            self.pa.terminate()
        except Exception:
            pass


# --------------------------------------------------------------------------- capture
class Capture:
    def __init__(self, target, settings, duration=None):
        self.target = target
        self.s = settings
        self.duration = duration
        self.proc = None
        self.audio = None
        self.logfile = None
        self.started = 0.0

    def _cmd(self, capture_mode):
        s = self.s
        fps = int(s["framerate"])
        br = int(s["video_bitrate_kbps"])
        cmd = [find_ffmpeg(), "-hide_banner", "-loglevel", "warning", "-y"]
        if capture_mode == "ddagrab":
            cmd += ["-f", "lavfi", "-i", f"ddagrab=output_idx={int(s['monitor'])}:framerate={fps}:draw_mouse=1"]
            vf = "hwdownload,format=bgra,"
        else:
            cmd += ["-f", "gdigrab", "-framerate", str(fps),
                    "-draw_mouse", "1", "-i", "desktop"]
            vf = ""
        if self.audio:
            cmd += ["-f", "s16le", "-ar", str(self.audio.rate),
                    "-ac", str(self.audio.channels), "-i", "pipe:0"]
        else:
            cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        vf += f"scale=-2:'min({int(s['max_height'])},ih)':flags=bicubic,format=yuv420p"
        cmd += ["-map", "0:v", "-map", "1:a", "-vf", vf]
        enc = s.get("encoder", "libx264")
        if enc == "libx264":
            cmd += ["-c:v", "libx264", "-preset", "veryfast"]
        else:
            cmd += ["-c:v", enc]
        cmd += ["-b:v", f"{br}k", "-maxrate", f"{br}k", "-bufsize", f"{br * 2}k",
                "-g", str(fps * 2), "-keyint_min", str(fps * 2), "-r", str(fps),
                "-c:a", "aac", "-b:a", f"{int(s['audio_bitrate_kbps'])}k", "-ar", "48000", "-ac", "2"]
        if self.duration:
            cmd += ["-t", str(self.duration)]
        if self.target.startswith("rtmp"):
            cmd += ["-f", "flv", self.target]
        else:
            cmd += [self.target]
        return cmd

    def start(self):
        modes = [self.s.get("capture", "ddagrab")]
        if modes[0] != "gdigrab":
            modes.append("gdigrab")
        last_err = ""
        for mode in modes:
            self.audio = None
            if self.s.get("capture_audio", True):
                try:
                    self.audio = LoopbackAudio()
                except Exception as e:
                    log("sound capture not available, streaming silence:", e)
            cmd = self._cmd(mode)
            log("ffmpeg:", " ".join(c if not c.startswith("rtmp") else "rtmp://<hidden>" for c in cmd))
            self.logfile = open(os.path.join(LOG_DIR, "ffmpeg.log"), "ab")
            self.logfile.write(f"\n==== {datetime.datetime.now()} mode={mode}\n".encode())
            self.logfile.flush()
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE if self.audio else subprocess.DEVNULL,
                                         stdout=subprocess.DEVNULL, stderr=self.logfile,
                                         creationflags=NO_WINDOW)
            if self.audio:
                self.audio.start(self.proc.stdin)
            self.started = time.monotonic()
            for _ in range(40):  # watch the first 4 seconds
                time.sleep(0.1)
                if self.proc.poll() is not None:
                    break
            if self.proc.poll() is None or (self.duration and self.proc.returncode == 0):
                log("capture running, mode:", mode)
                return
            last_err = tail_ffmpeg_log()
            log(f"capture mode {mode} failed (exit {self.proc.returncode}): {last_err}")
            self.stop()
        raise RuntimeError("Screen capture failed: " + last_err)

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def wait(self):
        if self.proc:
            self.proc.wait()

    def stop(self):
        if self.audio:
            self.audio.stop()
        if self.proc and self.proc.poll() is None:
            try:
                if self.proc.stdin:
                    self.proc.stdin.close()
            except Exception:
                pass
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.logfile:
            try:
                self.logfile.close()
            except Exception:
                pass


def tail_ffmpeg_log(n=600):
    try:
        with open(os.path.join(LOG_DIR, "ffmpeg.log"), "rb") as f:
            data = f.read()[-n:].decode(errors="replace")
        return data.strip().splitlines()[-1] if data.strip() else ""
    except Exception:
        return ""


# --------------------------------------------------------------------------- youtube
class YouTube:
    def __init__(self):
        self.lock = threading.RLock()
        self._svc = None

    def authorized(self):
        return os.path.exists(TOKEN_FILE)

    def svc(self):
        with self.lock:
            if self._svc is not None:
                return self._svc
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
            if not os.path.exists(CLIENT_SECRET):
                raise RuntimeError("client_secret.json is missing. Follow SETUP.md, part 1.")
            creds = None
            if os.path.exists(TOKEN_FILE):
                creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    try:
                        creds.refresh(Request())
                    except Exception as e:
                        log("token refresh failed, sign in again:", e)
                        creds = None
                else:
                    creds = None
                if creds is None:
                    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, SCOPES)
                    creds = flow.run_local_server(port=0, open_browser=True,
                                                  success_message="Sign-in complete. You can close this tab.")
                with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                    f.write(creds.to_json())
            self._svc = build("youtube", "v3", credentials=creds, cache_discovery=False)
            return self._svc

    def call(self, fn):
        from googleapiclient.errors import HttpError
        with self.lock:
            try:
                return fn(self.svc()).execute()
            except HttpError as e:
                msg = str(e)
                try:
                    msg = json.loads(e.content)["error"]["message"]
                except Exception:
                    pass
                raise RuntimeError(f"YouTube: {msg}") from e

    def create(self, title, privacy):
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        stream = self.call(lambda y: y.liveStreams().insert(part="snippet,cdn,contentDetails", body={
            "snippet": {"title": title[:100]},
            "cdn": {"ingestionType": "rtmp", "resolution": "variable", "frameRate": "variable"},
            "contentDetails": {"isReusable": False},
        }))
        try:
            bc = self.call(lambda y: y.liveBroadcasts().insert(part="snippet,status,contentDetails", body={
                "snippet": {"title": title[:100], "scheduledStartTime": now},
                "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
                "contentDetails": {"enableAutoStart": True, "enableAutoStop": True,
                                   "latencyPreference": "low", "enableDvr": True},
            }))
            self.call(lambda y: y.liveBroadcasts().bind(id=bc["id"], streamId=stream["id"], part="id"))
        except Exception:
            self.safe(lambda y: y.liveStreams().delete(id=stream["id"]))
            raise
        info = stream["cdn"]["ingestionInfo"]
        url = info["ingestionAddress"].rstrip("/") + "/" + info["streamName"]
        return bc, stream, url

    def safe(self, fn):
        try:
            return self.call(fn)
        except Exception as e:
            log("ignored:", e)
            return None

    def get(self, bid):
        r = self.call(lambda y: y.liveBroadcasts().list(part="snippet,status,contentDetails", id=bid))
        items = r.get("items", [])
        return items[0] if items else None

    def list_all(self):
        if not os.path.exists(CLIENT_SECRET) or not self.authorized():
            return []
        r = self.call(lambda y: y.liveBroadcasts().list(part="snippet,status", broadcastStatus="all",
                                                         broadcastType="all", maxResults=50))
        out = []
        for b in r.get("items", []):
            out.append({
                "id": b["id"],
                "title": b["snippet"].get("title", ""),
                "privacy": b["status"].get("privacyStatus", ""),
                "status": b["status"].get("lifeCycleStatus", ""),
                "start": b["snippet"].get("actualStartTime") or b["snippet"].get("scheduledStartTime", ""),
                "link": f"https://youtu.be/{b['id']}",
            })
        return out

    def set_title(self, bid, title):
        title = title.strip()[:100]
        if not title:
            raise RuntimeError("The title cannot be empty.")
        b = self.get(bid)
        if b and b["status"].get("lifeCycleStatus") != "complete":
            sn = b["snippet"]
            body = {"id": bid, "snippet": {"title": title, "description": sn.get("description", ""),
                                           "scheduledStartTime": sn["scheduledStartTime"]}}
            return self.call(lambda y: y.liveBroadcasts().update(part="snippet", body=body))
        v = self.call(lambda y: y.videos().list(part="snippet", id=bid))["items"][0]
        sn = v["snippet"]
        body = {"id": bid, "snippet": {"title": title, "description": sn.get("description", ""),
                                       "categoryId": sn.get("categoryId", "22"), "tags": sn.get("tags", [])}}
        return self.call(lambda y: y.videos().update(part="snippet", body=body))

    def set_privacy(self, bid, privacy):
        if privacy not in PRIVACY_VALUES:
            raise RuntimeError("Privacy must be public, unlisted or private.")
        b = self.get(bid)
        if b and b["status"].get("lifeCycleStatus") != "complete":
            body = {"id": bid, "status": {"privacyStatus": privacy,
                                          "selfDeclaredMadeForKids": b["status"].get("selfDeclaredMadeForKids", False)}}
            return self.call(lambda y: y.liveBroadcasts().update(part="status", body=body))
        v = self.call(lambda y: y.videos().list(part="status", id=bid))["items"][0]
        st = {k: v["status"][k] for k in ("embeddable", "license", "publicStatsViewable",
                                          "selfDeclaredMadeForKids") if k in v["status"]}
        st["privacyStatus"] = privacy
        return self.call(lambda y: y.videos().update(part="status", body={"id": bid, "status": st}))

    def complete(self, bid):
        return self.call(lambda y: y.liveBroadcasts().transition(broadcastStatus="complete", id=bid, part="status"))

    def go_live(self, bid):
        return self.call(lambda y: y.liveBroadcasts().transition(broadcastStatus="live", id=bid, part="status"))

    def delete(self, bid):
        try:
            self.call(lambda y: y.liveBroadcasts().delete(id=bid))
        except RuntimeError as e:
            log("liveBroadcasts.delete failed, trying videos.delete:", e)
            self.call(lambda y: y.videos().delete(id=bid))


# --------------------------------------------------------------------------- app
class App:
    def __init__(self):
        self.yt = YouTube()
        self.lock = threading.RLock()
        self.capture = None
        self.phase = "idle"  # idle | starting | waiting | live | stopping
        self.current = None  # {id, stream_id, title, privacy, link, started}
        self.yt_status = ""
        self.error = ""
        self.message = ""
        self.stop_event = threading.Event()
        self.rtmp = None

    # -- actions
    def start(self, title=None, privacy=None):
        with self.lock:
            if self.phase != "idle":
                return False
            self.phase = "starting"
            self.error = ""
            self.message = "Creating the stream on YouTube..."
        threading.Thread(target=self._start_worker, args=(title, privacy), daemon=True).start()
        return True

    def _start_worker(self, title, privacy):
        s = load_settings()
        title = (title or s["default_title"]).replace("{date}", datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
        privacy = privacy if privacy in PRIVACY_VALUES else s["default_privacy"]
        try:
            bc, stream, url = self.yt.create(title, privacy)
            self.rtmp = url
            link = f"https://youtu.be/{bc['id']}"
            with self.lock:
                self.current = {"id": bc["id"], "stream_id": stream["id"], "title": title,
                                "privacy": privacy, "link": link, "started": time.time()}
                self.message = "Starting screen and sound capture..."
            log("broadcast created:", bc["id"], link)
            if s.get("copy_link_on_start", True):
                copy_to_clipboard(link)
            cap = Capture(url, s)
            cap.start()
            with self.lock:
                self.capture = cap
                self.phase = "waiting"
                self.message = "Sending video. YouTube goes live in about 10-30 seconds."
            self.stop_event.clear()
            threading.Thread(target=self._monitor, daemon=True).start()
        except Exception as e:
            log("start failed:", traceback.format_exc())
            with self.lock:
                self.error = str(e)
                self.message = ""
                self.phase = "idle"
            if self.current:
                bid, sid = self.current["id"], self.current["stream_id"]
                self.yt.safe(lambda y: y.liveBroadcasts().delete(id=bid))
                self.yt.safe(lambda y: y.liveStreams().delete(id=sid))
                self.current = None

    def _monitor(self):
        restarts = 0
        t0 = time.monotonic()
        tried_manual = False
        while not self.stop_event.wait(8):
            cur = self.current
            if not cur:
                return
            # keep the encoder running (network drops etc.)
            if self.capture and not self.capture.alive() and self.phase in ("waiting", "live"):
                err = tail_ffmpeg_log()
                log("ffmpeg stopped:", err)
                if restarts < 5:
                    restarts += 1
                    self.message = f"Connection problem, reconnecting (try {restarts})..."
                    try:
                        self.capture = Capture(self.rtmp, load_settings())
                        self.capture.start()
                    except Exception as e:
                        log("restart failed:", e)
                else:
                    self.error = "The stream stopped: " + err
            try:
                b = self.yt.get(cur["id"])
                if b is None:
                    self.yt_status = "deleted"
                    continue
                st = b["status"].get("lifeCycleStatus", "")
                self.yt_status = st
                cur["privacy"] = b["status"].get("privacyStatus", cur["privacy"])
                cur["title"] = b["snippet"].get("title", cur["title"])
                if st == "live" and self.phase == "waiting":
                    self.phase = "live"
                    self.message = "You are LIVE."
                    restarts = 0
                elif st in ("ready", "created") and not tried_manual and time.monotonic() - t0 > 45:
                    tried_manual = True
                    sid = cur["stream_id"]
                    ss = self.yt.call(lambda y: y.liveStreams().list(part="status", id=sid))
                    if ss["items"] and ss["items"][0]["status"].get("streamStatus") == "active":
                        log("auto start did not happen, going live manually")
                        self.yt.safe(lambda y: y.liveBroadcasts().transition(
                            broadcastStatus="live", id=cur["id"], part="status"))
                elif st == "complete":
                    log("broadcast completed on YouTube side")
                    self._local_stop()
                    return
            except Exception as e:
                log("monitor:", e)

    def _local_stop(self):
        self.stop_event.set()
        cap, self.capture = self.capture, None
        if cap:
            cap.stop()
        cur = self.current
        if cur:
            sid = cur["stream_id"]
            threading.Thread(target=lambda: (time.sleep(5), self.yt.safe(lambda y: y.liveStreams().delete(id=sid))),
                             daemon=True).start()
        with self.lock:
            self.current = None
            self.phase = "idle"
            self.yt_status = ""
            self.message = "Stream ended."

    def stop(self):
        cur = self.current
        if not cur:
            return
        self.phase = "stopping"
        self.message = "Stopping..."
        if self.capture:
            self.capture.stop()
        try:
            b = self.yt.get(cur["id"])
            if b and b["status"].get("lifeCycleStatus") in ("live", "liveStarting", "testing"):
                self.yt.complete(cur["id"])
        except Exception as e:
            log("complete failed:", e)
        self._local_stop()

    def update(self, bid, title=None, privacy=None):
        if title is not None:
            self.yt.set_title(bid, title)
        if privacy is not None:
            self.yt.set_privacy(bid, privacy)
        cur = self.current
        if cur and cur["id"] == bid:
            if title is not None:
                cur["title"] = title.strip()
            if privacy is not None:
                cur["privacy"] = privacy

    def delete(self, bid):
        cur = self.current
        if cur and cur["id"] == bid:
            self.stop()
        self.yt.delete(bid)

    def status(self):
        s = load_settings()
        return {
            "setup_ok": os.path.exists(CLIENT_SECRET),
            "authorized": self.yt.authorized(),
            "phase": self.phase,
            "current": self.current,
            "yt_status": self.yt_status,
            "error": self.error,
            "message": self.message,
            "defaults": {"title": s["default_title"], "privacy": s["default_privacy"]},
        }


APP = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _host_ok(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"error": "forbidden"})
        try:
            if self.path in ("/", "/index.html"):
                with open(os.path.join(APP_DIR, "panel.html"), "rb") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")
            if self.path == "/api/status":
                return self._send(200, APP.status())
            if self.path == "/api/broadcasts":
                return self._send(200, {"items": APP.yt.list_all()})
            self._send(404, {"error": "not found"})
        except Exception as e:
            log("GET error:", traceback.format_exc())
            self._send(500, {"error": str(e)})

    def do_POST(self):
        # The custom header blocks other web sites from sending commands (CORS preflight fails).
        if not self._host_ok() or self.headers.get("X-Panel") != "1":
            return self._send(403, {"error": "forbidden"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            p = self.path
            if p == "/api/start":
                return self._send(200, {"started": APP.start(body.get("title"), body.get("privacy"))})
            if p == "/api/stop":
                APP.stop()
                return self._send(200, {"ok": True})
            if p == "/api/update":
                APP.update(body["id"], body.get("title"), body.get("privacy"))
                return self._send(200, {"ok": True})
            if p == "/api/delete":
                APP.delete(body["id"])
                return self._send(200, {"ok": True})
            if p == "/api/defaults":
                s = load_settings()
                if body.get("title", "").strip():
                    s["default_title"] = body["title"].strip()[:100]
                if body.get("privacy") in PRIVACY_VALUES:
                    s["default_privacy"] = body["privacy"]
                save_settings(s)
                return self._send(200, {"ok": True})
            if p == "/api/signin":
                APP.yt.svc()
                return self._send(200, {"ok": True})
            if p == "/api/clearerror":
                APP.error = ""
                return self._send(200, {"ok": True})
            if p == "/api/quit":
                self._send(200, {"ok": True})
                if APP.current:
                    APP.stop()
                threading.Thread(target=lambda: (time.sleep(0.5), os._exit(0)), daemon=True).start()
                return
            self._send(404, {"error": "not found"})
        except Exception as e:
            log("POST error:", traceback.format_exc())
            self._send(500, {"error": str(e)})


def server_running():
    try:
        with socket.create_connection((HOST, PORT), timeout=0.5):
            return True
    except OSError:
        return False


def post_existing(path):
    req = urllib.request.Request(PANEL_URL.rstrip("/") + path, data=b"{}", method="POST",
                                 headers={"X-Panel": "1", "Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=5).read()


def test_capture(out):
    s = load_settings()
    cap = Capture(out, s, duration=8)
    cap.start()
    cap.wait()
    cap.stop()
    print("exit code:", cap.proc.returncode, "->", out)


def main():
    global APP
    args = sys.argv[1:]
    if args[:1] == ["--test-capture"]:
        return test_capture(args[1] if len(args) > 1 else os.path.join(APP_DIR, "test.mp4"))
    panel_only = "--panel" in args
    s = load_settings()
    if server_running():
        if not panel_only:
            try:
                post_existing("/api/start")
            except Exception as e:
                log("could not reach the running app:", e)
        webbrowser.open(PANEL_URL)
        return
    APP = App()
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    log("control panel on", PANEL_URL)
    if not panel_only and os.path.exists(CLIENT_SECRET) and APP.yt.authorized():
        APP.start()
    if panel_only or s.get("open_panel_on_start", True) or not APP.yt.authorized():
        webbrowser.open(PANEL_URL)
    srv.serve_forever()


if __name__ == "__main__":
    main()
