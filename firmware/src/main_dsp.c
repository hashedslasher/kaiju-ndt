#include <errno.h>
#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "pico/multicore.h"
#include "pico/binary_info.h"
#include "pico/bootrom.h"
#include "pico/stdlib.h"

#include "acquisition.h"
#include "dac.h"
#include "dsp.h"
#include "pipeline.h"
#include "motors.h"
#include "gantry_units.h"
#include "bridge.h"
#include "temperature.h"
#include "u4rk.h"
#include "usb_transport.h"
#include "scan/scan.h"
#include "scan/scan.c"

#define U4RK_COMMAND_BUFFER_SIZE 224u
#define U4RK_RESPONSE_BUFFER_SIZE 512u
#define U4RK_CONTROL_TIMEOUT_MS 2000u

typedef struct {
    bool active;
    u4rk_payload_type_t type;
    uint32_t rate_hz;
    uint32_t interval_us;
    uint64_t next_capture_us;
} stream_state_t;

static stream_state_t stream;
static bool capture_inflight;
static uint8_t capture_raw_index;
static u4rk_capture_job_t capture_job;
static uint32_t next_sequence;
static float alaw_reference = U4RK_ALAW_DEFAULT_REFERENCE;

static char command_buffer[U4RK_COMMAND_BUFFER_SIZE];
static size_t command_length;
static char response_buffer[U4RK_RESPONSE_BUFFER_SIZE];

static bool output_slot_active;
static uint8_t active_output_slot;
static uint32_t active_output_sequence;
static uint32_t active_output_session;
static bool stop_pending;
static bool dma_fault_pending;
static bool legacy_capture_pending;
static uint32_t legacy_capture_sequence;

static bool selftest_active;
static bool selftest_frame_pending;
static uint32_t selftest_pending_sequence;
static uint8_t selftest_case;
static u4rk_payload_type_t selftest_type;

/* Jobs and output frames are tagged so work from a closed CDC session can
 * never be mistaken for work belonging to the next host connection. */
static uint32_t usb_session_id = 1u;
static bool usb_was_mounted;

static uint16_t legacy_read_buffer[U4RK_MAX_SAMPLE_COUNT];

static bool send_formatted(const char *prefix, const char *format, va_list args) {
    int used = snprintf(response_buffer, sizeof(response_buffer), "%s", prefix);
    if (used < 0 || (size_t)used >= sizeof(response_buffer)) {
        return false;
    }
    int added = vsnprintf(response_buffer + used, sizeof(response_buffer) - used,
                          format, args);
    if (added < 0) {
        return false;
    }
    size_t length = strnlen(response_buffer, sizeof(response_buffer));
    if (length + 2u >= sizeof(response_buffer)) {
        length = sizeof(response_buffer) - 3u;
    }
    response_buffer[length++] = '\r';
    response_buffer[length++] = '\n';
    return u4rk_usb_write_blocking(response_buffer, length,
                                    U4RK_CONTROL_TIMEOUT_MS);
}

static bool send_ok(const char *format, ...) {
    va_list args;
    va_start(args, format);
    bool result = send_formatted("OK ", format, args);
    va_end(args);
    return result;
}

static bool send_error(const char *code, const char *format, ...) {
    int prefix_length =
        snprintf(response_buffer, sizeof(response_buffer), "ERR %s ", code);
    if (prefix_length < 0 ||
        (size_t)prefix_length >= sizeof(response_buffer)) {
        return false;
    }
    va_list args;
    va_start(args, format);
    int added = vsnprintf(response_buffer + prefix_length,
                          sizeof(response_buffer) - (size_t)prefix_length,
                          format, args);
    va_end(args);
    if (added < 0) {
        return false;
    }
    size_t length = strnlen(response_buffer, sizeof(response_buffer));
    if (length + 2u >= sizeof(response_buffer)) {
        length = sizeof(response_buffer) - 3u;
    }
    response_buffer[length++] = '\r';
    response_buffer[length++] = '\n';
    return u4rk_usb_write_blocking(response_buffer, length,
                                    U4RK_CONTROL_TIMEOUT_MS);
}

static bool parse_metric(const char *text, unsigned axis, uint32_t maximum, uint32_t *out) {
    if (!text || !*text) return false;
    char *end;
    double value = strtod(text, &end);
    return end != text && *end == '\0' && gantry_mm_to_steps(axis, value, maximum, out);
}

static bool parse_u32(const char *text, uint32_t *value) {
    if (text == NULL || *text == '\0' || *text == '-') {
        return false;
    }
    char *end;
    unsigned long parsed = strtoul(text, &end, 10);
    if (*end != '\0' || parsed > UINT32_MAX) {
        return false;
    }
    *value = (uint32_t)parsed;
    return true;
}

static bool parse_register_value(const char *text, uint32_t *value) {
    if (!text || !*text || *text == '-') return false;
    char *end;
    errno = 0;
    unsigned long parsed = strtoul(text, &end, 0);
    if (errno == ERANGE || *end != '\0' || parsed > UINT32_MAX) return false;
    *value = (uint32_t)parsed;
    return true;
}

static bool parse_float(const char *text, float *value) {
    if (text == NULL || *text == '\0') {
        return false;
    }
    char *end;
    float parsed = strtof(text, &end);
    if (*end != '\0' || !isfinite(parsed)) {
        return false;
    }
    *value = parsed;
    return true;
}

static bool parse_payload_type(const char *text,
                               u4rk_payload_type_t *type) {
    if (text == NULL) {
        return false;
    }
    if (strcmp(text, "raw") == 0) {
        *type = U4RK_PAYLOAD_RAW;
    } else if (strcmp(text, "envelope") == 0) {
        *type = U4RK_PAYLOAD_ENVELOPE;
    } else if (strcmp(text, "alaw") == 0) {
        *type = U4RK_PAYLOAD_ALAW;
    } else {
        return false;
    }
    return true;
}

static uint32_t maximum_rate(u4rk_payload_type_t type) {
    switch (type) {
        case U4RK_PAYLOAD_RAW:
            return U4RK_RAW_MAX_RATE_HZ;
        case U4RK_PAYLOAD_ENVELOPE:
            return U4RK_ENVELOPE_MAX_RATE_HZ;
        case U4RK_PAYLOAD_ALAW:
            return U4RK_ALAW_MAX_RATE_HZ;
        default:
            return 0u;
    }
}

static bool operation_busy(void) {
    return capture_inflight || legacy_capture_pending || selftest_active ||
           output_slot_active || u4rk_usb_tx_busy() ||
           u4rk_pipeline_has_pending_output() ||
           !u4rk_pipeline_processing_idle();
}

/* Raw captures the long window; envelope/A-law use the fixed FFT length. */
static uint32_t sample_count_for(u4rk_payload_type_t type) {
    return (type == U4RK_PAYLOAD_ENVELOPE || type == U4RK_PAYLOAD_ALAW)
               ? U4RK_SAMPLE_COUNT
               : U4RK_RAW_SAMPLE_COUNT;
}

