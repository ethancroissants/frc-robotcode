' Cold Fusion Robotics — Control Panel launcher (Windows).
'
' Double-click start.vbs to open start.py. Uses pythonw.exe so no extra
' console window flashes up; falls back to python.exe if pythonw isn't
' installed, and shows a friendly error if Python can't be found at all.

Option Explicit

Dim shell, fso, scriptDir, startPy

Set shell = CreateObject("WScript.Shell")
Set fso  = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
startPy   = scriptDir & "\start.py"

If Not fso.FileExists(startPy) Then
    MsgBox "Couldn't find start.py next to this launcher." & vbCrLf & _
           "Expected: " & startPy, _
           vbCritical, "Cold Fusion Robotics"
    WScript.Quit 1
End If

' Run from the repo dir so start.py's relative paths resolve correctly.
shell.CurrentDirectory = scriptDir

' Try pythonw.exe (no console). Fall back to python.exe. Then to py -3.
Dim launched
launched = False

On Error Resume Next

shell.Run "pythonw.exe """ & startPy & """", 0, False
If Err.Number = 0 Then launched = True
Err.Clear

If Not launched Then
    shell.Run "py.exe -3 """ & startPy & """", 0, False
    If Err.Number = 0 Then launched = True
    Err.Clear
End If

If Not launched Then
    shell.Run "python.exe """ & startPy & """", 0, False
    If Err.Number = 0 Then launched = True
    Err.Clear
End If

On Error Goto 0

If Not launched Then
    MsgBox "Python isn't installed or isn't on your PATH." & vbCrLf & vbCrLf & _
           "Install Python 3 from:" & vbCrLf & _
           "https://www.python.org/downloads/" & vbCrLf & vbCrLf & _
           "Make sure to tick ""Add Python to PATH"" during install.", _
           vbCritical, "Cold Fusion Robotics"
    WScript.Quit 1
End If
