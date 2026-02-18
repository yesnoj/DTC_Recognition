# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_data_files
import os
import site

# Funzione per trovare file specifici
def find_package_files(package_name, file_patterns):
    """Trova file specifici in un package"""
    files = []
    try:
        for site_path in site.getsitepackages():
            pkg_path = os.path.join(site_path, package_name)
            if os.path.exists(pkg_path):
                for root, dirs, filenames in os.walk(pkg_path):
                    for pattern in file_patterns:
                        for filename in filenames:
                            if filename == pattern or filename.endswith(pattern):
                                src = os.path.join(root, filename)
                                dst = os.path.relpath(src, site_path)
                                files.append((src, dst))
                                print(f"✅ Found: {src} -> {dst}")
    except Exception as e:
        print(f"⚠️ Error finding package files: {e}")
    return files

# Raccogli PaddleOCR come prima
try:
    paddleocr_datas, paddleocr_binaries, paddleocr_hiddenimports = collect_all('paddleocr')
    paddleocr_datas = [(src, dst) for src, dst in paddleocr_datas 
                       if not any(x in dst for x in ['Cython/Utility', 'CppSupport.cpp', 'AsyncGen.c'])]
except:
    paddleocr_datas, paddleocr_binaries, paddleocr_hiddenimports = [], [], []

# Raccogli PaddleX e i suoi file di versione
try:
    paddlex_datas, paddlex_binaries, paddlex_hiddenimports = collect_all('paddlex')
    paddleocr_datas.extend(paddlex_datas)
    paddleocr_binaries.extend(paddlex_binaries)
    paddleocr_hiddenimports.extend(paddlex_hiddenimports)
    
    # Aggiungi specificamente il file .version mancante
    version_files = find_package_files('paddlex', ['.version', 'version.txt', 'VERSION'])
    paddleocr_datas.extend(version_files)
    
except Exception as e:
    print(f"⚠️ Could not collect paddlex: {e}")
    paddlex_hiddenimports = []

# SciPy e altre dipendenze come prima
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
    binaries=paddleocr_binaries,
    datas=paddleocr_datas,
    hiddenimports=[
        # PaddleOCR e PaddleX
        'paddleocr',
        'paddleocr.paddleocr',
        'paddleocr.tools',
        'paddleocr.tools.infer',
        'paddleocr.tools.infer.predict_system',
        'paddleocr.tools.infer.predict_rec',
        'paddleocr.tools.infer.predict_det',
        'paddleocr.ppocr',
        'paddleocr.ppocr.postprocess',
        'paddleocr.ppocr.utils',
        'paddleocr.ppocr.utils.utility',
        'paddleocr.ppocr.data',
        'paddleocr.ppocr.data.imaug',
        'paddleocr.ppocr.data.imaug.ct_process',
        'paddleocr._models',
        'paddleocr._models.base',
        'paddleocr._models.doc_img_orientation_classification',
        'paddleocr._models._image_classification',
        
        # PaddleX
        'paddlex',
        'paddlex.version',
        
        # Paddle core
        'paddle',
        'paddle.base',
        'paddle.utils',
        
        # Basic Python
        'numpy',
        'cv2',
        'PIL', 'PIL.Image', 'PIL.ImageTk',
        'tkinter', 'tkinter.ttk', 'tkinter.filedialog',
        'can', 'can.interface', 'can.interfaces.vector',
        'threading', 'time', 'datetime', 'csv', 'os', 'sys', 're', 'math',
        
        # PaddleOCR dependencies
        'attrdict', 'beautifulsoup4', 'fire', 'fonttools', 'imgaug', 
        'lmdb', 'lxml', 'openpyxl', 'pdf2docx', 'premailer', 'pyclipper', 
        'PyMuPDF', 'pyyaml', 'rapidfuzz', 'shapely', 'tqdm', 'visualdl',
        
        # Cython minimal
        'cython', 'Cython', 'Cython.Build.Dependencies',
        
    ] + paddleocr_hiddenimports + paddlex_hiddenimports + scipy_hiddenimports + skimage_hiddenimports,
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