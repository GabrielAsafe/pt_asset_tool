import bpy, json, pathlib, sys


def args_after_double_dash():
    argv=sys.argv
    return argv[argv.index('--')+1:] if '--' in argv else []


def main():
    args=args_after_double_dash()
    report=None
    for i,x in enumerate(args):
        if x == '--report' and i+1 < len(args):
            report=pathlib.Path(args[i+1])
    if report is None:
        raise RuntimeError('--report is required')

    weighted={}
    mesh_rows=[]
    for obj in bpy.data.objects:
        if obj.type != 'MESH':
            continue
        per={}
        weighted_vertices=0
        for v in obj.data.vertices:
            hit=False
            for elem in v.groups:
                if elem.weight <= 1e-8:
                    continue
                if elem.group < 0 or elem.group >= len(obj.vertex_groups):
                    continue
                vg=obj.vertex_groups[elem.group]
                row=per.setdefault(vg.name, {'group_index':int(vg.index),'vertices':0,'weight_sum':0.0})
                row['vertices'] += 1
                row['weight_sum'] += float(elem.weight)
                allrow=weighted.setdefault(vg.name, {'group_indices':set(),'vertices':0,'weight_sum':0.0})
                allrow['group_indices'].add(int(vg.index)); allrow['vertices'] += 1; allrow['weight_sum'] += float(elem.weight)
                hit=True
            if hit:
                weighted_vertices += 1
        mesh_rows.append({'object':obj.name,'vertex_count':len(obj.data.vertices),
                          'weighted_vertices':weighted_vertices,'weighted_groups':sorted(per.values(), key=lambda x:x['group_index'])})

    out_groups=[]
    for name,row in weighted.items():
        out_groups.append({'name':name,'group_indices':sorted(row['group_indices']),
                           'vertices':row['vertices'],'weight_sum':row['weight_sum']})
    out_groups.sort(key=lambda x:(x['group_indices'][0] if x['group_indices'] else 10**9, x['name'].casefold()))

    armatures=[]
    for obj in bpy.data.objects:
        if obj.type == 'ARMATURE':
            armatures.append({'object':obj.name,'bones':[b.name for b in obj.data.bones]})

    payload={'format':'PT_PHYSIQUE_USAGE_V1','mesh_objects':mesh_rows,
             'weighted_groups':out_groups,'weighted_group_count':len(out_groups),
             'armatures':armatures}
    report.parent.mkdir(parents=True,exist_ok=True)
    report.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(payload,ensure_ascii=False))

if __name__ == '__main__':
    main()
