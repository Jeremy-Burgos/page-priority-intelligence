# Security

## Scope

Page Priority Intelligence is a local-first application. It runs on your machine, reads
CSV files you provide, and writes output files you download. In this CSV-only phase it
makes no outbound network calls, holds no credentials, and exposes no server beyond the
local Streamlit instance you start yourself.

The most relevant security considerations are therefore local: who can reach the Streamlit
port while it is running, and what happens to the input and output files on your disk.

## Reporting a vulnerability

If you find a security issue, do not open a public issue with exploit details. Report it
privately to the maintainer through the repository's private contact channel or a direct
message to the maintainer. Include the affected file or component, a description of the
issue, and clear reproduction steps. You will receive an acknowledgement, and fixes for
confirmed issues will be prioritized over feature work.

Please allow a reasonable window for a fix before any public disclosure.

## Running the app safely

Streamlit binds to a local address by default. Do not expose the Streamlit port to an
untrusted network or the public internet. If you need remote access, place it behind an
authenticated reverse proxy or a VPN rather than opening the port directly.

Treat the CSVs you upload as sensitive. Search Console, GA4, and crawl exports can reveal
your site structure, traffic, and revenue signals. The output report concentrates that
information into one file. Store both inputs and outputs accordingly and delete them when
you no longer need them.

## Credential handling

This version handles no API credentials and requires none to run. The only configuration
value it reads is `PPI_SITE_DOMAIN`, which is not a secret.

The commented entries in `.env.example` are placeholders for a future phase that will pull
data directly from the Google APIs. When that phase ships, credentials must be supplied
through environment variables or a local `.env` file that is never committed. The provided
`.gitignore` already excludes `.env`. Do not hardcode keys in source, do not paste them
into the Streamlit interface, and do not commit them. Rotate any key that is exposed.

## Dependencies

Dependencies are pinned in `requirements.txt`. Review and update them periodically, and
check for advisories against pandas, numpy, pydantic, and streamlit before deploying in
any shared environment.
