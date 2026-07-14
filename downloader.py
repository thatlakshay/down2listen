import os
import re
import json
import shutil
import tempfile
import requests
import yt_dlp
import subprocess
import static_ffmpeg
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, APIC
from mutagen.flac import FLAC, Picture

# Initialize static-ffmpeg to add FFmpeg binaries to system PATH dynamically
static_ffmpeg.add_paths()

def sanitize_filename(name):
    """Remove characters that are invalid in Windows/macOS/Linux filenames."""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()

def parse_url(url):
    """
    Parse the URL and return (source, item_type, item_id).
    source can be 'apple', 'spotify', 'youtube'.
    item_type can be 'song' or 'album'.
    """
    # 1. Spotify
    if "spotify.com" in url:
        match_track = re.search(r'/track/([a-zA-Z0-9]+)', url)
        if match_track:
            return 'spotify', 'song', match_track.group(1)
        match_album = re.search(r'/album/([a-zA-Z0-9]+)', url)
        if match_album:
            return 'spotify', 'album', match_album.group(1)
            
    # 2. YouTube
    if "youtube.com" in url or "youtu.be" in url or "youtube.be" in url:
        match_list = re.search(r'[?&]list=([a-zA-Z0-9_-]+)', url)
        if match_list:
            return 'youtube', 'album', match_list.group(1)
        match_video = re.search(r'(?:v=|/v/|embed/|youtu\.be/|/watch\?v=)([a-zA-Z0-9_-]{11})', url)
        if match_video:
            return 'youtube', 'song', match_video.group(1)

    # 3. Apple Music
    # Check for track parameter 'i' (e.g. ?i=1488408568)
    match_i = re.search(r'[?&]i=(\d+)', url)
    if match_i:
        return 'apple', 'song', match_i.group(1)
        
    # Check for song path (e.g. /song/song-name/1488408568)
    match_song = re.search(r'/song/[^/]+/(\d+)', url)
    if match_song:
        return 'apple', 'song', match_song.group(1)
        
    # Check for album path (e.g. /album/album-name/1488408555)
    match_album = re.search(r'/album/[^/]+/(\d+)', url)
    if match_album:
        return 'apple', 'album', match_album.group(1)
        
    # Check for standard id (e.g. /id1488408555)
    match_id = re.search(r'/id(\d+)', url)
    if match_id:
        return 'apple', 'album', match_id.group(1)
        
    # Check if the URL simply ends with a numeric ID
    match_digits = re.search(r'/(\d+)(?:\?|$)', url)
    if match_digits:
        return 'apple', 'album', match_digits.group(1)
        
    raise ValueError("Invalid URL. Could not extract song or album ID.")

