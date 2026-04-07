Option Explicit

Dim shell, fso, scriptDir, batchPath, command

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
batchPath = fso.BuildPath(scriptDir, "start-wsl-voice-server.bat")
command = "cmd.exe /c """ & batchPath & """"

' Window style 0 keeps the launcher hidden for Startup use.
shell.Run command, 0, False
