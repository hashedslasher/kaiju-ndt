# Kaiju ultrasonic lab suite — Pico 2 DSP firmware

Run from `python-tools/`. This adds new tests but does not modify the A-scan viewer.

## Equipment / starting conditions

- 10 MHz, nominal 3-inch spherical-focus immersion probe, 11 mm active diameter (verify manufacturer marking).
- Aluminum sheet: 6.11 mm thick.
- Water path: approximately 63 mm, measured probe face to aluminum top surface.
- Initial receiver gain DAC setting: 200.
- Previously used pulse configuration: 72 ns negative, 72 ns positive, 6000 ns damping, positive-first. These are **not** characterized as safe pulse limits.
- Raw captures: nominally 8,000 samples at reported 60 MS/s, approximately 133.33 microseconds.
- No autonomous motion, no automatic PRF ramp, no change to electronics or firmware.

Expected **approximate** echo times, assuming water sound speed 1480 m/s and longitudinal aluminum sound speed 6320 m/s:

- Front-wall: 2 × 63 mm / 1480 m/s = **85.14 µs**.
- Aluminum thickness round trip: 2 × 6.11 mm / 6320 m/s = **1.934 µs**.
- First back-wall: **87.07 µs**.
- Both depend on true path length, temperature, alloy, and transmit-to-recording time zero. Earlier data showed echoes slightly earlier than these calculations.

## One-command live lab run

```bash
python acq.py --lab_suite --port /dev/ttyACM0 --shots 500 \
  --gain 200 --negative-ns 72 --positive-ns 72 --damp-ns 6000 \
  --echo-us 80 95 --noise-us 112 125 \
  --timing-gate 80 92 --max-lag 90 \
  --outdir results/aluminum_63mm
```

`--port` can be omitted if the device is discovered automatically. Close the GUI before running the suite so it does not compete for the USB port.

The suite captures **every shot from the first one**, including startup baseline settling, and saves the original 10-bit ADC values and frame metadata. It then analyzes those same saved waveforms. Live oneshot throughput is benchmarked separately for five seconds, using the previously selected pulse widths and gain. This is host-controlled full-waveform rate, **not** internal maximum pulser PRF.

The capture CSV is written one shot at a time. Even if later analysis fails, you can still reuse `raw/stationary.csv`.

## Offline replay (no pulsing, no serial port)

```bash
python acq.py --lab_suite --csv results/aluminum_63mm/raw/stationary.csv \
  --outdir results/aluminum_63mm_recheck
```

For a comparison to an old-firmware capture at a comparable probe position:

```bash
python acq.py --lab_suite --csv new_500.csv --reference-csv old_500.csv \
  --outdir results/firmware_comparison
```

The comparison checks **the distribution of relative shot-to-shot lags**, not an absolute time reference between independent acquisitions.

## Timing-offset measurement

```bash
python acq.py --timing_offset --csv results/aluminum_63mm/raw/stationary.csv \
  --timing-gate 80 92 --echo-us 80 95 --noise-us 112 125 \
  --max-lag 90 --outdir results/timing
```

The script compares each **baseline-subtracted RF echo** against the last captured echo using cross-correlation. With sample rate `f_s`, one sample of lag represents `1/f_s` seconds (16.67 ns at 60 MS/s). It separately cross-correlates the **Hilbert envelope** to help identify cycle-selection ambiguities. Timing-offset values are measured relative to the last capture, so their sign and zero reference are arbitrary. The script does **not** prove the pulser or ADC PIO is responsible.

Files: `timing_per_shot.csv`, `timing_summary.csv`, `lag_histogram.png`, `echo_overlays.png`, and `timing_and_stability.png`.

## What runs automatically

| Test | What it measures | Output |
|---|---|---|
| integrity | Frame sequence, ADC limits, reported dropped frames | CSV |
| snr | Peak-to-RMS noise ratio, noise in selected quiet gate | CSV, PNG |
| repeatability | Envelope peak CV and echo arrival spread | CSV, PNG |
| averaging | Unaligned coherent averaging at 1, 2, 4, 8, 16, 32, 64 | CSV, PNG |
| alignment | RF lag distribution with ±90 sample search | CSV, PNG |
| timing_offset | RF lag, envelope lag, baseline, clipping, raw P-P, per-shot SNR | CSV, PNGs |
| bandwidth | Existing FFT analysis of the mean RF waveform | CSV, PNG |
| bandwidth_individual | Median of individual-shot FFT magnitudes, avoiding phase cancellation | CSV, PNG |
| tof | Arrival-time spread for stationary reflector | CSV, PNG |
| echo_spacing | Tentative FWE–BWE echo separation and thickness using assumed aluminum velocity | CSV, PNG |
| prf_oneshot | Host-controlled raw acquisition throughput, five seconds | CSV |

