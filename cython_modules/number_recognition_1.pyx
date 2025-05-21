# number_recognition.pyx
import numpy as np
cimport numpy as np
cimport cython
import cv2
import pytesseract

@cython.boundscheck(False)
@cython.wraparound(False)
def process_number_area(np.ndarray[np.uint8_t, ndim=3] roi, 
                        display_frame, 
                        int x1, int y1):
    cdef:
        np.ndarray[np.uint8_t, ndim=2] roi_gray
        np.ndarray[np.uint8_t, ndim=2] roi_resized
        np.ndarray[np.uint8_t, ndim=2] roi_equalized
        np.ndarray[np.uint8_t, ndim=2] roi_enhanced
        np.ndarray[np.uint8_t, ndim=2] roi_denoised
        double scale_factor = 4.0
        list results = []
        dict text_groups = {}
        dict scores = {}
        str best_text
        double best_score
        int count
        double avg_conf
        double score

    # Gestisci immagini a colori e scala di grigi
    if roi.ndim == 3 and roi.shape[2] == 3:
        roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    elif roi.ndim == 2:
        roi_gray = roi
    else:
        raise ValueError("Input image must be 2D (grayscale) or 3D (color)")
    
    # Ridimensionamento
    roi_resized = cv2.resize(roi_gray, None, fx=scale_factor, fy=scale_factor, interpolation=cv2.INTER_CUBIC)
    
    # Equalizzazione istogramma
    roi_equalized = cv2.equalizeHist(roi_resized)
    
    # Miglioramento contrasto
    roi_enhanced = cv2.convertScaleAbs(roi_resized, alpha=1.8, beta=15)
    
    # Riduzione rumore
    roi_denoised = cv2.fastNlMeansDenoising(roi_enhanced, None, 10, 7, 21)
    
    # Metodi di preprocessamento
    cdef list methods = [
        cv2.threshold(roi_denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1],
        cv2.adaptiveThreshold(roi_denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                               cv2.THRESH_BINARY, 17, 5),
        cv2.threshold(roi_denoised, 127, 255, cv2.THRESH_BINARY)[1],
        cv2.threshold(roi_denoised, 127, 255, cv2.THRESH_BINARY_INV)[1],
        cv2.threshold(roi_equalized, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    ]
    
    # Configurazioni OCR
    cdef list configs = [
        "--psm 7 --oem 3 -c tessedit_char_whitelist=0123456789",
        "--psm 8 --oem 3 -c tessedit_char_whitelist=0123456789",
        "--psm 10 --oem 3 -c tessedit_char_whitelist=0123456789",
        "--psm 6 --oem 3 -c tessedit_char_whitelist=0123456789"
    ]
    
    # Operazioni morfologiche per pulizia
    cdef np.ndarray[np.uint8_t, ndim=2] kernel = np.ones((2, 2), dtype=np.uint8)
    
    for method in methods:
        # Applicazione morfologia
        method_cleaned = cv2.morphologyEx(method, cv2.MORPH_OPEN, kernel)
        method_cleaned = cv2.morphologyEx(method_cleaned, cv2.MORPH_CLOSE, kernel)
        
        for config in configs:
            try:
                # Riconoscimento con Tesseract
                result_data = pytesseract.image_to_data(
                    method_cleaned,
                    config=config,
                    output_type=pytesseract.Output.DICT
                )
                
                # Filtraggio risultati
                for j in range(len(result_data['text'])):
                    text = result_data['text'][j].strip()
                    conf = float(result_data['conf'][j]) if result_data['conf'][j] > 0 else 0
                    
                    if text.isdigit() and conf > 0:
                        if text not in text_groups:
                            text_groups[text] = []
                        text_groups[text].append({
                            'text': text,
                            'conf': conf
                        })
            except Exception as e:
                # Gestione silenziosa degli errori
                pass
    
    # Sistema di votazione ponderata
    for text, group in text_groups.items():
        count = len(group)
        avg_conf = sum(r['conf'] for r in group) / count
        
        # Calcolo dello score con fattore di lunghezza
        text_len = len(text)
        len_factor = 1.0 if 1 <= text_len <= 6 else 0.5
        
        scores[text] = count * (avg_conf ** 2) * len_factor
    
    # Selezione del miglior risultato
    if scores:
        best_text = max(scores, key=scores.get)
        best_score = scores[best_text]
        
        # Soglia di confidenza
        if best_score > 100:
            return int(best_text)
    
    return None