import math
import time

POLL_MS = 20
XY_ENTER = 0.18
XY_EXIT = 0.12
Z_ENTER = 0.18
Z_EXIT = 0.12
SNAP_ENTER_DEG = 15.0
SNAP_EXIT_DEG = 22.0
AXIS_ENTER = 0.12
AXIS_EXIT = 0.07
RESPONSE_EXPONENT = 1.4
MAX_SPEED_MM_S = {'x': 50.0, 'y': 50.0, 'z': 15.0}
SPEED_FRACTIONS = (0.12, 0.32, 0.52, 0.76, 1.0)
SPEED_BOUNDARIES = (0.22, 0.42, 0.64, 0.86)
SPEED_HYSTERESIS = 0.05
SPEED_SETTLE_S = 0.12
SPEED_CHANGE_INTERVAL_S = 0.45
REVERSE_SETTLE_S = 0.12


def normalize_axis(raw):
    raw = max(-32768, min(32767, raw))
    return raw / (32768.0 if raw < 0 else 32767.0)


def jog_command(axis, signed_speed):
    if not signed_speed:
        return f'stop_{axis}'
    negative, positive = {'x': ('plus', 'minus'),
                          'y': ('minus', 'plus'),
                          'z': ('down', 'up')}[axis]
    speed_mm_s = abs(signed_speed)
    return f'jog_mm_{axis} {positive if signed_speed > 0 else negative} {speed_mm_s:g}'


class _Axis:
    def __init__(self, maximum):
        self.maximum = maximum
        self.reset()

    def reset(self):
        self.sign = 0
        self.band = 0
        self.last_change = -math.inf
        self.pending = None
        self.pending_since = 0.0
        self.reverse_until = -math.inf
        self.last_sign = 0

    def _band(self, magnitude):
        if not self.sign:
            return sum(magnitude >= boundary for boundary in SPEED_BOUNDARIES)
        band = self.band
        while band < len(SPEED_BOUNDARIES) and magnitude >= SPEED_BOUNDARIES[band] + SPEED_HYSTERESIS:
            band += 1
        while band > 0 and magnitude <= SPEED_BOUNDARIES[band - 1] - SPEED_HYSTERESIS:
            band -= 1
        return band

    def update(self, raw, magnitude, now):
        threshold = AXIS_EXIT if self.sign else AXIS_ENTER
        requested = (1 if raw > 0 else -1) if abs(raw) >= threshold else 0
        if not requested or (self.sign and requested != self.sign):
            if self.sign:
                self.last_sign = self.sign
                self.reverse_until = now + REVERSE_SETTLE_S
            self.sign = 0
            self.pending = None
            return 0
        if not self.sign:
            if requested != self.last_sign and now < self.reverse_until:
                return 0
            self.band = self._band(magnitude)
            self.sign = requested
            self.last_change = now
            self.pending = None
        else:
            candidate = self._band(magnitude)
            if candidate == self.band:
                self.pending = None
            elif candidate != self.pending:
                self.pending = candidate
                self.pending_since = now
            elif now - self.pending_since >= SPEED_SETTLE_S and now - self.last_change >= SPEED_CHANGE_INTERVAL_S:
                self.band = candidate
                self.last_change = now
                self.pending = None
        return self.sign * round(self.maximum * SPEED_FRACTIONS[self.band], 3)


class GamepadFilter:
    def __init__(self):
        self.axes = {axis: _Axis(speed) for axis, speed in MAX_SPEED_MM_S.items()}
        self.reset()

    def reset(self):
        self.xy_active = False
        self.z_active = False
        self.snap = None
        for axis in self.axes.values():
            axis.reset()

    @staticmethod
    def neutral(raw_x, raw_y, raw_z):
        x, y, z = map(normalize_axis, (raw_x, raw_y, raw_z))
        return math.hypot(x, y) <= XY_EXIT and abs(z) <= Z_EXIT

    @staticmethod
    def _scale(magnitude, deadzone):
        return (max(0.0, min(1.0, magnitude) - deadzone) / (1.0 - deadzone)) ** RESPONSE_EXPONENT

    def update(self, raw_x, raw_y, raw_z, now=None):
        now = time.monotonic() if now is None else now
        x, y, z = map(normalize_axis, (raw_x, raw_y, raw_z))
        radius = math.hypot(x, y)
        self.xy_active = radius > (XY_EXIT if self.xy_active else XY_ENTER)
        self.z_active = abs(z) > (Z_EXIT if self.z_active else Z_ENTER)
        if not self.xy_active:
            self.snap = None
            x = y = mx = my = 0.0
        else:
            angle = math.degrees(math.atan2(abs(y), abs(x)))
            if self.snap == 'x' and angle > SNAP_EXIT_DEG:
                self.snap = None
            elif self.snap == 'y' and angle < 90.0 - SNAP_EXIT_DEG:
                self.snap = None
            if self.snap is None:
                if angle <= SNAP_ENTER_DEG:
                    self.snap = 'x'
                elif angle >= 90.0 - SNAP_ENTER_DEG:
                    self.snap = 'y'
            magnitude = self._scale(radius, XY_EXIT)
            if self.snap == 'x':
                x, y = math.copysign(min(radius, 1.0), x), 0.0
                mx, my = magnitude, 0.0
            elif self.snap == 'y':
                x, y = 0.0, math.copysign(min(radius, 1.0), y)
                mx, my = 0.0, magnitude
            else:
                mx, my = magnitude * abs(x) / radius, magnitude * abs(y) / radius
        if not self.z_active:
            z = 0.0
        return (self.axes['x'].update(x, mx, now),
                self.axes['y'].update(y, my, now),
                self.axes['z'].update(z, self._scale(abs(z), Z_EXIT), now))
