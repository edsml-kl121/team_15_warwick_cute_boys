# Cron worker

The worker logs the current UTC timestamp once and exits. It requires no environment variables or dependencies beyond Python.

## Run locally

Run `python3 CRON/job.py` from the repository root. The command should print one `Cron job completed at …` line and exit successfully.

## Schedule on Railway

1. Create a separate service connected to this repository and set its **Root Directory** to `/CRON` so Railway builds the included Dockerfile.
2. In **Settings → Cron Schedule**, enter `*/5 * * * *` to run every five minutes, or set your own UTC schedule.
3. Deploy the service and check its logs for the completion line after a scheduled run.

[Railway Cron Jobs](https://docs.railway.com/cron-jobs)
