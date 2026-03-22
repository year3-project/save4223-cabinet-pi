#!/usr/bin/env python3
"""
WS2812B control using rpi_ws281x library (no 'board' / Blinka needed)
"""

import time
import argparse
from rpi_ws281x import PixelStrip, Color


# ================= CONFIG =================
LED_PIN       = 18          # GPIO 18
LED_FREQ_HZ   = 800000      # usually fine
LED_DMA       = 10          # usually fine
LED_BRIGHTNESS = 180        # 0–255 (≈70% brightness)
LED_INVERT    = False
LED_CHANNEL   = 0
LED_COUNT     = 60          # ← change this
# ==========================================


def color_wipe(strip, color, wait_ms=20):
    for i in range(strip.numPixels()):
        strip.setPixelColor(i, color)
        strip.show()
        time.sleep(wait_ms / 1000.0)


def theater_chase(strip, color, wait_ms=100, iterations=10):
    for j in range(iterations):
        for q in range(3):
            for i in range(0, strip.numPixels() - 2, 3):
                strip.setPixelColor(i + q, color)
            strip.show()
            time.sleep(wait_ms / 1000.0)
            for i in range(0, strip.numPixels() - 2, 3):
                strip.setPixelColor(i + q, Color(0, 0, 0))
            strip.show()
            time.sleep(wait_ms / 1000.0)


def wheel(pos):
    pos = pos & 255
    if pos < 85:
        return Color(pos * 3, 255 - pos * 3, 0)
    elif pos < 170:
        pos -= 85
        return Color(255 - pos * 3, 0, pos * 3)
    else:
        pos -= 170
        return Color(0, pos * 3, 255 - pos * 3)


def rainbow_cycle(strip, wait_ms=3, iterations=5):
    for j in range(256 * iterations):
        for i in range(strip.numPixels()):
            strip.setPixelColor(i, wheel((int(i * 256 / strip.numPixels()) + j) & 255))
        strip.show()
        time.sleep(wait_ms / 1000.0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--count', type=int, default=LED_COUNT)
    parser.add_argument('--brightness', type=int, default=LED_BRIGHTNESS)
    args = parser.parse_args()

    strip = PixelStrip(
        args.count, LED_PIN, LED_FREQ_HZ, LED_DMA,
        LED_INVERT, args.brightness, LED_CHANNEL
    )
    strip.begin()

    print(f"rpi_ws281x demo – {args.count} LEDs @ brightness {args.brightness}")
    print("Ctrl+C to exit\n")

    try:
        while True:
            print("Color wipe white")
            color_wipe(strip, Color(255, 255, 255), 5)

            print("Color wipe red")
            color_wipe(strip, Color(255, 0, 0), 20)

            print("Rainbow cycle")
            rainbow_cycle(strip)

            print("Theater chase blue")
            theater_chase(strip, Color(0, 0, 180), 80, 5)

            print("Off...")
            color_wipe(strip, Color(0, 0, 0), 10)
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nStopped → clearing")
    finally:
        color_wipe(strip, Color(0, 0, 0), 1)


if __name__ == '__main__':
    main()
