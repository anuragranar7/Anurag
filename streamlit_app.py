import streamlit as st
import pandas as pd
import os
import hmac
import re
import time
from collections import Counter
from io import BytesIO
from datetime import datetime
import plotly.express as px

# =========================
# CONFIGURATION
# =========================

st.set_page_config(
    page_title="Failure Detection System",
    page_icon="🔍",
    layout="wide"
)

LOCAL_UPLOAD_DIR = "uploads"
GOOGLE_DRIVE_UPLOAD_FOLDER = "Failure Detection Uploads"
GOOGLE_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def get_upload_dir():
    custom_dir = os.environ.get("FAILURE_APP_UPLOAD_DIR")

    candidates = []

    if custom_dir:
        candidates.append(custom_dir)

    user_home = os.path.expanduser("~")

    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        candidates.append(
            os.path.join(
                f"{letter}:\\",
                "My Drive",
                GOOGLE_DRIVE_UPLOAD_FOLDER
            )
        )

    candidates.extend([
        os.path.join(
            user_home,
            "Google Drive",
            GOOGLE_DRIVE_UPLOAD_FOLDER
        ),
        os.path.join(
            user_home,
            "My Drive",
            GOOGLE_DRIVE_UPLOAD_FOLDER
        ),
        os.path.join(
            user_home,
            "GoogleDrive",
            GOOGLE_DRIVE_UPLOAD_FOLDER
        ),
    ])

    for upload_dir in candidates:
        parent_dir = os.path.dirname(upload_dir)

        if parent_dir and os.path.exists(parent_dir):
            os.makedirs(upload_dir, exist_ok=True)
            return upload_dir

    os.makedirs(LOCAL_UPLOAD_DIR, exist_ok=True)
    return LOCAL_UPLOAD_DIR


UPLOAD_DIR = get_upload_dir()


def get_secret_section(section_name):
    try:
        return st.secrets[section_name]
    except (FileNotFoundError, KeyError, AttributeError):
        return None


def get_secret_value(key):
    try:
        return st.secrets.get(key)
    except (FileNotFoundError, AttributeError):
        return None


def get_auth_config():
    auth_settings = get_secret_section("auth")

    if auth_settings:
        username = auth_settings.get("username")
        password = auth_settings.get("password")

        if username and password:
            return username, password

    username = get_secret_value("AUTH_USERNAME")
    password = get_secret_value("AUTH_PASSWORD")

    if username and password:
        return username, password

    username = get_secret_value("username")
    password = get_secret_value("password")

    if username and password:
        return username, password

    username = get_secret_value("USERNAME")
    password = get_secret_value("PASSWORD")

    if username and password:
        return username, password

    return (
        os.environ.get("FAILURE_APP_USERNAME"),
        os.environ.get("FAILURE_APP_PASSWORD")
    )


def credentials_are_valid(username, password):
    expected_username, expected_password = get_auth_config()

    if not expected_username or not expected_password:
        return False

    return (
        hmac.compare_digest(username, expected_username)
        and hmac.compare_digest(password, expected_password)
    )


def require_login():
    if st.session_state.get("authenticated"):
        with st.sidebar:
            if st.button("Log out"):
                st.session_state["authenticated"] = False
                st.rerun()
        return True

    st.title("Failure Detection & Analysis System")
    st.subheader("Login")

    expected_username, expected_password = get_auth_config()

    if not expected_username or not expected_password:
        st.error(
            "Login is not configured. Add username and password in "
            "Streamlit secrets before sharing this app."
        )
        st.info(
            "Use [auth] username/password, AUTH_USERNAME/AUTH_PASSWORD, "
            "or username/password in Streamlit secrets, then reboot the app."
        )
        st.stop()

    with st.form("login_form"):
        username = st.text_input("User ID")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")

    if submitted:
        if credentials_are_valid(username, password):
            st.session_state["authenticated"] = True
            st.rerun()

        st.error("Invalid user ID or password.")

    st.stop()


def get_google_drive_config():
    service_account = get_secret_section("gdrive_service_account")
    gdrive_settings = get_secret_section("gdrive")

    if not service_account or not gdrive_settings:
        return None, None

    folder_id = gdrive_settings.get("folder_id")

    if not folder_id:
        return None, None

    return dict(service_account), folder_id


