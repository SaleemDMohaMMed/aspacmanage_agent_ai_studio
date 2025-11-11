
from dotenv import load_dotenv
load_dotenv() # Load environment variables from .env file

import os
import logging
import sys
from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS
from werkzeug.utils import secure_filename
import io
import json

from utils.gcs_client import GCSClient
from utils.ai_agent import AIAgent

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# --- Constants ---
BASE_DIR = 'datastore/'

# --- Flask App Logger Configuration ---
log_file = 'app.log'
file_handler = logging.FileHandler(log_file)
file_handler.setLevel(logging.INFO)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)
app.logger.addHandler(file_handler)
app.logger.addHandler(console_handler)
app.logger.setLevel(logging.INFO)

UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

try:
    gcs_client = GCSClient()
    ai_agent = AIAgent(gcs_client)
except Exception as e:
    app.logger.error(f"Error initializing GCSClient or AIAgent: {e}")
    gcs_client = None
    ai_agent = None

def get_safe_path(user_path, is_file=False):
    """Create a secure, jailed path within BASE_DIR."""
    user_path = user_path.lstrip('/')
    full_path = os.path.join(BASE_DIR, user_path)
    safe_path = os.path.normpath(full_path)

    # For directories, ensure they end with a slash
    if not is_file and not safe_path.endswith('/'):
        safe_path += '/'
    
    # Security check to prevent traversal
    if not safe_path.startswith(os.path.normpath(BASE_DIR)):
        raise ValueError("Directory traversal attempt detected.")

    return safe_path

def create_api_response(user_path, gcs_path):
    """Helper to create a consistent API response for listing."""
    folders, files = gcs_client.list_folders(gcs_path)
    display_path = '/' if user_path == '/' else user_path.strip('/') + '/'

    response_data = {
        "status": "success",
        "path": display_path,
        "folders": folders,
        "files": files
    }

    if not folders and not files:
        response_data["status"] = "empty"
        response_data["message"] = f"No folders or files found in this path: {display_path}"

    return jsonify(response_data), 200

@app.route("/list_files", methods=["GET"])
def list_files():
    if not gcs_client: return jsonify({"error": "GCS client not initialized"}), 500
    user_path = request.args.get('folder', '/')
    try:
        safe_gcs_path = get_safe_path(user_path)
        if not gcs_client.folder_exists(safe_gcs_path):
            return jsonify({"error": f"Folder not found: {user_path}"}), 404
        return create_api_response(user_path, safe_gcs_path)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500

@app.route("/list_folders", methods=["GET"])
def list_folders_and_files():
    return list_files()

@app.route("/create_folder", methods=["POST"])
def create_folder():
    if not gcs_client: return jsonify({"error": "GCS client not initialized"}), 500
    data = request.get_json()
    folder_name = data.get("folderName")
    if not folder_name: return jsonify({"error": "Folder name is required"}), 400
    try:
        safe_path = get_safe_path(folder_name)
        result = gcs_client.create_folder(safe_path)
        return jsonify({"message": result}), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/delete_folder", methods=["DELETE"])
def delete_folder():
    if not gcs_client: return jsonify({"error": "GCS client not initialized"}), 500
    data = request.get_json()
    folder_names = data.get("folderNames")
    if not folder_names or not isinstance(folder_names, list):
        return jsonify({"error": "folderNames must be a list"}), 400
    
    successes, failures = [], []
    for name in folder_names:
        try:
            safe_path = get_safe_path(name)
            result = gcs_client.delete_folder(safe_path)
            successes.append(result)
        except Exception as e:
            failures.append(f"Failed to delete '{name}': {e}")
            
    if not failures:
        return jsonify({"message": f"Successfully deleted {len(successes)} folder(s)."}), 200
    else:
        return jsonify({"message": "Some deletions failed.", "successes": successes, "failures": failures}), 207

@app.route("/upload", methods=["POST"])
def upload_files():
    if not gcs_client: return jsonify({"error": "GCS client not initialized"}), 500
    files = request.files.getlist("files[]")
    paths = request.form.getlist("paths[]")
    if not files or not paths or len(files) != len(paths):
        return jsonify({"error": "Invalid files or paths provided"}), 400

    success_files, error_files = [], []
    for i, file in enumerate(files):
        try:
            # The path from the client includes the filename, so separate it
            folder, filename = os.path.split(paths[i])
            safe_folder_path = get_safe_path(folder)
            result = gcs_client.upload_file(safe_folder_path, file)
            success_files.append({"filename": file.filename, "message": result})
        except Exception as e:
            error_files.append({"filename": file.filename, "error": str(e)})

    if error_files:
        return jsonify({"message": "Upload completed with errors", "success_files": success_files, "error_files": error_files}), 207
    return jsonify({"message": "All files uploaded successfully", "success_files": success_files}), 201
    
