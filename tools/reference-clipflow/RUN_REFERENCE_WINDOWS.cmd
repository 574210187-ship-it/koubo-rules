@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if "%~1"=="" (
  echo Drag a reference MP4 onto RUN_REFERENCE_WINDOWS.cmd
  echo No audio transcription will run. Visible subtitles only.
  pause
  exit /b 2
)
where py >nul 2>&1
if not errorlevel 1 (
  py -3 -m clipflow.cli doctor
  py -3 -m clipflow.cli reference --input "%~1" --out "%~dp0output_%~n1"
) else (
  python -m clipflow.cli doctor
  python -m clipflow.cli reference --input "%~1" --out "%~dp0output_%~n1"
)
if errorlevel 1 (
  echo Check the error above. This workflow never falls back to ASR.
  pause
  exit /b 2
)
echo Done. Find segments_transcript.md beside numbered_segments.zip in the output folder.
pause