def get_google_drive_service():
    service_account, folder_id = get_google_drive_config()

    if not service_account or not folder_id:
        return None, None

    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build

        credentials = Credentials.from_service_account_info(
            service_account,
            scopes=GOOGLE_DRIVE_SCOPES
        )

        drive_service = build(
            "drive",
            "v3",
            credentials=credentials,
            cache_discovery=False
        )

        return drive_service, folder_id

    except Exception as e:
        st.warning(f"Google Drive connection failed: {e}")
        return None, None


def upload_file_to_google_drive(file_path, file_name):
    drive_service, folder_id = get_google_drive_service()

    if not drive_service or not folder_id:
        return None

    try:
        from googleapiclient.http import MediaFileUpload

        metadata = {
            "name": file_name,
            "parents": [folder_id],
        }

        media = MediaFileUpload(
            file_path,
            mimetype=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
            resumable=False
        )

        uploaded = (
            drive_service.files()
            .create(
                body=metadata,
                media_body=media,
                fields="id, webViewLink"
            )
            .execute()
        )

        return uploaded

    except Exception as e:
        st.warning(f"Google Drive upload failed for {file_name}: {e}")
        return None


def list_google_drive_files():
    drive_service, folder_id = get_google_drive_service()

    if not drive_service or not folder_id:
        return []

    try:
        query = (
            f"'{folder_id}' in parents and trashed = false "
            "and name contains '.xlsx'"
        )

        response = (
            drive_service.files()
            .list(
                q=query,
                fields="files(id, name, modifiedTime)",
                orderBy="modifiedTime desc"
            )
            .execute()
        )

        return response.get("files", [])

    except Exception as e:
        st.warning(f"Could not list Google Drive files: {e}")
        return []


def download_google_drive_file(file_id, file_name):
    drive_service, _ = get_google_drive_service()

    if not drive_service:
        return None

    try:
        from googleapiclient.http import MediaIoBaseDownload

        path = os.path.join(UPLOAD_DIR, file_name)
        request = drive_service.files().get_media(fileId=file_id)

        with open(path, "wb") as f:
            downloader = MediaIoBaseDownload(f, request)
            done = False

            while not done:
                _, done = downloader.next_chunk()

        return path

    except Exception as e:
        st.warning(f"Could not download {file_name} from Google Drive: {e}")
        return None


def delete_google_drive_file(file_name):
    drive_service, _ = get_google_drive_service()

    if not drive_service:
        return False

    try:
        for file_info in list_google_drive_files():
            if file_info.get("name") == file_name:
                drive_service.files().delete(
                    fileId=file_info["id"]
                ).execute()
                return True

    except Exception as e:
        st.warning(f"Could not delete {file_name} from Google Drive: {e}")

    return False

# =========================
# EXPECTED HEADERS
# =========================

EXPECTED_HEADERS = {
    'sno': 'Sno.',
    'id': 'ID',
    'location': 'Location',
    'failure_dept': 'Failure Dept',
    'sub_system': 'Sub system',
    'failed_equipment': 'Failed Equipment',
    'failure_time': 'Failure Time',
    'failure_date': 'Failure Date',
    'time_rectified': 'Time rectified',
    'date_rectified': 'Date rectified',
    'train_set_location': 'Train Set Location',
    'car_no': 'Car No.',
    'mode_of_operation': 'Mode of Operation',
    'train_id': 'Train ID',
    'description': 'Description of failures',
    'action_taken': 'Action Taken',
    'applicable_name': 'Applicable name of CC/TC/RSC/FMC/ASC/TPC',
    'train_movement_affecting': 'Train movement affecting',
    'sr_no': 'SR No.',
    'failure_category': 'Failure Category',
    'affected': 'Affected',
}

# =========================
# HELPERS
# =========================

def normalize_header(header):
    return ''.join(ch for ch in str(header).lower() if ch.isalnum())


def build_column_map(df):
    normalized_actual = {
        normalize_header(col): col for col in df.columns
    }

    mapping = {}

    for key, expected in EXPECTED_HEADERS.items():
        normalized_expected = normalize_header(expected)

        if normalized_expected in normalized_actual:
            mapping[key] = normalized_actual[normalized_expected]
            continue

        for actual_norm, actual_col in normalized_actual.items():
            if (
                normalized_expected in actual_norm
                or actual_norm in normalized_expected
            ):
                mapping[key] = actual_col
                break

    return mapping


