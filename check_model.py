"""Return 0 if the model is ready, 1 otherwise. Used by run.bat."""

import sys

from transcribe import model_is_ready

sys.exit(0 if model_is_ready() else 1)
