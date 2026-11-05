#include "scan.h"

#include <stdio.h>

#include "acquisition.h"
#include "motors.h"
#include "positioning.h"
#include "u4rk.h"
#include "usb_transport.h"
#include "pico/stdlib.h"

typedef enum {
    SCAN_IDLE,
    SCAN_SETTLE,
    SCAN_CAPTURE,
    SCAN_MOVE,
} scan_phase_t;

static scan_config_t scan_config;
static scan_phase_t scan_phase;
static uint16_t scan_samples[U4RK_RAW_SAMPLE_COUNT];
static int32_t scan_origin_x;
static int32_t scan_origin_y;
static uint32_t scan_row;
static uint32_t scan_column;
static uint32_t scan_points;
static uint64_t scan_deadline;
static uint64_t scan_move_deadline;

static bool scan_send(const char *message) {
    if (!u4rk_usb_connected()) return false;
    size_t length = 0;
    while (message[length]) ++length;
    return u4rk_usb_write_blocking(message, length, 2000);
}

static void scan_finish(const char *message) {
    if (scan_phase == SCAN_CAPTURE) u4rk_capture_abort();
    if (motor_any_active()) motor_stop_all();
    u4rk_pulser_disarm();
    scan_phase = SCAN_IDLE;
    if (message) scan_send(message);
}

static void scan_fail(const char *reason) {
    char line[120];
    snprintf(line, sizeof(line), "SCAN_ERROR %s\r\n", reason);
    scan_finish(line);
}

bool scan_active(void) {
    return scan_phase != SCAN_IDLE;
}

void scan_abort(void) {
    if (scan_active()) scan_finish("SCAN_ABORT\r\n");
}

bool scan_start(const scan_config_t *cfg, const char **error) {
    if (scan_active()) {
        *error = "scan already active";
        return false;
    }
    if (!cfg || cfg->nx == 0 || cfg->ny == 0 ||
        cfg->nx > 1000 || cfg->ny > 1000 ||
        (uint64_t)cfg->nx * cfg->ny > 100000u ||
        (cfg->nx > 1 && (!cfg->dx_steps || cfg->dx_steps > MAX_STEPS)) ||
        (cfg->ny > 1 && (!cfg->dy_steps || cfg->dy_steps > MAX_STEPS)) ||
        cfg->speed_hz == 0 || cfg->speed_hz > MAX_MOTOR_FREQ_HZ ||
        cfg->gate_start >= cfg->gate_end ||
        cfg->gate_end > U4RK_RAW_SAMPLE_COUNT ||
        cfg->settle_ms > 60000u) {
        *error = "invalid scan parameters";
        return false;
    }
    if (motor_any_active() || motor_is_homing_xy()) {
        *error = "motor busy";
        return false;
    }
    if (!positioning_is_homed(POSITION_AXIS_X) ||
        !positioning_is_homed(POSITION_AXIS_Y) ||
        !positioning_is_exact(POSITION_AXIS_X) ||
        !positioning_is_exact(POSITION_AXIS_Y)) {
        *error = "X/Y must be homed with exact positions";
        return false;
    }
    if (!u4rk_pulser_is_armed()) {
        *error = "pulser is not armed";
        return false;
    }
    int64_t x = positioning_get_steps(POSITION_AXIS_X);
    int64_t y = positioning_get_steps(POSITION_AXIS_Y);
    int64_t last_x = x + (int64_t)(cfg->nx - 1) * cfg->dx_steps;
    int64_t last_y = y + (int64_t)(cfg->ny - 1) * cfg->dy_steps;
    if (x < X_MIN_POSITION_STEPS || last_x > X_MAX_POSITION_STEPS ||
        y < Y_MIN_POSITION_STEPS || last_y > Y_MAX_POSITION_STEPS) {
        *error = "scan exceeds X/Y software limits";
        return false;
    }
    scan_config = *cfg;
    scan_origin_x = (int32_t)x;
    scan_origin_y = (int32_t)y;
    scan_row = 0;
    scan_column = 0;
    scan_points = 0;
    scan_deadline = time_us_64() + (uint64_t)cfg->settle_ms * 1000u;
    scan_phase = SCAN_SETTLE;
    return true;
}

