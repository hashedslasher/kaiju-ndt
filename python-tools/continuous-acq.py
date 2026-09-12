import datetime
import pathlib
import time
import tkinter as tk
from tkinter import simpledialog, filedialog
import numpy as np
import matplotlib.pyplot as plt


# --- FUNCTION IMPORT CONVERSION ---
# We now import the explicit functional methods instead of the class name
from lib.ndt_acquisition import (
    acquire_signal, 
    plot_acquisition, 
    get_time_vector, 
    filter_signal
)

# Clear built-in configurations to protect custom key mapping pipelines
plt.rcParams['keymap.save'] = [] 
plt.rcParams['toolbar'] = 'None'

PIEZOID = "10MHz Probe"                

MATERIAL_VELOCITIES = {
    "steel": 5.92,
    "aluminum": 6.32,
    "copper": 4.70,
    "brass": 4.43,
    "titanium": 6.07,
    "iron": 5.90,
    "plastic": 2.73,
    "acrylic": 2.73
}

print("--- Ultrasonic Time-of-Flight Configuration ---")
print(f"Available materials: {', '.join(MATERIAL_VELOCITIES.keys())}")

material_input = input("Enter material name: ").strip().lower()

try:
    thickness_input = input("Enter target thickness in mm: ").strip()
    if thickness_input == "":
        THICKNESS_MM = 4.64
    else:
        THICKNESS_MM = float(thickness_input)
except ValueError:
    print("Invalid numerical input. Defaulting to 4.64 mm.")
    THICKNESS_MM = 4.64

velocity = MATERIAL_VELOCITIES.get(material_input, 5.92)
if material_input not in MATERIAL_VELOCITIES:
    print(f"Material not recognized. Defaulting to steel velocity ({velocity} mm/us).")

EXPECTED_OFFSET_US = (2 * THICKNESS_MM) / velocity

gain = 320  
x_min, x_max = 0.0, 40.0
y_min, y_max = -1.2, 1.2
ZOOM_FACTOR = 1.2 

X_PAN_STEP = 1.5  
Y_PAN_STEP = 0.1  

current_held_key = None  
last_interaction_time = 0.0
FREEZE_DURATION_SEC = 1.5  

latest_thickness_string = "Unknown"
is_running = True  

is_dragging = False
drag_start_x = None
drag_start_y = None

root = tk.Tk()
root.withdraw()

def register_interaction():
    global last_interaction_time
    last_interaction_time = time.time()

def shutdown_application():
    global is_running
    is_running = False
    print("\nShutting down acquisition and exiting script...")
    plt.close('all')
    try:
        root.quit()
        root.destroy()
    except:
        pass

def on_window_close(event):
    print("\n[WINDOW CLOSE] Graph window closed by user.")
    shutdown_application()

def on_key_press(event):
    global x_min, x_max, y_min, y_max, gain, current_held_key
    
    if event.key in ['x', 'y', 'X', 'Y']:
        current_held_key = event.key.lower()
        return

    if event.key == 'escape':
        print("\n[ESCAPE] Escape key pressed.")
        shutdown_application()
        return

    if event.key in ['r', 'R']:
        x_min, x_max = 0.0, 40.0
        y_min, y_max = -1.2, 1.2
        print("\n[RESET] Graph view boundaries restored to default baseline.")
        ax.set_xlim(x_min, x_max)
        ax.set_ylim(y_min, y_max)
        fig.canvas.draw_idle()
        return
    
    # --- CUSTOM FILE EXPLORER SAVE PROMPT (S or s) ---
    elif event.key in ['s', 'S']:
        # Generate an intelligent, descriptive default name to help the inspector
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        thickness_slug = latest_thickness_string.replace(" ", "").replace(":", "-")
        default_name = f"ascan_{timestamp}_{gain}dB_{thickness_slug}.png"
        
        # 1. Open the native Windows File Explorer visual save window
        full_save_path = filedialog.asksaveasfilename(
            parent=root,
            title="Select Scan Destination and Name File",
            initialfile=default_name,
            defaultextension=".png",
            filetypes=[("PNG Image", "*.png"), ("All Files", "*.*")]
        )
        
        # 2. Break safely if the user hits Cancel or exits the explorer panel
        if not full_save_path:
            print("\n[CANCEL] File saving operation canceled by user.")
            return 
            
        print(f"\nExporting ultra-high resolution snapshot directly to selection...")
        
        # 3. Draw the crisp 300 DPI vector lines straight to your selected directory
        fig.savefig(str(full_save_path), 
                    dpi=300, 
                    metadata={"Source": "Pic0rick Live Dashboard"},
                    facecolor=fig.get_facecolor(), 
                    edgecolor='none')
                    
        print(f"[SUCCESS] Exported file footprint: {full_save_path}")
        return


    if event.key in ['+', '=', '-', 'right', 'left', 'down', 'up']:
        register_interaction()

    if event.key in ['+', '=']:  
        gain = min(500, gain + 20)
        print(f"Gain increased to: {gain}")
    elif event.key == '-':
        gain = max(0, gain - 20)
        print(f"Gain decreased to: {gain}")

    elif event.key == 'right':    
        x_min += X_PAN_STEP
        x_max += X_PAN_STEP
    elif event.key == 'left':     
        x_min -= X_PAN_STEP
        x_max -= X_PAN_STEP
    elif event.key == 'up':       
        y_min += Y_PAN_STEP
        y_max += Y_PAN_STEP
    elif event.key == 'down':     
        y_min -= Y_PAN_STEP
        y_max -= Y_PAN_STEP

    if is_running:
        ax.set_xlim(x_min, x_max)
        ax.set_ylim(y_min, y_max)
        fig.canvas.draw_idle()

