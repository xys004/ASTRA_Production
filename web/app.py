import os
import json
import threading
import sys
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename

# Allow imports from project root
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from core.state import state
from core.research_session import ResearchSession
from main import start_background_loop

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB

UPLOADS_DIR       = os.path.join(os.path.dirname(os.path.dirname(__file__)), "workspace", "uploads")
ASSETS_DIR        = os.path.join(os.path.dirname(os.path.dirname(__file__)), "workspace", "assets")
REPORTS_DIR       = os.path.join(os.path.dirname(os.path.dirname(__file__)), "workspace", "reports")
INVESTIGATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "workspace", "investigations")
os.makedirs(UPLOADS_DIR,        exist_ok=True)
os.makedirs(ASSETS_DIR,         exist_ok=True)
os.makedirs(REPORTS_DIR,        exist_ok=True)
os.makedirs(INVESTIGATIONS_DIR, exist_ok=True)

# Start background ASTRA loop — errors are caught and logged rather than crashing the thread
def _safe_background_loop():
    try:
        start_background_loop()
    except Exception as exc:
        state.add_log(f"[FATAL] Background loop terminated unexpectedly: {exc}")
        state.status = "IDLE"

threading.Thread(target=_safe_background_loop, daemon=True).start()


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/health')
def health():
    return jsonify({"status": "ok"})


@app.route('/api/state')
def get_state():
    return jsonify(state.get_state_dict())


@app.route('/api/start', methods=['POST'])
def start_loop():
    data = request.json or {}
    intuition = data.get('intuition', '')
    if intuition:
        state.current_intuition = intuition

    providers = data.get('providers', {})
    if providers:
        if 'conjecture' in providers:
            os.environ['ASTRA_CONJECTURE_PROVIDER'] = providers['conjecture']
        if 'translator' in providers:
            os.environ['ASTRA_TRANSLATOR_PROVIDER'] = providers['translator']
        if 'analyst' in providers:
            os.environ['ASTRA_ANALYST_PROVIDER'] = providers['analyst']

    state.start_loop_requested = True
    return jsonify({"success": True})


@app.route('/api/stop', methods=['POST'])
def stop_loop():
    state.stop_requested = True
    state.add_log("Stop requested by user.")
    return jsonify({"success": True})


@app.route('/api/approve', methods=['POST'])
def approve():
    state.approve_theorem_requested = True
    return jsonify({"success": True})


@app.route('/api/reject', methods=['POST'])
def reject():
    state.reject_theorem_requested = True
    return jsonify({"success": True})


@app.route('/api/reports')
def reports():
    return jsonify({"reports": state.reports})


@app.route('/reports/<path:filename>')
def report_file(filename):
    return send_from_directory(REPORTS_DIR, filename, as_attachment=False)


@app.route('/api/upload_doc', methods=['POST'])
def upload_doc():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if not file.filename:
        return jsonify({"error": "No file selected"}), 400

    filename = secure_filename(file.filename)
    filepath = os.path.join(UPLOADS_DIR, filename)
    file.save(filepath)

    extracted_text = f"Attached document: {filename}\n\n"

    if filename.lower().endswith('.pdf'):
        try:
            import fitz  # lazy import — optional dependency
            with fitz.open(filepath) as doc:
                for page in doc:
                    extracted_text += page.get_text() + "\n"
        except ImportError:
            return jsonify({"error": "PyMuPDF not installed. Run: pip install PyMuPDF"}), 500
        except Exception as exc:
            return jsonify({"error": f"Failed to parse PDF: {exc}"}), 500
    else:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                extracted_text += f.read()
        except UnicodeDecodeError:
            return jsonify({"error": "File encoding not supported. Use UTF-8 text files."}), 400

    state.current_intuition = extracted_text
    state.add_log(f"Document '{filename}' uploaded and parsed successfully.")
    return jsonify({"success": True, "message": "Document loaded into ASTRA context.", "text": extracted_text})


# ═══════════════════════════════════════════════════════════════════
# Research-loop endpoints
# ═══════════════════════════════════════════════════════════════════

