Set FSO = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")

Dim scriptDir, batchPath, cmdLine
scriptDir = FSO.GetParentFolderName(WScript.ScriptFullName)
batchPath = """" & scriptDir & "\start-windows-backend.bat" & """"
cmdLine = "cmd /c " & batchPath

WshShell.Run cmdLine, 0, False
