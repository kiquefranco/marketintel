"""Email an alert when the daily briefing halts after too many failed runs today.

Run by daily-briefing.yml when guard_skip_if_ran.py emits alert=true (i.e. the
failed-run cap was hit). Sends ONE email to the owner explaining that no briefing
went out and no further attempts will be made today. Stdlib only.

FAILS SOFT, always. The cap works by having this run conclude SUCCESS, which makes
every later dispatch today skip via the guard's success check. If this script exits
non-zero the job fails, no success is recorded, and the external cron re-dispatches
every 30 minutes into the same wall -- the circuit breaker becomes the thing
generating the retries (2026-09-14: a malformed ALERT_EMAIL_TO did exactly that).
So a bad address or a dead SMTP server is logged and swallowed, never raised.

Env: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, EMAIL_FROM,
     ALERT_EMAIL_TO (owner; falls back to EMAIL_TO), GITHUB_REPOSITORY.
"""
from __future__ import annotations

import os
import smtplib
import sys
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import getaddresses


def _addresses(raw: str | None) -> list[str]:
    """Parse a comma-separated recipient string into deliverable addresses.

    Drops anything that is not a real address: empty entries from a trailing
    comma, and display-name-only values such as a quoted or bracket-less name,
    which getaddresses returns with an empty addr-spec. Gmail rejects those with
    555 5.5.2 and refuses the whole message when nothing else is on the list.
    """
    if not raw:
        return []
    good = []
    for _name, addr in getaddresses([raw]):
        addr = addr.strip()
        if not addr or "@" not in addr:
            shown = addr or _name.strip()
            print(f"alert_capped: dropping unaddressable recipient {shown!r}")
            continue
        try:
            Address(addr_spec=addr)
        except (ValueError, IndexError):
            print(f"alert_capped: dropping malformed recipient {addr!r}")
            continue
        if addr not in good:
            good.append(addr)
    return good


def main() -> None:
    host = os.environ.get("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT") or "587")
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASS")
    sender = os.environ.get("EMAIL_FROM") or user
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    runs_url = f"https://github.com/{repo}/actions/workflows/daily-briefing.yml"

    # ALERT_EMAIL_TO wins, but only if it yields a real address -- a malformed
    # value must fall through to EMAIL_TO rather than silently swallow the alert.
    to = _addresses(os.environ.get("ALERT_EMAIL_TO")) or _addresses(os.environ.get("EMAIL_TO"))
    if not to:
        print("alert_capped: no deliverable recipient (check ALERT_EMAIL_TO / EMAIL_TO); "
              "skipping the alert email so the halt still holds.")
        return
    if not (host and user and password and sender):
        print("alert_capped: SMTP not configured; skipping the alert email.")
        return

    msg = EmailMessage()
    msg["Subject"] = "ALERT: daily briefing HALTED -- too many failed runs today"
    msg["From"] = sender
    msg["To"] = ", ".join(to)
    msg.set_content(
        "The Daily Market Intelligence Briefing hit its failed-run cap and will make "
        "NO further attempts today. No briefing was sent.\n\n"
        f"Run history / logs:\n  {runs_url}\n\n"
        "Most likely causes:\n"
        "  - Gemini API quota or billing problem (429s in the 'Run briefing pipeline' "
        "step; check the Google Cloud billing account linked to the API key's project)\n"
        "  - A code/config error introduced in a recent push (same error in every run)\n\n"
        "Once fixed, trigger a run manually from the Actions page (Run workflow) or "
        "wait for tomorrow's cron.\n"
    )
    try:
        with smtplib.SMTP(host, port, timeout=60) as smtp:
            smtp.starttls()
            smtp.login(user, password)
            smtp.send_message(msg)
    except Exception as exc:   # noqa: BLE001 -- see module docstring: never fail the job
        print(f"alert_capped: could not send the halt alert ({type(exc).__name__}: {exc}); "
              "continuing so the halt still holds.", file=sys.stderr)
        return
    print(f"alert_capped: sent halt alert to {', '.join(to)}")


if __name__ == "__main__":
    main()