def save_uploaded_file(uploaded_file):
    filename = uploaded_file.name
    path = os.path.join(UPLOAD_DIR, filename)

    if os.path.exists(path):
        base, ext = os.path.splitext(filename)

        filename = (
            f"{base}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"
        )

        path = os.path.join(UPLOAD_DIR, filename)

    with open(path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    upload_file_to_google_drive(path, filename)

    return path


def list_saved_files():
    saved_paths = []

    for file_info in list_google_drive_files():
        file_name = file_info.get("name", "")

        if file_name.lower().endswith(".xlsx"):
            local_path = os.path.join(UPLOAD_DIR, file_name)

            if not os.path.exists(local_path):
                download_google_drive_file(file_info["id"], file_name)

    for file_name in os.listdir(UPLOAD_DIR):
        if file_name.lower().endswith(".xlsx"):
            saved_paths.append(os.path.join(UPLOAD_DIR, file_name))

    return sorted(saved_paths, key=os.path.getmtime, reverse=True)


def delete_saved_file(file_name):
    deleted = False
    local_path = os.path.join(UPLOAD_DIR, file_name)

    if os.path.exists(local_path):
        os.remove(local_path)
        deleted = True

    if delete_google_drive_file(file_name):
        deleted = True

    return deleted


def get_sheet_names(file_path):
    try:
        excel_file = pd.ExcelFile(file_path)
        return excel_file.sheet_names
    except Exception:
        return []


# =========================
# FILE PROCESSING
# =========================

def process_excel_file(file_path, sheet_name=None):
    try:
        df = pd.read_excel(
            file_path,
            sheet_name=0 if sheet_name is None else sheet_name,
            dtype=str
        )

        if df.empty:
            return None

        column_map = build_column_map(df)

        required_columns = [
            'failure_dept',
            'failure_date',
            'failure_time',
            'description'
        ]

        missing = [
            EXPECTED_HEADERS[col]
            for col in required_columns
            if col not in column_map
        ]

        if missing:
            st.warning(
                f"Missing columns in "
                f"{os.path.basename(file_path)}: "
                f"{', '.join(missing)}"
            )
            return None

        # Rename columns
        df = df.rename(
            columns={v: k for k, v in column_map.items()}
        )

        # Ensure required columns exist
        for col in required_columns:
            if col not in df.columns:
                df[col] = ''

        # Convert dates
        df['failure_date'] = pd.to_datetime(
            df['failure_date'],
            errors='coerce'
        )

        return df

    except Exception as e:
        st.exception(e)
        return None


def process_uploaded_files(uploaded_files):
    data_frames = []

    for uploaded_file in uploaded_files:
        saved_path = save_uploaded_file(uploaded_file)

        df = process_excel_file(saved_path)

        if df is not None:
            df['source_file'] = os.path.basename(saved_path)
            data_frames.append(df)

    if data_frames:
        combined = pd.concat(data_frames, ignore_index=True)

        combined.drop_duplicates(inplace=True)

        combined['failure_month'] = (
            combined['failure_date']
            .dt.to_period('M')
            .dt.to_timestamp()
        )

        return combined

    return pd.DataFrame()


def process_saved_files(file_paths, sheet_selections=None):
    data_frames = []

    for path in file_paths:
        file_name = os.path.basename(path)

        selected_sheets = (
            sheet_selections.get(file_name, [None])
            if sheet_selections else [None]
        )

        for sheet in selected_sheets:

            df = process_excel_file(
                path,
                sheet_name=sheet
            )

            if df is not None:

                df['source_file'] = file_name

                if sheet:
                    df['sheet_name'] = sheet

                data_frames.append(df)

    if data_frames:
        combined = pd.concat(data_frames, ignore_index=True)

        combined.drop_duplicates(inplace=True)

        combined['failure_month'] = (
            combined['failure_date']
            .dt.to_period('M')
            .dt.to_timestamp()
        )

        return combined

    return pd.DataFrame()


# =========================
# CHARTS
# =========================

def create_failure_analysis_charts(df):

    if df.empty:
        return

    col1, col2 = st.columns(2)

    with col1:

        dept_counts = (
            df['failure_dept']
            .value_counts()
        )

        fig_dept = px.pie(
            values=dept_counts.values,
            names=dept_counts.index,
            title="Failures by Department"
        )

        st.plotly_chart(
            fig_dept,
            use_container_width=True
        )

    with col2:

        date_counts = (
            df['failure_date']
            .dt.date
            .value_counts()
            .sort_index()
        )

        fig_date = px.line(
            x=date_counts.index,
            y=date_counts.values,
            title="Failures Over Time",
            labels={
                'x': 'Date',
                'y': 'Count'
            }
        )

        st.plotly_chart(
            fig_date,
            use_container_width=True
        )


def create_monthly_analysis(df):

    if df.empty:
        return

    monthly_counts = (
        df.groupby('failure_month')
        .size()
        .reset_index(name='count')
    )

    fig = px.bar(
        monthly_counts,
        x='failure_month',
        y='count',
        title='Failures by Month',
        labels={
            'failure_month': 'Month',
            'count': 'Failures'
        }
    )

    fig.update_xaxes(
        dtick='M1',
        tickformat='%b %Y'
    )

    st.plotly_chart(fig, use_container_width=True)

    stacked = (
        df.groupby(
            ['failure_month', 'failure_dept']
        )
        .size()
        .reset_index(name='count')
    )

    fig_stack = px.bar(
        stacked,
        x='failure_month',
        y='count',
        color='failure_dept',
        title='Monthly Failures by Department'
    )

    fig_stack.update_xaxes(
        dtick='M1',
        tickformat='%b %Y'
    )

    st.plotly_chart(
        fig_stack,
        use_container_width=True
    )


def first_existing_column(df, columns):
    for column in columns:
        if column in df.columns:
            return column

    return None


def create_operator_performance_dashboard(df):
    if df.empty:
        return

    operator_col = first_existing_column(
        df,
        [
            'applicable_name',
            'train_id',
            'mode_of_operation',
            'failure_dept'
        ]
    )

    if not operator_col:
        st.info("Operator performance needs operator or train ID columns.")
        return

    operator_df = df.copy()
    operator_df[operator_col] = (
        operator_df[operator_col]
        .fillna("Unknown")
        .astype(str)
        .str.strip()
        .replace("", "Unknown")
    )

    summary = (
        operator_df
        .groupby(operator_col)
        .size()
        .reset_index(name="failure_records")
        .sort_values("failure_records", ascending=False)
    )

    affected_col = first_existing_column(df, ['affected'])

    if affected_col:
        affected_flags = (
            operator_df[affected_col]
            .fillna("")
            .astype(str)
            .str.lower()
            .str.contains("yes|affected|true|1", regex=True)
        )

        affected_summary = (
            operator_df.assign(train_affected=affected_flags)
            .groupby(operator_col)["train_affected"]
            .sum()
            .reset_index(name="train_affected_records")
        )

        summary = summary.merge(
            affected_summary,
            on=operator_col,
            how="left"
        )

        summary["affected_rate_%"] = (
            summary["train_affected_records"]
            / summary["failure_records"]
            * 100
        ).round(1)

    st.subheader("Train Operator Performance")

    p1, p2, p3 = st.columns(3)

    with p1:
        st.metric("Operators / Train IDs", summary[operator_col].nunique())

    with p2:
        st.metric("Failure Records", int(summary["failure_records"].sum()))

    with p3:
        top_value = summary.iloc[0][operator_col] if not summary.empty else "-"
        st.metric("Highest Records", top_value)

    top_summary = summary.head(15)

    fig = px.bar(
        top_summary,
        x=operator_col,
        y="failure_records",
        title="Top Operator / Train Failure Records",
        labels={
            operator_col: "Operator / Train",
            "failure_records": "Records"
        }
    )

    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(summary, use_container_width=True)

    category_col = first_existing_column(
        df,
        ['failure_category', 'failure_dept', 'mode_of_operation']
    )

    if category_col:
        heatmap_data = (
            operator_df
            .groupby([operator_col, category_col])
            .size()
            .reset_index(name="records")
        )

        fig_heatmap = px.density_heatmap(
            heatmap_data,
            x=category_col,
            y=operator_col,
            z="records",
            title="Operator / Train vs Failure Category"
        )

        st.plotly_chart(fig_heatmap, use_container_width=True)


def read_text_files(uploaded_files):
    text_parts = []

    for uploaded_file in uploaded_files:
        try:
            text_parts.append(
                uploaded_file.getvalue().decode("utf-8", errors="ignore")
            )
        except Exception:
            text_parts.append("")

    return "\n\n".join(text_parts)


def split_sentences(text):
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", text)
        if sentence.strip()
    ]


