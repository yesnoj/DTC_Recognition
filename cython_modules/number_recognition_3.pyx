# number_recognition.pyx
import numpy as np
cimport numpy as np
cimport cython
import cv2
import pytesseract
import onnxruntime as ort

# Limiti standard per SPN e FMI secondo i protocolli SAE J1939
cdef:
    int SPN_MIN = 1       # Il valore minimo per SPN è 1
    int SPN_MAX = 524287  # Il valore massimo per SPN è 524287 (2^19-1)
    int FMI_MIN = 0       # Il valore minimo per FMI è 0
    int FMI_MAX = 31      # Il valore massimo per FMI è 31

# Carica il modello ONNX
try:
    # Il modello dovrebbe essere nella stessa directory 
    # o specificare il percorso completo
    model_path = "digit_recognition_model.onnx"
    onnx_session = ort.InferenceSession(model_path)
    model_inputs = onnx_session.get_inputs()
    model_input_shape = model_inputs[0].shape
    # Estrai l'altezza e larghezza attese dal modello
    model_height = model_input_shape[2] if len(model_input_shape) == 4 else 28
    model_width = model_input_shape[3] if len(model_input_shape) == 4 else 28
    print(f"ONNX model loaded successfully. Input shape: {model_input_shape}")
    use_onnx = True
except Exception as e:
    print(f"Failed to load ONNX model: {e}")
    print("Falling back to traditional OCR")
    use_onnx = False

@cython.boundscheck(False)
@cython.wraparound(False)
def segment_digits(np.ndarray[np.uint8_t, ndim=2] img):
    """
    Segmenta i singoli caratteri/cifre nell'immagine
    
    Args:
        img: Immagine in scala di grigi
        
    Returns:
        list: Lista di tuple (immagine della cifra, posizione x)
    """
    # Soglia dell'immagine per trovare i contorni
    _, thresh = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    
    # Trova i contorni
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    # Filtra e ordina i contorni
    digit_regions = []
    for contour in contours:
        # Calcola il rettangolo del contorno
        x, y, w, h = cv2.boundingRect(contour)
        
        # Filtra in base alle dimensioni (per eliminare il rumore)
        if h > 10 and w > 5:  # Dimensioni minime per essere una cifra
            # Estrai la regione della cifra
            digit_img = thresh[y:y+h, x:x+w]
            
            # Aggiungi padding intorno alla cifra
            pad = 4
            digit_padded = np.zeros((h+2*pad, w+2*pad), dtype=np.uint8)
            digit_padded[pad:pad+h, pad:pad+w] = digit_img
            
            # Aggiungi la regione alla lista
            digit_regions.append((digit_padded, x))
    
    # Ordina le regioni da sinistra a destra
    digit_regions.sort(key=lambda r: r[1])
    
    return digit_regions

@cython.boundscheck(False)
@cython.wraparound(False)
def recognize_with_onnx(list digit_regions):
    """
    Riconosce le cifre utilizzando il modello ONNX
    
    Args:
        digit_regions: Lista di tuple (immagine della cifra, posizione x)
        
    Returns:
        str: Numero riconosciuto
    """
    if not digit_regions:
        return None
        
    digits = []
    
    for digit_img, _ in digit_regions:
        # Ridimensiona l'immagine alla dimensione attesa dal modello
        resized = cv2.resize(digit_img, (model_width, model_height))
        
        # Normalizza l'immagine
        normalized = resized.astype(np.float32) / 255.0
        
        # Prepara l'input per il modello
        # Dobbiamo adattarlo al formato di input specifico del modello
        # Tipicamente [batch_size, channels, height, width]
        input_data = np.expand_dims(normalized, axis=0)  # batch_size=1
        input_data = np.expand_dims(input_data, axis=0)  # channels=1 (grayscale)
        
        # Esegui l'inferenza
        try:
            # Ottieni il nome dell'input
            input_name = onnx_session.get_inputs()[0].name
            output_name = onnx_session.get_outputs()[0].name
            
            # Esegui il modello
            result = onnx_session.run([output_name], {input_name: input_data})
            
            # Ottieni la classe predetta (cifra)
            predicted_class = np.argmax(result[0])
            digits.append(str(predicted_class))
        except Exception as e:
            print(f"ONNX inference error: {e}")
            continue
    
    if digits:
        return ''.join(digits)
    return None

