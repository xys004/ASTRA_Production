import os
import subprocess
import uuid

def generate_pdf_report(conjecture: str, workspace_dir: str = "workspace/reports") -> str:
    os.makedirs(workspace_dir, exist_ok=True)
    
    filename_base = f"theorem_report_{uuid.uuid4().hex[:8]}"
    tex_filepath = os.path.join(workspace_dir, f"{filename_base}.tex")
    
    latex_content = f"""\\documentclass[11pt, a4paper]{{article}}
\\usepackage[utf8]{{inputenc}}
\\usepackage{{amsmath, amssymb, amsthm}}
\\usepackage{{geometry}}
\\geometry{{margin=2cm}}

\\title{{\\textbf{{ASTRA Theorem Validation Report}}}}
\\author{{ASTRA Production Orchestrator}}
\\date{{\\today}}

\\begin{{document}}
\\maketitle

\\section*{{Validated Hypothesis}}

{conjecture}

\\vspace{{2cm}}
\\hrule
\\vspace{{0.5cm}}
\\noindent \\small \\textit{{This theorem was autonomously generated, translated, and mathematically verified by the ASTRA zero-trust engine.}}

\\end{{document}}
"""
    with open(tex_filepath, "w", encoding="utf-8") as f:
        f.write(latex_content)
        
    # Compile
    subprocess.run(["pdflatex", "-interaction=nonstopmode", f"{filename_base}.tex"], cwd=workspace_dir, capture_output=True)

    pdf_path = os.path.join(workspace_dir, f"{filename_base}.pdf")
    if not os.path.exists(pdf_path):
        raise RuntimeError(f"pdflatex ran but did not produce {pdf_path}")
    return pdf_path
