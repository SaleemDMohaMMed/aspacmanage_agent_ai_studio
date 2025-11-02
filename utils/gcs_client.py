import os
import json
import logging
from google.cloud import storage
from google.cloud import secretmanager
import google.auth
from datetime import datetime

class GCSClient:
    def __init__(self):
        # --- Logging Setup ---
        self.logger = logging.getLogger(__name__)

        # --- Secure Credential Loading ---
        if "K_SERVICE" in os.environ:
            self.logger.info("Production environment detected. Loading credentials from Secret Manager.")
            try:
                _, project_id = google.auth.default()
                secret_id = "service_account_json"
                version_id = "latest"
                name = f"projects/{project_id}/secrets/{secret_id}/versions/{version_id}"
                client = secretmanager.SecretManagerServiceClient()
                response = client.access_secret_version(request={"name": name})
                secret_payload = response.payload.data.decode("UTF-8")
                credentials_info = json.loads(secret_payload)
                self.client = storage.Client.from_service_account_info(credentials_info)
                self.logger.info("Successfully initialized GCSClient from Secret Manager.")
            except Exception as e:
                self.logger.critical(f"Failed to load credentials from Secret Manager. Error: {e}")
                self.client = storage.Client()
        else:
            self.logger.info("Local environment detected. Loading credentials from service_account.json.")
            service_account_path = 'service_account.json'
            try:
                if not os.path.exists(service_account_path):
                    raise FileNotFoundError(f"Service account file not found at {service_account_path}")
                self.client = storage.Client.from_service_account_json(service_account_path)
                self.logger.info("Successfully initialized GCSClient from local file.")
            except Exception as e:
                self.logger.critical(f"Could not initialize GCSClient. Error: {e}")
                self.client = storage.Client()

        self.bucket_name = "storage_file_management"
        self.bucket = self.client.bucket(self.bucket_name)

    def _transfer_folder(self, source_path, destination_path, delete_source=False):
        source_path = source_path.strip('/') + '/'
        blobs = list(self.client.list_blobs(self.bucket_name, prefix=source_path))
        if not blobs:
            return None, None

        files_transferred = []
        source_folder_name = os.path.basename(source_path.strip('/'))
        destination_folder_base = os.path.join(destination_path, source_folder_name)
        if not destination_folder_base.endswith('/'):
            destination_folder_base += '/'

        for blob in blobs:
            if blob.name == source_path:
                continue

            relative_path = blob.name[len(source_path):]
            destination_blob_name = os.path.join(destination_folder_base, relative_path)
            
            new_blob = self.bucket.blob(destination_blob_name)
            if new_blob.exists():
                name, extension = os.path.splitext(destination_blob_name)
                timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
                destination_blob_name = f"{name}_copy_{timestamp}{extension}"

            self.bucket.copy_blob(blob, self.bucket, destination_blob_name)
            files_transferred.append(relative_path)

        # Ensure the destination folder exists, especially for empty source folders
        dest_blob = self.bucket.blob(destination_folder_base)
        if not dest_blob.exists():
            dest_blob.upload_from_string('')

        if delete_source:
            for blob in blobs:
                blob.delete()

        return destination_folder_base, files_transferred

    def list_folders(self, folder_path):
        """
        Lists folders and files for a given path in a GCS bucket using the pages iterator.
        """
        prefix = folder_path if folder_path else ''
        if prefix and not prefix.endswith('/'):
            prefix += '/'
        if prefix == '/': # Treat '/' as root
            prefix = ''

        iterator = self.client.list_blobs(self.bucket_name, prefix=prefix, delimiter='/')
        
        folders = set()
        files = set()

        for page in iterator.pages:
            for p in page.prefixes:
                folder_name = p[len(prefix):-1]
                if folder_name:
                    folders.add(folder_name)
            
            for blob in page:
                if blob.name != prefix:
                    file_name = blob.name[len(prefix):]
                    if file_name and not file_name.endswith('/'):
                        files.add(file_name)

        return sorted(list(folders)), sorted(list(files))

    def create_folder(self, folder_name):
        if not folder_name.endswith('/'):
            folder_name += '/'
        blob = self.bucket.blob(folder_name)
        if blob.exists():
            return f"Folder '{folder_name}' already exists."
        blob.upload_from_string('')
        return f"Folder '{folder_name}' created successfully."

    def delete_folder(self, folder_name):
        if not folder_name.endswith('/'):
            folder_name += '/'
        
        blobs_to_delete = list(self.client.list_blobs(self.bucket_name, prefix=folder_name))
        
        if not blobs_to_delete:
            return f"Folder '{folder_name}' not found or is already empty."

        for blob in blobs_to_delete:
            blob.delete()
            
        return f"Folder '{folder_name}' and all its contents have been deleted."

    def upload_file(self, folder, file):
        if not folder or folder == '/':
            folder_path = ''
        else:
            folder_path = folder.strip('/')

        # Use os.path.join to correctly handle path construction
        blob_name = os.path.join(folder_path, file.filename)
        
        blob = self.bucket.blob(blob_name)
        blob.upload_from_file(file)
        return f"File {file.filename} uploaded to {folder_path or '/'}"

    def copy_folder(self, source_paths, destination_path):
        copied_folders_details = []
        for source_path in source_paths:
            destination_folder_name, files_copied = self._transfer_folder(source_path, destination_path)
            if files_copied:
                copied_folders_details.append({
                    "source": source_path,
                    "destination": destination_folder_name,
                    "files_copied": files_copied
                })
        
        return copied_folders_details


    def move_folder(self, source_paths, destination_path):
        moved_folders_details = []
        for source_path in source_paths:
            destination_folder_name, files_moved = self._transfer_folder(source_path, destination_path, delete_source=True)
            if files_moved:
                moved_folders_details.append({
                    "source": source_path,
                    "destination": destination_folder_name,
                    "files_moved": files_moved
                })
        
        return moved_folders_details


    def list_files(self, folder_name):
        if folder_name == '/':
            folder_name = ''
            
        if folder_name and not folder_name.endswith('/'):
            folder_name += '/'
            
        blobs = self.client.list_blobs(self.bucket_name, prefix=folder_name)
        
        files = []
        for blob in blobs:
            if blob.name == folder_name:
                continue
            
            relative_path = os.path.relpath(blob.name, folder_name)
            
            if blob.name.endswith('/') and not relative_path.endswith('/'):
                relative_path += '/'

            files.append(relative_path)
            
        return files

    def download_file(self, folder, file_name):
        self.logger.info(f"--- GCSClient: download_file called with folder: '{folder}', file_name: '{file_name}' ---")
        folder_path = folder.strip('/')
        self.logger.info(f"Sanitized folder_path: '{folder_path}'")
        blob_name = os.path.join(folder_path, file_name)
        self.logger.info(f"Attempting to access blob: '{blob_name}'")
        blob = self.bucket.blob(blob_name)
        if not blob.exists():
            self.logger.error(f"Blob '{blob_name}' does not exist.")
            raise FileNotFoundError(f"File '{file_name}' not found in folder '{folder}'")
        self.logger.info(f"Blob '{blob_name}' found. Downloading...")
        return blob.download_as_bytes()

    def delete_file(self, folder, file_name):
        blob_name = os.path.join(folder, file_name)
        blob = self.bucket.blob(blob_name)
        if blob.exists():
            blob.delete()
            return f"File '{file_name}' in folder '{folder}' has been deleted."
        else:
            return f"File '{file_name}' not found in folder '{folder}'."

    def edit_file(self, folder, file_name, new_content):
        blob_name = os.path.join(folder, file_name)
        blob = self.bucket.blob(blob_name)
        blob.upload_from_string(new_content)
        return f"File '{file_name}' in folder '{folder}' has been updated."

    def rename_file(self, folder, old_file_name, new_file_name):
        source_blob_name = os.path.join(folder, old_file_name)
        new_blob_name = os.path.join(folder, new_file_name)

        source_blob = self.bucket.blob(source_blob_name)

        if not source_blob.exists():
            return f"Error: Source file '{old_file_name}' not found in folder '{folder}'."
        
        if old_file_name == new_file_name:
            return f"File '{old_file_name}' already has the desired name."
        
        new_blob = self.bucket.rename_blob(source_blob, new_name=new_blob_name)
        
        if new_blob.exists():
            return f"File '{old_file_name}' was successfully renamed to '{new_file_name}' in folder '{folder}'."
        else:
            return f"An unexpected error occurred while renaming the file."