@cython.boundscheck(False)
@cython.wraparound(False)
def process_number_area(np.ndarray[np.uint8_t, ndim=3] roi, 
                        display_frame, 
                        int x1, int y1):
    """
    Versione migliorata che utilizza sia ONNX che OCR tradizionale
    """
    cdef:
        np.ndarray[np.uint8_t, ndim=2] roi_gray
        np.ndarray[np.uint8_t, ndim=2] roi_resized
        np.ndarray[np.uint8_t, ndim=2] roi_processed
        list digit_regions
        str recognized_text, result_text
        int recognized_value
                
    # Converti in scala di grigi
    if roi.ndim == 3 and roi.shape[2] == 3:
        roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    elif roi.ndim == 2:
        roi_gray = roi
    else:
        return None
    
    # Preelaborazione base
    roi_resized = cv2.resize(roi_gray, None, fx=3.0, fy=3.0, 
                           interpolation=cv2.INTER_CUBIC)
    
    # Miglioramento contrasto
    roi_enhanced = cv2.convertScaleAbs(roi_resized, alpha=1.8, beta=15)
    
    # Denoise
    roi_processed = cv2.GaussianBlur(roi_enhanced, (5, 5), 0)
    
    # Tentativo con ONNX se disponibile
    if use_onnx:
        try:
            # Segmenta le cifre
            digit_regions = segment_digits(roi_processed)
            
            # Riconosci con ONNX
            recognized_text = recognize_with_onnx(digit_regions)
            
            if recognized_text and recognized_text.isdigit():
                recognized_value = int(recognized_text)
                
                # Verifica che il valore sia valido (SPN o FMI)
                if ((SPN_MIN <= recognized_value <= SPN_MAX) or 
                    (FMI_MIN <= recognized_value <= FMI_MAX)):
                    return recognized_value
        except Exception as e:
            print(f"Error in ONNX processing: {e}")
    
    # Fallback a OCR tradizionale se ONNX fallisce o non è disponibile
    try:
        # Metodi di preprocessing
        methods = [
            roi_processed,
            cv2.threshold(roi_processed, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1],
            cv2.adaptiveThreshold(roi_processed, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                cv2.THRESH_BINARY, 11, 2),
            cv2.threshold(roi_processed, 127, 255, cv2.THRESH_BINARY_INV)[1]
        ]
        
        # Configurazioni OCR
        configs = [
            "--psm 7 --oem 3 -c tessedit_char_whitelist=0123456789",
            "--psm 8 --oem 3 -c tessedit_char_whitelist=0123456789",
            "--psm 10 --oem 3 -c tessedit_char_whitelist=0123456789"
        ]
        
        # Dizionario per tracciare i risultati
        results = {}
        
        for method in methods:
            for config in configs:
                result_text = pytesseract.image_to_string(method, config=config).strip()
                
                if result_text.isdigit():
                    if result_text not in results:
                        results[result_text] = 0
                    results[result_text] += 1
        
        # Trova il risultato più frequente
        best_result = None
        max_count = 0
        
        for text, count in results.items():
            if count > max_count:
                recognized_value = int(text)
                
                # Verifica che sia un valore valido (SPN o FMI)
                if ((SPN_MIN <= recognized_value <= SPN_MAX) or 
                    (FMI_MIN <= recognized_value <= FMI_MAX)):
                    max_count = count
                    best_result = text
        
        if best_result and max_count >= 2:
            return int(best_result)
            
    except Exception as e:
        print(f"Error in OCR processing: {e}")
    
    return None