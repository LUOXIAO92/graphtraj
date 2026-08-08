可以。现在这套 **V1 纯 Agent Harness** 已经比较完整了，它的核心不是做一个硬编码 orchestrator，而是先用 **Master + Custom Agents + Skills + Hooks + Git Worktrees** 把职责、权限和状态流跑通。

## 1. 总体架构

```text
                         Master Agent
                         Sol xhigh
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
     Planning            Execution          Integration
         │                   │                   │
   grill 用户          ticket 分级          merge 排序
   文档理解                  │                   │
   $to-spec                  │                   │
   spec 对齐        ┌────────┼────────┐          │
   $to-tickets      ▼        ▼        ▼          │
                 Junior    Senior   Expert       │
                 Luna H    Terra H   Sol XH      │
                    │        │        │           │
                    └──── $implement ─┘           │
                             │                    │
                       $code-review               │
                       ┌─────┴─────┐              │
                       ▼           ▼              │
                   Standards      Spec            │
                    reviewer    reviewer          │
                             │                    │
                        reviewed commit ──────────┘
                                                  │
                                                  ▼
                                                 dev
                                                  │
                                          conflict / failure
                                                  │
                                                  ▼
                                           Merge Resolver
                                              Sol xhigh
```

**Master 是 control plane。**

目前没有硬 orchestrator，也不需要假装已经有。Master 就是用户正在交互的 Sol xhigh 主窗口。

---

## 2. Git / Worktree 模型

你的 Git 结构已经定成：

```text
main
└── 版本发布 / version update

dev
└── 日常开发的 integration branch
    ├── dev-ticket-a    Engineer worktree
    ├── dev-ticket-b    Engineer worktree
    ├── dev-ticket-c    Engineer worktree
    └── dev-ticket-d    Engineer worktree
```

边界：

```text
main
→ release 层
→ 不参与日常 multi-agent integration

dev
→ 唯一 development integration state

dev-*
→ Engineer 的隔离 implementation worktree
```

Engineer 通过 commit 向 Master 交付结果，而不是跨 worktree 直接协作。

---

# 3. Master Agent

模型：

```text
Sol xhigh
```

Master 当前负责：

```text
用户交互 / grill
复杂文档理解
$to-spec
spec alignment
$to-tickets

ticket dependency 判断
ticket complexity classification

Engineer dispatch
review failure 计数
escalation

integration queue
merge 顺序
integration validation

merge-resolver dispatch

长上下文 handoff 决策（V1 人工辅助）
```

Master **不负责**：

```text
❌ 普通 ticket implementation
❌ 自己替 Engineer 修 review
❌ 自己解决 merge conflict
```

Master 可以跨 worktree 做协调，所以：

> **Master 不挂 worktree isolation hook。**

---

# 4. 三档 Engineer

三者行为逻辑基本一致，只通过模型能力分级。

```text
engineer-junior
Luna high

engineer-senior
Terra high

engineer-expert
Sol xhigh
```

Routing：

```text
简单、明确、重复
→ Junior

中等复杂度、需要较广代码推理
→ Senior

极复杂 / 高歧义 / 架构敏感
→ Expert
```

三个 Engineer 的 developer instruction 不需要人格化，也不需要重复 SOP。

核心只是：

```text
执行当前 ticket
→ 使用 $implement
→ 只能待在当前 worktree
→ ticket/spec 是 settled scope
```

真正 implementation workflow 全部委托：

```text
$implement
    ↓
TDD
tests
typecheck
full suite
    ↓
$code-review
    ↓
commit
```

所以 Engineer prompt 不重新描述 Matt Pocock 已经维护的 SOP。

---

# 5. Reviewer 模型

`$implement` 内部会调用 `$code-review`。

当前规则：

```text
Junior
  implementation = Luna high
  review = Terra xhigh

Senior
  implementation = Terra high
  review = Terra xhigh

Expert
  implementation = Sol xhigh
  review = Sol xhigh
```

所以 Engineer agent TOML 中通过：

```toml
[agents]
default_subagent_model = "..."
default_subagent_reasoning_effort = "..."
```

控制它下面 `$code-review` spawn 出来的 reviewer 默认能力。

Review 仍然按照 Matt skill：

```text
Standards reviewer
+
Spec reviewer
```

Engineer 自己不拥有：

> “我的实现已经通过 review。”

