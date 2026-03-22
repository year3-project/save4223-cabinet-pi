import RPi.GPIO as GPIO
from time import sleep

# Use BCM numbering (most common)
GPIO.setmode(GPIO.BCM)

# The pins you want to read (BCM numbers)
PINS = [26,19,6,5]

# Set all as input (you can also use GPIO.PUD_UP / GPIO.PUD_DOWN)
for pin in PINS:
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)   # or PUD_UP / no pull

print("Monitoring GPIO pins (Ctrl+C to stop)...")
print("Pin → " + "  ".join(f"{p:2}" for p in PINS))
print("-" * (8 + len(PINS) * 4))

try:
    while True:
        states = [GPIO.input(pin) for pin in PINS]   # returns 1 or 0
        print("     " + "  ".join(f" {s} " for s in states))
        # Or more verbose:
        # print("     " + "  ".join("HIGH" if s else " LOW" for s in states))
        sleep(0.2)

except KeyboardInterrupt:
    print("\nStopped by user")

finally:
    GPIO.cleanup()   # important when using RPi.GPIO