def get_apple_page_metadata(url, track_id=None):
    """Scrape Apple Music webpage to extract album and track metadata."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }
    response = requests.get(url, headers=headers, timeout=15)
    response.raise_for_status()
    html = response.text
    
    script_match = re.search(r'<script[^>]*?id=["\']serialized-server-data["\'][^>]*?>(.*?)</script>', html, re.DOTALL | re.I)
    if not script_match:
        raise ValueError("Could not extract metadata from Apple Music page.")
        
    data = json.loads(script_match.group(1).strip())
    page_data = data[0] if isinstance(data, list) else data
    inner_data = page_data.get("data", [{}])[0].get("data", {}) if isinstance(page_data.get("data"), list) else page_data.get("data", {})
    sections = inner_data.get("sections", [])
    
    if not sections:
        raise ValueError("Could not find page sections in metadata.")
        
    header_item = sections[0].get("items", [{}])[0]
    album_name = header_item.get("title", "Unknown Album")
    subtitle_links = header_item.get("subtitleLinks", [])
    album_artist = subtitle_links[0].get("title", "Unknown Artist") if subtitle_links else "Unknown Artist"
    
    artwork_dict = header_item.get("artwork", {}).get("dictionary", {})
    artwork_url_template = artwork_dict.get("url", "")
    artwork_url = artwork_url_template.replace("{w}x{h}bb.{f}", "600x600bb.jpg") if artwork_url_template else ""
    
    quaternary_title = header_item.get("quaternaryTitle", "")
    year_match = re.search(r'(\d{4})', quaternary_title)
    release_date = year_match.group(1) if year_match else ""
    
    tracks_list = []
    for section in sections:
        items = section.get("items", [])
        if items and isinstance(items, list) and "trackNumber" in items[0]:
            tracks_list = items
            break
            
    if not tracks_list:
        raise ValueError("Could not find tracklist in Apple Music page metadata.")
        
    mapped_tracks = []
    for idx, item in enumerate(tracks_list):
        t_id = item.get("contentDescriptor", {}).get("identifiers", {}).get("storeAdamID") or str(item.get("trackNumber", idx+1))
        
        mapped_tracks.append({
            'trackName': item.get('title', 'Unknown Track'),
            'artistName': item.get('artistName', album_artist),
            'collectionName': album_name,
            'trackNumber': item.get('trackNumber', idx + 1),
            'trackCount': len(tracks_list),
            'discNumber': item.get('discNumber', 1),
            'discCount': 1,
            'releaseDate': release_date,
            'primaryGenreName': 'Pop',
            'artworkUrl100': artwork_url,
            'appleId': str(t_id)
        })
        
    if track_id:
        for track in mapped_tracks:
            if track['appleId'] == str(track_id):
                return track
        return mapped_tracks[0]
        
    album_info = {
        'collectionName': album_name,
        'artistName': album_artist,
        'artworkUrl100': artwork_url,
        'releaseDate': release_date,
        'primaryGenreName': 'Pop'
    }
    
    return {
        'album_info': album_info,
        'tracks': mapped_tracks
    }

def get_track_metadata(url_or_id, track_id=None):
    """Fetch track metadata either via Apple Music webpage scraping or iTunes Lookup API."""
    if isinstance(url_or_id, str) and url_or_id.startswith("http"):
        if not track_id:
            match_i = re.search(r'[?&]i=(\d+)', url_or_id)
            if match_i:
                track_id = match_i.group(1)
        return get_apple_page_metadata(url_or_id, track_id)
    else:
        url = f"https://itunes.apple.com/lookup?id={url_or_id}"
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
        if data.get("resultCount", 0) == 0:
            raise ValueError(f"Track with ID {url_or_id} not found in iTunes catalog.")
        result = data["results"][0]
        if result.get("wrapperType") != "track" and result.get("kind") != "song":
            raise ValueError(f"ID {url_or_id} does not represent a song.")
        return result

def get_album_metadata(url_or_id):
    """Fetch album metadata either via Apple Music webpage scraping or iTunes Lookup API."""
    if isinstance(url_or_id, str) and url_or_id.startswith("http"):
        return get_apple_page_metadata(url_or_id)
    else:
        url = f"https://itunes.apple.com/lookup?id={url_or_id}&entity=song"
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
        if data.get("resultCount", 0) == 0:
            raise ValueError(f"Album with ID {url_or_id} not found in iTunes catalog.")
        results = data["results"]
        album_info = results[0]
        if album_info.get("wrapperType") != "collection":
            raise ValueError(f"ID {url_or_id} does not represent an album/collection.")
        tracks = results[1:]
        tracks.sort(key=lambda t: (t.get("discNumber", 1), t.get("trackNumber", 1)))
        return {
            "album_info": album_info,
            "tracks": tracks
        }

def get_spotify_track_metadata(track_id):
    """Fetch Spotify track metadata anonymously via embed page."""
    url = f"https://open.spotify.com/embed/track/{track_id}"
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, headers=headers, timeout=15)
    response.raise_for_status()
    
    html = response.text
    next_data_match = re.search(r'<script\s+id=["\']__NEXT_DATA__["\']\s+type=["\']application/json["\']>(.*?)</script>', html, re.DOTALL | re.I)
    if not next_data_match:
        raise ValueError("Could not extract metadata from Spotify track page.")
        
    data = json.loads(next_data_match.group(1))
    entity = data.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})
    
    artists = entity.get("artists", [])
    artist_name = ", ".join([a.get("name") for a in artists]) if artists else "Unknown Artist"
    
    images = entity.get("visualIdentity", {}).get("image", [])
    artwork_url = images[0].get("url") if images else ""
    for img in images:
        if img.get("maxWidth") == 640:
            artwork_url = img.get("url")
            
    release_date_raw = entity.get("releaseDate", {})
    release_date = ""
    if isinstance(release_date_raw, dict):
        release_date = release_date_raw.get("isoString", "")[:10]
        
    # Get album name from description tag
    desc_match = re.search(r'<meta\s+property=["\']og:description["\']\s+content=["\'](.*?)["\']', html, re.I)
    desc = desc_match.group(1) if desc_match else ""
    parts = [p.strip() for p in re.split(r'·|•', desc)]
    album_name = "Single"
    if len(parts) >= 3:
        album_name = parts[1]
        
    return {
        'trackName': entity.get('name', 'Unknown Track'),
        'artistName': artist_name,
        'collectionName': album_name,
        'trackNumber': entity.get('trackNumber', 1),
        'trackCount': 1,
        'discNumber': 1,
        'discCount': 1,
        'releaseDate': release_date,
        'primaryGenreName': 'Pop',
        'artworkUrl100': artwork_url
    }

def get_spotify_album_metadata(album_id):
    """Fetch Spotify album metadata and tracks via embed page."""
    url = f"https://open.spotify.com/embed/album/{album_id}"
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, headers=headers, timeout=15)
    response.raise_for_status()
    
    html = response.text
    next_data_match = re.search(r'<script\s+id=["\']__NEXT_DATA__["\']\s+type=["\']application/json["\']>(.*?)</script>', html, re.DOTALL | re.I)
    if not next_data_match:
        raise ValueError("Could not extract metadata from Spotify album page.")
        
    data = json.loads(next_data_match.group(1))
    entity = data.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})
    
    album_name = entity.get("name", "Unknown Album")
    artist_name = entity.get("subtitle", "Unknown Artist")
    
    images = entity.get("visualIdentity", {}).get("image", [])
    artwork_url = images[0].get("url") if images else ""
    for img in images:
        if img.get("maxWidth") == 640:
            artwork_url = img.get("url")
            
    desc_match = re.search(r'<meta\s+property=["\']og:description["\']\s+content=["\'](.*?)["\']', html, re.I)
    desc = desc_match.group(1) if desc_match else ""
    year_match = re.search(r'·\s*(\d{4})\s*·', desc)
    release_date = year_match.group(1) if year_match else ""
    
    album_info = {
        'collectionName': album_name,
        'artistName': artist_name,
        'artworkUrl100': artwork_url,
        'releaseDate': release_date,
        'primaryGenreName': 'Pop'
    }
    
    tracks = []
    track_list_raw = entity.get("trackList", [])
    for idx, t in enumerate(track_list_raw):
        t_uri = t.get("uri", "")
        t_id = t_uri.split(":")[-1] if t_uri else f"track_{idx}"
        
        tracks.append({
            'trackName': t.get('title', 'Unknown Track'),
            'artistName': t.get('subtitle', artist_name),
            'collectionName': album_name,
            'trackNumber': idx + 1,
            'trackCount': len(track_list_raw),
            'discNumber': 1,
            'discCount': 1,
            'releaseDate': release_date,
            'primaryGenreName': 'Pop',
            'artworkUrl100': artwork_url,
            'spotifyId': t_id
        })
        
    return {
        'album_info': album_info,
        'tracks': tracks
    }

def get_youtube_track_metadata(video_id):
    """Fetch YouTube video metadata using yt-dlp."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        
    artist = info.get('uploader') or info.get('artist') or 'Unknown Artist'
    title = info.get('title') or 'Unknown Title'
    
    if " - " in title:
        parts = title.split(" - ", 1)
        artist = parts[0].strip()
        title = parts[1].strip()
        
    title = re.sub(r'\s*[\(\[][^\]\)]*(?:official|video|lyric|audio|clip)[^\]\)]*[\)\]]', '', title, flags=re.I).strip()
    
    return {
        'trackName': title,
        'artistName': artist,
        'collectionName': 'YouTube Download',
        'trackNumber': 1,
        'trackCount': 1,
        'discNumber': 1,
        'discCount': 1,
        'releaseDate': info.get('upload_date', '')[:4] if info.get('upload_date') else '',
        'primaryGenreName': 'Other',
        'artworkUrl100': info.get('thumbnail', ''),
        'youtubeId': video_id
    }

