import re
from utils.gcs_client import GCSClient

class AIAgent:
    def __init__(self, gcs_client: GCSClient):
        self.gcs_client = gcs_client

    def chat(self, message):
        try:
            message_lower = message.lower()

            # Intent: List files in a folder
            if "show me" in message_lower or "list" in message_lower or "show all" in message_lower:
                folder_match = re.search(r"(?:in|from|of)\s+(?:the\s+)?(?:folder\s+)?['\"]?([\w\._-]+)['\"]?", message_lower)
                if folder_match:
                    folder_name = folder_match.group(1)
                    files = self.gcs_client.list_files(folder_name)
                    if files:
                        return {"response": f"Here are the files in the '{folder_name}' folder: {', '.join(files)}", "intent": "list_files"}
                    else:
                        return {"response": f"The folder '{folder_name}' is empty or does not exist.", "intent": "list_files_empty"}

            # Intent: Rename a file
            elif "rename" in message_lower:
                rename_match = re.search(r"rename\s+['\"]?([\w\._-]+)['\"]?\s+to\s+['\"]?([\w\._-]+)['\"]?\s+in\s+(?:the\s+)?(?:folder\s+)?['\"]?([\w\._-]+)['\"]?", message_lower)
                if rename_match:
                    old_file_name = rename_match.group(1)
                    new_file_name = rename_match.group(2)
                    folder_name = rename_match.group(3)
                    result = self.gcs_client.rename_file(folder_name, old_file_name, new_file_name)
                    return {"response": result, "intent": "rename_file"}

            # Intent: Edit a file
            elif "edit" in message_lower or "update" in message_lower or "change" in message_lower:
                file_match = re.search(r"(?:file|document)\s+['\"]?([\w\._-]+)['\"]?", message_lower)
                folder_match = re.search(r"in\s+(?:folder\s+)?['\"]?([\w\._-]+)['\"]?", message_lower)
                content_match = re.search(r"to\s+(?:say|contain)\s+['\"]?(.+?)['\"]?$", message_lower)
                if file_match and folder_match and content_match:
                    file_name = file_match.group(1)
                    folder_name = folder_match.group(1)
                    new_content = content_match.group(1)
                    result = self.gcs_client.edit_file(folder_name, file_name, new_content)
                    return {"response": result, "intent": "edit_file"}

            # Intent: Upload a file (New and Improved!)
            elif "upload" in message_lower:
                parts = re.split(r" to | into ", message_lower)
                if len(parts) > 1:
                    last_part = parts[-1]
                    folder_match = re.search(r"(?:the\s+)?(?:folder\s+)?['\"]?([\w\._-]+)['\"]?", last_part)
                    if folder_match:
                        folder_name = folder_match.group(1)
                        response_message = f"Understood. I'm ready to accept a file for the '{folder_name}' folder. Please send your file in a POST request to the `/upload_file` endpoint."
                        return {"response": response_message, "intent": "upload_ready", "folder": folder_name}
                # Fallback if the split logic fails
                return {"response": "I can help with that. Please tell me which folder you'd like to upload to. For example: 'I want to upload a file to the images folder.'", "intent": "upload_request"}

            # Intent: Delete a file
            elif "delete" in message_lower or "remove" in message_lower:
                file_match = re.search(r"(?:the |a )?(?:file|video|image|document)\s+['\"]?([\w\._-]+)['\"]?", message_lower)
                folder_match = re.search(r"(?:from|in)\s+(?:the |a )?(?:folder\s+)?['\"]?([\w\._-]+)['\"]?", message_lower)
                if file_match and folder_match:
                    file_name = file_match.group(1)
                    folder_name = folder_match.group(1)
                    result = self.gcs_client.delete_file(folder_name, file_name)
                    return {"response": result, "intent": "delete_file"}

            # Fallback for unrecognized commands
            return {"response": "I'm sorry, I didn't understand that. I can help you list, edit, delete, and upload files from your cloud storage.", "intent": "fallback"}

        except Exception as e:
            # Basic error logging
            print(f"An error occurred in the AI agent: {e}")
            return {"response": "I'm sorry, something went wrong while processing your request.", "intent": "error"}
