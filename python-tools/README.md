```bash
python -m pip install -r requirements.txt
python acq.py --selftest
python acq.py --capture --shots 128 --output data/steel.csv
python acq.py --snr --csv data/steel.csv --echo-us 88 98 --noise-us 104 110 --plot
python acq.py --averaging --csv data/steel.csv --echo-us 88 98 --noise-us 104 110 --plot
python acq.py --alignment --csv data/steel.csv --echo-us 88 98 --plot
python acq.py --prf --mode raw --rates 10,25,50,75,100 --seconds 3
python acq.py
```


The top toolbar has **Scan setup**. Home X/Y first and verify that the transducer has clearance over the entire motion path. Enter coupon X width and Y height, margin per side, X/Y spacing (mm), speed (mm/s), amplitude/flaw/TOF/B-scan gates (µs), TOF threshold, averaging, settling, gain, and output paths. The grid is centered on the firmware software travel area. The gantry moves to the bottom-left scan corner before acquiring, then scans left-to-right on the first row and reverses on alternating rows. The scan plots and new centered CSVs use the bottom-left scan point as (0,0), with dimensions in mm. The A-scan, live B-scan and three C-scans appear from top to bottom. The B-scan row selector can inspect any acquired row after completion or a stop. The waveform data file is a raw uint16 NumPy array ordered [row, column, sample]; use the matching CSV to identify valid points, positions and pixel spacing. Data are recorded at 60 MHz with 8000 samples per point. The GUI saves the C-scan PNG, CSV and waveform data; the CLI defaults to centered metric scanning and still supports explicit legacy --nx/--ny grids. See `CENTERED_BSCAN.md` at the project root.

Flash the matching firmware before using metric commands. For details, see the project-root `METRIC_TOF.md`.

Run hardware-free tests from `python-tools`:

```bash
python -m unittest discover -s tests -t . -p 'test_*.py'
```
