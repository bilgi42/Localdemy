#!/usr/bin/env python3
"""
Main application entry point for Localdemy.
"""

import sys
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Gio, Adw, GLib

from .window import LocaldemyWindow


class LocaldemyApplication(Adw.Application):
    """Main application class for Localdemy."""

    def __init__(self):
        super().__init__(application_id="org.localdemy.app",
                         flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.connect("activate", self.on_activate)
        
    def on_activate(self, app):
        """Called when the application is activated."""
        win = self.props.active_window
        if not win:
            win = LocaldemyWindow(application=self)
        win.present()


def main():
    """Run the application."""
    app = LocaldemyApplication()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main()) 