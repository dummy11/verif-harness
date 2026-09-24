"""Durable project model for the verif-harness v1 control plane."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from .evidence_contracts import CLAIMS, EvidenceContractError, validate_workstream_evidence
from .evidence_policy import policy_for
from .reachability import ReachabilityError, validate_reachability


SCHEMA_VERSION = 2
STATE_DIR = ".verif-harness"
IGNORED_PARTS = {".git", ".deps", STATE_DIR, "__pycache__"}
RTL_SUFFIXES = {".v", ".sv", ".svh", ".vhd", ".vhdl"}
DOC_SUFFIXES = {".md", ".rst", ".txt", ".pdf"}
DOCUMENT_ITEM_KINDS = {
    "human-decision", "provisional", "assumption", "external-open-question",
}
DOCUMENT_ITEM_STATUSES = {"PENDING", "ACTIVE", "RESOLVED", "SUPERSEDED"}
ACTIVITY_STATUSES = {
    "PENDING", "RUNNING", "WAITING_FOR_HUMAN", "WAITING_FOR_PARENT",
    "COMPLETED", "FAILED", "CANCELLED",
}
AGENT_ASSIGNMENT_STATUSES = {
    "ACTIVE", "COMPLETED", "FAILED", "CANCELLED", "EXPIRED", "SUPERSEDED",
}
AGENT_ASSIGNMENT_PHASES = {"RUNNING", "WAITING_FOR_PARENT"}
VERIFICATION_AGENT_ROLES = (
    "VerificationArchitect", "EnvironmentEngineer", "TestEngineer",
    "AssertionEngineer", "CoverageEngineer", "DebugEngineer", "Reviewer",
)
HUMAN_ACTIONS = {"COMMENT", "REQUEST_CHANGE", "CLARIFY", "PRIORITIZE", "ACKNOWLEDGE"}
HUMAN_ACTION_STATUSES = {"OPEN", "RECORDED", "RESOLVED", "SUPERSEDED"}
AGENT_QUESTION_STATUSES = {"OPEN", "ANSWERED", "CANCELLED", "SUPERSEDED"}
PROJECT_TARGET = "project"
PROJECT_WORKSTREAM = "PROJECT"
PROJECT_AGENT_ID = "project-agent"
PROJECT_AGENT_ACTOR = "Project Main Agent"
SUBAGENT_PROTECTED_WRITE_PATHS = (
    ".git", ".deps", STATE_DIR, ".codex", ".kimi-code", ".agents",
    ".harness-config.json", "AGENTS.md",
)
AGENTS_MANAGED_BEGIN = "<!-- BEGIN verif-harness managed project instructions -->"
AGENTS_MANAGED_END = "<!-- END verif-harness managed project instructions -->"


class HarnessError(ValueError):
    """A user-actionable project-state error."""


class Validity(str, Enum):
    VALID = "VALID"
    PROVISIONAL = "PROVISIONAL"
    STALE = "STALE"
    INVALID = "INVALID"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    REVALIDATION_REQUIRED = "REVALIDATION_REQUIRED"
    BLOCKED = "BLOCKED"
    WAIVED = "WAIVED"
    UNKNOWN = "UNKNOWN"


VALIDITY_DESCRIPTIONS = {
    Validity.VALID.value: "已有有效材料",
    Validity.PROVISIONAL.value: "负责人暂定接受；允许带风险推进但不能关闭",
    Validity.STALE.value: "内容变化后尚未重新检查",
    Validity.INVALID.value: "当前检查未通过",
    Validity.REVIEW_REQUIRED.value: "等待负责人复核",
    Validity.REVALIDATION_REQUIRED.value: "需要重新验证",
    Validity.BLOCKED.value: "当前受阻",
    Validity.WAIVED.value: "负责人已接受例外",
    Validity.UNKNOWN.value: "尚未提供完成材料",
}


WORKSTREAM_STATES = {"REVIEW", "ACTIVE", "SATISFIED", "BASELINED", "PARTIALLY_STALE", "REVISE"}
VDOC_DOCUMENTS = {
    "verification-workflow": ("verification_workflow.md", "说明验证文档如何修改、评审和记录重要决定", ["VDOC"]),
    "verification-plan": ("verification_plan.md", "写清要验证什么、怎样验证、主要风险和完成标准", ["VDOC"]),
    "feature-matrix": ("feature_matrix.md", "列清每个验证点的来源、检查方法、覆盖目标和测试用例", ["VDOC", "VENV", "VSTIM", "VCHK", "VCOV", "VCASE", "VREG"]),
    "tb-architecture": ("tb_architecture.md", "说明验证环境各部分的职责、连接关系、数据流向和构建方式", ["VDOC", "VENV", "VSTIM", "VCHK", "VREG"]),
    "reference-model": ("reference_model_spec.md", "说明参考模型用在哪里、如何接入、怎样比较结果", ["VDOC", "VCHK"]),
    "coverage-plan": ("coverage_plan.md", "写清需要收集哪些覆盖率、何时采样以及如何处理未覆盖项", ["VDOC", "VCOV"]),
    "assertion-plan": ("assertion_plan.md", "列清需要检查的协议和关键规则，并说明如何确认这些检查真正生效", ["VDOC", "VCHK", "VCOV"]),
    "testcase-list": ("testcase_list.md", "列清每个测试用例要验证的内容、使用的场景、检查方法和运行方式", ["VDOC", "VCASE", "VREG"]),
}

VDOC_PLAN_CONTENT = {
    "verification-workflow": [
        "定义文档编写、评审、修改、失效重验和冻结流程",
        "明确负责人、Agent 与规则检查工具的职责，以及决定、问题和例外的记录方式",
    ],
    "verification-plan": [
        "列出 DUT 验证范围、功能目标、主要风险和明确不纳入范围的内容",
        "定义激励、检查、覆盖、用例和回归策略及项目级完成标准",
    ],
    "feature-matrix": [
        "为验证点建立稳定编号并关联规格来源",
        "映射每个验证点的激励、检查方法、覆盖目标和测试用例",
    ],
    "tb-architecture": [
        "定义验证环境拓扑、接口、时钟复位、配置传递和组件职责",
        "说明激励与观测数据流、构建边界和关键可观测点",
    ],
    "reference-model": [
        "说明参考模型适用范围、输入输出、数值行为和接入方式",
        "定义对齐、屏蔽、容差、比较时机和异常处理规则",
    ],
    "coverage-plan": [
        "定义 coverpoint、bin、cross、采样时机以及 illegal/ignore 规则",
        "说明覆盖目标、未覆盖项分析、排除与关闭标准",
    ],
    "assertion-plan": [
        "列出需要检查的协议和关键性质及其时钟、复位和 bind 位置",
        "定义 attempts、failure、vacuity、覆盖和例外处理要求",
    ],
    "testcase-list": [
        "列出测试用例编号、目标、前置条件、场景、配置和随机种子策略",
        "关联检查方法、覆盖目标、单测入口和回归分组",
    ],
}


def vdoc_document_contract(key: str) -> dict[str, Any]:
    filename, _title, workstreams = VDOC_DOCUMENTS[key]
    return {"filename": filename, "template": f"assets/vdoc/{filename}",
            "maintained_by": workstreams, "completion": "reviewed-content-not-file-existence"}


WORKSTREAM_TEMPLATES: dict[str, dict[str, Any]] = {
    "VDOC": {
        "name": "Verification Documentation",
        "objective": "持续维护验证范围、环境结构、检查方法和完成标准，让相关人员可以直接评审",
        # These rows are internal document containers and dependency anchors.
        # DUT-specific public VDOC nodes are proposed beneath the containers.
        "document_catalogs": [
            (key, value[1], "plan") for key, value in VDOC_DOCUMENTS.items()
        ],
        # VDOC 的 closure proof 是绑定到每份正文 revision 的 Human review，
        # 不是可由工具报告自动置为 PASS 的聚合 evidence node。
        "closure_evidence": [],
        "exit": [
            "每份必需文档的文档撰写方案节点和文档交付节点均已审批通过；暂定接受不计为完成",
            "所有文档交付节点中等待负责人确认的事项、修改要求和阻塞问题均已关闭",
        ],
    },
    "VENV": {
        "name": "Verification Environment",
        "objective": "建立能够编译、运行并观察设计行为的验证环境，同时保持设计代码只读",
        "capabilities": [
            ("interface-ready", "设计的输入输出接口已正确接入验证环境", "add-interface"),
            ("clock-reset-ready", "时钟与复位能够正确启动和控制设计", "add-harness-layer"),
            ("topology-ready", "验证环境各组件已连接，配置可以正确传递", "add-env-layer"),
            ("build-ready", "基础验证环境可以完成编译和装载", "finalize-filelist-and-make"),
            ("run-ready", "最小测试可以启动、正常结束，并正确报告错误", "add-regression-runner"),
            ("observation-ready", "可以看到设计的输入、输出和关键状态", "add-harness-layer"),
        ],
        "closure_evidence": [
            ("environment-smoke-evidence", "最小测试已实际运行，证明启动、复位、结束和观测链路可用", "evidence"),
        ],
        "exit": ["验证环境的必需功能都已完成", "最小测试无错误、无超时，且能看到设计的实际运行情况"],
    },
    "VSTIM": {
        "name": "Stimulus",
        "objective": "为必须验证的功能和场景提供稳定、可重复的输入",
        "capabilities": [
            ("transaction-contract", "写清输入数据的格式、生成顺序和限制条件", "plan"),
            ("stimulus-implementation", "必需验证的功能都有可以重复运行的激励实现", "add-uvc-skeleton"),
            ("corner-scenarios", "可以生成边界、错误、并发和流控场景", "add-testcase"),
        ],
        "closure_evidence": [
            ("reachability-evidence", "运行结果证明目标场景真正到达了设计的输入端", "reachability"),
            ("determinism-evidence", "使用相同测试、随机种子和配置重新运行时，生成的输入一致", "reachability"),
        ],
        "exit": ["所有必需激励都已实现", "已实际观察到目标场景进入设计，并且相同配置可以重复产生一致输入"],
    },
    "VCHK": {
        "name": "Checking",
        "objective": "确认设计结果是否正确，并能在出错时指出具体差异",
        "capabilities": [
            ("compare-policy", "写清数值、时间、顺序、异常和误差容许范围", "plan"),
            ("reference-model", "参考模型已接入，其输入输出边界可以检查", "add-refmodel-bridge"),
            ("scoreboard", "结果检查程序已实际检查必需验证的功能", "complete-scoreboard"),
            ("assertions", "协议和关键规则已建立自动检查，并证明这些检查在运行时真正触发", "add-assertion-skeleton"),
        ],
        "closure_evidence": [
            ("reference-model-evidence", "参考模型已在仿真中实际使用，比较结果没有未解释的差异", "evidence"),
            ("scoreboard-evidence", "结果检查程序已完成实际比较，没有未解释的差异", "evidence"),
            ("assertion-evidence", "必需的自动规则检查已编译、接入并在运行时触发，没有失败或未触发问题", "evidence"),
        ],
        "exit": ["必需的结果检查都有实际运行记录", "没有尚未解释的结果差异"],
    },
    "VCOV": {
        "name": "Coverage",
        "objective": "明确哪些功能和代码必须覆盖，并跟踪、处理尚未覆盖的部分",
        "capabilities": [
            ("coverage-model", "功能、代码和规则检查的覆盖率目标都能找到来源", "add-coverage-skeleton"),
            ("coverage-collection", "覆盖率数据可以重复收集，并明确对应的代码版本", "xverif"),
        ],
        "closure_evidence": [
            ("coverage-collection-evidence", "当前代码版本的覆盖率数据库完整，合并时没有遗漏或过期数据", "evidence"),
            ("hole-analysis-evidence", "未覆盖项已通过增加测试、证明不可达或负责人接受例外得到处理", "evidence"),
        ],
        "exit": ["所有必需覆盖目标都有当前版本的数据", "所有必须处理的未覆盖项都已完成分析和处理"],
    },
    "VCASE": {
        "name": "Testcase",
        "objective": "把验证目标组织成可重复运行、出错后便于定位的测试用例",
        "capabilities": [
            ("case-matrix", "每个必需验证的功能和场景都有对应测试用例", "plan"),
            ("case-implementation", "必需的测试用例和场景组合都已实现", "add-testcase"),
        ],
        "closure_evidence": [
            ("targeted-evidence", "新增测试用例已单独运行并通过", "xverif"),
        ],
        "exit": ["每个必需验证的功能都有对应用例", "新增用例都有当前代码版本的通过记录"],
    },
    "VREG": {
        "name": "Regression",
        "objective": "批量运行测试，汇总失败结果，记录问题处理进展，并确保结论来自当前代码版本",
        "capabilities": [
            ("regression-policy", "写清快速、每日和完整回归的用例范围、随机种子、超时、重跑和已知失败处理规则", "add-regression-runner"),
            ("executor-ready", "编译、运行和收集结果的工具已配置并通过自检", "add-regression-runner"),
        ],
        "closure_evidence": [
            ("execution-evidence", "必需的回归测试可以重复执行，并保留对应的代码版本", "evidence"),
            ("triage-evidence", "失败已分类，使用相同随机种子重跑，并记录处理结论", "evidence"),
            ("fresh-evidence", "必需验证项都已关联到当前代码版本的最新结果", "xverif"),
        ],
        "exit": ["没有尚未处理的最高或高优先级失败", "必需验证结果都对应当前代码版本"],
    },
}


def template_nodes(template: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    """Flatten explicit template sections without inferring role from a node name."""
    return [
        *((key, title, mode, "document-catalog")
          for key, title, mode in template.get("document_catalogs", [])),
        *((key, title, mode, "capability")
          for key, title, mode in template.get("capabilities", [])),
        *((key, title, mode, "closure-evidence")
          for key, title, mode in template["closure_evidence"]),
    ]


DESIRED_KEY = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
PROJECT_NODE_ROLES: dict[str, set[str]] = {
    "VDOC": {"document-writing-plan", "document-deliverable"},
    "VENV": {"environment-component", "interface", "clock-reset-domain", "observation-path"},
    "VSTIM": {"stimulus-feature", "stimulus-scenario"},
    "VCHK": {"checking-goal", "checker", "reference-path", "assertion-group"},
    "VCOV": {"coverage-goal", "coverage-scope"},
    "VCASE": {"case-mapping", "testcase"},
    "VREG": {"regression-profile", "regression-run-set", "failure-group"},
}
WORKSTREAM_DEFINITION_CONTEXT: dict[str, dict[str, Any]] = {
    "VDOC": {
        "purpose": "让后续的实现、检查和评审都能找到已经由负责人确认的文档依据。",
        "scope": ["当前版本的验证文档", "文档中的验证范围、重要决定、风险和完成标准"],
        "source_refs": ["项目初始信息", "负责人作出的工程决定", "已指定的只读设计代码和规格文档"],
    },
    "VENV": {
        "purpose": "保证验证代码能够连接、启动和观察被验证设计，为其他工作提供可信的运行基础。",
        "scope": ["所有必需的设计接口、时钟和复位", "验证环境组件、构建、运行和观测链路"],
        "source_refs": ["verification_plan.md", "tb_architecture.md", "feature_matrix.md"],
    },
    "VSTIM": {
        "purpose": "保证必需验证的功能和场景不只写在计划里，而是能稳定生成并真正进入设计。",
        "scope": ["验证点清单中必须验证的功能和场景", "输入数据、生成顺序、限制条件、边界场景和重放配置"],
        "source_refs": ["verification_plan.md", "feature_matrix.md", "testcase_list.md"],
    },
    "VCHK": {
        "purpose": "保证设计的行为会被明确且真正启用的结果比对、参考模型或规则检查发现问题。",
        "scope": ["必需验证功能的预期结果、顺序、时间、异常和允许误差", "结果检查、参考模型和自动规则检查的实现与运行链路"],
        "source_refs": ["verification_plan.md", "reference_model_spec.md", "assertion_plan.md", "feature_matrix.md"],
    },
    "VCOV": {
        "purpose": "把每个必须完成的覆盖率目标与采样实现、数据库结果和未覆盖项的处理记录对应起来。",
        "scope": ["覆盖率计划中必须完成的功能、代码和规则检查目标", "采样、收集、合并、未覆盖项分析和例外处理"],
        "source_refs": ["coverage_plan.md", "feature_matrix.md", "assertion_plan.md"],
    },
    "VCASE": {
        "purpose": "保证必需验证的功能和场景都有可运行、便于定位问题的测试用例。",
        "scope": ["功能和测试用例的对应关系", "必需的测试用例、场景组合、配置和单独运行结果"],
        "source_refs": ["testcase_list.md", "feature_matrix.md", "verification_plan.md"],
    },
    "VREG": {
        "purpose": "保证批量测试可以重复运行、失败可以追踪，并且完成判断使用的是当前代码版本的最新结果。",
        "scope": ["必需的回归配置、随机种子、超时、重跑和已知失败处理规则", "运行清单、失败分类和需要刷新的验证结果"],
        "source_refs": ["verification_workflow.md", "verification_plan.md", "testcase_list.md"],
    },
}

ASIC_NODE_CONTENT: dict[tuple[str, str], tuple[list[str], list[str]]] = {
    ("VENV", "interface-ready"): (["核对 DUT 端口方向、位宽、协议角色和 modport/clocking block 映射", "连接 DUT interface、driver 与 monitor，并检查所有必需信号可驱动或可观测"], ["与 DUT 端口一致的 interface 和连接清单"]),
    ("VENV", "clock-reset-ready"): (["识别 DUT 的时钟域、频率/相位关系、复位极性与同步方式", "实现启动、复位保持、释放和跨时钟复位次序，并检查复位后的稳定状态"], ["时钟复位控制及 reset/idle 检查结果"]),
    ("VENV", "topology-ready"): (["按 DUT 接口和数据流连接 agent、sequencer、monitor、scoreboard 与 coverage collector", "核对 active/passive 模式、配置传递、虚接口和分析端口连接"], ["与 DUT 验证结构对应的 TB 拓扑"]),
    ("VENV", "build-ready"): (["确定 DUT RTL、bind、interface、package、UVC、env 和 test 的编译顺序", "完成 compile/elaboration，确认顶层、参数、宏和 timescale 与当前 DUT 配置一致"], ["当前 DUT 配置的 filelist、构建入口和编译/装载结果"]),
    ("VENV", "run-ready"): (["启动最小测试并执行 DUT 时钟、复位、idle 和结束流程", "检查 timeout、objection、错误计数和退出码能真实反映运行结果"], ["当前 DUT 的最小可运行测试入口和 smoke 结果"]),
    ("VENV", "observation-ready"): (["确定 DUT 输入、输出、握手、关键状态和错误路径的观测点", "确认 monitor、transaction trace 或 waveform 能还原一次实际 DUT 交互"], ["DUT 观测路径和可复现的观测记录"]),
    ("VENV", "environment-smoke-evidence"): (["在当前 RTL 与 TB 配置上运行 reset/idle smoke", "保存启动、复位释放、结束、错误计数和关键观测证据"], ["当前代码版本的环境 smoke 日志与观测证据"]),
    ("VSTIM", "transaction-contract"): (["定义与 DUT 接口对应的 transaction 字段、合法值、顺序和握手语义", "明确约束、默认值、非法输入以及 transaction 到引脚的映射"], ["DUT 输入 transaction 与协议驱动合同"]),
    ("VSTIM", "stimulus-implementation"): (["实现 sequence/item/driver，使计划中的 DUT 功能输入可生成并正确驱动", "处理 backpressure、并发、延迟、复位中断和错误注入"], ["可重复驱动 DUT 的激励实现"]),
    ("VSTIM", "corner-scenarios"): (["实现规格定义的边界值、错误、并发、流控和状态转换场景", "将每个场景关联到验证点、checker、coverage 和 testcase"], ["DUT 边界与异常场景清单及激励入口"]),
    ("VSTIM", "reachability-evidence"): (["运行定向激励并确认目标 transaction 已到达 DUT 接收边界", "通过 monitor、transaction trace 或 waveform 核对场景条件真实成立"], ["目标场景到达 DUT 的运行证据"]),
    ("VSTIM", "determinism-evidence"): (["固定 testcase、seed、配置和 RTL 版本重复运行激励", "比较输入 transaction 序列与关键时序，确认可重放性"], ["同配置重复运行的一致性证据"]),
    ("VCHK", "compare-policy"): (["定义 DUT 结果的数值、位级、顺序、时间、异常与允许误差规则", "明确 unknown、mask、饱和/舍入、乱序、丢弃和复位清空策略"], ["与 DUT 输出语义对应的比较合同"]),
    ("VCHK", "reference-model"): (["将 DUT 输入 transaction 转换为参考模型输入，并取得可比较的期望结果", "处理数据格式、对齐、状态、延迟、mask 和模型错误"], ["参考模型适配器及输入输出映射"]),
    ("VCHK", "scoreboard"): (["关联 DUT 实际输出与期望结果，并按比较合同完成匹配", "报告 transaction 身份、字段差异、时序和上下文，处理复位与 flush"], ["覆盖必需 DUT 功能的 scoreboard/checker"]),
    ("VCHK", "assertions"): (["实现规格中的协议、时序、稳定性、互斥和错误响应性质", "绑定到正确 DUT 层级和时钟复位域，并防止 vacuous pass"], ["与 DUT 信号和规格规则对应的 SVA/bind"]),
    ("VCHK", "reference-model-evidence"): (["在实际仿真中证明参考模型收到输入并产生期望结果", "核对 compare 次数、差异、模型版本和当前 DUT 配置"], ["参考模型参与当前 DUT 比对的运行证据"]),
    ("VCHK", "scoreboard-evidence"): (["证明 scoreboard 实际接收 expected/actual transaction 并执行比较", "检查比较次数、未匹配队列、失败和复位清空行为"], ["scoreboard 非空运行和比较结果"]),
    ("VCHK", "assertion-evidence"): (["证明断言已编译、bind/elaborate 并在实际运行中产生 attempts", "检查 failure、vacuity、disable 条件和必要 cover property"], ["当前 DUT 运行中的断言尝试与结果"]),
    ("VCOV", "coverage-model"): (["把 DUT 功能、状态、配置、错误和交互场景映射为 coverpoint/bin/cross", "定义采样事件、iff、illegal/ignore bin 和每项覆盖目标来源"], ["与验证点对应的功能覆盖模型"]),
    ("VCOV", "coverage-collection"): (["配置当前 DUT/testbench 的功能、代码和断言覆盖收集", "确认数据库、merge 范围、RTL 版本、配置和测试清单可追溯"], ["可重复生成和合并的覆盖率配置"]),
    ("VCOV", "coverage-collection-evidence"): (["收集当前 RTL 与验证配置对应的 coverage database", "核对 planned/mapped/hit 数量、数据库完整性和版本一致性"], ["当前版本的覆盖率数据库和导出报告"]),
    ("VCOV", "hole-analysis-evidence"): (["逐项分析未命中的 DUT 功能、状态、bin、cross 和代码范围", "记录补测、不可达证明、模型修正或负责人接受例外的结论"], ["未覆盖项根因和关闭记录"]),
    ("VCASE", "case-matrix"): (["将每个 DUT 验证点和必需场景映射到一个或多个 testcase", "关联激励、checker、coverage、配置和预期结果"], ["验证点到 testcase 的可追溯矩阵"]),
    ("VCASE", "case-implementation"): (["实现 testcase/vseq 配置、场景组合、结束条件和错误检查", "保证单个用例可独立运行并能定位对应 DUT 功能问题"], ["已注册且可独立执行的 testcase"]),
    ("VCASE", "targeted-evidence"): (["在当前 RTL 与 TB 版本上单独运行新增或修改的 testcase", "保存 seed、配置、结果、checker 活动和覆盖命中"], ["testcase 定向运行记录"]),
    ("VREG", "regression-policy"): (["定义 smoke、daily 和 full regression 的 testcase、seed、配置、超时和资源边界", "明确失败重跑、已知失败、结果保留和准入规则"], ["面向当前 DUT 的回归策略与清单规则"]),
    ("VREG", "executor-ready"): (["配置 DUT/TB 构建、隔离运行、seed 传递、timeout 和结果收集", "验证并发运行、失败退出码和工件路径不会相互污染"], ["可重复执行当前 DUT 回归的 runner"]),
    ("VREG", "execution-evidence"): (["按评审清单运行当前 DUT 的必需 testcase 和 seed", "保存 RTL/TB 版本、配置、逐用例状态、耗时和工件索引"], ["当前代码版本的回归 manifest 与结果"]),
    ("VREG", "triage-evidence"): (["按 DUT 现象和签名归类失败，并使用相同 seed/config 重跑", "记录首个错误、相关 checker/波形、责任归属和处理结论"], ["失败分类、同 seed 重跑和处理记录"]),
    ("VREG", "fresh-evidence"): (["核对所有必需验证点关联的结果来自当前 RTL、TB、配置和计划版本", "标记过期、缺失或被新变更影响的运行证据"], ["当前版本验证结果的新鲜度审计"]),
}


def desired_definition(
    workstream: str, key: str, title: str, role: str,
    contract: dict[str, Any], origin: str = "template",
) -> dict[str, Any]:
    """Build an explicit review candidate without inventing project-specific facts."""
    context = WORKSTREAM_DEFINITION_CONTEXT[workstream]
    requirements = contract.get("requirements", contract.get("required", []))
    criteria = ["负责人已确认本轮工作的范围和依据"]
    for requirement in requirements:
        label = requirement.get("label") if isinstance(requirement, dict) else str(requirement)
        if label:
            criteria.append(label)
    criteria.append("所有前置工作都已完成，或负责人已明确接受例外")
    definition = {
        "statement": f"{title}。需要检查实际内容和支持材料；仅有文件，或某个命令运行成功，都不能说明这项工作已经完成。",
        "purpose": context["purpose"],
        "scope": list(context["scope"]),
        "acceptance_criteria": criteria,
        "source_refs": list(context["source_refs"]),
        "work_content": [
            "列出这项工作具体包含哪些对象，以及不包含哪些内容",
            "完成本节点所描述的实际工作",
            "收集能够证明工作结果的原始材料，并检查材料是否完整",
        ],
        "implementation_approach": [
            "Agent 读取项目文档和已登记状态，起草适用于当前项目的内容",
            "负责人确认工作范围、实现方法和完成标准",
            "Agent 或工程工具执行工作；verif-harness 检查材料格式、来源和前置关系",
        ],
        "deliverables": [
            f"{title} 对应的可评审实际成果",
            "完成判断所需的原始材料和分析结果",
        ],
        "progress_measures": [{
            "id": "required-objects",
            "label": "已完成的必需项数量",
            "unit": "项",
            "target": "以已经确认的项目文档为准",
            "source": "已登记的检查结果",
        }],
        "quality_checks": [
            "所有完成条件都已满足",
            "支持材料对应当前版本，且没有尚未处理的问题",
            "人工评审没有留下尚未完成的修改要求",
        ],
        "definition_origin": origin,
        "definition_status": "REVIEW_CANDIDATE",
        "role_description": (
            "这是一类通用工作的汇总；还需要按本项目的具体功能或场景继续细分"
            if role == "capability" else
            "汇总完成这项工作所需的运行结果；原始日志、波形或数据库作为支持材料"
        ),
    }
    asic_content = ASIC_NODE_CONTENT.get((workstream, key))
    if asic_content is not None:
        work_content, deliverables = asic_content
        evidence_node = role == "closure-evidence"
        definition.update({
            "work_content": list(work_content),
            "implementation_approach": [
                "从已评审的验证文档、只读 DUT RTL 和规格中解析本节点对应的实际接口、信号、功能、场景或结果",
                (
                    "在当前 RTL、TB、testcase、seed 和配置上执行并保存可追溯的原始证据"
                    if evidence_node else
                    "按当前 DUT 的协议、时序、数据格式和验证架构实现，并通过编译、装载或定向运行检查"
                ),
            ],
            "deliverables": list(deliverables),
            "progress_measures": [{
                "id": "dut-verification-objects",
                "label": f"{title}中已满足的 DUT 验证对象数量",
                "unit": "项",
                "target": "以已评审的验证点、接口、场景或运行清单为准",
                "source": (
                    "当前 RTL/TB/config 对应的仿真、波形、覆盖率或回归证据"
                    if evidence_node else
                    "当前 DUT 对应的实现、映射和结构化检查结果"
                ),
            }],
            "quality_checks": [
                "所有对象都能追溯到当前 DUT 的规格、RTL 接口或已评审验证点",
                (
                    "证据来自当前 RTL、TB、testcase、seed 和配置，且没有空运行、vacuous 或过期结果"
                    if evidence_node else
                    "实现与 DUT 的协议、时序、数据格式和验证架构一致，且没有尚未处理的工程问题"
                ),
            ],
            "role_description": (
                "当前 DUT 验证运行结果节点；必须用真实仿真、波形、覆盖率或回归证据证明"
                if evidence_node else
                "当前 DUT 验证能力节点；必须绑定具体接口、功能、场景、checker、coverage 或 testcase"
            ),
        })
    if workstream == "VDOC" and key in VDOC_PLAN_CONTENT:
        filename = VDOC_DOCUMENTS[key][0]
        definition.update({
            "scope": [f"{filename} 中需要由验证团队评审的当前工程定义"],
            "work_content": list(VDOC_PLAN_CONTENT[key]),
            "deliverables": [f"当前项目的 {filename} 可评审正文"],
            "role_description": "当前 DUT 的正式验证文档撰写方案；内容必须绑定实际规格、接口、验证点和工程决定",
        })
    return definition


def vdoc_internal_semantic_units(
    key: str, role: str, fields: dict[str, list[str]],
) -> tuple[list[dict[str, Any]], str]:
    """Create stable, non-Human-facing units for fine-grained VDOC work."""
    units: list[dict[str, Any]] = []
    for field in (
        "scope", "work_content", "acceptance_criteria", "source_refs",
        "deliverables", "quality_checks",
    ):
        for index, content in enumerate(fields[field], 1):
            unit_id = f"semantic:{key}:{field}:{index}"
            digest = hashlib.sha256(json_text({
                "node_key": key,
                "role": role,
                "field": field,
                "content": content,
            }).encode("utf-8")).hexdigest()
            units.append({
                "id": unit_id,
                "field": field,
                "sequence": index,
                "digest": digest,
                "content": content,
                "visible_to_human": False,
            })
    manifest_digest = hashlib.sha256(json_text([
        {"id": item["id"], "digest": item["digest"]} for item in units
    ]).encode("utf-8")).hexdigest()
    return units, manifest_digest


def vdoc_internal_child_specs(parent: dict[str, Any]) -> list[dict[str, Any]]:
    """Materialize hidden semantic units as full desired-state child nodes."""
    field_labels = {
        "scope": "范围",
        "work_content": "工作内容",
        "acceptance_criteria": "验收条件",
        "source_refs": "输入依据",
        "deliverables": "交付内容",
        "quality_checks": "质量检查",
    }
    children: list[dict[str, Any]] = []
    for unit in parent.get("internal_semantic_units", []):
        field = str(unit["field"])
        sequence = int(unit["sequence"])
        content = str(unit["content"])
        key = f"{parent['key']}--semantic--{field}--{sequence}"
        label = field_labels.get(field, field)
        children.append({
            "key": key,
            "title": f"{parent['title']} · {label} {sequence}",
            "role": "document-semantic-unit",
            "visibility": "internal",
            "visible_to_human": False,
            "required": parent.get("required", True),
            "suggested_mode": parent.get("suggested_mode", "review"),
            "evidence_claim": "document-review",
            "parent_key": parent["key"],
            "parent_role": parent["role"],
            "document_key": parent.get("document_key"),
            "content_kind": "internal-semantic-work",
            "semantic_unit_id": unit["id"],
            "semantic_field": field,
            "semantic_sequence": sequence,
            "semantic_digest": unit["digest"],
            "statement": content,
            "purpose": (
                f"独立跟踪公开文档节点“{parent['title']}”中的{label}，"
                "使其能够参与执行、依赖、证据、问题和失效传播。"
            ),
            "scope": [content],
            "acceptance_criteria": [
                f"当前版本的{label}已经完成，并与对应规格、正文和依赖工作一致",
            ],
            "source_refs": list(parent.get("source_refs", [])),
            "work_content": [content],
            "implementation_approach": list(parent.get("implementation_approach", [])),
            "deliverables": [f"公开文档节点“{parent['title']}”中的{label}完成结果"],
            "progress_measures": [{
                "id": f"semantic-{field}-{sequence}",
                "label": f"已完成{label}",
                "unit": "项",
                "target": "1",
                "source": str(unit["id"]),
            }],
            "quality_checks": list(parent.get("quality_checks", [])),
            "definition_origin": "engine-derived",
            "definition_status": "REVIEW_CANDIDATE",
            "role_description": (
                "负责人不可见的文档内部工作节点；与其他工作节点使用同一状态、"
                "依赖、证据、Activity、Agent assignment、问题和 closure 机制"
            ),
        })
    return children

# Stored as dependent (workstream, key) -> prerequisite (workstream, key).
# These are capability/evidence dependencies, never whole-Workstream gates.
DEFAULT_DEPENDENCIES: tuple[tuple[tuple[str, str], tuple[str, str]], ...] = (
    (("VENV", "interface-ready"), ("VDOC", "verification-plan")),
    (("VENV", "interface-ready"), ("VDOC", "tb-architecture")),
    (("VENV", "clock-reset-ready"), ("VDOC", "verification-plan")),
    (("VENV", "clock-reset-ready"), ("VDOC", "tb-architecture")),
    (("VENV", "topology-ready"), ("VDOC", "tb-architecture")),
    (("VENV", "topology-ready"), ("VENV", "interface-ready")),
    (("VENV", "build-ready"), ("VENV", "interface-ready")),
    (("VENV", "build-ready"), ("VENV", "clock-reset-ready")),
    (("VENV", "build-ready"), ("VENV", "topology-ready")),
    (("VENV", "run-ready"), ("VENV", "build-ready")),
    (("VENV", "observation-ready"), ("VENV", "interface-ready")),
    (("VENV", "observation-ready"), ("VENV", "topology-ready")),
    (("VREG", "regression-policy"), ("VDOC", "verification-workflow")),
    (("VREG", "regression-policy"), ("VDOC", "verification-plan")),
    (("VREG", "regression-policy"), ("VDOC", "testcase-list")),
    (("VREG", "executor-ready"), ("VREG", "regression-policy")),
    (("VREG", "executor-ready"), ("VENV", "run-ready")),
    (("VENV", "environment-smoke-evidence"), ("VENV", "build-ready")),
    (("VENV", "environment-smoke-evidence"), ("VENV", "clock-reset-ready")),
    (("VENV", "environment-smoke-evidence"), ("VENV", "run-ready")),
    (("VENV", "environment-smoke-evidence"), ("VENV", "observation-ready")),
    (("VSTIM", "transaction-contract"), ("VDOC", "verification-plan")),
    (("VSTIM", "transaction-contract"), ("VDOC", "feature-matrix")),
    (("VSTIM", "transaction-contract"), ("VDOC", "tb-architecture")),
    (("VSTIM", "stimulus-implementation"), ("VSTIM", "transaction-contract")),
    (("VSTIM", "stimulus-implementation"), ("VENV", "interface-ready")),
    (("VSTIM", "stimulus-implementation"), ("VENV", "topology-ready")),
    (("VSTIM", "stimulus-implementation"), ("VENV", "build-ready")),
    (("VSTIM", "corner-scenarios"), ("VSTIM", "transaction-contract")),
    (("VSTIM", "corner-scenarios"), ("VDOC", "feature-matrix")),
    (("VSTIM", "reachability-evidence"), ("VSTIM", "stimulus-implementation")),
    (("VSTIM", "reachability-evidence"), ("VSTIM", "corner-scenarios")),
    (("VSTIM", "reachability-evidence"), ("VREG", "executor-ready")),
    (("VSTIM", "reachability-evidence"), ("VENV", "environment-smoke-evidence")),
    (("VSTIM", "reachability-evidence"), ("VENV", "observation-ready")),
    (("VSTIM", "determinism-evidence"), ("VSTIM", "reachability-evidence")),
    (("VSTIM", "determinism-evidence"), ("VREG", "executor-ready")),
    (("VCHK", "compare-policy"), ("VDOC", "verification-plan")),
    (("VCHK", "compare-policy"), ("VDOC", "reference-model")),
    (("VCHK", "reference-model"), ("VCHK", "compare-policy")),
    (("VCHK", "reference-model"), ("VENV", "build-ready")),
    (("VCHK", "scoreboard"), ("VCHK", "compare-policy")),
    (("VCHK", "scoreboard"), ("VENV", "build-ready")),
    (("VCHK", "assertions"), ("VDOC", "assertion-plan")),
    (("VCHK", "assertions"), ("VENV", "build-ready")),
    (("VCHK", "reference-model-evidence"), ("VCHK", "reference-model")),
    (("VCHK", "reference-model-evidence"), ("VSTIM", "reachability-evidence")),
    (("VCHK", "reference-model-evidence"), ("VENV", "environment-smoke-evidence")),
    (("VCHK", "scoreboard-evidence"), ("VCHK", "scoreboard")),
    (("VCHK", "scoreboard-evidence"), ("VSTIM", "reachability-evidence")),
    (("VCHK", "scoreboard-evidence"), ("VENV", "environment-smoke-evidence")),
    (("VCHK", "assertion-evidence"), ("VCHK", "assertions")),
    (("VCHK", "assertion-evidence"), ("VSTIM", "reachability-evidence")),
    (("VCHK", "assertion-evidence"), ("VENV", "environment-smoke-evidence")),
    (("VCASE", "case-matrix"), ("VDOC", "feature-matrix")),
    (("VCASE", "case-matrix"), ("VDOC", "testcase-list")),
    (("VCASE", "case-implementation"), ("VCASE", "case-matrix")),
    (("VCASE", "case-implementation"), ("VSTIM", "stimulus-implementation")),
    (("VCASE", "case-implementation"), ("VENV", "build-ready")),
    (("VCASE", "case-implementation"), ("VREG", "executor-ready")),
    (("VCASE", "targeted-evidence"), ("VCASE", "case-implementation")),
    (("VCASE", "targeted-evidence"), ("VSTIM", "reachability-evidence")),
    (("VCASE", "targeted-evidence"), ("VCHK", "scoreboard-evidence")),
    (("VCASE", "targeted-evidence"), ("VENV", "environment-smoke-evidence")),
    (("VCOV", "coverage-model"), ("VDOC", "coverage-plan")),
    (("VCOV", "coverage-model"), ("VDOC", "feature-matrix")),
    (("VCOV", "coverage-collection"), ("VCOV", "coverage-model")),
    (("VCOV", "coverage-collection"), ("VREG", "executor-ready")),
    (("VCOV", "coverage-collection"), ("VENV", "build-ready")),
    (("VCOV", "coverage-collection-evidence"), ("VCOV", "coverage-collection")),
    (("VCOV", "coverage-collection-evidence"), ("VSTIM", "reachability-evidence")),
    (("VCOV", "coverage-collection-evidence"), ("VCASE", "targeted-evidence")),
    (("VCOV", "coverage-collection-evidence"), ("VENV", "environment-smoke-evidence")),
    (("VCOV", "hole-analysis-evidence"), ("VCOV", "coverage-collection-evidence")),
    (("VREG", "execution-evidence"), ("VREG", "executor-ready")),
    (("VREG", "execution-evidence"), ("VENV", "environment-smoke-evidence")),
    (("VREG", "execution-evidence"), ("VSTIM", "determinism-evidence")),
    (("VREG", "execution-evidence"), ("VCHK", "reference-model-evidence")),
    (("VREG", "execution-evidence"), ("VCHK", "scoreboard-evidence")),
    (("VREG", "execution-evidence"), ("VCHK", "assertion-evidence")),
    (("VREG", "execution-evidence"), ("VCASE", "targeted-evidence")),
    (("VREG", "execution-evidence"), ("VCOV", "coverage-collection-evidence")),
    (("VREG", "triage-evidence"), ("VREG", "execution-evidence")),
    (("VREG", "fresh-evidence"), ("VREG", "execution-evidence")),
    (("VREG", "fresh-evidence"), ("VREG", "triage-evidence")),
    (("VREG", "fresh-evidence"), ("VCOV", "hole-analysis-evidence")),
)


def validate_default_dependency_graph() -> None:
    """Fail fast when a built-in template or its default graph is inconsistent."""
    declared = {
        (workstream, key)
        for workstream, template in WORKSTREAM_TEMPLATES.items()
        for key, _title, _mode, _role in template_nodes(template)
    }
    referenced = {node for edge in DEFAULT_DEPENDENCIES for node in edge}
    unknown = sorted(referenced - declared)
    if unknown:
        raise RuntimeError(f"DEFAULT_DEPENDENCIES 引用了未声明 template node: {unknown}")

    graph: dict[tuple[str, str], list[tuple[str, str]]] = {node: [] for node in declared}
    for dependent, prerequisite in DEFAULT_DEPENDENCIES:
        graph[dependent].append(prerequisite)
    visiting: set[tuple[str, str]] = set()
    visited: set[tuple[str, str]] = set()

    def visit(node: tuple[str, str]) -> None:
        if node in visiting:
            raise RuntimeError(f"DEFAULT_DEPENDENCIES 存在循环依赖: {node}")
        if node in visited:
            return
        visiting.add(node)
        for prerequisite in graph[node]:
            visit(prerequisite)
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)


validate_default_dependency_graph()


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def json_text(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def capability_config_projection(
    path: Path, manifest: dict[str, Any], refresh: bool,
) -> dict[str, Any] | None:
    """Build the capability config while preserving non-bootstrap project fields."""
    existing: dict[str, Any] = {}
    if path.exists() or path.is_symlink():
        if not refresh:
            return None
        if path.is_symlink() or not path.is_file():
            raise HarnessError(f"拒绝刷新非普通 .harness-config.json: {path}")
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HarnessError(f"无法读取现有 .harness-config.json: {exc}") from exc
        if not isinstance(loaded, dict):
            raise HarnessError("现有 .harness-config.json 顶层必须是对象")
        existing = loaded

    verif_root = str(manifest["verif_root"])
    docs_output = "docs" if verif_root in {"", "."} else f"{verif_root.rstrip('/')}/docs"
    existing_rtl = existing.get("rtl") if isinstance(existing.get("rtl"), dict) else {}
    existing_verif = existing.get("verif") if isinstance(existing.get("verif"), dict) else {}
    existing_inputs = (
        existing.get("verification_inputs")
        if isinstance(existing.get("verification_inputs"), dict) else {}
    )
    verification_inputs = (
        manifest.get("verification_inputs")
        if isinstance(manifest.get("verification_inputs"), dict) else {}
    )
    verification_scripts = verification_inputs.get("scripts")
    if not isinstance(verification_scripts, list):
        verification_scripts = []
    return {
        **existing,
        "project_name": manifest["project_name"],
        "rtl": {
            **existing_rtl,
            "root": manifest["rtl_roots"][0],
            "top_module": manifest["dut"]["top_module"],
            "top_file": manifest["dut"]["top_file"],
        },
        "verif": {
            **existing_verif,
            "root": verif_root,
            "docs_root": docs_output,
            "verification_subdir": existing_verif.get("verification_subdir", "verification"),
            "governance_subdir": existing_verif.get("governance_subdir", "governance"),
        },
        "verification_inputs": {
            **existing_inputs,
            "testbench_root": verification_inputs.get("testbench_root"),
            "reference_model": verification_inputs.get("reference_model"),
            "scripts": list(verification_scripts),
        },
    }


def default_vdoc_document_root(manifest: dict[str, Any]) -> str:
    verif_root = str(manifest.get("verif_root") or ".").rstrip("/")
    return "docs/verification" if verif_root in {"", "."} else f"{verif_root}/docs/verification"


def project_agents_block(manifest: dict[str, Any], document_root: str | None = None) -> str:
    rtl_roots = manifest.get("rtl_roots") or []
    docs_roots = manifest.get("docs_roots") or []
    dut = manifest.get("dut") if isinstance(manifest.get("dut"), dict) else {}
    verification_inputs = (
        manifest.get("verification_inputs")
        if isinstance(manifest.get("verification_inputs"), dict) else {}
    )
    verification_scripts = verification_inputs.get("scripts") or []
    lines = [
        AGENTS_MANAGED_BEGIN,
        "## verif-harness 项目合同（受管）",
        "",
        "本区块由 verif-harness 维护。项目自有说明必须保留在 markers 之外；",
        "仅通过 bootstrap 或 VDOC planning 刷新本区块。",
        "",
        "### 项目标识与边界",
        "",
        f"- 项目：`{manifest.get('project_name') or 'unknown'}`",
        f"- RTL roots（只读，可位于项目外）：{', '.join(f'`{item}`' for item in rtl_roots) or '`未记录`'}",
        f"- DUT top: `{dut.get('top_module') or 'not recorded'}`",
        f"- DUT top file（只读）：`{dut.get('top_file') or 'not recorded'}`",
        f"- RTL specification 输入（只读，可位于项目外）：{', '.join(f'`{item}`' for item in docs_roots) or '`未提供`'}",
        f"- Verification 输出根目录：`{manifest.get('verif_root') or '.'}`",
        "- 治理状态事实源：`.verif-harness/model.sqlite3`",
        "",
        "### 已登记的验证输入（均为可选）",
        "",
        f"- Testbench 目录：`{verification_inputs.get('testbench_root') or '未提供'}`",
        f"- 参考模型（reference/golden model）：`{verification_inputs.get('reference_model') or '未提供'}`",
        f"- 编译、仿真或回归脚本：{', '.join(f'`{item}`' for item in verification_scripts) or '`未提供`'}",
        "- bootstrap 只确认这些路径存在并登记清单，不执行、不修改，也不把文件存在",
        "  当成已经接入、运行成功或通过验证。具体用途和状态由对应 Workstream 确认。",
        "",
        "### ASIC 验证控制面约束",
        "",
        "- 本项目使用的是面向 ASIC 验证工程师的验证控制面，不是通用项目管理、",
        "  任务管理或审批系统。可复用的是 ASIC 验证控制能力，不是通用工作流模板。",
        "- 工作流和工作节点必须根据当前 DUT、接口、功能、验证点、测试场景、",
        "  检查机制、覆盖目标和验证证据形成；节点类型、数量、依赖和完成条件可以",
        "  随验证对象变化，不得套用固定项目模板。",
        "- 面向用户时优先说明验证对象、当前结论、依据、缺口和下一步。使用已有的",
        "  ASIC 验证术语，不机械翻译英文，不自行创造术语；没有通行中文名称时保留",
        "  标准英文，并在首次出现时说明含义。",
        "- 主要页面和操作必须让不是 ASIC 验证工程师的用户也能理解当前对象、状态、",
        "  依据和下一步；内部编号、schema、digest、数据库状态码和工具字段只放在",
        "  详情或审计信息中。",
        "- 同一规则适用于 Dashboard、CLI 输出以及 Agent 对话。面向用户时称“你”或",
        "  “负责人”，不要直接显示协议角色名 Human；称“验证文档”“正文内容”，",
        "  不用“语义文档集”“语义交付”等内部抽象。状态和问题必须写清谁要对哪个",
        "  DUT、工作流、节点或文档做什么，不能只说“等待计划评审”“空闲”或“未登记活动”。",
        "  CLI 命令名、schema 字段和状态码可保留，但必须同时解释其用户可见含义。",
        "- Agent 在 SSH 远端启动或复用 Dashboard 成功后，必须在当前对话中逐项完整打印",
        "  CLI 返回的单跳 SSH 配置及启动命令、双跳 SSH 配置及启动命令，以及本地浏览器",
        "  访问远端 Dashboard 的完整 URL。不得只打印其中一项，不得只说配置位于",
        "  `access` 字段，也不得从 URL 删除 `project` 或 `token` 参数。",
        "",
        "验证文档正文以列出的 Markdown 文件为准；SQLite 保存文档摘要、revision、review、",
        "evidence、开放事项状态和失效关系，不保存或覆盖验证文档正文。",
        "所有 RTL 和 RTL specification 都是只读输入。禁止编辑、创建、覆盖、删除、",
        "重命名、格式化这些输入，也禁止向其中生成文件。验证产物必须放在 verification",
        "输出根目录；发现输入缺陷时交由负责人处理。",
        "",
        "### 交互与权限",
        "",
        "- 负责人（内部协议角色 Human）在 Agent 对话中说明目标、回答工程问题，并明确决定 review、waiver、",
        "  freeze 等 gate。",
        "- Agent 一旦因为需要负责人输入而停下，必须先把问题、选项、推荐项和影响登记到",
        "  项目控制状态。计划建立前使用项目级目标 `project`；已有工作流或工作节点后绑定",
        "  最具体的对象。负责人可在 Dashboard 或当前 Agent 对话回答；对话中的答案必须由",
        "  Agent 立即用 `agent-question answer` 写回同一问题。不得只使用未登记的原生终端",
        "  临时选择器，也不得让两个入口形成两套问题状态。",
        "- 当前 Agent 对话必须显示已登记问题的 ID、正文、上下文、全部选项、推荐项和影响。",
        "  Kimi 交互会话使用成对 checkpoint：先执行 `agent-question ask --no-wait` 并展示",
        "  返回的问题，再立即把 `agent-question await QUESTION_ID --timeout 300` 启动为 Kimi",
        "  Bash 后台任务，然后把普通输入框还给负责人；等待负责人时不得前台执行 `await` 或",
        "  调用 `WaitFor`。负责人在对话中回答后，Main Agent 必须立即用 `agent-question answer`",
        "  写回同一 ID；Dashboard 将实时同步为已回答。负责人在 Dashboard 回答后，同一 CLI",
        "  后台 checkpoint 必须完成并通知 Main Agent。单独使用 `--no-wait` 而不建立后台",
        "  checkpoint 属于错误。其他 runtime",
        "  若没有等价的完成通知后台任务，则保留阻塞型 `ask`。Dashboard 答案是持久化状态，",
        "  不会向没有活动 checkpoint 的 idle 会话注入 prompt。",
        "- Agent 开始非简单分析或后台子任务前必须登记 Activity。计划建立前使用",
        "  `activity start project`，使负责人不依赖 SSH 或终端也能看到真实运行状态。",
        "- Agent 在对话后自行调用 verif-harness CLI；CLI 默认值不构成负责人授权。",
        "- 多 Agent 协作只使用本项目已经选择的单一 runtime（Codex 或 Kimi）的原生",
        "  subagent 能力；verif-harness 不启动另一种 runtime，也不自建隐藏 worker。",
        "- 当前项目的 Main Agent 是唯一负责人交互入口和控制面写者。subagent 只执行",
        "  Main Agent 给出的有边界任务并返回结构化结果，不得直接调用 agent-question、",
        "  review、waive、freeze、record 或 evidence，也不得直接向负责人提问或审批 gate。",
        "- Main Agent 分派前先用 `agent-work candidates` 读取可并行动作，再为每个 child",
        "  执行 `agent-work claim`。只并行彼此独立的节点；写任务必须声明互不重叠的",
        "  `--write-scope`。runtime 负责线程和上下文，SQLite claim 只负责项目级防重、",
        "  revision 绑定、heartbeat 和 Dashboard 可观测性。",
        "- write scope 不能覆盖 `.verif-harness`、`.harness-config.json`、`.git`、`.deps`、",
        "  runtime 配置、`AGENTS.md` 或只读 RTL/spec（保留路径按大小写不敏感匹配）。",
        "  scope 是协作合同而不是 OS 级沙箱；Main Agent 必须检查实际 diff。",
        "  不受信任的 child 必须使用隔离 worktree 或更严格的 runtime sandbox。",
        "- subagent 缺少输入时向 Main Agent 返回 NEEDS_HUMAN 结构；Main Agent 先协调，",
        "  并用 `agent-work heartbeat --phase WAITING_FOR_PARENT` 记录。确需工程判断时，",
        "  只有 Main Agent 才登记 agent-question。负责人回答后由 Main Agent 决定续派。",
        "- Main Agent 必须等待所分派的结果、复核实际文件和检查输出，再用",
        "  `agent-work finish` 关闭 assignment 并重新计算 closure。assignment/subagent 完成、多数",
        "  Agent 同意或 Activity COMPLETED 都不是 evidence，也不会把节点改成 VALID。",
        "- 生成文件只是 review candidate。文件存在、模板已复制或 Agent 自检通过，",
        "  都不等于语义已批准或 evidence 已通过。",
        "- VDOC 必须按“负责人审批文档撰写方案 → Agent 撰写正文 →",
        "  负责人验收正文内容”串行推进。方案未进入 `ACTIVE` 前，Agent 只能",
        "  提交 `document-writing-plan`；不得生成或修改正式正文、执行 `docs sync`、",
        "  创建 `document-deliverable`，或要求负责人同时审批方案和验收正文。",
        "- 只有用户明确要求提前试写时，才可在方案批准前生成“未批准预览草稿”；",
        "  该草稿不得同步为正文语义版本，不得创建内容验收节点，也不得作为任何",
        "  完成、证据或下游实现授权。",
        "- 负责人提交文档交付节点的验收结论后，Main Agent 必须读取",
        "  `agent-review-check list --status PENDING` 并检查当前审批、正文和依赖影响。",
        "  Agent 自行判断是否需要负责人确认：需要时用绑定该交付节点的",
        "  `agent-question ask` 提问；不需要或所有问题回答并重新分析后，用",
        "  `agent-review-check complete REVIEW_ID --summary ...` 完成本轮检查。",
        "  未完成 Agent 检查或仍有开放问题时，节点不得显示为正文验收通过。",
        "- capability 写入验证资产前，必须读取本文件，执行 `docs sync`，查询当前",
        "  `status`/`closure`，并读取下列与当前动作相关且已经评审的合同；VDOC 仅在",
        "  文档撰写方案已进入 `ACTIVE` 后执行 `docs sync`。",
        "- 文档状态、修订记录、评审追踪与负责人评审意见通过 `docs status`",
        "  或 `docs render` 按需投影，不在验证文档正文中手工维护。",
        "- 所需合同缺失或未解决时，返回 VDOC 或负责该目标的 Workstream；不得猜测后继续。",
        "- 本项目不采用 Stage 或 Spec Kit；不得创建 `spec/plan/tasks` 流水线或按阶段阻塞工作域。",
        "",
        "### 必读上下文路由",
        "",
    ]
    if document_root is None:
        lines.extend([
            "VDOC 文档路由尚未建立。执行实现类 capability 前，必须通过 `plan VDOC`",
            "生成缺失模板，并由 Agent 与负责人逐项确认验证范围、检查方法、覆盖目标和完成标准。",
        ])
    else:
        lines.append(f"VDOC 文档根目录：`{document_root}`")
        lines.append("")
        for filename, _title, workstreams in VDOC_DOCUMENTS.values():
            owners = ", ".join(workstreams)
            lines.append(f"- `{document_root}/{filename}` — 维护者：{owners}")
        lines.extend([
            "",
            "只读取当前动作需要的合同。列出的文档尚不存在或未经评审时，将依赖视为",
            "pending 并返回 VDOC/closure，不得虚构项目语义。",
        ])
    lines.extend(["", AGENTS_MANAGED_END])
    return "\n".join(lines)


def update_project_agents(path: Path, block: str) -> None:
    if path.is_symlink():
        raise HarnessError(f"拒绝跟随项目指令符号链接: {path}")
    if path.exists() and not path.is_file():
        raise HarnessError(f"项目指令路径不是普通文件: {path}")
    source = path.read_text(encoding="utf-8") if path.exists() else ""
    begin_count = source.count(AGENTS_MANAGED_BEGIN)
    end_count = source.count(AGENTS_MANAGED_END)
    if (begin_count != end_count or begin_count > 1
            or (begin_count == 1 and source.find(AGENTS_MANAGED_BEGIN) > source.find(AGENTS_MANAGED_END))):
        raise HarnessError(f"AGENTS.md 中的 verif-harness managed block 损坏: {path}")
    if begin_count == 1:
        prefix, remainder = source.split(AGENTS_MANAGED_BEGIN, 1)
        _managed, suffix = remainder.split(AGENTS_MANAGED_END, 1)
        rendered = f"{prefix}{block}{suffix}"
    else:
        separator = "\n\n" if source and not source.endswith("\n\n") else ""
        rendered = f"{source}{separator}{block}\n"
    atomic_text(path, rendered)


def git_revision(root: Path) -> str | None:
    checked = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], check=False,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )
    value = checked.stdout.strip()
    return value if checked.returncode == 0 and len(value) == 40 else None


def relative_path(root: Path, value: str | Path) -> str:
    candidate = Path(value)
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        relative = resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise HarnessError(f"路径必须位于项目内: {value}") from exc
    return relative.as_posix() or "."


def input_path(root: Path, value: str | Path) -> str:
    """Keep project-local inputs relative and explicit external inputs absolute."""
    candidate = Path(value)
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix() or "."
    except ValueError:
        return str(resolved)


def resolved_path(root: Path, value: str | Path) -> Path:
    candidate = Path(value)
    return candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()


def path_is_within(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def source_inventory(
    root: Path, additional_inputs: Iterable[str] = (), limit: int = 10000,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    visited: set[Path] = set()
    roots: list[Path] = []
    seen_roots: set[Path] = set()
    for value in additional_inputs:
        source = resolved_path(root, value)
        if source not in seen_roots:
            roots.append(source)
            seen_roots.add(source)
    if root.resolve() not in seen_roots:
        roots.append(root.resolve())
    for source in roots:
        candidates = [source] if source.is_file() else sorted(source.rglob("*"))
        for path in candidates:
            canonical = path.resolve()
            if canonical in visited or path.is_symlink() or not path.is_file():
                continue
            visited.add(canonical)
            relative_to_source = Path(path.name) if source.is_file() else path.relative_to(source)
            if any(part in IGNORED_PARTS for part in relative_to_source.parts):
                continue
            suffix = path.suffix.lower()
            explicitly_named_file = source.is_file() and path == source
            if (suffix not in RTL_SUFFIXES | DOC_SUFFIXES | {".json", ".yaml", ".yml", ".toml", ".f"}
                    and not explicitly_named_file):
                continue
            stat = path.stat()
            kind = (
                "rtl" if suffix in RTL_SUFFIXES else
                "document" if suffix in DOC_SUFFIXES else
                "metadata" if suffix in {".json", ".yaml", ".yml", ".toml", ".f"} else
                "verification-asset"
            )
            rows.append({"path": input_path(root, path), "kind": kind, "size": stat.st_size})
            if len(rows) >= limit:
                return rows
    return rows


def capabilities() -> dict[str, Any]:
    groups = {
        "reasoning": {"codex": ("codex",), "kimi": ("kimi", "kimi-cli"), "claude": ("claude",)},
        "simulation": {"verilator": ("verilator",), "vcs": ("vcs",), "xrun": ("xrun",), "vsim": ("vsim",)},
        "debug": {"verdi": ("verdi",), "simvision": ("simvision",), "visualizer": ("visualizer",)},
        "scheduler": {"bsub": ("bsub",)},
        "formal_lint": {"jaspergold": ("jg", "jaspergold"), "vcformal": ("vcf", "vcformal"), "spyglass": ("spyglass",)},
        "source": {"git": ("git",)},
    }
    result: dict[str, Any] = {}
    for group, commands in groups.items():
        result[group] = {}
        for name, candidates in commands.items():
            executable = next((shutil.which(item) for item in candidates if shutil.which(item)), None)
            result[group][name] = {"available": executable is not None, "executable": executable}
    return result


SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS nodes (
  id TEXT PRIMARY KEY, type TEXT NOT NULL, title TEXT NOT NULL, workstream TEXT,
  status TEXT NOT NULL, data_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS edges (
  source TEXT NOT NULL, target TEXT NOT NULL, relation TEXT NOT NULL, origin TEXT NOT NULL,
  confidence REAL NOT NULL, data_json TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY (source, target, relation)
);
CREATE TABLE IF NOT EXISTS workstreams (
  name TEXT PRIMARY KEY, lifecycle TEXT NOT NULL, revision INTEGER NOT NULL,
  objective TEXT NOT NULL, desired_json TEXT NOT NULL, exit_json TEXT NOT NULL,
  decisions_json TEXT NOT NULL, context_json TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
  id TEXT PRIMARY KEY, workstream TEXT NOT NULL, revision INTEGER NOT NULL, verdict TEXT NOT NULL,
  reviewer TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, subject TEXT NOT NULL, revision TEXT,
  payload_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS findings (
  id TEXT PRIMARY KEY, subject TEXT NOT NULL, severity TEXT NOT NULL, status TEXT NOT NULL,
  cause_event TEXT, details TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence (
  id TEXT PRIMARY KEY, subject TEXT NOT NULL, kind TEXT NOT NULL, source TEXT NOT NULL,
  digest TEXT, verdict TEXT NOT NULL, data_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS actions (
  id TEXT PRIMARY KEY, workstream TEXT NOT NULL, kind TEXT NOT NULL, target TEXT NOT NULL,
  priority INTEGER NOT NULL, status TEXT NOT NULL, executor TEXT NOT NULL, suggested_mode TEXT,
  reason TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS baselines (
  id TEXT PRIMARY KEY, workstream TEXT, revision INTEGER, kind TEXT NOT NULL, digest TEXT NOT NULL,
  path TEXT NOT NULL, reviewer TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY, path TEXT UNIQUE NOT NULL, title TEXT NOT NULL, workstream TEXT NOT NULL,
  desired_id TEXT, owner TEXT NOT NULL, semantic_revision INTEGER NOT NULL, digest TEXT NOT NULL,
  status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS document_revisions (
  document_id TEXT NOT NULL, semantic_revision INTEGER NOT NULL, digest TEXT NOT NULL,
  summary TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY (document_id, semantic_revision)
);
CREATE TABLE IF NOT EXISTS document_reviews (
  id TEXT PRIMARY KEY, document_id TEXT NOT NULL, semantic_revision INTEGER NOT NULL,
  verdict TEXT NOT NULL, reviewer TEXT NOT NULL, notes TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS document_items (
  id TEXT PRIMARY KEY, document_id TEXT NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL,
  anchor TEXT, status TEXT NOT NULL, owner TEXT, review_trigger TEXT,
  affects_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS activities (
  id TEXT PRIMARY KEY, node_id TEXT NOT NULL, workstream TEXT, operation TEXT NOT NULL,
  status TEXT NOT NULL, actor TEXT NOT NULL, message TEXT NOT NULL,
  progress_current INTEGER, progress_total INTEGER, log_path TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, ended_at TEXT
);
CREATE TABLE IF NOT EXISTS agent_assignments (
  id TEXT PRIMARY KEY, action_id TEXT NOT NULL, node_id TEXT NOT NULL,
  workstream TEXT NOT NULL, workstream_revision INTEGER NOT NULL,
  definition_digest TEXT NOT NULL, runtime TEXT NOT NULL,
  agent_id TEXT NOT NULL, parent_agent_id TEXT NOT NULL, role TEXT NOT NULL,
  runtime_ref TEXT, status TEXT NOT NULL, activity_id TEXT NOT NULL,
  lease_seconds INTEGER NOT NULL, lease_expires_at TEXT NOT NULL,
  heartbeat_at TEXT NOT NULL, write_scope_json TEXT NOT NULL,
  summary TEXT NOT NULL, result_json TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  ended_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS agent_assignments_active_node
  ON agent_assignments(node_id) WHERE status='ACTIVE';
CREATE UNIQUE INDEX IF NOT EXISTS agent_assignments_active_agent
  ON agent_assignments(agent_id) WHERE status='ACTIVE';
CREATE TABLE IF NOT EXISTS human_actions (
  id TEXT PRIMARY KEY, target TEXT NOT NULL, target_type TEXT NOT NULL,
  action TEXT NOT NULL, status TEXT NOT NULL, reviewer TEXT NOT NULL, reason TEXT NOT NULL,
  payload_json TEXT NOT NULL, resolved_by TEXT, resolution TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_questions (
  id TEXT PRIMARY KEY, target TEXT NOT NULL, target_type TEXT NOT NULL,
  workstream TEXT NOT NULL, node_id TEXT,
  prompt TEXT NOT NULL, context TEXT NOT NULL, options_json TEXT NOT NULL,
  recommended_option TEXT, status TEXT NOT NULL, blocking INTEGER NOT NULL,
  asked_by TEXT NOT NULL, activity_id TEXT,
  answer_option TEXT, answer_text TEXT, answered_by TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, answered_at TEXT
);
CREATE TABLE IF NOT EXISTS node_closure_reviews (
  id TEXT PRIMARY KEY, node_id TEXT NOT NULL, workstream TEXT NOT NULL,
  revision INTEGER NOT NULL, assessment_digest TEXT NOT NULL, verdict TEXT NOT NULL,
  reviewer TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS node_plan_reviews (
  id TEXT PRIMARY KEY, node_id TEXT NOT NULL, workstream TEXT NOT NULL,
  revision INTEGER NOT NULL, definition_digest TEXT NOT NULL, verdict TEXT NOT NULL,
  reviewer TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS node_plan_section_reviews (
  id TEXT PRIMARY KEY, node_id TEXT NOT NULL, workstream TEXT NOT NULL,
  revision INTEGER NOT NULL, definition_digest TEXT NOT NULL, section TEXT NOT NULL,
  verdict TEXT NOT NULL, reviewer TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS document_delivery_reviews (
  id TEXT PRIMARY KEY, node_id TEXT NOT NULL, workstream TEXT NOT NULL,
  revision INTEGER NOT NULL, definition_digest TEXT NOT NULL,
  document_id TEXT NOT NULL, semantic_revision INTEGER NOT NULL,
  document_digest TEXT NOT NULL, verdict TEXT NOT NULL,
  reviewer TEXT NOT NULL, notes TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS document_delivery_provisionals (
  review_id TEXT PRIMARY KEY, owner TEXT NOT NULL, review_trigger TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS review_change_items (
  review_id TEXT NOT NULL, sequence INTEGER NOT NULL, operation TEXT NOT NULL,
  target TEXT NOT NULL, instruction TEXT NOT NULL,
  PRIMARY KEY (review_id, sequence)
);
CREATE TABLE IF NOT EXISTS review_agent_checks (
  review_id TEXT PRIMARY KEY, node_id TEXT NOT NULL, status TEXT NOT NULL,
  checked_by TEXT, summary TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, checked_at TEXT
);
"""