def on_key_release(event):
    global current_held_key
    if event.key in ['x', 'y', 'X', 'Y']:
        current_held_key = None

def on_scroll(event):
    global x_min, x_max, y_min, y_max
    if event.inaxes is None or not is_running:
        return
        
    register_interaction() 
    x_current = event.xdata
    y_current = event.ydata
    factor = 1.0 / ZOOM_FACTOR if event.button == 'up' else ZOOM_FACTOR
    
    if current_held_key == 'x':
        x_min = x_current - (x_current - x_min) * factor
        x_max = x_current + (x_max - x_current) * factor
    elif current_held_key == 'y':
        y_min = y_current - (y_current - y_min) * factor
        y_max = y_current + (y_max - y_current) * factor
    else:
        x_min = x_current - (x_current - x_min) * factor
        x_max = x_current + (x_max - x_current) * factor
        y_min = y_current - (y_current - y_min) * factor
        y_max = y_current + (y_max - y_current) * factor

    ax.set_xlim(x_min, x_max)
    ax.set_ylim(y_min, y_max)
    fig.canvas.draw_idle()

def on_mouse_press(event):
    global is_dragging, drag_start_x, drag_start_y
    if event.inaxes is None or not is_running:
        return
    if event.button == 1 or event.button == 3:
        is_dragging = True
        drag_start_x = event.xdata
        drag_start_y = event.ydata

def on_mouse_move(event):
    global x_min, x_max, y_min, y_max, is_dragging
    if not is_dragging or event.inaxes is None or not is_running:
        return
    register_interaction()
    dx = event.xdata - drag_start_x
    dy = event.ydata - drag_start_y
    x_min -= dx
    x_max -= dx
    y_min -= dy
    y_max -= dy
    ax.set_xlim(x_min, x_max)
    ax.set_ylim(y_min, y_max)
    fig.canvas.draw_idle()

def on_mouse_release(event):
    global is_dragging
    is_dragging = False

# Setup display frame layout
plt.ion() 
fig, ax = plt.subplots(figsize=(12, 7))
fig.set_layout_engine('tight') 

# Connect window listeners
fig.canvas.mpl_connect('key_press_event', on_key_press)
fig.canvas.mpl_connect('key_release_event', on_key_release)
fig.canvas.mpl_connect('scroll_event', on_scroll)
fig.canvas.mpl_connect('close_event', on_window_close)  
fig.canvas.mpl_connect('button_press_event', on_mouse_press)
fig.canvas.mpl_connect('motion_notify_event', on_mouse_move)
fig.canvas.mpl_connect('button_release_event', on_mouse_release)

print("\nDashboard Setup Complete.")
print("Controls: Mousewheel = Zoom Both | Hold X/Y + Mousewheel = Zoom Single Axis")
print("          Left/Right Click & Drag = Pan Graph  | Arrows = Move Panning step")
print("          + / - = Gain Live | R = Reset View | S = Save PNG | Esc or Close Window = Exit.")

