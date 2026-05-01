import asyncio
import json
import os
import sys
import datetime
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.benchmarks import load_benchmarks
from main import (
    phase_3_formal_translation, 
    phase_4_validation_oracle, 
    phase_5_result_analysis,
    MAX_CODE_RETRIES,
    conjecture_llm,
    translator_llm,
    analyst_llm
)

async def run_headless_cycle(conjecture):
    code_resolved = False
    python_code = None
    code_retries = 0
    final_status = "UNKNOWN"
    final_analysis = {}

    while not code_resolved:
        if python_code is None: 
            python_code = await phase_3_formal_translation(conjecture)
        
        exec_result = await phase_4_validation_oracle(python_code)
        analysis = await phase_5_result_analysis(conjecture, exec_result)
        
        status = analysis.get("status")
        final_status = status or "UNKNOWN"
        final_analysis = analysis
        
        if status == "CODE_ERROR":
            code_retries += 1
            if code_retries > MAX_CODE_RETRIES:
                final_status = "CODE_ERROR"
                code_resolved = True
                continue
            corrected = analysis.get("corrected_code")
            if corrected:
                if "```" in corrected:
                    parts = corrected.split("```")
                    if len(parts) >= 3:
                        corrected = parts[1]
                        if "\n" in corrected and corrected.split("\n")[0].strip() in ["python", "sage", "maxima", "cadabra"]:
                            corrected = corrected.split("\n", 1)[1]
                python_code = corrected.strip()
            else:
                python_code = await phase_3_formal_translation(
                    conjecture, 
                    is_correction=True, 
                    previous_error=exec_result.get('stderr', 'Unknown execution error')
                )
        elif status in ["REFUTED", "VALIDATED"]:
            code_resolved = True 
        else:
            final_status = "UNKNOWN"
            code_resolved = True
            
    return final_status, final_analysis

async def main():
    benchmarks = load_benchmarks()
    results = []
    
    stats = {"total": len(benchmarks), "matches": 0, "mismatches": 0, "errors": 0}
    
    # Reset tokens
    conjecture_llm.prompt_tokens = 0
    conjecture_llm.completion_tokens = 0
    translator_llm.prompt_tokens = 0
    translator_llm.completion_tokens = 0
    analyst_llm.prompt_tokens = 0
    analyst_llm.completion_tokens = 0
    
    # Load historical stats
    stats_file = ROOT / "workspace" / "benchmark_stats.json"
    history = []
    if stats_file.exists():
        try:
            with open(stats_file, "r") as f:
                data = json.load(f)
                history = data.get("history", [])
        except Exception:
            pass

    print(f"Starting ASTRUM Headless Benchmark Suite. Total tests: {len(benchmarks)}")
    
    global_start = time.time()
    
    for b in benchmarks:
        print(f"\nEvaluating: {b.id} [{b.domain}]")
        print(f"Expected: {b.expected}")
        
        prompt = b.to_prompt()
        test_start = time.time()
        actual_status, analysis = await run_headless_cycle(prompt)
        test_elapsed = time.time() - test_start
        
        match = (actual_status == b.expected)
        res = {
            "id": b.id,
            "domain": b.domain,
            "expected": b.expected,
            "actual": actual_status,
            "match": match,
            "time_seconds": round(test_elapsed, 2),
            "reasoning": analysis.get("reasoning", "")
        }
        results.append(res)
        
        if match:
            stats["matches"] += 1
            print(f" -> [PASS] Match! Got: {actual_status} ({round(test_elapsed, 2)}s)")
        else:
            if actual_status == "CODE_ERROR":
                stats["errors"] += 1
            else:
                stats["mismatches"] += 1
            print(f" -> [FAIL] Mismatch! Got: {actual_status} ({round(test_elapsed, 2)}s)")
            print(f"    Reasoning: {res['reasoning']}")
            
    global_elapsed = time.time() - global_start
    stats["accuracy"] = round((stats["matches"] / stats["total"]) * 100, 2)
    stats["total_time_seconds"] = round(global_elapsed, 2)
    
    total_prompt_tokens = conjecture_llm.prompt_tokens + translator_llm.prompt_tokens + analyst_llm.prompt_tokens
    total_completion_tokens = conjecture_llm.completion_tokens + translator_llm.completion_tokens + analyst_llm.completion_tokens
    stats["tokens"] = {
        "translator_prompt": translator_llm.prompt_tokens,
        "translator_completion": translator_llm.completion_tokens,
        "analyst_prompt": analyst_llm.prompt_tokens,
        "analyst_completion": analyst_llm.completion_tokens,
        "total_prompt": total_prompt_tokens,
        "total_completion": total_completion_tokens,
        "total": total_prompt_tokens + total_completion_tokens
    }
    
    print(f"\n======================================")
    print(f"      BENCHMARK SUITE COMPLETE        ")
    print(f"======================================")
    print(f"Total: {stats['total']} | Matches: {stats['matches']} | Mismatches: {stats['mismatches']} | Errors: {stats['errors']}")
    print(f"Accuracy: {stats['accuracy']}%")
    print(f"Time: {stats['total_time_seconds']}s")
    print(f"Tokens Used: {stats['tokens']['total']} ({stats['tokens']['total_prompt']} in, {stats['tokens']['total_completion']} out)")
    
    current_run = {
        "timestamp": datetime.datetime.now().isoformat(),
        "stats": stats,
        "details": results
    }
    history.append(current_run)
    
    os.makedirs(stats_file.parent, exist_ok=True)
    with open(stats_file, "w") as f:
        json.dump({"history": history, "latest_run": current_run}, f, indent=4)
    print(f"Saved accumulating statistics to {stats_file}")

if __name__ == "__main__":
    asyncio.run(main())
