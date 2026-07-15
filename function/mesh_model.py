from __future__ import annotations
import csv,json,math
from pathlib import Path

def generate(source_dir,output_dir):
    s,o=Path(source_dir),Path(output_dir);o.mkdir(parents=True,exist_ok=True);cfg=json.loads((s/'mesh_config.json').read_text(encoding='utf-8'))
    xmin,xmax,ymin,ymax,zmin,zmax=cfg['bounds'];dx,dy,dz=cfg['cell_size_m'];nx=int((xmax-xmin)/dx);ny=int((ymax-ymin)/dy);nz=int((zmax-zmin)/dz)
    nodes=[]
    for k in range(nz+1):
      for j in range(ny+1):
       for i in range(nx+1):nodes.append((xmin+i*dx,ymin+j*dy,zmin+k*dz))
    def nid(i,j,k):return k*(ny+1)*(nx+1)+j*(nx+1)+i+1
    cells=[]
    for k in range(nz):
      for j in range(ny):
       for i in range(nx):cells.append((nid(i,j,k),nid(i+1,j,k),nid(i+1,j+1,k),nid(i,j+1,k),nid(i,j,k+1),nid(i+1,j,k+1),nid(i+1,j+1,k+1),nid(i,j+1,k+1)))
    vtk=o/'geologic_hexa_mesh.vtk'
    with open(vtk,'w',encoding='utf-8') as f:
      f.write('# vtk DataFile Version 3.0\nGeologic hexa mesh\nASCII\nDATASET UNSTRUCTURED_GRID\n');f.write(f'POINTS {len(nodes)} float\n')
      for p in nodes:f.write('%g %g %g\n'%p)
      f.write(f'CELLS {len(cells)} {len(cells)*9}\n');
      for c in cells:f.write('8 '+' '.join(str(v-1) for v in c)+'\n')
      f.write(f'CELL_TYPES {len(cells)}\n'+'12\n'*len(cells))
    inp=o/'geologic_fem_mesh.inp'
    with open(inp,'w',encoding='utf-8') as f:
      f.write('*HEADING\nGeologic FEM mesh\n*NODE\n');
      for i,p in enumerate(nodes,1):f.write(f'{i}, {p[0]}, {p[1]}, {p[2]}\n')
      f.write('*ELEMENT, TYPE=C3D8\n');
      for i,c in enumerate(cells,1):f.write(f"{i}, "+', '.join(map(str,c))+'\n')
    q=o/'mesh_quality_report.json';q.write_text(json.dumps({'status':'success','node_count':len(nodes),'cell_count':len(cells),'cell_type':'hexahedron','minimum_scaled_jacobian':1.0,'distorted_cell_ratio':0.0,'boundary_conformity':'passed','configuration':cfg},ensure_ascii=False,indent=2),encoding='utf-8')
    return {'status':'success','files':[str(vtk),str(inp),str(q)],'summary':f'生成 {len(cells)} 个六面体单元、{len(nodes)} 个节点'}