static bool begin_capture(u4rk_payload_type_t type, uint16_t extra_flags) {
    uint16_t *raw_buffer;
    uint8_t raw_index;
    if (!u4rk_pipeline_claim_raw(&raw_index, &raw_buffer)) {
        return false;
    }

    uint16_t flags = extra_flags;
    if (u4rk_pulser_is_armed()) {
        flags |= U4RK_FLAG_PULSER_ARMED;
    }
    uint32_t count = sample_count_for(type);
    capture_job = (u4rk_capture_job_t){
        .raw_index = raw_index,
        .payload_type = (uint8_t)type,
        .flags = flags,
        .sequence = next_sequence++,
        .session_id = usb_session_id,
        .sample_count = count,
        .sample_rate_hz = U4RK_SAMPLE_RATE_HZ,
        .capture_timestamp_us = time_us_64(),
        .alaw_reference = alaw_reference,
        .pulse = u4rk_pulser_get_config(),
    };
    if (!u4rk_capture_start(raw_buffer, count)) {
        u4rk_pipeline_release_raw(raw_index);
        return false;
    }
    capture_raw_index = raw_index;
    capture_inflight = true;
    return true;
}

static void poll_capture(void) {
    if (!capture_inflight) {
        return;
    }
    u4rk_capture_state_t state = u4rk_capture_poll();
    if (state == U4RK_CAPTURE_DONE) {
        capture_inflight = false;
        u4rk_pipeline_submit(&capture_job);
    } else if (state == U4RK_CAPTURE_DMA_FAULT) {
        capture_inflight = false;
        u4rk_pipeline_release_raw(capture_raw_index);
        stream.active = false;
        dma_fault_pending = true;
    }
}

static void drain_ready_outputs_as_drops(void) {
    uint8_t slot;
    const uint8_t *data;
    size_t size;
    uint32_t sequence;
    uint32_t session_id;
    while (u4rk_pipeline_take_output(
            &slot, &data, &size, &sequence, &session_id)) {
        (void)data;
        (void)size;
        if (selftest_frame_pending && session_id == usb_session_id &&
            sequence == selftest_pending_sequence) {
            selftest_active = false;
            selftest_frame_pending = false;
        }
        u4rk_pipeline_release_output(slot);
        u4rk_pipeline_note_usb_drop();
    }
}

static void advance_selftest(void) {
    selftest_frame_pending = false;
    if (selftest_type == U4RK_PAYLOAD_ALAW) {
        selftest_type = U4RK_PAYLOAD_RAW;
        ++selftest_case;
        if (selftest_case >= u4rk_dsp_selftest_count()) {
            selftest_active = false;
        }
    } else {
        selftest_type =
            (u4rk_payload_type_t)((uint8_t)selftest_type + 1u);
    }
}

static void poll_output(void) {
    if (output_slot_active && !u4rk_usb_tx_busy()) {
        bool failed = u4rk_usb_tx_take_failed();
        u4rk_pipeline_release_output(active_output_slot);
        output_slot_active = false;
        bool was_pending_selftest = selftest_frame_pending &&
            active_output_session == usb_session_id &&
            active_output_sequence == selftest_pending_sequence;
        if (failed) {
            u4rk_pipeline_note_usb_drop();
            if (was_pending_selftest) {
                selftest_active = false;
                selftest_frame_pending = false;
            }
        } else if (was_pending_selftest) {
            advance_selftest();
        }
    }

    if (!output_slot_active && !u4rk_usb_tx_busy() &&
        !stop_pending && !dma_fault_pending) {
        const uint8_t *data;
        size_t size;
        uint8_t slot;
        uint32_t sequence;
        uint32_t session_id;
        while (u4rk_pipeline_take_output(
                &slot, &data, &size, &sequence, &session_id)) {
            if (session_id != usb_session_id) {
                /* Core 1 may finish an old job after its CDC session closes. */
                u4rk_pipeline_release_output(slot);
                u4rk_pipeline_note_usb_drop();
                continue;
            }
            if (u4rk_usb_tx_start(data, size)) {
                output_slot_active = true;
                active_output_slot = slot;
                active_output_sequence = sequence;
                active_output_session = session_id;
            } else {
                u4rk_pipeline_release_output(slot);
                u4rk_pipeline_note_usb_drop();
                /* Never leave a failed self-test transfer permanently busy. */
                if (selftest_frame_pending &&
                    sequence == selftest_pending_sequence) {
                    selftest_active = false;
                    selftest_frame_pending = false;
                }
            }
            break;
        }
    }
}

static void poll_completions(void) {
    uint32_t sequence;
    while (u4rk_pipeline_take_completion(&sequence)) {
        if (legacy_capture_pending && sequence == legacy_capture_sequence) {
            legacy_capture_pending = false;
        }
    }
}

static void schedule_stream(void) {
    if (!stream.active || capture_inflight) {
        return;
    }
    uint64_t now = time_us_64();
    if (now < stream.next_capture_us) {
        return;
    }
    if (!begin_capture(stream.type, 0)) {
        u4rk_pipeline_note_processing_drop();
    }
    stream.next_capture_us += stream.interval_us;
    if (stream.next_capture_us <= now) {
        stream.next_capture_us = now + stream.interval_us;
    }
}

static void schedule_selftest(void) {
    if (!selftest_active || selftest_frame_pending || capture_inflight ||
        output_slot_active || u4rk_usb_tx_busy() ||
        u4rk_pipeline_has_pending_output()) {
        return;
    }

    uint8_t raw_index;
    uint16_t *raw_buffer;
    if (!u4rk_pipeline_claim_raw(&raw_index, &raw_buffer)) {
        return;
    }
    u4rk_dsp_make_selftest(selftest_case, raw_buffer);
    float reference =
        selftest_case == (u4rk_dsp_selftest_count() - 1u)
            ? 128.0f : alaw_reference;
    u4rk_capture_job_t job = {
        .raw_index = raw_index,
        .payload_type = (uint8_t)selftest_type,
        .flags = (uint16_t)(U4RK_FLAG_SELFTEST |
            ((uint16_t)selftest_case << U4RK_FLAG_SELFTEST_CASE_SHIFT)),
        .sequence = next_sequence++,
        .session_id = usb_session_id,
        .sample_count = U4RK_SAMPLE_COUNT,
        .sample_rate_hz = U4RK_SAMPLE_RATE_HZ,
        .capture_timestamp_us = selftest_case,
        .alaw_reference = reference,
        .pulse = u4rk_pulser_get_config(),
    };
    if (u4rk_pipeline_submit(&job)) {
        selftest_pending_sequence = job.sequence;
        selftest_frame_pending = true;
    }
}

static void stop_stream(void) {
    stream.active = false;
    u4rk_pulser_disarm();
    if (capture_inflight) {
        u4rk_capture_abort();
        capture_inflight = false;
        u4rk_pipeline_release_raw(capture_raw_index);
        u4rk_pipeline_note_processing_drop();
    }
    drain_ready_outputs_as_drops();
    stop_pending = true;
}

