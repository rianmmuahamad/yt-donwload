from flask import Flask, request, jsonify, send_from_directory
import yt_dlp
import os
from werkzeug.utils import secure_filename
import logging

app = Flask(__name__, static_folder='static')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
DOWNLOAD_FOLDER = 'downloads'
COOKIES_FILE = 'cookies.txt'

# Ensure necessary directories exist
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

def clean_filename(filename):
    """Clean filename from invalid characters"""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '')
    return secure_filename(filename)

def get_size_str(bytes):
    """Convert file size to readable format"""
    if bytes is None:
        return "Unknown size"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes < 1024:
            return f"{bytes:.2f} {unit}"
        bytes /= 1024
    return f"{bytes:.2f} GB"

def check_cookies_file():
    """Check if cookies file exists and is not empty"""
    return os.path.exists(COOKIES_FILE) and os.path.getsize(COOKIES_FILE) > 0

def get_video_info(url):
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': False,
            'cookiefile': COOKIES_FILE if check_cookies_file() else None
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = []
            resolutions_found = set()
            
            for f in info.get('formats', []):
                height = f.get('height', 0)
                if (f['ext'] == 'mp4' and 
                    f['vcodec'] != 'none' and 
                    height not in resolutions_found and 
                    height > 0):
                    formats.append({
                        'height': height,
                        'filesize': get_size_str(f.get('filesize', 0)),
                        'format_id': f['format_id']
                    })
                    resolutions_found.add(height)
            
            formats.sort(key=lambda x: x['height'], reverse=True)
            
            return {
                'title': info.get('title', ''),
                'duration': info.get('duration', 0),
                'formats': formats,
                'thumbnail': info.get('thumbnail', '')
            }
    except yt_dlp.utils.DownloadError as e:
        if "Sign in to confirm you're not a bot" in str(e):
            return {
                'error': 'Authentication required',
                'message': 'Please provide YouTube cookies in cookies.txt file'
            }
        return {'error': str(e)}
    except Exception as e:
        logger.error(f"Error extracting video info: {str(e)}")
        return {'error': 'An unexpected error occurred'}

@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/api/info', methods=['POST'])
def get_info():
    data = request.get_json()
    url = data.get('url')
    if not url:
        return jsonify({'error': 'URL is required'}), 400
    
    info = get_video_info(url)
    if 'error' in info:
        return jsonify(info), 400
    return jsonify(info)

@app.route('/api/download', methods=['POST'])
def download():
    try:
        data = request.get_json()
        url = data.get('url')
        format_type = data.get('type')
        resolution = data.get('resolution')
        
        if not url or not format_type:
            return jsonify({'error': 'Missing parameters'}), 400

        if not check_cookies_file():
            return jsonify({
                'error': 'Authentication required',
                'message': 'Please provide YouTube cookies in cookies.txt file'
            }), 401

        ydl_opts = {
            'cookiefile': COOKIES_FILE,
            'outtmpl': os.path.join(DOWNLOAD_FOLDER, '%(title)s.%(ext)s'),
            'quiet': False,
            'no_warnings': False,
            'progress_hooks': [lambda d: logger.info(f"Downloading: {d.get('filename', 'Unknown')} - {d.get('status', 'Unknown')}")],
        }

        if format_type == 'video':
            ydl_opts.update({
                'format': f'bestvideo[height<={resolution}]+bestaudio/best',
                'merge_output_format': 'mp4',
            })
        else:  # audio
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            })

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if format_type == 'audio':
                filename = os.path.splitext(filename)[0] + '.mp3'
            
            return jsonify({
                'success': True,
                'message': 'Download completed',
                'filename': os.path.basename(filename)
            })
            
    except yt_dlp.utils.DownloadError as e:
        logger.error(f"Download error: {str(e)}")
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Unexpected error during download: {str(e)}")
        return jsonify({'error': 'An unexpected error occurred'}), 500

@app.route('/downloads/<filename>')
def download_file(filename):
    return send_from_directory(DOWNLOAD_FOLDER, filename, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)