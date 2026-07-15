from __future__ import annotations
import csv,json,math
from pathlib import Path
from typing import Any

def generate_voxel_model(sample_file: str|Path, config_file: str|Path, output_dir: str|Path) -> dict[str,Any]:
    out=Path(output_dir);out.mkdir(parents=True,exist_ok=True);cfg=json.loads(Path(config_file).read_text(encoding='utf-8'))
    with Path(sample_file).open(encoding='utf-8-sig',newline='') as f:samples=list(csv.DictReader(f))
    for s in samples:
        for k in ('x','y','z','density_g_cm3','permeability_m_s'):s[k]=float(s[k])
    ox,oy,oz=cfg['origin']; sx,sy,sz=cfg['size']; vx,vy,vz=cfg['voxel_size']; nx,ny,nz=round(sx/vx),round(sy/vy),round(sz/vz); power=float(cfg.get('power',2)); nmax=int(cfg.get('max_neighbors',6))
    cells=[]
    for k in range(nz):
      z=oz+(k+.5)*vz
      for j in range(ny):
       y=oy+(j+.5)*vy
       for i in range(nx):
        x=ox+(i+.5)*vx; near=sorted(samples,key=lambda s:(s['x']-x)**2+(s['y']-y)**2+(s['z']-z)**2)[:nmax]
        weights=[1/max(math.dist((x,y,z),(s['x'],s['y'],s['z']))**power,1e-12) for s in near]; sw=sum(weights)
        dens=sum(w*s['density_g_cm3'] for w,s in zip(weights,near))/sw; perm=10**(sum(w*math.log10(s['permeability_m_s']) for w,s in zip(weights,near))/sw)
        lith=max(set(s['lithology'] for s in near),key=lambda l:sum(w for w,s in zip(weights,near) if s['lithology']==l))
        cells.append({"id":len(cells)+1,"i":i,"j":j,"k":k,"x":round(x,3),"y":round(y,3),"z":round(z,3),"lithology":lith,"density_g_cm3":round(dens,4),"permeability_m_s":perm})
    csvp=out/f"{cfg['model_id']}_voxels.csv";jsonp=out/f"{cfg['model_id']}_voxel_model.json"
    with csvp.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=cells[0].keys());w.writeheader();w.writerows(cells)
    result={"model_id":cfg['model_id'],"grid":{"origin":cfg['origin'],"size":cfg['size'],"voxel_size":cfg['voxel_size'],"dimensions":[nx,ny,nz],"cell_count":len(cells)},"interpolation":{"method":cfg['interpolation'],"power":power,"max_neighbors":nmax,"sample_count":len(samples)},"lithology_counts":{l:sum(1 for c in cells if c['lithology']==l) for l in sorted(set(c['lithology'] for c in cells))},"attribute_file":csvp.name}
    jsonp.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return {"status":"success","module":"voxel_model","source_files":[str(sample_file),str(config_file)],"output_files":[str(csvp),str(jsonp)],"summary":result}