def extract_top_terms(text, limit=12):
    stop_words = {
        "about", "after", "again", "against", "also", "and", "are",
        "because", "been", "before", "being", "between", "during",
        "from", "have", "into", "that", "the", "their", "there",
        "this", "through", "train", "with", "were", "which", "will",
        "would", "operator", "failure", "statement", "report"
    }

    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text.lower())
    useful_words = [word for word in words if word not in stop_words]

    return Counter(useful_words).most_common(limit)


def sentences_matching(text, patterns, limit=8):
    matches = []

    for sentence in split_sentences(text):
        lowered = sentence.lower()

        if any(pattern in lowered for pattern in patterns):
            matches.append(sentence)

        if len(matches) >= limit:
            break

    return matches


def build_dataframe_operations_summary(df):
    if df.empty:
        return "No failure data is currently selected."

    lines = [
        f"Selected records: {len(df)}",
        f"Departments involved: {df['failure_dept'].nunique()}"
        if 'failure_dept' in df.columns else "Departments involved: N/A",
    ]

    if 'failure_date' in df.columns:
        dates = df['failure_date'].dropna()

        if not dates.empty:
            lines.append(
                f"Period: {dates.min().date()} to {dates.max().date()}"
            )

    for column, label in [
        ('failure_dept', 'Top departments'),
        ('failure_category', 'Top categories'),
        ('location', 'Top locations'),
        ('mode_of_operation', 'Modes of operation'),
        ('train_id', 'Train IDs')
    ]:
        if column in df.columns:
            values = (
                df[column]
                .dropna()
                .astype(str)
                .str.strip()
                .replace("", pd.NA)
                .dropna()
                .value_counts()
                .head(5)
            )

            if not values.empty:
                joined = ", ".join(
                    f"{name} ({count})"
                    for name, count in values.items()
                )
                lines.append(f"{label}: {joined}")

    return "\n".join(lines)


