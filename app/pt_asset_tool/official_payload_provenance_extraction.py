from __future__ import annotations

import argparse
import hashlib
import json
import mmap
import pathlib
import re
import shutil
import tarfile
import tempfile
import zipfile
from typing import Any

from .config import Settings
from .official_character_donor_census import _parse_donor_spec
from .official_container_character_atlas import _guard_snapshot
from .official_container_entry_recovery import _verify_content_baseline, _infer_model062_length
from .official_container_record_index import _lha_entries
from .rare_rigid_context import parse_model062_physique_context

FORMAT = "PT_OFFICIAL_PAYLOAD_PROVENANCE_EXTRACTION_V1"
RELEASE = "0.10.1"
PRIOR_FORMAT = "PT_OFFICIAL_PAYLOAD_SOURCE_LOCATOR_V1"
MODEL062 = b"SMD Model data Ver 0.62"
ARCHIVE_SUFFIXES = {".upw", ".zip", ".lha", ".lzh", ".rar", ".7z", ".cab", ".pak", ".pkg", ".gz", ".tgz", ".tar"}
PACK_RE = re.compile(r"^(?:[cbfl]data\d+|bdata\d+)$", re.I)
TARGET_RE = re.compile(r"^(?:6tfbf|ctfbf|tfbf|tfhf).+\.(?:smd|smb|inx|inf)$", re.I)
BODY_RE = re.compile(r"^(?:6tfbf|ctfbf|tfbf).+\.smd$", re.I)
HEAD_RE = re.compile(r"^tfhf.+\.smd$", re.I)


def _sha(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open('rb') as f:
        for c in iter(lambda: f.read(1024*1024), b''):
            h.update(c)
    return h.hexdigest()


def _snapshot(root: pathlib.Path) -> dict[str, tuple[int,int]]:
    out = {}
    if not root.is_dir(): return out
    for p in root.rglob('*'):
        if not p.is_file(): continue
        try: st=p.stat()
        except OSError: continue
        out[p.relative_to(root).as_posix()] = (int(st.st_size), int(st.st_mtime_ns))
    return out


def _is_within(p: pathlib.Path, root: pathlib.Path) -> bool:
    try: p.resolve().relative_to(root.resolve()); return True
    except Exception: return False


def _strict_prior(root: pathlib.Path) -> tuple[dict[str,Any],dict[str,Any]]:
    rp=root/'pt_build/official_payload_source_locator_v01000.json'
    bp=root/'pt_build/summit_client_content_baseline_v0960.json'
    if not rp.is_file(): raise FileNotFoundError(f'V01000_REPORT_MISSING:{rp}')
    if not bp.is_file(): raise FileNotFoundError(f'V0960_BASELINE_MISSING:{bp}')
    r=json.loads(rp.read_text(encoding='utf-8'))
    if r.get('format')!=PRIOR_FORMAT or r.get('status')!='PASS' or r.get('release_version')!='0.10.0':
        raise RuntimeError('V01000_STRICT_REPORT_MISMATCH')
    g=r.get('guards') or {}
    if not g.get('certified_writer_hashes_valid') or g.get('writer_modules_modified') or g.get('production_policies_modified'):
        raise RuntimeError('V01000_GUARD_STATE_INVALID')
    b=json.loads(bp.read_text(encoding='utf-8'))
    if b.get('format')!='PT_SUMMIT_CLIENT_CONTENT_BASELINE_V1' or b.get('status')!='PASS_READ_ONLY_WINDOW':
        raise RuntimeError('V0960_CONTENT_BASELINE_INVALID')
    return r,b


def _is_target(name: str) -> bool:
    return bool(TARGET_RE.match(pathlib.PurePosixPath(name.replace('\\','/')).name))


def _safe_member_name(name: str) -> str:
    return pathlib.PurePosixPath(name.replace('\\','/')).name


def _validate_smd_bytes(data: bytes, temp_dir: pathlib.Path, name: str) -> dict[str,Any]:
    if not data.startswith(MODEL062):
        return {'pass':False,'reason':'MODEL062_HEADER_MISMATCH'}
    tmp=temp_dir/(name+'.validate.smd')
    tmp.write_bytes(data)
    try:
        # Exact standalone closure from the serialized object table.
        with tmp.open('rb') as f:
            mm=mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ)
            try: length,err=_infer_model062_length(mm,0)
            finally: mm.close()
        if err is not None or length!=len(data):
            return {'pass':False,'reason':f'MODEL062_LENGTH_NOT_CLOSED:{err}:{length}:{len(data)}'}
        ctx=parse_model062_physique_context(tmp)
        return {
            'pass':True,
            'object_count':len(ctx.get('objects') or []),
            'bind_bone_count':len(ctx.get('bind_bones') or []),
            'bind_bones':(ctx.get('bind_bones') or [])[:80],
        }
    except Exception as exc:
        return {'pass':False,'reason':f'PHYSICAL_PARSE_FAILED:{type(exc).__name__}:{exc}'}
    finally:
        tmp.unlink(missing_ok=True)


