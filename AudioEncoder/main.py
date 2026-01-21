"""AudioEncoder - LED brightness frame generator from audio input.

This is the main entrypoint for the AudioEncoder Flet desktop application.
"""

import flet as ft
from ui.app import AudioEncoderApp


def main(page: ft.Page):
    """Main application entry point."""
    page.title = "AudioEncoder"
    page.window.width = 900
    page.window.height = 700
    page.window.min_width = 800
    page.window.min_height = 600
    page.padding = 0
    page.theme_mode = ft.ThemeMode.DARK
    page.scroll = ft.ScrollMode.ALWAYS  # show scrollbar on long pages
    
    # Create and mount the app
    app = AudioEncoderApp(page)
    page.add(app.build())
    page.update()


if __name__ == "__main__":
    ft.run(main)
