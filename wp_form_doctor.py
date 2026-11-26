"""WordPress form submissions audit CLI.

Reads a WordPress form submissions CSV export (from WPForms,
Gravity Forms, Contact Form 7 with a database plugin, or a
manual export) and audits every submission for the problems
that quietly cost a site its leads: spam patterns, link
drops, submissions too fast for a human to type, duplicate
submissions, bursts from one address, and genuine leads
that were never answered. It also scores every form
(submissions, spam, unanswered leads, and average time
to answer) so a site owner can see which form is leaking
leads and which one is drowning in spam.

Akismet, honeypots, and reCAPTCHA block spam live, before
it reaches the inbox. But nobody audits the entries export
afterwards to say which genuine leads sat unanswered for
days, which spam slipped past the live filters, and which
bot hammered the form at three in the morning. This tool
is that audit: it reads the export alone, and never
touches your WordPress site.

Each problem is a finding with a submission id, a rule
name, a severity (error or warning), and a message. Errors
are spam, link drops, too-fast submissions, duplicates,
and genuine leads left unanswered past the limit, plus
impossible dates and data that cannot be trusted; warnings
are single links in a message, short messages, submission
bursts, and genuine leads still waiting inside the limit.
--check exits 1 when any error is found, and --strict also
fails on warnings.

Dates are parsed defensively. A bad date is reported as a
finding and the row is still audited on the fields that
did parse, so one bad row never crashes the run.

Zero dependencies, Python 3.10 or newer, standard library only.

Usage:
    python3 wp_form_doctor.py examples/submissions.csv
    python3 wp_form_doctor.py submissions.csv --json --check
    python3 wp_form_doctor.py submissions.csv --as-of 2026-11-18
"""

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone

__version__ = "1.0.0"

DEFAULT_MIN_SECONDS = 5
DEFAULT_MAX_LINKS = 2
DEFAULT_UNANSWERED_DAYS = 3
DEFAULT_MIN_WORDS = 3
DEFAULT_BURST_COUNT = 3
DEFAULT_BURST_HOURS = 24
UNANSWERED_WARNING_HOURS = 24

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
LINK_PATTERN = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
WORD_PATTERN = re.compile(r"[A-Za-z0-9']+")

SPAM_PHRASES = (
    "buy cheap",
    "viagra",
    "cialis",
    "casino",
    "crypto",
    "bitcoin",
    "seo services",
    "guaranteed ranking",
    "make money fast",
    "work from home",
    "free followers",
    "loan approval",
    "weight loss",
    "lottery winner",
    "inheritance",
    "double your money",
)

TIMESTAMP_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M",
    "%m/%d/%Y %H:%M",
    "%d/%m/%Y",
    "%m/%d/%Y",
)


class Finding:
    """One audit finding for one submission."""

    def __init__(self, submission, rule, severity, message):
        self.submission = submission
        self.rule = rule
        self.severity = severity
        self.message = message

    def as_dict(self):
        """Return the finding as a plain dict."""
        return {"submission": self.submission, "rule": self.rule,
                "severity": self.severity, "message": self.message}

    def __str__(self):
        return "%s [%s] %s: %s" % (self.severity.upper(), self.rule,
                                   self.submission, self.message)


