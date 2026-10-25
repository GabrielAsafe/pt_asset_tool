"""Conservative, opt-in selection of post-upscale 1x material restoration.

Name and path heuristics are not authoritative material metadata. The scan command
should be reviewed before running AI. A default-deny policy protects unknown,
alpha/mask/UI/FX/technical textures and NEVER enables client deployment.
"""
from __future__ import annotations

from collections import Counter
import fnmatch
import json
from pathlib import Path
import re

from . import texture_upscale as tex

PROFILE = 'safe-game-v1'
ADAPTIVE_PROFILE = 'refocus-adaptive-v1'
# Pilot-tested scope only; expand to wood/other materials after in-game review.
ADAPTIVE_MATERIALS = frozenset({'stone', 'terrain'})
ADAPTIVE_LONG_SIDE_MIN = 1024
ADAPTIVE_SHORT_SIDE_MIN = 256
FORMAT = 'PT_TEXTURE_MATERIAL_PROFILES_V1'
MATERIALS = ('stone', 'terrain', 'wood', 'metal', 'fabric', 'skin', 'foliage', 'painted', 'unknown')
ACTIONS = ('skip', 'off', 'light', 'medium', 'ai')
DEFAULT_ACTIONS = {
    'stone': 'ai', 'terrain': 'ai', 'wood': 'ai', 'metal': 'ai',
    'fabric': 'ai', 'skin': 'ai',
    'foliage': 'skip', 'painted': 'skip', 'unknown': 'skip',
}
# Non-exhaustive, deliberately conservative. No rule may override this denylist.
UNSAFE = re.compile(
    r'(^|[/_.-])(?:ui|interface|interfaces|hud|menu|login|select|cselect|chrselect|startimage|'
    r'icon|icons|atlas|sprite|sprites|cursor|font|fonts|mask|masks|'
    r'alpha|opacity|specular|roughness|gloss|emissive|emission|'
    r'light|lights|glow|flare|particle|particles|effect|effects|fx|'
    r'sky|cloud|clouds|water|reflection|shadow|shadows|noise|'
    r'normal|normals|normalmap|nrm|height|heightmap|parallax|displacement)'
    r'(?=$|[/_.-]|\d)', re.IGNORECASE,
)
# Composite technical names may join a material word and a lightmap suffix,
# e.g. `floor_002lightingmap.bmp`: token-boundary guards alone miss these.
# Never process them as diffuse images, even if a user profile requests AI.
COMPOSITE_TECHNICAL = re.compile(
    r'(?:lightmaps?|lightingmaps?|illuminationmaps?|ambientocclusion|'
    r'occlusionmaps?|normalmaps?|heightmaps?|shadowmaps?)',
    re.IGNORECASE,
)
# Legacy assets often concatenate technical words into a directory name:
# `image/Sinimage/AssaEffect/GreatH/P/ground_ring.bmp` is an effect, not terrain.
# The directory guard is deliberately conservative, and cannot be overridden.
COMPOSITE_FX_DIRECTORY = re.compile(
    r'(?:^|/)[^/]*(?:effects?|particles?|sprites?)[^/]*/',
    re.IGNORECASE,
)
# A short suffix like `_m` is ambiguous in this engine (mask/material/etc.).
# Do not assume it is a diffuse texture until it is manually identified.
AMBIGUOUS_TECHNICAL_SUFFIX = re.compile(r'[_\-.]m$', re.IGNORECASE)
# Only a narrow set of unambiguous filename material prefixes.
HINTS = {
    'stone': ('stone', 'stones', 'rock', 'rocks', 'brick', 'bricks', 'wall', 'walls', 'cliff', 'cave'),
    'terrain': ('terrain', 'ground', 'floor', 'floors', 'dirt', 'soil', 'sand', 'road', 'roads', 'path'),
    'wood': ('wood', 'plank', 'planks', 'timber', 'bark', 'log', 'logs'),
    'metal': ('metal', 'iron', 'steel', 'armor', 'armour'),
    'fabric': ('fabric', 'cloth', 'robe', 'cape', 'leather'),
    'skin': ('skin', 'face', 'body', 'head'),
    'foliage': ('grass', 'leaf', 'leaves', 'foliage', 'bush', 'flower'),
}