这个裁决权。

---

# 6. Escalation

当前规则已经很明确：

```text
review FAIL
→ Engineer 修复
→ 再 review

连续 3 次 review FAIL
→ Master escalation
```

注意统计的是：

```text
✅ review failure
```

不是：

```text
❌ TDD 初始红灯
❌ typecheck 中途失败
❌ 普通测试修复循环
```

升级：

```text
Junior ×3
→ Senior fresh context

Senior ×3
→ Expert fresh context

Expert ×3
→ Master / 用户层异常处理
```

关键原则：

> **升级不继承旧 Agent conversation。**

但保留 canonical work state：

```text
ticket
spec
repository / current diff
tests
review findings
commit/state
```

不保留：

```text
旧 Agent conversation
旧 Agent reasoning
旧 Agent 的主观总结
```

也就是：

> fresh cognition, persistent work state.

---

# 7. Engineer Worktree Isolation

这是目前最重要的 safety harness 之一。

因为你已经实际观察到 subagent 会尝试：

```text
跑去 sibling worktree
读取那里代码
甚至修改那里文件
```

所以 Engineer 使用两层约束。

第一层是 developer instruction：

```text
Work exclusively inside the current worktree.
Do not navigate to, inspect for implementation purposes,
modify, or run commands in another worktree.
```

第二层是真正的：

```text
PreToolUse worktree_guard
```

拦：

```text
cd ../dev-other
git -C ../dev-other ...
cp → sibling worktree
rm sibling path
apply_patch sibling path
各种显式跨 worktree command
```

关键：

> **Hook 注册在 Engineer custom-agent TOML 中，而不是全局 `.codex/hooks.json`。**

否则 Master 也会被锁死。

---

# 8. Engineer 权限模型

Engineer 需要真实网络测试，所以目前：

```toml
sandbox_mode = "workspace-write"
approval_policy = "never"

[sandbox_workspace_write]
network_access = true
```

语义：

```text
当前 workspace/write
→ 预先允许

network
→ 预先允许

sandbox 外操作
→ 不询问
→ 直接失败
```

所以并不是：

> 自动批准一切 escalation。

而是：

> **正常工作无需询问，越界也没有 escalation 通道。**

非常适合 unattended workers。

---

# 9. 并行容量

目标：

```text
4 tickets simultaneously
```

每张票最大：

```text
1 Engineer
+
2 code reviewers
=
3 spawned agents
```

所以：

```text
4 × 3 = 12 spawned threads
```

再加：

```text
1 Master
```

实际 topology：

```text
13 active agent threads
```

但是当前：

```toml
max_concurrent_threads_per_session
```

统计的是 spawned threads，不包含 primary Master。

因此：

```toml
[agents]
enabled = true
max_concurrent_threads_per_session = 12
```

对应：

```text
12 spawned + 1 Master = 13 actual
```

---

# 10. Integration Harness

Implementation 可以并行。

Integration 必须串行：

```text
parallel implementation
        ↓
reviewed commits
        ↓
Master integration queue
        ↓
one by one
        ↓
dev
```

Master 负责：

```text
决定谁先 merge
```

不是简单 FIFO。

未来甚至可以考虑：

```text
dependency-unblocking ticket
> foundational ticket
> leaf ticket
```

但 V1 先由 Sol Master 判断。

---

# 11. Merge Resolver

独立角色：

```text
merge-resolver
Sol xhigh
```

运行位置：

```text
dev worktree
```

不是 Engineer 的 `dev-*` worktree。

职责：

```text
Master 尝试集成
        ↓
发生 integration conflict
        ↓
spawn merge-resolver
        ↓
resolver 只修改 dev
        ↓
返回 Master
```

Merge Resolver 不决定：

```text
❌ merge 顺序
❌ 合另一个 commit
❌ ticket scope
❌ spec redesign
❌ 最终 integration PASS
```

---

# 12. Merge Resolver + Matt Skill

对于真正 Git conflict：

```text
$resolving-merge-conflicts
```

直接使用 Matt Pocock skill。

不重复写一套：

```text
检查冲突
分析双方
逐 hunk 修改
验证
continue
```

这些 SOP。

Resolver prompt 只补 skill 当前没完全覆盖的部分：

```text
如果 Git operation 本身成功，
但 integration validation 暴露 semantic conflict：

→ diagnose
→ 做最小 reconciliation
→ preserve accepted dev behavior
→ preserve incoming ticket intent
```

