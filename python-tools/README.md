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


The top toolbar has **Scan setup**. Set scan grid, movement, gate, gain, and CSV/PNG paths, then click **Scan**. The A-scan shows the raw 8000-sample capture at each point; the C-scan grows below it, using the firmware's gated peak-to-peak amplitudes. **Stop scan** aborts the current run and leaves a partial CSV. Completed runs also save the PNG. The scan uses the port already connected by the GUI.

Flash the updated Pico 2 DSP firmware before using the GUI scan. The GUI sends the optional `waveforms` argument after the usual eight scan parameters; the original CLI scan command remains compatible. Firmware ADC sampling stays fixed at 60 MHz regardless of the value entered in the scan setup's sample-rate field (which controls gate index conversion).
