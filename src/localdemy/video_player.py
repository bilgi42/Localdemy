"""
Video player component for Localdemy.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gst', '1.0')
gi.require_version('GstVideo', '1.0')
gi.require_version('GstGL', '1.0')
gi.require_version('Pango', '1.0')
from gi.repository import Gtk, Gst, GLib, GstVideo, GstGL, Gdk, GObject, Pango, Gio, Adw
import os
import sys
from pathlib import Path
import subprocess

# Initialize GStreamer
Gst.init(None)


class VideoPlayer(Gtk.Box):
    """Video player component using GStreamer."""

    __gsignals__ = {
        'progress-updated': (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_FLOAT,)),
    }

    def __init__(self):
        try:
            super().__init__(orientation=Gtk.Orientation.VERTICAL)
            
            self.set_hexpand(True)
            self.set_vexpand(True)
            
            # Create main video container - this will hold our video display widget
            self.video_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            self.video_container.set_hexpand(True)
            self.video_container.set_vexpand(True)
            self.video_container.set_halign(Gtk.Align.FILL)
            self.video_container.set_valign(Gtk.Align.FILL)
            self.append(self.video_container)
            
            # Create an overlay to display subtitles on top of video
            self.video_overlay = Gtk.Overlay()
            self.video_overlay.set_hexpand(True)
            self.video_overlay.set_vexpand(True)
            self.video_container.append(self.video_overlay)
            
            # We'll start with a standard Picture widget that works reliably
            self.video_area = Gtk.Picture()
            self.video_area.set_hexpand(True)
            self.video_area.set_vexpand(True)
            self.video_area.set_size_request(640, 360)
            self.video_area.set_content_fit(Gtk.ContentFit.FILL)
            self.video_area.set_halign(Gtk.Align.FILL)
            self.video_area.set_valign(Gtk.Align.FILL)
            self.video_overlay.set_child(self.video_area)
            
            # Create a subtitle display widget
            self.subtitle_label = Gtk.Label()
            self.subtitle_label.set_margin_bottom(36)
            self.subtitle_label.set_margin_start(24)
            self.subtitle_label.set_margin_end(24)
            self.subtitle_label.set_halign(Gtk.Align.CENTER)
            self.subtitle_label.set_valign(Gtk.Align.END)
            self.subtitle_label.get_style_context().add_class("subtitle-text")
            self.subtitle_label.set_use_markup(True)
            self.subtitle_label.set_wrap(True)
            self.subtitle_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            self.video_overlay.add_overlay(self.subtitle_label)
            
            # We're not using GL by default - more reliable
            self.using_gl = False
            print("Using standard video rendering (more reliable)")
            
            # Initialize GStreamer components
            self.playbin = None  # Will be created in setup_gstreamer
            self.gl_context = None
            self.pipeline_initialized = False
            
            # Current video information
            self.current_video = None
            self.duration = 0
            self.position = 0
            
            # Subtitle track information
            self.subtitle_file = None
            self.subtitles_enabled = True
            self.current_subtitle_text = None
            self.subtitle_parser = None
            
            # Setup position update timer
            self.update_id = 0
            
            # Save progress timer
            self.save_progress_id = 0
            # Whether the progress should be saved
            self.save_progress = True
            
            # Create controls
            self.create_controls()
            
            # Initialize GStreamer right away with standard sink
            self.setup_gstreamer()
            
            # Flag to track loading state
            self._is_loading = False
        except Exception as e:
            print(f"ERROR initializing VideoPlayer: {e}")
            import traceback
            traceback.print_exc()
        
    def setup_gstreamer(self):
        """Set up GStreamer pipeline for video playback."""
        try:
            # First check if we have the necessary plugins
            has_all_plugins = self.check_gstreamer_plugins()
            
            # Create a playbin element which handles everything automatically
            self.playbin = Gst.ElementFactory.make("playbin", "player")
            if not self.playbin:
                print("ERROR: Could not create playbin element")
                return
                
            # Enable video rendering and subtitles
            flags = self.playbin.get_property("flags")
            flags |= (1 << 0)  # GST_PLAY_FLAG_VIDEO
            flags |= (1 << 2)  # GST_PLAY_FLAG_AUDIO
            flags |= (1 << 3)  # GST_PLAY_FLAG_SOFT_VOLUME
            
            # Only try to enable subtitles if we have the required plugins
            subtitle_plugins_available = (Gst.ElementFactory.find('subparse') or 
                                         Gst.ElementFactory.find('pango') or 
                                         Gst.ElementFactory.find('textoverlay'))
            
            if subtitle_plugins_available:
                flags |= (1 << 4)  # GST_PLAY_FLAG_TEXT (enable subtitles)
                flags |= (1 << 5)  # GST_PLAY_FLAG_NATIVE_SUBTITLES
                # Enable text all text display features
                flags |= (1 << 6)  # GST_PLAY_FLAG_FORCE_FILTERS
                print("Enabled subtitle support - subtitle plugins found")
            else:
                print("WARNING: Subtitle plugins not found - using custom subtitle handling")
                
            self.playbin.set_property("flags", flags)
            
            # Set up default volume 
            self.playbin.set_property("volume", 1.0)
            
            # Setup text rendering if the pango plugin is available
            if Gst.ElementFactory.find('pangodec') or Gst.ElementFactory.find('pango'):
                # Create pango text renderer when available
                if self.playbin.find_property('text-sink'):
                    print("Setting up pango text rendering")
                    # Create text output bin with pango renderer
                    text_bin = Gst.Bin.new("text-bin")
                    text_convert = Gst.ElementFactory.make("videoconvert", "text-convert")
                    text_sink = Gst.ElementFactory.make("pangodec", "text-sink")
                    if not text_sink:
                        text_sink = Gst.ElementFactory.make("textoverlay", "text-sink")
                    
                    if text_convert and text_sink:
                        text_bin.add(text_convert)
                        text_bin.add(text_sink)
                        text_convert.link(text_sink)
                        
                        # Create ghost pad
                        sink_pad = text_convert.get_static_pad("sink") 
                        ghost_pad = Gst.GhostPad.new("sink", sink_pad)
                        text_bin.add_pad(ghost_pad)
                        
                        # Set text renderer on playbin
                        self.playbin.set_property("text-sink", text_bin)
                        print("Set up pango text renderer")
            else:
                # We're using our own custom subtitle rendering if pango is not available
                print("Using custom subtitle rendering with GTK overlay")
            
            # Use a standard video sink configuration which works reliably
            self.setup_regular_sink()
            
            # Set up bus for pipeline messages
            bus = self.playbin.get_bus()
            bus.add_signal_watch()
            bus.connect("message", self.on_bus_message)
            
            # Explicitly set subtitle encoding to UTF-8
            if hasattr(self.playbin, 'set_property') and self.playbin.find_property('subtitle-encoding'):
                self.playbin.set_property('subtitle-encoding', 'UTF-8')
                print("Set subtitle encoding to UTF-8")

            # Set subtitle font properties if supported
            if hasattr(self.playbin, 'set_property'):
                if self.playbin.find_property('subtitle-font-desc'):
                    self.playbin.set_property('subtitle-font-desc', 'Sans 18')
                    print("Set subtitle font to Sans 18")
                    
            self.pipeline_initialized = True
            print("GStreamer pipeline initialized")
        except Exception as e:
            print(f"ERROR initializing GStreamer pipeline: {e}")
            import traceback
            traceback.print_exc()
            # Create a fallback minimal pipeline to avoid crashes
            if not hasattr(self, 'playbin') or not self.playbin:
                self.playbin = Gst.ElementFactory.make("playbin", "player")
                if self.playbin:
                    print("Created minimal fallback playbin")
            self.pipeline_initialized = False
        
    def setup_regular_sink(self):
        """Set up a regular (non-GL) video sink."""
        # First, check for CSS provider
        self.setup_css()
        
        # Create video output bin
        sink_factory_names = [
            "gtk4paintablesink",  # GTK4 paintable (preferred)
            "gtksink",            # GTK sink (alternative) 
            "xvimagesink",        # X11 video image sink
            "ximagesink",         # X11 image sink
            "autovideosink"       # Automatic video sink
        ]
        
        # Try each sink in order of preference
        sink_set = False
        for sink_name in sink_factory_names:
            try:
                # Check if the factory exists before attempting to create it
                if not Gst.ElementFactory.find(sink_name):
                    print(f"Sink {sink_name} not available")
                    continue
                    
                # Create sink element
                video_sink = Gst.ElementFactory.make(sink_name, "video-sink")
                if not video_sink:
                    continue
                
                if sink_name in ["gtk4paintablesink", "gtksink"]:
                    # Set video sink directly
                    self.video_sink = video_sink
                    self.playbin.set_property("video-sink", video_sink)
                    print(f"Using {sink_name} directly")
                    
                    # Connect to GTK widget
                    if sink_name == "gtk4paintablesink" and hasattr(video_sink, "get_property"):
                        try:
                            paintable = video_sink.get_property("paintable")
                            if paintable:
                                # Clear any previous content
                                self.video_area.set_paintable(None)
                                # Set new paintable
                                self.video_area.set_paintable(paintable)
                                self.video_area.set_content_fit(Gtk.ContentFit.FILL)
                                sink_set = True
                                print("Connected paintable to picture widget")
                                break
                        except Exception as e:
                            print(f"Error setting paintable: {str(e)}")
                    
                    elif sink_name == "gtksink" and hasattr(video_sink, "get_property"):
                        try:
                            widget = video_sink.get_property("widget")
                            if widget:
                                # Remove the picture widget
                                if self.video_area.get_parent() == self.video_container:
                                    self.video_container.remove(self.video_area)
                                # Clear existing children
                                while self.video_container.get_first_child():
                                    self.video_container.remove(self.video_container.get_first_child())
                                # Add the sink widget directly
                                widget.set_hexpand(True)
                                widget.set_vexpand(True)
                                widget.set_halign(Gtk.Align.FILL)
                                widget.set_valign(Gtk.Align.FILL)
                                self.video_container.append(widget)
                                sink_set = True
                                print("Added sink widget to video container")
                                break
                        except Exception as e:
                            print(f"Error setting widget: {str(e)}")
                
                else:
                    # For non-GTK sinks, create a bin with appropriate converters
                    self.video_bin = Gst.Bin.new("video-bin")
                    
                    # Create conversion elements for consistent rendering
                    videoconvert = Gst.ElementFactory.make("videoconvert", "videoconvert")
                    videoscale = Gst.ElementFactory.make("videoscale", "videoscale")
                    capsfilter = Gst.ElementFactory.make("capsfilter", "capsfilter")
                    
                    # Make sure all elements were created successfully
                    if not all([videoconvert, videoscale, capsfilter, video_sink]):
                        print(f"Failed to create elements for {sink_name}")
                        continue
                        
                    # Set properties
                    try:
                        # Set high quality scaling
                        if hasattr(videoscale, 'set_property'):
                            videoscale.set_property("method", 1)  # High quality scaling
                            
                        # Set caps for video format
                        caps = Gst.Caps.from_string("video/x-raw,pixel-aspect-ratio=1/1")
                        capsfilter.set_property("caps", caps)
                        
                        # Set aspect ratio if supported
                        if hasattr(video_sink, 'set_property'):
                            video_sink.set_property("force-aspect-ratio", True)
                    except Exception as e:
                        print(f"Error setting properties: {str(e)}")
                    
                    # Add elements to bin
                    for element in [videoconvert, videoscale, capsfilter, video_sink]:
                        self.video_bin.add(element)
                    
                    # Link elements
                    if not Gst.Element.link_many(videoconvert, videoscale, capsfilter, video_sink):
                        print(f"Failed to link elements for {sink_name}")
                        continue
                    
                    # Create ghost pad for the bin
                    pad = videoconvert.get_static_pad("sink")
                    if not pad:
                        print("Failed to get sink pad")
                        continue
                        
                    ghost_pad = Gst.GhostPad.new("sink", pad)
                    if not ghost_pad:
                        print("Failed to create ghost pad")
                        continue
                        
                    if not self.video_bin.add_pad(ghost_pad):
                        print("Failed to add ghost pad to bin")
                        continue
                    
                    # Set the video bin as the video sink for playbin
                    self.playbin.set_property("video-sink", self.video_bin)
                    self.video_sink = video_sink
                    
                    # Ensure the video area has a good background color
                    self.video_area.set_css_classes(['video-background'])
                    sink_set = True
                    print(f"Created bin with {sink_name}")
                    break
                    
            except Exception as e:
                print(f"Error setting up {sink_name}: {str(e)}")
                continue
        
        # If we get here and haven't set a sink, we failed
        if not sink_set:
            print("WARNING: Failed to create any video sink. Video playback may not work.")
            # Add a fallback - use autovideosink directly as last resort
            try:
                fallback = Gst.ElementFactory.make("autovideosink", "fallback-sink")
                if fallback:
                    self.playbin.set_property("video-sink", fallback)
                    print("Using autovideosink as fallback")
            except Exception as e:
                print(f"Error setting fallback sink: {str(e)}")
        
    def setup_css(self):
        """Set up CSS for the video player."""
        css_provider = Gtk.CssProvider()
        css_data = """
        .video-background {
            background-color: black;
            min-width: 320px;
            min-height: 240px;
        }
        
        .subtitle-text {
            color: white;
            font-size: 18px;
            font-weight: bold;
            text-shadow: 1px 1px 2px black, 0 0 1em black, 0 0 0.2em black;
            background-color: rgba(0, 0, 0, 0.5);
            border-radius: 8px;
            padding: 8px;
        }
        """
        css_provider.load_from_data(css_data.encode())
        
        # Apply the CSS provider to the default screen's style context
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
    
    def create_controls(self):
        """Create video player controls."""
        # Create the controls bar
        controls_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        controls_box.set_margin_top(6)
        controls_box.set_margin_bottom(12)
        controls_box.set_margin_start(12)
        controls_box.set_margin_end(12)
        
        # Progress bar
        progress_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        
        self.position_label = Gtk.Label(label="00:00:00")
        self.position_label.set_width_chars(8)
        self.position_label.set_xalign(0.5)
        progress_box.append(self.position_label)
        
        self.position_scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL)
        self.position_scale.set_draw_value(False)
        self.position_scale.set_range(0, 100)  # Will be updated when video is loaded
        self.position_scale.set_hexpand(True)
        self.position_scale.connect("change-value", self.on_progress_changed)
        self.position_scale.set_sensitive(False)  # Initially disabled
        progress_box.append(self.position_scale)
        
        self.duration_label = Gtk.Label(label="00:00:00")
        self.duration_label.set_width_chars(8)
        self.duration_label.set_xalign(0.5)
        progress_box.append(self.duration_label)
        
        controls_box.append(progress_box)
        
        # Control buttons
        buttons_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        buttons_box.set_margin_top(6)
        buttons_box.set_margin_bottom(6)
        buttons_box.set_halign(Gtk.Align.CENTER)
        
        # Previous button
        self.prev_button = Gtk.Button(icon_name="media-skip-backward-symbolic")
        self.prev_button.set_tooltip_text("Previous video")
        self.prev_button.connect("clicked", self.on_prev_clicked)
        buttons_box.append(self.prev_button)
        
        # Play/Pause button
        self.play_button = Gtk.Button(icon_name="media-playback-start-symbolic")
        self.play_button.set_tooltip_text("Play/Pause")
        self.play_button.connect("clicked", self.on_play_clicked)
        buttons_box.append(self.play_button)
        
        # Stop button
        self.stop_button = Gtk.Button(icon_name="media-playback-stop-symbolic")
        self.stop_button.set_tooltip_text("Stop")
        self.stop_button.connect("clicked", lambda x: self.stop())
        buttons_box.append(self.stop_button)
        
        # Next button
        self.next_button = Gtk.Button(icon_name="media-skip-forward-symbolic")
        self.next_button.set_tooltip_text("Next video")
        self.next_button.connect("clicked", self.on_next_clicked)
        buttons_box.append(self.next_button)
        
        # Volume button
        self.volume_button = Gtk.VolumeButton()
        self.volume_button.set_value(1.0)
        self.volume_button.connect("value-changed", self.on_volume_changed)
        self.volume_button.set_margin_start(12)
        buttons_box.append(self.volume_button)
        
        # Fullscreen button
        self.fullscreen_button = Gtk.Button(icon_name="view-fullscreen-symbolic")
        self.fullscreen_button.set_tooltip_text("Fullscreen")
        self.fullscreen_button.connect("clicked", self.on_fullscreen_clicked)
        self.fullscreen_button.set_margin_start(12)
        buttons_box.append(self.fullscreen_button)
        
        # Subtitle toggle button
        self.subtitle_button = Gtk.ToggleButton()
        subtitle_icon = Gtk.Image.new_from_icon_name("media-view-subtitles-symbolic")
        self.subtitle_button.set_child(subtitle_icon)
        self.subtitle_button.set_tooltip_text("Enable/Disable Subtitles")
        self.subtitle_button.set_active(True)  # Subtitles enabled by default
        self.subtitle_button.connect("toggled", self.on_subtitle_toggled)
        self.subtitle_button.set_margin_start(12)
        buttons_box.append(self.subtitle_button)
        
        controls_box.append(buttons_box)
        
        # Subtitle info bar
        self.subtitle_info_bar = Gtk.InfoBar()
        self.subtitle_info_bar.set_message_type(Gtk.MessageType.INFO)
        self.subtitle_info_bar.set_revealed(False)
        self.subtitle_info_bar.set_show_close_button(True)
        
        subtitle_info_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        
        subtitle_label = Gtk.Label(label="Subtitles: ")
        subtitle_info_box.append(subtitle_label)
        
        self.subtitle_file_label = Gtk.Label(label="None")
        self.subtitle_file_label.set_hexpand(True)
        self.subtitle_file_label.set_halign(Gtk.Align.START)
        self.subtitle_file_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        subtitle_info_box.append(self.subtitle_file_label)
        
        # Add load subtitle button
        load_subtitle_button = Gtk.Button(label="Load Subtitles")
        load_subtitle_button.connect("clicked", self.on_load_subtitle_clicked)
        subtitle_info_box.append(load_subtitle_button)
        
        # Add clear subtitle button
        clear_subtitle_button = Gtk.Button(label="Clear")
        clear_subtitle_button.connect("clicked", self.on_clear_subtitle_clicked)
        subtitle_info_box.append(clear_subtitle_button)
        
        self.subtitle_info_bar.add_child(subtitle_info_box)
        controls_box.append(self.subtitle_info_bar)
        
        # Add the controls to the main container
        self.append(controls_box)
    
    def load_video(self, video_path):
        """Load a video file for playback."""
        if not video_path or not os.path.exists(video_path):
            print(f"Invalid video path: {video_path}")
            return False
            
        # Prevent loading a new video while one is already being loaded
        if hasattr(self, '_loading_video') and self._loading_video:
            print("Already loading a video, ignoring request")
            return False
            
        self._loading_video = True
        
        try:
            print(f"Loading video: {video_path}")
            
            # Save the current video path
            self.current_video = video_path
            
            # Clear subtitle check flags for the new video
            if hasattr(self, '_subtitle_check_completed'):
                delattr(self, '_subtitle_check_completed')
            if hasattr(self, '_last_subtitle_check'):
                delattr(self, '_last_subtitle_check')
            if hasattr(self, '_subtitle_not_found'):
                delattr(self, '_subtitle_not_found')
            
            # Stop any current playback
            if self.playbin:
                self.playbin.set_state(Gst.State.NULL)
                
                # Reset any error flags
                if hasattr(self, '_subtitle_notification_shown'):
                    self._subtitle_notification_shown = False
                
            # Create a proper URI from the path - using Gst.filename_to_uri for proper escaping
            try:
                video_uri = Gst.filename_to_uri(video_path)
            except Exception as e:
                print(f"Error creating URI from path: {e}")
                # Fallback to GLib method
                video_uri = GLib.filename_to_uri(video_path, None)
            
            print(f"Video URI: {video_uri}")
            
            # Make sure playbin is initialized
            if not self.playbin:
                print("ERROR: playbin not initialized, initializing now")
                self.setup_gstreamer()
                if not self.playbin:
                    print("Failed to initialize playbin")
                    self._loading_video = False
                    return False
                    
            # Set the URI on the playbin
            self.playbin.set_property("uri", video_uri)
            
            # Reset position and duration
            self.position = 0
            self.duration = 0
            
            # Try to load subtitles directly ONE TIME before starting playback
            try:
                 self.load_subtitles(video_path)
            except Exception as e:
                 print(f"Error during initial subtitle search: {e}")
            
            # Start playback (GStreamer handles buffering internally)
            # GLib.timeout_add(500, self.play) # Removed delay, play directly
            self.play()
            
            # Clear loading flag after a timeout
            GLib.timeout_add(3000, self.reset_loading_flag)
            
            return True
            
        except Exception as e:
            print(f"Error loading video: {e}")
            self._loading_video = False
            return False
    
    def reset_loading_flag(self):
        """Reset the loading flag to allow loading new videos."""
        self._loading_video = False
        return False  # Don't repeat
        
    def start_playback_when_ready(self):
        """Start playback when the video is ready."""
        # Check if the pipeline is ready
        state = self.playbin.get_state(100 * Gst.MSECOND)[1]
        if state == Gst.State.PAUSED:
            # Video is prerolled and ready to play
            
            # Double-check subtitle settings are applied
            if self.subtitle_file and self.subtitles_enabled:
                # Ensure subtitles are visible
                self.playbin.set_property("current-text", 0)
                # Make subtitle info bar visible
                self.subtitle_info_bar.set_revealed(True)
                
            # Start playback
            self.play()
            
            # Schedule a one-time subtitle refresh check after 2 seconds
            # but only if we haven't already done the check
            if self.subtitle_file and self.subtitles_enabled and not hasattr(self, '_subtitle_check_scheduled'):
                self._subtitle_check_scheduled = True
                GLib.timeout_add(2000, self.check_subtitle_loading)
                
            return False  # Don't repeat
        
        # Not ready yet, check again later
        return True  # Repeat the timeout
        
    def check_subtitle_loading(self):
        """Check if subtitles are properly loaded and force reload if necessary."""
        if not self.playbin or not self.subtitle_file:
            return False
        
        # Prevent recurring checks - only check once per playback session
        if hasattr(self, '_subtitle_check_completed') and self._subtitle_check_completed:
            return False
        
        # Mark this check as completed to prevent future checks
        self._subtitle_check_completed = True
            
        # Try to get number of subtitle tracks
        n_text = 0
        try:
            n_text = self.playbin.get_property('n-text')
            print(f"Checking subtitle loading, found {n_text} subtitle tracks")
            
            # If no tracks, try to force reload
            if n_text == 0:
                print("No subtitle tracks found, trying to force subtitle loading...")
                # Re-apply subtitle file
                self.set_subtitle_file(self.subtitle_file)
                
                # Show a dialog suggesting to install the missing package
                if not Gst.ElementFactory.find('pango'):
                    self.show_subtitle_plugin_dialog()
        except Exception as e:
            print(f"Error checking subtitle tracks: {e}")
            
        return False  # Don't repeat
        
    def show_subtitle_plugin_dialog(self):
        """Show a dialog recommending to install the missing pango plugin."""
        # Only show once per session
        if hasattr(self, '_showed_subtitle_dialog') and self._showed_subtitle_dialog:
            return
            
        self._showed_subtitle_dialog = True
        
        # Show dialog
        dialog = Adw.MessageDialog.new(
            self.get_root(),
            "Subtitle Plugin Missing",
            "Subtitles may not display correctly because the 'pango' GStreamer plugin is missing.\n\n" +
            "Please install it with the following command:\n" +
            "sudo dnf install gstreamer1-plugins-base gstreamer1-plugins-good"
        )
        dialog.add_response("install", "Install Plugin")
        dialog.add_response("later", "Later")
        dialog.set_default_response("install")
        dialog.set_response_appearance("install", Adw.ResponseAppearance.SUGGESTED)
        
        # Connect response handler
        dialog.connect("response", self.on_subtitle_plugin_dialog_response)
        dialog.present()
        
    def on_subtitle_plugin_dialog_response(self, dialog, response):
        """Handle response from the subtitle plugin dialog."""
        if response == "install":
            # Try to install the plugin using PackageKit
            try:
                subprocess_cmd = "pkexec dnf install -y gstreamer1-plugins-base gstreamer1-plugins-good"
                process = subprocess.Popen(
                    subprocess_cmd,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                
                # Show a working dialog
                working_dialog = Adw.MessageDialog.new(
                    self.get_root(),
                    "Installing Plugins",
                    "Please wait while the required plugins are installed..."
                )
                working_dialog.present()
                
                # Check process status periodically
                GLib.timeout_add(1000, self.check_plugin_install_status, process, working_dialog)
            except Exception as e:
                print(f"Error launching installer: {e}")
                self.show_error_dialog(
                    "Installation Error",
                    f"Could not launch the installer: {str(e)}\n\n" +
                    "Please run this command manually in a terminal:\n" +
                    "sudo dnf install gstreamer1-plugins-base gstreamer1-plugins-good"
                )
        
    def check_plugin_install_status(self, process, dialog):
        """Check the status of the plugin installation process."""
        # Check if process has completed
        if process.poll() is not None:
            # Process completed
            dialog.destroy()
            
            # Check return code
            if process.returncode == 0:
                success_dialog = Adw.MessageDialog.new(
                    self.get_root(),
                    "Installation Complete",
                    "The required plugins have been installed. Please restart the application for the changes to take effect."
                )
                success_dialog.add_response("ok", "OK")
                success_dialog.present()
            else:
                # Get error output
                _, err = process.communicate()
                error_msg = err.decode('utf-8') if err else "Unknown error"
                
                self.show_error_dialog(
                    "Installation Failed",
                    f"Failed to install the required plugins.\n\n" +
                    f"Error: {error_msg}\n\n" +
                    "Please try installing manually with:\n" +
                    "sudo dnf install gstreamer1-plugins-base gstreamer1-plugins-good"
                )
            return False  # Don't repeat
        
        # Process still running
        return True  # Repeat check
        
    def load_subtitles(self, video_path):
        """Try to load subtitle file for the current video."""
        if not video_path:
            return False
            
        # Prevent repeated subtitle loading for the same video path
        if hasattr(self, '_last_subtitle_check') and self._last_subtitle_check == video_path:
            print(f"Already checked subtitles for this video, skipping: {video_path}")
            return False
            
        # Set the last checked path to prevent recursion
        self._last_subtitle_check = video_path

        # Reset subtitle state variables, but *don't* hide the info bar yet
        self.subtitle_file = None
        # self.subtitle_info_bar.set_revealed(False) # REMOVED - Keep bar potentially visible
        self.subtitle_label.set_text("")
        self.current_subtitle_text = None
        
        # Check for subtitle files with same name as video but different extensions
        base_path = os.path.splitext(video_path)[0]
        base_name = os.path.basename(base_path)
        directory = os.path.dirname(video_path)
        subtitle_extensions = ['.srt', '.vtt', '.ass', '.ssa', '.sub']
        
        found_subtitle = None
        
        # Common language codes to check
        language_codes = ['en', 'eng', 'english', 'es', 'spa', 'spanish', 'fr', 'fre', 'french', 
                          'de', 'ger', 'german', 'it', 'ita', 'italian', 'ru', 'rus', 'russian']
        
        # Pattern 1: Try language-specific subfiles with dot separator (video.en.srt)
        for lang in language_codes:
            for ext in subtitle_extensions:
                lang_subtitle = f"{base_path}.{lang}{ext}"
                if os.path.exists(lang_subtitle):
                    found_subtitle = lang_subtitle
                    print(f"Found language-specific subtitle with dot: {lang_subtitle}")
                    break
            if found_subtitle:
                break
                
        # Pattern 2: Try language-specific subfiles with underscore separator (video_en.srt)
        if not found_subtitle:
            for lang in language_codes:
                for ext in subtitle_extensions:
                    lang_subtitle = f"{base_path}_{lang}{ext}"
                    if os.path.exists(lang_subtitle):
                        found_subtitle = lang_subtitle
                        print(f"Found language-specific subtitle with underscore: {lang_subtitle}")
                        break
                if found_subtitle:
                    break
                    
        # Pattern 3: Try language-specific subfiles with dash separator (video-en.srt)
        if not found_subtitle:
            for lang in language_codes:
                for ext in subtitle_extensions:
                    lang_subtitle = f"{base_path}-{lang}{ext}"
                    if os.path.exists(lang_subtitle):
                        found_subtitle = lang_subtitle
                        print(f"Found language-specific subtitle with dash: {lang_subtitle}")
                        break
                if found_subtitle:
                    break

        # Pattern 4: If no language-specific subtitle, try generic subtitle with same name
        if not found_subtitle:
            for ext in subtitle_extensions:
                generic_subtitle = f"{base_path}{ext}"
                if os.path.exists(generic_subtitle):
                    found_subtitle = generic_subtitle
                    print(f"Found generic subtitle: {generic_subtitle}")
                    break
        
        # Pattern 5: Check if subtitles directory exists with matching filename
        if not found_subtitle:
            # Check in common subtitle directories
            for subdir in ['subtitles', 'subs', 'srt', 'subtitle', 'sub']:
                subs_dir = os.path.join(directory, subdir)
                if os.path.exists(subs_dir) and os.path.isdir(subs_dir):
                    # Check for subtitles with video name in the subtitles directory
                    for filename in os.listdir(subs_dir):
                        file_base, file_ext = os.path.splitext(filename)
                        if file_ext.lower() in subtitle_extensions:
                            # Various matching strategies
                            if (file_base.lower() in base_name.lower() or  # Contains video name
                                base_name.lower() in file_base.lower() or  # Video name contains subtitle name
                                file_base.lower() == base_name.lower()):    # Exact match
                                found_subtitle = os.path.join(subs_dir, filename)
                                print(f"Found subtitle in subtitles directory: {found_subtitle}")
                                break
                    if found_subtitle:
                        break
        
        # Pattern 6: Check parent directory for subtitle files with movie name 
        if not found_subtitle:
            parent_dir = os.path.dirname(directory)
            if os.path.exists(parent_dir) and os.path.isdir(parent_dir):
                for filename in os.listdir(parent_dir):
                    file_base, file_ext = os.path.splitext(filename)
                    if file_ext.lower() in subtitle_extensions and base_name.lower() in file_base.lower():
                        found_subtitle = os.path.join(parent_dir, filename)
                        print(f"Found subtitle in parent directory: {found_subtitle}")
                        break
        
        if found_subtitle:
            result = self.set_subtitle_file(found_subtitle)
            if result:
                # set_subtitle_file already reveals the bar and sets the label
                return result
            else:
                # set_subtitle_file failed, ensure bar is visible but label is 'None'
                self.subtitle_file_label.set_text("Error loading") # Indicate load failure
                self.subtitle_info_bar.set_revealed(True)
                return False
        else:
            # No subtitle found automatically
            self.subtitle_file_label.set_text("None")
            self.subtitle_info_bar.set_revealed(True) # Ensure bar is visible for manual loading
            
            # Only print this message once per video
            if not hasattr(self, '_subtitle_not_found') or self._subtitle_not_found != video_path:
                print(f"No subtitle found for {video_path}")
                self._subtitle_not_found = video_path
            
        return False
        
    def set_subtitle_file(self, subtitle_path):
        """Set a specific subtitle file for playback."""
        if not subtitle_path or not os.path.exists(subtitle_path):
            print(f"Subtitle file does not exist: {subtitle_path}")
            return False
            
        print(f"Setting subtitle file: {subtitle_path}")
        
        # Validate subtitle file has content (simple check)
        try:
            if os.path.getsize(subtitle_path) == 0:
                print("Subtitle file is empty")
                return False
        except Exception as e:
            print(f"Error checking subtitle file size: {e}")
            return False # Treat inability to check size as an error

        # Store subtitle file path *before* applying to playbin
        self.subtitle_file = subtitle_path
        self.subtitle_file_label.set_text(os.path.basename(subtitle_path))
        
        # Clear any existing custom subtitle display timer immediately
        if hasattr(self, '_subtitle_timer_id') and self._subtitle_timer_id > 0:
            GLib.source_remove(self._subtitle_timer_id)
            self._subtitle_timer_id = 0
        self.subtitle_parser = None # Clear parser
        self.subtitle_label.set_text("") # Clear display label
        self.current_subtitle_text = None

        if not self.playbin:
            print("Error: Playbin not available to set subtitle URI.")
            return False

        # Set the subtitle URI on the playbin
        try:
            subtitle_uri = Gst.filename_to_uri(subtitle_path)
            print(f"Setting subtitle URI: {subtitle_uri}")
            
            # Set subtitle URI - should ideally work dynamically
            self.playbin.set_property("suburi", subtitle_uri)
            
            # Make sure subtitle flags are enabled
            flags = self.playbin.get_property("flags")
            required_flags = (1 << 4) | (1 << 5) | (1 << 7) # TEXT, NATIVE_SUBTITLES, PREFER_EXTERNAL
            if (flags & required_flags) != required_flags:
                 flags |= required_flags
                 print("Enabling required subtitle flags.")
                 self.playbin.set_property("flags", flags)
            
            # Force subtitle encoding to UTF-8 if property exists
            if self.playbin.find_property('subtitle-encoding'):
                try:
                    self.playbin.set_property('subtitle-encoding', 'UTF-8')
                    print("Set subtitle encoding to UTF-8")
                except Exception as e_enc:
                     print(f"Warning: Could not set subtitle encoding: {e_enc}")

            # Force the selected subtitle stream after a short delay to allow GStreamer to process
            # Make this a one-shot check initially
            GLib.timeout_add(1000, self._check_and_force_subtitle_selection) # Renamed and adjusted logic later
            
            # ---- Defer custom parser setup ----
            # We'll check in _check_and_force_subtitle_selection if GStreamer failed
            # ext = os.path.splitext(subtitle_path)[1].lower()
            # self.setup_subtitle_parser(subtitle_path, ext) # REMOVED FOR NOW

            # Update UI immediately
            self.subtitle_info_bar.set_revealed(True)
            self.subtitle_button.set_active(True)
            self.subtitles_enabled = True
            
            print("Subtitle file URI configured, checking GStreamer status...")
            return True # Assume success for now, confirmation happens in _check_and_force_subtitle_selection

        except Exception as e:
            print(f"Error setting subtitle URI or flags: {e}")
            import traceback
            traceback.print_exc()
            # Clear subtitle state on error
            self.subtitle_file = None
            self.subtitle_file_label.set_text("None")
            self.subtitle_info_bar.set_revealed(False)
            return False
            
    def setup_subtitle_parser(self, subtitle_path, ext):
        """Set up the appropriate subtitle parser based on file extension."""
        try:
            # Remove any existing subtitle timer
            if hasattr(self, '_subtitle_timer_id') and self._subtitle_timer_id > 0:
                GLib.source_remove(self._subtitle_timer_id)
                self._subtitle_timer_id = 0
            
            # Import subtitle parser (a simple internal class)
            self.subtitle_parser = self.create_subtitle_parser(subtitle_path, ext)
            
            # Start the subtitle update timer
            if self.subtitle_parser:
                # Update subtitle display based on current position
                self._subtitle_timer_id = GLib.timeout_add(50, self.update_subtitle_display)
                print(f"Subtitle parser initialized for {ext} format")
                return True
            else:
                print(f"Failed to initialize subtitle parser for {ext}")
                return False
        except Exception as e:
            print(f"Error setting up subtitle parser: {e}")
            import traceback
            traceback.print_exc()
            return False
            
    def _check_and_force_subtitle_selection(self):
        """Check if GStreamer loaded the subtitle track, activate it, or fall back to custom parser."""
        if not self.playbin or not self.subtitle_file or not self.subtitles_enabled:
            print("Check subtitle: Conditions not met (no playbin, file, or subtitles disabled).")
            return False # Stop checking
            
        # Prevent running multiple checks concurrently or if already succeeded/failed
        if hasattr(self, '_subtitle_check_in_progress') and self._subtitle_check_in_progress:
            return False
        self._subtitle_check_in_progress = True
            
        try:
            n_text = self.playbin.get_property('n-text')
            print(f"Checking subtitle loading: Found {n_text} GStreamer subtitle tracks.")
            
            if n_text > 0:
                print("GStreamer detected subtitle track(s). Attempting to activate track 0.")
                # Try to set the current text stream to the first one (index 0)
                # This might require the pipeline to be in PAUSED or PLAYING state,
                # but we avoid forcing state changes here if possible.
                try:
                    current_text = self.playbin.get_property('current-text')
                    if current_text != 0:
                         self.playbin.set_property("current-text", 0)
                         print("Set GStreamer current-text to 0.")
                    else:
                         print("GStreamer current-text is already 0.")
                         
                    # Ensure flags are still set (might have been reset by something)
                    flags = self.playbin.get_property("flags")
                    required_flags = (1 << 4) | (1 << 5) | (1 << 7)
                    if (flags & required_flags) != required_flags:
                        flags |= required_flags
                        self.playbin.set_property("flags", flags)
                        print("Re-ensured subtitle flags are set.")

                    # Success: GStreamer should handle subtitles. Clear any custom parser.
                    if hasattr(self, '_subtitle_timer_id') and self._subtitle_timer_id > 0:
                        GLib.source_remove(self._subtitle_timer_id)
                        self._subtitle_timer_id = 0
                    self.subtitle_parser = None
                    self.subtitle_label.set_text("") # Ensure custom label is clear
                    print("GStreamer subtitle track activated. Custom parser disabled.")
                    
                except Exception as e_set:
                    print(f"Warning: Failed to set GStreamer current-text property: {e_set}. GStreamer might still work.")
                    # Proceed assuming GStreamer might handle it, don't fall back immediately.
                    self.subtitle_parser = None # Ensure custom parser is off
                    self.subtitle_label.set_text("") 

            else: # n_text == 0
                print("GStreamer reported 0 subtitle tracks. Falling back to custom subtitle parser.")
                # GStreamer failed to load the subtitle via suburi.
                # Initialize our custom parser/display mechanism.
                ext = os.path.splitext(self.subtitle_file)[1].lower()
                if not self.setup_subtitle_parser(self.subtitle_file, ext):
                    print("Error: Failed to initialize custom subtitle parser.")
                    # Show error to user? Maybe disable subtitles?
                    self.show_error_dialog("Subtitle Error",
                                           f"Could not load subtitle '{os.path.basename(self.subtitle_file)}\' using GStreamer or custom parser.")
                    self.disable_subtitles() # Disable UI elements
                else:
                    print("Custom subtitle parser initialized successfully.")
                    
        except Exception as e:
            print(f"Error checking/forcing subtitle selection: {e}")
            import traceback
            traceback.print_exc()
            # Fallback attempt: Try setting up custom parser anyway
            if self.subtitle_file:
                 ext = os.path.splitext(self.subtitle_file)[1].lower()
                 if not self.setup_subtitle_parser(self.subtitle_file, ext):
                     print("Error: Fallback custom subtitle parser setup also failed.")
                     self.disable_subtitles()
            
        finally:
             self._subtitle_check_in_progress = False
             
        return False  # Ensure this check runs only once per call

    def create_subtitle_parser(self, subtitle_path, ext):
        """Create a subtitle parser for the given file."""
        try:
            # Try different encodings in case of encoding issues
            encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
            subtitle_content = ""
            
            # Try each encoding until one works
            for encoding in encodings:
                try:
                    with open(subtitle_path, 'r', encoding=encoding) as f:
                        subtitle_content = f.read()
                    print(f"Successfully read subtitle file with {encoding} encoding")
                    break
                except UnicodeDecodeError:
                    continue
                except Exception as e:
                    print(f"Error reading subtitle with {encoding} encoding: {e}")
                    continue
            
            # If all encodings failed, try with errors='replace'
            if not subtitle_content:
                with open(subtitle_path, 'r', encoding='utf-8', errors='replace') as f:
                    subtitle_content = f.read()
                print("Read subtitle file with replacement characters (potential encoding issues)")
            
            # Basic SRT parser
            if ext.lower() == '.srt':
                parser = SRTParser(subtitle_content)
                print(f"Created SRT parser with {len(parser.subtitles)} subtitle entries")
                return parser
            # Basic VTT parser
            elif ext.lower() == '.vtt':
                parser = VTTParser(subtitle_content)
                print(f"Created VTT parser with {len(parser.subtitles)} subtitle entries")
                return parser
            # For other formats, try SRT as fallback
            else:
                # Try to detect format from content
                if subtitle_content.strip().startswith('WEBVTT'):
                    parser = VTTParser(subtitle_content)
                    print(f"Auto-detected VTT format with {len(parser.subtitles)} subtitle entries")
                    return parser
                else:
                    parser = SRTParser(subtitle_content)
                    print(f"Using SRT parser as fallback with {len(parser.subtitles)} subtitle entries")
                    return parser
        except Exception as e:
            print(f"Error creating subtitle parser: {e}")
            import traceback
            traceback.print_exc()
            return None

    def update_subtitle_display(self):
        """Update the subtitle text based on current playback position using the custom parser."""
        # This timer should only be active if the custom parser is needed (GStreamer failed)
        # and subtitles are enabled.
        if not self.playbin or not self.subtitle_parser or not self.subtitles_enabled:
            # If subtitles are disabled, ensure the label is cleared.
            if not self.subtitles_enabled and self.subtitle_label.get_text():
                self.subtitle_label.set_text("")
                self.current_subtitle_text = None
            # Keep the timer running if subtitles are enabled but parser/playbin isn't ready yet,
            # but stop if subtitles explicitly disabled.
            return self.subtitles_enabled 
            
        try:
            # Get current position in seconds
            success, position_sec = self.query_position()
            if not success:
                return True # Try again next time
            
            # Use our custom subtitle parser
            position_ms = position_sec * 1000 # Convert seconds to milliseconds
            subtitle_text = self.subtitle_parser.get_subtitle_at_time(position_ms)
            
            # Only update the GTK Label if the text has actually changed
            if subtitle_text != self.current_subtitle_text:
                self.current_subtitle_text = subtitle_text
                if subtitle_text:
                    # Apply formatting and set the text using markup
                    formatted_text = self.subtitle_parser.format_subtitle_text(subtitle_text)
                    self.subtitle_label.set_markup(f"<span>{formatted_text}</span>")
                else:
                    # Clear the label if no subtitle text for this timestamp
                    self.subtitle_label.set_text("")

            # ---- Removed debug counter and fallback force selection ----
            # The fallback logic is handled elsewhere. Less verbose logging.
            # Note: Original commented-out code for reference:
            # if hasattr(self, '_debug_counter'):
            #     self._debug_counter += 1
            # else:
            #     self._debug_counter = 0
            # 
            # if not has_text and self._debug_counter % 50 == 0:
            #     print(f"No subtitle text at position {position_sec:.2f}s")
            # 
            # if self._debug_counter % 100 == 0 and self.subtitle_file:
            #     self._check_and_force_subtitle_selection() # REMOVED
            
        except Exception as e:
            print(f"Error updating custom subtitle display: {e}")
            # Stop the timer on error to prevent spamming logs
            if hasattr(self, '_subtitle_timer_id') and self._subtitle_timer_id > 0:
                 GLib.source_remove(self._subtitle_timer_id)
                 self._subtitle_timer_id = 0
            self.subtitle_label.set_text("") # Clear label on error
            self.current_subtitle_text = None
            return False # Stop timer
        
        return True  # Keep the timer running

    def query_position(self):
        """Query current playback position."""
        if not self.playbin:
            return False, 0
            
        try:
            result, position = self.playbin.query_position(Gst.Format.TIME)
            if result:
                # Convert to seconds
                position_sec = position / Gst.SECOND
                return True, position_sec
        except Exception as e:
            print(f"Error querying position: {str(e)}")
            
        return False, 0

    def seek(self, position):
        """Seek to a specific position in the video."""
        if not self.playbin:
            return
            
        self.playbin.seek_simple(
            Gst.Format.TIME,
            Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
            position * Gst.SECOND
        )

    def on_progress_changed(self, scale, scroll_type, value):
        """Handle position scale change."""
        if self.duration == 0:
            return False
            
        # Mark that we're seeking to avoid position updates
        self.seeking = True
        
        # Calculate position in seconds
        position = (value / 100) * self.duration
        
        # Update position display immediately for better UX
        self.position_label.set_text(self.format_time(position))
        
        # Seek to position
        self.seek(position)
        
        # Clear seeking flag after a short delay to avoid jumps
        GLib.timeout_add(200, self.clear_seeking_flag)
        
        return False

    def clear_seeking_flag(self):
        """Clear the seeking flag after user interaction."""
        self.seeking = False
        return False

    def format_time(self, seconds):
        """Format time in seconds to HH:MM:SS format."""
        minutes, seconds = divmod(int(seconds), 60)
        hours, minutes = divmod(minutes, 60)
        
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes:02d}:{seconds:02d}"
            
    def play(self):
        """Start or resume playback."""
        if not self.playbin:
            print("ERROR: Cannot play - pipeline not initialized")
            return
            
        # If we have a subtitle file, make sure it's applied before starting playback
        if self.subtitle_file and self.subtitles_enabled:
            try:
                # Re-apply subtitle URI to ensure it's loaded
                subtitle_uri = Gst.filename_to_uri(self.subtitle_file)
                self.playbin.set_property("suburi", subtitle_uri)
                
                # Enable text flags if not already enabled
                flags = self.playbin.get_property("flags")
                if not (flags & (1 << 4)):  # Check if GST_PLAY_FLAG_TEXT is not set
                    flags |= (1 << 4)  # GST_PLAY_FLAG_TEXT
                    flags |= (1 << 5)  # GST_PLAY_FLAG_NATIVE_SUBTITLES
                    self.playbin.set_property("flags", flags)
                    print("Enabled subtitle flags for playback")
            except Exception as e:
                print(f"Error applying subtitle before play: {e}")
                
        # Start or resume playback
        self.playbin.set_state(Gst.State.PLAYING)
        self.play_button.set_icon_name("media-playback-pause-symbolic")
        
        # Start position update timer if not already running
        if self.update_id == 0:
            self.update_id = GLib.timeout_add(1000, self.update_position)
            
        # Start progress save timer if not already running
        if self.save_progress and self.save_progress_id == 0:
            # Save progress every 5 seconds
            self.save_progress_id = GLib.timeout_add_seconds(5, self.save_playback_progress)

    def pause(self):
        """Pause playback."""
        if not self.playbin:
            return
            
        self.playbin.set_state(Gst.State.PAUSED)
        self.play_button.set_icon_name("media-playback-start-symbolic")

    def stop(self):
        """Stop playback."""
        if not self.playbin:
            return
            
        self.playbin.set_state(Gst.State.NULL)
        self.play_button.set_icon_name("media-playback-start-symbolic")
        
        # Remove position update timer
        if self.update_id != 0:
            GLib.source_remove(self.update_id)
            self.update_id = 0
            
        # Remove save progress timer
        if self.save_progress_id != 0:
            GLib.source_remove(self.save_progress_id)
            self.save_progress_id = 0

    def update_position(self):
        """Update the position indicator."""
        if not self.playbin:
            return False
            
        # Check if pipeline is playing
        state = self.playbin.get_state(0)[1]
        if state != Gst.State.PLAYING:
            return True
            
        # Get current position
        success, position = self.query_position()
        if not success:
            return True
            
        # Update position
        self.position = position
        
        # Convert to time display
        position_text = self.format_time(position)
        self.position_label.set_text(position_text)
        
        # Only update scale if user isn't dragging it
        if not hasattr(self, 'seeking') or not self.seeking:
            # Avoid division by zero
            if self.duration > 0:
                value = (position / self.duration) * 100
                # Prevent setting out-of-range values which could cause warnings
                if 0 <= value <= 100:
                    self.position_scale.set_value(value)
        
        # Query duration if we don't have it yet
        if self.duration == 0:
            success, duration = self.query_duration()
            if success:
                self.duration = duration
                # Update duration display
                self.duration_label.set_text(self.format_time(duration))
                self.position_scale.set_sensitive(True)
                
        # Emit progress signal
        self.emit("progress-updated", int(position))
                
        # Continue timer
        return True

    def query_duration(self):
        """Query video duration."""
        if not self.playbin:
            return False, 0
            
        try:
            result, duration = self.playbin.query_duration(Gst.Format.TIME)
            if result:
                # Convert to seconds
                duration_sec = duration / Gst.SECOND
                return True, duration_sec
        except Exception as e:
            print(f"Error querying duration: {str(e)}")
            
        return False, 0

    def save_playback_progress(self):
        """Save the current playback position."""
        if self.current_video and self.position > 0:
            # Round to nearest second
            position = int(self.position)
            # Emit signal to notify progress update
            self.emit('progress-updated', position)
        return True  # Keep the timer running

    def on_play_clicked(self, button):
        """Handle play/pause button click."""
        if not self.playbin:
            return
            
        _, state, _ = self.playbin.get_state(Gst.CLOCK_TIME_NONE)
        
        if state == Gst.State.PLAYING:
            self.pause()
        else:
            self.play()

    def on_prev_clicked(self, button):
        """Handle previous button click."""
        # Jump to beginning if we're not already there
        if self.position > 3:
            self.seek(0)

    def on_next_clicked(self, button):
        """Handle next button click."""
        # TODO: Implement next video functionality
        pass

    def on_volume_changed(self, button, value):
        """Handle volume change."""
        if self.playbin:
            self.playbin.set_property("volume", value)
            print(f"Volume set to: {value}")
        return False

    def on_fullscreen_clicked(self, button):
        """Handle fullscreen button click."""
        window = self.get_root()
        if not isinstance(window, Gtk.Window):
            print("Could not get main window to toggle fullscreen")
            return
        
        # Find the control elements - this is the second child of our VideoPlayer box
        controls_box = None
        child = self.get_first_child()
        while child:
            if child != self.video_container:
                controls_box = child
                break
            child = child.get_next_sibling()
        
        if not controls_box:
            print("Could not find controls box")
            return
        
        # Determine if we're entering or exiting fullscreen
        is_entering_fullscreen = not window.is_fullscreen()
        
        # Handle fullscreen toggling
        if is_entering_fullscreen:
            # Enter fullscreen
            window.fullscreen()
            print("Entering fullscreen")
            
            # Save reference to controls
            self._controls_box = controls_box
            
            # Initially hide controls
            controls_box.set_visible(False)
            
            # Create motion controller and attach it to video_overlay
            # The motion controller needs to be on the widget that will receive mouse events
            motion_controller = Gtk.EventControllerMotion.new()
            motion_controller.connect("motion", self._on_fullscreen_motion)
            
            # Add the controller to the video_overlay (where the video is displayed)
            self.video_overlay.add_controller(motion_controller)
            self._motion_controller = motion_controller
            
            # We'll also add a motion controller to the main widget 
            # for better coverage of mouse events
            main_controller = Gtk.EventControllerMotion.new()
            main_controller.connect("motion", self._on_fullscreen_motion)
            self.add_controller(main_controller)
            self._main_controller = main_controller
            
            # Initialize control hiding timer ID
            self._hide_controls_timer_id = 0
        else:
            # Exit fullscreen
            window.unfullscreen()
            print("Exiting fullscreen")
            
            # Show controls again
            if controls_box:
                controls_box.set_visible(True)
            
            # Remove motion controllers
            if hasattr(self, "_motion_controller"):
                self.video_overlay.remove_controller(self._motion_controller)
                del self._motion_controller
                
            if hasattr(self, "_main_controller"):
                self.remove_controller(self._main_controller)
                del self._main_controller
                
            # Remove the timer if active
            if hasattr(self, "_hide_controls_timer_id") and self._hide_controls_timer_id > 0:
                GLib.source_remove(self._hide_controls_timer_id)
                self._hide_controls_timer_id = 0
                
    def _on_fullscreen_motion(self, controller, x, y):
        """Handle mouse motion in fullscreen mode to show/hide controls."""
        print(f"Motion detected: x={x}, y={y}")
        
        # Make sure we have controls to show
        if not hasattr(self, "_controls_box") or not self._controls_box:
            return
            
        # Show controls
        self._controls_box.set_visible(True)
        
        # Cancel any existing timer
        if hasattr(self, "_hide_controls_timer_id") and self._hide_controls_timer_id > 0:
            GLib.source_remove(self._hide_controls_timer_id)
            
        # Set a new timer to hide controls after 2.5 seconds of inactivity
        self._hide_controls_timer_id = GLib.timeout_add(2500, self._hide_controls_callback)
        
    def _hide_controls_callback(self):
        """Callback to hide controls after inactivity timer expires."""
        if hasattr(self, "_controls_box") and self._controls_box:
            print("Hiding controls due to inactivity")
            self._controls_box.set_visible(False)
            
        # Reset timer ID
        self._hide_controls_timer_id = 0
        
        # Return False to prevent the timer from repeating
        return False

    def on_load_subtitle_clicked(self, button):
        """Handle click on load subtitle button."""
        try:
            dialog = Gtk.FileDialog()
            dialog.set_title("Choose Subtitle File")
            
            # Create filters
            subtitle_filter = Gtk.FileFilter()
            subtitle_filter.set_name("Subtitle Files")
            subtitle_filter.add_pattern("*.srt")
            subtitle_filter.add_pattern("*.sub")
            subtitle_filter.add_pattern("*.ssa")
            subtitle_filter.add_pattern("*.ass")
            subtitle_filter.add_pattern("*.vtt")
            
            all_filter = Gtk.FileFilter()
            all_filter.set_name("All Files")
            all_filter.add_pattern("*")
            
            # Create filter list
            filters = Gio.ListStore.new(Gtk.FileFilter)
            filters.append(subtitle_filter)
            filters.append(all_filter)
            
            # Set filters on dialog
            dialog.set_filters(filters)
            dialog.set_default_filter(subtitle_filter)
            
            # Try to set the initial directory to the same as the video
            if self.current_video:
                try:
                    initial_folder = os.path.dirname(self.current_video)
                    if initial_folder and os.path.exists(initial_folder):
                        dialog.set_initial_folder(Gio.File.new_for_path(initial_folder))
                        print(f"Set initial folder to: {initial_folder}")
                except Exception as e:
                    print(f"Error setting initial folder: {e}")
            
            # Show the file dialog asynchronously
            dialog.open(self.get_root(), None, self._on_subtitle_file_selected)
            
        except Exception as e:
            print(f"Error opening subtitle file dialog: {e}")
            import traceback
            traceback.print_exc()
            self.show_error_dialog("Dialog Error", 
                                  f"Could not open file dialog: {str(e)}\n\nThis may be a problem with GTK.")

    def _on_subtitle_file_selected(self, dialog, result):
        """Handle subtitle file selection."""
        try:
            file = dialog.open_finish(result)
            if file:
                path = file.get_path()
                if path:
                    print(f"Selected subtitle file: {path}")
                    
                    # Check if the file is a valid subtitle file
                    if self._validate_subtitle_file(path):
                        # Apply the subtitle file
                        success = self.set_subtitle_file(path)
                        if success:
                            # Make sure subtitles are enabled (set_subtitle_file does this, but double check)
                            self.subtitle_button.set_active(True)
                            self.subtitles_enabled = True
                            
                            # Show confirmation toast if possible
                            self._show_subtitle_toast(f"Loaded subtitle: {os.path.basename(path)}")
                        else:
                            # set_subtitle_file failed, provide a more specific error
                            self.show_error_dialog(
                                "Subtitle Load Error",
                                f"Could not apply the subtitle file '{os.path.basename(path)}\'\\n\\n"
                                "This could be due to GStreamer issues or problems reading the file.\\n"
                                "Check the console output for more detailed errors."
                            )
                    else:
                        print(f"Invalid subtitle file selected: {path}")
                        self.show_error_dialog(
                            "Invalid Subtitle File",
                            "The selected file doesn't appear to be a valid subtitle file.\n\n"
                            "Please make sure it's in a supported format (SRT, VTT, SSA, ASS)."
                        )
                else:
                    print("Error: File selected but path is None")
            else:
                print("No file selected or dialog was cancelled")
        except GLib.Error as e:
            print(f"GLib Error selecting subtitle file: {e.message}")
            self.show_error_dialog("Error Loading Subtitle", f"Could not load subtitle file: {e.message}")
        except Exception as e:
            print(f"Error selecting subtitle file: {e}")
            import traceback
            traceback.print_exc()
            self.show_error_dialog("Error Loading Subtitle", f"Could not load subtitle file: {str(e)}")

    def _validate_subtitle_file(self, file_path):
        """Validate that the file is a proper subtitle file."""
        if not os.path.exists(file_path):
            print(f"Subtitle file does not exist: {file_path}")
            return False
            
        # Check file extension
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in ['.srt', '.vtt', '.sub', '.ssa', '.ass']:
            print(f"Unsupported subtitle extension: {ext}")
            return False
            
        # Check file size
        try:
            size = os.path.getsize(file_path)
            if size == 0:
                print("Subtitle file is empty")
                return False
            if size > 10 * 1024 * 1024:  # 10 MB limit
                print(f"Subtitle file too large: {size} bytes")
                return False
        except Exception as e:
            print(f"Error checking subtitle file size: {e}")
        
        # Check file content (first few lines)
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read(1000)  # Read first 1000 bytes
                
                # Look for common subtitle markers
                if ext == '.srt':
                    # SRT format typically has numbers, timestamps with --> and text
                    has_timestamps = '-->' in content
                    has_numbers = any(line.strip().isdigit() for line in content.split('\n') if line.strip())
                    has_content = len(content.strip()) > 10
                    
                    valid = has_timestamps and has_content
                    print(f"SRT validation: timestamps={has_timestamps}, numbers={has_numbers}, content={has_content}")
                    return valid
                    
                elif ext == '.vtt':
                    # WebVTT format - should start with WEBVTT or have timestamps
                    if content.strip().startswith('WEBVTT'):
                        return True
                    has_timestamps = '-->' in content
                    return has_timestamps and len(content.strip()) > 10
                    
                elif ext in ['.ssa', '.ass']:
                    # SSA/ASS has [Script Info] or [V4+ Styles] sections
                    has_script_info = '[Script Info]' in content
                    has_styles = '[V4+ Styles]' in content or '[Events]' in content
                    return has_script_info or has_styles
                    
                elif ext == '.sub':
                    # SUB format can vary - check for timestamps or frame markers
                    has_timestamps = '-->' in content
                    has_frame_markers = '{' in content and '}' in content
                    return has_timestamps or has_frame_markers
                    
                else:
                    # Generic check - has timestamps
                    return '-->' in content and len(content.strip()) > 10
        except UnicodeDecodeError:
            # Try with binary mode
            print("Unicode decode error, checking for binary subtitle format")
            try:
                with open(file_path, 'rb') as f:
                    binary_content = f.read(1000)
                    # Basic check for binary subtitle formats (e.g., idx/sub)
                    if ext == '.sub' and binary_content.startswith(b'\x00\x00\x01\xba'):
                        return True
                return False
            except Exception as e:
                print(f"Error validating binary subtitle file: {e}")
                return False
        except Exception as e:
            print(f"Error validating subtitle file: {e}")
            import traceback
            traceback.print_exc()
            return False
            
        # Default to accepting if we got this far
        return True

    def _show_subtitle_toast(self, message):
        """Show a toast notification for subtitle operations."""
        try:
            # Try to show a toast if running in Adw application
            root = self.get_root()
            if root and hasattr(root, 'add_toast'):
                toast = Adw.Toast.new(message)
                toast.set_timeout(3)
                root.add_toast(toast)
        except Exception as e:
            print(f"Error showing toast: {e}")
            # Fallback to print
            print(message)

    def on_clear_subtitle_clicked(self, button):
        """Handle clear subtitle button click."""
        # Clear subtitle file reference and update label
        self.subtitle_file = None
        self.subtitle_file_label.set_text("None")
        # Keep the info bar revealed so user can still load manually
        self.subtitle_info_bar.set_revealed(True) 
        
        # Clear subtitle text display
        self.subtitle_label.set_text("")
        
        # Stop any ongoing subtitle update timer
        if hasattr(self, '_subtitle_timer_id') and self._subtitle_timer_id > 0:
            GLib.source_remove(self._subtitle_timer_id)
            self._subtitle_timer_id = 0
        
        # Disable subtitle parser
        self.subtitle_parser = None
        
        # Reset debug counter
        if hasattr(self, '_debug_counter'):
            self._debug_counter = 0
        
        # Update playbin - remove subtitle URI
        if self.playbin:
            try:
                # Get current state to restore it later
                current_state = self.playbin.get_state(0)[1]
                
                # Set to READY state to change subtitle properties
                if current_state != Gst.State.NULL:
                    self.playbin.set_state(Gst.State.READY)
                
                # Clear subtitle URI
                self.playbin.set_property("suburi", None)
                
                # Disable subtitle flags
                flags = self.playbin.get_property("flags")
                flags &= ~(1 << 4)  # Clear GST_PLAY_FLAG_TEXT
                flags &= ~(1 << 5)  # Clear GST_PLAY_FLAG_NATIVE_SUBTITLES
                self.playbin.set_property("flags", flags)
                
                # Restore state
                if current_state != Gst.State.NULL:
                    self.playbin.set_state(current_state)
                
                print("Cleared subtitle settings")
            except Exception as e:
                print(f"Error clearing subtitle URI: {e}")
                import traceback
                traceback.print_exc()
        
        # Update button state
        self.subtitle_button.set_active(False)
        self.subtitles_enabled = False
        
        # Show confirmation message
        self._show_subtitle_toast("Subtitles cleared")

    def on_subtitle_toggled(self, button):
        """Handle toggling of subtitle display."""
        active = button.get_active()
        self.subtitles_enabled = active
        
        print(f"Subtitles {'enabled' if active else 'disabled'}")
        
        if self.playbin:
            # Get current state to restore later
            current_state = self.playbin.get_state(0)[1]
            
            # Get the flags
            flags = self.playbin.get_property("flags")
            
            if active:
                # Enable subtitle flags
                flags |= (1 << 4)  # GST_PLAY_FLAG_TEXT
                flags |= (1 << 5)  # GST_PLAY_FLAG_NATIVE_SUBTITLES
                flags |= (1 << 7)  # GST_PLAY_FLAG_PREFER_EXTERNAL_SUBTITLES
                
                # Re-apply subtitle file if we have one
                if self.subtitle_file:
                    try:
                        # Set to READY state to change subtitle properties
                        if current_state != Gst.State.NULL:
                            self.playbin.set_state(Gst.State.READY)
                        
                        # Re-apply subtitle URI
                        subtitle_uri = Gst.filename_to_uri(self.subtitle_file)
                        self.playbin.set_property("suburi", subtitle_uri)
                        
                        # Apply flags
                        self.playbin.set_property("flags", flags)
                        
                        # Restore state to at least PAUSED to make properties take effect
                        if current_state == Gst.State.NULL:
                            self.playbin.set_state(Gst.State.PAUSED)
                        else:
                            self.playbin.set_state(current_state)
                        
                        # Force subtitle selection after a short delay
                        GLib.timeout_add(500, self._check_and_force_subtitle_selection)
                        
                        print(f"Re-applied subtitle URI: {subtitle_uri}")
                    except Exception as e:
                        print(f"Error re-applying subtitle URI: {e}")
                        import traceback
                        traceback.print_exc()
            else:
                # Disable subtitle flags
                flags &= ~(1 << 4)  # Clear GST_PLAY_FLAG_TEXT
                flags &= ~(1 << 5)  # Clear GST_PLAY_FLAG_NATIVE_SUBTITLES
                
                # Set to READY state to change properties
                if current_state != Gst.State.NULL:
                    self.playbin.set_state(Gst.State.READY)
                
                # Apply flags
                self.playbin.set_property("flags", flags)
                
                # Restore state
                if current_state != Gst.State.NULL:
                    self.playbin.set_state(current_state)
                
                # Clear subtitle label
                self.subtitle_label.set_text("")
                self.current_subtitle_text = None
            
            # Update UI
            if active and self.subtitle_file:
                self.subtitle_info_bar.set_revealed(True)
            elif active and not self.subtitle_file:
                # Keep bar revealed even if toggled on but no file loaded
                self.subtitle_info_bar.set_revealed(True)
                self.subtitle_file_label.set_text("None") # Ensure label is correct
            else: # Not active
                # Keep bar revealed when toggling off
                self.subtitle_info_bar.set_revealed(True)

    def disable_subtitles(self):
        """Disable subtitles and update UI."""
        self.subtitle_button.set_active(False)
        self.subtitles_enabled = False
        self.subtitle_info_bar.set_revealed(True)
        self.subtitle_label.set_text("")
        self.current_subtitle_text = None
        self.update_subtitle_info(None)
        print("Subtitles disabled")

    def update_subtitle_info(self, subtitle_path):
        """Update subtitle information in the UI."""
        if subtitle_path:
            self.subtitle_file = subtitle_path
            self.subtitle_file_label.set_text(os.path.basename(subtitle_path))
            self.subtitle_info_bar.set_revealed(True)
        else:
            self.subtitle_file = None
            self.subtitle_file_label.set_text("None")
            self.subtitle_info_bar.set_revealed(False)
        print(f"Subtitle: {self.subtitle_file}")

    def disable_subtitles_and_continue(self):
        """Disable subtitles and continue playback after a subtitle error."""
        if not self.playbin or not self.current_video:
            return
        
        print("Disabling subtitles and continuing playback")
        
        try:
            # Save current position
            position = 0
            success, pos = self.query_position()
            if success:
                position = pos
                
            # Reset state
            self.playbin.set_state(Gst.State.NULL)
            
            # Disable subtitle flags
            flags = self.playbin.get_property("flags")
            flags &= ~(1 << 4)  # Disable GST_PLAY_FLAG_TEXT
            flags &= ~(1 << 5)  # Disable GST_PLAY_FLAG_NATIVE_SUBTITLES
            self.playbin.set_property("flags", flags)
            
            # Clear subtitle URI
            self.playbin.set_property("suburi", None)
            
            # Update UI
            self.subtitle_button.set_active(False)
            self.subtitles_enabled = False
            self.subtitle_info_bar.set_revealed(False)
            
            # Set standard video sink to avoid errors with subtitle overlay
            video_sink = None
            for sink_name in ["gtk4paintablesink", "gtksink", "autovideosink"]:
                if Gst.ElementFactory.find(sink_name):
                    video_sink = Gst.ElementFactory.make(sink_name, "video-sink")
                    if video_sink:
                        break
            
            if video_sink:
                self.playbin.set_property("video-sink", video_sink)
                
            # Set URI and play
            self.playbin.set_property("uri", Gst.filename_to_uri(self.current_video))
            self.playbin.set_state(Gst.State.PLAYING)
            
            # Seek to saved position after a delay
            if position > 0:
                GLib.timeout_add(1000, lambda: self.seek(position/Gst.SECOND) or False)
                
            # Show notification
            self.show_subtitle_disabled_notification()
                
        except Exception as e:
            print(f"Error while disabling subtitles: {e}")
            
    def show_subtitle_disabled_notification(self):
        """Show a notification that subtitles were disabled due to errors."""
        if not hasattr(self, '_subtitle_notification_shown'):
            self._subtitle_notification_shown = False
            
        if self._subtitle_notification_shown:
            return
            
        self._subtitle_notification_shown = True
        
        # Create a toast message if available (GTK4)
        try:
            parent = self.get_root()
            if parent and hasattr(parent, 'add_toast'):
                toast = Adw.Toast.new("Subtitles disabled due to errors")
                toast.set_timeout(3)
                parent.add_toast(toast)
                return
        except Exception:
            pass
            
        # Fallback to info bar
        try:
            info_bar = Gtk.InfoBar()
            info_bar.set_message_type(Gtk.MessageType.WARNING)
            
            label = Gtk.Label(label="Subtitles disabled due to errors")
            content = info_bar.get_content_area()
            content.append(label)
            
            self.append(info_bar)
            info_bar.set_revealed(True)
            
            # Auto-hide after 5 seconds
            GLib.timeout_add_seconds(5, lambda: info_bar.set_revealed(False) or False)
        except Exception as e:
            print(f"Error showing notification: {e}")

    def check_gstreamer_plugins(self):
        """Check if required GStreamer plugins are available."""
        missing_plugins = []
        
        # Check important plugins
        required_plugins = [
            "playbin",
            "gtk4paintablesink",
            "subparse",
            "pango",
            "videoconvert",
            "audioresample"
        ]
        
        # Check each plugin
        for plugin in required_plugins:
            if not Gst.ElementFactory.find(plugin):
                missing_plugins.append(plugin)
        
        # Show warning if plugins are missing
        if missing_plugins:
            print(f"WARNING: Missing GStreamer plugins: {', '.join(missing_plugins)}")
            print("Some features may not work correctly.")
            print("On Fedora: sudo dnf install gstreamer1-plugins-base gstreamer1-plugins-good gstreamer1-plugins-bad-free gstreamer1-plugins-ugly")
            
            # Specific warning for subtitle plugins
            if "pango" in missing_plugins or "subparse" in missing_plugins:
                print("WARNING: Missing subtitle plugins. Subtitles may not work correctly.")
                print("Install required subtitle plugins with: sudo dnf install gstreamer1-plugins-base gstreamer1-plugins-good")
                
        return len(missing_plugins) == 0

    def show_error_dialog(self, title, message):
        """Show an error dialog with the given title and message."""
        dialog = Adw.MessageDialog.new(
            self.get_root(),
            title,
            message
        )
        dialog.add_response("ok", "OK")
        dialog.present()
        
    def on_bus_message(self, bus, message):
        """Handle messages from GStreamer bus."""
        t = message.type
        
        if t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            error_msg = err.message
            error_domain = err.domain
            print(f"ERROR from element {message.src.get_name()}: {error_msg}")
            
            if debug:
                print(f"Debug info: {debug}")
                
            # Handle pad link errors specially - these often happen with subtitles
            if "pad link failed" in error_msg.lower() or "link" in error_msg.lower():
                print("Pad link error - this may be related to subtitle processing")
                if self.subtitle_file:
                    # Try to continue without subtitles
                    self.disable_subtitles_and_continue()
                    return
                
            # Common error handling patterns
            if "no element" in error_msg.lower() and "pango" in debug.lower():
                print("This error is related to pango subtitle rendering")
                self.show_subtitle_plugin_dialog()
                # Try to continue without subtitles
                self.disable_subtitles_and_continue()
                return
            elif "no suitable plugins" in error_msg.lower() or "no decoders" in error_msg.lower():
                print("This error is related to missing codec plugins")
                self.handle_playback_error("Codec plugins missing",
                                           "No suitable decoder found for the video format.\n"
                                           "Please install gstreamer1-plugins-good, gstreamer1-plugins-bad-free, and gstreamer1-plugins-bad-freeworld packages.")
            else:
                # Generic error handler
                self.handle_playback_error(error_msg, debug)
            
        elif t == Gst.MessageType.EOS:
            print("End of stream reached")
            # Reset to beginning
            self.stop()
            # Emit progress to update UI
            self.emit("progress-updated", 0)
            
        elif t == Gst.MessageType.STATE_CHANGED:
            # Only process messages from playbin
            if message.src != self.playbin:
                return
                
            old_state, new_state, pending = message.parse_state_changed()
            print(f"State changed: {old_state.value_name} -> {new_state.value_name} (pending: {pending.value_name})")
            
            if new_state == Gst.State.PLAYING:
                # Update UI for playing state
                self.play_button.set_icon_name("media-playback-pause-symbolic")
                
                # Check and report subtitle streams when we start playing
                if self.subtitle_file and self.subtitles_enabled:
                    n_text = 0
                    if hasattr(self.playbin, 'get_property'):
                        try:
                            n_text = self.playbin.get_property('n-text')
                            print(f"Number of subtitle tracks: {n_text}")
                            if n_text > 0:
                                # Re-enable subtitle track
                                self.playbin.set_property("current-text", 0)
                                print("Re-selected subtitle track 0")
                        except Exception as e:
                            print(f"Error getting subtitle track info: {e}")
                
                # Start progress updates
                if self.update_id == 0:
                    self.update_id = GLib.timeout_add(500, self.update_position)
                    
                # Start save progress timer
                if self.save_progress and self.save_progress_id == 0:
                    self.save_progress_id = GLib.timeout_add(5000, self.save_playback_progress)
                    
            elif new_state == Gst.State.PAUSED:
                # Update UI for paused state
                self.play_button.set_icon_name("media-playback-start-symbolic")
                
            elif new_state == Gst.State.READY:
                # Stop progress updates
                if self.update_id != 0:
                    GLib.source_remove(self.update_id)
                    self.update_id = 0
                    
                # Stop save progress timer
                if self.save_progress_id != 0:
                    GLib.source_remove(self.save_progress_id)
                    self.save_progress_id = 0
                    
                # Update UI
                self.play_button.set_icon_name("media-playback-start-symbolic")
                self.position_label.set_text("00:00:00")
                self.position_scale.set_value(0)
                
        elif t == Gst.MessageType.TAG:
            # Process metadata tags
            tag_list = message.parse_tag()
            # Print tags for debugging
            tag_list.foreach(self.print_tag, None)
            
        elif t == Gst.MessageType.ELEMENT:
            # Handle element-specific messages
            structure = message.get_structure()
            if structure and structure.has_name("missing-plugin"):
                detail = structure.get_string("detail")
                print(f"Missing plugin: {detail}")
                
                # If it's subtitle-related, show a more specific dialog
                if "subtitle" in detail.lower() or "text" in detail.lower():
                    self.show_error_dialog(
                        "Missing Subtitle Plugin",
                        "A plugin needed to display subtitles is missing.\n\n"
                        "Install the required plugins with:\n"
                        "sudo dnf install gstreamer1-plugins-base gstreamer1-plugins-good"
                    )
            
            # Handle subtitle-related element messages
            if structure and (structure.has_name("subtitle-added") or 
                             structure.has_name("text-added") or
                             structure.has_name("streams-changed")):
                # If we get a notification about subtitle streams changing
                if self.subtitle_file and self.subtitles_enabled:
                    GLib.timeout_add(500, self._check_and_force_subtitle_selection)
                    print("Subtitle streams changed, will try to reselect subtitle track")

    def handle_playback_error(self, error_msg, debug_info=None):
        """Handle playback errors with user-friendly messages."""
        # Try to recover from some errors
        if "pango" in error_msg.lower() or "subtitle" in error_msg.lower():
            # Try disabling subtitles
            print("Trying to recover by disabling subtitles")
            flags = self.playbin.get_property("flags")
            flags &= ~(1 << 4)  # Disable GST_PLAY_FLAG_TEXT
            self.playbin.set_property("flags", flags)
            # Try to play the video anyway
            if self.current_video:
                GLib.timeout_add(500, self.restart_playback)
            return
            
        # For codec errors, show specific installation instructions
        if "decoder" in error_msg.lower() or "codec" in error_msg.lower() or "element" in error_msg.lower():
            install_cmd = "sudo dnf install gstreamer1-plugins-good gstreamer1-plugins-bad-free gstreamer1-plugins-bad-freeworld gstreamer1-libav"
            
            # Try to identify specific codec
            codec_type = "video"
            if debug_info:
                if "mp3" in debug_info.lower() or "aac" in debug_info.lower() or "audio" in debug_info.lower():
                    codec_type = "audio"
                    
            message = f"""<b>Missing {codec_type} codec plugin</b>
            
