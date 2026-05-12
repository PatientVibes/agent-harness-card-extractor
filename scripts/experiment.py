"""Experiment runner — sweep model parameters to find optimal configuration.

Runs the agent pipeline with different configurations and collects metrics
for comparison. Results saved as JSON for analysis.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

from card_extractor.agent import AgentContext, process_pdf
from card_extractor.ai_client import GatewayConfig
from card_extractor.trace import PipelineTrace
from card_extractor.wiki import CardKnowledgeWiki
from card_extractor.review import ReviewQueue


@dataclass
class ExperimentConfig:
    name: str
    vlm_model: str = "Qwen/Qwen2.5-VL-32B-Instruct"
    text_model: str = "Qwen/Qwen3-30B-A3B"
    render_dpi: int = 300
    crop_pad_px: int = 10
    vlm_temperature: float = 0.1
    extraction_temperature: float = 0.0
    detection_confidence: float = 0.85
    review_threshold: float = 0.7
    max_retry: int = 1


# ---------------------------------------------------------------------------
# Experiment definitions
# ---------------------------------------------------------------------------

EXPERIMENTS = [
    ExperimentConfig(
        name="baseline",
        # POC defaults
    ),
    ExperimentConfig(
        name="dpi_200",
        render_dpi=200,
    ),
    ExperimentConfig(
        name="dpi_150",
        render_dpi=150,
    ),
    ExperimentConfig(
        name="temp_0",
        vlm_temperature=0.0,
        extraction_temperature=0.0,
    ),
    ExperimentConfig(
        name="temp_02",
        vlm_temperature=0.2,
        extraction_temperature=0.1,
    ),
    ExperimentConfig(
        name="confidence_80",
        detection_confidence=0.80,
    ),
    ExperimentConfig(
        name="confidence_90",
        detection_confidence=0.90,
    ),
    ExperimentConfig(
        name="pad_0",
        crop_pad_px=0,
    ),
    ExperimentConfig(
        name="pad_20",
        crop_pad_px=20,
    ),
    ExperimentConfig(
        name="no_retry",
        max_retry=0,
    ),
    ExperimentConfig(
        name="large_vlm",
        vlm_model="qwen.qwen3-vl-235b-a22b",
    ),
    ExperimentConfig(
        name="dpi200_temp0_pad5",
        render_dpi=200,
        vlm_temperature=0.0,
        crop_pad_px=5,
    ),
    ExperimentConfig(
        name="enhanced",
        render_dpi=200,
        vlm_temperature=0.0,
        extraction_temperature=0.0,
        crop_pad_px=5,
        detection_confidence=0.85,
        max_retry=0,
    ),
]


def build_context(exp: ExperimentConfig, output_dir: Path) -> AgentContext:
    """Build an AgentContext from an experiment config."""
    config = GatewayConfig(
        url=os.environ.get("AI_GATEWAY_URL", ""),
        api_key=os.environ.get("AI_GATEWAY_KEY", ""),
        vlm_model=exp.vlm_model,
        text_model=exp.text_model,
        vlm_temperature=exp.vlm_temperature,
        extraction_temperature=exp.extraction_temperature,
    )

    wiki_dir = output_dir / "wiki"
    queue_dir = output_dir / "queue"

    trace = PipelineTrace(output_dir / "_trace.jsonl")

    return AgentContext(
        config=config,
        wiki=CardKnowledgeWiki(wiki_dir),
        review_queue=ReviewQueue(queue_dir),
        trace=trace,
        output_dir=output_dir,
        render_dpi=exp.render_dpi,
        crop_pad_px=exp.crop_pad_px,
        detection_confidence=exp.detection_confidence,
        review_threshold=exp.review_threshold,
        max_retry_attempts=exp.max_retry,
    )


async def run_experiment(
    exp: ExperimentConfig,
    pdfs: list[Path],
    base_output: Path,
) -> dict:
    """Run one experiment config across all PDFs."""
    output_dir = base_output / exp.name
    if output_dir.exists():
        shutil.rmtree(output_dir, ignore_errors=True)

    ctx = build_context(exp, output_dir)

    all_extractions = []
    per_pdf = []
    total_start = time.time()

    for pdf_path in pdfs:
        pdf_start = time.time()
        try:
            extractions = await process_pdf(pdf_path, ctx)
            pdf_time = time.time() - pdf_start

            ext_dicts = [e.model_dump() for e in extractions]
            all_extractions.extend(ext_dicts)
            per_pdf.append({
                "pdf": pdf_path.name,
                "time_s": round(pdf_time, 1),
                "extractions": len(extractions),
                "cards": [
                    {
                        "type": e.card_type,
                        "confidence": e.confidence,
                        "issuer": e.issuer_hint,
                        "key_field": (
                            e.insurance.subscriber_name if e.card_type == "INSURANCE"
                            else e.government.name
                        ),
                    }
                    for e in extractions
                ],
            })
            sys.stdout.write(f"  {pdf_path.name}: {len(extractions)} cards in {pdf_time:.1f}s\n")
            sys.stdout.flush()
        except Exception as e:
            pdf_time = time.time() - pdf_start
            per_pdf.append({
                "pdf": pdf_path.name,
                "time_s": round(pdf_time, 1),
                "extractions": 0,
                "error": str(e),
            })
            sys.stdout.write(f"  {pdf_path.name}: ERROR in {pdf_time:.1f}s — {e}\n")
            sys.stdout.flush()

    total_time = time.time() - total_start
    summary = ctx.tracker.summary()

    # Collect review queue and trace summary
    pending = ctx.review_queue.list_pending()
    trace_summary = ctx.trace.summary() if ctx.trace else {}

    result = {
        "experiment": exp.name,
        "config": {
            "vlm_model": exp.vlm_model,
            "render_dpi": exp.render_dpi,
            "crop_pad_px": exp.crop_pad_px,
            "vlm_temperature": exp.vlm_temperature,
            "extraction_temperature": exp.extraction_temperature,
            "detection_confidence": exp.detection_confidence,
            "max_retry": exp.max_retry,
        },
        "totals": {
            "time_s": round(total_time, 1),
            "pdfs": len(pdfs),
            "extractions": len(all_extractions),
            "api_calls": summary["total_calls"],
            "input_tokens": summary["total_input_tokens"],
            "output_tokens": summary["total_output_tokens"],
            "flagged_for_review": len(pending),
        },
        "by_source": summary["by_source"],
        "trace": trace_summary,
        "per_pdf": per_pdf,
    }

    # Save individual result
    result_path = output_dir / "experiment_result.json"
    result_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

    return result


def print_comparison_table(results: list[dict]):
    """Print a comparison table across all experiments."""
    print(f"\n{'='*120}")
    print("EXPERIMENT COMPARISON")
    print(f"{'='*120}")

    header = f"{'Experiment':<25} {'Time':>8} {'Extr':>6} {'Calls':>7} {'In Tok':>10} {'Out Tok':>10} {'Review':>8} {'DPI':>5} {'Temp':>5} {'Pad':>5} {'Conf':>5}"
    print(header)
    print("-" * 120)

    for r in results:
        t = r["totals"]
        c = r["config"]
        print(
            f"{r['experiment']:<25} "
            f"{t['time_s']:>7.0f}s "
            f"{t['extractions']:>6} "
            f"{t['api_calls']:>7} "
            f"{t['input_tokens']:>10,} "
            f"{t['output_tokens']:>10,} "
            f"{t['flagged_for_review']:>8} "
            f"{c['render_dpi']:>5} "
            f"{c['vlm_temperature']:>5.1f} "
            f"{c['crop_pad_px']:>5} "
            f"{c['detection_confidence']:>5.2f}"
        )

    # Find best in each metric
    if len(results) > 1:
        print(f"\n{'Best performers:'}")
        fastest = min(results, key=lambda r: r["totals"]["time_s"])
        cheapest = min(results, key=lambda r: r["totals"]["input_tokens"])
        most_ext = max(results, key=lambda r: r["totals"]["extractions"])
        print(f"  Fastest:       {fastest['experiment']} ({fastest['totals']['time_s']:.0f}s)")
        print(f"  Cheapest:      {cheapest['experiment']} ({cheapest['totals']['input_tokens']:,} input tokens)")
        print(f"  Most extracts: {most_ext['experiment']} ({most_ext['totals']['extractions']} extractions)")


def main():
    api_key = os.environ.get("AI_GATEWAY_KEY", "")
    if not api_key:
        print("ERROR: AI_GATEWAY_KEY not set")
        return 1

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdfs", type=int, default=0, help="Number of PDFs to process (0=all)")
    parser.add_argument("--experiments", nargs="*", default=None,
                        help="Experiment names to run (default: all)")
    parser.add_argument("--output", default="./experiments",
                        help="Output directory")
    parser.add_argument("--input", default="./input",
                        help="Input directory containing PDF samples")
    args = parser.parse_args()

    samples_dir = Path(args.input)
    pdfs = sorted(samples_dir.glob("*.pdf"))
    if args.pdfs > 0:
        pdfs = pdfs[:args.pdfs]

    exps = EXPERIMENTS
    if args.experiments:
        exps = [e for e in EXPERIMENTS if e.name in args.experiments]

    base_output = Path(args.output)
    print(f"Running {len(exps)} experiments on {len(pdfs)} PDFs")
    print(f"Output: {base_output}")

    all_results = []
    for i, exp in enumerate(exps):
        print(f"\n{'='*80}")
        print(f"[{i+1}/{len(exps)}] Experiment: {exp.name}")
        print(f"  model={exp.vlm_model}, dpi={exp.render_dpi}, temp={exp.vlm_temperature}, "
              f"pad={exp.crop_pad_px}, conf={exp.detection_confidence}, retry={exp.max_retry}")
        print(f"{'='*80}")

        result = asyncio.run(run_experiment(exp, pdfs, base_output))
        all_results.append(result)

        t = result["totals"]
        print(f"\n  Result: {t['extractions']} extractions, {t['time_s']:.0f}s, "
              f"{t['input_tokens']:,} in / {t['output_tokens']:,} out tokens")

    print_comparison_table(all_results)

    # Save combined results
    combined_path = base_output / "all_experiments.json"
    combined_path.parent.mkdir(parents=True, exist_ok=True)
    combined_path.write_text(json.dumps(all_results, indent=2, default=str), encoding="utf-8")
    print(f"\nAll results saved to {combined_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