def build_incident_report(df, sections):
    combined_text = "\n\n".join(
        text for text in sections.values() if text.strip()
    )

    top_terms = extract_top_terms(combined_text)
    root_cause_lines = sentences_matching(
        combined_text,
        ["cause", "reason", "failed", "mistake", "delay", "violation"]
    )
    risk_lines = sentences_matching(
        combined_text,
        ["risk", "unsafe", "danger", "signal", "speed", "emergency"]
    )
    improvement_lines = sentences_matching(
        combined_text,
        ["improve", "training", "briefing", "counselling", "monitor"]
    )

    report_lines = [
        "# Train Operations Incident Analysis Report",
        "",
        f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## Data Summary",
        build_dataframe_operations_summary(df),
        "",
        "## Statement And Evidence Summary",
    ]

    if combined_text.strip():
        report_lines.extend([
            f"Text length analyzed: {len(combined_text.split())} words",
            "Key recurring terms: "
            + ", ".join(f"{term} ({count})" for term, count in top_terms)
            if top_terms else "Key recurring terms: N/A",
        ])
    else:
        report_lines.append("No statement, transcript, or CCTV text entered.")

    report_lines.extend(["", "## Possible Contributing Factors"])

    if root_cause_lines:
        report_lines.extend(f"- {line}" for line in root_cause_lines)
    else:
        report_lines.append("- Review operator action, communication, "
                            "equipment status, and procedural compliance.")

    report_lines.extend(["", "## Safety And Operational Risk Points"])

    if risk_lines:
        report_lines.extend(f"- {line}" for line in risk_lines)
    else:
        report_lines.append("- No explicit safety-risk wording was detected "
                            "in the entered text.")

    report_lines.extend(["", "## Improvement Recommendations"])

    recommendations = [
        "Conduct targeted counselling or refresher training for repeated "
        "operator-related failure patterns.",
        "Verify communication protocol compliance for incidents involving "
        "delay, signal, speed, or emergency handling.",
        "Compare statement timeline with CCTV observations and system logs.",
        "Track repeat locations, train IDs, and modes of operation for "
        "preventive action."
    ]

    report_lines.extend(f"- {item}" for item in recommendations)

    if improvement_lines:
        report_lines.extend(f"- Evidence note: {line}" for line in improvement_lines)

    report_lines.extend([
        "",
        "## Final Incident Report Draft",
        "Based on the available failure records, operator statements, "
        "transcript notes, and CCTV observations, the incident should be "
        "reviewed for immediate cause, contributing operational conditions, "
        "procedure compliance, communication quality, and recurrence risk. "
        "Final responsibility and corrective action should be confirmed after "
        "management review of original evidence."
    ])

    return "\n".join(report_lines)