def get_youtube_playlist_metadata(playlist_id):
    """Fetch YouTube playlist metadata using yt-dlp."""
    url = f"https://www.youtube.com/playlist?list={playlist_id}"
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        
    playlist_title = info.get('title', 'Unknown Playlist')
    uploader = info.get('uploader', 'Unknown Creator')
    
    album_info = {
        'collectionName': playlist_title,
        'artistName': uploader,
        'artworkUrl100': info.get('thumbnails', [{}])[0].get('url', '') if info.get('thumbnails') else '',
        'releaseDate': '',
        'primaryGenreName': 'Other'
    }
    
    tracks = []
    entries = info.get('entries', [])
    for idx, entry in enumerate(entries):
        title = entry.get('title', 'Unknown Track')
        artist = entry.get('uploader') or uploader
        
        if " - " in title:
            parts = title.split(" - ", 1)
            artist = parts[0].strip()
            title = parts[1].strip()
            
        title = re.sub(r'\s*[\(\[][^\]\)]*(?:official|video|lyric|audio|clip)[^\]\)]*[\)\]]', '', title, flags=re.I).strip()
        
        tracks.append({
            'trackName': title,
            'artistName': artist,
            'collectionName': playlist_title,
            'trackNumber': idx + 1,
            'trackCount': len(entries),
            'discNumber': 1,
            'discCount': 1,
            'releaseDate': '',
            'primaryGenreName': 'Other',
            'artworkUrl100': entry.get('thumbnail', album_info['artworkUrl100']),
            'youtubeId': entry.get('id')
        })
        
    return {
        'album_info': album_info,
        'tracks': tracks
    }

