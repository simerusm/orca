import subprocess
import logging

logger = logging.getLogger(__name__)

def run_command(command, cwd=None):
    """Run a shell command and return output"""
    logger.info(f"Running: {command}")
    result = subprocess.run(
        command,
        shell=True,
        check=True,
        text=True,
        capture_output=True,
        cwd=cwd
    )
    return result.stdout.strip()