def render_incident_analysis_workspace(df):
    st.subheader("Statement, Transcript, CCTV And Incident Report")

    statement_files = st.file_uploader(
        "Upload statement/report text files",
        type=["txt"],
        accept_multiple_files=True,
        key="statement_files"
    )

    transcript_files = st.file_uploader(
        "Upload transcript text files",
        type=["txt"],
        accept_multiple_files=True,
        key="transcript_files"
    )

    cctv_files = st.file_uploader(
        "Upload CCTV observation text files",
        type=["txt"],
        accept_multiple_files=True,
        key="cctv_files"
    )

    statement_text = st.text_area(
        "Statements / train operator failure report",
        value=read_text_files(statement_files),
        height=180
    )

    transcript_text = st.text_area(
        "Transcript analysis",
        value=read_text_files(transcript_files),
        height=160
    )

    cctv_text = st.text_area(
        "CCTV analysis notes",
        value=read_text_files(cctv_files),
        height=160
    )

    sections = {
        "statements": statement_text,
        "transcripts": transcript_text,
        "cctv": cctv_text,
    }

    report = build_incident_report(df, sections)

    st.markdown(report)

    st.download_button(
        label="Download Incident Analysis Report",
        data=report,
        file_name="train_operations_incident_report.md",
        mime="text/markdown"
    )


# =========================
# MAIN APP
# =========================

