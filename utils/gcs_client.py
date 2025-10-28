import os
import json
from google.cloud import storage
from google.cloud import secretmanager
import google.auth

class GCSClient:
    def __init__(self):
        # --- Secure Credential Loading ---
        # Check if running in a Google Cloud environment (like Cloud Run)
        if "K_SERVICE" in os.environ:
            print("Production environment detected. Loading credentials from Secret Manager.")
            try:
                # 1. Get Project ID from the environment
                _, project_id = google.auth.default()
                
                # 2. Build the secret name
                secret_id = "service_account_json"
                version_id = "latest"
                name = f"projects/{project_id}/secrets/{secret_id}/versions/{version_id}"

                # 3. Access the secret
                client = secretmanager.SecretManagerServiceClient()
                response = client.access_secret_version(request={"name": name})
                secret_payload = response.payload.data.decode("UTF-8")
                credentials_info = json.loads(secret_payload)

                # 4. Initialize Storage Client from the secret
                self.client = storage.Client.from_service_account_info(credentials_info)
                print("Successfully initialized GCSClient from Secret Manager.")

            except Exception as e:
                print(f"CRITICAL: Failed to load credentials from Secret Manager. Error: {e}")
                # Fallback to default credentials which rely on the runtime's service account
                self.client = storage.Client()
        else:
            # --- Local Development ---
            print("Local environment detected. Loading credentials from service_account.json.")
            service_account_path = 'service_account.json'
            try:
                if not os.path.exists(service_account_path):
                    raise FileNotFoundError(f"Service account file not found at {service_account_path}")
                
                self.client = storage.Client.from_service_account_json(service_account_path)
                print("Successfully initialized GCSClient from local file.")

            except Exception as e:
                print(f"CRITICAL: Could not initialize GCSClient with local service account. Error: {e}")
                # Fallback for local development
                self.client = storage.Client()

        # --- Bucket Configuration ---
        self.bucket_name = "storage_file_management"
        self.bucket = self.client.bucket(self.bucket_name)

    def list_folders(self):
        blobs = self.client.list_blobs(self.bucket_name)
        folders = set()
        for blob in blobs:
            if '/' in blob.name:
                folder_name = blob.name.split('/')[0] + '/'
                folders.add(folder_name)
        return sorted(list(folders))

    def create_folder(self, folder_name):
        # In GCS, folders are just empty objects with a trailing '/'
        if not folder_name.endswith('/'):
            folder_name += '/'
        blob = self.bucket.blob(folder_name)
        if blob.exists():
            return f"Folder '{folder_name}' already exists."
        blob.upload_from_string('')
        return f"Folder '{folder_name}' created successfully."

    def delete_folder(self, folder_name):
        """Deletes a 'folder' and all its contents from GCS."""
        if not folder_name.endswith('/'):
            folder_name += '/'
        
        # List all blobs with the given prefix
        blobs_to_delete = list(self.client.list_blobs(self.bucket_name, prefix=folder_name))
        
        if not blobs_to_delete:
            return f"Folder '{folder_name}' not found or is already empty."

        # Delete each blob found
        for blob in blobs_to_delete:
            blob.delete()
            
        return f"Folder '{folder_name}' and all its contents have been deleted."

    def list_files(self, folder_name):
        if not folder_name.endswith('/'):
            folder_name += '/'
        blobs = self.client.list_blobs(self.bucket_name, prefix=folder_name)
        return [blob.name[len(folder_name):] for blob in blobs if blob.name != folder_name]

    def upload_file(self, folder, file):
        if not folder:
            raise ValueError("Folder name cannot be empty.")
        blob_name = f"{folder}/{file.filename}"
        blob = self.bucket.blob(blob_name)
        blob.upload_from_file(file)
        return f"File {file.filename} uploaded to {folder}."

    def download_file(self, folder, file_name):
        blob_name = f"{folder}/{file_name}"
        blob = self.bucket.blob(blob_name)
        if not blob.exists():
            raise FileNotFoundError(f"File {file_name} not found in {folder}")
        return blob.download_as_bytes()

    def delete_file(self, folder, file_name):
        blob_name = f"{folder}/{file_name}"
        blob = self.bucket.blob(blob_name)
        if blob.exists():
            blob.delete()
            return f"File '{file_name}' in folder '{folder}' has been deleted."
        else:
            return f"File '{file_name}' not found in folder '{folder}'."

    def edit_file(self, folder, file_name, new_content):
        blob_name = f"{folder}/{file_name}"
        blob = self.bucket.blob(blob_name)
        blob.upload_from_string(new_content)
        return f"File '{file_name}' in folder '{folder}' has been updated."

    def rename_file(self, folder, old_file_name, new_file_name):
        """Renames a file within a given folder in GCS."""
        source_blob_name = f"{folder}/{old_file_name}"
        new_blob_name = f"{folder}/{new_file_name}"

        source_blob = self.bucket.blob(source_blob_name)

        if not source_blob.exists():
            return f"Error: Source file '{old_file_name}' not found in folder '{folder}'."
        
        if old_file_name == new_file_name:
            return f"File '{old_file_name}' already has the desired name."
        
        # rename_blob handles the copy and delete atomically
        new_blob = self.bucket.rename_blob(source_blob, new_name=new_blob_name)
        
        if new_blob.exists():
            return f"File '{old_file_name}' was successfully renamed to '{new_file_name}' in folder '{folder}'."
        else:
            return f"An unexpected error occurred while renaming the file."
