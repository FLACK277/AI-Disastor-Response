@echo off
cd /d C:\Users\PRIYANSHU\Downloads\AI_Disaster_Response
.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
