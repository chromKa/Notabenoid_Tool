import os
from cx_Freeze import setup, Executable

# Папка, где лежит setup.py — все пути считаются от неё
HERE = os.path.dirname(os.path.abspath(__file__))

executables = [
    Executable(
        script=os.path.join(HERE, "main.py"),
        base="Win32GUI",                       # без консоли
        icon=os.path.join(HERE, "resource", "Untitled-1.ico"),
        target_name="NotabenoidTool.exe",
    )
]

# Только локальные модули, которые могут не подхватиться автоматически
includes = [
    "main_ui",
    "res",
]

# Пакеты со своими DLL/бинарниками — НИКОГДА в zip
zip_include_packages = []          # оставь пустым

# Пакеты, которые cx_Freeze может не заметить (редко, но бывает)
packages = [
    "PyQt6",
    "requests",
    "bs4",
    "urllib3",
]


options = {
    "build_exe": {
        "include_msvcr": True,
        "includes": includes,
        "packages": packages,
        "zip_include_packages": zip_include_packages,
        "excludes": [
            # Убираем тяжёлые неиспользуемые модули Qt
            "PyQt6.QtWebEngineCore",
            "PyQt6.QtWebEngineWidgets",
            "PyQt6.QtWebEngineQuick",
            "PyQt6.QtQuick",
            "PyQt6.QtQml",
            "PyQt6.QtMultimedia",
            "PyQt6.QtMultimediaWidgets",
            "PyQt6.QtBluetooth",
            "PyQt6.QtNetworkAuth",
            "PyQt6.QtPositioning",
            "PyQt6.QtSerialPort",
            "PyQt6.QtSql",
            "PyQt6.QtTest",
            "PyQt6.QtSensors",
            "PyQt6.QtCharts",
            "PyQt6.QtDataVisualization",
            "PyQt6.Qt3DCore",
            # Стандартные библиотеки, которые точно не нужны
            "tkinter",
            "unittest",
            "http.server",
            "pydoc",
            "pdb",
            "doctest",
            "distutils",
            "setuptools",
            "pip",
        ],
        "build_exe": os.path.join(HERE, "build_windows"),
    }
}

setup(
    name="Notabenoid_Tool",
    version="2.1",
    description="Notabenoid Tool",
    executables=executables,
    options=options,
)