import os
import threading
import sys
from flask import Flask, render_template, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename

# Allow imports from project root
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from core.state import state
from core.research_session import ResearchSession
from main import start_background_loop

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB

UPLOADS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "workspace", "uploads")
ASSETS_DIR  = os.path.join(os.path.dirname(os.path.dirname(__file__)), "workspace", "assets")
REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "workspace", "reports")
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(ASSETS_DIR,  exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)

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
    return jsonify({"success": True, "message": "Document loaded into ASTRA context."})


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
