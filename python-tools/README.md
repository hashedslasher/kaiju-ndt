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