try:
    while is_running and plt.fignum_exists(fig.number):
        current_time = time.time()
        
        # --- CONDITIONAL INTERACTION PAUSE CHECK ---
        if (current_time - last_interaction_time) < FREEZE_DURATION_SEC:
            plt.pause(0.05) 
            continue
            
        # Call the updated functional data collector method
        acq = acquire_signal(
            Fech=60e6, gain=gain,                            
            piezo_central_freq=10e6, piezo_bandwidth=4e6,
            piezo_id=PIEZOID, pon=70, poff=70, damp=6000,                     
            target=f"Live Tracking: {material_input} {THICKNESS_MM}mm",   
            h5_path=None, overwrite=False             
        )
        
        if not is_running or not plt.fignum_exists(fig.number):
            break
            
        ax.clear()
        
        # Run the functional graphing method from the library
        plot_acquisition(acq, ax=ax) 
        
        # --- FIXED AUTOMATED PEAK DETECTION FROM THE DICTIONARY DATA ---
        # Instead of guessing class values, we draw data arrays straight from the active trace
        first_real_peak_time = 8.47 
        second_real_peak_time = None
        
        # Standardize matching x coordinates from the library's internal scale (us)
        x_data = get_time_vector(acq) * 1e6  # Convert seconds to microseconds
        y_data = filter_signal(acq)          # Extract the filtered data stream array
        
        # Find delay line interface peak
        search_mask1 = (x_data > 7.5) & (x_data < 12.0)
        if np.any(search_mask1):
            search_indices1 = np.where(search_mask1)[0]
            peak_idx1 = search_indices1[np.argmax(np.abs(y_data[search_mask1]))]
            first_real_peak_time = x_data[peak_idx1]
        
        # Narrowed search zone for thin targets (3mm to 6mm)
        search_mask2 = (x_data > 9.5) & (x_data < 12.5)
        if np.any(search_mask2):
            search_indices2 = np.where(search_mask2)[0]
            peak_idx2 = search_indices2[np.argmax(np.abs(y_data[search_mask2]))]
            second_real_peak_time = x_data[peak_idx2]
        
        dynamic_expected_echo = first_real_peak_time + EXPECTED_OFFSET_US
        
        ax.set_xlim(x_min, x_max) 
        ax.set_ylim(y_min, y_max) 
        
        # --- LIVE READOUT OVERLAY BOX ---
        if second_real_peak_time and (second_real_peak_time - first_real_peak_time) > 0.2:
            tof_us = second_real_peak_time - first_real_peak_time
            calculated_thickness_mm = (tof_us * velocity) / 2
            calculated_thickness_in = calculated_thickness_mm / 25.4
            
            latest_thickness_string = f"{calculated_thickness_mm:.2f}mm"
            
            text_str = (f"LIVE NDT READOUT\n"
                        f"-----------------\n"
                        f"Time of Flight: {tof_us:.2f} µs\n"
                        f"Thickness: {calculated_thickness_mm:.2f} mm\n"
                        f"Thickness: {calculated_thickness_in:.3f} in")
            
            ax.text(0.03, 0.94, text_str, transform=ax.transAxes, fontsize=11, fontweight='bold',
                    fontfamily='monospace', verticalalignment='top',
                    bbox=dict(boxstyle='round,pad=0.5', facecolor='#FDF6E3', edgecolor='#93A1A1', alpha=0.85))
        else:
            latest_thickness_string = "Air"

        ax.axvline(x=first_real_peak_time, color='blue', linestyle=':', linewidth=2,
                   label=f'Tracked Delay Interface ({first_real_peak_time:.2f} us)')
        ax.axvline(x=dynamic_expected_echo, color='red', linestyle='--', linewidth=2,
                   label=f'Expected {THICKNESS_MM}mm {material_input.capitalize()} Echo ({dynamic_expected_echo:.2f} us)')
        
        if second_real_peak_time and latest_thickness_string != "Air":
            ax.axvline(x=second_real_peak_time, color='orange', linestyle='-.', linewidth=2,
                       label=f'Measured Echo Peak ({second_real_peak_time:.2f} us)')

        ax.legend(loc="upper right")
        plt.pause(1.5)                 

except KeyboardInterrupt:
    print("\nAcquisition stopped via terminal command.")

finally:
    try:
        root.quit()
        root.destroy()
    except:
        pass
    print("Script finished safely.")
