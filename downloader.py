# -*- coding: utf-8 -*-
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

def normalize_smart_chars(text):
    """Normalize unicode smart punctuation (curly quotes, apostrophes, dashes, etc.) to standard ASCII equivalents."""
    if not isinstance(text, str):
        return text
    replacements = {
        '\u2019': "'",  # U+2019 Right single quotation mark (e.g. "It's", "I'd")
        '\u2018': "'",  # U+2018 Left single quotation mark
        '\u02bb': "'",  # U+02BB Modifier letter turned comma
        '\u02bc': "'",  # U+02BC Modifier letter apostrophe
        '\u201a': "'",  # U+201A Single low-9 quotation mark
        '\u201b': "'",  # U+201B Single high-reversed-9 quotation mark
        '`': "'",       # Grave accent
        '´': "'",       # Acute accent
        '\u201c': '"',  # U+201C Left double quotation mark
        '\u201d': '"',  # U+201D Right double quotation mark
        '\u209e': '"',  # U+209E Double low-9 quotation mark
        '\u2013': '-',  # U+2013 En dash
        '\u2014': '-',  # U+2014 Em dash
        '\u2010': '-',  # U+2010 Hyphen
        '\u2011': '-',  # U+2011 Non-breaking hyphen
        '\u2026': '...',# U+2026 Horizontal ellipsis
        '\xa0': ' ',   # Non-breaking space
        '\u200b': '',   # Zero-width space
        '\u200e': '',   # LTR mark
        '\u200f': '',   # RTL mark
    }
    for orig, repl in replacements.items():
        text = text.replace(orig, repl)
    return text

def sanitize_filename(name):
    """Remove characters that are invalid in Windows/macOS/Linux filenames and normalize unicode smart chars."""
    name = normalize_smart_chars(name)
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
    album_name = normalize_smart_chars(header_item.get("title", "Unknown Album"))
    subtitle_links = header_item.get("subtitleLinks", [])
    album_artist = normalize_smart_chars(subtitle_links[0].get("title", "Unknown Artist") if subtitle_links else "Unknown Artist")
    
    artwork_dict = header_item.get("artwork", {}).get("dictionary", {})
    artwork_url_template = artwork_dict.get("url", "")
    artwork_url = artwork_url_template.replace("{w}x{h}bb.{f}", "600x600bb.jpg") if artwork_url_template else ""
    
    quaternary_title = header_item.get("quaternaryTitle", "")
    year_match = re.search(r'(\d{4})', quaternary_title)
    release_date = year_match.group(1) if year_match else ""
    
    tracks_list = []
    for section in sections:
        items = section.get("items", [])
        if items and isinstance(items, list):
            if any("trackNumber" in item for item in items):
                for item in items:
                    if "trackNumber" in item:
                        tracks_list.append(item)
            
    if not tracks_list:
        raise ValueError("Could not find tracklist in Apple Music page metadata.")
        
    disc_count = 1
    for item in tracks_list:
        d_num = item.get("discNumber", 1)
        if isinstance(d_num, int) and d_num > disc_count:
            disc_count = d_num
        
    mapped_tracks = []
    for idx, item in enumerate(tracks_list):
        t_id = item.get("contentDescriptor", {}).get("identifiers", {}).get("storeAdamID") or str(item.get("trackNumber", idx+1))
        
        mapped_tracks.append({
            'trackName': normalize_smart_chars(item.get('title', 'Unknown Track')),
            'artistName': normalize_smart_chars(item.get('artistName', album_artist)),
            'albumArtist': album_artist,
            'collectionName': album_name,
            'trackNumber': item.get('trackNumber', idx + 1),
            'trackCount': len(tracks_list),
            'discNumber': item.get('discNumber', 1),
            'discCount': disc_count,
            'releaseDate': release_date,
            'primaryGenreName': 'Pop',
            'artworkUrl100': artwork_url,
            'appleId': str(t_id),
            'duration_ms': item.get('duration')
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

def normalize_metadata(data):
    """Recursively normalize string fields in metadata structures."""
    if isinstance(data, dict):
        new_data = {}
        for k, v in data.items():
            if isinstance(v, str) and k != 'artworkUrl100' and not v.startswith('http'):
                new_data[k] = normalize_smart_chars(v)
            elif isinstance(v, (dict, list)):
                new_data[k] = normalize_metadata(v)
            else:
                new_data[k] = v
        return new_data
    elif isinstance(data, list):
        return [normalize_metadata(item) for item in data]
    elif isinstance(data, str):
        return normalize_smart_chars(data)
    return data

def get_track_metadata(url_or_id, track_id=None):
    """Fetch track metadata either via Apple Music webpage scraping or iTunes Lookup API."""
    if isinstance(url_or_id, str) and url_or_id.startswith("http"):
        if not track_id:
            match_i = re.search(r'[?&]i=(\d+)', url_or_id)
            if match_i:
                track_id = match_i.group(1)
        res = get_apple_page_metadata(url_or_id, track_id)
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
        result["albumArtist"] = result.get("collectionArtistName") or result.get("artistName")
        res = result
    return normalize_metadata(res)

def get_album_metadata(url_or_id):
    """Fetch album metadata either via Apple Music webpage scraping or iTunes Lookup API."""
    if isinstance(url_or_id, str) and url_or_id.startswith("http"):
        res = get_apple_page_metadata(url_or_id)
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
        album_artist = album_info.get("artistName")
        for track in tracks:
            track["albumArtist"] = track.get("collectionArtistName") or album_artist
        tracks.sort(key=lambda t: (t.get("discNumber", 1), t.get("trackNumber", 1)))
        res = {
            "album_info": album_info,
            "tracks": tracks
        }
    return normalize_metadata(res)

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
        
    return normalize_metadata({
        'trackName': entity.get('name', 'Unknown Track'),
        'artistName': artist_name,
        'albumArtist': artist_name,
        'collectionName': album_name,
        'trackNumber': entity.get('trackNumber', 1),
        'trackCount': 1,
        'discNumber': 1,
        'discCount': 1,
        'releaseDate': release_date,
        'primaryGenreName': 'Pop',
        'artworkUrl100': artwork_url,
        'duration_ms': entity.get('duration')
    })

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
            'albumArtist': artist_name,
            'collectionName': album_name,
            'trackNumber': idx + 1,
            'trackCount': len(track_list_raw),
            'discNumber': 1,
            'discCount': 1,
            'releaseDate': release_date,
            'primaryGenreName': 'Pop',
            'artworkUrl100': artwork_url,
            'spotifyId': t_id,
            'duration_ms': t.get('duration')
        })
        
    return normalize_metadata({
        'album_info': album_info,
        'tracks': tracks
    })