def download_artwork(artwork_url, size=1000):
    """Download artwork image and return bytes."""
    # Scale up URL from 100x100 to target size
    high_res_url = re.sub(r'/\d+x\d+bb\.jpg$', f'/{size}x{size}bb.jpg', artwork_url)
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        r = requests.get(high_res_url, headers=headers, timeout=15)
        r.raise_for_status()
        return r.content
    except Exception as e:
        print(f"Error downloading high-res artwork ({high_res_url}): {e}. Falling back to standard size.")
        try:
            r = requests.get(artwork_url, headers=headers, timeout=15)
            r.raise_for_status()
            return r.content
        except Exception as e2:
            print(f"Failed to download fallback artwork: {e2}")
            return None

def convert_audio(input_path, output_path, target_format):
    """Convert audio file to target_format (mp3 or flac) using ffmpeg."""
    cmd = ['ffmpeg', '-y', '-i', input_path]
    
    if target_format == 'mp3':
        # 320kbps MP3 conversion, strip input metadata to write custom tags cleanly
        cmd.extend(['-ab', '320k', '-map_metadata', '-1', output_path])
    elif target_format == 'flac':
        # Highest standard FLAC compression, strip input metadata
        cmd.extend(['-compression_level', '8', '-map_metadata', '-1', output_path])
    else:
        raise ValueError(f"Unsupported conversion format: {target_format}")
        
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg conversion failed: {result.stderr}")

