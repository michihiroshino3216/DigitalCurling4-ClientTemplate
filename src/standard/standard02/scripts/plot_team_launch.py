import os
import csv
import math
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import sys


def read_shots(csv_path):
    rows = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        r = csv.DictReader(f)
        for i,row in enumerate(r):
            try:
                tv = float(row.get('tv',0))
                sa = float(row.get('sa_rad',0))
                traj_file = row.get('trajectory_file')
            except Exception:
                continue
            rows.append((i, tv, sa, traj_file))
    return rows


def read_traj(traj_path):
    xs=[]
    ys=[]
    try:
        with open(traj_path, 'r', encoding='utf-8') as f:
            r = csv.reader(f)
            next(r, None)
            for row in r:
                try:
                    x=float(row[0]); y=float(row[1])
                except Exception:
                    continue
                xs.append(x); ys.append(y)
    except Exception:
        pass
    return xs, ys


def model_to_dc(xs, ys):
    # model x->DC Y, model y->DC X
    return [y for y in ys], [x for x in xs]


def plot_launches(csv_path):
    outdir = os.path.abspath(os.path.join(os.path.dirname(csv_path), 'launch_plots'))
    os.makedirs(outdir, exist_ok=True)
    shots = read_shots(csv_path)
    all_arrows = []
    all_trajs = []
    for idx, tv, sa, traj_file in shots:
        # initial vector in model coords
        vx = tv * math.cos(sa)
        vy = tv * math.sin(sa)
        # DC coords
        dc_x_end = vy
        dc_y_end = vx
        all_arrows.append((0.0, 0.0, dc_x_end, dc_y_end))
        # trajectory
        traj_path = os.path.join(os.path.dirname(csv_path), traj_file)
        if not os.path.exists(traj_path):
            traj_path = os.path.join(os.path.dirname(os.path.dirname(csv_path)), traj_file)
        xs, ys = read_traj(traj_path)
        if xs:
            dc_xs, dc_ys = model_to_dc(xs, ys)
            all_trajs.append((dc_xs, dc_ys))

    # overlay plot
    plt.figure(figsize=(6,8))
    for dc_xs, dc_ys in all_trajs:
        plt.plot(dc_xs, dc_ys, color='gray', alpha=0.4)
    for x0,y0,dx,dy in all_arrows:
        plt.arrow(x0, y0, dx, dy, head_width=0.1, head_length=0.2, fc='blue', ec='blue', alpha=0.7)
    # house
    house_y = 38.405
    house_r = 1.829
    circle = plt.Circle((0.0, house_y), house_r, color='r', fill=False, linewidth=1)
    plt.gca().add_patch(circle)
    plt.xlabel('DC X (m)')
    plt.ylabel('DC Y (m)')
    plt.title('Team launches (vectors) + trajectories')
    plt.grid(True)
    plt.axis('equal')
    outpng = os.path.join(outdir, 'launch_overlay.png')
    plt.savefig(outpng)
    plt.close()
    print('Saved launch overlay to', outpng)


def main():
    csv_path = sys.argv[1] if len(sys.argv) >= 2 else r'.\\standard02\\analysis_outputs\\dc4_team1_20260227_102555_team0_20260227_102734\\team0_shots.csv'
    plot_launches(csv_path)


if __name__ == '__main__':
    main()
