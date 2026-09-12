from lib.ndt_acquisition import UltrasonicAcquisition

FECH = 60e6
h5_PATH = "calibration/calibration_6mm.h5"
piezo_ID = "10MHz_delay"


speed_of_sound = 5900.0
block_thickness = 6e-3
calib_target = "steel_6mm"

dt_us = (2.0 * block_thickness / speed_of_sound) * 1e6

calib_results = UltrasonicAcquisition.calibrate(
    h5_path=h5_PATH,
    Fech=FECH,
    gain=200,
    start_us=3.0,
    end_us=15.0,
    piezo_central_freq=10e6,
    piezo_bandwidth=4e6,
    piezo_id=piezo_ID,
    target=calib_target,
    pon_poff_values=range(25, 156, 10)
)

print(f"Best pon=poff: {calib_results['best_pon_poff']}")
print(f"Max Amplitude: {calib_results['best_amplitude']:.4f}")

calib_results["figure"].show()
