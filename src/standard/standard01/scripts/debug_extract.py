import json,re,ast,sys
from pathlib import Path
p = Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).parent.parent / 'logs' / 'dc4_team1_20260225_170008.jsonl'

key = 'stone_coordinate=StoneCoordinateSchema(data='

with p.open('r',encoding='utf-8') as f:
    for i,line in enumerate(f):
        if i>200: break
        line=line.strip()
        if not line: continue
        try:
            obj=json.loads(line)
            msg=obj.get('message','')
        except Exception:
            continue
        if key in msg:
            print('LINE',i)
            start = msg.find(key)+len(key)
            em = msg.find('}) score=', start)
            print('has end_marker?', em!=-1)
            if em!=-1:
                frag = msg[start:em+1]
            else:
                # fallback small slice
                frag = msg[start:start+300]
            print('FRAG_SNIPPET:', frag[:200])
            frag2 = re.sub(r"CoordinateDataSchema\\(x=([0-9eE+\-\\.]+), y=([0-9eE+\-\\.]+)\\)", r'{"x":\1, "y":\2}', frag)
            frag2 = frag2.replace("'team0'", '"team0"').replace("'team1'", '"team1"')
            frag2 = frag2.replace("'", '"')
            print('AFTER_SNIPPET:', frag2[:200])
            try:
                d = ast.literal_eval(frag2)
                print('PARSED:', {k: len(v) for k,v in d.items()})
            except Exception as e:
                print('PARSE ERROR:', e)
            print('---')
