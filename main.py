import os
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from werkzeug.utils import secure_filename
import io

from utils.gcs_client import GCSClient
from utils.ai_agent import AIAgent

app = Flask(__name__)
# More robust CORS configuration to handle all cases
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# Define the upload folder and ensure it exists
UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

try:
    gcs_client = GCSClient()
    ai_agent = AIAgent(gcs_client)
except Exception as e:
    print(f"Error initializing GCSClient or AIAgent: {e}")
    gcs_client = None
    ai_agent = None

# Hardcoded credentials for login
HARDCODED_CREDENTIALS = {
    "username": "admin",
    "password": "admin123"
}

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")

    if username == HARDCODED_CREDENTIALS["username"] and password == HARDCODED_CREDENTIALS["password"]:
        # In a real application, you would generate a proper JWT token here
        return jsonify({"token": "dummy-jwt-token"})
    else:
        return jsonify({"error": "Invalid credentials"}), 401

@app.route("/files", methods=["POST"])
def upload_file_locally():
    # Check for authorization header
    if 'Authorization' not in request.headers:
        return jsonify({"error": "Authorization header is missing"}), 401

    auth_header = request.headers.get('Authorization')
    # In a real app, you'd parse the token and verify it's valid
    if auth_header != 'Bearer dummy-jwt-token':
        return jsonify({"error": "Invalid token"}), 401

    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    if file:
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        return jsonify({"message": "File uploaded successfully"}), 200

@app.route("/list_folders", methods=["GET"])
def list_folders():
    if not gcs_client:
        return jsonify({"error": "GCS client not initialized"}), 500
    folders = gcs_client.list_folders()
    return jsonify({"folders": folders})

@app.route("/create_folder", methods=["POST"])
def create_folder():
    if 'Authorization' not in request.headers:
        return jsonify({"error": "Authorization header is missing"}), 401
    if not gcs_client:
        return jsonify({"error": "GCS client not initialized"}), 500
    
    data = request.get_json()
    folder_name = data.get("folderName")

    if not folder_name:
        return jsonify({"error": "Folder name is required"}), 400
    
    try:
        result = gcs_client.create_folder(folder_name)
        return jsonify({"message": result}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/delete_folder", methods=["DELETE"])
def delete_folder():
    if 'Authorization' not in request.headers:
        return jsonify({"error": "Authorization header is missing"}), 401
    if not gcs_client:
        return jsonify({"error": "GCS client not initialized"}), 500
    
    data = request.get_json()
    folder_names = data.get("folderNames")

    if not folder_names or not isinstance(folder_names, list):
        return jsonify({"error": "folderNames must be a non-empty list of strings."}), 400
    
    successes = []
    failures = []

    for name in folder_names:
        try:
            result = gcs_client.delete_folder(name)
            if "deleted" in result.lower():
                successes.append(result)
            else:
                failures.append(f"Failed to delete folder '{name}': {result}")
        except Exception as e:
            failures.append(f"Failed to delete folder '{name}': {str(e)}")

    if not failures:
        return jsonify({
            "message": f"Successfully deleted {len(successes)} folder(s).",
            "details": successes
        }), 200
    elif not successes:
        return jsonify({
            "message": "All folder deletions failed.",
            "details": failures
        }), 500
    else:
        return jsonify({
            "message": f"Completed with {len(failures)} failure(s) and {len(successes)} success(es).",
            "successes": successes,
            "failures": failures
        }), 207 # Multi-Status

@app.route("/list_files", methods=["GET"])
def list_files():
    if not gcs_client:
        return jsonify({"error": "GCS client not initialized"}), 500
    folder_name = request.args.get("folder")
    if not folder_name:
        return jsonify({"error": "Folder name is required"}), 400
    files = gcs_client.list_files(folder_name)
    return jsonify({"files": files})

@app.route("/upload_file", methods=["POST"])
def upload_file():
    if not gcs_client:
        return jsonify({"error": "GCS client not initialized"}), 500
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    folder = request.form.get("folder")
    if not folder:
        return jsonify({"error": "Folder name is required"}), 400
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    if file:
        result = gcs_client.upload_file(folder, file)
        return jsonify({"message": result})

@app.route("/download_file/<folder>/<file_name>", methods=["GET"])
def download_file(folder, file_name):
    if not gcs_client:
        return jsonify({"error": "GCS client not initialized"}), 500
    try:
        file_content = gcs_client.download_file(folder, file_name)
        return send_file(io.BytesIO(file_content), as_attachment=True, download_name=file_name)
    except Exception as e:
        return jsonify({"error": str(e)}), 404

@app.route("/delete_file", methods=["DELETE"])
def delete_file():
    if not gcs_client:
        return jsonify({"error": "GCS client not initialized"}), 500
    folder = request.args.get("folder")
    file_name = request.args.get("file_name")
    if not folder or not file_name:
        return jsonify({"error": "Folder and file name are required"}), 400
    result = gcs_client.delete_file(folder, file_name)
    return jsonify({"message": result})

@app.route("/edit_file", methods=["POST"])
def edit_file():
    if not gcs_client:
        return jsonify({"error": "GCS client not initialized"}), 500
    data = request.get_json()
    folder = data.get("folder")
    file_name = data.get("file_name")
    new_content = data.get("new_content")
    if not folder or not file_name or not new_content:
        return jsonify({"error": "Folder, file name, and new content are required"}), 400
    # In a real app, you should add checks for file type and permissions
    result = gcs_client.edit_file(folder, file_name, new_content)
    return jsonify({"message": result})

@app.route("/rename_file", methods=["POST"])
def rename_file():
    if not gcs_client:
        return jsonify({"error": "GCS client not initialized"}), 500
    data = request.get_json()
    folder = data.get("folder")
    old_file_name = data.get("old_file_name")
    new_file_name = data.get("new_file_name")

    if not all([folder, old_file_name, new_file_name]):
        return jsonify({"error": "Folder, old file name, and new file name are required"}), 400

    try:
        result = gcs_client.rename_file(folder, old_file_name, new_file_name)
        if "Error" in result:
             return jsonify({"error": result}), 404
        return jsonify({"message": result}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/chat", methods=["POST"])
def chat():
    if not ai_agent:
        return jsonify({"error": "AI Agent not initialized"}), 500
    data = request.get_json()
    message = data.get("message")
    if not message:
        return jsonify({"error": "Message is required"}), 400
    response = ai_agent.chat(message)
    return jsonify(response)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080, debug=True)
