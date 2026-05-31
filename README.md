# 榜单抓取

这个脚本会抓取 `config.json` 中配置的 Pintia/牛客 XCPC 榜单，输出：

- `rankings/latest.csv`
- `rankings/latest.json`
- `rankings/latest.html`
- `rankings/latest-*.csv`
- `rankings/latest-*.json`

CSV 里已经添加：

- `序号`：当前榜单展示顺序，从 1 开始。
- `队伍序号`：优先使用接口里的 `teamInfo.remark`，没有时回退到 `teamFid`。
- `队伍FID`：Pintia 接口中的队伍标识。

## 多比赛配置

同目录 `config.json`：

```json
{
  "contests": [
    {
      "key": "pintia-fujian-2026",
      "name": "第十三届福建省大学生程序设计竞赛 暨2026年CCPC全国邀请赛（福州）",
      "source": "pintia",
      "competition_id": "2056635464310784000",
      "team_excluded": "NO_FILTER"
    },
    {
      "key": "nowcoder-guangxi-2026",
      "name": "第九届广西大学生程序设计大赛暨2026邀请赛",
      "source": "nowcoder",
      "competition_id": "136164"
    }
  ]
}
```

前端右上角会出现榜单选择框。每轮刷新会抓取配置里的所有比赛。

默认会额外抓取牛客 `topCategoryFilter=13` 和 `14` 的正在进行比赛，只把榜单接口里
`rankType` 为 `ICPC`、`IOI`、`OI`、`NOIP` 或 `WEEKLY` 的比赛同步进 `config.json`，其中 `WEEKLY` 会按 `IOI` 标注和显示。自动写入的牛客比赛会带
`"managed_by": "nowcoder_running_contests"`，下次发现时会自动更新；已结束比赛默认保留
48 小时后再移除。手动写的 Pintia 或牛客比赛不会被删除。

## Cookie

把浏览器开发者工具里请求头的 `Cookie` 内容放到 `cookies.txt`：

```text
SESSION=...; other_cookie=...
```

也可以用环境变量或命令行参数：

```powershell
$env:PINTIA_COOKIE="SESSION=...; other_cookie=..."
$env:NOWCODER_COOKIE="SESSION=...; other_cookie=..."
python main.py
```

## 运行

抓取一次：

```powershell
python main.py
```

定时更新。进行中的比赛默认 10 秒更新一次，未开始或已结束的比赛默认 5 分钟更新一次：

```powershell
python main.py --watch
```

然后打开 `rankings/latest.html`，页面会按当前选择比赛自己的间隔自动刷新。
页面里的搜索框会按学校或队名把匹配队伍置顶并高亮，不会隐藏其它队伍。

推荐用本地网页服务打开，这样前端可以不刷新整页，直接读取最新数据重绘：

```powershell
python main.py --serve
```

地址：`http://127.0.0.1:7877/latest.html`
HTML 的倒计时和前端刷新间隔会跟比赛状态同步。可以分别设置进行中和非进行中的刷新间隔：

```powershell
python main.py --serve --running-interval 10 --ended-interval 300
```

旧的 `--interval` 仍可用，会同时覆盖这两个间隔。
牛客正在进行比赛的发现间隔默认 300 秒，可以单独设置：

```powershell
python main.py --serve --discover-interval 300
```

已结束的自动发现比赛默认保留 48 小时，可以单独设置：

```powershell
python main.py --serve --discover-keep-ended-hours 48
```

如需关闭自动发现：

```powershell
python main.py --serve --no-discover-nowcoder
```

同时保存历史快照：

```powershell
python main.py --watch --history
```

只看正式队：

```powershell
python main.py --team-excluded FALSE
```

临时抓单场牛客：

```powershell
python main.py --source nowcoder --competition-id 136164
```

临时抓单场 XCPCIO，`competition_id` 填 `https://board.xcpcio.com/data/` 后面的目录：

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

只列出 XCPCIO 当前正在进行的比赛：

```powershell
python xcpcio.py --running --output xcpcio_running_contests.json
```

只运行牛客比赛发现并同步 `config.json`：

```powershell
python nowcoder_running_contests.py --config config.json
```
