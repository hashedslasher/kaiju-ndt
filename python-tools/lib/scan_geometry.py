import math
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP


def centered_axis(size_mm, margin_mm, pitch_mm, steps_per_mm, limit_mm, max_move_mm):
    values = (size_mm, margin_mm, pitch_mm, steps_per_mm, limit_mm, max_move_mm)
    if not all(math.isfinite(float(v)) for v in values):
        raise ValueError('Scan geometry must be finite')
    if size_mm <= 0 or margin_mm < 0 or pitch_mm <= 0 or steps_per_mm <= 0:
        raise ValueError('Coupon size and spacing must be positive; margin must be nonnegative')
    scale = Decimal(str(steps_per_mm))
    total = (Decimal(str(size_mm)) + 2 * Decimal(str(margin_mm))) * scale
    pitch = int((Decimal(str(pitch_mm)) * scale).to_integral_value(rounding=ROUND_HALF_UP))
    limit = int((Decimal(str(limit_mm)) * scale).to_integral_value(rounding=ROUND_HALF_UP))
    max_move = int((Decimal(str(max_move_mm)) * scale).to_integral_value(rounding=ROUND_HALF_UP))
    if not 1 <= pitch <= max_move:
        raise ValueError('Spacing is outside the supported step range')
    intervals = int((total / pitch).to_integral_value(rounding=ROUND_CEILING))
    while True:
        span = intervals * pitch
        if span > limit or intervals + 1 > 1000:
            raise ValueError('Centered scan exceeds software limits or 1000 points per axis')
        origin = (limit + span + 1) // 2
        end = origin - span
        if 2 * origin - limit >= total and limit - 2 * end >= total:
            break
        intervals += 1
    return dict(count=intervals + 1, pitch_mm=float(Decimal(pitch) / scale),
                origin_mm=float(Decimal(origin) / scale), end_mm=float(Decimal(end) / scale),
                local_start_mm=float((Decimal(limit) / 2 - origin) / scale),
                local_end_mm=float((Decimal(limit) / 2 - end) / scale))


def centered_plan(geometry_reply, width_mm, height_mm, margin_mm, dx_mm, dy_mm):
    fields = dict(part.split('=', 1) for part in geometry_reply.split() if '=' in part)
    try:
        x = centered_axis(width_mm, margin_mm, dx_mm, int(fields['x_steps_per_mm']),
                          float(fields['xmax']), float(fields['max_move_mm']))
        y = centered_axis(height_mm, margin_mm, dy_mm, int(fields['y_steps_per_mm']),
                          float(fields['ymax']), float(fields['max_move_mm']))
    except KeyError as exc:
        raise ValueError('Firmware geometry is missing scan limits; rebuild and flash the updated firmware') from exc
    if x['count'] * y['count'] > 100000:
        raise ValueError('Maximum 100,000 scan points')
    return dict(nx=x['count'], ny=y['count'], dx_mm=x['pitch_mm'], dy_mm=y['pitch_mm'],
                x0_mm=0.0, y0_mm=0.0,
                home_start_x_mm=x['origin_mm'], home_start_y_mm=y['origin_mm'],
                home_end_x_mm=x['end_mm'], home_end_y_mm=y['end_mm'], centered=True)
