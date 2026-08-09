"""
Alert dispatch: send health alerts to Slack, Email, PagerDuty, or generic webhooks.

Supports deduplication — won't spam the same alert every 60 seconds.
"""

import hashlib
import json
import logging
import os
import smtplib
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

logger = logging.getLogger("ec2-sentinel.alerts")


# ---------------------------------------------------------------------------
# Alert deduplication
# ---------------------------------------------------------------------------

DEDUP_FILE = Path("/tmp/ec2_sentinel_alert_dedup.json")
DEDUP_WINDOW_SECONDS = 300  # don't re-fire the same alert within 5 minutes


def _alert_key(alert_type: str, message: str) -> str:
    raw = f"{alert_type}:{message}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _is_duplicate(key: str) -> bool:
    try:
        if DEDUP_FILE.exists():
            history = json.loads(DEDUP_FILE.read_text())
        else:
            history = {}
    except (json.JSONDecodeError, OSError):
        history = {}

    now = time.time()
    if key in history and (now - history[key]) < DEDUP_WINDOW_SECONDS:
        return True

    # Record this alert
    history[key] = now
    # Prune old entries
    history = {k: v for k, v in history.items() if (now - v) < DEDUP_WINDOW_SECONDS * 2}
    try:
        DEDUP_FILE.write_text(json.dumps(history))
    except OSError:
        pass
    return False


# ---------------------------------------------------------------------------
# Alert data
# ---------------------------------------------------------------------------

@dataclass
class Alert:
    severity: str       # "warning" or "critical"
    title: str          # short summary
    message: str        # detail
    hostname: str
    timestamp: str
    source: str = ""    # which collector generated this

    @property
    def emoji(self) -> str:
        return "🔴" if self.severity == "critical" else "⚠️"


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------