def _write_recovered(staging: pathlib.Path, source_tag: str, name: str, data: bytes, validation: dict[str,Any], source: pathlib.Path, kind: str) -> dict[str,Any]:
    safe=_safe_member_name(name)
    dest=staging/source_tag/safe
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_bytes(data)
    return {
        'name':safe,'role':'BODY' if BODY_RE.match(safe) else 'HEAD' if HEAD_RE.match(safe) else 'OTHER',
        'source_path':str(source),'source_kind':kind,'recovered_path':str(dest),
        'size':len(data),'sha256':hashlib.sha256(data).hexdigest(),'validation':validation,
    }


def _extract_zip(path: pathlib.Path, staging: pathlib.Path, tag: str, tmp: pathlib.Path) -> tuple[list[dict[str,Any]],list[dict[str,Any]]]:
    rec=[]; evidence=[]
    if not zipfile.is_zipfile(path): return rec,evidence
    try:
        with zipfile.ZipFile(path) as z:
            for info in z.infolist():
                if not _is_target(info.filename): continue
                base=_safe_member_name(info.filename)
                evidence.append({'kind':'ZIP_MEMBER','name':info.filename,'size':info.file_size})
                if not base.lower().endswith('.smd'): continue
                data=z.read(info)
                val=_validate_smd_bytes(data,tmp,base)
                if val['pass']: rec.append(_write_recovered(staging,tag,base,data,val,path,'ZIP_MEMBER'))
    except Exception as exc:
        evidence.append({'kind':'ZIP_ERROR','error':f'{type(exc).__name__}:{exc}'})
    return rec,evidence


def _extract_tar(path: pathlib.Path, staging: pathlib.Path, tag: str, tmp: pathlib.Path) -> tuple[list[dict[str,Any]],list[dict[str,Any]]]:
    rec=[]; evidence=[]
    try:
        if not tarfile.is_tarfile(path): return rec,evidence
        with tarfile.open(path,'r:*') as t:
            for m in t.getmembers():
                if not m.isfile() or not _is_target(m.name): continue
                base=_safe_member_name(m.name); evidence.append({'kind':'TAR_MEMBER','name':m.name,'size':m.size})
                if not base.lower().endswith('.smd'): continue
                fh=t.extractfile(m)
                if fh is None: continue
                data=fh.read(); val=_validate_smd_bytes(data,tmp,base)
                if val['pass']: rec.append(_write_recovered(staging,tag,base,data,val,path,'TAR_MEMBER'))
    except Exception as exc:
        evidence.append({'kind':'TAR_ERROR','error':f'{type(exc).__name__}:{exc}'})
    return rec,evidence


