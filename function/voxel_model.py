from __future__ import annotations
import csv,json,math
from pathlib import Path

def generate(source_dir,output_dir):
    s,o=Path(source_dir),Path(output_dir);o.mkdir(parents=True,exist_ok=True);cfg=json.loads((s/'model_boundary.json').read_text(encoding='utf-8'));dic=json.loads((s/'lithology_dictionary.json').read_text(encoding='utf-8'))
    with open(s/'geologic_samples.csv',encoding='utf-8-sig',newline='') as f:samples=list(csv.DictReader(f))
    ox,oy,oz=cfg['origin'];sx,sy,sz=cfg['size'];dx,dy,dz=cfg['voxel_size'];nx,ny,nz=int(sx/dx),int(sy/dy),int(sz/dz)
    rows=[]
    for k in range(nz):
      z=oz+(k+.5)*dz
      for j in range(ny):
       y=oy+(j+.5)*dy
       for i in range(nx):
        x=ox+(i+.5)*dx;near=sorted(samples,key=lambda r:(x-float(r['x']))**2+(y-float(r['y']))**2+(z-float(r['z']))**2)[:4]
        weights=[1/max(1e-9,math.dist((x,y,z),(float(r['x']),float(r['y']),float(r['z'])))**2) for r in near];density=sum(w*float(r['density_g_cm3']) for w,r in zip(weights,near))/sum(weights);perm=sum(w*float(r['permeability_m_d']) for w,r in zip(weights,near))/sum(weights);code=max(set(r['lithology_code'] for r in near),key=lambda c:sum(w for w,r in zip(weights,near) if r['lithology_code']==c));rows.append([i,j,k,x,y,z,code,dic[code]['name'],round(density,4),round(perm,5)])
    csvp=o/'geologic_voxel_cells.csv'
    with open(csvp,'w',newline='',encoding='utf-8-sig') as f:w=csv.writer(f);w.writerow(['i','j','k','center_x','center_y','center_z','lithology_code','lithology_name','density_g_cm3','permeability_m_d']);w.writerows(rows)
    hdr=o/'geologic_voxel_model.json';hdr.write_text(json.dumps({'format':'regular_voxel_grid','dimensions':[nx,ny,nz],'origin':cfg['origin'],'voxel_size':cfg['voxel_size'],'cell_count':len(rows),'attributes':['lithology_code','density_g_cm3','permeability_m_d'],'data_file':csvp.name,'crs':cfg['crs']},ensure_ascii=False,indent=2),encoding='utf-8')
    rp=o/'voxel_generation_report.json';rp.write_text(json.dumps({'status':'success','cell_count':len(rows),'empty_ratio':0.0,'interpolation':cfg['interpolation'],'lithology_classes':len(dic),'bounds':[cfg['origin'],cfg['size']]},ensure_ascii=False,indent=2),encoding='utf-8')
    return {'status':'success','files':[str(csvp),str(hdr),str(rp)],'summary':f'生成 {nx}×{ny}×{nz} 规则体素，共 {len(rows)} 个单元'}
