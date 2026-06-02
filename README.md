# Procurement Notice Monitor

This repository monitors:

- 西南联交所采购平台：四川省长江造林局六十周年纪念品采购项目
- 国家能源招标网：大渡河公司丹巴水电站相关招标信息

The GitHub Actions workflow runs every 30 minutes and sends alerts through PushPlus when new matching notices appear.

## Required GitHub Secret

Add this repository secret:

- `PUSHPLUS_TOKEN`

The token should be your PushPlus token. Do not commit it into the repository.

## Manual Run

In GitHub, open **Actions** -> **Monitor procurement notices** -> **Run workflow**.

## State

Known notice IDs are stored in:

- `outputs/monitor_swueecg_changjiang.state.json`

The workflow commits state updates automatically to avoid duplicate alerts.