def get_youtube_track_metadata(video_id):
    """Fetch YouTube video metadata using yt-dlp, and enrich it via iTunes Search API if possible."""
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
    
    # Strip "- Topic" from artist name if present
    if artist.lower().endswith(" - topic"):
        artist = artist[:-8].strip()
    elif artist.lower().endswith("-topic"):
        artist = artist[:-6].strip()
        
    if " - " in title:
        parts = title.split(" - ", 1)
        artist = parts[0].strip()
        title = parts[1].strip()
        
    title = re.sub(r'\s*[\(\[][^\]\)]*(?:official|video|lyric|audio|clip)[^\]\)]*[\)\]]', '', title, flags=re.I).strip()
    
    # Base metadata
    metadata = {
        'trackName': title,
        'artistName': artist,
        'albumArtist': artist,
        'collectionName': 'YouTube Download',
        'trackNumber': 1,
        'trackCount': 1,
        'discNumber': 1,
        'discCount': 1,
        'releaseDate': info.get('upload_date', '')[:4] if info.get('upload_date') else '',
        'primaryGenreName': 'Other',
        'artworkUrl100': info.get('thumbnail', ''),
        'youtubeId': video_id,
        'duration_ms': (info.get('duration') or 0) * 1000,
        'actual_duration_ms': (info.get('duration') or 0) * 1000
    }
    
    # Attempt to enrich via iTunes Search API
    try:
        search_url = "https://itunes.apple.com/search"
        search_term = f"{artist} {title}"
        params = {"term": search_term, "entity": "song", "limit": 1}
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(search_url, params=params, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data.get("resultCount", 0) > 0:
                result = data["results"][0]
                
                # Check for matching confidence
                def clean_str(s):
                    return re.sub(r'[^a-zA-Z0-9]', '', s).lower()
                
                itunes_t = clean_str(result.get('trackName', ''))
                itunes_a = clean_str(result.get('artistName', ''))
                parsed_t = clean_str(title)
                parsed_a = clean_str(artist)
                
                # If titles overlap, we consider it a confidence match
                if itunes_t in parsed_t or parsed_t in itunes_t:
                    metadata['trackName'] = result.get('trackName', title)
                    metadata['artistName'] = result.get('artistName', artist)
                    metadata['albumArtist'] = result.get('collectionArtistName') or result.get('artistName', artist)
                    metadata['collectionName'] = result.get('collectionName', 'YouTube Download')
                    metadata['releaseDate'] = result.get('releaseDate', metadata['releaseDate'])
                    metadata['primaryGenreName'] = result.get('primaryGenreName', 'Other')
                    if result.get('artworkUrl100'):
                        metadata['artworkUrl100'] = result['artworkUrl100']
                    metadata['duration_ms'] = result.get('trackTimeMillis', metadata['duration_ms'])
    except Exception:
        pass # Silently proceed with YouTube metadata if iTunes search fails
        
    return normalize_metadata(metadata)

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
            'albumArtist': uploader,
            'collectionName': playlist_title,
            'trackNumber': idx + 1,
            'trackCount': len(entries),
            'discNumber': 1,
            'discCount': 1,
            'releaseDate': '',
            'primaryGenreName': 'Other',
            'artworkUrl100': entry.get('thumbnail', album_info['artworkUrl100']),
            'youtubeId': entry.get('id'),
            'duration_ms': (entry.get('duration') or 0) * 1000
        })
        
    return normalize_metadata({
        'album_info': album_info,
        'tracks': tracks
    })

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
        
    audio['title'] = normalize_smart_chars(metadata.get('trackName', ''))
    audio['artist'] = normalize_smart_chars(metadata.get('artistName', ''))
    audio['album'] = normalize_smart_chars(metadata.get('collectionName', ''))
    audio['albumartist'] = normalize_smart_chars(metadata.get('albumArtist') or metadata.get('artistName', ''))
    
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
        audio['genre'] = normalize_smart_chars(metadata['primaryGenreName'])
        
    audio.save(v2_version=3)
    
    # Write artwork (requires full ID3 APIC frame, which EasyID3 doesn't support)
    if artwork_bytes:
        audio_id3 = ID3(file_path)
        audio_id3.add(APIC(
            encoding=3,  # UTF-8 encoding
            mime='image/jpeg',
            type=3,  # Cover Front
            desc='Cover',
            data=artwork_bytes
        ))
        audio_id3.save(v2_version=3)

