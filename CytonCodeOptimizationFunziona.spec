# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['CytonCodeOptimizationFunziona.py'],
    pathex=[],
    binaries=[],
    datas=[
        # Include Tesseract executable and data files
        ('C:\\Program Files\\Tesseract-OCR\\tesseract.exe', 'tesseract'),
        ('C:\\Program Files\\Tesseract-OCR\\tessdata', 'tessdata'),
        # Include Cython modules directory
        ('./cython_modules', 'cython_modules'),
        ('can.ico', '.'),
        ('can.png', '.'),
    ],
    hiddenimports=[
        'cv2',
        'numpy',
        'can',
        'can.interfaces',
        'can.interfaces.vector',  # Add this specific interface
        'PIL.Image',
        'PIL.ImageTk',
        'tkinter',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Add environment variables for Tesseract to find its data files
import os
os.environ['TESSDATA_PREFIX'] = os.path.join(DISTPATH, 'tessdata')

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='DTCRecognition',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # Set to True initially for debugging, change to False for final build
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='can.ico'
)



