import sys
import glob
import time
from typing import Dict, Any, List
import serial


def _find_port() -> str:
    import serial.tools.list_ports
    
    # Common USB-to-Serial controller chip keywords used in NDT hardware boards
    hw_keywords = ["ch340", "ftdi", "cp210", "prolific", "usb serial", "usb-to-serial"]
    
    ports = list(serial.tools.list_ports.comports())
    
    # 1. Smart Scan: Look for any port matching our hardware descriptors
    for p in ports:
        desc = p.description.lower()
        hwid = p.hwid.lower()
        if any(key in desc or key in hwid for key in hw_keywords):
            print(f"[AUTO-DETECT] Found NDT hardware on: {p.device} ({p.description})")
            return p.device
            
    # 2. Fallback Scan: If keywords fail, just grab the first available active COM port
    if ports:
        print(f"[AUTO-DETECT] No matching keywords. Defaulting to first active port: {ports[0].device}")
        return ports[0].device
        
    # 3. Crash Prevention: Alert the user if absolutely nothing is plugged in
    raise OSError("No serial device found. Please check your USB cable connection.")



def pprint(ans: List[bytes]) -> str:
    return "".join(b.decode("utf-8") for b in ans)


def sread(device: Dict[str, Any]) -> List[bytes]:
    done = False
    ans = []
    while not done:
        res = device["ser"].readline()
        ans.append(res)
        if res == b"":
            done = True
            
    if device["verbose"]:
        print(pprint(ans), end="")
        
    if device["log"]:
        with open(device["log_file"], "a") as f:
            for line in ans:
                if line and line != b"":
                    f.write(line.decode("utf-8", errors="replace"))
    return ans


def init_device(port: str = None, verbose: bool = True, logging: bool = False, log_file: str = ".log") -> Dict[str, Any]:
    port_device = port if port is not None else _find_port()
    print("Device on", port_device)

    ser = serial.Serial(port_device, 115200, timeout=0.2)
    time.sleep(1)  # wait for the serial connection to initialize

    device = {
        "ser": ser,
        "verbose": verbose,
        "log": logging,
        "log_file": log_file,
        "Fech": 60e6  # ADC sampling frequency (Hz)
    }
    
    sread(device)
    return device


def dac(device: Dict[str, Any], n_val: int) -> List[bytes]:
    """Write a value to the 10-bit DAC MCP4812 (write dac)."""
    device["ser"].write(bytearray(f"write dac {n_val}\n", "ascii"))
    return sread(device)


def read_device(device: Dict[str, Any]) -> List[bytes]:
    device["ser"].write(bytearray("read\n", "ascii"))
    return sread(device)


def pulse_adc_trigger(device: Dict[str, Any], pon: int = 200, poff: int = 200, damp: int = 2000) -> List[bytes]:
    device["ser"].write(bytearray(f"start acq {pon} {poff} {damp}\n", "ascii"))
    return sread(device)
