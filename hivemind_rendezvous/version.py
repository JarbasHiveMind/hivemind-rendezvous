"""Version information for hivemind-rendezvous."""
# START_VERSION_BLOCK
VERSION_MAJOR = 0
VERSION_MINOR = 1
VERSION_BUILD = 1
VERSION_ALPHA = 2
# END_VERSION_BLOCK


__version__ = (
    f"{VERSION_MAJOR}.{VERSION_MINOR}.{VERSION_BUILD}"
    + (f"a{VERSION_ALPHA}" if VERSION_ALPHA else "")
)

# Backwards-compatible alias for callers importing the old constant.
VERSION = __version__
