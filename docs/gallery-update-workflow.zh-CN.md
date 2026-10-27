# Figure Gallery 日常更新

所有命令均在网站仓库根目录执行。FIG 始终只读；导入结果、图注原文、审核材料、批次和审批文件都留在 Git 忽略的 `.gallery-local/`。网页样式无需调整。

## 1. 检查与准备

```powershell
# 完全只读：查看源文件变化和导入计划，不生成报告文件
python scripts/gallery_workflow.py prepare --dry-run

# 需要逐文件变更路径及完整诊断时
python scripts/gallery_workflow.py prepare --dry-run --json

# 更新本地图库，生成版本固定的待审核批次
python scripts/gallery_workflow.py prepare
python scripts/gallery_workflow.py status
```

默认复用现有 `settings.json` 中的 FIG 目录；迁移资料库时可指定 `--source "新目录"`。不要把网站仓库或 `.gallery-local` 指定为 FIG 源。

入口复用 `import_gallery.py`：去重、稳定 ID、增量复制、Markdown 解析、PDF/DOI/图注关联、PDF 缓存、英文候选和版权证据初筛。没有变化的 PDF 不重新解析。首次执行会建立源文件哈希基线；此时源文件清单中的 added 表示首次登记，实际新增图件数量以 importer.added 为准。

历史上直接编辑在本地 catalog 中的英文内容也会保留，但仅限原始 inventory（除 rights 字段）、图片和 PDF 关联证据全部不变。保留已有公开 rights 还必须先通过原有公开审批校验。任何源描述或证据变化均不能沿用旧批准；不会用自动导入的默认文字覆盖仍有效的人工编辑。

输出位置：

- `.gallery-local/updates/latest.json`：最新批次索引。
- `.gallery-local/updates/<batch>/REPORT.md`：中文汇总、待审核记录及失效公开绑定。
- 同目录 `report.json`：源图片/Markdown/PDF 校验值、代码变化、提案版本、诊断和完整导入结果。
- 同目录 `approval-template.json`：空的审批模板，不能直接发布。
- `.gallery-local/pdf-review.json`、`reviews/`、`english-candidates.json`：原文定位、版权初审和英文草稿。
- `.gallery-local/updates/backups/`：本轮导入将替换的本地数据原件；不删除旧图片资产。

报告中的 **needs-review** 表示仍需核对出版社许可、图件第三方权利、版本/处理方式或英文描述；**restricted** 表示自动初筛发现明确限制，仍以具体证据为准；**ready-for-human-approval** 只表示已有完整且校验通过的审核提案，不代表软件授予了转载许可。**fixable** 表示已准备提案但字段或版本绑定校验未通过，具体问题见 `proposal_errors`，修复并重新核对证据后再次 prepare，不会自动晋升为可公开。

准备模式不联网代替人工核查出版社当前条款，也不会因同一篇论文已有公开图而自动批准新图。需要时让 Codex 根据报告逐图补查官方页面、原图与署名，然后生成审核提案。缺失的英文内容只形成草稿，不能声称已经科学审核。

## 2. 审核与批准具体批次

告诉 Codex：“检查 FIG 新增内容，准备本次 Figure Gallery 更新。”检查报告后，再指定批准的图件 ID 和具体版本。

经过证据核查的发布提案放在 `.gallery-local/release-proposals.json` 的 `records` 数组中，沿用现有 `.gallery-local/publication-records.json` 的条目结构，不另建第二套卡片数据：

- `record`：现有公开字段模型，完整英文信息、作者、DOI、许可和处理说明。
- `asset`、`evidence_file`、`evidence_id`：私有根目录下的图件副本与审核证据。
- `bindings`：每条原始图件的图片 SHA、PDF 证据 SHA、catalog SHA、inventory SHA。

拟发布条目的 rights 使用待审核状态，保留完整许可字段；不能靠填写状态代替证据。prepare 只在内存中试验公开字段校验，不保存任何正式批准。正式公开 JSON 和白名单均不改变。

新增提案后重新运行 prepare。复制该批次 `approval-template.json` 为同目录 `approval.json`，由人工或收到明确批准后的 Codex 填写：

```json
{
  "batch": "从模板保留的批次ID",
  "report_sha256": "从模板保留的报告校验值",
  "approved_by": "User",
  "approved_at": "填写实际批准日期 YYYY-MM-DD",
  "confirm_noncommercial_use": true,
  "records": [
    {"id": "明确批准的ID", "proposal_sha256": "report.json中对应提案的校验值"}
  ]
}
```