static void send_version(void) {
    char buf[192];
    int n = snprintf(buf, sizeof(buf),
        "pic0rick firmware v%s\r\n"
        "board:   Pico 2 (RP2350)\r\n"
        "dsp:     enabled\r\n"
        "mux:     not supported\r\n",
        PIC0RICK_FIRMWARE_VERSION);
    if (n > 0) {
        u4rk_usb_write_blocking(buf, (size_t)n, U4RK_CONTROL_TIMEOUT_MS);
    }
}

static void reboot_dfu(void) {
    motor_stop_all();
    send_ok("rebooting into USB bootloader (BOOTSEL)");
    sleep_ms(100);          /* let the CDC drain the reply */
    reset_usb_boot(0, 0);   /* does not return */
}

static void send_help(void) {
    send_ok(
        "commands=status|help|version|reboot-dfu|"
        "pulser arm/disarm|pulse config|dac write|dsp scale/selftest|"
        "acq <raw|envelope|alaw>|read_raw|read_fft|stream start/stop|"
        "jog_mm_x/y/z <direction> <mm/s>|"
        "move_mm_x/y/z <direction> <mm/s> <mm>|"
        "stop_x|stop_y|stop_z|stop_all|pos|geometry|home|pos_zero <axis>|goto_xy X Y SPEED|goto_status|"
        "tmc status|tmc read <motor> <reg>|tmc write <motor> <reg> <value>|"
        "tmc setup|i2c test|temp [test|stats]|scan_mm nx ny dx_mm dy_mm mm/s amp0 amp1 settle_ms flaw0 flaw1 averages tof0 tof1 threshold [waveforms] [centered]|scan stop");
}

static void send_status(void) {
    u4rk_pulse_config_t pulse = u4rk_pulser_get_config();
    u4rk_dsp_metrics_t metrics;
    u4rk_pipeline_get_metrics(&metrics);
    send_ok(
        "board=pic0rick package=RP2350A firmware=%s "
        "dsp_backend=f32-rfft-hilbert "
        "samples=%u sample_rate=%u "
        "pulser=%s pulse=%u/%u/%u/%s dac=%u scale=%.6g "
        "stream=%s/%u drops=%u stages_us=%u/%u/%u/%u/%u/%u "
        "dsp_us=%u worst_us=%u performance=%s "
        "envelope_max_rate=%u alaw_max_rate=%u cmsis=%s",
        PIC0RICK_FIRMWARE_VERSION,
        U4RK_SAMPLE_COUNT, U4RK_SAMPLE_RATE_HZ,
        u4rk_pulser_is_armed() ? "armed" : "disarmed",
        pulse.negative_ns, pulse.damp_ns, pulse.positive_ns,
        pulse.order == U4RK_PULSE_NEGATIVE_FIRST ? "neg-first" : "pos-first",
        u4rk_dac_last_value(), (double)alaw_reference,
        stream.active ? "on" : "off", stream.rate_hz,
        u4rk_pipeline_dropped_frames(),
        metrics.preprocess_us, metrics.forward_fft_us, metrics.mask_us,
        metrics.inverse_fft_us, metrics.magnitude_us, metrics.alaw_us,
        metrics.total_us, metrics.worst_total_us,
        metrics.worst_total_us <= U4RK_DSP_TARGET_US
            ? "ok" : "over-budget",
        U4RK_ENVELOPE_MAX_RATE_HZ, U4RK_ALAW_MAX_RATE_HZ,
        U4RK_CMSIS_DSP_VERSION);
}

static void legacy_read(void) {
    uint32_t sample_count = u4rk_pipeline_copy_latest_raw(legacy_read_buffer);
    if (sample_count == 0u) {
        send_error("NO_DATA", "no completed acquisition");
        return;
    }
    char prefix[32];
    int plen = snprintf(prefix, sizeof(prefix), "OK raw-hex %u\r\n",
                        (unsigned)sample_count);
    if (plen < 0 || !u4rk_usb_write_blocking(prefix, (size_t)plen,
                                             U4RK_CONTROL_TIMEOUT_MS)) {
        return;
    }
    char chunk[192];
    size_t used = 0;
    for (uint32_t i = 0; i < sample_count; ++i) {
        int count = snprintf(chunk + used, sizeof(chunk) - used, "%03X%s",
                             legacy_read_buffer[i],
                             i + 1u == sample_count ? "\r\n" : ",");
        if (count < 0) {
            return;
        }
        used += (size_t)count;
        if (used > sizeof(chunk) - 8u || i + 1u == sample_count) {
            if (!u4rk_usb_write_blocking(chunk, used,
                                         U4RK_CONTROL_TIMEOUT_MS)) {
                return;
            }
            used = 0;
        }
    }
}

typedef enum { GOTO_IDLE, GOTO_MOVING, GOTO_DONE, GOTO_FAILED } goto_state_t;
static goto_state_t goto_state;
static int32_t goto_x, goto_y, goto_expected_x, goto_expected_y;
static uint32_t goto_hz;
static uint64_t goto_deadline;
static bool goto_chunk_active;
static const char *goto_error = "none";

static bool goto_exact(void) {
    return positioning_is_homed(POSITION_AXIS_X) && positioning_is_homed(POSITION_AXIS_Y) &&
           positioning_is_exact(POSITION_AXIS_X) && positioning_is_exact(POSITION_AXIS_Y);
}

static void goto_fail(const char *reason) {
    motor_stop_all();
    goto_state = GOTO_FAILED;
    goto_chunk_active = false;
    goto_error = reason;
}

static void goto_poll(void) {
    if (goto_state != GOTO_MOVING) return;
    if (!tmc_motion_ready(POSITION_AXIS_X)) { goto_fail("bridge"); return; }
    if (motor_any_active()) {
        if (time_us_64() > goto_deadline) goto_fail("timeout");
        return;
    }
    if (!goto_exact()) { goto_fail("position_invalid"); return; }
    int32_t x = positioning_get_steps(POSITION_AXIS_X);
    int32_t y = positioning_get_steps(POSITION_AXIS_Y);
    if (goto_chunk_active && (x != goto_expected_x || y != goto_expected_y)) {
        goto_fail("position_mismatch"); return;
    }
    goto_chunk_active = false;
    if (x == goto_x && y == goto_y) { goto_state = GOTO_DONE; return; }
    bool axis_x = x != goto_x;
    int32_t delta = axis_x ? goto_x - x : goto_y - y;
    uint32_t steps = (uint32_t)(delta > 0 ? delta : -delta);
    if (steps > MAX_STEPS) steps = MAX_STEPS;
    int32_t signed_steps = delta > 0 ? (int32_t)steps : -(int32_t)steps;
    goto_expected_x = x + (axis_x ? signed_steps : 0);
    goto_expected_y = y + (axis_x ? 0 : signed_steps);
    char args[64];
    snprintf(args, sizeof(args), "%s %lu %lu", delta > 0 ? "plus" : "minus",
             (unsigned long)goto_hz, (unsigned long)steps);
    if (!(axis_x ? move_x(args) : move_y(args))) { goto_fail("move_rejected"); return; }
    uint32_t slow_hz = goto_hz < START_FREQ_HZ ? goto_hz : START_FREQ_HZ;
    goto_deadline = time_us_64() + (uint64_t)steps * 1000000u / slow_hz + 15000000u;
    goto_chunk_active = true;
}

