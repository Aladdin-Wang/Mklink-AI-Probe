"""Internal subprocess entry contracts shared by CLI and frozen remote service."""
import sys


def dispatch_internal_process(arguments):
    """Return an exit code for an internal command, otherwise None."""
    values = list(arguments)
    if values == ['--internal-pack-worker']:
        from mklink.cmsis_dap.pack_worker import main
        return main()
    if values[:1] == ['--internal-process-guard']:
        from mklink.cmsis_dap.process_guard_exec import main
        previous = sys.argv
        try:
            sys.argv = [previous[0], *values[1:]]
            return main()
        finally:
            sys.argv = previous
    return None
