import os
import json
import math
import datetime
import importlib.util
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def load_export_module():
    p = os.path.join(os.path.dirname(__file__), 'export_shot_analysis.py')
    spec = importlib.util.spec_from_file_location('esa', p)
    esa = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(esa)
    return esa


def parse_all_shots(log_path):
    shots = []
    with open(log_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            msg = obj.get('message','')
            ts = obj.get('timestamp')
            if 'last_move=ShotInfoSchema' in msg:
                m_shot = None
                import re
                m_shot = re.search(r"last_move=ShotInfoSchema\(translational_velocity=([0-9eE.+-]+), angular_velocity=([0-9eE.+-]+), shot_angle=([0-9eE.+-]+)\)", msg)
                if not m_shot:
                    continue
                tv = float(m_shot.group(1))
                av = float(m_shot.group(2))
                sa = float(m_shot.group(3))
                m_total = re.search(r'total_shot_number=(\d+)', msg)
                total = int(m_total.group(1)) if m_total else None
                m_end = re.search(r'end_number=(\d+)', msg)
                end = int(m_end.group(1)) if m_end else None
                m_next = re.search(r"next_shot_team='(team0|team1|None)'", msg)
                next_team = m_next.group(1) if m_next else None
                # shooter inference (same logic as export_shot_analysis)
                shooter = None
                if next_team == 'team1':
                    shooter = 'team0'
                elif next_team == 'team0':
                    shooter = 'team1'
                # record
                shots.append({'ts': ts, 'end': end, 'total': total, 'tv': tv, 'av': av, 'sa_rad': sa, 'shooter': shooter})
    # sort by total_shot_number if present
    shots.sort(key=lambda s: (s['total'] if s['total'] is not None else 0))
    return shots


def compute_final_positions(esa, shots):
    # force local model
    try:
        esa.NATIVE_INFO['enabled'] = False
        esa.NATIVE_INFO['requested'] = False
    except Exception:
        pass
    results = []
    for s in shots:
        # prefer native endpoint if enabled, but we've disabled it above
        native = None
        try:
            native = esa.simulate_trajectory_native_endpoint(s['tv'], s['av'], s['sa_rad'], shooter_team=s['shooter'] or 'team0', total_shot_number=s.get('total'))
        except Exception:
            native = None
        if native:
            traj, fx, fy = native
        else:
            traj, est, (fx, fy) = esa.simulate_trajectory_fcv1(s['tv'], s['av'], s['sa_rad'])
        # map to DC coords: dc_x = fy, dc_y = fx
        dc_x = fy
        dc_y = fx
        results.append({**s, 'fx': fx, 'fy': fy, 'dc_x': dc_x, 'dc_y': dc_y})
    return results


def plot_boards_by_end(results, outdir, house_center_y=38.405, house_r=1.829):
    os.makedirs(outdir, exist_ok=True)
    # group by end
    by_end = {}
    for r in results:
        e = r.get('end') if r.get('end') is not None else 0
        by_end.setdefault(e, []).append(r)

    for end, shots in sorted(by_end.items()):
        fig, ax = plt.subplots(figsize=(6, 8))
        # draw house (original DC center at dc_x=0, dc_y=house_center_y)
        # after swapping axes we plot at (plot_x=dc_y, plot_y=dc_x)
        ax.add_artist(plt.Circle((house_center_y, 0), house_r*3, color='#f0f0f0', zorder=0))
        # concentric circles for house rings
        colors = ['#ffffcc', '#ffd699', '#ff9999', '#ff6666']
        rings = [6.4, 4.5, 2.0, 1.829]
        for rad, col in zip(rings, colors[-len(rings):]):
            ax.add_artist(plt.Circle((0, house_center_y), rad, fill=False, color='gray', ls='--', lw=0.6))

        for s in shots:
            team = s.get('shooter') or 'team0'
            dc_x = s['dc_x']
            dc_y = s['dc_y']
            # swap: plot_x shows DC Y, plot_y shows DC X
            plot_x = dc_y
            plot_y = dc_x
            color = 'red' if team == 'team0' else 'blue'
            ax.add_artist(plt.Circle((plot_x, plot_y), 0.145, color=color, alpha=0.9, zorder=2))
        # adjust limits: x axis is DC Y (long), y axis is DC X
        ax.set_xlim(-10, 80)
        ax.set_ylim(-10, 50)
        ax.set_aspect('equal')
        ax.set_title(f'End {end} — stones: {len(shots)}')
        ax.set_xlabel('DC Y (m)')
        ax.set_ylabel('DC X (m)')
        ax.grid(True, lw=0.3)
        fname = os.path.join(outdir, f'end_{end:02d}.png')
        fig.savefig(fname, dpi=150)
        plt.close(fig)


def main():
    import sys
    if len(sys.argv) >= 2:
        log_path = sys.argv[1]
    else:
        # default to active editor file if present
        log_path = os.path.join(os.path.dirname(__file__), '..', 'logs', 'dc4_team1_20260227_152642.jsonl')
    log_path = os.path.abspath(log_path)
    if not os.path.exists(log_path):
        print('Log not found:', log_path)
        return
    esa = load_export_module()
    shots = parse_all_shots(log_path)
    if not shots:
        print('No shots parsed from log')
        return
    results = compute_final_positions(esa, shots)
    now = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    outdir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'analysis_outputs', os.path.splitext(os.path.basename(log_path))[0] + '_boards_' + now))
    plot_boards_by_end(results, outdir)
    print('Saved board images to', outdir)


if __name__ == '__main__':
    main()
