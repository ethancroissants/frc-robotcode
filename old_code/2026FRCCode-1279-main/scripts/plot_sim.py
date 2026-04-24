#!/usr/bin/env python3
"""
Simple CSV plot for the offline PathPlanner sim output.
Usage: python scripts/plot_sim.py build/sim/sim_output.csv build/sim/sim_plot.png
"""
import sys
import csv
import math

if len(sys.argv) < 3:
    print("Usage: python scripts/plot_sim.py <input_csv> <output_png>")
    sys.exit(1)

infile = sys.argv[1]
outfile = sys.argv[2]

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
except Exception as e:
    print("matplotlib is required to run this script. Install with: pip install matplotlib")
    sys.exit(2)

times = []
dx = []
dy = []
dh = []
rvx = []
rvy = []
rov = []
rx = []
ry = []
rh = []
desired_vx = []
desired_vy = []
desired_omega = []
desired_linear = []
pos_error = []
heading_error = []

with open(infile, newline='') as csvfile:
    reader = csv.DictReader(csvfile)
    for r in reader:
        times.append(float(r.get('time', r.get('t', 0))))
        dx.append(float(r.get('desired_x', 0.0)))
        dy.append(float(r.get('desired_y', 0.0)))
        dh.append(float(r.get('desired_heading', r.get('desired_heading_rad', 0.0))))
        rx.append(float(r.get('robot_x', 0.0)))
        ry.append(float(r.get('robot_y', 0.0)))
        rh.append(float(r.get('robot_heading', 0.0)))
        # robot-relative speeds (may be named robotRel_vx in older CSVs)
        rvx.append(float(r.get('robotRel_vx', r.get('robot_rel_vx', 0.0))))
        rvy.append(float(r.get('robotRel_vy', r.get('robot_rel_vy', 0.0))))
        rov.append(float(r.get('robotRel_omega', r.get('robot_rel_omega', 0.0))))
        # desired field velocities and linear vel (added in extended CSV)
        desired_vx.append(float(r.get('desired_vx', 0.0)))
        desired_vy.append(float(r.get('desired_vy', 0.0)))
        desired_omega.append(float(r.get('desired_omega', 0.0)))
        desired_linear.append(float(r.get('desired_linear_vel', r.get('desired_linear_velocity', 0.0))))
        # errors
        pos_error.append(float(r.get('pos_error', r.get('position_error', 0.0))))
        heading_error.append(float(r.get('heading_error', 0.0)))

# Create a 2x2 plot: positions, heading, position error, heading error
plt.figure(figsize=(12,8))

plt.subplot(2,2,1)
plt.plot(times, dx, label='desired_x')
plt.plot(times, rx, label='robot_x', linestyle='--')
plt.plot(times, dy, label='desired_y')
plt.plot(times, ry, label='robot_y', linestyle='--')
plt.xlabel('time (s)')
plt.ylabel('meters')
plt.legend()
plt.title('Positions')

plt.subplot(2,2,2)
plt.plot(times, dh, label='desired_heading')
plt.plot(times, rh, label='robot_heading', linestyle='--')
plt.xlabel('time (s)')
plt.ylabel('radians')
plt.legend()
plt.title('Heading')

plt.subplot(2,2,3)
plt.plot(times, pos_error, label='pos_error')
plt.xlabel('time (s)')
plt.ylabel('meters')
plt.legend()
plt.title('Position error')

plt.subplot(2,2,4)
plt.plot(times, heading_error, label='heading_error')
plt.xlabel('time (s)')
plt.ylabel('radians')
plt.legend()
plt.title('Heading error')

plt.tight_layout()
plt.savefig(outfile)
print(f'Plot saved to {outfile}')