def tag_flac(file_path, metadata, artwork_bytes):
    """Write Vorbis Comments and embed artwork in FLAC file."""
    audio = FLAC(file_path)
    audio['title'] = normalize_smart_chars(metadata.get('trackName', ''))
    audio['artist'] = normalize_smart_chars(metadata.get('artistName', ''))
    audio['album'] = normalize_smart_chars(metadata.get('collectionName', ''))
    album_artist = normalize_smart_chars(metadata.get('albumArtist') or metadata.get('artistName', ''))
    audio['albumartist'] = album_artist
    audio['album_artist'] = album_artist
    
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

def clean_name(name):
    """Clean name by removing featured artists, punctuation, and tokenizing."""
    name = re.sub(r'\(feat\..*?\)', '', name, flags=re.I)
    name = re.sub(r'feat\..*', '', name, flags=re.I)
    name = re.sub(r'[^\w\s]', '', name)
    return [w.lower() for w in name.split() if w.strip()]

def score_video_match(title, channel, duration, artist, track_name, target_duration=None):
    """
    Score a YouTube search result based on how likely it is to be the clean, official audio track.
    Higher score is better. Rejects mismatches or bad content types (covers, reactions, etc.) with -9999.
    """
    score = 0
    title_lower = title.lower()
    channel_lower = (channel or "").lower()
    
    # 1. STRICT REJECTION OF WRONG VIDEO TYPES (reaction, cover, live, remix, parody, etc.)
    bad_words = ['reaction', 'react', 'reacts', 'cover', 'remix', 'live', 'mashup', 'slowed', 'reverb', 'karaoke', 'instrumental', 'tutorial', 'acoustic', 'tribute', 'parody', 'chopped', 'screwed']
    for word in bad_words:
        if re.search(rf"\b{word}\b", title_lower):
            in_track = re.search(rf"\b{word}\b", track_name.lower()) is not None
            in_artist = re.search(rf"\b{word}\b", artist.lower()) is not None
            if not in_track and not in_artist:
                return -9999
            
    # Reject if channel name indicates reaction/cover/karaoke/instrumental
    bad_channel_words = ['reaction', 'reacts', 'cover', 'karaoke', 'instrumental', 'tutorial']
    for word in bad_channel_words:
        if re.search(rf"\b{word}\b", channel_lower):
            in_track = re.search(rf"\b{word}\b", track_name.lower()) is not None
            in_artist = re.search(rf"\b{word}\b", artist.lower()) is not None
            if not in_track and not in_artist:
                return -9999
            
    # Noise words to ignore when doing strict matching on titles
    noise_words = {'intro', 'outro', 'interlude', 'feat', 'ft', 'remix', 'prod', 'version', 'deluxe', 'pt', 'part', 'official', 'audio', 'video', 'lyric', 'lyrics', 'visualizer'}
    
    # 2. Title Match Check (CRITICAL)
    track_words = clean_name(track_name)
    meaningful_track_words = [w for w in track_words if w not in noise_words]
    if not meaningful_track_words:
        meaningful_track_words = track_words if track_words else [track_name.lower()]
        
    matched_words = sum(1 for w in meaningful_track_words if w in title_lower)
    match_ratio = matched_words / len(meaningful_track_words) if meaningful_track_words else 0
    
    if match_ratio == 0:
        # Reject completely if no core words match the title
        return -9999
        
    score += int(match_ratio * 150)
    
    # 3. Artist Match Check
    artist_words = clean_name(artist)
    meaningful_artist_words = [w for w in artist_words if w not in noise_words]
    if not meaningful_artist_words:
        meaningful_artist_words = artist_words if artist_words else [artist.lower()]
        
    artist_matched = any(w in channel_lower or w in title_lower for w in meaningful_artist_words)
    if artist_matched:
        score += 50
    else:
        score -= 50
        
    # 4. Channel / Uploader check
    is_topic = "topic" in channel_lower
    if is_topic:
        score += 100
        
    # 5. Title keywords
    if "official audio" in title_lower:
        score += 30
    elif "audio" in title_lower:
        score += 15
    if "lyrics" in title_lower or "lyric" in title_lower:
        score += 10
    if "visualizer" in title_lower:
        score += 10
        
    # Video indicators (penalize music videos with potential extra parts)
    if "music video" in title_lower or "official music video" in title_lower:
        score -= 50
    elif "official video" in title_lower or "official 4k video" in title_lower:
        score -= 40
    elif "video" in title_lower:
        if "lyric" not in title_lower:
            score -= 20
    if "short film" in title_lower or "cinematic" in title_lower:
        score -= 60
        
    # 5. Duration match (if target duration is available)
    if target_duration and duration:
        diff = abs(duration - target_duration)
        if diff <= 3:
            score += 150 # Perfect duration match
        elif diff <= 8:
            score += 80  # Close match
        elif diff <= 15:
            score += 40  # Tolerable match
        elif diff > 40:
            score -= 100 # Massive difference (likely music video with intro/outro)
        elif diff > 20:
            score -= 40
            
    return score