@app.route('/api/session/start', methods=['POST'])
def session_start():
    """Start a new depth-first research session with a macro question."""
    data = request.json or {}
    macro_question = (data.get('macro_question') or '').strip()
    if not macro_question:
        return jsonify({"error": "macro_question is required"}), 400

    if state.status not in ("IDLE",):
        return jsonify({"error": f"ASTRA is currently {state.status}. Stop it before starting a research session."}), 409

    heartbeat = int(data.get('heartbeat_interval', 5))
    providers  = data.get('providers', {})
    if providers:
        if 'conjecture' in providers:
            os.environ['ASTRA_CONJECTURE_PROVIDER'] = providers['conjecture']
        if 'translator' in providers:
            os.environ['ASTRA_TRANSLATOR_PROVIDER'] = providers['translator']
        if 'analyst' in providers:
            os.environ['ASTRA_ANALYST_PROVIDER'] = providers['analyst']
        if 'navigator' in providers:
            os.environ['ASTRA_NAVIGATOR_PROVIDER'] = providers['navigator']

    autonomous = bool(data.get('autonomous_mode', False))
    state.autonomous_mode = autonomous
    if autonomous:
        state.add_log("Autonomous mode ON: milestones will be auto-continued. Stops only when macro question is resolved.")

    session = ResearchSession(macro_question=macro_question, heartbeat_interval=heartbeat)
    state.research_session = session
    state.start_research_requested = True
    state.add_log(f"Research session '{session.session_id}' started.")
    return jsonify({"success": True, "session_id": session.session_id})


@app.route('/api/session/state')
def session_state():
    """Return the current research session state (thread, branches, milestones)."""
    if state.research_session is None:
        return jsonify({"session": None})
    return jsonify({
        "session": state.research_session.to_dict(),
        "navigator_proposal": state.navigator_proposal,
        "astra_status": state.status,
    })


@app.route('/api/session/continue', methods=['POST'])
def session_continue():
    """At a milestone: accept the navigator's proposed next direction and continue."""
    if state.status != "WAITING_DIRECTION":
        return jsonify({"error": "Not waiting for direction"}), 409
    state.continue_research_requested = True
    state.add_log("Human confirmed: continuing with navigator's direction.")
    return jsonify({"success": True})


@app.route('/api/session/redirect', methods=['POST'])
def session_redirect():
    """At a milestone: override with a human-provided direction."""
    data = request.json or {}
    direction = (data.get('direction') or '').strip()
    if not direction:
        return jsonify({"error": "direction is required"}), 400
    if state.status != "WAITING_DIRECTION":
        return jsonify({"error": "Not waiting for direction"}), 409
    state.redirect_direction          = direction
    state.redirect_research_requested = True
    state.add_log(f"Human redirected: {direction[:120]}")
    return jsonify({"success": True})


@app.route('/api/session/switch_branch', methods=['POST'])
def session_switch_branch():
    """At a milestone: activate a saved branch from the registry."""
    data = request.json or {}
    branch_id = (data.get('branch_id') or '').strip()
    if not branch_id:
        return jsonify({"error": "branch_id is required"}), 400
    if state.status != "WAITING_DIRECTION":
        return jsonify({"error": "Not waiting for direction"}), 409
    state.switch_branch_id = branch_id
    state.add_log(f"Human selected branch: {branch_id}")
    return jsonify({"success": True})


@app.route('/api/session/stop', methods=['POST'])
def session_stop():
    """Stop the active research session."""
    state.stop_requested = True
    state.add_log("Research session stop requested by user.")
    return jsonify({"success": True})


@app.route('/api/session/branches')
def session_branches():
    """List all pending branches in the registry."""
    if state.research_session is None:
        return jsonify({"branches": []})
    return jsonify({"branches": state.research_session.pending_branches()})


@app.route('/api/session/set_autonomous', methods=['POST'])
def session_set_autonomous():
    """Toggle autonomous mode on an active session."""
    data    = request.json or {}
    enabled = bool(data.get('enabled', False))
    state.autonomous_mode = enabled
    state.add_log(f"Autonomous mode {'enabled' if enabled else 'disabled'}.")
    return jsonify({"success": True, "autonomous_mode": enabled})


@app.route('/api/open_reports', methods=['POST'])
def open_reports():
    """Open the reports folder in the system file explorer (local desktop only)."""
    try:
        import subprocess
        subprocess.Popen(f'explorer "{REPORTS_DIR}"')
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify({"success": True})


_DEFAULT_AXIOMATIC_BASE = ""


