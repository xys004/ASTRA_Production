"""Evaluator contracts and readiness checks for external benchmarks."""
from __future__ import annotations

import base64
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import scipy

from core.external_benchmarks import ExternalCase, cache_root


def normalize_final_answer(text: str) -> str:
    matches = re.findall(r"(?is)FINAL\s+ANSWER\s*:?\s*(.+)", text or "")
    value = matches[-1] if matches else (text or "")
    value = value.strip().splitlines()[0] if value.strip() else ""
    for token in ("```", "`", "\\(", "\\)", "\\[", "\\]", "$"):
        value = value.replace(token, "")
    value = re.sub(r"\\[ \t,;:!]", "", value)
    value = value.strip(" \t\r\n.'\"")
    return re.sub(r"\s+", "", value).lower()


def _numeric_quantity(text: str) -> tuple[float, str] | None:
    cleaned = normalize_final_answer(text).replace(",", "")
    for spacing in (r"\,", r"\;", r"\:", r"\!", "~"):
        cleaned = cleaned.replace(spacing, "")
    cleaned = re.sub(r"\\(?:mathrm|textrm|text)\{([^{}]*)\}", r"\1", cleaned)
    cleaned = re.sub(r"\{\\rm([^{}]*)\}", r"\1", cleaned)
    match = re.fullmatch(
        r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))"
        r"(?:\\times10\^\{?([+-]?\d+)\}?)?"
        r"([a-z][a-z0-9*/^._-]*)?",
        cleaned,
    )
    if not match:
        return None
    base = float(match.group(1))
    power = int(match.group(2) or 0)
    return base * (10 ** power), (match.group(3) or "")


def evaluate_frontier_answer(candidate: str, reference: str) -> dict[str, Any]:
    candidate_norm = normalize_final_answer(candidate)
    reference_norm = normalize_final_answer(reference)
    if candidate_norm and candidate_norm == reference_norm:
        return {"status": "PASS", "method": "normalized_exact"}
    candidate_quantity = _numeric_quantity(candidate)
    reference_quantity = _numeric_quantity(reference)
    if candidate_quantity is not None and reference_quantity is not None:
        candidate_number, candidate_unit = candidate_quantity
        reference_number, reference_unit = reference_quantity
        units_match = candidate_unit == reference_unit
        correct = units_match and math.isclose(
            candidate_number,
            reference_number,
            rel_tol=1e-6,
            abs_tol=1e-10,
        )
        return {
            "status": "PASS" if correct else "FAIL",
            "method": "numeric_equivalence",
            "candidate_unit": candidate_unit,
            "reference_unit": reference_unit,
        }
    return {
        "status": "NEEDS_EXPERT",
        "method": "rubric_or_symbolic_equivalence_required",
    }


def _h5_sparse(group):
    data = group["data"][()]
    shape = tuple(group["shape"][()])
    if "row" in group and "col" in group:
        return scipy.sparse.coo_matrix(
            (data, (group["row"][()], group["col"][()])),
            shape=shape,
        )
    indices = group["indices"][()]
    indptr = group["indptr"][()]
    if "blocksize" in group:
        return scipy.sparse.bsr_matrix(
            (data, indices, indptr),
            shape=shape,
            blocksize=tuple(group["blocksize"][()]),
        )
    return scipy.sparse.csr_matrix((data, indices, indptr), shape=shape)


def _h5_group_value(group):
    import h5py

    if "list" in group:
        return [group["list"][key][()] for key in group["list"].keys()]
    if "sparse_matrix" in group:
        return _h5_sparse(group["sparse_matrix"])
    result = {}
    for key, obj in group.items():
        if isinstance(obj, h5py.Group):
            result[key] = _h5_group_value(obj)
        else:
            value = obj[()]
            result[key] = value.decode("utf-8") if isinstance(value, bytes) else value
    return result


