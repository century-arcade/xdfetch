"""Adapters: one per transport (a plain URL, an embed's API, ...).

An adapter answers two questions for an outlet and a date: where is the file, and what
did the host send. It returns the bytes as served; it never converts.
"""
