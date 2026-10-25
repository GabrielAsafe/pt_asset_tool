#!/usr/bin/env python3
"""Plano e execução explícita de um pequeno lote ReFocus 1x, sem escrita no cliente.

Compatível com PT Asset Tool + refocus-adaptive-v1 + motor NCNN/Vulkan.
Usa apenas APIs públicas da CLI; não altera ficheiros de projeto.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import os
import json
from pathlib import Path, PurePosixPath
import secrets
import subprocess
import sys

HOME = Path.home()
PROJECT = Path(__file__).resolve().parents[2]
TRANSF = PROJECT / '.work/refocus'
APP = PROJECT / 'app'
CLIENTE = Path(os.environ.get('PT_SUMMIT_CLIENT', str(HOME / 'Área de Trabalho/summit/cliente'))).expanduser()
CONFIG = PROJECT / 'config/material_lab/refocus_v3_gpu.json'
PROFILE = 'refocus-adaptive-v1'
# Uma entrega limpa não exclui os ensaios históricos; não os confundir com aprovação.
ALREADY_TESTED = frozenset()
PREVIOUS_REFOCUS_MANIFEST_GLOBS = (
    'refocus_adaptive_*/manifest.json',
    'material_lab_refocus_*/manifest.json',
    'refocus_lote40_gpu_*/manifest.json',
)
FORMATO = 'PT_REFOCUS_LOTE40_PLAN_V1'


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def read_previous_sources(root: Path) -> set[str]:
    names = {x.casefold() for x in ALREADY_TESTED}
    for pattern in PREVIOUS_REFOCUS_MANIFEST_GLOBS:
        for manifest in root.glob(pattern):
            try:
                report = json.loads(manifest.read_text(encoding='utf-8'))
                for r in report.get('records', []):
                    if r.get('status') == 'staged' and isinstance(r.get('source'), str):
                        names.add(r['source'].casefold())
            except (OSError, ValueError, TypeError):
                # A broken older manifest does not authorize the script to touch it.
                print(f'AVISO: manifesto anterior não interpretável: {manifest}', file=sys.stderr)
    return names


def valid_source(rel: str) -> bool:
    if not isinstance(rel, str) or '\\' in rel:
        return False
    p = PurePosixPath(rel)
    parts = p.parts
    return (len(parts) >= 3 and parts[0].casefold() == 'field'
            and not p.is_absolute() and '..' not in parts
            and 'cooked' not in (x.casefold() for x in parts)
            and p.suffix.casefold() in {'.bmp', '.tga', '.png'})


def select_candidates(decisions: list[dict], already_done: set[str], *, limit: int = 40,
                      max_per_region: int = 4) -> tuple[list[dict], dict]:
    """Deterministic, balanced selection. Keep the Material Lab's own decisions."""
    if not 1 <= limit <= 50:
        raise ValueError('O limite deve ser de 1 a 50')
    by_region: dict[str, list[dict]] = defaultdict(list)
    stats = Counter()
    for r in decisions:
        stats['inspecionadas'] += 1
        src = r.get('source')
        if (r.get('action') != 'ai' or r.get('role') != 'diffuse_candidate'
                or r.get('material') not in {'stone', 'terrain'}
                or not valid_source(src)):
            stats['ignoradas_pela_politica'] += 1
            continue
        dims = r.get('dimensions')
        if not isinstance(dims, list) or len(dims) != 2 or not all(isinstance(n, int) for n in dims):
            stats['sem_dimensoes'] += 1
            continue
        long_side, short_side = max(dims), min(dims)
        if long_side < 1024 or short_side < 512 or long_side > 2048:
            stats['fora_resolucao_lote'] += 1
            continue
        if src.casefold() in already_done:
            stats['ja_testadas'] += 1
            continue
        region = PurePosixPath(src).parts[1]
        by_region[region.casefold()].append(r)
        stats['elegiveis'] += 1
    for region in by_region:
        by_region[region].sort(key=lambda r: (-min(r['dimensions']), -max(r['dimensions']), r['source'].casefold()))
    chosen = []
    region_used = Counter()
    regions = sorted(by_region)
    # Pass through regions in rounds rather than exhausting a single map first.
    for depth in range(max_per_region):
        for region in regions:
            if len(chosen) == limit:
                break
            if len(by_region[region]) > depth:
                chosen.append(by_region[region][depth])
                region_used[region] += 1
        if len(chosen) == limit:
            break
    stats['selecionadas'] = len(chosen)
    stats['regioes'] = len(region_used)
    stats['limite_por_regiao'] = max_per_region
    return chosen, dict(stats)