def download_and_process_track(track_metadata, download_dir, formats=['mp3', 'flac'], callback=None, cookies_from=None, clean_audio=True):
    """
    Search YouTube, download the track, convert it, and tag it.
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
    duration_ms = track_metadata.get('duration_ms') or track_metadata.get('trackTimeMillis')
    target_duration = float(duration_ms) / 1000.0 if duration_ms else None
    actual_duration = float(track_metadata.get('actual_duration_ms') or duration_ms) / 1000.0 if duration_ms else None
    
    video_id = None
    
    # 1. Resolve video_id
    if yt_id and not clean_audio:
        log('searching', f"Resolving direct YouTube link (ID: {yt_id})")
        video_id = yt_id
    else:
        # Evaluate direct video if it exists and clean_audio is True
        direct_clean = False
        direct_duration = None
        if yt_id:
            direct_title = track_metadata.get('trackName', '')
            direct_channel = track_metadata.get('artistName', '')
            direct_duration = actual_duration
            
            # Evaluate direct video score against target duration
            direct_score = score_video_match(direct_title, direct_channel, actual_duration, artist, title, target_duration)
            
            # If it's already clean, we can use it directly
            if "topic" in direct_channel.lower() or "official audio" in direct_title.lower() or direct_score >= 80:
                log('searching', f"Direct link (ID: {yt_id}) is already clean audio. Using it.")
                video_id = yt_id
                direct_clean = True
        
        if not video_id:
            # Run query search
            log('searching', f"Searching YouTube for cleanest audio of '{artist} - {title}'")
            search_query_term = f"{artist} - {title}"
            search_query = f"ytsearch5:{search_query_term}"
            
            def get_search_results(query, use_cookies=True):
                opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'extract_flat': 'in_playlist',
                    'nocheckcertificate': True,
                }
                if use_cookies and cookies_from and cookies_from != 'none':
                    opts['cookiesfrombrowser'] = (cookies_from, None, None, None)
                with yt_dlp.YoutubeDL(opts) as ydl:
                    return ydl.extract_info(query, download=False)
            
            info_search = None
            try:
                info_search = get_search_results(search_query, use_cookies=True)
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
                    log('warning', f"Could not read {cookies_from} cookies during search. Retrying search anonymously...")
                    try:
                        info_search = get_search_results(search_query, use_cookies=False)
                    except Exception as e_anon:
                        log('searching', "Primary search failed. Retrying fallback search anonymously...")
                        search_fallback = f"ytsearch5:{artist} - {title}"
                        info_search = get_search_results(search_fallback, use_cookies=False)
                else:
                    log('searching', "Primary search failed. Retrying fallback search...")
                    search_fallback = f"ytsearch5:{artist} - {title}"
                    try:
                        info_search = get_search_results(search_fallback, use_cookies=True)
                    except Exception:
                        info_search = get_search_results(search_fallback, use_cookies=False)
            
            entries = info_search.get('entries', []) if info_search else []
            if entries:
                scored_entries = []
                for entry in entries:
                    e_title = entry.get('title', 'Unknown')
                    e_channel = entry.get('channel') or entry.get('uploader') or 'Unknown'
                    e_duration = entry.get('duration')
                    e_id = entry.get('id')
                    
                    # For direct YouTube links, pass target_duration only if we successfully enriched it
                    # (meaning it is different from the actual direct video's duration by a significant margin).
                    has_enriched_duration = (yt_id and target_duration and actual_duration and abs(target_duration - actual_duration) > 5)
                    pass_target_duration = target_duration if (not yt_id or has_enriched_duration) else None
                    
                    e_score = score_video_match(e_title, e_channel, e_duration, artist, title, pass_target_duration)
                    scored_entries.append((e_score, e_duration, e_id, e_title))
                
                # Sort by score descending
                scored_entries.sort(key=lambda x: x[0], reverse=True)
                best_score, best_dur, best_id, best_title = scored_entries[0]
                
                if yt_id:
                    # If we had a direct link, only replace it if we found a strong topic/clean candidate
                    # and the best matched video is shorter (since music videos have extra non-music parts)
                    if best_score >= 80 and (direct_duration is None or best_dur < direct_duration - 15):
                        log('searching', f"Found cleaner audio version: '{best_title}' (ID: {best_id}). Replacing direct video link.")
                        video_id = best_id
                    else:
                        log('searching', f"Using user-provided direct YouTube link (ID: {yt_id})")
                        video_id = yt_id
                else:
                    log('searching', f"Selected cleanest audio track: '{best_title}' (ID: {best_id})")
                    video_id = best_id
            else:
                if yt_id:
                    log('searching', f"No search candidates found. Using direct YouTube link (ID: {yt_id})")
                    video_id = yt_id
                else:
                    raise ValueError("No matching audio stream found on YouTube.")
                    
    # Ultimate fallback just in case
    if not video_id:
        if yt_id:
            video_id = yt_id
        else:
            raise ValueError("Could not find any matching video on YouTube.")
            
    # Set final direct search query for downloading
    search_query = f"https://www.youtube.com/watch?v={video_id}"
    
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
                log('warning', f"Could not read {cookies_from} cookies (browser is likely running). Retrying download anonymously...")
                info = try_download(search_query, use_cookies=False)
            else:
                log('warning', "Direct video download failed. Retrying anonymously...")
                info = try_download(search_query, use_cookies=False)
                
        if not info:
            raise ValueError("No matching audio stream found on YouTube.")
            
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
