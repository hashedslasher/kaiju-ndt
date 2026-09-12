import numpy as np
import h5py
from datetime import datetime
from typing import Dict, Any, Optional, List

# Track the global dictionary handle state
_PROBE = None
_SCALAR_ATTRS = ["Fech", "pon", "poff", "damp", "gain", "target", "timestamp", "piezo_id", "piezo_central_freq", "piezo_bandwidth"]

def get_probe(force_new: bool = False) -> Dict[str, Any]:
    global _PROBE
    if _PROBE is None or force_new:
        from lib.device import init_device
        _PROBE = init_device(verbose=False)
    return _PROBE

def get_time_vector(acq: Dict[str, Any]) -> np.ndarray:
    n = len(acq["signal"])
    return np.arange(n) / acq["Fech"]

def filter_signal(acq: Dict[str, Any]) -> np.ndarray:
    from scipy.signal import butter, sosfilt
    f_ech = acq["Fech"]
    f_central = acq.get("piezo_central_freq")
    f_bw = acq.get("piezo_bandwidth")
    
    if f_central is None or f_bw is None:
        return acq["signal"]
        
    f_low = max(1e3, f_central - f_bw / 2)
    f_high = min(f_ech / 2 - 1e3, f_central + f_bw / 2)
    
    sos = butter(4, [f_low, f_high], btype="bandpass", fs=f_ech, output="sos")
    return sosfilt(sos, acq["signal"])

def get_label(acq: Dict[str, Any]) -> str:
    # 1. Grab parameters from the active dictionary
    target = acq.get("target", "Live Tracking")
    piezo = acq.get("piezo_id", "10MHz Probe")
    gain_val = acq.get("gain", 320)
    pon = acq.get("pon", 70)
    poff = acq.get("poff", 70)
    damp = acq.get("damp", 6000)
    
    # 2. Convert Fech from Hz to MHz safely
    fech_hz = acq.get("Fech", 60e6)
    fech_mhz = fech_hz / 1e6
    
    # 3. Build the exact full-parameter layout string
    return (f"{target} | piezo={piezo} | gain={gain_val} dB | "
            f"pon={pon}, poff={poff}, damp={damp} | Fech={fech_mhz:.2f} MHz") 

def get_key(acq: Dict[str, Any]) -> tuple:
    return (
        round(float(acq["gain"]), 6),
        int(acq["pon"]),
        int(acq["poff"]),
        int(acq["damp"]),
        str(acq["target"]),
        str(acq["piezo_id"])
    )

def _find_group_by_key(h5: h5py.File, key: tuple) -> Optional[str]:
    for name in h5:
        g = h5[name]
        try:
            g_key = (
                round(float(g.attrs["gain"]), 6),
                int(g.attrs["pon"]),
                int(g.attrs["poff"]),
                int(g.attrs["damp"]),
                str(g.attrs["target"]),
                str(g.attrs["piezo_id"])
            )
            if g_key == key:
                return name
        except KeyError:
            continue
    return None

def _load_by_key(path: str, key: tuple) -> Optional[Dict[str, Any]]:
    with h5py.File(path, "r") as h5:
        match = _find_group_by_key(h5, key)
        if match is not None:
            g = h5[match]
            acq = {"signal": np.array(g["signal"])}
            for k in _SCALAR_ATTRS:
                if k in g.attrs:
                    acq[k] = g.attrs[k]
            return acq
    return None

def acquire_signal(
    Fech: float,
    *,
    probe=None,
    pon: int = 70,
    poff: int = 70,
    damp: int = 6000,
    gain: float = 20,
    target: str = "",
    piezo_id: str = "",
    piezo_central_freq: Optional[float] = None,
    piezo_bandwidth: Optional[float] = None,
    h5_path: Optional[str] = None,
    overwrite: bool = False,
) -> Dict[str, Any]:
    
    if h5_path is not None and not overwrite:
        key = (round(float(gain), 6), int(pon), int(poff), int(damp), str(target), str(piezo_id))
        cached = _load_by_key(h5_path, key)
        if cached is not None:
            dirty = False
            if piezo_central_freq is not None and cached.get("piezo_central_freq") != piezo_central_freq:
                cached["piezo_central_freq"] = piezo_central_freq
                dirty = True
            if piezo_bandwidth is not None and cached.get("piezo_bandwidth") != piezo_bandwidth:
                cached["piezo_bandwidth"] = piezo_bandwidth
                dirty = True
            if dirty:
                save_acquisition(cached, h5_path)
            return cached

    if probe is None:
        probe = get_probe()
        
    # --- FUNCTIONAL HARDWARE CALL CONVERSION ---
    from lib.device import dac, pulse_adc_trigger, read_device
    
    dac(probe, int(gain))
    pulse_adc_trigger(probe, pon=pon, poff=poff, damp=damp)
    C = read_device(probe)
    
    raw = [x.replace("b'", "").replace("'", "") for x in str(C[2]).split(",") if len(x)]
    signal = np.array([(int(x, 16) - 512) / 512.0 for x in raw[:-1]], dtype=np.float32)
    
    acq = {
        "signal": signal,
        "Fech": Fech,
        "pon": pon,
        "poff": poff,
        "damp": damp,
        "gain": gain,
        "target": target,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "piezo_id": piezo_id,
        "piezo_central_freq": piezo_central_freq,
        "piezo_bandwidth": piezo_bandwidth,
        "h5_path": h5_path
    }
    
    if h5_path is not None:
        save_acquisition(acq, h5_path)
    return acq

def plot_acquisition(
    acq: Dict[str, Any],
    ax: Optional[plt.Axes] = None,
    unit: str = "us",
    figsize=(15, 5),
    **plot_kwargs,
) -> plt.Axes:
    import matplotlib.pyplot as plt
    has_filter = acq.get("piezo_central_freq") is not None and acq.get("piezo_bandwidth") is not None
    scale = {"s": 1.0, "ms": 1e3, "us": 1e6}[unit]
    t = get_time_vector(acq) * scale

    if ax is None:
        _, ax = plt.subplots(figsize=figsize)

    lw = plot_kwargs.pop("lw", 0.8)
    ax.plot(t, acq["signal"], lw=lw, color="tab:blue", alpha=0.45, label="raw", **plot_kwargs)
    if has_filter:
        ax.plot(t, filter_signal(acq), lw=lw, color="tab:orange", label="filtered")
        ax.legend(loc="upper right", fontsize=9)

    ax.set_xlabel(f"Time [{unit}]")
    ax.set_ylabel("Amplitude [norm.]")
    ax.set_title(get_label(acq))
    ax.grid(True, alpha=0.3)
    ax.margins(x=0)
    return ax

def save_acquisition(acq: Dict[str, Any], path: Optional[str] = None) -> None:
    p = path or acq.get("h5_path")
    if p is None:
        raise ValueError("No h5_path provided.")
    acq["h5_path"] = p
    with h5py.File(p, "a") as h5:
        match = _find_group_by_key(h5, get_key(acq))
        if match is not None:
            del h5[match]
        i = 0
        while f"acq_{i:04d}" in h5:
            i += 1
        g = h5.create_group(f"acq_{i:04d}")
        g.create_dataset("signal", data=np.asarray(acq["signal"]), compression="gzip")
        for k in _SCALAR_ATTRS:
            v = acq.get(k)
            if v is not None:
                g.attrs[k] = v