@app.route("/download_file/<path:file_path>", methods=["GET"])
def download_file(file_path):
    if not gcs_client: return jsonify({"error": "GCS client not initialized"}), 500
    try:
        safe_file_path = get_safe_path(file_path, is_file=True)
        folder = os.path.dirname(safe_file_path) + '/'
        file_name = os.path.basename(safe_file_path)
        
        file_content = gcs_client.download_file(folder, file_name)
        return send_file(io.BytesIO(file_content), as_attachment=True, download_name=file_name)
    except Exception as e:
        return jsonify({"error": f"Error downloading file: {e}"}), 404

@app.route("/delete_file", methods=["DELETE", "OPTIONS"])
def delete_file_by_param():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200
    if not gcs_client:
        return jsonify({"error": "GCS client not initialized"}), 500

    folder = request.args.get("folder")
    file_name = request.args.get("file_name")

    if not all([folder, file_name]):
        return jsonify({"error": "folder and file_name parameters are required"}), 400

    try:
        safe_folder_path = get_safe_path(folder)
        result = gcs_client.delete_file(safe_folder_path, file_name)
        return jsonify({"message": result}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/delete_files", methods=["DELETE", "OPTIONS"])
def delete_files():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200
    if not gcs_client:
        return jsonify({"error": "GCS client not initialized"}), 500
    data = request.get_json()
    filenames = data.get("filenames")
    if not filenames or not isinstance(filenames, list):
        return jsonify({"error": "filenames must be a list"}), 400
    successes, failures = [], []
    for filename in filenames:
        try:
            safe_path = get_safe_path(filename, is_file=True)
            folder = os.path.dirname(safe_path) + '/'
            file_to_delete = os.path.basename(safe_path)
            result = gcs_client.delete_file(folder, file_to_delete)
            successes.append(result)
        except Exception as e:
            failures.append(f"Failed to delete '{filename}': {str(e)}")
    if not failures:
        return jsonify({"message": f"Successfully deleted {len(successes)} file(s)."}), 200
    else:
        return jsonify({"message": "Some deletions failed.", "successes": successes, "failures": failures}), 207

@app.route("/rename_file", methods=["POST"])
def rename_pyw_file():
    if not gcs_client: return jsonify({"error": "GCS client not initialized"}), 500
    data = request.get_json()
    folder = data.get("folder")
    old_file_name = data.get("old_file_name")
    new_file_name = data.get("new_file_name")
    if not all([folder, old_file_name, new_file_name]):
        return jsonify({"error": "Folder, old_file_name, and new_file_name are required"}), 400
    try:
        safe_folder_path = get_safe_path(folder)
        result = gcs_client.rename_file(safe_folder_path, old_file_name, new_file_name)
        return jsonify({"message": result}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/copyFolder", methods=["POST"])
def copy_folder():
    if not gcs_client:
        return jsonify({"error": "GCS client not initialized"}), 500
    data = request.get_json()
    source_paths = data.get("sourcePaths")
    destination_path = data.get("destinationPath")

    if not all([source_paths, destination_path]):
        return jsonify({"error": "source_paths and destination_path are required"}), 400
    if not isinstance(source_paths, list):
        return jsonify({"error": "source_paths must be a list"}), 400

    try:
        safe_dest_path = get_safe_path(destination_path)
        safe_source_paths = [get_safe_path(src) for src in source_paths]
        
        # Prevent copying a folder into itself
        for src_path in safe_source_paths:
            if src_path in safe_dest_path:
                 return jsonify({"error": f"Cannot copy a folder into itself or a subfolder: {src_path} -> {destination_path}"}), 400

        copied_details = gcs_client.copy_folder(safe_source_paths, safe_dest_path)
        
        if not copied_details:
            return jsonify({"message": "No folders or files were copied. Source may be empty or not found."}), 404

        return jsonify({
            "message": f"Successfully copied {len(copied_details)} folder(s).",
            "details": copied_details
        }), 200

    except Exception as e:
        app.logger.error(f"Error during folder copy: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/moveFolder", methods=["POST"])
def move_folder():
    if not gcs_client:
        return jsonify({"error": "GCS client not initialized"}), 500
    data = request.get_json()
    source_paths = data.get("sourcePaths")
    destination_path = data.get("destinationPath")

    if not all([source_paths, destination_path]):
        return jsonify({"error": "source_paths and destination_path are required"}), 400
    if not isinstance(source_paths, list):
        return jsonify({"error": "source_paths must be a list"}), 400

    try:
        safe_dest_path = get_safe_path(destination_path)
        safe_source_paths = [get_safe_path(src) for src in source_paths]
        
        # Prevent moving a folder into itself
        for src_path in safe_source_paths:
            if src_path in safe_dest_path:
                 return jsonify({"error": f"Cannot move a folder into itself or a subfolder: {src_path} -> {destination_path}"}), 400

        moved_details = gcs_client.move_folder(safe_source_paths, safe_dest_path)

        if not moved_details:
            return jsonify({"message": "No folders or files were moved. Source may be empty or not found."}), 404

        return jsonify({
            "message": f"Successfully moved {len(moved_details)} folder(s).",
            "details": moved_details
        }), 200
        
    except Exception as e:
        app.logger.error(f"Error during folder move: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080, debug=True)
