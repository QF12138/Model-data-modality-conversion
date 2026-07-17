from __future__ import annotations
import csv,json
from pathlib import Path
from typing import Any

def structure_borehole_attributes(log_file: str|Path, water_file: str|Path, output_dir: str|Path) -> dict[str,Any]:
    out=Path(output_dir); out.mkdir(parents=True,exist_ok=True)
    def rows(p):
        with Path(p).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
    logs=rows(log_file); waters=rows(water_file); bid=logs[0]['borehole_id']
    numeric={'top_m','bottom_m','density_g_cm3','cohesion_kpa','friction_deg','permeability_m_s','modulus_mpa','spt_n','rock_ucs_mpa','water_depth_m','water_elevation_m','temperature_c'}
    def typed(row):
        result={}
        for k,v in row.items():
            if k in numeric: result[k]=None if v in ('',None) else float(v)
            else: result[k]=v
        return result
    layers=[typed(r) for r in logs]; water=[typed(r) for r in waters]
    issues=[]
    for i,r in enumerate(layers):
        if r['bottom_m']<=r['top_m']:issues.append({"level":"error","field":"depth","row":i+1,"message":"bottom_m must exceed top_m"})
        if i and abs(r['top_m']-layers[i-1]['bottom_m'])>1e-6:issues.append({"level":"warning","field":"depth","row":i+1,"message":"layer sequence has gap or overlap"})
    doc={"schema_version":"1.0","borehole":{"id":bid,"total_depth_m":layers[-1]['bottom_m'],"layer_count":len(layers)},"lithology_layers":layers,"groundwater":{"records":water,"stable_depth_m":water[-1]['water_depth_m'] if water else None},"engineering_summary":{"density_range_g_cm3":[min(r['density_g_cm3'] for r in layers),max(r['density_g_cm3'] for r in layers)],"permeability_range_m_s":[min(r['permeability_m_s'] for r in layers),max(r['permeability_m_s'] for r in layers)],"rock_layers":sum(1 for r in layers if r['weathering']!='无')},"spatial_relation":{"object_key":f"borehole:{bid}","join_key":"borehole_id","depth_reference":"collar_downward_m"},"quality":{"complete":not any(i['level']=='error' for i in issues),"issues":issues}}
    p=out/f"{bid}_attributes.json"; p.write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding='utf-8')
    return {"status":"success" if doc['quality']['complete'] else "warning","module":"borehole_attr","source_files":[str(log_file),str(water_file)],"output_files":[str(p)],"summary":{"borehole_id":bid,"layers":len(layers),"water_records":len(water),"quality_issues":len(issues)}}