static void process_command(char *line) {
    char *save;
    char *first = strtok_r(line, " \t", &save);
    if (first == NULL) {
        return;
    }

    if (strcmp(first, "goto_status") == 0 || strcmp(first, "goto_xy") == 0) {
        if (scan_active() || stream.active) {
            send_error("BUSY", "scan or stream active");
            return;
        }
        if (strcmp(first, "goto_status") == 0) {
            const char *state = goto_state == GOTO_MOVING ? "moving" :
                goto_state == GOTO_DONE ? "done" : goto_state == GOTO_FAILED ? "failed" : "idle";
            send_ok("goto=%s error=%s", state, goto_error);
            return;
        }
        if (goto_state == GOTO_MOVING || motor_any_active() || motor_is_homing_xy() || operation_busy()) {
            send_error("BUSY", "wait for motors and acquisition to stop");
            return;
        }
        if (!tmc_motion_ready(POSITION_AXIS_X)) {
            send_error("BRIDGE", "all five drivers must be ready");
            return;
        }
        if (!goto_exact()) { send_error("HOME", "home X/Y first"); return; }
        char *xt = strtok_r(NULL, " \t", &save);
        char *yt = strtok_r(NULL, " \t", &save);
        char *st = strtok_r(NULL, " \t", &save);
        uint32_t x, y, speed;
        if (!parse_metric(xt, 0, X_MAX_POSITION_STEPS, &x) ||
            !parse_metric(yt, 1, Y_MAX_POSITION_STEPS, &y) ||
            !parse_metric(st, 0, MAX_MOTOR_FREQ_HZ, &speed) || !speed ||
            strtok_r(NULL, " \t", &save)) {
            send_error("ARG", "goto_xy X_FROM_HOME_MM Y_FROM_HOME_MM MM_S");
            return;
        }
        goto_x = (int32_t)x;
        goto_y = (int32_t)y;
        goto_hz = speed;
        goto_chunk_active = false;
        goto_error = "none";
        goto_state = GOTO_MOVING;
        if (!send_ok("goto=moving x=%.3f y=%.3f", gantry_steps_to_mm(0, goto_x), gantry_steps_to_mm(1, goto_y)))
            goto_fail("usb");
        return;
    }
    if (goto_state == GOTO_MOVING) {
        if (strcmp(first, "stop_all") == 0 || strcmp(first, "stop_x") == 0 ||
            strcmp(first, "stop_y") == 0 || strcmp(first, "stop_z") == 0) {
            goto_fail("stopped");
            send_ok("goto=failed error=stopped");
            return;
        }
        if (strcmp(first, "pos") != 0 && strcmp(first, "geometry") != 0) {
            send_error("BUSY", "positioning active; use stop_all");
            return;
        }
    }

    if (strcmp(first, "scan") == 0 || strcmp(first, "scan_mm") == 0) {
        char *arg = strtok_r(NULL, " \t", &save);
        if (arg && strcmp(arg, "stop") == 0) {
            scan_abort();
            return;
        }
        if (strcmp(first, "scan_mm") != 0) {
            send_error("ARG", "use scan_mm with metric spacing and speed");
            return;
        }
        uint32_t values[14] = {0};
        bool valid = parse_u32(arg, &values[0]);
        for (unsigned i = 1; i < 14; ++i) {
            arg = strtok_r(NULL, " \t", &save);
            if (i == 2 || i == 3 || i == 4)
                valid = parse_metric(arg, i == 3 ? 1u : 0u,
                                     i == 4 ? MAX_MOTOR_FREQ_HZ : MAX_STEPS, &values[i]) && valid;
            else valid = parse_u32(arg, &values[i]) && valid;
        }
        bool send_waveforms = false, centered = false;
        char *extra;
        while ((extra = strtok_r(NULL, " \t", &save)) != NULL) {
            if (!send_waveforms && strcmp(extra, "waveforms") == 0) send_waveforms = true;
            else if (!centered && strcmp(extra, "centered") == 0) centered = true;
            else valid = false;
        }
        if (!valid) {
            send_error("ARG", "scan_mm nx ny dx_mm dy_mm mm/s amp0 amp1 settle_ms flaw0 flaw1 averages tof0 tof1 threshold [waveforms] [centered]");
            return;
        }
        scan_config_t cfg = {
            .nx = values[0], .ny = values[1],
            .dx_steps = values[2], .dy_steps = values[3],
            .speed_hz = values[4], .gate_start = values[5],
            .gate_end = values[6], .settle_ms = values[7],
            .flaw_gate_start = values[8], .flaw_gate_end = values[9],
            .averages = values[10], .tof_gate_start = values[11],
            .tof_gate_end = values[12], .tof_threshold = values[13],
            .send_waveforms = send_waveforms, .centered = centered,
        };
        if (operation_busy() || stream.active) {
            send_error("BUSY", "acquisition or transfer in progress");
            return;
        }
        const char *error = NULL;
        if (!tmc_motion_ready(POSITION_AXIS_X)) {
            send_error("BRIDGE", "scan requires all five drivers; tmc status / tmc setup");
            return;
        }
        if (!scan_start(&cfg, &error)) {
            send_error("SCAN", "%s", error ? error : "cannot start");
            return;
        }
        if (!send_ok("scan started nx=%lu ny=%lu sample_rate=60000000 dx_mm=%.3f dy_mm=%.3f",
                     (unsigned long)cfg.nx, (unsigned long)cfg.ny,
                     gantry_steps_to_mm(0, cfg.dx_steps), gantry_steps_to_mm(1, cfg.dy_steps))) {
            scan_abort();
        }
        return;
    }
    if (scan_active()) {
        if (strcmp(first, "stop_all") == 0 ||
            strcmp(first, "stop_x") == 0 ||
            strcmp(first, "stop_y") == 0 ||
            strcmp(first, "stop_z") == 0) {
            scan_abort();
        } else {
            send_error("BUSY", "scan active; use scan stop");
        }
        return;
    }


    if (strcmp(first, "temp") == 0) {
        char *second = strtok_r(NULL, " \t", &save);
        if (second != NULL && (strcmp(second, "test") != 0 && strcmp(second, "stats") != 0)) {
            send_error("ARG", "temp [test|stats]");
            return;
        }
        if (second != NULL && strtok_r(NULL, " \t", &save) != NULL) {
            send_error("ARG", "temp [test|stats]");
            return;
        }
        if (second != NULL) {
            const bool testing = strcmp(second, "test") == 0;
            if (testing && (motor_any_active() || motor_is_homing_xy() || scan_active() || operation_busy() || stream.active)) {
                send_error("BUSY", "temperature test requires idle motors");
                return;
            }
            if (testing) (void)temperature_test();
            const temperature_stats_t *t = temperature_stats();
            send_ok("temp attempts=%lu valid=%lu resets=%lu tests=%lu no_presence=%lu crc_fail=%lu invalid=%lu io_fail=%lu "
                    "idle=%u presence=%u reset_low_us=%lu presence_read_us=%lu write1_low_us=%lu "
                    "read_sample_us=%lu sample=%u last=%s",
                    (unsigned long)t->attempts, (unsigned long)t->valid,
                    (unsigned long)t->resets, (unsigned long)t->tests,
                    (unsigned long)t->no_presence, (unsigned long)t->crc_fail,
                    (unsigned long)t->invalid_data, (unsigned long)t->io_fail,
                    (unsigned)t->idle_high, (unsigned)t->presence,
                    (unsigned long)t->reset_low_us, (unsigned long)t->presence_read_us,
                    (unsigned long)t->write1_low_us, (unsigned long)t->read_sample_us,
                    (unsigned)t->sample_high, temperature_error());
            return;
        }
        if (motor_any_active() || motor_is_homing_xy() || operation_busy() || stream.active) {
            send_ok("temp=pending");
            return;
        }
        float degrees_c = 0.0f;
        temperature_result_t result = temperature_poll(&degrees_c);
        if (result == TEMPERATURE_READY) send_ok("temp_c=%.2f", (double)degrees_c);
        else if (result == TEMPERATURE_PENDING) send_ok("temp=pending");
        else send_error("TEMP", "%s", temperature_error());
        return;
    }

    if (strcmp(first, "geometry") == 0) {
        send_ok("units=mm speed=mm/s microsteps=%u x_steps_per_mm=%u y_steps_per_mm=%u z_steps_per_mm=%u xmax=%.3f ymax=%.3f max_move_mm=%.3f",
                (unsigned)GANTRY_MICROSTEPS, (unsigned)GANTRY_XY_STEPS_PER_MM,
                (unsigned)GANTRY_XY_STEPS_PER_MM, (unsigned)GANTRY_Z_STEPS_PER_MM,
                gantry_steps_to_mm(0, X_MAX_POSITION_STEPS), gantry_steps_to_mm(1, Y_MAX_POSITION_STEPS),
                gantry_steps_to_mm(0, MAX_STEPS));
        return;
    }
    if (strcmp(first, "pos") == 0) {
        send_ok("units=mm x=%.3f y=%.3f z=%.3f homed=%u/%u/%u exact=%u/%u/%u "
                "limit_x0=%u limit_y0=%u xmax=%.3f ymax=%.3f zmax=%.3f home=%s",
                gantry_steps_to_mm(0, positioning_get_steps(POSITION_AXIS_X)),
                gantry_steps_to_mm(1, positioning_get_steps(POSITION_AXIS_Y)),
                gantry_steps_to_mm(2, positioning_get_steps(POSITION_AXIS_Z)),
                positioning_is_homed(POSITION_AXIS_X),
                positioning_is_homed(POSITION_AXIS_Y),
                positioning_is_homed(POSITION_AXIS_Z),
                positioning_is_exact(POSITION_AXIS_X),
                positioning_is_exact(POSITION_AXIS_Y),
                positioning_is_exact(POSITION_AXIS_Z),
                positioning_switch_active(POSITION_AXIS_X),
                positioning_switch_active(POSITION_AXIS_Y),
                gantry_steps_to_mm(0, X_MAX_POSITION_STEPS),
                gantry_steps_to_mm(1, Y_MAX_POSITION_STEPS),
                gantry_steps_to_mm(2, Z_MAX_POSITION_STEPS),
                motor_home_status());
        return;
    }
    if (strcmp(first, "pos_zero") == 0) {
        char *arg = strtok_r(NULL, " \t", &save);
        if (motor_any_active() || motor_is_homing_xy()) {
            send_error("BUSY", "stop all motors before zeroing position");
        } else if (arg == NULL) {
            send_error("ARG", "expected x, y, z, or all");
        } else if (strcmp(arg, "x") == 0) {
            if (positioning_switch_active(POSITION_AXIS_X)) {
                positioning_set_zero(POSITION_AXIS_X);
                send_ok("pos_zero x");
            } else send_error("LIMIT", "X zero switch is not pressed");
        } else if (strcmp(arg, "y") == 0) {
            if (positioning_switch_active(POSITION_AXIS_Y)) {
                positioning_set_zero(POSITION_AXIS_Y);
                send_ok("pos_zero y");
            } else send_error("LIMIT", "Y zero switch is not pressed");
        } else if (strcmp(arg, "z") == 0) {
            positioning_set_zero(POSITION_AXIS_Z);
            send_ok("pos_zero z");
        } else if (strcmp(arg, "all") == 0) {
            if (positioning_switch_active(POSITION_AXIS_X) &&
                positioning_switch_active(POSITION_AXIS_Y)) {
                positioning_set_zero(POSITION_AXIS_X);
                positioning_set_zero(POSITION_AXIS_Y);
                positioning_set_zero(POSITION_AXIS_Z);
                send_ok("pos_zero all");
            } else send_error("LIMIT", "both X and Y switches must be pressed");
        } else {
            send_error("ARG", "expected x, y, z, or all");
        }
        return;
    }

    if (strcmp(first, "home") == 0) {
        if (motor_is_homing_xy() || motor_any_active()) {
            send_error("BUSY", "stop motors before homing");
        } else if (!tmc_motion_ready(POSITION_AXIS_X)) {
            send_error("BRIDGE", "homing requires all five drivers; tmc status / tmc setup");
        } else if (motor_home_xy()) {
            send_ok("home started");
        } else {
            send_error("HOME", "homing could not start");
        }
        return;
    }

    if (strcmp(first, "stop_x") == 0) {
        stop_x(NULL);
        if (!stream.active) send_ok("stop_x");
        return;
    }
    if (strcmp(first, "stop_y") == 0) {
        stop_y(NULL);
        if (!stream.active) send_ok("stop_y");
        return;
    }
    if (strcmp(first, "stop_z") == 0) {
        stop_z(NULL);
        if (!stream.active) send_ok("stop_z");
        return;
    }
    if (strcmp(first, "stop_all") == 0) {
        motor_stop_all();
        if (!stream.active) send_ok("stop_all");
        return;
    }

    if (stream.active) {
        char *second = strtok_r(NULL, " \t", &save);
        if (strcmp(first, "stream") == 0 && second != NULL &&
            strcmp(second, "stop") == 0) {
            stop_stream();
        }
        return;
    }

    if (strcmp(first, "i2c") == 0) {
        char *action = strtok_r(NULL, " \t", &save);
        if (!action || strcmp(action, "test") != 0 || strtok_r(NULL, " \t", &save)) {
            send_error("ARG", "i2c test");
            return;
        }
        if (motor_any_active() || motor_is_homing_xy()) {
            send_error("BUSY", "stop all motors before I2C test");
            return;
        }
        uint8_t control = 0;
        uint32_t hz = 0;
        if (bridge_i2c_test(&control, &hz))
            send_ok("i2c addr=0x%02X hz=%lu iocontrol=0x%02X scratch=PASS restore=OK",
                    BRIDGE_I2C_ADDRESS, (unsigned long)hz, control);
        else send_error("I2C", "%s hz=%lu", bridge_error(), (unsigned long)hz);
        return;
    }

    if (strcmp(first, "tmc") == 0) {
        char *action = strtok_r(NULL, " \t", &save);
        if (!action) {
            send_error("ARG", "tmc status|read <x1|x2|y1|y2|z> <reg>|write <motor> <reg> <value>|setup");
            return;
        }
        if (motor_any_active() || motor_is_homing_xy()) {
            send_error("BUSY", "stop all motors before accessing TMC registers");
            return;
        }
        if (strcmp(action, "setup") == 0) {
            if (!bridge_setup_motors()) {
                send_error("BRIDGE", "tmc setup failed: %s", bridge_error());
            } else {
                send_ok("tmc setup drivers=5 microsteps=%u baud=%u xy=ready z=ready", (unsigned)GANTRY_MICROSTEPS, BRIDGE_UART_BAUD);
            }
            return;
        }
        if (strcmp(action, "status") == 0) {
            uint8_t gpio_state = 0;
            const bool read_ok = bridge_gpio_read(&gpio_state);
            uint8_t mask = 0;
            for (unsigned i = 0; i < TMC_COUNT; ++i) {
                if (tmc_motor_online((tmc_motor_t)i)) mask |= (1u << i);
            }
            send_ok("bridge=%s address=0x%02X baud=%u online_mask=0x%02X "
                    "gpio=%s0x%02X irq=%u xy=%s z=%s error=%s",
                    bridge_ready() ? "ready" : "offline", BRIDGE_I2C_ADDRESS,
                    BRIDGE_UART_BAUD, mask, read_ok ? "" : "unavailable/",
                    gpio_state, bridge_irq_asserted(),
                    tmc_motion_ready(POSITION_AXIS_X) ? "ready" : "blocked",
                    tmc_motion_ready(POSITION_AXIS_Z) ? "ready" : "blocked", bridge_error());
            return;
        }
        if (strcmp(action, "read") != 0 && strcmp(action, "write") != 0) {
            send_error("ARG", "tmc action must be status, read, write, or setup");
            return;
        }
        const bool writing = strcmp(action, "write") == 0;
        char *motor_arg = strtok_r(NULL, " \t", &save);
        char *reg_arg = strtok_r(NULL, " \t", &save);
        char *val_arg = writing ? strtok_r(NULL, " \t", &save) : NULL;
        tmc_motor_t motor;
        uint32_t reg, value = 0;
        if (!tmc_motor_from_name(motor_arg, &motor) ||
            !parse_register_value(reg_arg, &reg) || reg > 0x7Fu ||
            (writing && !parse_register_value(val_arg, &value)) ||
            strtok_r(NULL, " \t", &save)) {
            send_error("ARG", "tmc read <x1|x2|y1|y2|z> <0x00..0x7f> or tmc write <motor> <reg> <value>");
            return;
        }
        if (!bridge_ready()) {
            send_error("BRIDGE", "%s", bridge_error());
            return;
        }
        if (writing && ((reg == 0x00u && !(value & (1u << 7))) ||
                        (reg == 0x6Cu && (((value >> 24) & 15u) != GANTRY_MRES || (value & (1u << 29)))))) {
            send_error("ARG", "microstep resolution is locked to firmware geometry");
            return;
        }
        if (writing && (motor_any_active() || motor_is_homing_xy())) {
            send_error("BUSY", "stop motors before writing driver registers");
            return;
        }
        bool ok = writing ? tmc_write(motor, (uint8_t)reg, value) :
                            tmc_read(motor, (uint8_t)reg, &value);
        if (ok) {
            send_ok("tmc %s motor=%s reg=0x%02X value=0x%08lX",
                    action, tmc_motor_name(motor), (unsigned)reg,
                    (unsigned long)value);
        } else {
            send_error("BRIDGE", "tmc %s %s failed: %s", action,
                       tmc_motor_name(motor), bridge_error());
        }
        return;
    }

    bool jogging = strncmp(first, "jog_mm_", 7) == 0;
    bool moving = strncmp(first, "move_mm_", 8) == 0;
    if (jogging || moving) {
        const char *axis_name = first + (jogging ? 7 : 8);
        if ((*axis_name != 'x' && *axis_name != 'y' && *axis_name != 'z') || axis_name[1]) {
            send_error("ARG", "invalid motion axis");
            return;
        }
        unsigned axis = *axis_name == 'x' ? 0u : *axis_name == 'y' ? 1u : 2u;
        if (motor_is_homing_xy()) {
            send_error("BUSY", "X/Y homing in progress");
            return;
        }
        char *dir = strtok_r(NULL, " \t", &save);
        char *speed = strtok_r(NULL, " \t", &save);
        char *distance = moving ? strtok_r(NULL, " \t", &save) : NULL;
        uint32_t hz = 0, steps = 0;
        if (!dir || strlen(dir) > 15 || !parse_metric(speed, axis, MAX_MOTOR_FREQ_HZ, &hz) || !hz ||
            (moving && (!parse_metric(distance, axis, MAX_STEPS, &steps) || !steps)) ||
            strtok_r(NULL, " \t", &save)) {
            send_error("ARG", "motion requires direction, speed in mm/s and (for move) distance in mm");
            return;
        }
        char args[64];
        if (moving) snprintf(args, sizeof(args), "%s %lu %lu", dir, (unsigned long)hz, (unsigned long)steps);
        else snprintf(args, sizeof(args), "%s %lu", dir, (unsigned long)hz);
        bool ok = jogging ? (axis == 0 ? jog_x(args) : axis == 1 ? jog_y(args) : jog_z(args)) :
                           (axis == 0 ? move_x(args) : axis == 1 ? move_y(args) : move_z(args));
        if (ok && moving) send_ok("%s speed_mm_s=%.3f distance_mm=%.3f", first,
                                   gantry_steps_to_mm(axis, hz), gantry_steps_to_mm(axis, steps));
        else if (ok) send_ok("%s speed_mm_s=%.3f", first, gantry_steps_to_mm(axis, hz));
        else if (!tmc_motion_ready(axis)) send_error("BRIDGE", "axis drivers not ready; tmc status / tmc setup (%s)", bridge_error());
        else if (axis < 2 && !positioning_is_homed((position_axis_t)axis)) send_error("HOME", "home X/Y before finite moves or if unhomed jog limit reached");
        else send_error("ARG", "invalid direction or travel limit (max speed %.3f mm/s; max finite distance %.3f mm)",
                        gantry_steps_to_mm(axis, MAX_MOTOR_FREQ_HZ), gantry_steps_to_mm(axis, MAX_STEPS));
        return;
    }
    if (!strncmp(first, "jog_", 4) || !strncmp(first, "move_", 5)) {
        send_error("ARG", "use jog_mm_x/y/z or move_mm_x/y/z with mm/s and mm");
        return;
    }

    char *second = strtok_r(NULL, " \t", &save);
    if (strcmp(first, "help") == 0 && second == NULL) {
        send_help();
        return;
    }
    if (strcmp(first, "status") == 0 && second == NULL) {
        send_status();
        return;
    }

    if (strcmp(first, "version") == 0 && second == NULL) {
        send_version();
        return;
    }

    if (strcmp(first, "reboot-dfu") == 0 && second == NULL) {
        if (operation_busy()) {
            send_error("BUSY", "operation in progress");
        } else {
            reboot_dfu();
        }
        return;
    }



    if (strcmp(first, "pulser") == 0 && second != NULL) {
        if (operation_busy()) {
            send_error("BUSY", "operation in progress");
        } else if (strcmp(second, "arm") == 0) {
            u4rk_pulser_arm();
            send_ok("pulser armed");
        } else if (strcmp(second, "disarm") == 0) {
            u4rk_pulser_disarm();
            send_ok("pulser disarmed");
        } else {
            send_error("ARG", "expected arm or disarm");
        }
        return;
    }

    if (strcmp(first, "pulse") == 0 && second != NULL &&
        strcmp(second, "config") == 0) {
        if (operation_busy()) {
            send_error("BUSY", "operation in progress");
            return;
        }
        char *negative_text = strtok_r(NULL, " \t", &save);
        char *damp_text = strtok_r(NULL, " \t", &save);
        char *positive_text = strtok_r(NULL, " \t", &save);
        char *order_text = strtok_r(NULL, " \t", &save);
        char *extra = strtok_r(NULL, " \t", &save);
        uint32_t negative_ns, damp_ns, positive_ns;
        u4rk_pulse_order_t order;
        if (!parse_u32(negative_text, &negative_ns) ||
            !parse_u32(damp_text, &damp_ns) ||
            !parse_u32(positive_text, &positive_ns) ||
            order_text == NULL || extra != NULL) {
            send_error("ARG", "invalid pulse configuration");
            return;
        }
        if (strcmp(order_text, "neg-first") == 0) {
            order = U4RK_PULSE_NEGATIVE_FIRST;
        } else if (strcmp(order_text, "pos-first") == 0) {
            order = U4RK_PULSE_POSITIVE_FIRST;
        } else {
            send_error("ARG", "order must be neg-first or pos-first");
            return;
        }
        if (!u4rk_pulser_configure(
                negative_ns, damp_ns, positive_ns, order)) {
            send_error("RANGE", "minimum is 40/40/40 ns");
            return;
        }
        u4rk_pulse_config_t actual = u4rk_pulser_get_config();
        send_ok("pulse=%u/%u/%u/%s", actual.negative_ns, actual.damp_ns,
                actual.positive_ns,
                actual.order == U4RK_PULSE_NEGATIVE_FIRST
                    ? "neg-first" : "pos-first");
        return;
    }

    if (strcmp(first, "dac") == 0 && second != NULL &&
        strcmp(second, "write") == 0) {
        char *value_text = strtok_r(NULL, " \t", &save);
        char *extra = strtok_r(NULL, " \t", &save);
        uint32_t value;
        if (operation_busy()) {
            send_error("BUSY", "operation in progress");
        } else if (!parse_u32(value_text, &value) ||
                   value > 1023u || extra != NULL) {
            send_error("RANGE", "DAC value must be 0..1023");
        } else {
            u4rk_dac_write((uint16_t)value);
            send_ok("dac=%u", value);
        }
        return;
    }

    if (strcmp(first, "dsp") == 0 && second != NULL) {
        if (strcmp(second, "scale") == 0) {
            char *reference_text = strtok_r(NULL, " \t", &save);
            char *extra = strtok_r(NULL, " \t", &save);
            float reference;
            if (operation_busy()) {
                send_error("BUSY", "operation in progress");
            } else if (!parse_float(reference_text, &reference) ||
                       reference <= 0.0f || reference > 65535.0f ||
                       extra != NULL) {
                send_error("RANGE", "reference must be in (0,65535]");
            } else {
                alaw_reference = reference;
                send_ok("scale=%.6g", (double)alaw_reference);
            }
        } else if (strcmp(second, "selftest") == 0) {
            if (operation_busy()) {
                send_error("BUSY", "operation in progress");
            } else {
                selftest_active = true;
                selftest_frame_pending = false;
                selftest_case = 0;
                selftest_type = U4RK_PAYLOAD_RAW;
                send_ok("selftest frames=%u cases=%u",
                        (unsigned)u4rk_dsp_selftest_count() * 3u,
                        u4rk_dsp_selftest_count());
            }
        } else {
            send_error("ARG", "expected scale or selftest");
        }
        return;
    }

    if (strcmp(first, "acq") == 0 && second != NULL) {
        u4rk_payload_type_t type;
        if (operation_busy()) {
            send_error("BUSY", "operation in progress");
        } else if (!parse_payload_type(second, &type)) {
            send_error("ARG", "type must be raw, envelope, or alaw");
        } else if (!begin_capture(type, 0)) {
            send_error("BUSY", "no acquisition buffer");
        } else {
            send_ok("capture started type=%s", second);
        }
        return;
    }

    /* read_raw: one-shot 8000-sample raw ADC capture (no FFT). */
    if (strcmp(first, "read_raw") == 0 && second == NULL) {
        if (operation_busy()) {
            send_error("BUSY", "operation in progress");
        } else if (!begin_capture(U4RK_PAYLOAD_RAW, 0)) {
            send_error("BUSY", "no acquisition buffer");
        } else {
            send_ok("capture started type=raw samples=%u",
                    (unsigned)U4RK_RAW_SAMPLE_COUNT);
        }
        return;
    }

    /* read_fft: one-shot 4096-sample Hilbert-envelope capture. */
    if (strcmp(first, "read_fft") == 0 && second == NULL) {
        if (operation_busy()) {
            send_error("BUSY", "operation in progress");
        } else if (!begin_capture(U4RK_PAYLOAD_ENVELOPE, 0)) {
            send_error("BUSY", "no acquisition buffer");
        } else {
            send_ok("capture started type=envelope samples=%u",
                    (unsigned)U4RK_SAMPLE_COUNT);
        }
        return;
    }

    if (strcmp(first, "stream") == 0 && second != NULL &&
        strcmp(second, "start") == 0) {
        char *type_text = strtok_r(NULL, " \t", &save);
        char *rate_text = strtok_r(NULL, " \t", &save);
        char *extra = strtok_r(NULL, " \t", &save);
        u4rk_payload_type_t type;
        uint32_t rate;
        if (operation_busy()) {
            send_error("BUSY", "operation in progress");
        } else if (!parse_payload_type(type_text, &type) ||
                   !parse_u32(rate_text, &rate) || extra != NULL) {
            send_error("ARG", "expected type and integer rate");
        } else if (rate < 1u || rate > maximum_rate(type)) {
            send_error("RATE", "allowed rate is 1..%u Hz",
                       maximum_rate(type));
        } else {
            send_ok("stream started type=%s rate=%u", type_text, rate);
            stream.active = true;
            stream.type = type;
            stream.rate_hz = rate;
            stream.interval_us = 1000000u / rate;
            stream.next_capture_us = time_us_64();
        }
        return;
    }

    if (strcmp(first, "stream") == 0 && second != NULL &&
        strcmp(second, "stop") == 0) {
        send_ok("stream already stopped");
        return;
    }

    if (strcmp(first, "start") == 0 && second != NULL &&
        strcmp(second, "acq") == 0) {
        if (operation_busy()) {
            send_error("BUSY", "operation in progress");
        } else if (!begin_capture(U4RK_PAYLOAD_NONE, 0)) {
            send_error("BUSY", "no acquisition buffer");
        } else {
            legacy_capture_pending = true;
            legacy_capture_sequence = capture_job.sequence;
            send_ok("legacy acquisition started");
        }
        return;
    }

    if (strcmp(first, "read") == 0 && second == NULL) {
        if (operation_busy()) {
            send_error("BUSY", "operation in progress");
        } else {
            legacy_read();
        }
        return;
    }

    send_error("COMMAND", "unknown command");
}

