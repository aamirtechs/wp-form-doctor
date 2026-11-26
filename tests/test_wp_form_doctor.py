"""Tests for wp_form_doctor."""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

import wp_form_doctor as doctor

AS_OF = datetime(2026, 11, 18, tzinfo=timezone.utc)

HEADER = ("submission_id,form,name,email,message,submitted_at,"
          "answered_at,ip\n")


def write_csv(body, directory=None):
    """Write body to a temp CSV file and return its path."""
    handle = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False,
        dir=directory, encoding="utf-8")
    handle.write(body)
    handle.close()
    return handle.name


def row(submission_id="F-1", form="Contact", name="Sarah Miller",
        email="sarah@example.com",
        message="Hi, I need a quote for a new company website.",
        submitted="2026-11-17 09:00",
        answered="2026-11-17 10:30", ip="203.0.113.10"):
    """Build one CSV data row."""
    return ",".join((submission_id, form, name, email,
                     '"%s"' % message, submitted, answered,
                     ip)) + "\n"


def run_cli(argv):
    """Run main with argv and capture stdout, return (code, text)."""
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = doctor.main(argv)
    return code, buffer.getvalue()


def parse_and_audit(body, **kwargs):
    """Parse body and audit it, return (submissions, findings)."""
    path = write_csv(HEADER + body)
    try:
        submissions, findings = doctor.parse_csv(path, AS_OF)
        findings.extend(doctor.audit(submissions, AS_OF, **kwargs))
        return submissions, findings
    finally:
        os.unlink(path)


def rules(findings):
    """Return the rule names of findings, in order."""
    return [item.rule for item in findings]


def by_rule(findings, rule):
    """Return the findings with the given rule."""
    return [item for item in findings if item.rule == rule]


class TestParseTimestamp(unittest.TestCase):
    """Timestamp parsing."""

    def test_iso_with_time(self):
        self.assertEqual(
            doctor.parse_timestamp("2026-11-17 09:00"),
            datetime(2026, 11, 17, 9, 0, tzinfo=timezone.utc))

    def test_iso_with_t_separator_and_z(self):
        self.assertEqual(
            doctor.parse_timestamp("2026-11-17T09:00:00Z"),
            datetime(2026, 11, 17, 9, 0, tzinfo=timezone.utc))

    def test_date_only(self):
        self.assertEqual(
            doctor.parse_timestamp("2026-11-17"),
            datetime(2026, 11, 17, tzinfo=timezone.utc))

    def test_day_month_year(self):
        self.assertEqual(
            doctor.parse_timestamp("17/11/2026 09:00"),
            datetime(2026, 11, 17, 9, 0, tzinfo=timezone.utc))

    def test_empty_returns_none(self):
        self.assertIsNone(doctor.parse_timestamp(""))
        self.assertIsNone(doctor.parse_timestamp(None))

    def test_unreadable_returns_none(self):
        self.assertIsNone(doctor.parse_timestamp("not-a-date"))


class TestLinkCounting(unittest.TestCase):
    """Link counting in messages."""

    def test_no_links(self):
        self.assertEqual(doctor.count_links("Hello there"), 0)

    def test_http_and_https_links(self):
        self.assertEqual(
            doctor.count_links("see http://a.example.com and "
                               "https://b.example.com"),
            2)

    def test_www_link(self):
        self.assertEqual(
            doctor.count_links("visit www.example.com today"), 1)

    def test_empty_message(self):
        self.assertEqual(doctor.count_links(""), 0)


