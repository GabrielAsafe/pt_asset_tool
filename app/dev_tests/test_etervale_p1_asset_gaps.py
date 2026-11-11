from pt_asset_tool.etervale_asset_gaps import parse_matbounds, classify_rows, _csv
import csv

SAMPLE='''\n  173  ALPHA           1  (-236,5, 304,1, 18361,2)       (71,9, 107,0, 1,0)              tem_wall04.bmp\n  174  ALPHA           0  (-236,5, 304,1, 18361,2)       (71,9, 107,0, 1,0)              missing_unused.bmp\n'''

def test_miss_only_when_material_has_faces(tmp_path):
    stage=tmp_path/'village-2.smd'; stage.write_bytes(b'legacy')
    rows=parse_matbounds(SAMPLE)
    assert len(rows)==2
    result=classify_rows(stage,rows)
    assert result[0]['state']=='MISSING_LOCAL'
    assert result[1]['state']=='UNUSED_MATERIAL_REFERENCE'

def test_case_insensitive_present_local(tmp_path):
    stage=tmp_path/'village-2.smd'; stage.write_bytes(b'legacy')
    (tmp_path/'tem_wall04.BMP').write_bytes(b'bitmap')
    result=classify_rows(stage,parse_matbounds(SAMPLE))
    assert result[0]['state']=='PRESENT_LOCAL'

def test_csv_report(tmp_path):
    p=tmp_path/'missing.csv';_csv(p,[{'stage':'X','material':173,'faces':1,'texture':'tem_wall04.bmp','state':'MISSING_LOCAL'}])
    with p.open() as f:rows=list(csv.DictReader(f))
    assert rows[0]['state']=='MISSING_LOCAL'
