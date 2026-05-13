"""Pass 2 runner — runs the pipeline on the same PDFs using a pre-populated wiki.

Measures the wiki learning effect: does injecting wiki context into extraction
prompts improve accuracy vs pass 1 (fresh wiki)?
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

from card_extractor.agent import AgentContext, process_pdf
from card_extractor.ai_client import GatewayConfig
from card_extractor.review import ReviewQueue
from pipeline_trace import PipelineTrace
from card_extractor.wiki import CardKnowledgeWiki


async def main():
    api_key = os.environ.get("AI_GATEWAY_KEY", "")
    if not api_key:
        print("ERROR: AI_GATEWAY_KEY not set")
        return 1

    output_dir = Path("./experiments/pass2/enhanced")
    wiki_dir = output_dir / "wiki"  # pre-populated from pass 1
    queue_dir = output_dir / "queue"

    if not wiki_dir.exists():
        print(f"ERROR: Wiki not found at {wiki_dir}. Run pass 1 first and copy.")
        return 1

    wiki_pages = list((wiki_dir / "issuers").glob("*.md"))
    wiki_pages = [p for p in wiki_pages if p.name != "_template.md"]
    print(f"Starting pass 2 with {len(wiki_pages)} wiki issuer pages pre-populated")

    # Enhanced config (matches the final run)
    config = GatewayConfig(
        url=os.environ.get("AI_GATEWAY_URL", ""),
        api_key=api_key,
        vlm_model="Qwen/Qwen2.5-VL-32B-Instruct",
        text_model="Qwen/Qwen3-30B-A3B",
        vlm_temperature=0.0,
        extraction_temperature=0.0,
    )

    trace = PipelineTrace(output_dir / "_trace.jsonl")

    ctx = AgentContext(
        config=config,
        wiki=CardKnowledgeWiki(wiki_dir),
        review_queue=ReviewQueue(queue_dir),
        trace=trace,
        output_dir=output_dir,
        render_dpi=200,
        crop_pad_px=5,
        detection_confidence=0.85,
        review_threshold=0.7,
        max_retry_attempts=0,
        enable_audit=True,
        enable_preprocessing=True,
    )

    samples_dir = Path("./input")
    pdfs = sorted(samples_dir.glob("*.pdf"))
    print(f"Processing {len(pdfs)} PDFs with pre-populated wiki...")
    print("=" * 80)

    all_extractions = []
    per_pdf = []
    total_start = time.time()

    for pdf_path in pdfs:
        pdf_start = time.time()
        try:
            extractions = await process_pdf(pdf_path, ctx)
            pdf_time = time.time() - pdf_start
            all_extractions.extend(extractions)
            per_pdf.append({
                "pdf": pdf_path.name,
                "time_s": round(pdf_time, 1),
                "extractions": len(extractions),
            })
            print(f"  {pdf_path.name}: {len(extractions)} cards in {pdf_time:.1f}s")
        except Exception as e:
            pdf_time = time.time() - pdf_start
            per_pdf.append({
                "pdf": pdf_path.name,
                "time_s": round(pdf_time, 1),
                "extractions": 0,
                "error": str(e),
            })
            print(f"  {pdf_path.name}: ERROR in {pdf_time:.1f}s — {e}")

    total_time = time.time() - total_start
    summary = ctx.tracker.summary()
    trace_summary = ctx.trace.summary()

    result = {
        "pass": 2,
        "wiki_pages_at_start": len(wiki_pages),
        "totals": {
            "time_s": round(total_time, 1),
            "pdfs": len(pdfs),
            "extractions": len(all_extractions),
            "api_calls": summary["total_calls"],
            "input_tokens": summary["total_input_tokens"],
            "output_tokens": summary["total_output_tokens"],
        },
        "by_source": summary["by_source"],
        "trace": trace_summary,
        "per_pdf": per_pdf,
    }

    out_path = output_dir / "pass2_result.json"
    out_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

    print()
    print("=" * 80)
    print(f"PASS 2 COMPLETE")
    print("=" * 80)
    print(f"Total time:    {total_time:.1f}s")
    print(f"Extractions:   {len(all_extractions)}")
    print(f"API calls:     {summary['total_calls']}")
    print(f"Input tokens:  {summary['total_input_tokens']:,}")
    print(f"Output tokens: {summary['total_output_tokens']:,}")
    print(f"Wiki pages:    {len(list((wiki_dir / 'issuers').glob('*.md'))) - 1}")  # exclude template
    print(f"\nResult: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