class TestSpamDetection(unittest.TestCase):
    """Spam pattern detection."""

    def test_clean_message(self):
        self.assertIsNone(doctor.spam_reason(
            "Hi, I need a quote for a new company website."))

    def test_spam_phrase(self):
        reason = doctor.spam_reason(
            "Buy cheap SEO services today")
        self.assertIn("buy cheap", reason)

    def test_spam_phrase_case_insensitive(self):
        reason = doctor.spam_reason("This is a great CASINO offer")
        self.assertIn("casino", reason)

    def test_keyword_stuffing(self):
        reason = doctor.spam_reason(
            "website website website website design help please")
        self.assertIn("website", reason)
        self.assertIn("keyword stuffing", reason)

    def test_three_repeats_is_not_stuffing(self):
        self.assertIsNone(doctor.spam_reason(
            "website website website design help please"))

    def test_all_caps_message(self):
        reason = doctor.spam_reason(
            "PLEASE HELP ME FIX MY WEBSITE IT IS BROKEN TODAY")
        self.assertIn("capital letters", reason)

    def test_short_caps_is_not_spam(self):
        self.assertIsNone(doctor.spam_reason("HELP ME PLEASE"))

    def test_mixed_case_is_not_spam(self):
        self.assertIsNone(doctor.spam_reason(
            "Please Help Me Fix My Website Today"))


class TestParseCsv(unittest.TestCase):
    """CSV parsing and data quality findings."""

    def test_clean_row_parses(self):
        submissions, findings = parse_and_audit(row())
        self.assertEqual(len(submissions), 1)
        self.assertEqual(findings, [])
        self.assertEqual(submissions[0]["id"], "F-1")
        self.assertEqual(submissions[0]["form"], "Contact")
        self.assertEqual(submissions[0]["email"],
                         "sarah@example.com")

    def test_header_aliases(self):
        body = ("id,form_name,full_name,email_address,message_text,"
                "created,reply_date,ip_address\n"
                "F-1,Contact,Sarah,sarah@example.com,"
                "\"Hello there friend\",2026-11-17 09:00,"
                "2026-11-17 10:00,203.0.113.10\n")
        path = write_csv(body)
        try:
            submissions, findings = doctor.parse_csv(path, AS_OF)
        finally:
            os.unlink(path)
        self.assertEqual(findings, [])
        self.assertEqual(submissions[0]["form"], "Contact")
        self.assertEqual(submissions[0]["name"], "Sarah")

    def test_bom_header(self):
        path = write_csv("\ufeff" + HEADER + row())
        try:
            submissions, findings = doctor.parse_csv(path, AS_OF)
        finally:
            os.unlink(path)
        self.assertEqual(len(submissions), 1)
        self.assertEqual(findings, [])

    def test_extra_columns_ignored(self):
        body = (HEADER.replace("ip\n", "ip,extra\n")
                + row().rstrip("\n") + ",ignored\n")
        path = write_csv(body)
        try:
            submissions, findings = doctor.parse_csv(path, AS_OF)
        finally:
            os.unlink(path)
        self.assertEqual(len(submissions), 1)
        self.assertEqual(findings, [])

    def test_blank_lines_skipped(self):
        submissions, findings = parse_and_audit(
            row() + "\n" + row(
                submission_id="F-2", email="john@example.com",
                submitted="2026-11-17 10:00", ip="203.0.113.11"))
        self.assertEqual(len(submissions), 2)
        self.assertEqual(findings, [])

    def test_missing_file(self):
        with self.assertRaises(ValueError):
            doctor.parse_csv("/no/such/file.csv", AS_OF)

    def test_empty_file(self):
        path = write_csv("")
        try:
            with self.assertRaises(ValueError):
                doctor.parse_csv(path, AS_OF)
        finally:
            os.unlink(path)

    def test_missing_id_column(self):
        body = ("form,name,email,message,submitted_at,answered_at,ip\n"
                + row().split(",", 1)[1])
        path = write_csv(body)
        try:
            with self.assertRaises(ValueError):
                doctor.parse_csv(path, AS_OF)
        finally:
            os.unlink(path)

    def test_missing_email_column(self):
        body = ("submission_id,form,name,message,submitted_at,"
                "answered_at,ip\n"
                "F-1,Contact,Sarah,\"Hello\",2026-11-17 09:00,"
                "2026-11-17 10:00,203.0.113.10\n")
        path = write_csv(body)
        try:
            with self.assertRaises(ValueError):
                doctor.parse_csv(path, AS_OF)
        finally:
            os.unlink(path)

    def test_malformed_row_skipped(self):
        submissions, findings = parse_and_audit(
            row() + row(submission_id="F-2").rstrip("\n")
            + ",extra-field\n")
        self.assertEqual(len(submissions), 1)
        self.assertEqual(rules(findings), ["malformed-row"])
        self.assertEqual(findings[0].severity, "error")

    def test_duplicate_submission_id(self):
        submissions, findings = parse_and_audit(
            row() + row(email="john@example.com",
                        submitted="2026-11-17 10:00",
                        ip="203.0.113.11"))
        self.assertEqual(rules(findings),
                         ["duplicate-submission-id"])

    def test_missing_submission_id(self):
        submissions, findings = parse_and_audit(
            row(submission_id=""))
        self.assertEqual(rules(findings), ["missing-submission-id"])
        self.assertEqual(len(submissions), 1)

    def test_missing_email(self):
        submissions, findings = parse_and_audit(row(email=""))
        self.assertEqual(rules(findings), ["missing-email"])

    def test_invalid_email(self):
        for bad in ("not-an-email", "a@b", "a b@example.com",
                    "@example.com"):
            submissions, findings = parse_and_audit(
                row(email=bad))
            self.assertEqual(rules(findings), ["invalid-email"],
                             bad)

    def test_valid_email_forms(self):
        for good in ("a@example.com", "first.last@sub.example.co"):
            submissions, findings = parse_and_audit(
                row(email=good))
            self.assertEqual(findings, [], good)

    def test_invalid_timestamp(self):
        submissions, findings = parse_and_audit(
            row(submitted="not-a-date"))
        self.assertEqual(rules(findings), ["invalid-timestamp"])

    def test_invalid_answered_timestamp(self):
        submissions, findings = parse_and_audit(
            row(answered="soon"))
        self.assertEqual(rules(findings), ["invalid-timestamp"])

    def test_future_timestamp(self):
        submissions, findings = parse_and_audit(
            row(submitted="2026-12-01 09:00", answered=""))
        self.assertEqual(rules(findings), ["future-timestamp"])

    def test_impossible_dates(self):
        submissions, findings = parse_and_audit(
            row(submitted="2026-11-17 10:00",
                answered="2026-11-16 09:00"))
        self.assertEqual(rules(findings), ["impossible-dates"])

    def test_optional_columns_can_be_absent(self):
        body = ("submission_id,email,submitted_at\n"
                "F-1,sarah@example.com,2026-11-17 09:00\n")
        path = write_csv(body)
        try:
            submissions, findings = doctor.parse_csv(path, AS_OF)
        finally:
            os.unlink(path)
        self.assertEqual(len(submissions), 1)
        self.assertEqual(findings, [])


