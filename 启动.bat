@echo off
chcp 65001 >nul
title 画镜 ArtMirror 一键启动
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