def tag_mp3(file_path, metadata, artwork_bytes):
    """Write ID3 tags and embed artwork in MP3 file."""
    try:
        audio = EasyID3(file_path)
    except Exception:
        audio = EasyID3()
        audio.save(file_path, v2_version=3)
        audio = EasyID3(file_path)
        
    audio['title'] = metadata.get('trackName', '')
    audio['artist'] = metadata.get('artistName', '')
    audio['album'] = metadata.get('collectionName', '')
    
    if 'trackNumber' in metadata:
        if 'trackCount' in metadata:
            audio['tracknumber'] = f"{metadata['trackNumber']}/{metadata['trackCount']}"
        else:
            audio['tracknumber'] = str(metadata['trackNumber'])
            
    if 'discNumber' in metadata:
        if 'discCount' in metadata:
            audio['discnumber'] = f"{metadata['discNumber']}/{metadata['discCount']}"
        else:
            audio['discnumber'] = str(metadata['discNumber'])
            
    if 'releaseDate' in metadata:
        # Extract year (YYYY)
        audio['date'] = metadata['releaseDate'][:4]
        
    if 'primaryGenreName' in metadata:
        audio['genre'] = metadata['primaryGenreName']
        
    audio.save(v2_version=3)
    
    # Write artwork (requires full ID3 APIC frame, which EasyID3 doesn't support)
    if artwork_bytes:
        audio_id3 = ID3(file_path)
        audio_id3.add(APIC(
            encoding=0,  # Latin-1 (highly compatible for ID3v2.3)
            mime='image/jpeg',
            type=3,  # Cover Front
            desc='Cover',
            data=artwork_bytes
        ))
        audio_id3.save(v2_version=3)

def tag_flac(file_path, metadata, artwork_bytes):
    """Write Vorbis Comments and embed artwork in FLAC file."""
    audio = FLAC(file_path)
    audio['title'] = metadata.get('trackName', '')
    audio['artist'] = metadata.get('artistName', '')
    audio['album'] = metadata.get('collectionName', '')
    
    if 'trackNumber' in metadata:
        audio['tracknumber'] = str(metadata['trackNumber'])
        audio['track'] = str(metadata['trackNumber'])
    if 'trackCount' in metadata:
        audio['totaltracks'] = str(metadata['trackCount'])
        
    if 'discNumber' in metadata:
        audio['discnumber'] = str(metadata['discNumber'])
        audio['disc'] = str(metadata['discNumber'])
    if 'discCount' in metadata:
        audio['totaldiscs'] = str(metadata['discCount'])
        
    if 'releaseDate' in metadata:
        audio['date'] = metadata['releaseDate'][:4]
        
    if 'primaryGenreName' in metadata:
        audio['genre'] = metadata['primaryGenreName']
        
    # Write artwork
    if artwork_bytes:
        pic = Picture()
        pic.type = 3  # Cover Front
        pic.mime = 'image/jpeg'
        pic.desc = 'Cover'
        pic.data = artwork_bytes
        audio.add_picture(pic)
        
    audio.save()