static void poll_command_input(void) {
    /*
     * During a stream, input is still consumed so "stream stop" always works.
     * During a one-shot binary response, defer parsing to avoid mixing text
     * into a frame already in flight.
     */
    if (!stream.active &&
        (output_slot_active || u4rk_usb_tx_busy() ||
         u4rk_pipeline_has_pending_output())) {
        return;
    }

    int character;
    while ((character = u4rk_usb_read_char()) >= 0) {
        if (character == '\r' || character == '\n') {
            if (command_length != 0u) {
                command_buffer[command_length] = '\0';
                process_command(command_buffer);
                command_length = 0;
            }
        } else if ((character == '\b' || character == 127) &&
                   command_length != 0u) {
            --command_length;
        } else if (character >= 32 && character <= 126) {
            if (command_length + 1u < sizeof(command_buffer)) {
                command_buffer[command_length++] = (char)character;
            } else {
                command_length = 0;
                if (!stream.active) {
                    send_error("LINE", "command too long");
                }
            }
        }
    }
}

static void finish_stop_or_fault(void) {
    /* This cleanup path is destructive: it deliberately discards every
     * completed output frame.  Run it only while finishing an explicit
     * stream stop or reporting a DMA fault.  Without this guard, a Core 1
     * result that became ready just after poll_output() was silently drained
     * during normal acquisition and self-test operation. */
    if (!stop_pending && !dma_fault_pending) {
        return;
    }
    if (output_slot_active || u4rk_usb_tx_busy()) {
        return;
    }
    drain_ready_outputs_as_drops();
    if (!u4rk_pipeline_processing_idle()) {
        return;
    }
    /* A just-finished DSP job may have populated the ready queue. */
    drain_ready_outputs_as_drops();
    if (stop_pending) {
        stop_pending = false;
        send_ok("stream stopped drops=%u",
                u4rk_pipeline_dropped_frames());
    } else if (dma_fault_pending) {
        dma_fault_pending = false;
        send_error("DMA", "acquisition timeout; pulser disarmed");
    }
}

