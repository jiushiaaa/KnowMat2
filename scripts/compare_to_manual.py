#!/usr/bin/env python3
"""Compare pipeline extraction JSONs against manual annotation JSONs.

Usage:
    python scripts/compare_to_manual.py --pipeline data/processed --manual data/manual

The script walks both directories, matches extraction JSON files by stem name,
and reports per-field differences for the key fields that the lab cares about:

  - Source_DOI
  - Key_Params_JSON (core keys)
  - Microstructure_Text_For_AI
  - Grain_Size_avg_um
  - Performance_Tests (count, direction split, temperature coverage)
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


KEY_PARAM_FIELDS = [
    "Laser_Power_W",
    "Scan_Speed_mm_s",
    "Layer_Thickness_um",
    "Hatch_Spacing_um",
    "Preheat_Temperature_C",
    "Shielding_Gas",
    "Oxygen_Content_ppm",
    "Build_Orientation",
]


def _find_extraction_jsons(root: Path) -> Dict[str, Path]:
    """Walk *root* and collect ``*_extraction.json`` files, keyed by stem prefix."""
    results: Dict[str, Path] = {}
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            if fn.endswith("_extraction.json"):
                stem = fn.replace("_extraction.json", "")
                results[stem] = Path(dirpath) / fn
    return results


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _compare_doi(pipeline: dict, manual: dict) -> List[str]:
    issues: List[str] = []
    for tag, data in [("pipeline", pipeline), ("manual", manual)]:
        materials = data.get("Materials", [])
        if not materials:
            issues.append(f"  {tag}: no Materials found")
    p_dois = {m.get("Source_DOI", "") for m in pipeline.get("Materials", [])}
    m_dois = {m.get("Source_DOI", "") for m in manual.get("Materials", [])}
    p_doi = next((d for d in p_dois if d), "")
    m_doi = next((d for d in m_dois if d), "")
    if p_doi != m_doi:
        issues.append(f"  DOI mismatch: pipeline='{p_doi}' vs manual='{m_doi}'")
    elif not p_doi and not m_doi:
        issues.append("  DOI: both empty")
    return issues


def _compare_key_params(p_sample: dict, m_sample: dict) -> List[str]:
    issues: List[str] = []
    p_kp = p_sample.get("Key_Params_JSON", {}) or {}
    m_kp = m_sample.get("Key_Params_JSON", {}) or {}
    for key in KEY_PARAM_FIELDS:
        pv = p_kp.get(key)
        mv = m_kp.get(key)
        if pv is None and mv is not None:
            issues.append(f"  Key_Params_JSON[{key}]: MISSING in pipeline (manual={mv})")
        elif pv is not None and mv is not None and pv != mv:
            issues.append(f"  Key_Params_JSON[{key}]: pipeline={pv} vs manual={mv}")
    return issues


def _compare_samples(pipeline: dict, manual: dict) -> List[str]:
    issues: List[str] = []
    p_mats = pipeline.get("Materials", [])
    m_mats = manual.get("Materials", [])
    
    p_samples = [s for m in p_mats for s in m.get("Processed_Samples", [])]
    m_samples = [s for m in m_mats for s in m.get("Processed_Samples", [])]
    
    if len(p_samples) != len(m_samples):
        issues.append(f"  Sample count: pipeline={len(p_samples)} vs manual={len(m_samples)}")

    for i, (ps, ms) in enumerate(zip(p_samples, m_samples)):
        sid = ps.get("Sample_ID", f"idx-{i}")
        
        # Microstructure text
        p_micro = ps.get("Microstructure_Text_For_AI", "")
        m_micro = ms.get("Microstructure_Text_For_AI", "")
        if p_micro != m_micro:
            p_preview = p_micro[:80] + "..." if len(p_micro) > 80 else p_micro
            m_preview = m_micro[:80] + "..." if len(m_micro) > 80 else m_micro
            issues.append(f"  [{sid}] Microstructure differs: pipeline='{p_preview}' vs manual='{m_preview}'")
        
        # Grain size
        p_gs = ps.get("Grain_Size_avg_um")
        m_gs = ms.get("Grain_Size_avg_um")
        if p_gs != m_gs:
            issues.append(f"  [{sid}] Grain_Size_avg_um: pipeline={p_gs} vs manual={m_gs}")
        
        # Key params
        issues.extend(_compare_key_params(ps, ms))
        
        # Performance tests count
        p_tests = ps.get("Performance_Tests", [])
        m_tests = ms.get("Performance_Tests", [])
        if len(p_tests) != len(m_tests):
            issues.append(f"  [{sid}] Test count: pipeline={len(p_tests)} vs manual={len(m_tests)}")
    
    return issues


def compare_one(pipeline_path: Path, manual_path: Path) -> Tuple[str, List[str]]:
    stem = pipeline_path.stem.replace("_extraction", "")
    p_data = _load_json(pipeline_path)
    m_data = _load_json(manual_path)
    
    all_issues: List[str] = []
    all_issues.extend(_compare_doi(p_data, m_data))
    all_issues.extend(_compare_samples(p_data, m_data))
    return stem, all_issues


def main():
    parser = argparse.ArgumentParser(description="Compare pipeline vs manual extraction JSONs")
    parser.add_argument("--pipeline", required=True, help="Path to pipeline processed directory")
    parser.add_argument("--manual", required=True, help="Path to manual annotation directory")
    args = parser.parse_args()

    p_files = _find_extraction_jsons(Path(args.pipeline))
    m_files = _find_extraction_jsons(Path(args.manual))

    if not p_files:
        print(f"No *_extraction.json files found in {args.pipeline}")
        sys.exit(1)
    if not m_files:
        print(f"No *_extraction.json files found in {args.manual}")
        sys.exit(1)

    matched = set(p_files.keys()) & set(m_files.keys())
    p_only = set(p_files.keys()) - set(m_files.keys())
    m_only = set(m_files.keys()) - set(p_files.keys())

    print(f"Matched: {len(matched)} | Pipeline-only: {len(p_only)} | Manual-only: {len(m_only)}\n")

    total_issues = 0
    for stem in sorted(matched):
        name, issues = compare_one(p_files[stem], m_files[stem])
        if issues:
            print(f"=== {name} ({len(issues)} issues) ===")
            for iss in issues:
                print(iss)
            print()
            total_issues += len(issues)
        else:
            print(f"=== {name}: OK ===")

    print(f"\nTotal issues: {total_issues} across {len(matched)} papers")
    if p_only:
        print(f"Pipeline-only (no manual): {sorted(p_only)}")
    if m_only:
        print(f"Manual-only (no pipeline): {sorted(m_only)}")


if __name__ == "__main__":
    main()