def parse_timestamp(text):
    """Parse a timestamp string into an aware datetime, or None.

    Accepts ISO 8601 with or without a timezone (a trailing Z is
    handled), plus a few common export formats. A naive timestamp
    is read as UTC. Returns None for an empty string or a value
    that matches no known format, so callers can report it
    instead of crashing.
    """
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    candidate = text
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        parsed = None
    if parsed is None:
        for fmt in TIMESTAMP_FORMATS:
            try:
                parsed = datetime.strptime(candidate, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def find_column(header, names):
    """Return the first of names present in header, or None."""
    for name in names:
        if name in header:
            return name
    return None


def count_links(message):
    """Return how many links a message contains."""
    if not message:
        return 0
    return len(LINK_PATTERN.findall(message))


def spam_reason(message):
    """Return why a message looks like spam, or None.

    Checks known spam phrases, keyword stuffing (one word
    repeated 4 or more times), and an all-caps message.
    """
    if not message:
        return None
    lowered = message.lower()
    for phrase in SPAM_PHRASES:
        if phrase in lowered:
            return "message contains the spam phrase %r" % phrase
    words = [word.lower() for word in WORD_PATTERN.findall(message)]
    counts = {}
    for word in words:
        counts[word] = counts.get(word, 0) + 1
    for word in sorted(counts):
        if counts[word] >= 4:
            return ("message repeats the word %r %d times, "
                    "which reads as keyword stuffing"
                    % (word, counts[word]))
    letters = [char for char in message if char.isalpha()]
    if len(message) >= 20 and letters and all(
            char.isupper() for char in letters):
        return "message is written entirely in capital letters"
    return None


def normalize_message(message):
    """Normalize a message for duplicate comparison."""
    return " ".join(message.lower().split())


def hours_between(start, end):
    """Return the hours from start to end, or None."""
    if start is None or end is None:
        return None
    return (end - start).total_seconds() / 3600.0


def parse_csv(path, as_of):
    """Parse a form submissions CSV export.

    Returns (submissions, findings). Each submission is a dict
    with the id, form, name, email, message, the parsed
    submitted and answered dates, and the IP address. Rows
    with the wrong number of fields are reported as
    malformed-row errors and skipped, never a crash. A UTF-8
    BOM header is handled. Extra columns are ignored.
    """
    findings = []
    submissions = []
    try:
        handle = open(path, newline="", encoding="utf-8-sig")
    except OSError as exc:
        raise ValueError("cannot read %s: %s" % (path, exc))
    with handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            raise ValueError("%s is empty, no header row found" % path)
        except csv.Error as exc:
            raise ValueError("%s is not a readable CSV file: %s"
                             % (path, exc))
        header = [name.strip() for name in header]
        id_column = find_column(
            header, ("submission_id", "id", "entry_id"))
        if id_column is None:
            raise ValueError(
                "%s has no submission_id or id column "
                "(header is: %s)" % (path, ", ".join(header)))
        email_column = find_column(
            header, ("email", "email_address"))
        if email_column is None:
            raise ValueError(
                "%s has no email column "
                "(header is: %s)" % (path, ", ".join(header)))
        submitted_column = find_column(
            header, ("submitted_at", "created_at", "submitted",
                     "date", "created"))
        if submitted_column is None:
            raise ValueError(
                "%s has no submitted_at column "
                "(header is: %s)" % (path, ", ".join(header)))
        form_column = find_column(header, ("form", "form_name"))
        name_column = find_column(
            header, ("name", "full_name", "your_name"))
        message_column = find_column(
            header, ("message", "message_text", "your_message",
                     "comments"))
        answered_column = find_column(
            header, ("answered_at", "replied_at", "answered",
                     "replied", "reply_date"))
        ip_column = find_column(header, ("ip", "ip_address"))
        seen_ids = set()
        for line_number, row in enumerate(reader, start=2):
            if not row or all(not cell.strip() for cell in row):
                continue
            if len(row) != len(header):
                findings.append(Finding(
                    "row %d" % line_number, "malformed-row", "error",
                    "row has %d fields but the header has %d, "
                    "so the row was skipped" % (len(row), len(header))))
                continue
            cells = dict(zip(header, (cell.strip() for cell in row)))
            submission_id = cells[id_column]
            if not submission_id:
                findings.append(Finding(
                    "row %d" % line_number, "missing-submission-id",
                    "error",
                    "row has no submission id, so the submission "
                    "cannot be matched to a form"))
                submission_id = "row %d" % line_number
            if submission_id in seen_ids:
                findings.append(Finding(
                    submission_id, "duplicate-submission-id", "error",
                    "submission id appears more than once in the "
                    "export"))
            else:
                seen_ids.add(submission_id)
            email = cells[email_column]
            if not email:
                findings.append(Finding(
                    submission_id, "missing-email", "error",
                    "submission has no email, so it cannot be "
                    "answered or matched to a sender"))
            elif not EMAIL_PATTERN.match(email):
                findings.append(Finding(
                    submission_id, "invalid-email", "error",
                    "email %r is not a valid email address"
                    % email))
            submitted = None
            submitted_raw = cells[submitted_column]
            if submitted_raw:
                submitted = parse_timestamp(submitted_raw)
                if submitted is None:
                    findings.append(Finding(
                        submission_id, "invalid-timestamp", "error",
                        "submitted date %r is not a readable date"
                        % submitted_raw))
            answered = None
            answered_raw = (cells[answered_column]
                            if answered_column else "")
            if answered_raw:
                answered = parse_timestamp(answered_raw)
                if answered is None:
                    findings.append(Finding(
                        submission_id, "invalid-timestamp", "error",
                        "answered date %r is not a readable date"
                        % answered_raw))
            if submitted is not None and submitted > as_of:
                findings.append(Finding(
                    submission_id, "future-timestamp", "error",
                    "submitted date %s is after the as-of date %s"
                    % (submitted.strftime("%Y-%m-%d %H:%M"),
                       as_of.strftime("%Y-%m-%d %H:%M"))))
            if submitted is not None and answered is not None \
                    and answered < submitted:
                findings.append(Finding(
                    submission_id, "impossible-dates", "error",
                    "answered date %s is before the submission "
                    "was made %s"
                    % (answered.strftime("%Y-%m-%d %H:%M"),
                       submitted.strftime("%Y-%m-%d %H:%M"))))
            submissions.append({
                "id": submission_id,
                "form": (cells[form_column]
                         if form_column else ""),
                "name": (cells[name_column]
                         if name_column else ""),
                "email": email,
                "message": (cells[message_column]
                            if message_column else ""),
                "submitted": submitted,
                "answered": answered,
                "ip": (cells[ip_column] if ip_column else ""),
                "line": line_number})
    return submissions, findings


def audit(submissions, as_of,
          min_seconds=DEFAULT_MIN_SECONDS,
          max_links=DEFAULT_MAX_LINKS,
          unanswered_days=DEFAULT_UNANSWERED_DAYS,
          min_words=DEFAULT_MIN_WORDS,
          burst_count=DEFAULT_BURST_COUNT,
          burst_hours=DEFAULT_BURST_HOURS):
    """Audit a parsed submission list and return findings."""
    findings = []
    spam_ids = set()
    too_fast_ids = {}
    for key_name in ("email", "ip"):
        groups = {}
        for submission in submissions:
            key = submission[key_name].strip().lower()
            if key and submission["submitted"] is not None:
                groups.setdefault(key, []).append(submission)
        for group in groups.values():
            ordered = sorted(group, key=lambda item: item["submitted"])
            for previous, current in zip(ordered, ordered[1:]):
                gap = (current["submitted"]
                       - previous["submitted"]).total_seconds()
                if 0 <= gap < min_seconds:
                    if current["id"] not in too_fast_ids:
                        too_fast_ids[current["id"]] = gap
    seen_messages = set()
    duplicate_ids = set()
    for submission in submissions:
        email = submission["email"].strip().lower()
        message = normalize_message(submission["message"])
        if email and message:
            key = (email, message)
            if key in seen_messages:
                duplicate_ids.add(submission["id"])
            else:
                seen_messages.add(key)
    for submission in submissions:
        submission_id = submission["id"]
        message = submission["message"]
        reason = spam_reason(message)
        if reason is not None:
            findings.append(Finding(
                submission_id, "spam-pattern", "error", reason))
            spam_ids.add(submission_id)
        links = count_links(message)
        if links > max_links:
            findings.append(Finding(
                submission_id, "link-drop", "error",
                "message contains %d links, past the %d link "
                "limit" % (links, max_links)))
            spam_ids.add(submission_id)
        elif links >= 1:
            findings.append(Finding(
                submission_id, "link-in-message", "warning",
                "message contains %d link%s, so check it "
                "before replying"
                % (links, "s" if links > 1 else "")))
        if submission_id in too_fast_ids:
            findings.append(Finding(
                submission_id, "too-fast-submission", "error",
                "submission arrived %.0f seconds after the "
                "previous one from the same sender, faster "
                "than the %d second minimum for a human"
                % (too_fast_ids[submission_id], min_seconds)))
        if submission_id in duplicate_ids:
            findings.append(Finding(
                submission_id, "duplicate-submission", "error",
                "the same sender sent the same message before, "
                "so this is a duplicate submission"))
        email = submission["email"].strip().lower()
        if email and submission["submitted"] is not None:
            same_sender = [item for item in submissions
                           if item["email"].strip().lower() == email
                           and item["submitted"] is not None]
            window_start = submission["submitted"]
            in_window = [item for item in same_sender
                         if item["submitted"] <= window_start
                         and (window_start - item["submitted"])
                         .total_seconds() <= burst_hours * 3600.0]
            if len(in_window) >= burst_count:
                findings.append(Finding(
                    submission_id, "submission-burst", "warning",
                    "this is submission %d from this sender "
                    "within %d hours"
                    % (len(in_window), burst_hours)))
        words = WORD_PATTERN.findall(message)
        if not message:
            findings.append(Finding(
                submission_id, "empty-message", "warning",
                "submission has no message, so there is "
                "nothing to answer"))
        elif len(words) < min_words:
            findings.append(Finding(
                submission_id, "short-message", "warning",
                "message has only %d word%s, past the %d word "
                "minimum, so it may be a throwaway submission"
                % (len(words), "s" if len(words) != 1 else "",
                   min_words)))
        if submission_id not in spam_ids \
                and submission["answered"] is None \
                and submission["submitted"] is not None:
            age_hours = (as_of - submission["submitted"]) \
                .total_seconds() / 3600.0
            if age_hours > unanswered_days * 24.0:
                findings.append(Finding(
                    submission_id, "unanswered-lead-overdue",
                    "error",
                    "genuine lead has waited %.1f hours with "
                    "no answer, past the %d day limit"
                    % (age_hours, unanswered_days)))
            elif age_hours > UNANSWERED_WARNING_HOURS:
                findings.append(Finding(
                    submission_id, "unanswered-lead", "warning",
                    "genuine lead has waited %.1f hours with "
                    "no answer" % age_hours))
    return findings


def summarize(submissions, findings, as_of):
    """Return the summary counts for a submission list."""
    errors = sum(1 for item in findings if item.severity == "error")
    warnings = sum(1 for item in findings
                   if item.severity == "warning")
    spam_ids = set()
    for item in findings:
        if item.rule in ("spam-pattern", "link-drop"):
            spam_ids.add(item.submission)
    spam = len(spam_ids)
    genuine = len(submissions) - spam
    unanswered = 0
    answered = 0
    answer_times = []
    for submission in submissions:
        if submission["answered"] is not None:
            answered += 1
            if submission["id"] not in spam_ids:
                value = hours_between(submission["submitted"],
                                      submission["answered"])
                if value is not None and value >= 0 \
                        and submission["submitted"] is not None \
                        and submission["submitted"] <= as_of:
                    answer_times.append(value)
        elif submission["id"] not in spam_ids:
            unanswered += 1
    average_answer = (sum(answer_times) / len(answer_times)
                      if answer_times else None)
    spam_rate = (spam / len(submissions) * 100.0
                 if submissions else 0.0)
    per_form = []
    forms = {}
    for submission in submissions:
        forms.setdefault(submission["form"] or "(no form)",
                         []).append(submission)
    for form in sorted(forms):
        form_submissions = forms[form]
        form_spam = sum(1 for item in form_submissions
                        if item["id"] in spam_ids)
        form_unanswered = sum(
            1 for item in form_submissions
            if item["answered"] is None
            and item["id"] not in spam_ids)
        form_answered = sum(
            1 for item in form_submissions
            if item["answered"] is not None)
        form_times = []
        for item in form_submissions:
            if item["id"] not in spam_ids:
                value = hours_between(item["submitted"],
                                      item["answered"])
                if value is not None and value >= 0 \
                        and item["submitted"] is not None \
                        and item["submitted"] <= as_of:
                    form_times.append(value)
        form_average = (sum(form_times) / len(form_times)
                        if form_times else None)
        per_form.append({
            "form": form,
            "submissions": len(form_submissions),
            "spam": form_spam,
            "unanswered": form_unanswered,
            "answered": form_answered,
            "average_answer_hours":
                (round(form_average, 1)
                 if form_average is not None else None)})
    return {"submissions": len(submissions),
            "findings": len(findings),
            "errors": errors,
            "warnings": warnings,
            "spam": spam,
            "genuine": genuine,
            "unanswered": unanswered,
            "answered": answered,
            "average_answer_hours":
                (round(average_answer, 1)
                 if average_answer is not None else None),
            "spam_rate": round(spam_rate, 1),
            "per_form": per_form}


def format_hours(value):
    """Format an average hours value, or n/a when there is none."""
    if value is None:
        return "n/a"
    return "%.1f hours" % value


def render_text(submissions, findings, summary):
    """Render the text report."""
    lines = [str(item) for item in findings]
    lines.append("")
    lines.append("Submissions: %(submissions)d, findings: "
                 "%(findings)d, errors: %(errors)d, warnings: "
                 "%(warnings)d" % summary)
    lines.append("Spam: %(spam)d, genuine: %(genuine)d, "
                 "unanswered: %(unanswered)d, answered: "
                 "%(answered)d" % summary)
    lines.append("Average time to answer: %s, spam rate: %.1f%%"
                 % (format_hours(summary["average_answer_hours"]),
                    summary["spam_rate"]))
    lines.append("")
    lines.append("Per-form summary:")
    for row in summary["per_form"]:
        lines.append(
            "%s: %d submissions, %d spam, %d unanswered, "
            "%d answered, average answer %s"
            % (row["form"], row["submissions"], row["spam"],
               row["unanswered"], row["answered"],
               format_hours(row["average_answer_hours"])))
    if summary["findings"] == 0:
        lines.append("")
        lines.append("All submissions clean.")
    return "\n".join(lines) + "\n"


def render_json(submissions, findings, summary):
    """Render the JSON report."""
    report = dict(summary)
    report["findings"] = [item.as_dict() for item in findings]
    return json.dumps(report, indent=2) + "\n"


def build_parser():
    """Build the command line parser."""
    parser = argparse.ArgumentParser(
        prog="wp-form-doctor",
        description="Audit a WordPress form submissions CSV "
                    "export for spam, link drops, too-fast "
                    "submissions, duplicates, and unanswered "
                    "genuine leads.")
    parser.add_argument("csv_file", help="form submissions CSV "
                        "export to audit")
    parser.add_argument("--min-seconds", type=int,
                        default=DEFAULT_MIN_SECONDS,
                        help="submissions from the same sender "
                        "faster than this many seconds apart are "
                        "too fast for a human "
                        "(default: %d)" % DEFAULT_MIN_SECONDS)
    parser.add_argument("--max-links", type=int,
                        default=DEFAULT_MAX_LINKS,
                        help="a message with more links than this "
                        "is a link drop "
                        "(default: %d)" % DEFAULT_MAX_LINKS)
    parser.add_argument("--unanswered-days", type=float,
                        default=DEFAULT_UNANSWERED_DAYS,
                        help="a genuine lead unanswered longer "
                        "than this many days is overdue "
                        "(default: %d)" % DEFAULT_UNANSWERED_DAYS)
    parser.add_argument("--min-words", type=int,
                        default=DEFAULT_MIN_WORDS,
                        help="a message with fewer words than "
                        "this is a short message "
                        "(default: %d)" % DEFAULT_MIN_WORDS)
    parser.add_argument("--burst-count", type=int,
                        default=DEFAULT_BURST_COUNT,
                        help="a sender with this many submissions "
                        "in the burst window is bursting "
                        "(default: %d)" % DEFAULT_BURST_COUNT)
    parser.add_argument("--burst-hours", type=int,
                        default=DEFAULT_BURST_HOURS,
                        help="the burst window in hours "
                        "(default: %d)" % DEFAULT_BURST_HOURS)
    parser.add_argument("--as-of", default=None,
                        help="date to compare timestamps against, "
                        "for example 2026-11-18 (default: now)")
    parser.add_argument("--json", action="store_true",
                        help="emit JSON instead of text")
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if any error is found")
    parser.add_argument("--strict", action="store_true",
                        help="with --check, also exit 1 on warnings")
    parser.add_argument("--out", default=None,
                        help="write the report to a file")
    return parser


def main(argv=None):
    """Run the CLI and return the exit code."""
    args = build_parser().parse_args(argv)
    if args.min_seconds < 0:
        print("error: --min-seconds must be at least 0",
              file=sys.stderr)
        return 2
    if args.max_links < 0:
        print("error: --max-links must be at least 0",
              file=sys.stderr)
        return 2
    if args.unanswered_days < 0:
        print("error: --unanswered-days must be at least 0",
              file=sys.stderr)
        return 2
    if args.min_words < 0:
        print("error: --min-words must be at least 0",
              file=sys.stderr)
        return 2
    if args.burst_count < 2:
        print("error: --burst-count must be at least 2",
              file=sys.stderr)
        return 2
    if args.burst_hours < 1:
        print("error: --burst-hours must be at least 1",
              file=sys.stderr)
        return 2
    if args.as_of is None:
        as_of = datetime.now(timezone.utc)
    else:
        as_of = parse_timestamp(args.as_of)
        if as_of is None:
            print("error: --as-of %r is not a readable date"
                  % args.as_of, file=sys.stderr)
            return 2
    try:
        submissions, findings = parse_csv(args.csv_file, as_of)
    except ValueError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    findings.extend(audit(submissions, as_of,
                          min_seconds=args.min_seconds,
                          max_links=args.max_links,
                          unanswered_days=args.unanswered_days,
                          min_words=args.min_words,
                          burst_count=args.burst_count,
                          burst_hours=args.burst_hours))
    summary = summarize(submissions, findings, as_of)
    if args.json:
        report = render_json(submissions, findings, summary)
    else:
        report = render_text(submissions, findings, summary)
    if args.out is not None:
        try:
            with open(args.out, "w", encoding="utf-8") as handle:
                handle.write(report)
        except OSError as exc:
            print("error: cannot write %s: %s" % (args.out, exc),
                  file=sys.stderr)
            return 2
    else:
        sys.stdout.write(report)
    if args.check:
        if summary["errors"] > 0:
            return 1
        if args.strict and summary["warnings"] > 0:
            return 1
    return 0


def main_entry():
    """Console script entry point."""
    sys.exit(main())


if __name__ == "__main__":
    main_entry()
