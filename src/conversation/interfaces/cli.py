"""Rich-powered CLI interface for CBC Part 5.

Interactive terminal interface for the conversational eligibility checker.
Uses the ``rich`` library for panels, tables, colored output, and Unicode
(Devanagari) support.

Usage::

    python -m src.conversation.interfaces.cli
    # or
    from src.conversation.interfaces.cli import CLIInterface
    asyncio.run(CLIInterface(Path("parsed_schemes")).run())
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme

from src.conversation.config import DEFAULT_LANGUAGE, DEFAULT_RULE_BASE_PATH
from src.conversation.engine import ConversationEngine, ConversationResponse
from src.conversation.presentation import render_summary, render_scheme_detail

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

CBC_THEME = Theme({
    "info": "cyan",
    "success": "bold green",
    "warning": "bold yellow",
    "error": "bold red",
    "user": "bold white",
    "system": "bright_cyan",
    "header": "bold magenta",
    "muted": "dim",
})


# ---------------------------------------------------------------------------
# CLI Interface
# ---------------------------------------------------------------------------


class CLIInterface:
    """Rich-powered interactive CLI for the conversation engine.

    Args:
        rule_base_path: Path to the rule base directory.
        language: Initial language (``"en"`` or ``"hi"``).
    """

    def __init__(
        self,
        rule_base_path: Path = DEFAULT_RULE_BASE_PATH,
        language: str = DEFAULT_LANGUAGE,
    ) -> None:
        self.rule_base_path = rule_base_path
        self.language = language
        self.console = Console(theme=CBC_THEME)
        self.engine = ConversationEngine(
            rule_base_path=rule_base_path,
            llm_provider="gemini",
        )
        self._session_token: str = ""

    async def run(self) -> None:
        """Run the interactive CLI conversation loop."""
        self._print_banner()

        # Start session
        response = await self.engine.start_session(language=self.language)
        self._session_token = response.session_token
        self._print_response(response)

        # Main loop
        while True:
            try:
                user_input = self._get_input()
            except (EOFError, KeyboardInterrupt):
                self.console.print("\n[muted]Session ended.[/muted]")
                break

            if not user_input:
                continue

            # Process message
            try:
                response = await self.engine.process_message(
                    session_token=self._session_token,
                    user_message=user_input,
                )
                self._session_token = response.session_token
                self._print_response(response)

                # Check if session ended
                if response.state_after == "ENDED":
                    break

            except Exception as exc:
                self.console.print(
                    f"[error]Error: {exc}[/error]"
                )
                logger.exception("CLI processing error")

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------

    def _print_banner(self) -> None:
        """Print the welcome banner."""
        banner = Text()
        banner.append("╔══════════════════════════════════════════╗\n", style="header")
        banner.append("║   ", style="header")
        banner.append("CBC Scheme Eligibility Checker", style="bold white")
        banner.append("      ║\n", style="header")
        banner.append("║   ", style="header")
        banner.append("Part 5: Conversational Interface", style="muted")
        banner.append("    ║\n", style="header")
        banner.append("╚══════════════════════════════════════════╝", style="header")
        self.console.print(banner)
        self.console.print()

    def _print_response(self, response: ConversationResponse) -> None:
        """Print a system response with appropriate formatting."""
        text = response.text

        # Detect if this contains matching results
        if response.matching_triggered and response.state_after in (
            "PRESENTING", "EXPLORING"
        ):
            self.console.print(
                Panel(
                    text,
                    title="[success]Eligibility Results[/success]",
                    border_style="green",
                    padding=(1, 2),
                )
            )
        elif response.state_after == "ENDED":
            self.console.print(
                Panel(
                    text,
                    title="[info]Session Complete[/info]",
                    border_style="cyan",
                    padding=(1, 2),
                )
            )
        else:
            # Regular conversational response
            self.console.print()
            self.console.print(
                Panel(
                    text,
                    title="[system]CBC Assistant[/system]",
                    border_style="bright_cyan",
                    padding=(0, 1),
                )
            )

        # Show extraction summary if present
        if response.extractions:
            self._print_extractions(response.extractions)

        self.console.print()

    def _print_extractions(self, extractions: list[dict]) -> None:
        """Show extracted fields as a compact list."""
        if not extractions:
            return

        from rich.table import Table

        table = Table(
            title="Extracted Fields",
            show_header=True,
            header_style="bold",
            border_style="dim",
            pad_edge=False,
        )
        table.add_column("Field", style="cyan")
        table.add_column("Value", style="white")
        table.add_column("Confidence", justify="center")

        for ext in extractions:
            conf = ext.get("confidence", "")
            conf_style = {
                "HIGH": "[green]HIGH[/green]",
                "MEDIUM": "[yellow]MEDIUM[/yellow]",
                "LOW": "[red]LOW[/red]",
            }.get(conf, conf)

            table.add_row(
                ext.get("field_path", ""),
                str(ext.get("value", "")),
                conf_style,
            )

        self.console.print(table)

    def _get_input(self) -> str:
        """Get user input with a styled prompt."""
        try:
            self.console.print("[user]You:[/user] ", end="")
            return input().strip()
        except EOFError:
            raise

    # ------------------------------------------------------------------
    # Result rendering (uses presentation module)
    # ------------------------------------------------------------------

    def render_results(self, result: dict) -> None:
        """Render matching results using the presentation module."""
        text = render_summary(result, self.language)
        self.console.print(
            Panel(
                text,
                title="[success]Eligibility Results[/success]",
                border_style="green",
                padding=(1, 2),
            )
        )

    def render_scheme_details(self, scheme: dict) -> None:
        """Render detailed scheme breakdown."""
        text = render_scheme_detail(scheme, self.language)
        self.console.print(
            Panel(
                text,
                title=f"[info]{scheme.get('name', 'Scheme Details')}[/info]",
                border_style="cyan",
                padding=(1, 2),
            )
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="CBC Scheme Eligibility Checker — Conversational Interface"
    )
    parser.add_argument(
        "--rule-base",
        type=Path,
        default=DEFAULT_RULE_BASE_PATH,
        help="Path to parsed scheme rule base",
    )
    parser.add_argument(
        "--language",
        choices=["en", "hi"],
        default=DEFAULT_LANGUAGE,
        help="Initial language (default: en)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)

    cli = CLIInterface(
        rule_base_path=args.rule_base,
        language=args.language,
    )
    asyncio.run(cli.run())


if __name__ == "__main__":
    main()
