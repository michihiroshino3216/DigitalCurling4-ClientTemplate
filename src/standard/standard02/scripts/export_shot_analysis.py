import os
import re
import json
import math
import csv
import urllib.request
import importlib.util
from collections import defaultdict
import datetime
import traceback

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


LOG_PATH = os.path.join(os.path.dirname(__file__), '..', 'logs', 'dc4_team1_20260226_113732.jsonl')

import sys


FCV1_RELEASE = 'v1.1.5'
NATIVE_SIMULATOR = None
NATIVE_STONE_SIMULATOR = None
NP = None
NATIVE_INFO = {
    'requested': True,
    'enabled': False,
    'path': None,
    'url': None,
    'reason': None,
}


def ensure_fcv1_native_simulator():
    global NATIVE_SIMULATOR, NATIVE_INFO
    if NATIVE_SIMULATOR is not None:
        return NATIVE_SIMULATOR
    if os.name != 'nt':
        NATIVE_INFO['reason'] = 'native binary auto-download is configured for Windows only'
        return None
    py_major = sys.version_info.major
    py_minor = sys.version_info.minor
    if py_major != 3 or py_minor < 9 or py_minor > 13:
        NATIVE_INFO['reason'] = f'unsupported python version for FCV1 release binary: {py_major}.{py_minor}'
        return None

    native_dir = os.path.join(os.path.dirname(__file__), 'fcv1_native')
    os.makedirs(native_dir, exist_ok=True)
    native_path = os.path.join(native_dir, 'simulator.pyd')
    config_path = os.path.join(native_dir, 'config.json')
    if not os.path.exists(config_path):
        with open(config_path, 'w', encoding='utf-8') as cf:
            json.dump({'thread_num': 1}, cf)
    url = f'https://github.com/kawamlab/FCV1-Simulation/releases/download/{FCV1_RELEASE}/simulator-windows-latest-py3.{py_minor}.pyd'
    NATIVE_INFO['url'] = url
    NATIVE_INFO['path'] = native_path

    if not os.path.exists(native_path):
        try:
            urllib.request.urlretrieve(url, native_path)
        except Exception as e:
            NATIVE_INFO['reason'] = f'download failed: {e}'
            return None

    try:
        spec = importlib.util.spec_from_file_location('simulator', native_path)
        if spec is None or spec.loader is None:
            NATIVE_INFO['reason'] = 'failed to create module spec for simulator.pyd'
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        NATIVE_SIMULATOR = module
        try:
            import numpy as _np
            global NP
            NP = _np
            global NATIVE_STONE_SIMULATOR
            old_cwd = os.getcwd()
            try:
                os.chdir(native_dir)
                NATIVE_STONE_SIMULATOR = NATIVE_SIMULATOR.StoneSimulator()
            finally:
                os.chdir(old_cwd)
        except Exception as e:
            NATIVE_INFO['reason'] = f'loaded .pyd but failed to init StoneSimulator: {e}'
            return None
        NATIVE_INFO['enabled'] = True
        return NATIVE_SIMULATOR
    except Exception as e:
        NATIVE_INFO['reason'] = f'load failed: {e}'
        return None


