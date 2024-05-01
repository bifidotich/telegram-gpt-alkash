cd /d %~dp0
call venv\Scripts\activate.bat 
call python -m pip freeze > requirements.txt

cmd.exe