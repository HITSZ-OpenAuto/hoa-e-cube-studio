# 深圳 E立方工作室 · 资料栈镜像

「E立方」学风涵养工作室资料栈的 GitHub 镜像，同时是 [hoa.moe](https://hoa.moe) 站点「站外资料」板块的数据源。

> 资料栈由信息学部「E立方」学风涵养工作室与 HITSZ 开源技术协会筹备与管理。
> 工作室早期曾以「程序援」名义开展活动，该名称为历史旧称，现统一称「E立方」。

## 这是什么

资料栈原始形态是一个部署在校内网 [Alist](https://alist.nn.ci/) 上的网盘目录。网盘直链依赖校园网、签名易失效，也无法被搜索引擎索引。

本仓库把资料栈里**适合公开分发**的部分镜像成普通 Git 仓库：

- 站点从 `worktree` 分支的文件清单渲染资料树；
- 每个文件都有一条经 `gh.hoa.moe` 网关加速的直链，点开即下；
- 超过 GitHub 单文件上限的资料**不入库**，但在清单中登记原地址，点击跳回资料栈。

站内入口：<https://hoa.moe/resources/e-cube>

## 目录结构

```
hoa-e-cube-studio/
├── README.md               # 本文件
├── LICENSE                 # 资料使用声明
├── resources.json          # 站点读取的元信息 + 未入库文件的原地址清单
├── .sync-state.json        # 同步状态（记录每个文件的源端时间，用来判断增量）
├── docs/                   # 资料栈自身的说明与图片
├── 学业辅导/                # 各科学习方法分享、学业帮扶讲座回放与笔记
├── 生涯规划/                # 生涯规划讲座、港校分享、经验分享
└── scripts/
    ├── sync-alist.py       # 从资料栈同步（校园网运行）
    ├── sync-and-push.sh    # 同步 + 提交 + 推送 + 触发站点构建
    └── update-worktree.py  # 重新生成 worktree 分支的文件清单
```

## 收录策略

| 类型 | 处理方式 | 站内表现 |
| --- | --- | --- |
| 单文件 ≤ 50 MiB | 镜像入库 | 清单中列出，站内直链下载 |
| 单文件 > 50 MiB | 不入库 | 清单中列出，标注「原站」，点击跳转资料栈原地址 |

站内镜像共约 900 MB、388 个文件（讲义、笔记、课件、试题、教材等）；
跳原地址的 31 个主要是各科讲座的整场录像与两本大部头教材，
需连接校园网或学校 VPN 下载，这是资料栈本身的部署位置决定的。

GitHub 单文件硬限制是 100 MiB，这里取 50 MiB 是留一半余量，
让仓库克隆与 CI 都不至于太慢。

## 自动化链路

```
Alist 资料栈（校内网）
        │  scripts/sync-alist.py（校园网机器执行）
        ▼
本仓库 main 分支 ──push──▶ GitHub Actions
                                │  scripts/update-worktree.py
                                ▼
                          worktree 分支（worktree.json）
                                │
                                ▼
                    hoa.moe 构建时 scripts/fetch-resources.mjs
                                │
                                ▼
                       hoa.moe/resources/e-cube
```

资料栈部署在校内网，GitHub Actions 的 runner 访问不到，因此**下载这一步必须在校园网内完成**；提交之后的清单生成与站点渲染都在 CI 里自动完成。

### 日常同步

在校园网机器上：

```bash
export ALIST_USERNAME='<账号>'
export ALIST_PASSWORD='<密码>'
./scripts/sync-and-push.sh
```

脚本会增量下载（体积变化才重新下载）、清理资料栈里已删除的文件、更新 `resources.json`，然后提交并推送。推送后 `update-worktree.yml` 自动重新生成 `worktree` 分支，站点在下一次构建时即可看到最新内容。

也可手动触发一次同步（只跑下载与清单，不提交）：

```bash
python3 scripts/sync-alist.py --dry-run   # 只看会变什么
python3 scripts/sync-alist.py             # 实际同步，不提交
```

### 凭据

账号密码只通过环境变量传入，**不要**写进仓库。资料栈部署在校内网，访问本身也需要校园网，因此没有把凭据放进 CI secrets；如需让定时任务无人值守运行，请在自有的校园网机器上配置 cron 调用 `sync-and-push.sh`。

## 资料栈原站

- 地址：<http://10.249.44.116:5244/>（校内网）
- 账号凭据：通过工作室内部渠道分发，**本仓库与站点均不公开**
- 内容板块：创新创业、学业辅导、生涯规划

工作坊原文说明见 [`docs/资料栈说明.md`](docs/资料栈说明.md)。

## 反馈与交流

- 建议与想法：填写[用户反馈问卷](https://docs.qq.com/form/page/DUnJtSEdKaEJpUXVT)
- 最新通知：QQ 群 537014050

## 许可与署名

资料版权归原作者及「E立方」学风涵养工作室所有，详见 [LICENSE](LICENSE)。转载或二次整理时请注明来源：**E立方学风涵养工作室（信息学部）× HITSZ 开源技术协会**。
