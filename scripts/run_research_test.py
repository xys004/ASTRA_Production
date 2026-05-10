"""
scripts/run_research_test.py — Headless integration test of the ASTRA Research Loop.

Runs N autonomous cycles with the Research Navigator on a real physics macro question.
No Flask server required.  Output is printed to stdout and saved as JSON + Markdown.

Usage:
    python scripts/run_research_test.py
    python scripts/run_research_test.py --provider vertexai --cycles 2
    python scripts/run_research_test.py --provider gemini --cycles 1 --question "..."
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.preflight import load_project_env
load_project_env()

# ── Default macro question ────────────────────────────────────────────────────
DEFAULT_MACRO = (
    "Determine whether the Alcubierre warp metric requires strictly negative "
    "energy density everywhere within the bubble, or whether there exist geometric "
    "modifications — shape function variations, modified velocity profiles — that "
    "can localise or reduce the exotic matter requirements while preserving the "
    "warp causal structure. Characterise the minimal NEC-violation for physically "
    "parametrised bubble geometries."
)

DIVIDER = "=" * 70


def _apply_provider(provider: str) -> None:
    for key in ("ASTRA_CONJECTURE_PROVIDER", "ASTRA_TRANSLATOR_PROVIDER",
                "ASTRA_ANALYST_PROVIDER", "ASTRA_NAVIGATOR_PROVIDER"):
        os.environ[key] = provider


def _banner(title: str) -> None:
    print(f"\n{DIVIDER}")
    print(f"  {title}")
    print(DIVIDER)


def _section(title: str) -> None:
    dashes = "-" * max(0, 66 - len(title))
    print(f"\n-- {title} {dashes}")


async def run_research_test(macro_question: str, max_cycles: int, provider: str) -> dict:
    from core.llm_client import ASTRAIntelligence
    from core.research_session import ResearchSession

    # Inline phases — same logic as main.py but without global state
    from main import (
        phase_3_formal_translation,
        phase_4_validation_oracle,
        phase_5_result_analysis,
        _reload_llm_clients,
        MAX_CODE_RETRIES,
    )
    from core.state import state

    _apply_provider(provider)
    _reload_llm_clients()

    from main import conjecture_llm, navigator_llm

    session = ResearchSession(macro_question=macro_question, heartbeat_interval=max_cycles + 1)
    state.research_session = session

    session_dir = ROOT / "workspace" / "sessions"
    session_dir.mkdir(parents=True, exist_ok=True)

    current_direction = macro_question
    cycles_run: list[dict] = []

    _banner(f"ASTRA RESEARCH LOOP TEST  —  provider: {provider}")
    print(f"\nMACRO QUESTION:\n{macro_question}\n")
    print(f"Cycles planned : {max_cycles}")
    print(f"Provider       : {provider}")

    for cycle_idx in range(1, max_cycles + 1):
        _banner(f"CYCLE {cycle_idx}/{max_cycles}")

        # ── Phase 2: Conjecture ──────────────────────────────────────────
        _section("Phase 2 — Conjecture")
        print(f"  Intuition fed to Conjecture Engine:\n  {current_direction[:300]}")
        conjecture = await conjecture_llm.generate_conjecture(
            axiomatic_base=state.axiomatic_base,
            intuition=current_direction,
        )
        state.current_conjecture = conjecture
        print(f"\n  Generated conjecture ({len(conjecture)} chars):")
        print("  " + conjecture[:600].replace("\n", "\n  "))

        # ── Phases 3–5 with retry ────────────────────────────────────────
        python_code  = None
        code_retries = 0
        final_status = "INCOMPLETE"
        final_analysis: dict = {}

        while True:
            if python_code is None:
                _section("Phase 3 — Formal Translation")
                python_code = await phase_3_formal_translation(conjecture)
                state.last_python_code = python_code
                print(f"  Code generated ({len(python_code)} chars).")

            _section("Phase 4 — Validation Oracle")
            exec_result = await phase_4_validation_oracle(python_code)
            state.last_execution_result = exec_result
            stdout_preview = (exec_result.get("stdout") or "")[:300]
            stderr_preview = (exec_result.get("stderr") or "")[:200]
            print(f"  exit_code : {exec_result.get('exit_code')}")
            if stdout_preview:
                print(f"  stdout    : {stdout_preview}")
            if stderr_preview:
                print(f"  stderr    : {stderr_preview}")

            _section("Phase 5 — Refutation Analysis")
            analysis = await phase_5_result_analysis(conjecture, exec_result)
            state.last_analysis = analysis
            status = analysis.get("status", "UNKNOWN")
            print(f"  STATUS    : {status}")
            print(f"  Reasoning : {analysis.get('reasoning', '')[:400]}")

            if status == "CODE_ERROR":
                code_retries += 1
                if code_retries > MAX_CODE_RETRIES:
                    print(f"  [ABORT] Max retries ({MAX_CODE_RETRIES}) reached.")
                    final_status   = "CODE_ERROR"
                    final_analysis = analysis
                    break
                print(f"  [RETRY {code_retries}/{MAX_CODE_RETRIES}] Attempting code correction...")
                corrected = analysis.get("corrected_code")
                if corrected:
                    if "```" in corrected:
                        parts = corrected.split("```")
                        if len(parts) >= 3:
                            corrected = parts[1]
                            first = corrected.split("\n")[0].strip()
                            if first in ("python", "sage", "maxima", "cadabra"):
                                corrected = corrected.split("\n", 1)[1]
                    python_code = corrected.strip()
                else:
                    python_code = await phase_3_formal_translation(
                        conjecture, is_correction=True,
                        previous_error=exec_result.get("stderr", ""),
                    )
            else:
                final_status   = status
                final_analysis = analysis
                # Update axiomatic base
                if status == "REFUTED":
                    state.axiomatic_base += (
                        f"\n[REFUTED]: {conjecture}\n"
                        f"Reasoning: {analysis.get('reasoning', '')}"
                    )
                elif status in ("VALIDATED", "VALIDATED_APPROVED"):
                    state.axiomatic_base += f"\n[ESTABLISHED THEOREM]: {conjecture}"
                break

        # ── Navigator ────────────────────────────────────────────────────
        _section("Research Navigator")
        nav_status = "VALIDATED" if final_status.startswith("VALIDATED") else final_status

        nav = await navigator_llm.navigate_research(
            macro_question=macro_question,
            axiomatic_base=state.axiomatic_base,
            last_conjecture=conjecture,
            last_status=nav_status,
            last_reasoning=final_analysis.get("reasoning", ""),
            thread_summary=session.thread_summary(),
            cycles_since_milestone=session.cycles_since_milestone,
        )

        session.add_branches(nav.get("parallel_branches", []))
        session.record_cycle(
            cycle_num=cycle_idx,
            conjecture=conjecture,
            status=final_status,
            reasoning=final_analysis.get("reasoning", ""),
            nav_direction=nav.get("next_direction", ""),
        )
        session.cycles_since_milestone += 1

        print(f"\n  Progress assessment:\n  {nav.get('progress_assessment', '')}")
        print(f"\n  Next direction proposed:\n  {nav.get('next_direction', '')[:400]}")
        print(f"\n  Rationale:\n  {nav.get('rationale', '')[:400]}")

        branches = nav.get("parallel_branches", [])
        if branches:
            print(f"\n  Parallel branches saved ({len(branches)}):")
            for b in branches:
                print(f"    [{b.get('id','?')}]  {b.get('direction','')[:120]}")
                print(f"           ↳ {b.get('motivation','')[:100]}")

        milestone = nav.get("milestone", False)
        print(f"\n  Milestone flag : {milestone}")
        if milestone:
            print(f"  Milestone reason: {nav.get('milestone_reason', '')}")

        cycles_run.append({
            "cycle": cycle_idx,
            "intuition": current_direction[:300],
            "conjecture": conjecture[:800],
            "status": final_status,
            "reasoning": final_analysis.get("reasoning", "")[:500],
            "navigator": nav,
        })

        current_direction = nav.get("next_direction", macro_question)

    # ── Session summary ──────────────────────────────────────────────────────
    session.save(str(session_dir))

    _banner("SESSION SUMMARY")
    print(f"  Session ID     : {session.session_id}")
    print(f"  Cycles run     : {len(cycles_run)}")
    print(f"  Branch registry: {len(session.pending_branches())} pending branches")
    print(f"\n  Thread:")
    for entry in session.thread:
        print(f"    Cycle {entry['cycle']} [{entry['status']}]: "
              f"{entry['conjecture'][:100]}...")
    if session.pending_branches():
        print(f"\n  Saved branches for future exploration:")
        for b in session.pending_branches():
            print(f"    [{b['id']}] {b['direction'][:120]}")

    result = {
        "session": session.to_dict(),
        "cycles": cycles_run,
        "axiomatic_base_final": state.axiomatic_base,
        "provider": provider,
        "timestamp": datetime.datetime.now().isoformat(),
    }

    # Save full result
    out_dir  = ROOT / "workspace" / "research_runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts_slug  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"research_test_{ts_slug}"

    out_file.with_suffix(".json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Markdown summary
    md_lines = [
        "# ASTRA Research Loop — Test Run",
        "",
        f"**Date:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}  ",
        f"**Provider:** {provider}  ",
        f"**Session:** `{session.session_id}`",
        "",
        "## Macro Question",
        "",
        macro_question,
        "",
        "## Thread",
        "",
    ]
    for c in cycles_run:
        status_icon = "✓" if "VALIDATED" in c["status"] else ("✗" if "REFUTED" in c["status"] else "?")
        md_lines += [
            f"### Cycle {c['cycle']} — {status_icon} {c['status']}",
            "",
            f"**Intuition fed:** {c['intuition'][:200]}",
            "",
            f"**Conjecture (excerpt):** {c['conjecture'][:400]}",
            "",
            f"**Reasoning:** {c['reasoning'][:300]}",
            "",
            f"**Navigator → next direction:** {c['navigator'].get('next_direction','')[:300]}",
            "",
        ]
    if session.pending_branches():
        md_lines += ["## Branch Registry", ""]
        for b in session.pending_branches():
            md_lines += [
                f"- **[{b['id']}]** {b['direction'][:160]}",
                f"  *{b['motivation'][:120]}*",
                "",
            ]
    out_file.with_suffix(".md").write_text("\n".join(md_lines), encoding="utf-8")

    print(f"\n  Full report saved to: {out_file}.md")
    print(DIVIDER)

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ASTRA Research Loop headless test")
    parser.add_argument("--provider", default="vertexai",
                        help="LLM provider for all phases (default: vertexai)")
    parser.add_argument("--cycles", type=int, default=2,
                        help="Number of autonomous cycles to run (default: 2)")
    parser.add_argument("--question", default=DEFAULT_MACRO,
                        help="Macro research question")
    args = parser.parse_args()

    asyncio.run(run_research_test(
        macro_question=args.question,
        max_cycles=args.cycles,
        provider=args.provider,
    ))
