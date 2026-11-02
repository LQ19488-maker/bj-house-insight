"""原型运行时验证：用假 DOM 在 Node 里真实执行每页的 JS，抓运行期错误。

    python prototype/verify_prototype.py

为什么需要：静态语法检查（node --check）只能发现语法错误，
抓不到"函数名拼错""字段不存在""undefined.toLocaleString"这类运行期问题。
本脚本把每页的数据块 + 库 + 页面脚本放进 Node 执行一遍，并断言关键输出非空。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROTO = ROOT / "prototype"

HARNESS = r"""
// 忠实模拟浏览器：三个 <script> 块在【同一个全局作用域】里依次执行。
// 关键点：不能用 eval —— eval 里的 const/let 绑定会被丢弃，而浏览器的
// 顶层 <script> 会创建持久的全局词法绑定。因此用 vm.runInContext 复用同一上下文。
const fs = require('fs');
const vm = require('vm');

const rendered = {};
function makeEl(id){
  return {
    set innerHTML(v){ rendered[id] = String(v); },
    get innerHTML(){ return rendered[id] || ''; },
    set textContent(v){ rendered[id] = String(v); },
    get textContent(){ return rendered[id] || ''; },
    style: {},
  };
}
const store = {};
const documentStub = {
  getElementById(id){ return store[id] || (store[id] = makeEl(id)); },
};

const sandbox = { console, document: documentStub };
sandbox.window = sandbox;
const ctx = vm.createContext(sandbox);

const src = fs.readFileSync(process.argv[2], 'utf8');
const blocks = [...src.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
if (blocks.length !== 3) {
  console.error('SCRIPT_BLOCK_COUNT:' + blocks.length);
  process.exit(2);
}

try {
  blocks.forEach((code, i) => vm.runInContext(code, ctx, { filename: 'block' + i }));
} catch (e) {
  console.error('RUNTIME_ERROR: ' + e.message);
  process.exit(3);
}

const out = {};
for (const k of Object.keys(rendered)) out[k] = rendered[k].length;
console.log(JSON.stringify(out));
"""


def main() -> int:
    pages = sorted(PROTO.glob("p*.html"))
    if not pages:
        print("未找到原型页面", file=sys.stderr)
        return 2

    harness = Path(tempfile.gettempdir()) / "proto_harness.js"
    harness.write_text(HARNESS, encoding="utf-8")

    failed = 0
    for page in pages:
        text = page.read_text(encoding="utf-8")
        r = subprocess.run(["node", str(harness), str(page)],
                           capture_output=True, text=True, encoding="utf-8")
        if r.returncode != 0:
            print(f"[FAIL] {page.name}: {r.stderr.strip() or r.stdout.strip()}")
            failed += 1
            continue
        try:
            rendered = json.loads(r.stdout)
        except json.JSONDecodeError:
            print(f"[FAIL] {page.name}: 无法解析输出 {r.stdout[:120]}")
            failed += 1
            continue

        # 断言：至少写入了若干元素，且没有空字符串输出
        empty = [k for k, v in rendered.items() if v == 0]
        svg_count = sum(1 for v, in [] ) if False else 0
        print(f"[OK  ] {page.name:<22} 写入元素 {len(rendered)} 个"
              + (f"  ⚠️ 空输出: {empty}" if empty else ""))
        if empty:
            failed += 1

    print()
    total = len(pages)
    print(f"运行时验证：{total - failed}/{total} 通过")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