def _scan_raw(path: pathlib.Path, staging: pathlib.Path, tag: str, tmp: pathlib.Path) -> tuple[list[dict[str,Any]],dict[str,Any]]:
    rec=[]
    info={'raw_target_names':[],'strict_lha_targets':[],'model062_offsets':[],'raw_carve_attempts':[]}
    try:
        with path.open('rb') as f:
            mm=mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ)
            try:
                lo=bytes(mm[:]) if len(mm)<=32*1024*1024 else None
                # target strings: regex streaming via bytes for moderate files; explicit seeded names via generic regex for all mmap.
                rx=re.compile(rb'(?:6[Tt][Ff][Bb][Ff]|[Cc][Tt][Ff][Bb][Ff]|[Tt][Ff][Bb][Ff]|[Tt][Ff][Hh][Ff])[A-Za-z0-9_-]{1,32}\.(?:smd|smb|inx|inf)',re.I)
                for m in rx.finditer(mm):
                    try: nm=m.group(0).decode('ascii')
                    except Exception: continue
                    info['raw_target_names'].append({'name':nm,'offset':m.start()})
                    if len(info['raw_target_names'])>=300: break
                pos=0
                while True:
                    pos=mm.find(MODEL062,pos)
                    if pos<0: break
                    info['model062_offsets'].append(int(pos)); pos+=len(MODEL062)
                    if len(info['model062_offsets'])>=1000: break
                for e in _lha_entries(mm):
                    if not _is_target(str(e.get('filename') or '')): continue
                    strict=bool(e.get('checksum_ok') and e.get('payload_bounds_ok_level0'))
                    row=dict(e); row['strict']=strict
                    info['strict_lha_targets'].append(row)
                    if strict and e.get('method')=='-lh0-' and str(e.get('filename','')).lower().endswith('.smd'):
                        ds=int(e['base_header_end']); de=ds+int(e['compressed_size']); data=bytes(mm[ds:de]); base=_safe_member_name(str(e['filename']))
                        val=_validate_smd_bytes(data,tmp,base)
                        if val['pass']: rec.append(_write_recovered(staging,tag,base,data,val,path,'LHA0_STRICT'))
                # Strict raw carve: only when target name is immediately before a Model0.62 header (<=8192 bytes).
                for nr in info['raw_target_names']:
                    if not str(nr['name']).lower().endswith('.smd'): continue
                    no=int(nr['offset']); nearest=None
                    for ho in info['model062_offsets']:
                        gap=ho-(no+len(str(nr['name'])))
                        if 0<=gap<=8192 and (nearest is None or gap<nearest[0]): nearest=(gap,ho)
                    if nearest is None: continue
                    gap,ho=nearest; length,err=_infer_model062_length(mm,ho)
                    att={'name':nr['name'],'name_offset':no,'header_offset':ho,'gap':gap,'length':length,'infer_error':err}
                    info['raw_carve_attempts'].append(att)
                    if err is not None or not length: continue
                    data=bytes(mm[ho:ho+length]); base=_safe_member_name(str(nr['name'])); val=_validate_smd_bytes(data,tmp,base)
                    att['validation']=val
                    if val['pass']: rec.append(_write_recovered(staging,tag,base,data,val,path,'RAW_ADJACENT_MODEL062'))
            finally: mm.close()
    except Exception as exc:
        info['scan_error']=f'{type(exc).__name__}:{exc}'
    # trim repetitive evidence
    info['raw_target_names']=info['raw_target_names'][:80]
    info['model062_offsets']=info['model062_offsets'][:80]
    info['strict_lha_targets']=info['strict_lha_targets'][:80]
    info['raw_carve_attempts']=info['raw_carve_attempts'][:80]
    return rec,info


def _candidate_files(root: pathlib.Path):
    for p in root.rglob('*'):
        if not p.is_file(): continue
        lo=p.name.lower(); suf=p.suffix.lower()
        if _is_target(lo):
            yield p,'LOOSE'; continue
        if suf in ARCHIVE_SUFFIXES or PACK_RE.match(lo) or (('patch' in lo or 'update' in lo) and p.stat().st_size>32):
            yield p,'ARCHIVE_OR_PACK'


def _prior_contamination(prior: dict[str,Any], project_root: pathlib.Path) -> dict[str,Any]:
    positives=[]; authoritative_like=[]
    for s in prior.get('search_roots') or []:
        for a in s.get('archive_candidates') or []:
            if not (a.get('archive_member_hits') or a.get('target_name_hits') or a.get('strict_lha_record_count') or a.get('model062_magic_count')): continue
            p=pathlib.Path(str(a.get('path') or ''))
            row={'path':str(p),'target_name_hit_count':len(a.get('target_name_hits') or []),'archive_member_hit_count':len(a.get('archive_member_hits') or []),'strict_lha_record_count':int(a.get('strict_lha_record_count') or 0),'model062_magic_count':int(a.get('model062_magic_count') or 0)}
            if _is_within(p,project_root): positives.append(row)
            else: authoritative_like.append(row)
    return {'workspace_positive_count':len(positives),'workspace_positive_samples':positives[:30],'nonworkspace_positive_count':len(authoritative_like),'nonworkspace_positive_samples':authoritative_like[:30]}


