from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path


REPORT_DIR = Path("workspace/reports")


def _safe_block(value) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return "\n".join(f"{k}: {v}" for k, v in value.items())
    return str(value)


def _write_pdf_stub(markdown_path: Path, pdf_path: Path) -> bool:
    if shutil.which("pdflatex") is None:
        return False

    content = markdown_path.read_text(encoding="utf-8", errors="replace")
    tex = r"""\documentclass[11pt,a4paper]{article}
\usepackage[utf8]{inputenc}
\usepackage{geometry}
\usepackage{hyperref}
\geometry{margin=2cm}
\title{ASTRUM Cycle Report}
\author{ASTRUM Production}
\date{\today}
\begin{document}
\maketitle
\begin{verbatim}
""" + content[:12000] + r"""
\end{verbatim}
\end{document}
"""
    tex_path = pdf_path.with_suffix(".tex")
    tex_path.write_text(tex, encoding="utf-8")
    subprocess.run(
        ["pdflatex", "-interaction=nonstopmode", tex_path.name],
        cwd=pdf_path.parent,
        capture_output=True,
        timeout=60,
    )
    return pdf_path.exists()


def generate_cycle_report(
    *,
    cycle: int,
    status: str,
    intuition: str | None,
    conjecture: str,
    code: str,
    execution_result: dict,
    analysis: dict,
    axiomatic_base: str,
    providers: dict,
) -> dict:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"cycle_{cycle:04d}_{timestamp}"
    md_path = REPORT_DIR / f"{base}.md"
    html_path = REPORT_DIR / f"{base}.html"
    pdf_path = REPORT_DIR / f"{base}.pdf"

    reasoning = analysis.get("reasoning") or analysis.get("status") or ""
    next_step = analysis.get("next_step") or analysis.get("suggestion") or (
        "Review the evidence, refine the hypothesis, or launch another cycle with a narrower intuition."
    )

    md = f"""# ASTRUM Cycle {cycle} Report

Generated: {datetime.now().isoformat(timespec="seconds")}

## Summary

- Final status: `{status}`
- Analyst status: `{analysis.get("status", "UNKNOWN")}`
- Providers: conjecture=`{providers.get("conjecture")}`, translator=`{providers.get("translator")}`, analyst=`{providers.get("analyst")}`

## User Intuition

```text
{_safe_block(intuition)}
```

## Hypothesis / Conjecture

```text
{_safe_block(conjecture)}
```

## Validation Script

```python
{_safe_block(code)}
```

## Oracle Result

```text
exit_code: {execution_result.get("exit_code")}
engine: {execution_result.get("engine", "python")}

STDOUT:
{execution_result.get("stdout", "")}

STDERR:
{execution_result.get("stderr", "")}
```

## Analysis

```text
{_safe_block(reasoning)}
```

## Conclusion

The cycle ended with analyst status `{analysis.get("status", "UNKNOWN")}`. Human approval is required before any validated theorem is added to the axiomatic base.

## Suggested Next Step

{next_step}

## Axiomatic Base Snapshot

```text
{_safe_block(axiomatic_base)}
```
"""
    md_path.write_text(md, encoding="utf-8")

    def _md_to_html(text: str) -> str:
        lines = text.split("\n")
        out = []
        in_code = False
        for line in lines:
            if line.startswith("```"):
                if not in_code:
                    lang = line[3:].strip()
                    cls = f' class="language-{lang}"' if lang else ""
                    out.append(f"<pre><code{cls}>")
                    in_code = True
                else:
                    out.append("</code></pre>")
                    in_code = False
            elif in_code:
                out.append(html.escape(line))
            elif line.startswith("# "):
                out.append(f"<h1>{html.escape(line[2:])}</h1>")
            elif line.startswith("## "):
                out.append(f"<h2>{html.escape(line[3:])}</h2>")
            elif line.startswith("### "):
                out.append(f"<h3>{html.escape(line[4:])}</h3>")
            elif line.startswith("- "):
                out.append(f"<li>{html.escape(line[2:])}</li>")
            elif line.strip() == "":
                out.append("<br>")
            else:
                escaped_line = html.escape(line)
                escaped_line = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped_line)
                out.append(f"<p>{escaped_line}</p>")
        return "\n".join(out)

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ASTRUM Cycle {cycle} Report</title>
  <style>
    body {{ font-family: Inter, Arial, sans-serif; margin: 2rem auto; max-width: 900px; color: #17202a; line-height: 1.6; }}
    h1 {{ color: #0b3b5a; border-bottom: 2px solid #0b3b5a; padding-bottom: .4rem; }}
    h2 {{ color: #0b3b5a; margin-top: 1.8rem; }}
    h3 {{ color: #1a4f72; margin-top: 1.2rem; }}
    pre {{ white-space: pre-wrap; background: #f3f6f8; border: 1px solid #d8e1e8; padding: 1rem; border-radius: 6px; overflow-x: auto; }}
    code {{ background: #f3f6f8; padding: .15rem .35rem; border-radius: 3px; font-family: Consolas, monospace; font-size: .9em; }}
    pre code {{ background: none; padding: 0; }}
    li {{ margin-left: 1.5rem; }}
    p {{ margin: .4rem 0; }}
  </style>
</head>
<body>
{_md_to_html(md)}
</body>
</html>
"""
    html_path.write_text(html_doc, encoding="utf-8")

    pdf_created = _write_pdf_stub(md_path, pdf_path)
    return {
        "cycle": cycle,
        "status": analysis.get("status", status),
        "md": str(md_path),
        "html": str(html_path),
        "pdf": str(pdf_path) if pdf_created else "",
        "created_at": timestamp,
    }
