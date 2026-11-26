# Good first issues

Seeded issues for new contributors. File each one on GitHub with
the `good first issue` and `help wanted` labels.

## 1. Flag forms whose spam rate is too high

Title: Warn when a form's spam rate passes a limit

Description: After the per-form summary, add a warning
finding for any form whose spam rate is above a new
--max-spam-rate flag (default 50). A form that is mostly
spam needs a honeypot or CAPTCHA, and the flag makes that
visible without reading every finding. The summary spam
rate stays as it is.

Difficulty: Easy

Acceptance criteria: the Contact form, at 18.2% spam
(4 of 22) on the sample file, is flagged when
--max-spam-rate 15 is passed and is not flagged by
default; the finding names the form and its spam rate;
JSON output gains the finding; a test checks both cases.

## 2. Report the longest-waiting unanswered lead in the summary

Title: Print the genuine lead that has waited longest

Description: Add one line to the text summary naming the
genuine unanswered lead that has waited longest
(submission id, form, hours waiting), so a site owner can
see the oldest lost lead at a glance. When no genuine
lead is unanswered, the line is omitted.

Difficulty: Easy

Acceptance criteria: the line appears for the sample file
naming F-104 at 111.0 hours; it is absent for a file
where every genuine lead is answered; JSON output is
unchanged; a test checks both cases.

## 3. Add a per-domain spam table

Title: Show which email domains send the spam

Description: Add a short table after the per-form summary
listing the email domains behind the spam submissions
(domain, spam count), sorted by count, so a site owner
can see whether the spam comes from one domain or many.
Only domains with at least one spam submission appear.

Difficulty: Easy

Acceptance criteria: the sample file shows spammy.biz
with 2 spam submissions; a clean file shows no table;
JSON output gains a per_domain list with the same
counts; a test checks both cases.

## 4. Let extra spam phrases come from a file

Title: Add a --spam-phrases-file flag for custom phrases

Description: Add a --spam-phrases-file flag that reads
one extra spam phrase per line from a file and adds them
to the built-in list, so a site owner can flag the
phrases their own spam uses without editing the code.
Blank lines and lines starting with # are ignored. A
missing file is an error that exits 2.

Difficulty: Easy

Acceptance criteria: a phrase file containing
"free iphone" flags a message with that phrase, and the
same message is not flagged without the flag; a missing
file exits 2; a test covers both cases; README documents
the flag.
