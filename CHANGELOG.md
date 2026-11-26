# Changelog

## 1.0.0 - 2026-11-22

Initial release.

* Form submissions audit over a WordPress form entries CSV
  export: spam patterns (known spam phrases, keyword
  stuffing, all-caps messages), link drops, submissions
  too fast for a human (same email or IP), duplicate
  submissions, submission bursts, and genuine leads left
  unanswered past the limit.
* Per-form scoring: submissions, spam, unanswered leads,
  answered leads, and average time to answer, with a
  spam rate and an overall average answer time.
* Data quality checks: duplicate and missing submission
  ids, missing and invalid emails, malformed rows,
  invalid timestamps, future timestamps, and impossible
  date orderings.
* Defensive timestamp parsing (ISO 8601 with or without
  a timezone, plus common day/month/year forms); a bad
  row is reported as a finding and never crashes the
  run. UTF-8 BOM headers and extra columns handled.
* Findings carry a submission id, a rule name, a severity
  (error or warning), and a message; errors and warnings
  are counted in the summary.
* Text and --json output, --out file output,
  --min-seconds, --max-links, --unanswered-days,
  --min-words, --burst-count, --burst-hours, and --as-of
  thresholds, and a --check CI gate that exits 1 on
  errors (and on warnings with --strict).
* Zero dependencies, Python 3.10 or newer.
