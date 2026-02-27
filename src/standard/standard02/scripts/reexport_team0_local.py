import os, datetime, importlib.util, sys, json
# load export_shot_analysis as module
p = os.path.join(os.path.dirname(__file__), 'export_shot_analysis.py')
spec = importlib.util.spec_from_file_location('esa', p)
esa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(esa)

log_path = r'.\standard02\logs\dc4_team1_20260227_114556.jsonl'
team = 'team0'
shots, scores = esa.parse_logs(log_path, target_team=team)
if not shots:
    print('No shots found for', team)
    sys.exit(1)
# disable native use
esa.NATIVE_INFO['enabled'] = False
now = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
outdir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'analysis_outputs', os.path.splitext(os.path.basename(log_path))[0] + '_' + team + '_' + now))
esa.export_results(shots, scores, outdir, target_team=team)
print('Re-exported to', outdir)
with open(os.path.join(outdir,'meta_local_override.json'),'w',encoding='utf-8') as f:
    json.dump({'native_forced_off':True},f,indent=2)
