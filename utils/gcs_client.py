import os
import json
from google.cloud import storage
from google.cloud import secretmanager
import google.auth
from datetime import datetime

class GCSClient:
    def __init__(self):
        # --- Secure Credential Loading ---
        if "K_SERVICE" in os.environ:
            print("Production environment detected. Loading credentials from Secret Manager.")
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
                print("Successfully initialized GCSClient from Secret Manager.")
            except Exception as e:
                print(f"CRITICAL: Failed to load credentials from Secret Manager. Error: {e}")
                self.client = storage.Client()
        else:
            print("Local environment detected. Loading credentials from service_account.json.")
            service_account_path = 'service_account.json'
            try:
                if not os.path.exists(service_account_path):
                    raise FileNotFoundError(f"Service account file not found at {service_account_path}")
                self.client = storage.Client.from_service_account_json(service_account_path)
                print("Successfully initialized GCSClient from local file.")
            except Exception as e:
                print(f"CRITICAL: Could not initialize GCSClient. Error: {e}")
                self.client = storage.Client()

        self.bucket_name = "storage_file_management"
        self.bucket = self.client.bucket(self.bucket_name)

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

        # Process pages to get prefixes (folders) and blobs (files)
        for page in iterator.pages:
            # The 'prefixes' attribute of a page contains the subdirectories.
            for p in page.prefixes:
                # Extract folder name from the full prefix
                folder_name = p[len(prefix):-1]
                if folder_name: # Ensure we don't add empty strings
                    folders.add(folder_name)
            
            # The items in the page iterator are the blobs (files).
            for blob in page:
                # A blob that is a "folder" placeholder will have the same name as the prefix.
                # We want to list files, not the folder itself.
                if blob.name != prefix:
                    # Extract file name from the full blob name
                    file_name = blob.name[len(prefix):]
                    if file_name: # Ensure we don't add empty strings
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

    # ... other methods remain unchanged ...
    def copy_folder(self, source_paths, destination_path):
        copied_folders = []
        for source_path in source_paths:
            source_path = source_path.strip('/') + '/'
            
            blobs = list(self.client.list_blobs(self.bucket_name, prefix=source_path))
            if not blobs:
                continue

            for blob in blobs:
                original_file_name = blob.name
                relative_path = os.path.relpath(original_file_name, source_path)
                
                if destination_path == '/':
                    destination_path = ''
                    
                destination_file_name = os.path.join(destination_path, os.path.basename(source_path.strip('/')), relative_path)
                
                new_blob = self.bucket.blob(destination_file_name)
                if new_blob.exists():
                    name, extension = os.path.splitext(destination_file_name)
                    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
                    destination_file_name = f"{name}_copy_{timestamp}{extension}"

                self.bucket.copy_blob(blob, self.bucket, destination_file_name)

            copied_folders.append(source_path.strip('/'))
        
        if not copied_folders:
            return "No folders were copied. Please check if the source paths exist and are not empty."
            
        return f"Folders {copied_folders} copied successfully to {destination_path or '/'}"


    def move_folder(self, source_paths, destination_path):
        moved_folders = []
        for source_path in source_paths:
            source_path = source_path.strip('/') + '/'

            self.copy_folder([source_path], destination_path)
            self.delete_folder(source_path)
            moved_folders.append(source_path.strip('/'))

        if not moved_folders:
            return "No folders were moved. Please check if the source paths exist."

        return f"Folders {moved_folders} moved successfully to {destination_path or '/'}"

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
        blob_name = os.path.join(folder, file_name)
        blob = self.bucket.blob(blob_name)
        if not blob.exists():
            raise FileNotFoundError(f"File {file_name} not found in {folder}")
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