def send_slack(alert: Alert, webhook_url: str, channel: Optional[str] = None) -> bool:
    """Send alert to Slack via incoming webhook."""
    key = _alert_key("slack", alert.title + alert.message)
    if _is_duplicate(key):
        logger.debug(f"Slack alert deduplicated: {alert.title}")
        return True

    payload = {
        "text": f"{alert.emoji} *EC2 Sentinel — {alert.severity.upper()}*",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{alert.emoji} {alert.title}",
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Host:*\n{alert.hostname}"},
                    {"type": "mrkdwn", "text": f"*Severity:*\n{alert.severity.upper()}"},
                    {"type": "mrkdwn", "text": f"*Source:*\n{alert.source}"},
                    {"type": "mrkdwn", "text": f"*Time:*\n{alert.timestamp}"},
                ],
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"```{alert.message}```"},
            },
        ],
    }

    if channel:
        payload["channel"] = channel

    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        logger.error(f"Slack alert failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def send_email(
    alert: Alert,
    smtp_host: str,
    to_addresses: list[str],
    from_address: str = "ec2-sentinel@localhost",
    smtp_port: int = 587,
    smtp_user: Optional[str] = None,
    smtp_pass: Optional[str] = None,
) -> bool:
    """Send alert via SMTP email."""
    key = _alert_key("email", alert.title + alert.message)
    if _is_duplicate(key):
        return True

    subject = f"[EC2 Sentinel {alert.severity.upper()}] {alert.title} — {alert.hostname}"
    body = f"""EC2 Sentinel Alert
{'=' * 50}
Severity:  {alert.severity.upper()}
Host:      {alert.hostname}
Time:      {alert.timestamp}
Source:    {alert.source}

{alert.message}
"""
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = from_address
    msg["To"] = ", ".join(to_addresses)

    try:
        server = smtplib.SMTP(smtp_host, smtp_port)
        server.ehlo()
        if smtp_port == 587:
            server.starttls()
        if smtp_user and smtp_pass:
            server.login(smtp_user, smtp_pass)
        server.sendmail(from_address, to_addresses, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        logger.error(f"Email alert failed: {e}")
        return False


# ---------------------------------------------------------------------------
# PagerDuty (Events API v2)
# ---------------------------------------------------------------------------

def send_pagerduty(alert: Alert, routing_key: str) -> bool:
    """Send alert to PagerDuty via Events API v2."""
    key = _alert_key("pagerduty", alert.title + alert.message)
    if _is_duplicate(key):
        return True

    severity_map = {"critical": "critical", "warning": "warning"}

    payload = {
        "routing_key": routing_key,
        "event_action": "trigger",
        "payload": {
            "summary": f"[EC2 Sentinel] {alert.title} — {alert.hostname}",
            "severity": severity_map.get(alert.severity, "warning"),
            "source": alert.hostname,
            "component": alert.source,
            "custom_details": {
                "message": alert.message,
                "timestamp": alert.timestamp,
            },
        },
    }

    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            "https://events.pagerduty.com/v2/enqueue",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 202)
    except Exception as e:
        logger.error(f"PagerDuty alert failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Generic Webhook
# ---------------------------------------------------------------------------

def send_webhook(alert: Alert, url: str, headers: Optional[dict] = None) -> bool:
    """Send alert as JSON POST to any webhook URL."""
    key = _alert_key("webhook", alert.title + alert.message)
    if _is_duplicate(key):
        return True

    payload = {
        "severity": alert.severity,
        "title": alert.title,
        "message": alert.message,
        "hostname": alert.hostname,
        "timestamp": alert.timestamp,
        "source": alert.source,
    }

    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)

    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, headers=req_headers, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status < 300
    except Exception as e:
        logger.error(f"Webhook alert failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Dispatcher — route alerts based on config
# ---------------------------------------------------------------------------

def dispatch_alerts(alerts: list[Alert], alert_config: dict) -> dict:
    """
    Send alerts through all configured channels.

    Returns dict of {channel: {sent: int, failed: int}}.
    """
    results = {}

    # Resolve env vars in config values
    def _resolve(val):
        if isinstance(val, str) and val.startswith("${") and val.endswith("}"):
            env_key = val[2:-1]
            return os.environ.get(env_key, "")
        return val

    # Slack
    slack_cfg = alert_config.get("slack", {})
    if slack_cfg.get("enabled"):
        webhook = _resolve(slack_cfg.get("webhook_url", ""))
        channel = slack_cfg.get("channel")
        sent, failed = 0, 0
        for alert in alerts:
            if send_slack(alert, webhook, channel):
                sent += 1
            else:
                failed += 1
        results["slack"] = {"sent": sent, "failed": failed}

    # Email
    email_cfg = alert_config.get("email", {})
    if email_cfg.get("enabled"):
        sent, failed = 0, 0
        for alert in alerts:
            if send_email(
                alert,
                smtp_host=email_cfg.get("smtp_host", "localhost"),
                to_addresses=email_cfg.get("to", []),
                smtp_port=email_cfg.get("smtp_port", 587),
                smtp_user=_resolve(email_cfg.get("smtp_user")),
                smtp_pass=_resolve(email_cfg.get("smtp_pass")),
            ):
                sent += 1
            else:
                failed += 1
        results["email"] = {"sent": sent, "failed": failed}

    # PagerDuty
    pd_cfg = alert_config.get("pagerduty", {})
    if pd_cfg.get("enabled"):
        routing_key = _resolve(pd_cfg.get("routing_key", ""))
        sent, failed = 0, 0
        for alert in alerts:
            if send_pagerduty(alert, routing_key):
                sent += 1
            else:
                failed += 1
        results["pagerduty"] = {"sent": sent, "failed": failed}

    # Generic webhook
    webhook_cfg = alert_config.get("webhook", {})
    if webhook_cfg.get("enabled"):
        url = _resolve(webhook_cfg.get("url", ""))
        sent, failed = 0, 0
        for alert in alerts:
            if send_webhook(alert, url):
                sent += 1
            else:
                failed += 1
        results["webhook"] = {"sent": sent, "failed": failed}

    return results
