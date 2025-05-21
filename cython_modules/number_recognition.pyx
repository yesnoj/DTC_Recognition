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
                        int x1, int y1,
                        int threshold_value):
    """
    Processa un'area dell'immagine per riconoscere numeri usando Tesseract con threshold configurabile.
    
    Args:
        roi: Regione di interesse (area dell'immagine)
        display_frame: Frame per visualizzazione
        x1, y1: Coordinate dell'angolo superiore sinistro dell'area
        threshold_value: Valore di threshold per la binarizzazione (0-255)
    
    Returns:
        int: Numero riconosciuto o None se non riconosciuto
    """
    cdef:
        np.ndarray[np.uint8_t, ndim=2] roi_gray
        np.ndarray[np.uint8_t, ndim=2] roi_resized
        np.ndarray[np.uint8_t, ndim=2] roi_binary
        double scale_factor = 4.0
        str result_text
        double best_confidence = 0.0
        int result_value = -1

    # Conversione a scala di grigi
    if roi.ndim == 3 and roi.shape[2] == 3:
        roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    elif roi.ndim == 2:
        roi_gray = roi
    else:
        raise ValueError("Input image must be 2D (grayscale) or 3D (color)")
    
    # Ridimensionamento per migliorare il riconoscimento
    roi_resized = cv2.resize(roi_gray, None, fx=scale_factor, fy=scale_factor, interpolation=cv2.INTER_CUBIC)
    
    # Equalizzazione dell'istogramma per migliorare il contrasto
    roi_equalized = cv2.equalizeHist(roi_resized)
    
    # Applicazione del threshold globale con il valore passato
    _, roi_binary = cv2.threshold(roi_equalized, threshold_value, 255, cv2.THRESH_BINARY)
    
    # Operazioni morfologiche per ridurre il rumore
    kernel = np.ones((2, 2), dtype=np.uint8)
    roi_binary = cv2.morphologyEx(roi_binary, cv2.MORPH_OPEN, kernel)
    roi_binary = cv2.morphologyEx(roi_binary, cv2.MORPH_CLOSE, kernel)
    
    # Configurazioni OCR ottimizzate per numeri
    configs = [
        "--psm 7 --oem 3 -c tessedit_char_whitelist=0123456789",  # Singola riga di testo
        "--psm 8 --oem 3 -c tessedit_char_whitelist=0123456789",  # Singola parola
        "--psm 10 --oem 3 -c tessedit_char_whitelist=0123456789"  # Singolo carattere
    ]
    
    # Prova ciascuna configurazione e prendi il risultato migliore
    for config in configs:
        try:
            # Riconoscimento con Tesseract
            result_data = pytesseract.image_to_data(
                roi_binary,
                config=config,
                output_type=pytesseract.Output.DICT
            )
            
            # Filtraggio risultati
            for j in range(len(result_data['text'])):
                text = result_data['text'][j].strip()
                conf = float(result_data['conf'][j]) if result_data['conf'][j] > 0 else 0
                
                if text.isdigit() and conf > best_confidence:
                    best_confidence = conf
                    result_text = text
        except Exception as e:
            # Gestione silenziosa degli errori
            pass
    
    # Se abbiamo trovato un risultato con confidenza sufficiente
    if best_confidence > 60:  # Soglia di confidenza
        try:
            result_value = int(result_text)
            
            # Aggiungi informazioni di debug al frame di visualizzazione
            height, width = roi.shape[:2]
            cv2.rectangle(display_frame, (x1, y1), (x1 + width, y1 + height), (0, 255, 0), 2)
            cv2.putText(display_frame, f"Value: {result_value} (Conf: {best_confidence:.1f}%)", 
                       (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
            
            return result_value
        except ValueError:
            pass
    
    return None