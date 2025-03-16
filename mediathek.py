import requests
from bs4 import BeautifulSoup

url = "https://www.mediathek.at/atom/01782930-3B8-006F8-00000BEC-01772EE2"
html = requests.get(url)
soup = BeautifulSoup(html.content, 'html.parser')
audio_tag = soup.find('audio')
data_src = audio_tag['data-src']
print(data_src)

if(".mp3" in data_src):
  filename = data_src.split("/")
  filename = filename[-1]
  print(filename)

  headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://www.mediathek.at/"
  }

  # Schritt 1: Dateigröße bestimmen
  response = requests.get(data_src, headers={**headers, "Range": "bytes=0-0"})
  if "Content-Range" in response.headers:
    total_size = int(response.headers["Content-Range"].split("/")[-1])
    print(f"Gesamtgröße: {total_size} Bytes")
  else:
    print("Server unterstützt keine Range-Anfragen")
    total_size = None

  # Schritt 2: Datei in Blöcken herunterladen
  chunk_size = 1024 * 1024  # 1 MB pro Anfrage
  downloaded_size = 0

  with open(filename, "wb") as file:
    while downloaded_size < total_size:
      end = min(downloaded_size + chunk_size - 1, total_size - 1)
      headers["Range"] = f"bytes={downloaded_size}-{end}"

      response = requests.get(data_src, headers=headers, stream=True)
      if response.status_code in [200, 206]:  # 206 = Partial Content
        file.write(response.content)
        downloaded_size += len(response.content)
        print(f"Heruntergeladen: {downloaded_size}/{total_size} Bytes")
      else:
        print(f"Fehler: {response.status_code}")
        break

  print("Download abgeschlossen.")
