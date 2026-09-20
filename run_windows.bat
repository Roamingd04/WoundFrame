@echo off
setlocal EnableExtensions
cd /d "%~dp0"

title Wound Panel Standardizer

rem ============================================================
rem DEFAULT VALUES
rem Press ENTER at "Use all defaults?" for the fastest workflow.
rem ============================================================
set "DEF_CALIBRATION=20"
set "DEF_CROPW=20"
set "DEF_CROPH=20"
set "DEF_SCALEBAR=5"
set "DEF_PPMM=50"
set "DEF_FULLSCREEN=yes"
set "DEF_SHOWSCALE=yes"
set "DEF_CELLW=2.75"
set "DEF_CELLH=2.75"
set "DEF_WSPACE=0.25"
set "DEF_HSPACE=0.40"
set "DEF_REUSE=yes"

set "calibration=%DEF_CALIBRATION%"
set "cropw=%DEF_CROPW%"
set "croph=%DEF_CROPH%"
set "scalebar=%DEF_SCALEBAR%"
set "ppmm=%DEF_PPMM%"
set "fullscreen=%DEF_FULLSCREEN%"
set "showscale=%DEF_SHOWSCALE%"
set "cellw=%DEF_CELLW%"
set "cellh=%DEF_CELLH%"
set "wspace=%DEF_WSPACE%"
set "hspace=%DEF_HSPACE%"
set "reuse=%DEF_REUSE%"

echo.
echo ==================================================
echo          WOUNDFRAME 1.0
echo ==================================================
echo.
echo Default settings:
echo   Calibration distance : %DEF_CALIBRATION% mm
echo   Crop                 : %DEF_CROPW% x %DEF_CROPH% mm
echo   Scale bar            : %DEF_SCALEBAR% mm
echo   Target resolution    : %DEF_PPMM% px/mm
echo   Fullscreen           : %DEF_FULLSCREEN%
echo   Add scale bar        : %DEF_SHOWSCALE%
echo   Cell size            : %DEF_CELLW% x %DEF_CELLH% in
echo   Panel gaps           : W=%DEF_WSPACE%  H=%DEF_HSPACE%
echo   Reuse calibration    : %DEF_REUSE%
echo.

set "use_defaults="
set /p "use_defaults=Use all defaults? [Y/n]: "
if /I "%use_defaults%"=="" goto RUN_SCRIPT
if /I "%use_defaults%"=="Y" goto RUN_SCRIPT
if /I "%use_defaults%"=="YES" goto RUN_SCRIPT

echo.
echo CUSTOM SETTINGS
echo Press ENTER at any prompt to keep the value in brackets.
echo.

set "tmp="
set /p "tmp=Distance between ruler points in mm [%DEF_CALIBRATION%]: "
if not "%tmp%"=="" set "calibration=%tmp%"

set "tmp="
set /p "tmp=Crop width in mm [%DEF_CROPW%]: "
if not "%tmp%"=="" set "cropw=%tmp%"

set "tmp="
set /p "tmp=Crop height in mm [%DEF_CROPH%]: "
if not "%tmp%"=="" set "croph=%tmp%"

set "tmp="
set /p "tmp=Scale bar length in mm [%DEF_SCALEBAR%]: "
if not "%tmp%"=="" set "scalebar=%tmp%"

set "tmp="
set /p "tmp=Target pixels per mm [%DEF_PPMM%]: "
if not "%tmp%"=="" set "ppmm=%tmp%"

set "tmp="
set /p "tmp=Fullscreen calibration? yes/no [%DEF_FULLSCREEN%]: "
if not "%tmp%"=="" set "fullscreen=%tmp%"

set "tmp="
set /p "tmp=Add scale bar? yes/no [%DEF_SHOWSCALE%]: "
if not "%tmp%"=="" set "showscale=%tmp%"

echo.
echo Panel layout:
echo.

set "tmp="
set /p "tmp=Panel cell width in inches [%DEF_CELLW%]: "
if not "%tmp%"=="" set "cellw=%tmp%"

set "tmp="
set /p "tmp=Panel cell height in inches [%DEF_CELLH%]: "
if not "%tmp%"=="" set "cellh=%tmp%"

set "tmp="
set /p "tmp=Horizontal gap between images [%DEF_WSPACE%]: "
if not "%tmp%"=="" set "wspace=%tmp%"

set "tmp="
set /p "tmp=Vertical gap between images [%DEF_HSPACE%]: "
if not "%tmp%"=="" set "hspace=%tmp%"

set "tmp="
set /p "tmp=Reuse saved calibration? yes/no [%DEF_REUSE%]: "
if not "%tmp%"=="" set "reuse=%tmp%"

:RUN_SCRIPT
echo.
echo ---------------- SETTINGS ----------------
echo Calibration distance : %calibration% mm
echo Crop                 : %cropw% x %croph% mm
echo Scale bar            : %scalebar% mm
echo Target resolution    : %ppmm% px/mm
echo Fullscreen           : %fullscreen%
echo Add scale bar        : %showscale%
echo Cell size            : %cellw% x %cellh% in
echo Panel gaps           : W=%wspace%  H=%hspace%
echo Reuse calibration    : %reuse%
echo ------------------------------------------
echo.

set "recalibrate_arg="
if /I "%reuse%"=="no" set "recalibrate_arg=--recalibrate"
if /I "%reuse%"=="n" set "recalibrate_arg=--recalibrate"

where py >nul 2>nul
if %errorlevel%==0 (
    py woundframe.py ^
      --calibration-mm "%calibration%" ^
      --crop-width-mm "%cropw%" ^
      --crop-height-mm "%croph%" ^
      --scale-bar-mm "%scalebar%" ^
      --target-ppmm "%ppmm%" ^
      --fullscreen "%fullscreen%" ^
      --scale-bar "%showscale%" ^
      --cell-width-in "%cellw%" ^
      --cell-height-in "%cellh%" ^
      --wspace "%wspace%" ^
      --hspace "%hspace%" ^
      %recalibrate_arg%
) else (
    python woundframe.py ^
      --calibration-mm "%calibration%" ^
      --crop-width-mm "%cropw%" ^
      --crop-height-mm "%croph%" ^
      --scale-bar-mm "%scalebar%" ^
      --target-ppmm "%ppmm%" ^
      --fullscreen "%fullscreen%" ^
      --scale-bar "%showscale%" ^
      --cell-width-in "%cellw%" ^
      --cell-height-in "%cellh%" ^
      --wspace "%wspace%" ^
      --hspace "%hspace%" ^
      %recalibrate_arg%
)

echo.
echo Finished.
echo If an error occurred, see error_log.txt.
pause
endlocal
