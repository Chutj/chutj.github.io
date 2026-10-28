# 网站访问统计：接入与长期归档

仅维护 `chutj.github.io`。不改动 SCI Figure Gallery 仓库、FIG 原始资料或图片发布流程。

## 当前状态

已根据用户提供的公共脚本标识配置 Production 采集，启用起始日期为 **2026-10-28（北京时间）**。部署后需在 Cloudflare 后台确认收到真实访问。

每日归档仍待配置账户标识及只读 API 凭据，`ANALYTICS_ENABLED` 应继续保持空或 `false`。历史记录尚为空，累计快照为 `null`，不是实际的 0 次访问。没有向首页添加计数器，没有自动创建或修改 Cloudflare 资源。

## 工作方式

- **持续采集**：Cloudflare 公共统计脚本覆盖 Home、Gallery、GEE Access 和其他公共页面。仅正式域名的 Production 构建启用；本地预览、开发构建、私有图库及候选预览不采集。
- **每日归档**：每天北京时间约 08:43，Actions 读取已结束日期的汇总。补查缺失日期，并重查最近 3 天，修正迟到数据。同一天按日期替换，不重复累加。
- **持久保存**：`analytics/history.json` 存入网站仓库，只有日期、页面浏览量、已配置页面、国家汇总及采样信息。文件在公开仓库中可见；不保存 IP、访客身份、原始请求、任意 URL、API 响应或私密 Token。
- **每月快照**：每月 1 日北京时间约 10:23，现有 Pages 工作流从已保存历史生成截至上月末的累计值，再构建网站。`data/site-analytics.json` 是供未来 Hugo 看板使用的数据；启用后还会发布为 `/site-analytics.json`，供以后前端读取。目前不改变页面外观。

每日任务只检出少量统计文件，不下载 Gallery 的图片和主题，也不构建 Hugo。它使用 `GITHUB_TOKEN` 保存小型历史文件，不会触发 `push` 部署；Pages 也忽略仅修改历史文件的推送。每月部署采用独立的 `schedule`，不依赖自动提交再触发其他工作流。

GitHub 定时任务可能延迟或漏跑；下次运行会补查。公开仓库长期无活动时，GitHub 可能停用定时任务，需要在 Actions 重新启用。运行器临时目录不承担长期存储，已提交的历史文件才是持久副本；本地可通过正常拉取仓库备份。

月度快照在构建环境中生成，不自动提交回 main，因此不会形成部署递归。本地需要同一份快照时，在拉取每日历史后执行 `snapshot --write`。

## 第一次接入（待用户确认本地改动后实施）

1. 登录 Cloudflare → **Web Analytics** → **Add a site**，填写 `chutj.github.io`，采用手动脚本接入。不需要迁移网站或修改 DNS。
2. 将 Cloudflare 给出的公共脚本标识填入 `hugo.toml` 的 `[params.webAnalytics] beaconToken`，并把 `enabled` 改为 `true`。这里只能放脚本中的公共标识，不能填私密 API Token。
3. 把 `analytics/settings.json` 的 `start_date` 设为实际启用采集的日期（北京时间），例如真实接入当天。此前的访问量不估算、不补造。
4. 核实 Cloudflare 的 **Account ID** 和 **Site tag / site ID**。`site_tag` 与脚本中的 `site_token` 是两个字段，不能假定相同；可从 Web Analytics 请求/站点详情或官方只读站点 API 核对。
5. 创建限制到该账号的自定义 API Token，权限仅为 **Account → Account Analytics → Read** 与 **Account → Account Settings → Read**。第二项用于只读核对站点 ID、域名和公共脚本标识；不要授予 DNS、RUM 修改或其他写权限。
6. 网站仓库 Settings → Secrets and variables → Actions，配置：

   | 类型 | 名称 | 值 |
   |---|---|---|
   | Variable | `CF_ANALYTICS_ACCOUNT_ID` | Cloudflare Account ID |
   | Variable | `CF_ANALYTICS_SITE_TAG` | 该站的 site_tag / site ID |
   | Secret | `CF_ANALYTICS_API_TOKEN` | 上述私密只读 API Token |
   | Variable | `ANALYTICS_ENABLED` | 初期保持空或 `false`，完成核对后设为 `true` |

   API Token 不发到聊天、不写入 TOML/JSON、不提交 Git，不进入公开前端。