def download_and_process_track(track_metadata, download_dir, formats=['mp3', 'flac'], callback=None, cookies_from=None):
    """
    Search YouTube Music, download the track, convert it, and tag it.
    callback(status, message) can be passed to report real-time updates.
    """
    def log(status, message):
        if callback:
            callback(status, message)
        else:
            print(f"[{status.upper()}] {message}")

    artist = track_metadata.get('artistName', 'Unknown Artist')
    title = track_metadata.get('trackName', 'Unknown Track')
    album = track_metadata.get('collectionName', 'Unknown Album')
    track_num = track_metadata.get('trackNumber', 1)
    
    yt_id = track_metadata.get('youtubeId')
    if yt_id:
        log('searching', f"Resolving direct YouTube link (ID: {yt_id})")
        search_query = f"https://www.youtube.com/watch?v={yt_id}"
    else:
        log('searching', f"Searching YouTube Music for '{artist} - {title}'")
        search_query = f"ytsearch1:{artist} - {title} (Official Audio)"
    
    # Create temp directory for downloading the raw stream
    temp_dir = tempfile.mkdtemp()
    
    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(temp_dir, 'temp_audio_%(id)s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
        }
        
        def try_download(query, use_cookies=True):
            opts = ydl_opts.copy()
            if use_cookies and cookies_from and cookies_from != 'none':
                opts['cookiesfrombrowser'] = (cookies_from, None, None, None)
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(query, download=True)
                
        info = None
        try:
            info = try_download(search_query, use_cookies=True)
        except Exception as e:
            err_msg = str(e)
            cookie_error = cookies_from and cookies_from != 'none' and (
                "cookie" in err_msg.lower() or 
                "lock" in err_msg.lower() or 
                "permission" in err_msg.lower() or 
                "database" in err_msg.lower() or 
                "7271" in err_msg.lower()
            )
            if cookie_error:
                log('warning', f"Could not read {cookies_from} cookies (browser is likely running). Retrying search anonymously...")
                try:
                    info = try_download(search_query, use_cookies=False)
                except Exception as e_anon:
                    if yt_id:
                        raise e_anon
                    log('searching', "Primary search failed. Retrying fallback search anonymously...")
                    search_query_fallback = f"ytsearch1:{artist} - {title}"
                    info = try_download(search_query_fallback, use_cookies=False)
            else:
                if yt_id:
                    log('warning', "Direct video download failed. Retrying anonymously...")
                    info = try_download(search_query, use_cookies=False)
                else:
                    log('searching', f"Retrying search for '{artist} - {title}' with fallback query")
                    search_query_fallback = f"ytsearch1:{artist} - {title}"
                    try:
                        info = try_download(search_query_fallback, use_cookies=True)
                    except Exception as e_fallback:
                        log('warning', "Fallback query failed. Retrying fallback search anonymously...")
                        info = try_download(search_query_fallback, use_cookies=False)
                
        if not info:
            raise ValueError("No matching audio stream found on YouTube.")
            
        if 'entries' in info:
            if len(info['entries']) == 0:
                raise ValueError("No matching audio stream found on YouTube.")
            entry = info['entries'][0]
            video_id = entry['id']
        else:
            video_id = info['id']
            
        log('downloading', f"Downloading audio stream from YouTube (ID: {video_id})")
            
        # Find the actual downloaded file in the temp directory
        downloaded_file = None
        for f in os.listdir(temp_dir):
            if f.startswith(f"temp_audio_{video_id}"):
                downloaded_file = os.path.join(temp_dir, f)
                break
                
        if not downloaded_file or not os.path.exists(downloaded_file):
            raise FileNotFoundError("Downloaded audio stream could not be located.")
                
        # Download artwork bytes
        log('metadata', "Downloading album artwork")
        artwork_bytes = None
        if 'artworkUrl100' in track_metadata:
            artwork_bytes = download_artwork(track_metadata['artworkUrl100'])
            
        # Determine output filename prefix based on single vs album
        # If it's part of an album, use "TrackNum - Title"
        # Otherwise use "Title - Artist"
        # We will let the caller decide or auto-format.
        # Let's check if total tracks > 1 or album title matches track title (single)
        is_single = track_metadata.get('trackCount', 1) == 1
        
        if is_single:
            base_filename = sanitize_filename(f"{title} - {artist}")
        else:
            base_filename = sanitize_filename(f"{track_num:02d} - {title}")
            
        # Ensure download directory exists
        os.makedirs(download_dir, exist_ok=True)
        
        # Convert and tag
        for fmt in formats:
            fmt = fmt.lower().strip()
            if fmt not in ['mp3', 'flac']:
                continue
                
            out_filename = f"{base_filename}.{fmt}"
            out_path = os.path.join(download_dir, out_filename)
            
            log('converting', f"Converting to {fmt.upper()} (highest quality)")
            convert_audio(downloaded_file, out_path, fmt)
            
            log('tagging', f"Embedding tags and artwork in {out_filename}")
            if fmt == 'mp3':
                tag_mp3(out_path, track_metadata, artwork_bytes)
            elif fmt == 'flac':
                tag_flac(out_path, track_metadata, artwork_bytes)
                
        log('completed', f"Finished processing '{title}' successfully.")
        
    except Exception as e:
        log('failed', f"Error processing '{title}': {str(e)}")
        raise e
    finally:
        # Cleanup temporary files
        try:
            shutil.rmtree(temp_dir)
        except Exception:
            pass
