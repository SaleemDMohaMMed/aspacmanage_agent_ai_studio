from google.cloud import storage
import os

class GCSClient:
    def __init__(self):
        # Define the path to the service account file
        service_account_path = 'service_account.json'
        
        # Explicitly use the service account credentials
        try:
            if not os.path.exists(service_account_path):
                raise FileNotFoundError(f"Service account file not found at {service_account_path}")
            self.client = storage.Client.from_service_account_json(service_account_path)
        except Exception as e:
            print(f"CRITICAL: Could not initialize GCSClient with service account. Error: {e}")
            # Fallback to default credentials if the service account file is not found or invalid
            self.client = storage.Client()
            
        # Use the correct bucket name provided by the user
        self.bucket_name = "storage_file_management"
        self.bucket = self.client.bucket(self.bucket_name)

    def list_folders(self):
        blobs = self.client.list_blobs(self.bucket_name)
        folders = set()
        for blob in blobs:
            if '/' in blob.name:
                # Extract the part before the first '/' which represents the folder
                folder_name = blob.name.split('/')[0] + '/'
                folders.add(folder_name)
        return sorted(list(folders))

    def list_files(self, folder_name):
        # Ensure the folder name ends with a '/' to avoid listing files from other folders with similar prefixes
        if not folder_name.endswith('/'):
            folder_name += '/'
        blobs = self.client.list_blobs(self.bucket_name, prefix=folder_name)
        # Strip the folder name from the beginning of the blob name for a cleaner list
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
        # Edit operation should create the file if it does not exist
        blob.upload_from_string(new_content)
        return f"File '{file_name}' in folder '{folder}' has been updated."
