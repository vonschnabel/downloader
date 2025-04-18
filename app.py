import os
import requests
import time
from flask import Flask, render_template, request, jsonify
from concurrent.futures import ThreadPoolExecutor
import threading
from urllib.parse import urlparse

download_folder = "downloads"
os.makedirs(download_folder, exist_ok=True)

app = Flask(__name__)

number_of_max_workers = 2
executor = ThreadPoolExecutor(max_workers=number_of_max_workers)
download_queue = []  # Warteschlange als Liste mit (url, filename)
active_downloads = {}  # Aktive Downloads {filename: {"progress": int, "speed": float}}
cancel_flags = {}

allowed_files = {".mp4", ".mp3"}  # Erlaubte Dateiendungen

def get_unique_filename(filename):
  """Überprüft, ob die Datei bereits existiert, und fügt eine Nummer an, falls nötig."""
  base, ext = os.path.splitext(filename)
  counter = 1
  new_filename = filename

  while os.path.exists(os.path.join(download_folder, new_filename)):
    new_filename = f"{base}_{counter}{ext}"
    counter += 1

  return new_filename

def extract_filename(url, custom_title):
  """Ermittelt den Dateinamen und prüft, ob die Endung erlaubt ist."""
  parsed_url = urlparse(url)
  original_filename = os.path.basename(parsed_url.path)
  extension = "." + original_filename.split(".")[-1] if "." in original_filename else ""

  if extension not in allowed_files:
    return None  # Ungültiger Dateityp

  filename = f"{custom_title}{extension}" if custom_title else original_filename
  return get_unique_filename(filename)