The video cannot be played because the required codec is not installed.

Run the following command in terminal to install required plugins:
<tt>{install_cmd}</tt>

After installation, restart the application."""

            # Show user-friendly error dialog
            self.show_error_dialog("Codec Not Found", message)
            
            # Stop playback
            self.stop()
            return
            
        # For other errors, use generic error dialog
        if not debug_info:
            debug_info = "No additional debug information available."
            
        # Default error dialog
        message = f"<b>Playback Error</b>\n\n{error_msg}\n\n<small>{debug_info}</small>"
        self.show_error_dialog("Playback Error", message)
        
        # Stop playback on fatal errors
        self.stop()
        
    def restart_playback(self):
        """Restart playback after recovering from an error."""
        # Clear any stateful error conditions
        if self.playbin and self.current_video:
            # Reset the pipeline
            self.playbin.set_state(Gst.State.NULL)
            # Set the URI again
            self.playbin.set_property("uri", Gst.filename_to_uri(self.current_video))
            # Start playback
            self.playbin.set_state(Gst.State.PLAYING)
            print("Restarted playback after error recovery")
        return False  # Don't call again

    def print_tag(self, tag_list, tag, user_data):
        """Debug helper to print tag information."""
        try:
            value = tag_list.get_value_index(tag, 0)
            print(f"Tag: {tag} = {value}")
        except Exception as e:
            print(f"Error getting tag value: {e}")

class SRTParser:
    """Parser for SRT subtitle format."""
    
    def __init__(self, content):
        self.subtitles = []
        self.parse(content)
        
    def parse(self, content):
        """Parse SRT content into a list of subtitle entries."""
        if not content:
            return
            
        # Split by double newline (subtitle separator)
        blocks = content.strip().replace('\r\n', '\n').split('\n\n')
        
        for block in blocks:
            lines = block.split('\n')
            if len(lines) < 3:
                continue  # Skip invalid blocks
                
            # Parse timing line
            timing = lines[1]
            times = timing.split(' --> ')
            if len(times) != 2:
                continue
                
            try:
                start_time = self.time_to_ms(times[0].strip())
                end_time = self.time_to_ms(times[1].strip())
                
                # Get text (could be multiple lines)
                text = '\n'.join(lines[2:])
                
                # Add to subtitle list
                self.subtitles.append({
                    'start': start_time,
                    'end': end_time,
                    'text': text
                })
            except Exception as e:
                print(f"Error parsing subtitle timing: {e}")
                
        # Sort by start time
        self.subtitles.sort(key=lambda x: x['start'])
        print(f"Parsed {len(self.subtitles)} SRT subtitles")
        
    def time_to_ms(self, time_str):
        """Convert SRT time format to milliseconds."""
        parts = time_str.replace(',', '.').split(':')
        if len(parts) != 3:
            return 0
            
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = float(parts[2])
        
        return (hours * 3600 + minutes * 60 + seconds) * 1000
        
    def get_subtitle_at_time(self, timestamp_ms):
        """Get subtitle text for the given timestamp."""
        for subtitle in self.subtitles:
            if subtitle['start'] <= timestamp_ms <= subtitle['end']:
                # Format the text for display
                return self.format_subtitle_text(subtitle['text'])
        return ""
        
    def format_subtitle_text(self, text):
        """Format subtitle text for display with GTK markup."""
        # Clean up text and apply basic formatting
        text = text.replace('&', '&amp;')
        text = text.replace('<', '&lt;')
        text = text.replace('>', '&gt;')
        
        # Handle basic formatting tags often found in SRT
        text = text.replace('{b}', '<b>')
        text = text.replace('{/b}', '</b>')
        text = text.replace('{i}', '<i>')
        text = text.replace('{/i}', '</i>')
        
        return text
        
class VTTParser:
    """Parser for WebVTT subtitle format."""
    
    def __init__(self, content):
        self.subtitles = []
        self.parse(content)
        
    def parse(self, content):
        """Parse WebVTT content into a list of subtitle entries."""
        if not content:
            return
            
        lines = content.strip().replace('\r\n', '\n').split('\n')
        
        # Check for WebVTT header
        if not lines or not lines[0].startswith('WEBVTT'):
            print("Invalid WebVTT file: missing header")
            return
            
        subtitle = None
        text_lines = []
        
        for line in lines[1:]:
            line = line.strip()
            
            # Skip comments and empty lines
            if not line or line.startswith('NOTE '):
                continue
                
            # Check if this is a timing line
            if ' --> ' in line:
                # If we were already building a subtitle, add it to the list
                if subtitle and text_lines:
                    subtitle['text'] = '\n'.join(text_lines)
                    self.subtitles.append(subtitle)
                
                # Start a new subtitle
                times = line.split(' --> ')
                if len(times) != 2:
                    continue
                    
                try:
                    start_time = self.time_to_ms(times[0].strip())
                    end_time = self.time_to_ms(times[1].strip().split(' ')[0])  # Remove settings
                    
                    subtitle = {
                        'start': start_time,
                        'end': end_time,
                        'text': ''
                    }
                    text_lines = []
                except Exception as e:
                    print(f"Error parsing VTT timing: {e}")
                    subtitle = None
            
            # If we're building a subtitle, add this line to the text
            elif subtitle is not None:
                text_lines.append(line)
        
        # Add the last subtitle
        if subtitle and text_lines:
            subtitle['text'] = '\n'.join(text_lines)
            self.subtitles.append(subtitle)
            
        # Sort by start time
        self.subtitles.sort(key=lambda x: x['start'])
        print(f"Parsed {len(self.subtitles)} WebVTT subtitles")
        
    def time_to_ms(self, time_str):
        """Convert WebVTT time format to milliseconds."""
        # Handle both HH:MM:SS.mmm and MM:SS.mmm formats
        parts = time_str.split(':')
        if len(parts) == 3:  # HH:MM:SS.mmm
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = float(parts[2])
        elif len(parts) == 2:  # MM:SS.mmm
            hours = 0
            minutes = int(parts[0])
            seconds = float(parts[1])
        else:
            return 0
            
        return (hours * 3600 + minutes * 60 + seconds) * 1000
        
    def get_subtitle_at_time(self, timestamp_ms):
        """Get subtitle text for the given timestamp."""
        for subtitle in self.subtitles:
            if subtitle['start'] <= timestamp_ms <= subtitle['end']:
                return self.format_subtitle_text(subtitle['text'])
        return ""
        
    def format_subtitle_text(self, text):
        """Format subtitle text for display with GTK markup."""
        # Clean up text and apply basic formatting
        text = text.replace('&', '&amp;')
        text = text.replace('<', '&lt;')
        text = text.replace('>', '&gt;')
        
        # Handle <b>, <i>, <u> tags that are allowed in WebVTT
        allowed_tags = ['b', 'i', 'u', 'c']
        for tag in allowed_tags:
            text = text.replace(f'<{tag}>', f'<{tag}>')
            text = text.replace(f'</{tag}>', f'</{tag}>')
        
        return text 