def run(root:pathlib.Path, output:pathlib.Path, donor_specs:list[str], external_roots:list[pathlib.Path]) -> dict[str,Any]:
    root=root.resolve(); settings=Settings.discover(root); prior,base_doc=_strict_prior(root)
    guards_before=_guard_snapshot(root)
    if not all(x['pass'] for x in guards_before['writers'].values()): raise RuntimeError('CERTIFIED_WRITER_HASH_MISMATCH')
    baseline={'files':base_doc.get('files') or {}}; cb=_verify_content_baseline(settings.client_root,baseline)
    if not cb['pass']: raise RuntimeError('SUMMIT_CORPUS_NO_LONGER_MATCHES_V0960_BASELINE')

    donors=[]
    for spec in donor_specs:
        name,dr=_parse_donor_spec(spec); donors.append((name,dr.resolve(),_snapshot(dr)))
    ext=[]
    for x in external_roots:
        if not x.is_dir(): continue
        xr=x.resolve()
        if _is_within(xr,root): raise RuntimeError(f'WORKSPACE_SEARCH_ROOT_NOT_AUTHORITATIVE:{xr}')
        ext.append((f'external-{len(ext)+1}',xr,_snapshot(xr)))
    sources=[(n,p,s,'OFFICIAL_DONOR') for n,p,s in donors]+[('summit-client',settings.client_root.resolve(),_snapshot(settings.client_root),'SUMMIT_CLIENT')]+[(n,p,s,'EXTERNAL_EXPLICIT') for n,p,s in ext]

    staging=root/'pt_build/official_tff_payload_staging_v01010'; shutil.rmtree(staging,ignore_errors=True); staging.mkdir(parents=True,exist_ok=True)
    tmp=root/'pt_build/.v01010_validation_tmp'; shutil.rmtree(tmp,ignore_errors=True); tmp.mkdir(parents=True,exist_ok=True)
    source_rows=[]; recovered=[]
    for name,sroot,snap,stype in sources:
        rows=[]; loose=[]
        for p,kind in _candidate_files(sroot):
            rel=p.relative_to(sroot).as_posix(); tag=re.sub(r'[^A-Za-z0-9_.-]+','_',name)
            if kind=='LOOSE':
                row={'path':str(p),'relative_path':rel,'size':p.stat().st_size,'sha256':_sha(p),'kind':'LOOSE'}; loose.append(row)
                if p.suffix.lower()=='.smd':
                    data=p.read_bytes(); val=_validate_smd_bytes(data,tmp,p.name); row['validation']=val
                    if val['pass']: recovered.append(_write_recovered(staging,tag,p.name,data,val,p,'LOOSE'))
                continue
            zr,ze=_extract_zip(p,staging,tag,tmp); tr,te=_extract_tar(p,staging,tag,tmp); rr,raw=_scan_raw(p,staging,tag,tmp)
            recovered.extend(zr+tr+rr)
            positive=bool(ze or te or raw.get('raw_target_names') or raw.get('strict_lha_targets') or raw.get('model062_offsets') or zr or tr or rr)
            if positive:
                rows.append({'path':str(p),'relative_path':rel,'size':p.stat().st_size,'sha256':_sha(p),'zip_or_tar_evidence':ze+te,'raw':raw,'recovered_count':len(zr)+len(tr)+len(rr)})
        source_rows.append({'name':name,'type':stype,'root':str(sroot),'read_only':_snapshot(sroot)==snap,'loose_target_hits':loose[:100],'positive_archive_or_pack_candidates':rows[:100]})

    shutil.rmtree(tmp,ignore_errors=True)
    # Deduplicate recovered by content + logical basename, but keep first authoritative source.
    uniq=[]; seen=set()
    for r in recovered:
        key=(r['name'].lower(),r['sha256'])
        if key in seen: continue
        seen.add(key); uniq.append(r)
    recovered=uniq
    bodies=[r for r in recovered if r['role']=='BODY']; heads=[r for r in recovered if r['role']=='HEAD']
    body_head_pair=bool(bodies and heads)
    evidence_candidates=sum(len(s['positive_archive_or_pack_candidates']) for s in source_rows)
    prior_contam=_prior_contamination(prior,root)
    if body_head_pair: mode='STRICT_TFF_BODY_HEAD_PAIR_RECOVERED'
    elif recovered: mode='STRICT_TFF_PARTIAL_PAYLOAD_RECOVERED'
    elif evidence_candidates: mode='AUTHORITATIVE_ARCHIVE_EVIDENCE_NEEDS_DECODER_OR_MAPPING'
    elif prior_contam['workspace_positive_count'] and not prior_contam['nonworkspace_positive_count']: mode='V100_WORKSPACE_SELF_CONTAMINATION_CONFIRMED_NO_AUTHORITATIVE_TFF_YET'
    else: mode='NO_AUTHORITATIVE_TFF_PAYLOAD_LOCALIZED'

    guards_after=_guard_snapshot(root); ca=_verify_content_baseline(settings.client_root,baseline)
    if guards_after!=guards_before: raise RuntimeError('PRODUCTION_GUARD_CHANGED_DURING_V01010')
    if not ca['pass']: raise RuntimeError('SUMMIT_CLIENT_CHANGED_DURING_V01010')
    for name,sroot,snap,stype in sources:
        if _snapshot(sroot)!=snap: raise RuntimeError(f'SOURCE_CHANGED_DURING_V01010:{name}')
    if not all(s['read_only'] for s in source_rows): raise RuntimeError('AUTHORITATIVE_SOURCE_CHANGED_DURING_V01010')

    output.parent.mkdir(parents=True,exist_ok=True)
    report={
        'format':FORMAT,'status':'PASS','release_version':RELEASE,'prior_v100_strict_pass':True,
        'client_donors_and_authoritative_roots_read_only':True,
        'research_target':'decontaminate V0.10.0 provenance and strictly recover first official TfF body/head payload when physically provable',
        'v100_provenance_reassessment':prior_contam,
        'authoritative_sources':source_rows,
        'recovered_strict':recovered,
        'summary':{
            'authoritative_source_count':len(source_rows),'authoritative_positive_candidate_count':evidence_candidates,
            'strict_recovered_count':len(recovered),'strict_body_count':len(bodies),'strict_head_count':len(heads),
            'strict_body_head_pair_found':body_head_pair,'v100_workspace_positive_count':prior_contam['workspace_positive_count'],
            'v100_nonworkspace_positive_count':prior_contam['nonworkspace_positive_count'],'mode':mode,
        },
        'decision':{
            'transplant_write_authorized':False,'new_class_claimed':False,'runtime_renderer_claimed':False,
            'recovered_files_are_staging_only':True,
            'next_on_pass': 'resolve SMB/INX/textures and open recovered body+head in Blender' if body_head_pair else ('implement decoder/mapping only for the authoritative positive candidate paths listed in this report' if evidence_candidates else 'obtain an external official patch/archive or fully expanded client; V0.10.0 workspace evidence is not sufficient'),
        },
        'guards':{'certified_writer_hashes_valid':True,'writer_modules_modified':False,'production_policies_modified':False,'policy_sha256':guards_after['policies'],'summit_matches_v0960_baseline_before':cb['pass'],'summit_matches_v0960_baseline_after':ca['pass']},
        'outputs':{'json':str(output),'staging_root':str(staging)},
    }
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report


