#ifndef SCAN_CENTERED_H
#define SCAN_CENTERED_H
#include <stdbool.h>
#include <stdint.h>

static inline bool scan_center_axis(int32_t minimum, int32_t maximum,
                                    uint32_t count, uint32_t pitch,
                                    int32_t *origin)
{
    if (minimum < 0 || maximum < minimum || count == 0 || (count > 1 && !pitch)) return false;
    const uint64_t span = (uint64_t)(count - 1u) * pitch;
    if (span > (uint64_t)((int64_t)maximum - minimum)) return false;
    *origin = (int32_t)(((int64_t)minimum + maximum + (int64_t)span + 1) / 2);
    return true;
}
#endif