def scicode_targets(step_id: str, test_count: int, h5_path: str | Path) -> list[Any]:
    """Compatibility loader for SciCode's official numeric HDF5 targets."""
    import h5py

    targets = []
    with h5py.File(str(h5_path), "r") as handle:
        for test_index in range(1, test_count + 1):
            group = handle[f"{step_id}/test{test_index}"]
            values = []
            for key in group.keys():
                item = group[key]
                if isinstance(item, h5py.Group):
                    values.append(_h5_group_value(item))
                else:
                    value = item[()]
                    values.append(value.decode("utf-8") if isinstance(value, bytes) else value)
            targets.append(values[0] if len(values) == 1 else tuple(values))
    return targets


def evaluate_scicode_code(
    case: ExternalCase,
    code: str,
    *,
    timeout: int = 300,
    h5_path: Path | None = None,
) -> dict[str, Any]:
    if case.evaluator != "scicode_h5_tests":
        raise ValueError("case is not a SciCode subproblem")
    h5_path = h5_path or cache_root() / "SciCode" / "eval" / "data" / "test_data.h5"
    if not h5_path.exists():
        return {"status": "MISSING_EVALUATOR", "missing": str(h5_path)}
    tests = list(case.metadata.get("test_cases") or [])
    harness = (
        "import sys\n"
        f"sys.path.insert(0, {str(Path(__file__).resolve().parent.parent)!r})\n"
        + str(case.metadata.get("required_dependencies") or "")
        + "\n\n"
        + code
        + "\n\n"
        + "from core.external_evaluators import scicode_targets\n"
        + f"targets = scicode_targets({case.metadata['step_number']!r}, "
          f"{len(tests)}, {str(h5_path)!r})\n"
    )
    for index, test in enumerate(tests):
        harness += f"\ntarget = targets[{index}]\n{test}\n"
    with tempfile.TemporaryDirectory(prefix="astra_scicode_") as directory:
        script = Path(directory) / "evaluate.py"
        script.write_text(harness, encoding="utf-8")
        try:
            result = subprocess.run(
                [sys.executable, str(script)],
                cwd=Path(__file__).resolve().parent.parent,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return {"status": "TIMEOUT", "timeout_s": timeout}
    return {
        "status": "PASS" if result.returncode == 0 else "FAIL",
        "exit_code": result.returncode,
        "stdout": result.stdout[-2000:],
        "stderr": result.stderr[-4000:],
        "tests": len(tests),
    }


def clean_lean_proof(response: str) -> str:
    blocks = re.findall(
        r"```(?:lean3?|text)?\s*\n(.*?)```",
        response or "",
        re.DOTALL | re.IGNORECASE,
    )
    proof = (max(blocks, key=len) if blocks else (response or "")).strip()
    if proof.startswith("theorem ") and ":=" in proof:
        proof = proof.split(":=", 1)[1].strip()
    return proof


def minif2f_source(case: ExternalCase, proof: str) -> str:
    if case.evaluator != "lean3_compile":
        raise ValueError("case is not a miniF2F Lean 3 theorem")
    proof = clean_lean_proof(proof)
    return (
        "import minif2f_import\n\n"
        "open_locale big_operators\n"
        "open_locale real\n"
        "open_locale nat\n"
        "open_locale topological_space\n\n"
        f"{case.metadata['statement']} :=\n"
        f"{proof}\n"
    )


async def evaluate_minif2f_proof_remote(
    case: ExternalCase,
    proof: str,
    *,
    timeout: int = 180,
) -> dict[str, Any]:
    """Compile one proof in the pinned miniF2F Lean 3 environment on ASTRUM."""
    proof = clean_lean_proof(proof)
    forbidden = sorted(set(re.findall(r"\b(?:sorry|admit)\b", proof, re.IGNORECASE)))
    if forbidden:
        return {
            "status": "REJECTED",
            "method": "forbidden_placeholder_scan",
            "forbidden": forbidden,
        }
    source = minif2f_source(case, proof)
    source_b64 = base64.b64encode(source.encode("utf-8")).decode("ascii")
    project = os.environ.get(
        "ASTRA_REMOTE_MINIF2F_ROOT",
        "~/astra-benchmarks/miniF2F",
    )
    lean_bin = os.environ.get("ASTRA_REMOTE_LEAN_BIN", "~/.elan/bin/lean")
    remote_code = f"""
import base64, json, os, subprocess, tempfile
project = os.path.abspath(os.path.expanduser({project!r}))
lean_bin = os.path.abspath(os.path.expanduser({lean_bin!r}))
source = base64.b64decode({source_b64!r}).decode("utf-8")
source_dir = os.path.join(project, "lean", "src")
fd, path = tempfile.mkstemp(prefix="astra_minif2f_", suffix=".lean", dir=source_dir)
os.close(fd)
try:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(source)
    env = os.environ.copy()
    env["PATH"] = os.path.dirname(lean_bin) + os.pathsep + env.get("PATH", "")
    try:
        result = subprocess.run(
            [lean_bin, path],
            cwd=project,
            env=env,
            capture_output=True,
            text=True,
            timeout={int(timeout)},
        )
        payload = {{
            "returncode": result.returncode,
            "stdout": result.stdout[-4000:],
            "stderr": result.stderr[-6000:],
        }}
    except subprocess.TimeoutExpired as exc:
        payload = {{
            "returncode": 124,
            "stdout": (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else "",
            "stderr": "Lean compilation timed out after {int(timeout)} seconds",
        }}
    print(json.dumps(payload))
finally:
    try:
        os.remove(path)
    except OSError:
        pass
"""
    from core.remote_executor import execute_remote_code

    response = await execute_remote_code(remote_code, timeout=timeout + 45)
    if int(response.get("exit_code", -1)) != 0:
        return {
            "status": "REMOTE_ERROR",
            "method": "lean3_compile",
            "stderr": str(response.get("stderr") or "")[-6000:],
        }
    try:
        compiler = json.loads(str(response.get("stdout") or "").strip())
    except json.JSONDecodeError:
        return {
            "status": "REMOTE_ERROR",
            "method": "lean3_compile",
            "stderr": "Remote Lean evaluator returned non-JSON output",
            "stdout": str(response.get("stdout") or "")[-4000:],
        }
    return {
        "status": "PASS" if compiler["returncode"] == 0 else (
            "TIMEOUT" if compiler["returncode"] == 124 else "FAIL"
        ),
        "method": "lean3_compile",
        "returncode": compiler["returncode"],
        "stdout": compiler["stdout"],
        "stderr": compiler["stderr"],
        "lean_version": "3.42.1",
        "mathlib_commit": "cb2b02fff213ed6f65bebd64446baac64137dcda",
        "oracle": "astrum",
    }


def resolve_ainstein_image(image: str) -> str:
    """Map the dataset namespace exactly as AInsteinBench's pull script does."""
    if image.startswith("mswebench/"):
        namespace = os.environ.get("ASTRA_AINSTEIN_IMAGE_NAMESPACE", "shuoxin").strip()
        return f"{namespace}/{image.split('/', 1)[1]}"
    return image


def parse_ainstein_msb_log(log: str) -> dict[str, Any]:
    """Match the official repo parsers' PASSED/FAILED line protocol."""
    passed = set()
    failed = set()
    for line in (log or "").splitlines():
        if line.startswith("PASSED"):
            match = re.match(r"PASSED\s+(.*)", line)
            if match:
                passed.add(match.group(1).strip())
        elif line.startswith("FAILED"):
            match = re.match(r"FAILED\s+([^\s-]+)", line)
            if match:
                failed.add(match.group(1).strip())
    return {
        "passed_count": len(passed),
        "failed_count": len(failed),
        "passed_tests": sorted(passed),
        "failed_tests": sorted(failed),
    }


def ainstein_patch_paths(patch: str) -> list[str]:
    paths = set()
    for match in re.finditer(
        r"(?m)^diff --git a/(\S+) b/(\S+)\s*$",
        patch or "",
    ):
        paths.update(path for path in match.groups() if path not in {"dev/null", "/dev/null"})
    for match in re.finditer(
        r"(?m)^(?:---|\+\+\+) (?:[ab]/)?(\S+)\s*$",
        patch or "",
    ):
        if match.group(1) != "/dev/null":
            paths.add(match.group(1))
    return sorted(paths)


def unsafe_ainstein_patch_paths(patch: str) -> list[str]:
    unsafe = []
    for path in ainstein_patch_paths(patch):
        lowered = path.replace("\\", "/").lower()
        parts = lowered.split("/")
        filename = parts[-1]
        if (
            any(part.startswith("test") for part in parts)
            or filename.startswith("test_")
            or filename in {"pytest.ini", "conftest.py", "fix-run.sh", "test-run.sh"}
            or "test.patch" in lowered
        ):
            unsafe.append(path)
    return unsafe


async def inspect_ainstein_repository_remote(
    case: ExternalCase,
    *,
    search_terms: list[str],
    path_hints: list[str],
    timeout: int = 300,
) -> dict[str, Any]:
    """Collect bounded source context without exposing tests or reference patches."""
    if case.evaluator != "ainstein_docker_tests":
        raise ValueError("case is not an AInsteinBench repository task")
    image = resolve_ainstein_image(str(case.metadata["docker_image"]))
    queries = {
        "terms": [str(item)[:120] for item in search_terms[:12] if str(item).strip()],
        "paths": [str(item)[:240] for item in path_hints[:12] if str(item).strip()],
    }
    inspector = r'''
import io
import json
import os
import subprocess

class CommandResult(object):
    def __init__(self, returncode, stdout, stderr):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

def run_command(args, timeout=None):
    # Python 2.7 has no subprocess.run. The outer container invocation enforces
    # the wall-clock timeout for this bounded, read-only inspector.
    process = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    stdout, stderr = process.communicate()
    return CommandResult(process.returncode, stdout, stderr)

query_path = "/astra_input/queries.json"
with io.open(query_path, encoding="utf-8") as handle:
    queries = json.load(handle)

repository_search = run_command(
    [
        "find", "/home", "/opt", "/workspace",
        "-maxdepth", "6", "-type", "d", "-name", ".git",
    ],
    timeout=30,
)
repository_roots = sorted({
    os.path.dirname(path.strip())
    for path in repository_search.stdout.splitlines()
    if path.strip()
})
if not repository_roots:
    raise RuntimeError("No Git repository found in the AInsteinBench image")
repository_root = repository_roots[0]
os.chdir(repository_root)

def safe_path(raw):
    value = os.path.normpath(str(raw).strip().lstrip("/"))
    if value in {"", "."} or value.startswith("../") or "/../" in value:
        return ""
    lowered = value.lower()
    parts = lowered.replace("\\", "/").split("/")
    filename = parts[-1]
    if (
        "test.patch" in lowered
        or "fix.patch" in lowered
        or any(part.startswith("test") for part in parts)
        or filename.startswith("test_")
        or filename in {"conftest.py", "pytest.ini", "fix-run.sh", "test-run.sh"}
    ):
        return ""
    return value

hits = []
for term in queries.get("terms", []):
    term = str(term).strip()
    if not term:
        continue
    result = run_command(
        ["git", "grep", "-n", "-i", "-F", term, "--", "."],
        timeout=30,
    )
    for line in result.stdout.splitlines()[:40]:
        parts = line.split(":", 2)
        if len(parts) == 3 and parts[1].isdigit():
            path = safe_path(parts[0])
            if not path:
                continue
            hits.append({
                "path": path,
                "line": int(parts[1]),
                "match": parts[2][:300],
                "term": term,
            })

files = []
# Exact navigator paths take priority over broad text-search hits so the bounded
# context cannot be exhausted before reaching the file the agents selected.
for raw in queries.get("paths", []):
    path = safe_path(raw)
    if not path:
        continue
    if os.path.isfile(path) and path not in files:
        files.append(path)
    elif os.path.isdir(path):
        listed = run_command(
            ["git", "ls-files", path],
            timeout=30,
        )
        for candidate in listed.stdout.splitlines():
            if candidate.endswith((".py", ".c", ".cc", ".cpp", ".h", ".f", ".f90")):
                if candidate not in files:
                    files.append(candidate)
                if len(files) >= 12:
                    break
for item in hits:
    if item["path"] and item["path"] not in files:
        files.append(item["path"])

snippets = []
budget = 32000
used = 0
for path in files[:12]:
    if not os.path.isfile(path):
        continue
    try:
        with io.open(path, encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    except OSError:
        continue
    line_hits = [item["line"] for item in hits if item["path"] == path]
    centers = line_hits[:3] or [1]
    for center in centers:
        start = max(1, center - 35)
        end = min(len(lines), center + 35)
        body = "".join(
            "{:6d}: {}".format(index, lines[index - 1])
            for index in range(start, end + 1)
        )
        entry = "FILE {} LINES {}-{}\n{}".format(path, start, end, body)
        if used + len(entry) > budget:
            break
        snippets.append(entry)
        used += len(entry)
    if used >= budget:
        break

payload = {
    "repository_root": repository_root,
    "git_commit": run_command(
        ["git", "rev-parse", "HEAD"],
        timeout=15,
    ).stdout.strip(),
    "queries": queries,
    "hits": hits[:80],
    "snippets": snippets,
}
print("ASTRA_CONTEXT_JSON=" + json.dumps(payload))
'''
    inspector_b64 = base64.b64encode(inspector.encode("utf-8")).decode("ascii")
    queries_b64 = base64.b64encode(json.dumps(queries).encode("utf-8")).decode("ascii")
    udocker_bin = os.environ.get(
        "ASTRA_REMOTE_UDOCKER_BIN",
        "~/miniforge3/envs/astra-bench/bin/udocker",
    )
    udocker_dir = os.environ.get(
        "ASTRA_REMOTE_UDOCKER_DIR",
        "~/astra-benchmarks/udocker",
    )
    eval_root = os.environ.get(
        "ASTRA_REMOTE_AINSTEIN_EVAL_ROOT",
        "~/astra-benchmarks/ainstein-evals",
    )
    remote_code = f"""
import base64, json, os, shutil, subprocess, tempfile, uuid
udocker_bin = os.path.abspath(os.path.expanduser({udocker_bin!r}))
udocker_dir = os.path.abspath(os.path.expanduser({udocker_dir!r}))
eval_root = os.path.abspath(os.path.expanduser({eval_root!r}))
image = {image!r}
os.makedirs(eval_root, exist_ok=True)
host_dir = tempfile.mkdtemp(prefix="astra_inspect_", dir=eval_root)
container = "astra_inspect_" + uuid.uuid4().hex[:12]
env = os.environ.copy()
env["UDOCKER_DIR"] = udocker_dir
payload = {{}}
try:
    with open(os.path.join(host_dir, "inspect.py"), "wb") as handle:
        handle.write(base64.b64decode({inspector_b64!r}))
    with open(os.path.join(host_dir, "queries.json"), "wb") as handle:
        handle.write(base64.b64decode({queries_b64!r}))
    images = subprocess.run(
        [udocker_bin, "images", "-l"],
        env=env, capture_output=True, text=True, timeout=60,
    )
    if image not in images.stdout:
        payload = {{"returncode": 125, "stderr": "Missing image: " + image}}
    else:
        create = subprocess.run(
            [udocker_bin, "create", "--name=" + container, image],
            env=env, capture_output=True, text=True, timeout=600,
        )
        setup = subprocess.run(
            [udocker_bin, "setup", "--execmode=P2", container],
            env=env, capture_output=True, text=True, timeout=120,
        ) if create.returncode == 0 else None
        if create.returncode != 0 or setup is None or setup.returncode != 0:
            payload = {{
                "returncode": create.returncode if create.returncode else setup.returncode,
                "stderr": (create.stderr if create.returncode else setup.stderr)[-5000:],
            }}
        else:
            run = subprocess.run(
                [
                    udocker_bin, "run", "--user=root",
                    "-v", host_dir + ":/astra_input",
                    container, "python", "/astra_input/inspect.py",
                ],
                env=env, capture_output=True, text=True, timeout={int(timeout)},
            )
            payload = {{
                "returncode": run.returncode,
                "stdout": run.stdout[-120000:],
                "stderr": run.stderr[-5000:],
            }}
finally:
    subprocess.run(
        [udocker_bin, "rm", container],
        env=env, capture_output=True, text=True, timeout=120,
    )
    shutil.rmtree(host_dir, ignore_errors=True)
print(json.dumps(payload))
"""
    from core.remote_executor import execute_remote_code

    response = await execute_remote_code(remote_code, timeout=timeout + 180)
    if int(response.get("exit_code", -1)) != 0:
        return {"status": "REMOTE_ERROR", "stderr": response.get("stderr", "")}
    try:
        run = json.loads(str(response.get("stdout") or "").strip())
    except json.JSONDecodeError:
        return {"status": "REMOTE_ERROR", "stderr": "Non-JSON inspection response"}
    marker = re.search(r"(?m)^ASTRA_CONTEXT_JSON=(\{.*\})$", run.get("stdout") or "")
    if run.get("returncode") != 0 or not marker:
        return {
            "status": "FAIL",
            "returncode": run.get("returncode"),
            "stdout": str(run.get("stdout") or "")[-6000:],
            "stderr": str(run.get("stderr") or "")[-5000:],
        }
    context = json.loads(marker.group(1))
    if not context.get("snippets"):
        return {
            "status": "FAIL",
            "returncode": run.get("returncode"),
            "stderr": (
                "Repository inspection returned no source snippets for the "
                "requested terms or path hints."
            ),
            **context,
        }
    return {
        "status": "PASS",
        "runtime": "udocker-1.3.17-proot-P2",
        **context,
    }


async def prepare_ainstein_image_remote(
    case: ExternalCase,
    *,
    timeout: int = 3600,
) -> dict[str, Any]:
    if case.evaluator != "ainstein_docker_tests":
        raise ValueError("case is not an AInsteinBench repository task")
    image = resolve_ainstein_image(str(case.metadata["docker_image"]))
    udocker_bin = os.environ.get(
        "ASTRA_REMOTE_UDOCKER_BIN",
        "~/miniforge3/envs/astra-bench/bin/udocker",
    )
    udocker_dir = os.environ.get(
        "ASTRA_REMOTE_UDOCKER_DIR",
        "~/astra-benchmarks/udocker",
    )
    remote_code = f"""
import json, os, subprocess
udocker_bin = os.path.abspath(os.path.expanduser({udocker_bin!r}))
udocker_dir = os.path.abspath(os.path.expanduser({udocker_dir!r}))
image = {image!r}
env = os.environ.copy()
env["UDOCKER_DIR"] = udocker_dir
images = subprocess.run(
    [udocker_bin, "images", "-l"],
    env=env, capture_output=True, text=True, timeout=60,
)
if image in images.stdout:
    payload = {{"returncode": 0, "already_present": True}}
else:
    try:
        result = subprocess.run(
            [udocker_bin, "pull", image],
            env=env, capture_output=True, text=True, timeout={int(timeout)},
        )
        payload = {{
            "returncode": result.returncode,
            "already_present": False,
            "stdout": result.stdout[-8000:],
            "stderr": result.stderr[-8000:],
        }}
    except subprocess.TimeoutExpired:
        payload = {{
            "returncode": 124,
            "already_present": False,
            "stderr": "Image pull timed out after {int(timeout)} seconds",
        }}
print(json.dumps(payload))
"""
    from core.remote_executor import execute_remote_code

    response = await execute_remote_code(remote_code, timeout=timeout + 90)
    if int(response.get("exit_code", -1)) != 0:
        return {
            "status": "REMOTE_ERROR",
            "image": image,
            "stderr": str(response.get("stderr") or "")[-8000:],
        }
    try:
        result = json.loads(str(response.get("stdout") or "").strip())
    except json.JSONDecodeError:
        return {
            "status": "REMOTE_ERROR",
            "image": image,
            "stderr": "Remote image preparation returned non-JSON output",
        }
    return {
        "status": "READY" if result.get("returncode") == 0 else (
            "TIMEOUT" if result.get("returncode") == 124 else "FAILED"
        ),
        "image": image,
        **result,
    }


async def evaluate_ainstein_patch_remote(
    case: ExternalCase,
    patch: str,
    *,
    timeout: int = 1800,
) -> dict[str, Any]:
    """Run a Multi-SWE-bench patch in its prepared OCI image on ASTRUM.

    ASTRUM currently uses uDocker's PRoot engine because unprivileged user
    namespaces are restricted. The image and bundled fix-run.sh remain the
    official AInsteinBench artifacts, but this runtime distinction is recorded.
    """
    if case.evaluator != "ainstein_docker_tests":
        raise ValueError("case is not an AInsteinBench repository task")
    if not patch.strip():
        return {"status": "REJECTED", "method": "empty_patch"}
    # Model responses commonly omit the final LF when a fenced diff is stripped.
    # `git apply` processes this together with the image's test patch and otherwise
    # reports an otherwise valid final hunk as corrupt.
    patch = patch.rstrip() + "\n"
    unsafe_paths = unsafe_ainstein_patch_paths(patch)
    if unsafe_paths:
        return {
            "status": "REJECTED",
            "method": "candidate_test_modification",
            "unsafe_paths": unsafe_paths,
        }
    image = str(case.metadata["docker_image"])
    resolved_image = resolve_ainstein_image(image)
    patch_b64 = base64.b64encode(patch.encode("utf-8")).decode("ascii")
    udocker_bin = os.environ.get(
        "ASTRA_REMOTE_UDOCKER_BIN",
        "~/miniforge3/envs/astra-bench/bin/udocker",
    )
    udocker_dir = os.environ.get(
        "ASTRA_REMOTE_UDOCKER_DIR",
        "~/astra-benchmarks/udocker",
    )
    eval_root = os.environ.get(
        "ASTRA_REMOTE_AINSTEIN_EVAL_ROOT",
        "~/astra-benchmarks/ainstein-evals",
    )
    remote_code = f"""
import base64, json, os, shutil, subprocess, tempfile, uuid
udocker_bin = os.path.abspath(os.path.expanduser({udocker_bin!r}))
udocker_dir = os.path.abspath(os.path.expanduser({udocker_dir!r}))
eval_root = os.path.abspath(os.path.expanduser({eval_root!r}))
image = {resolved_image!r}
os.makedirs(eval_root, exist_ok=True)
host_dir = tempfile.mkdtemp(prefix="astra_ainstein_", dir=eval_root)
container = "astra_" + uuid.uuid4().hex[:16]
env = os.environ.copy()
env["UDOCKER_DIR"] = udocker_dir
payload = {{}}
try:
    patch_path = os.path.join(host_dir, "fix.patch")
    with open(patch_path, "wb") as handle:
        handle.write(base64.b64decode({patch_b64!r}))
    images = subprocess.run(
        [udocker_bin, "images", "-l"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if image not in images.stdout:
        payload = {{
            "stage": "image",
            "returncode": 125,
            "stdout": images.stdout[-4000:],
            "stderr": "Prepared image is not present: " + image,
        }}
    else:
        create = subprocess.run(
            [udocker_bin, "create", "--name=" + container, image],
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if create.returncode != 0:
            payload = {{
                "stage": "create",
                "returncode": create.returncode,
                "stdout": create.stdout[-4000:],
                "stderr": create.stderr[-4000:],
            }}
        else:
            setup = subprocess.run(
                [udocker_bin, "setup", "--execmode=P2", container],
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if setup.returncode != 0:
                payload = {{
                    "stage": "setup",
                    "returncode": setup.returncode,
                    "stdout": setup.stdout[-4000:],
                    "stderr": setup.stderr[-4000:],
                }}
            else:
                try:
                    run = subprocess.run(
                        [
                            udocker_bin, "run", "--user=root",
                            "-v", host_dir + ":/astra_input",
                            container, "/bin/bash", "-lc",
                            "cp /astra_input/fix.patch /home/fix.patch && "
                            "bash /home/fix-run.sh",
                        ],
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout={int(timeout)},
                    )
                    payload = {{
                        "stage": "tests",
                        "returncode": run.returncode,
                        "stdout": run.stdout[-20000:],
                        "stderr": run.stderr[-8000:],
                    }}
                except subprocess.TimeoutExpired as exc:
                    payload = {{
                        "stage": "tests",
                        "returncode": 124,
                        "stdout": (exc.stdout or "")[-20000:]
                            if isinstance(exc.stdout, str) else "",
                        "stderr": "AInsteinBench tests timed out after {int(timeout)} seconds",
                    }}
finally:
    subprocess.run(
        [udocker_bin, "rm", container],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    shutil.rmtree(host_dir, ignore_errors=True)
print(json.dumps(payload))
"""
    from core.remote_executor import execute_remote_code

    response = await execute_remote_code(remote_code, timeout=timeout + 180)
    if int(response.get("exit_code", -1)) != 0:
        return {
            "status": "REMOTE_ERROR",
            "method": "ainstein_udocker_tests",
            "stderr": str(response.get("stderr") or "")[-8000:],
        }
    try:
        run = json.loads(str(response.get("stdout") or "").strip())
    except json.JSONDecodeError:
        return {
            "status": "REMOTE_ERROR",
            "method": "ainstein_udocker_tests",
            "stderr": "Remote AInstein evaluator returned non-JSON output",
            "stdout": str(response.get("stdout") or "")[-4000:],
        }
    parsed = parse_ainstein_msb_log(run.get("stdout") or "")
    passed = parsed["passed_count"]
    failed = parsed["failed_count"]
    if run.get("returncode") == 124:
        status = "TIMEOUT"
    elif run.get("stage") == "image":
        status = "MISSING_IMAGE"
    elif run.get("returncode") == 0 and passed > 0 and failed == 0:
        status = "PASS"
    else:
        status = "FAIL"
    return {
        "status": status,
        "method": "official_image_fix_run",
        "runtime": "udocker-1.3.17-proot-P2",
        "runtime_note": (
            "Official AInsteinBench image and test script under uDocker PRoot; "
            "not a native Docker daemon."
        ),
        "dataset_image": image,
        "resolved_image": resolved_image,
        "stage": run.get("stage"),
        "returncode": run.get("returncode"),
        **parsed,
        "resolve_points": (
            int(case.metadata.get("scoring_config", {}).get("resolve_points", 100))
            if status == "PASS" else 0
        ),
        "stdout": str(run.get("stdout") or "")[-12000:],
        "stderr": str(run.get("stderr") or "")[-6000:],
        "oracle": "astrum",
    }


def evaluator_readiness(case: ExternalCase) -> dict[str, Any]:
    root = cache_root()
    if case.evaluator == "frontier_answer_equivalence":
        return {"ready": True, "mode": "exact/numeric then expert fallback"}
    if case.evaluator == "frontier_expert_rubric":
        return {"ready": False, "mode": "blind expert or official rubric judge required"}
    if case.evaluator == "scicode_h5_tests":
        h5 = root / "SciCode" / "eval" / "data" / "test_data.h5"
        return {
            "ready": h5.exists(),
            "mode": "official HDF5 numerical tests",
            "missing": "" if h5.exists() else str(h5),
        }
    if case.evaluator == "lean3_compile":
        lean = shutil.which("lean")
        return {
            "ready": bool(lean),
            "mode": "Lean 3 compiler",
            "missing": "" if lean else "lean executable",
        }
    if case.evaluator == "ainstein_docker_tests":
        docker = shutil.which("docker")
        return {
            "ready": bool(docker),
            "mode": "official per-task Docker image and test patch",
            "missing": "" if docker else "docker executable",
        }
    return {"ready": False, "mode": "unknown evaluator"}
