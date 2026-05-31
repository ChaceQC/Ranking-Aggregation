# 榜单抓取

这个脚本会抓取 `config.json` 中配置的 Pintia、牛客、XCPCIO 榜单，输出：

- `rankings/latest.csv`
- `rankings/latest.json`
- `rankings/latest.html`
- `rankings/latest-*.csv`
- `rankings/latest-*.json`

CSV 里会包含：

- `序号`：当前榜单展示顺序，从 1 开始。
- `队伍序号`：优先使用接口里的座位号、备注或队伍标识。
- `队伍FID`：各平台接口中的队伍唯一标识。
- 每题结果和每题提交数。

## 多比赛配置

同目录 `config.json`：

```json
{
  "contests": [
    {
      "key": "pintia-fujian-2026",
      "name": "第十三届福建省大学生程序设计竞赛 暨 2026 年 CCPC 全国邀请赛（福州）",
      "source": "pintia",
      "competition_id": "2056635464310784000",
      "team_excluded": "NO_FILTER"
    },
    {
      "key": "nowcoder-136164",
      "name": "第九届广西大学生程序设计竞赛暨 2026 邀请赛",
      "source": "nowcoder",
      "competition_id": "136164"
    },
    {
      "key": "xcpcio-provincial-contest-2026-sichuan",
      "name": "第十八届四川省大学生程序设计竞赛 - 正式赛",
      "source": "xcpcio",
      "competition_id": "provincial-contest/2026/sichuan",
      "managed_by": "xcpcio_running_contests",
      "contest_url": "https://board.xcpcio.com/provincial-contest/2026/sichuan",
      "data_url": "https://board.xcpcio.com/data/provincial-contest/2026/sichuan/",
      "start_at": "2026-05-31T09:00:00+08:00",
      "end_at": "2026-05-31T14:05:00+08:00"
    }
  ]
}
```

前端右上角会出现榜单选择框。每轮刷新会抓取配置里的所有比赛，并按比赛开始时间倒序显示。

## 自动发现

默认会自动发现并同步：

- 牛客：抓取 `topCategoryFilter=13` 和 `14` 的正在进行比赛，只写入支持赛制 `ICPC`、`IOI`、`OI`、`NOIP`、`WEEKLY` 的比赛；`WEEKLY` 会按 `IOI` 展示。
- XCPCIO：抓取 `https://board.xcpcio.com/data/index/contest_list.json`，只写入当前正在进行的比赛。

自动写入的配置会带：

- 牛客：`"managed_by": "nowcoder_running_contests"`
- XCPCIO：`"managed_by": "xcpcio_running_contests"`

下次发现时会自动更新这些自动项；已结束比赛默认保留 48 小时后再移除。手动写入且没有 `managed_by` 的比赛不会被自动发现流程删除。

关闭自动发现：

```powershell
python main.py --serve --no-discover-nowcoder --no-discover-xcpcio
```

单独设置发现间隔：

```powershell
python main.py --serve --discover-interval 300
```

单独设置自动发现已结束比赛保留时间：

```powershell
python main.py --serve --discover-keep-ended-hours 48
```

只运行牛客比赛发现并同步 `config.json`：

```powershell
python nowcoder_running_contests.py --config config.json
```

只运行 XCPCIO 比赛发现并同步 `config.json`：

```powershell
python xcpcio.py --running --config config.json --output xcpcio_running_contests.json
```

## Cookie（非必须）

把浏览器开发者工具里的请求头 `Cookie` 内容放到 `cookies.txt`：

```text
SESSION=...; other_cookie=...
```

也可以用环境变量或命令行参数：

```powershell
$env:PINTIA_COOKIE="SESSION=...; other_cookie=..."
$env:NOWCODER_COOKIE="SESSION=...; other_cookie=..."
python main.py
```

XCPCIO 公开数据接口通常不需要 Cookie。

## 运行

抓取一次：

```powershell
python main.py
```

持续更新。进行中的比赛默认 10 秒刷新一次，未开始或已结束的比赛默认 5 分钟刷新一次：

```powershell
python main.py --watch
```

启动本地网页服务，前端会无刷新读取最新 JSON 并重绘：

```powershell
python main.py --serve
```

访问：

```text
http://127.0.0.1:7877/latest.html
```

分别设置进行中和非进行中的刷新间隔：

```powershell
python main.py --serve --running-interval 10 --ended-interval 300
```

旧参数 `--interval` 仍可用，会同时覆盖这两个间隔。

保存历史快照：

```powershell
python main.py --watch --history
```

只看 Pintia 正式队：

```powershell
python main.py --team-excluded FALSE
```

## 单场抓取

临时抓单场牛客：

```powershell
python main.py --source nowcoder --competition-id 136164
```

临时抓单场 XCPCIO。`competition_id` 填 `https://board.xcpcio.com/data/` 后面的目录：

```powershell
python main.py --source xcpcio --competition-id provincial-contest/2026/sichuan
```

也可以直接给任意一个 XCPCIO 数据文件 URL：

```powershell
python main.py --source xcpcio --ranking-url https://board.xcpcio.com/data/provincial-contest/2026/sichuan/config.json
```

单独转换 XCPCIO 四个数据接口为 `main.py` 可渲染的 JSON：

```powershell
python xcpcio.py --competition-id provincial-contest/2026/sichuan --output rankings/latest-xcpcio-sichuan-2026.json
```

## 日志

运行时会打印抓取过程日志，包括：

- 获取比赛列表：牛客/XCPCIO 自动发现时的来源 URL。
- 获取排名：当前抓取的平台、比赛 ID、比赛名称。
- 获取数据源：Pintia 排名 URL、牛客分页、XCPCIO 数据目录。
- 排名解析完成：解析出的队伍数量。

PowerShell 建议使用 UTF-8：

```powershell
$env:PYTHONIOENCODING="utf-8"
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
python main.py --serve
```