def calculate_remaining_time(speed, speedunit, total_size, downloaded):
    speedunits = ["B/s", "KB/s", "MB/s", "GB/s"]

    # Falls speed 0 ist, um eine Division durch 0 zu vermeiden
    if speed <= 0 or speedunit == "Unbekannt":
        return "Unbekannt"
    # Speed in Bytes pro Sekunde umrechnen
    unit_factor = 1024 ** speedunits.index(speedunit)  # B/s = 1, KB/s = 1024, MB/s = 1024^2, ...
    speed_in_bytes = speed * unit_factor
    # Restliche Bytes berechnen
    remaining_bytes = total_size - downloaded
    # Restzeit in Sekunden berechnen
    remaining_time = remaining_bytes / speed_in_bytes
    # Umwandlung in Stunden, Minuten, Sekunden
    hours = int(remaining_time // 3600)
    minutes = int((remaining_time % 3600) // 60)
    seconds = int(remaining_time % 60)

    return f"{hours}h {minutes}m {seconds}s"

def download_file(url, filename):
  """Lädt eine Datei herunter und berechnet die Download-Geschwindigkeit."""
  global active_downloads
  file_path = os.path.join(download_folder, filename)

  response = requests.get(url, stream=True, timeout=10)
  total_size = int(response.headers.get("content-length", 0))
  speedunits = ["B/s","KB/s","MB/s","GB/s"]
  filesizeunits = ["B","KB","MB","GB"]
  filesizeunit = ""
  filesize = total_size
  var_counts = 0
  while((filesize > 1024) and var_counts < 4):
    filesize = filesize / 1024
    var_counts += 1
  if var_counts < 3:
    filesizeunit = filesizeunits[var_counts]
  else:
    filesizeunit = "Unbekannt"
  filesize = str(round(filesize,2)) +" " +filesizeunit  
  downloaded = 0
  downloaded_segment = 0
  cancel_flags[filename] = threading.Event()
  start_time = time.time()
  start_time_segment = start_time
  number_of_segments = 25000
  segment = 0

  with open(file_path, "wb") as file:
    for chunk in response.iter_content(chunk_size=1024):
      if cancel_flags[filename].is_set():
        os.remove(file_path)
        del active_downloads[filename]
        start_next_download()
        return

      if chunk:
        file.write(chunk)
        downloaded += len(chunk)
        downloaded_segment += len(chunk)

        elapsed_time = time.time() - start_time
        if segment >= number_of_segments:
          start_time_segment = time.time()
          downloaded_segment = len(chunk)
          segment = 0
          print("foo")
        elapsed_time_segment = time.time() - start_time_segment
#        speed = (downloaded / elapsed_time) / 1024 if elapsed_time > 0 else 0  # KB/s        
        speedunit = ""
        speedunit_segment = ""
        if elapsed_time > 0:
          var_counts = 0
          speed = (downloaded / elapsed_time)
          while((speed > 1024) and var_counts < 4):
            speed = speed / 1024
            var_counts += 1
          if var_counts < 3:
            speedunit = speedunits[var_counts]
          else:
            speedunit = "Unbekannt"
        else:
          speed = 0

        if elapsed_time_segment > 0:
          var_counts = 0
          speed_segment = (downloaded_segment / elapsed_time_segment)
          while((speed_segment > 1024) and var_counts < 4):
            speed_segment = speed_segment / 1024
            var_counts += 1
          if var_counts < 3:
            speedunit_segment = speedunits[var_counts]
          else:
            speedunit_segment = "Unbekannt"
        else:
          speed = 0

        remaining_time = calculate_remaining_time(speed, speedunit, total_size, downloaded)
        remaining_time_2 = calculate_remaining_time(speed_segment, speedunit_segment, total_size, downloaded_segment)
        active_downloads[filename] = {
#          "progress": int((downloaded / total_size) * 100) if total_size else 0,
          "progress": round((downloaded / total_size) * 100, 2) if total_size else 0,
          "downloaded": downloaded,
          "speed": round(speed, 2),
          "speed_segment": round(speed_segment, 2),
          "speedunit": speedunit,
          "speedunit_segment": speedunit_segment,
          "remaining_time": remaining_time,
          "remaining_time_2": remaining_time_2,
          "filesize": filesize
        }

        segment += 1

  del active_downloads[filename]
  del cancel_flags[filename]
  start_next_download()

def start_next_download():
  """Startet den nächsten Download aus der Warteschlange, falls Kapazität frei ist."""
  if len(active_downloads) < number_of_max_workers and download_queue:
    url, filename = download_queue.pop(0)
#    active_downloads[filename] = {"progress": 0, "speed": 0}
    active_downloads[filename] = {"progress": 0, "downloaded": 0, "speed": 0, "speed_segment": 0, "speedunit": "", "speedunit_segment": "", "remaining_time": "", "remaining_time_2": "", "filesize": ""}
    executor.submit(download_file, url, filename)

@app.route("/")
def index():
  return render_template("index.html")

@app.route("/download", methods=["POST"])
def start_download():
  """Fügt eine Datei zur Warteschlange hinzu, wenn sie erlaubt ist."""
  data = request.json
  url = data.get("url")
  custom_title = data.get("title")

  filename = extract_filename(url, custom_title)

  if filename and not any(entry[0] == url for entry in download_queue) and filename not in active_downloads:
    download_queue.append((url, filename))
    start_next_download()
    return jsonify({"status": "added to queue", "filename": filename})

  return jsonify({"status": "error", "message": "Ungültige Datei oder bereits in der Warteschlange."})

@app.route("/status")
def status():
  """Liefert den aktuellen Status der Warteschlange und der aktiven Downloads."""
  return jsonify({
    "queue": [{"filename": entry[1], "url": entry[0]} for entry in download_queue],
    "active": active_downloads
  })

@app.route("/remove", methods=["POST"])
def remove_from_queue():
  """Entfernt eine Datei aus der Warteschlange."""
  filename = request.json.get("filename")
  for i, (url, f) in enumerate(download_queue):
    if f == filename:
      del download_queue[i]
      return jsonify({"status": "removed", "filename": filename})

  return jsonify({"status": "error", "message": "File not found"})

@app.route("/cancel", methods=["POST"])
def cancel_download():
  """Bricht einen laufenden Download ab."""
  filename = request.json.get("filename")
  if filename in cancel_flags:
    cancel_flags[filename].set()
    return jsonify({"status": "cancelled", "filename": filename})

  return jsonify({"status": "error", "message": "Download not found"})

if __name__ == "__main__":
  app.run(host="0.0.0.0", port=5000, debug=True)
