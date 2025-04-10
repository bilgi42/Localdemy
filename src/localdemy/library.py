"""
Library view component for displaying and managing video content.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, GLib, GdkPixbuf, Gio, GObject, Pango

class LibraryView(Gtk.Box):
    """Library view component for displaying videos."""
    
    __gsignals__ = {
        'video-selected': (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_PYOBJECT,)),
        'folder-selected': (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_PYOBJECT,)),
    }
    
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        
        self.show_folders = True  # Always show folders by default
        self._processing_selection = False  # Flag to prevent recursive selection events
        
        # Set up the container
        self.set_hexpand(True)
        self.set_vexpand(True)
        
        # Create the search entry
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("Search videos...")
        self.search_entry.connect("search-changed", self.on_search_changed)
        self.append(self.search_entry)
        
        # Create a scrolled window for the list
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        
        # Create the list view for videos
        self.create_list_view()
        scrolled.set_child(self.list_view)
        
        self.append(scrolled)
        
        # Create an empty model to start
        empty_model = Gio.ListStore.new(VideoItem)
        self.set_videos_model(empty_model)
    
    def create_list_view(self):
        """Create the list view component for videos."""
        # Create a signal list model
        self.videos_model = Gio.ListStore.new(VideoItem)
        
        # Create a selection model
        self.selection_model = Gtk.SingleSelection.new(self.videos_model)
        self.selection_model.connect("selection-changed", self.on_selection_changed)
        
        # Create factory for items
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_factory_setup)
        factory.connect("bind", self._on_factory_bind)
        
        # Create list view
        self.list_view = Gtk.ListView.new(self.selection_model, factory)
        self.list_view.add_css_class("navigation-sidebar")
    
    def _on_factory_setup(self, factory, list_item):
        """Set up the list item."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        
        # Add indent spacer for tree structure
        indent_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        indent_box.set_size_request(0, -1)  # Initial size, will be adjusted based on indent level
        box.append(indent_box)
        
        # Video info
        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        info_box.set_hexpand(True)
        
        title = Gtk.Label()
        title.set_halign(Gtk.Align.START)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        title.add_css_class("heading")
        
        details = Gtk.Label()
        details.set_halign(Gtk.Align.START)
        details.add_css_class("caption")
        details.set_opacity(0.7)
        
        progress_bar = Gtk.ProgressBar()
        progress_bar.set_show_text(False)
        progress_bar.set_margin_top(3)
        
        info_box.append(title)
        info_box.append(details)
        info_box.append(progress_bar)
        
        box.append(info_box)
        
        list_item.set_child(box)
        
        # Store widgets as properties
        list_item.title = title
        list_item.details = details
        list_item.progress_bar = progress_bar
        list_item.indent_box = indent_box
    
    def _on_factory_bind(self, factory, list_item):
        """Bind a VideoItem to the list item widget"""
        # Get the video item
        video_item = list_item.get_item()
        
        # Get the row from the list item
        row = list_item.get_child()
        
        # Apply indentation using the indent_box
        indent_box = row.get_first_child()
        indent_width = video_item.indent_level * 20  # 20 pixels per indent level
        indent_box.set_size_request(indent_width, -1)
        
        # Set the title
        title_label = indent_box.get_next_sibling().get_first_child()
        
        if video_item.is_folder:
            # Make folder names bold
            title_label.set_markup(f"<b>{video_item.title}</b>")
            # Add CSS class for folders
            row.add_css_class("folder-row")
        else:
            title_label.set_text(video_item.title)
            # Remove folder class if it was previously applied
            row.remove_css_class("folder-row")
        
        # Set the description
        description_label = title_label.get_next_sibling()
        description_label.set_text(video_item.details)
        
        # Show or hide the progress bar based on whether we're showing folders
        progress_bar = description_label.get_next_sibling()
        progress_bar.set_visible(not video_item.is_folder)
        
        # Set the progress
        progress_bar.set_fraction(video_item.progress)
    
    def set_show_folders(self, show_folders):
        """Set whether to show folder structure."""
        print(f"Library view setting show_folders to: {show_folders}")
        # Always use True for showing folders
        self.show_folders = True
        
        # Don't trigger a refresh if we're already set to show folders
        # This prevents recursion issues
        if self.videos_model and self.videos_model.get_n_items() > 0:
            # Get the root window to access current folder
            root = self.get_root()
            if root and hasattr(root, 'current_folder') and root.current_folder:
                # We no longer try to reload the folder when show_folders is False
                # This prevents the recursion problem
                pass
    
    def refresh_view(self):
        """Refresh the view based on current settings."""
        # Get the current window to access folder loading methods
        window = self.get_root()
        if window and hasattr(window, 'current_folder') and window.current_folder:
            # Check if we're in the middle of saving progress
            # This prevents recursive operations
            if hasattr(window, '_in_progress_save') and window._in_progress_save:
                print("Currently saving progress, ignoring view refresh")
                return False
                
            # Check if we're already loading a folder
            if hasattr(window, '_loading_folder') and window._loading_folder:
                print("Already loading a folder, ignoring view refresh")
                return False
                
            # Re-load the current folder with the current folder view setting
            window.load_videos_from_folder(window.current_folder)
            return True
        return False
    
    def set_videos_model(self, model):
        """Set the videos model."""
        self.videos_model = model
        self.selection_model.set_model(model)
    
    def connect_video_selected_handler(self, handler):
        """Connect a handler for video selection."""
        # First disconnect any existing handlers
        handlers = self.get_signal_handlers("video-selected")
        for handler_id in handlers:
            self.disconnect(handler_id)
        
        # Connect the new handler
        self.connect("video-selected", handler)
    
    def connect_folder_selected_handler(self, handler):
        """Connect a handler for folder selection."""
        # First disconnect any existing handlers
        handlers = self.get_signal_handlers("folder-selected")
        for handler_id in handlers:
            self.disconnect(handler_id)
        
        # Connect the new handler
        self.connect("folder-selected", handler)
    
    def get_signal_handlers(self, signal_name):
        """Get list of handler IDs for a given signal."""
        return [id for id in range(1, 100) if 
                GObject.signal_handler_is_connected(self, id) and 
                GObject.signal_query(id).signal_name == signal_name]
    
    def on_search_changed(self, entry):
        """Handle search entry changes."""
        search_text = entry.get_text().lower()
        
        # If search is empty, show all videos
        if not search_text:
            return
            
        # Search for matching videos
        # This only applies filtering for display, not actually changing the model
        for i in range(self.videos_model.get_n_items()):
            item = self.videos_model.get_item(i)
            if search_text in item.title.lower():
                # Make the matching item visible
                self.list_view.scroll_to(i, Gtk.ListScrollFlags.SELECT, None)
                break
            
    def on_selection_changed(self, selection_model, position, n_items):
        """Handle selection changes in the list view."""
        if position == Gtk.INVALID_LIST_POSITION:
            return
            
        # Prevent recursive selection handling
        if self._processing_selection:
            return
            
        self._processing_selection = True
        try:
            selected = selection_model.get_selected_item()
            if selected:
                # Don't emit signal for folder items
                if hasattr(selected, 'is_folder') and selected.is_folder:
                    # Get the folder name without icon prefix
                    folder_name = selected.title
                    if folder_name.startswith('📁 '):
                        folder_name = folder_name[2:].strip()
                    
                    print(f"Selected folder: {folder_name}")
                    
                    # Emit folder-selected signal
                    self.emit('folder-selected', {
                        'folder_name': folder_name
                    })
                    return
                    
                # Emit signal to notify parent that a video was selected
                self.emit('video-selected', {
                    'path': getattr(selected, 'file_path', ''),
                    'title': selected.title,
                    'duration': selected.duration,
                    'progress': selected.progress
                })
                print(f"Selected video: {selected.title}")
        finally:
            self._processing_selection = False
    
    def update_video_progress(self, video_path, progress_percentage):
        """Update the progress display for a video item in the list."""
        # Find the video item in the model and update its progress
        for i in range(self.videos_model.get_n_items()):
            item = self.videos_model.get_item(i)
            if hasattr(item, 'file_path') and item.file_path == video_path:
                item.progress = progress_percentage
                # Force update of the view
                self.list_view.queue_draw()
                return True
        return False
        
    def clear(self):
        """Clear the library view contents."""
        empty_model = Gio.ListStore.new(VideoItem)
        self.set_videos_model(empty_model)

class VideoItem(GObject.Object):
    """Video item model class."""
    
    def __init__(self, video_id, title, details, duration, progress=0.0, file_path=''):
        super().__init__()
        
        self.video_id = video_id
        self.title = title
        self.details = details
        self.duration = duration
        self.progress = progress  # 0.0 to 1.0
        self.is_folder = False    # Flag to indicate if this is a folder item
        self.file_path = file_path  # Store the actual file path for the video
        self.indent_level = 0     # Indentation level for tree view 