def main(argv:list[str]|None=None)->int:
    ap=argparse.ArgumentParser(); ap.add_argument('--root',required=True); ap.add_argument('--output',required=True); ap.add_argument('--donor',action='append',required=True); ap.add_argument('--search-root',action='append')
    a=ap.parse_args(argv); out=pathlib.Path(a.output)
    try:
        r=run(pathlib.Path(a.root),out,list(a.donor),[pathlib.Path(x) for x in (a.search_root or [])])
        compact={
            'format':r['format'],'status':r['status'],'release_version':r['release_version'],'client_donors_and_authoritative_roots_read_only':r['client_donors_and_authoritative_roots_read_only'],
            'v100_provenance_reassessment':r['v100_provenance_reassessment'],'summary':r['summary'],
            'authoritative_positive_samples':[{'source':s['name'],'type':s['type'],'root':s['root'],'loose_target_hit_count':len(s['loose_target_hits']),'positive_archive_or_pack_candidates':s['positive_archive_or_pack_candidates'][:12]} for s in r['authoritative_sources'] if s['loose_target_hits'] or s['positive_archive_or_pack_candidates']],
            'recovered_strict':r['recovered_strict'][:20],'decision':r['decision'],'guards':r['guards'],'outputs':r['outputs'],
        }
        print(json.dumps(compact,ensure_ascii=False,indent=2))
        s=r['summary']; print(f"official_payload_provenance_extraction=PASS mode={s['mode']} authoritative_positive={s['authoritative_positive_candidate_count']} recovered={s['strict_recovered_count']} body={s['strict_body_count']} head={s['strict_head_count']} pair={str(s['strict_body_head_pair_found']).lower()} read_only=true")
        return 0
    except Exception as exc:
        fail={'format':FORMAT,'status':'FAIL','release_version':RELEASE,'error':f'{type(exc).__name__}:{exc}','transplant_write_authorized':False}
        out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(fail,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(json.dumps(fail,ensure_ascii=False,indent=2)); return 2

if __name__=='__main__': raise SystemExit(main())
