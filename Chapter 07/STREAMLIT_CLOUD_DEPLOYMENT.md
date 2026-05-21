# Streamlit Cloud Deployment Guide

This app can be shared with your manager and team by hosting it on Streamlit Community Cloud from a GitHub repository.

## 1. Prepare Google Drive

1. Open Google Drive.
2. Create a folder named `Failure Detection Uploads`.
3. Copy the folder ID from the folder URL.
   - Example URL: `https://drive.google.com/drive/folders/FOLDER_ID_HERE`
4. Create a Google Cloud service account.
5. Enable the Google Drive API for that Google Cloud project.
6. Create a JSON key for the service account.
7. Share the `Failure Detection Uploads` Drive folder with the service account email.
   - The email usually ends with `iam.gserviceaccount.com`.
   - Give it Editor access.

## 2. Push The App To GitHub

Your repository should include at least:

```text
streamlit_app.py
requirements.txt
.gitignore
STREAMLIT_CLOUD_DEPLOYMENT.md
```

Do not upload `.venv`, `uploads`, or `.streamlit/secrets.toml` to GitHub.

## 3. Deploy On Streamlit Cloud

1. Go to Streamlit Community Cloud.
2. Select your GitHub repository.
3. Set the main file path to:

```text
streamlit_app.py
```

4. Open the app settings and add secrets.

## 4. Add Streamlit Secrets

Paste this structure into Streamlit Cloud secrets, replacing the values with your Google service account JSON values and Drive folder ID:

```toml
[gdrive]
folder_id = "YOUR_GOOGLE_DRIVE_FOLDER_ID"

[gdrive_service_account]
type = "service_account"
project_id = "YOUR_PROJECT_ID"
private_key_id = "YOUR_PRIVATE_KEY_ID"
private_key = """-----BEGIN PRIVATE KEY-----
YOUR_PRIVATE_KEY
-----END PRIVATE KEY-----"""
client_email = "YOUR_SERVICE_ACCOUNT_EMAIL"
client_id = "YOUR_CLIENT_ID"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "YOUR_CLIENT_CERT_URL"
universe_domain = "googleapis.com"
```

After deployment, share the Streamlit Cloud app URL with your manager and team.
