# Procurement Notice Monitor

This repository monitors:

- 西南联交所采购平台：四川省长江造林局六十周年纪念品采购项目
- 国家能源招标网：大渡河公司丹巴水电站相关招标信息

The GitHub Actions workflow runs every 30 minutes and sends alerts through PushPlus when new matching notices appear.
The monitor is pull-based: each run fetches the target sites directly at runtime. GitHub is only hosting the scheduled runner, secrets, and state persistence.
By default, scheduled runs are quiet:

- no change => exit 0 with no output
- transient fetch failure => exit 0 with no output
- new notice => send notification and print `Alert sent ...`

## Required GitHub Secret

Add this repository secret:

- `PUSHPLUS_TOKEN`

The token should be your PushPlus token. Do not commit it into the repository.

## Manual Run

In GitHub, open **Actions** -> **Monitor procurement notices** -> **Run workflow**.

For local debugging:

- `python outputs/monitor_swueecg_changjiang.py --verbose`
- `python outputs/monitor_swueecg_changjiang.py --verbose --fail-on-fetch-error`

## State

Known notice IDs are stored in:

- `outputs/monitor_swueecg_changjiang.state.json`

The workflow commits state updates automatically to avoid duplicate alerts.