def load_profile_config(path: Path | None) -> dict:
    if path is None:
        return {'format': FORMAT, 'actions': {}, 'rules': []}
    data = json.loads(path.expanduser().read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('format') != FORMAT:
        raise ValueError('INVALID_PROFILE_FORMAT')
    actions = data.get('actions', {})
    rules = data.get('rules', [])
    if not isinstance(actions, dict) or not isinstance(rules, list):
        raise ValueError('INVALID_PROFILE_CONFIG')
    if any(k not in MATERIALS or v not in ACTIONS for k, v in actions.items()):
        raise ValueError('INVALID_PROFILE_ACTION')
    for rule in rules:
        if not isinstance(rule, dict) or not isinstance(rule.get('pattern'), str) or not rule['pattern']:
            raise ValueError('INVALID_PROFILE_RULE_PATTERN')
        if rule.get('material') is not None and rule['material'] not in MATERIALS:
            raise ValueError('INVALID_PROFILE_RULE_MATERIAL')
        if rule.get('action') is not None and rule['action'] not in ACTIONS:
            raise ValueError('INVALID_PROFILE_RULE_ACTION')
        if not (rule.get('material') or rule.get('action')):
            raise ValueError('EMPTY_PROFILE_RULE')
    return data


def _tokens(path: str) -> list[str]:
    return [x for x in re.split(r'[^a-z0-9]+', path.lower()) if x]


def _material(rel: str, fallback: str, context: str='') -> tuple[str, str]:
    name = Path(rel).stem.lower()
    tokens = set(_tokens(rel))
    for material, words in HINTS.items():
        if tokens.intersection(words) or any(re.match(re.escape(w) + r'(?:\d|[_\-.]|$)', name) for w in words):
            return material, 'material_name_hint'
    path_tokens = _tokens(str(Path(rel).parent) + '/' + context)
    if 'npc' in path_tokens or 'character' in path_tokens or 'characters' in path_tokens or 'char' in path_tokens:
        return 'skin', 'character_directory_hint'
    # A caller may select a folder of ground/wall assets with opaque names.
    if any(t in ('ground', 'floor', 'terrain') for t in _tokens(context)):
        return 'terrain', 'material_directory_hint'
    if any(t in ('wall', 'stone', 'rock') for t in _tokens(context)):
        return 'stone', 'material_directory_hint'
    if fallback in MATERIALS and fallback != 'unknown':
        return fallback, 'existing_material_classifier'
    return 'unknown', 'unknown_requires_manual_rule'


def decide(rel: str, *, role: str, base_material: str='unknown', config: dict | None=None, context: str='') -> dict:
    """Return a previewable decision. A user rule never bypasses hard safety guards."""
    config = config or {}
    safe_rel = rel.lower().replace('\\', '/')
    if role != 'diffuse_candidate':
        return {'material': base_material, 'action': 'skip', 'reason': 'technical_map_safety_guard'}
    if (tex._risk_class(rel) == 'UI_ATLAS_RISK' or UNSAFE.search(safe_rel)
            or UNSAFE.search(context.lower()) or COMPOSITE_TECHNICAL.search(safe_rel)
            or COMPOSITE_FX_DIRECTORY.search(safe_rel)):
        return {'material': 'painted', 'action': 'skip', 'reason': 'ui_mask_fx_sky_safety_guard'}
    if AMBIGUOUS_TECHNICAL_SUFFIX.search(Path(safe_rel).stem):
        return {'material': 'unknown', 'action': 'skip', 'reason': 'ambiguous_suffix_requires_manual_review'}
    material, reason = _material(rel, base_material, context)
    forced_action = None
    for rule in config.get('rules', []):
        if fnmatch.fnmatchcase(safe_rel, rule['pattern'].lower()):
            if rule.get('material'):
                material = rule['material']
            forced_action = rule.get('action')
            reason = 'explicit_profile_rule'
            break
    action = forced_action or config.get('actions', {}).get(material, DEFAULT_ACTIONS[material])
    return {'material': material, 'action': action, 'reason': reason}


def adapt_by_dimensions(decision: dict, *, width: int, height: int) -> dict:
    """Fail closed on small/nonvalidated assets; never override an earlier skip.

    Dimensions must come from texture_upscale.inspect_texture, not Pillow:
    Priston Tale's protected BMP headers cannot always be opened by Pillow.
    This function makes *selection* decisions only, never edits a texture.
    """
    result = dict(decision)
    if result['action'] == 'skip':
        return result
    if width <= 0 or height <= 0:
        result.update(action='skip', reason='adaptive_invalid_dimensions')
    elif max(width, height) <= 16:
        result.update(action='skip', reason='adaptive_microtexture')
    elif result['material'] not in ADAPTIVE_MATERIALS:
        result.update(action='skip', reason='adaptive_material_not_validated')
    elif result['action'] != 'ai':
        # Explicit user 'off', 'light' or 'medium' remain non-AI choices.
        # This profile stages ONLY eligible ReFocus AI candidates.
        result.update(action='skip', reason='adaptive_no_ai_requested')
    elif max(width, height) < ADAPTIVE_LONG_SIDE_MIN or min(width, height) < ADAPTIVE_SHORT_SIDE_MIN:
        result.update(action='skip', reason='adaptive_below_resolution_threshold')
    else:
        result.update(action='ai', reason='adaptive_refocus_candidate_requires_review')
    return result


def adaptive_policy_summary() -> dict:
    return {'material_allowlist': sorted(ADAPTIVE_MATERIALS),
            'min_long_side': ADAPTIVE_LONG_SIDE_MIN,
            'min_short_side': ADAPTIVE_SHORT_SIDE_MIN,
            'no_upscale': True, 'human_review_required': True,
            'codec': 'texture_upscale.inspect_texture'}


def scan(root: Path, *, include: list[str], exact: list[str], all_: bool, config: dict,
         overrides: dict | None=None, profile: str=PROFILE) -> dict:
    if profile not in (PROFILE, ADAPTIVE_PROFILE):
        raise ValueError('INVALID_PROFILE')
    if not (all_ ^ bool(include or exact)):
        raise ValueError('EXPLICIT_SELECTION_REQUIRED: --all OR --include/--include-exact')
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    results = []
    counts = Counter()
    for path in sorted(tex.iter_textures(root)):
        rel = path.relative_to(root).as_posix()
        if not all_ and not tex._selected(rel, include, exact):
            continue
        if not tex._is_within(root, path.resolve()):
            raise ValueError('SYMLINK_OUTSIDE_INPUT_ROOT_BLOCKED')
        role = tex.detect_texture_role(rel)
        fallback = 'unknown'
        if overrides:
            from .texture_material_pipeline import material_of
            fallback = material_of(rel, overrides)
        context = '/'.join(root.parts[-4:])
        result = decide(rel, role=role, base_material=fallback, config=config, context=context)
        if profile == ADAPTIVE_PROFILE and result['action'] != 'skip':
            try:
                rec, _meta = tex.inspect_texture(path)
                result = adapt_by_dimensions(result, width=rec.width, height=rec.height)
                result['dimensions'] = [rec.width, rec.height]
                result['protected'] = rec.protected
                result['codec_format'] = rec.format
            except Exception as exc:
                # Unknown/protected families fail closed, never by Pillow guesswork.
                result = dict(result, action='skip',
                              reason='adaptive_codec_inspection_failed',
                              inspection_error=f'{type(exc).__name__}: {exc}'[:220])
        result.update(source=rel, role=role)
        results.append(result)
        counts[result['action']] += 1
    report = {'format': FORMAT, 'profile': profile, 'input_root': str(root),
              'texture_count': len(results), 'action_counts': dict(counts),
              'source_mutated': False, 'upscale_performed': False,
              'client_publish_authorized': False, 'decisions': results}
    if profile == ADAPTIVE_PROFILE:
        report['adaptive_policy'] = adaptive_policy_summary()
    return report
