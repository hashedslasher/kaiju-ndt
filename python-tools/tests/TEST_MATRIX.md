# Acquisition and motion test CLI

The commands below are independent of the GUI. All raw CSV captures store unscaled ADC counts and header metadata. No commands perform autonomous X/Y/Z movement. Offline analysis does not connect to the Pico.

Start with `python acq.py --selftest` to exercise the firmware's built-in synthetic DSP tests. Then put the immersion probe in a stable water path and record raw data:

```bash
python acq.py --capture --shots 128 --output data/stationary.csv --echo-us 90 98
python acq.py --integrity --csv data/stationary.csv
python acq.py --snr --csv data/stationary.csv --echo-us 90 98 --noise-us 105 110 --plot
python acq.py --repeatability --csv data/stationary.csv --echo-us 90 98 --noise-us 105 110
python acq.py --averaging --csv data/stationary.csv --echo-us 90 98 --noise-us 105 110 --plot
python acq.py --alignment --csv data/stationary.csv --echo-us 90 98 --max-lag 12
python acq.py --bandwidth --csv data/stationary.csv --echo-us 90 98 --plot
python acq.py --prf --mode raw --rates 10,25,50,75,100 --seconds 3
python acq.py --prf --mode oneshot --seconds 5
```

Choose signal and noise gates after inspecting the captured waveform. These gate times are examples and are not valid for every water path.

Gain sweep uses the live device, so set a safe water path and check for clipping before increasing gain:

```bash
python acq.py --gain --levels 100,200,300,400,460 --per-level 5 --echo-us 90 98 --plot
```

For TOF/focus, manually set measured Z, then append separate raw captures to a single file:

```bash
python acq.py --capture --shots 10 --z-mm 0 --output data/z_sweep.csv --append
python acq.py --capture --shots 10 --z-mm 1 --output data/z_sweep.csv --append
python acq.py --capture --shots 10 --z-mm 2 --output data/z_sweep.csv --append
python acq.py --tof --csv data/z_sweep.csv --echo-us 88 100 --plot
python acq.py --focus --csv data/z_sweep.csv --echo-us 88 100 --plot
```

For good-versus-hole contrast, capture the two regions at the same Z/gain/pulse settings:

```bash
python acq.py --capture --shots 50 --label good --output data/contrast.csv --append
python acq.py --capture --shots 50 --label hole --output data/contrast.csv --append
python acq.py --contrast --csv data/contrast.csv --echo-us 90 98
```

For acoustic edge response, take one or more captures at manually measured X locations and append them into one file. Then use `--edge --csv data/edge.csv --range-mm 1 4`. Supply a range isolating one transition, not the entire circular hole.

For mechanical positioning, create a CSV with headers `commanded_mm,measured_mm,direction` and one row per independent indicator reading. Analyze it with `python acq.py --gantry --csv data/gantry.csv --plot`. The default belt and pulley values are illustrative; set the real values for your MPCNC.

For motion-related interference, capture stationary waveforms with motor drivers disabled (`--label quiet`) and again under a separately verified motor-operating condition (`--label active`), then compare using `python acq.py --motion_noise --csv data/motion.csv`. The supplied firmware has no independent enable-without-motion command or motion safety interlocks, so this script never issues a jog automatically.

Set `PIC0RICK_PORT` to your device path or pass `--port`. The firmware imposes raw streaming at up to 100 Hz and finite moves of at most 5000 steps per command. The PRF test measures completed frames and USB throughput, not the pulser's autonomous maximum rate. An on-device benchmark is needed for that distinction.
