"""
Database module for Localdemy, handling SQLite storage and retrieval.
"""

import os
import sqlite3
import time
from pathlib import Path
from gi.repository import GLib

from .library import VideoItem


class Database:
    """Database handler for Localdemy application."""
    
    def __init__(self):
        # Get application data directory
        data_dir = os.path.join(GLib.get_user_data_dir(), "localdemy")
        os.makedirs(data_dir, exist_ok=True)
        
        # Set up database path
        self.db_path = os.path.join(data_dir, "localdemy.db")
        
        # Initialize database
        self.initialize_db()
    
    def initialize_db(self):
        """Initialize the database and create tables if they don't exist."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Create videos table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            duration INTEGER NOT NULL,
            added_date INTEGER NOT NULL,
            last_watched INTEGER,
            metadata TEXT
        )
        ''')
        
        # Create progress table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id INTEGER NOT NULL,
            position INTEGER NOT NULL,
            last_updated INTEGER NOT NULL,
            FOREIGN KEY (video_id) REFERENCES videos(id)
        )
        ''')
        
        # Create bookmarks table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS bookmarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id INTEGER NOT NULL,
            position INTEGER NOT NULL,
            title TEXT,
            notes TEXT,
            created_at INTEGER NOT NULL,
            FOREIGN KEY (video_id) REFERENCES videos(id)
        )
        ''')
        
        # Create courses table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            created_at INTEGER NOT NULL
        )
        ''')
        
        # Create course_videos table (many-to-many relationship)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS course_videos (
            course_id INTEGER NOT NULL,
            video_id INTEGER NOT NULL,
            position INTEGER NOT NULL,
            PRIMARY KEY (course_id, video_id),
            FOREIGN KEY (course_id) REFERENCES courses(id),
            FOREIGN KEY (video_id) REFERENCES videos(id)
        )
        ''')
        
        conn.commit()
        conn.close()
    
    def get_connection(self):
        """Get a database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Access columns by name
        return conn
    
    def add_video(self, path, title, description, duration, metadata=None):
        """Add a video to the database or update if it already exists."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        now = int(time.time())
        
        # Check if the video already exists
        cursor.execute('SELECT id FROM videos WHERE path = ?', (path,))
        existing_video = cursor.fetchone()
        
        if existing_video:
            # Update the existing video record
            video_id = existing_video['id']
            cursor.execute('''
            UPDATE videos 
            SET title = ?, description = ?, duration = ?, metadata = ?
            WHERE id = ?
            ''', (title, description, duration, metadata, video_id))
            print(f"Updated existing video: {title}")
        else:
            # Insert new video record
            cursor.execute('''
            INSERT INTO videos (path, title, description, duration, added_date, metadata)
            VALUES (?, ?, ?, ?, ?, ?)
            ''', (path, title, description, duration, now, metadata))
            video_id = cursor.lastrowid
            print(f"Added new video: {title}")
        
        conn.commit()
        conn.close()
        
        return video_id
    
    def update_video(self, video_id, title=None, description=None):
        """Update video metadata."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        updates = []
        params = []
        
        if title is not None:
            updates.append("title = ?")
            params.append(title)
        
        if description is not None:
            updates.append("description = ?")
            params.append(description)
        
        if updates:
            query = f"UPDATE videos SET {', '.join(updates)} WHERE id = ?"
            params.append(video_id)
            
            cursor.execute(query, params)
            conn.commit()
        
        conn.close()
    
    def update_progress(self, video_id, position):
        """Update or create a progress entry for a video."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        now = int(time.time())
        
        # Check if progress entry exists
        cursor.execute("SELECT id FROM progress WHERE video_id = ?", (video_id,))
        result = cursor.fetchone()
        
        if result:
            # Update existing record
            cursor.execute('''
            UPDATE progress
            SET position = ?, last_updated = ?
            WHERE video_id = ?
            ''', (position, now, video_id))
        else:
            # Create new record
            cursor.execute('''
            INSERT INTO progress (video_id, position, last_updated)
            VALUES (?, ?, ?)
            ''', (video_id, position, now))
        
        # Also update the last_watched time in videos table
        cursor.execute('''
        UPDATE videos
        SET last_watched = ?
        WHERE id = ?
        ''', (now, video_id))
        
        conn.commit()
        conn.close()
    
    def get_progress(self, video_id):
        """Get the progress position for a video."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
        SELECT position, last_updated
        FROM progress
        WHERE video_id = ?
        ''', (video_id,))
        
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return {
                'position': result['position'],
                'last_updated': result['last_updated']
            }
        return None
    
    def get_progress_percentage(self, video_id):
        """Get the progress percentage for a video."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
        SELECT p.position, v.duration
        FROM progress p
        JOIN videos v ON p.video_id = v.id
        WHERE p.video_id = ?
        ''', (video_id,))
        
        result = cursor.fetchone()
        conn.close()
        
        if result and result['duration'] > 0:
            return result['position'] / result['duration']
        return 0.0
    
    def add_bookmark(self, video_id, position, title=None, notes=None):
        """Add a bookmark for a video."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        now = int(time.time())
        
        cursor.execute('''
        INSERT INTO bookmarks (video_id, position, title, notes, created_at)
        VALUES (?, ?, ?, ?, ?)
        ''', (video_id, position, title, notes, now))
        
        bookmark_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return bookmark_id
    
    def get_bookmarks(self, video_id):
        """Get all bookmarks for a video."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
        SELECT id, position, title, notes, created_at
        FROM bookmarks
        WHERE video_id = ?
        ORDER BY position
        ''', (video_id,))
        
        results = cursor.fetchall()
        conn.close()
        
        bookmarks = []
        for row in results:
            bookmarks.append({
                'id': row['id'],
                'position': row['position'],
                'title': row['title'],
                'notes': row['notes'],
                'created_at': row['created_at']
            })
        
        return bookmarks
    
    def get_videos(self, limit=None, order_by="title"):
        """Get videos from the database."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        query = f'''
        SELECT v.id, v.path, v.title, v.description, v.duration, 
               v.added_date, v.last_watched,
               p.position
        FROM videos v
        LEFT JOIN progress p ON v.id = p.video_id
        ORDER BY {order_by}
        '''
        
        if limit:
            query += f" LIMIT {limit}"
        
        cursor.execute(query)
        results = cursor.fetchall()
        conn.close()
        
        videos = []
        for row in results:
            # Calculate progress percentage
            progress = 0.0
            if row['position'] and row['duration'] > 0:
                progress = min(1.0, row['position'] / row['duration'])
            
            # Format details text
            details = self._format_duration(row['duration'])
            if row['last_watched']:
                last_watched = time.strftime('%Y-%m-%d', time.localtime(row['last_watched']))
                details += f" • Last watched: {last_watched}"
            
            video_item = VideoItem(
                video_id=row['id'],
                title=row['title'],
                details=details,
                duration=row['duration'],
                progress=progress
            )
            # Store the description field separately for folder view
            video_item.details = details
            video_item.description = row['description']
            videos.append(video_item)
        
        return videos
    
    def get_video_path(self, video_id):
        """Get the file path for a video."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT path FROM videos WHERE id = ?", (video_id,))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return result['path']
        return None
    
    def search_videos(self, query):
        """Search for videos matching the query."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        search_term = f"%{query}%"
        cursor.execute('''
        SELECT id, path, title, description, duration, thumbnail_path
        FROM videos
        WHERE title LIKE ? OR description LIKE ?
        ORDER BY last_watched DESC
        ''', (search_term, search_term))
        
        results = cursor.fetchall()
        conn.close()
        
        videos = []
        for row in results:
            progress = self.get_progress_percentage(row['id'])
            details = self._format_duration(row['duration'])
            
            video_item = VideoItem(
                video_id=row['id'],
                title=row['title'],
                details=details,
                duration=row['duration'],
                thumbnail_path=row['thumbnail_path'],
                progress=progress
            )
            videos.append(video_item)
        
        return videos
    
    def delete_video(self, video_id):
        """Delete a video and its associated data from the database."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            # Start a transaction
            cursor.execute("BEGIN TRANSACTION")
            
            # Delete from progress table
            cursor.execute("DELETE FROM progress WHERE video_id = ?", (video_id,))
            
            # Delete from bookmarks table
            cursor.execute("DELETE FROM bookmarks WHERE video_id = ?", (video_id,))
            
            # Delete from course_videos table
            cursor.execute("DELETE FROM course_videos WHERE video_id = ?", (video_id,))
            
            # Get thumbnail path for deletion
            cursor.execute("SELECT thumbnail_path FROM videos WHERE id = ?", (video_id,))
            result = cursor.fetchone()
            thumbnail_path = result['thumbnail_path'] if result else None
            
            # Delete from videos table
            cursor.execute("DELETE FROM videos WHERE id = ?", (video_id,))
            
            # Commit the transaction
            conn.commit()
            
            # Delete thumbnail file if it exists
            if thumbnail_path and os.path.exists(thumbnail_path):
                os.remove(thumbnail_path)
                
            return True
        except Exception as e:
            print(f"Error deleting video: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()
    
    def _format_duration(self, seconds):
        """Format duration in seconds to a human-readable string."""
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        
        if hours > 0:
            return f"{hours}h {minutes}m"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"
    
    def get_last_watched_video(self):
        """Get the most recently watched video."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        query = '''
        SELECT v.id, v.path, v.title, v.description, v.duration, 
               v.added_date, v.last_watched,
               p.position
        FROM videos v
        LEFT JOIN progress p ON v.id = p.video_id
        WHERE v.last_watched IS NOT NULL
        ORDER BY v.last_watched DESC
        LIMIT 1
        '''
        
        cursor.execute(query)
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
            
        # Calculate progress percentage
        progress = 0.0
        if row['position'] and row['duration'] > 0:
            progress = min(1.0, row['position'] / row['duration'])
        
        # Format details text
        details = self._format_duration(row['duration'])
        if row['last_watched']:
            last_watched = time.strftime('%Y-%m-%d', time.localtime(row['last_watched']))
            details += f" • Last watched: {last_watched}"
        
        video_item = VideoItem(
            video_id=row['id'],
            title=row['title'],
            details=details,
            duration=row['duration'],
            progress=progress
        )
        # Store the description field separately for folder view
        video_item.details = details
        video_item.description = row['description']
        
        return video_item 