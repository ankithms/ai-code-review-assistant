# Privacy and private repositories

> **Important:** This application sends repository content to an external AI
> provider. When the configured provider is Gemini, that provider is Google.
> Connecting a private repository therefore authorizes selected private source
> code and pull-request data to leave GitHub and this application's deployment
> environment for model processing.

## Data sent to the AI provider

The application builds prompts for code reviews and generated fixes. Depending
on the operation and available context, a prompt can contain:

* pull-request diffs, file paths, branch names, commit identifiers, title, and
  description;
* relevant source from changed files, including complete enclosing functions or
  classes, imports, and related symbols;
* repository metadata, detected architecture and style information, and
  repository instruction files;
* existing review findings; and
* for fix generation, target and surrounding code plus relevant tests,
  call sites, and additional repository files selected as context.

Only context selected for the review or fix and fitted within the configured
prompt budget is sent. The application does not intentionally upload a complete
repository as one payload. This is data minimization, not a guarantee that a
particular file or secret will never be included: relevant complete functions,
classes, or files may be sent, and credentials committed in source or included
in a diff can become part of a prompt.

Model responses contain review findings and, when requested, suggested source
code changes. Those responses return to this application and may be stored and
posted to GitHub.

## External processors and retention boundaries

The default and currently supported AI provider is Google Gemini, configured
with `GOOGLE_API_KEY`, `AI_PROVIDER=gemini`, and `AI_MODEL`. Data sent to Gemini
is processed under the terms, privacy commitments, account settings, and data
retention policy that apply to the Google API account used by the operator.
Those controls can vary by service and contract and are outside this
application. Operators must verify that their provider account and selected
model are approved for the sensitivity and jurisdiction of every connected
repository before enabling reviews.

This application's cleanup settings do not delete copies held by external
systems:

* `SOURCE_SNIPPET_RETENTION_DAYS` and `REVIEW_DATA_RETENTION_DAYS` govern this
  application's database only, and only when the operator schedules the cleanup
  job described in the README.
* Review comments and suggested code posted to GitHub follow the repository's
  GitHub retention and access policies.
* Prompts, responses, and related service metadata held by the AI provider
  follow that provider account's policies and are not deleted by the local
  cleanup job.
* Deployment logs, database backups, and replicas are controlled by the
  operator and need their own access and expiry policies.

## Operator responsibilities

Before connecting a private repository, the operator should:

1. obtain authorization from the repository or organization owner to send code
   to the configured AI provider;
2. review the provider's current terms, retention, training/data-use controls,
   region, and subprocessors for the exact API account in use;
3. use least-privilege GitHub credentials and restrict dashboard access;
4. prevent secrets from being committed, rotate any secret that may have been
   included in a reviewed diff, and avoid requesting a fix for highly sensitive
   code; and
5. schedule the local retention job and apply matching limits to backups and
   logs.

Do not connect repositories whose policy prohibits external AI processing. If
the provider configuration changes in a future deployment, update this notice
and reassess the new provider before processing private code.

## Public demo

The public `/demo/` route uses hand-authored fixtures bundled with the frontend.
It does not contact GitHub, the backend, or Gemini. Private repository content
must never be copied into those fixtures.