class TestAudit(unittest.TestCase):
    """Audit rules."""

    def test_spam_pattern_error(self):
        submissions, findings = parse_and_audit(
            row(message="Buy cheap SEO services guaranteed ranking"))
        self.assertEqual(rules(findings), ["spam-pattern"])
        self.assertEqual(findings[0].severity, "error")

    def test_link_drop_error(self):
        submissions, findings = parse_and_audit(
            row(message="See http://a.example.com and "
                        "http://b.example.com and "
                        "http://c.example.com"))
        self.assertEqual(rules(findings), ["link-drop"])

    def test_two_links_is_a_warning(self):
        submissions, findings = parse_and_audit(
            row(message="See http://a.example.com and "
                        "http://b.example.com"))
        self.assertEqual(rules(findings), ["link-in-message"])
        self.assertEqual(findings[0].severity, "warning")

    def test_one_link_is_a_warning(self):
        submissions, findings = parse_and_audit(
            row(message="See https://example.com for reference"))
        self.assertEqual(rules(findings), ["link-in-message"])

    def test_max_links_flag(self):
        submissions, findings = parse_and_audit(
            row(message="See http://a.example.com and "
                        "http://b.example.com and "
                        "http://c.example.com"),
            max_links=3)
        self.assertEqual(rules(findings), ["link-in-message"])

    def test_too_fast_submission(self):
        submissions, findings = parse_and_audit(
            row(submitted="2026-11-17 09:00:00")
            + row(submission_id="F-2",
                  submitted="2026-11-17 09:00:03",
                  message="Hello I need a website now"))
        self.assertEqual(rules(findings), ["too-fast-submission"])
        self.assertEqual(findings[0].submission, "F-2")

    def test_exactly_min_seconds_is_not_too_fast(self):
        submissions, findings = parse_and_audit(
            row(submitted="2026-11-17 09:00:00")
            + row(submission_id="F-2",
                  submitted="2026-11-17 09:00:05",
                  message="Hello I need a website now"))
        self.assertEqual(findings, [])

    def test_too_fast_by_ip(self):
        submissions, findings = parse_and_audit(
            row(submitted="2026-11-17 09:00:00")
            + row(submission_id="F-2", email="other@example.com",
                  submitted="2026-11-17 09:00:02",
                  message="Another message here today"))
        self.assertEqual(rules(findings), ["too-fast-submission"])

    def test_min_seconds_flag(self):
        submissions, findings = parse_and_audit(
            row(submitted="2026-11-17 09:00:00")
            + row(submission_id="F-2",
                  submitted="2026-11-17 09:00:03",
                  message="Hello I need a website now"),
            min_seconds=1)
        self.assertEqual(findings, [])

    def test_duplicate_submission(self):
        submissions, findings = parse_and_audit(
            row(submitted="2026-11-17 09:00",
                answered="")
            + row(submission_id="F-2",
                  submitted="2026-11-16 10:00", answered=""))
        self.assertEqual(rules(findings),
                         ["duplicate-submission",
                          "unanswered-lead"])
        self.assertEqual(findings[0].submission, "F-2")

    def test_duplicate_needs_same_email_and_message(self):
        submissions, findings = parse_and_audit(
            row(submitted="2026-11-17 09:00")
            + row(submission_id="F-2", email="john@example.com",
                  submitted="2026-11-16 10:00"))
        self.assertEqual(findings, [])

    def test_duplicate_message_case_insensitive(self):
        submissions, findings = parse_and_audit(
            row(submitted="2026-11-17 09:00", answered="",
                message="Hi, I need a quote for a website.")
            + row(submission_id="F-2",
                  submitted="2026-11-16 10:00", answered="",
                  message="  HI, I NEED A QUOTE FOR A WEBSITE. "))
        self.assertIn("duplicate-submission", rules(findings))

    def test_submission_burst(self):
        body = ""
        for number, hour in ((1, "08:00"), (2, "08:30"),
                             (3, "09:00")):
            body += row(submission_id="F-%d" % number,
                        submitted="2026-11-17 " + hour,
                        answered="2026-11-17 10:00",
                        message="Message number %d about my site"
                                % number)
        submissions, findings = parse_and_audit(body)
        self.assertEqual(rules(findings), ["submission-burst"])
        self.assertEqual(findings[0].submission, "F-3")

    def test_two_submissions_is_not_a_burst(self):
        body = ""
        for number, hour in ((1, "08:00"), (2, "08:30")):
            body += row(submission_id="F-%d" % number,
                        submitted="2026-11-17 " + hour,
                        answered="2026-11-17 10:00",
                        message="Message number %d about my site"
                                % number)
        submissions, findings = parse_and_audit(body)
        self.assertEqual(findings, [])

    def test_burst_count_flag(self):
        body = ""
        for number, hour in ((1, "08:00"), (2, "08:30"),
                             (3, "09:00")):
            body += row(submission_id="F-%d" % number,
                        submitted="2026-11-17 " + hour,
                        answered="2026-11-17 10:00",
                        message="Message number %d about my site"
                                % number)
        submissions, findings = parse_and_audit(
            body, burst_count=4)
        self.assertEqual(findings, [])

    def test_short_message_warning(self):
        submissions, findings = parse_and_audit(row(message="Hi"))
        self.assertEqual(rules(findings), ["short-message"])

    def test_min_words_flag(self):
        submissions, findings = parse_and_audit(
            row(message="Hi"), min_words=1)
        self.assertEqual(findings, [])

    def test_empty_message_warning(self):
        submissions, findings = parse_and_audit(row(message=""))
        self.assertEqual(rules(findings), ["empty-message"])

    def test_unanswered_lead_overdue(self):
        submissions, findings = parse_and_audit(
            row(submitted="2026-11-13 09:00", answered=""))
        self.assertEqual(rules(findings),
                         ["unanswered-lead-overdue"])
        self.assertEqual(findings[0].severity, "error")

    def test_unanswered_lead_warning_inside_limit(self):
        submissions, findings = parse_and_audit(
            row(submitted="2026-11-16 09:00", answered=""))
        self.assertEqual(rules(findings), ["unanswered-lead"])
        self.assertEqual(findings[0].severity, "warning")

    def test_unanswered_recent_is_clean(self):
        submissions, findings = parse_and_audit(
            row(submitted="2026-11-17 09:00", answered=""))
        self.assertEqual(findings, [])

    def test_unanswered_exactly_at_limit_is_warning(self):
        submissions, findings = parse_and_audit(
            row(submitted="2026-11-15 00:00", answered=""))
        self.assertEqual(rules(findings), ["unanswered-lead"])

    def test_unanswered_days_flag(self):
        submissions, findings = parse_and_audit(
            row(submitted="2026-11-13 09:00", answered=""),
            unanswered_days=5)
        self.assertEqual(rules(findings), ["unanswered-lead"])

    def test_spam_is_not_flagged_unanswered(self):
        submissions, findings = parse_and_audit(
            row(submitted="2026-11-13 09:00", answered="",
                message="Buy cheap casino crypto now"))
        self.assertEqual(rules(findings), ["spam-pattern"])

    def test_answered_submission_is_not_flagged_unanswered(self):
        submissions, findings = parse_and_audit(
            row(submitted="2026-11-13 09:00"))
        self.assertEqual(findings, [])


