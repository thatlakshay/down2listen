import os
import argparse
import sys
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

def main():
    parser = argparse.ArgumentParser(description="down2listen CLI")
    parser.add_argument("--url", required=True, help="Apple Music, Spotify, or YouTube URL")
    parser.add_argument("--format", choices=["mp3", "flac", "both"], default="both", help="Format to download (default: both)")
    parser.add_argument("--output-dir", default="downloads", help="Base download directory (default: downloads)")
    parser.add_argument("--cookies-from", help="Browser to extract cookies from (e.g. chrome, edge, firefox, brave, safari) to bypass bot block")
    
    args = parser.parse_args()
    
    # Resolve formats
    formats = ["mp3", "flac"] if args.format == "both" else [args.format]
    
    try:
        source, item_type, item_id = parse_url(args.url)
        print(f"Parsed URL. Source: {source.upper()}, Type: {item_type.upper()}, ID: {item_id}")
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
        
    try:
        if item_type == "song":
            print("Fetching song metadata...")
            if source == 'apple':
                track_metadata = get_track_metadata(item_id)
            elif source == 'spotify':
                track_metadata = get_spotify_track_metadata(item_id)
            elif source == 'youtube':
                track_metadata = get_youtube_track_metadata(item_id)
            else:
                raise ValueError("Unsupported URL source.")
                
            title = track_metadata.get("trackName", "Unknown Track")
            artist = track_metadata.get("artistName", "Unknown Artist")
            print(f"Song found: '{title}' by '{artist}'")
            
            # Download directly to output directory
            download_and_process_track(track_metadata, args.output_dir, formats=formats, cookies_from=args.cookies_from)
            print("\nDownload complete!")
            
        elif item_type == "album":
            print("Fetching album metadata...")
            if source == 'apple':
                album_data = get_album_metadata(item_id)
            elif source == 'spotify':
                album_data = get_spotify_album_metadata(item_id)
            elif source == 'youtube':
                album_data = get_youtube_playlist_metadata(item_id)
            else:
                raise ValueError("Unsupported URL source.")
                
            album_info = album_data["album_info"]
            tracks = album_data["tracks"]
            
            album_name = album_info.get("collectionName", "Unknown Album")
            artist_name = album_info.get("artistName", "Unknown Artist")
            print(f"Album found: '{album_name}' by '{artist_name}' with {len(tracks)} track(s)")
            
            # Save tracks inside a subdirectory for the album
            album_dir_name = sanitize_filename(f"{artist_name} - {album_name}")
            album_output_dir = os.path.join(args.output_dir, album_dir_name)
            
            print(f"Downloading album tracks to '{album_output_dir}'...\n")
            for idx, track in enumerate(tracks):
                track_title = track.get("trackName", "Unknown Track")
                print(f"[{idx+1}/{len(tracks)}] Processing: {track_title}")
                try:
                    download_and_process_track(track, album_output_dir, formats=formats, cookies_from=args.cookies_from)
                except Exception as e:
                    print(f"Failed to download '{track_title}': {e}")
                    
            print("\nAlbum download complete!")
            
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
