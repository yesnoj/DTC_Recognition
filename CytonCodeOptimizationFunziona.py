import cv2
import pytesseract
import numpy as np
import can
import time
import tkinter as tk
from tkinter import ttk, filedialog
import threading
from PIL import Image, ImageTk
import re
import csv
import sys
import os
import time

START_TIME = time.time()
TIME_LOGS = []  # Lista per memorizzare i log temporanei

# Costanti SAE J1939 per validazione
SPN_MIN = 1       # Il valore minimo per SPN è 1
SPN_MAX = 524287  # Il valore massimo per SPN è 524287 (2^19-1)
FMI_MIN = 0       # Il valore minimo per FMI è 0
FMI_MAX = 31      # Il valore massimo per FMI è 31

# Set Tesseract path
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
sys.path.append(os.path.dirname(os.path.abspath(__file__)) + '/cython_modules')

def log_time(message):
    """Utility per loggare il tempo trascorso dall'inizio dell'applicazione"""
    elapsed = time.time() - START_TIME
    formatted = f"TIMING: {message} - {elapsed:.2f} secondi dall'avvio"
    
    # Invece di chiamare log_message direttamente, memorizziamo il messaggio
    TIME_LOGS.append(formatted)
    
    # Se output_text esiste, possiamo inviare anche lì
    if 'output_text' in globals() and output_text:
        try:
            output_text.insert(tk.END, formatted + "\n")
            output_text.see(tk.END)
        except:
            pass

def resource_path(relative_path):
    """ Ottiene il percorso corretto per le risorse, che funziona per dev e per .exe """
    try:
        # PyInstaller crea una cartella temporanea e memorizza il percorso in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)



class AppState:
    def __init__(self):
        # Webcam & frame variables
        self.cap = None
        self.selected_camera = 0
        self.frame = None
        self.current_frame = None
        self.areas = []  # [(x1, y1, x2, y2, type, slot_number)]
        self.area_slots = [False, False]  # Slots for number areas
        self.lamp_slots = [False, False]  # Slots for lamp areas
        self.last_recognition_values = None
        
        # Parametri webcam diretti
        self.webcam_contrast = 20
        self.webcam_saturation = 0
        self.webcam_exposure = -8
        self.webcam_focus = 73 
        self.webcam_initialized = False
        
        # Proprietà per la Live View
        self.live_view_active = False
        self.slider_changed = False
        
        # OCR threshold per il riconoscimento numeri
        self.ocr_threshold = 240
        
        # Manteniamo solo il threshold per le lampade
        self.lamp_threshold = 10
        
        # Riferimento al pannello di threshold preview
        self.threshold_preview_panel = None
        
        # Resolution settings
        self.selected_resolution = "800x600"
        self.resolution_options = [
            "640x480",   # VGA (balanced default value)
            "800x600",   # SVGA
        ]
        
        # CAN communication
        self.can_message_counter = 1
        self.waiting_for_can = False
        self.ecff_received = False
        self.running = False
        
        # UI components
        self.preview_btn = None
        self.start_btn = None
        self.stop_btn = None
        self.clear_log_btn = None
        self.dtc_frame = None
        
        
        # Drawing state
        self.drawing = False

        self.canalyzer_is_processing = False
        self.canalyzer_last_message = None
        self.canalyzer_last_message = None

        self.canalyzer_scheduled_timer = None
        self.message_to_process = None

        self.canalyzer_last_processed_message = None
        self.canalyzer_is_acquisition_scheduled = False

        self.asc_playback_active = False
        self.asc_loop_playback = False
        
        # Countdown variables
        self.countdown_active = False
        self.countdown_label = None
        self.countdown_value = 0


        # DTC CSV e test variables
        self.csv_file_path = None
        self.csv_data = []
        self.current_dtc_index = 0
        self.dm1_thread = None
        self.dm1_thread_running = False
        self.dm1_paused = False
        self.dm1_counter = 1
        self.is_canalyzer_mode = True  # Default in modalità Canalyzer
        
        # Risultati dei test
        self.errors_found = 0

        self.live_preview_during_recognition = False  # Flag per abilitare/disabilitare l'anteprima durante il riconoscimento
        self.preview_running = False  # Flag per indicare se l'anteprima è in esecuzione


# Initialize app state
app = AppState()

# ====== Funzioni per il controllo della webcam ======
def update_button_states(state):
    """
    Update button states based on current application state.
    
    Parameters:
        state: String indicating the current state ('initial', 'preview', 'start', 'stop')
    """
    # Il pulsante Preview è sempre attivo in tutti gli stati
    app.preview_btn.config(state=tk.NORMAL)
    
    if state == 'initial':
        # Stato iniziale - tutti i tasti speciali disabilitati
        app.start_btn.config(state=tk.DISABLED)
        app.stop_btn.config(state=tk.DISABLED)
        app.clear_log_btn.config(state=tk.NORMAL)
    
    elif state == 'preview':
        # Stato di preview - abilita Start solo se ci sono aree selezionate
        if app.areas:
            app.start_btn.config(state=tk.NORMAL)
        else:
            app.start_btn.config(state=tk.DISABLED)
            log_message("No areas selected. Start button is disabled.")
        
        app.stop_btn.config(state=tk.DISABLED)
    
    elif state == 'start':
        # Stato di acquisizione in corso
        app.start_btn.config(state=tk.DISABLED)
        app.stop_btn.config(state=tk.NORMAL)
    
    elif state == 'stop':
        # Stato dopo interruzione
        # Abilita il pulsante Start solo se ci sono aree
        if app.areas:
            app.start_btn.config(state=tk.NORMAL)
        else:
            app.start_btn.config(state=tk.DISABLED)
            log_message("No areas selected. Start button is disabled.")
        
        app.stop_btn.config(state=tk.DISABLED)
    
    # Log per debug
    #log_message(f"Button states updated: {state}")


# ====== Logging Helper ======
def clear_log():
    """Funzione dedicata per cancellare completamente il log senza aggiungere messaggi"""
    output_text.delete(1.0, tk.END)

def log_message(message, clear=False, error=False):
    """Centralized logging function to add messages to the output text area"""
    if clear:
        output_text.delete(1.0, tk.END)
        # Se il messaggio è vuoto, non continuare ad aggiungere nulla
        if not message:
            return
    
    # Get current timestamp with date and time
    current_time = time.strftime("%H:%M:%S", time.localtime())
    
    # Format message with timestamp
    formatted_message = f"[{current_time}] {message}\n"
    
    # Insert at the end of the text
    output_text.insert(tk.END, formatted_message)
    
    # Keep a maximum number of lines (e.g. 500)
    # to avoid excessive memory usage
    total_lines = int(output_text.index('end-1c').split('.')[0])
    if total_lines > 500:
        # Remove first lines if limit is exceeded
        output_text.delete('1.0', f'{total_lines - 500}.0')
    
    # Auto-scroll to the end
    output_text.see(tk.END)

def save_log_to_file():
    """Saves the current log content to a text file"""
    try:
        # Ask user for file name and location
        file_path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            title="Save Log As"
        )
        
        if file_path:
            # Get current log content
            log_content = output_text.get(1.0, tk.END)
            
            # Write to file
            with open(file_path, 'w', encoding='utf-8') as file:
                file.write(log_content)
            
            # Log the successful save
            log_message(f"Log saved to: {file_path}")
    except Exception as e:
        log_message(f"Error saving log: {str(e)}")


def auto_save_log():
    """Salva automaticamente il log in un file con timestamp"""
    try:
        # Crea un timestamp nel formato YYYYMMDD_HHMMSS
        timestamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
        
        # Crea il nome del file con timestamp
        filename = f"dtc_test_log_{timestamp}.txt"
        
        # Crea la directory logs se non esiste
        logs_dir = "logs"
        if not os.path.exists(logs_dir):
            os.makedirs(logs_dir)
        
        # Percorso completo del file
        file_path = os.path.join(logs_dir, filename)
        
        # Ottieni il contenuto del log
        log_content = output_text.get(1.0, tk.END)
        
        # Scrivi il contenuto nel file
        with open(file_path, 'w', encoding='utf-8') as file:
            file.write(log_content)
        
        # Log di conferma
        log_message(f"Log saved automatically to: {file_path}")
        return file_path
    except Exception as e:
        log_message(f"Error saving log automatically: {str(e)}")
        return None


# ====== Camera Management ======
def list_cameras():
    """Lists available webcam devices"""
    #log_time("Inizio list_cameras")
    available = []
    for index in range(2):
        try:
            log_time(f"Tentativo apertura webcam {index}")
            cap = cv2.VideoCapture(index)
            if cap.isOpened():
                ret, _ = cap.read()
                if ret:
                    available.append(f"Webcam {index}")
                cap.release()
            log_time(f"Fine tentativo webcam {index}")
        except:
            continue
    #log_time("Fine list_cameras")
    return available

def list_cameras_light():
    """Versione leggera che non verifica effettivamente le webcam all'avvio"""
    #log_time("Usando list_cameras_light (senza test)")
    # Questo metodo semplicemente elenca le potenziali webcam
    # L'utente dovrà selezionare quella funzionante
    return ["Webcam 0", "Webcam 1"]

def set_camera_resolution(cap, resolution_str):
    """Sets the specified resolution on the webcam"""
    if cap is None or not cap.isOpened():
        return False
    
    try:
        width, height = map(int, resolution_str.split('x'))
        
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        
        actual_width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        actual_height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        
        log_message(f"Requested resolution: {width}x{height}, Set: {int(actual_width)}x{int(actual_height)}")
        
        return abs(width - actual_width) < 50 and abs(height - actual_height) < 50
    except Exception as e:
        log_message(f"Error setting resolution: {e}")
        return False


# ====== Approccio semplificato per Live View ======

def update_live_view():
    """Aggiorna la visualizzazione live un frame alla volta senza overlay"""
    if not hasattr(app, 'live_view_active') or not app.live_view_active:
        return
    
    if app.cap is None or not app.cap.isOpened():
        log_message("Webcam not available")
        app.live_view_active = False
        live_view_btn.config(text="Start Live View", bg="#8cff8c")
        return
    
    try:
        # Leggi un frame
        ret, frame = app.cap.read()
        if not ret or frame is None:
            log_message("Impossible read frame from webcam")
            app.live_view_active = False
            live_view_btn.config(text="Start Live View", bg="#8cff8c")
            return
        
        # Applica le impostazioni correnti se uno slider è stato modificato
        if hasattr(app, 'slider_changed') and app.slider_changed:
            try:
                update_webcam_contrast(webcam_contrast_slider.get())
                update_webcam_saturation(webcam_saturation_slider.get())
                update_webcam_exposure(webcam_exposure_slider.get())
                update_webcam_focus(webcam_focus_slider.get())
                app.slider_changed = False
            except Exception as e:
                log_message(f"Error updating parameters: {str(e)}")
        
        # Mostra il frame nel pannello esistente senza overlay
        display_frame_in_panel(frame)
        
        # Aggiorna anche la threshold preview
        update_threshold_preview()
        
    except Exception as e:
        log_message(f"Live view error: {str(e)}")
    finally:
        # Programma il prossimo aggiornamento solo se la live view è ancora attiva
        if hasattr(app, 'live_view_active') and app.live_view_active:
            root.after(50, update_live_view)  # Aggiorna ogni 50ms (circa 20 fps)



# Funzione per attivare/disattivare Live Preview durante il riconoscimento
def toggle_live_preview_during_recognition(enabled):
    """Attiva o disattiva la visualizzazione live durante il riconoscimento"""
    app.live_preview_during_recognition = enabled
    log_message(f"Live Preview During Recognition {'Enabled' if enabled else 'Disabled'}")
    
    # Se il riconoscimento è già attivo, avvia o ferma l'anteprima
    if app.running:
        if enabled and not app.preview_running:
            start_continuous_preview()
        elif not enabled and app.preview_running:
            stop_continuous_preview()