如果发现：

```text
两边 accepted requirements 本身互斥
```

则：

```text
STOP
→ 返回 Master
→ Master 做 spec arbitration
```

目前先这么补。

等 V1 跑出足够真实案例，再决定：

```text
给 Matt 提 issue
PR
fork skill
或者单独做 resolving-integration-conflicts
```

---

# 13. Merge Resolver 也挂 Worktree Guard

Engineer 的 guard：

```text
dev-ticket-a
→ 只能碰 dev-ticket-a
```

Resolver：

```text
dev
→ 只能碰 dev
```

这样统一成一个很漂亮的 harness invariant：

> **所有执行型 subagent 只能修改 spawn 时所在的 worktree。**

Master 例外，因为它属于 control plane。

Resolver 想理解 incoming commit：

```text
git show SHA
git diff ...
```

而不是跑去：

```text
../dev-ticket-a
```

读取 Agent 的活工作区。

---

# 14. Integration Validation

当前还区分两个 conflict 类型：

```text
Textual conflict
→ Git merge/cherry-pick/rebase conflict
→ $resolving-merge-conflicts

Semantic conflict
→ Git clean
→ 但是 typecheck/test/integration validation fail
→ merge-resolver minimal reconciliation
```

所以：

```text
git merge success
≠
integration success
```

最终是否 accepted 仍由 Master validation 决定。

---

# 15. Long-context / Handoff

V1 暂时**不自动化 context lifecycle**。

目前流程：

```text
Master 正常工作
       ↓
人工观察 context
       ↓
约 ~70–75%
       ↓
$handoff
       ↓
保存 durable control-plane checkpoint
       ↓
二选一
   /compact
      或
   new session
       ↓
继续
```

Handoff 重点记录：

```text
当前目标
canonical artifacts

active tickets
Engineer tier
review failure counts
active worktrees

merge-ready tickets
integration queue
current dev state

重要决策/invariants
下一步 actions
```

而不是复制：

```text
整个 spec
整个 diff
代码
完整聊天历史
```

---

# 16. 为什么 V1 暂时人工管理 Context

当前 Hook API 没有直接暴露：

```text
context_used
context_remaining
context_window
```

虽然 Codex `app-server` 已经有：

```text
thread/tokenUsage/updated
```

能拿到 context telemetry。

所以未来 V2 可以：

```text
app-server telemetry
        ↓
Context Lifecycle Controller
        ↓
75%
        ↓
handoff
compact
rehydrate
```

但 V1 不急着手搓。

当前原则：

> **Codex measurement + future harness policy。**

现在先由人承担 context lifecycle。

---

# 17. 当前 V1 的完整状态流

```text
User
 ↓
Master Sol xhigh
 ↓
$to-spec / alignment
 ↓
$to-tickets
 ↓
ticket DAG
 ↓
Master classification
 ↓
┌──────────────┬──────────────┬──────────────┐
│ Junior       │ Senior       │ Expert       │
│ Luna high    │ Terra high   │ Sol xhigh    │
└──────┬───────┴──────┬───────┴──────┬───────┘
       │              │              │
       └──────── $implement ─────────┘
                      │
                 $code-review
                      │
              ┌───────┴───────┐
          Standards          Spec
          reviewer         reviewer
                      │
                 PASS / FAIL
                  │       │
                 PASS    FAIL
                  │       │
                  │    retry
                  │       │
                  │    ×3?
                  │       │
                  │      yes
                  │       ↓
                  │   Master escalation
                  │
                  ▼
             reviewed commit
                  │
                  ▼
          Master integration queue
                  │
             serialized merge
                  │
            ┌─────┴─────┐
            │           │
          clean      conflict
            │           │
       validation       ▼
            │      merge-resolver
        ┌───┴───┐      Sol xhigh
       PASS    FAIL        │
        │        └─────────┘
        ▼
       dev
        │
 eventually release
        ▼
       main
```

## V1 的一句话定义

现在这套东西可以总结成：

> **Master 负责思考、调度和裁决；Engineer 负责隔离实现；Reviewer 负责质量门禁；Merge Resolver 负责 integration reconciliation；Git worktree 提供执行隔离；Matt skills 提供工程 SOP；Hooks 提供越界防护；人暂时负责长上下文生命周期。**