def checks() -> None:
    for p, label in ((APP / 'pt_asset.py', 'PT Asset Tool'), (CLIENTE, 'cliente'),
                     (CONFIG, 'configuração ReFocus')):
        if not p.exists():
            raise FileNotFoundError(f'{label} não encontrado: {p}')


def create_plan(limit: int, max_per_region: int) -> None:
    checks()
    cmd = [sys.executable, 'pt_asset.py', 'texture-material', 'profile-scan',
           '--input-root', str(CLIENTE), '--include', 'Field/*',
           '--profile', PROFILE, '--model-config', str(CONFIG)]
    print('A analisar a pasta Field com o perfil adaptativo (apenas leitura)...', flush=True)
    cp = subprocess.run(cmd, cwd=APP, text=True, capture_output=True, check=False)
    if cp.returncode:
        raise RuntimeError(f'PROFILE_SCAN_FALHOU ({cp.returncode}):\n{cp.stderr[-4000:]}')
    try:
        scan = json.loads(cp.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError('O profile-scan não devolveu JSON válido') from exc
    if scan.get('profile') != PROFILE or scan.get('source_mutated') is not False:
        raise RuntimeError('Perfil ou flag de leitura inesperado no scan')
    if Path(scan.get('input_root', '')).resolve() != CLIENTE.resolve():
        raise RuntimeError('O scan não corresponde à raiz do cliente esperada')
    already = read_previous_sources(TRANSF)
    TRANSF.mkdir(parents=True, exist_ok=True)
    chosen, summary = select_candidates(scan.get('decisions', []), already,
                                         limit=limit, max_per_region=max_per_region)
    if not chosen:
        print('Nenhuma candidata passou todos os filtros. Não foi criado lote GPU.')
        return
    run_id = datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + secrets.token_hex(3)
    directory = TRANSF / f'refocus_lote40_plano_{run_id}'
    directory.mkdir(mode=0o755, parents=False, exist_ok=False)
    records = []
    for r in chosen:
        src = r['source']
        path = (CLIENTE / src).resolve()
        if CLIENTE.resolve() not in path.parents or not path.is_file():
            raise RuntimeError(f'Fonte insegura ou desaparecida: {src}')
        records.append({'source': src, 'dimensions': r['dimensions'],
                        'material': r['material'], 'codec_format': r.get('codec_format'),
                        'protected': r.get('protected'), 'source_sha256': sha256_file(path),
                        'profile_reason': r['reason']})
    plan = {'format': FORMATO, 'profile': PROFILE,
            'input_root': str(CLIENTE.resolve()), 'config': str(CONFIG.resolve()),
            'config_sha256': sha256_file(CONFIG), 'selection_summary': summary,
            'items': records, 'human_review_required': True, 'publish_to_client': False,
            'upscale_performed': False, 'output_root': None}
    (directory / 'plano.json').write_text(json.dumps(plan, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    (directory / 'candidatos.txt').write_text(''.join(x['source'] + '\n' for x in records), encoding='utf-8')
    (directory / 'scan_field.json').write_text(json.dumps(scan, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('\nPLANO CRIADO (a GPU ainda não foi utilizada):')
    print('CANDIDATAS:', len(records), '| REGIÕES:', summary['regioes'])
    for i, r in enumerate(records, 1):
        w, h = r['dimensions']
        print(f'{i:02d}. {w}x{h} | {r["material"]:7} | {r["source"]}')
    print('PLANO:', directory / 'plano.json')
    print('LISTA:', directory / 'candidatos.txt')
    print('SEM_PROCESSAMENTO_GPU=True; CLIENTE_INTACTO=True')
    print('\nPara processar APÓS rever a lista:')
    print(f'python3 "{Path(__file__).resolve()}" executar "{directory / "plano.json"}"')


def execute_plan(plan_file: Path) -> None:
    checks()
    plan_file = plan_file.expanduser().resolve()
    plan = json.loads(plan_file.read_text(encoding='utf-8'))
    if plan.get('format') != FORMATO or plan.get('profile') != PROFILE:
        raise RuntimeError('PLANO_DESCONHECIDO')
    if Path(plan['input_root']).resolve() != CLIENTE.resolve():
        raise RuntimeError('CLIENTE_DIFERENTE_DO_PLANO')
    if Path(plan['config']).resolve() != CONFIG.resolve() or sha256_file(CONFIG) != plan['config_sha256']:
        raise RuntimeError('CONFIGURACAO_MODIFICADA_DESDE_O_PLANO')
    records = plan.get('items', [])
    if not 1 <= len(records) <= 50 or len(set(r['source'].casefold() for r in records)) != len(records):
        raise RuntimeError('SELECAO_INVALIDA')
    planned_list = (plan_file.parent / 'candidatos.txt').read_text(encoding='utf-8').splitlines()
    if planned_list != [r['source'] for r in records]:
        raise RuntimeError('LISTA_DIVERGE_DO_PLANO')
    for r in records:
        src = r['source']
        if not valid_source(src):
            raise RuntimeError(f'CAMINHO_INSEGURO: {src}')
        p = (CLIENTE / src).resolve()
        if CLIENTE.resolve() not in p.parents or not p.is_file():
            raise RuntimeError(f'FONTE_INSEGURA: {src}')
        if sha256_file(p) != r['source_sha256']:
            raise RuntimeError(f'FONTE_ALTERADA_DESDE_O_SCAN: {src}')
    run_id = datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + secrets.token_hex(3)
    TRANSF.mkdir(parents=True, exist_ok=True)
    output = TRANSF / f'refocus_lote40_gpu_{run_id}'
    if output.exists():
        raise FileExistsError(output)
    args = [sys.executable, 'pt_asset.py', 'texture-material', 'run',
            '--input-root', str(CLIENTE), '--output-root', str(output),
            '--model-config', str(CONFIG), '--profile', PROFILE,
            '--maps', 'off', '--checkpoint-every', '10', '--max-dimension', '2048']
    for r in records:
        args.extend(['--include-exact', r['source']])
    print(f'Executar ReFocus 1× em {len(records)} candidatas, fora do cliente.', flush=True)
    print(f'SAÍDA: {output}', flush=True)
    cp = subprocess.run(args, cwd=APP, check=False)
    manifest = output / 'manifest.json'
    if manifest.exists():
        data = json.loads(manifest.read_text(encoding='utf-8'))
        counts = data.get('status_counts', {})
        print('CONTAGENS:', counts)
        print('GALERIA:', output / 'review_001.html')
        print('MANIFESTO:', manifest)
        print('APROVACAO_MANUAL_OBRIGATORIA=True')
        print('CLIENTE_INTACTO=' + str(data.get('source_mutated') is False))
        if counts.get('failed'):
            raise RuntimeError('O lote tem falhas; verificar manifesto antes de qualquer aprovação')
    if cp.returncode:
        raise RuntimeError(f'PROCESSAMENTO_DEVOLVEU_CODIGO_{cp.returncode}')
    if not manifest.exists():
        raise RuntimeError('PROCESSAMENTO_SEM_MANIFESTO')


def main() -> None:
    parser = argparse.ArgumentParser(description='Lote controlado ReFocus V3 GPU, com prévia e sem edição do cliente')
    sub = parser.add_subparsers(dest='action', required=True)
    plan = sub.add_parser('planear', help='apenas leitura; cria lista de até 40 imagens')
    plan.add_argument('--limite', type=int, default=40)
    plan.add_argument('--por-regiao', type=int, default=4)
    run = sub.add_parser('executar', help='processa apenas o plano escolhido')
    run.add_argument('plano', type=Path)
    args = parser.parse_args()
    if args.action == 'planear':
        if not 1 <= args.por_regiao <= 10:
            parser.error('--por-regiao deve ser de 1 a 10')
        create_plan(args.limite, args.por_regiao)
    else:
        execute_plan(args.plano)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(f'ERRO_SEGURO: {type(exc).__name__}: {exc}', file=sys.stderr)
        sys.exit(1)
