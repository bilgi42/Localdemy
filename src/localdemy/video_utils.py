"""
Video utility functions for metadata extraction and thumbnail generation.
"""

import os
import json
import tempfile
from pathlib import Path
import gi
import subprocess
import signal
gi.require_version('Gst', '1.0')
gi.require_version('GdkPixbuf', '2.0')
gi.require_version('GstPbutils', '1.0')
from gi.repository import Gst, GdkPixbuf, GLib, GstPbutils

# Ensure GStreamer is initialized
Gst.init(None)


class VideoMetadata:
    """Class for extracting metadata from video files."""
    
    def __init__(self, video_path):
        self.video_path = video_path
        self.duration = 0
        self.width = 0
        self.height = 0
        self.title = ""
        self.artist = ""
        self.mime_type = ""
        self.video_codec = ""
        self.audio_codec = ""
        self.container_format = ""
        
    def extract_metadata(self):
        """Extract metadata from video file using GStreamer."""
        discoverer = GstPbutils.Discoverer.new(5 * Gst.SECOND)
        
        try:
            info = discoverer.discover_uri(Gst.filename_to_uri(self.video_path))
            
            # Get basic information
            self.duration = info.get_duration() / Gst.SECOND
            
            # In newer GStreamer, use a different approach for MIME type
            stream_info = info.get_stream_info()
            if stream_info:
                caps = stream_info.get_caps()
                if caps and caps.get_size() > 0:
                    structure = caps.get_structure(0)
                    self.mime_type = structure.get_name()
                    
            # Get video information if available
            video_streams = info.get_video_streams()
            if video_streams:
                video_info = video_streams[0]
                self.width = video_info.get_width()
                self.height = video_info.get_height()
                # For codec, use the caps representation
                caps = video_info.get_caps()
                if caps and caps.get_size() > 0:
                    self.video_codec = caps.to_string()
            
            # Get audio information if available
            audio_streams = info.get_audio_streams()
            if audio_streams:
                audio_info = audio_streams[0]
                # For codec, use the caps representation
                caps = audio_info.get_caps()
                if caps and caps.get_size() > 0:
                    self.audio_codec = caps.to_string()
            
            # Get tags
            tags = info.get_tags()
            if tags:
                # Try to get title
                success, title = tags.get_string(Gst.TAG_TITLE)
                if success:
                    self.title = title
                
                # Try to get artist
                success, artist = tags.get_string(Gst.TAG_ARTIST)
                if success:
                    self.artist = artist
            
            # Use filename as title if no title was found
            if not self.title:
                self.title = Path(self.video_path).stem
            
            return True
            
        except GLib.Error as error:
            print(f"Error extracting metadata: {error.message}")
            # Use filename as fallback title
            self.title = Path(self.video_path).stem
            return False
    
    def to_dict(self):
        """Convert metadata to dictionary."""
        return {
            'duration': self.duration,
            'width': self.width,
            'height': self.height,
            'title': self.title,
            'artist': self.artist,
            'mime_type': self.mime_type,
            'video_codec': self.video_codec,
            'audio_codec': self.audio_codec,
            'container_format': self.container_format
        }
    
    def to_json(self):
        """Convert metadata to JSON string."""
        return json.dumps(self.to_dict())


def get_video_duration(file_path, timeout=None):
    """
    Get the duration of a video file in seconds.
    
    Args:
        file_path: Path to the video file
        timeout: Optional timeout in seconds to limit processing time
        
    Returns:
        Duration in seconds (float)
    """
    # Skip non-existent files
    if not os.path.exists(file_path):
        return 0
        
    # First try using GStreamer (fast and reliable on supported formats)
    try:
        # Create a playbin element
        playbin = Gst.ElementFactory.make("playbin", "durationquery")
        if not playbin:
            raise Exception("Could not create playbin")
            
        # Set the input file
        file_uri = GLib.filename_to_uri(file_path, None)
        playbin.set_property("uri", file_uri)
        
        # Set state to PAUSED to read information
        playbin.set_state(Gst.State.PAUSED)
        
        # Wait for state change or timeout
        if timeout:
            # Custom timeout for faster performance
            state_change = playbin.get_state(int(timeout * Gst.SECOND))
        else:
            # Default timeout (potentially slow for network files)
            state_change = playbin.get_state(Gst.CLOCK_TIME_NONE)
        
        # Query duration
        success, duration = playbin.query_duration(Gst.Format.TIME)
        
        # Clean up
        playbin.set_state(Gst.State.NULL)
        
        if success:
            # Convert to seconds
            return duration / Gst.SECOND
            
    except Exception as e:
        print(f"GStreamer duration query failed: {str(e)}")
    
    # Fall back to ffprobe if available (more formats supported)
    try:
        # Set up the ffprobe command with timeout
        cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", 
               "-of", "json", file_path]
               
        # Run with timeout
        if timeout:
            # This is Unix-specific, but we can handle the exception on Windows
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    stdout, stderr = proc.communicate(timeout=timeout)
                    output = json.loads(stdout)
                    if "format" in output and "duration" in output["format"]:
                        return float(output["format"]["duration"])
                except subprocess.TimeoutExpired:
                    # Kill the process if it times out
                    proc.kill()
                    proc.communicate()
                    print(f"ffprobe timed out for {file_path}")
            except (AttributeError, ValueError):
                # Fallback for platforms without timeout support
                output = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                data = json.loads(output)
                if "format" in data and "duration" in data["format"]:
                    return float(data["format"]["duration"])
        else:
            # Run without timeout
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            data = json.loads(output)
            if "format" in data and "duration" in data["format"]:
                return float(data["format"]["duration"])
                
    except Exception as e:
        print(f"ffprobe duration query failed: {str(e)}")
    
    # Return a default value if all methods fail
    return 0


def get_video_title(video_path):
    """
    Extract title from video metadata or use filename.
    
    Args:
        video_path: Path to the video file
        
    Returns:
        str: Title of the video
    """
    metadata = VideoMetadata(video_path)
    metadata.extract_metadata()
    return metadata.title 