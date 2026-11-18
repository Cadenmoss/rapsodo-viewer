"""Adapter contract.

Everything that can put shots into the database implements this. The live
Rapsodo adapter is deliberately NOT written yet: the device's wire format is
undecoded, and inventing a parser would produce numbers that look real and
aren't. See adapters/rapsodo_live.py.
"""
import abc


class ShotSource(abc.ABC):
    name = "abstract"

    @abc.abstractmethod
    def connect(self):
        """Raise with a clear message if the source is unreachable."""

    @abc.abstractmethod
    def shots(self):
        """Yield dicts keyed by store.FIELDS. May block between yields."""

    def close(self):
        pass
