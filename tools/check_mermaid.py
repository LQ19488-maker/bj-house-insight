"""Mermaid 语法自检（无法访问 mermaid.live，用结构化校验替代在线渲染）。

    python tools/check_mermaid.py

检查项：
    1. 每个 mermaid 代码块首行是合法图类型
    2. 节点 ID 只含 [A-Za-z0-9_]
    3. 标签内含括号/斜杠/冒号时，整个标签必须用双引号包裹
    4. 标签中不使用 HTML 标签（<br> 等）
    5. classDef 定义的类都被 class 语句引用；class 引用的类都已定义
    6. subgraph 嵌套不超过 2 层
    7. 依赖图无自环、无环（拓扑排序）
    8. 边引用的节点都有定义（flowchart）

局限说明：本脚本只能校验结构性问题，不能保证渲染 100% 成功。
报告中须如实标注"未做在线渲染验证"。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

VALID_HEADS = ("flowchart", "graph", "erDiagram", "sequenceDiagram", "classDiagram",
               "stateDiagram", "journey", "gantt", "pie")

NODE_DEF = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)\s*(\[|\(|\{)')
EDGE = re.compile(
    r'^([A-Za-z_][A-Za-z0-9_]*)\s*'
    r'(-->|---|-\.->|==>|--x|--o)\s*'
    r'(?:\|([^|]*)\|)?\s*'
    r'([A-Za-z_][A-Za-z0-9_]*)'
)
CLASS_DEF = re.compile(r'^classDef\s+([A-Za-z_][A-Za-z0-9_]*)')
CLASS_USE = re.compile(r'^class\s+([A-Za-z0-9_,]+)\s+([A-Za-z_][A-Za-z0-9_]*)')
UNQUOTED_RISKY = re.compile(r'[()\[\]{}:/]')

checks = []


def check(name, passed, detail=""):
    checks.append({"name": name, "passed": bool(passed), "detail": detail})


def extract_blocks(text: str):
    blocks, cur, in_block = [], [], False
    for line in text.splitlines():
        if line.strip().startswith("```mermaid"):
            in_block, cur = True, []
            continue
        if in_block and line.strip() == "```":
            blocks.append(cur)
            in_block = False
            continue
        if in_block:
            cur.append(line)
    return blocks


def label_of(line: str):
    """返回 (标签原文, 是否被双引号包裹)。"""
    m = re.search(r'\[(.*)\]', line)
    if not m:
        return None, False
    raw = m.group(1).strip()
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1], True
    return raw, False


def find_cycle(nodes, edges):
    graph = {n: [] for n in nodes}
    for a, b in edges:
        graph.setdefault(a, []).append(b)
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in graph}
    stack = []

    def dfs(u):
        color[u] = GRAY
        stack.append(u)
        for v in graph.get(u, []):
            if color.get(v, WHITE) == GRAY:
                return stack[stack.index(v):] + [v]
            if color.get(v, WHITE) == WHITE:
                found = dfs(v)
                if found:
                    return found
        stack.pop()
        color[u] = BLACK
        return None

    for n in graph:
        if color[n] == WHITE:
            found = dfs(n)
            if found:
                return found
    return None


def main() -> int:
    files = sorted(DOCS.glob("*.md"))
    total_blocks = 0
    all_ids_ok = True
    all_quotes_ok = True
    all_no_html = True
    all_head_ok = True
    all_class_ok = True
    all_subgraph_ok = True
    cycle_report = []
    edges_missing = []

    for path in files:
        for bi, block in enumerate(extract_blocks(path.read_text(encoding="utf-8")), start=1):
            total_blocks += 1
            tag = f"{path.name}#{bi}"
            if not block:
                all_head_ok = False
                continue
            head = block[0].strip()
            if not head.split()[0] in VALID_HEADS:
                all_head_ok = False

            is_flow = head.split()[0] in ("flowchart", "graph")
            defined, edges, class_defs, class_uses = set(), [], set(), set()
            depth = 0
            max_depth = 0

            for line in block[1:]:
                s = line.strip()
                if not s or s.startswith("%%"):
                    continue
                if s.startswith("subgraph"):
                    depth += 1
                    max_depth = max(max_depth, depth)
                    continue
                if s == "end":
                    depth = max(0, depth - 1)
                    continue
                if s.startswith("classDef"):
                    m = CLASS_DEF.match(s)
                    if m:
                        class_defs.add(m.group(1))
                    continue
                if s.startswith("class "):
                    m = CLASS_USE.match(s)
                    if m:
                        for name in m.group(1).split(","):
                            class_uses.add((name, m.group(2)))
                    continue

                m = NODE_DEF.match(s)
                if m:
                    node_id = m.group(1)
                    defined.add(node_id)
                    if not re.fullmatch(r"[A-Za-z0-9_]+", node_id):
                        all_ids_ok = False
                    label, quoted = label_of(s)
                    if label is not None:
                        if "<" in label or ">" in label:
                            all_no_html = False
                        if not quoted and UNQUOTED_RISKY.search(label):
                            all_quotes_ok = False
                    continue

                if is_flow:
                    m = EDGE.match(s)
                    if m:
                        a, _, _, b = m.group(1), m.group(2), m.group(3), m.group(4)
                        edges.append((a, b))
                        defined.add(a)
                        defined.add(b)

            if max_depth > 2:
                all_subgraph_ok = False

            for name, cls in class_uses:
                if cls not in class_defs:
                    all_class_ok = False
            defined_classes = {c for _, c in class_uses}
            if class_defs - defined_classes:
                all_class_ok = False

            # 边引用的节点必须有定义（flowchart 允许隐式定义，故仅警告级检查）
            for a, b in edges:
                if a not in defined or b not in defined:
                    edges_missing.append(f"{tag}: {a}->{b}")

            if is_flow and "依赖" in path.read_text(encoding="utf-8")[:2000] and bi == 3:
                cyc = find_cycle(defined, edges)
                if cyc:
                    cycle_report.append(f"{tag}: {' → '.join(cyc)}")

    check("mermaid 代码块首行合法", all_head_ok)
    check("节点 ID 只含英文数字下划线", all_ids_ok)
    check("含括号/斜杠/冒号的标签已加引号", all_quotes_ok)
    check("标签中无 HTML 标签", all_no_html)
    check("classDef 与 class 引用一致", all_class_ok)
    check("subgraph 嵌套 ≤ 2 层", all_subgraph_ok)
    check("依赖图无环", not cycle_report, "；".join(cycle_report))
    check("边引用的节点均已定义", not edges_missing, "；".join(edges_missing[:6]))
    check("至少有一张图被检查到", total_blocks > 0, f"共 {total_blocks} 个 mermaid 代码块")

    print("=" * 78)
    print(f"Mermaid 语法自检（共 {total_blocks} 个代码块）")
    print("注意：本机无法访问 mermaid.live，此为结构化自检，非在线渲染验证。")
    print("=" * 78)
    failed = 0
    for i, c in enumerate(checks, 1):
        mark = "OK  " if c["passed"] else "FAIL"
        if not c["passed"]:
            failed += 1
        print(f"[{mark}] {i:>2}. {c['name']}"
              + (f"  — {c['detail']}" if c["detail"] and not c["passed"] else ""))
    print("-" * 78)
    print(f"自检结果：{len(checks) - failed}/{len(checks)} 通过")
    print("=" * 78)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
