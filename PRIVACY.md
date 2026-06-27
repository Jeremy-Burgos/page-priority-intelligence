# Privacy

## Summary

Page Priority Intelligence processes your data locally and does not retain it. Uploaded
CSVs are held in memory only for the duration of a scoring run and are not written to disk
by the application. There is no telemetry, no analytics, and no transmission of your data
to any third party in this version.

## What data is involved

To produce a report the tool reads the CSV exports you provide: Screaming Frog crawl data,
Search Console clicks and impressions, GA4 sessions and conversions, backlink counts,
PageSpeed metrics, and URL Inspection verdicts. These files can contain commercially
sensitive information about your site's structure, traffic, and revenue. The tool treats
them only as inputs to the score.

## How uploads are handled

In the Streamlit interface, uploaded files are read directly from the in-memory upload
buffer and parsed into data structures in memory. The application does not save the
uploaded files to disk. When the run completes and the session ends, that in-memory data
is released by the process.

The repository `.gitignore` additionally excludes the `uploads/` and `outputs/` directories
so that, if you choose to save files there manually, they are not accidentally committed to
version control.

## Outputs

The scored master CSV and the unmatched-rows CSV are generated for you to download. Once
downloaded, those files live wherever you save them and are under your control. The
application does not keep a copy. Delete them when you no longer need them, and store them
with the same care as the source exports.

## No external transmission

This CSV-only version makes no outbound API calls and sends no data off your machine.
Nothing you upload is shared with the maintainer, with Anthropic, or with any analytics or
logging service.

## Future phases

A later phase will offer direct pulls from the Google APIs using your own credentials. That
is an opt-in feature that you would configure and authorize yourself. It does not change the
handling described here for the CSV workflow, and any live-pull behavior will be documented
before it ships.

## Your responsibilities

Because the data stays on your machine, its protection is ultimately yours. Run the app on
a trusted device, do not expose the local Streamlit port to untrusted networks, and dispose
of input and output files securely when you are done.
