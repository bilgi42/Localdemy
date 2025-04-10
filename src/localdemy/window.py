"""
Main window for the Localdemy application.
"""

import gi
import os
import json
import threading
import sys
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio, GLib, GObject

from .video_player import VideoPlayer
from .library import LibraryView
from .video_utils import get_video_duration

# List of common video file extensions
VIDEO_EXTENSIONS = ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.mpg', '.mpeg', '.3gp']

class LocaldemyWindow(Adw.ApplicationWindow):
    """Main window for the Localdemy application."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        self.set_default_size(1200, 800)
        self.set_title("Localdemy")
        
        # Flags to prevent recursive operations
        self._loading_folder = False
        self._selecting_video = False
        self._auto_loaded = False  # Flag to prevent multiple auto-loads
        self._in_progress_save = False  # Flag to prevent save operations triggering reloads
        
        # Progress tracking
        self.current_video_path = None
        self.progress_data = {}
        self.load_progress_data()
        
        # Create the main layout
        self.setup_ui()
        
        # Set folder view to on by default (or use saved setting)
        show_folders = True
        if '_app_state' in self.progress_data and 'show_folders' in self.progress_data['_app_state']:
            show_folders = self.progress_data['_app_state'].get('show_folders', True)
            print(f"Loaded saved folder view setting: {show_folders}")
        
        if hasattr(self, 'folder_view_switch'):
            self.folder_view_switch.set_active(show_folders)
            self.library_view.set_show_folders(show_folders)
        
        # Auto-load last folder and video (once and with delay)
        GLib.timeout_add_seconds(1, self.load_last_folder)
        
    def setup_ui(self):
        """Set up the user interface."""
        # Create the main layout container
        self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        
        # Create the header bar
        self.create_header()
        
        # Create the main content
        self.create_content()
        
        # Set the main box as the content of the window
        self.set_content(self.main_box)
        
        # Connect to the library view signals
        self.library_view.connect_video_selected_handler(self.on_video_selected)
        self.library_view.connect_folder_selected_handler(self.on_folder_selected)
        
    def create_header(self):
        """Create the header bar for the window."""
        # Create header bar
        self.header = Adw.HeaderBar()
        
        # Add the back button (initially hidden)
        self.back_button = Gtk.Button()
        self.back_button.set_icon_name("go-previous-symbolic")
        self.back_button.set_tooltip_text("Back to Library")
        self.back_button.connect("clicked", self.on_back_to_library_clicked)
        self.back_button.set_visible(False)
        self.header.pack_start(self.back_button)
        
        # Add folder navigation back button (initially hidden)
        self.folder_back_button = Gtk.Button()
        self.folder_back_button.set_icon_name("go-up-symbolic")
        self.folder_back_button.set_tooltip_text("Back to Parent Folder")
        self.folder_back_button.connect("clicked", self.on_folder_back_clicked)
        self.folder_back_button.set_visible(False)
        self.header.pack_start(self.folder_back_button)
        
        # Add 'Open Folder' button to the header
        self.open_folder_button = Gtk.Button()
        self.open_folder_button.set_label("Open Videos Folder")
        self.open_folder_button.set_icon_name("folder-open-symbolic")
        self.open_folder_button.connect("clicked", self.on_open_folder_clicked)
        self.header.pack_start(self.open_folder_button)
        
        # Add menu button
        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")
        
        # Create menu model
        menu = Gio.Menu()
        menu.append("Preferences", "app.preferences")
        menu.append("About", "app.about")
        menu.append("Quit", "app.quit")
        
        menu_button.set_menu_model(menu)
        self.header.pack_end(menu_button)
        
        # Add search button
        search_button = Gtk.Button(icon_name="system-search-symbolic")
        search_button.connect("clicked", self.on_search_clicked)
        self.header.pack_end(search_button)
        
        # Set folder view always on but hidden from UI
        self.folder_view_switch = Gtk.Switch()
        self.folder_view_switch.set_active(True)  # Always default to folder view
        
        # Add to main box
        self.main_box.append(self.header)
        
    def create_content(self):
        """Create the main content area."""
        # Create a split pane with library on the left and content on the right
        self.paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        
        # Create the library view (left side)
        self.library_view = LibraryView()
        self.library_view.connect("video-selected", self.on_video_selected)
        left_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        left_box.append(self.library_view)
        left_box.set_hexpand(True)
        left_box.set_vexpand(True)
        
        # Create the content view (right side)
        self.content_stack = Gtk.Stack()
        
        # Create the welcome page
        welcome_page = self.create_welcome_page()
        self.content_stack.add_named(welcome_page, "welcome")
        
        # Create the video player page
        self.video_player = VideoPlayer()
        self.video_player.connect("progress-updated", self.on_video_progress_updated)
        self.content_stack.add_named(self.video_player, "player")
        
        # Set up the paned view
        self.paned.set_start_child(left_box)
        self.paned.set_end_child(self.content_stack)
        self.paned.set_position(300)
        
        # Add the paned container to the main box
        self.main_box.append(self.paned)
        self.main_box.set_vexpand(True)
        
        # Show the welcome page by default
        self.content_stack.set_visible_child_name("welcome")
        
    def create_welcome_page(self):
        """Create the welcome page shown when no video is selected."""
        welcome_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        welcome_box.set_valign(Gtk.Align.CENTER)
        welcome_box.set_halign(Gtk.Align.CENTER)
        welcome_box.set_spacing(12)
        
        icon = Gtk.Image.new_from_icon_name("video-display-symbolic")
        icon.set_pixel_size(64)
        welcome_box.append(icon)
        
        title = Gtk.Label()
        title.set_markup("<span size='xx-large'>Welcome to Localdemy</span>")
        welcome_box.append(title)
        
        subtitle = Gtk.Label(label="Open a folder to start watching videos")
        welcome_box.append(subtitle)
        
        # Button for Open Folder
        open_button = Gtk.Button(label="Open Videos Folder")
        open_button.get_style_context().add_class("suggested-action")
        open_button.connect("clicked", self.on_open_folder_clicked)
        welcome_box.append(open_button)
        
        return welcome_box
        
    def on_search_clicked(self, button):
        """Handle search button click."""
        # TODO: Implement search functionality
        pass
    
    def on_folder_view_toggled(self, switch, state):
        """Handle folder view toggle switch state change."""
        print(f"Folder view toggled to: {state}")
        
        # Always show folders regardless of toggle
        self.library_view.set_show_folders(True)
        
        # Save the setting
        if '_app_state' not in self.progress_data:
            self.progress_data['_app_state'] = {}
        self.progress_data['_app_state']['show_folders'] = True
        # Call _save_progress_without_reload directly to prevent recursion
        self._save_progress_without_reload()
        
        # If we have a current folder loaded, no need to reload
        # This helps prevent recursion
        return False
    
    def load_progress_data(self):
        """Load the progress tracking data from file."""
        progress_file = os.path.join(GLib.get_user_config_dir(), "localdemy", "progress.json")
        os.makedirs(os.path.dirname(progress_file), exist_ok=True)
        
        if os.path.exists(progress_file):
            try:
                with open(progress_file, 'r') as f:
                    self.progress_data = json.load(f)
                print(f"Loaded progress data for {len(self.progress_data)} videos")
            except Exception as e:
                print(f"Error loading progress data: {e}")
                self.progress_data = {}
        else:
            self.progress_data = {}
            
        # Initialize app state if not exists
        if '_app_state' not in self.progress_data:
            self.progress_data['_app_state'] = {
                'last_folder': None,
                'last_video': None
            }
    
    def save_progress_data(self):
        """Save the progress tracking data to file."""
        # Use our dedicated function that doesn't trigger reloads
        return self._save_progress_without_reload()
    
    def get_video_progress(self, video_path):
        """Get the saved progress for a video."""
        if video_path in self.progress_data:
            return self.progress_data[video_path]
        return None
    
    def on_video_progress_updated(self, video_player, position):
        """Handle video playback progress updates."""
        if not self.current_video_path:
            return
            
        # If we're already in the process of saving or loading a folder, don't try to save again
        if (hasattr(self, '_in_progress_save') and self._in_progress_save) or \
           (hasattr(self, '_loading_folder') and self._loading_folder) or \
           (hasattr(self, '_saving_progress') and self._saving_progress):
            return
            
        # Save progress as position in seconds and percentage
        duration = video_player.duration
        if duration > 0:
            percentage = position / duration
            self.progress_data[self.current_video_path] = {
                'position': position,
                'percentage': percentage,
                'last_watched': GLib.get_real_time() // 1000000  # Current time in seconds
            }
            
            # Update video item in list if it exists
            self.update_video_item_progress(self.current_video_path, percentage)
            
            # Save progress data every 5 seconds but don't reload the folder
            # This prevents recursion when watching videos
            if not hasattr(self, '_saving_progress') or not self._saving_progress:
                self._saving_progress = True
                # Use a longer delay to reduce save frequency
                GLib.timeout_add_seconds(10, self._save_progress_without_reload)
                
            print(f"Progress updated for {os.path.basename(self.current_video_path)}: {position:.1f}s ({percentage:.1%})")
            
    def _save_progress_without_reload(self):
        """Save progress data without reloading the folder."""
        # If a save is already in progress, don't start another one
        if hasattr(self, '_in_progress_save') and self._in_progress_save:
            print("Save already in progress, ignoring duplicate request")
            return False
            
        try:
            # Set a flag to indicate we're in the middle of saving
            # This prevents recursive operations
            self._in_progress_save = True
            
            progress_file = os.path.join(GLib.get_user_config_dir(), "localdemy", "progress.json")
            os.makedirs(os.path.dirname(progress_file), exist_ok=True)
            
            # Update app state
            if '_app_state' not in self.progress_data:
                self.progress_data['_app_state'] = {}
                
            # Store current folder and video
            if hasattr(self, 'current_folder'):
                self.progress_data['_app_state']['last_folder'] = self.current_folder
            if self.current_video_path:
                self.progress_data['_app_state']['last_video'] = self.current_video_path
                
            # Store folder view setting
            if hasattr(self, 'folder_view_switch'):
                self.progress_data['_app_state']['show_folders'] = self.folder_view_switch.get_active()
            
            with open(progress_file, 'w') as f:
                json.dump(self.progress_data, f)
            print(f"Saved progress data for {len(self.progress_data) - 1} videos")  # -1 for _app_state
        except Exception as e:
            print(f"Error saving progress data: {str(e)}")
        finally:
            # Clear both flags
            if hasattr(self, '_saving_progress'):
                self._saving_progress = False
            
            # Important: clear the progress save flag to allow future operations
            self._in_progress_save = False
            
        return False  # Don't repeat
    
    def update_video_item_progress(self, video_path, progress_percentage):
        """Update the progress indicator in the library view."""
        try:
            self.library_view.update_video_progress(video_path, progress_percentage)
        except Exception as e:
            print(f"Error updating video progress: {str(e)}")
            
    def on_open_folder_clicked(self, button):
        """Handle open folder button click."""
        # Create a file dialog for selecting a folder
        dialog = Gtk.FileDialog()
        dialog.set_title("Select Videos Folder")
        
        # Set up the dialog for folder selection
        try:
            # GTK4 way for folder selection
            dialog.select_folder(self, None, self.on_open_folder_dialog_response)
        except Exception as e:
            print(f"Error opening folder dialog: {str(e)}")
            
            # Fallback to older method if needed
            try:
                file_chooser = Gtk.FileChooserDialog(
                    title="Select Videos Folder",
                    parent=self,
                    action=Gtk.FileChooserAction.SELECT_FOLDER
                )
                file_chooser.add_button("Cancel", Gtk.ResponseType.CANCEL)
                file_chooser.add_button("Open", Gtk.ResponseType.ACCEPT)
                file_chooser.connect("response", self.on_file_chooser_response)
                file_chooser.show()
            except Exception as e2:
                print(f"Error creating fallback dialog: {str(e2)}")
                self.show_error_dialog("Error opening folder dialog", str(e))

    def on_open_folder_dialog_response(self, dialog, result):
        """Handle open folder dialog response."""
        try:
            # Handle the result
            if isinstance(result, Gio.AsyncResult):
                # GTK4 style response
                folder = dialog.select_folder_finish(result)
                if folder:
                    folder_path = folder.get_path()
                    print(f"Opening videos folder: {folder_path}")
                    self.load_videos_from_folder(folder_path)
            else:
                print(f"Unexpected result type: {type(result)}")
        except Exception as e:
            print(f"Error opening folder: {str(e)}")
            self.show_error_dialog("Error Opening Folder", str(e))
    
    def on_file_chooser_response(self, dialog, response):
        """Handle response from the fallback file chooser dialog."""
        if response == Gtk.ResponseType.ACCEPT:
            folder_path = dialog.get_filename()
            if folder_path:
                print(f"Opening videos folder: {folder_path}")
                self.load_videos_from_folder(folder_path)
        dialog.destroy()
        
    def show_error_dialog(self, title, message):
        """Show an error dialog."""
        dialog = Adw.MessageDialog.new(
            self,
            title,
            message
        )
        dialog.add_response("ok", "OK")
        dialog.set_default_response("ok")
        dialog.present()

    def load_videos_from_folder(self, folder_path, auto_play_last=False):
        """Load videos from a folder into the library view."""
        if not folder_path or not os.path.isdir(folder_path):
            self.show_error_dialog("Error", f"Invalid folder path: {folder_path}")
            return False
            
        # CRITICAL FIX: Only check the loading flag but don't set it here
        # since it's now managed in on_folder_selected and delayed_load_folder
        if self._loading_folder:
            print("Already loading a folder, ignoring request")
            return False
            
        # Don't load a folder if we're in the middle of saving progress
        # This prevents recursive operations from progress saves triggering folder reloads
        if hasattr(self, '_in_progress_save') and self._in_progress_save:
            print("Currently saving progress, ignoring folder load request")
            return False
            
        # Set loading flag - now we set it here when actually loading
        self._loading_folder = True
        
        # Clear the library view
        self.library_view.clear()
        
        # Store the folder path
        self.current_folder = folder_path
        
        # Save the folder as the last used folder
        if '_app_state' not in self.progress_data:
            self.progress_data['_app_state'] = {}
        self.progress_data['_app_state']['last_folder'] = folder_path
        # Call _save_progress_without_reload directly to prevent recursion
        self._save_progress_without_reload()
        
        # Update the window title
        folder_name = os.path.basename(folder_path)
        self.set_title(f"Localdemy - {folder_name}")
        
        # Show folder back button if we have a navigation stack with items
        if hasattr(self, 'folder_navigation_stack') and self.folder_navigation_stack:
            self.folder_back_button.set_visible(True)
        else:
            # Check if we're in a subdirectory
            parent_dir = os.path.dirname(folder_path)
            # If we have a parent directory that's not the same as the current directory
            # we should show the back button even without a navigation stack
            if parent_dir and parent_dir != folder_path:
                self.folder_back_button.set_visible(True)
            else:
                self.folder_back_button.set_visible(False)
        
        # Create progress dialog manually instead of loading from UI file
        progress_dialog = Adw.MessageDialog.new(
            self,
            "Loading Videos",
            f"Scanning folder: {folder_path}"
        )
        
        # Add a progress bar
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content_box.set_margin_top(12)
        content_box.set_margin_bottom(12)
        content_box.set_margin_start(12)
        content_box.set_margin_end(12)
        
        progress_bar = Gtk.ProgressBar()
        progress_bar.set_show_text(True)
        progress_bar.set_text("Scanning...")
        progress_bar.set_fraction(0.0)
        content_box.append(progress_bar)
        
        # Add cancel button
        cancel_button = Gtk.Button(label="Cancel")
        cancel_button.set_halign(Gtk.Align.CENTER)
        cancel_button.connect("clicked", self.on_scan_cancelled, progress_dialog)
        content_box.append(cancel_button)
        
        progress_dialog.set_extra_child(content_box)
        progress_dialog.present()
        
        # Start a thread to scan the folder
        threading.Thread(
            target=self.scan_folder_thread,
            args=(folder_path, progress_dialog, progress_bar, auto_play_last),
            daemon=True
        ).start()
        
        return True

    def on_scan_cancelled(self, dialog, response):
        """Handle scan cancellation."""
        self.scan_cancelled = True
        print("Scan cancelled by user")
        dialog.destroy()
    
    def scan_folder_thread(self, folder_path, progress_dialog, progress_bar, auto_play_last):
        """Scan folder in a background thread."""
        try:
            # Initialize scan_cancelled flag
            self.scan_cancelled = False
            
            # Define a function to update UI from the main thread
            def update_progress(fraction, text):
                def update_ui():
                    # Check if the dialog is still valid
                    if progress_dialog and hasattr(progress_dialog, 'get_visible') and progress_dialog.get_visible():
                        progress_bar.set_fraction(fraction)
                        progress_bar.set_text(text)
                    return False
                GLib.idle_add(update_ui)
            
            # Count all video files to determine progress
            update_progress(0.0, "Counting files...")
            
            all_files = []
            folder_structure = {}
            total_files = 0
            
            print(f"Scanning folder as folder structure: {folder_path}")
            update_progress(0.1, "Scanning folder...")
            
            for root, dirs, files in os.walk(folder_path):
                # Skip hidden directories
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                
                # Count files with video extension
                video_files = [f for f in files if os.path.splitext(f)[1].lower() in VIDEO_EXTENSIONS]
                
                # Add to total count
                total_files += len(video_files)
                
                # Store in structure
                rel_path = os.path.relpath(root, folder_path)
                path_parts = rel_path.split(os.path.sep)
                
                # Add files to the appropriate level in the folder structure
                current_level = folder_structure
                
                # If we're not at the root level, navigate to the right folder
                if rel_path != '.':
                    for part in path_parts:
                        if part not in current_level:
                            current_level[part] = {}
                        current_level = current_level[part]
                
                # Add files at this level
                for file in video_files:
                    file_path = os.path.join(root, file)
                    all_files.append((file_path, file))
                    
                    # Add to structure
                    if '_files' not in current_level:
                        current_level['_files'] = []
                    current_level['_files'].append((file_path, file))
                    
                # Check if cancelled
                if hasattr(self, 'scan_cancelled') and self.scan_cancelled:
                    update_progress(1.0, "Cancelled")
                    GLib.idle_add(progress_dialog.destroy)
                    return
            
            # Sort files alphabetically
            all_files.sort(key=lambda x: x[1].lower())
            
            update_progress(0.2, f"Found {total_files} videos")
            
            # Build folder model on main thread - always use folder structure
            GLib.idle_add(self.build_folder_model, folder_structure, folder_path, total_files, progress_dialog, auto_play_last)
            
            return
        except Exception as e:
            print(f"Error scanning folder: {str(e)}")
            import traceback
            traceback.print_exc()
            
            # Show error in UI and make sure to reset loading flag
            def show_error():
                self.show_error_dialog("Error", f"Failed to scan folder: {str(e)}")
                if hasattr(progress_dialog, 'destroy'):
                    progress_dialog.destroy()
                self._loading_folder = False  # Reset loading flag on error
                return False
            
            GLib.idle_add(show_error)
            
            # Reset loading flag
            self._loading_folder = False
            return
        
    def build_folder_model(self, folder_structure, folder_path, total_files, progress_dialog, auto_play_last):
        """Build the folder-based model from scanned files."""
        try:
            print(f"Building folder model with {total_files} videos")
            
            # Check if we've been cancelled
            if hasattr(self, 'scan_cancelled') and self.scan_cancelled:
                progress_dialog.destroy()
                self._loading_folder = False
                return
                
            # Update progress dialog
            if progress_dialog and isinstance(progress_dialog, Gtk.Widget) and progress_dialog.get_visible():
                # For Adw.MessageDialog we can update the heading directly
                if hasattr(progress_dialog, 'set_heading'):
                    progress_dialog.set_heading(f"Building library for {total_files} videos...")
                
                # Update progress bar if it exists
                progress_bar = None
                if hasattr(progress_dialog, 'get_extra_child'):
                    extra_child = progress_dialog.get_extra_child()
                    if extra_child and isinstance(extra_child, Gtk.Box):
                        # Find progress bar inside the box
                        child = extra_child.get_first_child()
                        while child:
                            if isinstance(child, Gtk.ProgressBar):
                                progress_bar = child
                                break
                            child = child.get_next_sibling()
                
                if progress_bar:
                    progress_bar.set_fraction(0.5)
                    progress_bar.set_text("Building library view...")
            
            from .library import VideoItem
            
            # Create a new model for videos
            videos_model = Gio.ListStore.new(VideoItem)
            
            # Set window title
            folder_name = os.path.basename(folder_path)
            if folder_name:
                self.set_title(f"Localdemy - {folder_name}")
            else:
                self.set_title("Localdemy")
                
            # Always use folder view
            print(f"Building folder model with show_folders=True")
            
            # First add all folders in alphabetical order
            folder_names = sorted([k for k in folder_structure.keys() if k != '_files'])
            for folder_name in folder_names:
                subfolder = folder_structure[folder_name]
                video_count = len(subfolder.get('_files', [])) if '_files' in subfolder else 0
                
                # Create folder item
                folder_item = VideoItem(
                    f"folder_{folder_name}",
                    f"📁 {folder_name}",
                    f"{video_count} videos",
                    0,
                    0.0
                )
                folder_item.is_folder = True
                folder_item.folder_name = folder_name
                folder_item.indent_level = 0
                
                # Add to model
                videos_model.append(folder_item)
            
            # Then add root files if any exist
            if '_files' in folder_structure and folder_structure['_files']:
                root_files = sorted(folder_structure['_files'], key=lambda x: x[1].lower())
                
                # If we have folders, add a root files section
                if folder_names:
                    root_header = VideoItem(
                        "folder_root",
                        "📁 Root Files",
                        f"{len(root_files)} videos",
                        0,
                        0.0
                    )
                    root_header.is_folder = True
                    root_header.folder_name = "."  # Special marker for root
                    root_header.indent_level = 0
                    videos_model.append(root_header)
                
                # Add each root file
                for file_path, file_name in root_files:
                    file_title = os.path.splitext(file_name)[0]
                    
                    # Get progress
                    progress_percentage = 0.0
                    if file_path in self.progress_data:
                        progress_percentage = self.progress_data[file_path].get('percentage', 0.0)
                    
                    # Create video item
                    video_item = VideoItem(
                        f"video_{len(videos_model)}",
                        file_title,
                        "Root",
                        0,
                        progress_percentage,
                        file_path
                    )
                    # Set indent level
                    video_item.indent_level = 0
                    videos_model.append(video_item)
            
            # Set the model
            self.library_view.set_videos_model(videos_model)
            
            # Close progress dialog
            if progress_dialog and hasattr(progress_dialog, 'destroy'):
                progress_dialog.destroy()
            
            # Reset the loading flag
            self._loading_folder = False
            
            # Auto-play last video if requested and not in startup
            if auto_play_last and '_app_state' in self.progress_data and not hasattr(self, '_during_startup'):
                # Mark that we're setting up to avoid recursive loading
                self._during_startup = True
                
                last_video = self.progress_data['_app_state'].get('last_video')
                if last_video:
                    # Find the video in the model
                    for i in range(videos_model.get_n_items()):
                        item = videos_model.get_item(i)
                        if hasattr(item, 'file_path') and item.file_path == last_video:
                            # Set selection with a delay to prevent immediate loading issues
                            GLib.timeout_add(1000, self.delayed_select_video, i, item)
                            break
                    
                # Remove startup flag after delay
                GLib.timeout_add_seconds(5, self.clear_startup_flag)
                
        except Exception as e:
            print(f"Error building folder model: {str(e)}")
            import traceback
            traceback.print_exc()
            
            # Close progress dialog
            if progress_dialog and hasattr(progress_dialog, 'destroy'):
                progress_dialog.destroy()
        
        finally:
            # Clear loading flag
            self._loading_folder = False
        
        return False  # Don't repeat
    
    def clear_startup_flag(self):
        """Clear the startup flag after a delay."""
        if hasattr(self, '_during_startup'):
            delattr(self, '_during_startup')
        return False  # Don't repeat
    
    def delayed_select_video(self, index, item):
        """Select a video with a delay to prevent loading issues."""
        # Check if we're already in a selection process
        if hasattr(self, '_selecting_video') and self._selecting_video:
            return False
            
        # Select the item in the library view
        self.library_view.selection_model.set_selected(index)
        
        # Create video data
        video_data = {
            'path': item.file_path,
            'title': item.title,
            'duration': item.duration,
            'progress': item.progress
        }
        
        # Call video selected handler after a short delay
        GLib.timeout_add(500, self.emit_video_selected, video_data)
        return False  # Don't repeat
        
    def emit_video_selected(self, video_data):
        """Emit video selected signal with data."""
        self.on_video_selected(self.library_view, video_data)
        return False  # Don't repeat
    
    def scan_folder_direct(self, folder_path, progress_dialog, progress_bar, auto_play_last):
        """Scan folder directly without building hierarchical structure."""
        try:
            print(f"Scanning folder directly: {folder_path}")
            
            # Initialize scan cancelled flag
            self.scan_cancelled = False
            
            # Function to update progress from main thread
            def update_progress(fraction, text):
                def update_ui():
                    if progress_dialog and hasattr(progress_dialog, 'get_visible') and progress_dialog.get_visible():
                        progress_bar.set_fraction(fraction)
                        progress_bar.set_text(text)
                    return False
                GLib.idle_add(update_ui)
            
            # Find video files
            update_progress(0.0, "Finding video files...")
            all_files = []
            
            # Helper function to check if file is a video
            def is_video_file(filename):
                ext = os.path.splitext(filename)[1].lower()
                return ext in VIDEO_EXTENSIONS
            
            # Scan all files in folder
            total_files = 0
            for root, dirs, files in os.walk(folder_path):
                # Skip hidden directories
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                
                for file in files:
                    if self.scan_cancelled:
                        update_progress(1.0, "Cancelled")
                        GLib.idle_add(progress_dialog.destroy)
                        return
                        
                    if is_video_file(file):
                        file_path = os.path.join(root, file)
                        all_files.append((file_path, file))
                        total_files += 1
                        
                        # Update progress occasionally
                        if total_files % 10 == 0:
                            update_progress(0.3, f"Found {total_files} videos...")
            
            # Sort files by name
            all_files.sort(key=lambda x: x[1].lower())
            
            if not all_files:
                update_progress(1.0, "No videos found")
                GLib.idle_add(self.show_no_videos_dialog)
                GLib.idle_add(progress_dialog.destroy)
                return
            
            # Update progress
            update_progress(0.5, f"Processing {len(all_files)} videos...")
            
            # Build flat model on main thread
            GLib.idle_add(self.build_flat_model, all_files, progress_dialog, auto_play_last)
                
        except Exception as e:
            print(f"Error in direct scan: {str(e)}")
            import traceback
            traceback.print_exc()
            GLib.idle_add(progress_dialog.destroy)
    
    def on_video_selected(self, library_view, video_item):
        """Handle video selection in the library view."""
        # Extract the video path from the selected item
        video_path = video_item.get('path', '')
        if not video_path:
            print("No video path in the selected item")
            return
            
        # Prevent recursive selection handling
        if hasattr(self, '_selecting_video') and self._selecting_video:
            print("Already handling a video selection, ignoring")
            return
            
        self._selecting_video = True
        try:
            # Store the current video path for progress tracking
            self.current_video_path = video_path
            video_title = os.path.basename(video_path)
            
            print(f"Selected video: {video_title}")
            
            # Set window title to indicate the current video
            self.set_title(f"Localdemy - {video_title}")
            
            # Show back button when in video player
            self.back_button.set_visible(True)
            
            # Load and play the video
            self.content_stack.set_visible_child_name("player")
            if not self.video_player.load_video(video_path):
                print("Failed to load video")
                return
                
            # Check if we have progress for this video
            video_progress = self.get_video_progress(video_path)
            if video_progress and 'position' in video_progress:
                position = video_progress['position']
                try:
                    print(f"Resuming video at position {position} seconds")
                    # Wait a bit longer to ensure video is loaded before seeking
                    GLib.timeout_add(1500, lambda: self.seek_video(position))
                except Exception as e:
                    print(f"Error seeking to position: {str(e)}")
        finally:
            # Reset selection flag
            GLib.timeout_add(500, self.reset_selecting_video)
            
    def reset_selecting_video(self):
        """Reset the selecting video flag."""
        self._selecting_video = False
        return False  # Don't repeat

    def seek_video(self, position):
        """Seek to a specific position in the current video."""
        try:
            self.video_player.seek(position)
            return False  # Stop the timeout
        except Exception as e:
            print(f"Error seeking to position: {str(e)}")
            return False

    def on_back_to_library_clicked(self, button):
        """Go back to the welcome screen."""
        # Reset the window title
        self.set_title("Localdemy")
        
        # Hide the back button
        self.back_button.set_visible(False)
        
        # Show the welcome page
        self.content_stack.set_visible_child_name("welcome")
        
        # Save any pending progress data
        self._save_progress_without_reload()
        
        # Cancel any ongoing scan
        if hasattr(self, 'scan_cancelled'):
            self.scan_cancelled = True
        
        # Create an empty model (no videos)
        from .library import VideoItem
        empty_model = Gio.ListStore.new(VideoItem)
        self.library_view.set_videos_model(empty_model)

    def load_last_folder(self):
        """Load the last folder and video from saved progress data."""
        # Only run this once on startup
        if self._auto_loaded:
            return False
            
        self._auto_loaded = True
        
        try:
            if '_app_state' in self.progress_data:
                app_state = self.progress_data['_app_state']
                
                last_folder = app_state.get('last_folder', None)
                if last_folder and os.path.isdir(last_folder):
                    print(f"Loading last folder: {last_folder}")
                    
                    # Check if we should load the last video too
                    auto_play_last = 'last_video' in app_state
                    
                    # Define a function for delayed loading to prevent recursion
                    def delayed_startup_load():
                        if hasattr(self, '_loading_folder') and self._loading_folder:
                            print("Already loading a folder in startup, ignoring")
                            return False
                        # Use single-shot to load folder (will not repeat)
                        self.load_videos_from_folder(last_folder, auto_play_last)
                        return False  # Don't repeat
                    
                    # Use a delay to ensure UI is fully initialized
                    GLib.timeout_add(100, delayed_startup_load)
                    return False
        except Exception as e:
            print(f"Error loading last folder: {str(e)}")
            
        return False  # Never repeat

    def build_flat_model(self, all_files, progress_dialog, auto_play_last=False):
        """Build a flat model from all files."""
        try:
            print("NOTICE: Redirecting flat model to folder model")
            # Create a folder structure with all files at the root
            folder_structure = {'_files': sorted(all_files, key=lambda x: x[1].lower())}
            # Use folder model instead
            return self.build_folder_model(folder_structure, self.current_folder, len(all_files), progress_dialog, auto_play_last)
        except Exception as e:
            print(f"Error building flat model: {str(e)}")
            import traceback
            traceback.print_exc()
            
            if progress_dialog and hasattr(progress_dialog, 'destroy'):
                progress_dialog.destroy()
    
    def show_no_videos_dialog(self):
        """Show dialog when no videos are found."""
        dialog = Adw.MessageDialog.new(
            self,
            "No Videos Found",
            "No video files were found in the selected folder."
        )
        dialog.add_response("ok", "OK")
        dialog.present()

    def on_folder_selected(self, library_view, folder_data):
        """Handle folder selection in the library view."""
        folder_name = folder_data.get('folder_name', '')
        if not folder_name or not hasattr(self, 'current_folder'):
            return
        
        # Prevent recursive folder selection
        if hasattr(self, '_loading_folder') and self._loading_folder:
            print("Already loading a folder, ignoring folder selection")
            return
        
        # Set loading flag to prevent multiple selections
        self._loading_folder = True
        
        # Remove folder icon prefix if present
        if folder_name.startswith('📁 '):
            folder_name = folder_name[2:].strip()
        
        print(f"Selected folder: {folder_name}")
        
        # Special case for "Root Files" folder - just reload the current folder
        if folder_name == "Root Files" or folder_name == ".":
            print("Root files selected, showing files in current folder")
            self._loading_folder = False  # Reset flag here
            return
        
        # Build path for the selected folder
        selected_folder_path = os.path.join(self.current_folder, folder_name)
        
        # Debug logging to help diagnose the issue
        print(f"Current folder: {self.current_folder}")
        print(f"Selected folder path: {selected_folder_path}")
        print(f"Path exists: {os.path.exists(selected_folder_path)}")
        print(f"Is directory: {os.path.isdir(selected_folder_path) if os.path.exists(selected_folder_path) else 'N/A'}")
        
        if os.path.exists(selected_folder_path) and os.path.isdir(selected_folder_path):
            print(f"Navigating to folder: {selected_folder_path}")
            
            # Initialize navigation stack if it doesn't exist
            if not hasattr(self, 'folder_navigation_stack'):
                self.folder_navigation_stack = []
            
            # Add current folder to navigation stack before navigating
            self.folder_navigation_stack.append(self.current_folder)
            
            # Always enable the back button when navigating to a subfolder
            self.folder_back_button.set_visible(True)
            
            # Store the selected path for our delayed function to use
            self._pending_folder_path = selected_folder_path
            
            # Define a proper function instead of using lambda to prevent any recursion issues
            def delayed_load_folder():
                try:
                    # Use the stored path instead of relying on closure variable
                    if hasattr(self, '_pending_folder_path'):
                        path_to_load = self._pending_folder_path
                        # Clear the pending path
                        delattr(self, '_pending_folder_path')
                        
                        # Reset loading flag - CRITICAL FIX: Do this BEFORE loading the folder
                        self._loading_folder = False
                        
                        # Now load the folder
                        self.load_videos_from_folder(path_to_load)
                    else:
                        # Reset loading flag if no path is found
                        self._loading_folder = False
                    return False  # Don't repeat
                except Exception as e:
                    print(f"Error in delayed_load_folder: {e}")
                    import traceback
                    traceback.print_exc()
                    self._loading_folder = False
                    return False
                
            # Use a small delay before loading the folder to prevent UI issues
            GLib.timeout_add(100, delayed_load_folder)
        else:
            print(f"Folder not found: {selected_folder_path}")
            # Show error dialog
            self.show_error_dialog("Folder Not Found", f"The folder '{folder_name}' was not found.")
            # Reset loading flag
            self._loading_folder = False

    def on_folder_back_clicked(self, button):
        """Navigate back to the parent folder."""
        # Prevent recursive loading
        if hasattr(self, '_loading_folder') and self._loading_folder:
            print("Already loading a folder, ignoring back button")
            return

        # Set loading flag
        self._loading_folder = True
        
        target_folder = None
        
        # First try to use the navigation stack
        if hasattr(self, 'folder_navigation_stack') and self.folder_navigation_stack:
            # Get the parent folder from the navigation stack
            target_folder = self.folder_navigation_stack.pop()
            
            # Hide back button if we're at the root of the navigation stack
            if not self.folder_navigation_stack:
                # We'll check if we need to re-enable it after navigating
                pass
        else:
            # If no navigation stack, try to go to parent directory
            if hasattr(self, 'current_folder') and self.current_folder:
                parent_dir = os.path.dirname(self.current_folder)
                if parent_dir and parent_dir != self.current_folder:
                    # Load videos from the parent directory
                    target_folder = parent_dir
                else:
                    # We're at the root, hide the back button
                    self.folder_back_button.set_visible(False)
                    self._loading_folder = False
        
        # Update window title based on the current folder after navigation
        if target_folder:
            # Store the target for our delayed function
            self._pending_folder_path = target_folder
            
            # Define a proper function for delayed loading to prevent recursion
            def delayed_load_parent():
                try:
                    # Use the stored path
                    if hasattr(self, '_pending_folder_path'):
                        path_to_load = self._pending_folder_path
                        # Clear the pending path
                        delattr(self, '_pending_folder_path')
                        
                        # CRITICAL FIX: Reset loading flag BEFORE calling load_videos_from_folder
                        self._loading_folder = False
                        
                        # Now load the folder
                        self.load_videos_from_folder(path_to_load)
                    else:
                        # Reset loading flag if no path is found
                        self._loading_folder = False
                    return False  # Don't repeat
                except Exception as e:
                    print(f"Error in delayed_load_parent: {e}")
                    import traceback
                    traceback.print_exc()
                    self._loading_folder = False
                    return False
                
            # Delay the folder loading to prevent UI issues
            GLib.timeout_add(100, delayed_load_parent)
        else:
            # If we didn't find a target folder, reset the loading flag
            self._loading_folder = False

    def _add_subfolders_to_model(self, folder_structure, parent_folder_name, videos_model, level):
        """Recursively add subfolders to the model with proper indentation.
        
        Args:
            folder_structure: Dictionary containing folder structure
            parent_folder_name: Name of the parent folder
            videos_model: The model to add items to
            level: Current indentation level
        """
        # Skip if there are no subfolders
        if not isinstance(folder_structure, dict):
            return
            
        # Process each subfolder in alphabetical order
        subfolders = sorted([k for k in folder_structure.keys() if k != '_files'])
        for idx, folder_name in enumerate(subfolders):
            subfolder = folder_structure[folder_name]
            
            # Skip if not a dictionary (shouldn't happen but just in case)
            if not isinstance(subfolder, dict):
                continue
                
            # Create a folder header with indentation
            # Use folder icon with proper indentation
            folder_item = VideoItem(
                f"folder_{parent_folder_name}_{folder_name}",
                f"📁 {folder_name}",  # Add folder icon
                f"{len(subfolder.get('_files', []))} videos",
                0,
                0.0
            )
            folder_item.is_folder = True
            folder_item.folder_name = folder_name
            folder_item.indent_level = level  # Set proper indentation level
            
            # Add folder item to model
            videos_model.append(folder_item)
            
            # Add files in this subfolder
            if '_files' in subfolder:
                # Sort files alphabetically
                files = sorted(subfolder['_files'], key=lambda x: x[1].lower())
                for file_idx, (file_path, file_name) in enumerate(files):
                    # Get details
                    file_title = os.path.splitext(file_name)[0]
                    
                    # Get progress
                    progress_percentage = 0.0
                    if file_path in self.progress_data:
                        progress_percentage = self.progress_data[file_path].get('percentage', 0.0)
                    
                    # Determine tree symbol - use └─ for last item, ├─ for others
                    is_last_file = file_idx == len(files) - 1
                    has_subfolders = any(k != '_files' for k in subfolder.keys())
                    tree_symbol = "└─" if is_last_file and not has_subfolders else "├─"
                    
                    # Create video item
                    video_item = VideoItem(
                        f"video_{len(videos_model)}",
                        f"{tree_symbol} {file_title}",
                        f"{parent_folder_name}/{folder_name}",
                        0,
                        progress_percentage,
                        file_path
                    )
                    # Set indentation level for tree view
                    video_item.indent_level = level + 1
                    
                    # Add to model
                    videos_model.append(video_item)
            
            # Recursively process deeper subfolders
            self._add_subfolders_to_model(subfolder, f"{parent_folder_name}/{folder_name}", videos_model, level + 1) 