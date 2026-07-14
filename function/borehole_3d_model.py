import json

def create_vertical_cylinder(x,y,z,top,bottom,r=0.8):
    return {"center":[x,y,z-(top+bottom)/2],"height":bottom-top,"radius":r}

def borehole_to_3d(borehole, layers):
    objects=[]
    for layer in layers:
        objects.append({
            "BH_ID":borehole["BH_ID"],
            "lithology":layer["lithology"],
            "geometry":create_vertical_cylinder(float(borehole["X"]),float(borehole["Y"]),float(borehole["Z"]),float(layer["depth_top"]),float(layer["depth_bottom"]))
        })
    return objects

def export_vtk_like(objects,path):
    with open(path,"w",encoding="utf-8") as f:
        json.dump(objects,f,ensure_ascii=False,indent=2)
