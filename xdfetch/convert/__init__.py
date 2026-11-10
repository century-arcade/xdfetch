"""Converters: one per format, chosen by sniffing the bytes, never by file extension.

A converter takes the bytes an outlet served and builds a Puzzle. Whatever the source has
that .xd can't carry is listed on the Puzzle, not dropped silently.
"""