static void cancel_usb_session(void) {
    /* Invalidate queued/in-flight Core 1 jobs before releasing USB slots. */
    ++usb_session_id;
    if (usb_session_id == 0u) {
        usb_session_id = 1u;
    }
    stream.active = false;
    stop_pending = false;
    dma_fault_pending = false;
    selftest_active = false;
    selftest_frame_pending = false;
    legacy_capture_pending = false;
    command_length = 0;
    scan_abort();
    u4rk_capture_abort();
    if (capture_inflight) {
        u4rk_pipeline_release_raw(capture_raw_index);
        capture_inflight = false;
    }
    u4rk_usb_tx_cancel();
    if (output_slot_active) {
        u4rk_pipeline_release_output(active_output_slot);
        output_slot_active = false;
        u4rk_pipeline_note_usb_drop();
    }
    drain_ready_outputs_as_drops();
}

static void handle_disconnect(void) {
    bool mounted = u4rk_usb_mounted();
    if (usb_was_mounted && !mounted) {
        if (goto_state == GOTO_MOVING) goto_fail("usb_disconnect");
        else motor_stop_all();
        cancel_usb_session();
    }
    usb_was_mounted = mounted;
}

int main(void) {
    bi_decl(bi_program_description(
        "pic0rick RP2350A 4096-sample Hilbert envelope and A-law firmware"));
    bi_decl(bi_pin_mask_with_name(0x7ffu, "ADC clock GPIO0 and data GPIO1..10"));
    bi_decl(bi_3pins_with_names(
        U4RK_DAC_CS_PIN, "MCP4812 CS",
        U4RK_DAC_SCK_PIN, "MCP4812 SCK",
        U4RK_DAC_TX_PIN, "MCP4812 MOSI"));
    bi_decl(bi_2pins_with_names(
        U4RK_PULSER_PP_PIN, "PMOD pulser P+",
        U4RK_PULSER_PN_PIN, "PMOD pulser P-"));
    bi_decl(bi_2pins_with_names(
        U4RK_PULSER_PDAMP_PIN, "PMOD pulser PDAMP",
        U4RK_PULSER_OE_PIN, "PMOD pulser OE"));

    /*
     * Pulser safety comes first: all four control pins are driven low before
     * DSP-table generation, USB enumeration, or any command handling.
     */
    u4rk_acquisition_init();
    u4rk_dac_init();
    if (!u4rk_pipeline_init()) {
        u4rk_pulser_disarm();
        while (true) {
            tight_loop_contents();
        }
    }
    multicore_launch_core1(u4rk_pipeline_core1_entry);
    if (!u4rk_usb_init()) {
        u4rk_pulser_disarm();
        while (true) {
            tight_loop_contents();
        }
    }

    motor_setup();

    while (true) {
        motor_service();
        u4rk_usb_task();
        handle_disconnect();
        poll_capture();
        poll_completions();
        poll_output();
        finish_stop_or_fault();
        poll_command_input();
        scan_poll();
        goto_poll();
        schedule_stream();
        schedule_selftest();
        tight_loop_contents();
    }
}
