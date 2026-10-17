"""
crash.py - the Crash Simulator.

A real crash (power cut, kill -9) cannot be repeated on demand, so VFSafe
pretends. The file manager calls `crash.checkpoint("some_point")` at carefully
chosen places. If the simulator was *armed* for that point, it raises
SimulatedCrash and the program "dies" right there - leaving the disk exactly
as it was at that moment.

                 operation timeline (what the file manager does)
  ------------------------------------------------------------------------
   before_journal -> [write BEGIN to journal] -> after_journal
   -> [apply step 1: data file] -> during_apply -> [apply step 2: metadata]
   -> after_apply -> [write COMMIT to journal] -> after_commit
  ------------------------------------------------------------------------
   during_journal  = the BEGIN record is only HALF written (torn write)
   during_recovery = the recovery itself crashes (used by tests only)
"""

from errors import SimulatedCrash

# point name -> plain-English description (also used by the CLI help)
CRASH_POINTS = {
    "before_journal": "crash before anything is logged (operation never started)",
    "during_journal": "crash while the BEGIN record is half written (torn journal record)",
    "after_journal": "crash after BEGIN is logged but before any change is applied",
    "during_apply": "crash in the middle of applying (data changed, metadata not yet)",
    "after_apply": "crash after the change is applied but before COMMIT is written",
    "after_commit": "crash after COMMIT is written (operation fully done)",
    "during_recovery": "crash inside recovery, before it writes COMMIT (tests only)",
}

# The points that make sense for a normal user command.
OPERATION_CRASH_POINTS = [
    "before_journal",
    "during_journal",
    "after_journal",
    "during_apply",
    "after_apply",
    "after_commit",
]


class CrashSimulator:
    """Holds at most one 'armed' crash point; fires once, then disarms."""

    def __init__(self):
        self.armed = None

    def arm(self, point):
        if point not in CRASH_POINTS:
            raise ValueError(
                "Unknown crash point '%s'. Choose one of: %s"
                % (point, ", ".join(CRASH_POINTS))
            )
        self.armed = point

    def disarm(self):
        self.armed = None

    def is_armed(self, point):
        return self.armed == point

    def checkpoint(self, point):
        """Called by the program. Raises SimulatedCrash if armed for `point`."""
        if self.armed == point:
            self.armed = None  # a crash happens only once
            raise SimulatedCrash(point)