Important: The existing `bandwidth` test's mean-RF spectrum is biased when waveforms are misaligned. Even `bandwidth_individual` can be affected by multiple echoes, water-path reverberation and its analysis gate. Neither is a calibrated transducer-bandwidth measurement. Check an isolated, non-clipped echo before quoting a probe center frequency.

The `tof` test only measures stationary arrival-time repeatability unless you have **multiple physical Z positions**. The `echo_spacing` test provisionally labels two echo peaks as front- and back-wall. Verify them before treating the derived thickness as calibration.

## Optional live measurements

These require informed user action; the default lab command does not run them.

```bash
python acq.py --lab_suite --shots 500 --gain-levels 160,200,240 --gain-per-level 24
```

Captures a modest receiver-gain sweep after the stationary run. Gain is a DAC setting, not automatically a calibrated dB value. Avoid ADC clipping.

```bash
python acq.py --lab_suite --shots 500 --focus-z-values 58,60,63,66 \
  --focus-shots 32
```

The script pauses before each series and asks you to **manually position** the probe. The values are measured water-path distances in millimeters, recorded in the CSV `z_mm` field for compatibility with existing offline focus and TOF scripts. The program does not move the gantry. Keep the probe immersed, normal to the surface, and do not touch a powered HV daughterboard.

```bash
python acq.py --lab_suite --shots 500 --contrast-capture --stage-shots 64
python acq.py --lab_suite --shots 500 --motion-noise-capture --stage-shots 64
```

The contrast experiment requires a known defect or separately identified reference, not the blank aluminum plate alone. Motion-noise prompts are for manual motor-disabled and motor-enabled **stationary** conditions. The program does not command motion. If you have no known defect or no way to safely vary motor state, skip these options.

To measure only existing firmware-stream throughput, explicitly enable a **conservative** rate set:

```bash
python acq.py --lab_suite --shots 500 --stream-rates 10,25,50 --prf-seconds 3
```

This requests existing firmware streaming rates, **not** maximum hardware PRF. No rate is guaranteed electrically safe by the script. Do not increase rates or pulse energy simply to fill out a benchmark. You can omit `--stream-rates` and still get the safer one-shot host throughput test.

`--selftest` is also optional. It requests the firmware's synthetic DSP self-test.

## Analyze stage-specific CSV files offline

```bash
python acq.py --lab_suite --csv new_500.csv \
  --gain-csv gain_sweep.csv --focus-csv focus_z.csv \
  --contrast-csv contrast.csv --motion-noise-csv motor_conditions.csv \
  --prf-csv prf_timing.csv
```

Each CSV must have the schema expected by its original test module. The focus and contrast tests only make sense with distinct labeled or positioned acquisitions. Acoustic edge and gantry characterization are intentionally not part of this suite.

## Data and interpretation

- `raw/stationary.csv`: original unnormalized ADC samples `s0...s7999`, sample rate, sequence, timestamps, pulse settings, and gain. Keep this file.
- `raw/prf_oneshot.csv`: host/device timestamp benchmark; no waveforms.
- `analysis/<test>/`: individual test CSV/PNG results and a text execution log.
- `configuration.json`: probe, specimen, timing assumptions, and configured test parameters.
- `test_status.csv`: tests that succeeded or failed.

The quiet gate 112–125 µs is a starting point; verify it contains no meaningful acoustic echoes. Likewise, the echo and timing gates must actually contain the response of interest. A trace with DC baseline drift can still have stable peak-to-peak echo amplitude, but unaligned RF averages can lose amplitude. Check clipping and lag distributions before relying on averaged waveforms.

The nominal 3-inch focal length and 11 mm active aperture cannot establish focus position or lateral resolution in aluminum without additional experiments. This suite does not claim to measure either automatically.
