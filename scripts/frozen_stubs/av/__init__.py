"""Stand-in for PyAV in the frozen desktop engine.

faster-whisper imports `av` at module level but only uses it to decode files. PrePro decodes audio with
ffmpeg itself and hands Whisper a numpy array, so PyAV's bundled codec libraries (~126 MB) are dead weight in
the installer. Any real use fails loudly instead of silently.
"""

__version__ = "0.0-prepro-stub"


class error:  # noqa: N801 - mirrors the PyAV module layout
    class InvalidDataError(Exception):
        pass


def open(*_args, **_kwargs):  # noqa: A001
    raise RuntimeError("PyAV is not bundled in the PrePro desktop engine — pass decoded audio (numpy) to Whisper")
