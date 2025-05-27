# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_submodules
import os
import site

# Trova le librerie di sistema di Paddle
def find_paddle_dlls():
    """Trova tutte le DLL necessarie per Paddle"""
    dll_paths = []
    
    # Percorsi comuni dove Paddle installa le DLL
    search_paths = [
        os.path.join(site.getsitepackages()[0], 'paddle', 'libs'),
        os.path.join(site.getsitepackages()[0], 'paddle', 'fluid', 'core'),
        os.path.join(site.getsitepackages()[0], 'Lib', 'site-packages', 'paddle', 'libs'),
    ]
    
    dll_names = [
        'mklml.dll', 'libiomp5md.dll', 'mkldnn.dll', 'openblas.dll',
        'paddle_inference.dll', 'msvcp140.dll', 'vcruntime140.dll'
    ]
    
    for search_path in search_paths:
        if os.path.exists(search_path):
            for dll_name in dll_names:
                dll_path = os.path.join(search_path, dll_name)
                if os.path.exists(dll_path):
                    dll_paths.append((dll_path, '.'))
                    print(f"✅ Found DLL: {dll_path}")
    
    return dll_paths

# Raccogli moduli come prima
try:
    paddleocr_datas, paddleocr_binaries, paddleocr_hiddenimports = collect_all('paddleocr')
    paddleocr_datas = [(src, dst) for src, dst in paddleocr_datas 
                       if not any(x in dst for x in ['Cython/Utility', 'CppSupport.cpp', 'AsyncGen.c'])]
except:
    paddleocr_datas, paddleocr_binaries, paddleocr_hiddenimports = [], [], []

# Aggiungi le DLL di Paddle
paddle_dlls = find_paddle_dlls()
paddleocr_binaries.extend(paddle_dlls)

# Resto del codice scipy come prima
try:
    scipy_datas, scipy_binaries, scipy_hiddenimports = collect_all('scipy')
    scipy_submodules = collect_submodules('scipy')
    scipy_hiddenimports.extend(scipy_submodules)
    paddleocr_datas.extend(scipy_datas)
    paddleocr_binaries.extend(scipy_binaries)
except:
    scipy_hiddenimports = []

try:
    skimage_datas, skimage_binaries, skimage_hiddenimports = collect_all('skimage')
    skimage_submodules = collect_submodules('skimage')
    skimage_hiddenimports.extend(skimage_submodules)
    paddleocr_datas.extend(skimage_datas)
    paddleocr_binaries.extend(skimage_binaries)
except:
    skimage_hiddenimports = []

block_cipher = None

a = Analysis(
    ['FinalDTC_PaddleOCR.py'],
    pathex=[],
    binaries=paddleocr_binaries,  # Include le DLL
    datas=paddleocr_datas,
    hiddenimports=[
        # Tutti gli hiddenimports come prima
        'paddleocr', 'paddleocr.paddleocr', 'paddleocr.tools',
        'paddleocr.tools.infer', 'paddleocr.tools.infer.predict_system',
        'paddleocr.tools.infer.predict_rec', 'paddleocr.tools.infer.predict_det',
        'paddleocr.ppocr', 'paddleocr.ppocr.postprocess', 'paddleocr.ppocr.utils',
        'paddleocr.ppocr.utils.utility', 'paddleocr.ppocr.data',
        'paddleocr.ppocr.data.imaug', 'paddleocr.ppocr.data.imaug.ct_process',
        'paddle', 'paddle.base', 'paddle.utils',
        'numpy', 'cv2', 'PIL', 'PIL.Image', 'PIL.ImageTk',
        'tkinter', 'tkinter.ttk', 'tkinter.filedialog',
        'can', 'can.interface', 'can.interfaces.vector',
        'threading', 'time', 'datetime', 'csv', 'os', 'sys', 're', 'math',
        'attrdict', 'beautifulsoup4', 'fire', 'fonttools', 'imgaug', 
        'lmdb', 'lxml', 'openpyxl', 'pdf2docx', 'premailer', 'pyclipper', 
        'PyMuPDF', 'pyyaml', 'rapidfuzz', 'shapely', 'tqdm', 'visualdl',
        'cython', 'Cython', 'Cython.Build.Dependencies',
    ] + paddleocr_hiddenimports + scipy_hiddenimports + skimage_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'Cython.Compiler.Main', 'Cython.Compiler.Symtab', 
        'Cython.Compiler.PyrexTypes', 'Cython.Compiler.Code', 'Cython.Utils',
        'apted', 'matplotlib.backends._backend_pdf', 'matplotlib.backends._backend_ps',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='DTC_Recognition',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)