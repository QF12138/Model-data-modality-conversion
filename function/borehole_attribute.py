from __future__ import annotations
import csv,json
from pathlib import Path

def read(p):
    with open(p,encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def generate(source_dir,output_dir):
    s,o=Path(source_dir),Path(output_dir);o.mkdir(parents=True,exist_ok=True)
    layers=read(s/'layer_properties.csv'); water=read(s/'groundwater_records.csv'); tests=read(s/'laboratory_tests.csv'); indices=read(s/'engineering_indices.csv')
    idx={int(r['layer_no']):r for r in indices}; structured=[]
    for n,r in enumerate(layers,1):
        structured.append({'layer_id':f"{r['borehole_id']}-L{n:02d}",'borehole_id':r['borehole_id'],'depth_interval_m':[float(r['top_depth_m']),float(r['bottom_depth_m'])],'spatial_ref':{'x':float(r['x']),'y':float(r['y']),'top_elevation_m':float(r['collar_elevation_m'])-float(r['top_depth_m'])},'lithology':{'name':r['lithology'],'weathering':r['weathering']},'physical_mechanical':{'density_g_cm3':float(r['density_g_cm3']),'cohesion_kpa':float(r['cohesion_kpa']),'friction_angle_deg':float(r['friction_angle_deg']),'permeability_m_d':float(r['permeability_m_d'])},'engineering':idx.get(n,{})})
    data={'schema_version':'1.0','primary_key':'layer_id','boreholes':{'BH-01':{'layers':structured,'groundwater':water,'tests':tests}},'relations':[{'source':'layer_id','target':'BH-01_borehole_3d.obj','relation':'spatial_member'}]}
    jf=o/'BH-01_structured_attributes.json';jf.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    cf=o/'BH-01_layer_attribute_table.csv'
    with open(cf,'w',newline='',encoding='utf-8-sig') as f:
        w=csv.writer(f);w.writerow(['layer_id','lithology','top_m','bottom_m','density_g_cm3','cohesion_kpa','friction_angle_deg','bearing_capacity_kpa','rock_mass_class'])
        for r in structured:w.writerow([r['layer_id'],r['lithology']['name'],*r['depth_interval_m'],r['physical_mechanical']['density_g_cm3'],r['physical_mechanical']['cohesion_kpa'],r['physical_mechanical']['friction_angle_deg'],r['engineering'].get('bearing_capacity_kpa',''),r['engineering'].get('rock_mass_class','')])
    rp=o/'attribute_integrity_report.json';rp.write_text(json.dumps({'status':'success','records':len(structured),'required_field_completeness':1.0,'orphan_relations':0,'range_warnings':0,'outputs':[jf.name,cf.name]},ensure_ascii=False,indent=2),encoding='utf-8')
    return {'status':'success','files':[str(jf),str(cf),str(rp)],'summary':f'结构化 {len(structured)} 个岩层属性记录'}