@dataclass
class ProjectStore:
    root: Path

    def __post_init__(self) -> None:
        self.root = self.root.resolve()
        self.state = self.root / STATE_DIR
        self.database = self.state / "model.sqlite3"
        self._dashboard_schema_ready = False

    @property
    def initialized(self) -> bool:
        return (self.state / "project.json").is_file() and self.database.is_file()

    def bootstrap_refresh_prompt(self) -> dict[str, Any]:
        """Describe the Human confirmations required before a path refresh."""
        self.require()
        manifest = json.loads((self.state / "project.json").read_text(encoding="utf-8"))
        dut = manifest.get("dut", {})
        verification_inputs = (
            manifest.get("verification_inputs")
            if isinstance(manifest.get("verification_inputs"), dict) else {}
        )
        current = {
            "project_name": manifest.get("project_name"),
            "rtl_roots": manifest.get("rtl_roots", []),
            "dut_top": dut.get("top_module"),
            "dut_top_file": dut.get("top_file"),
            "docs_roots": manifest.get("docs_roots", []),
            "verif_root": manifest.get("verif_root"),
            "testbench_root": verification_inputs.get("testbench_root"),
            "reference_model": verification_inputs.get("reference_model"),
            "verification_scripts": verification_inputs.get("scripts", []),
        }
        return {
            "schema": "BootstrapReconfiguration/1",
            "status": "ACTION_REQUIRED",
            "message": "请在当前对话按顺序逐题确认 bootstrap 参数；尚未修改任何配置。",
            "current": current,
            "interaction": {
                "mode": "SEQUENTIAL",
                "one_question_at_a_time": True,
                "current_question_id": "rtl_roots",
                "final_confirmation_required": True,
            },
            "questions_for_human": [
                {"sequence": 1, "id": "rtl_roots", "required": True, "current": current["rtl_roots"],
                 "question": "只读 RTL root 是哪些目录？"},
                {"sequence": 2, "id": "dut_top", "required": True, "current": current["dut_top"],
                 "question": "DUT top 模块名是什么？"},
                {"sequence": 3, "id": "dut_top_file", "required": True, "current": current["dut_top_file"],
                 "question": "DUT top file 是哪个文件？"},
                {"sequence": 4, "id": "verif_root", "required": True, "current": current["verif_root"],
                 "question": "项目内 verification 输出目录是什么？"},
                {"sequence": 5, "id": "docs_roots", "required": False, "skip_allowed": True,
                 "current": current["docs_roots"],
                 "question": "可选 RTL spec 路径是哪些；保留、替换还是移除？"},
                {"sequence": 6, "id": "testbench_root", "required": False, "skip_allowed": True,
                 "current": current["testbench_root"],
                 "question": "是否已有 testbench 目录；保留、替换还是移除？"},
                {"sequence": 7, "id": "reference_model", "required": False, "skip_allowed": True,
                 "current": current["reference_model"],
                 "question": "是否已有 reference/golden model；保留、替换还是移除？"},
                {"sequence": 8, "id": "verification_scripts", "required": False,
                 "skip_allowed": True,
                 "current": current["verification_scripts"],
                 "question": "是否已有编译、仿真或回归脚本；保留、替换还是移除？"},
            ],
        }

    def require(self) -> None:
        if not self.initialized:
            raise HarnessError(f"项目尚未 bootstrap: {self.root}")

    def connect(self) -> sqlite3.Connection:
        self.state.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.executescript(SCHEMA)
        observed = connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if observed is not None and int(observed["value"]) != SCHEMA_VERSION:
            connection.close()
            raise HarnessError("检测到不兼容的 v1 开发态数据库；请移走 .verif-harness 后重新 bootstrap")
        connection.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)", (str(SCHEMA_VERSION),))
        connection.commit()
        self._dashboard_schema_ready = True
        return connection

    def ensure_dashboard_schema(self) -> None:
        """Install additive monitoring tables once per store instance."""
        if not self._dashboard_schema_ready:
            with self.connect():
                pass

    def read_connect(self) -> sqlite3.Connection:
        self.require()
        connection = sqlite3.connect(
            f"{self.database.as_uri()}?mode=ro", uri=True, timeout=30,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def bootstrap(
        self, project_name: str | None = None, runtime: str = "auto",
        rtl_roots: Iterable[str] = (), docs_roots: Iterable[str] = (),
        verif_root: str | None = None, dut_top: str | None = None,
        dut_top_file: str | None = None, refresh: bool = False,
        clear_docs_roots: bool = False,
        testbench_root: str | None = None,
        reference_model: str | None = None,
        verification_scripts: Iterable[str] = (),
        clear_testbench_root: bool = False,
        clear_reference_model: bool = False,
        clear_verification_scripts: bool = False,
    ) -> dict[str, Any]:
        if self.initialized and not refresh:
            raise HarnessError("项目已经 bootstrap；如需刷新非语义清单，请使用 --refresh")
        if not self.root.is_dir():
            raise HarnessError(f"项目目录不存在: {self.root}")
        previous: dict[str, Any] = {}
        if self.initialized:
            previous = json.loads((self.state / "project.json").read_text(encoding="utf-8"))
        caps = capabilities()
        reasoning = caps["reasoning"]
        detected = [name for name in ("codex", "kimi", "claude") if reasoning[name]["available"]]
        selected = runtime
        if runtime == "auto":
            selected = str(previous.get("runtime") or (detected[0] if len(detected) == 1 else "unselected"))
        rtl_values = [input_path(self.root, item) for item in rtl_roots] or list(previous.get("rtl_roots", []))
        docs_values = (
            [] if clear_docs_roots
            else [input_path(self.root, item) for item in docs_roots]
            or list(previous.get("docs_roots", []))
        )
        previous_inputs = (
            previous.get("verification_inputs")
            if isinstance(previous.get("verification_inputs"), dict) else {}
        )
        testbench_value = (
            None if clear_testbench_root
            else input_path(self.root, testbench_root) if testbench_root is not None
            else previous_inputs.get("testbench_root")
        )
        reference_model_value = (
            None if clear_reference_model
            else input_path(self.root, reference_model) if reference_model is not None
            else previous_inputs.get("reference_model")
        )
        script_inputs = list(verification_scripts)
        previous_scripts = previous_inputs.get("scripts", [])
        if not isinstance(previous_scripts, list):
            previous_scripts = []
        raw_verification_script_values = (
            [] if clear_verification_scripts
            else [input_path(self.root, item) for item in script_inputs]
            if script_inputs else [str(item) for item in previous_scripts if str(item).strip()]
        )
        verification_script_values = list(dict.fromkeys(raw_verification_script_values))
        verif_value = relative_path(self.root, verif_root) if verif_root is not None else str(previous.get("verif_root", "."))
        previous_dut = previous.get("dut", {}) if isinstance(previous.get("dut"), dict) else {}
        dut_top = dut_top or previous_dut.get("top_module")
        dut_top_file = dut_top_file or previous_dut.get("top_file")
        if not rtl_values or not dut_top or not dut_top_file:
            raise HarnessError("bootstrap 必须明确提供 rtl root、dut top 和 dut top file")
        for value in rtl_values:
            if not resolved_path(self.root, value).is_dir():
                raise HarnessError(f"RTL root 不是目录: {value}")
        top_file_value = input_path(self.root, dut_top_file)
        top_file_path = resolved_path(self.root, top_file_value)
        if not top_file_path.is_file():
            raise HarnessError(f"DUT top file 不是文件: {top_file_value}")
        if not any(path_is_within(top_file_path, resolved_path(self.root, value)) for value in rtl_values):
            raise HarnessError("DUT top file 必须位于某个已声明的 RTL root 内")
        for value in docs_values:
            if not resolved_path(self.root, value).exists():
                raise HarnessError(f"RTL specification 输入不存在: {value}")
        if testbench_value is not None and not resolved_path(self.root, testbench_value).is_dir():
            raise HarnessError(f"testbench 路径不是目录: {testbench_value}")
        if reference_model_value is not None and not resolved_path(self.root, reference_model_value).exists():
            raise HarnessError(f"reference/golden model 路径不存在: {reference_model_value}")
        for value in verification_script_values:
            if not resolved_path(self.root, value).is_file():
                raise HarnessError(f"验证脚本不是文件: {value}")
        vdoc_document_root = previous.get("vdoc_document_root")
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "project_name": project_name or previous.get("project_name") or self.root.name,
            "project_root": str(self.root), "runtime": selected,
            "baseline_revision": git_revision(self.root), "rtl_roots": rtl_values,
            "docs_roots": docs_values, "verif_root": verif_value,
            "verification_inputs": {
                "testbench_root": testbench_value,
                "reference_model": reference_model_value,
                "scripts": verification_script_values,
            },
            "dut": {"top_module": dut_top, "top_file": top_file_value},
            "vdoc_document_root": vdoc_document_root,
            "project_instructions": {"path": "AGENTS.md", "managed_by": ["bootstrap", "VDOC"]},
            "inventory_count": 0, "capabilities": caps, "updated_at": now(),
        }
        capability_config = self.root / ".harness-config.json"
        capability_projection = capability_config_projection(capability_config, manifest, refresh)
        update_project_agents(self.root / "AGENTS.md", project_agents_block(manifest, vdoc_document_root))
        if capability_projection is not None:
            atomic_json(capability_config, capability_projection)
        inventory_inputs = [*rtl_values, *docs_values, *verification_script_values]
        if testbench_value is not None:
            inventory_inputs.append(testbench_value)
        if reference_model_value is not None:
            inventory_inputs.append(reference_model_value)
        inventory = source_inventory(self.root, inventory_inputs)
        manifest["inventory_count"] = len(inventory)
        atomic_json(self.state / "project.json", manifest)
        atomic_json(self.state / "inventory.json", inventory)
        with self.connect() as connection:
            for item in inventory:
                node_type = "implementation" if item["kind"] == "rtl" else item["kind"]
                self.upsert_node(connection, f"file:{item['path']}", node_type, item["path"],
                                 Validity.UNKNOWN, data=item, preserve_status=True)
        self.write_model_projection()
        return manifest

    def upsert_node(
        self, connection: sqlite3.Connection, node_id: str, node_type: str, title: str,
        status: Validity | str = Validity.UNKNOWN, workstream: str | None = None,
        data: dict[str, Any] | None = None, preserve_status: bool = False,
    ) -> None:
        timestamp = now()
        status_update = "nodes.status" if preserve_status else "excluded.status"
        connection.execute(f"""
            INSERT INTO nodes(id,type,title,workstream,status,data_json,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET type=excluded.type,title=excluded.title,
              workstream=COALESCE(excluded.workstream,nodes.workstream),status={status_update},
              data_json=excluded.data_json,updated_at=excluded.updated_at
        """, (node_id, node_type, title, workstream,
              status.value if isinstance(status, Validity) else status,
              json_text(data or {}), timestamp, timestamp))

    @staticmethod
    def normalize_workstream(value: str) -> str:
        name = value.upper()
        if name not in WORKSTREAM_TEMPLATES:
            raise HarnessError("workstream 必须是 " + ", ".join(WORKSTREAM_TEMPLATES))
        return name

    @staticmethod
    def _reconcile_default_dependencies(connection: sqlite3.Connection) -> int:
        current: dict[tuple[str, str], str] = {}
        vdoc_semantic: dict[str, list[dict[str, str]]] = {}
        for row in connection.execute("SELECT name,desired_json FROM workstreams"):
            for desired in json.loads(row["desired_json"]):
                current[(row["name"], desired["key"])] = desired["id"]
                if (
                    row["name"] == "VDOC"
                    and desired.get("role") == "document-semantic-unit"
                    and desired.get("document_key")
                ):
                    vdoc_semantic.setdefault(str(desired["document_key"]), []).append({
                        "id": desired["id"],
                        "parent_role": str(desired.get("parent_role") or ""),
                    })
        connection.execute("DELETE FROM edges WHERE relation='DEPENDS_ON' AND origin='planner-default'")
        count = 0
        timestamp = now()
        for dependent_key, prerequisite_key in DEFAULT_DEPENDENCIES:
            dependent = current.get(dependent_key)
            prerequisite = current.get(prerequisite_key)
            if dependent is None or prerequisite is None:
                continue
            prerequisites = [prerequisite]
            if prerequisite_key[0] == "VDOC":
                candidates = vdoc_semantic.get(prerequisite_key[1], [])
                delivery_candidates = [
                    item["id"] for item in candidates
                    if item["parent_role"] == "document-deliverable"
                ]
                plan_candidates = [
                    item["id"] for item in candidates
                    if item["parent_role"] == "document-writing-plan"
                ]
                prerequisites = delivery_candidates or plan_candidates or prerequisites
            for resolved_prerequisite in prerequisites:
                connection.execute(
                    "INSERT OR REPLACE INTO edges VALUES(?,?,?,?,?,?,?)",
                    (dependent, resolved_prerequisite, "DEPENDS_ON", "planner-default", 1.0,
                     json_text({
                         "dependent": list(dependent_key),
                         "prerequisite": list(prerequisite_key),
                         "resolved_prerequisite": resolved_prerequisite,
                     }), timestamp),
                )
                count += 1
        return count

    def planning_context(self, workstream: str) -> dict[str, Any]:
        model = self.model()
        manifest = json.loads((self.state / "project.json").read_text(encoding="utf-8"))
        relevant = [item for item in model["nodes"] if item.get("workstream") in {None, workstream}]
        return {
            "project": manifest["project_name"], "revision": manifest.get("baseline_revision"),
            "dut": manifest.get("dut"), "rtl_roots": manifest.get("rtl_roots", []),
            "docs_roots": manifest.get("docs_roots", []),
            "model_summary": {
                "node_count": len(model["nodes"]), "edge_count": len(model["edges"]),
                "open_findings": sum(item["status"] == "OPEN" for item in model["findings"]),
                "workstream_nodes": sum(item.get("workstream") == workstream for item in model["nodes"]),
            },
            "model_excerpt": {
                "nodes": relevant[:200],
                "relations": model["edges"][:200],
                "open_findings": [item for item in model["findings"] if item["status"] == "OPEN"][:100],
                "truncated": len(relevant) > 200 or len(model["edges"]) > 200,
            },
        }

    def _document_path_allowed(self, relative: str) -> None:
        manifest = json.loads((self.state / "project.json").read_text(encoding="utf-8"))
        target = (self.root / relative).resolve()
        for value in [*manifest.get("rtl_roots", []), *manifest.get("docs_roots", [])]:
            source = resolved_path(self.root, value)
            if source.is_dir() and (target == source or source in target.parents):
                raise HarnessError(f"文档输出不得位于只读 RTL/spec 输入内: {relative}")
            if source.is_file() and target == source:
                raise HarnessError(f"文档输出与只读 RTL/spec 输入冲突: {relative}")

    def _project_or_declared_input_path(self, value: str | Path) -> str:
        candidate = resolved_path(self.root, value)
        if path_is_within(candidate, self.root):
            return candidate.relative_to(self.root).as_posix() or "."
        manifest = json.loads((self.state / "project.json").read_text(encoding="utf-8"))
        declared = [*manifest.get("rtl_roots", []), *manifest.get("docs_roots", [])]
        if any(path_is_within(candidate, resolved_path(self.root, item)) for item in declared):
            return str(candidate)
        raise HarnessError(f"项目外路径必须位于已声明的只读 RTL/spec 输入内: {value}")

    @staticmethod
    def _digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _register_document(
        self, connection: sqlite3.Connection, document_id: str, relative: str,
        title: str, desired_id: str | None, owner: str, summary: str,
    ) -> tuple[bool, dict[str, Any]]:
        path = self.root / relative
        if path.is_symlink():
            raise HarnessError(f"拒绝跟随验证文档符号链接: {relative}")
        if not path.is_file():
            raise HarnessError(f"验证文档不存在或不是文件: {relative}")
        digest = self._digest(path)
        existing = connection.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
        changed = existing is not None and existing["digest"] != digest
        revision = int(existing["semantic_revision"]) + 1 if changed else int(existing["semantic_revision"]) if existing else 1
        status = Validity.REVIEW_REQUIRED.value if existing is None or changed else existing["status"]
        timestamp = now()
        if existing is None:
            connection.execute(
                "INSERT INTO documents VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (document_id, relative, title, "VDOC", desired_id, owner, revision, digest,
                 status, timestamp, timestamp),
            )
            connection.execute(
                "INSERT INTO document_revisions VALUES(?,?,?,?,?)",
                (document_id, revision, digest, summary, timestamp),
            )
        else:
            connection.execute(
                "UPDATE documents SET path=?,title=?,desired_id=?,owner=?,semantic_revision=?,digest=?,status=?,updated_at=? WHERE id=?",
                (relative, title, desired_id, owner, revision, digest, status, timestamp, document_id),
            )
            if changed:
                connection.execute(
                    "INSERT INTO document_revisions VALUES(?,?,?,?,?)",
                    (document_id, revision, digest, summary, timestamp),
                )
        data = {
            "path": relative, "digest": digest, "semantic_revision": revision,
            "desired_id": desired_id, "owner": owner,
        }
        self.upsert_node(connection, f"file:{relative}", "artifact", relative,
                         Validity.UNKNOWN, data={"path": relative, "kind": "document"}, preserve_status=True)
        self.upsert_node(connection, document_id, "semantic-document", title, status, "VDOC", data)
        connection.execute(
            "INSERT OR REPLACE INTO edges VALUES(?,?,?,?,?,?,?)",
            (f"file:{relative}", document_id, "REPRESENTS", "runtime", 1.0, "{}", timestamp),
        )
        if desired_id:
            connection.execute(
                "INSERT OR REPLACE INTO edges VALUES(?,?,?,?,?,?,?)",
                (document_id, desired_id, "AFFECTS", "runtime", 1.0, "{}", timestamp),
            )
        return changed, {"id": document_id, "path": relative, "semantic_revision": revision,
                         "digest": digest, "status": status, "created": existing is None}

    def _materialize_vdoc_documents(self, desired_rows: list[dict[str, Any]], document_root: str) -> list[dict[str, Any]]:
        output = self.root / document_root
        output.mkdir(parents=True, exist_ok=True)
        changed_paths: list[tuple[str, int]] = []
        results: list[dict[str, Any]] = []
        skill_root = Path(__file__).resolve().parents[1] / "skills" / "verif-harness"
        with self.connect() as connection:
            for desired in desired_rows:
                contract = desired.get("document")
                if not contract:
                    continue
                candidate = output / contract["filename"]
                if candidate.is_symlink():
                    raise HarnessError(f"拒绝跟随验证文档符号链接: {candidate}")
                relative = relative_path(self.root, candidate)
                self._document_path_allowed(relative)
                target = self.root / relative
                source = skill_root / contract["template"]
                if not source.is_file():
                    raise HarnessError(f"VDOC 模板不存在: {contract['template']}")
                created = not target.exists()
                if created:
                    atomic_text(target, source.read_text(encoding="utf-8"))
                document_id = f"document:vdoc:{desired['key']}"
                owners = ",".join(contract["maintained_by"])
                changed, row = self._register_document(
                    connection, document_id, relative, desired["title"], desired["id"], owners,
                    "由 VDOC 模板创建" if created else "登记已有验证文档",
                )
                row["materialized"] = created
                results.append(row)
                if changed:
                    changed_paths.append((relative, row["semantic_revision"]))
        for relative, revision in changed_paths:
            self.record_change(relative, "modify", f"document-r{revision}")
        self.write_model_projection()
        return results

    def _load_desired_state_proposal(
        self, workstream: str, source: str | None,
        template_keys: set[str],
        external_parents: dict[str, dict[str, Any]] | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        if source is None:
            return [], None
        relative = self._project_or_declared_input_path(source)
        path = resolved_path(self.root, relative)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HarnessError(f"无法读取 desired-state proposal: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("schema") != "DesiredStateProposal/1":
            raise HarnessError("desired-state proposal schema 必须是 DesiredStateProposal/1")
        if str(payload.get("workstream", "")).upper() != workstream:
            raise HarnessError(f"desired-state proposal workstream 必须是 {workstream}")
        nodes = payload.get("nodes")
        if not isinstance(nodes, list) or not nodes:
            raise HarnessError("desired-state proposal nodes 必须是非空数组")
        normalized: list[dict[str, Any]] = []
        inherited = external_parents or {}
        seen = set(template_keys)
        proposal_keys: set[str] = set()
        supported_claims = set(CLAIMS.get(workstream, {}).values())
        if workstream == "VSTIM":
            supported_claims.update({"reachability-evidence", "determinism-evidence"})
        for index, item in enumerate(nodes):
            prefix = f"nodes[{index}]"
            if not isinstance(item, dict):
                raise HarnessError(f"{prefix} 必须是 object")
            key = str(item.get("key", "")).strip()
            if not DESIRED_KEY.fullmatch(key):
                raise HarnessError(f"{prefix}.key 只能使用小写字母、数字、点、下划线和连字符")
            if key in seen:
                raise HarnessError(f"desired-state key 重复: {key}")
            seen.add(key); proposal_keys.add(key)
            required_text = ("title", "statement", "purpose", "suggested_mode", "evidence_claim")
            values = {field: str(item.get(field, "")).strip() for field in required_text}
            missing = [field for field, value in values.items() if not value]
            if missing:
                raise HarnessError(f"{prefix} 缺少非空字段: {', '.join(missing)}")
            default_role = "document-writing-plan" if workstream == "VDOC" else "project-goal"
            role = str(item.get("role", default_role)).strip()
            allowed_roles = (
                PROJECT_NODE_ROLES[workstream]
                if workstream == "VDOC"
                else {"project-goal", "closure-evidence", *PROJECT_NODE_ROLES[workstream]}
            )
            if role not in allowed_roles:
                raise HarnessError(
                    f"{prefix}.role 必须是 " + ", ".join(sorted(allowed_roles))
                )
            parent_key = str(item.get("parent_key", "")).strip()
            if not parent_key:
                raise HarnessError(f"{prefix}.parent_key 必须指向模板或 proposal 节点")
            document_key = str(item.get("document_key", "")).strip()
            if workstream == "VDOC" and document_key not in VDOC_DOCUMENTS:
                raise HarnessError(
                    f"{prefix}.document_key 必须明确指定一份固定 VDOC 文档目录: "
                    + ", ".join(VDOC_DOCUMENTS)
                )
            claim = values["evidence_claim"]
            if workstream == "VDOC":
                if claim != "document-review":
                    raise HarnessError(f"{prefix}.evidence_claim 必须是 document-review")
            elif claim not in supported_claims:
                raise HarnessError(
                    f"{prefix}.evidence_claim 不支持: {claim}；可选值: "
                    + ", ".join(sorted(supported_claims))
                )
            lists: dict[str, list[str]] = {}
            for field in (
                "scope", "acceptance_criteria", "source_refs", "work_content",
                "implementation_approach", "deliverables", "quality_checks",
            ):
                raw = item.get(field)
                if not isinstance(raw, list) or not raw or not all(
                    isinstance(value, str) and value.strip() for value in raw
                ):
                    raise HarnessError(f"{prefix}.{field} 必须是非空字符串数组")
                lists[field] = [value.strip() for value in raw]
            raw_measures = item.get("progress_measures")
            if not isinstance(raw_measures, list) or not raw_measures:
                raise HarnessError(f"{prefix}.progress_measures 必须是非空对象数组")
            measures: list[dict[str, str]] = []
            for measure_index, measure in enumerate(raw_measures):
                if not isinstance(measure, dict):
                    raise HarnessError(f"{prefix}.progress_measures[{measure_index}] 必须是 object")
                fields = {
                    field: str(measure.get(field, "")).strip()
                    for field in ("id", "label", "unit", "target", "source")
                }
                missing_measure = [field for field, value in fields.items() if not value]
                if missing_measure:
                    raise HarnessError(
                        f"{prefix}.progress_measures[{measure_index}] 缺少非空字段: "
                        + ", ".join(missing_measure)
                    )
                measures.append(fields)
            required = item.get("required", True)
            if not isinstance(required, bool):
                raise HarnessError(f"{prefix}.required 必须是 boolean")
            internal_units: list[dict[str, Any]] = []
            semantic_manifest_digest = None
            if workstream == "VDOC":
                internal_units, semantic_manifest_digest = vdoc_internal_semantic_units(
                    key, role, lists,
                )
            normalized.append({
                "key": key, "title": values["title"], "statement": values["statement"],
                "purpose": values["purpose"], "scope": lists["scope"],
                "acceptance_criteria": lists["acceptance_criteria"],
                "source_refs": lists["source_refs"], "work_content": lists["work_content"],
                "implementation_approach": lists["implementation_approach"],
                "deliverables": lists["deliverables"], "progress_measures": measures,
                "quality_checks": lists["quality_checks"],
                "suggested_mode": values["suggested_mode"],
                "evidence_claim": claim, "role": role, "parent_key": parent_key,
                "document_key": document_key or None,
                "content_kind": (
                    "writing-plan" if role == "document-writing-plan"
                    else "semantic-acceptance" if role == "document-deliverable"
                    else "work-item"
                ),
                "required": required, "definition_origin": "project-proposal",
                "definition_status": "REVIEW_CANDIDATE",
                **({
                    "internal_semantic_units": internal_units,
                    "semantic_manifest_digest": semantic_manifest_digest,
                } if workstream == "VDOC" else {}),
                "role_description": (
                    "当前 DUT 的文档撰写方案节点；目标、内容、工程决定、输入和交付区块分别审批"
                    if workstream == "VDOC" and role == "document-writing-plan" else
                    "一份正式验证文档的公开正文验收节点；章节和依赖影响由内部语义单元定位"
                    if workstream == "VDOC" else
                    "项目级完成条件证据节点" if role == "closure-evidence"
                    else f"项目级 {role} 节点"
                ),
            })
        available = template_keys | set(inherited) | proposal_keys
        proposal_by_key = {item["key"]: item for item in normalized}
        all_by_key = {**inherited, **proposal_by_key}
        for item in normalized:
            if item["parent_key"] not in available:
                raise HarnessError(
                    f"{item['key']} 的 parent_key 不存在: {item['parent_key']}"
                )
            if item["parent_key"] == item["key"]:
                raise HarnessError(f"{item['key']} 不能把自己作为 parent")
            visited = {item["key"]}
            cursor = item["parent_key"]
            while cursor in all_by_key:
                if cursor in visited:
                    raise HarnessError(f"desired-state proposal 存在 parent 循环: {item['key']}")
                visited.add(cursor)
                cursor = str(all_by_key[cursor].get("parent_key") or "")
            if workstream == "VDOC":
                if cursor not in VDOC_DOCUMENTS:
                    raise HarnessError(
                        f"{item['key']} 的 parent_key 链必须归属于一份固定 VDOC 文档目录"
                    )
                if item["document_key"] != cursor:
                    raise HarnessError(
                        f"{item['key']} 的 document_key={item['document_key']} 与 parent_key 归属 {cursor} 不一致"
                    )
        return normalized, relative

    def _register_vdoc_deliverables(
        self, current_plan: dict[str, Any] | None,
        deliveries: list[dict[str, Any]], proposal_source: str | None,
    ) -> dict[str, Any]:
        """Attach semantic delivery nodes to an already-approved VDOC plan.

        This is deliberately an in-revision expansion: the approved writing-plan
        nodes and their review records remain unchanged, while delivery definitions
        become reviewable only after the plan gate has opened.
        """
        if current_plan is None:
            raise HarnessError(
                "必须先提交并批准 VDOC 文档撰写方案，才能登记正文内容验收节点"
            )
        if current_plan["lifecycle"] not in {"ACTIVE", "PARTIALLY_STALE", "SATISFIED"}:
            raise HarnessError(
                "当前 VDOC 文档撰写方案尚未批准；不能提前创建正文内容验收节点"
            )
        required_plans = [
            item for item in self._vdoc_writing_plan_desired(current_plan)
            if item.get("required", True)
        ]
        unapproved = [
            item["key"] for item in required_plans
            if self.node_plan_review_state(item["id"], current_plan, item)["status"] != "APPROVED"
        ]
        if unapproved:
            raise HarnessError(
                "必须先批准所有必需文档撰写方案，再登记正文内容验收节点: "
                + ", ".join(sorted(unapproved))
            )
        reserved = {
            item["key"] for item in current_plan["desired_state"]
            if item.get("role") != "document-deliverable"
        }
        collisions = sorted(item["key"] for item in deliveries if item["key"] in reserved)
        if collisions:
            raise HarnessError(
                "正文内容验收节点 key 与已批准方案或文档目录重复: "
                + ", ".join(collisions)
            )
        issues = self._vdoc_delivery_proposal_issues(current_plan, deliveries)
        if issues:
            raise HarnessError(
                "VDOC 正文内容验收范围不完整：" + "；".join(issues)
            )
        documents = {item["document_key"]: item for item in self.documents()}
        missing_documents = sorted({
            str(item.get("document_key")) for item in deliveries
            if item.get("document_key") not in documents
        })
        if missing_documents:
            raise HarnessError(
                "正文内容验收节点对应的验证文档尚未登记: "
                + ", ".join(missing_documents)
            )
        changed_documents = sorted({
            documents[str(item["document_key"])]["path"] for item in deliveries
            if documents[str(item["document_key"])]["content_changed"]
        })
        if changed_documents:
            raise HarnessError(
                "验证文档正文已变化；请在方案批准后先执行 docs sync，"
                "再登记绑定当前正文版本的内容验收节点: "
                + ", ".join(changed_documents)
            )

        revision = int(current_plan["revision"])
        retained = [
            item for item in current_plan["desired_state"]
            if item.get("role") != "document-deliverable"
            and not (
                item.get("role") == "document-semantic-unit"
                and item.get("parent_role") == "document-deliverable"
            )
        ]
        key_to_id = {item["key"]: item["id"] for item in retained}
        key_to_id.update({
            item["key"]: f"workstream:VDOC:r{revision}:desired:{item['key']}"
            for item in deliveries
        })
        delivery_rows: list[dict[str, Any]] = []
        for spec in deliveries:
            node_id = key_to_id[spec["key"]]
            row = {
                "id": node_id,
                "key": spec["key"],
                "title": spec["title"],
                "role": "document-deliverable",
                "required": spec.get("required", True),
                "suggested_mode": spec["suggested_mode"],
                "evidence_claim": spec["evidence_claim"],
                "evidence_contract": {
                    "version": "DocumentReviewPolicy/1",
                    "claim": "document-review",
                    "required": [
                        "已保存当前正文的评审记录",
                        "评审记录包含负责人和明确结论",
                    ],
                },
                "parent_key": spec.get("parent_key"),
                "parent_id": key_to_id.get(spec.get("parent_key")),
                "document_key": spec.get("document_key"),
                "content_kind": "semantic-acceptance",
                "visibility": "public",
                "visible_to_human": True,
                **{
                    field: spec[field] for field in (
                        "statement", "purpose", "scope", "acceptance_criteria",
                        "source_refs", "work_content", "implementation_approach",
                        "deliverables", "progress_measures", "quality_checks",
                        "definition_origin", "definition_status", "role_description",
                        "internal_semantic_units", "semantic_manifest_digest",
                    ) if field in spec
                },
            }
            delivery_rows.append(row)

        internal_rows: list[dict[str, Any]] = []
        for parent in delivery_rows:
            for spec in vdoc_internal_child_specs(parent):
                node_id = f"workstream:VDOC:r{revision}:desired:{spec['key']}"
                internal_rows.append({
                    **spec,
                    "id": node_id,
                    "parent_id": parent["id"],
                    "evidence_contract": {
                        "version": "DocumentReviewPolicy/1",
                        "claim": "document-review",
                        "required": [
                            "已保存当前语义工作单元的完成材料",
                            "完成材料与当前文档版本和节点定义一致",
                        ],
                    },
                })

        previous_deliveries = self._vdoc_delivery_desired(current_plan)
        previous_internal = [
            item for item in current_plan["desired_state"]
            if item.get("role") == "document-semantic-unit"
            and item.get("parent_role") == "document-deliverable"
        ]
        next_desired = [*retained, *delivery_rows, *internal_rows]
        timestamp = now()
        with self.connect() as connection:
            for item in [*previous_deliveries, *previous_internal]:
                connection.execute(
                    "UPDATE nodes SET workstream=NULL,status=?,updated_at=? WHERE id=?",
                    (Validity.STALE.value, timestamp, item["id"]),
                )
                connection.execute(
                    "DELETE FROM edges WHERE source=? AND relation='CHILD_OF'",
                    (item["id"],),
                )
            for row in [*delivery_rows, *internal_rows]:
                self.upsert_node(
                    connection, row["id"], "desired-state", row["title"],
                    Validity.REVIEW_REQUIRED, "VDOC", row,
                )
                connection.execute(
                    "INSERT OR REPLACE INTO edges VALUES(?,?,?,?,?,?,?)",
                    (
                        row["id"], row["parent_id"], "CHILD_OF", "planner-explicit",
                        1.0, json_text({
                            "child_key": row["key"], "parent_key": row["parent_key"],
                        }), timestamp,
                    ),
                )
            lifecycle = (
                "PARTIALLY_STALE"
                if current_plan["lifecycle"] == "PARTIALLY_STALE" else "ACTIVE"
            )
            connection.execute(
                "UPDATE workstreams SET desired_json=?,lifecycle=?,updated_at=? WHERE name='VDOC'",
                (json_text(next_desired), lifecycle, timestamp),
            )
            for document_key in sorted({str(item["document_key"]) for item in deliveries}):
                document = documents[document_key]
                connection.execute(
                    "UPDATE documents SET status=?,updated_at=? WHERE id=?",
                    (Validity.REVIEW_REQUIRED.value, timestamp, document["id"]),
                )
            default_dependency_count = self._reconcile_default_dependencies(connection)
        self.write_model_projection()
        self.write_workstream_projection("VDOC")
        result = self.workstream("VDOC")
        result.update({
            "desired_state_proposal": proposal_source,
            "project_goal_count": len(delivery_rows),
            "default_dependency_count": default_dependency_count,
            "vdoc_phase": "CONTENT_REVIEW",
            "questions_for_human": [],
        })
        result["auto_closure"] = self.evaluate_closure("VDOC")
        return result

    def design_workstream(
        self, workstream: str, objective: str | None, desired: list[str],
        exit_criteria: list[str], decisions: list[str], document_root: str | None = None,
        evidence_claims: list[str] | None = None, desired_file: str | None = None,
    ) -> dict[str, Any]:
        self.require()
        name = self.normalize_workstream(workstream)
        current_vdoc_plan: dict[str, Any] | None = None
        if name == "VDOC":
            try:
                current_vdoc_plan = self.workstream("VDOC")
            except HarnessError:
                current_vdoc_plan = None
        if document_root is not None and name != "VDOC":
            raise HarnessError("--document-root 只适用于 VDOC")
        template = WORKSTREAM_TEMPLATES[name]
        objective_value = objective.strip() if objective and objective.strip() else template["objective"]
        selected_claims = list(evidence_claims or [])
        if desired and desired_file:
            raise HarnessError("--desired 与 --desired-file 不能同时使用")
        if desired:
            if name == "VDOC":
                if selected_claims and (
                    len(selected_claims) != len(desired)
                    or set(selected_claims) != {"document-review"}
                ):
                    raise HarnessError("自定义 VDOC 目标的 evidence claim 只能是 document-review")
                desired_specs = [{
                    "key": f"custom-{index:03d}", "title": title, "suggested_mode": "review",
                    "role": "document-writing-plan", "evidence_claim": "document-review", "required": True,
                } for index, title in enumerate(desired, 1)]
            elif len(selected_claims) != len(desired):
                raise HarnessError("每个自定义 --desired 必须按相同顺序提供一个 --evidence-claim")
            else:
                supported_claims = set(CLAIMS[name].values())
                if name == "VSTIM":
                    supported_claims.update({"reachability-evidence", "determinism-evidence"})
                unsupported = sorted(set(selected_claims) - supported_claims)
                if unsupported:
                    raise HarnessError(
                        f"{name} 不支持 evidence claim: {', '.join(unsupported)}；可选值: "
                        + ", ".join(sorted(supported_claims))
                    )
                desired_specs = [{
                    "key": f"custom-{index:03d}", "title": title, "suggested_mode": "evidence",
                    "role": "capability", "evidence_claim": claim, "required": True,
                } for index, (title, claim) in enumerate(zip(desired, selected_claims), 1)]
        else:
            desired_specs = [{
                "key": key, "title": title, "suggested_mode": mode, "role": role,
                "evidence_claim": key, "required": True,
            } for key, title, mode, role in template_nodes(template)]
        template_keys = {item["key"] for item in desired_specs}
        external_parents = {
            item["key"]: item
            for item in (current_vdoc_plan or {}).get("desired_state", [])
            if item.get("role") == "document-writing-plan"
        }
        proposal_nodes, proposal_source = self._load_desired_state_proposal(
            name, desired_file, template_keys,
            external_parents if name == "VDOC" else None,
        )
        if name == "VDOC" and proposal_nodes:
            proposal_roles = {item.get("role") for item in proposal_nodes}
            if proposal_roles == {"document-deliverable"}:
                return self._register_vdoc_deliverables(
                    current_vdoc_plan, proposal_nodes, proposal_source,
                )
            if "document-deliverable" in proposal_roles:
                raise HarnessError(
                    "VDOC 不得同时提交文档撰写方案和正文内容验收节点；"
                    "请先只提交 document-writing-plan，批准后再单独登记 "
                    "document-deliverable"
                )
            issues = self._vdoc_plan_proposal_issues(proposal_nodes)
            if issues:
                raise HarnessError(
                    "VDOC 文档撰写方案不能进入审批：" + "；".join(issues)
                )
        desired_specs.extend(proposal_nodes)
        if name == "VDOC":
            desired_specs.extend(
                child
                for parent in proposal_nodes
                for child in vdoc_internal_child_specs(parent)
            )
        exit_values = exit_criteria or list(template["exit"])
        context = self.planning_context(name)
        manifest = json.loads((self.state / "project.json").read_text(encoding="utf-8"))
        document_root_value: str | None = None
        if name == "VDOC":
            document_root_value = (
                relative_path(self.root, document_root)
                if document_root is not None
                else str(manifest.get("vdoc_document_root") or default_vdoc_document_root(manifest))
            )
            output_path = (self.root / document_root_value).resolve()
            if output_path.exists() and not output_path.is_dir():
                raise HarnessError(f"VDOC document root 不是目录: {document_root_value}")
            readonly_inputs = [*manifest.get("rtl_roots", []), *manifest.get("docs_roots", [])]
            for value in readonly_inputs:
                source = resolved_path(self.root, value)
                if source.is_dir() and (output_path == source or source in output_path.parents):
                    raise HarnessError(f"VDOC document root 不得位于只读输入内: {document_root_value}")
                if source.is_file() and output_path == source:
                    raise HarnessError(f"VDOC document root 与只读输入冲突: {document_root_value}")
            context["document_root"] = document_root_value
        with self.connect() as connection:
            observed = connection.execute("SELECT revision FROM workstreams WHERE name=?", (name,)).fetchone()
            revision = int(observed["revision"]) + 1 if observed else 1
            connection.execute("UPDATE nodes SET workstream=NULL,status=?,updated_at=? WHERE workstream=? AND type='desired-state'",
                               (Validity.STALE.value, now(), name))
            desired_rows = []
            key_to_id = {
                item["key"]: f"workstream:{name}:r{revision}:desired:{item['key']}"
                for item in desired_specs
            }
            for spec in desired_specs:
                key, title = spec["key"], spec["title"]
                suggested_mode, role = spec["suggested_mode"], spec["role"]
                evidence_claim = spec["evidence_claim"]
                node_id = f"workstream:{name}:r{revision}:desired:{key}"
                row = {"id": node_id, "key": key, "title": title, "role": role,
                       "required": spec.get("required", True), "suggested_mode": suggested_mode,
                       "evidence_claim": evidence_claim,
                       "parent_key": spec.get("parent_key"),
                       "parent_id": key_to_id.get(spec.get("parent_key")),
                       "document_key": spec.get("document_key"),
                       "content_kind": spec.get("content_kind"),
                       "visibility": spec.get("visibility", "public"),
                       "visible_to_human": spec.get("visible_to_human", True),
                       "parent_role": spec.get("parent_role")}
                if name == "VDOC" and not desired:
                    if key in VDOC_DOCUMENTS:
                        row["document"] = vdoc_document_contract(key)
                    row["evidence_contract"] = {
                        "version": "DocumentReviewPolicy/1", "claim": "document-review",
                        "required": ["当前文档内容与本次评审一致", "负责人已明确认可当前正文"],
                    }
                elif name == "VDOC":
                    row["evidence_contract"] = {
                        "version": "DocumentReviewPolicy/1", "claim": "document-review",
                        "required": ["已保存当前文档的评审记录", "评审记录包含负责人和明确结论"],
                    }
                else:
                    contract = policy_for(name, evidence_claim)
                    if contract is None:
                        raise HarnessError(
                            f"{name}/{evidence_claim} 缺少 evidence admission policy；不能创建无证据合同的目标"
                        )
                    row["evidence_contract"] = contract
                if spec.get("statement"):
                    row.update({
                        field: spec[field] for field in (
                            "statement", "purpose", "scope", "acceptance_criteria",
                            "source_refs", "work_content", "implementation_approach",
                            "deliverables", "progress_measures", "quality_checks",
                            "definition_origin", "definition_status", "role_description",
                            "internal_semantic_units", "semantic_manifest_digest",
                            "semantic_unit_id", "semantic_field", "semantic_sequence",
                            "semantic_digest", "visibility", "visible_to_human", "parent_role",
                        ) if field in spec
                    })
                else:
                    row.update(desired_definition(
                        name, key, title, role, row["evidence_contract"],
                        "custom-title" if desired else "template",
                    ))
                desired_rows.append(row)
                self.upsert_node(connection, node_id, "desired-state", title, Validity.UNKNOWN, name, row)
            for row in desired_rows:
                if row.get("parent_id"):
                    connection.execute(
                        "INSERT OR REPLACE INTO edges VALUES(?,?,?,?,?,?,?)",
                        (row["id"], row["parent_id"], "CHILD_OF", "planner-explicit", 1.0,
                         json_text({"child_key": row["key"], "parent_key": row["parent_key"]}), now()),
                    )
            connection.execute("""
                INSERT INTO workstreams(name,lifecycle,revision,objective,desired_json,exit_json,decisions_json,context_json,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(name) DO UPDATE SET lifecycle=excluded.lifecycle,revision=excluded.revision,
                  objective=excluded.objective,desired_json=excluded.desired_json,exit_json=excluded.exit_json,
                  decisions_json=excluded.decisions_json,context_json=excluded.context_json,updated_at=excluded.updated_at
            """, (name, "REVIEW", revision, objective_value, json_text(desired_rows), json_text(exit_values),
                  json_text(decisions), json_text(context), now()))
            default_dependency_count = self._reconcile_default_dependencies(connection)
        self.write_workstream_projection(name)
        materialized_documents: list[dict[str, Any]] = []
        if name == "VDOC":
            manifest["vdoc_document_root"] = document_root_value
            manifest["updated_at"] = now()
            atomic_json(self.state / "project.json", manifest)
            update_project_agents(self.root / "AGENTS.md", project_agents_block(manifest, document_root_value))
            if not desired:
                materialized_documents = self._materialize_vdoc_documents(desired_rows, document_root_value)
        result = self.workstream(name)
        result["template"] = {
            "name": template["name"],
            "capabilities": [item[0] for item in template.get("capabilities", [])],
            "closure_evidence": [item[0] for item in template["closure_evidence"]],
        }
        if name == "VDOC":
            result["template"]["document_catalogs"] = [
                item[0] for item in template["document_catalogs"]
            ]
        if name == "VDOC":
            result["document_guidance"] = {
                "instructions": "vplan/vdoc.md",
                "templates_relative_to": "skill-root",
                "materialization": "missing-templates-created; agent-dialogue-required-for-semantics",
                "document_root": document_root_value,
                "project_instructions": "AGENTS.md",
                "documents": materialized_documents,
                "optional_documents": [{"filename": "code_coverage_waiver_manifest.md",
                                        "template": "assets/vdoc/code_coverage_waiver_manifest.md",
                                        "when": "specific-code-coverage-waiver-candidate", "maintained_by": ["VCOV"]}],
            }
        result["decision_log"] = decisions
        result["default_dependency_count"] = default_dependency_count
        result["desired_state_proposal"] = proposal_source
        result["project_goal_count"] = len(proposal_nodes)
        result["questions_for_human"] = [
            f"请确认 `{item['key']}`：{item['title']}；证据合同 `{item['evidence_claim']}` 是否适用"
            for item in desired_specs
        ] if not decisions else []
        if not desired and not proposal_nodes and name != "VDOC":
            result["questions_for_human"].append(
                f"{name} 当前只有汇总模板节点；请让 Agent 从已评审文档形成项目级 DesiredStateProposal/1 后重新 plan"
            )
        result["auto_closure"] = self.evaluate_closure(name)
        return result

    def restart_vdoc_workflow(
        self, reviewer: str, reason: str, confirm: bool = False,
    ) -> dict[str, Any]:
        """Start a new VDOC revision without deleting documents or history."""
        self.require()
        if not confirm:
            raise HarnessError("重新启动 VDOC 工作流必须再次确认")
        if not reviewer.strip() or not reason.strip():
            raise HarnessError("重新启动 VDOC 工作流必须填写操作人和原因")
        previous = self.workstream("VDOC")
        previous_revision = int(previous["revision"])
        previous_node_ids = [item["id"] for item in previous["desired_state"]]
        preserved_documents = [
            {
                "id": item["id"], "path": item["path"],
                "semantic_revision": item["semantic_revision"],
                "digest": item["digest"],
            }
            for item in self.documents()
        ]

        restarted = self.design_workstream(
            "VDOC", previous["objective"], [], previous["exit_criteria"],
            previous["decisions"],
        )
        current_revision = int(restarted["revision"])
        timestamp = now()
        targets = ["VDOC", *previous_node_ids]
        placeholders = ",".join("?" for _ in targets)
        resolution = (
            f"负责人重新启动 VDOC：revision {previous_revision} 已由 "
            f"revision {current_revision} 取代"
        )
        event_id = f"event:{uuid.uuid4().hex[:12]}"
        with self.connect() as connection:
            connection.execute(
                f"""UPDATE human_actions
                    SET status='SUPERSEDED',resolved_by=?,resolution=?,updated_at=?
                    WHERE status='OPEN' AND target IN ({placeholders})""",
                (reviewer.strip(), resolution, timestamp, *targets),
            )
            connection.execute(
                f"""UPDATE agent_questions
                    SET status='SUPERSEDED',updated_at=?
                    WHERE status='OPEN' AND target IN ({placeholders})""",
                (timestamp, *targets),
            )
            connection.execute(
                """UPDATE activities
                   SET status='CANCELLED',message=?,updated_at=?,ended_at=?
                   WHERE workstream='VDOC'
                     AND status IN ('PENDING','RUNNING','WAITING_FOR_HUMAN','WAITING_FOR_PARENT')""",
                (resolution, timestamp, timestamp),
            )
            self._refresh_agent_assignments(connection)
            connection.execute(
                "INSERT INTO events VALUES(?,?,?,?,?,?)",
                (
                    event_id, "workstream-restart", "workstream:VDOC",
                    f"{previous_revision}->{current_revision}",
                    json_text({
                        "reviewer": reviewer.strip(), "reason": reason.strip(),
                        "previous_revision": previous_revision,
                        "current_revision": current_revision,
                        "preserved_document_count": len(preserved_documents),
                    }), timestamp,
                ),
            )
        self.write_model_projection()
        self.write_workstream_projection("VDOC")
        result = self.workstream("VDOC")
        result.update({
            "event_id": event_id,
            "previous_revision": previous_revision,
            "current_revision": current_revision,
            "reviewer": reviewer.strip(),
            "reason": reason.strip(),
            "preserved_documents": preserved_documents,
            "auto_closure": self.evaluate_closure("VDOC"),
        })
        return result

    def workstream(self, workstream: str) -> dict[str, Any]:
        name = self.normalize_workstream(workstream)
        self.require()
        with self.read_connect() as connection:
            row = connection.execute("SELECT * FROM workstreams WHERE name=?", (name,)).fetchone()
        if row is None:
            raise HarnessError(f"Workstream {name} 尚未设计")
        return {
            "workstream": name, "display_name": WORKSTREAM_TEMPLATES[name]["name"],
            "lifecycle": row["lifecycle"], "revision": row["revision"], "objective": row["objective"],
            "desired_state": json.loads(row["desired_json"]), "exit_criteria": json.loads(row["exit_json"]),
            "decisions": json.loads(row["decisions_json"]), "planning_context": json.loads(row["context_json"]),
            "updated_at": row["updated_at"],
        }

    def workstreams(self) -> list[dict[str, Any]]:
        self.require()
        with self.read_connect() as connection:
            names = [row["name"] for row in connection.execute("SELECT name FROM workstreams ORDER BY name")]
        return [self.workstream(name) for name in names]

    @staticmethod
    def _validate_progress(current: int | None, total: int | None) -> None:
        if current is not None and current < 0:
            raise HarnessError("activity progress current 不能小于 0")
        if total is not None and total <= 0:
            raise HarnessError("activity progress total 必须大于 0")
        if current is not None and total is not None and current > total:
            raise HarnessError("activity progress current 不能大于 total")

    def create_activity(
        self, node_id: str, operation: str, actor: str, message: str = "",
        total: int | None = None, log_path: str | None = None,
    ) -> dict[str, Any]:
        """Record bounded Agent/tool work without changing verification validity."""
        self.require()
        if not operation.strip() or not actor.strip():
            raise HarnessError("activity operation 和 actor 不能为空")
        self._validate_progress(0 if total is not None else None, total)
        normalized_log = relative_path(self.root, log_path) if log_path else None
        activity_id = f"activity:{uuid.uuid4().hex[:12]}"
        timestamp = now()
        with self.connect() as connection:
            normalized_target = node_id.strip()
            if normalized_target.lower() == PROJECT_TARGET:
                normalized_target = PROJECT_TARGET
                workstream = PROJECT_WORKSTREAM
            else:
                node = connection.execute(
                    "SELECT workstream FROM nodes WHERE id=?", (normalized_target,),
                ).fetchone()
                if node is None:
                    raise HarnessError(f"未知 node 或项目级目标: {node_id}")
                workstream = node["workstream"]
            connection.execute(
                """INSERT INTO activities
                   (id,node_id,workstream,operation,status,actor,message,
                    progress_current,progress_total,log_path,created_at,updated_at,ended_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (activity_id, normalized_target, workstream, operation.strip(), "RUNNING",
                 actor.strip(), message.strip(), 0 if total is not None else None, total,
                 normalized_log, timestamp, timestamp, None),
            )
        return self.activity(activity_id)

    def activity(self, activity_id: str) -> dict[str, Any]:
        self.require()
        with self.read_connect() as connection:
            row = connection.execute("SELECT * FROM activities WHERE id=?", (activity_id,)).fetchone()
        if row is None:
            raise HarnessError(f"未知 activity: {activity_id}")
        return dict(row)

    def activities(
        self, workstream: str | None = None, node_id: str | None = None,
        active_only: bool = False,
    ) -> list[dict[str, Any]]:
        self.require()
        self.ensure_dashboard_schema()
        filters: list[str] = []
        values: list[Any] = []
        if workstream:
            filters.append("workstream=?")
            values.append(self.normalize_workstream(workstream))
        if node_id:
            filters.append("node_id=?")
            values.append(node_id)
        if active_only:
            filters.append(
                "status IN ('PENDING','RUNNING','WAITING_FOR_HUMAN','WAITING_FOR_PARENT')"
            )
        where = " WHERE " + " AND ".join(filters) if filters else ""
        with self.read_connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM activities" + where + " ORDER BY created_at DESC", values,
            )]

    def update_activity(
        self, activity_id: str, status: str, message: str | None = None,
        current: int | None = None, total: int | None = None,
        log_path: str | None = None,
    ) -> dict[str, Any]:
        self.require()
        selected = status.upper()
        if selected not in ACTIVITY_STATUSES:
            raise HarnessError("activity status 必须是 " + ", ".join(sorted(ACTIVITY_STATUSES)))
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM activities WHERE id=?", (activity_id,)).fetchone()
            if row is None:
                raise HarnessError(f"未知 activity: {activity_id}")
            assignment = connection.execute(
                "SELECT id FROM agent_assignments WHERE activity_id=? LIMIT 1",
                (activity_id,),
            ).fetchone()
            if assignment is not None:
                raise HarnessError(
                    "subagent assignment 的 Activity 只能通过 agent-work heartbeat/finish 更新"
                )
            if row["status"] in {"COMPLETED", "FAILED", "CANCELLED"}:
                raise HarnessError("已结束的 activity 不能再次更新")
            new_current = current if current is not None else row["progress_current"]
            new_total = total if total is not None else row["progress_total"]
            self._validate_progress(new_current, new_total)
            normalized_log = relative_path(self.root, log_path) if log_path else row["log_path"]
            timestamp = now()
            ended_at = timestamp if selected in {"COMPLETED", "FAILED", "CANCELLED"} else None
            connection.execute(
                """UPDATE activities SET status=?,message=?,progress_current=?,progress_total=?,
                   log_path=?,updated_at=?,ended_at=? WHERE id=?""",
                (selected, row["message"] if message is None else message.strip(),
                 new_current, new_total, normalized_log, timestamp, ended_at, activity_id),
            )
        return self.activity(activity_id)

    @staticmethod
    def _agent_assignment_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["write_scope"] = json.loads(item.pop("write_scope_json"))
        item["result"] = json.loads(item.pop("result_json"))
        return item

    @staticmethod
    def _agent_identity(value: str, field: str) -> str:
        selected = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", selected):
            raise HarnessError(
                f"{field} 必须以字母或数字开头，且只能包含字母、数字、._:/-"
            )
        return selected

    def _current_assignment_definition(
        self, connection: sqlite3.Connection, node_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        node = connection.execute(
            "SELECT workstream FROM nodes WHERE id=?", (node_id,),
        ).fetchone()
        if node is None:
            raise HarnessError(f"未知 agent assignment node: {node_id}")
        plan_row = connection.execute(
            "SELECT * FROM workstreams WHERE name=?", (node["workstream"],),
        ).fetchone()
        if plan_row is None:
            raise HarnessError(f"node 没有当前 Workstream: {node_id}")
        desired_state = json.loads(plan_row["desired_json"])
        desired = next((item for item in desired_state if item["id"] == node_id), None)
        if desired is None:
            raise HarnessError(f"node 不属于当前 Workstream revision: {node_id}")
        plan = {
            "workstream": plan_row["name"],
            "lifecycle": plan_row["lifecycle"],
            "revision": plan_row["revision"],
            "desired_state": desired_state,
        }
        return plan, desired

    def _refresh_agent_assignments(self, connection: sqlite3.Connection) -> None:
        """Expire lost leases and supersede claims bound to an old plan revision."""
        timestamp = now()
        observed_at = dt.datetime.fromisoformat(timestamp)
        rows = connection.execute(
            "SELECT * FROM agent_assignments WHERE status='ACTIVE' ORDER BY created_at"
        ).fetchall()
        for row in rows:
            terminal: str | None = None
            message = ""
            try:
                plan, desired = self._current_assignment_definition(connection, row["node_id"])
                digest = self._node_plan_digest(plan, desired)
                if (
                    plan["revision"] != row["workstream_revision"]
                    or digest != row["definition_digest"]
                ):
                    terminal = "SUPERSEDED"
                    message = "工作节点定义或 Workstream revision 已变化；旧 subagent assignment 已停止"
                elif connection.execute(
                    """SELECT id FROM actions
                       WHERE id=? AND status='OPEN' AND workstream=? AND target=?""",
                    (row["action_id"], row["workstream"], row["node_id"]),
                ).fetchone() is None:
                    terminal = "SUPERSEDED"
                    message = "节点当前 Closure action 已变化；旧 subagent assignment 已停止"
            except HarnessError:
                terminal = "SUPERSEDED"
                message = "工作节点已不属于当前计划；旧 subagent assignment 已停止"
            if terminal is None:
                try:
                    lease_expires_at = dt.datetime.fromisoformat(row["lease_expires_at"])
                except ValueError:
                    lease_expires_at = observed_at
                if lease_expires_at <= observed_at:
                    terminal = "EXPIRED"
                    message = "subagent heartbeat 已超出租约；仅停止本次协作记录，不代表验证失败"
            if terminal is None:
                continue
            connection.execute(
                """UPDATE agent_assignments
                   SET status=?,summary=?,updated_at=?,ended_at=? WHERE id=?""",
                (terminal, message, timestamp, timestamp, row["id"]),
            )
            activity = connection.execute(
                "SELECT status FROM activities WHERE id=?", (row["activity_id"],),
            ).fetchone()
            if activity is not None and activity["status"] not in {
                "COMPLETED", "FAILED", "CANCELLED",
            }:
                connection.execute(
                    """UPDATE activities SET status='CANCELLED',message=?,updated_at=?,ended_at=?
                       WHERE id=?""",
                    (message, timestamp, timestamp, row["activity_id"]),
                )

    def _normalized_write_scopes(self, values: Iterable[str]) -> list[str]:
        manifest = json.loads((self.state / "project.json").read_text(encoding="utf-8"))
        scopes = sorted({relative_path(self.root, value) for value in values if value.strip()})
        if "." in scopes:
            raise HarnessError("subagent write scope 不能是整个项目；请指定 verification 输出内的具体路径")
        output_root = resolved_path(self.root, manifest.get("verif_root") or ".")
        protected = [
            resolved_path(self.root, value)
            for value in [
                *manifest.get("rtl_roots", []),
                *manifest.get("docs_roots", []),
                *SUBAGENT_PROTECTED_WRITE_PATHS,
            ]
        ]
        for scope in scopes:
            resolved = resolved_path(self.root, scope)
            if not self._path_is_within_casefold(resolved, output_root):
                raise HarnessError(
                    f"subagent write scope 必须位于 verification 输出根目录内: {scope}"
                )
            if any(
                self._paths_overlap_casefold(resolved, item)
                for item in protected
            ):
                raise HarnessError(
                    "subagent write scope 不能覆盖只读 RTL/spec、控制状态、"
                    f"runtime 配置或仓库元数据: {scope}"
                )
        return scopes

    @staticmethod
    def _path_is_within_casefold(candidate: Path, root: Path) -> bool:
        candidate_parts = tuple(part.casefold() for part in candidate.parts)
        root_parts = tuple(part.casefold() for part in root.parts)
        return candidate_parts[:len(root_parts)] == root_parts

    @classmethod
    def _paths_overlap_casefold(cls, left: Path, right: Path) -> bool:
        return (
            cls._path_is_within_casefold(left, right)
            or cls._path_is_within_casefold(right, left)
        )

    @staticmethod
    def _scopes_overlap(left: str, right: str) -> bool:
        left_parts = tuple(part.casefold() for part in Path(left).parts)
        right_parts = tuple(part.casefold() for part in Path(right).parts)
        return (
            left_parts[:len(right_parts)] == right_parts
            or right_parts[:len(left_parts)] == left_parts
        )

    def agent_work_candidates(self, limit: int = 20) -> dict[str, Any]:
        """Return current closure actions that a runtime-native subagent may execute."""
        self.require()
        if limit < 1 or limit > 100:
            raise HarnessError("agent-work candidates limit 必须在 1..100")
        manifest = json.loads((self.state / "project.json").read_text(encoding="utf-8"))
        runtime = str(manifest.get("runtime") or "unselected")
        if runtime not in {"codex", "kimi"}:
            raise HarnessError("multi-agent 需要项目 runtime 明确选择 codex 或 kimi")
        closure = self.reconcile()
        active_nodes = {
            item["node_id"] for item in self.agent_assignments(active_only=True)
        }
        actions: list[dict[str, Any]] = []
        with self.read_connect() as connection:
            for action in closure["ranked_actions"]:
                if len(actions) >= limit:
                    break
                if (
                    action["executor"] == "human"
                    or action["kind"] == "WAIT_FOR_DEPENDENCY"
                    or action["target"] in active_nodes
                ):
                    continue
                try:
                    plan, desired = self._current_assignment_definition(
                        connection, action["target"],
                    )
                except HarnessError:
                    continue
                if plan["lifecycle"] not in {"ACTIVE", "PARTIALLY_STALE"}:
                    continue
                blocking_question = connection.execute(
                    """SELECT id FROM agent_questions
                       WHERE status='OPEN' AND blocking=1
                         AND target IN (?, ?, 'project') LIMIT 1""",
                    (action["target"], action["workstream"]),
                ).fetchone()
                if blocking_question is not None:
                    continue
                actions.append({
                    **action,
                    "workstream_revision": plan["revision"],
                    "definition_digest": self._node_plan_digest(plan, desired),
                })
        return {
            "schema": "AgentWorkCandidates/1",
            "runtime": runtime,
            "actions": actions,
        }

    def claim_agent_work(
        self, action_id: str, agent_id: str, role: str, operation: str,
        parent_agent_id: str = "project-agent", runtime_ref: str | None = None,
        lease_seconds: int = 300, write_scope: Iterable[str] = (),
        message: str = "", total: int | None = None,
    ) -> dict[str, Any]:
        """Atomically bind one current closure action to one native subagent."""
        self.require()
        selected_agent = self._agent_identity(agent_id, "agent_id")
        selected_parent = self._agent_identity(parent_agent_id, "parent_agent_id")
        if role not in VERIFICATION_AGENT_ROLES:
            raise HarnessError("agent role 必须是 " + ", ".join(VERIFICATION_AGENT_ROLES))
        if not operation.strip():
            raise HarnessError("agent-work operation 不能为空")
        if lease_seconds < 30 or lease_seconds > 86400:
            raise HarnessError("agent-work lease seconds 必须在 30..86400")
        self._validate_progress(0 if total is not None else None, total)
        scopes = self._normalized_write_scopes(write_scope)
        manifest = json.loads((self.state / "project.json").read_text(encoding="utf-8"))
        runtime = str(manifest.get("runtime") or "unselected")
        if runtime not in {"codex", "kimi"}:
            raise HarnessError("multi-agent 需要项目 runtime 明确选择 codex 或 kimi")
        # Reconciliation owns the stable action set; assignments never mutate actions.status.
        self.reconcile()
        assignment_id = f"assignment:{uuid.uuid4().hex[:12]}"
        activity_id = f"activity:{uuid.uuid4().hex[:12]}"
        timestamp_value = dt.datetime.now(dt.timezone.utc)
        timestamp = timestamp_value.isoformat()
        lease_expires_at = (timestamp_value + dt.timedelta(seconds=lease_seconds)).isoformat()
        try:
            with self.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                self._refresh_agent_assignments(connection)
                action = connection.execute(
                    "SELECT * FROM actions WHERE id=? AND status='OPEN'", (action_id,),
                ).fetchone()
                if action is None:
                    raise HarnessError(f"action 已不是当前可领取动作: {action_id}")
                if action["executor"] == "human" or action["kind"] == "WAIT_FOR_DEPENDENCY":
                    raise HarnessError("该 closure action 不能分派给 subagent")
                plan, desired = self._current_assignment_definition(
                    connection, action["target"],
                )
                if plan["lifecycle"] not in {"ACTIVE", "PARTIALLY_STALE"}:
                    raise HarnessError("Workstream 尚未获准执行，不能分派 subagent")
                blocking_question = connection.execute(
                    """SELECT id FROM agent_questions
                       WHERE status='OPEN' AND blocking=1
                         AND target IN (?, ?, 'project') LIMIT 1""",
                    (action["target"], action["workstream"]),
                ).fetchone()
                if blocking_question is not None:
                    raise HarnessError("当前存在未回答的 Main Agent 问题，不能分派 subagent")
                for existing in connection.execute(
                    "SELECT id,write_scope_json FROM agent_assignments WHERE status='ACTIVE'"
                ):
                    existing_scopes = json.loads(existing["write_scope_json"])
                    conflict = next((
                        (left, right) for left in scopes for right in existing_scopes
                        if self._scopes_overlap(left, right)
                    ), None)
                    if conflict is not None:
                        raise HarnessError(
                            f"write scope 与 active assignment {existing['id']} 冲突: "
                            f"{conflict[0]} / {conflict[1]}"
                        )
                digest = self._node_plan_digest(plan, desired)
                connection.execute(
                    """INSERT INTO activities
                       (id,node_id,workstream,operation,status,actor,message,
                        progress_current,progress_total,log_path,created_at,updated_at,ended_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (activity_id, action["target"], action["workstream"], operation.strip(),
                     "RUNNING", selected_agent, message.strip(),
                     0 if total is not None else None, total, None,
                     timestamp, timestamp, None),
                )
                connection.execute(
                    """INSERT INTO agent_assignments
                       (id,action_id,node_id,workstream,workstream_revision,
                        definition_digest,runtime,agent_id,parent_agent_id,role,runtime_ref,
                        status,activity_id,lease_seconds,lease_expires_at,heartbeat_at,
                        write_scope_json,summary,result_json,created_at,updated_at,ended_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (assignment_id, action["id"], action["target"], action["workstream"],
                     plan["revision"], digest, runtime, selected_agent, selected_parent, role,
                     runtime_ref.strip() if runtime_ref else None, "ACTIVE", activity_id,
                     lease_seconds, lease_expires_at, timestamp, json_text(scopes), "", "{}",
                     timestamp, timestamp, None),
                )
        except sqlite3.IntegrityError as exc:
            raise HarnessError(
                "node 或 agent 已被另一个 active subagent assignment 领取"
            ) from exc
        return self.agent_assignment(assignment_id)

    def agent_assignment(self, assignment_id: str) -> dict[str, Any]:
        self.require()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._refresh_agent_assignments(connection)
            row = connection.execute(
                "SELECT * FROM agent_assignments WHERE id=?", (assignment_id,),
            ).fetchone()
            if row is None:
                raise HarnessError(f"未知 agent assignment: {assignment_id}")
            activity = connection.execute(
                "SELECT * FROM activities WHERE id=?", (row["activity_id"],),
            ).fetchone()
        result = self._agent_assignment_row(row)
        result["activity"] = dict(activity) if activity is not None else None
        return result

    def agent_assignments(
        self, workstream: str | None = None, node_id: str | None = None,
        active_only: bool = False,
    ) -> list[dict[str, Any]]:
        self.require()
        filters: list[str] = []
        values: list[Any] = []
        if workstream:
            filters.append("workstream=?")
            values.append(self.normalize_workstream(workstream))
        if node_id:
            filters.append("node_id=?")
            values.append(node_id)
        if active_only:
            filters.append("status='ACTIVE'")
        where = " WHERE " + " AND ".join(filters) if filters else ""
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._refresh_agent_assignments(connection)
            rows = connection.execute(
                "SELECT * FROM agent_assignments" + where + " ORDER BY created_at DESC",
                values,
            ).fetchall()
            activity_by_id = {
                row["id"]: dict(row) for row in connection.execute("SELECT * FROM activities")
            }
        results: list[dict[str, Any]] = []
        for row in rows:
            item = self._agent_assignment_row(row)
            item["activity"] = activity_by_id.get(item["activity_id"])
            results.append(item)
        return results

    def heartbeat_agent_work(
        self, assignment_id: str, agent_id: str, phase: str = "RUNNING",
        message: str | None = None, current: int | None = None,
        total: int | None = None,
    ) -> dict[str, Any]:
        """Refresh an active lease using progress reported to Main Agent by the child."""
        selected_agent = self._agent_identity(agent_id, "agent_id")
        selected_phase = phase.upper()
        if selected_phase not in AGENT_ASSIGNMENT_PHASES:
            raise HarnessError(
                "agent-work phase 必须是 " + ", ".join(sorted(AGENT_ASSIGNMENT_PHASES))
            )
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._refresh_agent_assignments(connection)
            row = connection.execute(
                "SELECT * FROM agent_assignments WHERE id=?", (assignment_id,),
            ).fetchone()
            if row is None:
                raise HarnessError(f"未知 agent assignment: {assignment_id}")
            if row["agent_id"] != selected_agent:
                raise HarnessError("agent_id 与 assignment owner 不一致")
            if row["status"] != "ACTIVE":
                raise HarnessError(f"agent assignment 已结束: {row['status']}")
            activity = connection.execute(
                "SELECT * FROM activities WHERE id=?", (row["activity_id"],),
            ).fetchone()
            if activity is None:
                raise HarnessError("agent assignment 缺少关联 Activity")
            new_current = current if current is not None else activity["progress_current"]
            new_total = total if total is not None else activity["progress_total"]
            self._validate_progress(new_current, new_total)
            timestamp_value = dt.datetime.now(dt.timezone.utc)
            timestamp = timestamp_value.isoformat()
            lease_expires_at = (
                timestamp_value + dt.timedelta(seconds=row["lease_seconds"])
            ).isoformat()
            connection.execute(
                """UPDATE agent_assignments
                   SET heartbeat_at=?,lease_expires_at=?,updated_at=? WHERE id=?""",
                (timestamp, lease_expires_at, timestamp, assignment_id),
            )
            connection.execute(
                """UPDATE activities SET status=?,message=?,progress_current=?,progress_total=?,
                   updated_at=? WHERE id=?""",
                (selected_phase,
                 activity["message"] if message is None else message.strip(),
                 new_current, new_total, timestamp, row["activity_id"]),
            )
        return self.agent_assignment(assignment_id)

    def finish_agent_work(
        self, assignment_id: str, agent_id: str, outcome: str, summary: str,
        result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """End collaboration bookkeeping without changing node validity or evidence."""
        selected_agent = self._agent_identity(agent_id, "agent_id")
        selected_outcome = outcome.upper()
        if selected_outcome not in {"COMPLETED", "FAILED", "CANCELLED"}:
            raise HarnessError("agent-work outcome 必须是 COMPLETED, FAILED 或 CANCELLED")
        if not summary.strip():
            raise HarnessError("agent-work finish summary 不能为空")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._refresh_agent_assignments(connection)
            row = connection.execute(
                "SELECT * FROM agent_assignments WHERE id=?", (assignment_id,),
            ).fetchone()
            if row is None:
                raise HarnessError(f"未知 agent assignment: {assignment_id}")
            if row["agent_id"] != selected_agent:
                raise HarnessError("agent_id 与 assignment owner 不一致")
            if row["status"] != "ACTIVE":
                if row["status"] in {selected_outcome, "SUPERSEDED"}:
                    pass
                else:
                    raise HarnessError(f"agent assignment 已结束: {row['status']}")
            else:
                timestamp = now()
                connection.execute(
                    """UPDATE agent_assignments SET status=?,summary=?,result_json=?,
                       updated_at=?,ended_at=? WHERE id=?""",
                    (selected_outcome, summary.strip(), json_text(result or {}),
                     timestamp, timestamp, assignment_id),
                )
                activity = connection.execute(
                    "SELECT progress_current,progress_total FROM activities WHERE id=?",
                    (row["activity_id"],),
                ).fetchone()
                progress_current = (
                    activity["progress_total"]
                    if selected_outcome == "COMPLETED" and activity is not None
                    and activity["progress_total"] is not None
                    else activity["progress_current"] if activity is not None else None
                )
                connection.execute(
                    """UPDATE activities SET status=?,message=?,progress_current=?,
                       updated_at=?,ended_at=? WHERE id=?""",
                    (selected_outcome, summary.strip(), progress_current,
                     timestamp, timestamp, row["activity_id"]),
                )
        return self.agent_assignment(assignment_id)

    def add_human_action(
        self, target: str, action: str, reviewer: str, reason: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist Human input without silently changing node validity or plan lifecycle."""
        self.require()
        selected = action.upper().replace("-", "_")
        if selected not in HUMAN_ACTIONS:
            raise HarnessError("human action 必须是 " + ", ".join(sorted(HUMAN_ACTIONS)))
        if not reviewer.strip() or not reason.strip():
            raise HarnessError("human action reviewer 和 reason 不能为空")
        with self.connect() as connection:
            node = connection.execute("SELECT 1 FROM nodes WHERE id=?", (target,)).fetchone()
            workstream = connection.execute("SELECT 1 FROM workstreams WHERE name=?", (target.upper(),)).fetchone()
            if node is not None:
                normalized_target, target_type = target, "node"
            elif workstream is not None:
                normalized_target, target_type = target.upper(), "workstream"
            else:
                raise HarnessError(f"human action target 不是已知 node 或 Workstream: {target}")
            action_id = f"human:{uuid.uuid4().hex[:12]}"
            timestamp = now()
            status = "RECORDED" if selected in {"COMMENT", "ACKNOWLEDGE"} else "OPEN"
            connection.execute(
                """INSERT INTO human_actions
                   (id,target,target_type,action,status,reviewer,reason,payload_json,
                    resolved_by,resolution,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (action_id, normalized_target, target_type, selected, status, reviewer.strip(),
                 reason.strip(), json_text(payload or {}), None, None, timestamp, timestamp),
            )
        return self.human_action(action_id)

    def human_action(self, action_id: str) -> dict[str, Any]:
        self.require()
        with self.read_connect() as connection:
            row = connection.execute("SELECT * FROM human_actions WHERE id=?", (action_id,)).fetchone()
        if row is None:
            raise HarnessError(f"未知 human action: {action_id}")
        result = dict(row)
        result["payload"] = json.loads(result.pop("payload_json"))
        return result

    def human_actions(self, status: str | None = None) -> list[dict[str, Any]]:
        self.require()
        self.ensure_dashboard_schema()
        values: tuple[Any, ...] = ()
        where = ""
        if status:
            selected = status.upper()
            if selected not in HUMAN_ACTION_STATUSES:
                raise HarnessError("human action status 必须是 " + ", ".join(sorted(HUMAN_ACTION_STATUSES)))
            where = " WHERE status=?"
            values = (selected,)
        with self.read_connect() as connection:
            rows = [dict(row) for row in connection.execute(
                "SELECT * FROM human_actions" + where + " ORDER BY created_at DESC", values,
            )]
        for row in rows:
            row["payload"] = json.loads(row.pop("payload_json"))
        return rows

    def resolve_human_action(
        self, action_id: str, reviewer: str, resolution: str,
        status: str = "RESOLVED",
    ) -> dict[str, Any]:
        self.require()
        selected = status.upper()
        if selected not in {"RESOLVED", "SUPERSEDED"}:
            raise HarnessError("human action 只能解析为 RESOLVED 或 SUPERSEDED")
        if not reviewer.strip() or not resolution.strip():
            raise HarnessError("解析 human action 必须提供 reviewer 和 resolution")
        with self.connect() as connection:
            row = connection.execute("SELECT status FROM human_actions WHERE id=?", (action_id,)).fetchone()
            if row is None:
                raise HarnessError(f"未知 human action: {action_id}")
            if row["status"] not in {"OPEN", "RECORDED"}:
                raise HarnessError("human action 已经关闭")
            connection.execute(
                """UPDATE human_actions SET status=?,resolved_by=?,resolution=?,updated_at=?
                   WHERE id=?""",
                (selected, reviewer.strip(), resolution.strip(), now(), action_id),
            )
        return self.human_action(action_id)

    @staticmethod
    def _question_options(
        options: Iterable[dict[str, Any]], recommended_option: str | None = None,
    ) -> tuple[list[dict[str, str]], str | None]:
        normalized: list[dict[str, str]] = []
        seen: set[str] = set()
        for raw in options:
            if not isinstance(raw, dict):
                raise HarnessError("agent question option 必须是 object")
            option_id = str(raw.get("id", "")).strip()
            label = str(raw.get("label", "")).strip()
            description = str(raw.get("description", "")).strip()
            if not option_id or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", option_id):
                raise HarnessError("agent question option id 只能包含字母、数字、点、下划线和连字符")
            if option_id.lower() == "other":
                raise HarnessError("agent question option id 不能使用保留值 other")
            if option_id in seen:
                raise HarnessError(f"agent question option id 重复: {option_id}")
            if not label:
                raise HarnessError("agent question option label 不能为空")
            seen.add(option_id)
            normalized.append({"id": option_id, "label": label, "description": description})
        if not 2 <= len(normalized) <= 8:
            raise HarnessError("agent question 必须提供 2 到 8 个选项")
        recommended = recommended_option.strip() if recommended_option else None
        if recommended and recommended not in seen:
            raise HarnessError("recommended option 必须引用已登记的 option id")
        return normalized, recommended

    @staticmethod
    def _agent_question_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        result["options"] = json.loads(result.pop("options_json"))
        result["blocking"] = bool(result["blocking"])
        return result

    def ask_agent_question(
        self, target: str, prompt: str, options: Iterable[dict[str, Any]],
        recommended_option: str | None = None, context: str = "",
        asked_by: str = PROJECT_AGENT_ACTOR, blocking: bool = True,
        activity_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist a Main-Agent question so the responsible user's answer survives sessions."""
        self.require()
        if not prompt.strip() or not asked_by.strip():
            raise HarnessError("agent question prompt 和 asked_by 不能为空")
        if asked_by.strip() != PROJECT_AGENT_ACTOR:
            raise HarnessError(
                f"只有 {PROJECT_AGENT_ACTOR} 可以登记需要负责人回答的问题；"
                "subagent 必须先向 Main Agent 回报"
            )
        normalized_options, recommended = self._question_options(options, recommended_option)
        raw_target = target.strip()
        question_id = f"question:{uuid.uuid4().hex[:12]}"
        timestamp = now()
        with self.connect() as connection:
            node = connection.execute(
                "SELECT id,workstream FROM nodes WHERE id=?", (raw_target,),
            ).fetchone()
            workstream_name = (
                raw_target.split(":", 1)[1].upper()
                if raw_target.lower().startswith("workstream:")
                and raw_target.count(":") == 1 else raw_target.upper()
            )
            workstream = connection.execute(
                "SELECT name FROM workstreams WHERE name=?", (workstream_name,),
            ).fetchone()
            if raw_target.lower() == PROJECT_TARGET:
                normalized_target = PROJECT_TARGET
                target_type = "project"
                node_id = None
                question_workstream = PROJECT_WORKSTREAM
            elif node is not None:
                normalized_target = node["id"]
                target_type = "node"
                node_id = node["id"]
                question_workstream = node["workstream"]
            elif workstream is not None:
                normalized_target = workstream["name"]
                target_type = "workstream"
                node_id = None
                question_workstream = workstream["name"]
            else:
                raise HarnessError(f"agent question target 不是已知 node 或 Workstream: {target}")

            if activity_id:
                activity = connection.execute(
                    "SELECT * FROM activities WHERE id=?", (activity_id,),
                ).fetchone()
                if activity is None:
                    raise HarnessError(f"未知 activity: {activity_id}")
                subagent_assignment = connection.execute(
                    "SELECT id FROM agent_assignments WHERE activity_id=? LIMIT 1",
                    (activity_id,),
                ).fetchone()
                if subagent_assignment is not None:
                    raise HarnessError(
                        "subagent 的工作记录不能直接绑定需要负责人回答的问题；"
                        "请先向 Main Agent 回报，再由 Main Agent 统一提问"
                    )
                if activity["status"] in {"COMPLETED", "FAILED", "CANCELLED"}:
                    raise HarnessError("已结束的 Activity 不能提出等待回答的问题")
                if activity["workstream"] != question_workstream:
                    raise HarnessError("agent question 与 Activity 必须属于同一 Workstream")
                if target_type == "project" and activity["node_id"] != PROJECT_TARGET:
                    raise HarnessError("项目级 agent question 必须绑定项目级 Activity")
                if node_id and activity["node_id"] != node_id:
                    raise HarnessError("节点级 agent question 必须绑定同一节点的 Activity")

            connection.execute(
                """INSERT INTO agent_questions
                   (id,target,target_type,workstream,node_id,prompt,context,options_json,
                    recommended_option,status,blocking,asked_by,activity_id,
                    answer_option,answer_text,answered_by,created_at,updated_at,answered_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (question_id, normalized_target, target_type, question_workstream, node_id,
                 prompt.strip(), context.strip(), json_text(normalized_options), recommended,
                 "OPEN", int(blocking), PROJECT_AGENT_ACTOR, activity_id,
                 None, None, None, timestamp, timestamp, None),
            )
            if node_id and question_workstream == "VDOC":
                connection.execute(
                    """UPDATE review_agent_checks SET status='WAITING_FOR_HUMAN',
                       updated_at=? WHERE review_id=(
                         SELECT id FROM document_delivery_reviews
                         WHERE node_id=? ORDER BY rowid DESC LIMIT 1
                       )""",
                    (timestamp, node_id),
                )
            if activity_id and blocking:
                connection.execute(
                    """UPDATE activities SET status='WAITING_FOR_HUMAN',message=?,updated_at=?
                       WHERE id=?""",
                    (f"等待负责人回答：{prompt.strip()}", timestamp, activity_id),
                )
        if node_id and question_workstream == "VDOC":
            self._refresh_vdoc_delivery_acceptance(node_id)
            self.write_model_projection()
            self.evaluate_closure("VDOC")
        return self.agent_question(question_id)

    def agent_question(self, question_id: str) -> dict[str, Any]:
        self.require()
        self.ensure_dashboard_schema()
        with self.read_connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_questions WHERE id=?", (question_id,),
            ).fetchone()
        if row is None:
            raise HarnessError(f"未知 agent question: {question_id}")
        return self._agent_question_row(row)

    def agent_questions(
        self, status: str | None = None, target: str | None = None,
    ) -> list[dict[str, Any]]:
        self.require()
        self.ensure_dashboard_schema()
        filters: list[str] = []
        values: list[Any] = []
        if status:
            selected = status.upper()
            if selected not in AGENT_QUESTION_STATUSES:
                raise HarnessError(
                    "agent question status 必须是 " + ", ".join(sorted(AGENT_QUESTION_STATUSES))
                )
            filters.append("status=?")
            values.append(selected)
        if target:
            normalized = (
                target.split(":", 1)[1]
                if target.lower().startswith("workstream:") and target.count(":") == 1
                else target
            )
            filters.append("target=?")
            values.append(normalized.upper() if normalized.upper() in WORKSTREAM_TEMPLATES else normalized)
        where = " WHERE " + " AND ".join(filters) if filters else ""
        with self.read_connect() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_questions" + where + " ORDER BY created_at DESC", values,
            ).fetchall()
        return [self._agent_question_row(row) for row in rows]

    def answer_agent_question(
        self, question_id: str, option_id: str, answered_by: str,
        answer_text: str = "",
    ) -> dict[str, Any]:
        self.require()
        selected = option_id.strip()
        if not selected or not answered_by.strip():
            raise HarnessError("回答 agent question 必须提供 option 和 reviewer")
        timestamp = now()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_questions WHERE id=?", (question_id,),
            ).fetchone()
            if row is None:
                raise HarnessError(f"未知 agent question: {question_id}")
            if row["status"] != "OPEN":
                raise HarnessError("agent question 已经关闭")
            option_ids = {item["id"] for item in json.loads(row["options_json"])}
            if selected != "other" and selected not in option_ids:
                raise HarnessError("answer option 必须引用问题中的选项或 other")
            if selected == "other" and not answer_text.strip():
                raise HarnessError("选择 other 时必须填写 answer text")
            connection.execute(
                """UPDATE agent_questions SET status='ANSWERED',answer_option=?,answer_text=?,
                   answered_by=?,updated_at=?,answered_at=? WHERE id=?""",
                (selected, answer_text.strip(), answered_by.strip(), timestamp, timestamp, question_id),
            )
            activity_id = row["activity_id"]
            if activity_id and bool(row["blocking"]):
                remaining = connection.execute(
                    """SELECT COUNT(*) AS count FROM agent_questions
                       WHERE activity_id=? AND status='OPEN' AND blocking=1""",
                    (activity_id,),
                ).fetchone()["count"]
                activity = connection.execute(
                    "SELECT status,message FROM activities WHERE id=?", (activity_id,),
                ).fetchone()
                if (
                    activity is not None
                    and activity["status"] == "WAITING_FOR_HUMAN"
                    and activity["message"].startswith(("等待 Human 回答：", "等待负责人回答："))
                    and remaining == 0
                ):
                    connection.execute(
                        """UPDATE activities SET status='RUNNING',message=?,updated_at=?
                           WHERE id=?""",
                        (f"负责人已回答问题 {question_id}: {selected}", timestamp, activity_id),
                    )
            node_id = row["node_id"]
            question_workstream = row["workstream"]
            if node_id and question_workstream == "VDOC":
                remaining_for_node = connection.execute(
                    """SELECT COUNT(*) count FROM agent_questions
                       WHERE target=? AND status='OPEN'""",
                    (node_id,),
                ).fetchone()["count"]
                connection.execute(
                    """UPDATE review_agent_checks SET status=?,updated_at=?
                       WHERE review_id=(
                         SELECT id FROM document_delivery_reviews
                         WHERE node_id=? ORDER BY rowid DESC LIMIT 1
                       )""",
                    (
                        "WAITING_FOR_HUMAN" if remaining_for_node else "PENDING",
                        timestamp, node_id,
                    ),
                )
        if node_id and question_workstream == "VDOC":
            self._refresh_vdoc_delivery_acceptance(node_id)
            self.write_model_projection()
            self.evaluate_closure("VDOC")
        return self.agent_question(question_id)

    def await_agent_question(self, question_id: str, timeout: float = 60.0) -> dict[str, Any]:
        if timeout < 0:
            raise HarnessError("agent-question await timeout 不能小于 0")
        started = time.monotonic()
        while True:
            question = self.agent_question(question_id)
            if question["status"] != "OPEN":
                return {
                    "schema": "AgentQuestionCheckpoint/1",
                    "status": question["status"],
                    "question": question,
                    "resume": question["status"] == "ANSWERED",
                    "next": "continue" if question["status"] == "ANSWERED" else "stop",
                }
            elapsed = time.monotonic() - started
            if elapsed >= timeout:
                return {
                    "schema": "AgentQuestionCheckpoint/1", "status": "TIMEOUT",
                    "question": question, "resume": False, "next": "wait",
                }
            time.sleep(min(0.25, max(timeout - elapsed, 0.0)))

    def review_workstream(self, workstream: str, verdict: str, reviewer: str, reason: str) -> dict[str, Any]:
        if verdict not in {"approve", "reject", "modify", "clarify"}:
            raise HarnessError("workstream verdict 必须是 approve/reject/modify/clarify")
        if not reviewer.strip() or not reason.strip():
            raise HarnessError("workstream review 必须提供 reviewer 和 reason")
        plan = self.workstream(workstream)
        proposal_issues = (
            self._vdoc_plan_proposal_issues(plan["desired_state"])
            if plan["workstream"] == "VDOC" else []
        )
        if (
            plan["workstream"] == "VDOC" and verdict == "approve"
            and not self._vdoc_writing_plan_desired(plan)
        ):
            raise HarnessError(
                "当前 VDOC 尚未根据 DUT、规格、接口和验证目标形成文档撰写方案，不能审批"
            )
        if verdict == "approve" and proposal_issues:
            raise HarnessError(
                "当前 VDOC 文档工作分解不完整，不能批量审批撰写方案："
                + "；".join(proposal_issues)
            )
        lifecycle = {"approve": "ACTIVE", "reject": "REVISE", "modify": "REVISE", "clarify": "REVISE"}[verdict]
        with self.connect() as connection:
            if plan["workstream"] == "VDOC" and verdict == "approve":
                open_targets = {
                    row["target"] for row in connection.execute(
                        "SELECT target FROM human_actions WHERE status='OPEN'"
                    )
                }
                blocked = [
                    item["id"] for item in plan["desired_state"]
                    if item.get("required", True) and item["id"] in open_targets
                ]
                if blocked:
                    raise HarnessError(
                        "VDOC 文档节点仍有等待负责人确认的事项，不能批量批准文档撰写方案: "
                        + "、".join(blocked)
                    )
                timestamp = now()
                for item in self._vdoc_plan_desired(plan):
                    if not item.get("required", True):
                        continue
                    digest = self._node_plan_digest(plan, item)
                    for section in self._node_plan_sections(connection, item["id"]):
                        connection.execute(
                            "INSERT INTO node_plan_section_reviews VALUES(?,?,?,?,?,?,?,?,?,?)",
                            (f"plan-section-review:{uuid.uuid4().hex[:12]}", item["id"],
                             "VDOC", plan["revision"], digest, section, "APPROVE",
                             reviewer.strip(), reason.strip(), timestamp),
                        )
                    if item.get("definition_origin") == "project-proposal":
                        connection.execute(
                            "UPDATE nodes SET status=?,updated_at=? WHERE id=?",
                            (Validity.VALID.value, timestamp, item["id"]),
                        )
                        for child in self._vdoc_internal_desired(
                            plan, parent_id=item["id"],
                            parent_role="document-writing-plan",
                        ):
                            connection.execute(
                                "UPDATE nodes SET status=?,updated_at=? WHERE id=?",
                                (Validity.VALID.value, timestamp, child["id"]),
                            )
            review_id = uuid.uuid4().hex
            connection.execute("INSERT INTO reviews VALUES(?,?,?,?,?,?,?)",
                               (review_id, plan["workstream"], plan["revision"], verdict.upper(), reviewer, reason, now()))
            connection.execute("UPDATE workstreams SET lifecycle=?,updated_at=? WHERE name=?",
                               (lifecycle, now(), plan["workstream"]))
        self.write_workstream_projection(plan["workstream"])
        result = {"review_id": review_id, "workstream": plan["workstream"], "revision": plan["revision"],
                  "verdict": verdict.upper(), "lifecycle": lifecycle}
        result["auto_closure"] = self.evaluate_closure(plan["workstream"])
        return result

    @staticmethod
    def _node_plan_digest(plan: dict[str, Any], desired: dict[str, Any]) -> str:
        if desired.get("definition_origin") == "template":
            current_titles = {
                key: title for key, title, _mode, _role
                in template_nodes(WORKSTREAM_TEMPLATES[plan["workstream"]])
            }
            if desired.get("key") in current_titles:
                title = current_titles[desired["key"]]
                desired = {
                    **desired,
                    **desired_definition(
                        plan["workstream"], desired["key"], title,
                        desired.get("role", "capability"),
                        desired.get("evidence_contract") or {}, "template",
                    ),
                    "title": title,
                }
        payload = {
            "workstream": plan["workstream"],
            "revision": plan["revision"],
            "node": desired,
        }
        return hashlib.sha256(json_text(payload).encode("utf-8")).hexdigest()

    @staticmethod
    def _node_plan_sections(connection: sqlite3.Connection, node_id: str) -> list[str]:
        sections = ["human-confirmations", "planned-content", "inputs-scope-deliverable"]
        has_dependencies = connection.execute(
            "SELECT 1 FROM edges WHERE source=? OR target=? LIMIT 1",
            (node_id, node_id),
        ).fetchone()
        if has_dependencies is not None:
            sections.append("dependencies-impact")
        return sections

    @staticmethod
    def _vdoc_public_desired(plan: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            item for item in plan["desired_state"]
            if item.get("role") in PROJECT_NODE_ROLES["VDOC"]
        ]

    @staticmethod
    def _vdoc_writing_plan_desired(plan: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            item for item in plan["desired_state"]
            if item.get("role") == "document-writing-plan"
        ]

    @staticmethod
    def _vdoc_delivery_desired(plan: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            item for item in plan["desired_state"]
            if item.get("role") == "document-deliverable"
        ]

    @staticmethod
    def _vdoc_internal_desired(
        plan: dict[str, Any], *, parent_id: str | None = None,
        parent_role: str | None = None,
    ) -> list[dict[str, Any]]:
        return [
            item for item in plan["desired_state"]
            if item.get("role") == "document-semantic-unit"
            and (parent_id is None or item.get("parent_id") == parent_id)
            and (parent_role is None or item.get("parent_role") == parent_role)
        ]

    @staticmethod
    def _vdoc_plan_proposal_issues(
        desired_state: list[dict[str, Any]],
    ) -> list[str]:
        """Validate the Human-reviewable VDOC writing-plan phase.

        Template document catalogs and legacy ``--desired`` compatibility nodes
        are intentionally outside this check.  A new structured proposal must
        contain DUT-specific writing plans only.  Semantic delivery nodes are
        registered after those plans are approved, never in the same review batch.
        """
        public = [
            item for item in desired_state
            if item.get("definition_origin") == "project-proposal"
            and item.get("role") in PROJECT_NODE_ROLES["VDOC"]
        ]
        if not public:
            return []
        required_plans = [
            item for item in public
            if item.get("required", True)
            and item.get("role") == "document-writing-plan"
        ]
        premature_deliveries = [
            item for item in public
            if item.get("role") == "document-deliverable"
        ]
        issues: list[str] = []
        if not required_plans:
            issues.append("没有必需的文档撰写方案节点")
        if premature_deliveries:
            issues.append(
                "方案审批前不得创建正文内容验收节点: "
                + ", ".join(sorted(item["key"] for item in premature_deliveries))
            )
        return issues

    @staticmethod
    def _vdoc_delivery_proposal_issues(
        plan: dict[str, Any], deliveries: list[dict[str, Any]],
    ) -> list[str]:
        """Validate post-approval semantic delivery decomposition."""
        required_plans = {
            item["key"]: item for item in plan["desired_state"]
            if item.get("required", True)
            and item.get("role") == "document-writing-plan"
        }
        required_deliveries = [
            item for item in deliveries
            if item.get("required", True)
            and item.get("role") == "document-deliverable"
        ]
        issues: list[str] = []
        if not required_plans:
            issues.append("当前版本没有已批准的必需文档撰写方案节点")
        if not required_deliveries:
            issues.append("没有必需的正文内容验收节点")
        if not required_plans or not required_deliveries:
            return issues

        by_key = {
            item["key"]: item
            for item in [*plan["desired_state"], *deliveries]
            if item.get("role") in PROJECT_NODE_ROLES["VDOC"]
        }

        def owning_plan_key(delivery: dict[str, Any]) -> str | None:
            cursor = str(delivery.get("parent_key") or "")
            visited: set[str] = set()
            while cursor and cursor not in visited:
                if cursor in required_plans:
                    return cursor
                visited.add(cursor)
                parent = by_key.get(cursor)
                if parent is None:
                    return None
                cursor = str(parent.get("parent_key") or "")
            return None

        covered_plans: set[str] = set()
        orphan_deliveries: list[str] = []
        for delivery in required_deliveries:
            owner = owning_plan_key(delivery)
            if owner is None or (
                required_plans[owner].get("document_key")
                != delivery.get("document_key")
            ):
                orphan_deliveries.append(delivery["key"])
            else:
                covered_plans.add(owner)
        uncovered_plans = sorted(set(required_plans) - covered_plans)
        if uncovered_plans:
            issues.append(
                "以下必需撰写方案没有可独立验收的正文交付节点: "
                + ", ".join(uncovered_plans)
            )
        if orphan_deliveries:
            issues.append(
                "以下必需文档交付节点未归属必需撰写方案: "
                + ", ".join(sorted(orphan_deliveries))
            )
        return issues

    @staticmethod
    def _vdoc_document_key(
        plan: dict[str, Any], desired: dict[str, Any],
    ) -> str | None:
        explicit = desired.get("document_key")
        if explicit in VDOC_DOCUMENTS:
            return str(explicit)
        by_key = {item["key"]: item for item in plan["desired_state"]}
        cursor = desired
        visited: set[str] = set()
        while cursor.get("parent_key"):
            parent_key = str(cursor["parent_key"])
            if parent_key in VDOC_DOCUMENTS:
                return parent_key
            if parent_key in visited or parent_key not in by_key:
                return None
            visited.add(parent_key)
            cursor = by_key[parent_key]
        return desired.get("key") if desired.get("key") in VDOC_DOCUMENTS else None

    @staticmethod
    def _vdoc_plan_desired(plan: dict[str, Any]) -> list[dict[str, Any]]:
        return ProjectStore._vdoc_writing_plan_desired(plan)

    @staticmethod
    def _normalize_review_change_items(
        verdict: str, items: Iterable[dict[str, Any]] | None,
        *, default_target: str, default_instruction: str,
    ) -> list[dict[str, str]]:
        """Normalize structured add/modify/delete requests attached to a review."""
        selected = verdict.lower()
        normalized: list[dict[str, str]] = []
        for index, item in enumerate(items or []):
            if not isinstance(item, dict):
                raise HarnessError(f"审批变更项 {index + 1} 必须是 object")
            operation = str(item.get("operation", "")).strip().lower()
            target = str(item.get("target", "")).strip()
            instruction = str(item.get("instruction", "")).strip()
            if operation not in {"add", "modify", "delete"}:
                raise HarnessError("审批变更动作必须是 add/modify/delete")
            if not target or not instruction:
                raise HarnessError("审批变更项必须填写影响范围和具体要求")
            normalized.append({
                "operation": operation,
                "target": target,
                "instruction": instruction,
            })
        if selected == "modify" and not normalized:
            normalized.append({
                "operation": "modify",
                "target": default_target,
                "instruction": default_instruction,
            })
        if selected != "modify" and normalized:
            raise HarnessError("只有“要求修改”结论可以提交新增、修改或删除要求")
        return normalized

    @staticmethod
    def _review_change_items(
        connection: sqlite3.Connection, review_ids: Iterable[str],
    ) -> dict[str, list[dict[str, str]]]:
        identifiers = list(review_ids)
        if not identifiers:
            return {}
        placeholders = ",".join("?" for _ in identifiers)
        result: dict[str, list[dict[str, str]]] = {}
        for row in connection.execute(
            f"""SELECT review_id,operation,target,instruction
                FROM review_change_items
                WHERE review_id IN ({placeholders})
                ORDER BY review_id,sequence""",
            identifiers,
        ):
            result.setdefault(row["review_id"], []).append({
                "operation": row["operation"],
                "target": row["target"],
                "instruction": row["instruction"],
            })
        return result

    @staticmethod
    def _store_review_change_items(
        connection: sqlite3.Connection, review_id: str,
        items: Iterable[dict[str, str]],
    ) -> None:
        for sequence, item in enumerate(items, 1):
            connection.execute(
                "INSERT INTO review_change_items VALUES(?,?,?,?,?)",
                (
                    review_id, sequence, item["operation"], item["target"],
                    item["instruction"],
                ),
            )

    @staticmethod
    def _record_review_submitted_event(
        connection: sqlite3.Connection, review_id: str, node_id: str,
        verdict: str, reviewer: str, change_items: list[dict[str, str]],
        timestamp: str, *, requires_agent_check: bool = False,
    ) -> str:
        """Record a checkpoint for Agent analysis without claiming it already ran."""
        event_id = f"event:{uuid.uuid4().hex[:12]}"
        if requires_agent_check:
            connection.execute(
                "INSERT INTO review_agent_checks VALUES(?,?,?,?,?,?,?,?)",
                (
                    review_id, node_id, "PENDING", None, "", timestamp,
                    timestamp, None,
                ),
            )
        connection.execute(
            "INSERT INTO events VALUES(?,?,?,?,?,?)",
            (
                event_id, "review-submitted", node_id, None,
                json_text({
                    "review_id": review_id,
                    "verdict": verdict.upper(),
                    "reviewer": reviewer,
                    "change_items": change_items,
                    "agent_follow_up": "CHECK_REQUIRED",
                }), timestamp,
            ),
        )
        return event_id

    @staticmethod
    def _review_agent_check(
        connection: sqlite3.Connection, review_id: str | None,
    ) -> dict[str, Any] | None:
        if not review_id:
            return None
        row = connection.execute(
            "SELECT * FROM review_agent_checks WHERE review_id=?", (review_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def node_plan_review_state(
        self, node_id: str, plan: dict[str, Any] | None = None,
        desired: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.ensure_dashboard_schema()
        if plan is None or desired is None:
            for candidate in self.workstreams():
                match = next(
                    (item for item in candidate["desired_state"] if item["id"] == node_id),
                    None,
                )
                if match is not None:
                    plan, desired = candidate, match
                    break
        if plan is None or desired is None:
            raise HarnessError(f"未知当前计划节点: {node_id}")
        digest = self._node_plan_digest(plan, desired)
        with self.read_connect() as connection:
            rows = [dict(row) for row in connection.execute(
                """SELECT id,node_id,workstream,revision,definition_digest,section,
                          verdict,reviewer,reason,created_at
                   FROM node_plan_section_reviews WHERE node_id=? ORDER BY rowid""",
                (node_id,),
            )]
            change_items = self._review_change_items(
                connection, (row["id"] for row in rows),
            )
            required_sections = self._node_plan_sections(connection, node_id)
        for row in rows:
            row["change_items"] = change_items.get(row["id"], [])
        section_states: list[dict[str, Any]] = []
        for section in required_sections:
            section_rows = [row for row in rows if row["section"] == section]
            current = next((row for row in reversed(section_rows) if (
                row["revision"] == plan["revision"]
                and row["definition_digest"] == digest
            )), None)
            section_status = "PENDING"
            if current is not None:
                section_status = (
                    "APPROVED" if current["verdict"] == "APPROVE"
                    else "CHANGES_REQUESTED"
                )
            section_states.append({
                "section": section,
                "status": section_status,
                "current_review": current,
                "reviews": section_rows,
            })
        if section_states and all(item["status"] == "APPROVED" for item in section_states):
            status = "APPROVED"
        elif any(item["status"] == "CHANGES_REQUESTED" for item in section_states):
            status = "CHANGES_REQUESTED"
        else:
            status = "PENDING"
        return {
            "node_id": node_id,
            "workstream": plan["workstream"],
            "revision": plan["revision"],
            "definition_digest": digest,
            "status": status,
            "sections": section_states,
            "reviews": rows,
        }

    def review_node_plan_section(
        self, node_id: str, section: str, definition_digest: str, verdict: str,
        reviewer: str, reason: str,
        change_items: Iterable[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        selected = verdict.lower()
        if selected not in {"approve", "reject", "modify", "clarify"}:
            raise HarnessError("node plan section verdict 必须是 approve/reject/modify/clarify")
        if not reviewer.strip() or not reason.strip():
            raise HarnessError("node plan review 必须提供 reviewer 和 reason")
        normalized_changes = self._normalize_review_change_items(
            selected, change_items,
            default_target=section,
            default_instruction=reason.strip(),
        )
        state = self.node_plan_review_state(node_id)
        if state["workstream"] != "VDOC":
            raise HarnessError("节点级方案审批当前只适用于 VDOC 文档撰写方案节点")
        if state["definition_digest"] != definition_digest:
            raise HarnessError("文档撰写方案已变化；请刷新 Dashboard 后重新审批")
        allowed_sections = {item["section"] for item in state["sections"]}
        if section not in allowed_sections:
            raise HarnessError("未知或当前不需要审批的文档撰写方案区块")
        plan = self.workstream("VDOC")
        proposal_issues = self._vdoc_plan_proposal_issues(plan["desired_state"])
        if selected == "approve" and proposal_issues:
            raise HarnessError(
                "当前 VDOC 文档工作分解不完整，不能审批撰写方案："
                + "；".join(proposal_issues)
            )
        timestamp = now()
        with self.connect() as connection:
            if selected == "approve" and section == "human-confirmations":
                unresolved_actions = connection.execute(
                    "SELECT COUNT(*) count FROM human_actions WHERE target=? AND status='OPEN'",
                    (node_id,),
                ).fetchone()["count"]
                unresolved_questions = connection.execute(
                    "SELECT COUNT(*) count FROM agent_questions WHERE target=? AND status='OPEN'",
                    (node_id,),
                ).fetchone()["count"]
                if unresolved_actions or unresolved_questions:
                    raise HarnessError(
                        "该文档节点仍有等待负责人确认的事项或 Agent 问题；"
                        "请先处理后再批准文档撰写方案"
                    )
            review_id = f"plan-section-review:{uuid.uuid4().hex[:12]}"
            connection.execute(
                "INSERT INTO node_plan_section_reviews VALUES(?,?,?,?,?,?,?,?,?,?)",
                (review_id, node_id, "VDOC", plan["revision"], definition_digest,
                 section, selected.upper(), reviewer.strip(), reason.strip(), timestamp),
            )
            self._store_review_change_items(connection, review_id, normalized_changes)
            event_id = self._record_review_submitted_event(
                connection, review_id, node_id, selected, reviewer.strip(),
                normalized_changes, timestamp,
            )
            required = [
                item for item in self._vdoc_plan_desired(plan)
                if item.get("required", True)
            ]
            approved = 0
            has_changes_requested = False
            for item in required:
                digest = self._node_plan_digest(plan, item)
                section_approved = True
                for required_section in self._node_plan_sections(connection, item["id"]):
                    latest = connection.execute(
                        """SELECT verdict FROM node_plan_section_reviews
                           WHERE node_id=? AND revision=? AND definition_digest=? AND section=?
                           ORDER BY rowid DESC LIMIT 1""",
                        (item["id"], plan["revision"], digest, required_section),
                    ).fetchone()
                    if latest is None or latest["verdict"] != "APPROVE":
                        section_approved = False
                        if latest is not None:
                            has_changes_requested = True
                        break
                if section_approved:
                    approved += 1
                if item.get("definition_origin") == "project-proposal":
                    item_status = (
                        Validity.VALID.value
                        if section_approved else Validity.REVIEW_REQUIRED.value
                    )
                    connection.execute(
                        "UPDATE nodes SET status=?,updated_at=? WHERE id=?",
                        (item_status, timestamp, item["id"]),
                    )
                    for child in self._vdoc_internal_desired(
                        plan, parent_id=item["id"], parent_role="document-writing-plan",
                    ):
                        connection.execute(
                            "UPDATE nodes SET status=?,updated_at=? WHERE id=?",
                            (item_status, timestamp, child["id"]),
                        )
            all_approved = approved == len(required)
            lifecycle = "ACTIVE" if all_approved else (
                "REVISE" if has_changes_requested else "REVIEW"
            )
            connection.execute(
                "UPDATE workstreams SET lifecycle=?,updated_at=? WHERE name='VDOC'",
                (lifecycle, timestamp),
            )
            if all_approved:
                existing = connection.execute(
                    "SELECT id FROM reviews WHERE workstream='VDOC' AND revision=? AND verdict='APPROVE'",
                    (plan["revision"],),
                ).fetchone()
                if existing is None:
                    connection.execute(
                        "INSERT INTO reviews VALUES(?,?,?,?,?,?,?)",
                        (f"review:{uuid.uuid4().hex[:12]}", "VDOC", plan["revision"],
                         "APPROVE", reviewer.strip(),
                         "所有必需文档撰写方案节点均已由负责人审批通过", timestamp),
                    )
        self.write_workstream_projection("VDOC")
        refreshed = self.node_plan_review_state(node_id)
        return {
            "review_id": review_id,
            "node_id": node_id,
            "section": section,
            "verdict": selected.upper(),
            "reviewer": reviewer.strip(),
            "reason": reason.strip(),
            "change_items": normalized_changes,
            "event_id": event_id,
            "agent_follow_up": {
                "status": "CHECK_REQUIRED",
                "waiting_for_human": False,
                "message": "审批结论已保存；Agent 将在下一检查点分析意见和依赖影响",
            },
            "plan_review": refreshed,
            "lifecycle": self.workstream("VDOC")["lifecycle"],
            "auto_closure": self.evaluate_closure("VDOC"),
        }

    def await_human_review(
        self, workstream: str, revision: int | None = None,
        after_review_id: str | None = None, timeout: float = 60.0,
        activity_id: str | None = None,
    ) -> dict[str, Any]:
        """Wait for one revision-bound formal Workstream review.

        This is a bounded SQLite checkpoint, not a channel for injecting text into an
        Agent session. The caller remains responsible for interpreting the returned
        decision and for ending or continuing its Activity truthfully.
        """
        if timeout < 0:
            raise HarnessError("await-human timeout 不能小于 0")
        name = self.normalize_workstream(workstream)
        plan = self.workstream(name)
        selected_revision = plan["revision"] if revision is None else revision
        if selected_revision != plan["revision"]:
            raise HarnessError(
                f"await-human revision {selected_revision} 不是 {name} 当前 revision {plan['revision']}；"
                "旧 revision 的评审不能恢复当前工作"
            )
        closure = self.evaluate_closure(name, persist=False)
        has_pending_checkpoint = any(
            item.get("kind") == "HUMAN_REVIEW" and item.get("executor") == "human"
            for item in closure["actions"]
        )

        cursor_rowid: int | None = None
        if after_review_id:
            with self.read_connect() as connection:
                cursor = connection.execute(
                    "SELECT rowid,workstream,revision,verdict FROM reviews WHERE id=?",
                    (after_review_id,),
                ).fetchone()
            if cursor is None:
                raise HarnessError(f"未知 review: {after_review_id}")
            if cursor["workstream"] != name or int(cursor["revision"]) != selected_revision:
                raise HarnessError("--after-review 必须属于同一 Workstream 和 revision")
            if cursor["verdict"] not in {"APPROVE", "REJECT", "MODIFY", "CLARIFY"}:
                raise HarnessError("--after-review 必须引用正式 Workstream Review")
            cursor_rowid = int(cursor["rowid"])

        activity: dict[str, Any] | None = None
        if activity_id:
            activity = self.activity(activity_id)
            if activity["workstream"] != name:
                raise HarnessError(f"Activity {activity_id} 不属于 {name}")
            if activity["status"] in {"COMPLETED", "FAILED", "CANCELLED"}:
                raise HarnessError("已结束的 Activity 不能进入人工检查点")
            activity = self.update_activity(
                activity_id, "WAITING_FOR_HUMAN",
                f"等待负责人评审 {name} 工作流版本 {selected_revision}",
            )

        def matching_review() -> dict[str, Any] | None:
            filters = [
                "workstream=?", "revision=?",
                "verdict IN ('APPROVE','REJECT','MODIFY','CLARIFY')",
            ]
            values: list[Any] = [name, selected_revision]
            order = "ASC" if cursor_rowid is not None else "DESC"
            if cursor_rowid is not None:
                filters.append("rowid>?")
                values.append(cursor_rowid)
            with self.read_connect() as connection:
                row = connection.execute(
                    "SELECT rowid,* FROM reviews WHERE " + " AND ".join(filters)
                    + f" ORDER BY rowid {order} LIMIT 1",
                    values,
                ).fetchone()
            if row is None:
                return None
            result = dict(row)
            result.pop("rowid", None)
            return result

        started = time.monotonic()
        while True:
            review = matching_review()
            if review is not None:
                verdict = review["verdict"]
                if activity_id:
                    activity = self.update_activity(
                        activity_id, "RUNNING",
                        f"已收到负责人对 {name} 工作流版本 {selected_revision} 的评审结论：{verdict}",
                    )
                return {
                    "schema": "HumanCheckpoint/1",
                    "status": "DECIDED",
                    "checkpoint": {
                        "action": "HUMAN_REVIEW", "workstream": name,
                        "revision": selected_revision,
                    },
                    "review": review,
                    "resume": verdict == "APPROVE",
                    "next": {
                        "APPROVE": "continue",
                        "MODIFY": "revise",
                        "CLARIFY": "clarify",
                        "REJECT": "stop",
                    }[verdict],
                    "activity": activity,
                }
            if not has_pending_checkpoint:
                if activity_id:
                    self.update_activity(
                        activity_id, "RUNNING",
                        f"{name} 工作流版本 {selected_revision} 当前没有等待负责人处理的评审",
                    )
                raise HarnessError(
                    f"{name} 工作流版本 {selected_revision} 当前没有等待负责人评审的检查点"
                )
            elapsed = time.monotonic() - started
            if elapsed >= timeout:
                return {
                    "schema": "HumanCheckpoint/1",
                    "status": "TIMEOUT",
                    "checkpoint": {
                        "action": "HUMAN_REVIEW", "workstream": name,
                        "revision": selected_revision,
                    },
                    "review": None,
                    "resume": False,
                    "next": "wait",
                    "retry_after_review": after_review_id,
                    "activity": activity,
                }
            time.sleep(min(0.25, max(timeout - elapsed, 0.0)))

    def node_closure_assessment(self, node_id: str) -> dict[str, Any]:
        """Build a reproducible Human-reviewable explanation of one node conclusion."""
        self.require()
        with self.read_connect() as connection:
            row = connection.execute(
                "SELECT id,type,title,workstream,status,data_json,updated_at FROM nodes WHERE id=?",
                (node_id,),
            ).fetchone()
            if row is None:
                raise HarnessError(f"未知 node: {node_id}")
            if row["type"] != "desired-state" or not row["workstream"]:
                raise HarnessError("Closure Assessment 只适用于 Workstream desired-state node")
            data = json.loads(row["data_json"])
            plan = connection.execute(
                "SELECT revision,lifecycle,desired_json FROM workstreams WHERE name=?",
                (row["workstream"],),
            ).fetchone()
            current_ids = {item["id"] for item in json.loads(plan["desired_json"])}
            dependencies = [dict(item) for item in connection.execute(
                """SELECT nodes.id,nodes.title,nodes.status,nodes.workstream,nodes.updated_at
                   FROM edges JOIN nodes ON nodes.id=edges.target
                   WHERE edges.source=? AND edges.relation='DEPENDS_ON' ORDER BY nodes.id""",
                (node_id,),
            )]
            findings = [dict(item) for item in connection.execute(
                "SELECT id,severity,status,details,created_at FROM findings WHERE subject=? ORDER BY created_at",
                (node_id,),
            )]
            evidence_rows = [dict(item) for item in connection.execute(
                """SELECT id,kind,source,digest,verdict,data_json,created_at
                   FROM evidence WHERE subject=? ORDER BY created_at""", (node_id,),
            )]
            reviews = [dict(item) for item in connection.execute(
                "SELECT * FROM node_closure_reviews WHERE node_id=? ORDER BY created_at", (node_id,),
            )]
        evidence: list[dict[str, Any]] = []
        for item in evidence_rows:
            payload = json.loads(item.pop("data_json"))
            validation = payload.get("validation", {})
            evidence.append({
                **item,
                "validation_status": validation.get("status"),
                "blockers": validation.get("blockers", []),
                "facts": validation.get("facts", {}),
                "artifacts": payload.get("artifact_sources", []),
            })
        dependency_blockers = [
            item for item in dependencies
            if item["status"] not in {Validity.VALID.value, Validity.WAIVED.value}
        ]
        open_findings = [item for item in findings if item["status"] == "OPEN"]
        missing_definition = [
            field for field in (
                "statement", "purpose", "scope", "acceptance_criteria", "source_refs",
                "work_content", "implementation_approach", "deliverables",
                "progress_measures", "quality_checks",
            ) if not data.get(field)
        ]
        reasons: list[str] = []
        if node_id not in current_ids:
            conclusion = "STALE_REVISION"
            reasons.append("该节点来自旧版本，不属于当前工作计划")
        elif dependency_blockers:
            conclusion = "BLOCKED"
            reasons.append("有前置工作尚未完成")
        elif row["status"] not in {Validity.VALID.value, Validity.WAIVED.value}:
            conclusion = "NOT_SATISFIED"
            reasons.append(VALIDITY_DESCRIPTIONS.get(row["status"], "这项工作尚未完成"))
        elif open_findings:
            conclusion = "REVIEW_REQUIRED"
            reasons.append("还有尚未处理的问题")
        elif missing_definition:
            conclusion = "REVIEW_REQUIRED"
            reasons.append("缺少说明当前目标、工作范围或完成条件的必要信息")
        else:
            conclusion = "CLOSED"
            reasons.append("完成材料有效，前置工作已完成，且没有待处理问题")

        contract_labels = {
            item.get("label") for item in data.get("evidence_contract", {}).get("requirements", [])
            if isinstance(item, dict) and item.get("label")
        }
        latest_pass = next((item for item in reversed(evidence) if item["verdict"] == "PASS"), None)
        acceptance_results = []
        for criterion in data.get("acceptance_criteria", []):
            if criterion in contract_labels:
                status = "SUPPORTED" if latest_pass and not latest_pass["blockers"] else "NOT_SUPPORTED"
                basis = (
                    f"已有经过检查的支持材料：{latest_pass['source']}"
                    if status == "SUPPORTED" else "还没有找到通过专用检查且没有问题的支持材料"
                )
            elif "prerequisite" in criterion or "前置工作" in criterion:
                status = "SUPPORTED" if not dependency_blockers else "NOT_SUPPORTED"
                basis = (
                    "所有已登记的前置工作都已完成"
                    if status == "SUPPORTED" else
                    "还需要先完成：" + "、".join(item["title"] for item in dependency_blockers)
                )
            else:
                status = "HUMAN_REVIEW_REQUIRED"
                basis = "这项内容需要负责人阅读实际文档或结果后确认"
            acceptance_results.append({"criterion": criterion, "status": status, "basis": basis})
        observed_times = [row["updated_at"]]
        observed_times.extend(item["updated_at"] for item in dependencies)
        observed_times.extend(item["created_at"] for item in evidence)
        observed_times.extend(item["created_at"] for item in findings)
        core = {
            "schema": "NodeClosureAssessment/1",
            "rule_version": "node-closure/1",
            "node_id": node_id, "workstream": row["workstream"],
            "revision": int(plan["revision"]), "current_revision": node_id in current_ids,
            "node_status": row["status"], "conclusion": conclusion, "reasons": reasons,
            "definition": {
                key: data.get(key) for key in (
                    "key", "title", "role", "parent_key", "statement", "purpose",
                    "scope", "acceptance_criteria", "source_refs", "work_content",
                    "implementation_approach", "deliverables", "progress_measures",
                    "quality_checks", "evidence_contract",
                )
            },
            "acceptance_results": acceptance_results,
            "dependencies": dependencies, "dependency_blockers": dependency_blockers,
            "evidence": evidence, "findings": findings, "open_findings": open_findings,
            # This is the newest input observed by the assessment, not wall-clock
            # render time.  Dashboard polling therefore has a stable snapshot until
            # model facts actually change.
            "evaluated_at": max(observed_times),
        }
        digest_payload = {key: value for key, value in core.items() if key != "evaluated_at"}
        core["digest"] = hashlib.sha256(json_text(digest_payload).encode("utf-8")).hexdigest()
        core["reviews"] = reviews
        return core

    def review_node_closure(
        self, node_id: str, assessment_digest: str, verdict: str,
        reviewer: str, reason: str,
    ) -> dict[str, Any]:
        selected = verdict.lower()
        if selected not in {"approve", "reject", "modify", "clarify"}:
            raise HarnessError("node closure verdict 必须是 approve/reject/modify/clarify")
        if not reviewer.strip() or not reason.strip():
            raise HarnessError("node closure review 必须提供 reviewer 和 reason")
        assessment = self.node_closure_assessment(node_id)
        if assessment["digest"] != assessment_digest:
            raise HarnessError("Closure Assessment 已变化；请刷新 Dashboard 后重新评审")
        review_id = f"node-review:{uuid.uuid4().hex[:12]}"
        timestamp = now()
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO node_closure_reviews VALUES(?,?,?,?,?,?,?,?,?)",
                (review_id, node_id, assessment["workstream"], assessment["revision"],
                 assessment_digest, selected.upper(), reviewer.strip(), reason.strip(), timestamp),
            )
            if selected != "approve":
                connection.execute(
                    "UPDATE nodes SET status=?,updated_at=? WHERE id=?",
                    (Validity.REVIEW_REQUIRED.value, timestamp, node_id),
                )
                connection.execute(
                    "INSERT INTO findings VALUES(?,?,?,?,?,?,?)",
                    (f"finding:{uuid.uuid4().hex[:12]}", node_id, "HIGH", "OPEN", None,
                     f"负责人对节点完成判断的结论为 {selected.upper()}：{reason.strip()}", timestamp),
                )
        self.write_model_projection()
        self.write_workstream_projection(assessment["workstream"])
        return {
            "review_id": review_id, "node_id": node_id, "verdict": selected.upper(),
            "reviewer": reviewer.strip(), "reason": reason.strip(),
            "assessment_digest": assessment_digest,
            "node_status": self.model(node_id)["nodes"][0]["status"],
            "auto_closure": self.reconcile(),
        }

    def documents(self, selector: str | None = None) -> list[dict[str, Any]]:
        self.require()
        with self.read_connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='documents'"
            ).fetchone()
            if exists is None:
                if selector is not None:
                    raise HarnessError(f"未知验证文档: {selector}；先执行 plan VDOC")
                return []
            rows = [dict(row) for row in connection.execute("SELECT * FROM documents ORDER BY path")]
            if selector is not None:
                matches = [row for row in rows if selector in {row["id"], row["path"], Path(row["path"]).name}]
                if not matches:
                    raise HarnessError(f"未知验证文档: {selector}")
                if len(matches) > 1:
                    raise HarnessError(f"文档选择不唯一，请使用完整路径或 ID: {selector}")
                rows = matches
            for row in rows:
                current_path = self.root / row["path"]
                row["exists"] = current_path.is_file()
                row["content_changed"] = row["exists"] and self._digest(current_path) != row["digest"]
                row["effective_status"] = (
                    Validity.INVALID.value if not row["exists"] else
                    Validity.REVIEW_REQUIRED.value if row["content_changed"] else row["status"]
                )
                row["revisions"] = [dict(item) for item in connection.execute(
                    "SELECT semantic_revision,digest,summary,created_at FROM document_revisions WHERE document_id=? ORDER BY semantic_revision",
                    (row["id"],),
                )]
                row["reviews"] = [dict(item) for item in connection.execute(
                    "SELECT id,semantic_revision,verdict,reviewer,notes,created_at FROM document_reviews WHERE document_id=? ORDER BY created_at",
                    (row["id"],),
                )]
                items = [dict(item) for item in connection.execute(
                    "SELECT id,kind,title,anchor,status,owner,review_trigger,affects_json,created_at,updated_at "
                    "FROM document_items WHERE document_id=? ORDER BY kind,id",
                    (row["id"],),
                )]
                for item in items:
                    item["affects"] = json.loads(item.pop("affects_json"))
                row["governance_items"] = items
        try:
            plan = self.workstream("VDOC")
        except HarnessError:
            plan = None
        for row in rows:
            row["document_key"] = row["id"].removeprefix("document:vdoc:")
            row["delivery_nodes"] = []
            if plan is None or plan["lifecycle"] not in {
                "ACTIVE", "PARTIALLY_STALE", "SATISFIED", "BASELINED",
            }:
                continue
            row["delivery_nodes"] = [
                {
                    "id": item["id"], "key": item["key"], "title": item["title"],
                    "required": item.get("required", True),
                    "role": item.get("role"),
                    "document_key": self._vdoc_document_key(plan, item),
                    "acceptance_criteria": item.get("acceptance_criteria", []),
                    "work_content": item.get("work_content", []),
                }
                for item in self._vdoc_delivery_desired(plan)
                if self._vdoc_document_key(plan, item) == row["document_key"]
            ]
        return rows

    def document_delivery_review_state(
        self, node_id: str, plan: dict[str, Any] | None = None,
        desired: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return revision-bound review state for one semantic delivery node."""
        self.ensure_dashboard_schema()
        if plan is None:
            plan = self.workstream("VDOC")
        if desired is None:
            desired = next(
                (item for item in plan["desired_state"] if item["id"] == node_id), None,
            )
        if desired is None or desired.get("role") != "document-deliverable":
            raise HarnessError(f"未知当前文档交付节点: {node_id}")
        document_key = self._vdoc_document_key(plan, desired)
        if document_key is None:
            raise HarnessError(f"文档交付节点未明确归属文档: {node_id}")
        document = self.documents(f"document:vdoc:{document_key}")[0]
        definition_digest = self._node_plan_digest(plan, desired)
        internal_children = self._vdoc_internal_desired(plan, parent_id=node_id)
        with self.read_connect() as connection:
            rows = [dict(row) for row in connection.execute(
                """SELECT id,node_id,workstream,revision,definition_digest,document_id,
                          semantic_revision,document_digest,verdict,reviewer,notes,created_at
                   FROM document_delivery_reviews WHERE node_id=? ORDER BY rowid""",
                (node_id,),
            )]
            change_items = self._review_change_items(
                connection, (row["id"] for row in rows),
            )
            provisional_details = {
                row["review_id"]: dict(row) for row in connection.execute(
                    "SELECT review_id,owner,review_trigger FROM document_delivery_provisionals"
                )
            }
            agent_checks = {
                row["review_id"]: dict(row) for row in connection.execute(
                    "SELECT * FROM review_agent_checks WHERE node_id=?",
                    (node_id,),
                )
            }
            open_agent_questions = [dict(row) for row in connection.execute(
                """SELECT id,prompt,context,created_at FROM agent_questions
                   WHERE target=? AND status='OPEN' ORDER BY created_at""",
                (node_id,),
            )]
            observed_internal = {row["id"]: dict(row) for row in connection.execute(
                "SELECT id,title,status FROM nodes WHERE id IN (%s) ORDER BY id"
                % ",".join("?" for _ in internal_children),
                [item["id"] for item in internal_children],
            )} if internal_children else {}
        internal_statuses = [
            observed_internal.get(item["id"], {
                "id": item["id"], "title": item["title"], "status": "MISSING",
            })
            for item in internal_children
        ]
        internal_blockers = [
            item for item in internal_statuses
            if item["status"] not in {Validity.VALID.value, Validity.WAIVED.value}
        ]
        for row in rows:
            row["provisional"] = provisional_details.get(row["id"])
            row["change_items"] = change_items.get(row["id"], [])
            row["agent_check"] = agent_checks.get(row["id"])
        current = next((row for row in reversed(rows) if (
            row["revision"] == plan["revision"]
            and row["definition_digest"] == definition_digest
            and row["document_id"] == document["id"]
            and row["semantic_revision"] == document["semantic_revision"]
            and row["document_digest"] == document["digest"]
        )), None)
        status = "PENDING"
        if current is not None:
            check = current.get("agent_check")
            if open_agent_questions:
                status = "WAITING_FOR_HUMAN"
            elif check is not None and check["status"] != "COMPLETED":
                status = "AGENT_CHECKING"
            else:
                status = (
                    "APPROVED" if current["verdict"] == "APPROVE"
                    else "PROVISIONAL" if current["verdict"] == "PROVISIONAL"
                    else "CHANGES_REQUESTED"
                )
                if status in {"APPROVED", "PROVISIONAL"} and internal_blockers:
                    status = "AGENT_CHECKING"
        if not document["exists"] or document["content_changed"]:
            status = "PENDING"
            current = None
        return {
            "node_id": node_id,
            "workstream": "VDOC",
            "revision": plan["revision"],
            "definition_digest": definition_digest,
            "document_key": document_key,
            "document_id": document["id"],
            "document_path": document["path"],
            "semantic_revision": document["semantic_revision"],
            "document_digest": document["digest"],
            "status": status,
            "current_review": current,
            "reviews": rows,
            "agent_check": current.get("agent_check") if current is not None else None,
            "open_agent_questions": open_agent_questions,
            "internal_work": {
                "total": len(internal_statuses),
                "complete": len(internal_statuses) - len(internal_blockers),
                "ready": not internal_blockers,
                "blockers": internal_blockers,
            },
        }

    def _refresh_vdoc_delivery_acceptance(self, node_id: str) -> None:
        """Recompute delivery acceptance from review, Agent check, and open questions."""
        plan = self.workstream("VDOC")
        desired = next(
            (item for item in plan["desired_state"] if item["id"] == node_id), None,
        )
        if desired is None or desired.get("role") != "document-deliverable":
            return
        document_key = self._vdoc_document_key(plan, desired)
        if document_key is None:
            return
        document = self.documents(f"document:vdoc:{document_key}")[0]
        related = [
            item for item in self._vdoc_delivery_desired(plan)
            if item.get("required", True)
            and self._vdoc_document_key(plan, item) == document_key
        ]
        timestamp = now()
        all_approved = bool(related)
        all_usable = bool(related)
        has_provisional = False
        with self.connect() as connection:
            for item in related:
                digest = self._node_plan_digest(plan, item)
                latest = connection.execute(
                    """SELECT id,verdict FROM document_delivery_reviews
                       WHERE node_id=? AND revision=? AND definition_digest=?
                         AND document_id=? AND semantic_revision=? AND document_digest=?
                       ORDER BY rowid DESC LIMIT 1""",
                    (
                        item["id"], plan["revision"], digest, document["id"],
                        document["semantic_revision"], document["digest"],
                    ),
                ).fetchone()
                open_questions = connection.execute(
                    """SELECT COUNT(*) count FROM agent_questions
                       WHERE target=? AND status='OPEN'""",
                    (item["id"],),
                ).fetchone()["count"]
                check = self._review_agent_check(
                    connection, latest["id"] if latest is not None else None,
                )
                internal_children = self._vdoc_internal_desired(
                    plan, parent_id=item["id"],
                )
                internal_statuses = {
                    row["id"]: row["status"] for row in connection.execute(
                        "SELECT id,status FROM nodes WHERE id IN (%s)"
                        % ",".join("?" for _ in internal_children),
                        [child["id"] for child in internal_children],
                    )
                } if internal_children else {}
                internal_blockers = sum(
                    internal_statuses.get(child["id"])
                    not in {Validity.VALID.value, Validity.WAIVED.value}
                    for child in internal_children
                )
                agent_checked = check is None or check["status"] == "COMPLETED"
                eligible = (
                    latest is not None and not open_questions and agent_checked
                    and not internal_blockers
                )
                item_status = (
                    Validity.VALID.value
                    if eligible and latest["verdict"] == "APPROVE"
                    else Validity.PROVISIONAL.value
                    if eligible and latest["verdict"] == "PROVISIONAL"
                    else Validity.REVIEW_REQUIRED.value
                )
                connection.execute(
                    "UPDATE nodes SET status=?,updated_at=? WHERE id=?",
                    (item_status, timestamp, item["id"]),
                )
                if item_status not in {Validity.VALID.value, Validity.PROVISIONAL.value}:
                    all_usable = False
                if item_status == Validity.PROVISIONAL.value:
                    has_provisional = True
                if item_status != Validity.VALID.value:
                    all_approved = False
            document_status = (
                Validity.VALID.value if all_approved
                else Validity.PROVISIONAL.value if all_usable and has_provisional
                else Validity.REVIEW_REQUIRED.value
            )
            connection.execute(
                "UPDATE documents SET status=?,updated_at=? WHERE id=?",
                (document_status, timestamp, document["id"]),
            )
            connection.execute(
                "UPDATE nodes SET status=?,updated_at=? WHERE id IN (?,?,?)",
                (
                    document_status, timestamp, document["id"],
                    document["desired_id"], f"file:{document['path']}",
                ),
            )

    def complete_review_agent_check(
        self, review_id: str, checked_by: str, summary: str,
    ) -> dict[str, Any]:
        """Record that the Main Agent inspected one submitted delivery review."""
        self.ensure_dashboard_schema()
        if not checked_by.strip() or not summary.strip():
            raise HarnessError("Agent 检查必须提供 checked_by 和 summary")
        if checked_by.strip() != PROJECT_AGENT_ACTOR:
            raise HarnessError(
                f"正文验收检查只能由 {PROJECT_AGENT_ACTOR} 完成；负责人不能代替 Agent 检查"
            )
        timestamp = now()
        open_question_ids: list[str] = []
        with self.connect() as connection:
            check = connection.execute(
                "SELECT * FROM review_agent_checks WHERE review_id=?", (review_id,),
            ).fetchone()
            if check is None:
                raise HarnessError(f"未知或无需 Agent 检查的审批记录: {review_id}")
            open_questions = connection.execute(
                """SELECT id FROM agent_questions
                   WHERE target=? AND status='OPEN' ORDER BY created_at""",
                (check["node_id"],),
            ).fetchall()
            if open_questions:
                open_question_ids = [item["id"] for item in open_questions]
                connection.execute(
                    """UPDATE review_agent_checks SET status='WAITING_FOR_HUMAN',
                       checked_by=?,summary=?,updated_at=? WHERE review_id=?""",
                    (checked_by.strip(), summary.strip(), timestamp, review_id),
                )
            else:
                connection.execute(
                    """UPDATE review_agent_checks SET status='COMPLETED',checked_by=?,summary=?,
                       updated_at=?,checked_at=? WHERE review_id=?""",
                    (
                        checked_by.strip(), summary.strip(), timestamp, timestamp, review_id,
                    ),
                )
            node_id = check["node_id"]
        self._refresh_vdoc_delivery_acceptance(node_id)
        self.write_model_projection()
        closure = self.evaluate_closure("VDOC")
        if open_question_ids:
            raise HarnessError(
                "Agent 已提出等待负责人回答的问题（"
                + "、".join(open_question_ids)
                + "）；全部解决并重新检查后才能完成"
            )
        state = self.document_delivery_review_state(node_id)
        return {
            "review_id": review_id,
            "node_id": node_id,
            "agent_check": state["agent_check"],
            "delivery_review": state,
            "document": self.documents(state["document_id"])[0],
            "auto_closure": closure,
        }

    def review_agent_checks(self, status: str | None = None) -> list[dict[str, Any]]:
        """List durable Agent checkpoints created by submitted delivery reviews."""
        self.ensure_dashboard_schema()
        selected = status.upper() if status else None
        if selected and selected not in {"PENDING", "WAITING_FOR_HUMAN", "COMPLETED"}:
            raise HarnessError(
                "Agent 审批检查状态必须是 PENDING/WAITING_FOR_HUMAN/COMPLETED"
            )
        where = " WHERE c.status=?" if selected else ""
        values: tuple[Any, ...] = (selected,) if selected else ()
        with self.read_connect() as connection:
            rows = [dict(row) for row in connection.execute(
                """SELECT c.*,r.verdict,r.reviewer,r.notes,r.document_id,
                          r.semantic_revision,r.document_digest
                   FROM review_agent_checks c
                   JOIN document_delivery_reviews r ON r.id=c.review_id"""
                + where + " ORDER BY c.created_at DESC",
                values,
            )]
            change_items = self._review_change_items(
                connection, (row["review_id"] for row in rows),
            )
        for row in rows:
            row["change_items"] = change_items.get(row["review_id"], [])
        return rows

    def review_document_delivery(
        self, node_id: str, definition_digest: str, document_digest: str,
        verdict: str, reviewer: str, notes: str,
        provisional_owner: str = "", review_trigger: str = "",
        change_items: Iterable[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        selected = verdict.lower()
        if selected not in {"approve", "provisional", "reject", "modify", "clarify"}:
            raise HarnessError("document delivery verdict 必须是 approve/provisional/reject/modify/clarify")
        if not reviewer.strip() or not notes.strip():
            raise HarnessError("文档交付节点评审必须提供 reviewer 和 notes")
        normalized_changes = self._normalize_review_change_items(
            selected, change_items,
            default_target="当前文档交付范围",
            default_instruction=notes.strip(),
        )
        if selected == "provisional" and (
            not provisional_owner.strip() or not review_trigger.strip()
        ):
            raise HarnessError("暂定接受必须填写责任人和重新评审触发条件")
        plan = self.workstream("VDOC")
        desired = next(
            (item for item in plan["desired_state"] if item["id"] == node_id), None,
        )
        if desired is None or desired.get("role") != "document-deliverable":
            raise HarnessError(f"未知当前文档交付节点: {node_id}")
        if plan["lifecycle"] not in {"ACTIVE", "SATISFIED", "PARTIALLY_STALE"}:
            raise HarnessError("必须先批准当前 VDOC 文档撰写方案，再验收文档交付节点")
        document_key = self._vdoc_document_key(plan, desired)
        document_id = f"document:vdoc:{document_key}"
        self.sync_documents([document_id])
        state = self.document_delivery_review_state(node_id, plan, desired)
        if state["definition_digest"] != definition_digest:
            raise HarnessError("文档交付节点定义已变化；请刷新 Dashboard 后重新审批")
        if state["document_digest"] != document_digest:
            raise HarnessError("文档正文已变化；请刷新 Dashboard 后重新审批")
        if (
            state["current_review"] is not None
            and state["agent_check"] is not None
            and state["agent_check"]["status"] != "COMPLETED"
        ):
            raise HarnessError(
                "上一份正文验收结论仍在等待 Agent 检查或负责人回答；"
                "完成本轮检查后才能提交新的验收结论"
            )
        document = self.documents(document_id)[0]
        pending_items = [
            item for item in document["governance_items"]
            if item["kind"] in {"human-decision", "external-open-question"}
            and item["status"] in {"PENDING", "ACTIVE"}
        ]
        with self.read_connect() as connection:
            pending_confirmations = [dict(row) for row in connection.execute(
                """SELECT id,action,reviewer,reason,created_at FROM human_actions
                   WHERE target=? AND status='OPEN' ORDER BY created_at""",
                (node_id,),
            )]
            pending_questions = [dict(row) for row in connection.execute(
                """SELECT id,prompt,context,created_at FROM agent_questions
                   WHERE target=? AND status='OPEN' ORDER BY created_at""",
                (node_id,),
            )]
        if selected == "approve" and (
            pending_items or pending_confirmations or pending_questions
        ):
            blockers = [item["id"] for item in pending_items]
            blockers.extend(item["id"] for item in pending_confirmations)
            blockers.extend(item["id"] for item in pending_questions)
            raise HarnessError(
                "交付节点仍有等待负责人确认的问题、工程决定或 Agent 分析事项（"
                + "、".join(blockers) + "）；逐项处理后才能批准交付节点"
            )
        timestamp = now()
        review_id = f"delivery-review:{uuid.uuid4().hex[:12]}"
        node_status = (
            Validity.VALID.value if selected == "approve"
            else Validity.PROVISIONAL.value if selected == "provisional"
            else Validity.REVIEW_REQUIRED.value
        )
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO document_delivery_reviews VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (review_id, node_id, "VDOC", plan["revision"], definition_digest,
                 document["id"], document["semantic_revision"], document["digest"],
                 selected.upper(), reviewer.strip(), notes.strip(), timestamp),
            )
            self._store_review_change_items(connection, review_id, normalized_changes)
            if selected == "provisional":
                connection.execute(
                    "INSERT INTO document_delivery_provisionals VALUES(?,?,?)",
                    (review_id, provisional_owner.strip(), review_trigger.strip()),
                )
            connection.execute(
                "UPDATE nodes SET status=?,updated_at=? WHERE id=?",
                (node_status, timestamp, node_id),
            )
            related = [
                item for item in self._vdoc_delivery_desired(plan)
                if item.get("required", True)
                and self._vdoc_document_key(plan, item) == document_key
            ]
            all_approved = bool(related)
            all_usable = bool(related)
            has_provisional = False
            for item in related:
                digest = self._node_plan_digest(plan, item)
                latest = connection.execute(
                    """SELECT verdict FROM document_delivery_reviews
                       WHERE node_id=? AND revision=? AND definition_digest=?
                         AND document_id=? AND semantic_revision=? AND document_digest=?
                       ORDER BY rowid DESC LIMIT 1""",
                    (item["id"], plan["revision"], digest, document["id"],
                     document["semantic_revision"], document["digest"]),
                ).fetchone()
                if latest is None or latest["verdict"] not in {"APPROVE", "PROVISIONAL"}:
                    all_usable = False
                if latest is not None and latest["verdict"] == "PROVISIONAL":
                    has_provisional = True
                if latest is None or latest["verdict"] != "APPROVE":
                    all_approved = False
            document_status = (
                Validity.VALID.value if all_approved
                else Validity.PROVISIONAL.value if all_usable and has_provisional
                else Validity.REVIEW_REQUIRED.value
            )
            connection.execute(
                "UPDATE documents SET status=?,updated_at=? WHERE id=?",
                (document_status, timestamp, document["id"]),
            )
            connection.execute(
                "UPDATE nodes SET status=?,updated_at=? WHERE id IN (?,?,?)",
                (document_status, timestamp, document["id"], document["desired_id"],
                 f"file:{document['path']}"),
            )
            event_id = self._record_review_submitted_event(
                connection, review_id, node_id, selected, reviewer.strip(),
                normalized_changes, timestamp, requires_agent_check=True,
            )
        self._refresh_vdoc_delivery_acceptance(node_id)
        self.write_model_projection()
        closure = self.evaluate_closure("VDOC")
        return {
            "review_id": review_id,
            "node_id": node_id,
            "verdict": selected.upper(),
            "reviewer": reviewer.strip(),
            "notes": notes.strip(),
            "change_items": normalized_changes,
            "event_id": event_id,
            "agent_follow_up": {
                "status": "AGENT_CHECKING",
                "waiting_for_human": False,
                "message": "验收结论已保存；Agent 必须检查后才能形成验收状态",
            },
            "delivery_review": self.document_delivery_review_state(node_id),
            "document": self.documents(document_id)[0],
            "auto_closure": closure,
        }

    def document_content(self, selector: str) -> dict[str, Any]:
        """Read one registered VDOC body for the loopback Dashboard review surface."""
        document = self.documents(selector)[0]
        path = self.root / document["path"]
        if path.is_symlink():
            raise HarnessError(f"拒绝通过符号链接读取验证文档: {document['path']}")
        if not path.is_file():
            raise HarnessError(f"验证文档不存在: {document['path']}")
        if path.stat().st_size > 2 * 1024 * 1024:
            raise HarnessError("Dashboard 只预览不超过 2 MiB 的验证文档")
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise HarnessError("Dashboard 只预览 UTF-8 编码的验证文档") from exc
        return {"document": document, "content": content}

    def sync_documents(
        self, selectors: Iterable[str] = (), *, require_active: bool = False,
    ) -> dict[str, Any]:
        if require_active:
            plan = self.workstream("VDOC")
            if plan["lifecycle"] not in {"ACTIVE", "PARTIALLY_STALE", "SATISFIED"}:
                raise HarnessError(
                    "必须先由负责人批准当前 VDOC 文档撰写方案，"
                    "Agent 才能同步正文语义版本"
                )
        requested = list(selectors)
        rows = self.documents()
        if requested:
            selected: list[dict[str, Any]] = []
            for selector in requested:
                selected.extend(self.documents(selector))
            unique = {row["id"]: row for row in selected}
            rows = [unique[key] for key in sorted(unique)]
        if not rows:
            raise HarnessError("尚未登记验证文档；先执行 plan VDOC")
        try:
            plan = self.workstream("VDOC")
        except HarnessError:
            plan = None
        delivery_ids_by_document: dict[str, list[str]] = {}
        if plan is not None:
            for item in self._vdoc_delivery_desired(plan):
                key = self._vdoc_document_key(plan, item)
                if key is not None:
                    delivery_ids_by_document.setdefault(key, []).append(item["id"])
        changed: list[tuple[str, int]] = []
        missing: list[str] = []
        newly_missing: list[str] = []
        restored: list[tuple[str, int]] = []
        with self.connect() as connection:
            for row in rows:
                path = self.root / row["path"]
                if not path.is_file():
                    connection.execute("UPDATE documents SET status=?,updated_at=? WHERE id=?",
                                       (Validity.INVALID.value, now(), row["id"]))
                    connection.execute("UPDATE nodes SET status=?,updated_at=? WHERE id=?",
                                       (Validity.INVALID.value, now(), row["id"]))
                    for node_id in delivery_ids_by_document.get(row["document_key"], []):
                        connection.execute(
                            "UPDATE nodes SET status=?,updated_at=? WHERE id=?",
                            (Validity.INVALID.value, now(), node_id),
                        )
                    missing.append(row["path"])
                    if row["status"] != Validity.INVALID.value:
                        newly_missing.append(row["path"])
                    continue
                observed_changed, result = self._register_document(
                    connection, row["id"], row["path"], row["title"], row["desired_id"],
                    row["owner"], "验证文档正文摘要发生变化",
                )
                if observed_changed:
                    changed.append((row["path"], result["semantic_revision"]))
                    for node_id in delivery_ids_by_document.get(row["document_key"], []):
                        connection.execute(
                            "UPDATE nodes SET status=?,updated_at=? WHERE id=?",
                            (Validity.REVIEW_REQUIRED.value, now(), node_id),
                        )
                elif row["status"] == Validity.INVALID.value:
                    connection.execute("UPDATE documents SET status=?,updated_at=? WHERE id=?",
                                       (Validity.REVIEW_REQUIRED.value, now(), row["id"]))
                    connection.execute("UPDATE nodes SET status=?,updated_at=? WHERE id=?",
                                       (Validity.REVIEW_REQUIRED.value, now(), row["id"]))
                    for node_id in delivery_ids_by_document.get(row["document_key"], []):
                        connection.execute(
                            "UPDATE nodes SET status=?,updated_at=? WHERE id=?",
                            (Validity.REVIEW_REQUIRED.value, now(), node_id),
                        )
                    restored.append((row["path"], result["semantic_revision"]))
        for path, revision in changed:
            self.record_change(path, "modify", f"document-r{revision}")
        for path in newly_missing:
            self.record_change(path, "delete", None)
        for path, revision in restored:
            self.record_change(path, "add", f"document-r{revision}")
        self.write_model_projection()
        return {"documents": self.documents(), "changed": [path for path, _revision in changed],
                "missing": missing, "restored": [path for path, _revision in restored],
                "state_projection_written": False}

    def review_document(
        self, selector: str, verdict: str, reviewer: str, notes: str,
    ) -> dict[str, Any]:
        plan = self.workstream("VDOC")
        if plan["lifecycle"] not in {"ACTIVE", "SATISFIED", "PARTIALLY_STALE"}:
            raise HarnessError("必须先由负责人批准当前 VDOC 文档撰写方案，再评审文档正文")
        self.sync_documents([selector])
        document = self.documents(selector)[0]
        pending_items = [
            item for item in document["governance_items"]
            if item["kind"] in {"human-decision", "external-open-question"}
            and item["status"] in {"PENDING", "ACTIVE"}
        ]
        if verdict == "approve" and pending_items:
            item_ids = "、".join(item["id"] for item in pending_items)
            raise HarnessError(
                f"文档仍有待处理的问题或工程决定（{item_ids}）；"
                "请先更新正文并将这些事项标记为已处理，再评为通过"
            )
        normalized = verdict.upper()
        review_id = uuid.uuid4().hex
        status = Validity.VALID.value if verdict == "approve" else Validity.REVIEW_REQUIRED.value
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO document_reviews VALUES(?,?,?,?,?,?,?)",
                (review_id, document["id"], document["semantic_revision"], normalized,
                 reviewer, notes, now()),
            )
            connection.execute("UPDATE documents SET status=?,updated_at=? WHERE id=?",
                               (status, now(), document["id"]))
            connection.execute("UPDATE nodes SET status=?,updated_at=? WHERE id=?",
                               (status, now(), document["id"]))
            if verdict == "approve":
                connection.execute("UPDATE nodes SET status=?,updated_at=? WHERE id=?",
                                   (Validity.VALID.value, now(), f"file:{document['path']}"))
                connection.execute(
                    "UPDATE findings SET status='RESOLVED' WHERE subject IN (?,?) AND status='OPEN'",
                    (document["id"], f"file:{document['path']}"),
                )
            if verdict != "approve" and document["desired_id"]:
                connection.execute("UPDATE nodes SET status=?,updated_at=? WHERE id=?",
                                   (Validity.REVIEW_REQUIRED.value, now(), document["desired_id"]))
        evidence = None
        if verdict == "approve" and document["desired_id"]:
            evidence = self.add_evidence(document["desired_id"], "document-review", document["path"], "pass")
        self.write_model_projection()
        return {"review_id": review_id, "document": self.documents(selector)[0],
                "verdict": normalized, "reviewer": reviewer, "evidence": evidence,
                "auto_closure": self.evaluate_closure("VDOC")}

    def track_document_item(
        self, selector: str, item_id: str, kind: str, title: str, status: str,
        owner: str | None, review_trigger: str | None, affects: list[str], anchor: str | None,
    ) -> dict[str, Any]:
        document = self.documents(selector)[0]
        normalized_kind = kind.lower()
        normalized_status = status.upper()
        if normalized_kind not in DOCUMENT_ITEM_KINDS:
            raise HarnessError("治理事项类型必须是 " + ", ".join(sorted(DOCUMENT_ITEM_KINDS)))
        if normalized_status not in DOCUMENT_ITEM_STATUSES:
            raise HarnessError("治理事项状态必须是 " + ", ".join(sorted(DOCUMENT_ITEM_STATUSES)))
        if not item_id.strip() or any(character.isspace() for character in item_id):
            raise HarnessError("治理事项 ID 不能为空或包含空白")
        timestamp = now()
        with self.connect() as connection:
            previous = connection.execute("SELECT * FROM document_items WHERE id=?", (item_id,)).fetchone()
            connection.execute(
                "INSERT INTO document_items VALUES(?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET document_id=excluded.document_id,kind=excluded.kind,"
                "title=excluded.title,anchor=excluded.anchor,status=excluded.status,owner=excluded.owner,"
                "review_trigger=excluded.review_trigger,affects_json=excluded.affects_json,updated_at=excluded.updated_at",
                (item_id, document["id"], normalized_kind, title, anchor, normalized_status,
                 owner, review_trigger, json_text(affects), timestamp, timestamp),
            )
            connection.execute(
                "INSERT INTO events VALUES(?,?,?,?,?,?)",
                (f"event:{uuid.uuid4().hex[:12]}", "document-item-change", item_id,
                 str(document["semantic_revision"]), json_text({
                     "document_id": document["id"], "previous_status": previous["status"] if previous else None,
                     "status": normalized_status, "kind": normalized_kind,
                }), timestamp),
            )
            if normalized_kind in {"human-decision", "external-open-question"}:
                unresolved = connection.execute(
                    """SELECT COUNT(*) count FROM document_items
                       WHERE kind IN ('human-decision','external-open-question')
                         AND status IN ('PENDING','ACTIVE')"""
                ).fetchone()["count"]
                lifecycle = "PARTIALLY_STALE" if unresolved else "ACTIVE"
                connection.execute(
                    "UPDATE workstreams SET lifecycle=?,updated_at=? WHERE name='VDOC' AND lifecycle IN ('ACTIVE','SATISFIED','BASELINED','PARTIALLY_STALE')",
                    (lifecycle, timestamp),
                )
        result = {"id": item_id, "document_id": document["id"], "kind": normalized_kind,
                  "title": title, "status": normalized_status, "owner": owner,
                  "review_trigger": review_trigger, "affects": affects, "anchor": anchor}
        result["auto_closure"] = self.reconcile()
        return result

    def render_document_state(self, selector: str | None = None) -> str:
        documents = self.documents(selector)
        if not documents:
            raise HarnessError("尚未登记验证文档；先执行 plan VDOC")

        def cell(value: Any) -> str:
            return str(value if value not in {None, ""} else "—").replace("|", "\\|").replace("\n", " ")

        lines = ["# 验证文档治理状态", "",
                 "> 本内容由 `.verif-harness/model.sqlite3` 按需生成；不要手工并入验证文档正文。"]
        labels = {
            "human-decision": "负责人决定", "provisional": "暂定决定",
            "assumption": "Assumptions", "external-open-question": "External Open Questions",
        }
        for document in documents:
            lines.extend(["", f"## `{document['path']}`", "",
                          f"- Document ID：`{document['id']}`",
                          f"- Semantic revision：**{document['semantic_revision']}**",
                          f"- Status：**{document['effective_status']}**",
                          f"- Recorded status：**{document['status']}**",
                          f"- Working tree content changed：**{str(document['content_changed']).lower()}**",
                          f"- Content digest：`{document['digest']}`",
                          f"- Desired ID：`{document['desired_id'] or '—'}`",
                          f"- Owner：{document['owner']}"])
            for kind, label in labels.items():
                items = [item for item in document["governance_items"] if item["kind"] == kind]
                lines.extend(["", f"### {label}", "",
                              "| ID | 状态 | 内容 | Owner | 复审触发器 | 影响目标 | 文档锚点 |",
                              "| --- | --- | --- | --- | --- | --- | --- |"])
                lines.extend(
                    f"| `{cell(item['id'])}` | {cell(item['status'])} | {cell(item['title'])} | "
                    f"{cell(item['owner'])} | {cell(item['review_trigger'])} | "
                    f"{cell(', '.join(item['affects']))} | {cell(item['anchor'])} |" for item in items
                )
                if not items:
                    lines.append("| — | — | 无 | — | — | — | — |")
            lines.extend(["", "### Review Trace", "",
                          "| Revision | Verdict | Reviewer | 时间 |",
                          "| --- | --- | --- | --- |"])
            lines.extend(
                f"| {item['semantic_revision']} | {cell(item['verdict'])} | {cell(item['reviewer'])} | {cell(item['created_at'])} |"
                for item in document["reviews"]
            )
            if not document["reviews"]:
                lines.append("| — | — | 尚无评审 | — |")
            lines.extend(["", "### 负责人评审意见", ""])
            notes = [item for item in document["reviews"] if item["notes"]]
            lines.extend(
                f"- r{item['semantic_revision']} · {item['reviewer']} · {item['verdict']}：{item['notes']}"
                for item in notes
            )
            if not notes:
                lines.append("- 无")
            lines.extend(["", "### Revision Log", "",
                          "| Revision | Digest | 摘要 | 时间 |",
                          "| --- | --- | --- | --- |"])
            lines.extend(
                f"| {item['semantic_revision']} | `{item['digest']}` | {cell(item['summary'])} | {cell(item['created_at'])} |"
                for item in document["revisions"]
            )
        return "\n".join(lines) + "\n"

    def write_document_state_projection(self, output: str, selector: str | None = None) -> dict[str, Any]:
        relative = relative_path(self.root, output)
        self._document_path_allowed(relative)
        if any(row["path"] == relative for row in self.documents()):
            raise HarnessError("状态汇总文件不能覆盖验证文档")
        atomic_text(self.root / relative, self.render_document_state(selector))
        return {"path": relative, "selector": selector, "source": ".verif-harness/model.sqlite3"}

    def _baseline_payload(self, workstream: str, reviewer: str, reason: str) -> dict[str, Any]:
        plan = self.workstream(workstream)
        model = self.model()
        payload = {
            "schema": "WorkstreamBaseline/1", "created_at": now(), "project_revision": git_revision(self.root),
            "reviewer": reviewer, "reason": reason, "plan": plan,
            "nodes": [node for node in model["nodes"] if node.get("workstream") == workstream],
            "edges": [edge for edge in model["edges"] if any(
                node["id"] in {edge["source"], edge["target"]} for node in model["nodes"] if node.get("workstream") == workstream
            )],
            "findings": [finding for finding in model["findings"] if any(
                node["id"] == finding["subject"] for node in model["nodes"] if node.get("workstream") == workstream
            )],
            "evidence": [item for item in model["evidence"] if any(
                node["id"] == item["subject"] for node in model["nodes"] if node.get("workstream") == workstream
            )],
        }
        if workstream == "VDOC":
            documents = self.documents()
            if documents:
                payload["documents"] = documents
                payload["document_governance_projection"] = "document-governance.md"
                for document in documents:
                    document["snapshot_path"] = f"documents/{Path(document['path']).name}"
        return payload

    def freeze_workstream(self, workstream: str, reviewer: str, reason: str) -> dict[str, Any]:
        name = self.normalize_workstream(workstream)
        if name == "VDOC":
            registered_documents = self.documents()
            if registered_documents:
                self.sync_documents()
                unreviewed = [row["path"] for row in self.documents() if row["status"] != Validity.VALID.value]
                if unreviewed:
                    raise HarnessError("VDOC 存在尚未批准或内容已变化的验证文档: " + ", ".join(unreviewed))
        closure = self.evaluate_closure(name, persist=False)
        plan = self.workstream(name)
        if plan["lifecycle"] not in {"ACTIVE", "SATISFIED"}:
            raise HarnessError("必须先由负责人批准当前验证工作流方案，才能保存该工作流基线")
        if closure["actions"]:
            raise HarnessError("Workstream desired state 尚未满足；先处理 closure actions")
        payload = self._baseline_payload(name, reviewer, reason)
        canonical = json_text(payload).encode("utf-8")
        digest = hashlib.sha256(canonical).hexdigest()
        baseline_id = f"{name.lower()}-r{plan['revision']}-{digest[:12]}"
        relative = Path("baselines") / name.lower() / baseline_id / "manifest.json"
        target = self.state / relative
        if target.exists():
            raise HarnessError(f"不可变 baseline 已存在: {relative}")
        if name == "VDOC" and payload.get("documents"):
            for document in payload.get("documents", []):
                source = self.root / document["path"]
                if self._digest(source) != document["digest"]:
                    raise HarnessError(f"验证文档在保存基线期间发生变化: {document['path']}")
            atomic_text(target.parent / payload["document_governance_projection"], self.render_document_state())
            for document in payload.get("documents", []):
                source = self.root / document["path"]
                snapshot = target.parent / document["snapshot_path"]
                atomic_text(snapshot, source.read_text(encoding="utf-8"))
        atomic_json(target, payload)
        with self.connect() as connection:
            connection.execute("UPDATE workstreams SET lifecycle='BASELINED',updated_at=? WHERE name=?", (now(), name))
            connection.execute("INSERT INTO reviews VALUES(?,?,?,?,?,?,?)",
                               (uuid.uuid4().hex, name, plan["revision"], "FREEZE", reviewer, reason, now()))
            connection.execute("INSERT INTO baselines VALUES(?,?,?,?,?,?,?,?,?)",
                               (baseline_id, name, plan["revision"], "WORKSTREAM", digest, relative.as_posix(), reviewer, reason, now()))
        self.write_workstream_projection(name)
        return {"workstream": name, "lifecycle": "BASELINED", "revision": plan["revision"],
                "baseline_id": baseline_id, "digest": digest, "path": relative.as_posix()}

    def freeze_final(self, reviewer: str, reason: str) -> dict[str, Any]:
        plans = self.workstreams()
        present = {item["workstream"] for item in plans}
        missing = sorted(set(WORKSTREAM_TEMPLATES) - present)
        not_ready = [item["workstream"] for item in plans if item["lifecycle"] != "BASELINED"]
        audit = self.audit()
        if missing or not_ready or audit["open_findings"] or audit["status"] == "FAIL":
            raise HarnessError(f"final freeze 未满足: missing={missing}, not_baselined={not_ready}, audit={audit}")
        with self.read_connect() as connection:
            recorded_baselines = [dict(row) for row in connection.execute("SELECT * FROM baselines ORDER BY created_at")]
        payload = {
            "schema": "FinalBaseline/1", "created_at": now(), "project_revision": git_revision(self.root),
            "reviewer": reviewer, "reason": reason, "project": json.loads((self.state / "project.json").read_text(encoding="utf-8")),
            "workstreams": plans,
            "baselines": recorded_baselines,
        }
        digest = hashlib.sha256(json_text(payload).encode("utf-8")).hexdigest()
        baseline_id = f"final-{digest[:12]}"
        relative = Path("baselines") / "final" / baseline_id / "manifest.json"
        target = self.state / relative
        if target.exists():
            raise HarnessError(f"不可变 final baseline 已存在: {relative}")
        atomic_json(target, payload)
        with self.connect() as connection:
            connection.execute("INSERT INTO baselines VALUES(?,?,?,?,?,?,?,?,?)",
                               (baseline_id, None, None, "FINAL", digest, relative.as_posix(), reviewer, reason, now()))
        return {"baseline_id": baseline_id, "kind": "FINAL", "digest": digest, "path": relative.as_posix()}

    def add_node(self, node_id: str, node_type: str, title: str, workstream: str | None = None,
                 status: Validity = Validity.UNKNOWN) -> dict[str, Any]:
        self.require()
        if not node_id.strip() or any(character.isspace() for character in node_id):
            raise HarnessError("node ID 不能为空或包含空白")
        if status in {Validity.VALID, Validity.PROVISIONAL, Validity.WAIVED}:
            raise HarnessError("新节点不能直接声明 VALID/PROVISIONAL/WAIVED；必须提供对应验证证据或负责人评审记录")
        name = self.normalize_workstream(workstream) if workstream else None
        with self.connect() as connection:
            if connection.execute("SELECT 1 FROM nodes WHERE id=?", (node_id,)).fetchone() is not None:
                raise HarnessError(f"node 已存在: {node_id}")
            self.upsert_node(connection, node_id, node_type, title, status, name)
        self.write_model_projection()
        return {"id": node_id, "type": node_type, "title": title, "workstream": name, "status": status.value,
                "auto_closure": self.reconcile()}

    def add_edge(self, source: str, target: str, relation: str, origin: str, confidence: float) -> dict[str, Any]:
        self.require()
        if not 0 <= confidence <= 1:
            raise HarnessError("confidence 必须在 0 到 1 之间")
        if relation.upper() == "DEPENDS_ON":
            raise HarnessError("DEPENDS_ON 必须使用 record dependency，以执行方向与循环检查")
        with self.connect() as connection:
            known = {row["id"] for row in connection.execute("SELECT id FROM nodes WHERE id IN (?,?)", (source, target))}
            missing = [item for item in (source, target) if item not in known]
            if missing:
                raise HarnessError("未知 node: " + ", ".join(missing))
            connection.execute("INSERT OR REPLACE INTO edges VALUES(?,?,?,?,?,?,?)",
                               (source, target, relation.upper(), origin, confidence, "{}", now()))
        self.write_model_projection()
        return {"source": source, "target": target, "relation": relation.upper(), "origin": origin,
                "confidence": confidence, "auto_closure": self.reconcile()}

    def add_dependency(self, subject: str, prerequisite: str) -> dict[str, Any]:
        """Record a node-scoped dependency as dependent -> prerequisite."""
        self.require()
        if subject == prerequisite:
            raise HarnessError("node 不能依赖自身")
        with self.connect() as connection:
            known = {row["id"] for row in connection.execute(
                "SELECT id FROM nodes WHERE id IN (?,?)", (subject, prerequisite)
            )}
            missing = [item for item in (subject, prerequisite) if item not in known]
            if missing:
                raise HarnessError("未知 node: " + ", ".join(missing))
            queue = [prerequisite]
            visited: set[str] = set()
            while queue:
                current = queue.pop(0)
                if current == subject:
                    raise HarnessError(f"DEPENDS_ON 会形成循环依赖: {subject} -> {prerequisite}")
                if current in visited:
                    continue
                visited.add(current)
                queue.extend(row["target"] for row in connection.execute(
                    "SELECT target FROM edges WHERE source=? AND relation='DEPENDS_ON'", (current,)
                ))
            connection.execute("INSERT OR REPLACE INTO edges VALUES(?,?,?,?,?,?,?)",
                               (subject, prerequisite, "DEPENDS_ON", "explicit", 1.0, "{}", now()))
        self.write_model_projection()
        return {"subject": subject, "requires": prerequisite, "relation": "DEPENDS_ON",
                "semantics": "dependent-to-prerequisite", "auto_closure": self.reconcile()}

    def set_status(self, node_id: str, status: Validity) -> dict[str, Any]:
        self.require()
        if status in {Validity.VALID, Validity.PROVISIONAL, Validity.WAIVED}:
            raise HarnessError("VALID（已通过）必须由验证证据建立；PROVISIONAL/WAIVED 必须由负责人评审建立")
        with self.connect() as connection:
            node = connection.execute(
                "SELECT data_json FROM nodes WHERE id=?", (node_id,),
            ).fetchone()
            if node is None:
                raise HarnessError(f"未知 node: {node_id}")
            node_data = json.loads(node["data_json"])
            changed = connection.execute("UPDATE nodes SET status=?,updated_at=? WHERE id=?", (status.value, now(), node_id))
            if changed.rowcount != 1:
                raise HarnessError(f"未知 node: {node_id}")
        delivery_parent = (
            node_data.get("parent_id")
            if node_data.get("role") == "document-semantic-unit"
            and node_data.get("parent_role") == "document-deliverable"
            else None
        )
        if delivery_parent:
            self._refresh_vdoc_delivery_acceptance(str(delivery_parent))
        self.write_model_projection()
        return {"id": node_id, "status": status.value, "auto_closure": self.reconcile()}

    def waive_node(self, node_id: str, reviewer: str, reason: str) -> dict[str, Any]:
        self.require()
        with self.connect() as connection:
            node = connection.execute(
                "SELECT workstream,data_json FROM nodes WHERE id=?", (node_id,),
            ).fetchone()
            if node is None:
                raise HarnessError(f"未知 node: {node_id}")
            if node["workstream"] is None:
                raise HarnessError("waiver 只允许用于已规划 Workstream 中的 node")
            name = node["workstream"]
            node_data = json.loads(node["data_json"])
            plan = connection.execute("SELECT revision FROM workstreams WHERE name=?", (name,)).fetchone()
            review_id = uuid.uuid4().hex
            connection.execute("INSERT INTO reviews VALUES(?,?,?,?,?,?,?)",
                               (review_id, name, int(plan["revision"]), "WAIVE", reviewer, f"{node_id}: {reason}", now()))
            connection.execute("UPDATE nodes SET status=?,updated_at=? WHERE id=?", (Validity.WAIVED.value, now(), node_id))
            connection.execute("UPDATE findings SET status='WAIVED' WHERE subject=? AND status='OPEN'", (node_id,))
        delivery_parent = (
            node_data.get("parent_id")
            if node_data.get("role") == "document-semantic-unit"
            and node_data.get("parent_role") == "document-deliverable"
            else None
        )
        if delivery_parent:
            self._refresh_vdoc_delivery_acceptance(str(delivery_parent))
        self.write_model_projection()
        self.write_workstream_projection(name)
        return {"review_id": review_id, "id": node_id, "status": Validity.WAIVED.value,
                "reviewer": reviewer, "reason": reason, "auto_closure": self.reconcile()}

    def add_evidence(
        self, subject: str, kind: str, source: str, verdict: str,
        data: dict[str, Any] | None = None, contract_validated: bool = False,
    ) -> dict[str, Any]:
        self.require()
        source_path = Path(source)
        if not source_path.is_absolute():
            source_path = self.root / source_path
        if not source_path.is_file():
            raise HarnessError(f"evidence source 不存在或不是文件: {source}")
        digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
        evidence_id = f"evidence:{uuid.uuid4().hex[:12]}"
        with self.connect() as connection:
            subject_row = connection.execute(
                "SELECT type,workstream,data_json FROM nodes WHERE id=?", (subject,)
            ).fetchone()
            if subject_row is None:
                raise HarnessError(f"未知 evidence subject: {subject}")
            subject_data = json.loads(subject_row["data_json"])
            protected = (
                subject_row["workstream"] == "VSTIM"
                and (subject_row["type"] in {"desired-state", "stimulus-scenario"}
                     or subject_data.get("key") in {"reachability-evidence", "determinism-evidence"})
            ) or (
                subject_row["workstream"] in CLAIMS and subject_row["type"] == "desired-state"
            )
            if protected and not contract_validated:
                raise HarnessError("该 Workstream desired node 必须使用 evidence 命令登记专用结构化证据")
            relative = relative_path(self.root, source_path)
            connection.execute("INSERT INTO evidence VALUES(?,?,?,?,?,?,?,?)",
                               (evidence_id, subject, kind, relative, digest, verdict.upper(), json_text(data or {}), now()))
            file_node = f"file:{relative}"
            if connection.execute("SELECT 1 FROM nodes WHERE id=?", (file_node,)).fetchone() is None:
                self.upsert_node(connection, file_node, "artifact", relative, Validity.VALID,
                                 data={"path": relative, "kind": "evidence-source", "digest": digest})
            self.upsert_node(connection, evidence_id, "evidence", relative,
                             Validity.VALID if verdict == "pass" else Validity.INVALID, data=data)
            connection.execute("INSERT OR REPLACE INTO edges VALUES(?,?,?,?,?,?,?)",
                               (subject, evidence_id, "VALIDATED_BY", "runtime", 1.0, "{}", now()))
            if file_node != subject:
                connection.execute("INSERT OR REPLACE INTO edges VALUES(?,?,?,?,?,?,?)",
                                   (file_node, subject, "EVIDENCES", "runtime", 1.0,
                                    json_text({"evidence_id": evidence_id}), now()))
            for artifact in (data or {}).get("artifact_sources", []):
                artifact_node = f"file:{artifact['path']}"
                if connection.execute("SELECT 1 FROM nodes WHERE id=?", (artifact_node,)).fetchone() is None:
                    self.upsert_node(connection, artifact_node, "artifact", artifact["path"], Validity.VALID,
                                     data={"path": artifact["path"],
                                           "kind": artifact.get("kind", "native-evidence"),
                                           "analyzed_by": artifact.get("analyzed_by", []),
                                           "digest": artifact["sha256"]})
                if artifact_node != subject:
                    connection.execute("INSERT OR REPLACE INTO edges VALUES(?,?,?,?,?,?,?)",
                                       (artifact_node, subject, "EVIDENCES", "runtime", 1.0,
                                        json_text({"evidence_id": evidence_id}), now()))
            connection.execute("UPDATE nodes SET status=?,updated_at=? WHERE id=?",
                               (Validity.VALID.value if verdict == "pass" else Validity.INVALID.value, now(), subject))
            if verdict == "pass":
                connection.execute("UPDATE findings SET status='RESOLVED' WHERE subject=? AND status='OPEN'", (subject,))
        delivery_parent = (
            subject_data.get("parent_id")
            if subject_data.get("role") == "document-semantic-unit"
            and subject_data.get("parent_role") == "document-deliverable"
            else None
        )
        if delivery_parent:
            self._refresh_vdoc_delivery_acceptance(str(delivery_parent))
        self.write_model_projection()
        return {"id": evidence_id, "subject": subject, "kind": kind, "source": relative,
                "digest": digest, "verdict": verdict.upper(), "data": data or {},
                "auto_closure": self.reconcile()}

    def _verify_analysis_receipt(self, path: Path, artifact: dict[str, Any]) -> None:
        """Reject analyzer labels that are not backed by an adapter PASS receipt."""
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HarnessError(f"analysis-report 不是有效 JSON: {artifact['path']}: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("adapter_schema_version") != 1:
            raise HarnessError(f"analysis-report 缺少 adapter_schema_version=1: {artifact['path']}")
        if payload.get("state") != "PASS" or payload.get("blockers") != []:
            raise HarnessError(f"analysis-report 不是无 blocker 的 PASS 回执: {artifact['path']}")
        request_digest = payload.get("request_sha256")
        if not isinstance(request_digest, str) or len(request_digest) != 64 or any(
            character not in "0123456789abcdef" for character in request_digest
        ):
            raise HarnessError(f"analysis-report request_sha256 无效: {artifact['path']}")
        if not isinstance(payload.get("operation"), str) or not payload["operation"].strip():
            raise HarnessError(f"analysis-report 缺少 operation: {artifact['path']}")
        identity = payload.get("tool_identity")
        if not isinstance(identity, dict) or identity.get("state") != "PASS":
            raise HarnessError(f"analysis-report tool_identity 不是 PASS: {artifact['path']}")
        analyzers = set(artifact.get("analyzed_by", []))
        if "xverif" in analyzers:
            if not isinstance(payload.get("tool"), str) or not payload["tool"].strip():
                raise HarnessError(f"xverif analysis-report 缺少 tool: {artifact['path']}")
        elif "wavepeek" in analyzers:
            if not identity.get("binary_sha256"):
                raise HarnessError(f"WavePeek analysis-report 缺少 binary_sha256: {artifact['path']}")
        else:
            raise HarnessError(f"analysis-report 必须由 xverif 或 wavepeek 生成: {artifact['path']}")

    def _verify_evidence_artifacts(self, artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        verified: list[dict[str, Any]] = []
        for artifact in artifacts:
            relative = relative_path(self.root, artifact["path"])
            path = self.root / relative
            if not path.is_file():
                raise HarnessError(f"native evidence artifact 不存在或不是文件: {artifact['path']}")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != artifact["sha256"]:
                raise HarnessError(f"native evidence artifact digest 不匹配: {artifact['path']}")
            normalized = {**artifact, "path": relative, "sha256": digest}
            if normalized.get("kind") == "analysis-report":
                self._verify_analysis_receipt(path, normalized)
            verified.append(normalized)
        return verified

    def _apply_revision_check(self, summary: dict[str, Any]) -> None:
        manifest = json.loads((self.state / "project.json").read_text(encoding="utf-8"))
        expected = manifest.get("baseline_revision")
        if expected and summary.get("revision") != expected:
            summary.setdefault("blockers", []).append(
                f"evidence revision={summary.get('revision')}，project revision={expected}"
            )
            if "ready" in summary:
                summary["ready"] = False
            if "reachability_ready" in summary:
                summary["reachability_ready"] = False
                summary["determinism_ready"] = False

    def _evidence_dependency_blockers(self, subject: str) -> list[str]:
        blockers: list[str] = []
        with self.read_connect() as connection:
            row = connection.execute("SELECT workstream,data_json FROM nodes WHERE id=?", (subject,)).fetchone()
            if row is None:
                return [f"未知 evidence subject: {subject}"]
            data = json.loads(row["data_json"])
            current: dict[tuple[str, str], str] = {}
            for workstream_row in connection.execute("SELECT name,desired_json FROM workstreams"):
                for item in json.loads(workstream_row["desired_json"]):
                    current[(workstream_row["name"], item["key"])] = item["id"]
            expected = [
                prerequisite for dependent, prerequisite in DEFAULT_DEPENDENCIES
                if dependent == (row["workstream"], data.get("key"))
            ]
            blockers.extend(
                f"prerequisite 尚未规划: {workstream}/{key}"
                for workstream, key in expected if (workstream, key) not in current
            )
            for dependency in connection.execute(
                """SELECT nodes.id,nodes.status FROM edges JOIN nodes ON nodes.id=edges.target
                   WHERE edges.source=? AND edges.relation='DEPENDS_ON'""", (subject,)
            ):
                if dependency["status"] not in {
                    Validity.VALID.value, Validity.PROVISIONAL.value, Validity.WAIVED.value,
                }:
                    blockers.append(f"prerequisite {dependency['id']} 当前为 {dependency['status']}")
        return blockers

    @staticmethod
    def _latest_pass_validation(connection: sqlite3.Connection, subject: str) -> dict[str, Any] | None:
        row = connection.execute(
            "SELECT data_json FROM evidence WHERE subject=? AND verdict='PASS' ORDER BY created_at DESC LIMIT 1",
            (subject,),
        ).fetchone()
        if row is None:
            return None
        data = json.loads(row["data_json"])
        validation = data.get("validation")
        return validation if isinstance(validation, dict) else None

    @staticmethod
    def _current_desired_nodes(connection: sqlite3.Connection) -> dict[tuple[str, str], dict[str, Any]]:
        current: dict[tuple[str, str], dict[str, Any]] = {}
        for workstream_row in connection.execute("SELECT name,desired_json FROM workstreams"):
            for item in json.loads(workstream_row["desired_json"]):
                current[(workstream_row["name"], item["key"])] = item
        return current

    def _cross_evidence_blockers(
        self, connection: sqlite3.Connection, workstream: str, claim: str,
        summary: dict[str, Any], current: dict[tuple[str, str], dict[str, Any]],
    ) -> list[str]:
        """Validate relationships that cannot be proven inside one evidence file."""
        blockers: list[str] = []

        def facts(name: str, key: str) -> dict[str, Any] | None:
            item = current.get((name, key))
            if item is None:
                return None
            validation = self._latest_pass_validation(connection, item["id"])
            return validation.get("facts") if validation else None

        if workstream == "VENV" and claim == "environment-smoke-evidence":
            build = facts("VENV", "build-ready")
            if build is not None and summary["facts"].get("environment_digest") != build.get("environment_digest"):
                blockers.append(
                    "environment smoke 的 environment digest 与当前 build-ready 不一致"
                )

        if workstream == "VSTIM" and claim == "corner-scenarios":
            implementation = facts("VSTIM", "stimulus-implementation")
            if implementation is not None:
                components = {item["id"] for item in implementation.get("components", [])}
                missing = sorted({
                    item["generator"] for item in summary["facts"].get("mappings", [])
                    if item["generator"] not in components
                })
                if missing:
                    blockers.append("corner scenario 引用了未登记 generator: " + ", ".join(missing))

        if workstream == "VCHK" and claim in {"reference-model-evidence", "scoreboard-evidence"}:
            capability_key = claim.removesuffix("-evidence")
            capability = facts("VCHK", capability_key)
            if capability is not None and summary["facts"].get("implementation_digest") != capability.get("implementation_digest"):
                blockers.append(f"{claim} 的 implementation digest 与当前 {capability_key} capability 不一致")
        if workstream == "VCHK" and claim == "assertion-evidence":
            capability = facts("VCHK", "assertions")
            if capability is not None and summary["facts"].get("assertions") != capability.get("planned"):
                blockers.append("assertion evidence 数量与当前 assertion capability planned 数量不一致")

        if workstream == "VCASE" and claim == "case-implementation":
            matrix = facts("VCASE", "case-matrix")
            if matrix is not None:
                required_cases = {
                    case for mapping in matrix.get("mappings", []) for case in mapping.get("cases", [])
                }
                implemented = set(summary["facts"].get("cases", []))
                missing = sorted(required_cases - implemented)
                if missing:
                    blockers.append("case matrix 中的 testcase 尚未实现: " + ", ".join(missing))
        if workstream == "VCASE" and claim == "targeted-evidence":
            implementation = facts("VCASE", "case-implementation")
            if implementation is not None:
                missing = sorted(
                    set(implementation.get("cases", [])) - set(summary["facts"].get("executed_cases", []))
                )
                if missing:
                    blockers.append("尚无 targeted PASS 的 implemented testcase: " + ", ".join(missing))

        if workstream == "VREG" and claim == "triage-evidence":
            execution = facts("VREG", "execution-evidence")
            if execution is not None:
                expected = {(item["test"], item["seed"]) for item in execution.get("failed_runs", [])}
                observed = {
                    (item["test"], item["original_seed"])
                    for item in summary["facts"].get("failures", [])
                }
                missing = sorted(expected - observed)
                extra = sorted(observed - expected)
                if missing:
                    blockers.append("regression failure 尚未 triage: " + ", ".join(f"{test}/{seed}" for test, seed in missing))
                if extra:
                    blockers.append("triage 含当前 execution 不存在的 failure: " + ", ".join(f"{test}/{seed}" for test, seed in extra))
            for item in summary["facts"].get("failures", []):
                if item.get("disposition") != "accepted-known-fail":
                    continue
                waiver = connection.execute(
                    "SELECT 1 FROM reviews WHERE id=? AND verdict='WAIVE'", (item.get("waiver_ref"),)
                ).fetchone()
                if waiver is None:
                    blockers.append(f"{item['test']} 的 waiver_ref 不是 SQLite 中已登记的负责人例外评审")
        return blockers

    def _derive_fresh_evidence(
        self, connection: sqlite3.Connection, subject: str, summary: dict[str, Any],
        current: dict[tuple[str, str], dict[str, Any]],
    ) -> list[str]:
        blockers: list[str] = []
        manifest = json.loads((self.state / "project.json").read_text(encoding="utf-8"))
        expected_revision = manifest.get("baseline_revision")
        if summary["facts"].get("snapshot_revision") != summary.get("revision"):
            blockers.append("fresh-evidence snapshot_revision 必须等于报告 revision")
        derived: list[dict[str, str]] = []
        for item in sorted(current.values(), key=lambda value: value["id"]):
            if item["id"] == subject or item.get("role") != "closure-evidence" or not item.get("required", True):
                continue
            node = connection.execute("SELECT status FROM nodes WHERE id=?", (item["id"],)).fetchone()
            status = node["status"] if node else Validity.UNKNOWN.value
            if status == Validity.WAIVED.value:
                derived.append({"id": item["id"], "status": Validity.WAIVED.value})
                continue
            if status != Validity.VALID.value:
                blockers.append(f"required closure evidence node {item['id']} 当前为 {status}")
                continue
            evidence = connection.execute(
                "SELECT digest,data_json FROM evidence WHERE subject=? AND verdict='PASS' ORDER BY created_at DESC LIMIT 1",
                (item["id"],),
            ).fetchone()
            if evidence is None:
                blockers.append(f"required closure evidence node {item['id']} 没有 PASS evidence")
                continue
            validation = json.loads(evidence["data_json"]).get("validation", {})
            if expected_revision and validation.get("revision") != expected_revision:
                blockers.append(f"required closure evidence node {item['id']} 不是当前 project revision")
                continue
            derived.append({"id": item["id"], "status": Validity.VALID.value,
                            "evidence_digest": evidence["digest"]})
        summary["facts"]["required_nodes"] = derived
        return blockers

    def add_reachability_evidence(self, subject: str, source: str, claim: str | None = None) -> dict[str, Any]:
        self.require()
        source_path = resolved_path(self.root, source)
        if not source_path.is_file():
            raise HarnessError(f"reachability evidence source 不存在或不是文件: {source}")
        relative_path(self.root, source_path)
        with self.read_connect() as connection:
            row = connection.execute(
                "SELECT type,workstream,data_json FROM nodes WHERE id=?", (subject,)
            ).fetchone()
        if row is None:
            raise HarnessError(f"未知 evidence subject: {subject}")
        if row["workstream"] != "VSTIM":
            raise HarnessError("reachability evidence 只能绑定到 VSTIM node")
        node_data = json.loads(row["data_json"])
        inferred_by_contract = {
            "reachability-evidence": "reachability",
            "determinism-evidence": "determinism",
        }
        inferred = (
            inferred_by_contract.get(node_data.get("key"))
            or inferred_by_contract.get(node_data.get("evidence_claim"))
        )
        if inferred is None and node_data.get("key") in CLAIMS.get("VSTIM", {}):
            raise HarnessError(
                f"标准 VSTIM capability node {node_data.get('key')} 必须使用 StimulusCapabilityEvidence/1"
            )
        if inferred is not None and claim is not None and claim != inferred:
            raise HarnessError(
                f"标准 node {node_data.get('key')} 的 claim 固定为 {inferred}，不能改为 {claim}"
            )
        selected = inferred or claim
        if selected not in {"reachability", "determinism"}:
            raise HarnessError("无法从 node 推导 claim；请显式传 --claim reachability|determinism")
        try:
            summary = validate_reachability(source_path)
        except ReachabilityError as exc:
            raise HarnessError(str(exc)) from exc
        summary["artifacts"] = self._verify_evidence_artifacts(summary["artifacts"])
        self._apply_revision_check(summary)
        dependency_blockers = self._evidence_dependency_blockers(subject)
        with self.read_connect() as connection:
            current = self._current_desired_nodes(connection)
            corner = current.get(("VSTIM", "corner-scenarios"))
            corner_validation = (
                self._latest_pass_validation(connection, corner["id"]) if corner is not None else None
            )
            if corner_validation is not None:
                planned = set(corner_validation.get("facts", {}).get("required_scenarios", []))
                observed = set(summary.get("required_scenarios", []))
                missing = sorted(planned - observed)
                if missing:
                    dependency_blockers.append(
                        "reachability report 缺少当前 corner-scenarios required 项: " + ", ".join(missing)
                    )
        summary["blockers"] = [*summary.get("blockers", []), *dependency_blockers]
        if summary["blockers"]:
            summary["reachability_ready"] = False
            summary["determinism_ready"] = False
        ready_key = f"{selected}_ready"
        verdict = "pass" if summary[ready_key] else "fail"
        recorded = self.add_evidence(
            subject, f"stimulus-{selected}", str(source_path), verdict,
            data={"claim": selected, "validation": summary,
                  "artifact_sources": summary["artifacts"]}, contract_validated=True,
        )
        recorded["claim"] = selected
        recorded["validation"] = summary
        return recorded

    def add_workstream_evidence(self, subject: str, source: str, claim: str | None = None) -> dict[str, Any]:
        self.require()
        source_path = resolved_path(self.root, source)
        if not source_path.is_file():
            raise HarnessError(f"evidence source 不存在或不是文件: {source}")
        relative_path(self.root, source_path)
        with self.read_connect() as connection:
            row = connection.execute(
                "SELECT type,workstream,data_json FROM nodes WHERE id=?", (subject,)
            ).fetchone()
        if row is None:
            raise HarnessError(f"未知 evidence subject: {subject}")
        workstream = row["workstream"]
        node_data = json.loads(row["data_json"])
        if workstream == "VSTIM" and (
            node_data.get("key") in {"reachability-evidence", "determinism-evidence"}
            or claim in {"reachability", "determinism"}
        ):
            return self.add_reachability_evidence(subject, source, claim)
        if workstream not in CLAIMS:
            raise HarnessError("evidence 专用入口只适用于 VENV/VSTIM/VCHK/VCOV/VCASE/VREG；VDOC 使用 docs review")
        inferred = node_data.get("evidence_claim") or CLAIMS[workstream].get(node_data.get("key"))
        if inferred is not None and claim is not None and claim != inferred:
            raise HarnessError(
                f"标准 node {node_data.get('key')} 的 claim 固定为 {inferred}，不能改为 {claim}"
            )
        selected = inferred or claim
        if selected is None:
            supported = ", ".join(CLAIMS[workstream].values())
            raise HarnessError(f"无法从 node 推导 claim；请使用 --claim，{workstream} 支持: {supported}")
        try:
            summary = validate_workstream_evidence(source_path, workstream, selected)
        except EvidenceContractError as exc:
            raise HarnessError(str(exc)) from exc
        summary["artifacts"] = self._verify_evidence_artifacts(summary["artifacts"])
        self._apply_revision_check(summary)
        summary["blockers"].extend(self._evidence_dependency_blockers(subject))
        with self.read_connect() as connection:
            current = self._current_desired_nodes(connection)
            summary["blockers"].extend(
                self._cross_evidence_blockers(connection, workstream, selected, summary, current)
            )
            if workstream == "VREG" and selected == "fresh-evidence":
                summary["blockers"].extend(
                    self._derive_fresh_evidence(connection, subject, summary, current)
                )
        summary["ready"] = not summary["blockers"]
        verdict = "pass" if summary["ready"] else "fail"
        recorded = self.add_evidence(
            subject, f"{workstream.lower()}-{selected}", str(source_path), verdict,
            data={"claim": selected, "validation": summary,
                  "artifact_sources": summary["artifacts"]}, contract_validated=True,
        )
        recorded["claim"] = selected
        recorded["validation"] = summary
        return recorded

    @staticmethod
    def _impact_targets(connection: sqlite3.Connection, node_id: str) -> list[str]:
        """Return causal dependents; DEPENDS_ON is stored dependent -> prerequisite."""
        direct = [row["target"] for row in connection.execute(
            "SELECT target FROM edges WHERE source=? AND relation!='DEPENDS_ON' ORDER BY target", (node_id,)
        )]
        reverse_dependencies = [row["source"] for row in connection.execute(
            "SELECT source FROM edges WHERE target=? AND relation='DEPENDS_ON' ORDER BY source", (node_id,)
        )]
        return direct + reverse_dependencies

    def record_change(self, path: str, kind: str, revision: str | None = None) -> dict[str, Any]:
        self.require()
        relative = self._project_or_declared_input_path(path)
        subject = f"file:{relative}"
        event_id = f"event:{uuid.uuid4().hex[:12]}"
        initial = Validity.INVALID if kind == "delete" else Validity.STALE
        affected: list[str] = []
        with self.connect() as connection:
            if connection.execute("SELECT 1 FROM nodes WHERE id=?", (subject,)).fetchone() is None:
                self.upsert_node(connection, subject, "artifact", relative, initial)
            connection.execute("INSERT INTO events VALUES(?,?,?,?,?,?)",
                               (event_id, kind, subject, revision, json_text({"path": relative}), now()))
            queue = [subject]
            visited: set[str] = set()
            while queue:
                current = queue.pop(0)
                if current in visited:
                    continue
                visited.add(current)
                affected.append(current)
                queue.extend(self._impact_targets(connection, current))
            for index, node_id in enumerate(affected):
                status = initial if index == 0 else Validity.REVALIDATION_REQUIRED
                connection.execute("UPDATE nodes SET status=?,updated_at=? WHERE id=?", (status.value, now(), node_id))
                details = f"{relative} 的 {kind} 事件使该节点需要重新验证"
                duplicate = connection.execute(
                    "SELECT 1 FROM findings WHERE subject=? AND status='OPEN' AND details=?",
                    (node_id, details),
                ).fetchone()
                if duplicate is None:
                    connection.execute("INSERT INTO findings VALUES(?,?,?,?,?,?,?)",
                                       (f"finding:{uuid.uuid4().hex[:12]}", node_id,
                                        "HIGH" if index == 0 else "MEDIUM", "OPEN",
                                        event_id, details, now()))
            names = {row["workstream"] for row in connection.execute(
                "SELECT DISTINCT workstream FROM nodes WHERE id IN (%s) AND workstream IS NOT NULL" % ",".join("?" * len(affected)), affected
            )} if affected else set()
            for name in names:
                connection.execute("UPDATE workstreams SET lifecycle='PARTIALLY_STALE',updated_at=? WHERE name=? AND lifecycle IN ('ACTIVE','SATISFIED','BASELINED')",
                                   (now(), name))
        self.write_model_projection()
        for name in names:
            self.write_workstream_projection(name)
        return {"event_id": event_id, "kind": kind, "subject": subject, "revision": revision,
                "affected": affected, "auto_closure": self.reconcile()}

    def scan(self) -> dict[str, Any]:
        self.require()
        document_sync = self.sync_documents() if self.documents() else {"changed": [], "missing": []}
        missing: list[str] = []
        with self.connect() as connection:
            for row in connection.execute("SELECT id FROM nodes WHERE id LIKE 'file:%'"):
                relative = row["id"][5:]
                if relative != "." and not (self.root / relative).exists():
                    missing.append(row["id"])
                    connection.execute("UPDATE nodes SET status=?,updated_at=? WHERE id=?", (Validity.INVALID.value, now(), row["id"]))
            open_findings = connection.execute("SELECT COUNT(*) count FROM findings WHERE status='OPEN'").fetchone()["count"]
        self.write_model_projection()
        failed = bool(missing or document_sync["changed"] or open_findings)
        return {"missing_files": missing, "changed_documents": document_sync["changed"],
                "open_findings": open_findings, "status": "FAIL" if failed else "PASS",
                "auto_closure": self.reconcile()}

    def audit(self) -> dict[str, Any]:
        self.require()
        missing: list[str] = []
        changed_documents: list[str] = []
        registered_documents = self.documents()
        with self.read_connect() as connection:
            for row in connection.execute("SELECT id FROM nodes WHERE id LIKE 'file:%'"):
                relative = row["id"][5:]
                if relative != "." and not (self.root / relative).exists():
                    missing.append(row["id"])
            open_findings = connection.execute("SELECT COUNT(*) count FROM findings WHERE status='OPEN'").fetchone()["count"]
            for row in registered_documents:
                if row["content_changed"]:
                    changed_documents.append(row["path"])
        failed = bool(missing or changed_documents or open_findings)
        return {"missing_files": missing, "changed_documents": changed_documents,
                "open_findings": open_findings, "status": "FAIL" if failed else "PASS"}

    def _executable_exit_blockers(
        self, connection: sqlite3.Connection, workstream: str,
        current: dict[tuple[str, str], dict[str, Any]],
    ) -> list[str]:
        """Evaluate cross-document and cross-evidence exit predicates."""
        blockers: list[str] = []
        if workstream == "VDOC":
            unresolved = [dict(row) for row in connection.execute(
                """SELECT document_items.id,document_items.kind,document_items.status,documents.path
                   FROM document_items JOIN documents ON documents.id=document_items.document_id
                   WHERE document_items.kind IN ('human-decision','external-open-question')
                     AND document_items.status IN ('PENDING','ACTIVE')
                   ORDER BY document_items.id"""
            )]
            blockers.extend(
                f"未决 VDOC 治理事项 {item['id']} ({item['kind']}, {item['status']}, {item['path']})"
                for item in unresolved
            )
            return blockers

        reachability_claims = {
            "reachability-evidence": "reachability",
            "determinism-evidence": "determinism",
        }
        for (name, key), item in current.items():
            if name != workstream or not item.get("required", True):
                continue
            node = connection.execute("SELECT status FROM nodes WHERE id=?", (item["id"],)).fetchone()
            if node is None or node["status"] != Validity.VALID.value:
                continue
            contract_claim = item.get("evidence_claim")
            claim = (
                reachability_claims.get(key)
                or reachability_claims.get(contract_claim)
                or contract_claim
                or CLAIMS.get(workstream, {}).get(key)
            )
            if claim is None:
                continue
            validation = self._latest_pass_validation(connection, item["id"])
            if validation is None:
                blockers.append(f"标准 node {item['id']} 缺少专用 PASS evidence validation")
                continue
            if workstream == "VSTIM" and claim in {"reachability", "determinism"}:
                corner = current.get(("VSTIM", "corner-scenarios"))
                corner_validation = (
                    self._latest_pass_validation(connection, corner["id"]) if corner is not None else None
                )
                if corner_validation is not None:
                    planned = set(corner_validation.get("facts", {}).get("required_scenarios", []))
                    missing = sorted(planned - set(validation.get("required_scenarios", [])))
                    if missing:
                        blockers.append(
                            f"{key} 缺少当前 required scenario: " + ", ".join(missing)
                        )
                continue
            blockers.extend(
                self._cross_evidence_blockers(connection, workstream, claim, validation, current)
            )
            if workstream == "VREG" and claim == "fresh-evidence":
                blockers.extend(self._derive_fresh_evidence(connection, item["id"], validation, current))
        return blockers

    def evaluate_closure(self, workstream: str, persist: bool = True) -> dict[str, Any]:
        name = self.normalize_workstream(workstream)
        plan = self.workstream(name)
        actions: list[dict[str, Any]] = []
        vdoc_proposal_issues = (
            self._vdoc_plan_proposal_issues(plan["desired_state"])
            if name == "VDOC" and plan["lifecycle"] in {"REVIEW", "REVISE"}
            else []
        )
        vdoc_deliveries = (
            self._vdoc_delivery_desired(plan) if name == "VDOC" else []
        )
        vdoc_delivery_issues = (
            self._vdoc_delivery_proposal_issues(plan, vdoc_deliveries)
            if name == "VDOC"
            and plan["lifecycle"] in {"ACTIVE", "PARTIALLY_STALE", "SATISFIED"}
            and vdoc_deliveries
            else []
        )
        connector = self.connect if persist else self.read_connect
        with connector() as connection:
            current_nodes = self._current_desired_nodes(connection)
            current_desired = {key: item["id"] for key, item in current_nodes.items()}
            for desired in plan["desired_state"]:
                if name == "VDOC" and desired.get("role") == "document-catalog":
                    continue
                if (
                    name == "VDOC"
                    and desired.get("role") == "document-semantic-unit"
                    and plan["lifecycle"] in {"REVIEW", "REVISE"}
                ):
                    continue
                if (
                    name == "VDOC" and vdoc_proposal_issues
                    and desired.get("role") in PROJECT_NODE_ROLES["VDOC"]
                ):
                    continue
                row = connection.execute("SELECT status FROM nodes WHERE id=?", (desired["id"],)).fetchone()
                status = row["status"] if row else Validity.UNKNOWN.value
                dependencies = [dict(item) for item in connection.execute(
                    """SELECT nodes.id,nodes.status,nodes.workstream,nodes.title
                       FROM edges JOIN nodes ON nodes.id=edges.target
                       WHERE edges.source=? AND edges.relation='DEPENDS_ON'
                       ORDER BY nodes.id""", (desired["id"],)
                )]
                blockers = [item for item in dependencies if item["status"] not in {
                    Validity.VALID.value, Validity.PROVISIONAL.value, Validity.WAIVED.value,
                }]
                expected_dependencies = [
                    prerequisite for dependent, prerequisite in DEFAULT_DEPENDENCIES
                    if dependent == (name, desired["key"])
                ]
                missing_dependencies = [item for item in expected_dependencies if item not in current_desired]
                delivery_agent_check = None
                if name == "VDOC" and desired.get("role") == "document-deliverable":
                    delivery_agent_check = connection.execute(
                        """SELECT c.status,c.review_id FROM review_agent_checks c
                           JOIN document_delivery_reviews r ON r.id=c.review_id
                           WHERE r.node_id=? ORDER BY r.rowid DESC LIMIT 1""",
                        (desired["id"],),
                    ).fetchone()
                if desired.get("required", True) and missing_dependencies:
                    actions.append({
                        "kind": "PLAN_PREREQUISITE", "target": desired["id"], "priority": 3,
                        "executor": "reasoning", "suggested_mode": "plan",
                        "reason": "这项工作依赖的前置目标还没有纳入当前计划",
                        "blocked_by": [f"workstream:{ws}:desired:{key}" for ws, key in missing_dependencies],
                    })
                elif desired.get("required", True) and blockers:
                    actions.append({
                        "kind": "WAIT_FOR_DEPENDENCY", "target": desired["id"], "priority": 4,
                        "executor": "deterministic", "suggested_mode": "closure",
                        "reason": "请先完成下方列出的前置目标",
                        "blocked_by": [item["id"] for item in blockers],
                    })
                elif (
                    desired.get("required", True)
                    and delivery_agent_check is not None
                    and delivery_agent_check["status"] == "PENDING"
                ):
                    actions.append({
                        "kind": "CHECK_DOCUMENT_REVIEW",
                        "target": desired["id"],
                        "priority": 3,
                        "executor": "reasoning",
                        "suggested_mode": "review",
                        "reason": (
                            "负责人已提交正文验收结论；Main Agent 必须检查审批、"
                            "当前正文和依赖影响，并判断是否需要继续提问"
                        ),
                        "review_id": delivery_agent_check["review_id"],
                    })
                elif desired.get("required", True) and status not in {Validity.VALID.value, Validity.WAIVED.value}:
                    if status in {Validity.STALE.value, Validity.REVALIDATION_REQUIRED.value}:
                        kind, executor = "REVALIDATE", "deterministic"
                    elif status in {Validity.INVALID.value, Validity.BLOCKED.value}:
                        kind, executor = "REPAIR_OR_REPLAN", "reasoning"
                    else:
                        kind, executor = "SATISFY_DESIRED_STATE", "reasoning"
                    actions.append({"kind": kind, "target": desired["id"], "priority": 10, "executor": executor,
                                    "suggested_mode": desired.get("suggested_mode"),
                                    "reason": VALIDITY_DESCRIPTIONS.get(status, "这项工作尚未完成")})
            for index, blocker in enumerate(self._executable_exit_blockers(connection, name, current_nodes), 1):
                actions.append({
                    "kind": "EXIT_CRITERION_BLOCKED",
                    "target": f"workstream:{name}:exit:{index}",
                    "priority": 6,
                    "executor": "deterministic",
                    "suggested_mode": "closure",
                    "reason": blocker,
                })
            for row in connection.execute("SELECT subject,severity,details FROM findings WHERE status='OPEN' AND subject IN (SELECT id FROM nodes WHERE workstream=?)", (name,)):
                actions.append({"kind": "RESOLVE_FINDING", "target": row["subject"], "priority": 5,
                                "executor": "reasoning", "suggested_mode": "reason", "reason": row["details"]})
            if (
                name == "VDOC"
                and plan["lifecycle"] in {"ACTIVE", "PARTIALLY_STALE", "SATISFIED"}
            ):
                if not vdoc_deliveries:
                    actions.append({
                        "kind": "AUTHOR_DOCUMENT_CONTENT",
                        "target": "workstream:VDOC",
                        "priority": 2,
                        "executor": "reasoning",
                        "suggested_mode": "plan",
                        "reason": (
                            "文档撰写方案已批准；请 Agent 按已批准范围撰写正文，"
                            "执行 docs sync，然后单独登记可验收的 document-deliverable 节点"
                        ),
                    })
                elif vdoc_delivery_issues:
                    actions.append({
                        "kind": "REFINE_DOCUMENT_DELIVERIES",
                        "target": "workstream:VDOC",
                        "priority": 2,
                        "executor": "reasoning",
                        "suggested_mode": "plan",
                        "reason": (
                            "已批准方案的正文内容验收范围不完整："
                            + "；".join(vdoc_delivery_issues)
                        ),
                    })
            if name == "VDOC" and vdoc_proposal_issues:
                actions.append({
                    "kind": "REFINE_DESIRED_STATE", "target": "workstream:VDOC",
                    "priority": 1, "executor": "reasoning", "suggested_mode": "plan",
                    "reason": (
                        "当前 VDOC 文档撰写方案不能进入审批，请 Agent "
                        "只按 DUT、接口和验证目标提交新的 writing-plan revision："
                        + "；".join(vdoc_proposal_issues)
                    ),
                })
            if plan["lifecycle"] in {"REVIEW", "REVISE"}:
                if name == "VDOC":
                    vdoc_plan_nodes = self._vdoc_writing_plan_desired(plan)
                    if not vdoc_plan_nodes and not vdoc_proposal_issues:
                        actions.append({
                            "kind": "REFINE_DESIRED_STATE", "target": "workstream:VDOC",
                            "priority": 1, "executor": "reasoning", "suggested_mode": "plan",
                            "reason": (
                                "请先根据当前 DUT、规格、接口和验证目标形成项目级 VDOC 方案节点；"
                                "固定文档交付分类不作为文档撰写方案节点"
                            ),
                        })
                    for desired in ([] if vdoc_proposal_issues else vdoc_plan_nodes):
                        if not desired.get("required", True):
                            continue
                        review_state = self.node_plan_review_state(
                            desired["id"], plan, desired,
                        )
                        if review_state["status"] != "APPROVED":
                            actions.append({
                                "kind": "HUMAN_REVIEW", "target": desired["id"],
                                "priority": 1, "executor": "human", "suggested_mode": "plan",
                                "reason": "当前 DUT 的文档撰写方案节点等待负责人审批",
                            })
                else:
                    actions.append({"kind": "HUMAN_REVIEW", "target": f"workstream:{name}", "priority": 1,
                                    "executor": "human", "suggested_mode": "plan",
                                    "reason": "当前工作计划等待负责人评审"})
            actions.sort(key=lambda item: (item["priority"], item["target"], item["kind"]))
            unique_actions: list[dict[str, Any]] = []
            seen_action_ids: set[str] = set()
            for action in actions:
                stable = json_text({"workstream": name, **action})
                action["id"] = "action:" + hashlib.sha256(stable.encode("utf-8")).hexdigest()[:12]
                if action["id"] in seen_action_ids:
                    continue
                seen_action_ids.add(action["id"])
                unique_actions.append(action)
            actions = unique_actions
            lifecycle = plan["lifecycle"]
            if persist:
                connection.execute("DELETE FROM actions WHERE workstream=? AND status='OPEN'", (name,))
                for action in actions:
                    connection.execute("INSERT INTO actions VALUES(?,?,?,?,?,?,?,?,?,?)",
                                       (action["id"], name, action["kind"], action["target"], action["priority"], "OPEN",
                                        action["executor"], action["suggested_mode"], action["reason"], now()))
                if not actions and lifecycle in {"ACTIVE", "PARTIALLY_STALE"}:
                    lifecycle = "SATISFIED"
                    connection.execute("UPDATE workstreams SET lifecycle='SATISFIED',updated_at=? WHERE name=?", (now(), name))
                elif actions and name == "VDOC" and lifecycle == "SATISFIED":
                    lifecycle = "ACTIVE"
                    connection.execute(
                        "UPDATE workstreams SET lifecycle='ACTIVE',updated_at=? WHERE name='VDOC'",
                        (now(),),
                    )
        if persist:
            self.write_workstream_projection(name)
        return {"workstream": name, "ready": not actions, "lifecycle": lifecycle, "actions": actions}

    def reconcile(self) -> dict[str, Any]:
        closures = [self.evaluate_closure(item["workstream"]) for item in self.workstreams()]
        ranked = [
            {"workstream": closure["workstream"], **action}
            for closure in closures for action in closure["actions"]
        ]
        ranked.sort(key=lambda item: (item["priority"], item["workstream"], item["target"]))
        return {"workstreams": closures, "ranked_actions": ranked}

    def model(self, node_id: str | None = None) -> dict[str, Any]:
        self.require()
        with self.read_connect() as connection:
            suffix, params = ("", ()) if node_id is None else (" WHERE id=?", (node_id,))
            nodes = [dict(row) for row in connection.execute("SELECT id,type,title,workstream,status,updated_at FROM nodes" + suffix + " ORDER BY id", params)]
            if node_id is not None and not nodes:
                raise HarnessError(f"未知 node: {node_id}")
            if node_id is None:
                edges = [dict(row) for row in connection.execute("SELECT source,target,relation,origin,confidence FROM edges ORDER BY source,target,relation")]
                findings = [dict(row) for row in connection.execute("SELECT id,subject,severity,status,cause_event,details FROM findings ORDER BY created_at")]
                evidence = [dict(row) for row in connection.execute(
                    "SELECT id,subject,kind,source,digest,verdict,data_json,created_at FROM evidence ORDER BY created_at"
                )]
            else:
                edges = [dict(row) for row in connection.execute("SELECT source,target,relation,origin,confidence FROM edges WHERE source=? OR target=? ORDER BY source,target,relation", (node_id, node_id))]
                findings = [dict(row) for row in connection.execute("SELECT id,subject,severity,status,cause_event,details FROM findings WHERE subject=? ORDER BY created_at", (node_id,))]
                evidence = [dict(row) for row in connection.execute(
                    "SELECT id,subject,kind,source,digest,verdict,data_json,created_at FROM evidence WHERE subject=? ORDER BY created_at",
                    (node_id,),
                )]
        for item in evidence:
            item["data"] = json.loads(item.pop("data_json"))
        return {"schema_version": SCHEMA_VERSION, "nodes": nodes, "edges": edges, "findings": findings, "evidence": evidence}

    def trace(self, node_id: str) -> dict[str, Any]:
        model = self.model(node_id)
        return {"node": model["nodes"][0], "incoming": [e for e in model["edges"] if e["target"] == node_id],
                "outgoing": [e for e in model["edges"] if e["source"] == node_id],
                "findings": model["findings"], "evidence": model["evidence"]}

    def impact(self, node_id: str) -> dict[str, Any]:
        self.model(node_id)
        with self.read_connect() as connection:
            queue: list[tuple[str, int]] = [(node_id, 0)]
            visited: set[str] = set()
            affected: list[dict[str, Any]] = []
            while queue:
                current, depth = queue.pop(0)
                if current in visited:
                    continue
                visited.add(current)
                if current != node_id:
                    row = connection.execute("SELECT id,type,title,workstream,status FROM nodes WHERE id=?", (current,)).fetchone()
                    if row:
                        item = dict(row); item["depth"] = depth; affected.append(item)
                queue.extend((target, depth + 1) for target in self._impact_targets(connection, current))
        return {"source": node_id, "affected": affected}

    def status(self) -> dict[str, Any]:
        self.require()
        manifest = json.loads((self.state / "project.json").read_text(encoding="utf-8"))
        model = self.model()
        counts: dict[str, int] = {}
        for node in model["nodes"]:
            counts[node["status"]] = counts.get(node["status"], 0) + 1
        plans = self.workstreams()
        document_rows = self.documents()
        document_status: dict[str, int] = {}
        for document in document_rows:
            observed = document["effective_status"]
            document_status[observed] = document_status.get(observed, 0) + 1
        return {
            "project": manifest["project_name"], "baseline_revision": manifest.get("baseline_revision"),
            "runtime": manifest.get("runtime"), "lifecycle": "ACTIVE",
            "dut": manifest.get("dut", {}),
            "rtl_roots": manifest.get("rtl_roots", []),
            "docs_roots": manifest.get("docs_roots", []),
            "verif_root": manifest.get("verif_root"),
            "verification_inputs": (
                manifest.get("verification_inputs")
                if isinstance(manifest.get("verification_inputs"), dict) else {
                    "testbench_root": None, "reference_model": None, "scripts": [],
                }
            ),
            "workstreams": plans, "closures": [self.evaluate_closure(item["workstream"], persist=False) for item in plans],
            "node_status": counts, "open_findings": sum(item["status"] == "OPEN" for item in model["findings"]),
            "documents": {"count": len(document_rows), "status": document_status,
                          "content_changed": [row["path"] for row in document_rows if row["content_changed"]]},
        }

    def dashboard_snapshot(self) -> dict[str, Any]:
        """Return one coherent, Human-readable control-plane snapshot for the local dashboard."""
        self.require()
        # Adding dashboard tables is a backward-compatible schema extension for existing v1 projects.
        self.ensure_dashboard_schema()
        summary = self.status()
        model = self.model()
        agent_assignment_history = self.agent_assignments()
        activities = self.activities()
        human_actions = self.human_actions()
        agent_questions = self.agent_questions()
        agent_review_checks = self.review_agent_checks()
        documents = self.documents()
        documents_by_desired = {
            item["desired_id"]: item for item in documents if item.get("desired_id")
        }
        documents_by_key = {
            item["document_key"]: item for item in documents if item.get("document_key")
        }
        pending_document_items: list[dict[str, Any]] = []
        for document in documents:
            for item in document.get("governance_items", []):
                if (
                    item.get("kind") in {"human-decision", "external-open-question"}
                    and item.get("status") in {"PENDING", "ACTIVE"}
                ):
                    pending_document_items.append({
                        **item,
                        "document_id": document["id"],
                        "document_path": document["path"],
                        "desired_id": document.get("desired_id"),
                    })
        with self.read_connect() as connection:
            reviews = [dict(row) for row in connection.execute(
                "SELECT * FROM reviews ORDER BY created_at DESC"
            )]
            baselines = [dict(row) for row in connection.execute(
                "SELECT * FROM baselines ORDER BY created_at DESC"
            )]
            events = [dict(row) for row in connection.execute(
                "SELECT * FROM events ORDER BY created_at DESC LIMIT 200"
            )]
        for event in events:
            event["payload"] = json.loads(event.pop("payload_json"))

        nodes = {item["id"]: item for item in model["nodes"]}
        evidence_by_subject: dict[str, list[dict[str, Any]]] = {}
        for item in model["evidence"]:
            evidence_by_subject.setdefault(item["subject"], []).append(item)
        findings_by_subject: dict[str, list[dict[str, Any]]] = {}
        for item in model["findings"]:
            findings_by_subject.setdefault(item["subject"], []).append(item)
        activities_by_node: dict[str, list[dict[str, Any]]] = {}
        for item in activities:
            activities_by_node.setdefault(item["node_id"], []).append(item)
        incoming: dict[str, list[dict[str, Any]]] = {}
        outgoing: dict[str, list[dict[str, Any]]] = {}
        for item in model["edges"]:
            incoming.setdefault(item["target"], []).append(item)
            outgoing.setdefault(item["source"], []).append(item)
        closure_by_workstream = {item["workstream"]: item for item in summary["closures"]}

        workstream_views: list[dict[str, Any]] = []
        waiting_for_human: list[dict[str, Any]] = []
        def question_waiting_item(item: dict[str, Any]) -> dict[str, Any]:
            return {
                "id": item["id"],
                "source": "agent-question",
                "target": item["target"],
                "target_type": item["target_type"],
                "action": "AGENT_QUESTION",
                "status": item["status"],
                "reviewer": "待回答",
                "reason": item["prompt"],
                "created_at": item["created_at"],
                "question_id": item["id"],
                "options": item["options"],
                "recommended_option": item["recommended_option"],
                "context": item["context"],
                "asked_by": item["asked_by"],
                "blocking": item["blocking"],
            }

        current_desired_ids: set[str] = set()
        for plan in summary["workstreams"]:
            desired_nodes: list[dict[str, Any]] = []
            counts: dict[str, int] = {}
            required_total = 0
            satisfied = 0
            desired_ids = {item["id"] for item in plan["desired_state"]}
            vdoc_plan_ids = {
                item["id"] for item in plan["desired_state"]
                if plan["workstream"] == "VDOC"
                and item.get("role") == "document-writing-plan"
            }
            all_vdoc_delivery_ids = {
                item["id"] for item in plan["desired_state"]
                if plan["workstream"] == "VDOC"
                and item.get("role") == "document-deliverable"
            }
            vdoc_delivery_ids = (
                all_vdoc_delivery_ids
                if plan["workstream"] == "VDOC"
                and plan["lifecycle"] in {"ACTIVE", "PARTIALLY_STALE", "SATISFIED", "BASELINED"}
                else set()
            )
            implementation_ids = (
                vdoc_plan_ids | vdoc_delivery_ids if plan["workstream"] == "VDOC" else {
                    item["id"] for item in plan["desired_state"]
                    if item.get("definition_origin") != "template"
                }
            )
            workstream_closure = closure_by_workstream.get(plan["workstream"], {
                "workstream": plan["workstream"], "ready": False,
                "lifecycle": plan["lifecycle"], "actions": [],
            })
            current_template_titles = {
                key: title for key, title, _mode, _role
                in template_nodes(WORKSTREAM_TEMPLATES[plan["workstream"]])
            }
            current_desired_ids.update(desired_ids)
            for desired in plan["desired_state"]:
                if (
                    plan["workstream"] == "VDOC"
                    and desired.get("role") == "document-semantic-unit"
                ):
                    continue
                if (
                    plan["workstream"] == "VDOC"
                    and desired.get("role") == "document-deliverable"
                    and desired["id"] not in vdoc_delivery_ids
                ):
                    continue
                node = nodes.get(desired["id"], {
                    "id": desired["id"], "type": "desired-state", "title": desired["title"],
                    "workstream": plan["workstream"], "status": Validity.UNKNOWN.value,
                    "updated_at": plan["updated_at"],
                })
                status = node["status"]
                if desired["id"] in implementation_ids:
                    counts[status] = counts.get(status, 0) + 1
                if desired["id"] in implementation_ids and desired.get("required", True):
                    required_total += 1
                    if status in {Validity.VALID.value, Validity.WAIVED.value}:
                        satisfied += 1
                node_evidence = evidence_by_subject.get(desired["id"], [])
                latest_validation = (
                    node_evidence[-1].get("data", {}).get("validation", {})
                    if node_evidence else {}
                )
                display_definition = desired
                if (
                    desired.get("definition_origin") == "template"
                    and desired.get("key") in current_template_titles
                ):
                    display_title = current_template_titles[desired["key"]]
                    display_definition = {
                        **desired,
                        **desired_definition(
                            plan["workstream"], desired["key"], display_title,
                            desired.get("role", "capability"),
                            desired.get("evidence_contract") or {}, "template",
                        ),
                        "title": display_title,
                    }
                document_key = (
                    self._vdoc_document_key(plan, desired)
                    if plan["workstream"] == "VDOC" else None
                )
                mapped_document = (
                    documents_by_desired.get(desired["id"])
                    or documents_by_key.get(document_key)
                )
                delivery_review = (
                    self.document_delivery_review_state(desired["id"], plan, desired)
                    if desired["id"] in vdoc_delivery_ids else None
                )
                if delivery_review is not None:
                    status = (
                        Validity.VALID.value
                        if delivery_review["status"] == "APPROVED"
                        else Validity.PROVISIONAL.value
                        if delivery_review["status"] == "PROVISIONAL"
                        else Validity.REVIEW_REQUIRED.value
                    )
                desired_nodes.append({
                    **node,
                    "status": status,
                    "title": display_definition.get("title", node["title"]),
                    "key": desired.get("key"),
                    "role": desired.get("role", "capability"),
                    "required": desired.get("required", True),
                    "suggested_mode": desired.get("suggested_mode"),
                    "evidence_claim": desired.get("evidence_claim"),
                    "evidence_contract": desired.get("evidence_contract"),
                    "parent_key": desired.get("parent_key"),
                    "parent_id": desired.get("parent_id"),
                    "document_key": document_key,
                    "content_kind": desired.get("content_kind"),
                    "statement": display_definition.get("statement"),
                    "purpose": display_definition.get("purpose"),
                    "scope": display_definition.get("scope", []),
                    "acceptance_criteria": display_definition.get("acceptance_criteria", []),
                    "source_refs": display_definition.get("source_refs", []),
                    "work_content": display_definition.get("work_content", []),
                    "implementation_approach": display_definition.get("implementation_approach", []),
                    "deliverables": display_definition.get("deliverables", []),
                    "progress_measures": display_definition.get("progress_measures", []),
                    "progress_observation": latest_validation.get("facts", {}),
                    "quality_checks": display_definition.get("quality_checks", []),
                    "definition_origin": desired.get("definition_origin"),
                    "definition_status": desired.get("definition_status"),
                    "role_description": desired.get("role_description"),
                    "evidence": node_evidence,
                    "findings": findings_by_subject.get(desired["id"], []),
                    "activities": activities_by_node.get(desired["id"], []),
                    "human_actions": [
                        item for item in human_actions if item["target"] == desired["id"]
                    ],
                    "agent_questions": [
                        item for item in agent_questions if item["target"] == desired["id"]
                    ],
                    "agent_assignments": [
                        item for item in agent_assignment_history
                        if item["node_id"] == desired["id"]
                    ],
                    "incoming": incoming.get(desired["id"], []),
                    "outgoing": outgoing.get(desired["id"], []),
                    "document": mapped_document,
                    "plan_review": (
                        self.node_plan_review_state(desired["id"], plan, desired)
                        if desired["id"] in vdoc_plan_ids else None
                    ),
                    "delivery_review": delivery_review,
                    # This is the Engine's current, reproducible explanation for why the
                    # node is or is not closed.  It is deliberately separate from the raw
                    # status so a Human can review the reasoning rather than a badge.
                    "closure_assessment": self.node_closure_assessment(desired["id"]),
                    "next_actions": [
                        action for action in workstream_closure.get("actions", [])
                        if action.get("target") == desired["id"]
                    ],
                })
            workstream_human_actions = [item for item in human_actions if (
                item["target"] == plan["workstream"] or item["target"] in desired_ids
            )]
            explicit_waiting = [
                {**item, "source": "human-action"}
                for item in workstream_human_actions if item["status"] == "OPEN"
            ]
            workstream_agent_questions = [
                item for item in agent_questions
                if item["target"] == plan["workstream"] or item["target"] in desired_ids
            ]
            question_waiting = [
                question_waiting_item(item)
                for item in workstream_agent_questions
                if item["status"] == "OPEN" and item["blocking"]
            ]
            closure_waiting = [
                {
                    "id": item["id"],
                    "source": "closure",
                    "target": item["target"],
                    "target_type": "workstream" if item["target"] == f"workstream:{plan['workstream']}" else "node",
                    "action": item["kind"],
                    "status": "OPEN",
                    "reviewer": "待处理",
                    "reason": item["reason"],
                    "created_at": plan["updated_at"],
                }
                for item in closure_by_workstream.get(plan["workstream"], {}).get("actions", [])
                if item.get("executor") == "human"
            ]
            document_waiting = [
                {
                    "id": f"document-item:{item['document_id']}:{item['id']}",
                    "source": "document-item",
                    "target": item.get("desired_id") or item["document_id"],
                    "target_type": "document-item",
                    "action": {
                        "human-decision": "需要作出工程决定",
                        "external-open-question": "需要回答文档问题",
                        "provisional": "需要处理暂定事项",
                        "assumption": "需要确认待验证假设",
                    }.get(item["kind"], "需要处理文档事项"),
                    "status": "OPEN",
                    "reviewer": "待处理",
                    "reason": f"{item['title']}（{item['document_path']}，编号 {item['id']}）",
                    "created_at": item["created_at"],
                    "document_id": item["document_id"],
                    "document_path": item["document_path"],
                    "item_id": item["id"],
                    "item_kind": item["kind"],
                }
                for item in pending_document_items
                if plan["workstream"] == "VDOC"
            ]
            workstream_waiting = [
                *question_waiting, *closure_waiting, *document_waiting, *explicit_waiting,
            ]
            waiting_for_human.extend(workstream_waiting)
            workstream_views.append({
                "workstream": plan["workstream"],
                "display_name": plan["display_name"],
                "lifecycle": plan["lifecycle"],
                "revision": plan["revision"],
                "objective": plan["objective"],
                "exit_criteria": plan["exit_criteria"],
                "updated_at": plan["updated_at"],
                "progress": {
                    "required": required_total,
                    "satisfied": satisfied,
                    "remaining": max(required_total - satisfied, 0),
                    "counts": counts,
                },
                "nodes": desired_nodes,
                "plan_node_count": len(vdoc_plan_ids) if plan["workstream"] == "VDOC" else len(implementation_ids),
                "writing_plan_node_count": len(vdoc_plan_ids),
                "delivery_node_count": len(vdoc_delivery_ids),
                "catalog_node_count": len([
                    item for item in plan["desired_state"]
                    if item.get("role") == "document-catalog"
                ]),
                "closure": workstream_closure,
                "activities": [item for item in activities if item["node_id"] in desired_ids],
                "human_actions": workstream_human_actions,
                "agent_questions": workstream_agent_questions,
                # A closure review request is just as actionable as an explicit Human request.
                # Keep both in one derived list so the dashboard cannot report zero while a
                # Workstream is in REVIEW/REVISE and waiting for a Human decision.
                "waiting_for_human": workstream_waiting,
                "reviews": [item for item in reviews if item["workstream"] == plan["workstream"]],
            })

        current_node_status: dict[str, int] = {}
        for node_id in current_desired_ids:
            status = nodes.get(node_id, {}).get("status", Validity.UNKNOWN.value)
            current_node_status[status] = current_node_status.get(status, 0) + 1
        historical_desired_ids = {
            item["id"] for item in model["nodes"]
            if item["type"] == "desired-state" and item["id"] not in current_desired_ids
        }
        current_findings = [
            item for item in model["findings"]
            if item["subject"] not in historical_desired_ids
        ]
        project_questions = [
            item for item in agent_questions if item["target_type"] == "project"
        ]
        waiting_for_human.extend(
            question_waiting_item(item) for item in project_questions
            if item["status"] == "OPEN" and item["blocking"]
        )
        current_activities = [
            item for item in activities
            if item["node_id"] in current_desired_ids or item["node_id"] == PROJECT_TARGET
        ]
        current_human_actions = [item for item in human_actions if (
            item["target"] in current_desired_ids
            or item["target"] in {plan["workstream"] for plan in summary["workstreams"]}
        )]
        current_agent_questions = [item for item in agent_questions if (
            item["target"] in current_desired_ids
            or item["target"] in {plan["workstream"] for plan in summary["workstreams"]}
            or item["target_type"] == "project"
        )]
        current_agent_assignments = [
            item for item in agent_assignment_history
            if item["node_id"] in current_desired_ids
        ]
        current_agent_review_checks = [
            item for item in agent_review_checks if item["node_id"] in current_desired_ids
        ]
        pending_agent_review_checks = [
            item for item in current_agent_review_checks if item["status"] == "PENDING"
        ]

        # The project Agent is a persistent control-plane actor, not an Activity row.
        # Activities describe bounded work and may legitimately be empty while the
        # Agent is ready for its next instruction.
        active_agent_activities = [
            item for item in current_activities
            if item["status"] in {
                "PENDING", "RUNNING", "WAITING_FOR_HUMAN", "WAITING_FOR_PARENT",
            }
        ]
        open_agent_questions = [
            item for item in current_agent_questions if item["status"] == "OPEN"
        ]
        blocking_question_count = sum(
            bool(item["blocking"]) for item in open_agent_questions
        )
        pending_review_count = sum(
            item.get("source") == "closure" for item in waiting_for_human
        )
        pending_confirmation_count = sum(
            item.get("source") == "document-item" for item in waiting_for_human
        )
        waiting_activity_count = sum(
            item["status"] == "WAITING_FOR_HUMAN" for item in active_agent_activities
        )
        running_activity_count = sum(
            item["status"] == "RUNNING" for item in active_agent_activities
        )
        pending_activity_count = sum(
            item["status"] == "PENDING" for item in active_agent_activities
        )
        waiting_for_parent_count = sum(
            item["status"] == "WAITING_FOR_PARENT" for item in active_agent_activities
        )
        assignment_activity_ids = {
            item["activity_id"] for item in agent_assignment_history
        }
        current_main_activities = [
            item for item in current_activities
            if item["id"] not in assignment_activity_ids
        ]
        main_activity_history = [
            item for item in activities
            if item["id"] not in assignment_activity_ids
        ]
        latest_activity = (
            current_main_activities[0] if current_main_activities
            else main_activity_history[0] if main_activity_history else None
        )
        if blocking_question_count:
            project_agent_status = "WAITING_FOR_HUMAN"
            project_agent_message = (
                f"需要你回答 {blocking_question_count} 个问题；回答后 Agent 才会继续相关工作"
            )
        elif pending_agent_review_checks:
            project_agent_status = "RUNNING"
            project_agent_message = (
                f"Agent 正在检查 {len(pending_agent_review_checks)} 项已提交的文档验收结论，"
                "检查后自行判断是否需要你回答问题"
            )
        elif pending_review_count or pending_confirmation_count:
            pending_parts = []
            if pending_review_count:
                pending_parts.append(f"{pending_review_count} 项评审")
            if pending_confirmation_count:
                pending_parts.append(f"{pending_confirmation_count} 项文档确认")
            project_agent_status = "WAITING_FOR_HUMAN"
            project_agent_message = (
                f"需要你处理 {'、'.join(pending_parts)}；处理后 Agent 才会继续相关工作"
            )
        elif waiting_activity_count:
            project_agent_status = "WAITING_FOR_HUMAN"
            project_agent_message = (
                f"Agent 有 {waiting_activity_count} 项工作等待负责人处理；"
                "当前没有开放的 Agent 问题，请查看工作状态"
            )
        elif running_activity_count:
            project_agent_status = "RUNNING"
            project_agent_message = (
                f"Agent 正在处理 {running_activity_count} 项验证工作，当前无需你操作"
            )
        elif waiting_for_parent_count:
            project_agent_status = "RUNNING"
            project_agent_message = (
                f"有 {waiting_for_parent_count} 个 subagent 等待 Main Agent 协调；"
                "当前不需要负责人处理"
            )
        elif pending_activity_count:
            project_agent_status = "PENDING"
            project_agent_message = (
                f"有 {pending_activity_count} 项验证工作等待 Agent 开始处理，当前无需你操作"
            )
        elif latest_activity and latest_activity["status"] == "FAILED":
            project_agent_status = "FAILED"
            project_agent_message = (
                f"Agent 最近一项工作失败：{latest_activity['operation']}；请查看失败原因"
            )
        else:
            project_agent_status = "IDLE"
            project_agent_message = (
                "现在没有需要你回答的问题；Dashboard 也没有收到 Agent 正在处理验证工作的记录"
            )
            if latest_activity and latest_activity["status"] == "COMPLETED":
                project_agent_message = (
                    "现在没有需要你回答的问题；"
                    f"Agent 最近完成：{latest_activity['operation']}"
                )

        project_agent = {
            "id": PROJECT_AGENT_ID,
            "scope": "project",
            "label": "当前项目的 Agent",
            "runtime": summary["runtime"],
            "status": project_agent_status,
            "message": project_agent_message,
            "active_activity_count": len(active_agent_activities),
            "open_question_count": len(open_agent_questions),
            "pending_review_count": pending_review_count,
            "pending_confirmation_count": pending_confirmation_count,
            "pending_agent_review_check_count": len(pending_agent_review_checks),
            "latest_activity": latest_activity,
        }

        def subagent_view(item: dict[str, Any]) -> dict[str, Any]:
            activity = item.get("activity") or {}
            display_status = (
                activity.get("status", "RUNNING")
                if item["status"] == "ACTIVE" else item["status"]
            )
            return {
                "id": item["agent_id"],
                "assignment_id": item["id"],
                "parent_agent_id": item["parent_agent_id"],
                "runtime": item["runtime"],
                "runtime_ref": item["runtime_ref"],
                "role": item["role"],
                "status": display_status,
                "assignment_status": item["status"],
                "workstream": item["workstream"],
                "node_id": item["node_id"],
                "operation": activity.get("operation", ""),
                "message": activity.get("message") or item.get("summary", ""),
                "progress_current": activity.get("progress_current"),
                "progress_total": activity.get("progress_total"),
                "activity_id": item["activity_id"],
                "heartbeat_at": item["heartbeat_at"],
                "lease_expires_at": item["lease_expires_at"],
                "write_scope": item["write_scope"],
                "summary": item["summary"],
                "created_at": item["created_at"],
                "updated_at": item["updated_at"],
                "ended_at": item["ended_at"],
            }

        active_subagents = [
            subagent_view(item) for item in current_agent_assignments
            if item["status"] == "ACTIVE"
        ]
        recent_subagents = [
            subagent_view(item) for item in agent_assignment_history
            if item["status"] != "ACTIVE"
        ][:12]
        project_agent["active_subagent_count"] = len(active_subagents)
        project_agent["waiting_subagent_count"] = sum(
            item["status"] == "WAITING_FOR_PARENT" for item in active_subagents
        )
        agent_collaboration = {
            "schema": "AgentCollaboration/1",
            "interaction_owner": PROJECT_AGENT_ID,
            "coordinator": project_agent,
            "active_subagents": active_subagents,
            "recent_subagents": recent_subagents,
            "assignment_activity_ids": sorted(assignment_activity_ids),
        }

        payload: dict[str, Any] = {
            "schema": "VerificationDashboard/1",
            "project": {
                "name": summary["project"],
                "runtime": summary["runtime"],
                "lifecycle": summary["lifecycle"],
                "baseline_revision": summary["baseline_revision"],
                "root": str(self.root),
                "dut": summary["dut"],
                "rtl_roots": summary["rtl_roots"],
                "docs_roots": summary["docs_roots"],
                "verif_root": summary["verif_root"],
                "verification_inputs": summary["verification_inputs"],
            },
            "project_agent": project_agent,
            "agent_collaboration": agent_collaboration,
            # Dashboard totals describe the active desired-state revisions. The full model and
            # audit histories remain available below, but stale revisions must not look active.
            "node_status": current_node_status,
            "current_node_count": len(current_desired_ids),
            "open_findings": sum(item["status"] == "OPEN" for item in current_findings),
            "documents_summary": summary["documents"],
            "workstreams": workstream_views,
            "model": model,
            "documents": documents,
            "activities": current_activities,
            "activity_history": activities,
            "agent_assignments": current_agent_assignments,
            "agent_assignment_history": agent_assignment_history,
            "human_actions": current_human_actions,
            "human_action_history": human_actions,
            "agent_questions": current_agent_questions,
            "agent_question_history": agent_questions,
            "agent_review_checks": current_agent_review_checks,
            "waiting_for_human": waiting_for_human,
            "reviews": reviews,
            "baselines": baselines,
            "events": events,
        }
        payload["version"] = hashlib.sha256(json_text(payload).encode("utf-8")).hexdigest()[:16]
        payload["generated_at"] = now()
        return payload

    def write_model_projection(self) -> None:
        if not self.initialized:
            return
        model = self.model()
        lines = ["# Verification Knowledge Model", "", "> Verification Knowledge Model 生成的只读投影；SQLite 是机器事实源。", "", "## Nodes", ""]
        lines.extend(f"- `{item['id']}` · {item['type']} · **{item['status']}** · {item['title']}" for item in model["nodes"])
        if not model["nodes"]: lines.append("- 无")
        lines.extend(["", "## Relations", ""])
        lines.extend(f"- `{item['source']}` -[{item['relation']}]-> `{item['target']}` ({item['origin']}, {item['confidence']:.2f})" for item in model["edges"])
        if not model["edges"]: lines.append("- 无")
        lines.extend(["", "## Open Findings", ""])
        open_findings = [item for item in model["findings"] if item["status"] == "OPEN"]
        lines.extend(f"- **{item['severity']}** `{item['subject']}`：{item['details']}" for item in open_findings)
        if not open_findings: lines.append("- 无")
        (self.state / "model.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def write_workstream_projection(self, workstream: str) -> None:
        plan = self.workstream(workstream)
        directory = self.state / "workstreams" / plan["workstream"].lower()
        directory.mkdir(parents=True, exist_ok=True)
        atomic_json(directory / "desired-state.json", plan)
        lines = [f"# {plan['workstream']} · {plan['display_name']}", "",
                 "> Verification Planner 阅读投影；请通过结构化 CLI 记录修改。", "",
                 f"- 生命周期：**{plan['lifecycle']}**", f"- 修订：**{plan['revision']}**",
                 f"- 目标：{plan['objective']}", "", "## Current Verification Knowledge Model Context", "",
                 f"- Project: `{plan['planning_context']['project']}`",
                 f"- Model nodes: {plan['planning_context']['model_summary']['node_count']}",
                 f"- Open findings: {plan['planning_context']['model_summary']['open_findings']}",
                 "", "## Desired State", ""]
        for item in plan["desired_state"]:
            contract = item.get("evidence_contract") or {}
            claim = contract.get("claim") or item.get("evidence_claim") or "未指定"
            lines.extend([
                f"### `{item['key']}` · {item['title']}", "",
                f"- 角色：`{item.get('role', 'capability')}`",
                f"- 父节点：`{item.get('parent_key') or '无'}`",
                f"- 必需：`{item.get('required', True)}`",
                f"- 定义来源：`{item.get('definition_origin', 'unknown')}` / `{item.get('definition_status', 'unknown')}`",
                f"- Evidence claim：`{claim}`", "",
                f"**目标说明**：{item.get('statement') or '未登记'}", "",
                f"**目的**：{item.get('purpose') or '未登记'}", "",
                "**范围**", "",
            ])
            lines.extend(f"- {value}" for value in item.get("scope", []))
            if not item.get("scope"): lines.append("- 未登记")
            lines.extend(["", "**满足条件**", ""])
            lines.extend(f"- [ ] {value}" for value in item.get("acceptance_criteria", []))
            if not item.get("acceptance_criteria"): lines.append("- 未登记")
            lines.extend(["", "**来源引用**", ""])
            lines.extend(f"- `{value}`" for value in item.get("source_refs", []))
            if not item.get("source_refs"): lines.append("- 未登记")
            lines.extend(["", "**工作内容**", ""])
            lines.extend(f"- {value}" for value in item.get("work_content", []))
            if not item.get("work_content"): lines.append("- 未登记")
            lines.extend(["", "**实现方式**", ""])
            lines.extend(f"- {value}" for value in item.get("implementation_approach", []))
            if not item.get("implementation_approach"): lines.append("- 未登记")
            lines.extend(["", "**交付物**", ""])
            lines.extend(f"- {value}" for value in item.get("deliverables", []))
            if not item.get("deliverables"): lines.append("- 未登记")
            lines.extend(["", "**进度指标**", ""])
            lines.extend(
                f"- `{value['id']}`：{value['label']}；目标 `{value['target']} {value['unit']}`；来源 `{value['source']}`"
                for value in item.get("progress_measures", [])
            )
            if not item.get("progress_measures"): lines.append("- 未登记")
            lines.extend(["", "**质量检查**", ""])
            lines.extend(f"- {value}" for value in item.get("quality_checks", []))
            if not item.get("quality_checks"): lines.append("- 未登记")
            lines.extend(["", "**证据合同**", ""])
            for evidence_requirement in contract.get("requirements", []):
                alternatives = " 或 ".join(
                    f"`{choice['kind']}` / `{choice['analyzer']}`"
                    for choice in evidence_requirement.get("alternatives", [])
                )
                lines.append(f"  - {evidence_requirement['label']}：{alternatives}")
            for required in contract.get("required", []):
                lines.append(f"- {required}")
            lines.append("")
        documents = [item for item in plan["desired_state"] if item.get("document")]
        if documents:
            lines.extend(["", "## Document Deliverables", "",
                          "模板相对 Skill 根目录；由 Agent 在独立验证文档目录中对话填充，文件存在不代表目标通过。", "",
                          "| Desired ID | 文档 | 模板 | 维护工作域 |", "| --- | --- | --- | --- |"])
            lines.extend(f"| `{item['id']}` | `{item['document']['filename']}` | `{item['document']['template']}` | {', '.join(item['document']['maintained_by'])} |"
                         for item in documents)
        lines.extend(["", "## Exit Criteria", ""])
        lines.extend(f"- [ ] {item}" for item in plan["exit_criteria"])
        lines.extend(["", "## 负责人决定", ""])
        lines.extend(f"- {item}" for item in plan["decisions"])
        if not plan["decisions"]: lines.append("- 无")
        (directory / "plan.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