7. 经用户确认后，正常提交、推送网站代码。检查正式三页都有且仅有一份公共脚本，Cloudflare 后台能收到真实访问；本地页面没有脚本。
8. 把 `ANALYTICS_ENABLED` 设为 `true`。在 Actions 的 **Archive website page views** 手动运行，先保留 `dry_run=true` 检查日期，再取消勾选写入真实归档。

首次接入当天没有完整的历史日时，显示 `collecting` 是正常状态。取数前会通过官方只读 API 核对站点与脚本，并检查正式 Home 的脚本；匹配失败、权限不足、GraphQL 字段变化或网络错误会停止，不能把错误当成 0。

**本地验证无法替代真实账号联调。** 当前没有账号标识和凭据，API 查询只经过隔离响应测试；启用前需验证真实 RUM 查询字段、返回值、权限，并与 Cloudflare 同时区、同日期、同过滤条件的后台数字比较。如 API 有差异，保持关闭并修复，不绕过校验。

## 本地命令

需要 Python 3.11+；脚本不依赖第三方 Python 包。

```powershell
# 离线预检查：不联网、不写文件、不需要凭据
python scripts/archive_web_analytics.py archive

# 查看截至上月末的累计快照，不写文件
python scripts/archive_web_analytics.py snapshot

# 配置完毕后，读取真实数据并归档（私密凭据通过进程环境提供）
python scripts/archive_web_analytics.py archive --write

# 为下一次 Hugo 构建生成累计快照
python scripts/archive_web_analytics.py snapshot --write

# 隔离测试；全部测试数字仅存在于临时测试目录
python -m unittest discover -s scripts -p test_web_analytics.py
```

自定义 `snapshot --through YYYY-MM-DD` 可生成指定已完成日期的本地快照。正式自动发布始终以上月末为截止日。存在漏日时拒绝覆盖上一份有效快照；超过 31 天待补数据、可能超出 Cloudflare 保存期限或账号/时区/开始日期变化时，需要单独检查，禁止补零或混合统计口径。

## 指标口径与失败排查

- 累计的是 **Page views / PV**，从 `start_date` 起求和，不是全网去重访客人数，也不是粉丝数。
- 按北京时间 UTC+08:00 划分日期，API 使用明确的起止时间和左闭右开区间，避免日界线重叠。
- 保留的是 Cloudflare 测量或估算的 PV。拦截插件和网络会造成漏记，部分查询有抽样；不再自行乘采样倍率。页面和国家分项可能因抽样与总数存在差异，累计总量以单独查询的全站总量为准。
- 网站没有关注功能，第三方平台粉丝数仍由现有平台看板独立维护。
- 失败后查看 Actions 对应任务的错误。历史文件和上一份有效快照保持不变，处理后可手动重跑；并发推送冲突会正常失败，不做 force push、reset 或自动合并。
- 定期核对最后归档日期、漏日和 Token 有效期。月度快照成功后，未来可在首页展示 `Total page views`、`Since`、`Updated`；目前没有新增可见看板。

## 官方依据

- [Cloudflare 手动接入](https://developers.cloudflare.com/web-analytics/get-started/)
- [保存期限、抽样与功能限制](https://developers.cloudflare.com/web-analytics/faq/)
- [GraphQL API 与只读权限](https://developers.cloudflare.com/analytics/graphql-api/getting-started/authentication/api-token-auth/)
- [站点身份只读查询及 Account Settings Read 权限](https://developers.cloudflare.com/api/resources/rum/subresources/site_info/methods/get/)
- [API count 是抽样估计值的示例](https://developers.cloudflare.com/analytics/graphql-api/features/confidence-intervals/)
- [GitHub 定时触发机制](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
- [GITHUB_TOKEN 推送不触发后续 push 工作流](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow)
