from cx_Freeze import setup, Executable
# python setup.py build
executables = [Executable('C:\\Users\\Комп\\PycharmProjects\\NotabenoidTool\\main.py',
                          base='Win32GUI', icon='C:\\Users\\Комп\\PycharmProjects\\NotabenoidTool\\resource\\Untitled-1.ico')]

includes = ['os', 'datetime', 'webbrowser', 'sys', 'difflib', 'requests', 'bs4', 'math', 'PyQt6', 'time',
            ]

zip_include_packages = ['os', 'datetime', 'webbrowser', 'sys', 'difflib', 'requests', 'bs4', 'math', 'PyQt6', 'time',
                        ]

# include_files = ['C:\\Users\\Комп\\PycharmProjects\\NotabenoidTool\\replace.py']

options = {
    'build_exe': {
        'include_msvcr': True,
        'includes': includes,
        'zip_include_packages': zip_include_packages,
        'build_exe': 'build_windows',
        # 'include_files': include_files,
    }
}

setup(name='Notabenoid_Tool',
      version='1.3.0',
      description='Notabenoid_Tool',
      executables=executables,
      options=options)