class TestSummarize(unittest.TestCase):
    """Summary counts and per-form tables."""

    def test_sample_summary(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))),
            "examples", "submissions.csv")
        submissions, findings = doctor.parse_csv(path, AS_OF)
        findings.extend(doctor.audit(submissions, AS_OF))
        summary = doctor.summarize(submissions, findings, AS_OF)
        self.assertEqual(summary["submissions"], 24)
        self.assertEqual(summary["findings"], 20)
        self.assertEqual(summary["errors"], 16)
        self.assertEqual(summary["warnings"], 4)
        self.assertEqual(summary["spam"], 4)
        self.assertEqual(summary["genuine"], 20)
        self.assertEqual(summary["unanswered"], 8)
        self.assertEqual(summary["answered"], 12)
        self.assertEqual(summary["average_answer_hours"], 1.2)
        self.assertEqual(summary["spam_rate"], 16.7)
        self.assertEqual(len(summary["per_form"]), 2)
        contact = summary["per_form"][0]
        self.assertEqual(contact["form"], "Contact")
        self.assertEqual(contact["submissions"], 22)
        self.assertEqual(contact["spam"], 4)
        self.assertEqual(contact["unanswered"], 7)
        self.assertEqual(contact["answered"], 11)
        self.assertEqual(contact["average_answer_hours"], 1.2)
        quote = summary["per_form"][1]
        self.assertEqual(quote["form"], "Quote Request")
        self.assertEqual(quote["submissions"], 2)
        self.assertEqual(quote["unanswered"], 1)
        self.assertEqual(quote["answered"], 1)
        self.assertEqual(quote["average_answer_hours"], 1.0)

    def test_clean_summary(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))),
            "examples", "clean.csv")
        submissions, findings = doctor.parse_csv(path, AS_OF)
        findings.extend(doctor.audit(submissions, AS_OF))
        summary = doctor.summarize(submissions, findings, AS_OF)
        self.assertEqual(summary["submissions"], 5)
        self.assertEqual(summary["findings"], 0)
        self.assertEqual(summary["spam"], 0)
        self.assertEqual(summary["unanswered"], 0)
        self.assertEqual(summary["answered"], 5)
        self.assertEqual(summary["average_answer_hours"], 1.6)

    def test_empty_submissions(self):
        summary = doctor.summarize([], [], AS_OF)
        self.assertEqual(summary["submissions"], 0)
        self.assertEqual(summary["spam_rate"], 0.0)
        self.assertIsNone(summary["average_answer_hours"])
        self.assertEqual(summary["per_form"], [])