def main():

    require_login()

    st.title("🔍 Failure Detection & Analysis System")

    st.markdown(
        "Upload Excel files to analyze failure reports."
    )

    st.caption(f"Upload folder: {os.path.abspath(UPLOAD_DIR)}")

    # =====================
    # UPLOAD
    # =====================

    st.header("📤 Upload Excel Files")

    uploaded_files = st.file_uploader(
        "Choose Excel files",
        type=['xlsx'],
        accept_multiple_files=True
    )

    saved_paths = list_saved_files()

    selected_saved = []

    sheet_selections = {}

    # =====================
    # SAVED FILES
    # =====================

    if saved_paths:

        st.subheader("💾 Saved Files")

        saved_file_names = [
            os.path.basename(path)
            for path in saved_paths
        ]

        col_delete_select, col_delete_button = st.columns([3, 1])

        with col_delete_select:
            file_to_delete = st.selectbox(
                "Delete saved file",
                options=[""] + saved_file_names,
                format_func=lambda value: value or "Choose file"
            )

        with col_delete_button:
            st.write("")
            st.write("")

            if st.button(
                "Delete",
                disabled=not file_to_delete,
                type="secondary"
            ):
                if delete_saved_file(file_to_delete):
                    st.success(f"Deleted {file_to_delete}")
                    st.rerun()
                else:
                    st.warning(f"Could not delete {file_to_delete}")

        selected_saved = st.multiselect(
            "Select saved files",
            options=saved_file_names
        )

        for file_name in selected_saved:

            file_path = next(
                (
                    p for p in saved_paths
                    if os.path.basename(p) == file_name
                ),
                None
            )

            if file_path:

                sheets = get_sheet_names(file_path)

                if len(sheets) > 1:

                    selected_sheets = st.multiselect(
                        f"Select sheets for {file_name}",
                        options=sheets,
                        default=[sheets[0]],
                        key=file_name
                    )

                    sheet_selections[file_name] = (
                        selected_sheets
                    )

    # =====================
    # PROCESS DATA
    # =====================

    if uploaded_files or selected_saved:

        combined_df = pd.DataFrame()

        with st.spinner("Processing files..."):

            if uploaded_files:

                uploaded_df = process_uploaded_files(
                    uploaded_files
                )

                if not uploaded_df.empty:
                    combined_df = uploaded_df

            if selected_saved:

                selected_paths = [
                    path for path in saved_paths
                    if os.path.basename(path)
                    in selected_saved
                ]

                saved_df = process_saved_files(
                    selected_paths,
                    sheet_selections
                )

                if not saved_df.empty:

                    if combined_df.empty:
                        combined_df = saved_df
                    else:
                        combined_df = pd.concat(
                            [combined_df, saved_df],
                            ignore_index=True
                        )

        # =====================
        # DISPLAY DATA
        # =====================

        if not combined_df.empty:

            st.success(
                f"Processed "
                f"{len(combined_df)} records successfully!"
            )

            st.subheader("📁 File Summary")

            file_summary = (
                combined_df
                .groupby('source_file')
                .size()
                .reset_index(name='records')
            )

            st.dataframe(
                file_summary,
                use_container_width=True
            )

            # =====================
            # FILTERS
            # =====================

            st.header("🔍 Filters")

            col1, col2, col3 = st.columns(3)

            with col1:

                dept_filter = st.multiselect(
                    "Department",
                    options=combined_df[
                        'failure_dept'
                    ].dropna().unique()
                )

            with col2:

                subsystem_filter = st.multiselect(
                    "Sub System",
                    options=combined_df[
                        'sub_system'
                    ].dropna().unique()
                    if 'sub_system'
                    in combined_df.columns else []
                )

            with col3:

                search_term = st.text_input(
                    "Search Description"
                )

            filtered_df = combined_df.copy()

            if dept_filter:

                filtered_df = filtered_df[
                    filtered_df['failure_dept']
                    .isin(dept_filter)
                ]

            if subsystem_filter:

                filtered_df = filtered_df[
                    filtered_df['sub_system']
                    .isin(subsystem_filter)
                ]

            if search_term:

                filtered_df = filtered_df[
                    filtered_df['description']
                    .astype(str)
                    .str.contains(
                        search_term,
                        case=False,
                        na=False
                    )
                ]

            # =====================
            # METRICS
            # =====================

            st.header("📊 Overview")

            m1, m2, m3 = st.columns(3)

            with m1:
                st.metric(
                    "Total Records",
                    len(filtered_df)
                )

            with m2:
                st.metric(
                    "Departments",
                    filtered_df[
                        'failure_dept'
                    ].nunique()
                )

            with m3:

                date_range = (
                    filtered_df[
                        'failure_date'
                    ].dropna()
                )

                if not date_range.empty:

                    st.metric(
                        "Date Range",
                        f"{date_range.min().date()} "
                        f"to "
                        f"{date_range.max().date()}"
                    )

            # =====================
            # CHARTS
            # =====================

            st.header("📈 Charts")

            create_failure_analysis_charts(
                filtered_df
            )

            create_monthly_analysis(
                filtered_df
            )

            ops_tab, incident_tab = st.tabs([
                "Operator Performance",
                "Incident Analysis"
            ])

            with ops_tab:
                create_operator_performance_dashboard(filtered_df)

            with incident_tab:
                render_incident_analysis_workspace(filtered_df)

            # =====================
            # DATA TABLE
            # =====================

            st.header("📋 Failure Records")

            st.dataframe(
                filtered_df,
                use_container_width=True
            )

            # =====================
            # DOWNLOAD CSV
            # =====================

            csv = filtered_df.to_csv(
                index=False
            )

            st.download_button(
                label="📥 Download CSV",
                data=csv,
                file_name="filtered_failures.csv",
                mime="text/csv"
            )

            # =====================
            # DOWNLOAD EXCEL
            # =====================

            output = BytesIO()

            with pd.ExcelWriter(
                output,
                engine='openpyxl'
            ) as writer:

                filtered_df.to_excel(
                    writer,
                    index=False
                )

            excel_data = output.getvalue()

            st.download_button(
                label="📥 Download Excel",
                data=excel_data,
                file_name="filtered_failures.xlsx",
                mime=(
                    "application/"
                    "vnd.openxmlformats-"
                    "officedocument."
                    "spreadsheetml.sheet"
                )
            )

        else:
            st.warning(
                "No valid data found."
            )

    else:

        st.info(
            "👆 Upload Excel files to begin."
        )

        st.markdown("""
        ### Required Excel Columns

        - Failure Dept
        - Failure Date
        - Failure Time
        - Description of failures

        Optional:
        - Location
        - Failed Equipment
        - Action Taken
        - Failure Category
        """)

        st.header("Operations Incident Analysis")
        render_incident_analysis_workspace(pd.DataFrame())


# =========================
# RUN APP
# =========================

if __name__ == "__main__":
    main()
