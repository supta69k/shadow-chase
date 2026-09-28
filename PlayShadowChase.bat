@echo off
rem Shadow Chase launcher - double-click to play
cd /d "%~dp0"
py -3 main.py
if errorlevel 1 pause
