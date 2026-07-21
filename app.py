import os
import queue
import threading
import json
import re
from flask import Flask, render_template, request, jsonify, Response
from downloader import (
    parse_url,
    get_track_metadata,
    get_album_metadata,
    get_spotify_track_metadata,
    get_spotify_album_metadata,
    get_youtube_track_metadata,
    get_youtube_playlist_metadata,
    download_and_process_track,
    sanitize_filename
)

app = Flask(__name__)

# Ensure the downloads directory exists
DOWNLOADS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), 'downloads'))
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/preview', methods=['POST'])
def preview():
    data = request.json or {}
    url = data.get('url')
    if not url:
        return jsonify({'error': 'URL is required'}), 400
        
    try:
        source, item_type, item_id = parse_url(url)
        if item_type == 'song':
            if source == 'apple':
                track_metadata = get_track_metadata(item_id)
            elif source == 'spotify':
                track_metadata = get_spotify_track_metadata(item_id)
            elif source == 'youtube':
                track_metadata = get_youtube_track_metadata(item_id)
            else:
                raise ValueError("Unsupported URL source.")
                
            preview_data = {
                'type': 'song',
                'title': track_metadata.get('trackName'),
                'artist': track_metadata.get('artistName'),
                'album': track_metadata.get('collectionName'),
                'artwork': re.sub(r'/\d+x\d+bb\.jpg$', '/600x600bb.jpg', track_metadata.get('artworkUrl100', '')),
                'trackCount': 1,
                'releaseDate': track_metadata.get('releaseDate', '')[:4] if track_metadata.get('releaseDate') else '',
                'genre': track_metadata.get('primaryGenreName'),
            }
            return jsonify(preview_data)
            
        elif item_type == 'album':
            if source == 'apple':
                album_data = get_album_metadata(item_id)
            elif source == 'spotify':
                album_data = get_spotify_album_metadata(item_id)
            elif source == 'youtube':
                album_data = get_youtube_playlist_metadata(item_id)
            else:
                raise ValueError("Unsupported URL source.")
                
            album_info = album_data['album_info']
            tracks = album_data['tracks']
            
            preview_data = {
                'type': 'album',
                'title': album_info.get('collectionName'),
                'artist': album_info.get('artistName'),
                'album': album_info.get('collectionName'),
                'artwork': re.sub(r'/\d+x\d+bb\.jpg$', '/600x600bb.jpg', album_info.get('artworkUrl100', '')),
                'trackCount': len(tracks),
                'releaseDate': album_info.get('releaseDate', '')[:4] if album_info.get('releaseDate') else '',
                'genre': album_info.get('primaryGenreName'),
                'tracks': [t.get('trackName') for t in tracks]
            }
            return jsonify(preview_data)
            
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/download')
def download():
    url = request.args.get('url')
    fmt = request.args.get('format', 'both')
    cookies_from = request.args.get('cookies_from', 'none')
    clean_audio = request.args.get('clean_audio', 'true').lower() == 'true'
    
    if not url:
        def err_gen():
            yield f"data: {json.dumps({'status': 'failed', 'message': 'URL is required'})}\n\n"
        return Response(err_gen(), mimetype='text/event-stream')
        
    formats = ["mp3", "flac"] if fmt == "both" else [fmt]
    q = queue.Queue()
    
    def run_download():
        try:
            source, item_type, item_id = parse_url(url)
            q.put({'status': 'info', 'message': f"Parsed URL. Source: {source.upper()}, Type: {item_type.upper()}"})
            
            if item_type == 'song':
                if source == 'apple':
                    track_metadata = get_track_metadata(url, item_id)
                elif source == 'spotify':
                    track_metadata = get_spotify_track_metadata(item_id)
                elif source == 'youtube':
                    track_metadata = get_youtube_track_metadata(item_id)
                    
                title = track_metadata.get('trackName', 'Unknown')
                artist = track_metadata.get('artistName', 'Unknown')
                q.put({'status': 'start', 'title': title, 'artist': artist, 'type': 'song'})
                
                def cb(status, msg):
                    q.put({'status': status, 'message': msg})
                    
                download_and_process_track(track_metadata, DOWNLOADS_DIR, formats=formats, callback=cb, cookies_from=cookies_from, clean_audio=clean_audio)
                q.put({'status': 'completed', 'message': 'Track downloaded and processed successfully!'})
                
            elif item_type == 'album':
                if source == 'apple':
                    album_data = get_album_metadata(url)
                elif source == 'spotify':
                    album_data = get_spotify_album_metadata(item_id)
                elif source == 'youtube':
                    album_data = get_youtube_playlist_metadata(item_id)
                    
                album_info = album_data['album_info']
                tracks = album_data['tracks']
                
                album_name = album_info.get("collectionName", "Unknown Album")
                artist_name = album_info.get("artistName", "Unknown Artist")
                
                q.put({
                    'status': 'start',
                    'title': album_name,
                    'artist': artist_name,
                    'type': 'album',
                    'total_tracks': len(tracks)
                })
                
                album_dir_name = sanitize_filename(f"{artist_name} - {album_name}")
                album_output_dir = os.path.join(DOWNLOADS_DIR, album_dir_name)
                
                for idx, track in enumerate(tracks):
                    track_title = track.get("trackName", "Unknown Track")
                    q.put({'status': 'track_start', 'index': idx + 1, 'title': track_title})
                    
                    def cb(status, msg):
                        q.put({'status': status, 'message': f"[Track {idx+1}/{len(tracks)}] {msg}"})
                        
                    try:
                        download_and_process_track(track, album_output_dir, formats=formats, callback=cb, cookies_from=cookies_from, clean_audio=clean_audio)
                        q.put({'status': 'track_completed', 'index': idx + 1, 'title': track_title})
                    except Exception as e:
                        q.put({
                            'status': 'track_failed',
                            'index': idx + 1,
                            'title': track_title,
                            'error': str(e)
                        })
                        
                q.put({'status': 'completed', 'message': 'Album downloaded and processed successfully!'})
                
        except Exception as e:
            q.put({'status': 'failed', 'message': str(e)})
        finally:
            q.put(None) # Sentinel to close stream
            
    # Start download in a daemon thread so it runs concurrently and survives request cycles
    threading.Thread(target=run_download, daemon=True).start()
    
    def generate():
        while True:
            item = q.get()
            if item is None:
                break
            yield f"data: {json.dumps(item)}\n\n"
            
    return Response(generate(), mimetype='text/event-stream')

if __name__ == '__main__':
    # Print status and run server locally
    print(f"Downloads folder: {DOWNLOADS_DIR}")
    app.run(host='127.0.0.1', port=5000, debug=True)
