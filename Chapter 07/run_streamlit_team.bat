@echo off
REM Run the app so other people on the same office network can open it.
SET SCRIPT_DIR=%~dp0
SET PYTHON_EXE=%SCRIPT_DIR%\.venv\Scripts\python.exe
IF NOT EXIST "%PYTHON_EXE%" (
    echo Error: virtual environment Python not found at %PYTHON_EXE%
    exit /b 1
)
"%PYTHON_EXE%" -m streamlit run "%SCRIPT_DIR%streamlit_app.py" --server.port 8501 --server.address 0.0.0.0 --server.headless true
