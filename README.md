# wp-form-doctor

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/aamirtechs/wp-form-doctor/blob/main/LICENSE) [![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/aamirtechs/wp-form-doctor/issues)

A zero-dependency Python CLI that audits a WordPress form
submissions CSV export for spam patterns, link drops,
submissions too fast for a human to type, duplicate
submissions, bursts from one sender, and genuine leads
that were never answered. It also scores every form
(submissions, spam, unanswered leads, and average time
to answer) and flags the forms that are leaking leads or
drowning in spam.

69% of WordPress sites are attacked through form
submissions, and AI bot attacks are up 12.5x year over
year, per the Imperva 2026 Bad Bot Report. Akismet,
honeypots, and reCAPTCHA block spam live, before it
reaches the inbox. But nobody audits the entries export
afterwards to say which genuine leads sat unanswered for
days, which spam slipped past the live filters, and which
bot hammered the form at three in the morning. This tool
is that audit: it reads the export alone, and never
touches your WordPress site.

## Install

Requires Python 3.10 or newer. No dependencies beyond the
standard library.

```bash
pip install wp-form-doctor
```

Or run it straight from the source checkout:

```bash
python3 wp_form_doctor.py examples/submissions.csv
```

## Input format

A CSV export with a header row, from WPForms, Gravity
Forms, Contact Form 7 with a database plugin, or a manual
export. Columns used: `submission_id` (or `id`,
`entry_id`), `form` (or `form_name`), `name` (or
`full_name`, `your_name`), `email` (or `email_address`),
`message` (or `message_text`, `your_message`, `comments`),
`submitted_at` (or `created_at`, `submitted`, `date`,
`created`), `answered_at` (or `replied_at`, `answered`,
`replied`, `reply_date`), and `ip` (or `ip_address`).
Extra columns are ignored, so a full entries export works
as-is. A UTF-8 BOM header is handled. Only
`submission_id`, `email`, and `submitted_at` are required;
the other columns are optional, and the checks that need
a missing column are skipped.

Dates accept ISO 8601 with or without a timezone
(`2026-11-17 10:00`, `2026-11-17T10:00:00Z`,
`2026-11-17`), plus day/month/year and month/day/year
forms. A date with no timezone is read as UTC. A
submission with no `answered_at` counts as unanswered.

```csv
submission_id,form,name,email,message,submitted_at,answered_at,ip
F-101,Contact,Sarah Miller,sarah@example.com,"Hi, I need a quote for a new company website with five pages. Please email me your pricing.",2026-11-17 09:00,2026-11-17 10:30,203.0.113.10
F-102,Contact,John Carter,john@example.com,"Can you fix my slow WordPress site? It takes ten seconds to load.",2026-11-16 09:00,2026-11-16 12:00,203.0.113.11
F-103,Quote Request,Priya Nair,priya@example.com,"Please send a quote for an online store with twenty products and payment setup.",2026-11-14 09:00,,203.0.113.12
F-104,Contact,David Lee,david@example.com,"I would like help moving my blog to a new host next week.",2026-11-13 09:00,,203.0.113.13
F-105,Contact,Spam Bot,seo@spammy.biz,"Buy cheap SEO services guaranteed ranking number one Google fast results",2026-11-17 08:00,,198.51.100.5
```

## What it checks

Errors, the ones that mean a lead is lost now or data
that cannot be trusted:

* `spam-pattern`: a message matching a known spam phrase
  (`buy cheap`, `seo services`, `guaranteed ranking`,
  `casino`, `crypto`, and others), repeating one word 4
  or more times (keyword stuffing), or written entirely
  in capital letters.
* `link-drop`: a message with more than `--max-links`
  (default 2) links.
* `too-fast-submission`: a submission arriving less than
  `--min-seconds` (default 5) after the previous one from
  the same email or IP address, faster than a human can
  type.
* `duplicate-submission`: the same sender sending the
  same message twice.
* `unanswered-lead-overdue`: a genuine lead (not spam)
  with no answer, older than `--unanswered-days`
  (default 3).
* `duplicate-submission-id`: the same submission id
  twice in the export.
* `missing-submission-id`: a row with no submission id,
  so the submission cannot be matched to a form.
* `missing-email`: a submission with no email, so it
  cannot be answered or matched to a sender.
* `invalid-email`: an email address that is not a valid
  address.
* `invalid-timestamp`: a date field that matches no known
  format. The row is still audited on the fields that did
  parse.
* `future-timestamp`: a `submitted_at` after `--as-of`
  (default now).
* `impossible-dates`: an answered date before the
  submission was made.
* `malformed-row`: a row with the wrong number of fields.
  The row is skipped and reported, never a crash.

Warnings, submissions worth a second look:

* `unanswered-lead`: a genuine lead with no answer that
  has waited more than 24 hours but is still inside the
  unanswered limit.
* `link-in-message`: a message with 1 to `--max-links`
  links, so check it before replying.
* `submission-burst`: a sender reaching `--burst-count`
  (default 3) submissions inside `--burst-hours`
  (default 24).
* `short-message`: a message with fewer than
  `--min-words` (default 3) words.
* `empty-message`: a submission with no message at all,
  so there is nothing to answer.

The summary reports the submission count, the spam and
genuine counts, the unanswered and answered counts, the
average time to answer, the spam rate, and a per-form
table (submissions, spam, unanswered, answered, and
average time to answer).

## Usage

```bash
python3 wp_form_doctor.py examples/submissions.csv --as-of 2026-11-18
```

Captured output:

```
ERROR [invalid-timestamp] F-113: submitted date 'not-a-date' is not a readable date
ERROR [future-timestamp] F-114: submitted date 2026-12-01 09:00 is after the as-of date 2026-11-18 00:00
ERROR [impossible-dates] F-115: answered date 2026-11-16 09:00 is before the submission was made 2026-11-17 10:00
ERROR [duplicate-submission-id] F-101: submission id appears more than once in the export
ERROR [malformed-row] row 18: row has 9 fields but the header has 8, so the row was skipped
ERROR [missing-submission-id] row 19: row has no submission id, so the submission cannot be matched to a form
ERROR [missing-email] F-117: submission has no email, so it cannot be answered or matched to a sender
ERROR [invalid-email] F-118: email 'not-an-email' is not a valid email address
ERROR [unanswered-lead-overdue] F-103: genuine lead has waited 87.0 hours with no answer, past the 3 day limit
ERROR [unanswered-lead-overdue] F-104: genuine lead has waited 111.0 hours with no answer, past the 3 day limit
ERROR [spam-pattern] F-105: message contains the spam phrase 'buy cheap'
ERROR [link-drop] F-106: message contains 3 links, past the 2 link limit
ERROR [too-fast-submission] F-108: submission arrived 3 seconds after the previous one from the same sender, faster than the 5 second minimum for a human
ERROR [duplicate-submission] F-110: the same sender sent the same message before, so this is a duplicate submission
WARNING [unanswered-lead] F-110: genuine lead has waited 38.0 hours with no answer
WARNING [short-message] F-111: message has only 1 word, past the 3 word minimum, so it may be a throwaway submission
WARNING [link-in-message] F-112: message contains 1 link, so check it before replying
WARNING [submission-burst] F-121: this is submission 3 from this sender within 24 hours
ERROR [spam-pattern] F-122: message is written entirely in capital letters
ERROR [spam-pattern] F-123: message repeats the word 'website' 4 times, which reads as keyword stuffing

Submissions: 24, findings: 20, errors: 16, warnings: 4
Spam: 4, genuine: 20, unanswered: 8, answered: 12
Average time to answer: 1.2 hours, spam rate: 16.7%

Per-form summary:
Contact: 22 submissions, 4 spam, 7 unanswered, 11 answered, average answer 1.2 hours
Quote Request: 2 submissions, 0 spam, 1 unanswered, 1 answered, average answer 1.0 hours
```

The sample has 25 rows; the malformed row 18 is skipped,
so 24 submissions are audited. The headline numbers are
4 spam submissions (a spam phrase, a 3-link drop, an
all-caps message, and keyword stuffing), 2 genuine leads
left unanswered past the 3 day limit at 87.0 and 111.0
hours, 1 submission 3 seconds after the previous one
from the same sender, 1 duplicate submission, and 1
burst of 3 submissions from one sender in 24 hours. The
Contact form carries all 4 spam submissions and 7 of the
8 unanswered leads.

Use it as a CI gate: `--check` exits 1 when any error is
found, and 0 otherwise. On the sample above it exits 1:

```bash
python3 wp_form_doctor.py examples/submissions.csv --as-of 2026-11-18 --check
```

On `examples/clean.csv`, five clean submissions, it
exits 0:

```
Submissions: 5, findings: 0, errors: 0, warnings: 0
Spam: 0, genuine: 5, unanswered: 0, answered: 5
Average time to answer: 1.6 hours, spam rate: 0.0%

Per-form summary:
Contact: 4 submissions, 0 spam, 0 unanswered, 4 answered, average answer 1.6 hours
Quote Request: 1 submissions, 0 spam, 0 unanswered, 1 answered, average answer 2.0 hours

All submissions clean.
```

With `--strict`, `--check` also fails on warnings.
`examples/warnings-only.csv` has one unanswered lead
waiting 39.0 hours, one one-word message, and one
message with a single link, so it passes `--check`
(exit 0) and fails `--check --strict` (exit 1).
With a 1 second minimum the too-fast flag drops out:

```bash
python3 wp_form_doctor.py examples/submissions.csv --as-of 2026-11-18 --min-seconds 1
```

Captured output (only the summary is shown below; the
F-108 too-fast line is gone and the rest of the output
is identical to the default run):

```
Submissions: 24, findings: 19, errors: 15, warnings: 4
Spam: 4, genuine: 20, unanswered: 8, answered: 12
Average time to answer: 1.2 hours, spam rate: 16.7%

Per-form summary:
Contact: 22 submissions, 4 spam, 7 unanswered, 11 answered, average answer 1.2 hours
Quote Request: 2 submissions, 0 spam, 1 unanswered, 1 answered, average answer 1.0 hours
```

`--json` emits the summary and the findings as JSON, and
`--out` writes the report to a file. JSON for the
warnings-only file:

```json
{
  "submissions": 3,
  "findings": [
    {
      "submission": "F-401",
      "rule": "unanswered-lead",
      "severity": "warning",
      "message": "genuine lead has waited 39.0 hours with no answer"
    },
    {
      "submission": "F-402",
      "rule": "short-message",
      "severity": "warning",
      "message": "message has only 1 word, past the 3 word minimum, so it may be a throwaway submission"
    },
    {
      "submission": "F-403",
      "rule": "link-in-message",
      "severity": "warning",
      "message": "message contains 1 link, so check it before replying"
    }
  ],
  "errors": 0,
  "warnings": 3,
  "spam": 0,
  "genuine": 3,
  "unanswered": 1,
  "answered": 2,
  "average_answer_hours": 0.8,
  "spam_rate": 0.0,
  "per_form": [
    {
      "form": "Contact",
      "submissions": 1,
      "spam": 0,
      "unanswered": 0,
      "answered": 1,
      "average_answer_hours": 0.5
    },
    {
      "form": "Quote Request",
      "submissions": 2,
      "spam": 0,
      "unanswered": 1,
      "answered": 1,
      "average_answer_hours": 1.0
    }
  ]
}
```

## Options

| Flag | Meaning |
| --- | --- |
| `--min-seconds` | Submissions from the same sender faster than this many seconds apart are too fast for a human (default: 5) |
| `--max-links` | A message with more links than this is a link drop (default: 2) |
| `--unanswered-days` | A genuine lead unanswered longer than this many days is overdue (default: 3) |
| `--min-words` | A message with fewer words than this is a short message (default: 3) |
| `--burst-count` | A sender with this many submissions in the burst window is bursting (default: 3) |
| `--burst-hours` | The burst window in hours (default: 24) |
| `--as-of` | Date to compare timestamps against, for example 2026-11-18 (default: now) |
| `--json` | Emit JSON instead of text |
| `--check` | Exit 1 if any error is found |
| `--strict` | With --check, also exit 1 on warnings |
| `--out` | Write the report to a file |

## Edge cases

* A row with too many or too few fields is a malformed-row
  error and is skipped; the rest of the file is still
  audited.
* A bad date is an error, and the row is still audited on
  the fields that did parse, so one bad value never hides
  the other problems on the submission. A submission with
  an unreadable submitted date is left out of the age and
  average calculations, and a submission with a negative
  answer time is left out of the averages (the
  impossible-dates error already covers it).
* The average time to answer counts only genuine
  submissions created on or before `--as-of`, so a
  future-dated submission never pulls the average
  forward, and spam submissions never count as answered
  leads.
* The unanswered checks only fire for genuine leads, so
  spam, link drops, and duplicates are never counted as
  lost leads. A submission with no readable submitted
  date cannot be aged, so it is counted in the summary
  unanswered total but gets no overdue or waiting
  finding.
* The too-fast check groups by email and by IP, so a bot
  that rotates addresses but keeps one IP is still
  caught, and a bot that rotates IPs but keeps one
  address is still caught. Two submissions with the exact
  same timestamp count as 0 seconds apart.
* The duplicate check compares the sender email and the
  message text, lowercased with whitespace collapsed, so
  a resubmitted message with different capitalisation
  still matches. A submission with no email or no message
  is never called a duplicate.
* The spam phrase list is a starting point, not a
  blocklist: a genuine message that happens to contain
  one of the phrases is flagged, so review the findings
  before deleting anything.
* A blank line in the file is skipped silently.
* `--as-of` makes runs reproducible: without it, the
  future-timestamp and unanswered-lead checks compare
  against the current time.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

80 tests, all passing: timestamp parsing, link counting,
spam detection (phrases, keyword stuffing, all-caps, and
the clean cases), header aliases and BOM handling,
malformed rows, duplicate and missing submission ids,
missing and invalid emails, invalid timestamps, future
timestamps, impossible date orderings, too-fast
submissions with the boundary and the IP grouping,
link drops with the boundary, duplicate submissions,
submission bursts, short and empty messages, unanswered
leads with the overdue boundary and the warning window,
spam excluded from the unanswered checks, summary totals
and per-form tables, text and JSON output, `--out` file
output, `--min-seconds`, `--max-links`,
`--unanswered-days`, `--min-words`, and `--burst-count`
flags, and `--check` and `--strict` exit codes. The same
80 tests pass under pytest.

## License

MIT. See [LICENSE](LICENSE).
