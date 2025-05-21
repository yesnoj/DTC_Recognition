# number_recognition.pyx
import numpy as np
cimport numpy as np
cimport cython
import cv2
import pytesseract

# Limiti standard per SPN e FMI secondo i protocolli SAE J1939
cdef:
    int SPN_MIN = 1       # Il valore minimo per SPN è 1
    int SPN_MAX = 524287  # Il valore massimo per SPN è 524287 (2^19-1)
    int FMI_MIN = 0       # Il valore minimo per FMI è 0
    int FMI_MAX = 31      # Il valore massimo per FMI è 31

@cython.boundscheck(False)
@cython.wraparound(False)
def process_number_area(np.ndarray[np.uint8_t, ndim=3] roi, 
                        display_frame, 
                        int x1, int y1,
                        str area_type="Number",
                        int slot_number=1):
    """
    Versione ottimizzata per il riconoscimento di numeri nelle aree selezionate.
    
    Args:
        roi: Region of interest (area selezionata dall'immagine)
        display_frame: Frame su cui disegnare le informazioni di debug
        x1, y1: Coordinate dell'angolo in alto a sinistra dell'area
        area_type: Tipo di area ("Number" è il default)
        slot_number: Numero dello slot (1 per SPN, 2 per FMI)
        
    Returns:
        int or None: Il numero riconosciuto o None se il riconoscimento fallisce
    """
    cdef:
        np.ndarray[np.uint8_t, ndim=2] roi_gray
        np.ndarray[np.uint8_t, ndim=2] roi_resized
        np.ndarray[np.uint8_t, ndim=2] roi_equalized
        np.ndarray[np.uint8_t, ndim=2] roi_enhanced
        np.ndarray[np.uint8_t, ndim=2] roi_denoised
        double scale_factor = 5.0  # Aumentato a 5.0 per migliorare la risoluzione
        list results = []
        dict text_groups = {}
        dict scores = {}
        str best_text
        double best_score
        int count
        double avg_conf
        double score
        int i, j
        int recognized_value
        bint is_valid_value
        int min_value, max_value

    # Gestisci immagini a colori e scala di grigi
    if roi.ndim == 3 and roi.shape[2] == 3:
        roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    elif roi.ndim == 2:
        roi_gray = roi
    else:
        raise ValueError("Input image must be 2D (grayscale) or 3D (color)")
    
    # Applica un filtro bilaterale per ridurre il rumore preservando i bordi
    roi_gray = cv2.bilateralFilter(roi_gray, 9, 75, 75)
    
    # Ridimensionamento (aumentato il fattore di scala)
    roi_resized = cv2.resize(roi_gray, None, fx=scale_factor, fy=scale_factor, interpolation=cv2.INTER_CUBIC)
    
    # CLAHE (Contrast Limited Adaptive Histogram Equalization) per migliorare il contrasto locale
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    roi_equalized = clahe.apply(roi_resized)
    
    # Miglioramento contrasto con diversi parametri
    roi_enhanced1 = cv2.convertScaleAbs(roi_resized, alpha=1.8, beta=15)
    roi_enhanced2 = cv2.convertScaleAbs(roi_resized, alpha=2.0, beta=0)
    
    # Riduzione rumore con parametri ottimizzati
    roi_denoised1 = cv2.fastNlMeansDenoising(roi_enhanced1, None, 10, 7, 21)
    roi_denoised2 = cv2.fastNlMeansDenoising(roi_enhanced2, None, 15, 7, 21)
    roi_denoised3 = cv2.fastNlMeansDenoising(roi_equalized, None, 10, 7, 21)
    
    # Metodi di preprocessamento più completi
    cdef list methods = [
        # Otsu thresholding
        cv2.threshold(roi_denoised1, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1],
        cv2.threshold(roi_denoised2, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1],
        cv2.threshold(roi_denoised3, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1],
        
        # Adaptive thresholding con diversi parametri
        cv2.adaptiveThreshold(roi_denoised1, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                               cv2.THRESH_BINARY, 17, 5),
        cv2.adaptiveThreshold(roi_denoised1, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                               cv2.THRESH_BINARY, 11, 2),
        
        # Inversione per gestire testo bianco su sfondo scuro
        cv2.threshold(roi_denoised1, 127, 255, cv2.THRESH_BINARY_INV)[1],
        cv2.threshold(roi_denoised2, 127, 255, cv2.THRESH_BINARY_INV)[1],
        
        # Thresholding con valori fissi ma diversi
        cv2.threshold(roi_enhanced1, 100, 255, cv2.THRESH_BINARY)[1],
        cv2.threshold(roi_enhanced2, 150, 255, cv2.THRESH_BINARY)[1],
        
        # Canny edge detection seguito da dilatazione per trovare i contorni del testo
        cv2.dilate(cv2.Canny(roi_denoised1, 100, 200), None, iterations=1)
    ]
    
    # Configurazioni OCR ottimizzate
    cdef list configs = [
        # PSM 7 è per una singola riga di testo
        "--psm 7 --oem 3 -c tessedit_char_whitelist=0123456789",
        
        # PSM 8 è per una singola parola
        "--psm 8 --oem 3 -c tessedit_char_whitelist=0123456789",
        
        # PSM 10 è per una singola carattere
        "--psm 10 --oem 3 -c tessedit_char_whitelist=0123456789",
        
        # PSM 6 è per un blocco uniforme di testo
        "--psm 6 --oem 3 -c tessedit_char_whitelist=0123456789",
        
        # PSM 13 è per un singolo testo con orientamento e script liberi
        "--psm 13 --oem 3 -c tessedit_char_whitelist=0123456789"
    ]
    
    # Operazioni morfologiche per pulizia con diversi kernel
    cdef list kernels = [
        np.ones((2, 2), dtype=np.uint8),  # Kernel piccolo
        np.ones((3, 3), dtype=np.uint8),  # Kernel medio
        # Kernel a croce per preservare caratteristiche testo
        np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=np.uint8)
    ]
    
    for method in methods:
        for kernel in kernels:
            # Applicazione morfologia con diversi kernel
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
                        
                        # Verifica che sia un numero e abbia confidenza positiva
                        if text.isdigit() and conf > 0:
                            # Converti in numero
                            recognized_value = int(text)
                            
                            # Verifica limiti in base al tipo di area
                            if slot_number == 1:  # SPN
                                is_valid_value = SPN_MIN <= recognized_value <= SPN_MAX
                            elif slot_number == 2:  # FMI
                                is_valid_value = FMI_MIN <= recognized_value <= FMI_MAX
                            else:
                                is_valid_value = True  # Se il tipo non è specificato, accetta qualsiasi valore
                            
                            # Se il valore è nei limiti, aggiungilo ai gruppi
                            if is_valid_value:
                                if text not in text_groups:
                                    text_groups[text] = []
                                text_groups[text].append({
                                    'text': text,
                                    'conf': conf,
                                    'method': methods.index(method),
                                    'config': configs.index(config)
                                })
                except Exception as e:
                    # Gestione silenziosa degli errori
                    pass
    
    # Sistema di votazione ponderata migliorato
    for text, group in text_groups.items():
        count = len(group)
        avg_conf = sum(r['conf'] for r in group) / count
        
        # Calcolo dello score con fattori aggiuntivi
        text_len = len(text)
        
        # Fattore di lunghezza basato sul tipo
        if slot_number == 1:  # SPN
            # SPNs tipicamente 3-5 cifre
            len_factor = 1.0 if 3 <= text_len <= 5 else 0.7
        elif slot_number == 2:  # FMI
            # FMIs tipicamente 1-2 cifre
            len_factor = 1.0 if 1 <= text_len <= 2 else 0.5
        else:
            # Default
            len_factor = 1.0 if 1 <= text_len <= 6 else 0.5
        
        # Fattore di consistenza - favorisce risultati che appaiono con metodi diversi
        unique_methods = len(set(r['method'] for r in group))
        unique_configs = len(set(r['config'] for r in group))
        consistency_factor = 1.0 + (0.2 * unique_methods) + (0.1 * unique_configs)
        
        # Score finale
        scores[text] = count * (avg_conf ** 2) * len_factor * consistency_factor
    
    # Selezione del miglior risultato
    if scores:
        best_text = max(scores, key=scores.get)
        best_score = scores[best_text]
        
        # Soglia di confidenza adattiva basata sul tipo di area
        if slot_number == 1:  # SPN
            confidence_threshold = 80  # Soglia per SPN
        elif slot_number == 2:  # FMI
            confidence_threshold = 100  # Soglia più alta per FMI (numeri più semplici)
        else:
            confidence_threshold = 90  # Soglia default
        
        if best_score > confidence_threshold:
            return int(best_text)
    
    return None