def _save_investigation(name: str) -> str:
    os.makedirs(INVESTIGATIONS_DIR, exist_ok=True)
    inv_id  = datetime.now().strftime("%Y%m%d_%H%M%S")
    payload = {
        "id":           inv_id,
        "name":         name or f"Investigation {inv_id}",
        "saved_at":     datetime.now().isoformat(),
        "cycle_count":  state.cycle_count,
        "axiomatic_base": state.axiomatic_base,
        "reports":      state.reports,
    }
    path = os.path.join(INVESTIGATIONS_DIR, f"investigation_{inv_id}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    return inv_id


@app.route('/api/investigation/new', methods=['POST'])
def investigation_new():
    data = request.json or {}
    name = data.get('name', '').strip()
    if state.cycle_count > 0:
        _save_investigation(name)
    state.axiomatic_base             = _DEFAULT_AXIOMATIC_BASE
    state.cycle_count                = 0
    state.investigation_cycle_count  = 0
    state.current_cycle              = 0
    state.reports             = []
    state.current_conjecture  = ""
    state.last_python_code    = ""
    state.last_execution_result = {}
    state.last_analysis       = {}
    state.last_report         = {}
    with state._log_lock:
        state.logs.clear()
    state.save_state()
    state.add_log("New investigation started.")
    return jsonify({"success": True})


@app.route('/api/investigation/list')
def investigation_list():
    results = []
    for fname in sorted(os.listdir(INVESTIGATIONS_DIR), reverse=True):
        if not fname.endswith('.json'):
            continue
        try:
            with open(os.path.join(INVESTIGATIONS_DIR, fname), encoding="utf-8") as fh:
                d = json.load(fh)
            results.append({
                "id":            d.get("id", fname),
                "name":          d.get("name", "Untitled"),
                "saved_at":      d.get("saved_at", ""),
                "cycle_count":   d.get("cycle_count", 0),
                "theorems":      d.get("axiomatic_base", "").count("[ESTABLISHED THEOREM]"),
            })
        except Exception:
            pass
    return jsonify({"investigations": results})


@app.route('/api/investigation/load', methods=['POST'])
def investigation_load():
    data   = request.json or {}
    inv_id = data.get('id', '')
    path   = os.path.join(INVESTIGATIONS_DIR, f"investigation_{inv_id}.json")
    if not os.path.exists(path):
        return jsonify({"error": "Not found"}), 404
    with open(path, encoding="utf-8") as fh:
        inv = json.load(fh)
    state.axiomatic_base        = inv.get("axiomatic_base", _DEFAULT_AXIOMATIC_BASE)
    state.cycle_count           = inv.get("cycle_count", 0)
    state.current_cycle         = state.cycle_count
    state.reports               = inv.get("reports", [])
    state.current_conjecture    = ""
    state.last_python_code      = ""
    state.last_execution_result = {}
    state.last_analysis         = {}
    state.last_report           = {}
    with state._log_lock:
        state.logs.clear()
    state.save_state()
    state.add_log(f"Loaded: \"{inv.get('name')}\" — {state.cycle_count} cycles, {inv.get('axiomatic_base','').count('[ESTABLISHED THEOREM]')} theorems.")
    return jsonify({"success": True, "name": inv.get("name")})


@app.route('/api/investigation/delete', methods=['POST'])
def investigation_delete():
    data   = request.json or {}
    inv_id = data.get('id', '')
    path   = os.path.join(INVESTIGATIONS_DIR, f"investigation_{inv_id}.json")
    if os.path.exists(path):
        os.remove(path)
    return jsonify({"success": True})


PROVIDER_ENV_KEYS = {
    "GEMINI_API_KEY":     "Gemini Flash",
    "ANTHROPIC_API_KEY":  "Anthropic Claude",
    "OPENAI_API_KEY":     "OpenAI GPT-4o",
    "DEEPSEEK_API_KEY":   "DeepSeek R1",
    "XAI_API_KEY":        "xAI Grok 3",
    "DASHSCOPE_API_KEY":  "Qwen2.5-Math",
    "MISTRAL_API_KEY":    "Mistral / Codestral",
    "GROQ_API_KEY":       "Groq (Llama 3.3)",
}


@app.route('/api/config')
def get_config():
    from core.preflight import load_project_env
    load_project_env()

    def _mask(val):
        if not val:
            return ""
        return f"{val[:6]}...{val[-4:]}" if len(val) > 10 else "set"

    result = {}
    for env_key in PROVIDER_ENV_KEYS:
        val = os.environ.get(env_key, "")
        result[env_key] = {"set": bool(val), "masked": _mask(val)}
    for key in ("VERTEX_PROJECT", "VERTEX_LOCATION"):
        val = os.environ.get(key, "")
        result[key] = {"set": bool(val), "masked": val}
    return jsonify(result)


@app.route('/api/config/save', methods=['POST'])
def save_config():
    from core.preflight import load_project_env, _set_env_key
    data = request.json or {}
    saved = []
    for key, value in data.items():
        if isinstance(value, str) and value.strip():
            _set_env_key(key, value.strip())
            saved.append(key)
    if saved:
        load_project_env()
        state.add_log(f"API configuration updated: {', '.join(saved)}")
    return jsonify({"success": True, "saved": saved})


@app.route('/api/clear_logs', methods=['POST'])
def clear_logs():
    with state._log_lock:
        state.logs.clear()
    return jsonify({"success": True})


@app.route('/api/upload_asset', methods=['POST'])
def upload_asset():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if not file.filename:
        return jsonify({"error": "No file selected"}), 400

    filename = secure_filename(file.filename)
    filepath = os.path.join(ASSETS_DIR, filename)
    file.save(filepath)
    return jsonify({"success": True, "message": f"Asset '{filename}' saved."})


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5050, debug=False)
