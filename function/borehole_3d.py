from __future__ import annotations
import json, math
from pathlib import Path
from typing import Any


def _ring(center: tuple[float,float,float], radius: float, segments: int) -> list[tuple[float,float,float]]:
    x,y,z=center
    return [(x+radius*math.cos(2*math.pi*i/segments), y+radius*math.sin(2*math.pi*i/segments), z) for i in range(segments)]


def build_borehole_3d(source_file: str | Path, output_dir: str | Path) -> dict[str, Any]:
    src=Path(source_file); out=Path(output_dir); out.mkdir(parents=True, exist_ok=True)
    data=json.loads(src.read_text(encoding='utf-8'))
    bid=data['borehole_id']; c=data['collar']; az=math.radians(float(data.get('azimuth_deg',0))); inc=math.radians(float(data.get('inclination_deg',90)))
    radius=float(data.get('diameter_m',0.13))/2; seg=20
    def center(depth: float):
        horizontal=depth*math.cos(inc)
        return (c['x']+horizontal*math.sin(az), c['y']+horizontal*math.cos(az), c['elevation']-depth*math.sin(inc))
    obj=[]; mtl=[]; vertices=[]; faces=[]; groups=[]
    for li,layer in enumerate(data['layers']):
        top=center(float(layer['top_m'])); bottom=center(float(layer['bottom_m']))
        start=len(vertices)+1; vertices.extend(_ring(top,radius,seg)+_ring(bottom,radius,seg))
        fs=[]
        for i in range(seg):
            a=start+i; b=start+(i+1)%seg; c1=start+seg+(i+1)%seg; d=start+seg+i
            fs.append((a,b,c1,d))
        fs += [tuple(start+i for i in range(seg-1,-1,-1)), tuple(start+seg+i for i in range(seg))]
        faces.extend(fs); groups.append((f"layer_{li+1}_{layer['code']}", f"mat_{li+1}", len(faces)-len(fs), len(faces)))
        r,g,b=layer.get('color',[0.6,0.6,0.6]); mtl += [f"newmtl mat_{li+1}", f"Kd {r} {g} {b}", "Ka 0.15 0.15 0.15", "Ks 0.08 0.08 0.08", ""]
    obj=[f"# Borehole {bid}",f"mtllib {bid}.mtl"]+[f"v {x:.4f} {y:.4f} {z:.4f}" for x,y,z in vertices]
    for name,mat,s,e in groups:
        obj += [f"g {name}",f"usemtl {mat}"]+["f "+" ".join(map(str,f)) for f in faces[s:e]]
    # groundwater disk and discontinuity markers as comments/points
    gw=data.get('groundwater',[])
    if gw:
        gx,gy,gz=center(float(gw[-1]['depth_m'])); obj += [f"# groundwater {gw[-1]['depth_m']}m",f"v {gx:.4f} {gy:.4f} {gz:.4f}",f"p {len(vertices)+1}"]
    obj_path=out/f"{bid}_borehole.obj"; mtl_path=out/f"{bid}_borehole.mtl"; idx_path=out/f"{bid}_index.json"
    obj_path.write_text("\n".join(obj)+"\n",encoding='utf-8'); mtl_path.write_text("\n".join(mtl),encoding='utf-8')
    index={"borehole_id":bid,"source":str(src.resolve()),"coordinate_reference":"project_local_metric","layer_count":len(data['layers']),"vertex_count":len(vertices)+(1 if gw else 0),"face_count":len(faces),"groundwater":gw,"tests":data.get('tests',[]),"discontinuities":data.get('discontinuities',[]),"objects":[{"group":g[0],"material":g[1],"layer":data['layers'][i]} for i,g in enumerate(groups)]}
    idx_path.write_text(json.dumps(index,ensure_ascii=False,indent=2),encoding='utf-8')
    return {"status":"success","module":"borehole_3d","source_files":[str(src)],"output_files":[str(obj_path),str(mtl_path),str(idx_path)],"summary":{"borehole_id":bid,"layers":len(data['layers']),"tests":len(data.get('tests',[])),"discontinuities":len(data.get('discontinuities',[])),"groundwater_records":len(gw),"vertices":index['vertex_count'],"faces":len(faces)}}
