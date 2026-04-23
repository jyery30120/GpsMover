#!/usr/bin/env python3
"""
iPhone GPS 模擬器 Web UI  (iOS 17+)
啟動步驟：
  1. sudo python3 -m pymobiledevice3 remote tunneld   ← 背景跑，只需一次
  2. python3 app.py
  3. 開啟 http://localhost:5050
"""

import asyncio
import math
import threading
from flask import Flask, jsonify, render_template, request

try:
    from pymobiledevice3.tunneld.api import get_tunneld_devices
    from pymobiledevice3.exceptions import TunneldConnectionError
    from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
    from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation
    PYMOBILE_OK = True
except ImportError:
    PYMOBILE_OK = False

app = Flask(__name__)

# ── Persistent async loop ─────────────────────────────────────────────────────
_loop = asyncio.new_event_loop()
threading.Thread(target=_loop.run_forever, daemon=True).start()


def _run(coro, timeout=15):
    return asyncio.run_coroutine_threadsafe(coro, _loop).result(timeout=timeout)


# ── State ─────────────────────────────────────────────────────────────────────
state = {
    "lat": None, "lon": None,
    "target_lat": None, "target_lon": None,
    "running": False, "progress": 0.0,
    "distance": 0.0, "speed": 1.4,
    "connected": False, "device": None, "eta": 0,
}

_rsd = None
_walk_task: asyncio.Task | None = None  # runs inside _loop


# ── Geo helpers ───────────────────────────────────────────────────────────────

def _dist(lat1, lon1, lat2, lon2):
    R = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _lerp(lat1, lon1, lat2, lon2, t):
    return lat1 + (lat2 - lat1) * t, lon1 + (lon2 - lon1) * t


# ── Walk coroutine — DVT context stays open the whole time ───────────────────

async def _walk_async():
    s_lat, s_lon = state["lat"], state["lon"]
    e_lat, e_lon = state["target_lat"], state["target_lon"]
    speed = state["speed"]

    dist = _dist(s_lat, s_lon, e_lat, e_lon)
    total_s = max(1.0, dist / speed)
    steps = max(1, int(total_s))

    state["distance"] = round(dist)
    state["eta"] = round(total_s)
    state["running"] = True
    state["progress"] = 0.0

    try:
        # Keep DvtProvider + LocationSimulation open for the entire walk.
        # Closing the context even briefly lets the real GPS snap back in.
        async with DvtProvider(_rsd) as dvt:
            async with LocationSimulation(dvt) as sim:
                for i in range(steps + 1):
                    t = i / steps
                    lat, lon = _lerp(s_lat, s_lon, e_lat, e_lon, t)
                    state["lat"] = lat
                    state["lon"] = lon
                    state["progress"] = round(t * 100, 1)
                    await sim.set(lat, lon)
                    if i < steps:
                        await asyncio.sleep(1.0)
                # Hold the last position until explicitly stopped
                while True:
                    await asyncio.sleep(1.0)
    except asyncio.CancelledError:
        # Try to clear the simulated location when cancelled
        try:
            async with DvtProvider(_rsd) as dvt:
                async with LocationSimulation(dvt) as sim:
                    await sim.clear()
        except Exception:
            pass
    finally:
        state["running"] = False


async def _cancel_walk():
    global _walk_task
    if _walk_task and not _walk_task.done():
        _walk_task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(_walk_task), timeout=3)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
    _walk_task = None


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/connect", methods=["POST"])
def connect():
    global _rsd
    if not PYMOBILE_OK:
        return jsonify(ok=False, error="請先安裝 pymobiledevice3")
    try:
        rsds = _run(get_tunneld_devices())
    except TunneldConnectionError:
        return jsonify(ok=False,
            error="tunneld 未執行。請在終端機跑：\nsudo python3 -m pymobiledevice3 remote tunneld")
    except Exception as e:
        return jsonify(ok=False, error=str(e))

    if not rsds:
        return jsonify(ok=False, error="tunneld 執行中但找不到裝置。請確認 iPhone 已插上並信任此電腦。")

    _rsd = rsds[0]
    state["connected"] = True
    state["device"] = getattr(_rsd, "name", None) or "iPhone (iOS 17+)"
    return jsonify(ok=True, device=state["device"])


@app.route("/start", methods=["POST"])
def start():
    global _walk_task

    data = request.json
    # Cancel any existing walk
    _run(_cancel_walk())

    state["lat"] = data["start_lat"]
    state["lon"] = data["start_lon"]
    state["target_lat"] = data["end_lat"]
    state["target_lon"] = data["end_lon"]
    state["speed"] = float(data.get("speed", 1.4))

    # Schedule the walk coroutine in the persistent loop
    future = asyncio.run_coroutine_threadsafe(
        _schedule_walk_task(), _loop
    )
    future.result(timeout=5)

    return jsonify(ok=True, distance=round(
        _dist(data["start_lat"], data["start_lon"], data["end_lat"], data["end_lon"])
    ))


async def _schedule_walk_task():
    global _walk_task
    _walk_task = asyncio.ensure_future(_walk_async())


@app.route("/stop", methods=["POST"])
def stop():
    _run(_cancel_walk())
    return jsonify(ok=True)


@app.route("/status")
def status():
    return jsonify(state)


if __name__ == "__main__":
    print("GPS 模擬器啟動中 → http://localhost:5050")
    print("注意：請先在另一個終端機執行：sudo python3 -m pymobiledevice3 remote tunneld")
    app.run(host="0.0.0.0", port=5050, debug=False, threaded=True)