static bool scan_move(position_axis_t axis, bool increasing, uint32_t steps) {
    if (!steps) return true;
    char args[64];
    snprintf(args, sizeof(args), "%s %lu %lu",
             increasing ? "plus" : "minus",
             (unsigned long)scan_config.speed_hz, (unsigned long)steps);
    bool started = axis == POSITION_AXIS_X ? move_x(args) : move_y(args);
    if (started) {
        uint64_t slow_estimate = (uint64_t)steps * 1000000u / 100u;
        scan_move_deadline = time_us_64() + slow_estimate + 15000000u;
        scan_phase = SCAN_MOVE;
    }
    return started;
}

static bool scan_position_valid(void) {
    int64_t expected_x = (int64_t)scan_origin_x +
                         (int64_t)scan_column * scan_config.dx_steps;
    int64_t expected_y = (int64_t)scan_origin_y +
                         (int64_t)scan_row * scan_config.dy_steps;
    return positioning_is_exact(POSITION_AXIS_X) &&
           positioning_is_exact(POSITION_AXIS_Y) &&
           positioning_get_steps(POSITION_AXIS_X) == expected_x &&
           positioning_get_steps(POSITION_AXIS_Y) == expected_y;
}

void scan_poll(void) {
    if (!scan_active()) return;
    if (!u4rk_usb_mounted() || !u4rk_usb_connected()) {
        scan_finish(NULL);
        return;
    }
    uint64_t now = time_us_64();
    if (scan_phase == SCAN_MOVE) {
        if (now > scan_move_deadline) {
            scan_fail("MOTION_TIMEOUT");
            return;
        }
        if (motor_any_active()) return;
        if (!scan_position_valid()) {
            scan_fail("POSITION_MISMATCH");
            return;
        }
        scan_deadline = now + (uint64_t)scan_config.settle_ms * 1000u;
        scan_phase = SCAN_SETTLE;
    }
    if (scan_phase == SCAN_SETTLE) {
        if (now < scan_deadline) return;
        if (!scan_position_valid()) {
            scan_fail("POSITION_MISMATCH");
            return;
        }
        if (!u4rk_capture_start(scan_samples, U4RK_RAW_SAMPLE_COUNT)) {
            scan_fail("CAPTURE_START");
            return;
        }
        scan_phase = SCAN_CAPTURE;
        return;
    }
    if (scan_phase != SCAN_CAPTURE) return;
    u4rk_capture_state_t result = u4rk_capture_poll();
    if (result == U4RK_CAPTURE_ACTIVE) return;
    if (result != U4RK_CAPTURE_DONE) {
        scan_fail("CAPTURE_DMA");
        return;
    }
    uint16_t min_value = UINT16_MAX;
    uint16_t max_value = 0;
    for (uint32_t i = scan_config.gate_start; i < scan_config.gate_end; ++i) {
        uint16_t sample = (scan_samples[i] >> 1) & 0x3ffu;
        if (sample < min_value) min_value = sample;
        if (sample > max_value) max_value = sample;
    }
    char line[120];
    snprintf(line, sizeof(line), "SCAN_POINT %lu %lu %ld %ld %u\r\n",
             (unsigned long)scan_row, (unsigned long)scan_column,
             (long)positioning_get_steps(POSITION_AXIS_X),
             (long)positioning_get_steps(POSITION_AXIS_Y),
             (unsigned)(max_value - min_value));
    if (!scan_send(line)) {
        scan_finish(NULL);
        return;
    }
    ++scan_points;
    if (scan_points == scan_config.nx * scan_config.ny) {
        snprintf(line, sizeof(line), "SCAN_DONE %lu\r\n",
                 (unsigned long)scan_points);
        scan_finish(line);
        return;
    }
    if ((scan_row % 2u) == 0u) {
        if (scan_column + 1u < scan_config.nx) {
            ++scan_column;
            if (!scan_move(POSITION_AXIS_X, true, scan_config.dx_steps))
                scan_fail("X_MOVE");
            return;
        }
    } else {
        if (scan_column > 0u) {
            --scan_column;
            if (!scan_move(POSITION_AXIS_X, false, scan_config.dx_steps))
                scan_fail("X_MOVE");
            return;
        }
    }
    ++scan_row;
    if (!scan_move(POSITION_AXIS_Y, true, scan_config.dy_steps)) {
        scan_fail("Y_MOVE");
    }
}