class TestCli(unittest.TestCase):
    """CLI behaviour, output formats, and exit codes."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()

    def tearDown(self):
        for name in os.listdir(self.directory):
            os.unlink(os.path.join(self.directory, name))
        os.rmdir(self.directory)

    def test_sample_text_output(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))),
            "examples", "submissions.csv")
        code, text = run_cli([path, "--as-of", "2026-11-18"])
        self.assertEqual(code, 0)
        self.assertIn("Submissions: 24, findings: 20, errors: 16, "
                      "warnings: 4", text)
        self.assertIn("Spam: 4, genuine: 20, unanswered: 8, "
                      "answered: 12", text)
        self.assertIn("Average time to answer: 1.2 hours, "
                      "spam rate: 16.7%", text)
        self.assertIn("Contact: 22 submissions, 4 spam, "
                      "7 unanswered, 11 answered", text)

    def test_check_exits_1_on_sample(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))),
            "examples", "submissions.csv")
        code, text = run_cli([path, "--as-of", "2026-11-18",
                              "--check"])
        self.assertEqual(code, 1)

    def test_clean_passes_check(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))),
            "examples", "clean.csv")
        code, text = run_cli([path, "--as-of", "2026-11-18",
                              "--check"])
        self.assertEqual(code, 0)
        self.assertIn("All submissions clean.", text)

    def test_warnings_only_passes_check_fails_strict(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))),
            "examples", "warnings-only.csv")
        code, text = run_cli([path, "--as-of", "2026-11-18",
                              "--check"])
        self.assertEqual(code, 0)
        code, text = run_cli([path, "--as-of", "2026-11-18",
                              "--check", "--strict"])
        self.assertEqual(code, 1)

    def test_min_seconds_flag_changes_count(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))),
            "examples", "submissions.csv")
        code, text = run_cli([path, "--as-of", "2026-11-18",
                              "--min-seconds", "1"])
        self.assertIn("findings: 19, errors: 15, warnings: 4",
                      text)

    def test_json_output(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))),
            "examples", "warnings-only.csv")
        code, text = run_cli([path, "--as-of", "2026-11-18",
                              "--json"])
        self.assertEqual(code, 0)
        report = json.loads(text)
        self.assertEqual(report["submissions"], 3)
        self.assertEqual(report["errors"], 0)
        self.assertEqual(report["warnings"], 3)
        self.assertEqual(
            [item["rule"] for item in report["findings"]],
            ["unanswered-lead", "short-message",
             "link-in-message"])
        self.assertEqual(report["per_form"][0]["form"], "Contact")

    def test_out_writes_file(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))),
            "examples", "clean.csv")
        out_path = os.path.join(self.directory, "report.txt")
        code, text = run_cli([path, "--as-of", "2026-11-18",
                              "--out", out_path])
        self.assertEqual(code, 0)
        self.assertEqual(text, "")
        with open(out_path, encoding="utf-8") as handle:
            self.assertIn("All submissions clean.", handle.read())

    def test_missing_file_exits_2(self):
        code, text = run_cli(["/no/such/file.csv"])
        self.assertEqual(code, 2)

    def test_bad_as_of_exits_2(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))),
            "examples", "clean.csv")
        code, text = run_cli([path, "--as-of", "not-a-date"])
        self.assertEqual(code, 2)

    def test_negative_min_seconds_exits_2(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))),
            "examples", "clean.csv")
        code, text = run_cli([path, "--min-seconds", "-1"])
        self.assertEqual(code, 2)

    def test_negative_max_links_exits_2(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))),
            "examples", "clean.csv")
        code, text = run_cli([path, "--max-links", "-1"])
        self.assertEqual(code, 2)

    def test_negative_unanswered_days_exits_2(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))),
            "examples", "clean.csv")
        code, text = run_cli([path, "--unanswered-days", "-1"])
        self.assertEqual(code, 2)

    def test_burst_count_below_2_exits_2(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))),
            "examples", "clean.csv")
        code, text = run_cli([path, "--burst-count", "1"])
        self.assertEqual(code, 2)

    def test_burst_hours_below_1_exits_2(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))),
            "examples", "clean.csv")
        code, text = run_cli([path, "--burst-hours", "0"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
