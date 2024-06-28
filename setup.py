from cx_Freeze import setup, Executable

executables = [Executable('D:/tt2/notenaboid/main_untitled.py',
base='Win32GUI', icon='D:/tt2/notenaboid/download.ico')]

includes = ['os', 'datetime', 'webbrowser', 'sys', 'difflib', 'requests', 'bs4', 'math', 'PyQt6', 'time', 'notenaboid2', 'res']

zip_include_packages = ['os', 'datetime', 'webbrowser', 'sys', 'difflib', 'requests', 'bs4', 'math', 'PyQt6', 'time', 'notenaboid2', 'res']

#include_files = ['DINPro-CondensedMedium.ttf', 'download.png', 'D:/tt2/ui/1.qrc']

options = {
'build_exe': {
'include_msvcr': True,
'includes': includes,
'zip_include_packages': zip_include_packages,
'build_exe': 'build_windows',
#'include_files': include_files,
}
}

setup(name=' NotenaboidApp',
version='1.0.0',
description='NotenaboidApp',
executables=executables,
options=options)