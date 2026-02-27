import importlib.util
import os
p = os.path.join(os.path.dirname(__file__), 'export_shot_analysis.py')
spec = importlib.util.spec_from_file_location('m', p)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

# sample params
params = (
    2.406984,    # tv
    -15.707963,  # av
    0.055007     # sa_rad
)
traj, est, (fx, fy) = m.simulate_trajectory_fcv1(*params)
print('traj_len', len(traj))
print('first5', traj[:5])
print('est fx fy', est, fx, fy)
native = m.simulate_trajectory_native_endpoint(params[0], params[1], params[2], shooter_team='team0', total_shot_number=3)
print('native result is None?', native is None)
if native is not None:
    ntraj, nfx, nfy = native
    print('native fx,f y:', nfx, nfy)
    print('native first5', ntraj[:5])
