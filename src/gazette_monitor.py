"""Gazette monitor for CBC Part 1 — polls eGazette RSS/Atom feeds and triggers re-parses.

Why: Government welfare scheme notifications are published as gazette notifications.
When a notification amends eligibility criteria, any rules extracted from the
previous notification become stale. This module polls the feeds and queues
re-parse jobs so the eligibility engine stays current.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List
from xml.etree import ElementTree

import httpx

from src.exceptions import GazetteMonitorError


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class GazetteUpdate:
    """A new or updated gazette notification that affects a tracked scheme."""

    gazette_ref: str
    scheme_id: str
    notification_date: str
    summary: str
    feed_url: str


@dataclass
class ParseJob:
    """A queued re-parse job for a scheme whose source has changed."""

    job_id: str
    scheme_id: str
    queued_at: str  # ISO 8601 timestamp
    trigger_source: str  # "gazette_monitor" | "manual"


# ---------------------------------------------------------------------------
# Feed parsing helpers
# ---------------------------------------------------------------------------


def _parse_feed_entries(
    xml_text: str, feed_url: str, scheme_ids: list[str]
) -> list[GazetteUpdate]:
    """Parse RSS/Atom XML and return entries matching any of the tracked scheme_ids.

    Both RSS (channel/item) and Atom (feed/entry) formats are supported.

    Why: eGazette.gov.in publishes both RSS and Atom feeds. We must handle both
    without requiring the caller to specify the format.
    """
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        raise GazetteMonitorError(f"Failed to parse feed XML from {feed_url}: {exc}") from exc

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    updates: list[GazetteUpdate] = []

    # Atom feed
    atom_entries = root.findall("atom:entry", ns) or root.findall("entry", ns)
    if atom_entries:
        for entry in atom_entries:
            title_el = entry.find("atom:title", ns) or entry.find("title")
            title = title_el.text or "" if title_el is not None else ""
            summary_el = entry.find("atom:summary", ns) or entry.find("summary")
            summary = summary_el.text or "" if summary_el is not None else title
            date_el = (
                entry.find("atom:updated", ns)
                or entry.find("atom:published", ns)
                or entry.find("updated")
                or entry.find("published")
            )
            notification_date = (date_el.text or "")[:10] if date_el is not None else ""
            id_el = entry.find("atom:id", ns) or entry.find("id")
            gazette_ref = id_el.text or "" if id_el is not None else title

            for scheme_id in scheme_ids:
                if scheme_id.lower() in title.lower() or scheme_id.lower() in summary.lower():
                    updates.append(
                        GazetteUpdate(
                            gazette_ref=gazette_ref,
                            scheme_id=scheme_id,
                            notification_date=notification_date,
                            summary=summary,
                            feed_url=feed_url,
                        )
                    )
        return updates

    # RSS feed
    channel = root.find("channel")
    items = channel.findall("item") if channel is not None else root.findall("item")
    for item in items:
        title_el = item.find("title")
        title = title_el.text or "" if title_el is not None else ""
        desc_el = item.find("description")
        summary = desc_el.text or "" if desc_el is not None else title
        date_el = item.find("pubDate") or item.find("{http://purl.org/dc/elements/1.1/}date")
        notification_date = ""
        if date_el is not None and date_el.text:
            # RFC 2822 → ISO date
            try:
                from email.utils import parsedate_to_datetime
                notification_date = parsedate_to_datetime(date_el.text).date().isoformat()
            except Exception:
                notification_date = (date_el.text or "")[:10]
        guid_el = item.find("guid") or item.find("link")
        gazette_ref = guid_el.text or "" if guid_el is not None else title

        for scheme_id in scheme_ids:
            if scheme_id.lower() in title.lower() or scheme_id.lower() in summary.lower():
                updates.append(
                    GazetteUpdate(
                        gazette_ref=gazette_ref,
                        scheme_id=scheme_id,
                        notification_date=notification_date,
                        summary=summary,
                        feed_url=feed_url,
                    )
                )

    return updates


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def poll_gazette_feeds(
    scheme_ids: List[str], feed_urls: List[str]
) -> List[GazetteUpdate]:
    """Fetch RSS/Atom feeds from egazette.gov.in and return entries matching any scheme.

    Entries are matched by checking if the scheme_id appears in the entry title
    or summary (case-insensitive).

    Why: Polling-based detection is simpler and more reliable than webhook-based
    detection for government services that do not support webhooks.

    Raises:
        GazetteMonitorError: If any feed URL is unreachable or returns malformed XML.
    """
    updates: list[GazetteUpdate] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        for feed_url in feed_urls:
            try:
                response = await client.get(feed_url)
            except httpx.RequestError as exc:
                raise GazetteMonitorError(
                    f"Failed to fetch gazette feed at {feed_url}: {exc}"
                ) from exc

            if response.status_code >= 400:
                raise GazetteMonitorError(
                    f"Gazette feed returned HTTP {response.status_code}: {feed_url}"
                )

            try:
                feed_updates = _parse_feed_entries(response.text, feed_url, scheme_ids)
            except GazetteMonitorError:
                raise
            except Exception as exc:
                raise GazetteMonitorError(
                    f"Error processing feed {feed_url}: {exc}"
                ) from exc

            updates.extend(feed_updates)

    return updates


async def trigger_reparse(update: GazetteUpdate) -> ParseJob:
    """Schedule a re-parse job for the scheme that received a gazette update.

    Why: Re-parsing is deferred to the batch pipeline (spec_02). trigger_reparse
    is responsible only for creating a stable job record; the pipeline runner
    polls the job queue asynchronously.

    Args:
        update: The gazette update that triggered this re-parse.

    Returns: ParseJob with a UUID job_id and ISO 8601 queued_at timestamp.
    """
    return ParseJob(
        job_id=str(uuid.uuid4()),
        scheme_id=update.scheme_id,
        queued_at=datetime.now(tz=timezone.utc).isoformat(),
        trigger_source="gazette_monitor",
    )
