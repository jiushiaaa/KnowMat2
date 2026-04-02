"""
Aggregation Agent (Stage 1 of Two-Stage Manager)

This agent's SOLE responsibility is to merge data from multiple extraction runs
into a single comprehensive dataset. It does NOT validate, check for hallucinations,
or generate review guides - that's Stage 2's job.

Responsibilities:
- Select base run by confidence score
- Merge compositions from all runs
- Handle conflicts by preferring high-confidence values
- Preserve all characterisation data
- Simple, fast, rule-based merging

NOT responsible for:
- Hallucination detection/correction (Stage 2)
- ML-ready format validation (Stage 2)
- Review guide generation (Stage 2)
- Confidence scoring (Flagging Agent)
"""

import json
import logging
from typing import Dict, Any, List
from knowmat.states import KnowMatState, load_run_extraction

logger = logging.getLogger(__name__)


def aggregate_runs(state: KnowMatState) -> Dict[str, Any]:
    """Merge multiple extraction runs into single comprehensive dataset.
    
    Uses a simple, reliable strategy:
    1. Select the highest-confidence run as the base
    2. Add compositions from other runs that don't appear in base
    3. For each composition, prefer values from higher-confidence runs
    4. Preserve ALL characterisation data from all sources
    
    This is purely merging - no validation, no hallucination checks.
    Those happen in Stage 2 (Validation Agent).
    
    Parameters
    ----------
    state : KnowMatState
        Current workflow state containing run_results
    
    Returns
    -------
    dict
        Updates containing:
        - aggregated_data: Merged compositions from all runs
        - aggregation_notes: Brief explanation of merge strategy
    """
    run_results = state.get("run_results", [])
    
    if not run_results:
        # No runs to aggregate - use latest extraction
        latest_data = state.get("latest_extracted_data", {})
        return {
            "aggregated_data": latest_data,
            "aggregation_notes": "No evaluation runs. Using latest extraction.",
        }
    
    if len(run_results) == 1:
        single_run = run_results[0]
        return {
            "aggregated_data": load_run_extraction(single_run),
            "aggregation_notes": f"Single run (ID {single_run.get('run_id')}, confidence {single_run.get('confidence_score', 0.0):.2f}).",
        }
    
    # Sort runs by confidence (highest first)
    sorted_runs = sorted(
        run_results,
        key=lambda r: r.get("confidence_score", 0.0),
        reverse=True
    )
    
    logger.info("Aggregation Stage 1:")
    logger.info("  Merging %s extraction runs...", len(run_results))
    confidences = [f"{r.get('confidence_score', 0.0):.2f}" for r in sorted_runs]
    logger.info("  Run confidences: %s", confidences)
    
    base_run = sorted_runs[0]
    base_data = load_run_extraction(base_run)
    base_compositions = base_data.get("compositions", [])
    
    logger.info(
        "  Base run: ID %s (confidence %.2f)",
        base_run.get("run_id"),
        base_run.get("confidence_score", 0.0),
    )
    logger.info("  Base compositions: %s", len(base_compositions))
    
    # Create a copy to modify
    merged_data = {"compositions": []}
    composition_map = {}  # composition string -> composition data
    
    # Add all compositions from base run
    for comp in base_compositions:
        comp_str = comp.get("composition", "")
        if comp_str:
            composition_map[comp_str] = dict(comp)  # Make a copy
    
    # Merge compositions from other runs
    compositions_added = 0
    properties_merged = 0
    
    for run in sorted_runs[1:]:
        run_data = load_run_extraction(run)
        run_compositions = run_data.get("compositions", [])
        
        for comp in run_compositions:
            comp_str = comp.get("composition", "")
            if not comp_str:
                continue
            
            if comp_str not in composition_map:
                # New composition not in base - add it
                composition_map[comp_str] = dict(comp)
                compositions_added += 1
            else:
                # Composition exists - merge properties
                existing = composition_map[comp_str]
                
                # Merge processing_conditions (prefer longer/more detailed)
                if len(comp.get("processing_conditions", "")) > len(existing.get("processing_conditions", "")):
                    existing["processing_conditions"] = comp.get("processing_conditions")
                
                # Merge characterisation data
                existing_char = existing.get("characterisation", {})
                new_char = comp.get("characterisation", {})
                for technique, details in new_char.items():
                    if technique not in existing_char:
                        existing_char[technique] = details
                    elif len(details) > len(existing_char.get(technique, "")):
                        existing_char[technique] = details
                existing["characterisation"] = existing_char
                
                # Merge properties (avoid duplicates by property_name + property_symbol)
                existing_props = existing.get("properties_of_composition", [])
                new_props = comp.get("properties_of_composition", [])
                
                # Build a set of existing property signatures
                existing_signatures = set()
                for prop in existing_props:
                    sig = (prop.get("property_name"), prop.get("property_symbol"))
                    existing_signatures.add(sig)
                
                # Add new properties that don't exist yet
                for prop in new_props:
                    sig = (prop.get("property_name"), prop.get("property_symbol"))
                    if sig not in existing_signatures:
                        existing_props.append(dict(prop))
                        existing_signatures.add(sig)
                        properties_merged += 1
                
                existing["properties_of_composition"] = existing_props
    
    # Convert composition_map back to list
    merged_data["compositions"] = list(composition_map.values())
    
    total_compositions = len(merged_data["compositions"])
    
    logger.info("  Merged result: %s compositions", total_compositions)
    logger.info(
        "  Added from other runs: +%s compositions, +%s properties",
        compositions_added,
        properties_merged,
    )
    
    # Build aggregation notes
    notes = (
        f"Aggregation strategy: Used Run {base_run.get('run_id')} "
        f"(confidence {base_run.get('confidence_score', 0.0):.2f}) as base with "
        f"{len(base_compositions)} compositions. "
        f"Merged data from {len(run_results) - 1} other runs, adding "
        f"{compositions_added} new compositions and {properties_merged} properties. "
        f"Total final compositions: {total_compositions}."
    )
    
    # Stage 1 is rule-based - no schema validation needed
    # Validation happens in Stage 2 (LLM-based validator)
    logger.info("  Aggregation complete (no validation - rule-based)")
    
    return {
        "aggregated_data": merged_data,  # Pass merged data directly
        "aggregation_notes": notes,
    }
