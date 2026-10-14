"""Input limits shared by the web API and command-line interface."""

ALLOWED_EXTENSIONS = {
    ".mp3", ".mp4", ".m4a", ".mov", ".mpeg", ".mpga",
    ".wav", ".webm", ".mkv", ".aac", ".flac", ".ogg",
}
SPEED_OPTIONS = (1.0, 1.25, 1.5, 1.75, 2.0)
MAX_CONTEXT_CHARS = 4000