不能使用模糊的“全部候选”代替明确 ID；不能自动勾选所有记录。空列表不能发布。NC 的实际用途必须人工确认；其他许可条件、版本、第三方材料、ND/SA 和署名仍须逐项核验。审批文件只是具体人工决定的记录，不是自动产生的授权。

## 3. 计划与执行发布

**当前网站使用双仓库组件同步。** 如果网站根目录存在 `gallery-component.lock.json`，不要直接运行下面的单仓库 `--execute` 命令；程序会在写入公开文件前停止。正式流程复用独立 Gallery 仓库中的现有桥接程序：

1. 用 `prepare_approved_release.py` 读取本批审批，生成位于 Website `.gallery-local/` 的版本固定公开包。
2. 在 `sci-figure-gallery` 执行 `sync_website.py capture-public --bundle <公开包目录> --reviewed`，检查并提交、普通推送独立仓库。
3. 用 `sync_website.py apply --website <网站目录> --ref <已提交的完整SHA> --release-bundle <公开包目录>` 同步网站组件及私有审批绑定。
4. 在 Website 运行测试、`check_release_snapshot.py` 和公开输出检查后，审查实际暂存文件，再 Commit、Fetch、普通 Push，并验证 Actions 和线上结果。

`private-bindings.json` 必须始终留在私有包中，不能复制到公开仓库。完整命令及职责见 [SCI Figure Gallery 维护说明](https://github.com/Chutj/sci-figure-gallery/blob/main/docs/maintainers.zh-CN.md)。上述流程不会更改 FIG 源资料，也不会发布未选记录。下面的计划命令仍可用于检查；`--execute` 仅适用于没有组件版本锁的独立网站。

```powershell
# 仅验证该审批对应的记录、版本和计划；不会写白名单、暂存、提交或联网发布
python scripts/gallery_workflow.py publish --approval ".gallery-local/updates/<batch>/approval.json"

# 只有明确批准发布后才执行：更新公开数据、测试、干净构建、Commit、Fetch、普通 Push
python scripts/gallery_workflow.py publish --approval ".gallery-local/updates/<batch>/approval.json" --execute
```

执行模式只接受报告中版本固定的提案。它复用 `export_public_gallery.prepared_record` 的审核证据/源记录绑定校验、公开 schema、媒体校验、现有全套测试和 `check_release_snapshot.py` 的干净 Git 快照构建。公开原图保持审核字节不变，只生成等比例 WebP 缩略图；当前流程继续使用已验证的 GitHub Pages 静态文件，无 OSS 上传。

批次绑定 FIG 全量输入、catalog、inventory、正式白名单、HEAD 和待提交代码字节。任何相关变化都要重新准备和审核。现有公开记录也必须仍然通过证据检查；不能通过仅批准新图绕过失效的旧审批。准备流程保留当前线上数据，不把变化的私人文件自动替换进去。

发布前检查实际 Git 文件、可疑凭据、媒体 SHA、全部署名和公开输出。只暂存该批次审核过的 Gallery 数据、图片、scripts 和 docs；Home、其他配置、删除文件、已有暂存内容需要单独处理。只在 main 和预期 origin 上运行；远程 main 必须是本地 HEAD 的祖先，绝不自动合并、重置或 force push。

更换已公开图片可能留下旧图片资源；流程不会自动删除旧版本。若媒体清单与实际文件不一致，校验会停止，先人工审查旧文件处置方案，不以放宽检查解决。

## 4. 查看失败或部署状态

```powershell
python scripts/gallery_workflow.py status
python scripts/gallery_workflow.py status --commit <完整40位CommitID>
```

每次执行发布都会留下 `.gallery-local/updates/<batch>/publish-result.json`，记录停止原因、已完成的 Commit、构建快照或推送信息。`before-publish/` 保留替换前的公开配置字节。遇到错误不自动回滚、删除、重试 Push 或修改审批；先检查 Git 状态、报告和远程状态，避免覆盖有效数据。

Push 后会按确切 Commit 查询 Actions 工作流及 jobs。短时间仍未完成或 API 不可达时，必须继续查询，并在 GitHub Actions / Pages 检查部署成功，不能把 Push 成功当成部署成功。公开 API 可能限流；不需要为本流程录入 Token。

网络/构建失败后如已有本地 Commit，不要重复批准或盲目再次执行原批次。让 Codex核对确切 SHA、远程分支和失败原因，再决定安全续推或重新准备。流程会拒绝重复执行已有 `before-publish` 的发布批次。

底层 `update-gallery.ps1`、`preview-gallery.ps1`、`export_public_gallery.py` 等入口继续保留；日常准备优先使用以上统一命令，以便留下源文件变化、批次及审批链。
