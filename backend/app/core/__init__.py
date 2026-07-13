"""App-wide framework machinery: settings, logging config, exception
handling, auth dependency. Anything wired directly onto the FastAPI
`app` object and used by every request, regardless of domain.
"""
