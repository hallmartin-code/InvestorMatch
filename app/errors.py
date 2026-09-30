"""User-facing error types. Messages are written to be shown directly in the UI."""


class InvestorMatchError(Exception):
    """Base class for expected, explainable failures."""


class IngestError(InvestorMatchError):
    """A file could not be read."""


class UnsupportedFormatError(IngestError):
    """The file type is not supported (or needs a converter that is not installed)."""


class MappingError(InvestorMatchError):
    """Column mapping is missing a required field."""


class LLMUnavailableError(InvestorMatchError):
    """Model-assisted extraction is disabled or failed."""


class ExportUnavailableError(InvestorMatchError):
    """An optional export target (e.g. Google Sheets) is not configured."""
