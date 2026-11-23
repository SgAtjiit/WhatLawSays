import io
import logging
import sys
from typing import Any, Optional

RESET = "\033[0m"
BOLD = "\033[1m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
MAGENTA = "\033[35m"
BLUE = "\033[34m"


class PipelineLogger:

    def __init__(self, name: str = "WhatLawSays"):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)

        if not self.logger.handlers:
            # Reconfigure stdout stream encoding for Windows CP1252 compatibility
            stream = sys.stdout
            if hasattr(sys.stdout, "reconfigure"):
                try:
                    sys.stdout.reconfigure(errors="replace")
                except Exception:
                    pass

            handler = logging.StreamHandler(stream)
            formatter = logging.Formatter(
                "[%(asctime)s] %(message)s", datefmt="%H:%M:%S"
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

    def log_step(
        self,
        stage: str,
        message: str,
        details: Optional[Any] = None,
        status: str = "SUCCESS",
    ):
        """
        Logs a pipeline step with clear stage indicator, scenario flow, and status.
        Example: [API GATEWAY] Request received -> Next: Task Queue | Status: [SUCCESS]
        """
        if status == "SUCCESS":
            status_str = f"{GREEN}[SUCCESS]{RESET}"
        elif status == "WARNING" or status == "RETRY":
            status_str = f"{YELLOW}[{status}]{RESET}"
        elif status == "EARLY_EXIT":
            status_str = f"{MAGENTA}[EARLY EXIT]{RESET}"
        else:
            status_str = f"{RED}[FAILED]{RESET}"

        header = f"{BOLD}{CYAN}[{stage}]{RESET}"
        msg = f"{header} {message} | Status: {status_str}"

        self.logger.info(msg)
        if details is not None:
            if isinstance(details, (dict, list)):
                import json

                try:
                    formatted_details = json.dumps(details, indent=2, default=str)
                    for line in formatted_details.splitlines():
                        self.logger.info(f"   {BLUE}|{RESET} {line}")
                except Exception:
                    self.logger.info(f"   {BLUE}|{RESET} {details}")
            else:
                self.logger.info(f"   {BLUE}|{RESET} {details}")


pipeline_logger = PipelineLogger()
