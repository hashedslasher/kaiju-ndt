#ifndef GANTRY_UNITS_H
#define GANTRY_UNITS_H
#include <stdbool.h>
#include <stdint.h>
#include <math.h>

#define GANTRY_MRES 5u
#define GANTRY_MICROSTEPS (256u >> GANTRY_MRES)
#define GANTRY_FULL_STEPS_PER_REV 200u
#define GANTRY_XY_MM_PER_REV 32u
#define GANTRY_Z_MM_PER_REV 8u
#define GANTRY_XY_STEPS_PER_MM (GANTRY_FULL_STEPS_PER_REV * GANTRY_MICROSTEPS / GANTRY_XY_MM_PER_REV)
#define GANTRY_Z_STEPS_PER_MM (GANTRY_FULL_STEPS_PER_REV * GANTRY_MICROSTEPS / GANTRY_Z_MM_PER_REV)

static inline uint32_t gantry_steps_per_mm(unsigned axis)
{
    return axis == 2u ? GANTRY_Z_STEPS_PER_MM : GANTRY_XY_STEPS_PER_MM;
}

static inline double gantry_steps_to_mm(unsigned axis, int32_t steps)
{
    return (double)steps / gantry_steps_per_mm(axis);
}

static inline bool gantry_mm_to_steps(unsigned axis, double mm, uint32_t maximum, uint32_t *out)
{
    double scaled = mm * gantry_steps_per_mm(axis);
    if (!isfinite(scaled) || scaled < 0.0 || scaled >= (double)maximum + 0.5) return false;
    *out = (uint32_t)(scaled + 0.5);
    return true;
}
#endif