def simulate_trajectory_native_endpoint(tv, av, sa_rad, shooter_team='team0', total_shot_number=None):
    # Use FCV1 native simulator (.pyd) to estimate final resting position
    # and use FCV1-inspired curve only for visualization path.
    if not NATIVE_INFO.get('enabled') or NATIVE_STONE_SIMULATOR is None or NP is None:
        return None
    try:
        team0 = NP.zeros((8, 2), dtype=NP.float64)
        team1 = NP.zeros((8, 2), dtype=NP.float64)
        x_velocities = NP.array([tv * math.cos(sa_rad)], dtype=NP.float64)
        y_velocities = NP.array([tv * math.sin(sa_rad)], dtype=NP.float64)
        spin = 1 if av >= 0 else -1
        angular = NP.array([spin], dtype=NP.int32)

        if total_shot_number is None:
            shot_per_team = 0
        else:
            if shooter_team == 'team0':
                shot_per_team = max(0, int((int(total_shot_number) - 1) // 2))
            else:
                shot_per_team = max(0, int((int(total_shot_number) - 2) // 2))
        team_id = 0 if shooter_team == 'team0' else 1
        hummer_team = 1

        result = NATIVE_STONE_SIMULATOR.simulator(
            team0,
            team1,
            int(total_shot_number) if total_shot_number is not None else 1,
            x_velocities,
            y_velocities,
            angular,
            int(team_id),
            int(shot_per_team),
            int(hummer_team),
        )
        # shape: [sim, 2, 8, 2]
        out = NP.asarray(result)
        fx = float(out[0, team_id, shot_per_team, 0])
        fy = float(out[0, team_id, shot_per_team, 1])

        # visualization path still from local FCV1 equation and scaled to native endpoint
        traj, _, (lx, ly) = simulate_trajectory_fcv1(tv, av, sa_rad)
        if abs(lx) > 1e-9 and abs(ly) > 1e-9:
            sx = fx / lx
            sy = fy / ly
            scaled_traj = [(px * sx, py * sy) for px, py in traj]
        elif abs(lx) > 1e-9:
            sx = fx / lx
            scaled_traj = [(px * sx, py * sx) for px, py in traj]
        else:
            scaled_traj = traj
        return scaled_traj, fx, fy
    except Exception:
        NATIVE_INFO['reason'] = 'native simulation fallback: ' + traceback.format_exc(limit=1).strip()
        return None


def parse_logs(path, target_team='team0'):
    team_shots = []
    last_scores = None
    with open(path, 'r', encoding='utf-8') as f:
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
            # capture score
            m_score = re.search(r"score=ScoreSchema\(team0=\[([^\]]*)\], team1=\[([^\]]*)\]\)", msg)
            if m_score:
                a0=[int(x.strip()) for x in m_score.group(1).split(',') if x.strip()!='']
                a1=[int(x.strip()) for x in m_score.group(2).split(',') if x.strip()!='']
                last_scores=(a0,a1,ts)

            if 'last_move=ShotInfoSchema' in msg:
                m_shot = re.search(r"last_move=ShotInfoSchema\(translational_velocity=([0-9eE.+-]+), angular_velocity=([0-9eE.+-]+), shot_angle=([0-9eE.+-]+)\)", msg)
                if not m_shot:
                    continue
                tv=float(m_shot.group(1))
                av=float(m_shot.group(2))
                sa=float(m_shot.group(3))
                m_total = re.search(r'total_shot_number=(\d+)', msg)
                total = int(m_total.group(1)) if m_total else None
                m_end = re.search(r'end_number=(\d+)', msg)
                end = int(m_end.group(1)) if m_end else None
                m_next = re.search(r"next_shot_team='(team0|team1|None)'", msg)
                next_team = m_next.group(1) if m_next else None
                shooter = None
                if next_team=='team1':
                    shooter='team0'
                elif next_team=='team0':
                    shooter='team1'
                if shooter == target_team:
                    team_shots.append({'ts':ts,'end':end,'total':total,'tv':tv,'av':av,'sa_rad':sa,'sa_deg':math.degrees(sa)})
    return team_shots, last_scores


def simulate_trajectory(tv, sa_rad, decel=0.2, dt=0.05):
    # legacy simple linear model kept for compatibility
    v = tv
    t = 0.0
    x = 0.0
    y = 0.0
    traj = [(x,y)]
    while v > 0:
        dx = v * math.cos(sa_rad) * dt
        dy = v * math.sin(sa_rad) * dt
        x += dx
        y += dy
        traj.append((x,y))
        t += dt
        v = tv - decel * t
        if len(traj) > 2000:
            break
    est_dist = x
    return traj, est_dist, (x,y)


def simulate_trajectory_precise(tv, av, sa_rad, dt=0.05, scale=15.0, curvature_coeff=0.006):
    # Precise model using exponential decay v(t) = v0 * exp(-k t)
    # Parameters:
    #  - scale: target_stop = v0 * scale (maps translational velocity to stopping distance)
    #  - curvature_coeff: proportionality for lateral drift per (av * v * dt)
    v0 = tv
    target_stop = max(1.0, v0 * scale)
    # choose k so that integral of v(t) approximates target_stop
    # ∫0..∞ v0 exp(-k t) dt = v0 / k => set k = v0 / target_stop
    k = v0 / target_stop
    t = 0.0
    x = 0.0
    y = 0.0
    traj = [(x,y)]
    # integrate until speed negligible
    while True:
        v = v0 * math.exp(-k * t)
        if v < 0.01:
            break
        dx = v * math.cos(sa_rad) * dt
        # lateral drift proportional to angular velocity * forward speed
        dy = curvature_coeff * av * v * dt
        # sign of drift uses sign of shot angle (consistent with sample clients)
        if sa_rad < 0:
            dy = -dy
        x += dx
        y += dy
        traj.append((x,y))
        t += dt
        if len(traj) > 5000:
            break
    est_dist = x
    return traj, est_dist, (x,y)


def longitudinal_acceleration(speed: float) -> float:
    # from FCV1: -(0.00200985f / (speed + 0.06385782f) + 0.00626286f) * g
    g = 9.80665
    return -(0.00200985 / (speed + 0.06385782) + 0.00626286) * g


def yaw_rate(speed: float, angular_velocity: float) -> float:
    # from FCV1: sign(angularVelocity) * 0.00820 * speed^{-0.8}
    if abs(angular_velocity) <= 1e-12:
        return 0.0
    return (1.0 if angular_velocity > 0.0 else -1.0) * 0.00820 * (speed ** -0.8)


def angular_acceleration(linear_speed: float) -> float:
    # from FCV1: -0.025 / max(linearSpeed, 0.001)
    clamped = max(linear_speed, 0.001)
    return -0.025 / clamped


def simulate_trajectory_fcv1(tv, av, sa_rad, dt=0.001):
    # FCV1-inspired time-stepping simulation (simple port of core equations)
    # state: position (x,y) where x is forward, y lateral; velocity vector follows heading
    x = 0.0
    y = 0.0
    # initial velocity along heading
    speed = tv
    # angular velocity (rad/s) - use av as given magnitude
    ang = av
    # heading direction unit vector (initial)
    heading = math.cos(sa_rad), math.sin(sa_rad)
    traj = [(x, y)]
    max_steps = 100000
    steps = 0
    while True:
        if speed <= 0.0:
            break
        # longitudinal accel
        a_long = longitudinal_acceleration(speed)
        new_speed = speed + a_long * dt
        if new_speed <= 0.0:
            # move remaining distance proportionally
            x += speed * heading[0] * dt
            y += speed * heading[1] * dt
            traj.append((x, y))
            speed = 0.0
            break
        # yaw (heading change) based on yaw_rate function
        yaw = yaw_rate(speed, ang) * dt
        # update heading by small rotation
        ch = math.cos(yaw)
        sh = math.sin(yaw)
        hx, hy = heading
        heading = (ch * hx - sh * hy, sh * hx + ch * hy)
        # decompose new velocity into longitudinal and transverse components
        longitudinal_v = new_speed * heading[0]
        transverse_v = new_speed * heading[1]
        x += longitudinal_v * dt
        y += transverse_v * dt
        traj.append((x, y))
        # angular velocity update
        ang_acc = angular_acceleration(speed) * dt
        if abs(ang) <= abs(ang_acc):
            ang = 0.0
        else:
            ang = ang + ang_acc * (ang / abs(ang))
        speed = new_speed
        steps += 1
        if steps >= max_steps:
            break
    est_dist = x
    return traj, est_dist, (x, y)


def classify_shot(tv, sa_deg, est_dist, final_xy):
    # heuristic classification
    if tv >= 2.42:
        return 'hit'
    if abs(sa_deg) < 7.5 and est_dist > 10:
        return 'draw'
    if abs(sa_deg) >= 7.5 and abs(sa_deg) < 20:
        return 'guard'
    return 'other'


def export_results(shots, scores, outdir, target_team='team0', scale=15.0, curvature_coeff=0.006, house_y=38.405, house_r=1.829):
    os.makedirs(outdir, exist_ok=True)
    csv_path = os.path.join(outdir, 'team0_shots.csv')
    traj_dir = os.path.join(outdir, 'trajectories')
    os.makedirs(traj_dir, exist_ok=True)

    with open(csv_path, 'w', newline='', encoding='utf-8') as csvf:
        writer = csv.writer(csvf)
        writer.writerow(['ts','end','total_shot_number','tv','av','sa_rad','sa_deg','est_distance','final_x_model','final_y_model','dc_x','dc_y','in_house','class','trajectory_file'])
        for i,s in enumerate(shots):
            # choose model: prefer precise model using recorded angular velocity
            av = s.get('av', None)
            if av is not None:
                native = simulate_trajectory_native_endpoint(
                    s['tv'],
                    av,
                    s['sa_rad'],
                    shooter_team=target_team,
                    total_shot_number=s.get('total'),
                )
                if native is not None:
                    traj, fx, fy = native
                    est_dist = fx
                else:
                    traj, est_dist, (fx,fy) = simulate_trajectory_fcv1(s['tv'], av, s['sa_rad'])
            else:
                traj, est_dist, (fx,fy) = simulate_trajectory(s['tv'], s['sa_rad'])
            cls = classify_shot(s['tv'], s['sa_deg'], est_dist, (fx,fy))
            traj_file = f'traj_{i:03d}.csv'
            with open(os.path.join(traj_dir, traj_file), 'w', newline='', encoding='utf-8') as tf:
                tw = csv.writer(tf)
                tw.writerow(['x','y'])
                for px,py in traj:
                    tw.writerow([f'{px:.6f}', f'{py:.6f}'])
            # Convert to DigitalCurling coordinates: model's forward x -> DC Y, model's lateral y -> DC X
            # Correct mapping: dc_x = model_y (fy), dc_y = model_x (fx)
            dc_x = fy
            dc_y = fx
            # whether inside house
            in_house = (math.hypot(dc_x - 0.0, dc_y - house_y) <= house_r) if house_y is not None else False
            writer.writerow([s['ts'], s['end'], s['total'] if s['total'] is not None else '', f'{s["tv"]:.6f}', f'{s["av"]:.6f}', f'{s["sa_rad"]:.6f}', f'{s["sa_deg"]:.2f}', f'{est_dist:.6f}', f'{fx:.6f}', f'{fy:.6f}', f'{dc_x:.6f}', f'{dc_y:.6f}', '1' if in_house else '0', cls, os.path.join('trajectories', traj_file)])

    # plots
    plt.figure(figsize=(8,6))
    colors = {'hit':'red','draw':'green','guard':'orange','other':'gray'}
    for i,s in enumerate(shots):
        try:
            av = s.get('av', None)
        except Exception:
            av = None
        if av is not None:
            traj, est_dist, (fx,fy) = simulate_trajectory_fcv1(s['tv'], av, s['sa_rad'])
        else:
            traj, est_dist, (fx,fy) = simulate_trajectory(s['tv'], s['sa_rad'])
        cls = classify_shot(s['tv'], s['sa_deg'], est_dist, (fx,fy))
        xs = [p[0] for p in traj]
        ys = [p[1] for p in traj]
        plt.plot(xs, ys, color=colors.get(cls,'gray'), alpha=0.6)
    plt.xlabel('x (m)')
    plt.ylabel('y (m)')
    plt.title('Estimated trajectories for TEAM0 shots')
    plt.grid(True)
    plt.axvline(0, color='k', lw=0.5)
    plt.savefig(os.path.join(outdir, 'trajectories.png'))
    plt.close()

    # shot type histogram
    types = defaultdict(int)
    for s in shots:
        try:
            av = s.get('av', None)
        except Exception:
            av = None
        if av is not None:
            traj, est_dist, (fx,fy) = simulate_trajectory_fcv1(s['tv'], av, s['sa_rad'])
        else:
            traj, est_dist, (fx,fy) = simulate_trajectory(s['tv'], s['sa_rad'])
        cls = classify_shot(s['tv'], s['sa_deg'], est_dist, (fx,fy))
        types[cls]+=1
    plt.figure(figsize=(6,4))
    plt.bar(list(types.keys()), [types[k] for k in types.keys()], color=[colors.get(k,'gray') for k in types.keys()])
    plt.title('Shot classification counts (TEAM0)')
    plt.savefig(os.path.join(outdir, 'shot_types.png'))
    plt.close()

    # tv vs sa scatter
    tvs=[s['tv'] for s in shots]
    sas=[s['sa_deg'] for s in shots]
    classes=[classify_shot(s['tv'], s['sa_deg'], 0, (0,0)) for s in shots]
    plt.figure(figsize=(6,4))
    for tv,sa,cls in zip(tvs,sas,classes):
        plt.scatter(tv, sa, color=colors.get(cls,'gray'), alpha=0.7)
    plt.xlabel('translational_velocity')
    plt.ylabel('shot_angle (deg)')
    plt.title('TV vs Angle (TEAM0)')
    plt.grid(True)
    plt.savefig(os.path.join(outdir, 'tv_vs_angle.png'))
    plt.close()

    # metadata
    meta = {
        'num_shots': len(shots),
        'scores': scores,
        'fcv1_native': NATIVE_INFO,
        'generated': datetime.datetime.utcnow().isoformat() + 'Z'
    }
    with open(os.path.join(outdir, 'meta.json'), 'w', encoding='utf-8') as mf:
        json.dump(meta, mf, indent=2)


def main():
    # allow optional command-line override: python export_shot_analysis.py <log_path> [team0|team1]
    log_to_use = LOG_PATH
    team_to_analyze = 'team0'
    if len(sys.argv) >= 2 and sys.argv[1]:
        log_to_use = sys.argv[1]
    if len(sys.argv) >= 3 and sys.argv[2] in ('team0', 'team1'):
        team_to_analyze = sys.argv[2]
    ensure_fcv1_native_simulator()
    shots, scores = parse_logs(log_to_use, target_team=team_to_analyze)
    if not shots:
        print(f'No {team_to_analyze.upper()} shots found.')
        return
    now = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    outdir = os.path.join(os.path.dirname(__file__), '..', 'analysis_outputs', os.path.splitext(os.path.basename(log_to_use))[0] + '_' + team_to_analyze + '_' + now)
    outdir = os.path.abspath(outdir)
    export_results(shots, scores, outdir, target_team=team_to_analyze)
    if NATIVE_INFO.get('enabled'):
        print('FCV1 native simulator loaded:', NATIVE_INFO.get('path'))
    else:
        print('FCV1 native simulator not loaded:', NATIVE_INFO.get('reason'))
    print('Exported analysis to', outdir)


if __name__ == '__main__':
    main()
