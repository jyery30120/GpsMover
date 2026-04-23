#!/usr/bin/env python3
"""
iPhone GPS 模擬器 - 模擬從起點走到終點（走路速度）
使用方式：
    python gps.py <起點緯度> <起點經度> <終點緯度> <終點經度> [--speed 速度(m/s)]
範例：
    python gps.py 25.0330 121.5654 25.0400 121.5700 --speed 1.4
"""

import asyncio
import math
import argparse
import sys

try:
    from pymobiledevice3.lockdown import create_using_usbmux
    from pymobiledevice3.services.simulate_location import DtSimulateLocation
except ImportError:
    print("請先安裝 pymobiledevice3：pip install pymobiledevice3")
    sys.exit(1)


WALKING_SPEED = 1.4   # 預設步行速度 m/s（約 5 km/h）
UPDATE_INTERVAL = 1.0  # 每秒更新一次 GPS


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """計算兩個 GPS 座標之間的距離（公尺）"""
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def interpolate(lat1, lon1, lat2, lon2, fraction):
    """在兩點之間線性插值"""
    return lat1 + (lat2 - lat1) * fraction, lon1 + (lon2 - lon1) * fraction


async def _simulate_walk_async(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    speed_mps: float,
    update_interval: float,
):
    distance = haversine_distance(start_lat, start_lon, end_lat, end_lon)
    total_seconds = distance / speed_mps
    total_steps = max(1, int(total_seconds / update_interval))

    print(f"起點：({start_lat}, {start_lon})")
    print(f"終點：({end_lat}, {end_lon})")
    print(f"距離：{distance:.1f} 公尺")
    print(f"速度：{speed_mps:.1f} m/s（{speed_mps * 3.6:.1f} km/h）")
    print(f"預計時間：{total_seconds:.0f} 秒（{total_seconds / 60:.1f} 分鐘）")
    print("正在連接 iPhone...")

    try:
        lockdown = await create_using_usbmux()
    except Exception as e:
        print(f"連接失敗：{e}")
        print("請確認 iPhone 已用 USB 連接並信任此電腦。")
        sys.exit(1)

    print(f"已連接：{lockdown.identifier}（{lockdown.product_type}）")
    print("開始模擬，按 Ctrl+C 停止\n")

    svc = DtSimulateLocation(lockdown)
    try:
        for step in range(total_steps + 1):
            fraction = step / total_steps
            lat, lon = interpolate(start_lat, start_lon, end_lat, end_lon, fraction)
            await svc.set(lat, lon)

            bar_len = 30
            filled = int(bar_len * fraction)
            bar = "█" * filled + "░" * (bar_len - filled)
            elapsed = step * update_interval
            print(
                f"\r[{bar}] {fraction*100:.0f}%  "
                f"{lat:.6f}, {lon:.6f}  "
                f"({elapsed:.0f}s / {total_seconds:.0f}s)",
                end="",
                flush=True,
            )

            if step < total_steps:
                await asyncio.sleep(update_interval)

        print("\n已到達終點！")

    except KeyboardInterrupt:
        print("\n已中止模擬，清除模擬位置...")
        await svc.clear()
        print("GPS 模擬已關閉。")


def simulate_walk(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    speed_mps: float = WALKING_SPEED,
    update_interval: float = UPDATE_INTERVAL,
):
    asyncio.run(_simulate_walk_async(start_lat, start_lon, end_lat, end_lon, speed_mps, update_interval))


def main():
    parser = argparse.ArgumentParser(description="模擬 iPhone 走路路徑")
    parser.add_argument("start_lat", type=float, help="起點緯度")
    parser.add_argument("start_lon", type=float, help="起點經度")
    parser.add_argument("end_lat", type=float, help="終點緯度")
    parser.add_argument("end_lon", type=float, help="終點經度")
    parser.add_argument(
        "--speed",
        type=float,
        default=WALKING_SPEED,
        help=f"移動速度（m/s，預設 {WALKING_SPEED}）",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=UPDATE_INTERVAL,
        help=f"GPS 更新間隔秒數（預設 {UPDATE_INTERVAL}）",
    )
    args = parser.parse_args()
    simulate_walk(
        args.start_lat,
        args.start_lon,
        args.end_lat,
        args.end_lon,
        speed_mps=args.speed,
        update_interval=args.interval,
    )


if __name__ == "__main__":
    main()