# Funzione per avviare l'anteprima continua
def start_continuous_preview():
    """Avvia un ciclo continuo di acquisizione e visualizzazione dei frame dalla webcam"""
    if not hasattr(app, 'live_preview_during_recognition') or not app.live_preview_during_recognition or not app.running:
        if hasattr(app, 'preview_running'):
            app.preview_running = False
        return
    
    # Se è la prima volta che viene chiamata, aggiungi un log
    if not hasattr(app, 'preview_running') or not app.preview_running:
        log_message("Live Preview activated during recognition")
    
    app.preview_running = True
    
    # Assicurati che la webcam sia aperta
    if app.cap is None or not app.cap.isOpened():
        try:
            app.cap = cv2.VideoCapture(app.selected_camera, cv2.CAP_DSHOW)
            if not app.cap.isOpened():
                log_message("Impossible to open webcam for Live View")
                app.preview_running = False
                return
            
            # Imposta la risoluzione
            set_camera_resolution(app.cap, app.selected_resolution)
            
            # Applica i parametri della webcam
            update_webcam_contrast(webcam_contrast_slider.get())
            update_webcam_saturation(webcam_saturation_slider.get())
            update_webcam_exposure(webcam_exposure_slider.get())
            update_webcam_focus(webcam_focus_slider.get())
        except Exception as e:
            log_message(f"Webcam initializing error: {str(e)}")
            app.preview_running = False
            return
    
    try:
        # Leggi un frame dalla webcam
        ret, frame = app.cap.read()
        
        if ret:
            # Crea una copia del frame per non interferire con il processo di riconoscimento
            display_frame = frame.copy()
            
            # Ottieni il threshold delle lampade
            lamp_threshold = app.lamp_threshold if hasattr(app, 'lamp_threshold') else lamp_threshold_slider.get()
            
            # Aggiungi barra informativa in alto
            height, width = display_frame.shape[:2]
            bar_height = 30
            cv2.rectangle(display_frame, (0, 0), (width, bar_height), (0, 0, 0), -1)
            
            # Ottieni i valori attuali della webcam
            brightness = app.cap.get(cv2.CAP_PROP_BRIGHTNESS) if app.cap else 0
            
            # Aggiungi il testo con i valori di base
            info_text = f"LIVE - Lamp Threshold: {lamp_threshold}"
            cv2.putText(display_frame, info_text, (10, 20), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            
            # Array per memorizzare le luminosità delle lampade
            lamp_luminosities = []
            
            # Mostra le aree selezionate sul frame
            for area in app.areas:
                x1, y1, x2, y2, area_type, slot_number = area
                x1, x2 = min(x1, x2), max(x1, x2)
                y1, y2 = min(y1, y2), max(y1, y2)
                
                # Colore del rettangolo: verde per le aree numeriche, blu per le lampade
                color = (0, 255, 0) if area_type == "Number" else (255, 0, 0)
                cv2.rectangle(display_frame, (x1, y1), (x2, y2), color, 2)
                
                # Estrai l'area di interesse
                roi = frame[y1:y2, x1:x2]
                
                # Aggiunta di etichette
                if area_type == "Lamp":
                    lamp_name = "Amber" if slot_number == 1 else "Red"
                    
                    # Calcola la luminosità della lampada
                    if roi.size > 0:
                        avg_lamp = np.mean(roi, axis=(0,1)).astype(int).tolist()
                        luminosity = 0.299*avg_lamp[2] + 0.587*avg_lamp[1] + 0.114*avg_lamp[0]
                        is_bright = luminosity > lamp_threshold
                        
                        # Memorizza la luminosità per mostrarla nella barra in alto
                        lamp_luminosities.append((lamp_name, luminosity, is_bright))
                        
                        # Colore del rettangolo in base allo stato della lampada
                        rect_color = (0, 255, 0) if is_bright else (0, 0, 255)
                        cv2.rectangle(display_frame, (x1, y1), (x2, y2), rect_color, 2)
                        
                        
                        # Testo con informazioni sulla lampada
                        lamp_info = f"Lamp {slot_number} ({lamp_name}): L:{int(luminosity)} ({'ON' if is_bright else 'OFF'})"
                        cv2.putText(display_frame, lamp_info, (x1, y1-5), 
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                    else:
                        cv2.putText(display_frame, f"Lamp {slot_number} ({lamp_name})", (x1, y1-5), 
                                  cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
                else:  # Number area
                    area_name = "SPN" if slot_number == 1 else "FMI"
                    
                    # Se abbiamo un valore riconosciuto, mostralo
                    recognized_value = None
                    if hasattr(app, 'last_recognition_values') and app.last_recognition_values:
                        if slot_number == 1:  # SPN
                            recognized_value = app.last_recognition_values.get('SPN')
                        elif slot_number == 2:  # FMI
                            recognized_value = app.last_recognition_values.get('FMI')
                    
                    if recognized_value is not None:
                        value_text = f"Area {slot_number} ({area_name}): {recognized_value}"
                        cv2.putText(display_frame, value_text, (x1, y1-5), 
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                    else:
                        cv2.putText(display_frame, f"Area {slot_number} ({area_name})", (x1, y1-5), 
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
            
            # Aggiungi informazioni delle lampade nella barra superiore, se disponibili
            if lamp_luminosities:
                lamp_info_text = " | ".join([f"{name}: {int(lum)} ({('ON' if is_on else 'OFF')})" 
                                           for name, lum, is_on in lamp_luminosities])
                
                # Calcola la posizione per allineare a destra
                text_size = cv2.getTextSize(lamp_info_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]
                info_x = max(width - text_size[0] - 10, width // 2)
                
                cv2.putText(display_frame, lamp_info_text, (info_x, 20), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                        
            # Visualizza il frame nel pannello
            display_frame_in_panel(display_frame)
    except Exception as e:
        log_message(f"Error during live preview: {str(e)}")
    
    # Programma il prossimo aggiornamento solo se l'anteprima è ancora attiva
    if hasattr(app, 'preview_running') and app.preview_running:
        root.after(50, start_continuous_preview)  # Aggiorna ogni 50ms (circa 20 fps)

def stop_continuous_preview():
    """Ferma il ciclo di anteprima continua"""
    app.preview_running = False
    log_message("Live Preview stopped")


def toggle_live_view():
    """Avvia o ferma la visualizzazione live della webcam"""
    global app
    
    # Se la live view è già attiva, fermala
    if hasattr(app, 'live_view_active') and app.live_view_active:
        app.live_view_active = False
        live_view_btn.config(text="Start Live View", bg="#8cff8c")
        app.preview_btn.config(state=tk.NORMAL)
        log_message("Live View stopped")
        return
    
    # Altrimenti, avvia la live view
    # Blocca ogni altra acquisizione in corso
    if app.running:
        log_message("Stop acquisition before start Live View")
        stop_recognition()
        time.sleep(0.5)
    
    # Inizializza la webcam con la funzione delayed
    if not initialize_webcam_delayed(app):
        log_message("Errore: impossibile inizializzare la webcam per Live View")
        return
    
    # Aggiorna l'interfaccia
    live_view_btn.config(text="Stop Live View", bg="#ff8c8c")  # Rosso chiaro
    app.preview_btn.config(state=tk.DISABLED)
    
    # Attiva la live view
    app.live_view_active = True
    
    # Avvia il ciclo di aggiornamento
    update_live_view()
    
    log_message("Live View started. Set webcam parameters")



def display_frame_in_panel(frame):
    """Visualizza l'immagine nel pannello mantenendo le proporzioni corrette"""
    if frame is None:
        return
        
    # Ottieni le dimensioni del pannello e del frame
    panel_width = recognized_frame_panel.winfo_width()
    panel_height = recognized_frame_panel.winfo_height()
    
    # Se il pannello non è ancora stato inizializzato, usa valori di default
    if panel_width <= 1:
        panel_width = 640
    if panel_height <= 1:
        panel_height = 480
    
    frame_height, frame_width = frame.shape[:2]
    
    # Calcola il rapporto d'aspetto
    frame_ratio = frame_width / frame_height
    panel_ratio = panel_width / panel_height
    
    # Ridimensiona mantenendo le proporzioni
    if frame_ratio > panel_ratio:  # L'immagine è più larga del pannello
        new_width = panel_width
        new_height = int(panel_width / frame_ratio)
    else:  # L'immagine è più alta del pannello
        new_height = panel_height
        new_width = int(panel_height * frame_ratio)
    
    # Ridimensiona l'immagine
    resized = cv2.resize(frame, (new_width, new_height), interpolation=cv2.INTER_AREA)
    
    # Crea un'immagine canvas delle dimensioni del pannello
    canvas = np.zeros((panel_height, panel_width, 3), dtype=np.uint8)
    
    # Centra l'immagine ridimensionata sul canvas
    y_offset = (panel_height - new_height) // 2
    x_offset = (panel_width - new_width) // 2
    
    # Assicurati che gli offset siano non negativi e che non ci siano overflow
    y_offset = max(0, y_offset)
    x_offset = max(0, x_offset)
    
    # Copia l'immagine ridimensionata sul canvas
    canvas[y_offset:y_offset+new_height, x_offset:x_offset+new_width] = resized
    
    # Converti per Tkinter
    img_rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
    img = Image.fromarray(img_rgb)
    imgtk = ImageTk.PhotoImage(image=img)
    
    recognized_frame_panel.imgtk = imgtk
    recognized_frame_panel.configure(image=imgtk)

def update_webcam_contrast(value):
    """Aggiorna il valore di contrasto della webcam"""
    app.slider_changed = True
    if app.cap is not None and app.cap.isOpened():
        app.cap.set(cv2.CAP_PROP_CONTRAST, float(value))
        actual_value = app.cap.get(cv2.CAP_PROP_CONTRAST)
        log_message(f"Webcam contrast set to {value}, actual value: {actual_value}")
        return actual_value
    return None

def update_webcam_saturation(value):
    """Aggiorna il valore di saturazione della webcam"""
    app.slider_changed = True
    if app.cap is not None and app.cap.isOpened():
        app.cap.set(cv2.CAP_PROP_SATURATION, float(value))
        actual_value = app.cap.get(cv2.CAP_PROP_SATURATION)
        log_message(f"Webcam saturation set to {value}, actual value: {actual_value}")
        return actual_value
    return None

def update_webcam_exposure(value):
    app.slider_changed = True
    """Aggiorna il valore di esposizione della webcam"""
    if app.cap is not None and app.cap.isOpened():
        # Converte il valore dello slider al valore di esposizione effettivo
        # L'esposizione è solitamente rappresentata in valori negativi per la webcam
        actual_value = app.cap.set(cv2.CAP_PROP_EXPOSURE, float(value))
        actual_value = app.cap.get(cv2.CAP_PROP_EXPOSURE)
        log_message(f"Webcam exposure set to {value}, actual value: {actual_value}")
        return actual_value
    return None


def update_webcam_focus(value):
    """
    Aggiorna immediatamente la messa a fuoco della webcam quando lo slider cambia
    Questo sarà l'ultimo parametro che verrà applicato all'immagine per il riconoscimento
    """
    # Aggiorna il flag di modifica slider
    app.slider_changed = True
    
    # Aggiorna il valore di focus nell'app state
    app.webcam_focus = int(value)
    
    if app.cap is not None and app.cap.isOpened():
        try:
            # Imposta la messa a fuoco manuale
            app.cap.set(cv2.CAP_PROP_FOCUS, float(value))
            
            # Verifica il valore effettivamente impostato
            actual_value = app.cap.get(cv2.CAP_PROP_FOCUS)
            log_message(f"Webcam focus set to {value}, actual value: {actual_value}")
        except Exception as e:
            log_message(f"Error setting webcam focus: {str(e)}")


def update_ocr_threshold(value):
    """Aggiorna il valore di threshold per il riconoscimento OCR e aggiorna la preview"""
    app.ocr_threshold = int(value)
    app.slider_changed = True
    
    # Aggiorna la preview della threshold se la live view è attiva
    if hasattr(app, 'live_view_active') and app.live_view_active:
        update_threshold_preview()

def update_threshold_preview():
    """Aggiorna la visualizzazione dell'effetto della threshold per OCR"""
    # Anche se Live View non è attiva, prova comunque a fare l'aggiornamento
    # se è stata appena selezionata un'area numerica
    has_number_areas = any(area[4] == "Number" for area in app.areas if len(area) >= 5)
    
    if not (hasattr(app, 'live_view_active') and app.live_view_active) and not has_number_areas:
        return
    
    # Se non c'è una connessione attiva alla webcam, prova ad aprirla
    if app.cap is None or not app.cap.isOpened():
        try:
            initialize_webcam_delayed(app)
            if app.cap is None or not app.cap.isOpened():
                return
        except:
            return
    
    try:
        # Leggi un frame dalla webcam
        ret, frame = app.cap.read()
        if not ret or frame is None:
            return
        
        # Estrai il valore di threshold corrente
        threshold_value = app.ocr_threshold
        
        # Crea una copia del frame per la preview della threshold
        display_frame = np.zeros_like(frame)
        
        # Flag per verificare se ci sono aree numeriche
        number_areas_found = False
        number_areas = []
        
        # Raccogli prima tutte le aree numeriche
        for area in app.areas:
            if len(area) < 6 or area[4] != "Number":
                continue
            
            number_areas_found = True
            slot_number = area[5]
            
            # Usa le coordinate memorizzate se disponibili, altrimenti quelle dell'area
            if hasattr(app, 'ocr_areas') and slot_number in app.ocr_areas:
                x1, y1, x2, y2 = app.ocr_areas[slot_number]
            else:
                x1, y1, x2, y2, _, _ = area
                x1, x2 = min(x1, x2), max(x1, x2)
                y1, y2 = min(y1, y2), max(y1, y2)
            
            number_areas.append((x1, y1, x2, y2, slot_number))
        
        # Se ci sono aree numeriche, creiamo un layout che le mostri tutte
        if number_areas_found:
            # Crea un nuovo frame nero per la visualizzazione
            display_frame = np.zeros_like(frame)
            
            # Se c'è solo un'area, mostrala centrata e ingrandita
            if len(number_areas) == 1:
                x1, y1, x2, y2, slot_number = number_areas[0]
                width = x2 - x1
                height = y2 - y1
                
                roi = frame[y1:y2, x1:x2]
                if roi.size > 0:
                    # Elabora l'area come prima
                    roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
                    scale_factor = 4.0
                    roi_resized = cv2.resize(roi_gray, None, fx=scale_factor, fy=scale_factor, interpolation=cv2.INTER_CUBIC)
                    roi_equalized = cv2.equalizeHist(roi_resized)
                    _, roi_binary = cv2.threshold(roi_equalized, threshold_value, 255, cv2.THRESH_BINARY)
                    kernel = np.ones((2, 2), dtype=np.uint8)
                    roi_binary = cv2.morphologyEx(roi_binary, cv2.MORPH_OPEN, kernel)
                    roi_binary = cv2.morphologyEx(roi_binary, cv2.MORPH_CLOSE, kernel)
                    roi_color = cv2.cvtColor(roi_binary, cv2.COLOR_GRAY2BGR)
                    
                    # Mostra l'area centrata e ingrandita
                    zoom_factor = 3.0
                    new_width = int(width * zoom_factor)
                    new_height = int(height * zoom_factor)
                    
                    display_height, display_width = display_frame.shape[:2]
                    center_x = display_width // 2
                    center_y = display_height // 2
                    
                    new_x1 = max(0, center_x - new_width // 2)
                    new_y1 = max(0, center_y - new_height // 2)
                    new_x2 = min(display_width, new_x1 + new_width)
                    new_y2 = min(display_height, new_y1 + new_height)
                    
                    zoomed_roi = cv2.resize(roi_color, (new_width, new_height), interpolation=cv2.INTER_NEAREST)
                    
                    # Inserisci l'immagine ingrandita
                    display_frame[new_y1:new_y2, new_x1:new_x2] = zoomed_roi[:new_y2-new_y1, :new_x2-new_x1]
                    
                    # Disegna un rettangolo verde attorno all'area
                    cv2.rectangle(display_frame, (new_x1, new_y1), (new_x2, new_y2), (0, 255, 0), 2)
                    
                    # Aggiungi testo con informazioni sull'area e sul threshold
                    area_name = "SPN" if slot_number == 1 else "FMI"
                    text = f"{area_name} Area - Threshold: {threshold_value}"
                    
                    cv2.putText(display_frame, text, (new_x1, new_y1-10), 
                               cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            
            # Se ci sono multiple aree, mostrale in un layout a griglia
            else:
                # Dividi lo schermo in due parti
                display_height, display_width = display_frame.shape[:2]
                
                # Processa ogni area e posizionala nella griglia
                for i, (x1, y1, x2, y2, slot_number) in enumerate(number_areas):
                    width = x2 - x1
                    height = y2 - y1
                    
                    roi = frame[y1:y2, x1:x2]
                    if roi.size > 0:
                        # Elabora l'area
                        roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
                        scale_factor = 4.0
                        roi_resized = cv2.resize(roi_gray, None, fx=scale_factor, fy=scale_factor, interpolation=cv2.INTER_CUBIC)
                        roi_equalized = cv2.equalizeHist(roi_resized)
                        _, roi_binary = cv2.threshold(roi_equalized, threshold_value, 255, cv2.THRESH_BINARY)
                        kernel = np.ones((2, 2), dtype=np.uint8)
                        roi_binary = cv2.morphologyEx(roi_binary, cv2.MORPH_OPEN, kernel)
                        roi_binary = cv2.morphologyEx(roi_binary, cv2.MORPH_CLOSE, kernel)
                        roi_color = cv2.cvtColor(roi_binary, cv2.COLOR_GRAY2BGR)
                        
                        # Calcola la posizione nell'immagine
                        if i == 0:  # Prima area (solitamente SPN) - in alto
                            pos_y = display_height // 4 - height
                        else:  # Seconda area (solitamente FMI) - in basso
                            pos_y = 3 * display_height // 4 - height
                        
                        # Posiziona al centro orizzontalmente
                        pos_x = display_width // 2 - width
                        
                        # Ridimensiona per visualizzazione
                        zoom_factor = 2.5
                        new_width = int(width * zoom_factor)
                        new_height = int(height * zoom_factor)
                        
                        # Calcola posizione finale
                        new_x1 = max(0, pos_x)
                        new_y1 = max(0, pos_y)
                        new_x2 = min(display_width, new_x1 + new_width)
                        new_y2 = min(display_height, new_y1 + new_height)
                        
                        zoomed_roi = cv2.resize(roi_color, (new_width, new_height), interpolation=cv2.INTER_NEAREST)
                        
                        # Inserisci l'immagine nella posizione calcolata
                        try:
                            display_frame[new_y1:new_y2, new_x1:new_x2] = zoomed_roi[:new_y2-new_y1, :new_x2-new_x1]
                        except:
                            # In caso di errore di dimensioni, mostra un'area vuota con messaggio
                            cv2.rectangle(display_frame, (new_x1, new_y1), (new_x2, new_y2), (0, 0, 255), 2)
                        
                        # Disegna rettangolo e etichetta
                        cv2.rectangle(display_frame, (new_x1, new_y1), (new_x2, new_y2), (0, 255, 0), 2)
                        
                        area_name = "SPN" if slot_number == 1 else "FMI"
                        text = f"{area_name} Area - Threshold: {threshold_value}"
                        
                        cv2.putText(display_frame, text, (new_x1, new_y1-10), 
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        
        # Se non ci sono aree numeriche, mostra comunque un'anteprima della threshold sull'intero frame
        else:
            # Converti l'intero frame in scala di grigi
            frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
            # Equalizzazione dell'istogramma per migliorare il contrasto
            frame_equalized = cv2.equalizeHist(frame_gray)
            
            # Applicazione del threshold binario
            _, frame_binary = cv2.threshold(frame_equalized, threshold_value, 255, cv2.THRESH_BINARY)
            
            # Operazioni morfologiche per ridurre il rumore
            kernel = np.ones((2, 2), dtype=np.uint8)
            frame_binary = cv2.morphologyEx(frame_binary, cv2.MORPH_OPEN, kernel)
            frame_binary = cv2.morphologyEx(frame_binary, cv2.MORPH_CLOSE, kernel)
            
            # Converti in immagine a colori per visualizzazione
            display_frame = cv2.cvtColor(frame_binary, cv2.COLOR_GRAY2BGR)
            
            # Aggiungi testo informativo
            cv2.putText(display_frame, f"Full Frame Threshold: {threshold_value}", (30, 50), 
                      cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        
        # Visualizza il frame con la threshold applicata
        display_threshold_preview(display_frame)
    
    except Exception as e:
        # Log dell'errore per debug
        log_message(f"Errore in update_threshold_preview: {str(e)}")
        import traceback
        log_message(traceback.format_exc())

def display_threshold_preview(frame):
    """Visualizza il frame con threshold applicata nel pannello di preview"""
    if frame is None:
        return
    
    # Se il pannello non esiste, crealo
    if not hasattr(app, 'threshold_preview_panel') or app.threshold_preview_panel is None:
        return
    
    # Ottieni le dimensioni del pannello
    panel_width = app.threshold_preview_panel.winfo_width()
    panel_height = app.threshold_preview_panel.winfo_height()
    
    # Se il pannello non è ancora stato inizializzato, usa valori di default
    if panel_width <= 1:
        panel_width = 640
    if panel_height <= 1:
        panel_height = 240  # Altezza ridotta per il pannello di threshold
    
    frame_height, frame_width = frame.shape[:2]
    
    # Calcola il rapporto d'aspetto
    frame_ratio = frame_width / frame_height
    panel_ratio = panel_width / panel_height
    
    # Ridimensiona mantenendo le proporzioni
    if frame_ratio > panel_ratio:  # L'immagine è più larga del pannello
        new_width = panel_width
        new_height = int(panel_width / frame_ratio)
    else:  # L'immagine è più alta del pannello
        new_height = panel_height
        new_width = int(panel_height * frame_ratio)
    
    # Ridimensiona l'immagine
    resized = cv2.resize(frame, (new_width, new_height), interpolation=cv2.INTER_AREA)
    
    # Crea un'immagine canvas delle dimensioni del pannello
    canvas = np.zeros((panel_height, panel_width, 3), dtype=np.uint8)
    
    # Centra l'immagine ridimensionata sul canvas
    y_offset = (panel_height - new_height) // 2
    x_offset = (panel_width - new_width) // 2
    
    # Assicurati che gli offset siano non negativi e che non ci siano overflow
    y_offset = max(0, y_offset)
    x_offset = max(0, x_offset)
    
    # Copia l'immagine ridimensionata sul canvas
    canvas[y_offset:y_offset+new_height, x_offset:x_offset+new_width] = resized
    
    # Converti per Tkinter
    img_rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
    img = Image.fromarray(img_rgb)
    imgtk = ImageTk.PhotoImage(image=img)
    
    app.threshold_preview_panel.imgtk = imgtk
    app.threshold_preview_panel.configure(image=imgtk)

def update_selected_camera(event):
    """Handles the change of selected camera"""
    selection = camera_listbox.get()
    if selection:
        new_camera = int(selection.split()[-1])
        # Se è cambiata effettivamente la selezione
        if new_camera != app.selected_camera:
            app.selected_camera = new_camera
            # Importante: resetta il flag di inizializzazione per forzare la reinizializzazione
            app.webcam_initialized = False
            # Se la webcam è aperta, chiudila
            if app.cap is not None and app.cap.isOpened():
                app.cap.release()
                app.cap = None
            log_message(f"Webcam changed to {selection}, will be initialized on next use")


def update_selected_resolution(event):
    """Handles the change of selected resolution"""
    resolution = resolution_combobox.get()
    if resolution != app.selected_resolution:
        app.selected_resolution = resolution
        log_message(f"Selected resolution: {app.selected_resolution}")
        
        # Resetta il flag di inizializzazione per reinizializzare alla prossima apertura
        app.webcam_initialized = False
        
        # If the webcam is already open, update the resolution
        if app.cap is not None and app.cap.isOpened():
            log_message("Closing Webcam  for resolution updated, will be initialized on next use")
            app.cap.release()
            app.cap = None



def initialize_webcam(app):
    """
    Inizializza la webcam con ottimizzazioni specifiche per Logitech C920
    Sostituisce l'inizializzazione standard per migliorare le prestazioni
    """
    #log_time("Inizio initialize_webcam")
    log_message("Inizializzazione webcam ottimizzata in corso...")
    start_time = time.time()
    
    try:
        # Se la webcam è già aperta, chiudila
        if app.cap is not None and app.cap.isOpened():
            app.cap.release()
            app.cap = None
            #log_time("Webcam precedente chiusa")
        
        # Usa sempre DirectShow su Windows per migliorare prestazioni e compatibilità
        #log_time("Prima di VideoCapture")
        app.cap = cv2.VideoCapture(app.selected_camera, cv2.CAP_DSHOW)
        #log_time("Dopo VideoCapture")
        
        if not app.cap.isOpened():
            log_message(f"Errore: impossibile aprire la webcam {app.selected_camera}")
            #log_time("Errore apertura webcam")
            return False
            
        # Imposta la risoluzione selezionata
        width, height = map(int, app.selected_resolution.split('x'))
        app.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        app.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        #log_time("Dopo impostazione risoluzione")
        
        # Ottimizzazioni aggiuntive per le webcam, specialmente per Logitech C920
        app.cap.set(cv2.CAP_PROP_FPS, 30)             # Frame rate standard
        app.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)       # Buffer ridotto, frame più recenti
        app.cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)        # Disabilita autofocus iniziale
        #log_time("Dopo impostazioni ottimizzazione webcam")
        
        # Applica i controlli diretti della webcam
        update_webcam_contrast(webcam_contrast_slider.get())
        update_webcam_saturation(webcam_saturation_slider.get())
        update_webcam_exposure(webcam_exposure_slider.get())
        update_webcam_focus(webcam_focus_slider.get())
        #log_time("Dopo impostazione parametri webcam")
        
        # Leggi i primi frame per completare l'inizializzazione
        # e permettere alle impostazioni di essere applicate
        for i in range(5):
            log_time(f"Prima del frame di warmup {i+1}")
            ret, _ = app.cap.read()
            log_time(f"Dopo il frame di warmup {i+1}")
            if not ret:
                log_message("Attenzione: problema durante la lettura dei frame iniziali")
                
        # Verifica le dimensioni effettive ottenute
        actual_width = app.cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        actual_height = app.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        
        end_time = time.time()
        log_message(f"Webcam inizializzata con dimensioni: {int(actual_width)}x{int(actual_height)}")
        log_message(f"Tempo di inizializzazione webcam: {end_time - start_time:.2f} secondi")
        #log_time("Fine initialize_webcam")
        
        return True
        
    except Exception as e:
        log_message(f"Errore durante l'inizializzazione della webcam: {str(e)}")
        #log_time("Errore in initialize_webcam")
        return False

def initialize_webcam_delayed(app):
    """
    Inizializza la webcam in modo ottimizzato solo quando necessario
    Ritorna True se la webcam è già inizializzata o se l'inizializzazione ha successo
    """
    # Se la webcam è già stata inizializzata, non fare nulla
    if app.webcam_initialized and app.cap is not None and app.cap.isOpened():
        return True
        
    log_message("Inizializzazione webcam in corso...")
    start_time = time.time()
    
    try:
        # Se la webcam è già aperta, chiudila
        if app.cap is not None and app.cap.isOpened():
            app.cap.release()
            app.cap = None
        
        # Usa DirectShow su Windows
        app.cap = cv2.VideoCapture(app.selected_camera, cv2.CAP_DSHOW)
        
        if not app.cap.isOpened():
            log_message(f"Errore: impossibile aprire la webcam {app.selected_camera}")
            return False
            
        # Imposta la risoluzione selezionata
        width, height = map(int, app.selected_resolution.split('x'))
        app.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        app.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        
        # Ottimizzazioni per webcam
        app.cap.set(cv2.CAP_PROP_FPS, 30)
        app.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        app.cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
        
        # Applica i controlli diretti della webcam
        update_webcam_contrast(webcam_contrast_slider.get())
        update_webcam_saturation(webcam_saturation_slider.get())
        update_webcam_exposure(webcam_exposure_slider.get())
        update_webcam_focus(webcam_focus_slider.get())
        
        # Leggi i primi frame per completare l'inizializzazione (solo 2 invece di 5)
        for _ in range(2):
            ret, _ = app.cap.read()
            if not ret:
                log_message("Attenzione: problema durante la lettura dei frame iniziali")
                
        # Verifica le dimensioni effettive ottenute
        actual_width = app.cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        actual_height = app.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        
        end_time = time.time()
        log_message(f"Webcam inizializzata con dimensioni: {int(actual_width)}x{int(actual_height)}")
        log_message(f"Tempo di inizializzazione webcam: {end_time - start_time:.2f} secondi")
        
        # Imposta il flag di inizializzazione
        app.webcam_initialized = True
        
        return True
        
    except Exception as e:
        log_message(f"Errore durante l'inizializzazione della webcam: {str(e)}")
        return False

# ====== Image Processing ======

def update_lamp_threshold(value):
    """Updates the lamp threshold value"""
    app.lamp_threshold = int(value)

def on_preview_panel_resize(event):
    """Handles resizing of the preview panel"""
    if app.current_frame is not None:
        # Redraw the current image with the new dimensions
        display_frame_in_panel(app.current_frame)

# ====== Area Selection & Management ======
def update_area_display():
    """Updates the display of selected areas in the UI"""
    # Clear the areas container
    for widget in area_frame_container.winfo_children():
        widget.destroy()
        
    # Show all areas
    for i, area in enumerate(app.areas):
        x1, y1, x2, y2, area_type, slot_number = area
        config_frame = tk.Frame(area_frame_container)
        config_frame.pack(fill="x", pady=2)
        
        if area_type == "Lamp":
            lamp_name = "Amber" if slot_number == 1 else "Red"
            area_text = f"Lamp {slot_number} ({lamp_name})"
        else:  # Number area
            area_name = "SPN" if slot_number == 1 else "FMI"
            area_text = f"Area {slot_number} ({area_name})"
            
        label = tk.Label(config_frame, text=f"{area_text}: ({x1},{y1})-({x2},{y2}) - Type: {area_type}")
        label.pack(side=tk.LEFT)
        
        # Add removal button for this area - disabilitato se l'acquisizione è in corso
        remove_btn = tk.Button(config_frame, text="X", command=lambda idx=i: remove_area(idx),
                 font=('Arial', 8), width=2)
        remove_btn.pack(side=tk.RIGHT, padx=2)
        
        # Disabilita il pulsante di rimozione se l'acquisizione è in corso
        if app.running:
            remove_btn.config(state=tk.DISABLED)
        
    # If there are areas, show the button to remove them all
    if app.areas:
        remove_all_btn = tk.Button(area_frame_container, text="Remove all areas",
                                 command=remove_all_areas, font=('Arial', 9))
        remove_all_btn.pack(fill="x", pady=2)
        
        # Disabilita il pulsante "Remove all areas" se l'acquisizione è in corso
        if app.running:
            remove_all_btn.config(state=tk.DISABLED)

def remove_area(index):
    """Removes a single area from the selection"""
    if 0 <= index < len(app.areas):
        area = app.areas[index]
        # Free the appropriate slot
        if area[4] == "Number":
            app.area_slots[area[5] - 1] = False
        else:  # Lamp
            app.lamp_slots[area[5] - 1] = False
        
        # Remove the area
        app.areas.pop(index)
        update_area_display()
        
        # Disabilitiamo il pulsante Start se non ci sono più aree
        if not app.areas:
            app.start_btn.config(state=tk.DISABLED)
            log_message("No areas left. Start button is disabled.")
        
        # Se la finestra di selezione è aperta, aggiorna la visualizzazione
        try:
            if cv2.getWindowProperty("Select areas", cv2.WND_PROP_VISIBLE) >= 1:
                # La finestra è aperta, aggiorna la visualizzazione
                display_frame = app.frame.copy()
                if app.areas:
                    display_frame = draw_all_areas_with_labels(display_frame)
                cv2.imshow("Select areas", display_frame)
                app.current_frame = display_frame.copy()
                # Se Live View è attiva, aggiorna la threshold preview
                if hasattr(app, 'live_view_active') and app.live_view_active:
                   update_threshold_preview()
            else:
                # La finestra non è aperta, prova a riaprirla
                reopen_area_selection()
        except:
            # C'è stato un errore (finestra non trovata), riapri la selezione
            reopen_area_selection()

def remove_all_areas():
    """Removes all selected areas"""
    app.areas.clear()
    app.area_slots = [False, False]  # Reset all slots
    app.lamp_slots = [False, False]
    update_area_display()
    if app.current_frame is not None:
        display_frame = app.frame.copy()
        cv2.imshow("Select areas", display_frame)
        app.current_frame = display_frame.copy()

def draw_all_areas_with_labels(image):
    """Draws all selected areas with labels on the image"""
    display_frame = image.copy()
    
    for area in app.areas:
        if len(area) < 6:
            continue
            
        x1, y1, x2, y2, area_type, slot_number = area
        x1, x2 = min(x1, x2), max(x1, x2)
        y1, y2 = min(y1, y2), max(y1, y2)
        
        if area_type == "Lamp":
            lamp_name = "Amber" if slot_number == 1 else "Red"
            cv2.rectangle(display_frame, (x1, y1), (x2, y2), (255, 0, 0), 2)
            cv2.rectangle(display_frame, (x1, y1-20), (x1+150, y1), (0, 0, 0), -1)
            cv2.putText(display_frame, f"Lamp {slot_number} ({lamp_name})", (x1, y1-5),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        else:  # Number area
            area_name = "SPN" if slot_number == 1 else "FMI"
            cv2.rectangle(display_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.rectangle(display_frame, (x1, y1-20), (x1+150, y1), (0, 0, 0), -1)
            cv2.putText(display_frame, f"Area {slot_number} ({area_name})", (x1, y1-5),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    
    return display_frame

def select_area_or_lamp(event, x, y, flags, param):
    """Mouse callback for selecting areas"""
    display_frame = app.frame.copy()
    display_frame = draw_all_areas_with_labels(display_frame)

    # Number area selection (left click)
    if event == cv2.EVENT_LBUTTONDOWN:
        # Verifica quali aree numeriche sono già presenti
        existing_numbers = [a for a in app.areas if a[4] == "Number"]
        existing_slots = [a[5] for a in existing_numbers]
        
        if 1 not in existing_slots:  # Manca Area 1 (SPN)
            new_slot = 1
            app.area_slots[0] = True
            log_message("Adding SPN (Area 1)")
        elif 2 not in existing_slots:  # Manca Area 2 (FMI)
            new_slot = 2
            app.area_slots[1] = True
            log_message("Adding FMI (Area 2)")
        else:
            log_message("Maximum limit of 2 number areas reached.")
            return
            
        app.drawing = True
        app.areas.append([x, y, x, y, "Number", new_slot])
        update_area_display()
        # Se è stata selezionata un'area numerica, aggiorna la threshold preview
        if app.areas and app.areas[-1][4] == "Number":
            root.after(200, update_threshold_preview)  # Leggero ritardo per permettere alla webcam di stabilizzarsi
        # Abilitiamo direttamente il pulsante Start quando si aggiunge un'area
        app.start_btn.config(state=tk.NORMAL)
        
    elif event == cv2.EVENT_MOUSEMOVE and app.drawing and flags & cv2.EVENT_FLAG_LBUTTON:
        if app.areas:
            app.areas[-1][2:4] = [x, y]
            x1, y1 = app.areas[-1][0], app.areas[-1][1]
            cv2.rectangle(display_frame, (x1, y1), (x, y), (0, 255, 0), 2)
    elif event == cv2.EVENT_LBUTTONUP:
        if app.areas and app.drawing:
            app.drawing = False
            app.areas[-1][2:4] = [x, y]
            x1, y1, x2, y2 = app.areas[-1][:4]
            x1, x2 = min(x1, x2), max(x1, x2)
            y1, y2 = min(y1, y2), max(y1, y2)
            app.areas[-1][:4] = [x1, y1, x2, y2]  # Aggiorna le coordinate definitive
            
            # Salva esplicitamente le coordinate nell'oggetto app per il riferimento OCR
            if app.areas[-1][4] == "Number":
                slot_number = app.areas[-1][5]
                app.ocr_areas = getattr(app, 'ocr_areas', {})
                app.ocr_areas[slot_number] = (x1, y1, x2, y2)
                
                # Usa un timer con un ritardo leggermente maggiore
                root.after(500, update_threshold_preview)  # 300ms di ritardo
            
            display_frame = draw_all_areas_with_labels(display_frame)
            update_area_display()
            
            # Se è stata selezionata un'area numerica, aspetta un attimo prima di aggiornare
            if app.areas[-1][4] == "Number":
                # Usa un timer con un ritardo leggermente maggiore
                root.after(300, update_threshold_preview)  # 300ms di ritardo

    # Lamp area selection (right click)
    if event == cv2.EVENT_RBUTTONDOWN:
        # Stesso approccio per le lampade
        existing_lamps = [a for a in app.areas if a[4] == "Lamp"]
        existing_lamp_slots = [a[5] for a in existing_lamps]
        
        if 1 not in existing_lamp_slots:  # Manca Lamp 1 (Amber)
            new_slot = 1
            app.lamp_slots[0] = True
            log_message("Adding Amber (Lamp 1)")
        elif 2 not in existing_lamp_slots:  # Manca Lamp 2 (Red)
            new_slot = 2
            app.lamp_slots[1] = True
            log_message("Adding Red (Lamp 2)")
        else:
            log_message("Maximum limit of 2 lamp areas reached.")
            return
            
        app.drawing = True
        app.areas.append([x, y, x, y, "Lamp", new_slot])
        update_area_display()
        # Abilitiamo direttamente il pulsante Start quando si aggiunge un'area
        app.start_btn.config(state=tk.NORMAL)
        
    elif event == cv2.EVENT_MOUSEMOVE and app.drawing and flags & cv2.EVENT_FLAG_RBUTTON:
        if app.areas:
            app.areas[-1][2:4] = [x, y]
            x1, y1 = app.areas[-1][0], app.areas[-1][1]
            cv2.rectangle(display_frame, (x1, y1), (x, y), (255, 0, 0), 2)
    elif event == cv2.EVENT_RBUTTONUP:
        if app.areas and app.drawing:
            app.drawing = False
            app.areas[-1][2:4] = [x, y]
            x1, y1, x2, y2 = app.areas[-1][:4]
            x1, x2 = min(x1, x2), max(x1, x2)
            y1, y2 = min(y1, y2), max(y1, y2)
            app.areas[-1][:4] = [x1, y1, x2, y2]
            display_frame = draw_all_areas_with_labels(display_frame)
            update_area_display()

    cv2.imshow("Select areas", display_frame)
    app.current_frame = display_frame.copy()

# ====== Preview & Display ======
def capture_preview():
    """Versione che inizializza la webcam solo quando necessario"""
    try:
        cv2.destroyAllWindows()
        cv2.waitKey(1)
    except:
        pass
    
    try:
        # Inizializza la webcam con la funzione delayed
        if not initialize_webcam_delayed(app):
            log_message("Errore: impossibile inizializzare la webcam")
            update_button_states('initial')
            return

        # Leggi un frame
        ret, app.frame = app.cap.read()
        
        if not ret:
            log_message("Errore: impossibile acquisire un frame")
            update_button_states('initial')
            return

        # Ottieni le dimensioni effettive del frame
        height, width = app.frame.shape[:2]
        log_message(f"Dimensioni effettive del frame: {width}x{height}")

        # Reset delle aree selezionate
        app.areas.clear()
        app.area_slots = [False, False]
        app.lamp_slots = [False, False]
        
        # Aggiorna la visualizzazione delle aree
        update_area_display()

        app.current_frame = app.frame.copy()

        # Crea la finestra di preview con dimensioni adeguate
        cv2.namedWindow("Select areas", cv2.WINDOW_NORMAL)
        
        # Calcola le dimensioni massime per il display
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        
        # Calcola la dimensione massima che si adatta allo schermo
        max_display_width = min(width, int(screen_width * 0.6))
        max_display_height = min(height, int(screen_height * 0.8))
        
        # Calcola il rapporto d'aspetto e ridimensiona la finestra
        aspect_ratio = width / height
        
        if width > height:  # Immagine orizzontale
            display_width = max_display_width
            display_height = int(display_width / aspect_ratio)
            if display_height > max_display_height:
                display_height = max_display_height
                display_width = int(display_height * aspect_ratio)
        else:  # Immagine verticale
            display_height = max_display_height
            display_width = int(display_height * aspect_ratio)
            if display_width > max_display_width:
                display_width = max_display_width
                display_height = int(display_width / aspect_ratio)
        
        # Ridimensiona la finestra di preview
        cv2.resizeWindow("Select areas", display_width, display_height)
        
        # Imposta la callback per la selezione delle aree
        cv2.setMouseCallback("Select areas", select_area_or_lamp)
        cv2.imshow("Select areas", app.frame)
        cv2.waitKey(1)
        
        log_message(f"Finestra di preview ridimensionata a {display_width}x{display_height}")
        log_message("Usa il tasto SINISTRO del mouse per selezionare aree NUMERICHE (Area 1 = SPN, Area 2 = FMI)")
        log_message("Usa il tasto DESTRO del mouse per selezionare aree LAMPADE (Lamp 1 = Amber, Lamp 2 = Red)")
        
        # Aggiorna lo stato dei pulsanti dopo il preview
        update_button_states('preview')
        
    except Exception as e:
        log_message(f"Errore durante l'acquisizione: {str(e)}")
        update_button_states('initial')


# ====== CAN Communication ======

def create_can_bus(interface_name, channel, bitrate):
    """
    Crea un bus CAN con gestione migliorata degli errori e configurazione ottimizzata.
    
    Args:
        interface_name: Nome dell'interfaccia ('vector')
        channel: Canale CAN (0, 1, ecc.)
        bitrate: Velocità in bit/s
        
    Returns:
        can.interface.Bus: Istanza del bus CAN configurato
    """
    # Variabile statica per tracciare se i dettagli sono già stati loggati
    if not hasattr(create_can_bus, 'first_call'):
        create_can_bus.first_call = True
    
    # Log solo la prima volta
    if create_can_bus.first_call:
        log_message(f"Creating CAN bus: interface={interface_name}, channel={channel}, bitrate={bitrate}")
        create_can_bus.first_call = False
    
    try:
        # Converti il canale in intero per Vector
        if isinstance(channel, str) and channel.isdigit():
            channel = int(channel)
        
        # Configurazione ottimizzata per Vector CANcase
        bus = can.interface.Bus(
            interface=interface_name,
            channel=channel,
            bitrate=bitrate,
            fd=False,
            receive_own_messages=False,
            transmit_buffer_size=32,
            receive_buffer_size=512,
            bitrate_switch=False,
            single_handle=True,
            timing=None
        )
        
        # Verifica che il bus sia realmente aperto
        if not bus or not hasattr(bus, 'send'):
            raise Exception("Failed to initialize bus")
            
        return bus
    except can.CanError as e:
        detailed_error = str(e)
        log_message(f"CAN error creating bus: {detailed_error}")
        
        # Fornisci messaggi di errore più chiari e utili
        if "DLL" in detailed_error or "load" in detailed_error:
            raise Exception("Vector driver not found. Please verify Vector XL Driver installation.")
        elif "permission" in detailed_error:
            raise Exception("Permission denied. Another application may be using the CAN interface.")
        elif "hardware" in detailed_error:
            raise Exception("CANcase hardware error. Please check connections and restart the device.")
        else:
            raise Exception(f"Vector CAN bus error: {detailed_error}")
    except Exception as e:
        log_message(f"General error creating CAN bus: {str(e)}")
        raise Exception(f"Unable to create Vector CAN bus. Error: {str(e)}")


# ====== CAN Communication ======
def send_canalyzer_can_message(recognized_values, lamp_brightness_status):
    """
    Invia un messaggio CAN con PGN FF99 contenente i dati riconosciuti in modalità Canalyzer.
    Versione corretta che mantiene l'associazione tra area e valore.
    
    Args:
        recognized_values: Dizionario con chiavi 'SPN' e 'FMI'
        lamp_brightness_status: Lista di stati delle lampade [amber, red]
    """
    try:
        # Estrai i valori dal dizionario (usare 0 se None)
        spn_value = recognized_values.get('SPN', 0) if recognized_values.get('SPN') is not None else 0
        fmi_value = recognized_values.get('FMI', 0) if recognized_values.get('FMI') is not None else 0
        
        # Stato lampade
        amber_status = "ON" if lamp_brightness_status and len(lamp_brightness_status) > 0 and lamp_brightness_status[0] else "OFF"
        red_status = "ON" if lamp_brightness_status and len(lamp_brightness_status) > 1 and lamp_brightness_status[1] else "OFF"
        
        # Log dettagliato dei valori riconosciuti senza verifica (modalità Canalyzer)
        log_message("==================== Recognized Values ==================")
        log_message(f"SPN: {spn_value}")
        log_message(f"FMI: {fmi_value}")
        log_message(f"Amber Lamp: {amber_status}")
        log_message(f"Red Lamp: {red_status}")
        log_message("==========================================================")
        
        log_message("Attempting CAN connection for Canalyzer response...")
        
        # Get CAN parameters
        channel = can_channel_var.get()
        bitrate = int(can_bitrate_var.get())
        
        # PGN fisso per il messaggio di risposta in modalità Canalyzer
        pgn = 0xFF99
        
        # Parametri CAN
        priority = 6  # Priorità standard
        source_address = 0  # Indirizzo sorgente
        
        # Costruzione dell'ID CAN esteso
        arb_id = (priority << 26) | (pgn << 8) | source_address
        
        # Inizializza l'array di byte del messaggio
        data = [0x00] * 8
        
        # SPN (byte 0, 1, 2)
        data[0] = (spn_value >> 16) & 0xFF
        data[1] = (spn_value >> 8) & 0xFF
        data[2] = spn_value & 0xFF
        
        # FMI (byte 4, 5)
        data[4] = (fmi_value >> 8) & 0xFF
        data[5] = fmi_value & 0xFF
        
        # Stato lampade
        if lamp_brightness_status:
            # Amber lamp (primo elemento dell'array)
            if len(lamp_brightness_status) > 0 and lamp_brightness_status[0]:
                data[6] = 1
            
            # Red lamp (secondo elemento dell'array)
            if len(lamp_brightness_status) > 1 and lamp_brightness_status[1]:
                data[7] = 1
        
        # Formatta i dati in esadecimale per il log
        hex_data = ' '.join(f'{b:02X}' for b in data)
        
        # Crea e invia il messaggio CAN
        try:
            # Connect to CAN bus
            bus = create_can_bus('vector', channel, bitrate)
            
            # Create CAN message
            msg = can.Message(
                arbitration_id=arb_id,
                data=data,
                is_extended_id=True,
                dlc=8
            )
            
            # Send message
            bus.send(msg)
            
            # Log con dettagli esadecimali più concisi
            log_message(
                f"Canalyzer response #{app.can_message_counter} sent successfully - ID=0x{arb_id:08X}, Data=[{hex_data}]"
            )
            
            # Incrementa il contatore
            app.can_message_counter += 1
            
            return True
            
        except can.CanError as e:
            log_message(f"CAN send error: {str(e)}")
            return False
        finally:
            # Chiudi la connessione
            if 'bus' in locals() and bus:
                bus.shutdown()
                
    except Exception as e:
        log_message(f"Error preparing Canalyzer CAN message: {str(e)}")
        return False


def send_can_message(dtc_params):
    """
    Sends a DM1 CAN message con registrazione dei dettagli solo al primo invio.
    Replica esattamente la logica CAPL custom.
    """
    # Variabile statica per tracciare i DTC già inviati
    if not hasattr(send_can_message, 'sent_dtcs'):
        send_can_message.sent_dtcs = set()
    
    try:
        # Estrai i parametri
        spn = int(dtc_params.get("SPN", 0))
        fmi = int(dtc_params.get("FMI", 0))
        lamp_status = dtc_params.get("LAMP", "NONE")
        sa = int(dtc_params.get("SA", 0))
        
        # Crea una chiave univoca per il DTC
        dtc_key = (spn, fmi, lamp_status, sa)
        
        # Logga i dettagli solo la prima volta
        if dtc_key not in send_can_message.sent_dtcs:
            log_message("==================== Values to be sent ====================")
            log_message(f"SPN: {spn}")
            log_message(f"FMI: {fmi}")
            log_message(f"Lamp: {lamp_status}")
            log_message(f"Source Address: 0x{sa:02X}")
            log_message("=======================================================")
            
            # Aggiungi questo DTC alla lista
            send_can_message.sent_dtcs.add(dtc_key)
        
        # REPLICA ESATTA DELLA LOGICA CAPL generateDTC()
        
        # 1. SPN binary conversion
        bits_spn = [0] * 19
        for i in range(19-1, -1, -1):
            bits_spn[19-1-i] = 1 if (spn & (1 << i)) else 0
        
        # 2. Split SPN in 3+8+8 bit sequence
        SPN_3bit_H = bits_spn[0:3]
        SPN_8bit_M = bits_spn[3:11]
        SPN_8bit_L = bits_spn[11:19]
        
        # 3. FMI binary conversion
        FMI = [0] * 5
        for i in range(5-1, -1, -1):
            FMI[5-1-i] = 1 if (fmi & (1 << i)) else 0
        
        # 4. DTC2Byte creation: SPN_8bit_L + SPN_8bit_M
        DTC2Byte = [0] * 16
        for i in range(8):
            DTC2Byte[i] = SPN_8bit_L[i]
        for i in range(8):
            DTC2Byte[8 + i] = SPN_8bit_M[i]
        
        # 5. FaultType1Byte: SPN_3bit_H + FMI
        FaultType1Byte = [0] * 8
        for i in range(3):
            FaultType1Byte[i] = SPN_3bit_H[i]
        for i in range(5):
            FaultType1Byte[3 + i] = FMI[i]
        
        # 6. DTC3Byte: DTC2Byte + FaultType1Byte
        bits_dtc = [0] * 32
        for i in range(16):
            bits_dtc[i] = DTC2Byte[i]
        for i in range(8):
            bits_dtc[16 + i] = FaultType1Byte[i]
        
        # 7. BinToHex conversion
        dtc_generated = 0
        for i in range(len(bits_dtc)):
            b = 1 if bits_dtc[i] == 1 else 0
            dtc_generated = (dtc_generated << 1) | b
        
        # Build extended CAN ID
        pgn = 0xFECA
        priority = 6
        arb_id = (priority << 26) | (pgn << 8) | sa
        
        # Initialize message with 8 bytes
        data = [0x00] * 8
        
        # Handle lamps in first byte
        if lamp_status == "AMBER":
            data[0] |= (1 << 2)
        elif lamp_status == "RED":
            data[0] |= (1 << 4)
        
        # Byte 1: Reserved
        data[1] = 0xFF
        
        # Set DTC bytes (replica CAPL sendDTC)
        data[2] = (dtc_generated >> 24) & 0xFF
        data[3] = (dtc_generated >> 16) & 0xFF
        data[4] = (dtc_generated >> 8) & 0xFF
        data[5] = dtc_generated & 0xFF
        
        # Set Source Address
        data[6] = sa
        
        # Byte 7: Reserved
        data[7] = 0xFF
        
        # Connect to CAN bus
        bus = create_can_bus('vector', can_channel_var.get(), int(can_bitrate_var.get()))
        
        try:
            # Create CAN message
            msg = can.Message(
                arbitration_id=arb_id,
                data=data,
                is_extended_id=True,
                dlc=8
            )
            
            # Send message
            bus.send(msg)
            
            app.can_message_counter += 1
            return True
            
        except can.CanError as e:
            log_message(f"CAN send error: {str(e)}")
            return False
        finally:
            bus.shutdown()
        
    except Exception as e:
        log_message(f"Error preparing CAN message: {str(e)}")
        return False



def start_recognition():
    """Starts the process of waiting for the CAN message"""
    # Verify that there are selected areas
    if not app.areas:
        log_message("Error: no area selected")
        return
    
    # Se l'acquisizione è già in corso, fermala prima
    if app.running:
        log_message("Stopping current acquisition before starting a new one")
        stop_recognition()
        # Piccola pausa per assicurarsi che i thread precedenti si fermino
        time.sleep(0.5)
    
    # Close the area selection window if it's still open
    try:
        if cv2.getWindowProperty("Select areas", cv2.WND_PROP_VISIBLE) >= 1:
            cv2.destroyWindow("Select areas")
    except:
        pass # Ignore errors if window doesn't exist
    
    # Reset the message counter when starting
    app.can_message_counter = 1
    
    # Set running to True to indicate that the system is running
    app.running = True
    
    # AGGIUNTA: imposta il flag per continuare l'aggiornamento OCR threshold
    app.continue_threshold_preview = True
    
    # Avvia un timer che manterrà aggiornata la threshold preview
    def keep_threshold_preview_updated():
        if app.running and hasattr(app, 'continue_threshold_preview') and app.continue_threshold_preview:
            update_threshold_preview()
            root.after(500, keep_threshold_preview_updated)  # Aggiorna ogni 500ms
    
    # Avvia il timer
    root.after(100, keep_threshold_preview_updated)
    
    # AGGIUNTA: imposta il flag di riconoscimento avviato
    if app.dtc_frame:
        app.dtc_frame.update_main_recognition_state(True)
    
    # Aggiorna la visualizzazione delle aree per disabilitare i pulsanti di rimozione
    update_area_display()
        
    # Inizializza la webcam con la funzione delayed
    if not initialize_webcam_delayed(app):
        log_message("Errore: impossibile inizializzare la webcam")
        app.running = False
        update_button_states('initial')
        return
    
    # Check if already waiting for a CAN message
    if not app.waiting_for_can:
        app.waiting_for_can = True  # Set flag to True before starting the thread
        
        # Ottieni la modalità corrente
        is_canalyzer_mode = app.is_canalyzer_mode
        log_message(f"Starting in {'Canalyzer' if is_canalyzer_mode else 'DTC Test'} mode")
        
        # CORREZIONE: Usa approcci diversi in base alla modalità
        if is_canalyzer_mode:
            # In modalità Canalyzer, avvia il thread di ascolto DM1
            log_message("Starting acquisition in Canalyzer mode")
            threading.Thread(target=wait_for_canalyzer_message, daemon=True).start()
        else:
            # In modalità DTC Test, non avviamo wait_for_canalyzer_message
            # Il DTC Test sarà avviato manualmente dall'utente tramite il pulsante "Start DTC Test"
            log_message("Recognition started - Press 'Start DTC Test' to begin testing")
            # Resetta il flag di attesa perché non usiamo wait_for_canalyzer_message in questa modalità
            app.waiting_for_can = False
    else:
        log_message("Already waiting for CAN message...")
    
    # Update button states after starting recognition
    update_button_states('start')
    
    # Avvia l'anteprima continua se richiesto
    if hasattr(app, 'live_preview_during_recognition') and app.live_preview_during_recognition:
        log_message("Started Live Preview during recognition")
        start_continuous_preview()

# Sostituisci la funzione update_countdown con questa versione:
def update_countdown():
    """Aggiorna il valore del countdown senza visualizzarlo nella preview"""
    if not app.countdown_active or not app.running:
        app.countdown_active = False
        return
    
    # Aggiorna il valore
    app.countdown_value -= 1
    current_value = app.countdown_value
    
    # Punti di interesse per il log
    if current_value in [20, 10, 5, 4, 3, 2, 1]:
        log_message(f"Recognition countdown: {current_value} seconds")
    
    # Controlla se il countdown è terminato
    if current_value <= 0:
        # Terminato il countdown
        root.after(1000, end_countdown)
    else:
        # Continua il countdown
        root.after(1000, update_countdown)

# Sostituisci la funzione end_countdown con questa versione:
def end_countdown():
    """Fine del countdown, resetta i flag"""
    app.countdown_active = False
    log_message("Recognition countdown complete")

def perform_acquisition():
    """Performs a single acquisition cycle after receiving a CAN message"""
    if not app.running or not app.ecff_received:
        log_message("Conditions not met for acquisition")
        return
    
    try:
        if app.cap is not None and app.cap.isOpened():
            log_message("Webcam open and ready")
            
            # Read a few frames to 'warm up' the webcam
            for _ in range(3):
                app.cap.read()
                
            start_time = time.time()
            ret, frame = app.cap.read()
            acquisition_time = time.time() - start_time
            
            log_message(f"Frame acquisition completed. Time: {acquisition_time:.3f} seconds")
        
            if ret:
                log_message("Frame acquired successfully")
                
                # Elabora l'immagine in un thread separato
                threading.Thread(
                    target=process_frame_in_background,
                    args=(frame.copy(), True),
                    daemon=True
                ).start()
                
                # Reset acquisition flag immediately, don't wait for processing to complete
                app.ecff_received = False
                
                # Update CSV index after recognition will be handled in the thread
                log_message("Image processing started in background thread")
            else:
                log_message("Error: unable to acquire frame from webcam")
                app.ecff_received = False
        else:
            log_message("Error: webcam not initialized or closed")
            app.ecff_received = False
    except Exception as e:
        log_message(f"Error during acquisition: {e}")
        app.ecff_received = False

# Funzione di elaborazione per la modalità standard in background
def process_frame_in_background(frame, verify_expected=False):
    """Processa il frame in un thread di background per non bloccare l'UI"""
    try:
        log_message("Background processing: starting recognition...")
        
        # Usa il frame per il riconoscimento
        recognized_values, lamp_brightness_status = process_frame(frame, verify_expected)
        
        # Aggiorna l'UI nel thread principale
        root.after(0, lambda: update_ui_after_recognition(recognized_values, lamp_brightness_status))
        
        # Update CSV index after recognition
        if app.dtc_frame:
            root.after(0, lambda: app.dtc_frame.next_dtc())
            
        log_message("Background processing: recognition completed")
    except Exception as e:
        log_message(f"Error in background processing: {str(e)}")

def update_ui_after_recognition(recognized_values, lamp_brightness_status):
    """Aggiorna l'interfaccia utente dopo il completamento del riconoscimento"""
    # Questa funzione viene eseguita nel thread principale (UI thread)
    log_message("Updating UI with recognition results")

def perform_canalyzer_acquisition():
    """Performs a single acquisition cycle in Canalyzer mode with DTC verification"""
    if not app.running:
        log_message("Cannot perform acquisition - application not running")
        return
    
    # Modifica: in modalità NON-CANALYZER non controlliamo ecff_received perché
    # è già stato impostato nel dm1_sender_thread
    if app.is_canalyzer_mode and not app.ecff_received:
        log_message("Cannot perform acquisition - no pending DM1 message")
        return
    
    try:
        log_message("Starting acquisition cycle")
        
        if app.cap is not None and app.cap.isOpened():
            log_message("Webcam open and ready for acquisition")
            
            # Read a few frames to 'warm up' the webcam
            for _ in range(3):
                app.cap.read()
                
            ret, frame = app.cap.read()
            
            if ret:
                log_message("Frame acquired successfully")
                
                # Usa direttamente il frame catturato
                processed_frame = frame.copy()
                
                # Riconoscimento senza verifica
                log_message("Starting image recognition...")
                recognized_values, lamp_brightness_status = process_frame(processed_frame, verify_expected=False)
                
                # Verifica i valori riconosciuti contro quelli inviati nel DM1
                # (solo se siamo in modalità DTC Test)
                if not app.is_canalyzer_mode and app.dm1_thread_running and app.csv_data:
                    # Confronta i valori riconosciuti con il DTC corrente
                    if app.current_dtc_index < len(app.csv_data):
                        current_dtc = app.csv_data[app.current_dtc_index]
                        log_message("Verifying recognized values against current DTC...")
                        
                        # Estrai lo stato della lampada
                        lamp_status = "NONE"
                        if lamp_brightness_status and len(lamp_brightness_status) > 0:
                            if lamp_brightness_status[0]:
                                lamp_status = "AMBER"
                            elif len(lamp_brightness_status) > 1 and lamp_brightness_status[1]:
                                lamp_status = "RED"
                        
                        # Prepara i valori riconosciuti
                        recognized_dtc = {
                            "SPN": recognized_values.get('SPN', 0) if recognized_values.get('SPN') is not None else 0,
                            "FMI": recognized_values.get('FMI', 0) if recognized_values.get('FMI') is not None else 0,
                            "LAMP": lamp_status
                        }
                        
                        # Verifica
                        verify_ff99_response(current_dtc, recognized_dtc)
                
                # Invia il messaggio CAN come risposta
                log_message("Sending FF99 response...")
                send_canalyzer_can_message(recognized_values, lamp_brightness_status)
                
                # Reset flag acquisizione
                app.ecff_received = False
                
                # In modalità DTC Test, non avanza al prossimo DTC qui
                # Sarà gestito dal thread dm1_sender_thread
                
                # Log completamento ciclo
                log_message(">>> Recognition cycle completed")
                
            else:
                log_message("Error: unable to acquire frame from webcam")
                app.ecff_received = False
        else:
            log_message("Error: webcam not initialized or closed")
            app.ecff_received = False
    except Exception as e:
        log_message(f"Error during acquisition: {str(e)}")
        app.ecff_received = False

def process_canalyzer_recognition():
    """
    Funzione callback che gestisce l'acquisizione dopo il timeout.
    Chiamata dopo 35 secondi dal rilevamento di un nuovo messaggio.
    """
    # Esegui l'acquisizione
    perform_canalyzer_acquisition()
    
    # Resetta il flag di elaborazione per permettere nuovi messaggi
    app.canalyzer_is_processing = False
    
    log_message("Ready for next DM1 message")

def schedule_canalyzer_acquisition():
    """Funzione intermedia che prepara e avvia l'acquisizione dopo il countdown"""
    log_message("35 seconds elapsed - starting acquisition process")
    
    # Aggiorna l'ultimo messaggio elaborato
    app.canalyzer_last_processed_message = app.message_to_process
    
    # Esegui l'acquisizione
    perform_canalyzer_acquisition()
    
    # Resetta il flag di acquisizione programmata
    app.canalyzer_is_acquisition_scheduled = False
    log_message("Ready for next new DM1 message")



def add_number_recognition_debug(frame, x1, y1, x2, y2, area_type, slot_number, recognized_value):
    """
    Aggiunge informazioni di debug visive al frame per il riconoscimento numeri
    
    Args:
        frame: Il frame su cui disegnare
        x1, y1, x2, y2: Coordinate dell'area
        area_type: Tipo di area ('Number')
        slot_number: Numero dello slot (1=SPN, 2=FMI)
        recognized_value: Valore riconosciuto o None
    """
    # Colore del rettangolo: verde se riconosciuto, rosso se non riconosciuto
    color = (0, 255, 0) if recognized_value is not None else (0, 0, 255)
    
    # Disegna rettangolo
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
    
    # Etichetta con tipo di area
    area_name = "SPN" if slot_number == 1 else "FMI"
    label_text = f"{area_name}: "
    
    # Aggiungi il valore riconosciuto se presente
    if recognized_value is not None:
        label_text += f"{recognized_value}"
    else:
        label_text += "?"
    
    # Crea sfondo per il testo
    text_size = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]
    cv2.rectangle(frame, 
                 (x1, y1 - 20), 
                 (x1 + text_size[0] + 10, y1), 
                 (0, 0, 0), 
                 -1)
                 
    # Aggiungi il testo
    cv2.putText(frame, 
               label_text, 
               (x1 + 5, y1 - 5),
               cv2.FONT_HERSHEY_SIMPLEX, 
               0.5, 
               (255, 255, 255), 
               1)


def process_frame(frame, verify_expected=False):
    """
    Processa il frame catturato per riconoscimento numeri e stato lampade.
    Versione aggiornata con riconoscimento SPN/FMI ottimizzato.
    
    Args:
        frame: Il frame catturato dalla webcam
        verify_expected: Se True, verifica i valori riconosciuti contro quelli attesi
    
    Returns:
        tuple: (recognized_values, lamp_brightness_status)
        recognized_values è un dizionario con chiavi 'SPN' e 'FMI'
    """
    # Dizionario per i valori riconosciuti
    recognized_values = {'SPN': None, 'FMI': None}
    lamp_amber_status = False
    lamp_red_status = False
    
    # Variabili per valori attesi (usate solo se verify_expected=True)
    spn_expected = 0
    fmi_expected = 0
    lamp_expected = "NONE"
    
    # Ottieni i valori attesi se necessario
    if verify_expected and len(app.csv_data) > app.current_dtc_index:
        current_dtc = app.csv_data[app.current_dtc_index]
        spn_expected = current_dtc.get('SPN', 0)
        fmi_expected = current_dtc.get('FMI', 0)
        lamp_expected = current_dtc.get('LAMP', 'NONE')
    
    # Ottieni la soglia di luminosità per le lampade
    lamp_threshold = lamp_threshold_slider.get()
    
    # Ottieni la soglia OCR per il riconoscimento numeri
    ocr_threshold = app.ocr_threshold
    
    # Copia del frame per disegnare
    display_frame = frame.copy()
    
    # Aggiungi barra informativa in alto
    height, width = display_frame.shape[:2]
    bar_height = 30
    cv2.rectangle(display_frame, (0, 0), (width, bar_height), (0, 0, 0), -1)
    
    # Ottieni i valori attuali della webcam
    brightness = app.cap.get(cv2.CAP_PROP_BRIGHTNESS) if app.cap else 0
    
    # Aggiungi il testo con i valori di base
    info_text = f"Brightness: {brightness:.1f} | Lamp Thresh: {lamp_threshold} | OCR Thresh: {ocr_threshold}"
    cv2.putText(display_frame, info_text, (10, 20), 
               cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    
    # Processa ciascuna area
    amber_luminosity = None
    red_luminosity = None
    
    for area in app.areas:
        x1, y1, x2, y2, area_type, slot_number = area
        x1, x2 = min(x1, x2), max(x1, x2)
        y1, y2 = min(y1, y2), max(y1, y2)
        
        roi = frame[y1:y2, x1:x2]
        if roi.size == 0:
            continue
        
        if area_type == "Number":
            # Log prima del riconoscimento
            area_name = "SPN" if slot_number == 1 else "FMI"
            log_message(f"Processing {area_name} area ({x1},{y1})-({x2},{y2})")
            
            # USA LA FUNZIONE OTTIMIZZATA per SPN/FMI
            recognized_value = process_number_area_optimized(
                roi, display_frame, x1, y1, ocr_threshold, area_type, slot_number
            )
            
            # Assegna il valore riconosciuto in base al numero di slot
            if recognized_value is not None:
                if slot_number == 1:  # Area 1 è SPN
                    recognized_values['SPN'] = recognized_value
                elif slot_number == 2:  # Area 2 è FMI
                    recognized_values['FMI'] = recognized_value
            
        elif area_type == "Lamp":
            # Processa le aree delle lampade (rimane uguale)
            is_bright, luminosity = process_lamp_area(roi, display_frame, x1, y1, x2, y2, lamp_threshold)
            
            # Aggiorna lo stato delle lampade in base al numero di slot
            if slot_number == 1:  # Lamp 1 è Amber
                lamp_amber_status = is_bright
                lamp_name = "Amber"
                amber_luminosity = luminosity
            elif slot_number == 2:  # Lamp 2 è Red
                lamp_red_status = is_bright
                lamp_name = "Red"
                red_luminosity = luminosity
            
            # Aggiunge info sulla lampada al frame di display
            add_lamp_info_to_frame(display_frame, x1, y1, lamp_name, luminosity, is_bright, lamp_threshold)
    
    # Aggiorna la barra informativa con i valori delle lampade se disponibili
    additional_info = []
    if amber_luminosity is not None:
        additional_info.append(f"Amber: {int(amber_luminosity)}")
    if red_luminosity is not None:
        additional_info.append(f"Red: {int(red_luminosity)}")
    
    if additional_info:
        lamp_info_text = " | ".join(additional_info)
        lamp_info_pos_x = width - 200  # Posiziona a destra
        cv2.putText(display_frame, lamp_info_text, (lamp_info_pos_x, 20), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    
    # Determina lo stato della lampada per il ritorno
    lamp_status = "NONE"
    if lamp_amber_status and not lamp_red_status:
        lamp_status = "AMBER"
    elif lamp_red_status and not lamp_amber_status:
        lamp_status = "RED"
    
    # Converti stati lampade in stringhe ON/OFF per il log
    amber_status = "ON" if lamp_amber_status else "OFF"
    red_status = "ON" if lamp_red_status else "OFF"
    
    # Preparazione mismatch, solo se verify_expected è True
    spn_value = recognized_values.get('SPN')
    fmi_value = recognized_values.get('FMI')
    
    # Log uniforme dei valori riconosciuti, con indicazione di mismatch se in verifica
    log_message("==================== Recognized Values ==================")
    
    if verify_expected:
        # Verifica SPN
        spn_mismatch = spn_value != spn_expected if spn_value is not None else True
        spn_mismatch_text = f" [MISMATCH - Expected: {spn_expected}]" if spn_mismatch else " [MATCH]"
        log_message(f"SPN: {spn_value}{spn_mismatch_text}")
        
        # Verifica FMI
        fmi_mismatch = fmi_value != fmi_expected if fmi_value is not None else True
        fmi_mismatch_text = f" [MISMATCH - Expected: {fmi_expected}]" if fmi_mismatch else " [MATCH]"
        log_message(f"FMI: {fmi_value}{fmi_mismatch_text}")
        
        # Verifica lampade in modo corretto
        # Amber lamp dovrebbe essere ON se lamp_expected è "AMBER"
        amber_expected = (lamp_expected == "AMBER")
        amber_actual = (amber_status == "ON")
        amber_mismatch = amber_expected != amber_actual
        amber_mismatch_text = f" [MISMATCH - Expected: {'ON' if amber_expected else 'OFF'}]" if amber_mismatch else " [MATCH]"
        log_message(f"Amber Lamp: {amber_status}{amber_mismatch_text}")
        
        # Red lamp dovrebbe essere ON se lamp_expected è "RED"
        red_expected = (lamp_expected == "RED")
        red_actual = (red_status == "ON")
        red_mismatch = red_expected != red_actual
        red_mismatch_text = f" [MISMATCH - Expected: {'ON' if red_expected else 'OFF'}]" if red_mismatch else " [MATCH]"
        log_message(f"Red Lamp: {red_status}{red_mismatch_text}")
    else:
        # Log standard senza verifica
        log_message(f"SPN: {spn_value}")
        log_message(f"FMI: {fmi_value}")
        log_message(f"Amber Lamp: {amber_status}")
        log_message(f"Red Lamp: {red_status}")
        
    log_message("======================================================")
    
    # Se richiesto, prepara i valori per la verifica ma non mostrare i risultati duplicati
    if verify_expected:
        # Prepara i valori per la verifica
        actual_values = {
            "SPN": recognized_values.get('SPN', 0) if recognized_values.get('SPN') is not None else 0,
            "FMI": recognized_values.get('FMI', 0) if recognized_values.get('FMI') is not None else 0,
            "LAMP": lamp_status
        }
    
    # Mostra il frame riconosciuto
    display_frame_in_panel(display_frame)
    
    # Prepara lo stato lampade da restituire
    app.last_recognition_values = recognized_values
    lamp_brightness_status = [lamp_amber_status, lamp_red_status]
    
    return recognized_values, lamp_brightness_status

def process_number_area_optimized(roi, display_frame, x1, y1, threshold_value, area_type="Unknown", slot_number=1):
    """
    Riconoscimento numeri ottimizzato per SPN e FMI con validazione range-specific
    
    Args:
        roi: Region of interest (area selezionata dall'immagine)
        display_frame: Frame su cui disegnare le informazioni di debug
        x1, y1: Coordinate dell'angolo in alto a sinistra dell'area
        threshold_value: Valore di threshold per la binarizzazione (da slider)
        area_type: "Number" per aree numeriche
        slot_number: 1 per SPN, 2 per FMI
        
    Returns:
        int or None: Il numero riconosciuto e validato o None se fallisce
    """
    try:
        # Determina il tipo di numero da riconoscere
        is_spn = (area_type == "Number" and slot_number == 1)
        is_fmi = (area_type == "Number" and slot_number == 2)
        
        # Imposta i range di validazione
        if is_spn:
            min_val, max_val = SPN_MIN, SPN_MAX
            area_name = "SPN"
        elif is_fmi:
            min_val, max_val = FMI_MIN, FMI_MAX
            area_name = "FMI"
        else:
            min_val, max_val = 0, 999999
            area_name = "Generic"
        
        # Step 1: Conversione a scala di grigi
        if roi.ndim == 3 and roi.shape[2] == 3:
            roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        elif roi.ndim == 2:
            roi_gray = roi
        else:
            log_message(f"ERROR: Input image must be 2D or 3D for {area_name}")
            return None
        
        # Step 2: Ridimensionamento adattivo basato sul tipo di numero
        height, width = roi_gray.shape
        
        if is_fmi:
            # FMI: numeri piccoli (0-31), aumentiamo di più il ridimensionamento
            min_target_size = 80
            scale_factor = max(min_target_size / min(width, height), 4.0)
        else:  # SPN o generico
            # SPN: numeri più grandi, ridimensionamento standard
            min_target_size = 60
            scale_factor = max(min_target_size / min(width, height), 3.0)
        
        scale_factor = min(scale_factor, 8.0)  # Limite massimo
        
        roi_resized = cv2.resize(roi_gray, None, fx=scale_factor, fy=scale_factor, 
                               interpolation=cv2.INTER_CUBIC)
        
        # Step 3: Preprocessing specifico per tipo di numero
        if is_fmi:
            # FMI: preprocessing più aggressivo per numeri piccoli
            roi_smooth = cv2.GaussianBlur(roi_resized, (5, 5), 0)
            # Miglioramento contrasto più marcato
            roi_enhanced = cv2.convertScaleAbs(roi_smooth, alpha=1.8, beta=20)
            roi_equalized = cv2.equalizeHist(roi_enhanced)
        else:
            # SPN: preprocessing standard
            roi_smooth = cv2.GaussianBlur(roi_resized, (3, 3), 0)
            roi_equalized = cv2.equalizeHist(roi_smooth)
        
        # Step 4: Binarizzazione
        _, roi_binary = cv2.threshold(roi_equalized, threshold_value, 255, cv2.THRESH_BINARY)
        
        # Step 5: Morphologia adattiva
        if is_fmi:
            # FMI: morfologia più leggera per preservare numeri piccoli
            kernel_size = 2
        else:
            # SPN: morfologia standard
            kernel_size = max(2, min(4, int(scale_factor / 2)))
        
        kernel = np.ones((kernel_size, kernel_size), dtype=np.uint8)
        roi_clean = cv2.morphologyEx(roi_binary, cv2.MORPH_OPEN, kernel)
        roi_clean = cv2.morphologyEx(roi_clean, cv2.MORPH_CLOSE, kernel)
        
        # Step 6: OCR ottimizzato per tipo di numero
        if is_fmi:
            # FMI: configurazioni ottimizzate per numeri piccoli (0-31)
            configs = [
                ("PSM10", "--psm 10 --oem 3 -c tessedit_char_whitelist=0123456789"),  # Singolo carattere
                ("PSM8", "--psm 8 --oem 3 -c tessedit_char_whitelist=0123456789"),   # Parola singola
                ("PSM7", "--psm 7 --oem 3 -c tessedit_char_whitelist=0123456789"),   # Riga singola
            ]
        else:
            # SPN: configurazioni ottimizzate per numeri grandi (1-524287)
            configs = [
                ("PSM8", "--psm 8 --oem 3 -c tessedit_char_whitelist=0123456789"),   # Parola singola
                ("PSM7", "--psm 7 --oem 3 -c tessedit_char_whitelist=0123456789"),   # Riga singola
                ("PSM6", "--psm 6 --oem 3 -c tessedit_char_whitelist=0123456789"),   # Blocco uniforme
                ("PSM10", "--psm 10 --oem 3 -c tessedit_char_whitelist=0123456789"), # Singolo carattere
            ]
        
        # Step 7: Riconoscimento con validazione specifica
        valid_results = []  # Lista di risultati validi
        
        for config_name, config_string in configs:
            try:
                result_data = pytesseract.image_to_data(roi_clean, config=config_string, 
                                                      output_type=pytesseract.Output.DICT)
                
                for j in range(len(result_data['text'])):
                    text = result_data['text'][j].strip()
                    conf = float(result_data['conf'][j]) if result_data['conf'][j] > 0 else 0
                    
                    # Verifica che sia un numero
                    if text.isdigit() and conf > 0:
                        try:
                            value = int(text)
                            
                            # VALIDAZIONE SPECIFICA PER RANGE
                            if min_val <= value <= max_val:
                                # Calcola score di qualità
                                quality_score = conf
                                
                                # Bonus per lunghezza appropriata
                                if is_fmi and 1 <= len(text) <= 2:
                                    quality_score *= 1.2  # FMI: 1-2 cifre
                                elif is_spn and 1 <= len(text) <= 6:
                                    quality_score *= 1.1  # SPN: 1-6 cifre
                                
                                # Bonus per configurazioni più accurate
                                if config_name in ["PSM8", "PSM7"]:
                                    quality_score *= 1.05
                                
                                valid_results.append({
                                    'value': value,
                                    'text': text,
                                    'confidence': conf,
                                    'quality_score': quality_score,
                                    'config': config_name
                                })
                        
                        except ValueError:
                            continue
            except:
                continue
        
        # Step 8: Selezione del miglior risultato valido
        if valid_results:
            # Ordina per quality_score decrescente
            valid_results.sort(key=lambda x: x['quality_score'], reverse=True)
            best_result = valid_results[0]
            
            # Soglia di confidence adattiva
            if is_fmi:
                confidence_threshold = 60  # FMI: soglia più bassa
            else:
                confidence_threshold = 70  # SPN: soglia standard
            
            if best_result['quality_score'] >= confidence_threshold:
                result_value = best_result['value']
                
                # SUCCESS - Disegna indicatori di successo
                roi_height, roi_width = roi.shape[:2]
                cv2.rectangle(display_frame, (x1, y1), (x1 + roi_width, y1 + roi_height), (0, 255, 0), 2)
                
                # Testo di debug dettagliato
                debug_text = f"{area_name}: {result_value} ({best_result['confidence']:.0f}%)"
                cv2.putText(display_frame, debug_text, (x1, y1 - 5),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                
                # Log di successo con dettagli
                log_message(f"✅ {area_name} SUCCESS: '{result_value}' "
                          f"(conf: {best_result['confidence']:.1f}%, "
                          f"quality: {best_result['quality_score']:.1f}, "
                          f"config: {best_result['config']})")
                
                return result_value
        
        # FALLIMENTO - Nessun risultato valido nel range
        roi_height, roi_width = roi.shape[:2]
        cv2.rectangle(display_frame, (x1, y1), (x1 + roi_width, y1 + roi_height), (0, 0, 255), 2)
        
        # Testo di debug per fallimento
        if valid_results:
            # Abbiamo risultati ma confidence troppo bassa
            best_invalid = max(valid_results, key=lambda x: x['confidence'])
            debug_text = f"{area_name}: {best_invalid['value']} (LOW:{best_invalid['confidence']:.0f}%)"
        else:
            # Nessun risultato nel range valido
            debug_text = f"{area_name}: OUT OF RANGE"
        
        cv2.putText(display_frame, debug_text, (x1, y1 - 5),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)
        
        # Log di fallimento con dettagli
        if valid_results:
            log_message(f"❌ {area_name} FAILED: Miglior risultato qualità {valid_results[0]['quality_score']:.1f} < {confidence_threshold}")
        else:
            log_message(f"❌ {area_name} FAILED: Nessun numero trovato nel range {min_val}-{max_val}")
        
        return None
        
    except Exception as e:
        log_message(f"ERRORE CRITICO in OCR {area_name}: {str(e)}")
        return None


def process_lamp_area(roi, display_frame, x1, y1, x2, y2, threshold):
    """Processa un'area di lampada (rimane uguale alla versione originale)"""
    # Elabora le aree delle lampade
    avg_lamp = np.mean(roi, axis=(0,1)).astype(int).tolist()
    
    # Calcola la luminosità utilizzando la formula standard
    luminosity = 0.299*avg_lamp[2] + 0.587*avg_lamp[1] + 0.114*avg_lamp[0]
    
    # Determina se la lampada è accesa basandosi sulla soglia
    is_bright = luminosity > threshold
    
    # Colore del rettangolo in base allo stato della lampada
    rect_lamp = (0, 255, 0) if is_bright else (0, 0, 255)
    cv2.rectangle(display_frame, (x1, y1), (x2, y2), rect_lamp, 2)
    
    return is_bright, luminosity

def add_lamp_info_to_frame(display_frame, x1, y1, lamp_name, luminosity, is_bright, threshold):
    """Aggiunge informazioni sulla lampada al frame di display (rimane uguale)"""
    # Aggiungi informazioni sulla luminosità e lo stato
    brightness_text = f"{lamp_name}: L:{int(luminosity)} Th:{threshold} ({'ON' if is_bright else 'OFF'})"
    
    # Posiziona il testo sopra l'area della lampada
    text_y = max(y1 - 10, 30)  # Assicurati che il testo non vada sopra la barra info
    cv2.putText(display_frame, brightness_text, (x1, text_y),
               cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

def verify_recognition_results(spn_value, fmi_value, lamp_amber_status, lamp_red_status,
                            spn_expected, fmi_expected, lamp_expected):
    """Verifica i risultati del riconoscimento contro i valori attesi"""
    # Comparazioni
    spn_match = spn_value == spn_expected if spn_value is not None else False
    fmi_match = fmi_value == fmi_expected if fmi_value is not None else False
    
    # Confronto lampade
    if lamp_expected == 'AMBER':
        lamp_match = lamp_amber_status and not lamp_red_status
    elif lamp_expected == 'RED':
        lamp_match = lamp_red_status and not lamp_amber_status
    else:  # NONE
        lamp_match = not lamp_amber_status and not lamp_red_status
    
    # Log dei risultati
    log_message(f"DTC Verification:")
    log_message(f"SPN: {'OK' if spn_match else 'ERROR'} (Expected: {spn_expected}, Recognized: {spn_value if spn_value is not None else 'N/A'})")
    log_message(f"FMI: {'OK' if fmi_match else 'ERROR'} (Expected: {fmi_expected}, Recognized: {fmi_value if fmi_value is not None else 'N/A'})")
    log_message(f"Lamp: {'OK' if lamp_match else 'ERROR'} (Expected: {lamp_expected})")
    
    # Risultato finale
    if spn_match and fmi_match and lamp_match:
        log_message("---- VERIFICATION PASSED ----")
        if app.dtc_frame and app.dtc_frame.csv_data and app.dtc_frame.current_dtc_index < len(app.dtc_frame.csv_data):
            app.dtc_frame.csv_data[app.dtc_frame.current_dtc_index]["error_found"] = False
    else:
        log_message("---- VERIFICATION FAILED ----")
        if app.dtc_frame and app.dtc_frame.csv_data and app.dtc_frame.current_dtc_index < len(app.dtc_frame.csv_data):
            app.dtc_frame.csv_data[app.dtc_frame.current_dtc_index]["error_found"] = True

# ====== Main Control Functions ======
def wait_for_canalyzer_message():
    """
    Attende un messaggio DM1 in modalità Canalyzer.
    Ignora messaggi da source address 0x27 e gestisce il countdown di 35 secondi.
    """
    try:
        # PGN fisso per DM1
        wait_pgn = 0xFECA
        # Source address da ignorare
        ignore_sa = 0x27
        
        # Ottieni parametri CAN
        channel = can_channel_var.get()
        bitrate = int(can_bitrate_var.get())
        
        # Reset delle variabili di stato
        app.canalyzer_last_processed_message = None
        app.canalyzer_is_acquisition_scheduled = False
        app.ecff_received = False
        
        log_message(f"Waiting for DM1 message with PGN 0x{wait_pgn:04X} in Canalyzer mode (ignoring SA=0x{ignore_sa:02X})...")
        
        # Crea il bus CAN
        bus = None
        try:
            bus = create_can_bus('vector', channel, bitrate)
            
            # Loop principale di attesa
            while app.running:
                # Ricezione con timeout
                msg = bus.recv(timeout=1.0)
                
                if not app.running:
                    break
                    
                if msg and msg.dlc == 8:
                    # Estrai il PGN e il source address
                    received_pgn = (msg.arbitration_id >> 8) & 0xFFFF
                    source_address = msg.arbitration_id & 0xFF
                    
                    # Se il PGN corrisponde a quello atteso
                    if received_pgn == wait_pgn:
                        # Verifica se il source address è quello da ignorare
                        if source_address == ignore_sa:
                            # Ignora silenziosamente questo messaggio
                            continue
                        
                        # Converti il messaggio in una stringa per il confronto
                        current_message = ' '.join(f'{b:02X}' for b in msg.data)
                        
                        # Se un'acquisizione è già programmata, ignora tutti i messaggi
                        if app.canalyzer_is_acquisition_scheduled:
                            continue
                            
                        # Se è un nuovo messaggio (diverso dall'ultimo elaborato)
                        if current_message != app.canalyzer_last_processed_message:
                            log_message(f"NEW DM1 MESSAGE DETECTED from SA=0x{source_address:02X}")
                            log_message(f"Current: [{current_message}]")
                            log_message(f"Last processed: [{app.canalyzer_last_processed_message}]")
                            
                            # Memorizza questo messaggio come "da elaborare"
                            app.message_to_process = current_message
                            
                            # Imposta i flag
                            app.ecff_received = True
                            app.canalyzer_is_acquisition_scheduled = True
                            
                            # Avvia il countdown di 35 secondi
                            #log_message(">>> Starting 35 second countdown for recognition")
                            root.after(0, lambda: start_recognition_countdown(35))
                            
                            # Programma l'acquisizione dopo 35 secondi
                            root.after(35000, schedule_canalyzer_acquisition)
                        else:
                            log_message(f"Ignoring duplicate DM1 message (same as last processed)")
            
            # Chiudi il bus quando esci dal loop
            if bus:
                bus.shutdown()
                
        except can.CanError as e:
            log_message(f"CAN error during Canalyzer listening: {str(e)}")
        except Exception as e:
            log_message(f"Error during Canalyzer message waiting: {str(e)}")
            log_message(f"Exception details: {type(e)}")
        finally:
            # Chiudi sempre il bus se è ancora aperto
            if bus:
                try:
                    bus.shutdown()
                except:
                    pass
                    
    except Exception as e:
        log_message(f"Error initializing Canalyzer CAN waiting: {str(e)}")
    finally:
        # Resetta il flag di attesa
        app.waiting_for_can = False


def start_recognition():
    """Starts the process of waiting for the CAN message"""
    # Verify that there are selected areas
    if not app.areas:
        log_message("Error: no area selected")
        return
    
    # Se l'acquisizione è già in corso, fermala prima
    if app.running:
        log_message("Stopping current acquisition before starting a new one")
        stop_recognition()
        # Piccola pausa per assicurarsi che i thread precedenti si fermino
        time.sleep(0.5)
    
    # Close the area selection window if it's still open
    try:
        if cv2.getWindowProperty("Select areas", cv2.WND_PROP_VISIBLE) >= 1:
            cv2.destroyWindow("Select areas")
    except:
        pass # Ignore errors if window doesn't exist
    
    # Reset the message counter when starting
    app.can_message_counter = 1
    
    # Set running to True to indicate that the system is running
    app.running = True
    
    # AGGIUNTA: imposta il flag di riconoscimento avviato
    if app.dtc_frame:
        app.dtc_frame.update_main_recognition_state(True)
    
    # Aggiorna la visualizzazione delle aree per disabilitare i pulsanti di rimozione
    update_area_display()
        
    # Inizializza la webcam con la funzione delayed
    if not initialize_webcam_delayed(app):
        log_message("Errore: impossibile inizializzare la webcam")
        app.running = False
        update_button_states('initial')
        return
    
    # Check if already waiting for a CAN message
    if not app.waiting_for_can:
        app.waiting_for_can = True  # Set flag to True before starting the thread
        
        # Ottieni la modalità corrente
        is_canalyzer_mode = app.is_canalyzer_mode
        log_message(f"Starting in {'Canalyzer' if is_canalyzer_mode else 'DTC Test'} mode")
        
        # CORREZIONE: Usa approcci diversi in base alla modalità
        if is_canalyzer_mode:
            # In modalità Canalyzer, avvia il thread di ascolto DM1
            log_message("Starting acquisition in Canalyzer mode")
            threading.Thread(target=wait_for_canalyzer_message, daemon=True).start()
        else:
            # In modalità DTC Test, non avviamo wait_for_canalyzer_message
            # Il DTC Test sarà avviato manualmente dall'utente tramite il pulsante "Start DTC Test"
            log_message("Recognition started - Press 'Start DTC Test' to begin testing")
            # Resetta il flag di attesa perché non usiamo wait_for_canalyzer_message in questa modalità
            app.waiting_for_can = False
    else:
        log_message("Already waiting for CAN message...")
    
    # Update button states after starting recognition
    update_button_states('start')
    
    # Avvia l'anteprima continua se richiesto
    if hasattr(app, 'live_preview_during_recognition') and app.live_preview_during_recognition:
        log_message("Started Live Preview during recognition")
        start_continuous_preview()


def stop_recognition():
    """Stops the recognition process and resets the state."""
    # Disabilita il flag di esecuzione
    app.running = False
    app.ecff_received = False
    app.waiting_for_can = False  # Reset waiting flag when stopping recognition
    app.can_message_counter = 1  # Reset the counter
    
    # Ferma l'aggiornamento della threshold preview
    app.continue_threshold_preview = False
    
    # Ferma l'anteprima continua se attiva
    if hasattr(app, 'preview_running') and app.preview_running:
        log_message("Preview stopped, continues during recognize process")
        stop_continuous_preview()
    
    # AGGIUNTA: resetta il flag di riconoscimento
    if app.dtc_frame:
        app.dtc_frame.update_main_recognition_state(False)
    
    # Chiude la webcam solo se non c'è live view attiva
    if not hasattr(app, 'live_view_active') or not app.live_view_active:
        if app.cap is not None and app.cap.isOpened():
            app.cap.release()
            app.cap = None
            log_message("Webcam closed")
    
    log_message("Acquisition stopped. CAN counter reset.")
    
    # Aggiorna la visualizzazione delle aree per riabilitare i pulsanti di rimozione
    update_area_display()
    
    # Ripristina lo stato dei bottoni
    update_button_states('stop')
    
    # Ricrea la finestra di selezione delle aree se ci sono ancora aree
    if app.areas:
        reopen_area_selection()
        
    # Ferma la riproduzione ASC se attiva
    if hasattr(app, 'asc_playback_active') and app.asc_playback_active:
        stop_asc_playback()
        if app.dtc_frame:
            update_asc_player_ui(app.dtc_frame, False)

def reopen_area_selection():
    """Reopens the area selection window with the current areas"""
    try:
        # Se la webcam è già chiusa, riapriamola
        if app.cap is None or not app.cap.isOpened():
            app.cap = cv2.VideoCapture(app.selected_camera, cv2.CAP_DSHOW)
            if not app.cap.isOpened():
                log_message("Error reopening webcam for area selection")
                return
                
            # Imposta la risoluzione
            set_camera_resolution(app.cap, app.selected_resolution)
            
            # Applica i parametri della webcam
            update_webcam_contrast(webcam_contrast_slider.get())
            update_webcam_saturation(webcam_saturation_slider.get())
            update_webcam_exposure(webcam_exposure_slider.get())
        
        # Acquisisci un nuovo frame
        ret, app.frame = app.cap.read()
        if not ret:
            log_message("Error acquiring frame for area selection")
            return
            
        # Non applichiamo più l'elaborazione dell'immagine, usiamo il frame così com'è
        app.current_frame = app.frame.copy()
        
        # Crea una nuova finestra per la selezione delle aree
        cv2.namedWindow("Select areas", cv2.WINDOW_NORMAL)
        
        # Ridimensiona la finestra in modo appropriato
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        height, width = app.frame.shape[:2]
        
        max_display_width = min(width, int(screen_width * 0.6))
        max_display_height = min(height, int(screen_height * 0.8))
        aspect_ratio = width / height
        
        if width > height:
            display_width = max_display_width
            display_height = int(display_width / aspect_ratio)
            if display_height > max_display_height:
                display_height = max_display_height
                display_width = int(display_height * aspect_ratio)
        else:
            display_height = max_display_height
            display_width = int(display_height * aspect_ratio)
            if display_width > max_display_width:
                display_width = max_display_width
                display_height = int(display_width / aspect_ratio)
        
        cv2.resizeWindow("Select areas", display_width, display_height)
        
        # Imposta il callback per la selezione delle aree
        cv2.setMouseCallback("Select areas", select_area_or_lamp)
        
        # Disegna le aree esistenti
        display_frame = app.frame.copy()
        display_frame = draw_all_areas_with_labels(display_frame)
        cv2.imshow("Select areas", display_frame)
        app.current_frame = display_frame.copy()
        
        log_message("Area selection window reopened")
        
    except Exception as e:
        log_message(f"Error reopening area selection: {str(e)}")

def init_camera_list():
    """Function to call after the interface has been created"""
    #log_time("Inizio init_camera_list")
    
    # Detect available webcams - usa la versione leggera per l'avvio
    # cameras = list_cameras()  # Versione pesante originale
    cameras = list_cameras_light()  # Versione leggera per l'avvio rapido
    
    if not cameras:
        log_message("WARNING: No webcams found!")
    else:
        log_message(f"Webcams found: {len(cameras)}")
    
    #log_time("Fine init_camera_list")


def update_channel_options(event=None):
    """Update channel options for Vector interface"""
    global can_channel_combo, can_channel_var, can_channel_label

    # Vector specific channel options
    can_channel_combo['values'] = ["0", "1"]
    can_channel_var.set("0")
    can_channel_label.config(text="Channel:")
    
    # Log the update
    #log_message(f"Selected Vector interface, updated channel options")

def initialize_application():
    """Initializes the application and sets up the UI components"""
    #log_time("Inizio initialize_application")
    
    # Detect available webcams
    #log_time("Prima di init_camera_list")
    init_camera_list()
    #log_time("Dopo init_camera_list")
    
    # Inizializza le proprietà per la Live View
    app.live_view_active = False
    app.slider_changed = False
    
    # Inizializza le nuove proprietà per il Live Preview durante riconoscimento
    app.live_preview_during_recognition = True  # Impostato a True di default
    app.preview_running = False
    
    # Inizializza proprietà per DTC Test
    #log_time("Prima dell'inizializzazione DTC Test properties")
    app.is_canalyzer_mode = True  # Default to Canalyzer mode
    app.csv_file_path = None
    app.csv_data = []
    app.current_dtc_index = 0
    app.dm1_thread_running = False
    app.dm1_thread = None
    app.ocr_threshold = 240
    #log_time("Dopo inizializzazione DTC Test properties")
    
    # Inizializza il flag di riconoscimento principale
    app.main_recognition_started = False

    # Creazione frame DTCAutoTestFrame nella parte superiore del pannello destro
    #log_time("Prima della creazione DTCAutoTestFrame")
    app.dtc_frame = DTCAutoTestFrame(top_right_frame)
    app.dtc_frame.pack(fill="x", expand=False, padx=5, pady=5)
    #log_time("Dopo la creazione DTCAutoTestFrame")
    
    # AGGIUNTA: Assicura che i controlli ASC siano correttamente inizializzati
    # indipendentemente dalla modalità
    app.dtc_frame.select_asc_button.config(state=tk.NORMAL)
    
    # Ensure Vector is set as the only option
    global can_interface_var
    can_interface_var.set("vector")
    update_channel_options()
    
    # Aggiorna i valori iniziali degli slider webcam con i valori predefiniti
    webcam_contrast_slider.set(app.webcam_contrast)
    webcam_saturation_slider.set(app.webcam_saturation)
    webcam_exposure_slider.set(app.webcam_exposure)
    webcam_focus_slider.set(app.webcam_focus)
    ocr_threshold_slider.set(app.ocr_threshold)

    # Log iniziale
    log_message("Application initialized")
    log_message("Webcam default settings: Brightness=4, Contrast=7, Saturation=60, Exposure=-10")
    log_message("Use 'Start Live View' to see webcam e regulate parameters")
    
    # AGGIUNTA: Log per indicare che ASC Player è disponibile in tutte le modalità
    log_message("ASC Trace Player is available in all modes (including Canalyzer mode)")
    
    # AGGIUNTA: Log per indicare che Live Preview è disponibile e attivo di default
    log_message("Live Preview during recognition is ENABLED by default")
    
    # AGGIUNTA: Log per indicare che OCR Threshold Preview è disponibile
    log_message("OCR Threshold Preview added - press Start Live, after selecting areas, for choose the optimal value")
    
    #log_time("Fine initialize_application")
    
    # Ora che output_text è definito, possiamo visualizzare tutti i log di timing
    #display_time_logs()

def display_time_logs():
    """Visualizza tutti i log di timing memorizzati"""
    for log in TIME_LOGS:
        log_message(log)
    
    # Pulisci la lista dopo averli visualizzati
    TIME_LOGS.clear()

def parse_asc_file(file_path):
    """
    Parsa un file ASC di traccia CAN nel formato specifico.
    Supporta il formato con ID esadecimali seguiti da 'x' e campi Length e BitCount.
    
    Returns:
        list: Lista di dizionari con i campi:
            - timestamp: tempo assoluto del messaggio
            - arbitration_id: ID CAN
            - is_extended_id: True se è un ID esteso
            - data: lista di byte di dati
            - relative_time: tempo relativo dal messaggio precedente
    """
    log_message(f"Parsing ASC file: {file_path}")
    messages = []
    prev_timestamp = 0
    
    try:
        with open(file_path, 'r', errors='replace') as file:
            for line_number, line in enumerate(file, 1):
                line = line.strip()
                
                # Ignora linee vuote, commenti, intestazioni e stati
                if (not line or line.startswith('//') or line.startswith('date ') or 
                    line.startswith('base ') or line.startswith('internal ') or 
                    line.startswith('Begin ') or line.startswith('End ') or 
                    "Status:" in line or "Start of measurement" in line):
                    continue
                
                try:
                    # Dividi la linea in parti
                    parts = line.split()
                    
                    # Deve avere almeno 10 parti per essere un messaggio CAN valido
                    # timestamp, channel, ID, Rx/Tx, d, DLC, [dati...]
                    if len(parts) < 10:
                        continue
                    
                    # Prima parte deve essere un timestamp numerico
                    try:
                        timestamp = float(parts[0])
                    except ValueError:
                        # Non è un timestamp, salta
                        continue
                    
                    # Terza parte dovrebbe contenere l'ID CAN, spesso seguito da 'x'
                    id_part = parts[2]
                    
                    # Controlla se l'ID termina con 'x' (indica ID esteso)
                    is_extended = id_part.endswith('x')
                    
                    # Rimuovi il suffisso 'x' se presente
                    if is_extended:
                        id_part = id_part[:-1]
                    
                    # Converti l'ID in un numero
                    try:
                        can_id = int(id_part, 16)
                    except ValueError:
                        continue
                    
                    # Trova la direzione del messaggio (Rx/Tx)
                    direction = parts[3]
                    if direction not in ["Rx", "Tx"]:
                        continue
                    
                    # Verifica che il tipo di frame sia corretto (tipicamente 'd')
                    frame_type = parts[4]
                    if frame_type != 'd':
                        continue
                    
                    # Ottieni la lunghezza dati (DLC)
                    try:
                        dlc = int(parts[5])
                    except ValueError:
                        continue
                    
                    # Raccogli i byte di dati
                    data = []
                    for i in range(6, 6 + dlc):
                        if i < len(parts):
                            try:
                                data.append(int(parts[i], 16))
                            except ValueError:
                                continue
                    
                    # Calcola il tempo relativo
                    relative_time = timestamp - prev_timestamp if prev_timestamp else 0
                    prev_timestamp = timestamp
                    
                    # Crea il messaggio come dizionario (non un oggetto con attributi)
                    message_dict = {
                        'timestamp': timestamp,
                        'arbitration_id': can_id,
                        'is_extended_id': is_extended,
                        'data': data,
                        'relative_time': relative_time,
                        'direction': direction
                    }
                    
                    # Aggiungi alla lista
                    messages.append(message_dict)
                    
                except Exception as e:
                    log_message(f"Error parsing line {line_number}: {line}. Error: {str(e)}")
            
        log_message(f"Parsed {len(messages)} CAN messages from ASC file")
        
        # Debug: log dei primi 3 messaggi
        for i, msg in enumerate(messages[:3]):
            if i < 3:
                hex_data = ' '.join(f'{b:02X}' for b in msg['data'])
                log_message(f"Message {i+1}: ID=0x{msg['arbitration_id']:X}, Dir={msg['direction']}, " + 
                          f"Extended={msg['is_extended_id']}, Data=[{hex_data}]")
        
        return messages
    except Exception as e:
        log_message(f"Error reading ASC file: {str(e)}")
        return []

def play_asc_trace(messages, dtc_frame):
    """
    Riproduce una traccia ASC inviando i messaggi CAN con i tempi appropriati
    
    Args:
        messages: Lista di messaggi CAN parsati
        dtc_frame: Riferimento al frame DTC per aggiornare l'UI
    """
    # Ottieni parametri CAN
    channel = can_channel_var.get()
    bitrate = int(can_bitrate_var.get())
    
    try:
        log_message(f"Starting ASC trace playback with {len(messages)} messages")
        start_time = time.time()
        last_msg_timestamp = messages[0]['timestamp'] if messages else 0
        
        # Connetti al bus CAN
        bus = create_can_bus('vector', channel, bitrate)
        
        # Imposta flag di playback attivo
        app.asc_playback_active = True
        
        msg_counter = 0
        
        # Ciclo principale di riproduzione
        for msg_idx, msg_data in enumerate(messages):
            # Controlla se il playback è stato interrotto
            if not hasattr(app, 'asc_playback_active') or not app.asc_playback_active:
                log_message("ASC trace playback stopped")
                break
                
            # Calcola il tempo di attesa basato sui timestamp relativi
            if msg_idx > 0:
                wait_time = msg_data['timestamp'] - messages[msg_idx-1]['timestamp']
                # Limita il tempo massimo di attesa a 1 secondo
                #wait_time = min(max(0, wait_time), 0.5)

                #if wait_time > 0.001:  # Ignora ritardi troppo piccoli
                time.sleep(wait_time)

            
            # Crea messaggio CAN
            try:
                can_msg = can.Message(
                    arbitration_id=msg_data['arbitration_id'],
                    data=msg_data['data'],
                    is_extended_id=msg_data['is_extended_id'],
                    dlc=len(msg_data['data'])
                )
                
                # Invia messaggio
                bus.send(can_msg)
                
                # Log ogni 50 messaggi per non sovraccaricarlo
                msg_counter += 1
                if msg_counter % 50 == 0:
                    # Formatta i dati in esadecimale
                    hex_data = ' '.join(f'{b:02X}' for b in msg_data['data'])
                    #log_message(f"ASC Msg #{msg_counter}: ID=0x{msg_data['arbitration_id']:X}, " + f"Data=[{hex_data}]")

            except Exception as e:
                log_message(f"Error sending CAN message: {str(e)}")
        
        log_message(f"ASC trace playback completed, sent {msg_counter} messages")
        
        # Se è stata completata normalmente e la riproduzione in loop è attiva, riavvia
        if hasattr(app, 'asc_playback_active') and app.asc_playback_active and hasattr(app, 'asc_loop_playback') and app.asc_loop_playback:
            log_message("Restarting ASC trace in loop mode")
            threading.Thread(target=play_asc_trace, args=(messages, dtc_frame), daemon=True).start()
        else:
            # Reset flag
            app.asc_playback_active = False
            root.after(0, lambda: update_asc_player_ui(dtc_frame, False))
            
    except Exception as e:
        log_message(f"Error in ASC trace playback: {str(e)}")
        app.asc_playback_active = False
        root.after(0, lambda: update_asc_player_ui(dtc_frame, False))
    finally:
        # Chiudi la connessione CAN
        if 'bus' in locals() and bus:
            bus.shutdown()

def stop_asc_playback():
    """Ferma la riproduzione della traccia ASC"""
    app.asc_playback_active = False
    log_message("Stopping ASC trace playback")

def update_asc_player_ui(dtc_frame, is_playing):
    """Aggiorna l'interfaccia del player ASC in base allo stato"""
    if is_playing:
        # Disabilita il pulsante Play e abilita Stop
        dtc_frame.play_asc_button.config(state=tk.DISABLED)
        dtc_frame.stop_asc_button.config(state=tk.NORMAL)
    else:
        # Abilita il pulsante Play e disabilita Stop
        if dtc_frame.asc_file_path:
            dtc_frame.play_asc_button.config(state=tk.NORMAL)
        dtc_frame.stop_asc_button.config(state=tk.DISABLED)

# Dobbiamo modificare le funzioni che chiamano dtc_frame.add_error()

def select_asc_file(dtc_frame):
    """Apre un dialogo per selezionare un file ASC"""
    file_path = filedialog.askopenfilename(
        title="Select ASC Trace File",
        filetypes=[("ASC files", "*.asc"), ("All files", "*.*")]
    )
    
    if file_path:
        dtc_frame.asc_file_path = file_path
        
        # Mostra il nome del file selezionato
        filename = os.path.basename(file_path)
        if len(filename) > 25:
            # Tronca il nome se troppo lungo
            filename = filename[:22] + "..."
        dtc_frame.asc_file_label.config(text=f"ASC: {filename}", fg="blue")
        
        # Abilita il pulsante Play
        dtc_frame.play_asc_button.config(state=tk.NORMAL)
        
        # Parsa il file ASC (in un thread separato per non bloccare l'interfaccia)
        log_message(f"Loading ASC file: {filename}")
        threading.Thread(target=load_asc_file, args=(dtc_frame, file_path), daemon=True).start()

def load_asc_file(dtc_frame, file_path):
    """Carica e parsa un file ASC in un thread separato"""
    try:
        # Parsa il file ASC
        messages = parse_asc_file(file_path)
        
        # Aggiorna i messaggi nella classe
        dtc_frame.asc_messages = messages
        
        # Aggiorna l'interfaccia utente nel thread principale
        root.after(0, lambda: log_message(f"Loaded {len(messages)} CAN messages from ASC file"))
    except Exception as e:
        root.after(0, lambda: log_message(f"Error loading ASC file: {str(e)}"))

def play_asc_file(dtc_frame):
    """Avvia la riproduzione del file ASC"""
    if not dtc_frame.asc_file_path or not dtc_frame.asc_messages:
        log_message("No valid ASC file loaded")
        return
    
    # Verifica che l'acquisizione non sia già in corso
    if hasattr(app, 'asc_playback_active') and app.asc_playback_active:
        log_message("ASC trace playback already running")
        return
    
    # Imposta i flag per la riproduzione
    app.asc_playback_active = True
    app.asc_loop_playback = dtc_frame.asc_loop_var.get()
    
    # Aggiorna l'interfaccia
    update_asc_player_ui(dtc_frame, True)
    
    # Avvia il thread di riproduzione
    threading.Thread(target=play_asc_trace, args=(dtc_frame.asc_messages, dtc_frame), daemon=True).start()
    
    # Log
    log_message(f"Starting ASC playback with {len(dtc_frame.asc_messages)} messages" + 
               f" (Loop: {'Enabled' if app.asc_loop_playback else 'Disabled'})")

def stop_asc_file_playback(dtc_frame):
    """Ferma la riproduzione del file ASC"""
    stop_asc_playback()
    update_asc_player_ui(dtc_frame, False)
    log_message("ASC playback stopped by user")


def verify_ff99_response(sent_dtc, received_values):
    """
    Verifica i valori ricevuti contro quelli inviati nel DM1
    
    Args:
        sent_dtc: Dizionario con i valori inviati nel DM1
        received_values: Dizionario con i valori ricevuti dal riconoscimento
    """
    # Confronta SPN
    spn_match = sent_dtc['SPN'] == received_values['SPN']
    
    # Confronta FMI
    fmi_match = sent_dtc['FMI'] == received_values['FMI']
    
    # Confronta stato lampada
    lamp_match = sent_dtc['LAMP'] == received_values['LAMP']
    
    # Logga i risultati
    #log_message(f"Verification results:")
    #log_message(f"SPN: {'MATCH' if spn_match else 'MISMATCH'} (Expected: {sent_dtc['SPN']}, Got: {received_values['SPN']})")
    #log_message(f"FMI: {'MATCH' if fmi_match else 'MISMATCH'} (Expected: {sent_dtc['FMI']}, Got: {received_values['FMI']})")
    #log_message(f"LAMP: {'MATCH' if lamp_match else 'MISMATCH'} (Expected: {sent_dtc['LAMP']}, Got: {received_values['LAMP']})")
    
    # Verifica globale
    is_match = spn_match and fmi_match and lamp_match
    
    # Imposta il flag di errore se c'è una discrepanza
    if not is_match:
        #log_message("ERROR: Mismatch detected between sent DTC and received values")
        sent_dtc['error_found'] = True
        
        # Aggiorna il contatore degli errori globale
        app.errors_found += 1
        
        # Log dettagliato degli errori
        '''
        if not spn_match:
            log_message(f"SPN Mismatch: Expected {sent_dtc['SPN']}, Got {received_values['SPN']}")
        
        if not fmi_match:
            log_message(f"FMI Mismatch: Expected {sent_dtc['FMI']}, Got {received_values['FMI']}")
        
        if not lamp_match:
            log_message(f"Lamp Status Mismatch: Expected {sent_dtc['LAMP']}, Got {received_values['LAMP']}")
        '''
    else:
        log_message("All values match correctly")
        sent_dtc['error_found'] = False
    
    # Restituisce il risultato del match per eventuale ulteriore elaborazione
    return is_match

# ====== DTCAutoTestFrame Class ======
class DTCAutoTestFrame(tk.Frame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.parent = parent
        
        # ASC player variables
        self.asc_file_path = None
        self.asc_messages = []
        
        # Variabili per CSV e DTC
        self.csv_file_path = None

        self.auto_save_log_var = tk.BooleanVar(value=False)  # Attivo di default
        
        # Create the main frame
        self.create_widgets()

    def add_error(self, error_text):
        """Metodo di compatibilità che redireziona i messaggi a log_message"""
        log_message(error_text)

    def update_dtc_start_button_state(self):
        """Aggiorna lo stato del pulsante Start DTC Test"""
        # Abilita solo se:
        # 1. Riconoscimento principale avviato
        # 2. CSV caricato
        # 3. Non in modalità Canalyzer
        if (hasattr(app, 'main_recognition_started') and 
            app.main_recognition_started and 
            self.csv_file_path and 
            not self.canalyzer_var.get()):
            self.start_dtc_button.config(state=tk.NORMAL)
        else:
            self.start_dtc_button.config(state=tk.DISABLED)

    def update_main_recognition_state(self, started):
        """
        Aggiorna lo stato del riconoscimento principale
        e abilita/disabilita il pulsante Start DTC Test di conseguenza
        """
        # Imposta il flag globale
        app.main_recognition_started = started
        
        # Aggiorna lo stato del pulsante
        self.update_dtc_start_button_state()

    def toggle_canalyzer_mode(self):
        """
        Enables or disables input fields based on Canalyzer mode
        """
        is_canalyzer_mode = self.canalyzer_var.get()
        app.is_canalyzer_mode = is_canalyzer_mode
        
        # Log essenziale
        log_message(f"Canalyzer mode {'activated' if is_canalyzer_mode else 'deactivated'}")
        
        # Se l'acquisizione è in corso, fermala prima di cambiare modalità
        if app.running:
            log_message("Stopping acquisition due to mode change")
            stop_recognition()  # Richiama direttamente la funzione di stop
        
        # In modalità Canalyzer, disabilita il pulsante Select CSV
        if is_canalyzer_mode:
            self.select_csv_button.config(state=tk.DISABLED)
            self.start_dtc_button.config(state=tk.DISABLED)
            self.stop_dtc_button.config(state=tk.DISABLED)
            
            # MODIFICATO: Mantieni abilitati i controlli ASC anche in modalità Canalyzer
            self.select_asc_button.config(state=tk.NORMAL)
            if self.asc_file_path:
                self.play_asc_button.config(state=tk.NORMAL)
            if hasattr(app, 'asc_playback_active') and app.asc_playback_active:
                self.stop_asc_button.config(state=tk.NORMAL)
            else:
                self.stop_asc_button.config(state=tk.DISABLED)
            self.loop_asc_check.config(state=tk.NORMAL)
        else:
            # In modalità DTC Test, abilita il pulsante Select CSV
            self.select_csv_button.config(state=tk.NORMAL)
            
            # Abilita il pulsante Start solo se un file CSV è selezionato
            if app.running and self.csv_file_path:
                self.start_dtc_button.config(state=tk.NORMAL)
            else:
                self.start_dtc_button.config(state=tk.DISABLED)
            # Stop viene abilitato solo quando il test è in esecuzione
            
            # ASC Player controlli - lasciati come erano
            self.select_asc_button.config(state=tk.NORMAL)
            if self.asc_file_path:
                self.play_asc_button.config(state=tk.NORMAL)
            # Stato specifico per ASC stop button
            if hasattr(app, 'asc_playback_active') and app.asc_playback_active:
                self.stop_asc_button.config(state=tk.NORMAL)
            else:
                self.stop_asc_button.config(state=tk.DISABLED)
            self.loop_asc_check.config(state=tk.NORMAL)

    def select_csv_file(self):
        """Opens a dialog to select a CSV file containing DTC codes"""
        file_path = filedialog.askopenfilename(
            title="Select DTC CSV file",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        
        if file_path:
            self.csv_file_path = file_path
            app.csv_file_path = file_path
            
            # Show the selected file name
            filename = os.path.basename(file_path)
            if len(filename) > 25:
                # Truncate name if too long
                filename = filename[:22] + "..."
            self.csv_file_label.config(text=f"CSV: {filename}", fg="blue")
            
            # Load the CSV file contents
            self.load_csv_data(file_path)
            
            # Aggiorna lo stato del pulsante DTC
            self.update_dtc_start_button_state()
    
    def load_csv_data(self, file_path):
        """Loads data from the selected CSV file with custom format"""
        try:
            app.csv_data = []
            with open(file_path, 'r', newline='') as csvfile:
                # Try with semicolon as separator first
                dialect = csv.Sniffer().sniff(csvfile.read(1024))
                csvfile.seek(0)
                
                # Determine the separator (default: semicolon)
                delimiter = dialect.delimiter if dialect.delimiter in [';', ','] else ';'
                
                reader = csv.reader(csvfile, delimiter=delimiter)
                
                # Read the header
                header = next(reader, None)
                if not header:
                    log_message("CSV Error: Empty file or no header found")
                    return
                
                # Normalize headers (remove spaces and convert to uppercase)
                header = [col.strip().upper() for col in header]
                
                # Check if required columns are present
                col_map = {}
                
                # Map found columns
                for i, col in enumerate(header):
                    if "SOURCE" in col and "CONTROLLER" in col:
                        col_map["DTC_SOURCE"] = i
                    elif "SPN" in col:
                        col_map["SPN"] = i
                    elif "FMI" in col:
                        col_map["FMI"] = i
                    elif "LAMP" in col:
                        col_map["LAMP"] = i
                    elif "DESCRIPTION" in col:
                        col_map["DESCRIPTION"] = i
                
                # Check if all required columns were found
                if not all(col in col_map for col in ["SPN", "FMI", "LAMP"]):
                    log_message(f"CSV Format Error: Missing required columns. Found: {header}")
                    return
                
                # Read data
                line_num = 2  # Start from row 2 (after header)
                for row in reader:
                    if len(row) >= max(col_map.values()) + 1:
                        try:
                            # Convert LAMP values from numbers/strings to AMBER/RED/NONE values
                            lamp_value = row[col_map["LAMP"]].strip().upper()
                            
                            # Handle numeric format for LAMP (0=NONE, 1=AMBER, 2=RED)
                            if lamp_value in ["0", "NONE"]:
                                lamp_status = "NONE"
                            elif lamp_value in ["1", "AMBER"]:
                                lamp_status = "AMBER"
                            elif lamp_value in ["2", "RED"]:
                                lamp_status = "RED"
                            else:
                                lamp_status = lamp_value  # Keep original value if not recognized
                            
                            # Handle DTC Source Controller (format 0xNN or NN)
                            sa_value = 0
                            if "DTC_SOURCE" in col_map:
                                sa_str = row[col_map["DTC_SOURCE"]].strip()
                                # Remove 0x prefix if present
                                sa_str = sa_str[2:] if sa_str.lower().startswith("0x") else sa_str
                                try:
                                    # Try to convert from hexadecimal to integer
                                    sa_value = int(sa_str, 16)
                                except ValueError:
                                    # If it fails, try as decimal integer
                                    try:
                                        sa_value = int(sa_str)
                                    except ValueError:
                                        log_message(f"Row {line_num}: Invalid Source Address format: {sa_str}")
                            
                            # Build DTC entry
                            dtc_entry = {
                                "SPN": int(row[col_map["SPN"]]),
                                "FMI": int(row[col_map["FMI"]]),
                                "LAMP": lamp_status,
                                "SA": sa_value,
                                "error_found": False  # Per tracciare gli errori
                            }
                            
                            # Add description if available
                            if "DESCRIPTION" in col_map and len(row) > col_map["DESCRIPTION"]:
                                dtc_entry["DESCRIPTION"] = row[col_map["DESCRIPTION"]]
                            else:
                                dtc_entry["DESCRIPTION"] = f"DTC {dtc_entry['SPN']}-{dtc_entry['FMI']}"
                                
                            app.csv_data.append(dtc_entry)
                            
                        except ValueError as e:
                            log_message(f"Row {line_num}: {str(e)}")
                        except Exception as e:
                            log_message(f"Row {line_num}: Unexpected error: {str(e)}")
                    
                    line_num += 1
            
            # If data was loaded successfully, set the first element
            if app.csv_data:
                app.current_dtc_index = 0
                
                # Update log with summary
                log_message(f"Loaded {len(app.csv_data)} DTC codes from CSV")
            else:
                log_message("No valid DTC codes found in the CSV file")
        
        except Exception as e:
            log_message(f"Error loading CSV: {str(e)}")

        log_message("First 3 DTC entries:")
        for dtc in app.csv_data[:3]:
            log_message(str(dtc))

    def execute_dtc_acquisition(self, expected_index):
        """
        Esegue l'acquisizione per il DTC corrente
        
        Args:
            expected_index: Indice DTC atteso per verificare che non sia cambiato
        """
        # Verifica che l'indice non sia cambiato
        if app.current_dtc_index != expected_index:
            log_message(f"Skipping acquisition for DTC {expected_index+1} - already processed")
            return
            
        log_message(f"Executing acquisition for DTC {expected_index+1} after 35s countdown")
        
        try:
            # Verifica che l'acquisizione sia ancora in corso
            if not app.running or not app.dm1_thread_running:
                log_message("Acquisition skipped - test not running anymore")
                return
                
            # Verifica che l'acquisizione sia ancora in corso
            if app.cap is not None and app.cap.isOpened():
                #log_message("Starting webcam capture")
                
                # Warm up webcam
                for _ in range(3):
                    app.cap.read()
                    
                ret, frame = app.cap.read()
                
                if ret:
                    #log_message("Frame captured successfully")
                    
                    # Riconoscimento con verifica
                    log_message("Starting image recognition...")
                    recognized_values, lamp_brightness_status = process_frame(frame.copy(), verify_expected=True)
                    
                    # Ottieni lo stato della lampada
                    lamp_status = "NONE"
                    if lamp_brightness_status and len(lamp_brightness_status) > 0:
                        if lamp_brightness_status[0]:
                            lamp_status = "AMBER"
                        elif len(lamp_brightness_status) > 1 and lamp_brightness_status[1]:
                            lamp_status = "RED"
                    
                    # Prepara i valori riconosciuti
                    recognized_dtc = {
                        "SPN": recognized_values.get('SPN', 0) if recognized_values.get('SPN') is not None else 0,
                        "FMI": recognized_values.get('FMI', 0) if recognized_values.get('FMI') is not None else 0,
                        "LAMP": lamp_status
                    }
                    
                    # Verifica i valori con quelli attesi senza inviare 0xFF99
                    if expected_index < len(app.csv_data):
                        current_dtc = app.csv_data[expected_index]
                        verify_ff99_response(current_dtc, recognized_dtc)
                    
                    # Avanza all'indice successivo
                    app.current_dtc_index += 1
                    #log_message(f"Advanced to next DTC index: {app.current_dtc_index}")
                else:
                    log_message("Error: unable to capture frame from webcam")
            else:
                log_message("Error: webcam not initialized or closed")
        except Exception as e:
            log_message(f"Error during acquisition: {str(e)}")

    def dm1_sender_thread(self):
        """
        Thread per l'invio di messaggi DM1 in modo ciclico solo in modalità DTC Test.
        Invia lo stesso messaggio ogni secondo fino a scadere il timeout di 35 secondi.
        """
        # Verifica che non sia in modalità Canalyzer
        if app.is_canalyzer_mode:
            log_message("DM1 sender thread not applicable in Canalyzer mode")
            return
        
        # Flag per tracciare lo stato complessivo del test
        test_successful = True
        
        # Preparazione delle variabili di tracciamento
        total_dtcs = len(app.csv_data)
        
        # Log di inizio test
        #log_message(f"DM1 Sender Thread Started - Total DTCs: {total_dtcs}")
        
        # Aggiorna l'interfaccia all'inizio del test
        root.after(0, self.update_current_dtc_display, 
                   "Test Running", 0, None)

        try:
            # Ciclo principale di invio DTC
            while app.dm1_thread_running and app.current_dtc_index < total_dtcs:
                # Gestione pausa
                if app.dm1_paused:
                    time.sleep(0.5)
                    continue
                
                # Estrai il DTC corrente
                current_dtc = app.csv_data[app.current_dtc_index]
                
                # Memorizza l'indice corrente
                current_index = app.current_dtc_index
                
                # Aggiorna display in modo thread-safe
                root.after(0, self.update_current_dtc_display, 
                           "Sending DTC", 
                           app.current_dtc_index + 1, 
                           current_dtc)
                
                # Log dettagliato del DTC corrente
                log_message(
                    f"Sending DTC: Index={app.current_dtc_index + 1}/{total_dtcs}, "
                    f"SPN={current_dtc['SPN']}, FMI={current_dtc['FMI']}, "
                    f"Lamp={current_dtc.get('LAMP', 'NONE')}"
                )
                
                # Imposta ecff_received per avviare il processo di acquisizione
                app.ecff_received = True
                
                # Avvia il countdown di 35 secondi per il riconoscimento
                log_message(">>> Starting 35 second countdown for recognition")
                
                # Programmiamo l'acquisizione dopo 35 secondi
                root.after(35000, lambda: self.execute_dtc_acquisition(current_index))
                
                # Ciclo di invio del messaggio DM1 
                start_time = time.time()
                max_wait_time = 36  # Poco più di 35 secondi
                
                # Punti di countdown da visualizzare
                countdown_points = [35, 20, 10, 5, 4, 3, 2, 1]
                next_countdown_idx = 0
                
                while (app.dm1_thread_running and 
                       app.current_dtc_index == current_index and  # Controlliamo se l'indice è cambiato
                       time.time() - start_time < max_wait_time):
                    
                    # Calcola il tempo rimanente
                    elapsed_time = time.time() - start_time
                    remaining_time = max(0, max_wait_time - elapsed_time)
                    remaining_seconds = int(remaining_time)
                    
                    # Verifica se dobbiamo visualizzare un punto del countdown
                    if next_countdown_idx < len(countdown_points) and remaining_seconds <= countdown_points[next_countdown_idx]:
                        log_message(f"Recognition countdown: {remaining_seconds} seconds")
                        next_countdown_idx += 1
                    
                    try:
                        # Invia messaggio CAN solo in modalità DTC Test
                        send_can_message(current_dtc)
                        
                        # Breve attesa tra gli invii
                        time.sleep(1)
                    
                    except Exception as send_error:
                        log_message(f"Error sending DTC: {str(send_error)}")
                        break
                
                # Verifica se siamo ancora allo stesso indice dopo il timeout
                if app.current_dtc_index == current_index:
                    log_message(f"Timeout waiting for recognition for DTC {current_index + 1}")
                    current_dtc['error_found'] = True
                    test_successful = False
                    
                    # Avanza l'indice dato che l'acquisizione automatica non è avvenuta
                    app.current_dtc_index += 1
                    log_message(f"Manually advancing to next DTC index: {app.current_dtc_index}")
                
                # Breve pausa tra i DTC
                time.sleep(1)
                
                # Controllo interruzione thread 
                if not app.dm1_thread_running:
                    break
        
        except Exception as thread_error:
            log_message(f"Critical error in DM1 sender thread: {str(thread_error)}")
            import traceback
            log_message(traceback.format_exc())
            test_successful = False
        
        finally:
            # Fase di chiusura e reporting
            final_status = "Test Completed Successfully" if test_successful else "Test Completed with Errors"
            
            log_message(final_status)
            
            # Aggiorna display finale in modo thread-safe
            root.after(0, self.update_current_dtc_display, 
                       final_status, 
                       total_dtcs, 
                       None)
            
            # Ferma il riconoscimento (incluso lo stop del tasto)
            root.after(0, stop_recognition)
            
            # Chiama lo stop test nel thread principale 
            root.after(0, self.stop_dtc_test)

    def update_current_dtc_display(self, status_text, current_index, current_dtc):
        """Aggiorna l'interfaccia con i dettagli del DTC corrente"""
        self.test_status_label.config(text=status_text)
        
        if current_index:
            self.current_index_label.config(text=str(current_index))
        
        if current_dtc:
            self.current_spn_label.config(text=str(current_dtc.get('SPN', '-')))
            self.current_fmi_label.config(text=str(current_dtc.get('FMI', '-')))  
            self.current_lamp_label.config(text=str(current_dtc.get('LAMP', '-')))
            
            # Source Address in formato esadecimale
            source_address = current_dtc.get('SA', 0)
            self.current_sa_label.config(text=f"0x{source_address:02X}")
            
            # Description
            description = current_dtc.get('DESCRIPTION', '-')
            # Se la descrizione è troppo lunga, tronchiamola
            if len(description) > 40:
                description = description[:37] + "..."
            self.current_description_label.config(text=description)
            
            # Calcola il codice DTC nello stesso modo del codice di riferimento
            spn = current_dtc.get('SPN', 0)
            fmi = current_dtc.get('FMI', 0)
            
            # Utilizza lo stesso calcolo del codice di riferimento
            spn_low = spn & 0xFF          # Least significant byte of SPN
            spn_high = (spn >> 8) & 0xFF  # Most significant byte of SPN
            dtc_code = (spn_low << 16) | (spn_high << 8) | fmi
            
            # Formatta come stringa esadecimale di 6 cifre (3 byte)
            dtc_code_hex = f"{dtc_code:06X}"
            self.current_dtc_code_label.config(text=dtc_code_hex)
        else:
            # Resetta valori  
            self.current_index_label.config(text="-")
            self.current_spn_label.config(text="-") 
            self.current_fmi_label.config(text="-")
            self.current_lamp_label.config(text="-")
            self.current_dtc_code_label.config(text="-")
            self.current_sa_label.config(text="-")
            self.current_description_label.config(text="-")

    def show_test_results(self):
        """Show test results after test completes"""
        if not app.csv_data:
            return
            
        error_count = sum(1 for entry in app.csv_data if entry.get("error_found", False))
        
        log_message("----------------------------------------")
        log_message("DTC Test Results Summary")
        log_message(f"Tested {len(app.csv_data)} DTCs")
        
        if error_count > 0:
            log_message(f"Found {error_count} errors")
            # Report errors
            for i, entry in enumerate(app.csv_data):
                if entry.get("error_found", False):
                    error_msg = (
                        f"DTC {i+1}: SPN={entry['SPN']}, FMI={entry['FMI']}, "
                        f"Lamp={entry['LAMP']}, Description: {entry.get('DESCRIPTION', 'N/A')}"
                    )
                    log_message(error_msg)
        else:
            log_message("No errors found - all DTCs verified successfully")
            
        log_message("----------------------------------------")


    def process_ff99_message(self, msg):
        """
        Estrae i valori SPN, FMI e stato lampade da un messaggio 0xFF99
        
        Returns:
            dict: Valori estratti {'SPN': spn, 'FMI': fmi, 'LAMP': lamp}
        """
        try:
            data = msg.data
            
            # Estrai SPN (byte 0, 1, 2) - Formato big-endian
            spn_value = (data[0] << 16) | (data[1] << 8) | data[2]
            
            # Estrai FMI (byte 4, 5) - Formato big-endian
            fmi_value = (data[4] << 8) | data[5]
            
            # Estrai stato lampade (byte 6, 7)
            amber_lamp = bool(data[6] & 0x01)  # Bit 0 del byte 6
            red_lamp = bool(data[7] & 0x01)    # Bit 0 del byte 7
            
            # Debug estrazione dati
            hex_data = ' '.join(f'{b:02X}' for b in data)
            log_message(f"Raw FF99 data: [{hex_data}]")
            log_message(f"Extracted values: SPN={spn_value}, FMI={fmi_value}")
            log_message(f"Lamp states: Amber={amber_lamp}, Red={red_lamp}")
            
            # Determina stato lampada complessivo
            lamp_status = "NONE"
            if amber_lamp and not red_lamp:
                lamp_status = "AMBER"
            elif red_lamp and not amber_lamp:
                lamp_status = "RED"
            elif amber_lamp and red_lamp:
                # In caso entrambe siano accese, considera AMBER come prioritaria
                log_message("Warning: Both lamps are ON, defaulting to AMBER")
                lamp_status = "AMBER"
            
            log_message(f"Final FF99 values: SPN={spn_value}, FMI={fmi_value}, Lamp={lamp_status}")
            
            return {
                "SPN": spn_value,
                "FMI": fmi_value,
                "LAMP": lamp_status
            }
        except Exception as e:
            log_message(f"Error processing FF99 message: {str(e)}")
            import traceback
            log_message(traceback.format_exc())
            
            # Ritorna valori predefiniti in caso di errore
            return {
                "SPN": 0,
                "FMI": 0,
                "LAMP": "NONE"
            }

    def start_dtc_test(self):
        # Verifica caricamento CSV
        if not app.csv_data:
            log_message("Error: No CSV loaded or invalid data")
            return
        
        # Verifica che il riconoscimento sia già avviato
        if not app.running:
            log_message("Error: Start before the main application")
            return
        
        # Reset variabili
        app.current_dtc_index = 0
        app.dm1_counter = 1
        app.dm1_thread_running = True
        app.dm1_paused = False
        app.errors_found = 0
        
        # Resetta flag errori
        for entry in app.csv_data:
            entry["error_found"] = False
        
        # Aggiorna UI
        self.start_dtc_button.config(state=tk.DISABLED)
        self.stop_dtc_button.config(state=tk.NORMAL)
        
        app.dm1_thread = threading.Thread(target=self.dm1_sender_thread, daemon=True)
        app.dm1_thread.start()
        
        # Resetta visualizzazione iniziale
        root.after(0, self.update_current_dtc_display, "Test Started", 0, None)
        
        log_message(f"DTC test started with {len(app.csv_data)} elements")
        
    def stop_dtc_test(self):
        """Stop DTC test"""
        app.dm1_thread_running = False
        
        # Update UI
        if not self.canalyzer_var.get() and self.csv_file_path:
            self.start_dtc_button.config(state=tk.NORMAL)
        else:
            self.start_dtc_button.config(state=tk.DISABLED)
        self.stop_dtc_button.config(state=tk.DISABLED)
        
        log_message("DTC test stopped")
        
        # Wait for thread to terminate (with timeout)
        if app.dm1_thread and app.dm1_thread.is_alive():
            log_message("Waiting for DM1 thread to terminate...")
            app.dm1_thread.join(timeout=2.0)
        
        # Show summary of results
        self.show_test_results()
        root.after(0, self.update_current_dtc_display, "Test Stopped", 0, None)
        
        # Check if auto-save is enabled and we're in NON-CANALYZER mode
        if self.auto_save_log_var.get() and not self.canalyzer_var.get():
            log_message("Auto-save is enabled, saving log...")
            auto_save_log()

    def create_widgets(self):
        # Main frame containing controls with some padding to make it cleaner
        top_controls_frame = tk.Frame(self)
        top_controls_frame.pack(fill="x", expand=True, padx=5, pady=5)
        
        # Checkbox per modalità Canalyzer
        canalyzer_frame = tk.LabelFrame(top_controls_frame, text="Mode Selection", font=("Arial", 9, "bold"))
        canalyzer_frame.pack(fill="x", padx=5, pady=5)
        
        # Frame interno per contenere checkbox affiancati
        checkbox_container = tk.Frame(canalyzer_frame)
        checkbox_container.pack(fill="x", padx=5, pady=2)
        
        self.canalyzer_var = tk.BooleanVar(value=True)
        self.canalyzer_checkbox = tk.Checkbutton(
            checkbox_container, 
            text="Canalyzer Mode (listen for DM1)", 
            variable=self.canalyzer_var,
            command=self.toggle_canalyzer_mode,
            font=("Arial", 9)
        )
        self.canalyzer_checkbox.pack(side=tk.LEFT, padx=5, pady=2)
        
        # Nuovo checkbox per il salvataggio automatico del log
        self.auto_save_log_check = tk.Checkbutton(
            checkbox_container,
            text="Auto-save log at test end (DTC Mode only)",
            variable=self.auto_save_log_var,
            font=("Arial", 9)
        )
        self.auto_save_log_check.pack(side=tk.RIGHT, padx=5, pady=2)

        # Frame per il CSV DTC Test
        dtc_test_frame = tk.LabelFrame(top_controls_frame, text="DTC CSV Test", font=("Arial", 9, "bold"))
        dtc_test_frame.pack(fill="x", padx=5, pady=5)
        
        # Frame per il pulsante di selezione file CSV
        csv_file_frame = tk.Frame(dtc_test_frame)
        csv_file_frame.pack(fill="x", pady=2, padx=5)
        
        # Etichetta per il file CSV selezionato
        self.csv_file_label = tk.Label(csv_file_frame, text="No CSV file selected", 
                                     font=("Arial", 9), fg="gray", width=40, anchor="w")
        self.csv_file_label.pack(side=tk.LEFT, padx=5)
        
        # Pulsante per selezionare il file CSV
        self.select_csv_button = tk.Button(csv_file_frame, text="Select CSV", 
                                         command=self.select_csv_file, width=12,
                                         state=tk.DISABLED,
                                         font=("Arial", 9))
        self.select_csv_button.pack(side=tk.RIGHT, padx=5)
        
        # Frame per i controlli di invio DTC
        dtc_controls_frame = tk.Frame(dtc_test_frame)
        dtc_controls_frame.pack(fill="x", pady=2, padx=5)
        
        # Pulsante Start DTC Test - verde
        self.start_dtc_button = tk.Button(dtc_controls_frame, text="Start DTC Test", 
                                        command=self.start_dtc_test, width=15,
                                        state=tk.DISABLED, font=("Arial", 9),
                                        bg="#8cff8c")  # Verde chiaro
        self.start_dtc_button.pack(side=tk.LEFT, padx=5)
        
        # Pulsante Stop DTC Test - rosso
        self.stop_dtc_button = tk.Button(dtc_controls_frame, text="Stop DTC Test", 
                                       command=self.stop_dtc_test, width=15,
                                       state=tk.DISABLED, font=("Arial", 9),
                                       bg="#ff8c8c")  # Rosso chiaro
        self.stop_dtc_button.pack(side=tk.LEFT, padx=5)
        
        # Frame per il lettore ASC - più ampio e ben evidenziato
        asc_player_frame = tk.LabelFrame(top_controls_frame, text="ASC Trace Player", font=("Arial", 9, "bold"))
        asc_player_frame.pack(fill="x", padx=5, pady=5)
        
        # Frame per il pulsante di selezione file
        asc_file_frame = tk.Frame(asc_player_frame)
        asc_file_frame.pack(fill="x", pady=5, padx=5)
        
        # Etichetta per il file selezionato - più grande e meglio formattata
        self.asc_file_label = tk.Label(asc_file_frame, text="No ASC file selected", 
                                    font=("Arial", 9), fg="gray", width=40, anchor="w")
        self.asc_file_label.pack(side=tk.LEFT, padx=5)
        
        # Pulsante per selezionare il file ASC - più grande
        self.select_asc_button = tk.Button(asc_file_frame, text="Select ASC", 
                                        command=lambda: select_asc_file(self), width=12,
                                        font=("Arial", 9))
        self.select_asc_button.pack(side=tk.RIGHT, padx=5)
        
        # Frame per i controlli di riproduzione
        asc_controls_frame = tk.Frame(asc_player_frame)
        asc_controls_frame.pack(fill="x", pady=5, padx=5)
        
        # Pulsante Play - più grande e con colore verde
        self.play_asc_button = tk.Button(asc_controls_frame, text="▶ Play", 
                                       command=lambda: play_asc_file(self), width=12,
                                       state=tk.DISABLED, font=("Arial", 9),
                                       bg="#8cff8c")  # Verde chiaro
        self.play_asc_button.pack(side=tk.LEFT, padx=5)
        
        # Pulsante Stop - più grande e con colore rosso
        self.stop_asc_button = tk.Button(asc_controls_frame, text="■ Stop", 
                                       command=lambda: stop_asc_file_playback(self), width=12,
                                       state=tk.DISABLED, font=("Arial", 9),
                                       bg="#ff8c8c")  # Rosso chiaro
        self.stop_asc_button.pack(side=tk.LEFT, padx=5)
        
        # Checkbox per la riproduzione in loop - più grande
        self.asc_loop_var = tk.BooleanVar(value=False)
        self.loop_asc_check = tk.Checkbutton(asc_controls_frame, text="Loop Playback", 
                                           variable=self.asc_loop_var,
                                           font=("Arial", 9))
        self.loop_asc_check.pack(side=tk.RIGHT, padx=10)
        
        # Frame per visualizzare il DTC corrente
        current_dtc_frame = tk.LabelFrame(dtc_test_frame, text="Current DTC Details", font=("Arial", 9, "bold"))
        current_dtc_frame.pack(fill="x", padx=5, pady=5)

        # Frame interno per organizzare le etichette
        current_dtc_info = tk.Frame(current_dtc_frame)
        current_dtc_info.pack(fill="x", padx=5, pady=2)

        # Etichette per mostrare i dettagli - Organizziamo in 3 righe
        tk.Label(current_dtc_info, text="Index:", font=("Arial", 8)).grid(row=0, column=0, sticky='w')
        tk.Label(current_dtc_info, text="SPN:", font=("Arial", 8)).grid(row=0, column=2, sticky='w')
        tk.Label(current_dtc_info, text="FMI:", font=("Arial", 8)).grid(row=1, column=0, sticky='w')
        tk.Label(current_dtc_info, text="Lamp:", font=("Arial", 8)).grid(row=1, column=2, sticky='w')
        tk.Label(current_dtc_info, text="DTC Code:", font=("Arial", 8)).grid(row=2, column=0, sticky='w')
        # AGGIUNTA: Etichette per Source Address e Description
        tk.Label(current_dtc_info, text="Source Addr:", font=("Arial", 8)).grid(row=2, column=2, sticky='w')
        tk.Label(current_dtc_info, text="Description:", font=("Arial", 8)).grid(row=3, column=0, sticky='w')

        # Etichette per i valori (inizialmente vuote)
        self.current_index_label = tk.Label(current_dtc_info, text="-", font=("Arial", 8, "bold"), width=10)
        self.current_index_label.grid(row=0, column=1, sticky='w')

        self.current_spn_label = tk.Label(current_dtc_info, text="-", font=("Arial", 8, "bold"), width=10)
        self.current_spn_label.grid(row=0, column=3, sticky='w')

        self.current_fmi_label = tk.Label(current_dtc_info, text="-", font=("Arial", 8, "bold"), width=10)
        self.current_fmi_label.grid(row=1, column=1, sticky='w')

        self.current_lamp_label = tk.Label(current_dtc_info, text="-", font=("Arial", 8, "bold"), width=10)
        self.current_lamp_label.grid(row=1, column=3, sticky='w')

        self.current_dtc_code_label = tk.Label(current_dtc_info, text="-", font=("Arial", 8, "bold"), width=10)
        self.current_dtc_code_label.grid(row=2, column=1, sticky='w')

        # AGGIUNTA: Etichette per i valori di Source Address e Description
        self.current_sa_label = tk.Label(current_dtc_info, text="-", font=("Arial", 8, "bold"), width=10)
        self.current_sa_label.grid(row=2, column=3, sticky='w')
        
        # Per la description usiamo più spazio
        self.current_description_label = tk.Label(current_dtc_info, text="-", 
                                              font=("Arial", 8, "bold"), width=40, anchor='w')
        self.current_description_label.grid(row=3, column=1, columnspan=3, sticky='w')

        # Etichetta stato test
        self.test_status_label = tk.Label(current_dtc_frame, text="Test Not Started", 
                                          font=("Arial", 9), fg="blue")
        self.test_status_label.pack(fill="x", padx=5, pady=2)

        self.create_manual_dtc_widgets()

    def clear_errors(self):
        """Clear the log"""
        self.errors_text.delete(1.0, tk.END)
    
    def add_error(self, error_text):
        """Add a message to the log, keeping the history"""
        # Get current timestamp with date and time
        current_time = time.strftime("%H:%M:%S", time.localtime())
        
        # Format message with timestamp
        formatted_message = f"[{current_time}] {error_text}\n"
        
        # Insert at the end of the text
        self.errors_text.insert(tk.END, formatted_message)
        
        # Keep a maximum number of lines (e.g. 500)
        # to avoid excessive memory usage
        total_lines = int(self.errors_text.index('end-1c').split('.')[0])
        if total_lines > 500:
            # Remove first lines if limit is exceeded
            self.errors_text.delete('1.0', f'{total_lines - 500}.0')
        
        # Always scroll to last line
        self.errors_text.see(tk.END)

    def next_dtc(self):
        """Move to the next DTC in the list, called after recognition"""
        if app.csv_data and app.current_dtc_index < len(app.csv_data):
            app.current_dtc_index += 1
            return True
        return False

    def create_manual_dtc_widgets(self):
        """
        Aggiunge la sezione Manual DTC Sender all'interfaccia esistente
        """
        # Frame per Manual DTC Sender - Posizionato dopo ASC Player
        manual_dtc_frame = tk.LabelFrame(self, text="Manual DTC Sender", font=("Arial", 9, "bold"))
        manual_dtc_frame.pack(fill="x", padx=5, pady=5)
        
        # Frame per input parametri - Layout compatto
        params_frame = tk.Frame(manual_dtc_frame)
        params_frame.pack(fill="x", padx=5, pady=5)
        
        # Prima riga: SPN e FMI
        row1_frame = tk.Frame(params_frame)
        row1_frame.pack(fill="x", pady=2)
        
        # SPN Input
        tk.Label(row1_frame, text="SPN:", font=("Arial", 8)).pack(side="left")
        self.manual_spn_var = tk.StringVar(value="520313")
        spn_entry = tk.Entry(row1_frame, textvariable=self.manual_spn_var, width=8, font=("Arial", 8))
        spn_entry.pack(side="left", padx=2)
        
        # FMI Input
        tk.Label(row1_frame, text="FMI:", font=("Arial", 8)).pack(side="left", padx=(10, 0))
        self.manual_fmi_var = tk.StringVar(value="14")
        fmi_entry = tk.Entry(row1_frame, textvariable=self.manual_fmi_var, width=4, font=("Arial", 8))
        fmi_entry.pack(side="left", padx=2)
        
        # Lamp Selection
        tk.Label(row1_frame, text="Lamp:", font=("Arial", 8)).pack(side="left", padx=(10, 0))
        self.manual_lamp_var = tk.StringVar(value="NONE")
        lamp_combo = ttk.Combobox(row1_frame, textvariable=self.manual_lamp_var,
                                 values=["NONE", "AMBER", "RED"], 
                                 state="readonly", width=6, font=("Arial", 8))
        lamp_combo.pack(side="left", padx=2)
        
        # Source Address
        tk.Label(row1_frame, text="SA:", font=("Arial", 8)).pack(side="left", padx=(10, 0))
        self.manual_sa_var = tk.StringVar(value="0")
        sa_entry = tk.Entry(row1_frame, textvariable=self.manual_sa_var, width=4, font=("Arial", 8))
        sa_entry.pack(side="left", padx=2)
                
        # Terza riga: Controlli di invio
        row3_frame = tk.Frame(params_frame)
        row3_frame.pack(fill="x", pady=5)
        
        # Pulsante Send
        self.manual_send_btn = tk.Button(row3_frame, text="📤 Send DTC", 
                                        command=self.send_manual_dtc,
                                        font=("Arial", 8, "bold"),
                                        bg="#8cff8c", width=12, height=1)
        self.manual_send_btn.pack(side="left", padx=2)
        
        # Pulsante Send 3x
        self.manual_send_3x_btn = tk.Button(row3_frame, text="🔄 Send 3x", 
                                           command=self.send_manual_dtc_multiple,
                                           font=("Arial", 8),
                                           bg="#ffcc8c", width=10, height=1)
        self.manual_send_3x_btn.pack(side="left", padx=2)
        
        # Pulsante Validate
        validate_btn = tk.Button(row3_frame, text="✓ Check", 
                               command=self.validate_manual_dtc,
                               font=("Arial", 8),
                               bg="#8cccff", width=8, height=1)
        validate_btn.pack(side="left", padx=2)
        
        # Status label compatto
        self.manual_status_label = tk.Label(row3_frame, text="Ready", 
                                           fg="blue", font=("Arial", 7))
        self.manual_status_label.pack(side="right", padx=5)

    def load_manual_preset(self, spn, fmi, lamp, sa):
        """Carica un preset nei campi manuali"""
        self.manual_spn_var.set(str(spn))
        self.manual_fmi_var.set(str(fmi))
        self.manual_lamp_var.set(lamp)
        self.manual_sa_var.set(str(sa))
        self.manual_status_label.config(text=f"Loaded: SPN={spn}, FMI={fmi}", fg="blue")

    def validate_manual_dtc(self):
        """Valida i valori DTC manuali"""
        try:
            spn = int(self.manual_spn_var.get())
            fmi = int(self.manual_fmi_var.get())
            sa = int(self.manual_sa_var.get())
            lamp = self.manual_lamp_var.get()
            
            errors = []
            
            # Valida SPN
            if not (SPN_MIN <= spn <= SPN_MAX):
                errors.append(f"SPN {spn} out of range")
            
            # Valida FMI
            if not (FMI_MIN <= fmi <= FMI_MAX):
                errors.append(f"FMI {fmi} out of range")
            
            # Valida SA
            if not (0 <= sa <= 255):
                errors.append(f"SA {sa} out of range")
            
            if errors:
                self.manual_status_label.config(text="❌ " + "; ".join(errors), fg="red")
                return False
            else:
                self.manual_status_label.config(text="✅ Valid values", fg="green")
                return True
                
        except ValueError:
            self.manual_status_label.config(text="❌ Invalid number format", fg="red")
            return False

    def send_manual_dtc(self):
        """Invia un DTC manuale"""
        if not self.validate_manual_dtc():
            return
        
        try:
            # Prepara i parametri
            dtc_params = {
                "SPN": int(self.manual_spn_var.get()),
                "FMI": int(self.manual_fmi_var.get()),
                "LAMP": self.manual_lamp_var.get(),
                "SA": int(self.manual_sa_var.get())
            }
            
            # Disabilita il pulsante durante l'invio
            self.manual_send_btn.config(state="disabled")
            self.manual_status_label.config(text="📤 Sending...", fg="orange")
            
            # Invia in un thread separato
            def send_thread():
                try:
                    success = send_can_message(dtc_params)
                    
                    # Aggiorna UI nel thread principale
                    if success:
                        root.after(0, lambda: self.manual_status_label.config(
                            text=f"✅ Sent: SPN={dtc_params['SPN']}, FMI={dtc_params['FMI']}", fg="green"))
                        root.after(0, lambda: log_message(f"Manual DTC sent: {dtc_params}"))
                    else:
                        root.after(0, lambda: self.manual_status_label.config(
                            text="❌ Send failed", fg="red"))
                
                except Exception as e:
                    root.after(0, lambda: self.manual_status_label.config(
                        text=f"❌ Error: {str(e)[:20]}...", fg="red"))
                finally:
                    # Riabilita il pulsante
                    root.after(0, lambda: self.manual_send_btn.config(state="normal"))
            
            # Avvia il thread
            threading.Thread(target=send_thread, daemon=True).start()
            
        except Exception as e:
            self.manual_send_btn.config(state="normal")
            self.manual_status_label.config(text="❌ Send error", fg="red")

    def send_manual_dtc_multiple(self):
        """Invia lo stesso DTC 3 volte"""
        if not self.validate_manual_dtc():
            return
        
        try:
            # Prepara i parametri
            dtc_params = {
                "SPN": int(self.manual_spn_var.get()),
                "FMI": int(self.manual_fmi_var.get()),
                "LAMP": self.manual_lamp_var.get(),
                "SA": int(self.manual_sa_var.get())
            }
            
            # Disabilita i pulsanti
            self.manual_send_btn.config(state="disabled")
            self.manual_send_3x_btn.config(state="disabled")
            
            def send_multiple_thread():
                try:
                    for i in range(3):
                        # Aggiorna status
                        root.after(0, lambda i=i: self.manual_status_label.config(
                            text=f"📤 Sending {i+1}/3...", fg="orange"))
                        
                        # Invia messaggio
                        success = send_can_message(dtc_params)
                        
                        if not success:
                            root.after(0, lambda i=i: self.manual_status_label.config(
                                text=f"❌ Failed at {i+1}/3", fg="red"))
                            return
                        
                        # Pausa tra i messaggi
                        if i < 2:
                            time.sleep(1)
                    
                    # Successo
                    root.after(0, lambda: self.manual_status_label.config(
                        text=f"✅ 3x sent: SPN={dtc_params['SPN']}, FMI={dtc_params['FMI']}", fg="green"))
                    root.after(0, lambda: log_message(f"Manual DTC sent 3x: {dtc_params}"))
                
                except Exception as e:
                    root.after(0, lambda: self.manual_status_label.config(
                        text=f"❌ Error: {str(e)[:15]}...", fg="red"))
                finally:
                    # Riabilita i pulsanti
                    root.after(0, lambda: self.manual_send_btn.config(state="normal"))
                    root.after(0, lambda: self.manual_send_3x_btn.config(state="normal"))
            
            # Avvia il thread
            threading.Thread(target=send_multiple_thread, daemon=True).start()
            
        except Exception as e:
            self.manual_send_btn.config(state="normal")
            self.manual_send_3x_btn.config(state="normal")
            self.manual_status_label.config(text="❌ Multiple send error", fg="red")


# ====== Main Application UI Setup ======
if __name__ == "__main__":
    # --- Tkinter Interface ---
    root = tk.Tk()
    root.title("Cluster DTC Recognition")
    root.geometry("1700x850")  # Width increased to accommodate three columns

    # Carica l'icona
    try:
        icon_path = resource_path('can.ico')  # o can.ico
        icon = tk.PhotoImage(file=icon_path)
        root.iconphoto(True, icon)
    except Exception as e:
        print(f"Loading icon error: {e}")

    # Main frame to organize the three panels
    main_frame = tk.Frame(root)
    main_frame.pack(fill="both", expand=True, padx=5, pady=5)

    # Left frame for controls (400px)
    left_controls = tk.Frame(main_frame, width=400)
    left_controls.pack(side=tk.LEFT, fill="y", padx=5, pady=5)
    left_controls.pack_propagate(False)  # Maintains fixed width

    # Center frame for preview (600px)
    center_preview = tk.Frame(main_frame, width=600)
    center_preview.pack(side=tk.LEFT, fill="both", padx=5, pady=5)
    center_preview.pack_propagate(False)  # Maintains fixed width

    # Right frame for output
    right_output = tk.Frame(main_frame, width=650)
    right_output.pack(side=tk.LEFT, fill="both", expand=True, padx=5, pady=5)
    
    # Dividi il pannello destro in due parti: superiore per controlli e inferiore per log
    top_right_frame = tk.Frame(right_output)
    top_right_frame.pack(side=tk.TOP, fill="x", pady=5)
    
    bottom_right_frame = tk.Frame(right_output)
    bottom_right_frame.pack(side=tk.TOP, fill="both", expand=True, pady=5)

    # --- Left controls organization ---
    # Frame for webcam selection
    camera_frame = tk.LabelFrame(left_controls, text="Webcam", font=("Arial", 9, "bold"))
    camera_frame.pack(fill="x", pady=2)
    
    camera_listbox = ttk.Combobox(camera_frame, values=["Webcam 0", "Webcam 1"], state="readonly", width=15)
    if camera_listbox['values']:
        camera_listbox.current(0)
    camera_listbox.bind("<<ComboboxSelected>>", update_selected_camera)
    camera_listbox.pack(fill="x", padx=5, pady=2)

    resolution_frame = tk.Frame(camera_frame)
    resolution_frame.pack(fill="x", padx=5, pady=2)

    tk.Label(resolution_frame, text="Resolution:", font=('Arial', 8)).pack(side=tk.LEFT)

    resolution_combobox = ttk.Combobox(
        resolution_frame, 
        values=app.resolution_options, 
        state="readonly", 
        width=10
    )
    resolution_combobox.set(app.selected_resolution)  # Set default value
    resolution_combobox.bind("<<ComboboxSelected>>", update_selected_resolution)
    resolution_combobox.pack(side=tk.LEFT, padx=5)

    ttk.Separator(camera_frame, orient='horizontal').pack(fill='x', padx=5, pady=3)

    # Checkbox per il Live Preview durante il riconoscimento
    live_preview_during_rec_var = tk.BooleanVar(value=True)  # Cambio da False a True
    live_preview_during_rec_check = tk.Checkbutton(
        camera_frame, 
        text="Live Preview During Recognition", 
        variable=live_preview_during_rec_var,
        command=lambda: toggle_live_preview_during_recognition(live_preview_during_rec_var.get()),
        font=('Arial', 9)
    )
    live_preview_during_rec_check.pack(fill="x", padx=5, pady=3)

    # Aggiungiamo un altro separatore prima della prossima sezione
    ttk.Separator(camera_frame, orient='horizontal').pack(fill='x', padx=5, pady=3)
        
    # Frame for brightness threshold
    lamp_threshold_frame = tk.LabelFrame(left_controls, text="Lamp Threshold", font=("Arial", 9, "bold"))
    lamp_threshold_frame.pack(fill="x", pady=2)

    lamp_threshold_slider = tk.Scale(lamp_threshold_frame, from_=0, to=255, orient="horizontal", 
                                    command=update_lamp_threshold, label="ON/OFF", 
                                    length=150, font=('Arial', 8))
    lamp_threshold_slider.set(app.lamp_threshold)
    lamp_threshold_slider.pack(fill="x", padx=5)

    # Frame per i controlli diretti della webcam
    webcam_direct_frame = tk.LabelFrame(left_controls, text="Webcam Direct Controls", font=("Arial", 9, "bold"))
    webcam_direct_frame.pack(fill="x", pady=2)

    # Pulsante Live View all'inizio del frame
    live_view_btn = tk.Button(webcam_direct_frame, text="Start Live View", 
                            command=toggle_live_view, font=('Arial', 9, 'bold'),
                            bg="#8cff8c")  # Verde chiaro per evidenziare
    live_view_btn.pack(fill="x", padx=5, pady=5)

    # Slider contrasto webcam (tipicamente 0-10)
    webcam_contrast_slider = tk.Scale(webcam_direct_frame, from_=0, to=10, orient="horizontal", 
                                    command=update_webcam_contrast, label="Contrast", 
                                    length=150, font=('Arial', 8))
    webcam_contrast_slider.set(20)  # Valore predefinito
    webcam_contrast_slider.pack(fill="x", padx=5)

    # Slider saturazione webcam (tipicamente 0-200)
    webcam_saturation_slider = tk.Scale(webcam_direct_frame, from_=0, to=200, orient="horizontal", 
                                      command=update_webcam_saturation, label="Saturation", 
                                      length=150, font=('Arial', 8))
    webcam_saturation_slider.set(0)  # Valore predefinito
    webcam_saturation_slider.pack(fill="x", padx=5)

    # Slider esposizione webcam (tipicamente valori negativi)
    webcam_exposure_slider = tk.Scale(webcam_direct_frame, from_=-13, to=0, orient="horizontal", 
                                    command=update_webcam_exposure, label="Exposure", 
                                    length=150, font=('Arial', 8))
    webcam_exposure_slider.set(-8)  # Valore predefinito
    webcam_exposure_slider.pack(fill="x", padx=5)

    # Slider focus distance webcam (typically 0-255)
    webcam_focus_slider = tk.Scale(webcam_direct_frame, from_=0, to=255, orient="horizontal", 
                                 command=update_webcam_focus, label="Focus Distance", 
                                 length=150, font=('Arial', 8))
    webcam_focus_slider.set(73)  # Default to minimum focus distance
    webcam_focus_slider.pack(fill="x", padx=5)

    # Slider OCR threshold (valori tra 0-255)
    ocr_threshold_slider = tk.Scale(webcam_direct_frame, from_=0, to=255, orient="horizontal", 
                                   command=update_ocr_threshold, label="OCR Threshold (Start Live to see changes)", 
                                   length=150, font=('Arial', 8))
    ocr_threshold_slider.set(240)  # Valore predefinito medio
    ocr_threshold_slider.pack(fill="x", padx=5)

    # Frame for CAN parameters  
    can_frame = tk.LabelFrame(left_controls, text="CAN Parameters", font=("Arial", 9, "bold"))
    can_frame.pack(fill="x", pady=2)

    # Tipo di interfaccia CAN
    can_interface_frame = tk.Frame(can_frame)
    can_interface_frame.pack(fill="x", padx=5, pady=2)

    can_interface_var = tk.StringVar(value="vector")  # Change default to vector

    # Internal frame for Channel (dinamico)
    can_channel_frame = tk.Frame(can_frame)
    can_channel_frame.pack(fill="x", padx=5, pady=2)

    can_channel_label = tk.Label(can_channel_frame, text="Channel:", font=('Arial', 8))
    can_channel_label.pack(side=tk.LEFT)
    can_channel_var = tk.StringVar(value="0")  # Default
    can_channel_combo = ttk.Combobox(can_channel_frame, 
                                    values=["0", "1"], # Valori predefiniti, verranno aggiornati
                                    textvariable=can_channel_var, 
                                    state="readonly", 
                                    width=10)
    can_channel_combo.pack(side=tk.LEFT, padx=5)

    # Frame for Bitrate (invariato)
    can_bitrate_frame = tk.Frame(can_frame)
    can_bitrate_frame.pack(fill="x", padx=5, pady=2)

    tk.Label(can_bitrate_frame, text="Bitrate:", font=('Arial', 8)).pack(side=tk.LEFT)
    can_bitrate_var = tk.StringVar(value="250000")  # Default to 250k
    can_bitrate_combo = ttk.Combobox(can_bitrate_frame, values=["125000", "250000", "500000", "1000000"], 
                                    textvariable=can_bitrate_var, state="readonly", width=8)
    can_bitrate_combo.pack(side=tk.LEFT, padx=5)

    # Frame for buttons
    buttons_frame = tk.Frame(left_controls)
    buttons_frame.pack(fill="x", pady=2)

    btn_width = 12
    btn_pad = 2

    # Create buttons with global variable assignment
    app.preview_btn = tk.Button(buttons_frame, text="Select Areas", command=capture_preview, 
              width=btn_width, font=('Arial', 9),state=tk.DISABLED)
    app.preview_btn.pack(fill="x", padx=btn_pad, pady=1)

    app.start_btn = tk.Button(buttons_frame, text="Start", command=start_recognition, 
              width=btn_width, font=('Arial', 9), state=tk.DISABLED)
    app.start_btn.pack(fill="x", padx=btn_pad, pady=1)

    app.stop_btn = tk.Button(buttons_frame, text="Stop", command=stop_recognition, 
              width=btn_width, font=('Arial', 9), state=tk.DISABLED)
    app.stop_btn.pack(fill="x", padx=btn_pad, pady=1)

    # Frame for selected areas
    area_frame = tk.LabelFrame(left_controls, text="Selected Areas", font=("Arial", 9, "bold"))
    area_frame.pack(fill="x", pady=2)

    area_frame_container = tk.Frame(area_frame, bd=1, relief=tk.GROOVE)
    area_frame_container.pack(fill="x", padx=5, pady=2)

    # --- Center preview organization ---
    # Frame for recognized preview
    preview_paned = tk.PanedWindow(center_preview, orient=tk.VERTICAL, sashrelief=tk.RAISED, sashwidth=4)
    preview_paned.pack(fill="both", expand=True, padx=5, pady=5)

    
    # Frame for OCR threshold preview (pannello secondario)
    threshold_preview_frame = tk.LabelFrame(preview_paned, text="OCR Threshold Preview (Press Start Live View to see changes)", font=("Arial", 9, "bold"))

    # Pannello per OCR threshold
    app.threshold_preview_panel = tk.Label(threshold_preview_frame, bd=1, relief=tk.SUNKEN, bg="black")
    app.threshold_preview_panel.pack(fill="both", expand=True, padx=5, pady=5)

    # Frame for recognized preview (pannello principale)
    preview_frame = tk.LabelFrame(preview_paned, text="Recognition Preview", font=("Arial", 9, "bold"))

    # Pannello immagine principale
    recognized_frame_panel = tk.Label(preview_frame, bd=1, relief=tk.SUNKEN, bg="black")
    recognized_frame_panel.pack(fill="both", expand=True, padx=5, pady=5)

    # Add the resize event binding
    recognized_frame_panel.bind("<Configure>", on_preview_panel_resize)

    preview_paned.add(threshold_preview_frame, stretch="always", minsize=100)
    preview_paned.add(preview_frame, stretch="always", minsize=200)

    # Impostiamo la posizione iniziale del divisore
    def configure_paned_window(event):
        height = preview_paned.winfo_height()
        if height > 10:
            sash_pos = int(height * 0.33)
            try:
                preview_paned.sashpos(0, sash_pos)  # Prova con il metodo ttk
            except AttributeError:
                # Fallback per tk.PanedWindow
                preview_paned.paneconfigure(threshold_preview_frame, height=sash_pos)
                preview_paned.update()
            preview_paned.unbind('<Configure>')

    # Configura la posizione del separatore quando il pannello viene ridimensionato
    preview_paned.bind('<Configure>', configure_paned_window)

    # --- Right output organization ---
    # Frame for output - ora nella parte inferiore del pannello destro
    output_frame = tk.LabelFrame(bottom_right_frame, text="Application Log", font=('Arial', 9, "bold"))
    output_frame.pack(fill="both", expand=True, pady=2)

    # Container for text and button
    output_container = tk.Frame(output_frame)
    output_container.pack(fill="both", expand=True)

    output_text = tk.Text(output_container, font=('Arial', 9))
    output_text.pack(side=tk.TOP, fill="both", expand=True, padx=5, pady=2)

    # Scrollbar for output
    scrollbar = tk.Scrollbar(output_text)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    output_text.config(yscrollcommand=scrollbar.set)
    scrollbar.config(command=output_text.yview)

    # Frame for buttons
    log_buttons_frame = tk.Frame(output_container)
    log_buttons_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=2, padx=5)

    # Clear Log button
    app.clear_log_btn = tk.Button(log_buttons_frame, 
                               text="Clear Log", 
                               command=clear_log, 
                               width=12, 
                               font=('Arial', 9))
    app.clear_log_btn.pack(side=tk.LEFT, padx=5, pady=2)

    # Add Save Log button
    app.save_log_btn = tk.Button(log_buttons_frame, 
                              text="Save Log", 
                              command=save_log_to_file, 
                              width=12, 
                              font=('Arial', 9))
    app.save_log_btn.pack(side=tk.LEFT, padx=5, pady=2)

    # Initialize the application
    root.after(100, initialize_application)
    root.mainloop()