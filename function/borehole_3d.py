from __future__ import annotations
import csv, json, math
from pathlib import Path

def _read(path):
    with open(path, encoding='utf-8-sig', newline='') as f: return list(csv.DictReader(f))

def generate(source_dir: str|Path, output_dir: str|Path) -> dict:
    source_dir, output_dir = Path(source_dir), Path(output_dir); output_dir.mkdir(parents=True, exist_ok=True)
    layers=_read(source_dir/'borehole_layers.csv'); water=_read(source_dir/'groundwater.csv'); tests=_read(source_dir/'tests.csv'); joints=_read(source_dir/'joints.csv')
    if not layers: raise ValueError('岩性分层表为空')
    x=float(layers[0]['x']); y=float(layers[0]['y']); collar=float(layers[0]['collar_elevation_m']); radius=0.65; seg=16
    obj=output_dir/'BH-01_borehole_3d.obj'; mtl=output_dir/'BH-01_borehole_3d.mtl'
    colors=[(0.62,0.47,0.32),(0.76,0.62,0.38),(0.69,0.42,0.23),(0.54,0.34,0.20),(0.39,0.25,0.16)]
    with open(mtl,'w',encoding='utf-8') as f:
        for i,c in enumerate(colors,1): f.write(f'newmtl layer_{i}\nKd {c[0]} {c[1]} {c[2]}\n\n')
        f.write('newmtl groundwater\nKd 0.15 0.55 0.92\nd 0.65\n')
    verts=[]; faces=[]; groups=[]
    for li,row in enumerate(layers):
        top=collar-float(row['top_depth_m']); bot=collar-float(row['bottom_depth_m']); start=len(verts)
        for z in (top,bot):
            for i in range(seg):
                a=2*math.pi*i/seg; verts.append((x+radius*math.cos(a),y+radius*math.sin(a),z))
        fs=[]
        for i in range(seg):
            a=start+i+1;b=start+(i+1)%seg+1;c=start+seg+(i+1)%seg+1;d=start+seg+i+1;fs.append((a,b,c,d))
        groups.append((li+1,row['lithology'],fs))
    with open(obj,'w',encoding='utf-8') as f:
        f.write('# 三维钻孔对象 BH-01\nmtllib BH-01_borehole_3d.mtl\n')
        for v in verts:f.write('v %.4f %.4f %.4f\n'%v)
        for idx,name,fs in groups:
            f.write(f'g layer_{idx}_{name}\nusemtl layer_{idx}\n');
            for face in fs:f.write('f '+' '.join(map(str,face))+'\n')
    index={'borehole_id':'BH-01','crs':'EPSG:4547','collar':[x,y,collar],'total_depth_m':max(float(r['bottom_depth_m']) for r in layers),'layers':layers,'groundwater':water,'tests':tests,'joints':joints,'obj_file':obj.name}
    idx=output_dir/'BH-01_spatial_index.json'; idx.write_text(json.dumps(index,ensure_ascii=False,indent=2),encoding='utf-8')
    report=output_dir/'BH-01_generation_report.json'; report.write_text(json.dumps({'status':'success','layer_count':len(layers),'test_count':len(tests),'joint_count':len(joints),'vertex_count':len(verts),'face_count':sum(len(g[2]) for g in groups),'outputs':[obj.name,mtl.name,idx.name]},ensure_ascii=False,indent=2),encoding='utf-8')
    return {'status':'success','files':[str(obj),str(mtl),str(idx),str(report)],'summary':f'生成 {len(layers)} 层三维钻孔，{len(verts)} 个顶点'}
