import os
import threading
from flask import Flask, render_template, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
import fitz  # PyMuPDF

# Import ASTRA core
import sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from core.state import state
from main import start_background_loop

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB max

# Setup folders
UPLOADS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "workspace", "uploads")
ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "workspace", "assets")
REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "workspace", "reports")
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(ASSETS_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)

# Start background ASTRA loop
threading.Thread(target=start_background_loop, daemon=True).start()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/state')
def get_state():
    return jsonify(state.get_state_dict())

@app.route('/api/start', methods=['POST'])
def start_loop():
    data = request.json
    intuition = data.get('intuition', '')
    if intuition:
        state.current_intuition = intuition
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
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
        
    filename = secure_filename(file.filename)
    filepath = os.path.join(UPLOADS_DIR, filename)
    file.save(filepath)
    
    # Extract text if PDF
    extracted_text = f"Attached document: {filename}\n\n"
    if filename.lower().endswith('.pdf'):
        try:
            with fitz.open(filepath) as doc:
                for page in doc:
                    extracted_text += page.get_text() + "\n"
        except Exception as e:
            return jsonify({"error": f"Failed to parse PDF: {str(e)}"}), 500
    else:
        # Assuming text file
        with open(filepath, 'r', encoding='utf-8') as f:
            extracted_text += f.read()
            
    # Set as intuition
    state.current_intuition = extracted_text
    state.add_log(f"Document {filename} uploaded and parsed successfully.")
    
    return jsonify({"success": True, "message": "Document loaded into ASTRA context."})

@app.route('/api/upload_asset', methods=['POST'])
def upload_asset():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
        
    filename = secure_filename(file.filename)
    filepath = os.path.join(ASSETS_DIR, filename)
    file.save(filepath)
    
    return jsonify({"success": True, "message": f"Asset {filename} saved for OS Agent."})

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5050, debug=False)
