@echo off

call "%~dp0tools\packman\python.bat" %~dp0tools\scripts\link_app.py %*
if %errorlevel% neq 0 ( goto Error )

:Success
call "%~dp0Install_requirments.bat"
exit /b 0

:Error
exit /b %errorlevel%
